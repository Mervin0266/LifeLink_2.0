"""
LifeLink 2.0 - Pi Zero W Camera & IR LED Service Daemon
Lightweight HTTP service bound to USB gadget Ethernet link (192.168.55.2:5001).
Coordinates Camera Module 3 NoIR and 850 nm IR LED synchronization.
Ensures IR LED is ON only during active iris acquisition, and guarantees OFF
upon completion, cancellation, error, timeout, or application shutdown.
"""

import atexit
import io
import logging
import signal
import sys
import threading
import time
from typing import Dict, Any, Optional

from flask import Flask, jsonify, request, send_file

try:
    from . import config
    from .ir_led_controller import IRLEDController, get_ir_led_controller
    from .camera_client import CameraClient
    from .iris_capture import IrisCaptureCoordinator
    from .photo_capture import PhotoCaptureCoordinator
    from .usb_communication import USBCommunicationHelper
except ImportError:
    import config
    from ir_led_controller import IRLEDController, get_ir_led_controller
    from camera_client import CameraClient
    from iris_capture import IrisCaptureCoordinator
    from photo_capture import PhotoCaptureCoordinator
    from usb_communication import USBCommunicationHelper

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s"
)
logger = logging.getLogger("LifeLink.CameraService")

app = Flask(__name__)

# State definitions
VALID_STATES = {
    "IDLE",
    "INITIALIZING",
    "SCANNING",
    "PROCESSING",
    "TRANSFERRING",
    "COMPLETED",
    "CANCELLED",
    "ERROR"
}

# State management
_state_lock = threading.RLock()
_current_state = "IDLE"
_session_lock = threading.Lock()

# Subsystem singletons
_led_controller = get_ir_led_controller()
_camera_client = CameraClient()
_active_iris_coordinator: Optional[IrisCaptureCoordinator] = None


def set_camera_state(new_state: str):
    """Sets the authoritative camera state and enforces LED state policy."""
    global _current_state
    with _state_lock:
        if new_state in VALID_STATES:
            _current_state = new_state
            logger.info(f"[CAMERA] State changed to: {_current_state}")
            
            # Policy enforcement: IR LED must be OFF in all states except SCANNING
            if _current_state != "SCANNING" and _led_controller.is_on():
                logger.info("[IR LED] Policy enforcement: Ensuring IR LED is OFF in non-scanning state")
                _led_controller.turn_off()


def get_camera_state() -> str:
    """Returns the current camera state."""
    with _state_lock:
        return _current_state


def _safe_log(msg: str):
    """Safely logs message without failing if stderr or handler streams are closed."""
    for h in logger.handlers:
        s = getattr(h, "stream", None)
        if s is not None and getattr(s, "closed", False):
            return
    if hasattr(sys, "stderr") and getattr(sys.stderr, "closed", False):
        return
    if hasattr(sys, "is_finalizing") and sys.is_finalizing():
        return
    try:
        logger.info(msg)
    except Exception:
        pass


def emergency_cleanup():
    """Emergency cleanup callback executed on SIGINT, SIGTERM, or process exit."""
    try:
        _safe_log("\n[CAMERA] Initiating graceful shutdown / emergency cleanup...")
        set_camera_state("IDLE")
        if _active_iris_coordinator is not None:
            _active_iris_coordinator.cancel()
        _led_controller.cleanup()
        _camera_client.release()
        _safe_log("[CAMERA] Cleanup complete. IR LED confirmed OFF.")
    except Exception:
        pass


# Register signal handlers and atexit
signal.signal(signal.SIGINT, lambda s, f: (emergency_cleanup(), sys.exit(0)))
signal.signal(signal.SIGTERM, lambda s, f: (emergency_cleanup(), sys.exit(0)))
atexit.register(emergency_cleanup)


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.route("/health", methods=["GET"])
@app.route("/api/v1/camera/health", methods=["GET"])
def health():
    """Returns health, state, and IR LED diagnostic info."""
    return jsonify(USBCommunicationHelper.format_health_response(
        camera_state=get_camera_state(),
        led_status=_led_controller.get_status()
    )), 200


@app.route("/camera/state", methods=["GET"])
@app.route("/api/v1/camera/state", methods=["GET"])
def get_state_endpoint():
    """Returns the current camera state."""
    return jsonify({
        "state": get_camera_state(),
        "led_active": _led_controller.is_on()
    }), 200


@app.route("/camera/led/status", methods=["GET"])
@app.route("/api/v1/camera/led/status", methods=["GET"])
def led_status_endpoint():
    """Returns authoritative status of the IR LED illumination controller."""
    return jsonify({
        "status": "ok",
        "ir_led": _led_controller.get_status(),
        "camera_state": get_camera_state()
    }), 200


