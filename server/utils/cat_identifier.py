"""나나/토토 개체 식별 (Cat-ID) — 외형 기반 CNN 분류."""

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from loguru import logger

try:
    import torch
    import torch.nn.functional as F
    from torchvision import transforms

    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    logger.warning("PyTorch not installed — Cat-ID disabled")


@dataclass
class CatIdentification:
    cat_id: str  # "nana" | "toto" | "unknown"
    confidence: float  # 0.0 ~ 1.0
    name_ko: str
    name_en: str
    icon: str


# 고양이 프로필
CAT_PROFILES = {
    "nana": {"name_ko": "나나", "name_en": "Nana", "icon": "🐱", "pattern": "tabby"},
    "toto": {"name_ko": "토토", "name_en": "Toto", "icon": "🐈\u200d⬛", "pattern": "tuxedo"},
}


class CatIdentifier:
    """
    고양이 개체 식별기.

    2마리만 분류하므로 간단한 CNN으로 충분.
    학습 데이터: 각 고양이 200~500장.
    """

    def __init__(self, config: dict):
        self.config = config
        self.model = None
        self.model_path = Path(config.get("models_dir", "models")) / "cat_id_nana_toto.pt"
        self.confidence_threshold = 0.7
        self.transform = None

        if TORCH_AVAILABLE:
            self.transform = transforms.Compose([
                transforms.ToPILImage(),
                transforms.Resize((224, 224)),
                transforms.ToTensor(),
                transforms.Normalize(
                    mean=[0.485, 0.456, 0.406],
                    std=[0.229, 0.224, 0.225],
                ),
            ])

    def load_model(self):
        """모델 로드 (최초 1회)."""
        if not TORCH_AVAILABLE:
            return

        if self.model_path.exists():
            try:
                self.model = torch.jit.load(str(self.model_path), map_location="cpu")
                self.model.eval()
                logger.info(f"Cat-ID model loaded: {self.model_path}")
            except Exception as e:
                logger.error(f"Failed to load Cat-ID model: {e}")
        else:
            logger.warning(f"Cat-ID model not found: {self.model_path}")

    def identify(self, crop_image: np.ndarray) -> CatIdentification:
        """
        고양이 크롭 이미지 → 개체 식별.

        Args:
            crop_image: BGR 이미지 (고양이 바운딩 박스 크롭)

        Returns:
            CatIdentification with cat_id, confidence, name
        """
        if self.model is None or not TORCH_AVAILABLE:
            return self._unknown()

        try:
            # BGR → RGB
            rgb = crop_image[:, :, ::-1].copy()
            tensor = self.transform(rgb).unsqueeze(0)

            with torch.no_grad():
                logits = self.model(tensor)
                probs = F.softmax(logits, dim=1)
                conf, pred = probs.max(dim=1)

            conf_val = conf.item()
            pred_idx = pred.item()

            if conf_val < self.confidence_threshold:
                return self._unknown()

            cat_id = ["nana", "toto"][pred_idx]
            profile = CAT_PROFILES[cat_id]

            return CatIdentification(
                cat_id=cat_id,
                confidence=conf_val,
                name_ko=profile["name_ko"],
                name_en=profile["name_en"],
                icon=profile["icon"],
            )

        except Exception as e:
            logger.error(f"Cat-ID inference error: {e}")
            return self._unknown()

    def _unknown(self) -> CatIdentification:
        return CatIdentification(
            cat_id="unknown",
            confidence=0.0,
            name_ko="고양이",
            name_en="Cat",
            icon="🐱",
        )
