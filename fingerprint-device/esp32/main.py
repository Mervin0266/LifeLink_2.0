"""
LifeLink 2.0 - ESP32 MicroPython Firmware Daemon
Listens on USB CDC serial for binary-framed LLFP commands from Raspberry Pi 5.
Coordinates GT-521F32 sensor operations over UART2 and returns binary responses.

MANDATORY BEHAVIOR:
Sensor backlight and optical scanning remain strictly IDLE and OFF until
explicit command is received from the Pi 5 terminal following a GUI button click.
"""

import sys
try:
    import utime  # type: ignore
except ImportError:
    import time
    class _UtimeCompat:
        @staticmethod
        def sleep_ms(ms: int):
            time.sleep(ms / 1000.0)
        @staticmethod
        def ticks_ms() -> int:
            return int(time.time() * 1000)
        @staticmethod
        def ticks_diff(t1: int, t2: int) -> int:
            return t1 - t2
    utime = _UtimeCompat()

try:
    import select
except ImportError:
    select = None

try:
    from fplibMicro import Fingerprint, SensorError, TEMPLATE_SIZE  # type: ignore
    from framing import (  # type: ignore
        SerialFrame,
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
        STATUS_OK,
        STATUS_ERROR,
        STATUS_BAD_FINGER,
        STATUS_TIMEOUT
    )
except ImportError:
    import os
    _P = os.path.dirname(__file__)
    if _P not in sys.path:
        sys.path.insert(0, _P)
    from fplibMicro import Fingerprint, SensorError, TEMPLATE_SIZE  # type: ignore
    from framing import (  # type: ignore
        SerialFrame,
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
        STATUS_OK,
        STATUS_ERROR,
        STATUS_BAD_FINGER,
        STATUS_TIMEOUT
    )

FIRMWARE_VERSION = b"LifeLink-ESP32-v2.0-wired"
SCRATCH_SLOT = 199
# Commands that need no sensor access
_NO_SENSOR_COMMANDS = (CMD_HELLO, CMD_STATUS)


