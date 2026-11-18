"""
LifeLink 2.0 - Complete Iris Pipeline Service
Orchestrates segmentation, Daugman normalization, and Vis-IrisFormer feature extraction.

Construction loads both trained models and raises an IrisEngineError subclass
if either cannot be loaded (all failing components are reported together).
`process_eye_image` either returns a genuine model embedding or raises.
"""

from typing import Dict, Any
from pathlib import Path
import sys
import numpy as np

_ENGINE_DIR = Path(__file__).resolve().parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

from iris_errors import IrisEngineError, IrisModelLoadError, IrisModelUnavailableError, InvalidIrisImageError, IrisSegmentationError
from segmenter import IrisSegmenter
from normalizer import IrisNormalizer
from recognizer import IrisRecognizer, STRIP_SHAPE

MIN_EYE_IMAGE_SIDE = 64
MIN_STRIP_STD = 1.0  # a (near-)constant strip means the sampled region has no texture


def validate_eye_image(eye_image: np.ndarray) -> np.ndarray:
    """Returns an RGB uint8 (H, W, 3) copy of the input or raises InvalidIrisImageError."""
    if not isinstance(eye_image, np.ndarray) or eye_image.size == 0:
        raise InvalidIrisImageError("Eye image is empty or not an array")
    if eye_image.dtype != np.uint8:
        raise InvalidIrisImageError(f"Eye image dtype {eye_image.dtype}, expected uint8")
    if eye_image.ndim == 2:
        eye_image = np.stack([eye_image] * 3, axis=-1)
    elif eye_image.ndim == 3 and eye_image.shape[2] == 4:
        eye_image = eye_image[:, :, :3]
    elif not (eye_image.ndim == 3 and eye_image.shape[2] == 3):
        raise InvalidIrisImageError(f"Eye image shape {eye_image.shape} is not grayscale, RGB or RGBA")
    h, w = eye_image.shape[:2]
    if min(h, w) < MIN_EYE_IMAGE_SIDE:
        raise InvalidIrisImageError(f"Eye image {w}x{h} is smaller than {MIN_EYE_IMAGE_SIDE}px")
    if float(eye_image.std()) == 0.0:
        raise InvalidIrisImageError("Eye image is uniform (no content)")
    return np.ascontiguousarray(eye_image)


class IrisPipelineService:
    """End-to-end pipeline for iris segmentation, normalization, and feature extraction."""

    def __init__(self):
        errors = []
        self.segmenter = self.recognizer = None
        try:
            self.segmenter = IrisSegmenter()
        except IrisEngineError as exc:
            errors.append(exc)
        try:
            self.recognizer = IrisRecognizer()
        except IrisEngineError as exc:
            errors.append(exc)
        if errors:
            components = [c for e in errors for c in e.components]
            detail = "; ".join(str(e) for e in errors)
            error_cls = IrisModelLoadError if any(isinstance(e, IrisModelLoadError) for e in errors) else IrisModelUnavailableError
            raise error_cls(detail, components)
        self.normalizer = IrisNormalizer(target_height=STRIP_SHAPE[0], target_width=STRIP_SHAPE[1])

    @property
    def model_version(self) -> str:
        return f"{self.segmenter.MODEL_NAME}+{self.recognizer.model_version}"

    def process_eye_image(self, eye_image_rgb: np.ndarray, eye_side: str = "OD") -> Dict[str, Any]:
        """
        Executes the end-to-end iris pipeline on an RGB uint8 eye image.
        Returns the extracted template embedding, normalization strip and geometry.
        Raises IrisEngineError subclasses; never returns a partial or synthetic result.
        """
        eye_image_rgb = validate_eye_image(eye_image_rgb)

        # 1. Segmentation (trained LightIrisNet)
        seg_res = self.segmenter.segment(eye_image_rgb)

        # 2. Polar Normalization
        norm_res = self.normalizer.normalize(
            eye_image=eye_image_rgb,
            iris_mask=seg_res["iris_mask"],
            pupil_mask=seg_res["pupil_mask"],
            iris_ellipse=seg_res.get("iris_ellipse"),
            pupil_ellipse=seg_res.get("pupil_ellipse")
        )
        strip = norm_res["normalized_iris"]
        if strip.shape != STRIP_SHAPE or float(strip.std()) < MIN_STRIP_STD:
            raise IrisSegmentationError(
                f"Normalization produced a degenerate strip (shape={strip.shape}, std={float(strip.std()):.3f})"
            )

        # 3. Feature Extraction (trained Vis-IrisFormer)
        embedding = self.recognizer.extract_features(strip)

        return {
            "eye_side": eye_side,
            "embedding": embedding,
            "embedding_shape": list(embedding.shape),
            "normalized_iris": strip,
            "geometry": norm_res["geometry"],
            "segmentation_mode": seg_res["mode"],
            "segmentation_diagnostics": seg_res["diagnostics"],
            "model_version": self.model_version,
        }

    def compare_templates(self, template_a: np.ndarray, template_b: np.ndarray) -> float:
        """Compares two templates via patch-wise cosine similarity."""
        return self.recognizer.compare(template_a, template_b)
