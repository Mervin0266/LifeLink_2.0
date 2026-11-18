"""
LifeLink 2.0 - MicroPython driver for the GT-521Fx2 (GT-521F32 / GT-521F52) sensor.
Incorporates verified firmware quirks:
  - 2048-byte UART buffer to prevent 498-byte template truncation
  - Backlight energization before IsPressFinger checks
  - Three-scan enrollment via scratch slot 199 with GetTemplate and DeleteID
  - 1:1 on-sensor verification against loaded scratch templates
"""

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
    from machine import UART, Pin  # type: ignore
except ImportError:
    # Allows simulator imports on PC
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

TEMPLATE_SIZE = 498
DEVICE_INFO_SIZE = 24


class SensorError(Exception):
    pass


class Fingerprint:
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

    def _open_uart(self, baud):
        if self.ser:
            self.ser.deinit()
        if UART is not None:
            self.ser = UART(self.port, baud, tx=self.tx, rx=self.rx, rxbuf=2048, timeout=50)
            self._flush()

    def _flush(self):
        if not self.ser:
            return
        for _ in range(8):
            if not self.ser.any():
                return
            self.ser.read(self.ser.any())

    @staticmethod
    def _checksum(buf):
        return sum(buf) & 0xFFFF

    def _send_cmd(self, cmd, param=0):
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
        pkt[11] = chk >> 8
        self._flush()
        if self.ser:
            self.ser.write(pkt)

    def set_led(self, on):
        if not self.ser:
            self.led_on = on
            return True
        self._send_cmd(CMD_CMOS_LED, 1 if on else 0)
        self.led_on = on
        return True

    def init(self):
        self._open_uart(self.baud)
        return True
