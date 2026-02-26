"""
세로 변환 모듈 — 16:9 원본을 9:16 숏폼으로 스마트 크롭.

YOLOv8으로 고양이 위치를 감지하여 크롭 중심을 결정하고,
Kalman-filter 스무딩으로 부드러운 카메라 팬 효과를 만든다.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from loguru import logger

# ──────────────────────────────────────────────
# 상수
# ──────────────────────────────────────────────
SRC_W, SRC_H = 1920, 1080
CROP_W = int(SRC_H * 9 / 16)         # 608 (정확히 9:16 비율)
OUT_W, OUT_H = 1080, 1920             # 최종 출력 해상도
HALF_CROP = CROP_W // 2               # 304
MIN_X = HALF_CROP                     # 304 — 좌측 한계
MAX_X = SRC_W - HALF_CROP             # 1616 — 우측 한계


@dataclass
class CropPosition:
    """프레임별 크롭 중심 X 좌표."""
    frame_idx: int
    center_x: float
    confidence: float = 0.0
    detected: bool = False


@dataclass
class KalmanState:
    """1D Kalman filter 상태 (크롭 중심 X 스무딩용)."""
    x: float = SRC_W / 2              # 위치 추정
    v: float = 0.0                    # 속도 추정
    p_x: float = 100.0               # 위치 불확실성
    p_v: float = 10.0                # 속도 불확실성
    q_x: float = 1.0                 # 프로세스 노이즈 (위치)
    q_v: float = 0.5                 # 프로세스 노이즈 (속도)
    r: float = 50.0                  # 관측 노이즈


class KalmanFilter1D:
    """크롭 중심 X 스무딩을 위한 1D Kalman filter."""

    def __init__(self, smoothing_factor: float = 0.85):
        self.state = KalmanState()
        # smoothing_factor가 높을수록 관측 노이즈(R)를 높여 부드럽게
        self.state.r = 50.0 / max(1.0 - smoothing_factor, 0.01)

    def predict(self) -> float:
        """예측 단계."""
        self.state.x += self.state.v
        self.state.p_x += self.state.p_v + self.state.q_x
        self.state.p_v += self.state.q_v
        return self.state.x

    def update(self, measurement: float) -> float:
        """관측 업데이트 단계."""
        # Kalman gain
        k = self.state.p_x / (self.state.p_x + self.state.r)

        # 상태 업데이트
        innovation = measurement - self.state.x
        self.state.x += k * innovation
        self.state.v += 0.1 * k * innovation  # 속도도 약하게 보정
        self.state.p_x *= (1 - k)

        return self.state.x

    def step(self, measurement: Optional[float] = None) -> float:
        """predict + update. measurement=None이면 predict만."""
        predicted = self.predict()
        if measurement is not None:
            return self.update(measurement)
        return predicted


class VerticalConverter:
    """16:9 원본 클립을 9:16 세로 영상으로 스마트 크롭 변환."""

    def __init__(self, config: dict):
        self.config = config
        sf_cfg = config.get("shortform", {})
        sc_cfg = sf_cfg.get("smart_crop", {})

        self.smoothing_factor: float = sc_cfg.get("smoothing_factor", 0.85)
        self.padding_ratio: float = sc_cfg.get("padding_ratio", 1.3)
        self.cat_detector_model: str = sc_cfg.get("cat_detector", "yolov8n")
        self.fallback_mode: str = sc_cfg.get("fallback", "center_crop")
        self.output_resolution: list[int] = sf_cfg.get(
            "output_resolution", [OUT_W, OUT_H]
        )

        # YOLOv8 모델 — lazy load
        self._model = None

        logger.info(
            f"VerticalConverter initialized — "
            f"model={self.cat_detector_model}, "
            f"smoothing={self.smoothing_factor}, "
            f"crop={CROP_W}x{SRC_H} -> {self.output_resolution}"
        )

    def _load_model(self):
        """YOLOv8 모델 로드 (최초 호출 시 1회)."""
        if self._model is not None:
            return
        try:
            from ultralytics import YOLO
            self._model = YOLO(self.cat_detector_model)
            logger.info(f"YOLOv8 model loaded: {self.cat_detector_model}")
        except ImportError:
            logger.error(
                "ultralytics 패키지가 설치되지 않음 — "
                "pip install ultralytics 필요. 센터 크롭으로 폴백."
            )
            self._model = None
        except Exception as e:
            logger.error(f"YOLOv8 모델 로드 실패: {e} — 센터 크롭으로 폴백.")
            self._model = None

    async def convert(self, clip_path: Path, metadata: dict) -> Path:
        """
        16:9 클립을 9:16 세로 영상으로 변환.

        1) YOLOv8로 프레임별 고양이 위치 감지
        2) Kalman filter로 크롭 중심 스무딩
        3) ffmpeg crop+scale 적용

        Parameters
        ----------
        clip_path : Path
            원본 16:9 클립 경로.
        metadata : dict
            이벤트 메타데이터 (cat_id, event_type 등).

        Returns
        -------
        Path
            변환된 9:16 클립 경로 (_vertical 접미사).
        """
        output_path = clip_path.with_stem(f"{clip_path.stem}_vertical")

        logger.info(
            f"[VerticalConverter] Converting: {clip_path.name} -> {output_path.name}"
        )

        try:
            # 1. 고양이 위치 감지 → 프레임별 크롭 중심 계산
            crop_positions = await self._detect_cat_positions(clip_path)

            # 2. Kalman filter 스무딩
            smoothed_center_x = self._smooth_positions(crop_positions)

            # 3. 최종 크롭 X 결정 (평균값 — 단일 crop 필터로 적용)
            avg_center_x = self._compute_crop_center(smoothed_center_x)

            # 4. ffmpeg 크롭 + 스케일 적용
            await self._apply_crop(clip_path, output_path, avg_center_x)

            logger.info(
                f"[VerticalConverter] Done: {output_path.name} "
                f"(crop_center_x={avg_center_x})"
            )
            return output_path

        except Exception as e:
            logger.error(f"[VerticalConverter] Conversion failed: {e}")
            # 폴백: 센터 크롭
            logger.warning("[VerticalConverter] Falling back to center crop")
            await self._apply_crop(clip_path, output_path, SRC_W // 2)
            return output_path

    async def _detect_cat_positions(
        self, clip_path: Path
    ) -> list[CropPosition]:
        """YOLOv8로 프레임별 고양이 중심 X 좌표 감지."""
        self._load_model()

        positions: list[CropPosition] = []

        if self._model is None:
            logger.warning(
                "[VerticalConverter] No YOLO model — using center fallback"
            )
            return positions

        try:
            import cv2

            cap = cv2.VideoCapture(str(clip_path))
            if not cap.isOpened():
                logger.error(f"Cannot open video: {clip_path}")
                return positions

            fps = cap.get(cv2.CAP_PROP_FPS) or 30
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            # 매 프레임 감지하면 느리므로 sample_interval마다 감지
            # 20fps 영상 기준 약 3프레임마다 = ~7fps 감지
            sample_interval = max(1, int(fps / 10))

            frame_idx = 0
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                if frame_idx % sample_interval == 0:
                    pos = await self._detect_single_frame(frame, frame_idx)
                    positions.append(pos)

                frame_idx += 1

            cap.release()

            detected_count = sum(1 for p in positions if p.detected)
            logger.info(
                f"[VerticalConverter] Cat detection: "
                f"{detected_count}/{len(positions)} frames "
                f"({total_frames} total, sampled every {sample_interval})"
            )

        except ImportError:
            logger.error("cv2 (opencv-python) not installed — center fallback")
        except Exception as e:
            logger.error(f"Cat detection failed: {e}")

        return positions

    async def _detect_single_frame(
        self, frame: np.ndarray, frame_idx: int
    ) -> CropPosition:
        """단일 프레임에서 고양이 감지 → CropPosition 반환."""
        # YOLO 추론을 별도 스레드에서 실행 (CPU-bound)
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None, self._yolo_detect, frame
        )

        if result is not None:
            center_x, confidence = result
            return CropPosition(
                frame_idx=frame_idx,
                center_x=center_x,
                confidence=confidence,
                detected=True,
            )

        return CropPosition(
            frame_idx=frame_idx,
            center_x=SRC_W / 2,  # 미감지 시 중앙
            confidence=0.0,
            detected=False,
        )

    def _yolo_detect(
        self, frame: np.ndarray
    ) -> Optional[tuple[float, float]]:
        """
        YOLOv8로 고양이 감지.

        Returns (center_x, confidence) 또는 None.
        COCO 클래스 15 = cat.
        """
        if self._model is None:
            return None

        try:
            results = self._model(frame, verbose=False, conf=0.3)

            best_cat = None
            best_conf = 0.0

            for result in results:
                boxes = result.boxes
                if boxes is None:
                    continue

                for i in range(len(boxes)):
                    cls_id = int(boxes.cls[i].item())
                    conf = float(boxes.conf[i].item())

                    # COCO class 15 = cat
                    if cls_id == 15 and conf > best_conf:
                        # bbox: x1, y1, x2, y2
                        x1, y1, x2, y2 = boxes.xyxy[i].cpu().numpy()
                        center_x = (x1 + x2) / 2

                        # padding 적용 (고양이 주변 여유 공간)
                        bbox_w = (x2 - x1) * self.padding_ratio
                        # 크롭 영역이 고양이를 충분히 포함하는지 확인
                        if bbox_w <= CROP_W:
                            best_cat = center_x
                            best_conf = conf

            if best_cat is not None:
                return (best_cat, best_conf)

        except Exception as e:
            logger.debug(f"YOLO detection error: {e}")

        return None

    def _smooth_positions(
        self, positions: list[CropPosition]
    ) -> list[float]:
        """Kalman filter로 크롭 중심 X 스무딩."""
        if not positions:
            return [SRC_W / 2]

        kf = KalmanFilter1D(smoothing_factor=self.smoothing_factor)
        smoothed: list[float] = []

        for pos in positions:
            if pos.detected:
                sx = kf.step(measurement=pos.center_x)
            else:
                # 미감지 시 예측만 (관성으로 이동)
                sx = kf.step(measurement=None)

            # 경계 클램핑
            sx = max(MIN_X, min(MAX_X, sx))
            smoothed.append(sx)

        return smoothed

    def _compute_crop_center(self, smoothed_positions: list[float]) -> int:
        """
        스무딩된 크롭 중심들로부터 최종 단일 크롭 X 결정.

        단순화된 전략: 가중 평균 사용.
        - 중앙 프레임에 가중치를 더 부여 (이벤트 핵심 부분)
        """
        if not smoothed_positions:
            return SRC_W // 2

        n = len(smoothed_positions)
        if n == 1:
            return int(smoothed_positions[0])

        # 가우시안 가중치: 중앙 프레임에 높은 가중치
        center_idx = n / 2
        sigma = n / 4
        weights = np.array([
            np.exp(-0.5 * ((i - center_idx) / max(sigma, 1)) ** 2)
            for i in range(n)
        ])
        weights /= weights.sum()

        avg_x = float(np.dot(weights, smoothed_positions))
        avg_x = max(MIN_X, min(MAX_X, avg_x))

        return int(round(avg_x))

    async def _apply_crop(
        self,
        input_path: Path,
        output_path: Path,
        center_x: int,
    ):
        """
        ffmpeg로 크롭 + 스케일 적용.

        crop=CROP_W:SRC_H:(center_x - HALF_CROP):0
        scale=OUT_W:OUT_H
        """
        crop_left = max(0, center_x - HALF_CROP)
        # 크롭 영역이 프레임을 벗어나지 않도록
        crop_left = min(crop_left, SRC_W - CROP_W)

        out_w, out_h = self.output_resolution

        cmd = [
            "ffmpeg", "-y",
            "-i", str(input_path),
            "-vf", (
                f"crop={CROP_W}:{SRC_H}:{crop_left}:0,"
                f"scale={out_w}:{out_h}:flags=lanczos"
            ),
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            "-c:a", "aac",
            "-b:a", "128k",
            "-movflags", "+faststart",
            str(output_path),
        ]

        logger.debug(
            f"[VerticalConverter] ffmpeg crop: "
            f"x={crop_left}, w={CROP_W}, "
            f"scale={out_w}x{out_h}"
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
                f"ffmpeg crop failed (rc={proc.returncode}): {error_msg}"
            )

        logger.debug(f"[VerticalConverter] ffmpeg crop done: {output_path}")
