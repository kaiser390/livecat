"""
자막 생성 모듈 — 이벤트 기반 한글 자막 + 이모지 오버레이.

음성 인식(STT) 없이, 이벤트 타입별 사전 정의된 자막 템플릿에서
랜덤 선택하여 다양성을 확보한다.
ffmpeg drawtext 필터로 페이드 애니메이션과 함께 적용.
"""

from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from loguru import logger


# ──────────────────────────────────────────────
# 이벤트별 자막 템플릿 (한글 + 이모지)
# ──────────────────────────────────────────────
SUBTITLE_TEMPLATES: dict[str, list[str]] = {
    "climb": [
        "🧗 올라간다 올라가!",
        "🏔️ 정상을 향해!",
        "🐱 등반 본능 발동!",
        "⬆️ 높이높이 더 높이~",
        "🧗 클라이밍 마스터!",
        "🐾 어디까지 올라갈 거야?",
        "🏆 산악 고양이 등장!",
    ],
    "jump": [
        "🦘 점프!",
        "✨ 나는 고양이다 날아라!",
        "🐱 슈퍼 점프!",
        "🚀 이륙!",
        "💫 엄청난 점프력!",
        "🎯 착지 성공!",
        "🐾 점프의 달인!",
        "🌟 하늘을 향해!",
    ],
    "run": [
        "💨 전속력!",
        "🏃 달린다 달려!",
        "⚡ 고양이 스프린트!",
        "🐱 폭주 모드 ON!",
        "💨 빠르다 빨라~",
        "🏎️ 터보 모드!",
        "⚡ 번개처럼!",
    ],
    "interact": [
        "💕 같이 놀자!",
        "🐱🐱 우리 사이 좋지?",
        "❤️ 친구야~",
        "🤝 함께하는 시간",
        "💛 둘이서 함께!",
        "😻 베프 인증!",
        "🐾🐾 투샷!",
        "💕 케미 폭발!",
    ],
    "hunt_attempt": [
        "🎯 사냥 본능!",
        "🐱 타겟 포착!",
        "👀 눈빛이 달라졌다...",
        "🔍 발견! 추적 개시!",
        "⚡ 사냥꾼의 본능!",
        "🐾 살금살금...",
        "👁️ 집중!",
    ],
    "sleep": [
        "😴 꿀잠 타임~",
        "💤 스르르...",
        "🌙 잘 자~",
        "😪 졸려졸려...",
        "🛌 낮잠의 고수",
        "💤 코~ 자는 중",
        "😴 꿈나라로~",
        "🌙 방해하지 마세요",
    ],
    "walk": [
        "🚶 산책 중~",
        "🐾 여유로운 발걸음",
        "🌿 느긋느긋",
        "🐱 탐험 중!",
        "🐾 어디로 갈까?",
        "🚶 여유 만끽 중",
    ],
    "play": [
        "🎾 놀이 시간!",
        "🐱 신난다!",
        "✨ 장난감 발견!",
        "🎮 놀이 모드 ON!",
        "🐾 놀자놀자!",
        "🎉 즐거운 시간~",
        "💫 재밌다!",
    ],
}

# 고양이별 개인화 자막 접미사
CAT_PERSONALITY: dict[str, list[str]] = {
    "nana": [
        " 나나의 일상",
        " by 나나",
        "",  # 접미사 없음 (다양성)
        "",
    ],
    "toto": [
        " 토토의 일상",
        " by 토토",
        "",
        "",
    ],
}


@dataclass
class SubtitleEntry:
    """단일 자막 항목."""
    text: str
    start_sec: float
    end_sec: float
    position: str = "bottom_center"  # 화면 내 위치
    fontsize: int = 52
    fontcolor: str = "white"
    borderw: int = 4
    bordercolor: str = "black"
    fade_in_sec: float = 0.3
    fade_out_sec: float = 0.3


