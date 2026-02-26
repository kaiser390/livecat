"""블러 적용 — 사냥 감지 결과에 따라 프레임에 가우시안 블러를 적용한다."""

from __future__ import annotations

from typing import Dict, List, Tuple

import cv2
import numpy as np
from loguru import logger

from server.blur.hunt_detector import HuntDetector, HuntResult
from server.blur.prey_segmenter import PreySegmenter


class BlurProcessor:
    """사냥 감지 결과에 따라 프레임에 블러를 적용한다.

    블러 레벨별 처리:
        - level 0: 먹잇감 bbox 영역만 블러 (kernel 31x31)
        - level 1: 입 주변 확장 블러 (kernel 61x61)
        - level 2: 전체 화면 블러 (kernel 101x101)

    페더링을 통해 블러 경계가 자연스럽게 처리된다.
    """

    def __init__(self, config: dict, hunt_detector: HuntDetector):
        self._hunt_detector = hunt_detector
        self._segmenter = PreySegmenter(config)

        blur_config = config.get("blur", {})
        self._enabled = blur_config.get("enabled", True)

        # 블러 레벨별 커널 크기
        kernels = blur_config.get("blur_kernels", {})
        self._kernels: Dict[int, Tuple[int, int]] = {
            0: tuple(kernels.get("level_0", [31, 31])),
            1: tuple(kernels.get("level_1", [61, 61])),
            2: tuple(kernels.get("level_2", [101, 101])),
        }

        self._is_active = False  # 현재 블러 적용 중 여부

        logger.info(
            f"BlurProcessor initialized — enabled={self._enabled}, "
            f"kernels={self._kernels}"
        )

    @property
    def is_active(self) -> bool:
        """현재 블러가 적용 중인지 여부."""
        return self._is_active

    async def apply(
        self, frame: np.ndarray, hunt_result: HuntResult
    ) -> np.ndarray:
        """사냥 감지 결과에 따라 프레임에 블러를 적용한다.

        Args:
            frame: BGR 이미지 (HxWx3, numpy array)
            hunt_result: HuntDetector의 감지 결과

        Returns:
            블러가 적용된 프레임 (원본이 수정되지 않음)
        """
        if not self._enabled or not hunt_result.detected:
            self._is_active = False
            return frame

        self._is_active = True
        blur_level = hunt_result.blur_level
        kernel = self._kernels.get(blur_level, self._kernels[0])

        logger.debug(
            f"Applying blur: level={blur_level}, kernel={kernel}, "
            f"prey={hunt_result.prey_class}, conf={hunt_result.confidence:.2f}"
        )

        try:
            if blur_level == 2:
                # 전체 화면 블러
                return self._apply_full_blur(frame, kernel)
            elif hunt_result.bbox is not None:
                # 영역 블러 (level 0 또는 1)
                return self._apply_masked_blur(frame, hunt_result.bbox, kernel)
            else:
                self._is_active = False
                return frame

        except Exception as e:
            logger.error(f"Blur processing error: {e}")
            self._is_active = False
            return frame

    def _apply_full_blur(
        self, frame: np.ndarray, kernel: Tuple[int, int]
    ) -> np.ndarray:
        """전체 프레임에 가우시안 블러를 적용한다."""
        kw, kh = self._ensure_odd_kernel(kernel)
        blurred = cv2.GaussianBlur(frame, (kw, kh), 0)
        return blurred

    def _apply_masked_blur(
        self,
        frame: np.ndarray,
        bbox: Tuple[int, int, int, int],
        kernel: Tuple[int, int],
    ) -> np.ndarray:
        """마스크 기반 영역 블러를 적용한다.

        페더링된 마스크를 사용하여 블러 영역과 원본이
        자연스럽게 블렌딩된다.
        """
        # 마스크 생성 (feathered)
        mask = self._segmenter.segment(frame, bbox)

        # 전체 프레임 블러
        kw, kh = self._ensure_odd_kernel(kernel)
        blurred = cv2.GaussianBlur(frame, (kw, kh), 0)

        # 마스크 기반 블렌딩: result = blurred * mask + original * (1 - mask)
        mask_3ch = mask[:, :, np.newaxis]  # (H, W, 1)
        result = (
            blurred.astype(np.float32) * mask_3ch
            + frame.astype(np.float32) * (1.0 - mask_3ch)
        )

        return result.astype(np.uint8)

    @staticmethod
    def _ensure_odd_kernel(kernel: Tuple[int, int]) -> Tuple[int, int]:
        """커널 크기가 홀수인지 확인하고 조정한다.

        가우시안 블러 커널은 홀수여야 한다.
        """
        kw = kernel[0] if kernel[0] % 2 == 1 else kernel[0] + 1
        kh = kernel[1] if kernel[1] % 2 == 1 else kernel[1] + 1
        return kw, kh
