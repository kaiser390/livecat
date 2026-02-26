"""
롤링 스트림 버퍼 모듈.

카메라별 최근 60초 영상을 10초 세그먼트 단위 파일로 관리한다.
RAM에 전체 영상을 보관하지 않고, 파일시스템 기반으로 동작하여 메모리 효율적이다.
현재 프레임(최신 1장)만 메모리에 유지하여 실시간 파이프라인이 참조할 수 있다.
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from loguru import logger


@dataclass
class _SegmentInfo:
    """세그먼트 파일 메타데이터."""

    path: Path
    cam_id: str
    start_time: float  # monotonic 기준
    end_time: float
    duration_sec: float


@dataclass
class _CameraBuffer:
    """단일 카메라의 버퍼 상태."""

    cam_id: str
    segments: list[_SegmentInfo] = field(default_factory=list)
    latest_frame: np.ndarray | None = None
    latest_frame_time: float = 0.0

    # ffmpeg 인코딩용 상태
    _frame_queue: asyncio.Queue | None = None
    _current_segment_path: Path | None = None
    _current_segment_start: float = 0.0
    _ffmpeg_process: subprocess.Popen | None = None
    _frame_count: int = 0


class StreamBuffer:
    """카메라별 롤링 버퍼 — 60초 영상을 10초 세그먼트로 저장.

    역할:
    1. VideoReceiver로부터 프레임을 수신 (push_frame)
    2. 프레임을 ffmpeg 파이프로 전달하여 10초 단위 mp4 세그먼트 생성
    3. 오래된 세그먼트 자동 삭제 (rolling window)
    4. 클립 추출 시 세그먼트 구간 반환 (get_segment)
    """

    def __init__(self, config: dict) -> None:
        self._config = config
        self._running = False

        clip_cfg = config.get("clip", {})
        self._buffer_sec: int = clip_cfg.get("rolling_buffer_sec", 60)
        self._segment_sec: int = clip_cfg.get("rolling_buffer_segment_sec", 10)
        self._buffer_dir = Path(clip_cfg.get("rolling_buffer_dir", "clips/_buffer"))

        cam_cfg = config.get("camera", {})
        self._fps: int = cam_cfg.get("fps", 30)
        self._resolution: str = cam_cfg.get("resolution", "1080p")
        self._width, self._height = self._parse_resolution(self._resolution)

        # 카메라별 버퍼
        self._cameras: dict[str, _CameraBuffer] = {}
        for cam in cam_cfg.get("cameras", []):
            cam_id = cam["id"]
            buf = _CameraBuffer(cam_id=cam_id)
            buf._frame_queue = asyncio.Queue(maxsize=self._fps * 2)  # 2초분 큐
            self._cameras[cam_id] = buf

        # 클린업 주기
        self._cleanup_interval_sec: float = 5.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """세그먼트 인코딩 + 클린업 루프를 시작한다."""
        self._running = True
        self._ensure_buffer_dir()
        logger.info(
            f"StreamBuffer starting — {self._buffer_sec}s window, "
            f"{self._segment_sec}s segments, dir={self._buffer_dir}"
        )

        tasks = []
        for cam_id, cam_buf in self._cameras.items():
            tasks.append(
                asyncio.create_task(
                    self._encoding_loop(cam_buf),
                    name=f"encode_{cam_id}",
                )
            )

        # 오래된 세그먼트 클린업 태스크
        tasks.append(
            asyncio.create_task(self._cleanup_loop(), name="segment_cleanup")
        )

        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        finally:
            self._stop_all_encoders()
            logger.info("StreamBuffer stopped")

    async def push_frame(self, cam_id: str, frame: np.ndarray) -> None:
        """VideoReceiver가 호출 — 프레임을 버퍼에 전달한다.

        Args:
            cam_id: 카메라 ID (e.g. "CAM-1")
            frame: BGR numpy 배열 (H, W, 3)
        """
        cam_buf = self._cameras.get(cam_id)
        if cam_buf is None:
            return

        # 최신 프레임 메모리에 유지 (실시간 파이프라인용)
        cam_buf.latest_frame = frame
        cam_buf.latest_frame_time = time.monotonic()

        # 인코딩 큐에 넣기 (가득 차면 오래된 프레임 버림)
        if cam_buf._frame_queue is not None:
            if cam_buf._frame_queue.full():
                try:
                    cam_buf._frame_queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            try:
                cam_buf._frame_queue.put_nowait(frame)
            except asyncio.QueueFull:
                pass

    def get_latest_frame(self, cam_id: str) -> np.ndarray | None:
        """특정 카메라의 최신 프레임을 반환한다.

        Returns:
            BGR numpy 배열, 또는 프레임이 없으면 None.
        """
        cam_buf = self._cameras.get(cam_id)
        if cam_buf is None:
            return None

        # 2초 이상 된 프레임은 stale로 간주
        if cam_buf.latest_frame is not None:
            age = time.monotonic() - cam_buf.latest_frame_time
            if age > 2.0:
                return None

        return cam_buf.latest_frame

    def get_segment(self, cam_id: str, start_sec: float, end_sec: float) -> Path | None:
        """지정 시간 구간의 영상을 하나의 파일로 결합하여 반환한다.

        Args:
            cam_id: 카메라 ID
            start_sec: 현재 시각 기준 N초 전 (양수, e.g. 15 = 15초 전)
            end_sec: 현재 시각 기준 N초 전 (양수, e.g. 0 = 현재)

        Returns:
            결합된 영상 파일 경로, 또는 해당 구간 세그먼트가 없으면 None.
        """
        cam_buf = self._cameras.get(cam_id)
        if cam_buf is None:
            return None

        now = time.monotonic()
        abs_start = now - start_sec
        abs_end = now - end_sec

        # 구간에 겹치는 세그먼트 찾기
        matching = [
            seg
            for seg in cam_buf.segments
            if seg.end_time >= abs_start and seg.start_time <= abs_end
        ]

        if not matching:
            logger.debug(
                f"[{cam_id}] No segments for range -{start_sec}s to -{end_sec}s"
            )
            return None

        matching.sort(key=lambda s: s.start_time)

        # 세그먼트가 1개면 그대로 반환
        if len(matching) == 1:
            return matching[0].path

        # 여러 세그먼트를 ffmpeg concat으로 결합
        return self._concat_segments(cam_id, matching)

    def is_healthy(self) -> bool:
        """버퍼가 정상 동작 중인지 확인한다.

        모든 카메라에 대해 최근 10초 이내에 세그먼트가 존재하면 healthy.
        """
        if not self._running:
            return False

        now = time.monotonic()
        for cam_id, cam_buf in self._cameras.items():
            if not cam_buf.segments:
                # 아직 세그먼트가 없으면 시작 직후일 수 있으므로 skip
                continue
            latest = max(cam_buf.segments, key=lambda s: s.end_time)
            if now - latest.end_time > self._segment_sec * 2:
                logger.warning(
                    f"[{cam_id}] Buffer unhealthy — last segment "
                    f"{now - latest.end_time:.1f}s ago"
                )
                return False

        return True

    # ------------------------------------------------------------------
    # 인코딩 루프
    # ------------------------------------------------------------------

    async def _encoding_loop(self, cam_buf: _CameraBuffer) -> None:
        """프레임 큐에서 프레임을 꺼내 ffmpeg으로 세그먼트 파일을 생성한다."""
        cam_id = cam_buf.cam_id
        frames_per_segment = self._fps * self._segment_sec

        logger.info(
            f"[{cam_id}] Encoding loop started — "
            f"{frames_per_segment} frames/segment"
        )

        while self._running:
            try:
                # 새 세그먼트 시작
                segment_path = self._new_segment_path(cam_id)
                ffmpeg_proc = self._start_ffmpeg_writer(segment_path)
                segment_start = time.monotonic()
                frame_count = 0

                cam_buf._ffmpeg_process = ffmpeg_proc
                cam_buf._current_segment_path = segment_path
                cam_buf._current_segment_start = segment_start

                # 세그먼트 길이만큼 프레임 수집
                while frame_count < frames_per_segment and self._running:
                    try:
                        frame = await asyncio.wait_for(
                            cam_buf._frame_queue.get(),
                            timeout=2.0,
                        )
                    except asyncio.TimeoutError:
                        # 프레임이 안 오면 검은 프레임으로 채움
                        frame = np.zeros(
                            (self._height, self._width, 3), dtype=np.uint8
                        )

                    # ffmpeg stdin에 raw BGR 쓰기
                    try:
                        ffmpeg_proc.stdin.write(frame.tobytes())
                    except (BrokenPipeError, OSError):
                        logger.warning(f"[{cam_id}] ffmpeg pipe broken")
                        break

                    frame_count += 1

                # 세그먼트 완료
                segment_end = time.monotonic()
                self._finish_ffmpeg_writer(ffmpeg_proc)

                if segment_path.exists() and segment_path.stat().st_size > 0:
                    seg_info = _SegmentInfo(
                        path=segment_path,
                        cam_id=cam_id,
                        start_time=segment_start,
                        end_time=segment_end,
                        duration_sec=segment_end - segment_start,
                    )
                    cam_buf.segments.append(seg_info)
                    logger.debug(
                        f"[{cam_id}] Segment saved: {segment_path.name} "
                        f"({seg_info.duration_sec:.1f}s, {frame_count} frames)"
                    )
                else:
                    logger.warning(
                        f"[{cam_id}] Segment file empty or missing: {segment_path}"
                    )

                cam_buf._ffmpeg_process = None
                cam_buf._current_segment_path = None

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[{cam_id}] Encoding error: {e}")
                await asyncio.sleep(1.0)

    # ------------------------------------------------------------------
    # ffmpeg 프로세스 관리
    # ------------------------------------------------------------------

    def _start_ffmpeg_writer(self, output_path: Path) -> subprocess.Popen:
        """ffmpeg를 파이프 모드로 시작하여 raw BGR 입력을 mp4로 인코딩한다."""
        cmd = [
            "ffmpeg",
            "-y",
            "-f", "rawvideo",
            "-vcodec", "rawvideo",
            "-pix_fmt", "bgr24",
            "-s", f"{self._width}x{self._height}",
            "-r", str(self._fps),
            "-i", "pipe:0",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-tune", "zerolatency",
            "-crf", "23",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            "-an",  # 오디오 없음
            str(output_path),
        ]

        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return proc

    @staticmethod
    def _finish_ffmpeg_writer(proc: subprocess.Popen) -> None:
        """ffmpeg 프로세스를 정상 종료한다."""
        if proc is None:
            return
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def _stop_all_encoders(self) -> None:
        """모든 카메라의 ffmpeg 프로세스를 종료한다."""
        for cam_buf in self._cameras.values():
            if cam_buf._ffmpeg_process is not None:
                self._finish_ffmpeg_writer(cam_buf._ffmpeg_process)
                cam_buf._ffmpeg_process = None

    # ------------------------------------------------------------------
    # 세그먼트 결합
    # ------------------------------------------------------------------

    def _concat_segments(
        self, cam_id: str, segments: list[_SegmentInfo]
    ) -> Path | None:
        """여러 세그먼트를 ffmpeg concat demuxer로 결합한다."""
        output_dir = self._buffer_dir / cam_id / "_concat"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"concat_{int(time.time() * 1000)}.mp4"

        # concat 리스트 파일 작성
        list_path = output_dir / f"_list_{int(time.time() * 1000)}.txt"
        try:
            with open(list_path, "w", encoding="utf-8") as f:
                for seg in segments:
                    # ffmpeg concat demuxer는 절대 경로 또는 상대 경로 사용 가능
                    safe_path = str(seg.path).replace("\\", "/")
                    f.write(f"file '{safe_path}'\n")

            cmd = [
                "ffmpeg",
                "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(list_path),
                "-c", "copy",
                "-movflags", "+faststart",
                str(output_path),
            ]

            result = subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=30,
            )

            if result.returncode != 0:
                logger.error(
                    f"[{cam_id}] Concat failed: {result.stderr.decode(errors='replace')[:200]}"
                )
                return None

            return output_path

        except Exception as e:
            logger.error(f"[{cam_id}] Concat error: {e}")
            return None
        finally:
            # 임시 리스트 파일 정리
            try:
                list_path.unlink(missing_ok=True)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 클린업
    # ------------------------------------------------------------------

    async def _cleanup_loop(self) -> None:
        """오래된 세그먼트를 주기적으로 삭제한다."""
        while self._running:
            try:
                self._cleanup_old_segments()
                await asyncio.sleep(self._cleanup_interval_sec)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Cleanup error: {e}")
                await asyncio.sleep(self._cleanup_interval_sec)

    def _cleanup_old_segments(self) -> None:
        """buffer_sec보다 오래된 세그먼트를 삭제한다."""
        now = time.monotonic()
        cutoff = now - self._buffer_sec

        for cam_buf in self._cameras.values():
            expired = [seg for seg in cam_buf.segments if seg.end_time < cutoff]
            for seg in expired:
                try:
                    seg.path.unlink(missing_ok=True)
                except OSError as e:
                    logger.debug(f"Failed to delete segment {seg.path}: {e}")
                cam_buf.segments.remove(seg)

            if expired:
                logger.debug(
                    f"[{cam_buf.cam_id}] Cleaned {len(expired)} expired segments, "
                    f"{len(cam_buf.segments)} remaining"
                )

        # concat 임시 파일도 정리 (5분 이상 된 것)
        self._cleanup_concat_files()

    def _cleanup_concat_files(self) -> None:
        """결합용 임시 파일을 정리한다."""
        for cam_id in self._cameras:
            concat_dir = self._buffer_dir / cam_id / "_concat"
            if not concat_dir.exists():
                continue
            now_epoch = time.time()
            for f in concat_dir.iterdir():
                try:
                    if now_epoch - f.stat().st_mtime > 300:  # 5분
                        f.unlink(missing_ok=True)
                except Exception:
                    pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _ensure_buffer_dir(self) -> None:
        """버퍼 디렉토리를 생성한다."""
        for cam_id in self._cameras:
            cam_dir = self._buffer_dir / cam_id
            cam_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"Buffer directory ready: {self._buffer_dir}")

    def _new_segment_path(self, cam_id: str) -> Path:
        """새 세그먼트 파일 경로를 생성한다."""
        cam_dir = self._buffer_dir / cam_id
        timestamp_ms = int(time.time() * 1000)
        return cam_dir / f"seg_{timestamp_ms}.mp4"

    @staticmethod
    def _parse_resolution(resolution: str) -> tuple[int, int]:
        """해상도 문자열을 (width, height) 튜플로 변환한다."""
        presets = {
            "720p": (1280, 720),
            "1080p": (1920, 1080),
            "1440p": (2560, 1440),
            "4k": (3840, 2160),
        }
        if resolution.lower() in presets:
            return presets[resolution.lower()]
        # "1920x1080" 형태 파싱 시도
        if "x" in resolution:
            parts = resolution.lower().split("x")
            return int(parts[0]), int(parts[1])
        return 1920, 1080  # 기본값