class SubtitleGenerator:
    """이벤트 기반 한글 자막 생성기."""

    def __init__(self, config: dict):
        self.config = config

        # 고양이 프로필
        self.cats: dict = config.get("cats", {})

        # 썸네일 폰트 공유
        self.font: str = config.get("thumbnail", {}).get(
            "font", "NanumSquareRoundEB.ttf"
        )

        # 자막 템플릿 (config에서 확장 가능)
        self.templates: dict[str, list[str]] = dict(SUBTITLE_TEMPLATES)

        logger.info(
            f"SubtitleGenerator initialized — "
            f"{sum(len(v) for v in self.templates.values())} templates, "
            f"font={self.font}"
        )

    async def generate(self, clip_path: Path, metadata: dict) -> Path:
        """
        클립에 이벤트 기반 자막 오버레이.

        1) 이벤트 타입에서 자막 템플릿 랜덤 선택
        2) 고양이 이름 기반 개인화
        3) ffmpeg drawtext 페이드 애니메이션 적용

        Parameters
        ----------
        clip_path : Path
            입력 클립 경로.
        metadata : dict
            이벤트 메타데이터 (event_type, cat_id 포함).

        Returns
        -------
        Path
            자막이 적용된 클립 경로 (_sub 접미사).
        """
        output_path = clip_path.with_stem(f"{clip_path.stem}_sub")
        event_type: str = metadata.get("event_type", "play")
        cat_id: str = metadata.get("cat_id", "nana")

        logger.info(
            f"[SubtitleGenerator] Generating subtitles: "
            f"{clip_path.name} (event={event_type}, cat={cat_id})"
        )

        try:
            # 1. 클립 길이 파악
            clip_duration = await self._get_duration(clip_path)

            # 2. 자막 항목 생성
            entries = self._create_subtitle_entries(
                event_type, cat_id, clip_duration
            )

            if not entries:
                logger.warning(
                    "[SubtitleGenerator] No subtitle entries — "
                    "copying original"
                )
                import shutil
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None, shutil.copy2, str(clip_path), str(output_path)
                )
                return output_path

            # 3. ffmpeg drawtext 적용
            await self._apply_subtitles(clip_path, output_path, entries)

            logger.info(
                f"[SubtitleGenerator] Done: {output_path.name} "
                f"({len(entries)} subtitles)"
            )
            return output_path

        except Exception as e:
            logger.error(f"[SubtitleGenerator] Failed: {e}")
            # 폴백: 원본 복사
            import shutil
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None, shutil.copy2, str(clip_path), str(output_path)
            )
            return output_path

    def _create_subtitle_entries(
        self,
        event_type: str,
        cat_id: str,
        clip_duration: float,
    ) -> list[SubtitleEntry]:
        """
        이벤트 타입과 클립 길이에 맞는 자막 항목들 생성.

        전략:
        - 메인 자막: 클립 초반 (0.5s ~ 3.5s)에 이벤트 템플릿
        - 서브 자막: 클립 중반 (40%~70% 지점)에 리액션/감탄사
        - 아웃로 자막: 클립 종료 직전 고양이 이름
        """
        entries: list[SubtitleEntry] = []

        # --- 메인 자막 (이벤트 텍스트) ---
        templates = self.templates.get(event_type, self.templates.get("play", []))
        if templates:
            main_text = random.choice(templates)

            # 고양이 개인화 접미사
            cat_suffixes = CAT_PERSONALITY.get(cat_id, [""])
            suffix = random.choice(cat_suffixes)
            if suffix:
                main_text = main_text + suffix

            main_start = 0.5
            main_end = min(3.5, clip_duration - 0.5)

            if main_end > main_start:
                entries.append(SubtitleEntry(
                    text=main_text,
                    start_sec=main_start,
                    end_sec=main_end,
                    position="bottom_center",
                    fontsize=52,
                    fontcolor="white",
                    borderw=4,
                    bordercolor="black",
                    fade_in_sec=0.3,
                    fade_out_sec=0.3,
                ))

        # --- 서브 자막 (중반 리액션) ---
        if clip_duration > 6.0:
            reaction_texts = _get_reaction_texts(event_type)
            if reaction_texts:
                reaction_text = random.choice(reaction_texts)
                react_start = clip_duration * 0.4
                react_end = min(react_start + 2.5, clip_duration - 2.0)

                if react_end > react_start:
                    entries.append(SubtitleEntry(
                        text=reaction_text,
                        start_sec=react_start,
                        end_sec=react_end,
                        position="bottom_center",
                        fontsize=44,
                        fontcolor="#FFD700",
                        borderw=3,
                        bordercolor="black",
                        fade_in_sec=0.2,
                        fade_out_sec=0.3,
                    ))

        # --- 아웃로 자막 (고양이 이름) ---
        if clip_duration > 4.0:
            cat_info = self.cats.get(cat_id, {})
            cat_name = cat_info.get("name_ko", "")
            cat_icon = cat_info.get("icon", "")

            if cat_name:
                outro_text = f"{cat_icon} {cat_name}의 하루"
                outro_start = max(clip_duration - 2.5, 3.0)
                outro_end = clip_duration - 0.3

                if outro_end > outro_start:
                    entries.append(SubtitleEntry(
                        text=outro_text,
                        start_sec=outro_start,
                        end_sec=outro_end,
                        position="top_center",
                        fontsize=40,
                        fontcolor="#FFFFFF",
                        borderw=3,
                        bordercolor="#444444",
                        fade_in_sec=0.4,
                        fade_out_sec=0.5,
                    ))

        return entries

    async def _apply_subtitles(
        self,
        input_path: Path,
        output_path: Path,
        entries: list[SubtitleEntry],
    ):
        """ffmpeg drawtext 필터로 자막 오버레이 + 페이드 애니메이션."""
        filter_parts: list[str] = []

        for entry in entries:
            x_expr, y_expr = _position_to_xy(entry.position)
            escaped_text = _escape_ffmpeg_text(entry.text)

            # 페이드 알파 표현식:
            # - fade_in: t < start+fade_in → alpha 0→1
            # - visible: start+fade_in < t < end-fade_out → alpha 1
            # - fade_out: t > end-fade_out → alpha 1→0
            fade_in_end = entry.start_sec + entry.fade_in_sec
            fade_out_start = entry.end_sec - entry.fade_out_sec

            # ffmpeg drawtext enable + alpha 표현식
            alpha_expr = (
                f"if(lt(t\\,{entry.start_sec})\\,0\\,"
                f"if(lt(t\\,{fade_in_end:.2f})\\,"
                f"(t-{entry.start_sec})/{entry.fade_in_sec:.2f}\\,"
                f"if(lt(t\\,{fade_out_start:.2f})\\,1\\,"
                f"if(lt(t\\,{entry.end_sec})\\,"
                f"({entry.end_sec}-t)/{entry.fade_out_sec:.2f}\\,"
                f"0))))"
            )

            dt = (
                f"drawtext=text='{escaped_text}':"
                f"fontfile='{self.font}':"
                f"fontsize={entry.fontsize}:"
                f"fontcolor={entry.fontcolor}@%{{eif\\:{alpha_expr}\\:d}}:"
                f"borderw={entry.borderw}:"
                f"bordercolor={entry.bordercolor}:"
                f"x={x_expr}:y={y_expr}:"
                f"enable='between(t,{entry.start_sec},{entry.end_sec})'"
            )

            filter_parts.append(dt)

        filter_chain = ",".join(filter_parts)

        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-vf", filter_chain,
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-c:a", "copy",
            "-movflags", "+faststart",
            str(output_path),
        ]

        logger.debug(
            f"[SubtitleGenerator] ffmpeg drawtext: "
            f"{len(filter_parts)} subtitle layers"
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
                f"ffmpeg subtitle failed (rc={proc.returncode}): {error_msg}"
            )

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
                f"[SubtitleGenerator] ffprobe failed for "
                f"{file_path.name}, using default 20s"
            )
            return 20.0

        try:
            return float(stdout.decode().strip())
        except ValueError:
            return 20.0


