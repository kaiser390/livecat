"""
LiveCat - Clip Extractor

감지된 이벤트를 기반으로 롤링 버퍼에서 영상 클립을 추출한다.
이벤트 기준 -5초 ~ +15초 (총 20초)를 ffmpeg로 추출/트림.
클립과 메타데이터 JSON을 함께 저장한다.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from server.clipper.event_detector import CatEvent


def _generate_event_id(event: CatEvent) -> str:
    """이벤트 ID 생성: timestamp + event_type."""
    ts_str = datetime.fromtimestamp(event.timestamp, tz=timezone.utc).strftime(
        "%H%M%S"
    )
    ms = int((event.timestamp % 1) * 1000)
    return f"{ts_str}{ms:03d}_{event.event_type}"


class ClipExtractor:
    """
    롤링 버퍼에서 이벤트 클립을 추출한다.

    StreamBuffer는 10초 단위 세그먼트를 유지하며,
    이 클래스는 필요한 세그먼트를 연결하여 정확한 구간을 잘라낸다.
    """

    def __init__(self, config: dict, stream_buffer: Any) -> None:
        self.config = config
        self.stream_buffer = stream_buffer

        clip_cfg = config.get("clip", {})
        self.pre_event_sec: float = clip_cfg.get("pre_event_sec", 5)
        self.post_event_sec: float = clip_cfg.get("post_event_sec", 15)
        self.total_duration_sec: float = clip_cfg.get("total_duration_sec", 20)
        self.output_dir = Path(clip_cfg.get("output_dir", "clips"))
        self.buffer_dir = Path(clip_cfg.get("rolling_buffer_dir", "clips/_buffer"))
        self.segment_sec: int = clip_cfg.get("rolling_buffer_segment_sec", 10)

        # Ensure base output directory exists
        self.output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"ClipExtractor initialised — "
            f"pre={self.pre_event_sec}s post={self.post_event_sec}s "
            f"output={self.output_dir}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def extract(self, event: CatEvent) -> Path | None:
        """
        이벤트 기반으로 클립을 추출한다.

        1. post_event 시간만큼 대기 (이벤트 후 영상 확보)
        2. 롤링 버퍼에서 세그먼트 파일 수집
        3. ffmpeg로 연결 + 트림
        4. 메타데이터 JSON 저장

        Returns:
            클립 파일 경로, 실패 시 None.
        """
        event_id = _generate_event_id(event)

        # 오늘 날짜 디렉토리
        today_str = datetime.fromtimestamp(
            event.timestamp, tz=timezone.utc
        ).strftime("%Y-%m-%d")
        day_dir = self.output_dir / today_str
        day_dir.mkdir(parents=True, exist_ok=True)

        clip_path = day_dir / f"{event_id}.mp4"
        meta_path = day_dir / f"{event_id}.json"

        logger.info(
            f"Extracting clip: {event_id} "
            f"({self.pre_event_sec}s pre + {self.post_event_sec}s post)"
        )

        # Wait for post-event footage to accumulate in the buffer
        await asyncio.sleep(self.post_event_sec)

        try:
            # Step 1: Collect relevant segment files from rolling buffer
            segments = self._collect_segments(event)

            if not segments:
                logger.warning(
                    f"No segments found for event {event_id} — skipping"
                )
                return None

            # Step 2: Concatenate segments and trim to exact range
            success = await self._extract_with_ffmpeg(
                segments, event, clip_path
            )

            if not success:
                logger.error(f"ffmpeg extraction failed for {event_id}")
                return None

            # Step 3: Verify output file
            if not clip_path.exists() or clip_path.stat().st_size < 1024:
                logger.error(
                    f"Clip file missing or too small: {clip_path}"
                )
                return None

            # Step 4: Save metadata JSON
            self._save_metadata(meta_path, event, event_id, clip_path)

            file_size_mb = clip_path.stat().st_size / (1024 * 1024)
            logger.info(
                f"Clip extracted: {clip_path.name} "
                f"({file_size_mb:.1f} MB)"
            )

            return clip_path

        except Exception as e:
            logger.error(f"Clip extraction error for {event_id}: {e}")
            return None

    # ------------------------------------------------------------------
    # Segment collection
    # ------------------------------------------------------------------

    def _collect_segments(self, event: CatEvent) -> list[Path]:
        """
        롤링 버퍼에서 이벤트 구간에 해당하는 세그먼트 파일을 수집한다.

        StreamBuffer 인터페이스:
          - get_segments(camera_id, start_time, end_time) -> list[SegmentInfo]
            SegmentInfo: path, start_time, end_time
          - get_segment_files(camera_id, start_time, end_time) -> list[Path]
        """
        start_time = event.timestamp - self.pre_event_sec
        end_time = event.timestamp + self.post_event_sec

        # Try StreamBuffer's segment retrieval methods
        if hasattr(self.stream_buffer, "get_segment_files"):
            segments = self.stream_buffer.get_segment_files(
                event.camera_id, start_time, end_time
            )
            if segments:
                return [Path(s) for s in segments]

        if hasattr(self.stream_buffer, "get_segments"):
            seg_infos = self.stream_buffer.get_segments(
                event.camera_id, start_time, end_time
            )
            if seg_infos:
                return [Path(s.path) for s in seg_infos]

        # Fallback: scan buffer directory for matching segment files
        # Convention: {camera_id}_{timestamp}.ts or .mp4
        return self._scan_buffer_directory(event.camera_id, start_time, end_time)

    def _scan_buffer_directory(
        self, camera_id: str, start_time: float, end_time: float
    ) -> list[Path]:
        """
        버퍼 디렉토리를 직접 스캔하여 세그먼트를 찾는다.

        파일명 규칙: {camera_id}_{unix_timestamp}.{ext}
        """
        if not self.buffer_dir.exists():
            logger.warning(f"Buffer directory does not exist: {self.buffer_dir}")
            return []

        segments: list[tuple[float, Path]] = []
        patterns = [f"{camera_id}_*.ts", f"{camera_id}_*.mp4"]

        for pattern in patterns:
            for seg_path in self.buffer_dir.glob(pattern):
                try:
                    # Extract timestamp from filename
                    stem = seg_path.stem  # e.g. "CAM-1_1700000000"
                    parts = stem.split("_", 1)
                    if len(parts) < 2:
                        continue
                    seg_ts = float(parts[1])

                    # Segment covers [seg_ts, seg_ts + segment_sec]
                    seg_end = seg_ts + self.segment_sec

                    # Overlap check
                    if seg_end >= start_time and seg_ts <= end_time:
                        segments.append((seg_ts, seg_path))
                except (ValueError, IndexError):
                    continue

        # Sort by timestamp
        segments.sort(key=lambda x: x[0])
        return [p for _, p in segments]

    # ------------------------------------------------------------------
    # ffmpeg operations
    # ------------------------------------------------------------------

    async def _extract_with_ffmpeg(
        self,
        segments: list[Path],
        event: CatEvent,
        output_path: Path,
    ) -> bool:
        """
        ffmpeg로 세그먼트를 연결하고 정확한 구간을 트림한다.

        단일 세그먼트이면 직접 trim, 복수이면 concat 후 trim.
        """
        if len(segments) == 1:
            return await self._trim_single(segments[0], event, output_path)
        else:
            return await self._concat_and_trim(segments, event, output_path)

    async def _trim_single(
        self, segment: Path, event: CatEvent, output_path: Path
    ) -> bool:
        """단일 세그먼트에서 직접 트림."""
        # Calculate offset within segment
        try:
            seg_ts = float(segment.stem.split("_", 1)[1])
        except (ValueError, IndexError):
            seg_ts = event.timestamp - self.pre_event_sec

        start_offset = max(0, (event.timestamp - self.pre_event_sec) - seg_ts)

        cmd = [
            "ffmpeg",
            "-y",
            "-ss", f"{start_offset:.3f}",
            "-i", str(segment),
            "-t", f"{self.total_duration_sec:.3f}",
            "-c:v", "libx264",
            "-preset", "fast",
            "-crf", "23",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ]

        return await self._run_ffmpeg(cmd)

    async def _concat_and_trim(
        self,
        segments: list[Path],
        event: CatEvent,
        output_path: Path,
    ) -> bool:
        """복수 세그먼트를 concat 후 트림."""
        # Create concat list file
        concat_list = output_path.with_suffix(".concat.txt")
        try:
            with open(concat_list, "w", encoding="utf-8") as f:
                for seg in segments:
                    # ffmpeg concat requires forward slashes or escaped backslashes
                    safe_path = str(seg).replace("\\", "/")
                    f.write(f"file '{safe_path}'\n")

            # Calculate start offset relative to first segment
            try:
                first_seg_ts = float(segments[0].stem.split("_", 1)[1])
            except (ValueError, IndexError):
                first_seg_ts = event.timestamp - self.pre_event_sec

            start_offset = max(
                0, (event.timestamp - self.pre_event_sec) - first_seg_ts
            )

            cmd = [
                "ffmpeg",
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_list),
                "-ss", f"{start_offset:.3f}",
                "-t", f"{self.total_duration_sec:.3f}",
                "-c:v", "libx264",
                "-preset", "fast",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                str(output_path),
            ]

            return await self._run_ffmpeg(cmd)

        finally:
            # Clean up concat list
            if concat_list.exists():
                concat_list.unlink()

    async def _run_ffmpeg(self, cmd: list[str]) -> bool:
        """ffmpeg 프로세스를 비동기로 실행한다."""
        logger.debug(f"ffmpeg cmd: {' '.join(cmd)}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=120
            )

            if proc.returncode != 0:
                err_text = stderr.decode("utf-8", errors="replace")[-500:]
                logger.error(f"ffmpeg failed (rc={proc.returncode}): {err_text}")
                return False

            return True

        except asyncio.TimeoutError:
            logger.error("ffmpeg timed out (120s)")
            proc.kill()
            return False
        except FileNotFoundError:
            logger.error(
                "ffmpeg not found — ensure ffmpeg is installed and on PATH"
            )
            return False

    # ------------------------------------------------------------------
    # Metadata JSON
    # ------------------------------------------------------------------

    def _save_metadata(
        self,
        meta_path: Path,
        event: CatEvent,
        event_id: str,
        clip_path: Path,
    ) -> None:
        """이벤트 메타데이터를 JSON으로 저장한다."""
        meta = {
            "event_id": event_id,
            "event_type": event.event_type,
            "camera_id": event.camera_id,
            "cats": event.cats,
            "score": event.score,
            "timestamp": event.timestamp,
            "timestamp_iso": datetime.fromtimestamp(
                event.timestamp, tz=timezone.utc
            ).isoformat(),
            "duration_sec": event.duration_sec,
            "pre_event_sec": self.pre_event_sec,
            "post_event_sec": self.post_event_sec,
            "total_clip_sec": self.total_duration_sec,
            "clip_file": clip_path.name,
            "clip_size_bytes": clip_path.stat().st_size if clip_path.exists() else 0,
            "event_metadata": event.metadata,
            "extracted_at": datetime.now(tz=timezone.utc).isoformat(),
        }

        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2, ensure_ascii=False)

        logger.debug(f"Metadata saved: {meta_path.name}")
