"""
LifeLink 2.0 - GT-521F32 sensor simulator and ESP32 test doubles (test support, not a test module).

The simulator speaks the sensor's UART protocol and encodes every packet independently of
fplibMicro (with `struct`), so driver tests do not just round-trip the driver's own helpers:

  command / response:  55 AA 01 00 | param <I | command or 0x30/0x31 <H | sum16 <H
  data packet:         5A A5 01 00 | data             | sum16 <H

It models the sensor behaviour main.py relies on: Open (+24-byte device info), CMOS LED,
IsPressFinger (does not answer while the backlight is off, as observed on this sensor),
CaptureFinger, EnrollStart/1/2/3 into a slot, GetTemplate/SetTemplate (498-byte data
packets), Verify1_1, DeleteID, CheckEnrolled and GetEnrollCount, with the documented NACK
codes. Fault injection covers partial/garbled/silent replies and partial writes.

It is a model of the protocol, not of the optics: templates are a deterministic function
of a simulated finger identity, which real sensors do not guarantee.
"""

import hashlib
import struct

CMD = dict(OPEN=0x01, CLOSE=0x02, CHANGE_BAUD=0x04, CMOS_LED=0x12, GET_ENROLL_COUNT=0x20, CHECK_ENROLLED=0x21,
           ENROLL_START=0x22, ENROLL1=0x23, ENROLL2=0x24, ENROLL3=0x25, IS_PRESS_FINGER=0x26, DELETE_ID=0x40,
           DELETE_ALL=0x41, VERIFY=0x50, CAPTURE_FINGER=0x60, GET_TEMPLATE=0x70, SET_TEMPLATE=0x71)
ACK, NACK = 0x30, 0x31
NACK_IS_NOT_USED, NACK_IS_ALREADY_USED, NACK_INVALID_POS = 0x1004, 0x1005, 0x1003
NACK_COMM_ERR, NACK_VERIFY_FAILED, NACK_TURN_ERR, NACK_BAD_FINGER = 0x1006, 0x1007, 0x100B, 0x100C
NACK_ENROLL_FAILED, NACK_INVALID_PARAM, NACK_FINGER_NOT_PRESSED = 0x100D, 0x1011, 0x1012
TEMPLATE_SIZE = 498


def sum16(data):
    return sum(data) & 0xFFFF


def response_packet(code, param=0):
    body = struct.pack("<2s2sIH", b"\x55\xaa", b"\x01\x00", param & 0xFFFFFFFF, code)
    return body + struct.pack("<H", sum16(body))


def data_packet(data):
    body = b"\x5a\xa5\x01\x00" + bytes(data)
    return body + struct.pack("<H", sum16(body))


def finger_template(finger_id):
    """Deterministic 498-byte stand-in for the template of one simulated finger."""
    out = b""
    counter = 0
    while len(out) < TEMPLATE_SIZE:
        out += hashlib.sha256(f"{finger_id}:{counter}".encode()).digest()
        counter += 1
    return out[:TEMPLATE_SIZE]


class VirtualClock:
    """Stands in for MicroPython `utime`; sleeping advances virtual time instantly."""

    def __init__(self):
        self.now_ms = 10_000.0

    def ticks_ms(self):
        return int(self.now_ms)

    def ticks_add(self, ticks, delta):
        return ticks + delta

    def ticks_diff(self, a, b):
        return a - b

    def sleep_ms(self, ms):
        self.now_ms += max(ms, 1)


