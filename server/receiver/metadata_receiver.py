"""
WebSocket 메타데이터 수신 모듈.

iPhone 앱(LiveCatCam)에서 10Hz로 전송하는 JSON 메타데이터를 수신하여
카메라별 최신 상태를 유지한다.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any

import websockets
import websockets.server
from loguru import logger


@dataclass
class CameraMetadata:
    """단일 카메라의 최신 메타데이터 스냅샷."""

    cam_id: str
    tracking_state: str = "unknown"  # tracking, lost, idle, searching
    activity_score: float = 0.0
    cat_positions: list[dict[str, float]] = field(default_factory=list)
    motor_position: dict[str, float] = field(default_factory=dict)
    timestamp: float = 0.0
    raw: dict[str, Any] = field(default_factory=dict)

    def age_sec(self) -> float:
        """마지막 업데이트 이후 경과 시간(초)."""
        if self.timestamp <= 0:
            return float("inf")
        return time.monotonic() - self.timestamp


class MetadataReceiver:
    """WebSocket 서버로 iPhone 메타데이터를 수신한다.

    - 포트 8081에서 WebSocket 서버를 실행
    - 각 iPhone 클라이언트는 접속 시 cam_id를 등록
    - 10Hz로 수신되는 JSON 메타데이터를 카메라별로 저장
    """

    _STALE_THRESHOLD_SEC: float = 3.0  # 이 시간 이상 수신 없으면 stale 처리

    def __init__(self, config: dict) -> None:
        self._config = config
        self._running = False

        server_cfg = config.get("server", {})
        # 메타데이터 전용 포트 (메인 서버 포트 + 1)
        self._host: str = server_cfg.get("host", "0.0.0.0")
        self._port: int = 8081

        # 카메라별 최신 메타데이터 저장소
        cam_cfg = config.get("camera", {})
        self._metadata: dict[str, CameraMetadata] = {}
        for cam in cam_cfg.get("cameras", []):
            cam_id = cam["id"]
            self._metadata[cam_id] = CameraMetadata(cam_id=cam_id)

        # 연결된 클라이언트 추적
        self._clients: dict[str, websockets.WebSocketServerProtocol] = {}
        self._server: websockets.server.WebSocketServer | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """WebSocket 서버를 시작하고 수신 대기한다."""
        self._running = True
        logger.info(f"MetadataReceiver starting on ws://{self._host}:{self._port}")

        self._server = await websockets.serve(
            self._handle_client,
            self._host,
            self._port,
            ping_interval=20,
            ping_timeout=10,
            max_size=65536,  # 메타데이터 JSON은 작으므로 64KB 제한
        )

        logger.info(f"MetadataReceiver listening on ws://{self._host}:{self._port}")

        try:
            # 서버가 닫힐 때까지 대기
            while self._running:
                await asyncio.sleep(1.0)
        except asyncio.CancelledError:
            pass
        finally:
            await self._shutdown_server()

    async def stop(self) -> None:
        """WebSocket 서버를 정상 종료한다."""
        logger.info("MetadataReceiver stopping...")
        self._running = False
        await self._shutdown_server()
        logger.info("MetadataReceiver stopped")

    def get_state(self, cam_id: str) -> str:
        """특정 카메라의 현재 추적 상태를 반환한다.

        Returns:
            tracking_state 문자열. 데이터가 stale이면 "stale"을 반환.
        """
        meta = self._metadata.get(cam_id)
        if meta is None:
            return "unknown"
        if meta.age_sec() > self._STALE_THRESHOLD_SEC:
            return "stale"
        return meta.tracking_state

    def get_latest(self, cam_id: str) -> dict:
        """특정 카메라의 최신 메타데이터를 dict로 반환한다.

        Returns:
            카메라 메타데이터 딕셔너리. 등록되지 않은 cam_id이면 빈 dict.
        """
        meta = self._metadata.get(cam_id)
        if meta is None:
            return {}
        return {
            "cam_id": meta.cam_id,
            "tracking_state": meta.tracking_state,
            "activity_score": meta.activity_score,
            "cat_positions": meta.cat_positions,
            "motor_position": meta.motor_position,
            "timestamp": meta.timestamp,
            "age_sec": round(meta.age_sec(), 2),
            "stale": meta.age_sec() > self._STALE_THRESHOLD_SEC,
        }

    # ------------------------------------------------------------------
    # WebSocket 핸들러
    # ------------------------------------------------------------------

    async def _handle_client(
        self, websocket: websockets.WebSocketServerProtocol
    ) -> None:
        """단일 WebSocket 클라이언트 연결을 처리한다.

        클라이언트는 첫 메시지에서 cam_id를 등록한 뒤 메타데이터를 스트리밍한다.
        첫 메시지 형식: {"type": "register", "cam_id": "CAM-1"}
        이후 메시지 형식: {"cam_id": "CAM-1", "tracking_state": "tracking", ...}
        """
        remote = websocket.remote_address
        registered_cam_id: str | None = None

        logger.info(f"MetadataReceiver: client connected from {remote}")

        try:
            async for raw_message in websocket:
                try:
                    data = json.loads(raw_message)
                except json.JSONDecodeError:
                    logger.warning(
                        f"MetadataReceiver: invalid JSON from {remote}"
                    )
                    continue

                # 등록 메시지 처리
                if data.get("type") == "register":
                    registered_cam_id = data.get("cam_id")
                    if registered_cam_id and registered_cam_id in self._metadata:
                        self._clients[registered_cam_id] = websocket
                        logger.info(
                            f"MetadataReceiver: {remote} registered as {registered_cam_id}"
                        )
                        # 등록 확인 응답
                        await websocket.send(
                            json.dumps({"type": "registered", "cam_id": registered_cam_id})
                        )
                    else:
                        logger.warning(
                            f"MetadataReceiver: unknown cam_id '{registered_cam_id}' from {remote}"
                        )
                        registered_cam_id = None
                    continue

                # cam_id 결정: 메시지 내 cam_id 또는 등록된 cam_id 사용
                cam_id = data.get("cam_id", registered_cam_id)
                if cam_id is None or cam_id not in self._metadata:
                    continue

                # 메타데이터 업데이트
                self._update_metadata(cam_id, data)

        except websockets.exceptions.ConnectionClosed:
            logger.info(
                f"MetadataReceiver: client {remote} (cam={registered_cam_id}) disconnected"
            )
        except Exception as e:
            logger.error(
                f"MetadataReceiver: error handling client {remote}: {e}"
            )
        finally:
            # 클라이언트 목록에서 제거
            if registered_cam_id and registered_cam_id in self._clients:
                if self._clients[registered_cam_id] is websocket:
                    del self._clients[registered_cam_id]

    # ------------------------------------------------------------------
    # 메타데이터 파싱 / 저장
    # ------------------------------------------------------------------

    def _update_metadata(self, cam_id: str, data: dict) -> None:
        """수신된 JSON 데이터를 카메라 메타데이터에 반영한다.

        Expected JSON fields:
            tracking_state: str  — "tracking" | "lost" | "idle" | "searching"
            activity_score: float — 0.0 ~ 100.0
            cat_positions: list[{x, y, w, h, confidence}]
            motor_position: {pan, tilt}
        """
        meta = self._metadata[cam_id]
        now = time.monotonic()

        if "tracking_state" in data:
            meta.tracking_state = str(data["tracking_state"])

        if "activity_score" in data:
            try:
                meta.activity_score = float(data["activity_score"])
            except (ValueError, TypeError):
                pass

        if "cat_positions" in data:
            positions = data["cat_positions"]
            if isinstance(positions, list):
                meta.cat_positions = positions

        if "motor_position" in data:
            motor = data["motor_position"]
            if isinstance(motor, dict):
                meta.motor_position = motor

        meta.timestamp = now
        meta.raw = data

    # ------------------------------------------------------------------
    # 서버 종료
    # ------------------------------------------------------------------

    async def _shutdown_server(self) -> None:
        """WebSocket 서버와 모든 클라이언트 연결을 닫는다."""
        if self._server is not None:
            # 모든 클라이언트에 종료 알림
            for cam_id, ws in list(self._clients.items()):
                try:
                    await ws.close(1001, "server shutting down")
                except Exception:
                    pass

            self._clients.clear()
            self._server.close()
            await self._server.wait_closed()
            self._server = None
            logger.debug("MetadataReceiver: WebSocket server closed")
