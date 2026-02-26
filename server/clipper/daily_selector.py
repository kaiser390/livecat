"""
LiveCat - Daily Selector

오늘 추출된 클립 중 TOP 10을 선별한다.

선별 기준:
  1. 메타데이터 JSON에서 quality_score 읽기 (없으면 실시간 채점)
  2. 연속 동일 이벤트 중복 제거 (최고 점수만 유지)
  3. 다양성 필터: 동일 event_type 최대 3개
  4. 점수 순 TOP N (기본 10) 반환
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from server.clipper.clip_scorer import ClipScorer
from server.clipper.event_detector import CatEvent


@dataclass
class ClipInfo:
    """선별된 클립 정보."""

    clip_path: Path
    metadata: dict[str, Any]
    score: float
    processed: bool = False


class DailySelector:
    """
    일일 TOP N 클립 선별기.

    오늘 날짜 디렉토리의 모든 클립을 스캔하고,
    중복 제거 + 다양성 필터를 거쳐 상위 N개를 반환한다.
    """

    def __init__(self, config: dict, clip_scorer: ClipScorer) -> None:
        self.config = config
        self.clip_scorer = clip_scorer

        clip_cfg = config.get("clip", {})
        self.top_n: int = clip_cfg.get("daily_top_n", 10)
        self.output_dir = Path(clip_cfg.get("output_dir", "clips"))
        self.max_same_event_type: int = 3  # diversity cap

        # Cache: day_str -> list[ClipInfo]
        self._cache: dict[str, list[ClipInfo]] = {}
        self._cache_timestamp: float = 0.0
        self._cache_ttl: float = 60.0  # refresh every 60 seconds

        logger.info(
            f"DailySelector initialised — top_n={self.top_n} "
            f"max_same_type={self.max_same_event_type}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def select_top_clips(self) -> list[ClipInfo]:
        """
        오늘의 TOP N 클립을 선별하여 반환한다.

        Returns:
            점수 순으로 정렬된 ClipInfo 리스트 (최대 top_n개).
        """
        today_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        day_dir = self.output_dir / today_str

        if not day_dir.exists():
            logger.debug(f"No clips directory for today: {day_dir}")
            return []

        # Load all clips with metadata
        all_clips = self._load_clips(day_dir)

        if not all_clips:
            logger.debug("No clips found for today")
            return []

        logger.info(f"Loaded {len(all_clips)} clips for {today_str}")

        # Step 1: Deduplicate consecutive same events
        deduped = self._deduplicate_consecutive(all_clips)
        logger.debug(
            f"After dedup: {len(deduped)} clips (removed {len(all_clips) - len(deduped)})"
        )

        # Step 2: Diversity filter (max N per event_type)
        diverse = self._apply_diversity_filter(deduped)
        logger.debug(
            f"After diversity filter: {len(diverse)} clips "
            f"(removed {len(deduped) - len(diverse)})"
        )

        # Step 3: Sort by score and take top N
        diverse.sort(key=lambda c: c.score, reverse=True)
        top_clips = diverse[: self.top_n]

        # Preserve processed state from cache
        self._merge_processed_state(today_str, top_clips)

        logger.info(
            f"Selected top {len(top_clips)} clips "
            f"(scores: {[round(c.score, 1) for c in top_clips]})"
        )

        return top_clips

    @property
    def clips_today_count(self) -> int:
        """오늘 저장된 총 클립 수."""
        today_str = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")
        day_dir = self.output_dir / today_str

        if not day_dir.exists():
            return 0

        return len(list(day_dir.glob("*.mp4")))

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def _load_clips(self, day_dir: Path) -> list[ClipInfo]:
        """
        오늘의 클립과 메타데이터를 로드한다.

        각 .mp4 파일에 대응하는 .json이 있으면 메타데이터를 읽고,
        quality_score가 없으면 ClipScorer로 채점한다.
        """
        clips: list[ClipInfo] = []

        for mp4_path in sorted(day_dir.glob("*.mp4")):
            meta_path = mp4_path.with_suffix(".json")
            metadata: dict[str, Any] = {}
            score: float = 0.0

            if meta_path.exists():
                try:
                    with open(meta_path, "r", encoding="utf-8") as f:
                        metadata = json.load(f)

                    score = metadata.get("quality_score", 0.0)
                except (json.JSONDecodeError, OSError) as e:
                    logger.warning(f"Failed to read metadata {meta_path.name}: {e}")

            # If no score yet, score it now
            if score <= 0.0:
                score = self._score_clip(mp4_path, metadata)

            clips.append(
                ClipInfo(
                    clip_path=mp4_path,
                    metadata=metadata,
                    score=score,
                    processed=False,
                )
            )

        return clips

    def _score_clip(self, clip_path: Path, metadata: dict) -> float:
        """메타데이터로부터 CatEvent를 재구성하여 채점한다."""
        try:
            event = CatEvent(
                event_type=metadata.get("event_type", "unknown"),
                camera_id=metadata.get("camera_id", "unknown"),
                cats=metadata.get("cats", []),
                score=metadata.get("score", 50.0),
                timestamp=metadata.get("timestamp", 0.0),
                duration_sec=metadata.get("duration_sec", 0.0),
                metadata=metadata.get("event_metadata", {}),
            )
            return self.clip_scorer.score(clip_path, event)
        except Exception as e:
            logger.warning(f"Scoring failed for {clip_path.name}: {e}")
            return 0.0

    # ------------------------------------------------------------------
    # Deduplication
    # ------------------------------------------------------------------

    def _deduplicate_consecutive(self, clips: list[ClipInfo]) -> list[ClipInfo]:
        """
        연속된 동일 이벤트에서 최고 점수만 유지한다.

        동일 이벤트 판정: event_type이 같고 timestamp 차이가 60초 이내.
        """
        if not clips:
            return []

        # Sort by timestamp
        sorted_clips = sorted(
            clips,
            key=lambda c: c.metadata.get("timestamp", 0.0),
        )

        deduped: list[ClipInfo] = []
        current_group: list[ClipInfo] = [sorted_clips[0]]

        for i in range(1, len(sorted_clips)):
            prev = sorted_clips[i - 1]
            curr = sorted_clips[i]

            prev_type = prev.metadata.get("event_type", "")
            curr_type = curr.metadata.get("event_type", "")
            prev_ts = prev.metadata.get("timestamp", 0.0)
            curr_ts = curr.metadata.get("timestamp", 0.0)

            # Same event type within 60 seconds = consecutive duplicate
            if curr_type == prev_type and abs(curr_ts - prev_ts) <= 60.0:
                current_group.append(curr)
            else:
                # Keep best from current group
                best = max(current_group, key=lambda c: c.score)
                deduped.append(best)
                current_group = [curr]

        # Don't forget the last group
        if current_group:
            best = max(current_group, key=lambda c: c.score)
            deduped.append(best)

        return deduped

    # ------------------------------------------------------------------
    # Diversity filter
    # ------------------------------------------------------------------

    def _apply_diversity_filter(self, clips: list[ClipInfo]) -> list[ClipInfo]:
        """
        동일 event_type 최대 max_same_event_type개로 제한한다.

        점수 순으로 처리하여 상위 클립이 우선 선택된다.
        """
        # Sort by score descending first
        scored = sorted(clips, key=lambda c: c.score, reverse=True)

        type_counts: dict[str, int] = {}
        filtered: list[ClipInfo] = []

        for clip in scored:
            event_type = clip.metadata.get("event_type", "unknown")
            count = type_counts.get(event_type, 0)

            if count < self.max_same_event_type:
                filtered.append(clip)
                type_counts[event_type] = count + 1
            else:
                logger.debug(
                    f"Diversity cap: skipping {clip.clip_path.name} "
                    f"({event_type} already has {self.max_same_event_type})"
                )

        return filtered

    # ------------------------------------------------------------------
    # Cache / state management
    # ------------------------------------------------------------------

    def _merge_processed_state(
        self, today_str: str, top_clips: list[ClipInfo]
    ) -> None:
        """
        이전 선별 결과의 processed 상태를 보존한다.

        이미 처리된 클립은 processed=True를 유지하여 batch pipeline이
        중복 처리하지 않도록 한다.
        """
        cached = self._cache.get(today_str, [])
        processed_paths: set[str] = {
            str(c.clip_path) for c in cached if c.processed
        }

        for clip in top_clips:
            if str(clip.clip_path) in processed_paths:
                clip.processed = True

        # Update cache
        self._cache[today_str] = top_clips

        # Clean old dates from cache (keep only last 3 days)
        if len(self._cache) > 3:
            sorted_keys = sorted(self._cache.keys())
            for old_key in sorted_keys[:-3]:
                del self._cache[old_key]
