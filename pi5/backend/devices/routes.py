"""
LifeLink 2.0 - Peripheral Device Routes
API endpoints for device health, fingerprint enrollment/verification,
iris acquisition, photo capture, and job lifecycle control.
"""

import base64
from flask import Blueprint, request, jsonify, g
from backend.devices.manager import DeviceManager
from backend.auth.rbac import login_required, require_permission, Permissions
from backend.audit.service import AuditService

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

    # Encode template bytes to base64 if pass 3 completed
    b64_template = None
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
            "max_passes": 3,
            "finger_position": finger_position,
            "instruction": res.get("instruction", res.get("message")),
            "template_b64": b64_template
        }
    }), 200


@devices_bp.route("/camera/capture-iris", methods=["POST"])
@login_required
@require_permission(Permissions.REGISTER_PATIENT)
def camera_capture_iris():
    """
    Acquires an iris crop from the camera and returns quality metrics.
    Body:
        eye_side: 'OD' (Right) or 'OS' (Left)
    """
    data = request.get_json() or {}
    eye_side = data.get("eye_side", "OD").upper()

    manager = DeviceManager()
    if manager.is_device_busy("pizero-cam3"):
        return jsonify({"status": "error", "message": "Camera device is busy with another active capture session"}), 409

    job_id = manager.create_job("iris_capture", "pizero-cam3", {"eye_side": eye_side})

    res = manager.camera.capture_iris(eye_side=eye_side)
    if res.get("status") == "completed":
        manager.update_job_status(job_id, "completed", {"eye_side": eye_side, "quality": res["quality"]})
        b64_img = base64.b64encode(res["image_bytes"]).decode("utf-8")
        return jsonify({
            "status": "success",
            "job_id": job_id,
            "eye_side": eye_side,
            "quality": res["quality"],
            "image_b64": b64_img
        }), 200
    else:
        manager.update_job_status(job_id, "failed", {"reasons": res.get("quality", {}).get("rejection_reasons")})
        return jsonify({
            "status": "rejected",
            "job_id": job_id,
            "eye_side": eye_side,
            "quality": res.get("quality"),
            "message": "Quality criteria not met; adjust lighting and eye distance."
        }), 422


@devices_bp.route("/camera/capture-photo", methods=["POST"])
@login_required
def camera_capture_photo():
    """Captures a patient face photograph."""
    manager = DeviceManager()
    if manager.is_device_busy("pizero-cam3"):
        return jsonify({"status": "error", "message": "Camera device is busy with another active capture session"}), 409

    job_id = manager.create_job("camera_photo", "pizero-cam3")
    res = manager.camera.capture_patient_photo()
    if res.get("status") == "completed":
        manager.update_job_status(job_id, "completed")
        b64_img = base64.b64encode(res["image_bytes"]).decode("utf-8")
        return jsonify({
            "status": "success",
            "job_id": job_id,
            "image_b64": b64_img
        }), 200
    return jsonify({"status": "error", "message": "Failed to capture photo"}), 500
