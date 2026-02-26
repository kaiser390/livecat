"""장면 분석 — 카메라별 활동 점수를 수집하고 EMA로 스무딩한다."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from loguru import logger


@dataclass
class CameraScore:
    """단일 카메라의 활동 점수 상태."""

    cam_id: str
    raw_score: float = 0.0
    smoothed_score: float = 0.0
    tracking_active: bool = False
    last_update: float = field(default_factory=time.time)


@dataclass
class SceneState:
    """전체 장면 상태 — 모든 카메라의 점수 및 추적 상태를 포함한다."""

    camera_scores: Dict[str, CameraScore] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def get_score(self, cam_id: str) -> float:
        """특정 카메라의 스무딩된 활동 점수를 반환한다."""
        if cam_id in self.camera_scores:
            return self.camera_scores[cam_id].smoothed_score
        return 0.0

    def get_top_camera(self) -> Optional[str]:
        """가장 높은 점수를 가진 카메라 ID를 반환한다."""
        if not self.camera_scores:
            return None
        return max(
            self.camera_scores,
            key=lambda cid: self.camera_scores[cid].smoothed_score,
        )

    def all_below(self, threshold: float) -> bool:
        """모든 카메라 점수가 threshold 미만인지 확인한다."""
        if not self.camera_scores:
            return True
        return all(
            cs.smoothed_score < threshold
            for cs in self.camera_scores.values()
        )

    def all_above(self, threshold: float) -> bool:
        """모든 카메라 점수가 threshold 이상인지 확인한다."""
        if not self.camera_scores:
            return False
        return all(
            cs.smoothed_score >= threshold
            for cs in self.camera_scores.values()
        )


class SceneAnalyzer:
    """카메라별 활동 점수를 집계하고 EMA로 스무딩한다.

    MetadataReceiver로부터 실시간 추적 데이터를 받아
    각 카메라의 활동 점수를 계산한다.

    - 활동 점수: 0 ~ 100 (0=비활동, 100=최대 활동)
    - EMA alpha=0.3 으로 급격한 점수 변동을 억제
    """

    EMA_ALPHA = 0.3

    def __init__(self, config: dict, metadata_receiver):
        self._config = config
        self._metadata_receiver = metadata_receiver

        cam_configs = config.get("camera", {}).get("cameras", [])
        self._camera_ids = [c["id"] for c in cam_configs]

        # 카메라별 점수 상태 초기화
        self._scores: Dict[str, CameraScore] = {
            cam_id: CameraScore(cam_id=cam_id)
            for cam_id in self._camera_ids
        }

        logger.info(
            f"SceneAnalyzer initialized — cameras={self._camera_ids}, "
            f"ema_alpha={self.EMA_ALPHA}"
        )

    def analyze(self) -> SceneState:
        """현재 장면 상태를 분석하여 SceneState를 반환한다.

        MetadataReceiver에서 최신 추적 데이터를 가져와
        활동 점수를 EMA로 갱신한다.
        """
        now = time.time()

        for cam_id in self._camera_ids:
            state = self._metadata_receiver.get_state(cam_id)
            raw = self._compute_raw_score(cam_id, state)
            self._update_ema(cam_id, raw, now)

        scene_state = SceneState(
            camera_scores={
                cam_id: CameraScore(
                    cam_id=cam_id,
                    raw_score=self._scores[cam_id].raw_score,
                    smoothed_score=self._scores[cam_id].smoothed_score,
                    tracking_active=self._scores[cam_id].tracking_active,
                    last_update=self._scores[cam_id].last_update,
                )
                for cam_id in self._camera_ids
            },
            timestamp=now,
        )

        return scene_state

    def get_score(self, cam_id: str) -> float:
        """특정 카메라의 현재 스무딩된 점수를 반환한다."""
        if cam_id in self._scores:
            return self._scores[cam_id].smoothed_score
        return 0.0

    def _compute_raw_score(self, cam_id: str, tracking_state) -> float:
        """추적 상태 데이터로부터 원시 활동 점수를 계산한다.

        tracking_state는 MetadataReceiver.get_state()가 반환하는 dict로
        다음 키를 기대한다:
            - tracking: bool (고양이 추적 중 여부)
            - activity: float (0~100, 움직임 활동량)
            - bbox_area: float (0~1, 화면 내 고양이 비율)
            - interaction: bool (다른 고양이와 상호작용 중)
        """
        if tracking_state is None:
            self._scores[cam_id].tracking_active = False
            return 0.0

        tracking = tracking_state.get("tracking", False)
        activity = tracking_state.get("activity", 0.0)
        bbox_area = tracking_state.get("bbox_area", 0.0)
        interaction = tracking_state.get("interaction", False)

        self._scores[cam_id].tracking_active = tracking

        if not tracking:
            return 0.0

        # 활동량(0~100) 기반 + 화면 비율 보너스 + 상호작용 보너스
        score = activity
        score += bbox_area * 20  # 화면에 크게 잡히면 보너스
        if interaction:
            score += 30  # 두 고양이 상호작용 시 큰 보너스

        return min(max(score, 0.0), 100.0)

    def _update_ema(self, cam_id: str, raw_score: float, now: float):
        """EMA 스무딩으로 점수를 갱신한다."""
        cs = self._scores[cam_id]
        cs.raw_score = raw_score
        cs.smoothed_score = (
            self.EMA_ALPHA * raw_score
            + (1 - self.EMA_ALPHA) * cs.smoothed_score
        )
        cs.last_update = now
