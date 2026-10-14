"""
LifeLink 2.0 - Mock Fingerprint Subsystem
Accurately emulates GT-521F32 UART sensor + ESP32 USB serial framed interface in software.
Generates valid synthetic 498-byte templates, simulates 3-stage enrollment passes,
scratch slot zeroization, and 1:1 on-device verification without physical hardware.
"""

import time
import os
import hashlib
import struct
from typing import Dict, Any, Optional, Tuple

MAGIC = b"LLFP"
PROTOCOL_VERSION = 1

# Commands
CMD_HELLO = 0x01
CMD_STATUS = 0x02
CMD_LED = 0x03
CMD_ENROLL_START = 0x10
CMD_ENROLL_PASS = 0x11
CMD_GET_TEMPLATE = 0x12
CMD_LOAD_TEMPLATE = 0x13
CMD_VERIFY_1_1 = 0x14
CMD_DELETE_SLOT = 0x15
CMD_CANCEL = 0x1F


class MockFingerprintDevice:
    """Simulates the ESP32 + GT-521F32 fingerprint peripheral."""

    def __init__(self):
        self.connected = True
        self.led_on = False
        self.active_job_id: Optional[str] = None
        self.scratch_slots: Dict[int, bytes] = {}  # slot_id -> 498-byte template
        self.current_enroll_pass = 0
        self.failure_mode: Optional[str] = None  # None, "disconnect", "timeout", "low_quality"

    def set_failure_mode(self, mode: Optional[str]):
        """Sets an intentional failure mode for negative testing."""
        self.failure_mode = mode

    def connect(self) -> bool:
        if self.failure_mode == "disconnect":
            self.connected = False
            return False
        self.connected = True
        return True

    def get_status(self) -> Dict[str, Any]:
        """Returns device status metadata."""
        if not self.connected or self.failure_mode == "disconnect":
            return {
                "connected": False,
                "device_id": "MOCK-ESP32-GT521F32",
                "firmware_version": "20171018-mock",
                "led_status": False,
                "scratch_slots_in_use": len(self.scratch_slots),
                "status": "DISCONNECTED"
            }
        return {
            "connected": True,
            "device_id": "MOCK-ESP32-GT521F32",
            "firmware_version": "20171018-mock",
            "led_status": self.led_on,
            "scratch_slots_in_use": len(self.scratch_slots),
            "status": "READY"
        }

    def set_led(self, state: bool) -> bool:
        if not self.connected:
            return False
        self.led_on = state
        return True

    def generate_synthetic_template(self, seed: str) -> bytes:
        """
        Generates a deterministic 498-byte synthetic fingerprint template.
        Matches GT-521F32 template specification layout:
        Header (4 bytes) + Feature blocks + Checksum.
        """
        hasher = hashlib.sha256(seed.encode("utf-8"))
        digest = hasher.digest()  # 32 bytes
        # Repeat digest with counter to produce exactly 498 bytes
        buf = bytearray(b"\x55\xAA\x01\x00")  # GT header
        counter = 0
        while len(buf) < 496:
            block = hashlib.sha256(digest + struct.pack("<I", counter)).digest()
            buf.extend(block)
            counter += 1
        buf = buf[:496]
        # Calculate 16-bit checksum
        chk = sum(buf) & 0xFFFF
        buf.extend(struct.pack("<H", chk))
        return bytes(buf)

    def start_enrollment(self, finger_position: str, scratch_slot: int = 199) -> Dict[str, Any]:
        """Initiates 3-pass guided enrollment into scratch slot."""
        if not self.connected or self.failure_mode == "disconnect":
            return {"status": "error", "message": "Sensor disconnected"}
        if self.failure_mode == "timeout":
            return {"status": "error", "message": "Finger detection timed out"}

        self.current_enroll_pass = 1
        self.led_on = True
        return {
            "status": "in_progress",
            "pass": 1,
            "max_passes": 3,
            "finger_position": finger_position,
            "instruction": f"Place {finger_position} on sensor (pass 1 of 3)"
        }

    def advance_enrollment(self, finger_position: str, pass_number: int, scratch_slot: int = 199) -> Dict[str, Any]:
        """Advances enrollment pass."""
        if not self.connected:
            return {"status": "error", "message": "Sensor disconnected"}
        if self.failure_mode == "low_quality":
            return {"status": "retry", "message": "Poor image quality. Place finger flat and press gently."}

        if pass_number < 3:
            self.current_enroll_pass = pass_number + 1
            return {
                "status": "in_progress",
                "pass": self.current_enroll_pass,
                "max_passes": 3,
                "finger_position": finger_position,
                "instruction": f"Lift and place {finger_position} again (pass {self.current_enroll_pass} of 3)"
            }
        else:
            # Pass 3 completed: Generate template and store in scratch slot
            seed = f"synthetic_fp_{finger_position}_{time.time()}"
            template_bytes = self.generate_synthetic_template(seed)
            self.scratch_slots[scratch_slot] = template_bytes
            self.current_enroll_pass = 0
            self.led_on = False
            return {
                "status": "completed",
                "pass": 3,
                "max_passes": 3,
                "finger_position": finger_position,
                "scratch_slot": scratch_slot,
                "template_bytes": template_bytes,
                "template_size": len(template_bytes),
                "instruction": "Fingerprint successfully captured"
            }

    def wipe_scratch_slot(self, slot_id: int = 199) -> bool:
        """Simulates DeleteID(199) scratch slot zeroization."""
        if slot_id in self.scratch_slots:
            del self.scratch_slots[slot_id]
        return True

    def verify_1_to_1(self, live_finger_probe: Any, enrolled_template_bytes: bytes) -> Tuple[bool, float]:
        """
        Simulates on-device 1:1 comparison: loads template into scratch slot,
        captures live finger, compares minutiae, and reports result.
        """
        if not self.connected:
            return False, 0.0
        
        if isinstance(live_finger_probe, (bytes, bytearray)):
            if len(live_finger_probe) == 498 and live_finger_probe == enrolled_template_bytes:
                return True, 0.99
            if len(live_finger_probe) == 498:
                live_template = bytes(live_finger_probe)
            else:
                live_template = self.generate_synthetic_template(live_finger_probe.decode("utf-8", errors="ignore"))
        else:
            live_template = self.generate_synthetic_template(str(live_finger_probe))

        if live_template == enrolled_template_bytes:
            return True, 0.98

        # Calculate synthetic similarity based on byte overlap
        matches = sum(1 for a, b in zip(live_template, enrolled_template_bytes) if a == b)
        similarity = matches / max(len(enrolled_template_bytes), 1)
        matched = similarity > 0.40  # Synthetic threshold for mock
        return matched, round(similarity, 4)
