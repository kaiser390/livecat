"""2캠 AI 스위칭 — 장면 분석 결과를 기반으로 카메라 전환을 결정한다."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from loguru import logger

from server.director.scene_analyzer import SceneAnalyzer, SceneState
from server.director.rules_engine import RulesEngine
from server.director.transition_engine import TransitionEngine, TransitionConfig


@dataclass
class SwitchDecision:
    """카메라 전환 결정 결과."""

    active_camera_id: Optional[str]  # 현재(또는 전환 후) 활성 카메라
    should_switch: bool              # 전환 실행 여부
    transition_type: str             # "crossfade", "cut", "pip", "sleep_fade"
    scene_mode: str                  # "main", "pip", "sleeping", "offline"
    transition_config: Optional[TransitionConfig] = None


class CameraSelector:
    """2대의 카메라 중 최적의 카메라를 선택하고 전환을 결정한다.

    핵심 규칙:
        - 최소 유지 시간 8초 (min_hold_sec)
        - 후보 점수가 현재 점수의 1.5배를 초과하면 전환
        - 두 카메라 모두 활동적(>50)이면 PIP 모드
        - 두 카메라 모두 비활동(<10) 5분 이상이면 수면 모드
        - 전환 타입: crossfade(기본), cut(긴급), pip, sleep_fade
        - 장면 모드: main, pip, sleeping, offline
    """

    def __init__(self, config: dict, scene_analyzer: SceneAnalyzer):
        self._config = config
        self._scene_analyzer = scene_analyzer

        cam_configs = config.get("camera", {}).get("cameras", [])
        self._camera_ids = [c["id"] for c in cam_configs]

        self._rules = RulesEngine(config)
        self._transitions = TransitionEngine(config)

        # 현재 상태
        self._active_camera_id: Optional[str] = (
            self._camera_ids[0] if self._camera_ids else None
        )
        self._scene_mode: str = "main"
        self._switch_time: float = time.time()
        self._all_low_since: Optional[float] = None  # sleep 감지용

        switching = config.get("switching", {})
        self._pip_threshold = switching.get("pip_mode_both_active_threshold", 50)
        self._sleep_threshold = switching.get("sleep_mode_threshold", 10)
        self._sleep_delay = switching.get("sleep_mode_delay_sec", 300)

        logger.info(
            f"CameraSelector initialized — cameras={self._camera_ids}, "
            f"active={self._active_camera_id}, "
            f"pip_threshold={self._pip_threshold}, "
            f"sleep_threshold={self._sleep_threshold}"
        )

    @property
    def active_camera_id(self) -> Optional[str]:
        """현재 활성 카메라 ID."""
        return self._active_camera_id

    def decide(self, scene_state: SceneState) -> SwitchDecision:
        """장면 상태를 분석하여 카메라 전환 결정을 반환한다.

        Args:
            scene_state: SceneAnalyzer가 제공하는 현재 장면 상태

        Returns:
            SwitchDecision — 전환 여부, 대상, 전환 효과 정보
        """
        now = time.time()
        time_on_current = now - self._switch_time

        # 카메라 없으면 offline
        if not self._camera_ids:
            return self._make_decision(
                should_switch=self._scene_mode != "offline",
                scene_mode="offline",
                transition_type="cut",
            )

        # 1. 수면 모드 체크 — 모든 카메라 비활동 상태 지속
        sleep_decision = self._check_sleep_mode(scene_state, now)
        if sleep_decision is not None:
            return sleep_decision

        # 수면 모드 해제: 활동 감지 시
        if self._scene_mode == "sleeping":
            wake_decision = self._check_wake_up(scene_state)
            if wake_decision is not None:
                return wake_decision
            # 아직 깨어나지 않았으면 수면 유지
            return self._make_decision(
                should_switch=False,
                scene_mode="sleeping",
                transition_type="sleep_fade",
            )

        # 2. PIP 모드 체크 — 두 카메라 모두 활동적
        pip_decision = self._check_pip_mode(scene_state)
        if pip_decision is not None:
            return pip_decision

        # PIP에서 빠져나오는 경우
        if self._scene_mode == "pip":
            exit_pip = self._check_exit_pip(scene_state)
            if exit_pip is not None:
                return exit_pip
            # PIP 유지
            return self._make_decision(
                should_switch=False,
                scene_mode="pip",
                transition_type="crossfade",
            )

        # 3. 일반 전환 판단
        candidate_id = self._get_other_camera(self._active_camera_id)
        if candidate_id is None:
            return self._make_decision(
                should_switch=False,
                scene_mode="main",
                transition_type="crossfade",
            )

        should_switch = self._rules.should_switch(
            current_camera_id=self._active_camera_id,
            candidate_camera_id=candidate_id,
            scene_state=scene_state,
            time_on_current=time_on_current,
        )

        if should_switch:
            # 전환 실행
            prev_mode = self._scene_mode
            self._active_camera_id = candidate_id
            self._switch_time = now
            self._scene_mode = "main"

            tc = self._transitions.get_transition(prev_mode, "main")

            logger.info(
                f"Camera switch: {self._get_other_camera(candidate_id)} -> "
                f"{candidate_id}, transition={tc.type} ({tc.duration_ms}ms)"
            )

            return SwitchDecision(
                active_camera_id=candidate_id,
                should_switch=True,
                transition_type=tc.type,
                scene_mode="main",
                transition_config=tc,
            )

        return self._make_decision(
            should_switch=False,
            scene_mode=self._scene_mode,
            transition_type="crossfade",
        )

    def _check_sleep_mode(
        self, scene_state: SceneState, now: float
    ) -> Optional[SwitchDecision]:
        """모든 카메라가 비활동 상태로 sleep_delay초 이상 지속되면 수면 모드 진입."""
        if self._scene_mode == "sleeping":
            return None  # 이미 수면 중

        if scene_state.all_below(self._sleep_threshold):
            if self._all_low_since is None:
                self._all_low_since = now
            elif now - self._all_low_since >= self._sleep_delay:
                # 수면 모드 진입
                prev_mode = self._scene_mode
                self._scene_mode = "sleeping"
                tc = self._transitions.get_transition(prev_mode, "sleeping")

                logger.info(
                    f"Sleep mode entered — all cameras below "
                    f"{self._sleep_threshold} for {self._sleep_delay}s"
                )

                return SwitchDecision(
                    active_camera_id=self._active_camera_id,
                    should_switch=True,
                    transition_type=tc.type,
                    scene_mode="sleeping",
                    transition_config=tc,
                )
        else:
            self._all_low_since = None  # 리셋

        return None

    def _check_wake_up(
        self, scene_state: SceneState
    ) -> Optional[SwitchDecision]:
        """수면 모드에서 활동 감지 시 깨어난다."""
        top_cam = scene_state.get_top_camera()
        if top_cam is None:
            return None

        top_score = scene_state.get_score(top_cam)
        if top_score >= self._sleep_threshold:
            self._active_camera_id = top_cam
            self._switch_time = time.time()
            self._scene_mode = "main"
            self._all_low_since = None

            tc = self._transitions.get_transition("sleeping", "main")

            logger.info(
                f"Wake up! camera={top_cam} score={top_score:.1f} — "
                f"transition={tc.type}"
            )

            return SwitchDecision(
                active_camera_id=top_cam,
                should_switch=True,
                transition_type=tc.type,
                scene_mode="main",
                transition_config=tc,
            )

        return None

    def _check_pip_mode(
        self, scene_state: SceneState
    ) -> Optional[SwitchDecision]:
        """두 카메라 모두 활동적(>pip_threshold)이면 PIP 모드 진입."""
        if self._scene_mode == "pip":
            return None  # 이미 PIP

        if len(self._camera_ids) < 2:
            return None

        if scene_state.all_above(self._pip_threshold):
            prev_mode = self._scene_mode
            self._scene_mode = "pip"
            tc = self._transitions.get_transition(prev_mode, "pip")

            logger.info(
                f"PIP mode entered — both cameras above {self._pip_threshold}"
            )

            return SwitchDecision(
                active_camera_id=self._active_camera_id,
                should_switch=True,
                transition_type="pip",
                scene_mode="pip",
                transition_config=tc,
            )

        return None

    def _check_exit_pip(
        self, scene_state: SceneState
    ) -> Optional[SwitchDecision]:
        """PIP 모드에서 한 카메라만 활동적이면 메인 모드로 복귀."""
        if not scene_state.all_above(self._pip_threshold):
            top_cam = scene_state.get_top_camera()
            if top_cam:
                self._active_camera_id = top_cam
                self._switch_time = time.time()
                self._scene_mode = "main"

                tc = self._transitions.get_transition("pip", "main")

                logger.info(
                    f"PIP exit -> main, active={top_cam}, "
                    f"transition={tc.type}"
                )

                return SwitchDecision(
                    active_camera_id=top_cam,
                    should_switch=True,
                    transition_type=tc.type,
                    scene_mode="main",
                    transition_config=tc,
                )

        return None

    def _get_other_camera(self, cam_id: Optional[str]) -> Optional[str]:
        """현재 카메라가 아닌 다른 카메라 ID를 반환한다."""
        others = [c for c in self._camera_ids if c != cam_id]
        return others[0] if others else None

    def _make_decision(
        self,
        should_switch: bool,
        scene_mode: str,
        transition_type: str,
    ) -> SwitchDecision:
        """상태 변경 없는 SwitchDecision을 생성한다."""
        return SwitchDecision(
            active_camera_id=self._active_camera_id,
            should_switch=should_switch,
            transition_type=transition_type,
            scene_mode=scene_mode,
        )
