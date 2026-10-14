"""
LifeLink 2.0 - LightIrisNet Segmenter Wrapper
Interfaces with MobileNetV3 DeepLabv3+ model to predict iris/pupil masks and fit boundary ellipses.
Supports physical PyTorch inference with automatic fallback in MOCK_MODE.
"""

import sys
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
import numpy as np
import cv2
import torch
try:
    from backend.config import Config
except ImportError:
    _PI5_ROOT = Path(__file__).resolve().parent.parent
    if str(_PI5_ROOT) not in sys.path:
        sys.path.insert(0, str(_PI5_ROOT))
    from backend.config import Config

LIGHTIRISNET_SRC = Config.BASE_DIR.parent.parent / "LifeLink" / "LightIrisNet" / "src"
if str(LIGHTIRISNET_SRC) not in sys.path and LIGHTIRISNET_SRC.exists():
    sys.path.append(str(LIGHTIRISNET_SRC))


class IrisSegmenter:
    """Wrapper for LightIrisNet MobileNetV3 segmentation network."""

    def __init__(self, checkpoint_path: Optional[str] = None, device: Optional[str] = None):
        self.device = torch.device(device or ("cuda" if torch.cuda.is_available() else "cpu"))
        self.checkpoint_path = Path(checkpoint_path or Config.LIGHTIRISNET_WEIGHTS)
        self.model = None
        self._init_model()

    def _init_model(self):
        """Attempts to load LightIrisNet model weights if available."""
        if not self.checkpoint_path.exists():
            return

        try:
            from irisseg._train_impl import IrisNetDeepLab  # type: ignore
            self.model = IrisNetDeepLab(
                backbone="mobilenetv3",
                use_ellipse=True,
                extra_decoder_conv=True,
                pupil_refine_depth=1,
                pretrained_encoder=False,
            )
            ckpt = torch.load(str(self.checkpoint_path), map_location="cpu")
            state_dict = ckpt.get("model_state", ckpt.get("state_dict", ckpt.get("model", ckpt)))
            self.model.load_state_dict(state_dict, strict=False)
            self.model.to(self.device)
            self.model.eval()
        except Exception as e:
            print(f"[IrisSegmenter] PyTorch weight load skipped: {e}")
            self.model = None

    def segment(self, eye_image_rgb: np.ndarray) -> Dict[str, Any]:
        """
        Segments iris and pupil regions from an RGB eye crop image.
        Returns binary masks and fitted ellipse parameters.
        """
        H, W = eye_image_rgb.shape[:2]

        if self.model is not None:
            try:
                # Real ML inference path
                img = eye_image_rgb.astype(np.float32) / 255.0
                tensor = torch.from_numpy(img.transpose(2, 0, 1)).unsqueeze(0).to(self.device)
                with torch.inference_mode():
                    outputs = self.model(tensor)
                    pred_iris = (torch.sigmoid(outputs["iris"]).squeeze().cpu().numpy() > 0.5).astype(np.uint8)
                    pred_pupil = (torch.sigmoid(outputs["pupil"]).squeeze().cpu().numpy() > 0.5).astype(np.uint8)

                # Fit ellipses
                iris_ellipse = self._fit_ellipse(pred_iris)
                pupil_ellipse = self._fit_ellipse(pred_pupil)
                return {
                    "iris_mask": pred_iris,
                    "pupil_mask": pred_pupil,
                    "iris_ellipse": iris_ellipse,
                    "pupil_ellipse": pupil_ellipse,
                    "mode": "ML_INFERENCE"
                }
            except Exception as e:
                print(f"[IrisSegmenter] ML inference exception ({e}), falling back to geometric estimation")

        # Geometric fallback / Mock mode
        center_x, center_y = W // 2, H // 2
        iris_r = int(min(H, W) * 0.28)
        pupil_r = int(iris_r * 0.35)

        iris_mask = np.zeros((H, W), dtype=np.uint8)
        cv2.circle(iris_mask, (center_x, center_y), iris_r, 1, -1)

        pupil_mask = np.zeros((H, W), dtype=np.uint8)
        cv2.circle(pupil_mask, (center_x, center_y), pupil_r, 1, -1)

        iris_ellipse = ((float(center_x), float(center_y)), (float(iris_r * 2), float(iris_r * 2)), 0.0)
        pupil_ellipse = ((float(center_x), float(center_y)), (float(pupil_r * 2), float(pupil_r * 2)), 0.0)

        return {
            "iris_mask": iris_mask,
            "pupil_mask": pupil_mask,
            "iris_ellipse": iris_ellipse,
            "pupil_ellipse": pupil_ellipse,
            "mode": "GEOMETRIC_FALLBACK"
        }

    def _fit_ellipse(self, mask: np.ndarray) -> Optional[Tuple]:
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if cnts:
            cnt = max(cnts, key=cv2.contourArea)
            if len(cnt) >= 5:
                return cv2.fitEllipse(cnt)
        return None
