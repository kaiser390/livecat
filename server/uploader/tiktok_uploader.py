"""
TikTok Content Posting API v2 업로드 모듈.

TikTok Content Posting API를 사용하여 동영상을 업로드한다.
OAuth 2.0 Authorization Code Flow 인증,
3단계 업로드 프로세스 (init → upload → status check),
청크 업로드, 재시도 로직을 포함한다.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import field
from pathlib import Path
from typing import Optional

import aiohttp
from loguru import logger

from server.uploader.youtube_uploader import UploadResult

# TikTok API 엔드포인트
_TIKTOK_API_BASE = "https://open.tiktokapis.com"
_INIT_URL = f"{_TIKTOK_API_BASE}/v2/post/publish/inbox/video/init/"
_STATUS_URL = f"{_TIKTOK_API_BASE}/v2/post/publish/status/fetch/"

# 재시도 설정
_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 5.0
_RETRY_MAX_DELAY = 60.0

# 업로드 청크 크기 (10MB)
_CHUNK_SIZE = 10 * 1024 * 1024

# 상태 확인 폴링 설정
_STATUS_POLL_INTERVAL = 5.0
_STATUS_POLL_MAX_ATTEMPTS = 60  # 최대 5분


class TikTokUploader:
    """TikTok Content Posting API v2 기반 동영상 업로더.

    config['upload']['tiktok'] 설정에 따라 동작한다.

    업로드 프로세스:
        1. POST /v2/post/publish/inbox/video/init/ → upload_url 획득
        2. PUT upload_url → 동영상 파일 청크 업로드
        3. POST /v2/post/publish/status/fetch/ → 상태 확인
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        self._tt_config = config.get("upload", {}).get("tiktok", {})

        self._privacy_level: str = self._tt_config.get(
            "privacy_level", "PUBLIC_TO_EVERYONE"
        )
        self._disable_duet: bool = self._tt_config.get("disable_duet", False)
        self._disable_comment: bool = self._tt_config.get("disable_comment", False)

        # OAuth 토큰 경로
        self._credentials_dir = (
            Path(config.get("_root_dir", ".")) / "config" / "credentials"
        )
        self._token_path = self._credentials_dir / "tiktok_token.json"

        # 캐시된 토큰
        self._access_token: Optional[str] = None
        self._token_expiry: float = 0.0

        logger.info(
            f"TikTokUploader initialized — "
            f"privacy={self._privacy_level}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def upload(
        self,
        video_path: Path | str,
        title: str = "",
        hashtags: Optional[list[str]] = None,
    ) -> UploadResult:
        """TikTok에 동영상을 업로드한다.

        Args:
            video_path: 업로드할 동영상 파일 경로.
            title: 동영상 제목/캡션.
            hashtags: 해시태그 목록 (# 포함).

        Returns:
            UploadResult: 업로드 결과.
        """
        video_path = Path(video_path)
        if not video_path.exists():
            return UploadResult(
                success=False,
                platform="tiktok",
                error_message=f"Video file not found: {video_path}",
            )

        # 해시태그를 제목에 추가
        caption = self._build_caption(title, hashtags or [])

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                result = await self._upload_flow(video_path, caption)
                if result.success:
                    logger.bind(event=True).info(
                        f"TikTok upload success — "
                        f"id={result.video_id}, title={title[:50]}"
                    )
                    return result

                # 재시도 불가능한 오류
                if "auth" in result.error_message.lower():
                    return result

            except Exception as e:
                logger.error(
                    f"TikTok upload attempt {attempt}/{_MAX_RETRIES} failed: {e}"
                )
                result = UploadResult(
                    success=False,
                    platform="tiktok",
                    error_message=str(e),
                )

            # 재시도 대기
            if attempt < _MAX_RETRIES:
                delay = min(
                    _RETRY_BASE_DELAY * (2 ** (attempt - 1)),
                    _RETRY_MAX_DELAY,
                )
                logger.info(f"TikTok upload retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)

        return result

    # ------------------------------------------------------------------
    # 3-Step Upload Flow
    # ------------------------------------------------------------------

    async def _upload_flow(self, video_path: Path, caption: str) -> UploadResult:
        """TikTok 3단계 업로드를 수행한다.

        Step 1: init — upload_url과 publish_id를 획득
        Step 2: upload — 동영상 파일을 upload_url로 전송
        Step 3: status — 업로드 처리 상태를 확인
        """
        access_token = await self._get_access_token()
        if not access_token:
            return UploadResult(
                success=False,
                platform="tiktok",
                error_message="TikTok authentication failed — no access token",
            )

        file_size = video_path.stat().st_size

        async with aiohttp.ClientSession() as session:
            # Step 1: 업로드 초기화
            init_result = await self._init_upload(
                session, access_token, file_size, caption
            )
            if init_result is None:
                return UploadResult(
                    success=False,
                    platform="tiktok",
                    error_message="TikTok upload init failed",
                )

            upload_url = init_result["upload_url"]
            publish_id = init_result["publish_id"]
            logger.info(
                f"TikTok upload initialized — publish_id={publish_id}"
            )

            # Step 2: 동영상 파일 업로드 (chunked)
            upload_ok = await self._upload_video(
                session, upload_url, video_path, file_size
            )
            if not upload_ok:
                return UploadResult(
                    success=False,
                    platform="tiktok",
                    error_message="TikTok video file upload failed",
                )

            # Step 3: 상태 확인 (폴링)
            status_result = await self._poll_status(
                session, access_token, publish_id
            )

            return status_result

    async def _init_upload(
        self,
        session: aiohttp.ClientSession,
        access_token: str,
        file_size: int,
        caption: str,
    ) -> Optional[dict]:
        """Step 1: 업로드 초기화 — upload_url과 publish_id를 획득한다."""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

        payload = {
            "post_info": {
                "title": caption[:150],  # TikTok 캡션 제한
                "privacy_level": self._privacy_level,
                "disable_duet": self._disable_duet,
                "disable_comment": self._disable_comment,
            },
            "source_info": {
                "source": "FILE_UPLOAD",
                "video_size": file_size,
                "chunk_size": _CHUNK_SIZE,
                "total_chunk_count": max(1, -(-file_size // _CHUNK_SIZE)),
            },
        }

        try:
            async with session.post(
                _INIT_URL,
                headers=headers,
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json()

                if resp.status != 200:
                    error_msg = data.get("error", {}).get("message", resp.reason)
                    logger.error(
                        f"TikTok init failed — "
                        f"status={resp.status}, error={error_msg}"
                    )
                    return None

                error_info = data.get("error", {})
                if error_info.get("code", "ok") != "ok":
                    logger.error(f"TikTok init error: {error_info}")
                    return None

                publish_data = data.get("data", {})
                return {
                    "upload_url": publish_data["upload_url"],
                    "publish_id": publish_data["publish_id"],
                }

        except aiohttp.ClientError as e:
            logger.error(f"TikTok init request failed: {e}")
            return None

    async def _upload_video(
        self,
        session: aiohttp.ClientSession,
        upload_url: str,
        video_path: Path,
        file_size: int,
    ) -> bool:
        """Step 2: 동영상 파일을 upload_url에 청크 단위로 전송한다."""
        total_chunks = max(1, -(-file_size // _CHUNK_SIZE))
        uploaded = 0

        logger.info(
            f"TikTok uploading {video_path.name} "
            f"({file_size / 1024 / 1024:.1f}MB, {total_chunks} chunks)"
        )

        try:
            with open(video_path, "rb") as f:
                for chunk_idx in range(total_chunks):
                    chunk_data = f.read(_CHUNK_SIZE)
                    if not chunk_data:
                        break

                    chunk_start = chunk_idx * _CHUNK_SIZE
                    chunk_end = chunk_start + len(chunk_data) - 1

                    headers = {
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(chunk_data)),
                        "Content-Range": f"bytes {chunk_start}-{chunk_end}/{file_size}",
                    }

                    async with session.put(
                        upload_url,
                        headers=headers,
                        data=chunk_data,
                        timeout=aiohttp.ClientTimeout(total=300),
                    ) as resp:
                        if resp.status not in (200, 201, 206):
                            body = await resp.text()
                            logger.error(
                                f"TikTok chunk {chunk_idx + 1}/{total_chunks} "
                                f"failed — status={resp.status}, body={body[:200]}"
                            )
                            return False

                    uploaded += len(chunk_data)
                    progress = int(uploaded / file_size * 100)
                    logger.debug(
                        f"TikTok upload progress: {progress}% "
                        f"(chunk {chunk_idx + 1}/{total_chunks})"
                    )

            logger.info("TikTok video file upload complete")
            return True

        except (aiohttp.ClientError, IOError) as e:
            logger.error(f"TikTok video upload error: {e}")
            return False

    async def _poll_status(
        self,
        session: aiohttp.ClientSession,
        access_token: str,
        publish_id: str,
    ) -> UploadResult:
        """Step 3: 업로드 처리 상태를 폴링하여 확인한다."""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json; charset=UTF-8",
        }

        payload = {"publish_id": publish_id}

        for attempt in range(1, _STATUS_POLL_MAX_ATTEMPTS + 1):
            try:
                async with session.post(
                    _STATUS_URL,
                    headers=headers,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    data = await resp.json()

                    if resp.status != 200:
                        logger.warning(
                            f"TikTok status check {attempt} — "
                            f"HTTP {resp.status}"
                        )
                        await asyncio.sleep(_STATUS_POLL_INTERVAL)
                        continue

                    status_data = data.get("data", {})
                    status = status_data.get("status", "PROCESSING_UPLOAD")

                    if status == "PUBLISH_COMPLETE":
                        video_id = status_data.get("publicaly_available_post_id", [""])[0]
                        return UploadResult(
                            success=True,
                            platform="tiktok",
                            video_id=video_id,
                            url=f"https://www.tiktok.com/@me/video/{video_id}" if video_id else "",
                            status="published",
                        )

                    if status in ("FAILED", "PUBLISH_FAILED"):
                        fail_reason = status_data.get("fail_reason", "Unknown error")
                        return UploadResult(
                            success=False,
                            platform="tiktok",
                            error_message=f"TikTok publish failed: {fail_reason}",
                            status="failed",
                        )

                    # PROCESSING_UPLOAD, PROCESSING_DOWNLOAD, SENDING_TO_USER_INBOX
                    logger.debug(
                        f"TikTok status: {status} "
                        f"(poll {attempt}/{_STATUS_POLL_MAX_ATTEMPTS})"
                    )

            except aiohttp.ClientError as e:
                logger.warning(f"TikTok status poll error: {e}")

            await asyncio.sleep(_STATUS_POLL_INTERVAL)

        return UploadResult(
            success=False,
            platform="tiktok",
            error_message="TikTok status check timed out after polling",
            status="timeout",
        )

    # ------------------------------------------------------------------
    # OAuth 2.0 Token Management
    # ------------------------------------------------------------------

    async def _get_access_token(self) -> Optional[str]:
        """유효한 TikTok access token을 반환한다.

        캐시된 토큰이 유효하면 재사용, 만료 시 갱신한다.
        """
        now = time.time()

        # 캐시된 토큰이 유효한 경우
        if self._access_token and now < self._token_expiry - 60:
            return self._access_token

        # 토큰 파일에서 로드/갱신
        token_data = self._load_token_file()
        if token_data is None:
            logger.error(
                f"TikTok token file not found: {self._token_path}. "
                "Run the OAuth authorization flow first."
            )
            return None

        # 토큰 만료 체크
        expires_at = token_data.get("expires_at", 0)
        if now < expires_at - 60:
            self._access_token = token_data["access_token"]
            self._token_expiry = expires_at
            return self._access_token

        # refresh_token으로 갱신
        refresh_token = token_data.get("refresh_token")
        if not refresh_token:
            logger.error("TikTok refresh token not available — re-authorize required")
            return None

        new_token = await self._refresh_token(
            client_key=token_data.get("client_key", ""),
            client_secret=token_data.get("client_secret", ""),
            refresh_token=refresh_token,
        )

        if new_token:
            self._access_token = new_token["access_token"]
            self._token_expiry = new_token["expires_at"]
            self._save_token_file(new_token)
            logger.info("TikTok access token refreshed")
            return self._access_token

        logger.error("TikTok token refresh failed")
        return None

    async def _refresh_token(
        self,
        client_key: str,
        client_secret: str,
        refresh_token: str,
    ) -> Optional[dict]:
        """refresh_token으로 새 access_token을 획득한다."""
        url = f"{_TIKTOK_API_BASE}/v2/oauth/token/"
        payload = {
            "client_key": client_key,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data=payload,
                    timeout=aiohttp.ClientTimeout(total=30),
                ) as resp:
                    data = await resp.json()

                    if resp.status != 200 or "access_token" not in data:
                        logger.error(f"TikTok token refresh error: {data}")
                        return None

                    return {
                        "access_token": data["access_token"],
                        "refresh_token": data.get("refresh_token", refresh_token),
                        "expires_at": time.time() + data.get("expires_in", 86400),
                        "client_key": client_key,
                        "client_secret": client_secret,
                    }

        except aiohttp.ClientError as e:
            logger.error(f"TikTok token refresh request failed: {e}")
            return None

    def _load_token_file(self) -> Optional[dict]:
        """TikTok 토큰 파일을 로드한다."""
        if not self._token_path.exists():
            return None
        try:
            with open(self._token_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load TikTok token file: {e}")
            return None

    def _save_token_file(self, token_data: dict) -> None:
        """TikTok 토큰 데이터를 파일에 저장한다."""
        self._credentials_dir.mkdir(parents=True, exist_ok=True)
        with open(self._token_path, "w", encoding="utf-8") as f:
            json.dump(token_data, f, indent=2, ensure_ascii=False)
        logger.debug(f"TikTok token saved to {self._token_path}")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_caption(title: str, hashtags: list[str]) -> str:
        """제목과 해시태그를 합쳐 TikTok 캡션을 구성한다.

        TikTok 캡션은 최대 ~2200자이며, 해시태그를 끝에 추가한다.
        """
        tags_str = " ".join(hashtags) if hashtags else ""
        if tags_str:
            caption = f"{title} {tags_str}"
        else:
            caption = title

        # TikTok 캡션 길이 제한
        return caption[:2200]
