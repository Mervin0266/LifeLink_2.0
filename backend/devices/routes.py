"""
LifeLink 2.0 - Peripheral Device Routes
API endpoints for device health, fingerprint enrollment/verification,
iris acquisition, photo capture, and job lifecycle control.
"""

import base64
import threading
import logging
from typing import Tuple, Dict, Any
from flask import Blueprint, request, jsonify, g, Response
from backend.config import Config
from backend.devices.manager import DeviceManager
from backend.auth.rbac import login_required, require_permission, Permissions
from backend.audit.service import AuditService

logger = logging.getLogger("LifeLink.DevicesRoute")
_camera_route_lock = threading.Lock()

devices_bp = Blueprint("devices", __name__, url_prefix="/api/v1/devices")


@devices_bp.route("/health", methods=["GET"])
def health():
    """System and hardware peripheral health diagnostic endpoint."""
    manager = DeviceManager()
    return jsonify({
        "status": "success",
        "health": manager.get_health()
    }), 200


@devices_bp.route("/jobs/<job_id>", methods=["GET"])
@login_required
def get_job(job_id: str):
    """Retrieves status and result of a device job."""
    manager = DeviceManager()
    job = manager.get_job(job_id)
    if not job:
        return jsonify({"status": "error", "message": "Job not found"}), 404
    return jsonify({"status": "success", "job": job}), 200


@devices_bp.route("/jobs/<job_id>/cancel", methods=["POST"])
@login_required
def cancel_job(job_id: str):
    """Cancels an active device job and resets peripheral state."""
    manager = DeviceManager()
    cancelled = manager.cancel_job(job_id)
    if not cancelled:
        return jsonify({"status": "error", "message": "Job cannot be cancelled or was not found"}), 400
    return jsonify({"status": "success", "message": f"Job {job_id} cancelled"}), 200


@devices_bp.route("/fingerprint/enroll-step", methods=["POST"])
@login_required
@require_permission(Permissions.REGISTER_PATIENT)
def fingerprint_enroll_step():
    """
    Executes or advances a guided fingerprint enrollment pass.
    Body:
        finger_position: 'R1'..'R5', 'L1'..'L5'
        pass_number: 1, 2, or 3
        job_id: optional existing job ID
    """
    data = request.get_json() or {}
    finger_position = data.get("finger_position", "R1").upper()
    pass_number = int(data.get("pass_number", 1))
    job_id = data.get("job_id")

    manager = DeviceManager()
    if not job_id:
        if manager.is_device_busy("esp32-gt521f32"):
            return jsonify({"status": "error", "message": "Fingerprint device is busy with another active job"}), 409
        job_id = manager.create_job("fingerprint_enroll", "esp32-gt521f32", {"finger": finger_position})

    if pass_number == 1:
        res = manager.fingerprint.start_enrollment(finger_position)
    else:
        res = manager.fingerprint.advance_enrollment(finger_position, pass_number)

    # Encode template bytes to base64 if pass completed
    b64_template = None
    max_passes = res.get("max_passes", 1 if getattr(Config, "SINGLE_IMPRESSION_ENROLL", False) else 3)
    if res.get("status") == "completed" and "template_bytes" in res:
        b64_template = base64.b64encode(res["template_bytes"]).decode("utf-8")
        # Wipe scratch slot 199 immediately after retrieval
        manager.fingerprint.wipe_scratch_slot(199)
        manager.update_job_status(job_id, "completed", {
            "finger": finger_position,
            "template_size": len(res["template_bytes"])
        })
    elif res.get("status") == "in_progress":
        manager.update_job_status(job_id, "running", {"pass": res.get("pass")})
    elif res.get("status") == "retry":
        manager.update_job_status(job_id, "waiting_for_input", {"retry_reason": res.get("message")})
    else:
        manager.update_job_status(job_id, "failed", {"error": res.get("message")})

    return jsonify({
        "status": "success",
        "job_id": job_id,
        "step_result": {
            "status": res.get("status"),
            "pass": res.get("pass", pass_number),
            "max_passes": max_passes,
            "finger_position": finger_position,
            "instruction": res.get("instruction", res.get("message")),
            "template_b64": b64_template
        }
    }), 200


@devices_bp.route("/fingerprint/cancel", methods=["POST"])
@login_required
def cancel_fingerprint():
    """Cancels any active fingerprint scanning session and ensures sensor LED is OFF."""
    manager = DeviceManager()
    if hasattr(manager.fingerprint, "cancel"):
        manager.fingerprint.cancel()
    else:
        manager.fingerprint.wipe_scratch_slot(199)
        manager.fingerprint.set_led(False)
    return jsonify({"status": "cancelled", "message": "Fingerprint scan cancelled, LED turned OFF"}), 200