@app.route("/camera/cancel", methods=["POST"])
@app.route("/api/v1/camera/cancel", methods=["POST"])
def cancel_scan():
    """Cancels any active scan session and guarantees IR LED is switched OFF."""
    global _active_iris_coordinator
    logger.info("[CAMERA] Manual scan cancellation requested via API")
    if _active_iris_coordinator is not None:
        _active_iris_coordinator.cancel()
    _led_controller.turn_off()
    set_camera_state("CANCELLED")
    time.sleep(0.1)
    set_camera_state("IDLE")
    return jsonify({
        "status": "cancelled",
        "message": "Scan cancelled, IR LED switched OFF",
        "led_is_on": _led_controller.is_on()
    }), 200


@app.route("/camera/iris/capture", methods=["POST"])
@app.route("/api/v1/camera/iris/capture", methods=["POST"])
def capture_iris():
    """
    Executes an iris scanning session with synchronized IR LED illumination.
    IR LED is ON during active acquisition and strictly OFF upon completion or failure.
    """
    global _active_iris_coordinator

    # Prevent concurrent conflicting scan requests
    if not _session_lock.acquire(blocking=False):
        logger.warning("[CAMERA] Rejected concurrent scan request: session already active")
        return jsonify({
            "status": "error",
            "message": "Camera session already in progress",
            "current_state": get_camera_state()
        }), 409

    try:
        data = request.get_json(silent=True) or {}
        eye_side = data.get("eye_side", "OD")
        include_base64 = data.get("include_base64", False)
        return_binary = request.args.get("format") == "jpeg"

        coordinator = IrisCaptureCoordinator(
            camera_client=_camera_client,
            led_controller=_led_controller,
            state_callback=set_camera_state
        )
        _active_iris_coordinator = coordinator

        # Execute synchronized scan (handles LED ON -> settle -> capture -> LED OFF)
        result = coordinator.execute_scan(eye_side=eye_side)

        if return_binary and result.get("image_bytes"):
            set_camera_state("IDLE")
            return send_file(
                io.BytesIO(result["image_bytes"]),
                mimetype="image/jpeg",
                as_attachment=False
            )

        response_payload = USBCommunicationHelper.format_capture_response(
            result,
            include_image_base64=include_base64
        )
        return jsonify(response_payload), (200 if result.get("status") in ("completed", "rejected") else 500)

    except Exception as exc:
        logger.error(f"[CAMERA] Uncaught exception in capture_iris endpoint: {exc}", exc_info=True)
        set_camera_state("ERROR")
        _led_controller.turn_off()
        return jsonify({
            "status": "error",
            "message": f"Unexpected server error: {str(exc)}",
            "led_is_on": _led_controller.is_on()
        }), 500

    finally:
        # Guarantee LED is OFF and state returns to IDLE
        _led_controller.turn_off()
        _active_iris_coordinator = None
        set_camera_state("IDLE")
        _session_lock.release()


@app.route("/camera/photo/capture", methods=["POST"])
@app.route("/api/v1/camera/photo/capture", methods=["POST"])
def capture_photo():
    """
    Captures patient face portrait under visible illumination with IR LED kept strictly OFF.
    """
    if not _session_lock.acquire(blocking=False):
        return jsonify({
            "status": "error",
            "message": "Camera session already in progress"
        }), 409

    try:
        set_camera_state("INITIALIZING")
        coordinator = PhotoCaptureCoordinator(
            camera_client=_camera_client,
            led_controller=_led_controller
        )

        set_camera_state("SCANNING")
        result = coordinator.capture_photo(enable_ir=False)
        set_camera_state("COMPLETED")

        return_binary = request.args.get("format") == "jpeg"
        if return_binary and result.get("image_bytes"):
            set_camera_state("IDLE")
            return send_file(
                io.BytesIO(result["image_bytes"]),
                mimetype="image/jpeg",
                as_attachment=False
            )

        return jsonify({
            "status": result.get("status", "completed"),
            "message": result.get("message", "Face photo acquired"),
            "led_active": _led_controller.is_on()
        }), 200

    except Exception as exc:
        logger.error(f"[CAMERA] Error capturing patient photo: {exc}", exc_info=True)
        set_camera_state("ERROR")
        _led_controller.turn_off()
        return jsonify({"status": "error", "message": str(exc)}), 500

    finally:
        _led_controller.turn_off()
        set_camera_state("IDLE")
        _session_lock.release()


if __name__ == "__main__":
    logger.info(f"Starting LifeLink 2.0 Camera Service on {config.HOST}:{config.PORT}...")
    app.run(host=config.HOST, port=config.PORT, debug=False)
