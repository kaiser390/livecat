"""텍스트 오버레이 모듈.

선택된 프레임 위에 이벤트 키워드, 고양이 이름 뱃지,
채널 로고 워터마크를 렌더링한다.
한글 폰트 지원 및 플랫폼별 사이즈 대응.
"""

from __future__ import annotations

import platform as _platform
from pathlib import Path

import cv2
import numpy as np
from loguru import logger
from PIL import Image, ImageDraw, ImageFont

# 프로젝트 루트 (server/ 의 상위)
_ROOT_DIR = Path(__file__).resolve().parent.parent.parent


class TextOverlay:
    """이미지 위에 텍스트, 이름 뱃지, 로고를 합성한다.

    - 이벤트 키워드: 큰 볼드 텍스트 + 검정 외곽선 + 그림자
    - 고양이 이름 뱃지: 좌측 하단, 반투명 배경
    - 채널 로고: 우측 하단 워터마크
    - 플랫폼별 출력 사이즈: YouTube 1280x720, TikTok 1080x1920
    """

    # 이벤트 타입 → 한글 키워드 매핑
    EVENT_KEYWORDS: dict[str, str] = {
        "climb": "나무등반!",
        "jump": "점프!",
        "run": "전력질주!",
        "interact": "함께 노는 중!",
        "hunt_attempt": "사냥 본능!",
        "sleep": "꿀잠 타임",
        "groom": "그루밍 중",
        "sunbathe": "일광욕",
        "fail": "앗, 실패!",
    }

    # 플랫폼별 출력 사이즈
    PLATFORM_SIZES: dict[str, tuple[int, int]] = {
        "youtube": (1280, 720),
        "shorts": (1080, 1920),
        "tiktok": (1080, 1920),
    }

    def __init__(self, config: dict) -> None:
        self._config = config
        thumb_cfg = config.get("thumbnail", {})

        self._yt_size = tuple(thumb_cfg.get("youtube_size", [1280, 720]))
        self._tt_size = tuple(thumb_cfg.get("tiktok_size", [1080, 1920]))
        self._font_name: str = thumb_cfg.get("font", "NanumSquareRoundEB.ttf")
        self._quality: int = thumb_cfg.get("quality", 95)

        # 로고 경로
        self._logo_path = _ROOT_DIR / "templates" / "overlays" / "logo_80x80.png"
        self._logo_image: Image.Image | None = None
        self._load_logo()

        # 폰트 캐시 (size -> ImageFont)
        self._font_cache: dict[int, ImageFont.FreeTypeFont] = {}

        logger.info(
            f"TextOverlay initialized — "
            f"font={self._font_name}, "
            f"yt_size={self._yt_size}, tt_size={self._tt_size}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def apply(
        self,
        image: np.ndarray,
        text: str,
        cat_names: list[str],
        platform: str = "youtube",
    ) -> Image.Image:
        """이미지에 텍스트 오버레이를 적용하여 PIL Image를 반환한다.

        Args:
            image: BGR numpy 배열 (원본 프레임).
            text: 오버레이할 메인 텍스트 (이벤트 키워드).
            cat_names: 등장 고양이 이름 리스트 (예: ["나나", "토토"]).
            platform: 대상 플랫폼 ("youtube", "tiktok", "shorts").

        Returns:
            완성된 PIL Image (RGB).
        """
        # BGR -> RGB -> PIL
        rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(rgb)

        # 플랫폼별 리사이즈
        target_size = self._get_platform_size(platform)
        pil_image = pil_image.resize(target_size, Image.LANCZOS)

        draw = ImageDraw.Draw(pil_image)
        w, h = pil_image.size

        # 1. 메인 텍스트 (이벤트 키워드) — 중앙 상단
        self._draw_main_text(draw, text, w, h, platform)

        # 2. 고양이 이름 뱃지 — 좌측 하단
        if cat_names:
            self._draw_cat_badge(pil_image, draw, cat_names, w, h)

        # 3. 채널 로고 워터마크 — 우측 하단
        self._draw_logo(pil_image, w, h)

        return pil_image

    # ------------------------------------------------------------------
    # Main Text Rendering
    # ------------------------------------------------------------------

    def _draw_main_text(
        self,
        draw: ImageDraw.ImageDraw,
        text: str,
        w: int,
        h: int,
        platform: str,
    ) -> None:
        """중앙에 큰 볼드 텍스트 + 검정 외곽선 + 그림자를 그린다."""
        # 플랫폼별 텍스트 크기 조정
        if platform in ("tiktok", "shorts"):
            font_size = 64
            stroke_width = 3
        else:
            font_size = 72
            stroke_width = 4

        font = self._get_font(font_size)

        # 텍스트 바운딩 박스 측정
        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        # 중앙 배치
        x = (w - text_w) // 2
        y = int(h * 0.35) - text_h // 2  # 약간 상단 쪽

        # 그림자 (오프셋 +3, +3, 반투명 검정)
        shadow_offset = 3
        draw.text(
            (x + shadow_offset, y + shadow_offset),
            text,
            font=font,
            fill=(0, 0, 0, 180),
        )

        # 메인 텍스트: 흰색 + 검정 외곽선
        draw.text(
            (x, y),
            text,
            font=font,
            fill=(255, 255, 255),
            stroke_width=stroke_width,
            stroke_fill=(0, 0, 0),
        )

    # ------------------------------------------------------------------
    # Cat Name Badge
    # ------------------------------------------------------------------

    def _draw_cat_badge(
        self,
        pil_image: Image.Image,
        draw: ImageDraw.ImageDraw,
        cat_names: list[str],
        w: int,
        h: int,
    ) -> None:
        """좌측 하단에 반투명 배경의 고양이 이름 뱃지를 그린다."""
        badge_font = self._get_font(36)
        badge_text = " & ".join(cat_names)

        # 뱃지 텍스트 크기 측정
        bbox = draw.textbbox((0, 0), badge_text, font=badge_font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        padding_x = 16
        padding_y = 8
        margin = 20

        badge_x = margin
        badge_y = h - margin - text_h - padding_y * 2

        # 반투명 배경 (오버레이)
        overlay = Image.new("RGBA", pil_image.size, (0, 0, 0, 0))
        overlay_draw = ImageDraw.Draw(overlay)
        overlay_draw.rounded_rectangle(
            [
                badge_x,
                badge_y,
                badge_x + text_w + padding_x * 2,
                badge_y + text_h + padding_y * 2,
            ],
            radius=8,
            fill=(0, 0, 0, 140),
        )

        # 오버레이 합성
        if pil_image.mode != "RGBA":
            pil_image_rgba = pil_image.convert("RGBA")
        else:
            pil_image_rgba = pil_image

        composited = Image.alpha_composite(pil_image_rgba, overlay)

        # 결과를 원본 이미지에 반영
        pil_image.paste(composited.convert("RGB"))

        # 텍스트 다시 그리기 (합성 후)
        draw = ImageDraw.Draw(pil_image)
        draw.text(
            (badge_x + padding_x, badge_y + padding_y),
            badge_text,
            font=badge_font,
            fill=(255, 255, 255),
            stroke_width=1,
            stroke_fill=(0, 0, 0),
        )

    # ------------------------------------------------------------------
    # Logo Watermark
    # ------------------------------------------------------------------

    def _draw_logo(self, pil_image: Image.Image, w: int, h: int) -> None:
        """우측 하단에 채널 로고 워터마크를 합성한다."""
        if self._logo_image is None:
            return

        logo_size = 80
        margin = 20

        logo = self._logo_image.resize((logo_size, logo_size), Image.LANCZOS)

        # 반투명 적용 (opacity 0.7)
        if logo.mode != "RGBA":
            logo = logo.convert("RGBA")

        alpha = logo.split()[3]
        alpha = alpha.point(lambda a: int(a * 0.7))
        logo.putalpha(alpha)

        # 우측 하단 배치
        pos_x = w - logo_size - margin
        pos_y = h - logo_size - margin

        pil_image.paste(logo, (pos_x, pos_y), logo)

    # ------------------------------------------------------------------
    # Font Loading
    # ------------------------------------------------------------------

    def _get_font(self, size: int) -> ImageFont.FreeTypeFont:
        """지정 크기의 폰트를 로드한다 (캐시 사용)."""
        if size in self._font_cache:
            return self._font_cache[size]

        font = self._load_font(size)
        self._font_cache[size] = font
        return font

    def _load_font(self, size: int) -> ImageFont.FreeTypeFont:
        """한글 폰트를 로드한다. 실패 시 시스템 폰트로 폴백."""
        # 1차: 프로젝트 내 폰트
        project_font = _ROOT_DIR / "assets" / "fonts" / self._font_name
        if project_font.exists():
            try:
                return ImageFont.truetype(str(project_font), size)
            except Exception:
                pass

        # 2차: 시스템 폰트 경로에서 직접 탐색
        font_dirs = self._get_system_font_dirs()
        for font_dir in font_dirs:
            font_path = Path(font_dir) / self._font_name
            if font_path.exists():
                try:
                    return ImageFont.truetype(str(font_path), size)
                except Exception:
                    continue

        # 3차: 시스템 한글 폰트 폴백 목록
        fallback_fonts = [
            "NanumSquareRoundEB.ttf",
            "NanumSquareRoundB.ttf",
            "NanumGothicBold.ttf",
            "NanumGothic.ttf",
            "malgunbd.ttf",  # Windows 맑은 고딕 Bold
            "malgun.ttf",    # Windows 맑은 고딕
            "AppleGothic.ttf",
            "NotoSansCJK-Bold.ttc",
        ]

        for fb_name in fallback_fonts:
            for font_dir in font_dirs:
                fb_path = Path(font_dir) / fb_name
                if fb_path.exists():
                    try:
                        return ImageFont.truetype(str(fb_path), size)
                    except Exception:
                        continue

        # 최종 폴백: Pillow 기본 폰트
        logger.warning(
            f"No Korean font found — falling back to Pillow default. "
            f"Tried: {self._font_name}"
        )
        return ImageFont.load_default()

    @staticmethod
    def _get_system_font_dirs() -> list[str]:
        """OS별 시스템 폰트 디렉토리 목록을 반환한다."""
        system = _platform.system()
        if system == "Windows":
            import os
            windir = os.environ.get("WINDIR", r"C:\Windows")
            return [
                str(Path(windir) / "Fonts"),
                str(Path.home() / "AppData" / "Local" / "Microsoft" / "Windows" / "Fonts"),
            ]
        elif system == "Darwin":
            return [
                "/System/Library/Fonts",
                "/Library/Fonts",
                str(Path.home() / "Library" / "Fonts"),
            ]
        else:
            return [
                "/usr/share/fonts/truetype",
                "/usr/share/fonts",
                "/usr/local/share/fonts",
                str(Path.home() / ".fonts"),
                str(Path.home() / ".local" / "share" / "fonts"),
            ]

    # ------------------------------------------------------------------
    # Logo Loading
    # ------------------------------------------------------------------

    def _load_logo(self) -> None:
        """채널 로고를 로드한다. 파일이 없으면 플레이스홀더를 생성한다."""
        if self._logo_path.exists():
            try:
                self._logo_image = Image.open(self._logo_path).convert("RGBA")
                logger.info(f"Logo loaded: {self._logo_path}")
                return
            except Exception as e:
                logger.warning(f"Failed to load logo: {e}")

        # 플레이스홀더 생성 (빨간 원 + LC 텍스트)
        logger.info("Creating placeholder logo (logo file not found)")
        self._logo_image = self._create_placeholder_logo()
        self._save_placeholder_logo()

    def _create_placeholder_logo(self) -> Image.Image:
        """80x80 플레이스홀더 로고를 생성한다."""
        size = 80
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # 빨간 원 배경
        draw.ellipse([4, 4, size - 4, size - 4], fill=(255, 59, 48, 220))

        # "LC" 텍스트
        try:
            font = ImageFont.truetype("arial.ttf", 28)
        except Exception:
            font = ImageFont.load_default()

        bbox = draw.textbbox((0, 0), "LC", font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        draw.text(
            ((size - tw) // 2, (size - th) // 2 - 2),
            "LC",
            font=font,
            fill=(255, 255, 255),
        )

        return img

    def _save_placeholder_logo(self) -> None:
        """플레이스홀더 로고를 디스크에 저장한다."""
        if self._logo_image is None:
            return
        try:
            self._logo_path.parent.mkdir(parents=True, exist_ok=True)
            self._logo_image.save(str(self._logo_path))
            logger.info(f"Placeholder logo saved: {self._logo_path}")
        except Exception as e:
            logger.warning(f"Failed to save placeholder logo: {e}")

    # ------------------------------------------------------------------
    # Platform Size Helper
    # ------------------------------------------------------------------

    def _get_platform_size(self, platform: str) -> tuple[int, int]:
        """플랫폼에 맞는 이미지 사이즈를 반환한다."""
        if platform in ("tiktok", "shorts"):
            return self._tt_size
        return self._yt_size
