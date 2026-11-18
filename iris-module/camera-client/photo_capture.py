"""
LifeLink 2.0 - Patient Photo Capture Coordinator
Captures visible-light patient profile photographs with IR illumination strictly OFF.
"""

import logging
from typing import Optional, Dict, Any
import cv2
import numpy as np

try:
    from . import config
    from .camera_client import CameraClient
    from .ir_led_controller import IRLEDController, get_ir_led_controller
except ImportError:
    import config
    from camera_client import CameraClient
    from ir_led_controller import IRLEDController, get_ir_led_controller

logger = logging.getLogger("LifeLink.PhotoCapture")


class PhotoCaptureCoordinator:
    """
    Handles visible-spectrum patient portrait photographs.
    Ensures IR LEDs remain OFF so photos use natural illumination without NIR color distortion.
    """

    def __init__(
        self,
        camera_client: Optional[CameraClient] = None,
        led_controller: Optional[IRLEDController] = None
    ):
        self.camera = camera_client or CameraClient()
        self.led = led_controller or get_ir_led_controller()

    def capture_photo(self, enable_ir: bool = False) -> Dict[str, Any]:
        """
        Captures a portrait photo.
        Enforces that IR LED is OFF unless explicitly overridden and permitted by configuration.
        """
        logger.info("[CAMERA] Patient profile photo capture requested")

        # By default, verify IR illumination is OFF
        should_illuminate = enable_ir and not config.IR_LED_IRIS_MODE_ONLY
        if not should_illuminate and self.led.is_on():
            logger.warning("[IR LED] IR LED was active; shutting down before visible-light portrait capture")
            self.led.turn_off()

        try:
            if should_illuminate:
                self.led.turn_on()

            if not self.camera.initialize():
                return {"status": "error", "message": "Camera initialization failed"}

            frame_bgr, meta = self.camera.capture_frame()
            if frame_bgr is None:
                return {"status": "error", "message": meta.get("error", "Frame acquisition failed")}

            success, encoded_jpeg = cv2.imencode(".jpg", frame_bgr)
            jpeg_bytes = encoded_jpeg.tobytes() if success else b""

            logger.info("[CAMERA] Patient photo capture complete (IR LED: OFF)")
            return {
                "status": "completed",
                "message": "Face photo acquired",
                "image_bytes": jpeg_bytes,
                "led_active": False
            }
        finally:
            if should_illuminate:
                self.led.turn_off()