class ESP32FirmwareDaemon:
    """Firmware event loop for USB serial command execution."""

    def __init__(self):
        # GT-521F32 connected to ESP32 UART2 (TX=GPIO17, RX=GPIO16, Baud=9600)
        self.sensor = Fingerprint(port=2, baud=9600, tx=17, rx=16)
        self.sensor_ready = False
        self._init_hardware()

    def _init_hardware(self):
        """Initializes sensor and guarantees LED is OFF at startup. Never raises."""
        self.sensor_ready = bool(self.sensor.init())
        if not self.sensor_ready:
            print("[FPS] sensor init failed: %s" % self.sensor.last_error)
            return
        try:
            # Guarantee optical backlight is OFF at startup
            if not self.sensor.set_led(False):
                print("[FPS] LED-off NACK: %s" % self.sensor.last_error)
        except SensorError as exc:
            print("[FPS] LED-off failed: %s" % exc)
            self.sensor_ready = False

    @staticmethod
    def _error_payload(prefix, detail):
        """Short ASCII failure text for the host (shown to the operator)."""
        text = prefix if not detail else "%s: %s" % (prefix, detail)
        return text.encode()[:96]

    def _cleanup_after_failure(self):
        """Best effort after a sensor failure: LED off and scratch slot wiped."""
        try:
            self.sensor.set_led(False)
            self.sensor.delete_id(SCRATCH_SLOT)
        except Exception:
            pass

    def _begin_enrollment(self):
        """Clears scratch slot 199 (EnrollStart NACKs on a used slot) and starts enrollment."""
        self.sensor.delete_id(SCRATCH_SLOT)  # NACK 'is_not_used' simply means it was empty
        return self.sensor.enroll_start(SCRATCH_SLOT)

    def _wait_for_finger(self, timeout_ms):
        start = utime.ticks_ms()
        while utime.ticks_diff(utime.ticks_ms(), start) < timeout_ms:
            if self.sensor.is_press_finger():
                return True
            utime.sleep_ms(50)
        return False

    def send_response(self, command: int, req_id: bytes, status: int = STATUS_OK, payload: bytes = b""):
        """Packs and writes binary response frame to USB serial stdout."""
        pkt = SerialFrame.pack(KIND_RESPONSE, command, req_id, payload=payload, status=status)
        sys.stdout.buffer.write(pkt)

    def handle_command(self, frame: dict):
        """
        Executes one host command and always answers it (echoing command and request ID).
        A sensor transport failure is reported as STATUS_TIMEOUT / STATUS_ERROR with the
        cause, never as success, and marks the sensor for re-initialisation.
        """
        cmd = frame.get("command")
        if cmd is None or not isinstance(cmd, int):
            return
        req_id = frame.get("request_id", b"\x00" * 16)
        payload = frame.get("payload", b"")

        if cmd not in _NO_SENSOR_COMMANDS and not self.sensor_ready:
            self._init_hardware()
            if not self.sensor_ready:
                self.send_response(cmd, req_id, STATUS_ERROR,
                                   payload=self._error_payload("Sensor not ready", self.sensor.last_error))
                return
        try:
            self._dispatch(cmd, req_id, payload)
        except SensorError as exc:
            print("[FPS] sensor error during 0x%04x: %s" % (cmd, exc))
            self.sensor_ready = False
            self._cleanup_after_failure()
            self.send_response(cmd, req_id, STATUS_TIMEOUT if exc.timeout else STATUS_ERROR,
                               payload=self._error_payload("Sensor communication error", str(exc)))
        except Exception as exc:
            print("[FPS] firmware error during 0x%04x: %s" % (cmd, exc))
            self._cleanup_after_failure()
            self.send_response(cmd, req_id, STATUS_ERROR, payload=self._error_payload("Firmware error", str(exc)))

    def _dispatch(self, cmd, req_id, payload):
        # 1. Handshake / Ping
        if cmd == CMD_HELLO:
            self.send_response(cmd, req_id, STATUS_OK, payload=FIRMWARE_VERSION)
            return

        # 2. Hardware Status
        if cmd == CMD_STATUS:
            status_payload = b"\x01" if self.sensor_ready else b"\x00"
            status_payload += b"\x01" if self.sensor.led_on else b"\x00"
            self.send_response(cmd, req_id, STATUS_OK, payload=status_payload)
            return

        # 3. Explicit LED Backlight Control
        if cmd == CMD_LED:
            turn_on = bool(payload and payload[0] != 0)
            ok = self.sensor.set_led(turn_on)
            self.send_response(cmd, req_id, STATUS_OK if ok else STATUS_ERROR)
            return

        # 4. Three-Stage Enrollment: Pass 1
        if cmd == CMD_ENROLL_START:
            # Energize sensor backlight for acquisition
            self.sensor.set_led(True)
            if not self._begin_enrollment():
                self.sensor.set_led(False)
                self.send_response(cmd, req_id, STATUS_ERROR,
                                   payload=self._error_payload("Enroll start failed", self.sensor.last_error))
                return

            # Wait for finger press (up to 4 seconds)
            pressed = self._wait_for_finger(4000)

            if not pressed:
                self.sensor.set_led(False)
                self.send_response(cmd, req_id, STATUS_BAD_FINGER, payload=b"No finger detected")
                return

            if not self.sensor.capture_finger(high_quality=True):
                self.sensor.set_led(False)
                self.send_response(cmd, req_id, STATUS_BAD_FINGER, payload=b"Capture failed")
                return

            ok = self.sensor.enroll1()
            err = self.sensor.last_error
            self.sensor.set_led(False)
            if ok:
                self.send_response(cmd, req_id, STATUS_OK, payload=b"Pass 1 OK")
            else:
                self.send_response(cmd, req_id, STATUS_ERROR, payload=self._error_payload("Enroll1 failed", err))
            return

        # 5. Three-Stage Enrollment: Advance Pass 2 or Pass 3
        if cmd == CMD_ENROLL_PASS:
            pass_num = payload[0] if payload else 2
            if pass_num not in (2, 3):
                self.send_response(cmd, req_id, STATUS_ERROR, payload=b"Invalid enrollment pass")
                return
            self.sensor.set_led(True)

            # Wait for finger press
            pressed = self._wait_for_finger(4000)

            if not pressed:
                self.sensor.set_led(False)
                self.send_response(cmd, req_id, STATUS_BAD_FINGER, payload=b"No finger detected")
                return

            if not self.sensor.capture_finger(high_quality=True):
                self.sensor.set_led(False)
                self.send_response(cmd, req_id, STATUS_BAD_FINGER, payload=b"Capture failed")
                return

            if pass_num == 2:
                ok = self.sensor.enroll2()
            else:
                ok = self.sensor.enroll3()
            err = self.sensor.last_error

            self.sensor.set_led(False)
            if ok:
                self.send_response(cmd, req_id, STATUS_OK)
            else:
                self.send_response(cmd, req_id, STATUS_ERROR,
                                   payload=self._error_payload("Enroll%d failed" % pass_num, err))
            return

        # 5b. Single-Impression Capture POC
        if cmd == CMD_CAPTURE_SINGLE:
            self.sensor.set_led(True)
            if not self._begin_enrollment():
                self.sensor.set_led(False)
                self.send_response(cmd, req_id, STATUS_ERROR,
                                   payload=self._error_payload("Enroll start failed", self.sensor.last_error))
                return

            pressed = self._wait_for_finger(8000)

            if not pressed:
                self.sensor.set_led(False)
                self.send_response(cmd, req_id, STATUS_BAD_FINGER, payload=b"No finger detected")
                return

            if not self.sensor.capture_finger(high_quality=True):
                self.sensor.set_led(False)
                self.send_response(cmd, req_id, STATUS_BAD_FINGER, payload=b"Capture failed")
                return

            # Every step must be acknowledged; a template is only returned after Enroll3 succeeded.
            # NOTE: all three scans come from the same placement. Bench notes from the reference
            # driver report that this sensor NACKs Enroll3 unless each scan is a separate
            # placement; in that case this command fails explicitly (not with a fake template).
            ok = self.sensor.enroll1()
            failed_step = None if ok else "Enroll1"
            for step, enroll in (("Enroll2", self.sensor.enroll2), ("Enroll3", self.sensor.enroll3)):
                if not ok:
                    break
                utime.sleep_ms(80)
                ok = self.sensor.capture_finger(high_quality=True) and enroll()
                if not ok:
                    failed_step = step
            err = self.sensor.last_error
            self.sensor.set_led(False)

            template = self.sensor.get_template(SCRATCH_SLOT) if ok else None
            if template is not None and len(template) == TEMPLATE_SIZE:
                self.send_response(cmd, req_id, STATUS_OK, payload=template)
            else:
                detail = "%s %s" % (failed_step, err) if failed_step else (self.sensor.last_error or err)
                self.send_response(cmd, req_id, STATUS_ERROR,
                                   payload=self._error_payload("Single impression template failed", detail))
            return

        # 6. Retrieve Enrolled Template from Scratch Slot 199
        if cmd == CMD_GET_TEMPLATE:
            template = self.sensor.get_template(SCRATCH_SLOT)
            if template is not None and len(template) == TEMPLATE_SIZE:
                self.send_response(cmd, req_id, STATUS_OK, payload=template)
            else:
                self.send_response(cmd, req_id, STATUS_ERROR,
                                   payload=self._error_payload("Template retrieval failed", self.sensor.last_error))
            return

        # 7. Load Template to Scratch Slot 199 (for 1:1 verify)
        if cmd == CMD_LOAD_TEMPLATE:
            if len(payload) == TEMPLATE_SIZE:
                # Clear the slot first: if this load fails, Verify must not run against an earlier template
                self.sensor.delete_id(SCRATCH_SLOT)
                ok = self.sensor.set_template(SCRATCH_SLOT, bytes(payload))
                if ok:
                    self.send_response(cmd, req_id, STATUS_OK)
                else:
                    self.send_response(cmd, req_id, STATUS_ERROR,
                                       payload=self._error_payload("Template load failed", self.sensor.last_error))
            else:
                self.send_response(cmd, req_id, STATUS_ERROR, payload=b"Invalid template size")
            return

        # 8. Execute 1:1 On-Sensor Verification
        if cmd == CMD_VERIFY_1_1:
            self.sensor.set_led(True)
            # Capture live finger
            pressed = self._wait_for_finger(4000)

            if not pressed or not self.sensor.capture_finger(high_quality=False):
                self.sensor.set_led(False)
                self.send_response(cmd, req_id, STATUS_BAD_FINGER, payload=b"No finger detected")
                return

            matched = self.sensor.verify(SCRATCH_SLOT)
            err = self.sensor.last_error
            # Always shut off LED after verification completes
            self.sensor.set_led(False)
            if matched:
                self.send_response(cmd, req_id, STATUS_OK, payload=b"Match")
            elif err == "verify_failed":
                self.send_response(cmd, req_id, STATUS_ERROR, payload=b"No match")
            else:
                # e.g. is_not_used (no template loaded) - a failure, not a non-matching finger
                self.send_response(cmd, req_id, STATUS_ERROR, payload=self._error_payload("Verify failed", err))
            return

        # 9. Delete Template / Zeroize Scratch Slot
        if cmd == CMD_DELETE_SLOT:
            slot_id = 199
            if len(payload) >= 2:
                slot_id = payload[0] | (payload[1] << 8)
            ok = self.sensor.delete_id(slot_id)
            if ok or self.sensor.last_error == "is_not_used":
                self.send_response(cmd, req_id, STATUS_OK)  # slot is empty either way
            else:
                self.send_response(cmd, req_id, STATUS_ERROR,
                                   payload=self._error_payload("Delete failed", self.sensor.last_error))
            return

        # 10. Operator Cancellation
        if cmd == CMD_CANCEL:
            led_ok = self.sensor.set_led(False)
            self.sensor.delete_id(SCRATCH_SLOT)
            self.send_response(cmd, req_id, STATUS_OK if led_ok else STATUS_ERROR)
            return

        # Unknown Command
        self.send_response(cmd or 0, req_id, STATUS_ERROR, payload=b"Unknown command")

    def run(self):
        """Non-blocking main loop reading LLFP packets from USB serial buffer."""
        poll = None
        if select is not None and hasattr(select, "poll") and hasattr(select, "POLLIN"):
            poll = select.poll()
            poll.register(sys.stdin, getattr(select, "POLLIN", 1))

        rx_buf = bytearray()
        while True:
            # Read from USB CDC serial
            has_data = True
            if poll:
                events = poll.poll(10)
                has_data = bool(events)

            chunk = sys.stdin.buffer.read(1) if has_data else None
            if not chunk:
                utime.sleep_ms(5)  # idle; never sleep between bytes of an incoming frame
                continue
            rx_buf.extend(chunk)
            # Attempt unpacking when minimum frame size reached
            if len(rx_buf) >= SerialFrame.HEADER_SIZE + 4:
                frame = SerialFrame.unpack(bytes(rx_buf))
                if frame:
                    rx_buf = self._drop_frame(rx_buf, frame)
                    if "error" not in frame:
                        self.handle_command(frame)
                elif len(rx_buf) > 1024:
                    # Discard malformed noise
                    rx_buf = bytearray()

    @staticmethod
    def _drop_frame(rx_buf, frame):
        """Removes the frame just decoded, keeping any bytes of a following frame."""
        start = bytes(rx_buf).find(b"LLFP")
        if "error" in frame:
            return rx_buf[start + 1:]  # corrupt frame: resynchronise on the next magic
        return rx_buf[start + SerialFrame.HEADER_SIZE + len(frame["payload"]) + 4:]


if __name__ == "__main__":
    daemon = ESP32FirmwareDaemon()
    daemon.run()
