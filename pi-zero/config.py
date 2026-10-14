"""
LifeLink 2.0 - Pi Zero W Camera & IR LED Configuration
Centralized configuration for camera acquisition, IR illumination, and USB gadget service.
"""

import os

# IR LED Hardware & Synchronization Parameters
IR_LED_ENABLED: bool = os.getenv("IR_LED_ENABLED", "true").lower() in ("true", "1", "yes")
IR_LED_GPIO_PIN: int = int(os.getenv("IR_LED_GPIO_PIN", "18"))  # BCM 18 = Physical Pin 12
IR_LED_ACTIVE_HIGH: bool = os.getenv("IR_LED_ACTIVE_HIGH", "true").lower() in ("true", "1", "yes")
IR_LED_SETTLE_TIME: float = float(os.getenv("IR_LED_SETTLE_TIME", "0.3"))  # Stabilization delay (seconds)
IR_LED_IRIS_MODE_ONLY: bool = os.getenv("IR_LED_IRIS_MODE_ONLY", "true").lower() in ("true", "1", "yes")
MAX_SCAN_TIMEOUT_SECONDS: float = float(os.getenv("MAX_SCAN_TIMEOUT_SECONDS", "15.0"))  # Fail-safe hardware shutoff

# Camera Subsystem Parameters
CAMERA_MODULE: str = os.getenv("CAMERA_MODULE", "IMX708_WIDE_NOIR")
CAMERA_WARMUP_SECONDS: float = float(os.getenv("CAMERA_WARMUP_SECONDS", "0.5"))
DEFAULT_IMAGE_WIDTH: int = int(os.getenv("DEFAULT_IMAGE_WIDTH", "640"))
DEFAULT_IMAGE_HEIGHT: int = int(os.getenv("DEFAULT_IMAGE_HEIGHT", "480"))
MAX_CAPTURE_ATTEMPTS: int = int(os.getenv("MAX_CAPTURE_ATTEMPTS", "3"))

# Quality Evaluation Criteria (ISO/IEC 29794-6)
SHARPNESS_MIN: float = float(os.getenv("SHARPNESS_MIN", "50.0"))
INTENSITY_MIN: float = float(os.getenv("INTENSITY_MIN", "35.0"))
INTENSITY_MAX: float = float(os.getenv("INTENSITY_MAX", "220.0"))
MAX_GLARE_RATIO: float = float(os.getenv("MAX_GLARE_RATIO", "0.05"))
MIN_IRIS_DIAMETER: int = int(os.getenv("MIN_IRIS_DIAMETER", "100"))

# Service & Networking Parameters
HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "5001"))
MOCK_MODE: bool = os.getenv("MOCK_MODE", "false").lower() in ("true", "1", "yes")
