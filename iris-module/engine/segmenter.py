"""
LifeLink 2.0 - LightIrisNet Segmenter Wrapper
Runs the trained LightIrisNet (MobileNetV3 DeepLabv3+) network to predict iris and
pupil masks and fit boundary ellipses.

Fail-closed: if the checkpoint, the upstream source tree or a dependency is
missing, construction raises IrisModelUnavailableError; an incompatible
checkpoint raises IrisModelLoadError. There is no geometric fallback: an image
whose iris cannot be segmented raises IrisSegmentationError.

Preprocessing and post-processing mirror upstream LightIrisNet
`irisseg._test_impl.predict` and its documented inference flags:
RGB in [0, 1], ImageNet mean/std, sigmoid > 0.5, soft pupil containment
(inside_thresh 0.85, keep_area_frac 0.90), largest connected component and
ellipse refit (min 20 contour points).
"""

from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np

from backend.config import Config
from iris_errors import IrisInferenceError, IrisModelLoadError, IrisModelUnavailableError, IrisSegmentationError
from iris_model_loading import add_source_path, extract_state_dict, require_file, resolve_device, safe_torch_load

COMPONENT = "LightIrisNet"

_IMAGENET_MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
_IMAGENET_STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


class IrisSegmenter:
    """Wrapper for the trained LightIrisNet MobileNetV3 segmentation network."""

    MODEL_NAME = "LightIrisNet-MobileNetV3"

    # Geometric sanity gates on the post-processed masks. These reject frames
    # where the network found no plausible eye; they are not calibrated
    # biometric quality metrics.
    MIN_IRIS_AREA_RATIO = 0.02
    MIN_PUPIL_AREA_RATIO = 0.003
    MIN_PUPIL_TO_IRIS_RATIO = 0.05
    MAX_PUPIL_TO_IRIS_RATIO = 0.80
    MIN_PUPIL_INSIDE_RATIO = 0.85

    def __init__(
        self,
        checkpoint_path: Optional[str] = None,
        device: Optional[str] = None,
        source_dir: Optional[str] = None,
        thr_iris: float = 0.5,
        thr_pupil: float = 0.5,
    ):
        self.checkpoint_path = Path(checkpoint_path or Config.LIGHTIRISNET_WEIGHTS)
        self.source_dir = Path(source_dir or Config.LIGHTIRISNET_SRC)
        self.thr_iris = thr_iris
        self.thr_pupil = thr_pupil
        self.model = None
        self._load_model(device or Config.IRIS_INFERENCE_DEVICE)

    def _load_model(self, device: Optional[str]) -> None:
        require_file(self.checkpoint_path, COMPONENT, "checkpoint")
        add_source_path(self.source_dir, COMPONENT, "irisseg")
        try:
            import torch  # noqa: F401
            from irisseg._train_impl import IrisNetDeepLab  # type: ignore
            from irisseg._test_impl import apply_containment, largest_cc, refit_ellipse  # type: ignore
        except ImportError as exc:
            raise IrisModelUnavailableError(f"{COMPONENT} model code could not be imported: {exc}", [COMPONENT]) from exc

        self._apply_containment = apply_containment
        self._largest_cc = largest_cc
        self._refit_ellipse = refit_ellipse
        self.device = resolve_device(device)

        # Constructor flags must mirror the training configuration of best_mobilenetv3.pt.
        model = IrisNetDeepLab(
            backbone="mobilenetv3",
            use_ellipse=True,
            extra_decoder_conv=True,
            pupil_refine_depth=1,
            pretrained_encoder=False,
        )
        ckpt = safe_torch_load(self.checkpoint_path, COMPONENT)
        state_dict = extract_state_dict(ckpt, ("model_state", "state_dict", "model"), COMPONENT)
        try:
            model.load_state_dict(state_dict, strict=True)
        except Exception as exc:
            raise IrisModelLoadError(f"{COMPONENT} checkpoint is incompatible with IrisNetDeepLab: {exc}", [COMPONENT]) from exc
        model.to(self.device)
        model.eval()
        self.model = model

    def segment(self, eye_image_rgb: np.ndarray) -> Dict[str, Any]:
        """
        Segments iris and pupil regions from an RGB uint8 eye image (H, W, 3).
        Returns binary masks, fitted ellipses and diagnostics. Raises on failure.
        """
        import torch

        H, W = eye_image_rgb.shape[:2]
        img = eye_image_rgb.astype(np.float32) / 255.0
        img = (img - _IMAGENET_MEAN) / _IMAGENET_STD

        # The encoder downsamples by 32; pad (edge mode) and crop the output back.
        pad_h, pad_w = (-H) % 32, (-W) % 32
        if pad_h or pad_w:
            img = np.pad(img, ((0, pad_h), (0, pad_w), (0, 0)), mode="edge")
        tensor = torch.from_numpy(np.ascontiguousarray(img.transpose(2, 0, 1))).unsqueeze(0).to(self.device)

        try:
            with torch.inference_mode():
                outputs = self.model(tensor)
                iris_prob = torch.sigmoid(outputs["iris"]).float()[0, 0, :H, :W].cpu().numpy()
                pupil_prob = torch.sigmoid(outputs["pupil"]).float()[0, 0, :H, :W].cpu().numpy()
        except Exception as exc:
            raise IrisInferenceError(f"{COMPONENT} forward pass failed: {exc}", [COMPONENT]) from exc

        if not (np.isfinite(iris_prob).all() and np.isfinite(pupil_prob).all()):
            raise IrisInferenceError(f"{COMPONENT} produced non-finite probabilities", [COMPONENT])

        iris_bin = (iris_prob > self.thr_iris).astype(np.uint8)
        pupil_bin = (pupil_prob > self.thr_pupil).astype(np.uint8)
        pupil_adj, containment = self._apply_containment(
            pupil_bin, iris_bin, mode="soft", inside_thresh=0.85, keep_area_frac=0.90
        )
        iris_post = self._largest_cc(iris_bin)
        pupil_post = self._largest_cc(pupil_adj)
        iris_ellipse, iris_refit = self._refit_ellipse(iris_post, min_pts=20)
        pupil_ellipse, pupil_refit = self._refit_ellipse(pupil_post, min_pts=20)

        if iris_ellipse is None or pupil_ellipse is None:
            raise IrisSegmentationError(
                "No iris/pupil boundary could be fitted "
                f"(iris={'ok' if iris_ellipse else 'missing'}, pupil={'ok' if pupil_ellipse else 'missing'})"
            )
        iris_mask = iris_refit.astype(np.uint8)
        pupil_mask = pupil_refit.astype(np.uint8)
        diagnostics = self._validate_masks(iris_mask, pupil_mask)
        diagnostics["containment"] = containment
        diagnostics["iris_prob_mean"] = float(iris_prob[iris_mask > 0].mean())
        diagnostics["pupil_prob_mean"] = float(pupil_prob[pupil_mask > 0].mean())

        return {
            "iris_mask": iris_mask,
            "pupil_mask": pupil_mask,
            "iris_ellipse": iris_ellipse,
            "pupil_ellipse": pupil_ellipse,
            "diagnostics": diagnostics,
            "mode": "ML_INFERENCE",
        }

    def _validate_masks(self, iris_mask: np.ndarray, pupil_mask: np.ndarray) -> Dict[str, float]:
        area = float(iris_mask.size)
        iris_area = float(iris_mask.sum())
        pupil_area = float(pupil_mask.sum())
        iris_ratio = iris_area / area
        pupil_ratio = pupil_area / area
        pupil_to_iris = pupil_area / max(1.0, iris_area)
        inside = float((iris_mask & pupil_mask).sum()) / max(1.0, pupil_area)
        stats = {
            "iris_area_ratio": round(iris_ratio, 5),
            "pupil_area_ratio": round(pupil_ratio, 5),
            "pupil_to_iris_ratio": round(pupil_to_iris, 4),
            "pupil_inside_ratio": round(inside, 4),
        }
        if iris_ratio < self.MIN_IRIS_AREA_RATIO:
            raise IrisSegmentationError(f"Iris region too small ({iris_ratio:.4f} of frame)")
        if pupil_ratio < self.MIN_PUPIL_AREA_RATIO:
            raise IrisSegmentationError(f"Pupil region too small ({pupil_ratio:.4f} of frame)")
        if not (self.MIN_PUPIL_TO_IRIS_RATIO <= pupil_to_iris <= self.MAX_PUPIL_TO_IRIS_RATIO):
            raise IrisSegmentationError(f"Implausible pupil/iris area ratio ({pupil_to_iris:.3f})")
        if inside < self.MIN_PUPIL_INSIDE_RATIO:
            raise IrisSegmentationError(f"Pupil not inside iris ({inside:.3f})")
        return stats
