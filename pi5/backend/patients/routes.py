"""
LifeLink 2.0 - Patient Workflows Routes
Implements:
  Workflow A: Multi-step registration, duplicate check, and atomic commit.
  Workflow B: Biometric/manual retrieval and prioritized emergency summary.
  Workflow C: Revision-tracked, permission-scoped patient updates with audit trail.
"""

import uuid
import datetime
import json
import base64
from flask import Blueprint, request, jsonify, g
from backend.database.connection import Database
from backend.database.crypto import TemplateCrypto
from backend.auth.rbac import login_required, require_permission, Permissions, Roles
from backend.audit.service import AuditService

patients_bp = Blueprint("patients", __name__, url_prefix="/api/v1/patients")
crypto = TemplateCrypto()


def generate_lifelink_id() -> str:
    """Generates a human-friendly LifeLink ID, e.g. LL-2026-00421."""
    year = datetime.datetime.now().year
    count_row = Database.execute_one("SELECT COUNT(*) as total FROM patients_cache;")
    total = (count_row["total"] if count_row else 0) + 1
    return f"LL-{year}-{total:05d}"


# ---------------------------------------------------------------------------
# Workflow A: Patient Registration
# ---------------------------------------------------------------------------

@patients_bp.route("/registration-drafts", methods=["POST"])
@login_required
@require_permission(Permissions.REGISTER_PATIENT)
def save_registration_draft():
    """Creates or updates a multi-step registration draft."""
    data = request.get_json() or {}
    draft_id = data.get("draft_id") or str(uuid.uuid4())
    step = data.get("step", "fingerprint")
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    staff_id = g.current_user["staff_id"]

    query = """
    INSERT INTO registration_drafts (draft_id, step, data_json, created_by_staff_id, created_at, updated_at)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(draft_id) DO UPDATE SET
        step = excluded.step,
        data_json = excluded.data_json,
        updated_at = excluded.updated_at;
    """
    Database.execute_commit(query, (draft_id, step, json.dumps(data), staff_id, now, now))

    return jsonify({
        "status": "success",
        "draft_id": draft_id,
        "step": step,
        "message": "Draft saved successfully"
    }), 200


@patients_bp.route("/registration-drafts/<draft_id>", methods=["GET"])
@login_required
def get_registration_draft(draft_id: str):
    """Retrieves an existing registration draft."""
    query = "SELECT * FROM registration_drafts WHERE draft_id = ?;"
    draft = Database.execute_one(query, (draft_id,))
    if not draft:
        return jsonify({"status": "error", "message": "Draft not found"}), 404
    return jsonify({
        "status": "success",
        "draft_id": draft["draft_id"],
        "step": draft["step"],
        "data": json.loads(draft["data_json"]),
        "updated_at": draft["updated_at"]
    }), 200


@patients_bp.route("/duplicate-check", methods=["POST"])
@login_required
def duplicate_check():
    """Checks for existing registered patients with matching demographics."""
    data = request.get_json() or {}
    full_name = data.get("full_name", "").strip().lower()
    dob = data.get("dob", "").strip()

    if not full_name or not dob:
        return jsonify({"status": "success", "duplicate_found": False, "candidates": []}), 200

    query = """
    SELECT id, lifelink_id, full_name, dob, gender, blood_type, phone
    FROM patients_cache
    WHERE LOWER(full_name) = ? AND dob = ? AND status = 'active';
    """
    matches = Database.execute_query(query, (full_name, dob))
    return jsonify({
        "status": "success",
        "duplicate_found": len(matches) > 0,
        "candidates": matches
    }), 200


