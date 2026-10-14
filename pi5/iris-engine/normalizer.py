"""
LifeLink 2.0 - Daugman's Rubber-Sheet Iris Normalizer
Unwraps the annular iris region between pupil boundary and limbus boundary
into a fixed rectangular polar matrix of 64 x 512 pixels.
"""

from typing import Tuple, Dict, Any, Optional
import numpy as np
import cv2


class IrisNormalizer:
    """Rubber-sheet polar coordinate unwrapping for iris recognition."""

    def __init__(self, target_height: int = 64, target_width: int = 512):
        self.target_height = target_height
        self.target_width = target_width

    def _extract_geometry(
        self,
        mask: np.ndarray,
        ellipse: Optional[Tuple] = None,
    ) -> Tuple[float, float, float]:
        """Extracts center (cx, cy) and radius r from mask or fitted ellipse."""
        if ellipse is not None and len(ellipse) == 3 and ellipse[0][0] > 0:
            (cx, cy), (ma, mi), angle = ellipse
            r = (ma + mi) / 4.0
            return float(cx), float(cy), float(r)

        cnts, _ = cv2.findContours(
            mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
        )
        if cnts:
            cnt = max(cnts, key=cv2.contourArea)
            (cx, cy), radius = cv2.minEnclosingCircle(cnt)
            if radius > 0:
                return float(cx), float(cy), float(radius)

        # Fallback to image center if mask is empty
        H, W = mask.shape[:2]
        return float(W / 2.0), float(H / 2.0), float(min(H, W) / 6.0)

    def normalize(
        self,
        eye_image: np.ndarray,
        iris_mask: np.ndarray,
        pupil_mask: np.ndarray,
        iris_ellipse: Optional[Tuple] = None,
        pupil_ellipse: Optional[Tuple] = None,
    ) -> Dict[str, Any]:
        """
        Normalizes annular iris to rectangular polar strip of target_height x target_width.
        """
        if eye_image.ndim == 3:
            gray = cv2.cvtColor(eye_image, cv2.COLOR_RGB2GRAY)
        else:
            gray = eye_image.copy()

        if gray.dtype != np.uint8:
            gray = (np.clip(gray, 0.0, 1.0) * 255).astype(np.uint8)

        cx_p, cy_p, r_p = self._extract_geometry(pupil_mask, pupil_ellipse)
        cx_i, cy_i, r_i = self._extract_geometry(iris_mask, iris_ellipse)

        if r_i <= r_p:
            r_i = r_p + 10.0  # Prevent division by zero or negative radius

        # Create polar coordinate sampling mesh
        angles = np.linspace(0, 2 * np.pi, self.target_width, endpoint=False)
        rad_samples = np.linspace(0, 1, self.target_height)
        theta_grid, r_grid = np.meshgrid(angles, rad_samples)

        # Boundary mappings
        xp = cx_p + r_p * np.cos(theta_grid)
        yp = cy_p + r_p * np.sin(theta_grid)
        xi = cx_i + r_i * np.cos(theta_grid)
        yi = cy_i + r_i * np.sin(theta_grid)

        # Interpolate points between pupil (r=0) and iris (r=1)
        map_x = ((1 - r_grid) * xp + r_grid * xi).astype(np.float32)
        map_y = ((1 - r_grid) * yp + r_grid * yi).astype(np.float32)

        # Bilinear remap
        normalized_iris = cv2.remap(
            gray,
            map_x,
            map_y,
            interpolation=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )

        return {
            "normalized_iris": normalized_iris,
            "geometry": {
                "pupil": {"cx": cx_p, "cy": cy_p, "r": r_p},
                "iris": {"cx": cx_i, "cy": cy_i, "r": r_i},
            }
        }
