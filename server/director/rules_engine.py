"""전환 규칙 엔진 — 카메라 전환 여부를 판단하는 규칙을 관리한다."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Optional

from loguru import logger

from server.director.scene_analyzer import SceneState


@dataclass
class SwitchContext:
    """전환 판단에 필요한 컨텍스트."""

    current_camera_id: str
    candidate_camera_id: str
    current_score: float
    candidate_score: float
    current_tracking_active: bool
    candidate_tracking_active: bool
    time_on_current: float  # 현재 카메라 유지 시간 (초)


class RulesEngine:
    """카메라 전환 규칙을 평가한다.

    규칙 우선순위 (높은 것부터):
        1. 특수 이벤트 오버라이드 (상호작용 감지 등)
        2. 추적 로스트 타임아웃 (현재 카메라가 고양이를 놓침)
        3. 최소 유지 시간 미충족 시 전환 금지
        4. 점수 기반 판단 (후보 > 현재 * threshold)
    """

    def __init__(self, config: dict):
        switching = config.get("switching", {})

        self._min_hold_sec = switching.get("min_hold_sec", 8)
        self._score_threshold_mult = switching.get("score_threshold_multiplier", 1.5)
        self._tracking_lost_timeout = switching.get("tracking_lost_timeout_sec", 3)
        self._sleep_threshold = switching.get("sleep_mode_threshold", 10)
        self._sleep_delay_sec = switching.get("sleep_mode_delay_sec", 300)
        self._pip_both_active = switching.get("pip_mode_both_active_threshold", 50)

        # 특수 이벤트 오버라이드 플래그
        self._special_event_active = False
        self._special_event_camera: Optional[str] = None
        self._special_event_expire: float = 0.0

        # 추적 로스트 타이머
        self._tracking_lost_since: dict[str, Optional[float]] = {}

        logger.info(
            f"RulesEngine initialized — min_hold={self._min_hold_sec}s, "
            f"threshold_mult={self._score_threshold_mult}, "
            f"tracking_lost_timeout={self._tracking_lost_timeout}s"
        )

    def should_switch(
        self,
        current_camera_id: str,
        candidate_camera_id: str,
        scene_state: SceneState,
        time_on_current: float,
    ) -> bool:
        """현재 카메라에서 후보 카메라로 전환해야 하는지 판단한다.

        Args:
            current_camera_id: 현재 활성 카메라 ID
            candidate_camera_id: 전환 후보 카메라 ID
            scene_state: 현재 장면 상태
            time_on_current: 현재 카메라 유지 시간 (초)

        Returns:
            True면 전환, False면 유지
        """
        now = time.time()
        current_cs = scene_state.camera_scores.get(current_camera_id)
        candidate_cs = scene_state.camera_scores.get(candidate_camera_id)

        if current_cs is None or candidate_cs is None:
            return False

        ctx = SwitchContext(
            current_camera_id=current_camera_id,
            candidate_camera_id=candidate_camera_id,
            current_score=current_cs.smoothed_score,
            candidate_score=candidate_cs.smoothed_score,
            current_tracking_active=current_cs.tracking_active,
            candidate_tracking_active=candidate_cs.tracking_active,
            time_on_current=time_on_current,
        )

        # 1. 특수 이벤트 오버라이드
        if self._check_special_event(ctx, now):
            logger.info(
                f"Switch: special event override -> {candidate_camera_id}"
            )
            return True

        # 2. 추적 로스트 타임아웃
        if self._check_tracking_lost(ctx, now):
            logger.info(
                f"Switch: tracking lost on {current_camera_id} "
                f"for >{self._tracking_lost_timeout}s -> {candidate_camera_id}"
            )
            return True

        # 3. 최소 유지 시간 체크
        if time_on_current < self._min_hold_sec:
            return False

        # 4. 점수 기반 전환 (후보가 현재의 threshold배 이상일 때)
        if self._check_score_threshold(ctx):
            logger.info(
                f"Switch: score threshold — {current_camera_id}="
                f"{ctx.current_score:.1f} vs {candidate_camera_id}="
                f"{ctx.candidate_score:.1f} (x{self._score_threshold_mult})"
            )
            return True

        return False

    def set_special_event(
        self, camera_id: str, duration_sec: float = 10.0
    ):
        """특수 이벤트 발생 시 특정 카메라로 강제 전환한다.

        상호작용, 사냥 등 중요한 이벤트 발생 시 호출된다.
        """
        self._special_event_active = True
        self._special_event_camera = camera_id
        self._special_event_expire = time.time() + duration_sec
        logger.info(
            f"Special event set — camera={camera_id}, duration={duration_sec}s"
        )

    def clear_special_event(self):
        """특수 이벤트 오버라이드를 해제한다."""
        self._special_event_active = False
        self._special_event_camera = None
        self._special_event_expire = 0.0

    @property
    def min_hold_sec(self) -> float:
        return self._min_hold_sec

    @property
    def score_threshold_multiplier(self) -> float:
        return self._score_threshold_mult

    @property
    def sleep_threshold(self) -> float:
        return self._sleep_threshold

    @property
    def sleep_delay_sec(self) -> float:
        return self._sleep_delay_sec

    @property
    def pip_both_active_threshold(self) -> float:
        return self._pip_both_active

    def _check_special_event(self, ctx: SwitchContext, now: float) -> bool:
        """특수 이벤트 오버라이드를 확인한다."""
        if not self._special_event_active:
            return False

        # 만료 확인
        if now > self._special_event_expire:
            self.clear_special_event()
            return False

        # 특수 이벤트 카메라가 후보와 일치하면 전환
        return self._special_event_camera == ctx.candidate_camera_id

    def _check_tracking_lost(self, ctx: SwitchContext, now: float) -> bool:
        """현재 카메라의 추적 로스트 타임아웃을 확인한다."""
        cam_id = ctx.current_camera_id

        if ctx.current_tracking_active:
            # 추적 중이면 로스트 타이머 리셋
            self._tracking_lost_since[cam_id] = None
            return False

        # 추적 로스트 시작 시간 기록
        if self._tracking_lost_since.get(cam_id) is None:
            self._tracking_lost_since[cam_id] = now
            return False

        lost_duration = now - self._tracking_lost_since[cam_id]
        if lost_duration >= self._tracking_lost_timeout:
            # 후보 카메라가 추적 중이어야 전환 의미 있음
            if ctx.candidate_tracking_active:
                self._tracking_lost_since[cam_id] = None
                return True

        return False

    def _check_score_threshold(self, ctx: SwitchContext) -> bool:
        """점수 기반 전환 조건을 확인한다.

        후보 점수가 현재 점수의 threshold배를 초과하면 전환.
        현재 점수가 0이면 후보가 양수이기만 하면 전환.
        """
        if ctx.current_score <= 0:
            return ctx.candidate_score > 0

        return ctx.candidate_score > ctx.current_score * self._score_threshold_mult
