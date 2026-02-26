"""오버레이 관리 — 고양이 이름, 시계, 상태 정보 오버레이를 제어한다."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Dict, Optional

from loguru import logger


class OverlayManager:
    """OBS 텍스트 오버레이를 관리한다.

    3가지 오버레이를 관리한다:
        - CatNameOverlay: 현재 추적 중인 고양이 이름 (나나/토토)
        - ClockWidget: 현재 시각 (HH:MM 형식)
        - StatusInfo: 상태 정보 (추적 상태, 활동 점수 등)
    """

    # OBS 텍스트 소스 이름
    SOURCE_CAT_NAME = "CatNameOverlay"
    SOURCE_CLOCK = "ClockWidget"
    SOURCE_STATUS = "StatusInfo"

    CLOCK_UPDATE_INTERVAL_SEC = 30

    def __init__(self, config: dict):
        self._config = config

        # 고양이 프로필
        cats_config = config.get("cats", {})
        self._cat_names: Dict[str, str] = {}
        for cat_key, cat_info in cats_config.items():
            self._cat_names[cat_key] = cat_info.get("name_ko", cat_key)

        # 카메라 -> 고양이 매핑
        cam_configs = config.get("camera", {}).get("cameras", [])
        self._cam_to_cat: Dict[str, str] = {}
        for cam in cam_configs:
            role = cam.get("role", "")
            if "nana" in role:
                self._cam_to_cat[cam["id"]] = "nana"
            elif "toto" in role:
                self._cam_to_cat[cam["id"]] = "toto"

        self._obs_controller = None
        self._current_cat_name: Optional[str] = None
        self._clock_task: Optional[asyncio.Task] = None

        logger.info(
            f"OverlayManager initialized — cats={self._cat_names}, "
            f"cam_map={self._cam_to_cat}"
        )

    def set_obs_controller(self, obs_controller):
        """OBSController 인스턴스를 주입한다.

        OBSController 초기화 후 호출해야 한다.
        """
        self._obs_controller = obs_controller

    async def start_clock(self):
        """시계 위젯 자동 업데이트를 시작한다."""
        if self._clock_task and not self._clock_task.done():
            return

        self._clock_task = asyncio.create_task(
            self._clock_loop(), name="overlay_clock"
        )
        logger.info("Clock overlay auto-update started")

    async def stop_clock(self):
        """시계 위젯 자동 업데이트를 중지한다."""
        if self._clock_task and not self._clock_task.done():
            self._clock_task.cancel()
            try:
                await self._clock_task
            except asyncio.CancelledError:
                pass
            self._clock_task = None
            logger.info("Clock overlay auto-update stopped")

    async def update_cat_name(self, camera_id: str) -> bool:
        """현재 활성 카메라에 해당하는 고양이 이름 오버레이를 갱신한다.

        Args:
            camera_id: 현재 활성 카메라 ID

        Returns:
            True면 업데이트 성공
        """
        cat_key = self._cam_to_cat.get(camera_id)
        if cat_key is None:
            return False

        cat_name = self._cat_names.get(cat_key, cat_key)

        # 동일한 이름이면 스킵
        if cat_name == self._current_cat_name:
            return True

        self._current_cat_name = cat_name

        success = await self._update_text_source(
            self.SOURCE_CAT_NAME,
            cat_name,
        )

        if success:
            logger.debug(f"Cat name overlay updated: {cat_name}")

        return success

    async def update_clock(self) -> bool:
        """시계 오버레이를 현재 시각으로 갱신한다.

        Returns:
            True면 업데이트 성공
        """
        now = datetime.now()
        time_str = now.strftime("%H:%M")

        return await self._update_text_source(
            self.SOURCE_CLOCK,
            time_str,
        )

    async def update_status(
        self,
        tracking_state: str = "",
        activity_score: float = 0.0,
        scene_mode: str = "",
        blur_active: bool = False,
    ) -> bool:
        """상태 정보 오버레이를 갱신한다.

        Args:
            tracking_state: 추적 상태 문자열
            activity_score: 활동 점수 (0~100)
            scene_mode: 현재 장면 모드
            blur_active: 블러 적용 중 여부

        Returns:
            True면 업데이트 성공
        """
        parts = []
        if scene_mode:
            parts.append(f"Mode: {scene_mode}")
        if tracking_state:
            parts.append(f"Track: {tracking_state}")
        parts.append(f"Activity: {activity_score:.0f}")
        if blur_active:
            parts.append("BLUR ON")

        status_text = " | ".join(parts)

        return await self._update_text_source(
            self.SOURCE_STATUS,
            status_text,
        )

    async def show_special_event(self, event_text: str, duration_sec: float = 5.0):
        """특수 이벤트 텍스트를 잠시 표시한다.

        Args:
            event_text: 표시할 텍스트
            duration_sec: 표시 지속 시간 (초)
        """
        await self._update_text_source(self.SOURCE_STATUS, event_text)

        # duration 후 원래 상태로 복구
        await asyncio.sleep(duration_sec)
        await self._update_text_source(self.SOURCE_STATUS, "")

    async def _update_text_source(self, source_name: str, text: str) -> bool:
        """OBS 텍스트 소스의 내용을 갱신한다."""
        if self._obs_controller is None or not self._obs_controller.connected:
            return False

        try:
            self._obs_controller._ws.set_input_settings(
                source_name,
                {"text": text},
                overlay=True,
            )
            return True

        except Exception as e:
            logger.debug(f"Failed to update overlay '{source_name}': {e}")
            return False

    async def _clock_loop(self):
        """시계 위젯을 주기적으로 업데이트하는 루프."""
        while True:
            try:
                await self.update_clock()
                await asyncio.sleep(self.CLOCK_UPDATE_INTERVAL_SEC)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Clock update error: {e}")
                await asyncio.sleep(self.CLOCK_UPDATE_INTERVAL_SEC)
