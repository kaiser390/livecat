"""
속도 조절 모듈 — 이벤트 타입에 따라 슬로모/타임랩스 적용.

- jump: 0.5x 슬로모 (핵심 구간)
- run: 1.0x (변경 없음)
- walk/move: 2.0x 타임랩스
- sleep: 4.0x 타임랩스

ffmpeg setpts(영상)와 atempo(오디오) 필터를 조합한다.
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from loguru import logger


@dataclass
class SpeedProfile:
    """속도 조절 프로필."""
    factor: float           # 재생 속도 배수 (0.5 = 슬로모, 2.0 = 배속)
    description: str
    preserve_audio: bool = True  # 오디오 유지 여부


# ──────────────────────────────────────────────
# 이벤트 → 속도 프로필
# ──────────────────────────────────────────────
DEFAULT_SPEED_PROFILES: dict[str, SpeedProfile] = {
    "jump": SpeedProfile(
        factor=0.5,
        description="슬로모 — 점프 하이라이트",
        preserve_audio=True,
    ),
    "run": SpeedProfile(
        factor=1.0,
        description="원속 — 전력 질주",
        preserve_audio=True,
    ),
    "climb": SpeedProfile(
        factor=1.0,
        description="원속 — 등반",
        preserve_audio=True,
    ),
    "interact": SpeedProfile(
        factor=1.0,
        description="원속 — 상호작용",
        preserve_audio=True,
    ),
    "hunt_attempt": SpeedProfile(
        factor=0.5,
        description="슬로모 — 사냥 하이라이트",
        preserve_audio=True,
    ),
    "walk": SpeedProfile(
        factor=2.0,
        description="배속 — 이동",
        preserve_audio=True,
    ),
    "move": SpeedProfile(
        factor=2.0,
        description="배속 — 이동",
        preserve_audio=True,
    ),
    "sleep": SpeedProfile(
        factor=4.0,
        description="4배속 타임랩스 — 수면",
        preserve_audio=False,  # 4배속에서 오디오는 의미 없음
    ),
    "play": SpeedProfile(
        factor=1.0,
        description="원속 — 놀이",
        preserve_audio=True,
    ),
}


class SpeedAdjuster:
    """이벤트 타입 기반 속도 조절 (슬로모 / 타임랩스)."""

    def __init__(self, config: dict):
        self.config = config
        sf_cfg = config.get("shortform", {})
        speed_cfg = sf_cfg.get("speed", {})

        # config에서 오버라이드 가능한 속도 팩터
        self.slowmo_factor: float = speed_cfg.get("slowmo_factor", 0.5)
        self.timelapse_factor: float = speed_cfg.get("timelapse_factor", 2.0)
        self.sleep_timelapse_factor: float = speed_cfg.get(
            "sleep_timelapse_factor", 4.0
        )

        # config 값으로 기본 프로필 업데이트
        self.profiles = dict(DEFAULT_SPEED_PROFILES)
        self.profiles["jump"] = SpeedProfile(
            factor=self.slowmo_factor,
            description="슬로모",
            preserve_audio=True,
        )
        self.profiles["hunt_attempt"] = SpeedProfile(
            factor=self.slowmo_factor,
            description="슬로모 — 사냥",
            preserve_audio=True,
        )
        self.profiles["walk"] = SpeedProfile(
            factor=self.timelapse_factor,
            description="배속",
            preserve_audio=True,
        )
        self.profiles["move"] = SpeedProfile(
            factor=self.timelapse_factor,
            description="배속",
            preserve_audio=True,
        )
        self.profiles["sleep"] = SpeedProfile(
            factor=self.sleep_timelapse_factor,
            description="타임랩스",
            preserve_audio=False,
        )

        logger.info(
            f"SpeedAdjuster initialized — "
            f"slowmo={self.slowmo_factor}x, "
            f"timelapse={self.timelapse_factor}x, "
            f"sleep={self.sleep_timelapse_factor}x"
        )

    async def adjust(self, clip_path: Path, metadata: dict) -> Path:
        """
        이벤트 타입에 따라 속도 조절 적용.

        Parameters
        ----------
        clip_path : Path
            입력 클립 경로.
        metadata : dict
            이벤트 메타데이터 (event_type 포함).

        Returns
        -------
        Path
            속도 조절된 클립 경로 (_speed 접미사).
            1.0x인 경우 원본 복사만 수행.
        """
        output_path = clip_path.with_stem(f"{clip_path.stem}_speed")
        event_type: str = metadata.get("event_type", "play")

        # 프로필 결정
        profile = self.profiles.get(
            event_type,
            SpeedProfile(factor=1.0, description="기본"),
        )

        logger.info(
            f"[SpeedAdjuster] {clip_path.name}: "
            f"event={event_type}, speed={profile.factor}x "
            f"({profile.description})"
        )

        # 1.0x — 변경 불필요
        if abs(profile.factor - 1.0) < 0.01:
            logger.debug(
                f"[SpeedAdjuster] No speed change needed, copying original"
            )
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, shutil.copy2, str(clip_path), str(output_path)
            )
            return output_path

        try:
            await self._apply_speed(clip_path, output_path, profile)
            logger.info(
                f"[SpeedAdjuster] Done: {output_path.name} "
                f"({profile.factor}x)"
            )
            return output_path

        except Exception as e:
            logger.error(f"[SpeedAdjuster] Speed adjust failed: {e}")
            # 폴백: 원본 복사
            logger.warning("[SpeedAdjuster] Falling back to original speed")
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, shutil.copy2, str(clip_path), str(output_path)
            )
            return output_path

    async def _apply_speed(
        self,
        input_path: Path,
        output_path: Path,
        profile: SpeedProfile,
    ):
        """
        ffmpeg setpts + atempo로 속도 조절.

        - 영상: setpts=PTS*{1/factor} (0.5x → setpts=PTS*2.0)
        - 오디오: atempo 체인 (범위 제한: 0.5~2.0, 초과 시 체이닝)

        atempo는 0.5~2.0 범위만 지원하므로,
        4.0x의 경우 atempo=2.0,atempo=2.0으로 체이닝한다.
        """
        factor = profile.factor

        # 영상 필터: setpts=PTS*(1/factor)
        pts_factor = 1.0 / factor
        video_filter = f"setpts={pts_factor:.4f}*PTS"

        # 오디오 필터 구성
        if not profile.preserve_audio:
            # 오디오 제거 (sleep 등)
            cmd = [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-vf", video_filter,
                "-an",  # 오디오 제거
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "20",
                "-movflags", "+faststart",
                str(output_path),
            ]
        else:
            # 오디오 속도 조절 (atempo 체이닝)
            atempo_chain = self._build_atempo_chain(factor)

            cmd = [
                "ffmpeg", "-y",
                "-i", str(input_path),
                "-vf", video_filter,
                "-af", atempo_chain,
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "20",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                str(output_path),
            ]

        logger.debug(
            f"[SpeedAdjuster] ffmpeg: factor={factor}, "
            f"pts={pts_factor:.4f}, "
            f"audio={'preserved' if profile.preserve_audio else 'removed'}"
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
                f"ffmpeg speed adjust failed (rc={proc.returncode}): "
                f"{error_msg}"
            )

    @staticmethod
    def _build_atempo_chain(factor: float) -> str:
        """
        atempo 필터 체인 생성.

        atempo는 0.5~2.0 범위만 허용.
        - 0.5x → atempo=0.5
        - 2.0x → atempo=2.0
        - 4.0x → atempo=2.0,atempo=2.0
        - 0.25x → atempo=0.5,atempo=0.5

        Parameters
        ----------
        factor : float
            재생 속도 배수.

        Returns
        -------
        str
            ffmpeg atempo 필터 체인 문자열.
        """
        if abs(factor - 1.0) < 0.01:
            return "anull"

        parts: list[str] = []
        remaining = factor

        # 배속 (factor > 1.0)
        if remaining > 1.0:
            while remaining > 1.01:
                if remaining > 2.0:
                    parts.append("atempo=2.0")
                    remaining /= 2.0
                else:
                    parts.append(f"atempo={remaining:.4f}")
                    remaining = 1.0
        # 슬로모 (factor < 1.0)
        else:
            while remaining < 0.99:
                if remaining < 0.5:
                    parts.append("atempo=0.5")
                    remaining /= 0.5
                else:
                    parts.append(f"atempo={remaining:.4f}")
                    remaining = 1.0

        if not parts:
            return "anull"

        return ",".join(parts)

    def get_profile(self, event_type: str) -> SpeedProfile:
        """이벤트 타입의 속도 프로필 조회 (디버그/대시보드용)."""
        return self.profiles.get(
            event_type,
            SpeedProfile(factor=1.0, description="기본"),
        )