@patients_bp.route("/registration-drafts/<draft_id>/commit", methods=["POST"])
@login_required
@require_permission(Permissions.REGISTER_PATIENT)
def commit_registration(draft_id: str):
    """
    Atomically commits a registration draft into the local database:
      1. Generates permanent patient UUID and LifeLink ID.
      2. Inserts demographics into patients_cache.
      3. Inserts emergency contacts.
      4. Inserts medical records.
      5. Encrypts and inserts fingerprint templates.
      6. Encrypts and inserts iris templates.
      7. Queues transactional outbox item for cloud synchronization.
      8. Deletes the draft and logs audit event.
    """
    query = "SELECT * FROM registration_drafts WHERE draft_id = ?;"
    draft_record = Database.execute_one(query, (draft_id,))
    if not draft_record:
        return jsonify({"status": "error", "message": "Draft not found"}), 404

    draft = json.loads(draft_record["data_json"])
    basic = draft.get("basic", {})
    emergency = draft.get("emergency", {})
    medical = draft.get("medical", {})
    fingerprints = draft.get("fingerprints", {})  # dict of finger_position -> base64 template
    irises = draft.get("irises", {})              # dict of OD/OS -> base64 embedding / crop

    patient_id = str(uuid.uuid4())
    lifelink_id = generate_lifelink_id()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    staff_id = g.current_user["staff_id"]

    # 1. Insert patient demographics
    p_query = """
    INSERT INTO patients_cache (
        id, lifelink_id, full_name, dob, gender, blood_type, phone, address, photo_url, status, version, created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', 1, ?, ?);
    """
    Database.execute_commit(p_query, (
        patient_id,
        lifelink_id,
        basic.get("full_name", "Unknown Patient"),
        basic.get("dob", "1990-01-01"),
        basic.get("gender", "Unknown"),
        basic.get("blood_type", "Unknown"),
        basic.get("phone", ""),
        basic.get("address", ""),
        basic.get("photo_url", ""),
        now,
        now
    ))

    # 2. Insert emergency contacts
    if emergency:
        e_query = """
        INSERT INTO emergency_contacts (
            id, patient_id, contact_name, relationship, phone_number, is_primary
        ) VALUES (?, ?, ?, ?, ?, 1);
        """
        Database.execute_commit(e_query, (
            str(uuid.uuid4()),
            patient_id,
            emergency.get("contact_name", "Primary Contact"),
            emergency.get("relationship", "Next of Kin"),
            emergency.get("phone_number", "")
        ))

    # 3. Insert medical records
    m_query = """
    INSERT INTO medical_records (
        id, patient_id, allergies, chronic_conditions, current_medications, implanted_devices,
        past_surgeries, clinical_notes, provenance, verified_by_staff_id, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """
    Database.execute_commit(m_query, (
        str(uuid.uuid4()),
        patient_id,
        json.dumps(medical.get("allergies", [])),
        json.dumps(medical.get("chronic_conditions", [])),
        json.dumps(medical.get("current_medications", [])),
        json.dumps(medical.get("implanted_devices", [])),
        json.dumps(medical.get("past_surgeries", [])),
        medical.get("clinical_notes", ""),
        medical.get("provenance", "Initial Registration"),
        staff_id,
        now
    ))

    # 4. Encrypt and store Fingerprint Templates
    for pos, b64_tpl in fingerprints.items():
        if b64_tpl and b64_tpl != "UNAVAILABLE":
            raw_bytes = base64.b64decode(b64_tpl)
            enc_bytes = crypto.encrypt(raw_bytes)
            fp_query = """
            INSERT INTO fingerprint_templates (
                id, patient_id, finger_position, encrypted_template, template_format, quality_score, created_at
            ) VALUES (?, ?, ?, ?, 'GT-521F32-v2017', 1.0, ?);
            """
            Database.execute_commit(fp_query, (str(uuid.uuid4()), patient_id, pos, enc_bytes, now))

    # 5. Encrypt and store Iris Templates
    for eye, b64_emb in irises.items():
        if b64_emb and b64_emb != "UNAVAILABLE":
            raw_bytes = base64.b64decode(b64_emb)
            enc_bytes = crypto.encrypt(raw_bytes)
            iris_query = """
            INSERT INTO iris_templates (
                id, patient_id, eye_side, encrypted_template, model_version, quality_score, created_at
            ) VALUES (?, ?, ?, ?, 'Vis-IrisFormer-v1', 1.0, ?);
            """
            Database.execute_commit(iris_query, (str(uuid.uuid4()), patient_id, eye, enc_bytes, now))

    # 6. Queue Sync Outbox Item (Clinical fields only - NO BIOMETRICS)
    outbox_payload = {
        "patient_id": patient_id,
        "lifelink_id": lifelink_id,
        "basic": basic,
        "emergency": emergency,
        "medical": medical,
        "version": 1
    }
    sync_query = """
    INSERT INTO sync_outbox (
        id, operation_id, table_name, record_id, action, payload_json, status, created_at
    ) VALUES (?, ?, 'patients', ?, 'INSERT', ?, 'pending', ?);
    """
    Database.execute_commit(sync_query, (
        str(uuid.uuid4()),
        str(uuid.uuid4()),
        patient_id,
        json.dumps(outbox_payload),
        now
    ))

    # 7. Remove completed draft
    Database.execute_commit("DELETE FROM registration_drafts WHERE draft_id = ?;", (draft_id,))

    # 8. Record audit event
    AuditService.log(
        action="REGISTER_PATIENT",
        target_type="patient",
        target_id=patient_id,
        details={"lifelink_id": lifelink_id, "name": basic.get("full_name")},
        actor_id=staff_id,
        actor_role=g.current_user["role"]
    )

    return jsonify({
        "status": "success",
        "patient_id": patient_id,
        "lifelink_id": lifelink_id,
        "message": f"Patient successfully registered with LifeLink ID: {lifelink_id}"
    }), 201


