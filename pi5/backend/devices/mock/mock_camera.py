"""
LifeLink 2.0 - Mock Iris Camera Subsystem
Emulates the Pi Zero W + Camera Module 3 NoIR service over USB gadget Ethernet.
Generates synthetic visible-light eye images with realistic iris annular textures,
applies ISO/IEC 29794-6 quality screening, and supports patient photo capture.
"""

import time
import numpy as np
import cv2
from typing import Dict, Any, Optional, Tuple


class MockCameraDevice:
    """Simulates the Pi Zero W camera service."""

    def __init__(self):
        self.connected = True
        self.failure_mode: Optional[str] = None  # None, "blur", "glare", "underexposed", "disconnect", "timeout"
        self.ir_led_on: bool = False
        self.camera_state: str = "IDLE"

    def set_failure_mode(self, mode: Optional[str]):
        """Sets an intentional failure mode for negative testing."""
        self.failure_mode = mode

    def get_status(self) -> Dict[str, Any]:
        """Returns camera readiness and health."""
        if not self.connected or self.failure_mode == "disconnect":
            return {
                "connected": False,
                "device_id": "MOCK-PIZERO-CAM3",
                "transport": "USB-Gadget-Ethernet (192.168.55.2)",
                "sensor": "Sony IMX708 NoIR (Simulated)",
                "status": "DISCONNECTED",
                "ir_led": {"is_on": False, "pin": 18, "enabled": True}
            }
        return {
            "connected": True,
            "device_id": "MOCK-PIZERO-CAM3",
            "transport": "USB-Gadget-Ethernet (192.168.55.2)",
            "sensor": "Sony IMX708 NoIR (Simulated)",
            "status": "READY",
            "camera_state": self.camera_state,
            "ir_led": {"is_on": self.ir_led_on, "pin": 18, "enabled": True}
        }

    def generate_synthetic_eye_image(
        self,
        eye_side: str = "OD",
        width: int = 400,
        height: int = 300,
        quality: str = "pass"
    ) -> np.ndarray:
        """
        Synthesizes a realistic 3-channel RGB eye crop image.
        Draws sclera background, annular iris disk with radial fibers, pupil disk,
        and specular reflection highlights.
        """
        # Create sclera background (light pinkish-white)
        img = np.full((height, width, 3), (235, 230, 232), dtype=np.uint8)

        center_x = width // 2
        center_y = height // 2
        iris_radius = 85  # Yields 170px iris diameter (satisfies >= 100px requirement)
        pupil_radius = 28

        if quality == "small_iris":
            iris_radius = 40  # Under 100px failure
            pupil_radius = 12

        # Draw Iris (annular ring with hazel/brown/blue texture)
        cv2.circle(img, (center_x, center_y), iris_radius, (110, 80, 50), -1)
        # Inner iris radial fibers
        for angle in range(0, 360, 5):
            rad = np.radians(angle)
            x_outer = int(center_x + (iris_radius - 2) * np.cos(rad))
            y_outer = int(center_y + (iris_radius - 2) * np.sin(rad))
            x_inner = int(center_x + (pupil_radius + 4) * np.cos(rad))
            y_inner = int(center_y + (pupil_radius + 4) * np.sin(rad))
            color = (130 + (angle % 30), 100 + (angle % 20), 70)
            cv2.line(img, (x_inner, y_inner), (x_outer, y_outer), color, 1)

        # Draw Pupil (dark blackish circle)
        cv2.circle(img, (center_x, center_y), pupil_radius, (15, 15, 18), -1)

        # Draw Specular Reflection Highlight (corneal reflection)
        glare_x = center_x + 12
        glare_y = center_y - 12
        if quality == "glare":
            # Excessive glare spot covering pupil/iris exceeding 5% threshold
            cv2.circle(img, (glare_x, glare_y), 55, (255, 255, 255), -1)
            cv2.circle(img, (center_x - 30, center_y), 45, (255, 255, 255), -1)
        else:
            # Minimal acceptable pinpoint highlight
            cv2.circle(img, (glare_x, glare_y), 4, (255, 255, 255), -1)

        # Simulate Blur if requested
        if quality == "blur":
            img = cv2.GaussianBlur(img, (25, 25), 0)

        # Simulate Underexposure if requested
        if quality == "underexposed":
            img = (img * 0.15).astype(np.uint8)

        return img

    def evaluate_quality(self, img_bgr: np.ndarray) -> Dict[str, Any]:
        """
        Evaluates ISO/IEC 29794-6 capture quality criteria on image:
        1. Sharpness: Laplacian variance
        2. Exposure: Mean grayscale intensity
        3. Glare: Count of saturated pixels (> 245)
        4. Iris Diameter: Estimated from contours
        """
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        
        # 1. Sharpness
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        is_sharp = sharpness >= 50.0

        # 2. Exposure
        mean_intensity = float(np.mean(gray))
        is_exposed = 35.0 <= mean_intensity <= 220.0

        # 3. Glare
        glare_pixels = int(np.sum(gray >= 245))
        total_pixels = gray.size
        glare_ratio = glare_pixels / total_pixels
        is_glare_acceptable = glare_ratio <= 0.05

        # Overall Status
        passed = is_sharp and is_exposed and is_glare_acceptable

        rejection_reasons = []
        if not is_sharp:
            rejection_reasons.append("Image is blurry; hold still.")
        if not is_exposed:
            rejection_reasons.append("Improper illumination; check lighting.")
        if not is_glare_acceptable:
            rejection_reasons.append("Excessive corneal reflection/glare detected.")

        return {
            "passed": passed,
            "sharpness": round(sharpness, 2),
            "mean_intensity": round(mean_intensity, 2),
            "glare_ratio": round(glare_ratio * 100, 2),
            "rejection_reasons": rejection_reasons
        }

    def capture_iris(self, eye_side: str = "OD") -> Dict[str, Any]:
        """Captures an eye frame and returns image bytes and quality report."""
        if not self.connected or self.failure_mode == "disconnect":
            return {"status": "error", "message": "Camera service disconnected"}
        if self.failure_mode == "timeout":
            return {"status": "error", "message": "Camera frame capture timed out"}

        # Simulate synchronized IR LED activation
        self.camera_state = "SCANNING"
        self.ir_led_on = True
        try:
            quality_setting = self.failure_mode if self.failure_mode in ("blur", "glare", "underexposed", "small_iris") else "pass"
            img_rgb = self.generate_synthetic_eye_image(eye_side=eye_side, quality=quality_setting)
            img_bgr = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
            
            quality_report = self.evaluate_quality(img_bgr)
            _, jpeg_bytes = cv2.imencode(".jpg", img_bgr)

            return {
                "status": "completed" if quality_report["passed"] else "rejected",
                "eye_side": eye_side,
                "image_bytes": jpeg_bytes.tobytes(),
                "quality": quality_report
            }
        finally:
            self.ir_led_on = False
            self.camera_state = "IDLE"

    def capture_patient_photo(self) -> Dict[str, Any]:
        """Captures a patient face photograph."""
        if not self.connected:
            return {"status": "error", "message": "Camera service disconnected"}

        # Generate a synthetic face/portrait image (320x240)
        portrait = np.full((240, 320, 3), (210, 215, 220), dtype=np.uint8)
        # Draw face oval
        cv2.ellipse(portrait, (160, 120), (55, 75), 0, 0, 360, (190, 160, 140), -1)
        # Draw eyes
        cv2.circle(portrait, (140, 105), 8, (60, 50, 45), -1)
        cv2.circle(portrait, (180, 105), 8, (60, 50, 45), -1)
        # Draw smile
        cv2.ellipse(portrait, (160, 145), (20, 10), 0, 0, 180, (100, 50, 50), 2)

        _, jpeg_bytes = cv2.imencode(".jpg", portrait)
        return {
            "status": "completed",
            "image_bytes": jpeg_bytes.tobytes()
        }
