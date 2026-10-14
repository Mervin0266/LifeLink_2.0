"""
LifeLink 2.0 - Iris Capture Coordinator
Coordinates camera acquisition and 850 nm IR LED synchronization.
Ensures exception-safe LED lifecycle, illumination settling, multi-frame quality screening,
and immediate LED shutoff upon completion, cancellation, or error.
"""

import logging
import threading
import time
from typing import Optional, Dict, Any, Callable, List
import cv2
import numpy as np

try:
    from . import config
    from .ir_led_controller import IRLEDController, get_ir_led_controller
    from .camera_client import CameraClient
    from .quality_checker import QualityChecker
except ImportError:
    import config
    from ir_led_controller import IRLEDController, get_ir_led_controller
    from camera_client import CameraClient
    from quality_checker import QualityChecker

logger = logging.getLogger("LifeLink.IrisCapture")


class IrisCaptureCoordinator:
    """
    Manages the lifecycle of an active iris scanning session.
    
    Guarantees:
    - LED is turned ON only after camera initialization.
    - LED stays ON across multi-frame capture attempts.
    - Guaranteed LED shutoff in finally block under all circumstances (success, failure, cancellation).
    - Cooperative cancellation flag.
    """

    def __init__(
        self,
        camera_client: Optional[CameraClient] = None,
        led_controller: Optional[IRLEDController] = None,
        state_callback: Optional[Callable[[str], None]] = None
    ):
        self.camera = camera_client or CameraClient()
        self.led = led_controller or get_ir_led_controller()
        self.state_callback = state_callback or (lambda s: None)
        self._cancel_event = threading.Event()

    def cancel(self):
        """Signals active capture to abort immediately."""
        logger.info("[CAMERA] Capture cancellation requested")
        self._cancel_event.set()

    def execute_scan(self, eye_side: str = "OD") -> Dict[str, Any]:
        """
        Executes a synchronized iris scanning session.
        
        Lifecycle:
        1. INITIALIZING -> Camera prepared
        2. SCANNING -> IR LED ON (GPIO18 HIGH), settling delay
        3. Multi-frame capture & quality screening while LED is ON
        4. PROCESSING -> IR LED OFF (GPIO18 LOW), best frame selection
        5. TRANSFERRING -> Final preparation for return to Pi 5
        6. COMPLETED / CANCELLED / ERROR -> Final status returned
        """
        if self._cancel_event.is_set():
            logger.info("[CAMERA] Scan was already cancelled prior to execution")
            self.state_callback("CANCELLED")
            self.led.turn_off()
            return {"status": "cancelled", "message": "Scan cancelled before capture"}

        self._cancel_event.clear()
        logger.info(f"[CAMERA] Iris scan requested (eye: {eye_side})")

        # Step 1: Initialize Camera
        self.state_callback("INITIALIZING")
        if not self.camera.initialize():
            logger.error("[CAMERA] Camera initialization failed")
            self.state_callback("ERROR")
            self.led.turn_off()
            return {"status": "error", "message": "Camera initialization failed"}

        if self._cancel_event.is_set():
            self.state_callback("CANCELLED")
            self.led.turn_off()
            return {"status": "cancelled", "message": "Scan cancelled before capture"}

        # Step 2: Activate IR LED & Settle
        self.state_callback("SCANNING")
        logger.info("[CAMERA] Activating IR LED illumination...")
        self.led.turn_on()

        best_frame: Optional[np.ndarray] = None
        best_quality: Dict[str, Any] = {}
        highest_score = -1.0
        attempts_recorded: List[Dict[str, Any]] = []

        try:
            # Allow camera exposure and IR illumination to stabilize
            if config.IR_LED_SETTLE_TIME > 0:
                logger.info(f"[CAMERA] Settling illumination for {config.IR_LED_SETTLE_TIME}s...")
                settle_steps = int(config.IR_LED_SETTLE_TIME / 0.05)
                for _ in range(max(1, settle_steps)):
                    if self._cancel_event.is_set():
                        logger.info("[CAMERA] Cancelled during settle period")
                        self.state_callback("CANCELLED")
                        return {"status": "cancelled", "message": "Scan cancelled during settle"}
                    time.sleep(0.05)

            # Multi-attempt capture loop while IR LED is ON
            max_attempts = max(1, config.MAX_CAPTURE_ATTEMPTS)
            for attempt in range(1, max_attempts + 1):
                if self._cancel_event.is_set():
                    logger.info("[CAMERA] Scan cancelled by user between frames")
                    self.state_callback("CANCELLED")
                    return {"status": "cancelled", "message": "Scan cancelled during capture"}

                logger.info(f"[CAMERA] Capturing iris frame (attempt {attempt}/{max_attempts})...")
                frame_bgr, meta = self.camera.capture_frame()

                if frame_bgr is None:
                    logger.warning(f"[CAMERA] Frame capture failed on attempt {attempt}: {meta.get('error')}")
                    continue

                quality_report = QualityChecker.evaluate_frame(frame_bgr)
                attempts_recorded.append({
                    "attempt": attempt,
                    "passed": quality_report.get("passed", False),
                    "metrics": quality_report.get("metrics", {})
                })

                # Compute heuristic quality ranking score
                metrics = quality_report.get("metrics", {})
                sharpness = metrics.get("sharpness", 0.0)
                glare = metrics.get("glare_percentage", 100.0)
                score = sharpness - (glare * 2.0)

                if score > highest_score:
                    highest_score = score
                    best_frame = frame_bgr
                    best_quality = quality_report

                if quality_report.get("passed", False):
                    logger.info(f"[QUALITY] Frame {attempt} passed quality criteria!")
                    break

        except Exception as exc:
            logger.error(f"[CAMERA] Unhandled exception during iris scanning: {exc}", exc_info=True)
            self.state_callback("ERROR")
            return {"status": "error", "message": f"Scan failed: {str(exc)}"}

        finally:
            # CRITICAL INVARIANT: The IR LED must NEVER remain powered after scanning ends
            logger.info("[CAMERA] Acquisition finished. Deactivating IR LED...")
            self.led.turn_off()
            logger.info("[IR LED] OFF")

        # Step 4: Processing (LED is already safely OFF)
        self.state_callback("PROCESSING")
        logger.info("[QUALITY] Image evaluation complete")

        if best_frame is None:
            self.state_callback("ERROR")
            return {
                "status": "error",
                "message": "No frames could be acquired from camera sensor",
                "attempts": attempts_recorded
            }

        # Step 5: Transferring
        self.state_callback("TRANSFERRING")
        logger.info("[USB] Preparing image payload for Raspberry Pi 5...")
        success, encoded_jpeg = cv2.imencode(".jpg", best_frame)
        jpeg_bytes = encoded_jpeg.tobytes() if success else b""

        # Step 6: Completion
        passed = bool(best_quality.get("passed", False))
        final_status = "completed" if passed else "rejected"
        self.state_callback("COMPLETED" if passed else "IDLE")

        logger.info(f"[CAMERA] Scan finished with status: {final_status}")
        return {
            "status": final_status,
            "eye_side": eye_side,
            "quality": best_quality,
            "image_bytes": jpeg_bytes,
            "attempts": attempts_recorded
        }