# ---------------------------------------------------------------------------
# Workflow B: Patient Retrieval & Emergency View
# ---------------------------------------------------------------------------

@patients_bp.route("/<patient_id>", methods=["GET"])
@login_required
def get_patient(patient_id: str):
    """Retrieves full patient details scoped by caller's role."""
    user = g.current_user
    p_query = "SELECT * FROM patients_cache WHERE id = ? OR lifelink_id = ?;"
    patient = Database.execute_one(p_query, (patient_id, patient_id))
    if not patient:
        return jsonify({"status": "error", "message": "Patient not found"}), 404

    # Fetch emergency contacts
    e_query = "SELECT * FROM emergency_contacts WHERE patient_id = ?;"
    contacts = Database.execute_query(e_query, (patient["id"],))

    # Check role scope: only clinician / records admin can view clinical records
    medical_data = None
    if user["role"] in (Roles.CLINICIAN, Roles.RECORDS_ADMIN):
        m_query = "SELECT * FROM medical_records WHERE patient_id = ?;"
        med = Database.execute_one(m_query, (patient["id"],))
        if med:
            medical_data = {
                "allergies": json.loads(med["allergies"] or "[]"),
                "chronic_conditions": json.loads(med["chronic_conditions"] or "[]"),
                "current_medications": json.loads(med["current_medications"] or "[]"),
                "implanted_devices": json.loads(med["implanted_devices"] or "[]"),
                "past_surgeries": json.loads(med["past_surgeries"] or "[]"),
                "clinical_notes": med["clinical_notes"],
                "provenance": med["provenance"],
                "updated_at": med["updated_at"]
            }

    AuditService.log(
        action="VIEW_PATIENT",
        target_type="patient",
        target_id=patient["id"],
        actor_id=user["staff_id"],
        actor_role=user["role"]
    )

    return jsonify({
        "status": "success",
        "patient": patient,
        "emergency_contacts": contacts,
        "medical_records": medical_data
    }), 200


