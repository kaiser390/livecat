"""먹잇감 영역 세그멘테이션 — bbox로부터 블러용 마스크를 생성한다."""

from __future__ import annotations

from typing import Tuple

import cv2
import numpy as np
from loguru import logger


class PreySegmenter:
    """먹잇감 영역 마스크를 생성한다.

    사냥 감지 결과의 bbox를 확장하고,
    가장자리를 페더링하여 자연스러운 블러 마스크를 만든다.

    - bbox_expand_margin: 원본 대비 확장 비율 (1.5 = 50% 확장)
    - feather_radius: 가장자리 페더링 반경 (픽셀)
    """

    def __init__(self, config: dict):
        blur_config = config.get("blur", {})
        self._expand_margin = blur_config.get("bbox_expand_margin", 1.5)
        self._feather_radius = blur_config.get("feather_radius", 20)

        logger.info(
            f"PreySegmenter initialized — expand_margin={self._expand_margin}, "
            f"feather_radius={self._feather_radius}"
        )

    def segment(
        self,
        frame: np.ndarray,
        bbox: Tuple[int, int, int, int],
    ) -> np.ndarray:
        """bbox 영역으로부터 페더링된 블러 마스크를 생성한다.

        Args:
            frame: BGR 이미지 (HxWx3)
            bbox: (x1, y1, x2, y2) 바운딩 박스

        Returns:
            float32 마스크 (HxW), 값 범위 0.0 ~ 1.0
            1.0 = 블러 적용 영역, 0.0 = 원본 유지 영역
        """
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = bbox

        # bbox 확장
        ex1, ey1, ex2, ey2 = self._expand_bbox(x1, y1, x2, y2, w, h)

        # 기본 마스크 생성 (확장된 bbox 영역 = 1.0)
        mask = np.zeros((h, w), dtype=np.float32)
        mask[ey1:ey2, ex1:ex2] = 1.0

        # 페더링 적용 (가우시안 블러로 가장자리 부드럽게)
        mask = self._apply_feathering(mask)

        return mask

    def segment_full_frame(self, frame: np.ndarray) -> np.ndarray:
        """전체 프레임 블러용 마스크를 생성한다 (blur_level=2).

        중앙이 가장 강하고 가장자리로 갈수록 약해지는 비네팅 마스크.

        Args:
            frame: BGR 이미지 (HxWx3)

        Returns:
            float32 마스크 (HxW), 값 범위 0.0 ~ 1.0
        """
        h, w = frame.shape[:2]
        mask = np.ones((h, w), dtype=np.float32)
        return mask

    def _expand_bbox(
        self,
        x1: int, y1: int, x2: int, y2: int,
        img_w: int, img_h: int,
    ) -> Tuple[int, int, int, int]:
        """bbox를 margin 비율만큼 확장한다.

        확장 후 이미지 경계를 넘지 않도록 클리핑한다.
        """
        bw = x2 - x1
        bh = y2 - y1
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2

        new_bw = bw * self._expand_margin
        new_bh = bh * self._expand_margin

        ex1 = int(max(0, cx - new_bw / 2))
        ey1 = int(max(0, cy - new_bh / 2))
        ex2 = int(min(img_w, cx + new_bw / 2))
        ey2 = int(min(img_h, cy + new_bh / 2))

        return ex1, ey1, ex2, ey2

    def _apply_feathering(self, mask: np.ndarray) -> np.ndarray:
        """마스크 가장자리에 가우시안 블러로 페더링을 적용한다.

        feather_radius에 따라 가장자리가 부드럽게 감쇠한다.
        """
        if self._feather_radius <= 0:
            return mask

        # 커널 크기는 홀수여야 함
        ksize = self._feather_radius * 2 + 1
        feathered = cv2.GaussianBlur(mask, (ksize, ksize), 0)

        # 원래 1.0이었던 영역 내부는 보존 (최대값 유지)
        feathered = np.maximum(feathered, mask * 0.8)

        return np.clip(feathered, 0.0, 1.0)
