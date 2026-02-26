"""
SRT 2채널 영상 수신 모듈.

ffmpeg 서브프로세스를 사용하여 SRT 리스너로 iPhone에서 전송하는
영상을 수신하고, raw 프레임을 StreamBuffer에 전달한다.
연결 끊김 시 자동 재시작 로직 포함.
"""

from __future__ import annotations

import asyncio
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np
from loguru import logger

if TYPE_CHECKING:
    from server.receiver.stream_buffer import StreamBuffer


@dataclass
class _CameraConnection:
    """개별 카메라 SRT 연결 상태 추적."""

    cam_id: str
    srt_port: int
    role: str
    connected: bool = False
    process: subprocess.Popen | None = None
    reconnect_attempts: int = 0


class VideoReceiver:
    """SRT 프로토콜 기반 2채널 영상 수신기.

    각 카메라에 대해 ffmpeg SRT 리스너를 실행하고,
    raw BGR 프레임을 읽어 stream_buffer에 push한다.
    """

    _RECONNECT_BASE_DELAY: float = 2.0
    _RECONNECT_MAX_DELAY: float = 30.0

    def __init__(self, config: dict, stream_buffer: StreamBuffer) -> None:
        self._config = config
        self._stream_buffer = stream_buffer
        self._running = False

        cam_cfg = config.get("camera", {})
        self._fps: int = cam_cfg.get("fps", 30)

        # 해상도 파싱
        res = cam_cfg.get("resolution", "720p")
        if res == "1080p":
            self._width, self._height = 1920, 1080
        elif res == "720p":
            self._width, self._height = 1280, 720
        else:
            self._width, self._height = 1280, 720

        self._frame_size = self._width * self._height * 3  # BGR24

        # 카메라별 연결 객체 생성
        self._cameras: dict[str, _CameraConnection] = {}
        for cam in cam_cfg.get("cameras", []):
            cam_id = cam["id"]
            self._cameras[cam_id] = _CameraConnection(
                cam_id=cam_id,
                srt_port=cam.get("srt_port", 9000),
                role=cam.get("role", "unknown"),
            )

        self._tasks: list[asyncio.Task] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """모든 카메라에 대한 수신 루프를 시작한다."""
        self._running = True
        logger.info(
            f"VideoReceiver starting — {len(self._cameras)} cameras, "
            f"{self._width}x{self._height}@{self._fps}fps via SRT"
        )

        self._tasks = [
            asyncio.create_task(
                self._camera_loop(conn),
                name=f"srt_recv_{conn.cam_id}",
            )
            for conn in self._cameras.values()
        ]

        try:
            await asyncio.gather(*self._tasks)
        except asyncio.CancelledError:
            logger.info("VideoReceiver tasks cancelled")
        finally:
            self._cleanup_all()

    async def stop(self) -> None:
        """모든 수신 태스크를 정상 종료한다."""
        logger.info("VideoReceiver stopping...")
        self._running = False
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._cleanup_all()
        logger.info("VideoReceiver stopped")

    def is_connected(self, cam_id: str) -> bool:
        """특정 카메라의 현재 연결 상태를 반환한다."""
        conn = self._cameras.get(cam_id)
        return conn.connected if conn else False

    # ------------------------------------------------------------------
    # 카메라별 수신 루프
    # ------------------------------------------------------------------

    async def _camera_loop(self, conn: _CameraConnection) -> None:
        """단일 카메라에 대한 SRT 수신 -> 재시작 루프."""
        logger.info(f"[{conn.cam_id}] SRT listener on port {conn.srt_port}")

        while self._running:
            try:
                await self._receive_srt(conn)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[{conn.cam_id}] Error: {e}")
            finally:
                self._kill_process(conn)

            if self._running:
                delay = self._reconnect_delay(conn)
                logger.info(f"[{conn.cam_id}] Restarting in {delay:.1f}s...")
                await asyncio.sleep(delay)

    async def _receive_srt(self, conn: _CameraConnection) -> None:
        """ffmpeg SRT 리스너로 프레임을 수신한다."""
        srt_url = f"srt://0.0.0.0:{conn.srt_port}?mode=listener&timeout=60000000"

        cmd = [
            "ffmpeg",
            "-hide_banner", "-loglevel", "warning",
            "-i", srt_url,
            "-f", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{self._width}x{self._height}",
            "-r", str(self._fps),
            "-"
        ]

        logger.info(f"[{conn.cam_id}] Starting ffmpeg: port={conn.srt_port}")

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        conn.process = proc
        conn.connected = False

        # stderr 모니터링 (별도 태스크)
        stderr_task = asyncio.create_task(
            self._monitor_stderr(conn, proc.stderr),
            name=f"stderr_{conn.cam_id}",
        )

        try:
            frame_count = 0
            while self._running:
                try:
                    data = await proc.stdout.readexactly(self._frame_size)
                except asyncio.IncompleteReadError:
                    logger.warning(f"[{conn.cam_id}] ffmpeg stdout closed")
                    break

                if len(data) == self._frame_size:
                    frame = np.frombuffer(data, dtype=np.uint8).reshape(
                        (self._height, self._width, 3)
                    )
                    await self._stream_buffer.push_frame(conn.cam_id, frame)

                    frame_count += 1
                    if not conn.connected:
                        conn.connected = True
                        conn.reconnect_attempts = 0
                        logger.info(
                            f"[{conn.cam_id}] Receiving video: "
                            f"{self._width}x{self._height}@{self._fps}fps"
                        )

                    if frame_count % (self._fps * 30) == 0:
                        logger.debug(
                            f"[{conn.cam_id}] {frame_count} frames received"
                        )

        finally:
            stderr_task.cancel()
            try:
                await stderr_task
            except asyncio.CancelledError:
                pass

    async def _monitor_stderr(self, conn, stderr) -> None:
        """ffmpeg stderr를 모니터링하여 연결 상태를 추적한다."""
        try:
            while True:
                line = await stderr.readline()
                if not line:
                    break
                text = line.decode("utf-8", errors="replace").strip()
                if text:
                    if "error" in text.lower() or "fail" in text.lower():
                        logger.warning(f"[{conn.cam_id}] ffmpeg: {text}")
                    else:
                        logger.debug(f"[{conn.cam_id}] ffmpeg: {text}")
        except asyncio.CancelledError:
            pass

    # ------------------------------------------------------------------
    # 프로세스 관리
    # ------------------------------------------------------------------

    def _kill_process(self, conn: _CameraConnection) -> None:
        """ffmpeg 프로세스를 안전하게 종료한다."""
        conn.connected = False
        if conn.process is not None:
            try:
                conn.process.kill()
            except Exception:
                pass
            conn.process = None

    def _cleanup_all(self) -> None:
        """모든 ffmpeg 프로세스를 종료한다."""
        for conn in self._cameras.values():
            self._kill_process(conn)
        logger.debug("All SRT receivers cleaned up")

    def _reconnect_delay(self, conn: _CameraConnection) -> float:
        """지수 백오프 기반 재시작 대기 시간을 계산한다."""
        conn.reconnect_attempts += 1
        delay = min(
            self._RECONNECT_BASE_DELAY * (2 ** (conn.reconnect_attempts - 1)),
            self._RECONNECT_MAX_DELAY,
        )
        return delay
