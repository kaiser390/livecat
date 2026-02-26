"""OBS WebSocket 제어 — OBS Studio와 WebSocket 5.x를 통해 통신한다."""

from __future__ import annotations

import asyncio
from typing import Optional

from loguru import logger


class OBSController:
    """OBS WebSocket 5.x 클라이언트.

    obsws-python을 사용하여 OBS Studio를 제어한다.
    장면 전환, 소스 제어, 필터 활성화/비활성화를 담당하며,
    연결이 끊어지면 자동으로 재연결을 시도한다.
    """

    RECONNECT_INTERVAL_SEC = 5
    MAX_RECONNECT_ATTEMPTS = 0  # 0 = 무제한

    def __init__(self, config: dict):
        obs_config = config.get("obs", {})
        self._ws_url = obs_config.get("ws_url", "ws://localhost:4455")
        self._scenes = obs_config.get("scenes", {})

        # ws_url에서 host/port 파싱
        url_part = self._ws_url.replace("ws://", "").replace("wss://", "")
        parts = url_part.split(":")
        self._host = parts[0] if parts else "localhost"
        self._port = int(parts[1]) if len(parts) > 1 else 4455

        self._ws = None
        self._connected = False
        self._reconnect_task: Optional[asyncio.Task] = None
        self._should_reconnect = True

        logger.info(
            f"OBSController initialized — url={self._ws_url}, "
            f"scenes={self._scenes}"
        )

    @property
    def connected(self) -> bool:
        """OBS WebSocket 연결 상태."""
        return self._connected

    async def connect(self):
        """OBS WebSocket에 연결한다.

        연결 실패 시 백그라운드에서 자동 재연결을 시도한다.
        """
        self._should_reconnect = True
        await self._try_connect()

        if not self._connected:
            logger.warning("OBS initial connection failed, starting reconnect loop")
            self._start_reconnect_loop()

    async def disconnect(self):
        """OBS WebSocket 연결을 종료한다."""
        self._should_reconnect = False

        if self._reconnect_task and not self._reconnect_task.done():
            self._reconnect_task.cancel()
            try:
                await self._reconnect_task
            except asyncio.CancelledError:
                pass
            self._reconnect_task = None

        if self._ws is not None:
            try:
                self._ws.disconnect()
            except Exception as e:
                logger.debug(f"OBS disconnect cleanup: {e}")
            self._ws = None

        self._connected = False
        logger.info("OBS WebSocket disconnected")

    async def switch_scene(self, decision) -> bool:
        """SwitchDecision에 따라 OBS 장면을 전환한다.

        Args:
            decision: CameraSelector의 SwitchDecision
                - decision.scene_mode: "main", "pip", "sleeping", "offline"
                - decision.transition_type: "crossfade", "cut", "pip", "sleep_fade"
                - decision.transition_config: TransitionConfig (type, duration_ms)

        Returns:
            True면 전환 성공, False면 실패
        """
        if not self._connected:
            logger.warning("OBS not connected — cannot switch scene")
            return False

        scene_name = self._scenes.get(decision.scene_mode)
        if not scene_name:
            logger.error(f"Unknown scene mode: {decision.scene_mode}")
            return False

        try:
            # 전환 효과 설정
            if decision.transition_config:
                await self._set_transition(
                    decision.transition_config.type,
                    decision.transition_config.duration_ms,
                )

            # 장면 전환
            self._ws.set_current_program_scene(scene_name)

            logger.info(
                f"OBS scene switched: {scene_name} "
                f"(mode={decision.scene_mode}, "
                f"transition={decision.transition_type})"
            )
            return True

        except Exception as e:
            logger.error(f"OBS scene switch failed: {e}")
            self._handle_connection_error()
            return False

    async def set_source_visibility(
        self, scene_name: str, source_name: str, visible: bool
    ) -> bool:
        """특정 장면 내 소스의 가시성을 설정한다.

        Args:
            scene_name: OBS 장면 이름
            source_name: OBS 소스 이름
            visible: True면 보이기, False면 숨기기
        """
        if not self._connected:
            return False

        try:
            # 소스의 scene item ID를 가져옴
            item_id = self._ws.get_scene_item_id(scene_name, source_name).scene_item_id
            self._ws.set_scene_item_enabled(scene_name, item_id, visible)
            logger.debug(
                f"Source visibility: {scene_name}/{source_name} = {visible}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to set source visibility: {e}")
            return False

    async def set_filter_enabled(
        self, source_name: str, filter_name: str, enabled: bool
    ) -> bool:
        """소스에 적용된 필터의 활성화 상태를 설정한다.

        Args:
            source_name: 필터가 적용된 소스 이름
            filter_name: OBS 필터 이름
            enabled: True면 활성화, False면 비활성화
        """
        if not self._connected:
            return False

        try:
            self._ws.set_source_filter_enabled(source_name, filter_name, enabled)
            logger.debug(
                f"Filter: {source_name}/{filter_name} = {enabled}"
            )
            return True
        except Exception as e:
            logger.error(f"Failed to set filter state: {e}")
            return False

    async def get_current_scene(self) -> Optional[str]:
        """현재 활성화된 OBS 장면 이름을 반환한다."""
        if not self._connected:
            return None

        try:
            resp = self._ws.get_current_program_scene()
            return resp.scene_name
        except Exception as e:
            logger.error(f"Failed to get current scene: {e}")
            return None

    async def _set_transition(self, transition_type: str, duration_ms: int):
        """OBS 전환 효과를 설정한다."""
        try:
            # 전환 타입 매핑
            obs_transition_map = {
                "crossfade": "Fade",
                "cut": "Cut",
                "sleep_fade": "Fade",
                "pip": "Fade",
            }

            obs_transition = obs_transition_map.get(transition_type, "Fade")
            self._ws.set_current_scene_transition(obs_transition)

            if duration_ms > 0:
                self._ws.set_current_scene_transition_duration(duration_ms)

        except Exception as e:
            logger.debug(f"Failed to set transition (non-critical): {e}")

    async def _try_connect(self):
        """OBS WebSocket 연결을 시도한다."""
        try:
            import obsws_python as obsws

            self._ws = obsws.ReqClient(
                host=self._host,
                port=self._port,
            )
            self._connected = True
            logger.info(f"OBS WebSocket connected: {self._ws_url}")

        except ImportError:
            logger.error(
                "obsws-python not installed. "
                "Install with: pip install obsws-python"
            )
            self._connected = False

        except Exception as e:
            logger.warning(f"OBS connection failed: {e}")
            self._connected = False
            self._ws = None

    def _start_reconnect_loop(self):
        """백그라운드 재연결 루프를 시작한다."""
        if self._reconnect_task and not self._reconnect_task.done():
            return  # 이미 실행 중

        self._reconnect_task = asyncio.create_task(
            self._reconnect_loop(), name="obs_reconnect"
        )

    async def _reconnect_loop(self):
        """연결이 끊어진 경우 주기적으로 재연결을 시도한다."""
        attempts = 0

        while self._should_reconnect:
            if self._connected:
                await asyncio.sleep(self.RECONNECT_INTERVAL_SEC)
                continue

            attempts += 1
            if (
                self.MAX_RECONNECT_ATTEMPTS > 0
                and attempts > self.MAX_RECONNECT_ATTEMPTS
            ):
                logger.error(
                    f"OBS reconnect failed after {attempts - 1} attempts, giving up"
                )
                break

            logger.info(f"OBS reconnect attempt #{attempts}...")
            await self._try_connect()

            if self._connected:
                logger.info(f"OBS reconnected after {attempts} attempts")
                attempts = 0
            else:
                await asyncio.sleep(self.RECONNECT_INTERVAL_SEC)

    def _handle_connection_error(self):
        """연결 오류 발생 시 상태를 갱신하고 재연결을 트리거한다."""
        self._connected = False
        self._ws = None

        if self._should_reconnect:
            self._start_reconnect_loop()
