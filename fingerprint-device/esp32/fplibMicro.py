"""
LifeLink 2.0 - MicroPython driver for the GT-521Fx2 (GT-521F32 / GT-521F52) sensor.

Sensor UART protocol (GT-521Fx2 datasheet, "UART protocol"; this is the sensor link,
not the LLFP link between the ESP32 and the Pi 5):

  command packet  (12 bytes):  55 AA | dev_id 01 00 | param LE32 | command LE16 | checksum LE16
  response packet (12 bytes):  55 AA | dev_id 01 00 | param LE32 | 0x30 ACK / 0x31 NACK LE16 | checksum LE16
  data packet  (4 + N + 2):    5A A5 | dev_id 01 00 | data (N)  | checksum LE16
  checksum = 16-bit sum of every preceding byte of the packet.

On a NACK, `param` carries the error code (NACK_ERRORS); for Enroll1-3 a value below
0x1000 is the slot ID of an already-enrolled duplicate finger.

Error policy (callers rely on it):
  * Transport failures - no reply before the deadline, truncated or partial packet,
    bad checksum, wrong start code / device ID, an ACK field that is neither ACK nor
    NACK, UART unavailable - raise SensorError. They are never reported as a NACK
    or as success.
  * A well-formed NACK returns False / None and sets `last_error` to a short name.

Incorporates verified firmware quirks of this sensor:
  - 2048-byte UART RX buffer so the 504-byte template data packet is not truncated
    (MicroPython's default 256-byte buffer silently truncated templates).
  - Backlight must be on before IsPressFinger, otherwise the sensor stops answering.
  - Three-scan enrollment into scratch slot 199, read back with GetTemplate, then DeleteID.
  - 1:1 on-sensor verification (Verify1_1) against a template loaded with SetTemplate.

Method contracts used by main.py are listed in docs/fingerprint-driver.md.
"""

try:
    import utime  # type: ignore
except ImportError:  # CPython (tests / simulators)
    import time as _time

    class _UtimeCompat:
        @staticmethod
        def sleep_ms(ms):
            _time.sleep(ms / 1000.0)

        @staticmethod
        def ticks_ms():
            return int(_time.monotonic() * 1000)

        @staticmethod
        def ticks_add(ticks, delta):
            return ticks + delta

        @staticmethod
        def ticks_diff(t1, t2):
            return t1 - t2

    utime = _UtimeCompat()

try:
    from machine import UART, Pin  # type: ignore
except ImportError:
    # Allows simulator imports on PC; tests substitute a UART double.
    UART = None
    Pin = None

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
CMD_VERIFY_TEMPLATE = 0x52
CMD_CAPTURE_FINGER = 0x60
CMD_MAKE_TEMPLATE = 0x61
CMD_GET_TEMPLATE = 0x70
CMD_SET_TEMPLATE = 0x71

ACK = 0x30
NACK = 0x31

CMD_START = b"\x55\xaa"
DATA_START = b"\x5a\xa5"
DEVICE_ID = b"\x01\x00"

TEMPLATE_SIZE = 498
DEVICE_INFO_SIZE = 24
MAX_SLOT = 199  # GT-521F32: 200 templates (0-199); the firmware only uses scratch slot 199

NACK_ERRORS = {
    0x1001: "timeout",
    0x1002: "invalid_baudrate",
    0x1003: "invalid_pos",
    0x1004: "is_not_used",
    0x1005: "is_already_used",
    0x1006: "comm_err",
    0x1007: "verify_failed",
    0x1008: "identify_failed",
    0x1009: "db_is_full",
    0x100A: "db_is_empty",
    0x100B: "turn_err",
    0x100C: "bad_finger",
    0x100D: "enroll_failed",
    0x100E: "is_not_supported",
    0x100F: "dev_err",
    0x1010: "capture_canceled",
    0x1011: "invalid_param",
    0x1012: "finger_is_not_pressed",
}

# Per-command reply deadlines (ms). Capture / enroll / verify do image processing on the sensor.
RESPONSE_TIMEOUT_MS = 1000
CAPTURE_TIMEOUT_MS = 5000
ENROLL_TIMEOUT_MS = 8000
VERIFY_TIMEOUT_MS = 5000
DATA_TIMEOUT_MS = 3000
OPEN_TIMEOUT_MS = 600


