"""
LifeLink 2.0 - Complete Iris Pipeline Service
Orchestrates segmentation, Daugman normalization, and Vis-IrisFormer feature extraction.
"""

from typing import Dict, Any, Optional
from pathlib import Path
import sys
import numpy as np
import cv2

_ENGINE_DIR = Path(__file__).resolve().parent
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

from segmenter import IrisSegmenter
from normalizer import IrisNormalizer
from recognizer import IrisRecognizer


class IrisPipelineService:
    """End-to-end pipeline for iris segmentation, normalization, and feature extraction."""

    def __init__(self):
        self.segmenter = IrisSegmenter()
        self.normalizer = IrisNormalizer(target_height=64, target_width=512)
        self.recognizer = IrisRecognizer()

    def process_eye_image(self, eye_image_rgb: np.ndarray, eye_side: str = "OD") -> Dict[str, Any]:
        """
        Executes end-to-end iris pipeline on an eye crop image.
        Returns extracted template embedding, normalization strip, and masks.
        """
        # 1. Segmentation
        seg_res = self.segmenter.segment(eye_image_rgb)

        # 2. Polar Normalization
        norm_res = self.normalizer.normalize(
            eye_image=eye_image_rgb,
            iris_mask=seg_res["iris_mask"],
            pupil_mask=seg_res["pupil_mask"],
            iris_ellipse=seg_res.get("iris_ellipse"),
            pupil_ellipse=seg_res.get("pupil_ellipse")
        )

        # 3. Feature Extraction
        embedding = self.recognizer.extract_features(norm_res["normalized_iris"])

        return {
            "eye_side": eye_side,
            "embedding": embedding,
            "embedding_shape": list(embedding.shape),
            "normalized_iris": norm_res["normalized_iris"],
            "geometry": norm_res["geometry"],
            "segmentation_mode": seg_res["mode"]
        }

    def compare_templates(self, template_a: np.ndarray, template_b: np.ndarray) -> float:
        """Compares two templates via patch-wise cosine similarity."""
        return self.recognizer.compare(template_a, template_b)
