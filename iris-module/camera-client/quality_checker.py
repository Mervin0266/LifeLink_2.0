"""
LifeLink 2.0 - Iris Quality Checker Module
Adapts ISO/IEC 29794-6 quality evaluation routines for the Pi Zero W camera capture pipeline.
"""

from typing import Dict, Any, Optional
import numpy as np

try:
    from .quality import IrisQualityEvaluator
    from . import config
except ImportError:
    from quality import IrisQualityEvaluator
    import config


class QualityChecker:
    """Wrapper around ISO/IEC 29794-6 image evaluation."""

    @staticmethod
    def evaluate_frame(img_bgr: np.ndarray) -> Dict[str, Any]:
        """Runs sharpness, illumination, glare, and resolution evaluation on eye frame."""
        return IrisQualityEvaluator.evaluate(img_bgr)

    @staticmethod
    def is_acceptable(quality_report: Dict[str, Any]) -> bool:
        """Returns True if the frame meets all quality thresholds."""
        return bool(quality_report.get("passed", False))