@devices_bp.route("/fingerprint/config", methods=["GET"])
def get_fingerprint_config():
    """Returns current fingerprint configuration and mode."""
    return jsonify({
        "status": "success",
        "single_impression_enroll": getattr(Config, "SINGLE_IMPRESSION_ENROLL", False)
    }), 200


@devices_bp.route("/fingerprint/capture-probe", methods=["POST"])
@login_required
def fingerprint_capture_probe():
    """
    Acquires a fresh live fingerprint probe from the connected optical sensor for 1:N retrieval.
    Guarantees:
      - Sensor optical backlight turns ON during acquisition.
      - Patient places finger flat on optical glass prism.
      - Backlight is extinguished immediately upon completion, timeout, or cancellation.
      - Wipes temporary scratch slot 199 immediately.
    """
    manager = DeviceManager()
    status = manager.fingerprint.get_status()
    if not status.get("connected"):
        return jsonify({
            "status": "error",
            "error_type": "HARDWARE_DISCONNECTED",
            "message": "Optical fingerprint sensor is disconnected or unreachable on serial port."
        }), 503

    if manager.is_device_busy("esp32-gt521f32"):
        return jsonify({
            "status": "error",
            "error_type": "DEVICE_BUSY",
            "message": "Fingerprint sensor is busy with another active job."
        }), 409

    job_id = manager.create_job("fingerprint_probe", "esp32-gt521f32", {"action": "retrieval_probe"})
    try:
        res = manager.fingerprint.capture_single_impression("probe")
        res_status = res.get("status")

        if res_status == "completed" and res.get("template_bytes"):
            manager.update_job_status(job_id, "completed", {"template_size": len(res["template_bytes"])})
            b64_tpl = base64.b64encode(res["template_bytes"]).decode("utf-8")
            return jsonify({
                "status": "success",
                "job_id": job_id,
                "template_b64": b64_tpl,
                "template_size": len(res["template_bytes"]),
                "message": "Fingerprint probe acquired successfully from hardware."
            }), 200
        elif res_status == "retry":
            manager.update_job_status(job_id, "failed", {"reason": res.get("message")})
            return jsonify({
                "status": "failed",
                "job_id": job_id,
                "error_type": "NO_FINGER_DETECTED",
                "message": res.get("message", "No finger detected on sensor. Please press finger flat and retry.")
            }), 422
        else:
            err_msg = res.get("message", "Fingerprint acquisition failed")
            manager.update_job_status(job_id, "failed", {"error": err_msg})
            return jsonify({
                "status": "error",
                "job_id": job_id,
                "error_type": "ACQUISITION_FAILED",
                "message": err_msg
            }), 500
    except Exception as exc:
        logger.error(f"[FINGERPRINT ROUTE] Error during probe capture: {exc}", exc_info=True)
        manager.update_job_status(job_id, "failed", {"error": str(exc)})
        return jsonify({
            "status": "error",
            "job_id": job_id,
            "error_type": "INTERNAL_ERROR",
            "message": f"Sensor acquisition error: {str(exc)}"
        }), 500


def _extract_and_validate_iris_template(image_bytes: bytes, eye_side: str) -> Tuple[bool, Dict[str, Any]]:
    """
    Attempts immediate iris segmentation and template extraction on Pi 5.
    Returns (True, template_dict) if a valid iris template was extracted, or (False, error_dict) if extraction failed.
    """
    if not image_bytes:
        return False, {"reason": "No image bytes received from camera"}

    try:
        from backend.biometrics.service import BiometricService
        embedding = BiometricService._resolve_iris_embedding(image_bytes)
        if embedding is not None and len(embedding) > 0:
            return True, {
                "status": "extracted",
                "model_version": "Vis-IrisFormer-v1",
                "embedding_dim": 512,
                "storage_vault": "AES-256-GCM"
            }
        return False, {"reason": "Iris features could not be extracted; boundary or pupil not distinct."}
    except Exception as exc:
        logger.warning(f"[IRIS EXTRACTION] Error during template validation: {exc}")
        return False, {"reason": f"Template extraction error: {str(exc)}"}


