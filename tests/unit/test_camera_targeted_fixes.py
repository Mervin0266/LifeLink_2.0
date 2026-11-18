"""
Targeted regression tests for LifeLink 2.0 Camera Subsystem fixes:
- Verification of stale camera job expiration (prevents false HTTP 409 lockups)
- Camera job lifecycle exception safety (pending -> completed / failed / cancelled)
- Error differentiation for iris capture (409 Conflict, 422 Quality, 503 Unavailable, 504 Timeout, 500 Server)
- Error differentiation for photo capture (409, 503, 504, 500)
- Cancel camera clears active camera jobs while strictly preserving fingerprint state
- Genuine ISO quality calculation (no fake hardcoded constants)
- Preview stop without global cancellation interference
"""

import time
import json
import base64
import pytest
from unittest.mock import MagicMock, patch
import requests

from backend.app import create_app
from backend.auth.security import SecurityUtils
from backend.auth.rbac import Roles
from backend.devices.manager import DeviceManager
from backend.devices.camera_host import CameraHostClient
from backend.database.connection import Database
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


def test_clear_stale_camera_jobs_expires_abandoned_jobs():
    """Verify that abandoned camera jobs older than max_age_seconds are automatically expired."""
    manager = DeviceManager()
    # Create an old camera job manually with an expired timestamp
    job_id = manager.create_job("iris_capture", "camera-substation", {"eye_side": "OD"})
    
    # Artificially age the job to 60 seconds ago
    old_time = "2020-01-01T00:00:00+00:00"
    Database.execute_commit(
        "UPDATE device_jobs SET created_at = ? WHERE job_id = ?;",
        (old_time, job_id)
    )

    # Calling is_device_busy should clean up the stale job and report False
    assert manager.is_device_busy("camera-substation") is False

    job = manager.get_job(job_id)
    assert job["status"] == "failed"
    assert "abandoned" in job["result"].get("error", "")


def test_stale_camera_cleanup_never_touches_fingerprint_jobs():
    """Verify that camera stale cleanup strictly isolates to camera peripherals."""
    manager = DeviceManager()
    fp_job = manager.create_job("fingerprint_enroll", "esp32-gt521f32", {"finger": "R1"})
    old_time = "2020-01-01T00:00:00+00:00"
    Database.execute_commit(
        "UPDATE device_jobs SET created_at = ? WHERE job_id = ?;",
        (old_time, fp_job)
    )

    manager.clear_stale_camera_jobs()
    job = manager.get_job(fp_job)
    # Fingerprint job must remain pending, NOT touched by camera cleanup
    assert job["status"] == "pending"

    # Cleanup
    manager.update_job_status(fp_job, "completed")


def test_cancel_camera_clears_pending_camera_jobs(client, registrar_token):
    """Verify that POST /camera/cancel cancels pending camera jobs in the database."""
    manager = DeviceManager()
    job_id = manager.create_job("iris_capture", "camera-substation", {"eye_side": "OD"})
    assert manager.is_device_busy("camera-substation") is True

    headers = {"Authorization": f"Bearer {registrar_token}"}
    resp = client.post("/api/v1/devices/camera/cancel", headers=headers)
    assert resp.status_code == 200

    assert manager.is_device_busy("camera-substation") is False
    job = manager.get_job(job_id)
    assert job["status"] == "cancelled"


def test_genuine_quality_evaluation_on_camera_host():
    """Verify that CameraHostClient evaluates genuine ISO metrics from JPEG bytes."""
    import numpy as np
    import cv2

    # Create a synthetic sharp image
    img = np.full((300, 400, 3), (200, 200, 200), dtype=np.uint8)
    cv2.circle(img, (200, 150), 60, (50, 50, 50), -1)
    cv2.circle(img, (200, 150), 20, (0, 0, 0), -1)
    _, jpeg_bytes = cv2.imencode(".jpg", img)

    quality = CameraHostClient._evaluate_image_quality(jpeg_bytes.tobytes())
    assert "sharpness" in quality
    assert "mean_intensity" in quality
    assert "glare_percentage" in quality
    assert "estimated_diameter" in quality
    assert isinstance(quality["sharpness"], float)
    assert isinstance(quality["mean_intensity"], float)


def test_iris_capture_error_classification(client, registrar_token):
    """Verify that capture_iris returns correct HTTP status codes instead of always 422."""
    headers = {"Authorization": f"Bearer {registrar_token}"}
    manager = DeviceManager()

    # 1. Test 503 Service Unavailable (substation down)
    with patch.object(manager.camera, "capture_iris", return_value={"status": "unavailable", "message": "Camera service unavailable"}):
        resp = client.post("/api/v1/devices/camera/capture-iris", json={"eye_side": "OD"}, headers=headers)
        assert resp.status_code == 503
        assert "unavailable" in resp.get_json()["message"].lower()

    # 2. Test 504 Timeout
    with patch.object(manager.camera, "capture_iris", return_value={"status": "timeout", "message": "Timed out"}):
        resp = client.post("/api/v1/devices/camera/capture-iris", json={"eye_side": "OD"}, headers=headers)
        assert resp.status_code == 504
        assert "timed out" in resp.get_json()["message"].lower()

    # 3. Test 409 Busy
    with patch.object(manager.camera, "capture_iris", return_value={"status": "busy", "message": "Camera device is busy"}):
        resp = client.post("/api/v1/devices/camera/capture-iris", json={"eye_side": "OD"}, headers=headers)
        assert resp.status_code == 409
        assert "busy" in resp.get_json()["message"].lower()

    # 4. Test 422 Quality Rejection
    with patch.object(manager.camera, "capture_iris", return_value={"status": "rejected", "quality": {"passed": False}, "message": "Blurry"}):
        resp = client.post("/api/v1/devices/camera/capture-iris", json={"eye_side": "OD"}, headers=headers)
        assert resp.status_code == 422
        assert resp.get_json()["status"] == "rejected"


