"""
LifeLink 2.0 - Admin Dashboard Routes
Implements:
  - System Overview KPI widgets
  - Patient Lifecycle Management (search, view metadata, edit, archive, deletion request)
  - Multi-stage Deletion Request State Machine (Request -> Legal Hold Check -> Secondary Approval -> Tombstone)
  - Staff Account and Role Administration
  - Device Status and Diagnostics
  - Sync Outbox and Conflict Explorer
  - Tamper-Evident Audit Explorer
"""

import uuid
import datetime
import json
from flask import Blueprint, request, jsonify, g
from backend.database.connection import Database
from backend.auth.rbac import (
    login_required,
    require_role,
    require_permission,
    Roles,
    Permissions
)
from backend.auth.security import SecurityUtils
from backend.audit.service import AuditService
from backend.devices.manager import DeviceManager

admin_bp = Blueprint("admin", __name__, url_prefix="/api/v1/admin")


@admin_bp.route("/overview", methods=["GET"])
@login_required
@require_role(Roles.RECORDS_ADMIN, Roles.SYSTEM_ADMIN)
def overview():
    """Returns real-time KPI metrics for the Admin Dashboard."""
    # 1. Patient Counts
    p_counts = Database.execute_one("""
    SELECT 
        COUNT(*) as total_patients,
        SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active_patients,
        SUM(CASE WHEN status = 'archived' THEN 1 ELSE 0 END) as archived_patients,
        SUM(CASE WHEN status = 'deletion_pending' THEN 1 ELSE 0 END) as deletion_pending_patients
    FROM patients_cache;
    """) or {}

    # 2. Staff Counts
    s_counts = Database.execute_one("SELECT COUNT(*) as total_staff FROM staff_accounts WHERE is_active = 1;") or {}

    # 3. Biometric Completion Statistics
    b_counts = Database.execute_one("""
    SELECT 
        COUNT(DISTINCT patient_id) as patients_with_fingerprints
    FROM fingerprint_templates;
    """) or {}

    # 4. Sync Outbox Counts
    sync_counts = Database.execute_one("""
    SELECT 
        SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending_sync,
        SUM(CASE WHEN status = 'conflict' THEN 1 ELSE 0 END) as sync_conflicts
    FROM sync_outbox;
    """) or {}

    # 5. Device Health
    device_health = DeviceManager().get_health()

    # 6. Recent Audit Events
    recent_audits = Database.execute_query("""
    SELECT id, actor_id, actor_role, action, target_type, target_id, timestamp
    FROM audit_events
    ORDER BY timestamp DESC
    LIMIT 6;
    """)

    return jsonify({
        "status": "success",
        "kpis": {
            "total_patients": p_counts.get("total_patients", 0),
            "active_patients": p_counts.get("active_patients", 0),
            "archived_patients": p_counts.get("archived_patients", 0),
            "deletion_pending": p_counts.get("deletion_pending_patients", 0),
            "total_staff": s_counts.get("total_staff", 0),
            "enrolled_biometrics": b_counts.get("patients_with_fingerprints", 0),
            "pending_sync": sync_counts.get("pending_sync", 0),
            "sync_conflicts": sync_counts.get("sync_conflicts", 0)
        },
        "devices": device_health,
        "recent_audits": recent_audits
    }), 200


# ---------------------------------------------------------------------------
# Patient Lifecycle Management
# ---------------------------------------------------------------------------

@admin_bp.route("/patients", methods=["GET"])
@login_required
@require_role(Roles.RECORDS_ADMIN, Roles.SYSTEM_ADMIN)
def list_admin_patients():
    """Lists and filters patient records with biometric metadata (no raw templates)."""
    status_filter = request.args.get("status")
    search = request.args.get("search", "").strip()

    query = """
    SELECT 
        p.id, p.lifelink_id, p.full_name, p.dob, p.gender, p.blood_type, p.phone, p.status, p.version, p.updated_at,
        (SELECT COUNT(*) FROM fingerprint_templates WHERE patient_id = p.id) as finger_count,
        (SELECT COUNT(*) FROM iris_templates WHERE patient_id = p.id) as iris_count
    FROM patients_cache p
    WHERE 1=1
    """
    params = []
    if status_filter:
        query += " AND p.status = ?"
        params.append(status_filter)
    if search:
        query += " AND (p.full_name LIKE ? OR p.lifelink_id LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])

    query += " ORDER BY p.updated_at DESC LIMIT 50;"
    patients = Database.execute_query(query, tuple(params))
    return jsonify({"status": "success", "patients": patients}), 200


