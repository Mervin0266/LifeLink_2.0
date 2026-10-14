"""
LifeLink 2.0 - Biometric Identification and Verification Routes
API endpoints for 1:N candidate identification search and 1:1 confirmation.
"""

from flask import Blueprint, request, jsonify, g
from backend.biometrics.service import BiometricService
from backend.auth.rbac import login_required, require_permission, Permissions
from backend.audit.service import AuditService

biometrics_bp = Blueprint("biometrics", __name__, url_prefix="/api/v1")


@biometrics_bp.route("/identify", methods=["POST"])
@biometrics_bp.route("/biometrics/identify", methods=["POST"])
@login_required
def identify_patient():
    """
    Executes 1:N biometric candidate identification search.
    Body:
        biometric_type: 'fingerprint' | 'iris'
        probe_b64: base64 encoded template / embedding
    """
    data = request.get_json() or {}
    b_type = data.get("biometric_type", "").lower()
    probe_b64 = data.get("probe_b64", "")

    if b_type not in ("fingerprint", "iris") or not probe_b64:
        return jsonify({
            "status": "error",
            "message": "Invalid request: biometric_type ('fingerprint' or 'iris') and probe_b64 are required."
        }), 400

    result = BiometricService.identify_1_to_n(b_type, probe_b64)

    AuditService.log(
        action=f"BIOMETRIC_IDENTIFY_{b_type.upper()}",
        target_type="biometrics",
        target_id=result.get("candidates", [{}])[0].get("patient_id") if result.get("candidates") else "no_match",
        details={"outcome": result["outcome"], "candidate_count": len(result.get("candidates", []))},
        actor_id=g.current_user["staff_id"],
        actor_role=g.current_user["role"]
    )

    return jsonify({
        "status": "success",
        "identification": result
    }), 200


@biometrics_bp.route("/verify", methods=["POST"])
@biometrics_bp.route("/biometrics/verify", methods=["POST"])
@login_required
def verify_patient():
    """
    Executes 1:1 confirmation against a known patient record.
    Body:
        patient_id: string UUID
        biometric_type: 'fingerprint' | 'iris'
        probe_b64: base64 template / embedding
        feature_position: optional 'R1'..'L5' or 'OD'/'OS'
    """
    data = request.get_json() or {}
    patient_id = data.get("patient_id")
    b_type = data.get("biometric_type", "").lower()
    probe_b64 = data.get("probe_b64", "")
    position = data.get("feature_position", "R1")

    if not patient_id or b_type not in ("fingerprint", "iris") or not probe_b64:
        return jsonify({
            "status": "error",
            "message": "patient_id, biometric_type, and probe_b64 are required."
        }), 400

    if b_type == "fingerprint":
        result = BiometricService.verify_fingerprint_1_to_1(patient_id, probe_b64)
    else:
        result = BiometricService.verify_iris_1_to_1(patient_id, probe_b64, eye_side=position)

    AuditService.log(
        action=f"BIOMETRIC_VERIFY_{b_type.upper()}",
        target_type="patient",
        target_id=patient_id,
        details={"matched": result["matched"], "confidence": result["confidence"]},
        actor_id=g.current_user["staff_id"],
        actor_role=g.current_user["role"]
    )

    return jsonify({
        "status": "success",
        "verification": result
    }), 200
