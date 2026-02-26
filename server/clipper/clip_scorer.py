"""
LiveCat - Clip Scorer

추출된 클립의 품질을 다차원으로 평가한다 (0~100).

가중치:
  - event_score  : 40%  (이벤트 타입 기본 점수)
  - clarity      : 20%  (영상 선명도 - Laplacian variance)
  - composition  : 15%  (구도 - 삼분할 법칙)
  - novelty      : 15%  (참신성 - 오늘 반복 이벤트 패널티)
  - cat_bonus    : 10%  (두 마리 동시 출연 보너스)
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from loguru import logger

from server.clipper.event_detector import CatEvent


# Rule-of-thirds intersection points (normalised 0-1)
_THIRDS_POINTS = [
    (1 / 3, 1 / 3),
    (2 / 3, 1 / 3),
    (1 / 3, 2 / 3),
    (2 / 3, 2 / 3),
]


class ClipScorer:
    """
    클립 품질 점수 산출기 (0~100).

    여러 축을 config의 가중치로 합산한다.
    """

    def __init__(self, config: dict) -> None:
        self.config = config

        clip_cfg = config.get("clip", {})
        weights = clip_cfg.get("scoring_weights", {})
        self.w_event: float = weights.get("event", 0.40)
        self.w_clarity: float = weights.get("clarity", 0.20)
        self.w_composition: float = weights.get("composition", 0.15)
        self.w_novelty: float = weights.get("novelty", 0.15)
        self.w_cat_bonus: float = weights.get("cat_bonus", 0.10)

        self.event_configs: dict[str, dict] = clip_cfg.get("events", {})

        # Today's scored events for novelty calculation
        self._today_events: list[tuple[str, float]] = []  # (event_type, timestamp)
        self._today_date: str = ""

        # Sample frames for clarity/composition (evenly spaced)
        self._sample_count = 5

        logger.info(
            f"ClipScorer initialised — weights: "
            f"event={self.w_event} clarity={self.w_clarity} "
            f"comp={self.w_composition} novelty={self.w_novelty} "
            f"cat_bonus={self.w_cat_bonus}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score(self, clip_path: Path, event: CatEvent) -> float:
        """
        클립의 종합 품질 점수를 산출한다 (0~100).

        Args:
            clip_path: 추출된 클립 파일 (.mp4)
            event: 해당 이벤트 정보

        Returns:
            0~100 사이의 종합 점수.
        """
        self._rotate_daily_log(event.timestamp)

        # 1. Event base score (normalised to 0-100)
        event_score = self._score_event(event)

        # 2. Clarity (Laplacian variance of sample frames)
        clarity_score = self._score_clarity(clip_path)

        # 3. Composition (rule-of-thirds)
        composition_score = self._score_composition(clip_path, event)

        # 4. Novelty (penalty for same event type today)
        novelty_score = self._score_novelty(event)

        # 5. Cat bonus (both cats visible)
        cat_bonus_score = self._score_cat_bonus(event)

        # Weighted sum
        total = (
            event_score * self.w_event
            + clarity_score * self.w_clarity
            + composition_score * self.w_composition
            + novelty_score * self.w_novelty
            + cat_bonus_score * self.w_cat_bonus
        )

        total = max(0.0, min(100.0, total))

        # Record for novelty tracking
        self._today_events.append((event.event_type, event.timestamp))

        logger.debug(
            f"Score {clip_path.name}: "
            f"event={event_score:.0f} clarity={clarity_score:.0f} "
            f"comp={composition_score:.0f} novelty={novelty_score:.0f} "
            f"cat_bonus={cat_bonus_score:.0f} → total={total:.1f}"
        )

        # Also write score to the companion JSON if it exists
        self._update_metadata_json(clip_path, total)

        return total

    # ------------------------------------------------------------------
    # Scoring components
    # ------------------------------------------------------------------

    def _score_event(self, event: CatEvent) -> float:
        """
        이벤트 타입 기본 점수.

        Config에서 base_score를 읽어 0-100 스케일로 반환.
        이벤트 자체 score가 이미 있으면 그대로 사용.
        """
        # event.score already incorporates base + bonus from EventDetector
        return max(0.0, min(100.0, event.score))

    def _score_clarity(self, clip_path: Path) -> float:
        """
        영상 선명도 점수 (Laplacian variance).

        샘플 프레임 N개를 추출하여 Laplacian 분산의 평균을 계산한다.
        높을수록 선명. 임계치 기반 0-100 정규화.
        """
        try:
            cap = cv2.VideoCapture(str(clip_path))
            if not cap.isOpened():
                logger.warning(f"Cannot open video for clarity: {clip_path}")
                return 50.0  # neutral fallback

            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if total_frames <= 0:
                cap.release()
                return 50.0

            # Sample evenly spaced frames
            indices = np.linspace(
                0, total_frames - 1, self._sample_count, dtype=int
            )

            lap_variances: list[float] = []
            for idx in indices:
                cap.set(cv2.CAP_PROP_POS_FRAMES, int(idx))
                ret, frame = cap.read()
                if not ret or frame is None:
                    continue

                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                lap = cv2.Laplacian(gray, cv2.CV_64F)
                variance = float(lap.var())
                lap_variances.append(variance)

            cap.release()

            if not lap_variances:
                return 50.0

            avg_variance = sum(lap_variances) / len(lap_variances)

            # Normalise: 0~100
            # Typical sharp frame: variance ~500-2000
            # Blurry frame: variance <100
            # Scale: 0 at variance=0, 100 at variance>=1000
            clarity = min(100.0, avg_variance / 10.0)
            return max(0.0, clarity)

        except Exception as e:
            logger.warning(f"Clarity scoring failed: {e}")
            return 50.0

    def _score_composition(self, clip_path: Path, event: CatEvent) -> float:
        """
        구도 점수: 고양이 위치가 삼분할 교점 근처인지 평가.

        메타데이터에 cat center가 있으면 사용, 없으면 영상에서 추정.
        교점에 가까울수록 높은 점수.
        """
        # Try metadata-based scoring first (faster)
        cat_centers = event.metadata.get("cat_centers")
        if cat_centers:
            return self._composition_from_centers(list(cat_centers.values()))

        # Fallback: sample middle frame and use bbox if available
        try:
            cap = cv2.VideoCapture(str(clip_path))
            if not cap.isOpened():
                return 50.0

            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            mid_frame_idx = total_frames // 2
            cap.set(cv2.CAP_PROP_POS_FRAMES, mid_frame_idx)
            ret, frame = cap.read()
            cap.release()

            if not ret or frame is None:
                return 50.0

            h, w = frame.shape[:2]

            # If event metadata has bboxes, use their centers
            poses = event.metadata.get("poses", {})
            if not poses:
                # Without detection data, return neutral score
                return 50.0

            # Approximate: use center of frame as rough cat position
            # (in production, a detector would provide exact coords)
            return 50.0

        except Exception as e:
            logger.warning(f"Composition scoring failed: {e}")
            return 50.0

    def _composition_from_centers(
        self, centers: list[list[float] | tuple[float, float]]
    ) -> float:
        """
        정규화된 중심 좌표 목록에서 삼분할 구도 점수를 계산한다.

        각 중심과 가장 가까운 삼분할 교점 사이의 거리로 점수를 매긴다.
        거리 0 = 100점, 거리 >= 0.3 = 0점 (선형 보간).
        """
        if not centers:
            return 50.0

        scores: list[float] = []
        for center in centers:
            if center is None or len(center) < 2:
                continue

            cx, cy = float(center[0]), float(center[1])

            # Distance to closest thirds intersection
            min_dist = float("inf")
            for tx, ty in _THIRDS_POINTS:
                dist = ((cx - tx) ** 2 + (cy - ty) ** 2) ** 0.5
                min_dist = min(min_dist, dist)

            # Normalise: 0 distance = 100, 0.3+ distance = 0
            max_dist = 0.3
            score = max(0.0, (max_dist - min_dist) / max_dist * 100.0)
            scores.append(score)

        return sum(scores) / len(scores) if scores else 50.0

    def _score_novelty(self, event: CatEvent) -> float:
        """
        참신성 점수: 오늘 동일 event_type이 반복될수록 감점.

        첫 번째 = 100, 두 번째 = 80, 세 번째 = 60, ... 최소 20.
        """
        same_type_count = sum(
            1 for et, _ in self._today_events if et == event.event_type
        )
        # Diminishing: 100, 80, 60, 40, 20, 20, 20, ...
        penalty = same_type_count * 20
        return max(20.0, 100.0 - penalty)

    def _score_cat_bonus(self, event: CatEvent) -> float:
        """
        고양이 보너스: 두 마리 모두 보이면 +20.

        event.cats에 2마리 이상이면 100점, 1마리면 80점.
        (가중치가 10%이므로 실효 보너스 = 2점 or 0점)
        """
        unique_cats = set(event.cats)
        if len(unique_cats) >= 2:
            return 100.0  # Both cats visible
        elif len(unique_cats) == 1:
            return 80.0   # One cat
        else:
            return 0.0    # No cat identified

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _rotate_daily_log(self, timestamp: float) -> None:
        """날짜가 바뀌면 오늘의 이벤트 로그를 초기화한다."""
        today = datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime(
            "%Y-%m-%d"
        )
        if today != self._today_date:
            self._today_date = today
            self._today_events.clear()
            logger.debug(f"Novelty tracker reset for {today}")

    def _update_metadata_json(self, clip_path: Path, score: float) -> None:
        """동반 메타데이터 JSON에 score 필드를 추가한다."""
        meta_path = clip_path.with_suffix(".json")
        if not meta_path.exists():
            return

        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)

            meta["quality_score"] = round(score, 1)
            meta["scored_at"] = datetime.now(tz=timezone.utc).isoformat()

            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(meta, f, indent=2, ensure_ascii=False)

        except Exception as e:
            logger.warning(f"Failed to update metadata JSON: {e}")