class SensorError(Exception):
    """Sensor transport failure (no/partial/corrupt reply). `timeout` is True when nothing arrived in time."""

    def __init__(self, message, timeout=False):
        Exception.__init__(self, message)
        self.timeout = timeout


def _checksum(buf):
    return sum(buf) & 0xFFFF


def _le32(buf, offset):
    return buf[offset] | (buf[offset + 1] << 8) | (buf[offset + 2] << 16) | (buf[offset + 3] << 24)


def build_command_packet(cmd, param=0):
    """12-byte GT-521Fx2 command packet."""
    param &= 0xFFFFFFFF
    pkt = bytearray(CMD_START + DEVICE_ID)
    pkt.extend(bytes((param & 0xFF, (param >> 8) & 0xFF, (param >> 16) & 0xFF, (param >> 24) & 0xFF,
                      cmd & 0xFF, (cmd >> 8) & 0xFF)))
    chk = _checksum(pkt)
    pkt.append(chk & 0xFF)
    pkt.append(chk >> 8)
    return pkt


def build_data_packet(data):
    """4 + len(data) + 2 byte GT-521Fx2 data packet."""
    pkt = bytearray(DATA_START + DEVICE_ID)
    pkt.extend(data)
    chk = _checksum(pkt)
    pkt.append(chk & 0xFF)
    pkt.append(chk >> 8)
    return pkt


