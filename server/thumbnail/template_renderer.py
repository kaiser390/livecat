"""썸네일 템플릿 렌더러.

FrameSelector가 선택한 최적 프레임에 템플릿(A/B/C)을 적용하고,
TextOverlay를 통해 텍스트를 합성하여 최종 썸네일 파일을 저장한다.
"""

from __future__ import annotations

import random
from pathlib import Path

import cv2
import numpy as np
from loguru import logger
from PIL import Image, ImageDraw

from server.thumbnail.frame_selector import SelectedFrame
from server.thumbnail.text_overlay import TextOverlay

# 프로젝트 루트 (server/ 의 상위)
_ROOT_DIR = Path(__file__).resolve().parent.parent.parent


class TemplateRenderer:
    """3종 템플릿(A: Bold, B: Minimal, C: Frame)을 렌더링한다.

    각 템플릿은 배경 처리, 텍스트 위치, 프레임 효과가 다르며,
    A/B 테스트를 위해 랜덤 또는 순환 선택된다.
    """

    # 이벤트 타입 → 한글 키워드
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

    def __init__(self, config: dict) -> None:
        self._config = config
        thumb_cfg = config.get("thumbnail", {})

        self._quality: int = thumb_cfg.get("quality", 95)
        self._templates: list[dict] = thumb_cfg.get("templates", [])
        self._output_dir = _ROOT_DIR / "thumbnails"
        self._output_dir.mkdir(parents=True, exist_ok=True)

        # 고양이 프로필
        cats_cfg = config.get("cats", {})
        self._cat_names: dict[str, str] = {}
        for key, profile in cats_cfg.items():
            self._cat_names[key] = profile.get("name_ko", key)

        # TextOverlay 인스턴스
        self._text_overlay = TextOverlay(config)

        # 템플릿 순환 카운터 (A/B 테스트용)
        self._template_counter = 0

        logger.info(
            f"TemplateRenderer initialized — "
            f"{len(self._templates)} templates, "
            f"output={self._output_dir}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def render(
        self,
        frame: SelectedFrame,
        metadata: dict,
        platform: str = "youtube",
    ) -> Path:
        """선택된 프레임에 템플릿을 적용하여 썸네일을 생성한다.

        Args:
            frame: FrameSelector가 반환한 SelectedFrame.
            metadata: 클립 메타데이터 (event_type, cats, event_id 등).
            platform: 대상 플랫폼 ("youtube", "tiktok", "shorts").

        Returns:
            저장된 썸네일 파일 경로.
        """
        # 템플릿 선택 (순환)
        template = self._pick_template()
        template_id = template.get("id", "A")
        template_name = template.get("name", "Unknown")

        event_type = metadata.get("event_type", "unknown")
        cats = metadata.get("cats", [])
        event_id = metadata.get("event_id", "unknown")

        # 이벤트 키워드
        keyword = self.EVENT_KEYWORDS.get(event_type, event_type)

        # 고양이 표시 이름
        cat_display_names = [
            self._cat_names.get(c, c) for c in cats
        ]

        logger.info(
            f"Rendering template {template_id} ({template_name}) "
            f"for {event_id} [{platform}]"
        )

        # 프레임 복사
        img = frame.frame.copy()

        # 1. 템플릿별 배경 처리
        img = self._apply_background(img, template)

        # 2. 템플릿별 프레임 테두리
        img = self._apply_frame_border(img, template)

        # 3. TextOverlay 적용 (텍스트 위치는 템플릿에 따라 다름)
        pil_result = self._apply_template_text(
            img, keyword, cat_display_names, platform, template
        )

        # 4. 저장
        platform_suffix = self._platform_suffix(platform)
        output_path = self._output_dir / f"{event_id}_{platform_suffix}.jpg"

        pil_result.convert("RGB").save(
            str(output_path),
            "JPEG",
            quality=self._quality,
        )

        logger.info(
            f"Thumbnail saved: {output_path.name} "
            f"(template={template_id}, size={pil_result.size})"
        )
        return output_path

    # ------------------------------------------------------------------
    # Template Selection
    # ------------------------------------------------------------------

    def _pick_template(self) -> dict:
        """템플릿을 순환 선택한다 (A/B 테스트)."""
        if not self._templates:
            return self._default_template()

        template = self._templates[self._template_counter % len(self._templates)]
        self._template_counter += 1
        return template

    @staticmethod
    def _default_template() -> dict:
        """기본 Bold 템플릿."""
        return {
            "id": "A",
            "name": "Bold",
            "text_position": "center",
            "text_size": 72,
            "text_stroke": 4,
            "background_darken": 0.3,
        }

    # ------------------------------------------------------------------
    # Background Processing
    # ------------------------------------------------------------------

    def _apply_background(self, img: np.ndarray, template: dict) -> np.ndarray:
        """템플릿에 따라 배경을 어둡게 한다."""
        darken = template.get("background_darken", 0.0)
        if darken <= 0.0:
            return img

        # 배경 어둡게: pixel * (1 - darken)
        factor = 1.0 - darken
        darkened = (img.astype(np.float32) * factor).clip(0, 255).astype(np.uint8)
        return darkened

    # ------------------------------------------------------------------
    # Frame Border (Template C)
    # ------------------------------------------------------------------

    def _apply_frame_border(self, img: np.ndarray, template: dict) -> np.ndarray:
        """Template C: 컬러 프레임 테두리를 추가한다."""
        frame_color_hex = template.get("frame_color")
        frame_width = template.get("frame_width", 0)

        if not frame_color_hex or frame_width <= 0:
            return img

        # Hex -> BGR
        color_rgb = self._hex_to_rgb(frame_color_hex)
        color_bgr = (color_rgb[2], color_rgb[1], color_rgb[0])

        # 테두리 추가
        h, w = img.shape[:2]
        bordered = img.copy()

        # 상/하/좌/우 테두리
        bordered[:frame_width, :] = color_bgr        # 상단
        bordered[-frame_width:, :] = color_bgr        # 하단
        bordered[:, :frame_width] = color_bgr         # 좌측
        bordered[:, -frame_width:] = color_bgr        # 우측

        return bordered

    # ------------------------------------------------------------------
    # Template-Specific Text
    # ------------------------------------------------------------------

    def _apply_template_text(
        self,
        img: np.ndarray,
        keyword: str,
        cat_names: list[str],
        platform: str,
        template: dict,
    ) -> Image.Image:
        """템플릿에 맞는 텍스트 오버레이를 적용한다.

        Template A (Bold): 큰 중앙 텍스트, TextOverlay 기본 사용.
        Template B (Minimal): 작은 좌측 하단 텍스트, 이미지 중심.
        Template C (Frame): 상단 중앙 텍스트.
        """
        template_id = template.get("id", "A")
        text_position = template.get("text_position", "center")
        text_size = template.get("text_size", 72)
        stroke_width = template.get("text_stroke", 4)

        # BGR -> RGB -> PIL
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        pil_image = Image.fromarray(rgb)

        # 플랫폼별 리사이즈
        target_size = self._text_overlay._get_platform_size(platform)
        pil_image = pil_image.resize(target_size, Image.LANCZOS)

        w, h = pil_image.size
        draw = ImageDraw.Draw(pil_image)

        # 메인 텍스트 렌더링
        font = self._text_overlay._get_font(text_size)
        bbox = draw.textbbox((0, 0), keyword, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        # 위치 계산
        if text_position == "center":
            x = (w - text_w) // 2
            y = int(h * 0.35) - text_h // 2
        elif text_position == "bottom_left":
            x = 30
            y = h - text_h - 100
        elif text_position == "top_center":
            x = (w - text_w) // 2
            y = 30
        else:
            x = (w - text_w) // 2
            y = int(h * 0.35) - text_h // 2

        # 그림자
        shadow_offset = 3
        draw.text(
            (x + shadow_offset, y + shadow_offset),
            keyword,
            font=font,
            fill=(0, 0, 0, 180),
        )

        # 메인 텍스트: 흰색 + 검정 외곽선
        draw.text(
            (x, y),
            keyword,
            font=font,
            fill=(255, 255, 255),
            stroke_width=stroke_width,
            stroke_fill=(0, 0, 0),
        )

        # 고양이 이름 뱃지 (좌측 하단)
        if cat_names:
            self._text_overlay._draw_cat_badge(pil_image, draw, cat_names, w, h)

        # 채널 로고 (우측 하단)
        self._text_overlay._draw_logo(pil_image, w, h)

        return pil_image

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
        """#RRGGBB 형식의 Hex를 (R, G, B) 튜플로 변환한다."""
        hex_color = hex_color.lstrip("#")
        return (
            int(hex_color[0:2], 16),
            int(hex_color[2:4], 16),
            int(hex_color[4:6], 16),
        )

    @staticmethod
    def _platform_suffix(platform: str) -> str:
        """플랫폼별 파일 접미사."""
        mapping = {
            "youtube": "yt",
            "shorts": "yt",
            "tiktok": "tt",
        }
        return mapping.get(platform, platform)