@devices_bp.route("/camera/capture-iris", methods=["POST"])
@login_required
@require_permission(Permissions.REGISTER_PATIENT)
def camera_capture_iris():
    """
    Acquires an iris crop from the camera and returns quality metrics and biometric template confirmation.
    Body:
        eye_side: 'OD' (Right) or 'OS' (Left)
    """
    data = request.get_json() or {}
    eye_side = data.get("eye_side", "OD").upper()

    manager = DeviceManager()
    manager.clear_stale_camera_jobs(max_age_seconds=5.0)
    if manager.is_device_busy("camera-substation") or manager.is_device_busy("pizero-cam3"):
        return jsonify({"status": "error", "message": "Camera device is busy with another active capture session"}), 409

    if not _camera_route_lock.acquire(timeout=6.0):
        return jsonify({"status": "error", "message": "Camera device is busy with another active capture session"}), 409

    job_id = manager.create_job("iris_capture", "camera-substation", {"eye_side": eye_side})
    try:
        res = manager.camera.capture_iris(eye_side=eye_side)
        res_status = res.get("status")

        if res_status == "completed" and res.get("image_bytes"):
            image_bytes = res["image_bytes"]
            b64_img = base64.b64encode(image_bytes).decode("utf-8")
            quality = res.get("quality", {})
            template_ok, template_info = _extract_and_validate_iris_template(image_bytes, eye_side)

            if template_ok:
                manager.update_job_status(job_id, "completed", {"eye_side": eye_side, "quality": quality})
                return jsonify({
                    "status": "success",
                    "template_extracted": True,
                    "job_id": job_id,
                    "eye_side": eye_side,
                    "quality": quality,
                    "image_b64": b64_img,
                    "template": template_info
                }), 200
            else:
                reason = template_info.get("reason", "Iris template could not be extracted.")
                manager.update_job_status(job_id, "failed", {"reason": reason})
                return jsonify({
                    "status": "retry",
                    "template_extracted": False,
                    "job_id": job_id,
                    "eye_side": eye_side,
                    "quality": quality,
                    "image_b64": b64_img,
                    "message": reason
                }), 422
        elif res_status == "rejected":
            manager.update_job_status(job_id, "failed", {"reasons": res.get("quality", {}).get("rejection_reasons")})
            b64_img = base64.b64encode(res["image_bytes"]).decode("utf-8") if res.get("image_bytes") else ""
            return jsonify({
                "status": "rejected",
                "template_extracted": False,
                "job_id": job_id,
                "eye_side": eye_side,
                "quality": res.get("quality", {}),
                "image_b64": b64_img,
                "message": res.get("message", "Quality criteria not met; adjust lighting and eye distance.")
            }), 422
        elif res_status == "busy":
            manager.update_job_status(job_id, "failed", {"error": res.get("message")})
            return jsonify({
                "status": "error",
                "job_id": job_id,
                "message": res.get("message", "Camera device is busy with another active capture session")
            }), 409
        elif res_status == "timeout":
            manager.update_job_status(job_id, "failed", {"error": res.get("message")})
            return jsonify({
                "status": "error",
                "job_id": job_id,
                "message": res.get("message", "Camera capture timed out")
            }), 504
        elif res_status == "unavailable":
            manager.update_job_status(job_id, "failed", {"error": res.get("message")})
            return jsonify({
                "status": "error",
                "job_id": job_id,
                "message": res.get("message", "Camera service unavailable on Pi 3B+")
            }), 503
        else:
            err_msg = res.get("message", "Failed to capture iris")
            manager.update_job_status(job_id, "failed", {"error": err_msg})
            return jsonify({
                "status": "error",
                "job_id": job_id,
                "message": err_msg
            }), 500
    except Exception as exc:
        logger.error(f"[CAMERA ROUTE] Uncaught error during iris capture: {exc}", exc_info=True)
        manager.update_job_status(job_id, "failed", {"error": str(exc)})
        return jsonify({
            "status": "error",
            "job_id": job_id,
            "message": f"Camera capture error: {str(exc)}"
        }), 500
    finally:
        _camera_route_lock.release()