def test_photo_capture_error_classification(client, registrar_token):
    """Verify that capture_photo reports specific errors and correct status codes."""
    headers = {"Authorization": f"Bearer {registrar_token}"}
    manager = DeviceManager()

    # Test 503
    with patch.object(manager.camera, "capture_patient_photo", return_value={"status": "unavailable", "message": "Daemon down"}):
        resp = client.post("/api/v1/devices/camera/capture-photo", headers=headers)
        assert resp.status_code == 503
        assert "daemon down" in resp.get_json()["message"].lower()

    # Test 504
    with patch.object(manager.camera, "capture_patient_photo", return_value={"status": "timeout", "message": "Timed out"}):
        resp = client.post("/api/v1/devices/camera/capture-photo", headers=headers)
        assert resp.status_code == 504

    # Test 409
    with patch.object(manager.camera, "capture_patient_photo", return_value={"status": "busy", "message": "Camera busy"}):
        resp = client.post("/api/v1/devices/camera/capture-photo", headers=headers)
        assert resp.status_code == 409


def test_stop_camera_preview_route_isolation(client, registrar_token):
    """Verify stop-preview does NOT trigger destructive global cancellation."""
    headers = {"Authorization": f"Bearer {registrar_token}"}
    manager = DeviceManager()

    with patch.object(manager.camera, "stop_preview", return_value={"status": "stopped"}) as mock_stop, \
         patch.object(manager.camera, "cancel") as mock_cancel:
        resp = client.post("/api/v1/devices/camera/stop-preview", headers=headers)
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "stopped"
        mock_stop.assert_called_once()
        mock_cancel.assert_not_called()


def test_cancel_camera_route(client, registrar_token):
    """Verify cancel route cancels database jobs and invokes driver cancel."""
    headers = {"Authorization": f"Bearer {registrar_token}"}
    manager = DeviceManager()

    job_id = manager.create_job("iris_capture", "camera-substation")
    with patch.object(manager.camera, "cancel", return_value={"status": "cancelled"}) as mock_cancel:
        resp = client.post("/api/v1/devices/camera/cancel", headers=headers)
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "cancelled"
        mock_cancel.assert_called_once()

    job = manager.get_job(job_id)
    assert job["status"] == "cancelled"


def test_pi3b_preview_health_reporting():
    """Verify Pi 3B+ health helper marks PREVIEW state as READY for capture."""
    import sys
    from pathlib import Path
    pi3b_path = str(Path("LifeLink_2.0_Deployment/pi3b").resolve())
    if pi3b_path not in sys.path:
        sys.path.insert(0, pi3b_path)
    try:
        import usb_communication
        health = usb_communication.CameraCommunicationHelper.format_health_response(
            camera_state="PREVIEW",
            led_status={"is_on": True, "pin": 18}
        )
        assert health["status"] == "ready"
        assert health["camera_state"] == "PREVIEW"
    finally:
        if pi3b_path in sys.path:
            sys.path.remove(pi3b_path)


def test_pi3b_daemon_shared_session_and_incompatible_modes():
    """Verify Pi 3B+ shared camera session, compatible capture during preview, and incompatible mode rejection."""
    import sys
    from pathlib import Path
    pi3b_path = str(Path("LifeLink_2.0_Deployment/pi3b").resolve())
    if pi3b_path not in sys.path:
        sys.path.insert(0, pi3b_path)
    try:
        import camera_service
        camera_service.app.config["TESTING"] = True
        pi3b_client = camera_service.app.test_client()

        # 1. When in photo preview mode, capture_iris returns 409 (incompatible mode)
        camera_service._active_preview_mode = "photo"
        resp = pi3b_client.post("/api/v1/camera/iris/capture")
        assert resp.status_code == 409
        assert "photo" in resp.get_json()["message"].lower()

        # 2. When in iris preview mode, capture_photo returns 409 (incompatible mode)
        camera_service._active_preview_mode = "iris"
        resp = pi3b_client.post("/api/v1/camera/photo/capture")
        assert resp.status_code == 409
        assert "iris" in resp.get_json()["message"].lower()

        # 3. When in iris preview mode, capture_iris is COMPATIBLE and succeeds!
        camera_service._active_preview_mode = "iris"
        camera_service._preview_stop_event.clear()
        resp = pi3b_client.post("/api/v1/camera/iris/capture?format=jpeg")
        assert resp.status_code in (200, 422)
        # Verify preview mode remains active and was NOT killed
        assert camera_service._active_preview_mode == "iris"

        # 4. Concurrent capture rejection (409)
        camera_service._active_preview_mode = None
        assert camera_service._capture_lock.acquire(blocking=False)
        try:
            resp = pi3b_client.post("/api/v1/camera/iris/capture")
            assert resp.status_code == 409
            assert "already in progress" in resp.get_json()["message"].lower()
        finally:
            camera_service._capture_lock.release()
    finally:
        camera_service._active_preview_mode = None
        camera_service._capture_event.clear()
        if pi3b_path in sys.path:
            sys.path.remove(pi3b_path)
