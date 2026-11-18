"""
LifeLink 2.0 - Raspberry Pi 3B+ Camera & IR LED Service Daemon
Lightweight HTTP service bound to wired Ethernet link (192.168.50.2:5000 or configurable).
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
import cv2
from typing import Dict, Any, Optional

from flask import Flask, jsonify, request, send_file, Response

try:
    from . import config
    from .ir_led_controller import IRLEDController, get_ir_led_controller
    from .camera_client import CameraClient
    from .iris_capture import IrisCaptureCoordinator
    from .photo_capture import PhotoCaptureCoordinator
    from .usb_communication import CameraCommunicationHelper, USBCommunicationHelper
except ImportError:
    import config
    from ir_led_controller import IRLEDController, get_ir_led_controller
    from camera_client import CameraClient
    from iris_capture import IrisCaptureCoordinator
    from photo_capture import PhotoCaptureCoordinator
    from usb_communication import CameraCommunicationHelper, USBCommunicationHelper

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
    "PREVIEW",
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
_capture_lock = threading.Lock()
_capture_event = threading.Event()
_preview_stop_event = threading.Event()
_active_preview_mode: Optional[str] = None

# Subsystem singletons
_led_controller = get_ir_led_controller()
_camera_client = CameraClient()
_active_iris_coordinator: Optional[IrisCaptureCoordinator] = None


def check_authentication() -> bool:
    """Validates the X-Camera-Token header for protected operations."""
    if app.config.get("TESTING"):
        return True
    if not getattr(config, "REQUIRE_AUTH", True):
        return True
    expected_token = getattr(config, "CAMERA_API_TOKEN", "")
    if not expected_token:
        return True
    provided_token = request.headers.get("X-Camera-Token")
    return bool(provided_token and provided_token == expected_token)


def set_camera_state(new_state: str):
    """Sets the authoritative camera state and enforces LED state policy."""
    global _current_state
    with _state_lock:
        if new_state in VALID_STATES:
            _current_state = new_state
            logger.info(f"[CAMERA] State changed to: {_current_state}")
            
            # Policy enforcement: IR LED must be OFF in all states except SCANNING and PREVIEW
            if _current_state not in ("SCANNING", "PREVIEW") and _led_controller.is_on():
                logger.info("[IR LED] Policy enforcement: Ensuring IR LED is OFF in non-scanning/preview state")
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
    return jsonify(CameraCommunicationHelper.format_health_response(
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
    global _active_iris_coordinator, _active_preview_mode
    if not check_authentication():
        return jsonify({"status": "error", "message": "Unauthorized: missing or invalid X-Camera-Token"}), 401

    logger.info("[CAMERA] Manual scan cancellation requested via API")
    _preview_stop_event.set()
    _active_preview_mode = None
    if _active_iris_coordinator is not None:
        _active_iris_coordinator.cancel()
    _capture_event.clear()
    _led_controller.turn_off()
    set_camera_state("CANCELLED")
    time.sleep(0.05)
    set_camera_state("IDLE")
    return jsonify({
        "status": "cancelled",
        "message": "Scan cancelled, IR LED switched OFF",
        "led_is_on": _led_controller.is_on()
    }), 200


@app.route("/camera/preview/stop", methods=["POST"])
@app.route("/api/v1/camera/preview/stop", methods=["POST"])
def stop_preview():
    """Explicitly terminates live preview and turns off IR LED."""
    global _active_preview_mode
    _preview_stop_event.set()
    _active_preview_mode = None
    # Only extinguish LED and reset state if still capture is not currently in progress
    if not _capture_event.is_set():
        _led_controller.turn_off()
        set_camera_state("IDLE")
    return jsonify({"status": "stopped", "led_is_on": _led_controller.is_on()}), 200


@app.route("/camera/stream", methods=["GET"])
@app.route("/api/v1/camera/stream", methods=["GET"])
def stream_camera():
    """
    Continuous MJPEG live preview stream for terminal eye/face alignment.
    Supports ?mode=iris (IR LED active on GPIO18) or ?mode=photo (IR LED strictly OFF).
    Shares the underlying Picamera2 session with still capture operations.
    """
    global _active_preview_mode
    mode = request.args.get("mode", "iris").lower()

    if _active_preview_mode and _active_preview_mode != mode:
        return jsonify({
            "status": "error",
            "message": f"Camera is already streaming in {_active_preview_mode} mode"
        }), 409

    _preview_stop_event.clear()
    _active_preview_mode = mode

    def generate():
        global _active_preview_mode
        is_iris = (mode == "iris")
        try:
            set_camera_state("PREVIEW")
            if is_iris:
                _led_controller.turn_on()
            else:
                _led_controller.turn_off()

            if not _camera_client.initialize():
                logger.error("[CAMERA] Failed to initialize camera for live stream")
                return

            frame_interval = 0.08  # ~12 FPS
            while not _preview_stop_event.is_set():
                t0 = time.time()
                # Yield sensor bandwidth briefly if a still capture is acquiring frames
                if _capture_event.is_set():
                    time.sleep(0.04)
                    continue

                frame_bgr, _ = _camera_client.capture_frame()
                if frame_bgr is not None:
                    if is_iris:
                        h, w = frame_bgr.shape[:2]
                        cx, cy = w // 2, h // 2
                        cv2.circle(frame_bgr, (cx, cy), 85, (0, 255, 0), 1)
                        cv2.circle(frame_bgr, (cx, cy), 28, (0, 255, 0), 1)
                    ok, jpeg = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    if ok:
                        frame_bytes = jpeg.tobytes()
                        yield (b"--frame\r\n"
                               b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n")
                elapsed = time.time() - t0
                if elapsed < frame_interval:
                    time.sleep(frame_interval - elapsed)
        finally:
            _active_preview_mode = None
            if not _capture_event.is_set():
                _led_controller.turn_off()
                set_camera_state("IDLE")

    return Response(generate(), mimetype="multipart/x-mixed-replace; boundary=frame")


@app.route("/camera/iris/capture", methods=["POST"])
@app.route("/api/v1/camera/iris/capture", methods=["POST"])
def capture_iris():
    """
    Executes an iris scanning session with synchronized IR LED illumination.
    Shares the active camera instance with live preview if preview is running.
    """
    global _active_iris_coordinator, _active_preview_mode

    if not check_authentication():
        return jsonify({"status": "error", "message": "Unauthorized: missing or invalid X-Camera-Token"}), 401

    # Check for incompatible mode: cannot capture iris when photo preview is active
    if _active_preview_mode == "photo":
        return jsonify({
            "status": "error",
            "message": "Camera is currently active in Photo Preview mode. Switch to Iris mode first."
        }), 409

    # Acquire capture lock (non-blocking) - prevents concurrent conflicting scan requests
    if not _capture_lock.acquire(blocking=False):
        logger.warning("[CAMERA] Rejected concurrent scan request: capture session already active")
        return jsonify({
            "status": "error",
            "message": "Camera capture session already in progress",
            "current_state": get_camera_state()
        }), 409

    try:
        # Signal the live preview loop to briefly yield frame production
        _capture_event.set()
        set_camera_state("SCANNING")

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

        is_preview_running = (_active_preview_mode == "iris" and not _preview_stop_event.is_set())
        # Execute synchronized scan, keeping LED on if preview continues
        result = coordinator.execute_scan(eye_side=eye_side, keep_led_on=is_preview_running)

        if return_binary:
            if result.get("status") == "completed" and result.get("image_bytes"):
                response = send_file(
                    io.BytesIO(result["image_bytes"]),
                    mimetype="image/jpeg",
                    as_attachment=False
                )
                q_metrics = result.get("quality", {}).get("metrics", {})
                response.headers["X-Quality-Sharpness"] = str(q_metrics.get("sharpness", 75.0))
                response.headers["X-Quality-Intensity"] = str(q_metrics.get("mean_intensity", 120.0))
                response.headers["X-Quality-Glare"] = str(q_metrics.get("glare_percentage", 0.5))
                response.headers["X-Quality-Diameter"] = str(q_metrics.get("estimated_diameter", 120))
                response.headers["X-Quality-Passed"] = "true"
                return response
            elif result.get("status") == "rejected":
                return jsonify({
                    "status": "rejected",
                    "eye_side": eye_side,
                    "quality": result.get("quality", {}),
                    "message": "Quality criteria not met; adjust lighting and eye distance."
                }), 422
            else:
                return jsonify({
                    "status": "error",
                    "eye_side": eye_side,
                    "message": result.get("message", "Iris capture failed")
                }), 500

        response_payload = CameraCommunicationHelper.format_capture_response(
            result,
            include_image_base64=include_base64
        )
        return jsonify(response_payload), (200 if result.get("status") == "completed" else (422 if result.get("status") == "rejected" else 500))

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
        _active_iris_coordinator = None
        _capture_event.clear()
        # If iris preview is still running, restore PREVIEW state and ensure IR LED stays ON!
        if _active_preview_mode == "iris" and not _preview_stop_event.is_set():
            _led_controller.turn_on()
            set_camera_state("PREVIEW")
        else:
            _led_controller.turn_off()
            set_camera_state("IDLE")
        _capture_lock.release()


@app.route("/camera/photo/capture", methods=["POST"])
@app.route("/api/v1/camera/photo/capture", methods=["POST"])
def capture_photo():
    """
    Captures patient face portrait under visible illumination with IR LED kept strictly OFF.
    Shares the active camera instance with photo live preview if preview is running.
    """
    global _active_preview_mode

    if not check_authentication():
        return jsonify({"status": "error", "message": "Unauthorized: missing or invalid X-Camera-Token"}), 401

    # Check for incompatible mode: cannot capture photo when iris preview (with IR illumination) is active
    if _active_preview_mode == "iris":
        return jsonify({
            "status": "error",
            "message": "Camera is currently streaming in Iris mode with IR illumination. Switch to Photo mode first."
        }), 409

    if not _capture_lock.acquire(blocking=False):
        return jsonify({
            "status": "error",
            "message": "Camera capture session already in progress"
        }), 409

    try:
        _capture_event.set()
        set_camera_state("SCANNING")
        # Ensure IR LED is strictly OFF
        _led_controller.turn_off()

        coordinator = PhotoCaptureCoordinator(
            camera_client=_camera_client,
            led_controller=_led_controller
        )

        result = coordinator.capture_photo(enable_ir=False)

        return_binary = request.args.get("format") == "jpeg"
        if return_binary and result.get("image_bytes"):
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
        _capture_event.clear()
        if _active_preview_mode == "photo" and not _preview_stop_event.is_set():
            set_camera_state("PREVIEW")
        else:
            set_camera_state("IDLE")
        _capture_lock.release()


if __name__ == "__main__":
    logger.info(f"Starting LifeLink 2.0 Raspberry Pi 3B+ Camera Service on {config.HOST}:{config.PORT}...")
    app.run(host=config.HOST, port=config.PORT, debug=False)
