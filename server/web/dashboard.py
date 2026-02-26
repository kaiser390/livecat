"""
FastAPI 대시보드 모듈.

LiveCat 서버의 실시간 상태를 웹으로 모니터링할 수 있는
대시보드 애플리케이션을 제공한다. Uvicorn 위에서 비동기로 실행된다.
WebSocket을 통해 실시간 상태 업데이트를 푸시한다.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse
    from fastapi.staticfiles import StaticFiles
    import uvicorn
except ImportError:
    logger.warning(
        "fastapi / uvicorn not installed — Dashboard will be unavailable"
    )
    FastAPI = None

try:
    from jinja2 import Environment, FileSystemLoader
except ImportError:
    logger.warning("jinja2 not installed — Template rendering will be unavailable")
    Environment = None

if TYPE_CHECKING:
    pass  # LiveCatServer type hint (avoid circular import)


class DashboardApp:
    """FastAPI 기반 웹 대시보드.

    config['web'] 설정에 따라 동작한다.

    - GET /: 대시보드 HTML 페이지
    - WebSocket /ws: 실시간 상태 업데이트 (2초 간격)
    - API 라우트는 web/api.py에서 별도 정의
    """

    def __init__(self, config: dict, server) -> None:
        self._config = config
        self._server = server
        self._web_config = config.get("web", {})

        self._host: str = self._web_config.get("host", "0.0.0.0")
        self._port: int = self._web_config.get("port", 8080)
        self._title: str = self._web_config.get("title", "LiveCat Dashboard")

        # 템플릿 디렉토리
        self._template_dir = Path(__file__).resolve().parent / "templates"

        # WebSocket 연결 관리
        self._ws_clients: list[WebSocket] = []

        # FastAPI 앱 생성
        self._app: FastAPI | None = None
        if FastAPI is not None:
            self._app = self._create_app()

        logger.info(
            f"DashboardApp initialized — "
            f"host={self._host}, port={self._port}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """대시보드 서버를 비동기로 실행한다."""
        if self._app is None:
            logger.error("FastAPI not available — Dashboard cannot start")
            return

        config = uvicorn.Config(
            app=self._app,
            host=self._host,
            port=self._port,
            log_level="warning",
            access_log=False,
        )
        server = uvicorn.Server(config)

        logger.info(f"Dashboard running at http://{self._host}:{self._port}")

        # WebSocket 브로드캐스트 태스크와 Uvicorn을 동시 실행
        broadcast_task = asyncio.create_task(
            self._ws_broadcast_loop(), name="ws_broadcast"
        )

        try:
            await server.serve()
        finally:
            broadcast_task.cancel()
            try:
                await broadcast_task
            except asyncio.CancelledError:
                pass

    # ------------------------------------------------------------------
    # App Creation
    # ------------------------------------------------------------------

    def _create_app(self) -> FastAPI:
        """FastAPI 애플리케이션을 생성하고 라우트를 등록한다."""
        app = FastAPI(title=self._title, docs_url=None, redoc_url=None)

        # Jinja2 환경 설정
        jinja_env = None
        if Environment is not None and self._template_dir.exists():
            jinja_env = Environment(
                loader=FileSystemLoader(str(self._template_dir)),
                autoescape=True,
            )

        # --- 대시보드 메인 페이지 ---
        @app.get("/", response_class=HTMLResponse)
        async def dashboard_page():
            if jinja_env is None:
                return HTMLResponse(
                    content="<h1>Template engine not available</h1>",
                    status_code=500,
                )
            try:
                template = jinja_env.get_template("dashboard.html")
                status = self._get_status()
                html = template.render(
                    title=self._title,
                    status=status,
                    cameras=status.get("cameras", {}),
                    config=self._config,
                )
                return HTMLResponse(content=html)
            except Exception as e:
                logger.error(f"Dashboard render error: {e}")
                return HTMLResponse(
                    content=f"<h1>Render Error</h1><pre>{e}</pre>",
                    status_code=500,
                )

        # --- WebSocket 실시간 업데이트 ---
        @app.websocket("/ws")
        async def websocket_endpoint(ws: WebSocket):
            await ws.accept()
            self._ws_clients.append(ws)
            logger.debug(
                f"WebSocket client connected — "
                f"total={len(self._ws_clients)}"
            )
            try:
                # 연결 유지 (클라이언트 메시지 수신 대기)
                while True:
                    # 클라이언트로부터 ping 또는 명령을 수신
                    data = await ws.receive_text()
                    # 즉시 상태 응답 (수동 요청)
                    if data == "status":
                        status = self._get_status()
                        await ws.send_json(status)
            except WebSocketDisconnect:
                pass
            except Exception as e:
                logger.debug(f"WebSocket error: {e}")
            finally:
                if ws in self._ws_clients:
                    self._ws_clients.remove(ws)
                logger.debug(
                    f"WebSocket client disconnected — "
                    f"total={len(self._ws_clients)}"
                )

        # --- API 라우트 등록 ---
        try:
            from server.web.api import create_api_router

            api_router = create_api_router(self._config, self._server)
            app.include_router(api_router)
        except ImportError as e:
            logger.warning(f"API router not loaded: {e}")

        return app

    # ------------------------------------------------------------------
    # WebSocket Broadcast
    # ------------------------------------------------------------------

    async def _ws_broadcast_loop(self) -> None:
        """2초 간격으로 연결된 모든 WebSocket 클라이언트에 상태를 푸시한다."""
        while True:
            if self._ws_clients:
                status = self._get_status()
                disconnected = []

                for ws in self._ws_clients:
                    try:
                        await ws.send_json(status)
                    except Exception:
                        disconnected.append(ws)

                # 끊어진 클라이언트 제거
                for ws in disconnected:
                    if ws in self._ws_clients:
                        self._ws_clients.remove(ws)

            await asyncio.sleep(2.0)

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def _get_status(self) -> dict:
        """서버 상태를 JSON-serializable dict로 반환한다."""
        try:
            return self._server.get_status()
        except Exception as e:
            logger.debug(f"Failed to get server status: {e}")
            return {
                "running": False,
                "cameras": {},
                "active_camera": None,
                "blur_active": False,
                "clips_today": 0,
                "upload_queue": 0,
                "error": str(e),
            }
