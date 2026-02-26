"""
REST API 모듈.

LiveCat 서버의 상태 조회 및 제어를 위한 REST API 엔드포인트를 제공한다.
FastAPI Router로 구성되어 DashboardApp에 포함된다.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

try:
    from fastapi import APIRouter, HTTPException
    from pydantic import BaseModel
except ImportError:
    APIRouter = None
    BaseModel = object
    HTTPException = Exception


# ------------------------------------------------------------------
# Request/Response Models
# ------------------------------------------------------------------

class CameraSwitchRequest(BaseModel):
    """카메라 수동 전환 요청."""
    camera_id: str


class ClipSaveRequest(BaseModel):
    """수동 클립 저장 요청."""
    camera_id: Optional[str] = None
    duration_sec: Optional[float] = 20.0


class UploadEnqueueRequest(BaseModel):
    """수동 업로드 큐 추가 요청."""
    clip_path: str
    platform: str = "shorts"
    title: str = ""
    description: str = ""
    hashtags: list[str] = []


class StatusResponse(BaseModel):
    """서버 상태 응답."""
    running: bool
    cameras: dict
    active_camera: Optional[str]
    blur_active: bool
    clips_today: int
    upload_queue: int


class MessageResponse(BaseModel):
    """단순 메시지 응답."""
    success: bool
    message: str


# ------------------------------------------------------------------
# Router Factory
# ------------------------------------------------------------------

def create_api_router(config: dict, server) -> APIRouter:
    """API 라우터를 생성한다.

    Args:
        config: 서버 설정.
        server: LiveCatServer 인스턴스.

    Returns:
        FastAPI APIRouter.
    """
    router = APIRouter(prefix="/api", tags=["api"])

    # ------------------------------------------------------------------
    # GET /api/status — 서버 상태
    # ------------------------------------------------------------------

    @router.get("/status")
    async def get_status() -> dict:
        """서버 전체 상태를 반환한다.

        Returns:
            cameras, active_camera, blur, clips, queue 등 상태 정보.
        """
        try:
            status = server.get_status()
            return status
        except Exception as e:
            logger.error(f"API /status error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ------------------------------------------------------------------
    # GET /api/clips — 오늘의 클립 목록
    # ------------------------------------------------------------------

    @router.get("/clips")
    async def get_clips() -> dict:
        """오늘의 클립 목록을 점수와 함께 반환한다.

        Returns:
            clips: [{path, event_type, score, timestamp, processed}, ...]
        """
        try:
            today = datetime.date.today().isoformat()
            clip_dir = Path(config.get("_root_dir", ".")) / "clips" / today

            clips = []
            if clip_dir.exists():
                # 메타데이터 JSON 파일 검색
                for meta_file in sorted(
                    clip_dir.glob("*_meta.json"), reverse=True
                ):
                    try:
                        import json

                        with open(meta_file, "r", encoding="utf-8") as f:
                            meta = json.load(f)

                        clip_name = meta_file.stem.replace("_meta", "")
                        clip_path = clip_dir / f"{clip_name}.mp4"

                        clips.append(
                            {
                                "name": clip_name,
                                "path": str(clip_path),
                                "event_type": meta.get("event_type", "unknown"),
                                "score": meta.get("score", 0.0),
                                "timestamp": meta.get("timestamp", ""),
                                "camera_id": meta.get("camera_id", ""),
                                "processed": meta.get("processed", False),
                                "exists": clip_path.exists(),
                            }
                        )
                    except Exception as e:
                        logger.debug(f"Failed to read clip meta {meta_file}: {e}")

            return {
                "date": today,
                "count": len(clips),
                "clips": clips,
            }

        except Exception as e:
            logger.error(f"API /clips error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ------------------------------------------------------------------
    # GET /api/uploads — 업로드 히스토리
    # ------------------------------------------------------------------

    @router.get("/uploads")
    async def get_uploads(date: Optional[str] = None) -> dict:
        """업로드 히스토리를 반환한다.

        Args:
            date: 특정 날짜 필터 (YYYY-MM-DD). 없으면 최근 50건.

        Returns:
            uploads: [{event_id, platform, success, url, timestamp}, ...]
        """
        try:
            history = server.upload_tracker.get_history(date=date)

            # 날짜 필터 없으면 최근 50건으로 제한
            if date is None:
                history = history[:50]

            stats = server.upload_tracker.get_daily_stats(date)

            return {
                "date": date or datetime.date.today().isoformat(),
                "stats": stats,
                "count": len(history),
                "uploads": history,
            }

        except Exception as e:
            logger.error(f"API /uploads error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ------------------------------------------------------------------
    # POST /api/camera/switch — 카메라 수동 전환
    # ------------------------------------------------------------------

    @router.post("/camera/switch")
    async def switch_camera(req: CameraSwitchRequest) -> dict:
        """활성 카메라를 수동으로 전환한다.

        Args:
            req.camera_id: 전환할 대상 카메라 ID.
        """
        try:
            # 유효한 카메라 ID인지 확인
            valid_ids = [
                cam["id"]
                for cam in config.get("camera", {}).get("cameras", [])
            ]
            if req.camera_id not in valid_ids:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid camera_id: {req.camera_id}. "
                    f"Valid IDs: {valid_ids}",
                )

            # 카메라 전환 실행
            server.camera_selector.force_switch(req.camera_id)

            logger.bind(event=True).info(
                f"Manual camera switch to {req.camera_id}"
            )

            return {
                "success": True,
                "message": f"Camera switched to {req.camera_id}",
                "active_camera": req.camera_id,
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"API /camera/switch error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ------------------------------------------------------------------
    # POST /api/clip/save — 수동 클립 저장
    # ------------------------------------------------------------------

    @router.post("/clip/save")
    async def save_clip(req: ClipSaveRequest) -> dict:
        """현재 버퍼에서 수동으로 클립을 저장한다.

        Args:
            req.camera_id: 클립을 저장할 카메라 ID (없으면 활성 카메라).
            req.duration_sec: 클립 길이 (초).
        """
        try:
            camera_id = req.camera_id or server.camera_selector.active_camera_id

            if not camera_id:
                raise HTTPException(
                    status_code=400, detail="No active camera available"
                )

            # 수동 이벤트 생성 및 클립 추출
            from dataclasses import dataclass

            @dataclass
            class ManualEvent:
                event_type: str = "manual"
                camera_id: str = ""
                duration_sec: float = 20.0
                score: float = 50.0

            event = ManualEvent(
                camera_id=camera_id,
                duration_sec=req.duration_sec or 20.0,
            )

            clip_path = await server.clip_extractor.extract(event)

            if clip_path:
                logger.bind(event=True).info(
                    f"Manual clip saved: {clip_path}"
                )
                return {
                    "success": True,
                    "message": f"Clip saved: {clip_path.name}",
                    "clip_path": str(clip_path),
                }
            else:
                return {
                    "success": False,
                    "message": "Failed to extract clip from buffer",
                }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"API /clip/save error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ------------------------------------------------------------------
    # POST /api/blur/toggle — 블러 토글
    # ------------------------------------------------------------------

    @router.post("/blur/toggle")
    async def toggle_blur() -> dict:
        """블러 기능을 켜거나 끈다."""
        try:
            current = server.blur_processor.is_active
            server.blur_processor.is_active = not current
            new_state = server.blur_processor.is_active

            logger.bind(event=True).info(
                f"Blur toggled: {current} -> {new_state}"
            )

            return {
                "success": True,
                "message": f"Blur {'enabled' if new_state else 'disabled'}",
                "blur_active": new_state,
            }

        except Exception as e:
            logger.error(f"API /blur/toggle error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    # ------------------------------------------------------------------
    # POST /api/upload/enqueue — 수동 업로드 큐 추가
    # ------------------------------------------------------------------

    @router.post("/upload/enqueue")
    async def enqueue_upload(req: UploadEnqueueRequest) -> dict:
        """클립을 업로드 큐에 수동으로 추가한다.

        Args:
            req.clip_path: 업로드할 동영상 파일 경로.
            req.platform: "shorts" 또는 "tiktok".
            req.title: 제목.
            req.description: 설명.
            req.hashtags: 해시태그 목록.
        """
        try:
            clip_path = Path(req.clip_path)
            if not clip_path.exists():
                raise HTTPException(
                    status_code=400,
                    detail=f"Clip file not found: {req.clip_path}",
                )

            if req.platform not in ("shorts", "tiktok"):
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid platform: {req.platform}. "
                    "Must be 'shorts' or 'tiktok'.",
                )

            item_id = await server.upload_scheduler.enqueue(
                video_path=clip_path,
                title=req.title,
                description=req.description,
                hashtags=req.hashtags,
                platform=req.platform,
                metadata={
                    "event_type": "manual",
                    "source": "api",
                },
            )

            logger.bind(event=True).info(
                f"Manual upload enqueued — id={item_id}, "
                f"platform={req.platform}"
            )

            return {
                "success": True,
                "message": f"Upload enqueued: {item_id}",
                "item_id": item_id,
                "queue_size": server.upload_scheduler.queue_size,
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"API /upload/enqueue error: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    return router