@devices_bp.route("/camera/capture-probe", methods=["POST"])
@login_required
def camera_capture_probe():
    """
    Acquires an iris probe from camera hardware for 1:N patient retrieval identification.
    Activates 850nm NIR LED, captures frame, runs quality checks, and returns base64 image probe.
    Body:
        eye_side: 'OD' (Right) or 'OS' (Left) - optional, defaults to 'OD'
    """
    data = request.get_json() or {}
    eye_side = data.get("eye_side", "OD").upper()
    if eye_side not in ("OD", "OS"):
        eye_side = "OD"

    manager = DeviceManager()
    manager.clear_stale_camera_jobs(max_age_seconds=5.0)
    if manager.is_device_busy("camera-substation") or manager.is_device_busy("pizero-cam3"):
        return jsonify({
            "status": "error",
            "error_type": "DEVICE_BUSY",
            "message": "Camera device is busy with another active capture session."
        }), 409

    if not _camera_route_lock.acquire(timeout=6.0):
        return jsonify({
            "status": "error",
            "error_type": "DEVICE_BUSY",
            "message": "Camera device is busy with another active capture session."
        }), 409

    job_id = manager.create_job("iris_probe", "camera-substation", {"action": "retrieval_probe", "eye_side": eye_side})
    try:
        res = manager.camera.capture_iris(eye_side=eye_side)
        res_status = res.get("status")

        if res_status == "completed" and res.get("image_bytes"):
            image_bytes = res["image_bytes"]
            b64_img = base64.b64encode(image_bytes).decode("utf-8")
            quality = res.get("quality", {})
            template_ok, template_info = _extract_and_validate_iris_template(image_bytes, eye_side)

            if template_ok:
                manager.update_job_status(job_id, "completed", {"eye_side": eye_side, "quality": quality})
                return jsonify({
                    "status": "success",
                    "template_extracted": True,
                    "job_id": job_id,
                    "eye_side": eye_side,
                    "quality": quality,
                    "image_b64": b64_img,
                    "message": "Iris probe captured and template extracted successfully."
                }), 200
            else:
                reason = template_info.get("reason", "Iris template could not be extracted.")
                manager.update_job_status(job_id, "failed", {"reason": reason})
                return jsonify({
                    "status": "retry",
                    "template_extracted": False,
                    "job_id": job_id,
                    "eye_side": eye_side,
                    "quality": quality,
                    "image_b64": b64_img,
                    "message": reason
                }), 422
        elif res_status == "rejected":
            manager.update_job_status(job_id, "failed", {"reasons": res.get("quality", {}).get("rejection_reasons")})
            b64_img = base64.b64encode(res["image_bytes"]).decode("utf-8") if res.get("image_bytes") else ""
            return jsonify({
                "status": "failed",
                "template_extracted": False,
                "job_id": job_id,
                "error_type": "QUALITY_REJECTED",
                "eye_side": eye_side,
                "quality": res.get("quality", {}),
                "image_b64": b64_img,
                "message": res.get("message", "Iris probe quality criteria not met; adjust lighting and eye distance.")
            }), 422
        elif res_status == "busy":
            manager.update_job_status(job_id, "failed", {"error": res.get("message")})
            return jsonify({
                "status": "error",
                "job_id": job_id,
                "error_type": "DEVICE_BUSY",
                "message": res.get("message", "Camera device is busy with another active capture session.")
            }), 409
        elif res_status == "timeout":
            manager.update_job_status(job_id, "failed", {"error": res.get("message")})
            return jsonify({
                "status": "error",
                "job_id": job_id,
                "error_type": "CAPTURE_TIMEOUT",
                "message": res.get("message", "Iris camera capture timed out. Ensure eye is positioned 12-15 cm from camera.")
            }), 504
        elif res_status == "unavailable":
            manager.update_job_status(job_id, "failed", {"error": res.get("message")})
            return jsonify({
                "status": "error",
                "job_id": job_id,
                "error_type": "HARDWARE_UNAVAILABLE",
                "message": res.get("message", "Iris camera substation unreachable at 192.168.50.2:5001.")
            }), 503
        else:
            err_msg = res.get("message", "Failed to capture iris probe")
            manager.update_job_status(job_id, "failed", {"error": err_msg})
            return jsonify({
                "status": "error",
                "job_id": job_id,
                "error_type": "ACQUISITION_FAILED",
                "message": err_msg
            }), 500
    except Exception as exc:
        logger.error(f"[CAMERA ROUTE] Uncaught error during iris probe capture: {exc}", exc_info=True)
        manager.update_job_status(job_id, "failed", {"error": str(exc)})
        return jsonify({
            "status": "error",
            "job_id": job_id,
            "error_type": "INTERNAL_ERROR",
            "message": f"Camera acquisition error: {str(exc)}"
        }), 500
    finally:
        _camera_route_lock.release()


