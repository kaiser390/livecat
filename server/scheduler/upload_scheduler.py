"""
업로드 스케줄러 모듈.

최적 시간대에 맞춰 YouTube Shorts와 TikTok 업로드를 자동 스케줄링한다.
우선순위 큐, 일일 제한, 최소 간격, 재시도 로직을 포함한다.
큐는 scheduler/queue.json에 영속 저장된다.
"""

from __future__ import annotations

import asyncio
import datetime
import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from loguru import logger

from server.uploader.youtube_uploader import YouTubeUploader, UploadResult
from server.uploader.tiktok_uploader import TikTokUploader
from server.uploader.upload_tracker import UploadTracker


# 이벤트 유형별 우선순위 (낮을수록 높은 우선순위)
_DEFAULT_PRIORITY_ORDER = [
    "interact",
    "climb",
    "jump",
    "hunt_attempt",
    "run",
    "sleep",
]


@dataclass
class QueueItem:
    """업로드 큐 아이템."""

    item_id: str
    video_path: str
    thumbnail_path: str = ""
    title: str = ""
    description: str = ""
    hashtags: list[str] = field(default_factory=list)
    platform: str = "shorts"  # "shorts" or "tiktok"
    event_type: str = "unknown"
    priority: int = 99
    metadata: dict = field(default_factory=dict)
    enqueued_at: float = field(default_factory=time.time)
    retry_count: int = 0
    last_error: str = ""
    status: str = "pending"  # pending, uploading, done, failed


