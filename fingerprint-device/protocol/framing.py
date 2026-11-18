"""
LifeLink 2.0 - USB Serial Framed Protocol for Fingerprint Peripheral
Defines packet framing, CRC32 checksums, request IDs, and commands for the ESP32 <-> Pi 5 link.
"""

import struct

# This module also runs on the ESP32 under MicroPython (copied next to main.py), which
# has no `typing` or `uuid` module and provides CRC32 as `binascii.crc32`, not `zlib.crc32`.
try:
    from zlib import crc32 as _crc32
except ImportError:  # MicroPython
    from binascii import crc32 as _crc32  # type: ignore

try:
    from typing import Optional, Dict, Any
except ImportError:  # MicroPython
    pass

MAGIC = b"LLFP"
PROTOCOL_VERSION = 1

# Message Kinds
KIND_REQUEST = 0x01
KIND_RESPONSE = 0x02
KIND_EVENT = 0x03

# Commands
CMD_HELLO = 0x0001
CMD_STATUS = 0x0002
CMD_LED = 0x0003
CMD_ENROLL_START = 0x0010
CMD_ENROLL_PASS = 0x0011
CMD_GET_TEMPLATE = 0x0012
CMD_LOAD_TEMPLATE = 0x0013
CMD_VERIFY_1_1 = 0x0014
CMD_DELETE_SLOT = 0x0015
CMD_CAPTURE_SINGLE = 0x0016
CMD_CANCEL = 0x001F

# Status Codes
STATUS_OK = 0x0000
STATUS_ERROR = 0x0001
STATUS_TIMEOUT = 0x0002
STATUS_BAD_CHECKSUM = 0x0003
STATUS_BUSY = 0x0004
STATUS_BAD_FINGER = 0x0005


class SerialFrame:
    """Pack and unpack framed binary packets for the ESP32 USB serial link."""

    HEADER_FORMAT = "<4sBB16sHHH"  # magic(4), ver(1), kind(1), req_id(16), cmd(2), status(2), payload_len(2)
    HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 28 bytes

    @classmethod
    def pack(
        cls,
        msg_kind: int,
        command: int,
        request_id: bytes,
        payload: bytes = b"",
        status: int = STATUS_OK
    ) -> bytes:
        """Packs a frame with header, payload, and 32-bit CRC."""
        if len(request_id) != 16:
            request_id = (bytes(request_id) + b"\x00" * 16)[:16]

        payload_len = len(payload)
        header = struct.pack(
            cls.HEADER_FORMAT,
            MAGIC,
            PROTOCOL_VERSION,
            msg_kind,
            request_id,
            command,
            status,
            payload_len
        )
        packet_without_crc = header + payload
        crc = _crc32(packet_without_crc) & 0xFFFFFFFF
        return packet_without_crc + struct.pack("<I", crc)

    @classmethod
    def unpack(cls, raw_bytes: bytes) -> "Optional[Dict[str, Any]]":
        """Unpacks and validates a binary frame with magic alignment and CRC verification."""
        idx = raw_bytes.find(MAGIC)
        if idx == -1:
            return None
        if idx > 0:
            raw_bytes = raw_bytes[idx:]

        if len(raw_bytes) < cls.HEADER_SIZE:
            return None

        header_bytes = raw_bytes[:cls.HEADER_SIZE]
        magic, ver, kind, req_id, cmd, status, plen = struct.unpack(
            cls.HEADER_FORMAT, header_bytes
        )
        total_len = cls.HEADER_SIZE + plen + 4
        if len(raw_bytes) < total_len:
            return None  # Full frame not yet arrived

        packet_bytes = raw_bytes[:total_len]
        expected_crc = struct.unpack("<I", packet_bytes[-4:])[0]
        actual_crc = _crc32(packet_bytes[:-4]) & 0xFFFFFFFF
        if expected_crc != actual_crc:
            return {"error": "bad_crc", "status": STATUS_BAD_CHECKSUM}

        payload = packet_bytes[cls.HEADER_SIZE:-4]
        return {
            "version": ver,
            "kind": kind,
            "request_id": req_id,
            "command": cmd,
            "status": status,
            "payload": payload
        }