class GT521Sim:
    """GT-521F32 behind a MicroPython-style UART (any / read / write / deinit)."""

    def __init__(self, clock, read_chunk=None, write_chunk=None, read_timeout_ms=50):
        self.clock = clock
        self.read_chunk = read_chunk          # max bytes returned per read() (partial reads)
        self.write_chunk = write_chunk        # max bytes accepted per write() (partial writes)
        self.read_timeout_ms = read_timeout_ms
        self.out = bytearray()                # sensor -> ESP32
        self.inp = bytearray()                # ESP32 -> sensor
        self.led = False
        self.finger = None                    # finger identity currently on the glass
        self.placement = 0                    # increments on every new placement
        self.captured = None                  # (finger_id, placement) of the last CaptureFinger
        self.slots = {}                       # slot -> template bytes
        self.enroll = None                    # {"slot", "next", "scans": [(finger, placement)]}
        self.awaiting_data_for = None         # slot of a pending SetTemplate
        self.require_separate_placements = False
        self.commands = []                    # log of (command, param)
        self.alive = True                     # False = unplugged / unpowered
        self.wedged = False                   # IsPressFinger with LED off wedges the sensor
        self.next_reply_faults = []           # queue of callables(bytes) -> bytes applied to replies
        self.deinit_calls = 0
        self.writes_with_none = 0             # first N writes return None (busy TX FIFO)
        self.sensor_baud = 9600               # GT-521F32 power-on default
        self.link_baud = 9600                 # rate the ESP32 UART was opened at

    # ----- finger handling --------------------------------------------------
    def place(self, finger_id):
        self.finger = finger_id
        self.placement += 1

    def lift(self):
        self.finger = None

    # ----- UART interface ---------------------------------------------------
    def any(self):
        return len(self.out)

    def read(self, n=-1):
        if not self.out:
            self.clock.sleep_ms(self.read_timeout_ms)   # UART(timeout=50) blocks, then returns None
            return None
        if n is None or n < 0:
            n = len(self.out)
        if self.read_chunk:
            n = min(n, self.read_chunk)
        data = bytes(self.out[:n])
        del self.out[:n]
        return data

    def write(self, data):
        if self.writes_with_none:
            self.writes_with_none -= 1
            return None
        data = bytes(data)
        if self.write_chunk:
            data = data[:self.write_chunk]
        self.inp.extend(data)
        self._process()
        return len(data)

    def deinit(self):
        self.deinit_calls += 1

    # ----- protocol engine --------------------------------------------------
    def _reply(self, code, param=0, data=None):
        packet = response_packet(code, param) + (data_packet(data) if data is not None else b"")
        while self.next_reply_faults:
            packet = self.next_reply_faults.pop(0)(packet)
        self.out.extend(packet)

    def _process(self):
        while True:
            if self.awaiting_data_for is not None:
                need = 4 + TEMPLATE_SIZE + 2
                if len(self.inp) < need:
                    return
                pkt, self.inp = bytes(self.inp[:need]), self.inp[need:]
                self._receive_template(pkt)
                continue
            idx = self.inp.find(b"\x55\xaa")
            if idx < 0 or len(self.inp) - idx < 12:
                return
            pkt = bytes(self.inp[idx:idx + 12])
            del self.inp[:idx + 12]
            param, cmd, chk = struct.unpack_from("<IHH", pkt, 4)
            if chk != sum16(pkt[:10]) or pkt[2:4] != b"\x01\x00":
                continue  # the real sensor ignores corrupt commands
            self.commands.append((cmd, param))
            if self.alive and self.link_baud == self.sensor_baud:
                self._execute(cmd, param)

    def _receive_template(self, pkt):
        slot, self.awaiting_data_for = self.awaiting_data_for, None
        ok = pkt[:4] == b"\x5a\xa5\x01\x00" and struct.unpack_from("<H", pkt, len(pkt) - 2)[0] == sum16(pkt[:-2])
        if not ok:
            return self._reply(NACK, NACK_COMM_ERR)
        self.slots[slot] = pkt[4:-2]
        self._reply(ACK)

    def _execute(self, cmd, param):
        if self.wedged:
            return
        if cmd == CMD["OPEN"]:
            info = struct.pack("<II", 0x20170101, 1600) + b"SIMSERIAL0000001"
            return self._reply(ACK, 0, info if param else None)
        if cmd == CMD["CLOSE"]:
            return self._reply(ACK)
        if cmd == CMD["CHANGE_BAUD"]:
            self._reply(ACK)
            self.sensor_baud = param
            return None
        if cmd == CMD["CMOS_LED"]:
            self.led = bool(param)
            return self._reply(ACK)
        if cmd == CMD["IS_PRESS_FINGER"]:
            if not self.led:
                self.wedged = True
                return
            return self._reply(ACK, 0 if self.finger else NACK_FINGER_NOT_PRESSED)
        if cmd == CMD["CAPTURE_FINGER"]:
            if not self.finger:
                return self._reply(NACK, NACK_FINGER_NOT_PRESSED)
            self.captured = (self.finger, self.placement)
            return self._reply(ACK)
        if cmd in (CMD["ENROLL_START"], CMD["DELETE_ID"], CMD["CHECK_ENROLLED"], CMD["GET_TEMPLATE"],
                   CMD["SET_TEMPLATE"], CMD["VERIFY"]) and param > 199:
            return self._reply(NACK, NACK_INVALID_POS)
        if cmd == CMD["ENROLL_START"]:
            if param in self.slots:
                return self._reply(NACK, NACK_IS_ALREADY_USED)
            self.enroll = {"slot": param, "next": CMD["ENROLL1"], "scans": []}
            return self._reply(ACK)
        if cmd in (CMD["ENROLL1"], CMD["ENROLL2"], CMD["ENROLL3"]):
            return self._enroll_step(cmd)
        if cmd == CMD["GET_TEMPLATE"]:
            if param not in self.slots:
                return self._reply(NACK, NACK_IS_NOT_USED)
            return self._reply(ACK, 0, self.slots[param])
        if cmd == CMD["SET_TEMPLATE"]:
            self.awaiting_data_for = param
            return self._reply(ACK)
        if cmd == CMD["VERIFY"]:
            if param not in self.slots:
                return self._reply(NACK, NACK_IS_NOT_USED)
            if not self.captured:
                return self._reply(NACK, NACK_BAD_FINGER)
            matched = self.slots[param] == finger_template(self.captured[0])
            self.captured = None
            return self._reply(ACK) if matched else self._reply(NACK, NACK_VERIFY_FAILED)
        if cmd == CMD["DELETE_ID"]:
            if param not in self.slots:
                return self._reply(NACK, NACK_IS_NOT_USED)
            del self.slots[param]
            return self._reply(ACK)
        if cmd == CMD["DELETE_ALL"]:
            self.slots.clear()
            return self._reply(ACK)
        if cmd == CMD["GET_ENROLL_COUNT"]:
            return self._reply(ACK, len(self.slots))
        return self._reply(NACK, NACK_INVALID_PARAM)

    def _enroll_step(self, cmd):
        if not self.enroll or self.enroll["next"] != cmd:
            return self._reply(NACK, NACK_TURN_ERR)
        if not self.captured:
            return self._reply(NACK, NACK_BAD_FINGER)
        self.enroll["scans"].append(self.captured)
        self.captured = None
        if cmd != CMD["ENROLL3"]:
            self.enroll["next"] = cmd + 1
            return self._reply(ACK)
        scans, slot = self.enroll["scans"], self.enroll["slot"]
        self.enroll = None
        fingers = {f for f, _ in scans}
        placements = {p for _, p in scans}
        if len(fingers) != 1 or (self.require_separate_placements and len(placements) < 3):
            return self._reply(NACK, NACK_ENROLL_FAILED)
        template = finger_template(scans[0][0])
        for other_slot, other in self.slots.items():
            if other == template:
                return self._reply(NACK, other_slot)  # duplicate: NACK param = existing slot ID
        self.slots[slot] = template
        return self._reply(ACK)


