"""
업로드 추적 모듈.

모든 업로드 결과를 일별 JSON 파일과 append-only JSONL 로그에 기록한다.
일별 업로드 횟수, 플랫폼별 통계 조회 기능을 제공한다.
"""

from __future__ import annotations

import datetime
import json
import time
from pathlib import Path
from typing import Optional

from loguru import logger

from server.uploader.youtube_uploader import UploadResult


class UploadTracker:
    """업로드 결과를 추적하고 기록하는 클래스.

    - uploads/{YYYY-MM-DD}/{event_id}_result.json: 이벤트별 상세 결과
    - uploads/upload_history.jsonl: 전체 이력 (append-only)

    config에서 uploads 디렉토리 경로를 결정한다.
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        self._root_dir = Path(config.get("_root_dir", "."))
        self._uploads_dir = self._root_dir / "uploads"
        self._uploads_dir.mkdir(parents=True, exist_ok=True)

        self._history_path = self._uploads_dir / "upload_history.jsonl"

        logger.info(f"UploadTracker initialized — dir={self._uploads_dir}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def track(self, result: UploadResult, metadata: Optional[dict] = None) -> None:
        """업로드 결과를 기록한다.

        Args:
            result: UploadResult 데이터.
            metadata: 추가 메타데이터 (event_id, event_type, clip_path 등).
        """
        metadata = metadata or {}
        today = datetime.date.today().isoformat()
        event_id = metadata.get("event_id", f"upload_{int(time.time() * 1000)}")

        # 결과 데이터 구성
        record = {
            "event_id": event_id,
            "timestamp": datetime.datetime.now().isoformat(),
            "platform": result.platform,
            "success": result.success,
            "video_id": result.video_id,
            "url": result.url,
            "status": result.status,
            "error_message": result.error_message,
            "uploaded_at": result.uploaded_at,
            "metadata": metadata,
        }

        # 1. 일별 디렉토리에 상세 결과 저장
        self._save_daily_result(today, event_id, record)

        # 2. JSONL 히스토리에 추가
        self._append_history(record)

        log_msg = (
            f"Upload tracked — platform={result.platform}, "
            f"success={result.success}, event_id={event_id}"
        )
        if result.success:
            logger.bind(event=True).info(log_msg)
        else:
            logger.bind(event=True).warning(
                f"{log_msg}, error={result.error_message}"
            )

    def get_history(self, date: Optional[str] = None) -> list[dict]:
        """업로드 히스토리를 반환한다.

        Args:
            date: 특정 날짜 (YYYY-MM-DD) 필터. None이면 전체 히스토리.

        Returns:
            업로드 기록 목록 (최신 순).
        """
        records = []

        if date:
            # 특정 날짜의 일별 디렉토리에서 로드
            day_dir = self._uploads_dir / date
            if day_dir.exists():
                for f in sorted(day_dir.glob("*_result.json"), reverse=True):
                    try:
                        with open(f, "r", encoding="utf-8") as fh:
                            records.append(json.load(fh))
                    except (json.JSONDecodeError, IOError) as e:
                        logger.debug(f"Failed to read upload result {f}: {e}")
        else:
            # JSONL 전체 히스토리에서 로드
            if self._history_path.exists():
                try:
                    with open(self._history_path, "r", encoding="utf-8") as fh:
                        for line in fh:
                            line = line.strip()
                            if line:
                                try:
                                    records.append(json.loads(line))
                                except json.JSONDecodeError:
                                    continue
                except IOError as e:
                    logger.error(f"Failed to read upload history: {e}")

            # 최신 순 정렬
            records.sort(key=lambda r: r.get("timestamp", ""), reverse=True)

        return records

    def get_daily_count(self, platform: str, date: Optional[str] = None) -> int:
        """특정 플랫폼의 오늘(또는 지정 날짜) 업로드 횟수를 반환한다.

        Args:
            platform: 플랫폼 이름 ("youtube" 또는 "tiktok").
            date: 날짜 (YYYY-MM-DD). None이면 오늘.

        Returns:
            성공한 업로드 횟수.
        """
        target_date = date or datetime.date.today().isoformat()
        day_dir = self._uploads_dir / target_date

        if not day_dir.exists():
            return 0

        count = 0
        for f in day_dir.glob("*_result.json"):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    record = json.load(fh)
                    if (
                        record.get("platform") == platform
                        and record.get("success") is True
                    ):
                        count += 1
            except (json.JSONDecodeError, IOError):
                continue

        return count

    def get_daily_stats(self, date: Optional[str] = None) -> dict:
        """오늘(또는 지정 날짜)의 플랫폼별 업로드 통계를 반환한다.

        Returns:
            {"youtube": {"success": N, "failed": M}, "tiktok": {...}, "total": T}
        """
        target_date = date or datetime.date.today().isoformat()
        day_dir = self._uploads_dir / target_date

        stats = {
            "youtube": {"success": 0, "failed": 0},
            "tiktok": {"success": 0, "failed": 0},
            "total": 0,
        }

        if not day_dir.exists():
            return stats

        for f in day_dir.glob("*_result.json"):
            try:
                with open(f, "r", encoding="utf-8") as fh:
                    record = json.load(fh)
                    platform = record.get("platform", "unknown")
                    if platform in stats:
                        if record.get("success"):
                            stats[platform]["success"] += 1
                        else:
                            stats[platform]["failed"] += 1
                        stats["total"] += 1
            except (json.JSONDecodeError, IOError):
                continue

        return stats

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _save_daily_result(self, date: str, event_id: str, record: dict) -> None:
        """일별 디렉토리에 개별 업로드 결과를 저장한다."""
        day_dir = self._uploads_dir / date
        day_dir.mkdir(parents=True, exist_ok=True)

        result_path = day_dir / f"{event_id}_result.json"
        try:
            with open(result_path, "w", encoding="utf-8") as f:
                json.dump(record, f, indent=2, ensure_ascii=False)
            logger.debug(f"Upload result saved: {result_path}")
        except IOError as e:
            logger.error(f"Failed to save upload result: {e}")

    def _append_history(self, record: dict) -> None:
        """JSONL 히스토리 파일에 레코드를 추가한다 (append-only)."""
        try:
            with open(self._history_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except IOError as e:
            logger.error(f"Failed to append to upload history: {e}")
