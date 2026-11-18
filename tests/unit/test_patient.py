"""
Unit tests for LifeLink 2.0 Patient Workflows (Registration, Retrieval, Updates).
"""

import pytest
import base64
from backend.app import create_app
from backend.auth.security import SecurityUtils
from backend.auth.rbac import Roles


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def clinician_token():
    return SecurityUtils.create_token({
        "staff_id": "staff-clinician-001",
        "username": "clinician",
        "role": Roles.CLINICIAN,
        "portal": "clinical"
    })


@pytest.fixture
def registrar_token():
    return SecurityUtils.create_token({
        "staff_id": "staff-hospital-002",
        "username": "registrar",
        "role": Roles.REGISTRATION_STAFF,
        "portal": "hospital"
    })


def test_registration_draft_and_commit(client, registrar_token):
    """Tests complete registration lifecycle from draft to atomic commit."""
    headers = {"Authorization": f"Bearer {registrar_token}"}

    # 1. Save Draft
    draft_payload = {
        "draft_id": "draft-test-unit-001",
        "step": "review",
        "basic": {
            "full_name": "Test Patient Alpha",
            "dob": "1992-05-15",
            "gender": "Male",
            "blood_type": "AB-Positive",
            "phone": "+1-555-9988",
            "address": "101 Test Way"
        },
        "emergency": {
            "contact_name": "Emergency Alpha",
            "relationship": "Spouse",
            "phone_number": "+1-555-9989"
        },
        "medical": {
            "allergies": ["Ibuprofen"],
            "chronic_conditions": ["None"],
            "current_medications": [],
            "implanted_devices": [],
            "clinical_notes": "Unit test patient record."
        },
        "fingerprints": {
            "R1": base64.b64encode(b"mock_fingerprint_template_r1").decode("utf-8")
        },
        "irises": {
            "OD": base64.b64encode(b"mock_iris_embedding_od").decode("utf-8")
        }
    }
    draft_resp = client.post("/api/v1/patients/registration-drafts", json=draft_payload, headers=headers)
    assert draft_resp.status_code == 200

    # 2. Duplicate Check
    dup_resp = client.post("/api/v1/patients/duplicate-check", json={
        "full_name": "Test Patient Alpha",
        "dob": "1992-05-15"
    }, headers=headers)
    assert dup_resp.status_code == 200

    # 3. Commit Draft
    commit_resp = client.post("/api/v1/patients/registration-drafts/draft-test-unit-001/commit", headers=headers)
    assert commit_resp.status_code == 201
    c_data = commit_resp.get_json()
    assert c_data["status"] == "success"
    assert "patient_id" in c_data
    assert "lifelink_id" in c_data
    patient_id = c_data["patient_id"]

    # 4. Retrieve Patient
    get_resp = client.get(f"/api/v1/patients/{patient_id}", headers=headers)
    assert get_resp.status_code == 200
    p_data = get_resp.get_json()
    assert p_data["patient"]["full_name"] == "Test Patient Alpha"


def test_patient_update_with_reason(client, clinician_token):
    """Tests patient update requiring rationale and generating revisions."""
    headers = {"Authorization": f"Bearer {clinician_token}"}
    patient_id = "pat-synthetic-001"  # Seeded patient Jane Doe

    # 1. Update demographics & clinical record
    update_resp = client.patch(f"/api/v1/patients/{patient_id}", json={
        "reason": "Annual clinical wellness review and phone update",
        "demographics": {"phone": "+1-555-8888"},
        "medical": {"allergies": ["Severe Penicillin Anaphylaxis", "Latex", "Aspirin"]}
    }, headers=headers)
    assert update_resp.status_code == 200

    # 2. Check Revisions History
    rev_resp = client.get(f"/api/v1/patients/{patient_id}/revisions", headers=headers)
    assert rev_resp.status_code == 200
    r_data = rev_resp.get_json()
    assert len(r_data["revisions"]) >= 1
    assert any("Aspirin" in r["new_value"] for r in r_data["revisions"])
