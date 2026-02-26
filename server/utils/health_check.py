"""시스템 헬스 체크 — iPhone 연결, OBS 상태, 디스크 등."""

import asyncio
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from loguru import logger


@dataclass
class HealthStatus:
    timestamp: datetime = field(default_factory=datetime.now)
    cameras: dict = field(default_factory=dict)  # {cam_id: bool}
    obs_connected: bool = False
    disk_free_gb: float = 0.0
    buffer_ok: bool = False
    errors: list = field(default_factory=list)

    @property
    def healthy(self) -> bool:
        return (
            all(self.cameras.values())
            and self.obs_connected
            and self.disk_free_gb > 5.0
            and self.buffer_ok
            and not self.errors
        )


class HealthChecker:
    """주기적 헬스 체크 수행."""

    def __init__(self, config: dict, server=None):
        self.config = config
        self.server = server
        self.check_interval_sec = 30
        self.last_status: HealthStatus | None = None

    async def run(self):
        """주기적 헬스 체크 루프."""
        while True:
            self.last_status = await self.check()
            if not self.last_status.healthy:
                logger.warning(f"Health check UNHEALTHY: {self.last_status.errors}")
            await asyncio.sleep(self.check_interval_sec)

    async def check(self) -> HealthStatus:
        """전체 시스템 상태 체크."""
        status = HealthStatus()

        # 카메라 연결 상태
        if self.server:
            for cam in self.config.get("camera", {}).get("cameras", []):
                cam_id = cam["id"]
                connected = self.server.video_receiver.is_connected(cam_id)
                status.cameras[cam_id] = connected
                if not connected:
                    status.errors.append(f"Camera {cam_id} disconnected")

            # OBS 연결
            status.obs_connected = self.server.obs_controller.connected
            if not status.obs_connected:
                status.errors.append("OBS disconnected")

            # 롤링 버퍼
            status.buffer_ok = self.server.stream_buffer.is_healthy()
            if not status.buffer_ok:
                status.errors.append("Stream buffer unhealthy")

        # 디스크 공간
        root_dir = Path(__file__).resolve().parent.parent.parent
        usage = shutil.disk_usage(root_dir)
        status.disk_free_gb = usage.free / (1024**3)
        if status.disk_free_gb < 5.0:
            status.errors.append(f"Low disk: {status.disk_free_gb:.1f}GB free")

        return status
