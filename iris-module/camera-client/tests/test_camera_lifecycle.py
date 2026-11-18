"""
LifeLink 2.0 - Standalone Pi Zero W Test for Camera Lifecycle & IR LED Sync
Can be run directly on the Raspberry Pi Zero W via pytest.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from camera_service import app, _led_controller


class TestCameraLifecycleLocal:
    @pytest.fixture
    def client(self):
        app.config["TESTING"] = True
        with app.test_client() as client:
            _led_controller.turn_off()
            yield client
            _led_controller.turn_off()

    def test_health_endpoint(self, client):
        res = client.get("/api/v1/camera/health")
        assert res.status_code == 200
        data = res.get_json()
        assert "ir_led" in data
        assert data["ir_led"]["is_on"] is False

    def test_iris_capture_synchronization(self, client):
        res = client.post("/api/v1/camera/iris/capture", json={"eye_side": "OD"})
        assert res.status_code in (200, 500)
        assert _led_controller.is_on() is False

    def test_patient_photo_capture(self, client):
        res = client.post("/api/v1/camera/photo/capture")
        assert res.status_code == 200
        assert _led_controller.is_on() is False