# ----- reply fault helpers ---------------------------------------------------
def corrupt_checksum(packet):
    return packet[:10] + bytes([packet[10] ^ 0xFF]) + packet[11:]


def wrong_device_id(packet):
    body = b"\x55\xaa\x02\x00" + packet[4:10]
    return body + struct.pack("<H", sum16(body)) + packet[12:]


def unexpected_code(packet):
    body = packet[:8] + struct.pack("<H", 0x0040)
    return body + struct.pack("<H", sum16(body)) + packet[12:]


def truncate(n):
    return lambda packet: packet[:n]


def garbage_prefix(packet):
    return b"\x00\xff\x55\x13noise" + packet


def drop(packet):
    return b""


def corrupt_data_checksum(packet):
    return packet[:-1] + bytes([packet[-1] ^ 0x01])


def flip_template_byte(index):
    def _f(packet):
        b = bytearray(packet)
        b[12 + 4 + index] ^= 0x01  # corrupt the payload but keep the original (now wrong) checksum
        return bytes(b)
    return _f


class FakeUartFactory:
    """Replaces machine.UART: every UART(...) call returns the same simulator and records the config."""

    def __init__(self, sim):
        self.sim = sim
        self.calls = []

    def __call__(self, port, baud, tx=None, rx=None, rxbuf=None, timeout=None):
        self.calls.append(dict(port=port, baud=baud, tx=tx, rx=rx, rxbuf=rxbuf, timeout=timeout))
        self.sim.link_baud = baud
        self.sim.out.clear()  # re-opening the UART discards received bytes
        return self.sim
