"""
LifeLink 2.0 - MicroPython Driver for ADH-Tech GT-521F32 / GT-521F52 Fingerprint Sensor
Hardware Interface: ESP32 UART2 (TX=GPIO17, RX=GPIO16, Baud=115200, Buffer=2048 bytes).
Implements complete optical sensing, 3-stage enrollment, 498-byte template download,
scratch slot zeroization, and 1:1 on-sensor verification.
"""

import utime
try:
    from machine import UART, Pin
except ImportError:
    UART = None
    Pin = None

# GT-521Fx2 Command Codes
CMD_OPEN = 0x01
CMD_CLOSE = 0x02
CMD_CHANGE_BAUD = 0x04
CMD_CMOS_LED = 0x12
CMD_GET_ENROLL_COUNT = 0x20
CMD_CHECK_ENROLLED = 0x21
CMD_ENROLL_START = 0x22
CMD_ENROLL1 = 0x23
CMD_ENROLL2 = 0x24
CMD_ENROLL3 = 0x25
CMD_IS_PRESS_FINGER = 0x26
CMD_DELETE_ID = 0x40
CMD_DELETE_ALL = 0x41
CMD_VERIFY = 0x50
CMD_IDENTIFY = 0x51
CMD_CAPTURE_FINGER = 0x60
CMD_MAKE_TEMPLATE = 0x61
CMD_GET_TEMPLATE = 0x70
CMD_SET_TEMPLATE = 0x71

# Sensor Response Codes
ACK = 0x30
NACK = 0x31

# Error Codes
ERR_SUCCESS = 0x0000
ERR_VERIFY_FAILED = 0x1001
ERR_NOT_ENROLLED = 0x1004
ERR_BAD_FINGER = 0x1005
ERR_ENROLL_FAILED = 0x1006
ERR_DUPLICATED_ID = 0x1008
ERR_INVALID_PARAM = 0x100A
ERR_COMM_FAIL = 0x100B
ERR_TIMEOUT = 0x100E

TEMPLATE_SIZE = 498
DATA_HEADER = b"\x5A\xA5\x01\x00"


class SensorError(Exception):
    pass