@admin_bp.route("/patients/<patient_id>/archive", methods=["POST"])
@login_required
@require_permission(Permissions.ARCHIVE_PATIENT)
def archive_patient(patient_id: str):
    """Archives an active patient record with documented reason."""
    data = request.get_json() or {}
    reason = data.get("reason", "").strip()
    if not reason:
        return jsonify({"status": "error", "message": "Documented reason is mandatory for record archival"}), 400

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    Database.execute_commit("UPDATE patients_cache SET status = 'archived', updated_at = ? WHERE id = ?;", (now, patient_id))

    # Queue sync outbox
    Database.execute_commit("""
    INSERT INTO sync_outbox (id, operation_id, table_name, record_id, action, payload_json, status, created_at)
    VALUES (?, ?, 'patients', ?, 'ARCHIVE', ?, 'pending', ?);
    """, (str(uuid.uuid4()), str(uuid.uuid4()), patient_id, json.dumps({"reason": reason}), now))

    AuditService.log(
        action="ARCHIVE_PATIENT",
        target_type="patient",
        target_id=patient_id,
        details={"reason": reason},
        actor_id=g.current_user["staff_id"],
        actor_role=g.current_user["role"]
    )
    return jsonify({"status": "success", "message": f"Patient {patient_id} has been archived."}), 200


@admin_bp.route("/patients/<patient_id>/deletion-requests", methods=["POST"])
@login_required
@require_permission(Permissions.REQUEST_DELETION)
def request_patient_deletion(patient_id: str):
    """
    Initiates a controlled deletion request:
    Requires documented rationale and verification of legal retention holds.
    """
    data = request.get_json() or {}
    reason = data.get("reason", "").strip()
    legal_hold_confirmed = data.get("legal_hold_confirmed", False)

    if not reason:
        return jsonify({"status": "error", "message": "Documented reason is mandatory for deletion request"}), 400
    if not legal_hold_confirmed:
        return jsonify({"status": "error", "message": "Confirmation that no legal retention holds apply is required"}), 400

    req_id = str(uuid.uuid4())
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    staff_id = g.current_user["staff_id"]

    Database.execute_commit("""
    INSERT INTO deletion_requests (id, patient_id, requested_by_staff_id, reason, legal_hold_checked, status, created_at)
    VALUES (?, ?, ?, ?, 1, 'pending_approval', ?);
    """, (req_id, patient_id, staff_id, reason, now))

    Database.execute_commit("UPDATE patients_cache SET status = 'deletion_pending', updated_at = ? WHERE id = ?;", (now, patient_id))

    AuditService.log(
        action="REQUEST_PATIENT_DELETION",
        target_type="patient",
        target_id=patient_id,
        details={"deletion_request_id": req_id, "reason": reason},
        actor_id=staff_id,
        actor_role=g.current_user["role"]
    )

    return jsonify({
        "status": "success",
        "deletion_request_id": req_id,
        "message": "Deletion request created. Requires secondary administrative approval before erasure."
    }), 202


@admin_bp.route("/deletion-requests", methods=["GET"])
@login_required
@require_role(Roles.SYSTEM_ADMIN, Roles.RECORDS_ADMIN)
def list_deletion_requests():
    """Lists pending and historical deletion requests."""
    query = """
    SELECT d.*, p.lifelink_id, p.full_name, s.full_name as requester_name
    FROM deletion_requests d
    JOIN patients_cache p ON d.patient_id = p.id
    JOIN staff_accounts s ON d.requested_by_staff_id = s.id
    ORDER BY d.created_at DESC;
    """
    requests = Database.execute_query(query)
    return jsonify({"status": "success", "deletion_requests": requests}), 200


