"""
BGM 믹싱 모듈 — 이벤트 무드 기반 BGM 자동 선택 + 오디오 믹싱.

이벤트 타입에 따라 무드를 매핑하고, 해당 무드 폴더에서 BGM을 랜덤 선택.
최근 사용된 BGM을 피해 반복을 방지하며, ffmpeg amix로 원본 오디오와 믹싱한다.
"""

from __future__ import annotations

import asyncio
import random
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger


# ──────────────────────────────────────────────
# 이벤트 → 무드 매핑 기본값
# ──────────────────────────────────────────────
DEFAULT_MOOD_MAP: dict[str, str] = {
    "climb": "active",
    "jump": "active",
    "run": "active",
    "interact": "comic",
    "hunt_attempt": "tension",
    "sleep": "healing",
    "walk": "healing",
    "play": "comic",
}

# BGM 파일 확장자
BGM_EXTENSIONS = {".mp3", ".wav", ".ogg", ".m4a", ".aac", ".flac"}


@dataclass
class BGMInfo:
    """선택된 BGM 정보."""
    path: Path
    mood: str
    start_sec: float = 0.0
    duration_sec: float = 0.0


class BGMMixer:
    """이벤트 무드 기반 BGM 자동 선택 + ffmpeg amix 믹싱."""

    def __init__(self, config: dict):
        self.config = config
        bgm_cfg = config.get("bgm", {})

        self.volume_bgm: float = bgm_cfg.get("volume_bgm", 0.15)
        self.volume_original: float = bgm_cfg.get("volume_original", 0.85)
        self.fade_in_sec: float = bgm_cfg.get("fade_in_sec", 1.0)
        self.fade_out_sec: float = bgm_cfg.get("fade_out_sec", 1.5)
        self.random_start: bool = bgm_cfg.get("random_start", True)
        self.avoid_repeat_count: int = bgm_cfg.get("avoid_repeat_count", 3)
        self.base_dir = Path(bgm_cfg.get("base_dir", "bgm"))

        # 무드 매핑 (config에서 오버라이드 가능)
        self.mood_map: dict[str, str] = bgm_cfg.get(
            "mood_map", DEFAULT_MOOD_MAP
        )

        # 최근 사용 BGM 추적 (반복 방지용 deque)
        self._recent_bgms: deque[str] = deque(
            maxlen=self.avoid_repeat_count
        )

        # 무드별 BGM 목록 캐시
        self._bgm_cache: dict[str, list[Path]] = {}

        logger.info(
            f"BGMMixer initialized — "
            f"vol_orig={self.volume_original}, vol_bgm={self.volume_bgm}, "
            f"fade_in={self.fade_in_sec}s, fade_out={self.fade_out_sec}s, "
            f"base_dir={self.base_dir}"
        )

    async def mix(self, clip_path: Path, metadata: dict) -> Path:
        """
        클립에 BGM을 믹싱.

        1) 이벤트 타입 → 무드 결정
        2) 무드 폴더에서 BGM 랜덤 선택 (최근 사용 회피)
        3) 클립 길이 파악 → BGM 랜덤 시작점 결정
        4) ffmpeg amix로 원본 + BGM 믹싱

        Parameters
        ----------
        clip_path : Path
            입력 클립 경로.
        metadata : dict
            이벤트 메타데이터 (event_type 포함).

        Returns
        -------
        Path
            BGM 믹싱된 클립 경로 (_bgm 접미사).
        """
        output_path = clip_path.with_stem(f"{clip_path.stem}_bgm")
        event_type: str = metadata.get("event_type", "play")

        logger.info(
            f"[BGMMixer] Mixing BGM: {clip_path.name} (event={event_type})"
        )

        try:
            # 1. 무드 결정
            mood = self.mood_map.get(event_type, "healing")

            # 2. BGM 선택
            bgm_info = self._select_bgm(mood)
            if bgm_info is None:
                logger.warning(
                    f"[BGMMixer] No BGM found for mood={mood} — "
                    f"copying original"
                )
                await _copy_file(clip_path, output_path)
                return output_path

            # 3. 클립 길이 파악
            clip_duration = await self._get_duration(clip_path)
            bgm_duration = await self._get_duration(bgm_info.path)

            # 4. BGM 랜덤 시작점 결정
            if self.random_start and bgm_duration > clip_duration + 5:
                max_start = bgm_duration - clip_duration - 2
                bgm_info.start_sec = random.uniform(0, max(0, max_start))
            else:
                bgm_info.start_sec = 0.0

            bgm_info.duration_sec = clip_duration

            logger.info(
                f"[BGMMixer] Selected: {bgm_info.path.name} "
                f"(mood={mood}, start={bgm_info.start_sec:.1f}s, "
                f"clip_dur={clip_duration:.1f}s)"
            )

            # 5. ffmpeg 믹싱
            await self._apply_mix(clip_path, bgm_info, output_path)

            # 6. 최근 사용 기록
            self._recent_bgms.append(bgm_info.path.name)

            logger.info(f"[BGMMixer] Done: {output_path.name}")
            return output_path

        except Exception as e:
            logger.error(f"[BGMMixer] Mix failed: {e}")
            # 폴백: 원본 복사
            logger.warning("[BGMMixer] Falling back to original audio")
            await _copy_file(clip_path, output_path)
            return output_path

    def _select_bgm(self, mood: str) -> Optional[BGMInfo]:
        """
        무드 폴더에서 BGM 랜덤 선택 (최근 사용 회피).

        BGM 디렉토리 구조: {base_dir}/{mood}/*.mp3
        예: bgm/active/, bgm/healing/, bgm/comic/, bgm/tension/
        """
        # 캐시에서 해당 무드의 BGM 목록 조회
        if mood not in self._bgm_cache:
            mood_dir = self.base_dir / mood
            if mood_dir.is_dir():
                files = [
                    f for f in mood_dir.iterdir()
                    if f.is_file() and f.suffix.lower() in BGM_EXTENSIONS
                ]
                self._bgm_cache[mood] = sorted(files)
            else:
                logger.warning(
                    f"[BGMMixer] BGM mood dir not found: {mood_dir}"
                )
                self._bgm_cache[mood] = []

        candidates = self._bgm_cache[mood]
        if not candidates:
            return None

        # 최근 사용 BGM 제외
        available = [
            f for f in candidates
            if f.name not in self._recent_bgms
        ]

        # 모두 최근 사용이면 전체에서 선택
        if not available:
            available = candidates

        selected = random.choice(available)
        return BGMInfo(path=selected, mood=mood)

    async def _get_duration(self, file_path: Path) -> float:
        """ffprobe로 미디어 파일 길이(초) 조회."""
        cmd = [
            "ffprobe",
            "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(file_path),
        ]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            logger.warning(
                f"[BGMMixer] ffprobe failed for {file_path.name}, "
                f"using default 20s"
            )
            return 20.0

        try:
            return float(stdout.decode().strip())
        except ValueError:
            return 20.0

    async def _apply_mix(
        self,
        clip_path: Path,
        bgm_info: BGMInfo,
        output_path: Path,
    ):
        """
        ffmpeg로 원본 오디오 + BGM 믹싱.

        - 원본 볼륨: volume_original (0.85)
        - BGM 볼륨: volume_bgm (0.15)
        - BGM fade in/out 적용
        - BGM은 랜덤 시작점에서 클립 길이만큼만 사용
        """
        clip_duration = bgm_info.duration_sec
        fade_out_start = max(0, clip_duration - self.fade_out_sec)

        # BGM 오디오 필터:
        # 1) 시작점 건너뛰기 (ss)
        # 2) 클립 길이만큼 자르기
        # 3) 볼륨 조절
        # 4) 페이드 인/아웃
        bgm_filter = (
            f"[1:a]atrim=start={bgm_info.start_sec:.2f}:"
            f"end={bgm_info.start_sec + clip_duration:.2f},"
            f"asetpts=PTS-STARTPTS,"
            f"volume={self.volume_bgm},"
            f"afade=t=in:st=0:d={self.fade_in_sec},"
            f"afade=t=out:st={fade_out_start:.2f}:d={self.fade_out_sec}"
            f"[bgm]"
        )

        # 원본 오디오 볼륨 조절
        orig_filter = f"[0:a]volume={self.volume_original}[orig]"

        # 믹싱
        mix_filter = (
            f"{orig_filter};{bgm_filter};"
            f"[orig][bgm]amix=inputs=2:duration=first:dropout_transition=2[out]"
        )

        cmd = [
            "ffmpeg", "-y",
            "-i", str(clip_path),
            "-i", str(bgm_info.path),
            "-filter_complex", mix_filter,
            "-map", "0:v",
            "-map", "[out]",
            "-c:v", "copy",
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            str(output_path),
        ]

        logger.debug(
            f"[BGMMixer] ffmpeg mix: "
            f"orig_vol={self.volume_original}, bgm_vol={self.volume_bgm}, "
            f"bgm_start={bgm_info.start_sec:.1f}s"
        )

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            error_msg = stderr.decode("utf-8", errors="replace")[-500:]
            raise RuntimeError(
                f"ffmpeg BGM mix failed (rc={proc.returncode}): {error_msg}"
            )

    def clear_cache(self):
        """BGM 목록 캐시 초기화 (새 BGM 추가 시 호출)."""
        self._bgm_cache.clear()
        logger.info("[BGMMixer] BGM cache cleared")

    def get_recent_bgms(self) -> list[str]:
        """최근 사용된 BGM 파일명 리스트 반환 (디버그용)."""
        return list(self._recent_bgms)


async def _copy_file(src: Path, dst: Path):
    """asyncio-safe 파일 복사 (폴백용)."""
    import shutil
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, shutil.copy2, str(src), str(dst))
