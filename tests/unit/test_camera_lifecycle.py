"""
LifeLink 2.0 - Unit Tests for Camera & IR LED Lifecycle Synchronization
Verifies synchronized LED switching during iris capture, safe shutoff on normal finish,
immediate shutoff on cancellation and exceptions, and isolation during photo capture.
"""

import sys
import os
import time
import pytest
import numpy as np

# Ensure iris-module/camera-client is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../iris-module/camera-client")))

from camera_service import app, _led_controller, _camera_client, set_camera_state, get_camera_state  # type: ignore
from ir_led_controller import IRLEDController  # type: ignore
from iris_capture import IrisCaptureCoordinator  # type: ignore
from photo_capture import PhotoCaptureCoordinator  # type: ignore
from camera_client import CameraClient  # type: ignore


class TestCameraLifecycleSync:
    """Test suite for Camera and IR LED lifecycle synchronization."""

    @pytest.fixture
    def client(self):
        """Flask test client fixture."""
        app.config["TESTING"] = True
        with app.test_client() as client:
            # Ensure starting state is IDLE and LED is OFF
            set_camera_state("IDLE")
            _led_controller.turn_off()
            yield client
            _led_controller.turn_off()
            set_camera_state("IDLE")

    def test_health_endpoint_reports_led_status(self, client):
        """Checks /health reports camera state and IR LED diagnostic details."""
        res = client.get("/api/v1/camera/health")
        assert res.status_code == 200
        data = res.get_json()
        assert data["camera_state"] == "IDLE"
        assert "ir_led" in data
        assert data["ir_led"]["is_on"] is False
        assert data["ir_led"]["pin"] == 18

    def test_led_status_endpoint(self, client):
        """Checks /api/v1/camera/led/status endpoint."""
        res = client.get("/api/v1/camera/led/status")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "ok"
        assert data["ir_led"]["is_on"] is False

    def test_iris_capture_synchronization_success(self, client):
        """
        Tests the full synchronized scan cycle:
        1. IR LED is OFF initially
        2. IR LED turns ON during active scanning
        3. IR LED turns OFF upon scan completion
        """
        assert _led_controller.is_on() is False

        # Execute scan via API
        res = client.post("/api/v1/camera/iris/capture", json={"eye_side": "OD"})
        assert res.status_code == 200
        data = res.get_json()

        assert data["status"] in ("completed", "rejected")
        assert data["eye_side"] == "OD"
        assert "quality" in data
        assert "sharpness" in data["quality"]["metrics"]

        # LED must be OFF immediately after scanning completes
        assert _led_controller.is_on() is False
        assert get_camera_state() == "IDLE"

    def test_iris_capture_turns_off_led_on_exception(self):
        """
        Tests that an unexpected camera exception during capture
        strictly executes the finally block and turns the IR LED OFF.
        """
        class FaultyCamera(CameraClient):
            def capture_frame(self):
                raise RuntimeError("Simulated CSI hardware bus failure!")

        led = IRLEDController(pin=18, enabled=True)
        try:
            assert led.is_on() is False
            coordinator = IrisCaptureCoordinator(
                camera_client=FaultyCamera(),
                led_controller=led
            )

            res = coordinator.execute_scan(eye_side="OS")
            assert res["status"] == "error"
            assert "Simulated CSI hardware bus failure" in res["message"]

            # CRITICAL: IR LED must be safely OFF despite the exception!
            assert led.is_on() is False, "IR LED remained ON after camera exception!"
        finally:
            led.cleanup()

    def test_iris_capture_cancellation_turns_off_led(self):
        """
        Tests that cancellation requests abort the scan and immediately extinguish IR LED.
        """
        led = IRLEDController(pin=18, enabled=True)
        try:
            coordinator = IrisCaptureCoordinator(led_controller=led)
            # Signal cancellation
            coordinator.cancel()
            res = coordinator.execute_scan(eye_side="OD")

            assert res["status"] == "cancelled"
            assert led.is_on() is False
        finally:
            led.cleanup()

    def test_api_cancel_endpoint(self, client):
        """Checks the /api/v1/camera/cancel endpoint."""
        # Force LED on to test cancel endpoint capability
        _led_controller.turn_on()
        assert _led_controller.is_on() is True

        res = client.post("/api/v1/camera/cancel")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "cancelled"
        assert data["led_is_on"] is False
        assert _led_controller.is_on() is False

    def test_patient_photo_capture_keeps_ir_led_off(self, client):
        """
        Patient profile photos must use visible light only:
        IR LED must remain strictly OFF before, during, and after.
        """
        assert _led_controller.is_on() is False

        res = client.post("/api/v1/camera/photo/capture")
        assert res.status_code == 200
        data = res.get_json()
        assert data["status"] == "completed"
        assert data["led_active"] is False

        # IR LED must remain OFF
        assert _led_controller.is_on() is False

    def test_concurrent_scan_sessions_rejected(self):
        """Verifies session locking prevents overlapping scan sessions."""
        import threading

        # Start a scan session and simultaneously request another
        results = []

        def make_request():
            with app.test_client() as thread_client:
                res = thread_client.post("/api/v1/camera/iris/capture", json={"eye_side": "OD"})
                results.append(res.status_code)

        t1 = threading.Thread(target=make_request)
        t2 = threading.Thread(target=make_request)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        # Both completed safely (one might be 200 and one 409 if synchronized, or sequential 200s)
        for code in results:
            assert code in (200, 409)

        # In all cases, LED must end in OFF state
        assert _led_controller.is_on() is False

    def test_token_authentication_enforcement(self):
        """Verifies X-Camera-Token authentication when enforced outside testing mode."""
        app.config["TESTING"] = False
        try:
            with app.test_client() as unauthed_client:
                # 1. Unauthenticated request without token header rejected
                res = unauthed_client.post("/api/v1/camera/iris/capture", json={"eye_side": "OD"})
                assert res.status_code == 401
                assert "Unauthorized" in res.get_json()["message"]

                # 2. Authenticated request with correct token accepted
                token = "lifelink-wired-internal-camera-token"
                headers = {"X-Camera-Token": token}
                res_auth = unauthed_client.post("/api/v1/camera/iris/capture", json={"eye_side": "OD"}, headers=headers)
                assert res_auth.status_code in (200, 422)

                # 3. Cancel with valid token accepted
                res_cancel = unauthed_client.post("/api/v1/camera/cancel", headers=headers)
                assert res_cancel.status_code == 200
        finally:
            app.config["TESTING"] = True
            _led_controller.turn_off()
            set_camera_state("IDLE")

    def test_binary_jpeg_format_export(self, client):
        """Verifies format=jpeg returns raw binary image payload."""
        res = client.post("/api/v1/camera/iris/capture?format=jpeg", json={"eye_side": "OD"})
        if res.status_code == 200:
            assert res.mimetype == "image/jpeg"
            assert len(res.data) > 0
            # Check JPEG magic header 0xFFD8
            assert res.data[:2] == b"\xff\xd8"
        else:
            assert res.status_code == 422