class Fingerprint:
    """MicroPython driver for GT-521F32 optical fingerprint sensor."""

    def __init__(self, port=2, baud=115200, tx=17, rx=16, timeout=3.0):
        self.port = port
        self.baud = baud
        self.tx = tx
        self.rx = rx
        self.timeout_ms = int(timeout * 1000)
        self.ser = None
        self.led_on = False
        self.firmware_info = ""

    def init(self) -> bool:
        """Initializes UART2 with 2048B rxbuf and verifies sensor communication."""
        self._open_uart(self.baud)
        # Attempt OPEN command
        try:
            return self.open()
        except Exception:
            # Fallback attempt at 9600 baud in case sensor was reset to factory default
            try:
                self._open_uart(9600)
                if self.open():
                    self.change_baud(self.baud)
                    self._open_uart(self.baud)
                    return True
            except Exception:
                pass
            return False

    def _open_uart(self, baud: int):
        """Initializes hardware UART with large buffer to prevent 498B packet truncation."""
        if self.ser:
            try:
                self.ser.deinit()
            except Exception:
                pass
        if UART is not None:
            self.ser = UART(self.port, baud, tx=self.tx, rx=self.rx, rxbuf=2048, timeout=100)
            self._flush()

    def _flush(self):
        """Flushes residual bytes from UART receive buffer."""
        if not self.ser:
            return
        for _ in range(8):
            if not self.ser.any():
                return
            self.ser.read(self.ser.any())
            utime.sleep_ms(5)

    @staticmethod
    def _checksum(buf: bytes) -> int:
        return sum(buf) & 0xFFFF

    def _send_cmd(self, cmd: int, param: int = 0) -> None:
        """Constructs and transmits standard 12-byte command packet."""
        pkt = bytearray(12)
        pkt[0] = 0x55
        pkt[1] = 0xAA
        pkt[2] = 0x01
        pkt[3] = 0x00
        param &= 0xFFFFFFFF
        pkt[4] = param & 0xFF
        pkt[5] = (param >> 8) & 0xFF
        pkt[6] = (param >> 16) & 0xFF
        pkt[7] = (param >> 24) & 0xFF
        pkt[8] = cmd & 0xFF
        pkt[9] = (cmd >> 8) & 0xFF
        chk = self._checksum(pkt[:10])
        pkt[10] = chk & 0xFF
        pkt[11] = (chk >> 8) & 0xFF
        self._flush()
        if self.ser:
            self.ser.write(pkt)

    def _recv_response(self, timeout_ms: int = 1500):
        """Receives and validates 12-byte response packet."""
        if not self.ser:
            return False, 0
        start = utime.ticks_ms()
        buf = bytearray()
        while utime.ticks_diff(utime.ticks_ms(), start) < timeout_ms:
            if self.ser.any():
                chunk = self.ser.read(self.ser.any())
                if chunk:
                    buf.extend(chunk)
                if len(buf) >= 12:
                    break
            utime.sleep_ms(5)

        if len(buf) < 12:
            return False, ERR_TIMEOUT

        # Check sync bytes 0x55, 0xAA
        if buf[0] != 0x55 or buf[1] != 0xAA:
            return False, ERR_COMM_FAIL

        # Checksum validation
        chk = self._checksum(buf[:10])
        expected_chk = buf[10] | (buf[11] << 8)
        if chk != expected_chk:
            return False, ERR_COMM_FAIL

        param = buf[4] | (buf[5] << 8) | (buf[6] << 16) | (buf[7] << 24)
        resp_code = buf[8] | (buf[9] << 8)
        return (resp_code == ACK), param

    def open(self) -> bool:
        """Sends OPEN command; returns True if sensor responds with ACK."""
        self._send_cmd(CMD_OPEN, 1)  # 1 = extra device info
        ok, param = self._recv_response(2000)
        return ok

    def close(self) -> bool:
        """Sends CLOSE command."""
        self._send_cmd(CMD_CLOSE, 0)
        ok, _ = self._recv_response(500)
        return ok

    def change_baud(self, baud: int) -> bool:
        """Changes sensor UART baud rate."""
        self._send_cmd(CMD_CHANGE_BAUD, baud)
        ok, _ = self._recv_response(500)
        return ok

    def set_led(self, on: bool) -> bool:
        """Switches sensor optical backlight LED on or off."""
        self._send_cmd(CMD_CMOS_LED, 1 if on else 0)
        ok, _ = self._recv_response(500)
        self.led_on = on if ok else self.led_on
        return ok

    def is_press_finger(self) -> bool:
        """Returns True if finger is pressed against the optical prism."""
        self._send_cmd(CMD_IS_PRESS_FINGER, 0)
        ok, param = self._recv_response(500)
        # Parameter 0 means finger is pressed
        return ok and (param == 0)

    def capture_finger(self, high_quality: bool = True) -> bool:
        """Captures finger image from optical prism into sensor RAM."""
        self._send_cmd(CMD_CAPTURE_FINGER, 1 if high_quality else 0)
        ok, _ = self._recv_response(2500)
        return ok

    def enroll_start(self, slot_id: int = 199) -> bool:
        """Starts 3-pass guided enrollment for specified slot (default: 199)."""
        self._send_cmd(CMD_ENROLL_START, slot_id)
        ok, _ = self._recv_response(1000)
        return ok

    def enroll1(self) -> bool:
        """Generates template from 1st scan."""
        self._send_cmd(CMD_ENROLL1, 0)
        ok, _ = self._recv_response(2000)
        return ok

    def enroll2(self) -> bool:
        """Generates template from 2nd scan."""
        self._send_cmd(CMD_ENROLL2, 0)
        ok, _ = self._recv_response(2000)
        return ok

    def enroll3(self) -> bool:
        """Generates template from 3rd scan and commits to slot."""
        self._send_cmd(CMD_ENROLL3, 0)
        ok, _ = self._recv_response(2500)
        return ok

    def get_template(self, slot_id: int = 199) -> bytes:
        """
        Retrieves 498-byte binary template from sensor slot.
        Sensor responds with 12B ACK, followed by 504B data packet (header 4B + 498B + chk 2B).
        """
        self._send_cmd(CMD_GET_TEMPLATE, slot_id)
        ok, _ = self._recv_response(1500)
        if not ok or not self.ser:
            return b""

        # Read data packet: 4B header + 498B template + 2B checksum = 504 bytes
        start = utime.ticks_ms()
        buf = bytearray()
        while utime.ticks_diff(utime.ticks_ms(), start) < 3000:
            if self.ser.any():
                chunk = self.ser.read(self.ser.any())
                if chunk:
                    buf.extend(chunk)
                if len(buf) >= 504:
                    break
            utime.sleep_ms(5)

        if len(buf) < 504:
            return b""

        # Verify data header 0x5A, 0xA5
        if buf[0] != 0x5A or buf[1] != 0xA5:
            return b""

        template = bytes(buf[4:502])  # 498 bytes
        return template

    def set_template(self, slot_id: int, template_bytes: bytes) -> bool:
        """
        Uploads 498-byte binary template to temporary slot on sensor.
        Sends 12B command, receives ACK, then streams 504B data packet.
        """
        if len(template_bytes) != TEMPLATE_SIZE or not self.ser:
            return False

        self._send_cmd(CMD_SET_TEMPLATE, slot_id)
        ok, _ = self._recv_response(1000)
        if not ok:
            return False

        # Build 504B data packet
        pkt = bytearray(504)
        pkt[0] = 0x5A
        pkt[1] = 0xA5
        pkt[2] = 0x01
        pkt[3] = 0x00
        pkt[4:502] = template_bytes
        chk = self._checksum(pkt[:502])
        pkt[502] = chk & 0xFF
        pkt[503] = (chk >> 8) & 0xFF
        self.ser.write(pkt)

        ok, _ = self._recv_response(1500)
        return ok

    def verify(self, slot_id: int = 199) -> bool:
        """Executes 1:1 match of captured finger against template in specified slot."""
        self._send_cmd(CMD_VERIFY, slot_id)
        ok, _ = self._recv_response(2000)
        return ok

    def delete_id(self, slot_id: int = 199) -> bool:
        """Deletes template from sensor slot (zeroization of scratch slot)."""
        self._send_cmd(CMD_DELETE_ID, slot_id)
        ok, _ = self._recv_response(1000)
        return ok

    def delete_all(self) -> bool:
        """Wipes all enrolled templates from sensor memory."""
        self._send_cmd(CMD_DELETE_ALL, 0)
        ok, _ = self._recv_response(2000)
        return ok
