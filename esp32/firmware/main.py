"""
LifeLink 2.0 - ESP32 MicroPython Firmware Daemon
Listens on USB CDC serial for binary-framed LLFP commands from Raspberry Pi 5.
Coordinates GT-521F32 sensor operations over UART2 and returns binary responses.

MANDATORY BEHAVIOR:
Sensor backlight and optical scanning remain strictly IDLE and OFF until
explicit command is received from the Pi 5 terminal following a GUI button click.
"""

import sys
import utime
try:
    import select
except ImportError:
    select = None

from fplibMicro import Fingerprint, TEMPLATE_SIZE
from framing import (
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
    CMD_CANCEL,
    STATUS_OK,
    STATUS_ERROR,
    STATUS_BAD_FINGER,
    STATUS_TIMEOUT
)

FIRMWARE_VERSION = b"LifeLink-ESP32-v2.0-wired"


class ESP32FirmwareDaemon:
    """Firmware event loop for USB serial command execution."""

    def __init__(self):
        # GT-521F32 connected to ESP32 UART2 (TX=GPIO17, RX=GPIO16)
        self.sensor = Fingerprint(port=2, baud=115200, tx=17, rx=16)
        self.sensor_ready = False
        self._init_hardware()

    def _init_hardware(self):
        """Initializes sensor and guarantees LED is OFF at startup."""
        self.sensor_ready = self.sensor.init()
        # Guarantee optical backlight is OFF at startup
        self.sensor.set_led(False)

    def send_response(self, command: int, req_id: bytes, status: int = STATUS_OK, payload: bytes = b""):
        """Packs and writes binary response frame to USB serial stdout."""
        pkt = SerialFrame.pack(KIND_RESPONSE, command, req_id, payload=payload, status=status)
        sys.stdout.buffer.write(pkt)

    def handle_command(self, frame: dict):
        """Executes authorized host command."""
        cmd = frame.get("command")
        req_id = frame.get("request_id", b"\x00" * 16)
        payload = frame.get("payload", b"")

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
            self.sensor.enroll_start(199)

            # Wait for finger press (up to 4 seconds)
            start = utime.ticks_ms()
            pressed = False
            while utime.ticks_diff(utime.ticks_ms(), start) < 4000:
                if self.sensor.is_press_finger():
                    pressed = True
                    break
                utime.sleep_ms(50)

            if not pressed:
                self.send_response(cmd, req_id, STATUS_BAD_FINGER, payload=b"No finger detected")
                return

            if not self.sensor.capture_finger(high_quality=True):
                self.send_response(cmd, req_id, STATUS_BAD_FINGER, payload=b"Capture failed")
                return

            if self.sensor.enroll1():
                self.send_response(cmd, req_id, STATUS_OK, payload=b"Pass 1 OK")
            else:
                self.send_response(cmd, req_id, STATUS_ERROR, payload=b"Enroll1 failed")
            return

        # 5. Three-Stage Enrollment: Advance Pass 2 or Pass 3
        if cmd == CMD_ENROLL_PASS:
            pass_num = payload[0] if payload else 2
            self.sensor.set_led(True)

            # Wait for finger press
            start = utime.ticks_ms()
            pressed = False
            while utime.ticks_diff(utime.ticks_ms(), start) < 4000:
                if self.sensor.is_press_finger():
                    pressed = True
                    break
                utime.sleep_ms(50)

            if not pressed:
                self.send_response(cmd, req_id, STATUS_BAD_FINGER, payload=b"No finger detected")
                return

            if not self.sensor.capture_finger(high_quality=True):
                self.send_response(cmd, req_id, STATUS_BAD_FINGER, payload=b"Capture failed")
                return

            if pass_num == 2:
                ok = self.sensor.enroll2()
            else:
                ok = self.sensor.enroll3()
                # Shut off backlight immediately after Pass 3 completes
                self.sensor.set_led(False)

            self.send_response(cmd, req_id, STATUS_OK if ok else STATUS_ERROR)
            return

        # 6. Retrieve Enrolled Template from Scratch Slot 199
        if cmd == CMD_GET_TEMPLATE:
            template = self.sensor.get_template(199)
            if template and len(template) == TEMPLATE_SIZE:
                self.send_response(cmd, req_id, STATUS_OK, payload=template)
            else:
                self.send_response(cmd, req_id, STATUS_ERROR, payload=b"Template retrieval failed")
            return

        # 7. Load Template to Scratch Slot 199 (for 1:1 verify)
        if cmd == CMD_LOAD_TEMPLATE:
            if len(payload) == TEMPLATE_SIZE:
                ok = self.sensor.set_template(199, payload)
                self.send_response(cmd, req_id, STATUS_OK if ok else STATUS_ERROR)
            else:
                self.send_response(cmd, req_id, STATUS_ERROR, payload=b"Invalid template size")
            return

        # 8. Execute 1:1 On-Sensor Verification
        if cmd == CMD_VERIFY_1_1:
            self.sensor.set_led(True)
            # Capture live finger
            start = utime.ticks_ms()
            pressed = False
            while utime.ticks_diff(utime.ticks_ms(), start) < 4000:
                if self.sensor.is_press_finger():
                    pressed = True
                    break
                utime.sleep_ms(50)

            if not pressed or not self.sensor.capture_finger(high_quality=False):
                self.sensor.set_led(False)
                self.send_response(cmd, req_id, STATUS_BAD_FINGER)
                return

            matched = self.sensor.verify(199)
            # Always shut off LED after verification completes
            self.sensor.set_led(False)
            self.send_response(cmd, req_id, STATUS_OK if matched else STATUS_ERROR)
            return

        # 9. Delete Template / Zeroize Scratch Slot
        if cmd == CMD_DELETE_SLOT:
            slot_id = 199
            if len(payload) >= 2:
                slot_id = payload[0] | (payload[1] << 8)
            ok = self.sensor.delete_id(slot_id)
            self.send_response(cmd, req_id, STATUS_OK if ok else STATUS_ERROR)
            return

        # 10. Operator Cancellation
        if cmd == CMD_CANCEL:
            self.sensor.set_led(False)
            self.sensor.delete_id(199)
            self.send_response(cmd, req_id, STATUS_OK)
            return

        # Unknown Command
        self.send_response(cmd or 0, req_id, STATUS_ERROR, payload=b"Unknown command")

    def run(self):
        """Non-blocking main loop reading LLFP packets from USB serial buffer."""
        poll = None
        if select is not None and hasattr(select, "poll"):
            poll = select.poll()
            poll.register(sys.stdin, select.POLLIN)

        rx_buf = bytearray()
        while True:
            # Read from USB CDC serial
            has_data = True
            if poll:
                events = poll.poll(10)
                has_data = bool(events)

            if has_data:
                chunk = sys.stdin.buffer.read(1)
                if chunk:
                    rx_buf.extend(chunk)
                    # Attempt unpacking when minimum frame size reached
                    if len(rx_buf) >= SerialFrame.HEADER_SIZE + 4:
                        frame = SerialFrame.unpack(bytes(rx_buf))
                        if frame:
                            rx_buf.clear()
                            if "error" not in frame:
                                self.handle_command(frame)
                        elif len(rx_buf) > 1024:
                            # Discard malformed noise
                            rx_buf.clear()

            utime.sleep_ms(5)


if __name__ == "__main__":
    daemon = ESP32FirmwareDaemon()
    daemon.run()
