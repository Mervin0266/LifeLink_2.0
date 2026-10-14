"""
LifeLink 2.0 - Camera Client Hardware Abstraction
Interfaces with Raspberry Pi Camera Module 3 Wide NoIR via Picamera2.
Provides graceful synthetic emulation when running in mock mode or on non-RPi hosts.
"""

import logging
import threading
import time
from typing import Optional, Tuple, Dict, Any
import numpy as np
import cv2

try:
    from . import config
except ImportError:
    import config

logger = logging.getLogger("LifeLink.CameraClient")


class CameraClient:
    """
    Hardware abstraction for Camera Module 3 NoIR on Pi Zero W.
    Handles sensor warm-up, frame capture directly to RAM, and resource cleanup.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._picam2 = None
        self._is_hardware: bool = False
        self._is_initialized: bool = False

    def initialize(self) -> bool:
        """Initializes the camera sensor."""
        with self._lock:
            if self._is_initialized:
                return True

            logger.info("[CAMERA] Initializing camera subsystem...")
            try:
                # Attempt to import Picamera2 dynamically on Raspberry Pi OS
                import importlib
                picam2_module = importlib.import_module("picamera2")
                Picamera2 = getattr(picam2_module, "Picamera2")
                picam2 = Picamera2()
                camera_config = picam2.create_still_configuration(
                    main={"size": (config.DEFAULT_IMAGE_WIDTH, config.DEFAULT_IMAGE_HEIGHT), "format": "RGB888"}
                )
                picam2.configure(camera_config)
                picam2.start()
                # Warm-up delay for auto-exposure and sensor calibration
                time.sleep(config.CAMERA_WARMUP_SECONDS)
                self._picam2 = picam2
                self._is_hardware = True
                self._is_initialized = True
                logger.info("[CAMERA] Hardware Picamera2 initialized successfully")
                return True
            except Exception as e:
                logger.warning(f"[CAMERA] Hardware camera unavailable ({e}). Using synthetic frame generator.")
                self._picam2 = None
                self._is_hardware = False
                self._is_initialized = True
                return True

    def capture_frame(self) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
        """
        Captures a single raw frame in RAM (BGR format).
        Returns (frame_bgr, metadata).
        """
        with self._lock:
            if not self._is_initialized:
                if not self.initialize():
                    return None, {"error": "Camera initialization failed"}

            if self._is_hardware and self._picam2 is not None:
                try:
                    # Capture RGB array from Picamera2
                    rgb_array = self._picam2.capture_array()
                    bgr_frame = cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)
                    return bgr_frame, {"hardware": True, "source": "Picamera2-IMX708"}
                except Exception as exc:
                    logger.error(f"[CAMERA] Frame capture error from hardware: {exc}")
                    return None, {"error": str(exc)}
            else:
                # Synthetic realistic test frame
                return self._generate_synthetic_frame(), {"hardware": False, "source": "Synthetic-Simulator"}

    def _generate_synthetic_frame(self) -> np.ndarray:
        """Generates a synthetic eye frame for testing and off-Pi simulation."""
        H, W = config.DEFAULT_IMAGE_HEIGHT, config.DEFAULT_IMAGE_WIDTH
        img = np.full((H, W, 3), (235, 230, 232), dtype=np.uint8)
        cx, cy = W // 2, H // 2
        iris_r, pupil_r = 85, 28

        # Sclera / eye background
        cv2.circle(img, (cx, cy), iris_r, (110, 80, 50), -1)
        for angle in range(0, 360, 6):
            rad = np.radians(angle)
            x1 = int(cx + (pupil_r + 4) * np.cos(rad))
            y1 = int(cy + (pupil_r + 4) * np.sin(rad))
            x2 = int(cx + (iris_r - 2) * np.cos(rad))
            y2 = int(cy + (iris_r - 2) * np.sin(rad))
            cv2.line(img, (x1, y1), (x2, y2), (135, 105, 75), 1)

        cv2.circle(img, (cx, cy), pupil_r, (15, 15, 18), -1)
        # Glare pinpoint
        cv2.circle(img, (cx + 10, cy - 10), 3, (255, 255, 255), -1)
        return img

    def release(self):
        """Releases camera resources."""
        with self._lock:
            if self._picam2 is not None:
                try:
                    self._picam2.stop()
                    self._picam2.close()
                except Exception as e:
                    logger.debug(f"[CAMERA] Error closing picam2: {e}")
                self._picam2 = None
            self._is_initialized = False
            self._is_hardware = False
            logger.info("[CAMERA] Camera resources released")