@admin_bp.route("/deletion-requests/<req_id>/approve", methods=["POST"])
@login_required
@require_role(Roles.SYSTEM_ADMIN)
def approve_patient_deletion(req_id: str):
    """
    Secondary administrative approval for deletion request:
    Zeroizes local biometric templates, records deletion tombstone, queues cloud erasure.
    """
    req = Database.execute_one("SELECT * FROM deletion_requests WHERE id = ?;", (req_id,))
    if not req or req["status"] != "pending_approval":
        return jsonify({"status": "error", "message": "Pending deletion request not found"}), 404

    patient_id = req["patient_id"]
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    staff_id = g.current_user["staff_id"]

    # Prevent self-approval (must be secondary approver)
    if req["requested_by_staff_id"] == staff_id:
        return jsonify({"status": "error", "message": "Secondary approval policy requires a different administrator"}), 403

    # 1. Zeroize local biometric templates
    Database.execute_commit("DELETE FROM fingerprint_templates WHERE patient_id = ?;", (patient_id,))
    Database.execute_commit("DELETE FROM iris_templates WHERE patient_id = ?;", (patient_id,))

    # 2. Mark patient as deleted_tombstone
    Database.execute_commit("UPDATE patients_cache SET status = 'deleted_tombstone', full_name = '[DELETED]', updated_at = ? WHERE id = ?;", (now, patient_id))

    # 3. Mark deletion request approved
    Database.execute_commit("UPDATE deletion_requests SET status = 'approved', approved_by_staff_id = ?, processed_at = ? WHERE id = ?;", (staff_id, now, req_id))

    # 4. Queue cloud deletion tombstone in sync outbox
    Database.execute_commit("""
    INSERT INTO sync_outbox (id, operation_id, table_name, record_id, action, payload_json, status, created_at)
    VALUES (?, ?, 'patients', ?, 'DELETE_TOMBSTONE', ?, 'pending', ?);
    """, (str(uuid.uuid4()), str(uuid.uuid4()), patient_id, json.dumps({"reason": req["reason"]}), now))

    AuditService.log(
        action="APPROVE_PATIENT_DELETION",
        target_type="patient",
        target_id=patient_id,
        details={"deletion_request_id": req_id, "approved_by": staff_id},
        actor_id=staff_id,
        actor_role=g.current_user["role"]
    )

    return jsonify({
        "status": "success",
        "message": f"Patient {patient_id} biometrics zeroized and record archived with deletion tombstone."
    }), 200


# ---------------------------------------------------------------------------
# Staff Account Administration (System Admin only)
# ---------------------------------------------------------------------------

@admin_bp.route("/staff", methods=["GET"])
@login_required
@require_role(Roles.SYSTEM_ADMIN)
def list_staff():
    """Lists staff accounts."""
    staff = Database.execute_query("SELECT id, username, email, full_name, role, is_active, created_at FROM staff_accounts ORDER BY created_at DESC;")
    return jsonify({"status": "success", "staff": staff}), 200


@admin_bp.route("/staff", methods=["POST"])
@login_required
@require_role(Roles.SYSTEM_ADMIN)
def create_staff():
    """Creates a new staff account."""
    data = request.get_json() or {}
    username = data.get("username", "").strip()
    email = data.get("email", "").strip().lower()
    full_name = data.get("full_name", "").strip()
    role = data.get("role", "").strip()
    password = data.get("password", "")

    if not username or not email or not full_name or not role or not password:
        return jsonify({"status": "error", "message": "All fields are required"}), 400

    if role not in Roles.ALL:
        return jsonify({"status": "error", "message": f"Invalid role: {role}"}), 400

    staff_id = str(uuid.uuid4())
    pw_hash = SecurityUtils.hash_password(password)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    try:
        Database.execute_commit("""
        INSERT INTO staff_accounts (id, username, email, full_name, role, password_hash, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?);
        """, (staff_id, username, email, full_name, role, pw_hash, now, now))
    except Exception as e:
        return jsonify({"status": "error", "message": f"Username or email already exists ({e})"}), 409

    AuditService.log(
        action="CREATE_STAFF_ACCOUNT",
        target_type="staff",
        target_id=staff_id,
        details={"username": username, "role": role},
        actor_id=g.current_user["staff_id"],
        actor_role=g.current_user["role"]
    )
    return jsonify({"status": "success", "message": f"Staff account {username} created", "staff_id": staff_id}), 201


@admin_bp.route("/audit", methods=["GET"])
@login_required
@require_role(Roles.SYSTEM_ADMIN, Roles.RECORDS_ADMIN)
def get_audit_logs():
    """Explores audit trail logs with filtering."""
    action_filter = request.args.get("action")
    query = "SELECT * FROM audit_events WHERE 1=1"
    params = []
    if action_filter:
        query += " AND action = ?"
        params.append(action_filter)
    query += " ORDER BY timestamp DESC LIMIT 100;"

    logs = Database.execute_query(query, tuple(params))
    return jsonify({"status": "success", "audit_logs": logs}), 200


@admin_bp.route("/sync", methods=["GET"])
@login_required
@require_role(Roles.SYSTEM_ADMIN, Roles.RECORDS_ADMIN)
def get_sync_status():
    """Inspects pending outbox queue and conflicts."""
    outbox = Database.execute_query("SELECT * FROM sync_outbox ORDER BY created_at DESC LIMIT 50;")
    conflicts = Database.execute_query("SELECT * FROM sync_conflicts WHERE resolved = 0;")
    return jsonify({
        "status": "success",
        "pending_outbox": outbox,
        "conflicts": conflicts
    }), 200
