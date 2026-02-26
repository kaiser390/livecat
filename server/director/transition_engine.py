"""전환 효과 설정 — 장면 전환 시 적용할 트랜지션 타입과 지속 시간을 결정한다."""

from __future__ import annotations

from dataclasses import dataclass

from loguru import logger


@dataclass
class TransitionConfig:
    """전환 효과 설정값."""

    type: str          # "crossfade", "cut", "pip", "sleep_fade"
    duration_ms: int   # 전환 지속 시간 (밀리초)


class TransitionEngine:
    """장면 전환 효과를 결정한다.

    from_scene / to_scene 조합에 따라 적절한 트랜지션 타입과
    지속 시간을 반환한다.

    기본 규칙:
        - 일반 전환: crossfade 500ms
        - 긴급 전환 (추적 로스트): cut 0ms
        - sleep 진입/탈출: sleep_fade 30000ms
        - PIP 전환: crossfade 500ms
    """

    def __init__(self, config: dict):
        switching = config.get("switching", {})
        transition = switching.get("transition", {})

        self._crossfade_ms = transition.get("crossfade_duration_ms", 500)
        self._cut_ms = transition.get("cut_duration_ms", 0)
        self._sleep_fade_ms = 30000  # 30초 페이드
        self._pip_main_ratio = transition.get("pip_main_ratio", 0.7)
        self._pip_sub_ratio = transition.get("pip_sub_ratio", 0.3)

        logger.info(
            f"TransitionEngine initialized — crossfade={self._crossfade_ms}ms, "
            f"cut={self._cut_ms}ms, sleep_fade={self._sleep_fade_ms}ms"
        )

    def get_transition(self, from_scene: str, to_scene: str) -> TransitionConfig:
        """from_scene -> to_scene 전환에 적합한 TransitionConfig를 반환한다.

        Args:
            from_scene: 현재 장면 모드 ("main", "pip", "sleeping", "offline")
            to_scene: 전환할 장면 모드

        Returns:
            TransitionConfig with type and duration_ms
        """
        # sleep 관련 전환: 긴 페이드
        if to_scene == "sleeping" or from_scene == "sleeping":
            tc = TransitionConfig(type="sleep_fade", duration_ms=self._sleep_fade_ms)
            logger.debug(f"Transition: {from_scene} -> {to_scene} = {tc}")
            return tc

        # offline 전환: 즉시 컷
        if to_scene == "offline" or from_scene == "offline":
            tc = TransitionConfig(type="cut", duration_ms=self._cut_ms)
            logger.debug(f"Transition: {from_scene} -> {to_scene} = {tc}")
            return tc

        # PIP 관련 전환
        if to_scene == "pip" or from_scene == "pip":
            tc = TransitionConfig(type="crossfade", duration_ms=self._crossfade_ms)
            logger.debug(f"Transition: {from_scene} -> {to_scene} = {tc}")
            return tc

        # 기본: crossfade
        tc = TransitionConfig(type="crossfade", duration_ms=self._crossfade_ms)
        logger.debug(f"Transition: {from_scene} -> {to_scene} = {tc}")
        return tc

    def get_urgent_transition(self) -> TransitionConfig:
        """긴급 전환용 설정 (추적 로스트 등) — 즉시 컷."""
        return TransitionConfig(type="cut", duration_ms=self._cut_ms)

    @property
    def pip_main_ratio(self) -> float:
        """PIP 모드에서 메인 화면 비율."""
        return self._pip_main_ratio

    @property
    def pip_sub_ratio(self) -> float:
        """PIP 모드에서 서브 화면 비율."""
        return self._pip_sub_ratio
