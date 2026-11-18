"""
LifeLink 2.0 - Wired ESP32 Fingerprint Host Client
Communicates with the ESP32 + GT-521F32 sensor over USB serial using the LLFP binary framing protocol.
Handles port discovery, handshakes, 3-stage enrollment, 1:1 on-sensor verification,
and automatic reconnection recovery.
"""

import logging
import os
import struct
import time
import uuid
import sys
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

from backend.config import Config

_CANDIDATE_DIRS = [
    Path(__file__).resolve().parent.parent.parent / "protocol",
    Path(__file__).resolve().parent.parent.parent / "fingerprint-device" / "protocol",
    Path(__file__).resolve().parent / "protocol",
    Path(__file__).resolve().parent,
]
for p in _CANDIDATE_DIRS:
    if p.exists() and str(p) not in sys.path:
        sys.path.insert(0, str(p))

from framing import (  # type: ignore
    SerialFrame,
    KIND_REQUEST,
    KIND_RESPONSE,
    CMD_HELLO,
    CMD_STATUS,
    CMD_LED,
    CMD_ENROLL_START,
    CMD_ENROLL_PASS,
    CMD_GET_TEMPLATE,
    CMD_LOAD_TEMPLATE,
    CMD_VERIFY_1_1,
    CMD_DELETE_SLOT,
    CMD_CAPTURE_SINGLE,
    CMD_CANCEL,
    STATUS_OK
)

logger = logging.getLogger("LifeLink.FingerprintHost")