class UploadScheduler:
    """업로드 스케줄러 — 최적 시간대에 자동 업로드를 관리한다.

    config['upload']['scheduler'] 설정에 따라 동작한다.

    - 최적 업로드 시간 (KST): [18, 19, 20, 21, 22]
    - 일일 제한: YouTube Shorts 3회, TikTok 3회
    - 최소 간격: 같은 플랫폼 업로드 사이 2시간
    - 우선순위: interact > climb > jump > hunt_attempt > run > sleep
    - 재시도: 실패 시 최대 3회
    - 매시간 큐를 체크하여 업로드 가능한 아이템을 처리한다
    """

    def __init__(
        self,
        config: dict,
        youtube_uploader: YouTubeUploader,
        tiktok_uploader: TikTokUploader,
        upload_tracker: UploadTracker,
    ) -> None:
        self._config = config
        self._youtube = youtube_uploader
        self._tiktok = tiktok_uploader
        self._tracker = upload_tracker

        sched_cfg = config.get("upload", {}).get("scheduler", {})
        self._optimal_hours: list[int] = sched_cfg.get(
            "optimal_hours_kst", [18, 19, 20, 21, 22]
        )
        self._daily_shorts: int = sched_cfg.get("daily_shorts", 3)
        self._daily_tiktok: int = sched_cfg.get("daily_tiktok", 3)
        self._min_interval_hours: float = sched_cfg.get("min_interval_hours", 2)
        self._max_retry: int = sched_cfg.get("max_retry", 3)

        # 우선순위 맵 구성
        priority_order = config.get("upload", {}).get(
            "priority_order", _DEFAULT_PRIORITY_ORDER
        )
        self._priority_map: dict[str, int] = {
            event_type: idx for idx, event_type in enumerate(priority_order)
        }

        # 큐 영속 저장 경로
        self._root_dir = Path(config.get("_root_dir", "."))
        self._queue_dir = self._root_dir / "scheduler"
        self._queue_dir.mkdir(parents=True, exist_ok=True)
        self._queue_path = self._queue_dir / "queue.json"

        # 큐 로드
        self._queue: list[QueueItem] = self._load_queue()

        # 플랫폼별 마지막 업로드 시각
        self._last_upload_time: dict[str, float] = {}

        self._running = False

        logger.info(
            f"UploadScheduler initialized — "
            f"optimal_hours={self._optimal_hours}, "
            f"daily_shorts={self._daily_shorts}, "
            f"daily_tiktok={self._daily_tiktok}, "
            f"queue_size={len(self._queue)}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """스케줄러 메인 루프 — 매시간 큐를 체크하고 업로드를 수행한다."""
        self._running = True
        logger.info("UploadScheduler started — hourly check loop")

        while self._running:
            try:
                await self._process_queue()
            except Exception as e:
                logger.error(f"UploadScheduler error: {e}")

            # 1시간 대기 (5분 간격으로 중단 체크)
            for _ in range(12):
                if not self._running:
                    break
                await asyncio.sleep(300)

    async def stop(self) -> None:
        """스케줄러를 중지한다."""
        self._running = False
        self._save_queue()
        logger.info("UploadScheduler stopped")

    async def enqueue(
        self,
        video_path: Path | str,
        thumbnail_path: Optional[Path | str] = None,
        title: str = "",
        description: str = "",
        hashtags: Optional[list[str]] = None,
        platform: str = "shorts",
        metadata: Optional[dict] = None,
    ) -> str:
        """새 업로드 아이템을 큐에 추가한다.

        Args:
            video_path: 동영상 파일 경로.
            thumbnail_path: 썸네일 이미지 경로.
            title: 제목.
            description: 설명.
            hashtags: 해시태그 목록.
            platform: "shorts" 또는 "tiktok".
            metadata: 추가 메타데이터 (event_type, event_id 등).

        Returns:
            큐 아이템 ID.
        """
        metadata = metadata or {}
        event_type = metadata.get("event_type", "unknown")
        priority = self._priority_map.get(event_type, 99)

        item_id = f"{platform}_{int(time.time() * 1000)}"

        item = QueueItem(
            item_id=item_id,
            video_path=str(video_path),
            thumbnail_path=str(thumbnail_path) if thumbnail_path else "",
            title=title,
            description=description,
            hashtags=hashtags or [],
            platform=platform,
            event_type=event_type,
            priority=priority,
            metadata=metadata,
        )

        self._queue.append(item)
        self._sort_queue()
        self._save_queue()

        logger.info(
            f"Enqueued upload — id={item_id}, platform={platform}, "
            f"event={event_type}, priority={priority}, "
            f"queue_size={len(self._queue)}"
        )

        return item_id

    @property
    def queue_size(self) -> int:
        """현재 큐에 대기 중인 아이템 수를 반환한다."""
        return sum(1 for item in self._queue if item.status == "pending")

    def get_queue(self) -> list[dict]:
        """현재 큐 상태를 반환한다."""
        return [asdict(item) for item in self._queue]

    # ------------------------------------------------------------------
    # Queue Processing
    # ------------------------------------------------------------------

    async def _process_queue(self) -> None:
        """큐에서 업로드 가능한 아이템을 처리한다.

        조건:
        1. 현재 시각이 최적 업로드 시간대 (KST)인지 확인
        2. 일일 업로드 제한 체크
        3. 최소 간격 체크
        4. 우선순위 순으로 처리
        """
        if not self._queue:
            return

        # 현재 KST 시간 확인
        now_kst = self._get_kst_now()
        current_hour = now_kst.hour

        if current_hour not in self._optimal_hours:
            logger.debug(
                f"Not in optimal upload hours — "
                f"current={current_hour}h KST, "
                f"optimal={self._optimal_hours}"
            )
            return

        # pending 아이템만 대상 (우선순위 정렬됨)
        pending = [item for item in self._queue if item.status == "pending"]
        if not pending:
            return

        logger.info(
            f"Processing upload queue — "
            f"{len(pending)} pending, hour={current_hour}h KST"
        )

        for item in pending:
            # 일일 제한 체크
            if not self._check_daily_limit(item.platform):
                logger.debug(
                    f"Daily limit reached for {item.platform} — skipping"
                )
                continue

            # 최소 간격 체크
            if not self._check_interval(item.platform):
                logger.debug(
                    f"Min interval not met for {item.platform} — skipping"
                )
                continue

            # 업로드 실행
            item.status = "uploading"
            self._save_queue()

            result = await self._execute_upload(item)

            if result.success:
                item.status = "done"
                self._last_upload_time[item.platform] = time.time()

                # 추적 기록
                self._tracker.track(result, item.metadata)

                logger.info(
                    f"Upload success — id={item.item_id}, "
                    f"platform={item.platform}, video_id={result.video_id}"
                )
            else:
                item.retry_count += 1
                item.last_error = result.error_message

                if item.retry_count >= self._max_retry:
                    item.status = "failed"
                    self._tracker.track(result, item.metadata)
                    logger.warning(
                        f"Upload permanently failed — id={item.item_id}, "
                        f"retries={item.retry_count}, error={result.error_message}"
                    )
                else:
                    item.status = "pending"
                    logger.info(
                        f"Upload failed, will retry — id={item.item_id}, "
                        f"retry={item.retry_count}/{self._max_retry}, "
                        f"error={result.error_message}"
                    )

            self._save_queue()

        # 완료/실패 아이템 정리 (7일 보관)
        self._cleanup_queue()

    async def _execute_upload(self, item: QueueItem) -> UploadResult:
        """아이템에 따라 적절한 업로더로 업로드를 실행한다."""
        video_path = Path(item.video_path)

        if item.platform == "shorts":
            return await self._youtube.upload(
                video_path=video_path,
                thumbnail_path=Path(item.thumbnail_path) if item.thumbnail_path else None,
                title=item.title,
                description=item.description,
                tags=item.hashtags,
                category_id=int(
                    self._config.get("upload", {}).get("youtube", {}).get("category_id", 15)
                ),
            )
        elif item.platform == "tiktok":
            return await self._tiktok.upload(
                video_path=video_path,
                title=item.title,
                hashtags=item.hashtags,
            )
        else:
            return UploadResult(
                success=False,
                platform=item.platform,
                error_message=f"Unknown platform: {item.platform}",
            )

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------

    def _check_daily_limit(self, platform: str) -> bool:
        """일일 업로드 제한 내인지 확인한다."""
        if platform == "shorts":
            count = self._tracker.get_daily_count("youtube")
            return count < self._daily_shorts
        elif platform == "tiktok":
            count = self._tracker.get_daily_count("tiktok")
            return count < self._daily_tiktok
        return True

    def _check_interval(self, platform: str) -> bool:
        """같은 플랫폼의 마지막 업로드와 최소 간격이 지났는지 확인한다."""
        last_time = self._last_upload_time.get(platform, 0)
        elapsed_hours = (time.time() - last_time) / 3600
        return elapsed_hours >= self._min_interval_hours

    # ------------------------------------------------------------------
    # Queue Persistence
    # ------------------------------------------------------------------

    def _load_queue(self) -> list[QueueItem]:
        """queue.json에서 큐를 로드한다."""
        if not self._queue_path.exists():
            return []

        try:
            with open(self._queue_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            items = []
            for d in data:
                item = QueueItem(
                    item_id=d.get("item_id", ""),
                    video_path=d.get("video_path", ""),
                    thumbnail_path=d.get("thumbnail_path", ""),
                    title=d.get("title", ""),
                    description=d.get("description", ""),
                    hashtags=d.get("hashtags", []),
                    platform=d.get("platform", "shorts"),
                    event_type=d.get("event_type", "unknown"),
                    priority=d.get("priority", 99),
                    metadata=d.get("metadata", {}),
                    enqueued_at=d.get("enqueued_at", 0),
                    retry_count=d.get("retry_count", 0),
                    last_error=d.get("last_error", ""),
                    status=d.get("status", "pending"),
                )
                items.append(item)

            # uploading 상태였던 것은 pending으로 복구 (서버 재시작)
            for item in items:
                if item.status == "uploading":
                    item.status = "pending"

            logger.info(f"Queue loaded — {len(items)} items from {self._queue_path}")
            return items

        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Failed to load queue: {e}")
            return []

    def _save_queue(self) -> None:
        """현재 큐를 queue.json에 저장한다."""
        try:
            data = [asdict(item) for item in self._queue]
            with open(self._queue_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except IOError as e:
            logger.error(f"Failed to save queue: {e}")

    def _sort_queue(self) -> None:
        """큐를 우선순위 순으로 정렬한다 (pending만, done/failed는 뒤로)."""
        status_order = {"pending": 0, "uploading": 1, "done": 2, "failed": 3}
        self._queue.sort(
            key=lambda item: (
                status_order.get(item.status, 9),
                item.priority,
                item.enqueued_at,
            )
        )

    def _cleanup_queue(self) -> None:
        """완료/실패한 오래된 아이템을 큐에서 제거한다 (7일 보관)."""
        cutoff = time.time() - 7 * 86400
        before = len(self._queue)
        self._queue = [
            item
            for item in self._queue
            if item.status == "pending"
            or item.status == "uploading"
            or item.enqueued_at > cutoff
        ]
        removed = before - len(self._queue)
        if removed > 0:
            logger.debug(f"Queue cleanup: removed {removed} old items")
            self._save_queue()

    # ------------------------------------------------------------------
    # Time Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_kst_now() -> datetime.datetime:
        """현재 KST (UTC+9) 시각을 반환한다."""
        import zoneinfo

        try:
            kst = zoneinfo.ZoneInfo("Asia/Seoul")
        except Exception:
            # zoneinfo 사용 불가 시 수동 오프셋
            kst = datetime.timezone(datetime.timedelta(hours=9))

        return datetime.datetime.now(tz=kst)
