"""
Unit tests for ESP32 <-> Pi 5 Framed Serial Protocol and CRC32 verification.
"""

import pytest
import uuid
from pathlib import Path
import sys

_PROTOCOL_DIR = Path(__file__).resolve().parent.parent.parent / "fingerprint-device" / "protocol"
if str(_PROTOCOL_DIR) not in sys.path:
    sys.path.insert(0, str(_PROTOCOL_DIR))

from framing import (
    SerialFrame,
    MAGIC,
    PROTOCOL_VERSION,
    KIND_REQUEST,
    KIND_RESPONSE,
    CMD_HELLO,
    CMD_ENROLL_START,
    STATUS_OK,
    STATUS_BAD_CHECKSUM
)


def test_frame_pack_and_unpack():
    req_id = uuid.uuid4().bytes
    payload = b"test_biometric_serial_payload"
    packet = SerialFrame.pack(
        msg_kind=KIND_REQUEST,
        command=CMD_ENROLL_START,
        request_id=req_id,
        payload=payload,
        status=STATUS_OK
    )

    unpacked = SerialFrame.unpack(packet)
    assert unpacked is not None
    assert unpacked["version"] == PROTOCOL_VERSION
    assert unpacked["kind"] == KIND_REQUEST
    assert unpacked["command"] == CMD_ENROLL_START
    assert unpacked["payload"] == payload


def test_frame_corrupted_crc_detection():
    req_id = uuid.uuid4().bytes
    packet = bytearray(SerialFrame.pack(
        msg_kind=KIND_REQUEST,
        command=CMD_HELLO,
        request_id=req_id,
        payload=b"test"
    ))

    # Corrupt last byte (CRC)
    packet[-1] ^= 0xFF
    result = SerialFrame.unpack(bytes(packet))
    assert result is not None
    assert result.get("error") == "bad_crc"
    assert result.get("status") == STATUS_BAD_CHECKSUM