# ──────────────────────────────────────────────
# 유틸리티 함수
# ──────────────────────────────────────────────

def _get_reaction_texts(event_type: str) -> list[str]:
    """이벤트별 중간 리액션 텍스트."""
    reactions: dict[str, list[str]] = {
        "climb": ["대단해!", "오오!", "어디까지?!", "무섭지 않아?"],
        "jump": ["와!", "높다!", "대박!", "몇 미터?!"],
        "run": ["빠르다!", "잡아봐!", "전력 질주!", "운동 신경!"],
        "interact": ["귀여워!", "사이좋다~", "찐 우정!", "부러워!"],
        "hunt_attempt": ["집중!", "긴장감!", "본능이다!", "조용히..."],
        "sleep": ["편안~", "좋겠다~", "꿀잠!", "귀여워..."],
        "walk": ["어디 가?", "탐험!", "산책~"],
        "play": ["신난다!", "재밌겠다!", "놀자!"],
    }
    return reactions.get(event_type, ["귀여워!"])


def _escape_ffmpeg_text(text: str) -> str:
    """ffmpeg drawtext 텍스트 이스케이프."""
    text = text.replace("\\", "\\\\")
    text = text.replace("'", "'\\''")
    text = text.replace(":", "\\:")
    text = text.replace("%", "%%")
    return text


def _position_to_xy(position: str) -> tuple[str, str]:
    """위치 문자열을 ffmpeg drawtext x/y 표현식으로 변환."""
    margin = 60  # 자막은 여유 있게
    positions: dict[str, tuple[str, str]] = {
        "top_center": ("(w-text_w)/2", f"{margin}"),
        "top_left": (f"{margin}", f"{margin}"),
        "top_right": (f"w-text_w-{margin}", f"{margin}"),
        "bottom_left": (f"{margin}", f"h-text_h-{margin}"),
        "bottom_right": (f"w-text_w-{margin}", f"h-text_h-{margin}"),
        "bottom_center": ("(w-text_w)/2", f"h-text_h-{margin}"),
        "center": ("(w-text_w)/2", "(h-text_h)/2"),
    }
    return positions.get(position, positions["bottom_center"])
