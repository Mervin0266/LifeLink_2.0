"""
Unit tests for LifeLink 2.0 Biometric Verification and Identification.
"""

import pytest
import base64
from backend.app import create_app
from backend.auth.security import SecurityUtils
from backend.auth.rbac import Roles
from backend.biometrics.service import BiometricService


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


def test_fingerprint_1_to_1_verify(client, clinician_token):
    headers = {"Authorization": f"Bearer {clinician_token}"}
    patient_id = "pat-synthetic-001"
    probe_b64 = base64.b64encode(b"synthetic_fingerprint_probe_sample").decode("utf-8")

    resp = client.post("/api/v1/verify", json={
        "patient_id": patient_id,
        "biometric_type": "fingerprint",
        "probe_b64": probe_b64,
        "feature_position": "R1"
    }, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert "matched" in data["verification"]
    assert "confidence" in data["verification"]


def test_iris_1_to_1_verify(client, clinician_token):
    headers = {"Authorization": f"Bearer {clinician_token}"}
    patient_id = "pat-synthetic-001"
    probe_b64 = base64.b64encode(b"synthetic_iris_embedding_probe").decode("utf-8")

    resp = client.post("/api/v1/verify", json={
        "patient_id": patient_id,
        "biometric_type": "iris",
        "probe_b64": probe_b64,
        "feature_position": "OD"
    }, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert "matched" in data["verification"]


def test_1_to_n_identification(client, clinician_token):
    headers = {"Authorization": f"Bearer {clinician_token}"}
    probe_b64 = base64.b64encode(b"synthetic_search_probe_vector").decode("utf-8")

    resp = client.post("/api/v1/identify", json={
        "biometric_type": "iris",
        "probe_b64": probe_b64
    }, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["identification"]["outcome"] in ("MATCH", "NO_MATCH", "INCONCLUSIVE")