class Fingerprint:
    """GT-521F32 driver. Default wiring: UART2, TX=GPIO17, RX=GPIO16, 9600 baud."""

    def __init__(self, port=2, baud=9600, tx=17, rx=16, ledpin=None, timeout=3):
        self.port = port
        self.baud = baud
        self.tx = tx
        self.rx = rx
        self.timeout_ms = int(timeout * 1000)
        self.led = Pin(ledpin, Pin.OUT) if (ledpin is not None and Pin is not None) else None
        self.ser = None
        self.last_error = None
        self.device_info = None
        self.led_on = False

    # ------------------------------------------------------------------ transport

    def _open_uart(self, baud):
        if self.ser:
            try:
                self.ser.deinit()
            except Exception:
                pass
            self.ser = None
        if UART is None:
            raise SensorError("UART unavailable on this platform")
        # rxbuf must hold a full response + template data packet (12 + 504).
        self.ser = UART(self.port, baud, tx=self.tx, rx=self.rx, rxbuf=2048, timeout=50)
        self._flush()

    def _require_uart(self):
        if self.ser is None:
            raise SensorError("sensor UART not initialised")

    def _flush(self):
        """Discards stale bytes. Bounded: a floating/noisy RX line must not wedge us here."""
        if self.ser is None:
            return
        for _ in range(8):
            waiting = self.ser.any()
            if not waiting:
                return
            self.ser.read(waiting)

    def _write_all(self, data, timeout_ms=None):
        """Writes every byte; UART.write may accept fewer bytes than offered (or None)."""
        self._require_uart()
        deadline = utime.ticks_add(utime.ticks_ms(), timeout_ms or self.timeout_ms)
        view = memoryview(data)
        sent = 0
        while sent < len(data):
            n = self.ser.write(view[sent:])
            if n:
                sent += n
                continue
            if utime.ticks_diff(deadline, utime.ticks_ms()) <= 0:
                raise SensorError("UART write stalled (%d of %d bytes sent)" % (sent, len(data)), timeout=True)
            utime.sleep_ms(1)

    def _read_exact(self, n, deadline):
        """Reads exactly n bytes, accumulating partial reads; None if the deadline passes."""
        buf = bytearray()
        while len(buf) < n:
            if utime.ticks_diff(deadline, utime.ticks_ms()) <= 0:
                return None
            chunk = self.ser.read(n - len(buf))
            if chunk:
                buf.extend(chunk)
            else:
                utime.sleep_ms(1)
        return buf

    def _sync(self, start, deadline):
        """Skips bytes until the two-byte start code; False if the deadline passes."""
        prev = None
        while True:
            b = self._read_exact(1, deadline)
            if b is None:
                return False
            if prev == start[0] and b[0] == start[1]:
                return True
            prev = b[0]

    def _send_cmd(self, cmd, param=0):
        self._require_uart()
        self._flush()
        self._write_all(build_command_packet(cmd, param))

    def _read_response(self, timeout_ms=None):
        """Returns (ack, param). Raises SensorError on timeout / partial / corrupt / unexpected reply."""
        self._require_uart()
        deadline = utime.ticks_add(utime.ticks_ms(), timeout_ms or self.timeout_ms)
        if not self._sync(CMD_START, deadline):
            raise SensorError("no response from sensor", timeout=True)
        rest = self._read_exact(10, deadline)
        if rest is None:
            raise SensorError("truncated response packet", timeout=True)
        pkt = bytearray(CMD_START) + rest
        if bytes(pkt[2:4]) != DEVICE_ID:
            raise SensorError("response from unexpected device id 0x%02x%02x" % (pkt[3], pkt[2]))
        if _checksum(pkt[:10]) != (pkt[10] | (pkt[11] << 8)):
            raise SensorError("bad response checksum")
        param = _le32(pkt, 4)
        code = pkt[8] | (pkt[9] << 8)
        if code == ACK:
            self.last_error = None
            return True, param
        if code == NACK:
            if param in NACK_ERRORS:
                self.last_error = NACK_ERRORS[param]
            elif param < 0x1000:
                self.last_error = "duplicate_finger_id_%d" % param
            else:
                self.last_error = "nack_0x%04x" % param
            return False, param
        raise SensorError("unexpected response code 0x%04x" % code)

    def _read_data(self, size, timeout_ms=None):
        """Returns exactly `size` data bytes of a checksum-verified data packet, or raises SensorError."""
        self._require_uart()
        deadline = utime.ticks_add(utime.ticks_ms(), timeout_ms or DATA_TIMEOUT_MS)
        if not self._sync(DATA_START, deadline):
            raise SensorError("no data packet from sensor", timeout=True)
        rest = self._read_exact(2 + size + 2, deadline)
        if rest is None:
            raise SensorError("truncated data packet", timeout=True)
        pkt = bytearray(DATA_START) + rest
        if bytes(pkt[2:4]) != DEVICE_ID:
            raise SensorError("data packet from unexpected device id")
        if _checksum(pkt[:-2]) != (pkt[-2] | (pkt[-1] << 8)):
            raise SensorError("bad data packet checksum")
        return bytes(pkt[4:-2])

    def _send_data(self, data):
        """Sends a data packet (e.g. a template for SetTemplate)."""
        self._write_all(build_data_packet(data))

    def command(self, cmd, param=0, timeout_ms=None):
        """Sends one command packet and returns (ack, param) from its response packet."""
        if self.led:
            self.led.value(1)
        try:
            self._send_cmd(cmd, param)
            return self._read_response(timeout_ms)
        finally:
            if self.led:
                self.led.value(0)

    # ------------------------------------------------------------------ lifecycle

    def _try_open(self):
        try:
            ack, _ = self.command(CMD_OPEN, 1, timeout_ms=OPEN_TIMEOUT_MS)
            if not ack:
                return False
            # Open(1) is followed by a 24-byte device info data packet (firmware, serial number).
            self.device_info = self._read_data(DEVICE_INFO_SIZE, OPEN_TIMEOUT_MS)
            return True
        except SensorError as exc:
            self.last_error = str(exc)
            return False

    def init(self):
        """
        Opens the UART at self.baud and sends Open. The sensor powers up at 9600 and keeps a
        rate set by ChangeBaudrate until it loses power, so other common rates are tried next
        and the sensor is switched back to self.baud. Returns True only if the sensor ACKs Open.
        """
        try:
            self._open_uart(self.baud)
        except SensorError as exc:
            self.last_error = str(exc)
            return False
        if self._try_open():
            return True
        for baud in (9600, 115200, 57600, 38400, 19200):
            if baud == self.baud:
                continue
            self._open_uart(baud)
            if not self._try_open():
                continue
            try:
                self.command(CMD_CHANGE_BAUD, self.baud, timeout_ms=OPEN_TIMEOUT_MS)
            except SensorError:
                pass  # the sensor may switch before its ACK is readable at the old rate
            utime.sleep_ms(100)
            self._open_uart(self.baud)
            return self._try_open()
        self.last_error = self.last_error or "sensor did not answer Open"
        return False

    def open(self):
        return self._try_open()

    def close(self):
        return self.command(CMD_CLOSE)[0]

    # ------------------------------------------------------------------ finger

    def set_led(self, on):
        """Backlight on/off. Returns the sensor's ACK; raises SensorError if it does not answer."""
        ack = self.command(CMD_CMOS_LED, 1 if on else 0)[0]
        if ack:
            self.led_on = bool(on)
        return ack

    def is_press_finger(self):
        """True when a finger is on the sensor (IsPressFinger ACK with param 0)."""
        # With the backlight off this sensor never answers IsPressFinger and wedges
        # until power-cycled, so always light it first.
        if not self.led_on:
            if not self.set_led(True):
                return False
            utime.sleep_ms(300)
        ack, param = self.command(CMD_IS_PRESS_FINGER)
        if ack and param != 0:
            self.last_error = "finger_is_not_pressed"
        return ack and param == 0

    def capture_finger(self, high_quality=True):
        """CaptureFinger: high_quality=True (slow, for enrollment) / False (fast, for verify)."""
        return self.command(CMD_CAPTURE_FINGER, 1 if high_quality else 0, timeout_ms=CAPTURE_TIMEOUT_MS)[0]

    # ------------------------------------------------------------------ enrollment

    def enroll_start(self, slot):
        """EnrollStart(slot). NACKs with is_already_used if the slot holds a template."""
        self._check_slot(slot)
        return self.command(CMD_ENROLL_START, slot)[0]

    def enroll1(self):
        """Enroll1 on the image from the preceding CaptureFinger."""
        return self.command(CMD_ENROLL1, timeout_ms=ENROLL_TIMEOUT_MS)[0]

    def enroll2(self):
        """Enroll2 on the image from the preceding CaptureFinger."""
        return self.command(CMD_ENROLL2, timeout_ms=ENROLL_TIMEOUT_MS)[0]

    def enroll3(self):
        """Enroll3: merges the three scans and stores the template in the EnrollStart slot."""
        return self.command(CMD_ENROLL3, timeout_ms=ENROLL_TIMEOUT_MS)[0]

    # ------------------------------------------------------------------ templates

    def get_template(self, slot):
        """The 498-byte template stored in `slot`, or None if the sensor NACKs (e.g. empty slot)."""
        self._check_slot(slot)
        ack, _ = self.command(CMD_GET_TEMPLATE, slot)
        if not ack:
            return None
        return self._read_data(TEMPLATE_SIZE, DATA_TIMEOUT_MS)

    def set_template(self, slot, template):
        """Stores a 498-byte template in `slot`. True only after the sensor ACKs the data packet."""
        self._check_slot(slot)
        if not isinstance(template, (bytes, bytearray)) or len(template) != TEMPLATE_SIZE:
            self.last_error = "bad_template_size"
            return False
        ack, _ = self.command(CMD_SET_TEMPLATE, slot)
        if not ack:
            return False
        self._send_data(template)
        return self._read_response(VERIFY_TIMEOUT_MS)[0]

    def verify(self, slot):
        """
        Verify1_1 of the last CaptureFinger image against `slot`.
        True = match; False = no match (last_error 'verify_failed') or another NACK
        such as 'is_not_used' / 'invalid_pos' (inspect last_error).
        """
        self._check_slot(slot)
        return self.command(CMD_VERIFY, slot, timeout_ms=VERIFY_TIMEOUT_MS)[0]

    def delete_id(self, slot):
        """DeleteID(slot). False with last_error 'is_not_used' when the slot was already empty."""
        self._check_slot(slot)
        return self.command(CMD_DELETE_ID, slot)[0]

    def check_enrolled(self, slot):
        self._check_slot(slot)
        return self.command(CMD_CHECK_ENROLLED, slot)[0]

    def get_enrolled_count(self):
        ack, param = self.command(CMD_GET_ENROLL_COUNT)
        return param if ack else -1

    def _check_slot(self, slot):
        if not isinstance(slot, int) or slot < 0 or slot > MAX_SLOT:
            raise ValueError("slot %r out of range 0-%d" % (slot, MAX_SLOT))
