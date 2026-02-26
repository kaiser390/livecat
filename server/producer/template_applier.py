"""
템플릿 적용 모듈 — 인트로/아웃로/오버레이를 숏폼 클립에 합성.

플랫폼별(youtube shorts, tiktok) 아웃로 문구가 다르고,
이벤트 텍스트 + 고양이 이름 + 워터마크를 drawtext 필터로 오버레이한다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger


@dataclass
class OverlaySpec:
    """drawtext 오버레이 사양."""
    text: str
    position: str              # "top_center", "bottom_left", "bottom_right"
    fontsize: int = 48
    fontcolor: str = "white"
    borderw: int = 3
    bordercolor: str = "black"
    font: str = "NanumSquareRoundEB"
    fade_in: float = 0.3
    fade_out: float = 0.3


# ──────────────────────────────────────────────
# 이벤트 타입 → 한글 표시 텍스트
# ──────────────────────────────────────────────
EVENT_DISPLAY_TEXT: dict[str, str] = {
    "climb": "등반 챌린지!",
    "jump": "점프!",
    "run": "전력 질주!",
    "interact": "함께 노는 중",
    "hunt_attempt": "사냥 본능!",
    "sleep": "꿀잠 타임",
    "walk": "산책 중",
    "play": "놀이 시간",
}

# 플랫폼별 아웃로 문구
OUTRO_TEXT: dict[str, str] = {
    "youtube": "구독과 좋아요 부탁해요!",
    "shorts": "구독과 좋아요 부탁해요!",
    "tiktok": "팔로우하면 매일 만나요!",
}


class TemplateApplier:
    """인트로/아웃로 연결 + 텍스트 오버레이 적용."""

    def __init__(self, config: dict):
        self.config = config
        sf_cfg = config.get("shortform", {})

        self.intro_duration: float = sf_cfg.get("intro_duration_sec", 1.5)
        self.outro_duration: float = sf_cfg.get("outro_duration_sec", 2.0)
        self.output_resolution: list[int] = sf_cfg.get(
            "output_resolution", [1080, 1920]
        )

        # 고양이 프로필
        self.cats: dict = config.get("cats", {})

        # 출력 기본 디렉토리
        self.base_output_dir = Path(
            config.get("clip", {}).get("output_dir", "clips")
        )

        # 썸네일 폰트
        self.font: str = config.get("thumbnail", {}).get(
            "font", "NanumSquareRoundEB.ttf"
        )

        logger.info(
            f"TemplateApplier initialized — "
            f"intro={self.intro_duration}s, outro={self.outro_duration}s, "
            f"font={self.font}"
        )

    async def apply(
        self,
        clip_path: Path,
        metadata: dict,
        platform: str = "shorts",
    ) -> Path:
        """
        인트로 + 메인 클립 + 아웃로를 연결하고 텍스트 오버레이 적용.

        Parameters
        ----------
        clip_path : Path
            메인 클립 경로 (세로, BGM 믹싱 완료 상태).
        metadata : dict
            이벤트 메타데이터:
            - event_type: str
            - cat_id: str (nana / toto)
            - event_id: str
            - timestamp: str (ISO format)
        platform : str
            대상 플랫폼 ("shorts" / "tiktok").

        Returns
        -------
        Path
            최종 출력 경로: output/{platform}/{date}/{event_id}_{platform}.mp4
        """
        event_type: str = metadata.get("event_type", "play")
        cat_id: str = metadata.get("cat_id", "nana")
        event_id: str = metadata.get("event_id", "unknown")
        timestamp_str: str = metadata.get("timestamp", "")

        # 날짜 파싱
        try:
            dt = datetime.fromisoformat(timestamp_str)
        except (ValueError, TypeError):
            dt = datetime.now()
        date_str = dt.strftime("%Y-%m-%d")

        # 출력 디렉토리 구성
        output_dir = self.base_output_dir / "output" / platform / date_str
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path = output_dir / f"{event_id}_{platform}.mp4"

        logger.info(
            f"[TemplateApplier] Applying template: "
            f"{clip_path.name} -> {output_path} "
            f"(platform={platform})"
        )

        try:
            # 1. 인트로 영상 생성 (컬러 배경 + 텍스트)
            intro_path = clip_path.with_stem(f"{clip_path.stem}_intro_tmp")
            await self._generate_intro(intro_path, metadata)

            # 2. 아웃로 영상 생성
            outro_path = clip_path.with_stem(f"{clip_path.stem}_outro_tmp")
            await self._generate_outro(outro_path, platform, metadata)

            # 3. 메인 클립에 오버레이 적용
            overlaid_path = clip_path.with_stem(f"{clip_path.stem}_overlaid_tmp")
            await self._apply_overlays(clip_path, overlaid_path, metadata)

            # 4. 인트로 + 메인(오버레이) + 아웃로 연결
            await self._concatenate(
                intro_path, overlaid_path, outro_path, output_path
            )

            # 5. 임시 파일 정리
            for tmp in [intro_path, outro_path, overlaid_path]:
                if tmp.exists():
                    tmp.unlink()

            logger.info(f"[TemplateApplier] Done: {output_path}")
            return output_path

        except Exception as e:
            logger.error(f"[TemplateApplier] Failed: {e}")
            raise

    async def _generate_intro(
        self, output_path: Path, metadata: dict
    ):
        """인트로 영상 생성: 단색 배경 + 고양이 이름/이벤트 텍스트."""
        cat_id = metadata.get("cat_id", "nana")
        cat_info = self.cats.get(cat_id, {})
        cat_name = cat_info.get("name_ko", "고양이")
        cat_icon = cat_info.get("icon", "")
        event_type = metadata.get("event_type", "play")
        event_text = EVENT_DISPLAY_TEXT.get(event_type, "")

        display_text = f"{cat_icon} {cat_name}"
        sub_text = event_text

        out_w, out_h = self.output_resolution

        # ffmpeg: 단색 배경 + drawtext (메인 + 서브)
        # 폰트 이스케이프 처리
        escaped_display = _escape_ffmpeg_text(display_text)
        escaped_sub = _escape_ffmpeg_text(sub_text)

        drawtext_main = (
            f"drawtext=text='{escaped_display}':"
            f"fontfile='{self.font}':"
            f"fontsize=72:fontcolor=white:borderw=4:bordercolor=black:"
            f"x=(w-text_w)/2:y=(h-text_h)/2-40:"
            f"enable='between(t,0,{self.intro_duration})'"
        )

        drawtext_sub = (
            f"drawtext=text='{escaped_sub}':"
            f"fontfile='{self.font}':"
            f"fontsize=48:fontcolor=#FFD700:borderw=3:bordercolor=black:"
            f"x=(w-text_w)/2:y=(h/2)+40:"
            f"enable='between(t,0,{self.intro_duration})'"
        )

        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", (
                f"color=c=#1a1a2e:size={out_w}x{out_h}:"
                f"duration={self.intro_duration}:rate=30"
            ),
            "-f", "lavfi",
            "-i", f"anullsrc=r=44100:cl=stereo:d={self.intro_duration}",
            "-vf", f"{drawtext_main},{drawtext_sub}",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest",
            str(output_path),
        ]

        await _run_ffmpeg(cmd, "intro generation")

    async def _generate_outro(
        self, output_path: Path, platform: str, metadata: dict
    ):
        """아웃로 영상 생성: CTA 텍스트 + 페이드 아웃."""
        cta_text = OUTRO_TEXT.get(platform, OUTRO_TEXT["shorts"])
        escaped_cta = _escape_ffmpeg_text(cta_text)

        out_w, out_h = self.output_resolution

        drawtext_cta = (
            f"drawtext=text='{escaped_cta}':"
            f"fontfile='{self.font}':"
            f"fontsize=56:fontcolor=white:borderw=4:bordercolor=black:"
            f"x=(w-text_w)/2:y=(h-text_h)/2,"
            f"fade=t=out:st={self.outro_duration - 0.5}:d=0.5"
        )

        cmd = [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", (
                f"color=c=#0f0f23:size={out_w}x{out_h}:"
                f"duration={self.outro_duration}:rate=30"
            ),
            "-f", "lavfi",
            "-i", f"anullsrc=r=44100:cl=stereo:d={self.outro_duration}",
            "-vf", drawtext_cta,
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest",
            str(output_path),
        ]

        await _run_ffmpeg(cmd, "outro generation")

    async def _apply_overlays(
        self,
        input_path: Path,
        output_path: Path,
        metadata: dict,
    ):
        """메인 클립에 이벤트 텍스트, 고양이 이름, 워터마크 오버레이."""
        event_type = metadata.get("event_type", "play")
        cat_id = metadata.get("cat_id", "nana")
        cat_info = self.cats.get(cat_id, {})
        cat_name = cat_info.get("name_ko", "고양이")
        cat_icon = cat_info.get("icon", "")
        event_text = EVENT_DISPLAY_TEXT.get(event_type, "")

        overlays = [
            # 이벤트 텍스트 (상단 중앙) — 처음 3초만 표시
            OverlaySpec(
                text=event_text,
                position="top_center",
                fontsize=52,
                fontcolor="white",
                borderw=4,
                bordercolor="black",
                fade_in=0.3,
                fade_out=0.5,
            ),
            # 고양이 이름 (좌측 하단) — 항상 표시
            OverlaySpec(
                text=f"{cat_icon} {cat_name}",
                position="bottom_left",
                fontsize=40,
                fontcolor="#FFFFFF",
                borderw=3,
                bordercolor="#333333",
            ),
            # 워터마크 (우측 하단) — 항상 표시
            OverlaySpec(
                text="LiveCat",
                position="bottom_right",
                fontsize=28,
                fontcolor="#AAAAAA",
                borderw=2,
                bordercolor="#333333",
            ),
        ]

        # drawtext 필터 체인 생성
        filter_parts: list[str] = []

        for i, ovl in enumerate(overlays):
            x_expr, y_expr = _position_to_xy(ovl.position)
            escaped_text = _escape_ffmpeg_text(ovl.text)

            # 이벤트 텍스트는 처음 3초만 페이드로 표시
            if ovl.position == "top_center":
                enable = (
                    f"alpha='if(lt(t,{ovl.fade_in}),"
                    f"t/{ovl.fade_in},"
                    f"if(gt(t,3-{ovl.fade_out}),"
                    f"(3-t)/{ovl.fade_out},1))'"
                )
                dt = (
                    f"drawtext=text='{escaped_text}':"
                    f"fontfile='{self.font}':"
                    f"fontsize={ovl.fontsize}:"
                    f"fontcolor={ovl.fontcolor}:"
                    f"borderw={ovl.borderw}:bordercolor={ovl.bordercolor}:"
                    f"x={x_expr}:y={y_expr}:"
                    f"enable='lte(t,3)'"
                )
            else:
                dt = (
                    f"drawtext=text='{escaped_text}':"
                    f"fontfile='{self.font}':"
                    f"fontsize={ovl.fontsize}:"
                    f"fontcolor={ovl.fontcolor}:"
                    f"borderw={ovl.borderw}:bordercolor={ovl.bordercolor}:"
                    f"x={x_expr}:y={y_expr}"
                )

            filter_parts.append(dt)

        filter_chain = ",".join(filter_parts)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-vf", filter_chain,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ]

        await _run_ffmpeg(cmd, "overlay application")

    async def _concatenate(
        self,
        intro_path: Path,
        main_path: Path,
        outro_path: Path,
        output_path: Path,
    ):
        """인트로 + 메인 + 아웃로를 concat demuxer로 연결."""
        # concat 목록 파일 생성
        concat_list_path = output_path.with_suffix(".txt")

        try:
            lines = [
                f"file '{intro_path.as_posix()}'",
                f"file '{main_path.as_posix()}'",
                f"file '{outro_path.as_posix()}'",
            ]
            concat_list_path.write_text(
                "\n".join(lines), encoding="utf-8"
            )

            cmd = [
                "ffmpeg", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_list_path),
                "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                str(output_path),
            ]

            await _run_ffmpeg(cmd, "concatenation")

        finally:
            if concat_list_path.exists():
                concat_list_path.unlink()


# ──────────────────────────────────────────────
# 유틸리티 함수
# ──────────────────────────────────────────────

def _escape_ffmpeg_text(text: str) -> str:
    """ffmpeg drawtext 텍스트 이스케이프."""
    # ffmpeg drawtext에서 특수문자 이스케이프
    text = text.replace("\\", "\\\\")
    text = text.replace("'", "'\\''")
    text = text.replace(":", "\\:")
    text = text.replace("%", "%%")
    return text


def _position_to_xy(position: str) -> tuple[str, str]:
    """위치 문자열을 ffmpeg drawtext x/y 표현식으로 변환."""
    margin = 40
    positions: dict[str, tuple[str, str]] = {
        "top_center": ("(w-text_w)/2", f"{margin}"),
        "top_left": (f"{margin}", f"{margin}"),
        "top_right": (f"w-text_w-{margin}", f"{margin}"),
        "bottom_left": (f"{margin}", f"h-text_h-{margin}"),
        "bottom_right": (f"w-text_w-{margin}", f"h-text_h-{margin}"),
        "bottom_center": ("(w-text_w)/2", f"h-text_h-{margin}"),
        "center": ("(w-text_w)/2", "(h-text_h)/2"),
    }
    return positions.get(position, positions["top_center"])


async def _run_ffmpeg(cmd: list[str], description: str):
    """ffmpeg 명령 실행 + 에러 처리."""
    logger.debug(f"[ffmpeg] {description}: {' '.join(cmd[:6])}...")

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        error_msg = stderr.decode("utf-8", errors="replace")[-500:]
        raise RuntimeError(
            f"ffmpeg {description} failed (rc={proc.returncode}): {error_msg}"
        )

    logger.debug(f"[ffmpeg] {description} done")
