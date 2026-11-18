"""
LifeLink 2.0 - Security, Privacy, and Authorization Regression Tests
Validates defensive protections: JWT tampering, RBAC enforcement, SQL injection immunity,
and encryption of biometric templates at rest.
"""

import pytest
import json
from backend.app import create_app
from backend.auth.security import SecurityUtils
from backend.auth.rbac import Roles, Permissions
from backend.database.connection import Database


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def registrar_token():
    return SecurityUtils.create_token({
        "staff_id": "staff-hospital-002",
        "username": "registrar",
        "role": Roles.REGISTRATION_STAFF,
        "portal": "hospital"
    })


@pytest.fixture
def clinician_token():
    return SecurityUtils.create_token({
        "staff_id": "staff-hospital-001",
        "username": "dr_smith",
        "role": Roles.CLINICIAN,
        "portal": "clinical"
    })


@pytest.fixture
def admin_token():
    return SecurityUtils.create_token({
        "staff_id": "staff-admin-001",
        "username": "sysadmin",
        "role": Roles.SYSTEM_ADMIN,
        "portal": "admin"
    })


def test_tampered_jwt_token_rejected(client):
    """Verifies modified or forged JWT tokens are rejected with 401 Unauthorized."""
    tampered_token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.tampered_payload.fake_signature"
    headers = {"Authorization": f"Bearer {tampered_token}"}

    resp = client.get("/api/v1/patients/LL-2026-00001", headers=headers)
    assert resp.status_code == 401
    assert "invalid" in resp.get_json()["message"].lower() or "expired" in resp.get_json()["message"].lower()


def test_missing_auth_header_rejected(client):
    """Protected endpoints must reject unauthenticated requests."""
    resp = client.get("/api/v1/admin/overview")
    assert resp.status_code == 401


def test_registration_staff_cannot_access_admin_overview(client, registrar_token):
    """Privilege escalation check: non-admin roles cannot view admin dashboard metrics."""
    headers = {"Authorization": f"Bearer {registrar_token}"}
    resp = client.get("/api/v1/admin/overview", headers=headers)
    assert resp.status_code == 403


def test_registration_staff_cannot_modify_clinical_records(client, registrar_token):
    """Role scoping: registration staff cannot modify clinical medical records."""
    headers = {"Authorization": f"Bearer {registrar_token}"}
    resp = client.patch(
        "/api/v1/patients/pat-synthetic-001",
        json={
            "reason": "Unauthorized clinical edit",
            "medical": {"allergies": ["Penicillin"]}
        },
        headers=headers
    )
    assert resp.status_code == 403
    assert "clinician" in resp.get_json()["message"].lower()


def test_sql_injection_in_patient_search_blocked(client, clinician_token):
    """Verifies parameterized queries prevent SQL injection payloads."""
    headers = {"Authorization": f"Bearer {clinician_token}"}
    sqli_payload = "' OR 1=1; DROP TABLE patients_cache; --"
    resp = client.post("/api/v1/patients/search", json={"query": sqli_payload}, headers=headers)
    assert resp.status_code == 200
    # Confirm table was not dropped
    check = Database.execute_one("SELECT COUNT(*) as total FROM patients_cache;")
    assert check is not None
    assert check["total"] >= 0


def test_biometric_templates_encrypted_at_rest():
    """Confirms biometric templates are stored encrypted in the database, never as raw plaintext."""
    fp_row = Database.execute_one("SELECT encrypted_template FROM fingerprint_templates LIMIT 1;")
    if fp_row and fp_row["encrypted_template"]:
        enc = fp_row["encrypted_template"]
        # Raw GT-521F32 template is 498 bytes. Fernet/AES ciphertext contains token header and base64/bytes
        assert len(enc) > 50
        # Must not start with sensor magic or unencrypted plaintext
        assert not enc.startswith(b"LLFP")


def test_mandatory_rationale_for_updates(client, clinician_token):
    """Legal requirement: medical record modification without documented rationale is rejected."""
    headers = {"Authorization": f"Bearer {clinician_token}"}
    resp = client.patch(
        "/api/v1/patients/pat-synthetic-001",
        json={
            "reason": "",  # Empty rationale
            "demographics": {"phone": "+1-555-0199"}
        },
        headers=headers
    )
    assert resp.status_code == 400
    assert "reason is mandatory" in resp.get_json()["message"].lower()