class FingerprintHostClient:
    """Wired serial host driver for ESP32 and GT-521F32 optical fingerprint sensor."""

    def __init__(self, port: Optional[str] = None, baud_rate: Optional[int] = None):
        self.port = port or Config.ESP32_SERIAL_PORT
        self.baud_rate = baud_rate or Config.ESP32_BAUD_RATE
        self.ser = None
        self.connected = False
        self.led_on = False
        self.device_id = "ESP32-GT521F32"
        self.firmware_version = "Unknown"
        self._auto_discover_and_connect()

    def _auto_discover_and_connect(self) -> bool:
        """Attempts to open the serial port to the ESP32."""
        try:
            import serial  # pyserial
        except ImportError:
            logger.warning("[FINGERPRINT HOST] pyserial not installed. Serial communication unavailable.")
            self.connected = False
            return False

        # Attempt configured port first
        candidates = [self.port] if self.port else []
        for p in ["/dev/lifelink-fingerprint", "/dev/ttyUSB0", "/dev/ttyUSB1", "/dev/ttyACM0", "/dev/ttyACM1"]:
            if p not in candidates:
                candidates.append(p)

        # On Linux, scan /dev/serial/by-id if configured port doesn't exist
        if os.path.exists("/dev/serial/by-id"):
            for entry in os.listdir("/dev/serial/by-id"):
                full_path = os.path.join("/dev/serial/by-id", entry)
                if full_path not in candidates:
                    candidates.append(full_path)

        for candidate in candidates:
            if not candidate or not os.path.exists(candidate):
                continue
            try:
                self.ser = serial.Serial(candidate, baudrate=self.baud_rate, timeout=1.0)
                # Send HELLO handshake
                req_id = uuid.uuid4().bytes[:16]
                hello_packet = SerialFrame.pack(KIND_REQUEST, CMD_HELLO, req_id)
                self.ser.write(hello_packet)
                resp_bytes = self.ser.read(64)
                frame = SerialFrame.unpack(resp_bytes)
                if frame and frame.get("status") == STATUS_OK:
                    self.port = candidate
                    self.connected = True
                    self.firmware_version = frame.get("payload", b"").decode("utf-8", errors="ignore") or "2.0-wired"
                    logger.info(f"[FINGERPRINT HOST] Connected to ESP32 on {candidate} (v{self.firmware_version})")
                    return True
                else:
                    self.ser.close()
                    self.ser = None
            except Exception as e:
                logger.debug(f"[FINGERPRINT HOST] Failed candidate {candidate}: {e}")
                if self.ser:
                    try:
                        self.ser.close()
                    except Exception:
                        pass
                    self.ser = None

        self.connected = False
        return False

    def get_status(self) -> Dict[str, Any]:
        """Returns peripheral status and connection readiness."""
        if not self.connected or not self.ser or not self.ser.is_open:
            # Attempt non-blocking reconnection check
            if not self._auto_discover_and_connect():
                return {
                    "connected": False,
                    "device_id": self.device_id,
                    "transport": f"USB-Serial ({self.port})",
                    "status": "DISCONNECTED",
                    "error": "Device port not detected"
                }

        return {
            "connected": True,
            "device_id": self.device_id,
            "transport": f"USB-Serial ({self.port})",
            "baud_rate": self.baud_rate,
            "firmware_version": self.firmware_version,
            "status": "READY"
        }

    def is_connected(self) -> bool:
        """Returns True if the peripheral is connected and ready."""
        return bool(self.get_status().get("connected", False))

    def set_led(self, state: bool) -> bool:
        """Controls optical backlight LED via CMD_LED."""
        self.led_on = state
        if self.ser is None or not getattr(self.ser, "is_open", False):
            return False
        try:
            req_id = uuid.uuid4().bytes[:16]
            payload = struct.pack("<?", state)
            packet = SerialFrame.pack(KIND_REQUEST, CMD_LED, req_id, payload=payload)
            self.ser.write(packet)
            return True
        except Exception:
            return False

    def start_enrollment(self, finger_position: str) -> Dict[str, Any]:
        """
        Sends enrollment command to ESP32.
        If Config.SINGLE_IMPRESSION_ENROLL is enabled, performs 1-stage capture and extracts template.
        Otherwise, initiates standard 3-pass guided enrollment.
        """
        if not self.get_status()["connected"] or self.ser is None:
            return {"status": "error", "message": "ESP32 fingerprint sensor disconnected"}

        if getattr(Config, "SINGLE_IMPRESSION_ENROLL", False):
            return self.capture_single_impression(finger_position)

        try:
            req_id = uuid.uuid4().bytes[:16]
            payload = finger_position.encode("utf-8")
            packet = SerialFrame.pack(KIND_REQUEST, CMD_ENROLL_START, req_id, payload=payload)
            self.ser.write(packet)
            resp = self._read_frame(timeout=7.0)
            if resp and resp.get("status") == STATUS_OK:
                return {
                    "status": "in_progress",
                    "pass": 2,
                    "max_passes": 3,
                    "instruction": f"Place {finger_position} again (pass 2 of 3)"
                }
            # Abort cleanly to ensure LED is turned off
            self.cancel()
            return {"status": "retry", "message": "Finger not detected. Please press flat on the sensor."}
        except Exception as e:
            self.cancel()
            return {"status": "error", "message": str(e)}

    def capture_single_impression(self, finger_position: str) -> Dict[str, Any]:
        """
        Executes single-impression capture on GT-521F32 and returns 498-byte template.
        Supports direct CMD_CAPTURE_SINGLE or auto-fallback to scratch slot sequence.
        Guarantees LED is extinguished upon completion or error.
        """
        if not self.get_status()["connected"] or self.ser is None:
            return {"status": "error", "message": "ESP32 fingerprint sensor disconnected"}

        try:
            req_id = uuid.uuid4().bytes[:16]
            payload = finger_position.encode("utf-8")
            packet = SerialFrame.pack(KIND_REQUEST, CMD_CAPTURE_SINGLE, req_id, payload=payload)
            self.ser.write(packet)
            resp = self._read_frame(timeout=9.0)

            if resp and resp.get("status") == STATUS_OK:
                template_bytes = resp.get("payload", b"")
                if len(template_bytes) == 498:
                    self.wipe_scratch_slot(199)
                    self.set_led(False)
                    return {
                        "status": "completed",
                        "pass": 1,
                        "max_passes": 1,
                        "template_bytes": template_bytes,
                        "instruction": f"{finger_position} probe acquired successfully"
                    }

            # If CMD_CAPTURE_SINGLE failed or returned non-OK, fall back to proven scratch enrollment
            logger.info("[FINGERPRINT HOST] Direct capture non-OK, engaging scratch sequence fallback...")
            fallback_res = self._fallback_scratch_capture(finger_position)
            if fallback_res.get("status") == "completed":
                return fallback_res

            self.cancel()
            err_msg = "Single impression capture failed. Press finger flat."
            if resp and resp.get("payload"):
                try:
                    p_txt = resp["payload"].decode("utf-8", errors="ignore")
                    if p_txt:
                        err_msg = f"{p_txt}. Press finger flat and retry."
                except Exception:
                    pass
            return {"status": "retry", "message": err_msg}
        except Exception as e:
            self.cancel()
            return {"status": "error", "message": str(e)}

    def _fallback_scratch_capture(self, finger_position: str) -> Dict[str, Any]:
        """
        Fallback capture for GT-521F32 sensor using CMD_ENROLL_START -> CMD_ENROLL_PASS -> CMD_GET_TEMPLATE.
        Allows the operator to simply place and hold their finger on the sensor.
        """
        if self.ser is None or not getattr(self.ser, "is_open", False):
            return {"status": "error", "message": "Serial connection closed"}

        try:
            # Step 1: Enroll Start on Scratch Slot 199
            req_id = uuid.uuid4().bytes[:16]
            pkt1 = SerialFrame.pack(KIND_REQUEST, CMD_ENROLL_START, req_id, payload=finger_position.encode("utf-8"))
            self.ser.write(pkt1)
            resp1 = self._read_frame(timeout=8.0)
            if not resp1 or resp1.get("status") != STATUS_OK:
                return {"status": "retry", "message": "No finger detected on sensor. Press finger flat."}

            # Step 2: Pass 2 (finger is held on sensor)
            req_id = uuid.uuid4().bytes[:16]
            pkt2 = SerialFrame.pack(KIND_REQUEST, CMD_ENROLL_PASS, req_id, payload=struct.pack("<B", 2))
            time.sleep(0.1)
            self.ser.write(pkt2)
            resp2 = self._read_frame(timeout=5.0)

            # Step 3: Pass 3 (finger is held on sensor)
            req_id = uuid.uuid4().bytes[:16]
            pkt3 = SerialFrame.pack(KIND_REQUEST, CMD_ENROLL_PASS, req_id, payload=struct.pack("<B", 3))
            time.sleep(0.1)
            self.ser.write(pkt3)
            resp3 = self._read_frame(timeout=5.0)

            # Step 4: Retrieve Template
            req_id = uuid.uuid4().bytes[:16]
            t_pkt = SerialFrame.pack(KIND_REQUEST, CMD_GET_TEMPLATE, req_id)
            self.ser.write(t_pkt)
            t_resp = self._read_frame(timeout=5.0)

            template_bytes = t_resp.get("payload", b"") if t_resp else b""
            self.wipe_scratch_slot(199)
            self.set_led(False)

            if template_bytes and len(template_bytes) == 498:
                return {
                    "status": "completed",
                    "pass": 1,
                    "max_passes": 1,
                    "template_bytes": template_bytes,
                    "instruction": f"{finger_position} probe acquired successfully"
                }

            return {"status": "retry", "message": "Template extraction failed. Reposition finger and retry."}
        except Exception as exc:
            logger.error(f"[FINGERPRINT HOST] Fallback scratch capture error: {exc}")
            self.cancel()
            return {"status": "error", "message": str(exc)}

    def advance_enrollment(self, finger_position: str, pass_number: int) -> Dict[str, Any]:
        """Advances enrollment pass (pass 2 or pass 3)."""
        if not self.get_status()["connected"] or self.ser is None:
            return {"status": "error", "message": "Sensor disconnected"}

        try:
            req_id = uuid.uuid4().bytes[:16]
            payload = struct.pack("<B", pass_number)
            packet = SerialFrame.pack(KIND_REQUEST, CMD_ENROLL_PASS, req_id, payload=payload)
            self.ser.write(packet)
            resp = self._read_frame(timeout=7.0)

            if not resp or resp.get("status") != STATUS_OK:
                self.cancel()
                return {"status": "retry", "message": "Finger not detected. Please press flat on the sensor."}

            if pass_number < 3:
                return {
                    "status": "in_progress",
                    "pass": pass_number + 1,
                    "max_passes": 3,
                    "instruction": f"Place {finger_position} once more (pass 3 of 3)"
                }
            else:
                # Pass 3 completed: request final 498-byte template from scratch slot
                t_packet = SerialFrame.pack(KIND_REQUEST, CMD_GET_TEMPLATE, req_id)
                self.ser.write(t_packet)
                t_resp = self._read_frame(timeout=4.0)
                template_bytes = t_resp.get("payload", b"") if t_resp else b""
                self.wipe_scratch_slot(199)
                self.set_led(False)
                return {
                    "status": "completed",
                    "pass": 3,
                    "max_passes": 3,
                    "template_bytes": template_bytes,
                    "instruction": "Enrolled successfully"
                }
        except Exception as e:
            self.cancel()
            return {"status": "error", "message": str(e)}

    @staticmethod
    def compare_templates(probe_bytes: bytes, enrolled_bytes: bytes) -> Tuple[bool, float]:
        """
        Compares two GT-521F32 498-byte templates in software.
        Evaluates exact match, byte correlation, and minutiae block overlap.
        """
        if not probe_bytes or not enrolled_bytes:
            return False, 0.0
        if probe_bytes == enrolled_bytes:
            return True, 0.99
        min_len = min(len(probe_bytes), len(enrolled_bytes))
        if min_len == 0:
            return False, 0.0

        byte_matches = sum(1 for a, b in zip(probe_bytes[:min_len], enrolled_bytes[:min_len]) if a == b)
        byte_score = byte_matches / min_len

        # GT-521F32 minutiae feature block comparison (header: 4B, blocks: 4B each)
        feature_matches = 0.0
        num_blocks = (min_len - 4) // 4
        if num_blocks > 0:
            for b in range(num_blocks):
                p_blk = probe_bytes[4 + b * 4 : 4 + (b + 1) * 4]
                e_blk = enrolled_bytes[4 + b * 4 : 4 + (b + 1) * 4]
                if p_blk == e_blk:
                    feature_matches += 1.0
                elif len(p_blk) >= 2 and len(e_blk) >= 2:
                    if abs(p_blk[0] - e_blk[0]) <= 3 and abs(p_blk[1] - e_blk[1]) <= 3:
                        feature_matches += 0.75
            feature_score = feature_matches / num_blocks
            score = max(byte_score, feature_score)
        else:
            score = byte_score

        matched = score >= 0.50
        return matched, round(float(score), 4)

    def verify_1_1(self, probe_bytes: Any, enrolled_template_bytes: bytes) -> Tuple[bool, float]:
        """
        Compares a probe template against an enrolled template.
        If probe_bytes is provided as a template buffer, performs software minutiae comparison.
        If probe_bytes is omitted, empty, or 'live', requests on-sensor verification against scratch slot 199.
        """
        if isinstance(probe_bytes, (bytes, bytearray)) and len(probe_bytes) > 0 and probe_bytes != b"live":
            return self.compare_templates(bytes(probe_bytes), enrolled_template_bytes)

        if not self.get_status()["connected"] or self.ser is None:
            return False, 0.0

        try:
            req_id = uuid.uuid4().bytes[:16]
            # Load template
            load_packet = SerialFrame.pack(KIND_REQUEST, CMD_LOAD_TEMPLATE, req_id, payload=enrolled_template_bytes)
            self.ser.write(load_packet)
            resp = self._read_frame(timeout=3.0)

            # Execute verify
            v_packet = SerialFrame.pack(KIND_REQUEST, CMD_VERIFY_1_1, req_id)
            self.ser.write(v_packet)
            v_resp = self._read_frame(timeout=7.0)

            if v_resp and v_resp.get("status") == STATUS_OK:
                return True, 0.95
            return False, 0.15
        except Exception as e:
            logger.error(f"[FINGERPRINT HOST] Error during 1:1 verify: {e}")
            return False, 0.0
        finally:
            self.wipe_scratch_slot(199)
            self.set_led(False)

    # Backward and cross-module compatibility alias
    verify_1_to_1 = verify_1_1

    def wipe_scratch_slot(self, slot_id: int = 199) -> bool:
        """Zeroizes temporary RAM slot on sensor for biometric protection."""
        if self.ser is None or not getattr(self.ser, "is_open", False):
            return True
        try:
            req_id = uuid.uuid4().bytes[:16]
            packet = SerialFrame.pack(KIND_REQUEST, CMD_DELETE_SLOT, req_id, payload=struct.pack("<H", slot_id))
            self.ser.write(packet)
            return True
        except Exception:
            return False

    def cancel(self) -> bool:
        """Cancels active sensor acquisition and guarantees LED is OFF."""
        self.led_on = False
        if self.ser is None or not getattr(self.ser, "is_open", False):
            return True
        try:
            req_id = uuid.uuid4().bytes[:16]
            packet = SerialFrame.pack(KIND_REQUEST, CMD_CANCEL, req_id)
            self.ser.write(packet)
            self.wipe_scratch_slot(199)
            return True
        except Exception:
            return False

    def _read_frame(self, timeout: float = 7.0) -> Optional[Dict[str, Any]]:
        """Reads and unpacks a binary LLFP response frame from serial buffer."""
        if self.ser is None or not getattr(self.ser, "is_open", False):
            return None
        ser = self.ser
        start_t = time.time()
        buf = bytearray()
        while time.time() - start_t < timeout:
            if ser.in_waiting:
                chunk = ser.read(ser.in_waiting)
                buf.extend(chunk)
                frame = SerialFrame.unpack(bytes(buf))
                if frame:
                    return frame
            time.sleep(0.02)
        return None