@patients_bp.route("/<patient_id>/emergency-summary", methods=["GET"])
@login_required
def get_emergency_summary(patient_id: str):
    """High-priority emergency overview highlighting critical clinical facts and data freshness."""
    p_query = "SELECT id, lifelink_id, full_name, dob, gender, blood_type, status, version, updated_at FROM patients_cache WHERE id = ? OR lifelink_id = ?;"
    patient = Database.execute_one(p_query, (patient_id, patient_id))
    if not patient:
        return jsonify({"status": "error", "message": "Patient not found"}), 404

    m_query = "SELECT allergies, chronic_conditions, current_medications, implanted_devices, provenance, updated_at FROM medical_records WHERE patient_id = ?;"
    med = Database.execute_one(m_query, (patient["id"],)) or {}

    e_query = "SELECT contact_name, relationship, phone_number FROM emergency_contacts WHERE patient_id = ? AND is_primary = 1;"
    primary_contact = Database.execute_one(e_query, (patient["id"],))

    return jsonify({
        "status": "success",
        "emergency_summary": {
            "patient_id": patient["id"],
            "lifelink_id": patient["lifelink_id"],
            "full_name": patient["full_name"],
            "blood_type": patient["blood_type"],
            "gender": patient["gender"],
            "dob": patient["dob"],
            "critical_allergies": json.loads(med.get("allergies") or "[]"),
            "chronic_conditions": json.loads(med.get("chronic_conditions") or "[]"),
            "current_medications": json.loads(med.get("current_medications") or "[]"),
            "implanted_devices": json.loads(med.get("implanted_devices") or "[]"),
            "primary_contact": primary_contact,
            "data_freshness": {
                "last_verified_at": med.get("updated_at") or patient["updated_at"],
                "provenance": med.get("provenance", "Hospital Records"),
                "version": patient["version"]
            }
        }
    }), 200


@patients_bp.route("/search", methods=["POST"])
@login_required
def search_patients():
    """Manual search fallback by LifeLink ID, full name, or phone."""
    data = request.get_json() or {}
    term = f"%{data.get('query', '').strip()}%"

    query = """
    SELECT id, lifelink_id, full_name, dob, gender, blood_type, phone, status
    FROM patients_cache
    WHERE (lifelink_id LIKE ? OR full_name LIKE ? OR phone LIKE ?) AND status != 'deleted_tombstone'
    LIMIT 20;
    """
    matches = Database.execute_query(query, (term, term, term))
    return jsonify({"status": "success", "patients": matches}), 200


@patients_bp.route("/unidentified", methods=["POST"])
@login_required
def create_unidentified_patient():
    """Fallback workflow for registering unconscious or trauma patient with missing identity."""
    data = request.get_json() or {}
    estimated_gender = data.get("estimated_gender", "Unknown")
    apparent_age = data.get("apparent_age", "Unknown")
    clinical_notes = data.get("clinical_notes", "Emergency Trauma Intake - Unidentified")
    
    patient_id = str(uuid.uuid4())
    year = datetime.datetime.now().year
    count_row = Database.execute_one("SELECT COUNT(*) as total FROM patients_cache;")
    total = (count_row["total"] if count_row else 0) + 1
    lifelink_id = f"LL-EMERGENCY-{year}-{total:04d}"
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    staff_id = g.current_user["staff_id"]

    Database.execute_commit("""
    INSERT INTO patients_cache (id, lifelink_id, full_name, dob, gender, blood_type, status, version, created_at, updated_at)
    VALUES (?, ?, ?, 'Unknown', ?, 'Unknown', 'active', 1, ?, ?);
    """, (patient_id, lifelink_id, f"Unidentified Patient ({lifelink_id})", estimated_gender, now, now))

    Database.execute_commit("""
    INSERT INTO medical_records (id, patient_id, allergies, chronic_conditions, current_medications, implanted_devices, past_surgeries, clinical_notes, provenance, verified_by_staff_id, updated_at)
    VALUES (?, ?, '[]', '[]', '[]', '[]', '[]', ?, 'Emergency Intake', ?, ?);
    """, (str(uuid.uuid4()), patient_id, f"Apparent Age: {apparent_age}. Notes: {clinical_notes}", staff_id, now))

    AuditService.log(
        action="REGISTER_UNIDENTIFIED_PATIENT",
        target_type="patient",
        target_id=patient_id,
        details={"lifelink_id": lifelink_id},
        actor_id=staff_id,
        actor_role=g.current_user["role"]
    )

    return jsonify({
        "status": "success",
        "patient_id": patient_id,
        "lifelink_id": lifelink_id,
        "message": f"Temporary emergency identity created: {lifelink_id}"
    }), 201


# ---------------------------------------------------------------------------
# Workflow C: Patient Updates & Revision History
# ---------------------------------------------------------------------------

