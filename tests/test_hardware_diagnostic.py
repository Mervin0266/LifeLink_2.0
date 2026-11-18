"""
LifeLink 2.0 - Unit Tests for Hardware Diagnostic Tool
Tests LLFP framing, component filtering, harness execution, report generation, and mocked hardware responses.
"""

import json
import os
import tempfile
import uuid
from pathlib import Path
import pytest

from lifelink_hardware_diagnostic import (
    LLFPSerialFrame,
    KIND_REQUEST,
    KIND_RESPONSE,
    CMD_HELLO,
    CMD_STATUS,
    STATUS_OK,
    STATUS_BAD_CHECKSUM,
    DiagnosticResult,
    HardwareDiagnosticHarness
)


def test_llfp_framing_pack_unpack():
    """Verifies binary framing packing, CRC32 computation, and unpacking."""
    req_id = uuid.uuid4().bytes[:16]
    payload = b"LifeLink-ESP32-v2.0-wired"
    
    # Pack frame
    packet = LLFPSerialFrame.pack(
        msg_kind=KIND_RESPONSE,
        command=CMD_HELLO,
        request_id=req_id,
        payload=payload,
        status=STATUS_OK
    )
    assert len(packet) == 28 + len(payload) + 4
    assert packet[:4] == b"LLFP"
    
    # Unpack frame
    frame = LLFPSerialFrame.unpack(packet)
    assert frame is not None
    assert frame["version"] == 1
    assert frame["kind"] == KIND_RESPONSE
    assert frame["command"] == CMD_HELLO
    assert frame["status"] == STATUS_OK
    assert frame["payload"] == payload


def test_llfp_framing_corrupted_crc():
    """Verifies that frame corruption is rejected with STATUS_BAD_CHECKSUM."""
    req_id = uuid.uuid4().bytes[:16]
    packet = bytearray(LLFPSerialFrame.pack(KIND_REQUEST, CMD_STATUS, req_id))
    # Corrupt a byte in payload
    packet[-2] = (packet[-2] + 1) % 256
    
    frame = LLFPSerialFrame.unpack(bytes(packet))
    assert frame is not None
    assert frame.get("status") == STATUS_BAD_CHECKSUM


def test_diagnostic_result_serialization():
    """Verifies result object dictionary formatting."""
    res = DiagnosticResult(
        test_id="SYS-01",
        section="PI 5 SYSTEM",
        name="Host Check",
        status="PASS",
        summary="Test passed successfully",
        details={"key": "val"},
        duration_ms=12.3456
    )
    d = res.to_dict()
    assert d["test_id"] == "SYS-01"
    assert d["status"] == "PASS"
    assert d["duration_ms"] == 12.35
    assert d["details"]["key"] == "val"


def test_harness_component_filters():
    """Verifies that component selection flags isolate diagnostic execution."""
    harness = HardwareDiagnosticHarness(components=["esp32", "fingerprint"])
    assert harness.should_run_section("esp32") is True
    assert harness.should_run_section("fingerprint") is True
    assert harness.should_run_section("sys") is False
    assert harness.should_run_section("camera") is False

    harness_all = HardwareDiagnosticHarness(components=[])
    assert harness_all.should_run_section("sys") is True
    assert harness_all.should_run_section("camera") is True


def test_harness_sys_verification_and_reporting():
    """Verifies system diagnostic execution and JSON/TXT report outputs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        harness = HardwareDiagnosticHarness(
            mode="quick",
            components=["sys"],
            output_dir=tmpdir
        )
        harness.run_all()
        
        # Verify reports generated
        json_files = list(Path(tmpdir).glob("*.json"))
        txt_files = list(Path(tmpdir).glob("*.txt"))
        assert len(json_files) == 1
        assert len(txt_files) == 1
        
        # Verify JSON report structure
        with open(json_files[0], "r", encoding="utf-8") as f:
            data = json.load(f)
            assert "metadata" in data
            assert "summary" in data
            assert data["summary"]["total"] >= 5
            assert "manual_physical_inspection_checklist" in data
            assert len(data["manual_physical_inspection_checklist"]) == 6


def test_mocked_camera_network_and_preview(monkeypatch):
    """Verifies camera preview frame unpacking and status parsing with mocked endpoints."""
    # Mock http_request to return health and JPEG frames
    mock_jpeg = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"\x00" * 2500 + b"\xff\xd9"
    
    def fake_http_request(self, url, method="GET", headers=None, json_data=None, timeout=None):
        if "health" in url:
            body = json.dumps({
                "status": "ready",
                "device": "RaspberryPi-3B-Plus-CameraModule3-NoIR",
                "sensor": "Sony IMX708 NoIR",
                "ir_led": {"pin": 18, "is_on": False, "enabled": True}
            }).encode()
            return 200, body, {}
        elif "capture" in url:
            return 200, mock_jpeg, {"X-Quality-Sharpness": "78.5", "X-Quality-Passed": "true"}
        elif "preview/stop" in url or "cancel" in url:
            return 200, b'{"status": "stopped"}', {}
        elif "state" in url:
            return 200, b'{"state": "IDLE", "led_active": false}', {}
        elif "led/status" in url:
            return 200, b'{"ir_led": {"pin": 18, "active_high": true, "enabled": true, "is_on": false}}', {}
        return 404, b'{"error": "not found"}', {}

    monkeypatch.setattr(HardwareDiagnosticHarness, "http_request", fake_http_request)

    with tempfile.TemporaryDirectory() as tmpdir:
        harness = HardwareDiagnosticHarness(
            mode="full",
            components=["camera"],
            output_dir=tmpdir
        )
        harness.camera_service_online = True
        harness.test_pi3_service()
        harness.test_ir_illuminator()
        
        # Verify test results recorded
        srv_res = [r for r in harness.results if r.test_id == "SRV-01"]
        ir_res = [r for r in harness.results if r.test_id == "IR-01"]
        assert len(srv_res) == 1
        assert srv_res[0].status == "PASS"
        assert len(ir_res) == 1
        assert ir_res[0].status == "PASS"
