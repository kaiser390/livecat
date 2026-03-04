"""
YouTube Shorts 업로드 모듈.

Google API Python Client를 사용하여 YouTube Data API v3으로
Shorts 동영상을 업로드한다. OAuth 2.0 인증, 리줌어블 업로드,
썸네일 설정, 쿼타 추적 기능을 포함한다.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger

try:
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from google.auth.transport.requests import Request
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaFileUpload
    from googleapiclient.errors import HttpError
except ImportError:
    logger.warning(
        "google-api-python-client / google-auth not installed — "
        "YouTube upload will be unavailable"
    )
    Credentials = None


# YouTube Data API v3 scopes
_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

# Retry 대상 HTTP 상태 코드 (일시적 오류)
_RETRIABLE_STATUS_CODES = [500, 502, 503, 504]
_RETRIABLE_EXCEPTIONS = (ConnectionError, TimeoutError, OSError)

# 기본 재시도 설정
_MAX_RETRIES = 5
_RETRY_BASE_DELAY = 2.0
_RETRY_MAX_DELAY = 60.0


@dataclass
class UploadResult:
    """업로드 결과를 담는 데이터 클래스 (모든 플랫폼 공용)."""

    success: bool
    platform: str
    video_id: str = ""
    url: str = ""
    status: str = ""
    error_message: str = ""
    uploaded_at: float = field(default_factory=time.time)


class YouTubeUploader:
    """YouTube Shorts 업로드 클래스.

    config['upload']['youtube'] 설정에 따라 동작한다.
    OAuth 2.0 인증, 리줌어블 업로드, 썸네일 설정, 쿼타 추적을 수행한다.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        self._yt_config = config.get("upload", {}).get("youtube", {})

        self._category_id: str = str(self._yt_config.get("category_id", 15))
        self._privacy_status: str = self._yt_config.get("privacy_status", "public")
        self._made_for_kids: bool = self._yt_config.get("made_for_kids", False)
        self._default_language: str = self._yt_config.get("default_language", "ko")
        self._daily_quota: int = self._yt_config.get("daily_quota", 10000)
        self._upload_cost: int = self._yt_config.get("upload_cost", 1600)
        self._thumbnail_cost: int = self._yt_config.get("thumbnail_cost", 50)

        # 자격증명 파일 경로
        self._credentials_dir = Path(config.get("_root_dir", ".")) / "config" / "credentials"
        self._oauth_path = self._credentials_dir / "youtube_oauth.json"
        self._token_path = self._credentials_dir / "youtube_token.json"

        # 쿼타 추적 (일별)
        self._quota_used: int = 0
        self._quota_date: str = ""

        # YouTube API 서비스 (lazy init)
        self._service = None

        logger.info(
            f"YouTubeUploader initialized — "
            f"category={self._category_id}, "
            f"privacy={self._privacy_status}, "
            f"daily_quota={self._daily_quota}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def upload(
        self,
        video_path: Path | str,
        thumbnail_path: Optional[Path | str] = None,
        title: str = "",
        description: str = "",
        tags: Optional[list[str]] = None,
        category_id: int = 15,
        is_short: bool = True,
    ) -> UploadResult:
        """YouTube 동영상을 업로드한다.

        Args:
            video_path: 업로드할 동영상 파일 경로.
            thumbnail_path: 커스텀 썸네일 이미지 경로 (optional).
            title: 동영상 제목 (최대 100자).
            description: 동영상 설명.
            tags: 태그 목록.
            category_id: YouTube 카테고리 ID (기본 15=Pets & Animals).
            is_short: True면 Shorts (#Shorts 태그 추가), False면 롱폼.

        Returns:
            UploadResult: 업로드 결과.
        """
        video_path = Path(video_path)
        if not video_path.exists():
            return UploadResult(
                success=False,
                platform="youtube",
                error_message=f"Video file not found: {video_path}",
            )

        # 쿼타 체크
        if not self._check_quota():
            return UploadResult(
                success=False,
                platform="youtube",
                error_message="Daily YouTube API quota exceeded",
            )

        # Shorts 표시: is_short=True일 때만 제목에 #Shorts 추가
        if is_short:
            title = self._ensure_shorts_tag(title)

        try:
            # OAuth 인증
            service = await self._get_service()
            if service is None:
                return UploadResult(
                    success=False,
                    platform="youtube",
                    error_message="Failed to authenticate with YouTube API",
                )

            # 리줌어블 업로드
            video_id = await self._resumable_upload(
                service=service,
                video_path=video_path,
                title=title,
                description=description,
                tags=tags or [],
                category_id=str(category_id or self._category_id),
            )

            if not video_id:
                return UploadResult(
                    success=False,
                    platform="youtube",
                    error_message="Upload returned no video ID",
                )

            # 쿼타 기록 (업로드 비용)
            self._consume_quota(self._upload_cost)

            # 썸네일 설정
            if thumbnail_path:
                thumbnail_path = Path(thumbnail_path)
                if thumbnail_path.exists():
                    await self._set_thumbnail(service, video_id, thumbnail_path)
                    self._consume_quota(self._thumbnail_cost)
                else:
                    logger.warning(f"Thumbnail file not found: {thumbnail_path}")

            if is_short:
                url = f"https://youtube.com/shorts/{video_id}"
            else:
                url = f"https://youtube.com/watch?v={video_id}"
            logger.bind(event=True).info(
                f"YouTube upload success — id={video_id}, title={title[:50]}"
            )

            return UploadResult(
                success=True,
                platform="youtube",
                video_id=video_id,
                url=url,
                status="uploaded",
            )

        except Exception as e:
            logger.error(f"YouTube upload failed: {e}")
            return UploadResult(
                success=False,
                platform="youtube",
                error_message=str(e),
            )

    # ------------------------------------------------------------------
    # OAuth 2.0 Authentication
    # ------------------------------------------------------------------

    async def _get_service(self):
        """YouTube Data API v3 서비스 객체를 반환한다 (인증 포함).

        토큰 파일이 있으면 로드, 없거나 만료되면 갱신/재인증한다.
        """
        if self._service is not None:
            return self._service

        if Credentials is None:
            logger.error("google-auth library not available")
            return None

        loop = asyncio.get_running_loop()
        credentials = await loop.run_in_executor(None, self._load_or_refresh_credentials)

        if credentials is None:
            return None

        self._service = await loop.run_in_executor(
            None,
            lambda: build("youtube", "v3", credentials=credentials),
        )
        return self._service

    def _load_or_refresh_credentials(self) -> Optional[Credentials]:
        """자격증명을 로드하거나 갱신한다 (블로킹).

        1. youtube_token.json 존재 → 로드 → 만료 시 refresh
        2. youtube_token.json 없음 → OAuth flow 실행 → 토큰 저장
        """
        creds = None

        # 기존 토큰 로드
        if self._token_path.exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    str(self._token_path), _SCOPES
                )
            except Exception as e:
                logger.warning(f"Failed to load YouTube token: {e}")
                creds = None

        # 토큰 갱신
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._save_token(creds)
                logger.info("YouTube token refreshed")
            except Exception as e:
                logger.warning(f"Token refresh failed, re-authenticating: {e}")
                creds = None

        # 새 인증 (토큰이 없거나 갱신 실패)
        if creds is None or not creds.valid:
            if not self._oauth_path.exists():
                logger.error(f"YouTube OAuth credentials not found: {self._oauth_path}")
                return None
            try:
                flow = InstalledAppFlow.from_client_secrets_file(
                    str(self._oauth_path), _SCOPES
                )
                creds = flow.run_local_server(port=0)
                self._save_token(creds)
                logger.info("YouTube OAuth authentication completed")
            except Exception as e:
                logger.error(f"YouTube OAuth flow failed: {e}")
                return None

        return creds

    def _save_token(self, creds: Credentials) -> None:
        """인증 토큰을 JSON 파일로 저장한다."""
        self._credentials_dir.mkdir(parents=True, exist_ok=True)
        with open(self._token_path, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        logger.debug(f"YouTube token saved to {self._token_path}")

    # ------------------------------------------------------------------
    # Resumable Upload
    # ------------------------------------------------------------------

    async def _resumable_upload(
        self,
        service,
        video_path: Path,
        title: str,
        description: str,
        tags: list[str],
        category_id: str,
    ) -> Optional[str]:
        """리줌어블 업로드를 수행하고 video_id를 반환한다.

        네트워크 오류 시 자동 재시도하며, 진행률을 로깅한다.
        """
        body = {
            "snippet": {
                "title": title[:100],  # YouTube 제목 최대 100자
                "description": description[:5000],
                "tags": tags[:500],
                "categoryId": category_id,
                "defaultLanguage": self._default_language,
                "defaultAudioLanguage": self._default_language,
            },
            "status": {
                "privacyStatus": self._privacy_status,
                "selfDeclaredMadeForKids": self._made_for_kids,
                "embeddable": True,
            },
        }

        media = MediaFileUpload(
            str(video_path),
            mimetype="video/mp4",
            resumable=True,
            chunksize=10 * 1024 * 1024,  # 10MB 청크
        )

        loop = asyncio.get_running_loop()

        # insert 요청 생성
        request = service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        retry_count = 0

        logger.info(f"Starting YouTube upload: {video_path.name} ({video_path.stat().st_size / 1024 / 1024:.1f}MB)")

        while response is None:
            try:
                # 청크 업로드 (블로킹이므로 executor 사용)
                status, response = await loop.run_in_executor(
                    None, request.next_chunk
                )

                if status:
                    progress = int(status.progress() * 100)
                    logger.debug(f"YouTube upload progress: {progress}%")

            except HttpError as e:
                if e.resp.status in _RETRIABLE_STATUS_CODES:
                    retry_count += 1
                    if retry_count > _MAX_RETRIES:
                        logger.error(f"YouTube upload max retries exceeded: {e}")
                        return None

                    delay = min(
                        _RETRY_BASE_DELAY * (2 ** (retry_count - 1)),
                        _RETRY_MAX_DELAY,
                    )
                    logger.warning(
                        f"YouTube upload retry {retry_count}/{_MAX_RETRIES} "
                        f"(HTTP {e.resp.status}), waiting {delay:.1f}s"
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"YouTube upload HTTP error: {e}")
                    return None

            except _RETRIABLE_EXCEPTIONS as e:
                retry_count += 1
                if retry_count > _MAX_RETRIES:
                    logger.error(f"YouTube upload max retries exceeded: {e}")
                    return None

                delay = min(
                    _RETRY_BASE_DELAY * (2 ** (retry_count - 1)),
                    _RETRY_MAX_DELAY,
                )
                logger.warning(
                    f"YouTube upload retry {retry_count}/{_MAX_RETRIES} "
                    f"({type(e).__name__}), waiting {delay:.1f}s"
                )
                await asyncio.sleep(delay)

        video_id = response.get("id", "")
        logger.info(f"YouTube upload complete — video_id={video_id}")
        return video_id

    # ------------------------------------------------------------------
    # Thumbnail
    # ------------------------------------------------------------------

    async def _set_thumbnail(self, service, video_id: str, thumbnail_path: Path) -> bool:
        """업로드된 동영상에 커스텀 썸네일을 설정한다."""
        loop = asyncio.get_running_loop()

        try:
            media = MediaFileUpload(
                str(thumbnail_path),
                mimetype="image/jpeg",
                resumable=False,
            )

            await loop.run_in_executor(
                None,
                lambda: service.thumbnails().set(
                    videoId=video_id,
                    media_body=media,
                ).execute(),
            )

            logger.info(f"Thumbnail set for video {video_id}")
            return True

        except HttpError as e:
            logger.warning(f"Failed to set thumbnail for {video_id}: {e}")
            return False

    # ------------------------------------------------------------------
    # Shorts Detection & Tagging
    # ------------------------------------------------------------------

    @staticmethod
    def _ensure_shorts_tag(title: str) -> str:
        """제목에 #Shorts 태그가 없으면 추가한다.

        YouTube Shorts는 제목이나 설명에 #Shorts가 있어야
        Shorts 피드에 노출된다.
        """
        if "#Shorts" not in title and "#shorts" not in title:
            # 제목 길이 제한 (100자) 고려
            tag = " #Shorts"
            if len(title) + len(tag) <= 100:
                title = title + tag
            else:
                # 공간 부족 시 제목 끝을 잘라서 추가
                title = title[: 100 - len(tag)] + tag

        return title

    # ------------------------------------------------------------------
    # Quota Tracking
    # ------------------------------------------------------------------

    def _check_quota(self) -> bool:
        """일일 쿼타 내에서 업로드 가능한지 확인한다."""
        self._refresh_quota_date()
        remaining = self._daily_quota - self._quota_used
        needed = self._upload_cost + self._thumbnail_cost
        if remaining < needed:
            logger.warning(
                f"YouTube quota insufficient — "
                f"used={self._quota_used}/{self._daily_quota}, needed={needed}"
            )
            return False
        return True

    def _consume_quota(self, cost: int) -> None:
        """쿼타 사용량을 기록한다."""
        self._refresh_quota_date()
        self._quota_used += cost
        logger.debug(
            f"YouTube quota: {self._quota_used}/{self._daily_quota} "
            f"(+{cost})"
        )

    def _refresh_quota_date(self) -> None:
        """날짜가 바뀌면 쿼타를 리셋한다.

        YouTube API 쿼타는 태평양 시간(PT) 자정에 리셋되지만,
        단순화를 위해 로컬 날짜 기준으로 리셋한다.
        """
        import datetime

        today = datetime.date.today().isoformat()
        if self._quota_date != today:
            self._quota_date = today
            self._quota_used = 0
            logger.debug(f"YouTube quota reset for {today}")

    @property
    def quota_remaining(self) -> int:
        """남은 일일 쿼타를 반환한다."""
        self._refresh_quota_date()
        return max(0, self._daily_quota - self._quota_used)