@devices_bp.route("/camera/capture-photo", methods=["POST"])
@login_required
def camera_capture_photo():
    """Captures a patient face photograph."""
    manager = DeviceManager()
    manager.clear_stale_camera_jobs(max_age_seconds=5.0)
    if manager.is_device_busy("camera-substation") or manager.is_device_busy("pizero-cam3"):
        return jsonify({"status": "error", "message": "Camera device is busy with another active capture session"}), 409

    if not _camera_route_lock.acquire(timeout=6.0):
        return jsonify({"status": "error", "message": "Camera device is busy with another active capture session"}), 409

    job_id = manager.create_job("camera_photo", "camera-substation")
    try:
        res = manager.camera.capture_patient_photo()
        res_status = res.get("status")

        if res_status == "completed" and res.get("image_bytes"):
            manager.update_job_status(job_id, "completed")
            b64_img = base64.b64encode(res["image_bytes"]).decode("utf-8")
            return jsonify({
                "status": "success",
                "job_id": job_id,
                "image_b64": b64_img
            }), 200
        elif res_status == "busy":
            manager.update_job_status(job_id, "failed", {"error": res.get("message")})
            return jsonify({
                "status": "error",
                "job_id": job_id,
                "message": res.get("message", "Camera device is busy with another active capture session")
            }), 409
        elif res_status == "timeout":
            manager.update_job_status(job_id, "failed", {"error": res.get("message")})
            return jsonify({
                "status": "error",
                "job_id": job_id,
                "message": res.get("message", "Photo capture timed out")
            }), 504
        elif res_status == "unavailable":
            manager.update_job_status(job_id, "failed", {"error": res.get("message")})
            return jsonify({
                "status": "error",
                "job_id": job_id,
                "message": res.get("message", "Camera service unavailable on Pi 3B+")
            }), 503
        else:
            err_msg = res.get("message", "Failed to capture photo")
            manager.update_job_status(job_id, "failed", {"error": err_msg})
            return jsonify({
                "status": "error",
                "job_id": job_id,
                "message": err_msg
            }), 500
    except Exception as exc:
        logger.error(f"[CAMERA ROUTE] Uncaught error during photo capture: {exc}", exc_info=True)
        manager.update_job_status(job_id, "failed", {"error": str(exc)})
        return jsonify({"status": "error", "job_id": job_id, "message": f"Photo capture error: {str(exc)}"}), 500
    finally:
        _camera_route_lock.release()


@devices_bp.route("/camera/stream", methods=["GET"])
def camera_stream():
    """
    Relays continuous live preview MJPEG stream from camera hardware or simulator.
    Query param ?mode=iris (IR LED active on GPIO18) or ?mode=photo (IR LED strictly OFF).
    """
    mode = request.args.get("mode", "iris").lower()
    manager = DeviceManager()

    def generate_frames():
        # Fallback to synthetic stream only when MOCK_MODE is enabled AND not in HARDWARE_MODE
        if Config.MOCK_MODE and not getattr(Config, "HARDWARE_MODE", False):
            import time
            while True:
                if hasattr(manager.camera, "generate_stream_frame"):
                    frame_bytes = manager.camera.generate_stream_frame(mode=mode)
                else:
                    break
                yield (b"--frame\r\n"
                       b"Content-Type: image/jpeg\r\n\r\n" + frame_bytes + b"\r\n")
                time.sleep(0.08)  # ~12 fps
        elif hasattr(manager.camera, "stream_preview"):
            yield from manager.camera.stream_preview(mode=mode)

    return Response(generate_frames(), mimetype="multipart/x-mixed-replace; boundary=frame")


@devices_bp.route("/camera/stop-preview", methods=["POST"])
@login_required
def stop_camera_preview():
    """
    Terminates live preview stream without cancelling active still capture operations.
    Preserves ongoing iris/photo capture jobs.
    """
    manager = DeviceManager()
    if hasattr(manager.camera, "stop_preview"):
        manager.camera.stop_preview()
    return jsonify({"status": "stopped", "message": "Preview stream stopped"}), 200


@devices_bp.route("/camera/cancel", methods=["POST"])
@login_required
def cancel_camera():
    """Explicitly cancels camera session, stops live stream, clears stuck jobs, and extinguishes IR LED."""
    manager = DeviceManager()
    # Cancel any active camera jobs in the local database
    manager.cancel_camera_jobs()
    if hasattr(manager.camera, "cancel"):
        manager.camera.cancel()
    return jsonify({"status": "cancelled", "message": "Camera session cancelled, IR LED OFF"}), 200
