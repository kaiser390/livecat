"""
LiveCat - Event Detector

메타데이터 스트림에서 하이라이트 이벤트를 실시간 감지한다.
감지 대상: climb, jump, run, interact, hunt_attempt
쿨다운 30초로 동일 이벤트 중복 방지.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from loguru import logger


@dataclass
class CatEvent:
    """감지된 고양이 이벤트."""

    event_type: str                     # climb | jump | run | interact | hunt_attempt
    camera_id: str                      # CAM-1 | CAM-2
    cats: list[str]                     # ["nana"], ["toto"], ["nana", "toto"]
    score: float                        # base score from config
    timestamp: float                    # time.time() of detection
    duration_sec: float = 0.0           # estimated event duration
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Cooldown record: (event_type, camera_id) -> last trigger timestamp
# ---------------------------------------------------------------------------
_CooldownKey = tuple[str, str]

# Defaults for detection thresholds (overridden by config when present)
_DEFAULT_CLIMB_POSE_ANGLES = {"front_leg_angle_min": 120}  # front legs raised
_DEFAULT_JUMP_AIRBORNE_FRAMES = 3
_DEFAULT_RUN_MIN_SPEED = 50          # px/frame equivalent
_DEFAULT_INTERACT_MAX_DISTANCE = 0.3  # normalised 0-1
_DEFAULT_HUNT_KEYWORDS = {"crouch", "stalk", "pounce", "wiggle"}

COOLDOWN_SEC = 30.0


class EventDetector:
    """
    이벤트 감지 엔진.

    MetadataReceiver가 제공하는 프레임별 메타데이터를 소비하며,
    규칙 기반으로 하이라이트 이벤트를 판별한다.
    """

    def __init__(self, config: dict, metadata_receiver: Any) -> None:
        self.config = config
        self.metadata_receiver = metadata_receiver

        clip_cfg = config.get("clip", {})
        self.event_configs: dict[str, dict] = clip_cfg.get("events", {})

        # Cooldown tracking: (event_type, camera_id) -> last trigger time
        self._cooldowns: dict[_CooldownKey, float] = {}

        # Recent events for external dedup queries (ring buffer, max 200)
        self._recent_events: list[CatEvent] = []
        self._recent_max = 200

        logger.info(
            "EventDetector initialised — "
            f"event types: {list(self.event_configs.keys())}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self) -> list[CatEvent]:
        """
        현재 메타데이터를 읽어 이벤트 목록을 반환한다.

        MetadataReceiver.get_latest() 가 camera_id 별 최신 메타데이터 dict를
        반환한다고 가정한다. 메타데이터 구조 (예시):
            {
                "camera_id": "CAM-1",
                "cats": [
                    {
                        "id": "nana",
                        "bbox": [x1, y1, x2, y2],  # normalised 0-1
                        "pose": "climb",             # 추정 포즈
                        "speed": 72.5,               # px/frame
                        "center": [cx, cy],          # normalised
                        "airborne_frames": 0,
                    },
                    ...
                ],
                "hunt_signals": ["crouch"],  # optional
                "timestamp": 1700000000.0,
            }
        """
        events: list[CatEvent] = []
        now = time.time()

        # Fetch latest metadata from all cameras
        all_meta = self._get_all_metadata()

        for meta in all_meta:
            camera_id: str = meta.get("camera_id", "unknown")
            cats_data: list[dict] = meta.get("cats", [])
            ts: float = meta.get("timestamp", now)

            if not cats_data:
                continue

            # --- Detect each event type ---
            detected = self._detect_climb(camera_id, cats_data, ts)
            if detected:
                events.append(detected)

            detected = self._detect_jump(camera_id, cats_data, ts)
            if detected:
                events.append(detected)

            detected = self._detect_run(camera_id, cats_data, ts)
            if detected:
                events.append(detected)

            detected = self._detect_interact(camera_id, cats_data, ts)
            if detected:
                events.append(detected)

            detected = self._detect_hunt_attempt(camera_id, cats_data, meta, ts)
            if detected:
                events.append(detected)

        # Apply cooldown filter
        filtered: list[CatEvent] = []
        for ev in events:
            key: _CooldownKey = (ev.event_type, ev.camera_id)
            last = self._cooldowns.get(key, 0.0)
            if now - last >= COOLDOWN_SEC:
                self._cooldowns[key] = now
                filtered.append(ev)
                self._store_recent(ev)
                logger.info(
                    f"Event detected: {ev.event_type} "
                    f"cam={ev.camera_id} cats={ev.cats} score={ev.score:.0f}"
                )
            else:
                remaining = COOLDOWN_SEC - (now - last)
                logger.debug(
                    f"Cooldown skip: {ev.event_type} cam={ev.camera_id} "
                    f"({remaining:.1f}s remaining)"
                )

        return filtered

    @property
    def recent_events(self) -> list[CatEvent]:
        """최근 감지 이벤트 목록 (최대 200개)."""
        return list(self._recent_events)

    # ------------------------------------------------------------------
    # Metadata access helper
    # ------------------------------------------------------------------

    def _get_all_metadata(self) -> list[dict]:
        """
        MetadataReceiver에서 모든 카메라의 최신 메타데이터를 가져온다.

        MetadataReceiver 인터페이스:
          - get_latest(camera_id) -> dict | None
          - get_all_latest() -> list[dict]    (preferred)
        둘 다 시도하여 호환성을 유지한다.
        """
        receiver = self.metadata_receiver

        # Prefer batch method
        if hasattr(receiver, "get_all_latest"):
            result = receiver.get_all_latest()
            if result:
                return result

        # Fallback: per-camera query
        cameras = self.config.get("camera", {}).get("cameras", [])
        results: list[dict] = []
        for cam in cameras:
            cam_id = cam.get("id", "")
            if hasattr(receiver, "get_latest"):
                meta = receiver.get_latest(cam_id)
                if meta:
                    results.append(meta)
        return results

    # ------------------------------------------------------------------
    # Detection rules
    # ------------------------------------------------------------------

    def _detect_climb(
        self, camera_id: str, cats_data: list[dict], ts: float
    ) -> CatEvent | None:
        """
        Climb detection: pose == "climb" 이면서 min_duration 이상 유지.

        Config:
            clip.events.climb.base_score: 80
            clip.events.climb.min_duration_sec: 2
        """
        cfg = self.event_configs.get("climb", {})
        base_score = cfg.get("base_score", 80)
        min_dur = cfg.get("min_duration_sec", 2)

        climbing_cats: list[str] = []
        for cat in cats_data:
            pose = cat.get("pose", "").lower()
            if pose in ("climb", "climbing"):
                climbing_cats.append(cat.get("id", "unknown"))

        if not climbing_cats:
            return None

        # Front-leg angle heuristic (if provided)
        for cat in cats_data:
            angle = cat.get("front_leg_angle")
            if angle is not None:
                if angle < _DEFAULT_CLIMB_POSE_ANGLES["front_leg_angle_min"]:
                    return None  # legs not high enough

        return CatEvent(
            event_type="climb",
            camera_id=camera_id,
            cats=climbing_cats,
            score=base_score,
            timestamp=ts,
            duration_sec=min_dur,
            metadata={
                "poses": {c.get("id"): c.get("pose") for c in cats_data},
            },
        )

    def _detect_jump(
        self, camera_id: str, cats_data: list[dict], ts: float
    ) -> CatEvent | None:
        """
        Jump detection: airborne_frames >= threshold.

        고양이가 공중에 떠 있는 프레임 수가 일정 이상이면 점프로 판정.
        """
        cfg = self.event_configs.get("jump", {})
        base_score = cfg.get("base_score", 70)
        min_airborne = cfg.get("min_airborne_frames", _DEFAULT_JUMP_AIRBORNE_FRAMES)

        jumping_cats: list[str] = []
        max_airborne = 0
        for cat in cats_data:
            airborne = cat.get("airborne_frames", 0)
            if airborne >= min_airborne:
                jumping_cats.append(cat.get("id", "unknown"))
                max_airborne = max(max_airborne, airborne)

            # Also check pose label
            pose = cat.get("pose", "").lower()
            if pose in ("jump", "jumping", "leap") and cat.get("id", "unknown") not in jumping_cats:
                jumping_cats.append(cat.get("id", "unknown"))
                max_airborne = max(max_airborne, min_airborne)

        if not jumping_cats:
            return None

        # Bonus for high jumps
        bonus = min(10, (max_airborne - min_airborne) * 2)

        return CatEvent(
            event_type="jump",
            camera_id=camera_id,
            cats=jumping_cats,
            score=base_score + bonus,
            timestamp=ts,
            duration_sec=max_airborne / 30.0,  # estimate from fps
            metadata={"airborne_frames": max_airborne},
        )

    def _detect_run(
        self, camera_id: str, cats_data: list[dict], ts: float
    ) -> CatEvent | None:
        """
        Run detection: speed >= min_speed for min_duration.

        Config:
            clip.events.run.base_score: 60
            clip.events.run.min_speed: 50
            clip.events.run.min_duration_sec: 1
        """
        cfg = self.event_configs.get("run", {})
        base_score = cfg.get("base_score", 60)
        min_speed = cfg.get("min_speed", _DEFAULT_RUN_MIN_SPEED)
        min_dur = cfg.get("min_duration_sec", 1)

        running_cats: list[str] = []
        max_speed: float = 0.0
        for cat in cats_data:
            speed = cat.get("speed", 0.0)
            if speed >= min_speed:
                running_cats.append(cat.get("id", "unknown"))
                max_speed = max(max_speed, speed)

        if not running_cats:
            return None

        # Speed bonus: up to +15 for very fast movement
        speed_bonus = min(15, (max_speed - min_speed) / min_speed * 10)

        return CatEvent(
            event_type="run",
            camera_id=camera_id,
            cats=running_cats,
            score=base_score + speed_bonus,
            timestamp=ts,
            duration_sec=min_dur,
            metadata={"max_speed": max_speed},
        )

    def _detect_interact(
        self, camera_id: str, cats_data: list[dict], ts: float
    ) -> CatEvent | None:
        """
        Interact detection: 두 마리 고양이 사이 거리가 min_distance 이하.

        두 마리가 동시에 보일 때만 발생. normalised center 좌표 기반.
        Config:
            clip.events.interact.base_score: 90
            clip.events.interact.min_distance: 0.3
        """
        cfg = self.event_configs.get("interact", {})
        base_score = cfg.get("base_score", 90)
        max_dist = cfg.get("min_distance", _DEFAULT_INTERACT_MAX_DISTANCE)

        if len(cats_data) < 2:
            return None

        # Calculate pairwise distances
        for i in range(len(cats_data)):
            for j in range(i + 1, len(cats_data)):
                c1 = cats_data[i].get("center")
                c2 = cats_data[j].get("center")
                if c1 is None or c2 is None:
                    continue

                dist = ((c1[0] - c2[0]) ** 2 + (c1[1] - c2[1]) ** 2) ** 0.5

                if dist <= max_dist:
                    cat_ids = [
                        cats_data[i].get("id", "unknown"),
                        cats_data[j].get("id", "unknown"),
                    ]
                    # Closer = higher bonus
                    proximity_bonus = max(0, (max_dist - dist) / max_dist * 15)

                    return CatEvent(
                        event_type="interact",
                        camera_id=camera_id,
                        cats=cat_ids,
                        score=base_score + proximity_bonus,
                        timestamp=ts,
                        duration_sec=3.0,
                        metadata={
                            "distance": round(dist, 4),
                            "cat_centers": {
                                cats_data[i].get("id"): c1,
                                cats_data[j].get("id"): c2,
                            },
                        },
                    )

        return None

    def _detect_hunt_attempt(
        self, camera_id: str, cats_data: list[dict], meta: dict, ts: float
    ) -> CatEvent | None:
        """
        Hunt attempt detection: 사냥 관련 신호 감지.

        hunt_signals 키워드 또는 pose가 사냥 관련이면 트리거.
        Config:
            clip.events.hunt_attempt.base_score: 85
        """
        cfg = self.event_configs.get("hunt_attempt", {})
        base_score = cfg.get("base_score", 85)

        # Check global hunt_signals from metadata
        hunt_signals: list[str] = meta.get("hunt_signals", [])
        signal_keywords = {s.lower() for s in hunt_signals}
        matched_keywords = signal_keywords & _DEFAULT_HUNT_KEYWORDS

        # Check per-cat pose
        hunting_cats: list[str] = []
        for cat in cats_data:
            pose = cat.get("pose", "").lower()
            if pose in _DEFAULT_HUNT_KEYWORDS or pose in ("hunt", "hunting"):
                hunting_cats.append(cat.get("id", "unknown"))

        if not matched_keywords and not hunting_cats:
            return None

        # If we have hunt signals but no specific hunting cat, attribute to all
        if not hunting_cats:
            hunting_cats = [c.get("id", "unknown") for c in cats_data]

        return CatEvent(
            event_type="hunt_attempt",
            camera_id=camera_id,
            cats=hunting_cats,
            score=base_score,
            timestamp=ts,
            duration_sec=5.0,
            metadata={
                "hunt_signals": list(matched_keywords),
                "cat_poses": {c.get("id"): c.get("pose") for c in cats_data},
            },
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _store_recent(self, event: CatEvent) -> None:
        """최근 이벤트 링 버퍼에 저장."""
        self._recent_events.append(event)
        if len(self._recent_events) > self._recent_max:
            self._recent_events = self._recent_events[-self._recent_max:]
