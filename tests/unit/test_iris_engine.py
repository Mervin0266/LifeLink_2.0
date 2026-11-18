"""
Unit tests for LifeLink 2.0 Iris ML Pipeline (Normalization, Feature Extraction, Matching).
"""

import pytest
import numpy as np
from pathlib import Path
import sys

_ENGINE_DIR = Path(__file__).resolve().parent.parent.parent / "iris-module" / "engine"
if str(_ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(_ENGINE_DIR))

from normalizer import IrisNormalizer
from recognizer import IrisRecognizer
from service import IrisPipelineService


def test_iris_normalizer_dimensions():
    """Verifies Daugman Rubber-Sheet unwrapping creates exactly 64x512 matrix."""
    normalizer = IrisNormalizer(target_height=64, target_width=512)
    synthetic_eye = np.full((300, 400, 3), 128, dtype=np.uint8)
    iris_mask = np.zeros((300, 400), dtype=np.uint8)
    pupil_mask = np.zeros((300, 400), dtype=np.uint8)

    # Draw pupil and iris disks
    import cv2
    cv2.circle(iris_mask, (200, 150), 80, 1, -1)
    cv2.circle(pupil_mask, (200, 150), 25, 1, -1)

    res = normalizer.normalize(synthetic_eye, iris_mask, pupil_mask)
    norm = res["normalized_iris"]
    assert norm.shape == (64, 512)


def test_iris_recognizer_embedding_shape_and_matching():
    """Verifies feature extractor returns 128x768 embedding and computes cosine similarity."""
    recognizer = IrisRecognizer()
    norm_strip = np.random.randint(0, 255, (64, 512), dtype=np.uint8)
    emb1 = recognizer.extract_features(norm_strip)
    assert emb1.shape == (128, 768)

    # Identical template comparison should yield high similarity (~1.0)
    score_self = recognizer.compare(emb1, emb1)
    assert score_self >= 0.99

    # Different template comparison
    emb2 = np.random.randn(128, 768).astype(np.float32)
    score_diff = recognizer.compare(emb1, emb2)
    assert -1.0 <= score_diff <= 1.0


def test_iris_pipeline_service_end_to_end():
    """Verifies full pipeline service processes synthetic eye image."""
    service = IrisPipelineService()
    eye_rgb = np.random.randint(0, 255, (240, 320, 3), dtype=np.uint8)
    res = service.process_eye_image(eye_rgb, eye_side="OD")
    assert res["eye_side"] == "OD"
    assert res["embedding"].shape == (128, 768)
    assert res["normalized_iris"].shape == (64, 512)
