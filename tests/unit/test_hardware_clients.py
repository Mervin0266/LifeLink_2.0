"""
LifeLink 2.0 - Unit Tests for Wired Hardware Host Clients & Autoconnect
Tests CameraHostClient (HTTP over USB gadget ethernet) and FingerprintHostClient (serial LLFP).
"""

import pytest
from unittest.mock import patch, MagicMock
from backend.devices.camera_host import CameraHostClient
from backend.devices.fingerprint_host import FingerprintHostClient
from backend.devices.manager import DeviceManager
from backend.config import Config


def test_camera_host_client_disconnected_handling():
    """Verifies CameraHostClient returns DISCONNECTED gracefully when daemon is unreachable."""
    client = CameraHostClient(base_url="http://127.0.0.1:59999", timeout=0.2)
    status = client.get_status()
    assert status["connected"] is False
    assert status["status"] == "DISCONNECTED"
    assert "error" in status


def test_camera_host_client_connected_handling():
    """Verifies CameraHostClient correctly parses health and IR LED state from daemon."""
    client = CameraHostClient(base_url="http://mock-pizero:5001")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": "ready",
        "device": "PiZeroW-CameraModule3-NoIR",
        "transport": "USB-Gadget-Ethernet (192.168.55.2)",
        "camera_state": "IDLE",
        "ir_led": {"is_on": False, "pin": 18, "enabled": True}
    }

    with patch("requests.get", return_value=mock_resp):
        status = client.get_status()
        assert status["connected"] is True
        assert status["status"] == "READY"
        assert status["camera_state"] == "IDLE"
        assert status["ir_led"]["is_on"] is False


def test_camera_host_client_capture_iris():
    """Verifies CameraHostClient captures binary JPEG frames."""
    client = CameraHostClient(base_url="http://mock-pizero:5001")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"\xff\xd8\xff\xe0\x00\x10JFIF"  # JPEG header bytes

    with patch("requests.post", return_value=mock_resp):
        res = client.capture_iris(eye_side="OD")
        assert res["status"] == "completed"
        assert res["eye_side"] == "OD"
        assert len(res["image_bytes"]) > 0


def test_fingerprint_host_client_disconnected_handling():
    """Verifies FingerprintHostClient reports DISCONNECTED when serial port is unavailable."""
    client = FingerprintHostClient(port="/dev/nonexistent_serial_port")
    status = client.get_status()
    assert status["connected"] is False
    assert status["status"] == "DISCONNECTED"


def test_fingerprint_host_client_operations_when_disconnected():
    """Verifies enrollment and verification safely abort with clean error when disconnected."""
    client = FingerprintHostClient(port="/dev/nonexistent_serial_port")
    enroll_res = client.start_enrollment("R1")
    assert enroll_res["status"] == "error"
    assert "disconnected" in enroll_res["message"].lower()

    matched, score = client.verify_1_1(b"probe", b"enrolled")
    assert matched is False
    assert score == 0.0


def test_device_manager_mode_switching():
    """Verifies DeviceManager properly toggles between MOCK and HARDWARE modes."""
    manager = DeviceManager()
    original_mode = Config.MOCK_MODE
    try:
        # Mock mode
        Config.MOCK_MODE = True
        manager._init_devices()
        assert manager.mode == "MOCK"
        assert manager.fingerprint.__class__.__name__ == "MockFingerprintDevice"
        assert manager.camera.__class__.__name__ == "MockCameraDevice"

        # Hardware mode
        Config.MOCK_MODE = False
        manager._init_devices()
        assert manager.mode == "HARDWARE"
        assert manager.fingerprint.__class__.__name__ == "FingerprintHostClient"
        assert manager.camera.__class__.__name__ == "CameraHostClient"
    finally:
        Config.MOCK_MODE = original_mode
        manager._init_devices()