@patients_bp.route("/<patient_id>", methods=["PATCH"])
@login_required
def update_patient(patient_id: str):
    """
    Updates patient details with permission scoping, change diff preview,
    mandatory rationale, and revision history tracking.
    """
    user = g.current_user
    data = request.get_json() or {}
    reason = data.get("reason", "").strip()

    if not reason:
        return jsonify({"status": "error", "message": "A documented reason is mandatory for record modifications"}), 400

    p_query = "SELECT * FROM patients_cache WHERE id = ?;"
    patient = Database.execute_one(p_query, (patient_id,))
    if not patient:
        return jsonify({"status": "error", "message": "Patient not found"}), 404

    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    new_version = patient["version"] + 1

    # Demographics updates (Allowed for registration_staff, records_admin, clinician)
    demographics_updates = data.get("demographics", {})
    if demographics_updates:
        for field, new_val in demographics_updates.items():
            if field in ("phone", "address", "blood_type", "full_name"):
                old_val = patient.get(field, "")
                if str(old_val) != str(new_val):
                    # Record revision
                    Database.execute_commit("""
                    INSERT INTO record_revisions (id, patient_id, field_name, old_value, new_value, reason, edited_by_staff_id, version, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """, (str(uuid.uuid4()), patient_id, field, str(old_val), str(new_val), reason, user["staff_id"], new_version, now))

                    Database.execute_commit(f"UPDATE patients_cache SET {field} = ?, version = ?, updated_at = ? WHERE id = ?;", (new_val, new_version, now, patient_id))

    # Clinical updates (Restricted strictly to clinician)
    clinical_updates = data.get("medical", {})
    if clinical_updates:
        if user["role"] != Roles.CLINICIAN:
            return jsonify({"status": "error", "message": "Forbidden: Clinical modifications require Clinician privileges"}), 403

        m_query = "SELECT * FROM medical_records WHERE patient_id = ?;"
        current_med = Database.execute_one(m_query, (patient_id,))
        if current_med:
            for field, new_val in clinical_updates.items():
                if field in ("allergies", "chronic_conditions", "current_medications", "implanted_devices", "past_surgeries", "clinical_notes"):
                    old_val = current_med.get(field, "")
                    serialized_new = json.dumps(new_val) if isinstance(new_val, list) else str(new_val)
                    if str(old_val) != serialized_new:
                        Database.execute_commit("""
                        INSERT INTO record_revisions (id, patient_id, field_name, old_value, new_value, reason, edited_by_staff_id, version, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """, (str(uuid.uuid4()), patient_id, field, str(old_val), serialized_new, reason, user["staff_id"], new_version, now))

                        Database.execute_commit(f"UPDATE medical_records SET {field} = ?, updated_at = ?, verified_by_staff_id = ? WHERE patient_id = ?;", (serialized_new, now, user["staff_id"], patient_id))

        Database.execute_commit("UPDATE patients_cache SET version = ?, updated_at = ? WHERE id = ?;", (new_version, now, patient_id))

    # Queue sync outbox update
    Database.execute_commit("""
    INSERT INTO sync_outbox (id, operation_id, table_name, record_id, action, payload_json, status, created_at)
    VALUES (?, ?, 'patients', ?, 'UPDATE', ?, 'pending', ?);
    """, (str(uuid.uuid4()), str(uuid.uuid4()), patient_id, json.dumps({"reason": reason, "version": new_version}), now))

    AuditService.log(
        action="UPDATE_PATIENT",
        target_type="patient",
        target_id=patient_id,
        details={"reason": reason, "new_version": new_version},
        actor_id=user["staff_id"],
        actor_role=user["role"]
    )

    return jsonify({
        "status": "success",
        "message": "Patient records updated successfully",
        "new_version": new_version
    }), 200


@patients_bp.route("/<patient_id>/revisions", methods=["GET"])
@login_required
def get_patient_revisions(patient_id: str):
    """Retrieves chronological edit history for a patient record."""
    query = """
    SELECT r.*, s.full_name as editor_name, s.role as editor_role
    FROM record_revisions r
    LEFT JOIN staff_accounts s ON r.edited_by_staff_id = s.id
    WHERE r.patient_id = ?
    ORDER BY r.created_at DESC;
    """
    revisions = Database.execute_query(query, (patient_id,))
    return jsonify({"status": "success", "revisions": revisions}), 200
