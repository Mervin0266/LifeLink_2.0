"""
Unit tests for Peripheral Devices (Mock Fingerprint & Camera).
"""

import pytest
from backend.app import create_app
from backend.auth.security import SecurityUtils
from backend.auth.rbac import Roles
from backend.devices.manager import DeviceManager
from backend.config import Config


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


def test_device_health(client):
    resp = client.get("/api/v1/devices/health")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["health"]["mock_mode"] is True
    assert data["health"]["fingerprint_device"]["connected"] is True
    assert data["health"]["camera_device"]["connected"] is True


def test_fingerprint_3_stage_enrollment(client, registrar_token):
    headers = {"Authorization": f"Bearer {registrar_token}"}

    # Pass 1
    resp1 = client.post("/api/v1/devices/fingerprint/enroll-step", json={
        "finger_position": "R1",
        "pass_number": 1
    }, headers=headers)
    assert resp1.status_code == 200
    d1 = resp1.get_json()
    job_id = d1["job_id"]
    assert d1["step_result"]["status"] == "in_progress"

    # Pass 2
    resp2 = client.post("/api/v1/devices/fingerprint/enroll-step", json={
        "finger_position": "R1",
        "pass_number": 2,
        "job_id": job_id
    }, headers=headers)
    assert resp2.status_code == 200
    d2 = resp2.get_json()
    assert d2["step_result"]["pass"] == 3

    # Pass 3 (Complete)
    resp3 = client.post("/api/v1/devices/fingerprint/enroll-step", json={
        "finger_position": "R1",
        "pass_number": 3,
        "job_id": job_id
    }, headers=headers)
    assert resp3.status_code == 200
    d3 = resp3.get_json()
    assert d3["step_result"]["status"] == "completed"
    assert d3["step_result"]["template_b64"] is not None


def test_camera_quality_and_iris_capture(client, registrar_token, monkeypatch):
    from backend.devices import routes as device_routes
    # Camera behaviour under test; iris template extraction (trained models) is stubbed
    # so this test does not depend on model weights (covered by test_iris_engine.py).
    monkeypatch.setattr(device_routes, "_extract_and_validate_iris_template",
                        lambda image_bytes, eye_side: (True, {"status": "extracted", "model_version": "TEST-STUB"}))
    headers = {"Authorization": f"Bearer {registrar_token}"}
    resp = client.post("/api/v1/devices/camera/capture-iris", json={
        "eye_side": "OD"
    }, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["quality"]["passed"] is True
    assert data["quality"]["sharpness"] >= 50.0
    assert "image_b64" in data


def test_device_job_cancellation(client, registrar_token):
    headers = {"Authorization": f"Bearer {registrar_token}"}
    manager = DeviceManager()
    job_id = manager.create_job("fingerprint_enroll", "esp32-mock", {"finger": "R2"})

    resp = client.post(f"/api/v1/devices/jobs/{job_id}/cancel", headers=headers)
    assert resp.status_code == 200
    job = manager.get_job(job_id)
    assert job["status"] == "cancelled"


def test_single_impression_enrollment(client, registrar_token):
    headers = {"Authorization": f"Bearer {registrar_token}"}
    orig = Config.SINGLE_IMPRESSION_ENROLL
    try:
        Config.SINGLE_IMPRESSION_ENROLL = True
        resp = client.post("/api/v1/devices/fingerprint/enroll-step", json={
            "finger_position": "L1",
            "pass_number": 1
        }, headers=headers)
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["step_result"]["status"] == "completed"
        assert data["step_result"]["max_passes"] == 1
        assert data["step_result"]["template_b64"] is not None
    finally:
        Config.SINGLE_IMPRESSION_ENROLL = orig


def test_fingerprint_cancel_endpoint(client, registrar_token):
    headers = {"Authorization": f"Bearer {registrar_token}"}
    resp = client.post("/api/v1/devices/fingerprint/cancel", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "cancelled"


def test_camera_stream_endpoint(client):
    resp = client.get("/api/v1/devices/camera/stream?mode=iris")
    assert resp.status_code == 200
    assert "multipart/x-mixed-replace" in resp.headers.get("Content-Type", "")


def test_camera_cancel_preview(client, registrar_token):
    headers = {"Authorization": f"Bearer {registrar_token}"}
    resp = client.post("/api/v1/devices/camera/cancel", headers=headers)
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "cancelled"


def test_fingerprint_capture_probe_success(client, registrar_token):
    """Verifies physical fingerprint probe acquisition for 1:N retrieval."""
    headers = {"Authorization": f"Bearer {registrar_token}"}
    resp = client.post("/api/v1/devices/fingerprint/capture-probe", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert "template_b64" in data
    assert len(data["template_b64"]) > 0
    assert data.get("template_size", 0) > 0


def test_camera_capture_probe_success(client, registrar_token, monkeypatch):
    """Verifies camera iris probe acquisition with quality evaluation for 1:N retrieval."""
    from backend.devices import routes as device_routes
    # Camera behaviour under test; iris template extraction (trained models) is stubbed
    # so this test does not depend on model weights (covered by test_iris_engine.py).
    monkeypatch.setattr(device_routes, "_extract_and_validate_iris_template",
                        lambda image_bytes, eye_side: (True, {"status": "extracted", "model_version": "TEST-STUB"}))
    headers = {"Authorization": f"Bearer {registrar_token}"}
    resp = client.post("/api/v1/devices/camera/capture-probe", json={"eye_side": "OD"}, headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["eye_side"] == "OD"
    assert "image_b64" in data
    assert "quality" in data


def test_probe_endpoints_require_auth(client):
    """Verifies that biometric probe endpoints enforce authentication."""
    resp_fp = client.post("/api/v1/devices/fingerprint/capture-probe")
    assert resp_fp.status_code == 401

    resp_iris = client.post("/api/v1/devices/camera/capture-probe", json={"eye_side": "OD"})
    assert resp_iris.status_code == 401
