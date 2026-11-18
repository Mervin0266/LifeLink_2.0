"""
LifeLink 2.0 - Failure Injection and Fault Tolerance Tests
Validates resilience against disconnected peripherals, blurred/glare images,
concurrent scan collisions (409 Conflict), watchdog timeouts, and corrupted serial framing.
"""

import sys
import os
import time
import pytest
from pathlib import Path

# Add protocol directory dynamically
_PROTOCOL_DIR = Path(__file__).resolve().parent.parent.parent / "fingerprint-device" / "protocol"
if str(_PROTOCOL_DIR) not in sys.path:
    sys.path.insert(0, str(_PROTOCOL_DIR))

# Add camera-client directory dynamically
_CAM_DIR = Path(__file__).resolve().parent.parent.parent / "iris-module" / "camera-client"
if str(_CAM_DIR) not in sys.path:
    sys.path.insert(0, str(_CAM_DIR))

from framing import SerialFrame, STATUS_BAD_CHECKSUM, STATUS_ERROR, CMD_HELLO  # type: ignore
from ir_led_controller import IRLEDController  # type: ignore
from backend.app import create_app
from backend.devices.manager import DeviceManager
from backend.devices.mock.mock_camera import MockCameraDevice
from backend.devices.mock.mock_fingerprint import MockFingerprintDevice
from backend.auth.security import SecurityUtils
from backend.auth.rbac import Roles


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


def test_camera_disconnect_failure_injection():
    """Validates graceful failure and safety shutoff when camera disconnects during scan."""
    cam = MockCameraDevice()
    cam.set_failure_mode("disconnect")
    
    status = cam.get_status()
    assert status["connected"] is False
    assert status["status"] == "DISCONNECTED"

    res = cam.capture_iris("OD")
    assert res["status"] == "error"
    assert "disconnected" in res["message"].lower()
    assert cam.ir_led_on is False


def test_iris_blur_failure_injection():
    """Validates ISO/IEC 29794-6 rejection when camera captures out-of-focus blurred frame."""
    cam = MockCameraDevice()
    cam.set_failure_mode("blur")

    res = cam.capture_iris("OD")
    assert res["status"] == "rejected"
    assert res["quality"]["passed"] is False
    assert res["quality"]["sharpness"] < 50.0
    assert any("blurry" in r.lower() for r in res["quality"]["rejection_reasons"])
    assert cam.ir_led_on is False


def test_iris_glare_failure_injection():
    """Validates rejection when corneal reflection / glare exceeds allowable threshold."""
    cam = MockCameraDevice()
    cam.set_failure_mode("glare")

    res = cam.capture_iris("OS")
    assert res["status"] == "rejected"
    assert res["quality"]["passed"] is False
    assert res["quality"]["glare_ratio"] > 5.0
    assert any("glare" in r.lower() for r in res["quality"]["rejection_reasons"])
    assert cam.ir_led_on is False


def test_ir_led_watchdog_auto_shutoff():
    """Verifies that IR LED watchdog timer safely forces shutoff after timeout."""
    led = IRLEDController(pin=18, max_on_time=0.2)
    led.turn_on()
    assert led.is_on() is True

    # Sleep past watchdog
    time.sleep(0.35)
    assert led.is_on() is False


def test_concurrent_iris_scan_collision_returns_409(client, registrar_token):
    """Enforces single-owner camera access: concurrent capture attempts return 409 Conflict."""
    headers = {"Authorization": f"Bearer {registrar_token}"}
    manager = DeviceManager()

    # Pre-occupy camera with an active pending job
    job_id = manager.create_job("iris_capture", "pizero-cam3")

    try:
        # Secondary scan attempt must collide and be rejected
        resp = client.post(
            "/api/v1/devices/camera/capture-iris",
            json={"eye_side": "OD"},
            headers=headers
        )
        assert resp.status_code == 409
        data = resp.get_json()
        assert "busy" in data["message"].lower()
    finally:
        manager.cancel_job(job_id)


def test_concurrent_fingerprint_scan_collision_returns_409(client, registrar_token):
    """Enforces single-owner serial bus access: concurrent fingerprint attempts return 409 Conflict."""
    headers = {"Authorization": f"Bearer {registrar_token}"}
    manager = DeviceManager()

    # Pre-occupy fingerprint device with an active pending job
    job_id = manager.create_job("fingerprint_enroll", "esp32-gt521f32")

    try:
        # Secondary enrollment attempt must collide and be rejected
        resp = client.post(
            "/api/v1/devices/fingerprint/enroll-step",
            json={"finger_position": "R1", "pass_number": 1},
            headers=headers
        )
        assert resp.status_code == 409
        data = resp.get_json()
        assert "busy" in data["message"].lower()
    finally:
        manager.cancel_job(job_id)


def test_device_job_cancellation_wipes_scratch_slot():
    """Confirms cancelling an in-progress enrollment wipes scratch slot 199 and turns LED off."""
    manager = DeviceManager()
    job_id = manager.create_job("fingerprint_enroll", "esp32-gt521f32")
    
    # Simulate partial enrollment putting template in scratch slot 199
    if hasattr(manager.fingerprint, "scratch_slots"):
        manager.fingerprint.scratch_slots[199] = b"\x00" * 498
        manager.fingerprint.set_led(True)

    cancelled = manager.cancel_job(job_id)
    assert cancelled is True

    # Scratch slot 199 must be wiped
    if hasattr(manager.fingerprint, "scratch_slots"):
        assert 199 not in manager.fingerprint.scratch_slots
        assert manager.fingerprint.led_on is False

    job = manager.get_job(job_id)
    assert job is not None
    assert job["status"] == "cancelled"


def test_corrupt_serial_framing_resilience():
    """Validates that corrupt, truncated, or tampered binary serial frames do not crash parser."""
    req_id = b"test-req-0000001"
    valid_packet = SerialFrame.pack(1, CMD_HELLO, req_id, b"PING")

    # 1. Valid packet unpacks properly
    unpacked = SerialFrame.unpack(valid_packet)
    assert unpacked is not None
    assert unpacked.get("payload") == b"PING"

    # 2. Corrupted byte in payload triggers bad CRC
    corrupt_packet = bytearray(valid_packet)
    corrupt_packet[SerialFrame.HEADER_SIZE] ^= 0xFF
    result = SerialFrame.unpack(bytes(corrupt_packet))
    assert result is not None
    assert result.get("error") == "bad_crc"
    assert result.get("status") == STATUS_BAD_CHECKSUM

    # 3. Invalid magic header returns None
    corrupt_magic = b"XXXX" + valid_packet[4:]
    assert SerialFrame.unpack(corrupt_magic) is None

    # 4. Truncated short buffer returns None
    assert SerialFrame.unpack(valid_packet[:10]) is None

    # 5. Pure random noise doesn't raise unhandled exceptions
    random_noise = os.urandom(64)
    noise_res = SerialFrame.unpack(random_noise)
    assert noise_res is None or "error" in noise_res
