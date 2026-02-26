"""최적 프레임 선택 모듈.

클립에서 매 N프레임을 샘플링하고, 선명도 / 포즈 매력도 / 구도를
종합 평가하여 썸네일에 가장 적합한 단일 프레임을 선택한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from loguru import logger

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None
    logger.warning("ultralytics not installed — pose scoring will be unavailable")


@dataclass
class SelectedFrame:
    """프레임 선택 결과."""

    frame: np.ndarray
    frame_index: int
    scores: dict[str, float] = field(default_factory=dict)
    # scores keys: clarity, pose, composition, total


class FrameSelector:
    """클립 내 최적 프레임을 AI 기반으로 선택한다.

    평가 기준:
        - clarity (0.3): Laplacian variance 기반 선명도
        - pose_attractiveness (0.4): YOLOv8 고양이 감지 — 전신 노출, 중앙 배치
        - composition (0.3): 삼분할 법칙 (고양이 중심이 교차점 근접)
        - both_cats bonus: 2마리 동시 감지 시 +20
    """

    # COCO 클래스 ID for cat
    _CAT_CLASS_ID = 15

    def __init__(self, config: dict) -> None:
        self._config = config
        thumb_cfg = config.get("thumbnail", {})

        self._sample_interval: int = thumb_cfg.get("sample_interval", 10)
        self._clarity_threshold: float = thumb_cfg.get("clarity_threshold", 50.0)

        weights = thumb_cfg.get("weights", {})
        self._w_clarity: float = weights.get("clarity", 0.30)
        self._w_pose: float = weights.get("pose_attractiveness", 0.40)
        self._w_composition: float = weights.get("composition", 0.30)
        self._both_cats_bonus: float = thumb_cfg.get("prefer_both_cats_bonus", 20)

        # YOLOv8 모델 (지연 로드)
        self._model: Any | None = None
        self._model_loaded = False

        logger.info(
            f"FrameSelector initialized — "
            f"interval={self._sample_interval}, "
            f"weights=(clarity={self._w_clarity}, pose={self._w_pose}, "
            f"comp={self._w_composition}), "
            f"both_cats_bonus={self._both_cats_bonus}"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def select(self, clip_path: Path) -> SelectedFrame:
        """클립에서 최적 프레임 1장을 선택하여 반환한다.

        Args:
            clip_path: 클립 동영상 파일 경로 (.mp4)

        Returns:
            SelectedFrame 인스턴스 (최고 점수 프레임).

        Raises:
            FileNotFoundError: 클립 파일이 존재하지 않을 때.
            RuntimeError: 프레임을 하나도 읽지 못했을 때.
        """
        clip_path = Path(clip_path)
        if not clip_path.exists():
            raise FileNotFoundError(f"Clip not found: {clip_path}")

        self._ensure_model()

        cap = cv2.VideoCapture(str(clip_path))
        if not cap.isOpened():
            raise RuntimeError(f"Cannot open video: {clip_path}")

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        logger.debug(f"Sampling every {self._sample_interval}th frame from {total_frames} total")

        best: SelectedFrame | None = None
        frame_idx = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % self._sample_interval == 0:
                scores = self._evaluate_frame(frame)

                if best is None or scores["total"] > best.scores["total"]:
                    best = SelectedFrame(
                        frame=frame.copy(),
                        frame_index=frame_idx,
                        scores=scores,
                    )

            frame_idx += 1

        cap.release()

        if best is None:
            raise RuntimeError(f"No frames could be read from: {clip_path}")

        logger.info(
            f"Best frame selected: idx={best.frame_index}, "
            f"total={best.scores['total']:.1f} "
            f"(clarity={best.scores['clarity']:.1f}, "
            f"pose={best.scores['pose']:.1f}, "
            f"comp={best.scores['composition']:.1f})"
        )
        return best

    # ------------------------------------------------------------------
    # Frame Evaluation
    # ------------------------------------------------------------------

    def _evaluate_frame(self, frame: np.ndarray) -> dict[str, float]:
        """프레임의 선명도, 포즈, 구도를 종합 평가한다."""
        clarity = self._score_clarity(frame)
        detections = self._detect_cats(frame)
        pose = self._score_pose(frame, detections)
        composition = self._score_composition(frame, detections)

        # 2마리 동시 감지 보너스
        num_cats = len(detections)
        bonus = self._both_cats_bonus if num_cats >= 2 else 0.0

        total = (
            self._w_clarity * clarity
            + self._w_pose * pose
            + self._w_composition * composition
            + bonus
        )

        return {
            "clarity": clarity,
            "pose": pose,
            "composition": composition,
            "num_cats": float(num_cats),
            "bonus": bonus,
            "total": total,
        }

    # ------------------------------------------------------------------
    # 1. Clarity — Laplacian Variance
    # ------------------------------------------------------------------

    def _score_clarity(self, frame: np.ndarray) -> float:
        """Laplacian variance 기반 선명도 점수 (0~100).

        높은 분산 = 엣지가 많은 선명한 이미지.
        """
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()

        # 정규화: 일반적으로 laplacian_var 범위 0~2000+
        # 500 이상이면 매우 선명, 50 이하면 블러
        score = min(laplacian_var / 5.0, 100.0)

        # 최소 임계값 이하인 경우 크게 감점
        if laplacian_var < self._clarity_threshold:
            score *= 0.3

        return score

    # ------------------------------------------------------------------
    # 2. Pose Attractiveness — YOLOv8 Cat Detection
    # ------------------------------------------------------------------

    def _detect_cats(self, frame: np.ndarray) -> list[dict]:
        """YOLOv8으로 고양이를 감지하여 bbox 목록을 반환한다.

        Returns:
            list of dict, 각 원소는 {'bbox': [x1,y1,x2,y2], 'conf': float}
        """
        if self._model is None:
            return []

        try:
            results = self._model(frame, verbose=False)
        except Exception as e:
            logger.debug(f"YOLO detection failed: {e}")
            return []

        detections = []
        for result in results:
            boxes = result.boxes
            if boxes is None:
                continue
            for i in range(len(boxes)):
                cls_id = int(boxes.cls[i].item())
                if cls_id == self._CAT_CLASS_ID:
                    bbox = boxes.xyxy[i].cpu().numpy().tolist()
                    conf = float(boxes.conf[i].item())
                    detections.append({"bbox": bbox, "conf": conf})

        return detections

    def _score_pose(self, frame: np.ndarray, detections: list[dict]) -> float:
        """고양이 포즈 매력도 점수 (0~100).

        - 전신 노출 (bbox 면적 비율)
        - 프레임 중앙 근접도
        - 감지 신뢰도
        """
        if not detections:
            return 10.0  # 고양이 미감지 시 낮은 기본점

        h, w = frame.shape[:2]
        frame_area = h * w

        best_score = 0.0
        for det in detections:
            x1, y1, x2, y2 = det["bbox"]
            conf = det["conf"]

            # 전신 노출 점수: bbox 면적이 프레임의 10~50%일 때 최적
            bbox_area = (x2 - x1) * (y2 - y1)
            area_ratio = bbox_area / frame_area
            if area_ratio < 0.05:
                # 너무 작음 (멀리 있음)
                fullbody_score = area_ratio / 0.05 * 40.0
            elif area_ratio <= 0.50:
                # 적정 범위
                fullbody_score = 40.0 + (area_ratio - 0.05) / 0.45 * 30.0
            else:
                # 너무 클 수 있음 (클로즈업)
                fullbody_score = 70.0 - (area_ratio - 0.50) * 40.0

            fullbody_score = max(fullbody_score, 0.0)

            # 프레임 중앙 근접도
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2
            dx = abs(cx - w / 2) / (w / 2)
            dy = abs(cy - h / 2) / (h / 2)
            center_dist = (dx ** 2 + dy ** 2) ** 0.5
            center_score = max(0.0, 30.0 * (1.0 - center_dist))

            # 신뢰도 보너스
            conf_score = conf * 30.0

            total = fullbody_score + center_score + conf_score
            best_score = max(best_score, total)

        return min(best_score, 100.0)

    # ------------------------------------------------------------------
    # 3. Composition — Rule of Thirds
    # ------------------------------------------------------------------

    def _score_composition(self, frame: np.ndarray, detections: list[dict]) -> float:
        """삼분할 법칙 기반 구도 점수 (0~100).

        고양이 중심이 삼분할 교차점(4개)에 가까울수록 높은 점수.
        """
        if not detections:
            return 30.0  # 기본 구도 점수 (고양이 미감지)

        h, w = frame.shape[:2]

        # 삼분할 교차점 (4개)
        thirds_x = [w / 3, 2 * w / 3]
        thirds_y = [h / 3, 2 * h / 3]
        intersections = [
            (tx, ty) for tx in thirds_x for ty in thirds_y
        ]

        best_score = 0.0
        for det in detections:
            x1, y1, x2, y2 = det["bbox"]
            cx = (x1 + x2) / 2
            cy = (y1 + y2) / 2

            # 가장 가까운 삼분할 교차점까지의 거리
            min_dist = float("inf")
            for ix, iy in intersections:
                dist = ((cx - ix) ** 2 + (cy - iy) ** 2) ** 0.5
                min_dist = min(min_dist, dist)

            # 정규화: 최대 거리는 대각선의 1/3 정도
            max_dist = ((w / 3) ** 2 + (h / 3) ** 2) ** 0.5
            normalized = min_dist / max_dist

            # 가까울수록 높은 점수
            score = max(0.0, 100.0 * (1.0 - normalized))
            best_score = max(best_score, score)

            # 적절한 여백 보너스: 고양이가 프레임의 20~80% 차지
            bbox_w_ratio = (x2 - x1) / w
            bbox_h_ratio = (y2 - y1) / h
            if 0.2 <= bbox_w_ratio <= 0.8 and 0.2 <= bbox_h_ratio <= 0.8:
                best_score = min(best_score + 10.0, 100.0)

        return best_score

    # ------------------------------------------------------------------
    # Model Loading
    # ------------------------------------------------------------------

    def _ensure_model(self) -> None:
        """YOLOv8 모델을 필요 시 로드한다."""
        if self._model_loaded:
            return
        self._model_loaded = True

        if YOLO is None:
            logger.warning("ultralytics not available — using clarity-only scoring")
            return

        try:
            self._model = YOLO("yolov8n.pt")
            logger.info("YOLOv8n model loaded for frame selection")
        except Exception as e:
            logger.warning(f"Failed to load YOLOv8 model: {e}")
            self._model = None
