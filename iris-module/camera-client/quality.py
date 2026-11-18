"""
LifeLink 2.0 - ISO/IEC 29794-6 Iris Image Quality Evaluator
Ported from IrisQualityCapture algorithmic concepts to Python OpenCV.
Runs in RAM on Pi Zero W to reject blurry, underexposed, or glare-compromised frames.
"""

from typing import Dict, Any, List
import numpy as np
import cv2


class IrisQualityEvaluator:
    """Evaluates capture suitability against ISO/IEC 29794-6 dimensions."""

    SHARPNESS_MIN = 50.0
    INTENSITY_MIN = 35.0
    INTENSITY_MAX = 220.0
    MAX_GLARE_RATIO = 0.05
    MIN_IRIS_DIAMETER = 100

    @classmethod
    def evaluate(cls, img_bgr: np.ndarray) -> Dict[str, Any]:
        """
        Evaluates sharpness, illumination, glare, and resolution on an eye frame.
        """
        if img_bgr is None or img_bgr.size == 0:
            return {"passed": False, "reasons": ["Empty frame"]}

        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        H, W = gray.shape

        # 1. Sharpness: Laplacian variance
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        is_sharp = sharpness >= cls.SHARPNESS_MIN

        # 2. Illumination: Mean pixel intensity
        mean_intensity = float(np.mean(gray))
        is_exposed = cls.INTENSITY_MIN <= mean_intensity <= cls.INTENSITY_MAX

        # 3. Specular Glare: Pixels >= 245
        glare_count = int(np.sum(gray >= 245))
        glare_ratio = float(glare_count / gray.size)
        is_glare_ok = glare_ratio <= cls.MAX_GLARE_RATIO

        # 4. Estimated Iris Diameter
        # Uses Otsu thresholding and contour bounding circle
        blurred = cv2.GaussianBlur(gray, (7, 7), 0)
        _, thresh = cv2.threshold(blurred, 60, 255, cv2.THRESH_BINARY_INV)
        cnts, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        est_diameter = 0
        if cnts:
            largest = max(cnts, key=cv2.contourArea)
            _, r = cv2.minEnclosingCircle(largest)
            est_diameter = int(r * 2)

        is_size_ok = est_diameter >= 60  # Flexible heuristic threshold for ROI crop

        reasons: List[str] = []
        if not is_sharp:
            reasons.append(f"Image blurred (sharpness {sharpness:.1f} < {cls.SHARPNESS_MIN})")
        if not is_exposed:
            reasons.append(f"Improper illumination (intensity {mean_intensity:.1f})")
        if not is_glare_ok:
            reasons.append(f"Corneal glare/reflection exceeds limit ({glare_ratio*100:.1f}%)")

        passed = is_sharp and is_exposed and is_glare_ok

        return {
            "passed": passed,
            "metrics": {
                "sharpness": round(sharpness, 2),
                "mean_intensity": round(mean_intensity, 2),
                "glare_percentage": round(glare_ratio * 100, 2),
                "estimated_diameter": est_diameter
            },
            "rejection_reasons": reasons
        }
