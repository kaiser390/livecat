"""YOLOv8 사냥 감지 — 고양이가 먹잇감을 사냥하는 장면을 감지한다."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from loguru import logger


@dataclass
class HuntResult:
    """사냥 감지 결과."""

    detected: bool                                 # 사냥 감지 여부
    confidence: float = 0.0                        # 감지 신뢰도 (0~1)
    prey_class: Optional[str] = None               # "mouse", "bird", "lizard"
    bbox: Optional[Tuple[int, int, int, int]] = None  # (x1, y1, x2, y2)
    blur_level: int = 0                            # 0=prey만, 1=입주변, 2=전체

    @staticmethod
    def no_detection() -> HuntResult:
        """사냥 미감지 결과를 반환한다."""
        return HuntResult(detected=False)


class HuntDetector:
    """YOLOv8 기반 사냥 감지기.

    ultralytics YOLOv8 모델을 사용하여 먹잇감(쥐, 새, 도마뱀)을
    감지한다. 감지 신뢰도에 따라 블러 레벨을 결정한다.

    블러 레벨:
        - 0: 먹잇감 영역만 블러 (confidence < aggressive_threshold)
        - 1: 입 주변 영역 블러 (confidence >= aggressive_threshold)
        - 2: 전체 화면 블러 (confidence >= 0.9, 확실한 사냥)
    """

    def __init__(self, config: dict):
        blur_config = config.get("blur", {})

        self._enabled = blur_config.get("enabled", True)
        self._model_path = Path(blur_config.get("model_path", "models/hunt_detector.pt"))
        self._confidence_threshold = blur_config.get("confidence_threshold", 0.3)
        self._aggressive_threshold = blur_config.get("aggressive_blur_threshold", 0.7)
        self._prey_classes: List[str] = blur_config.get(
            "prey_classes", ["mouse", "bird", "lizard"]
        )

        self._model = None
        self._model_loaded = False

        if self._enabled:
            self._load_model()

        logger.info(
            f"HuntDetector initialized — enabled={self._enabled}, "
            f"model={self._model_path}, "
            f"conf_threshold={self._confidence_threshold}, "
            f"prey_classes={self._prey_classes}"
        )

    def _load_model(self):
        """YOLOv8 모델을 로드한다. 실패 시 graceful fallback."""
        try:
            from ultralytics import YOLO

            if self._model_path.exists():
                self._model = YOLO(str(self._model_path))
                self._model_loaded = True
                logger.info(f"YOLOv8 model loaded: {self._model_path}")
            else:
                # 커스텀 모델이 없으면 사전훈련 모델로 폴백
                logger.warning(
                    f"Model not found: {self._model_path}, "
                    f"falling back to yolov8n.pt"
                )
                self._model = YOLO("yolov8n.pt")
                self._model_loaded = True

        except ImportError:
            logger.warning(
                "ultralytics not installed — hunt detection disabled. "
                "Install with: pip install ultralytics"
            )
            self._model_loaded = False
        except Exception as e:
            logger.error(f"Failed to load YOLO model: {e}")
            self._model_loaded = False

    async def detect(self, frame: np.ndarray) -> HuntResult:
        """프레임에서 사냥 장면을 감지한다.

        Args:
            frame: BGR 이미지 (numpy array, HxWx3)

        Returns:
            HuntResult — 감지 여부, 신뢰도, 먹잇감 종류, bbox, 블러 레벨
        """
        if not self._enabled or not self._model_loaded:
            return HuntResult.no_detection()

        try:
            results = self._model(frame, verbose=False, conf=self._confidence_threshold)

            best_detection = self._find_prey(results)
            if best_detection is None:
                return HuntResult.no_detection()

            prey_class, confidence, bbox = best_detection
            blur_level = self._determine_blur_level(confidence)

            logger.debug(
                f"Hunt detected: {prey_class} conf={confidence:.2f} "
                f"blur_level={blur_level} bbox={bbox}"
            )

            return HuntResult(
                detected=True,
                confidence=confidence,
                prey_class=prey_class,
                bbox=bbox,
                blur_level=blur_level,
            )

        except Exception as e:
            logger.error(f"Hunt detection error: {e}")
            return HuntResult.no_detection()

    def _find_prey(
        self, results
    ) -> Optional[Tuple[str, float, Tuple[int, int, int, int]]]:
        """YOLO 결과에서 먹잇감을 찾는다.

        여러 감지 결과 중 prey_classes에 해당하면서
        가장 높은 신뢰도를 가진 것을 반환한다.
        """
        best = None
        best_conf = 0.0

        for result in results:
            if result.boxes is None:
                continue

            for box in result.boxes:
                cls_id = int(box.cls[0])
                conf = float(box.conf[0])
                class_name = result.names.get(cls_id, "")

                # prey_classes에 해당하는지 확인
                matched_prey = None
                for prey in self._prey_classes:
                    if prey.lower() in class_name.lower():
                        matched_prey = prey
                        break

                if matched_prey and conf > best_conf:
                    x1, y1, x2, y2 = box.xyxy[0].cpu().numpy().astype(int)
                    best = (matched_prey, conf, (int(x1), int(y1), int(x2), int(y2)))
                    best_conf = conf

        return best

    def _determine_blur_level(self, confidence: float) -> int:
        """신뢰도에 따라 블러 레벨을 결정한다.

        - level 0: 먹잇감 영역만 (confidence < aggressive)
        - level 1: 입 주변 (confidence >= aggressive)
        - level 2: 전체 화면 (confidence >= 0.9)
        """
        if confidence >= 0.9:
            return 2
        elif confidence >= self._aggressive_threshold:
            return 1
        else:
            return 0

    @property
    def is_available(self) -> bool:
        """모델이 로드되어 사용 가능한지 여부."""
        return self._enabled and self._model_loaded
