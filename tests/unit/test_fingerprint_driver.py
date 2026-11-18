"""
LifeLink 2.0 - Regression tests for the ESP32 GT-521F32 driver (fingerprint-device/esp32/fplibMicro.py)
and its integration with the MicroPython firmware daemon (fingerprint-device/esp32/main.py).

LL-002A: fplibMicro.py was truncated after `init()`, so every biometric command in main.py
raised AttributeError on the ESP32. These tests drive the restored driver and the real
firmware handlers against a GT-521F32 protocol simulator (tests/unit/gt521_sim.py) on a
virtual clock. They validate the protocol implementation, not real optics or hardware.

  A  driver API completeness (every self.sensor.* call in main.py, no placeholder bodies)
  B  sensor UART protocol: valid / NACK / partial / timeout / corrupt / unexpected / empty / disconnect
  C  enrollment through main.py, including failure at every stage
  D  template operations and byte-for-byte integrity across the LLFP boundary
  E  1:1 verification outcomes
  F  firmware robustness and MicroPython compatibility
"""

import ast
import base64
import importlib.util
import inspect
import io
import struct
import subprocess
import sys
import textwrap
from pathlib import Path
from types import SimpleNamespace

import pytest

REPO = Path(__file__).resolve().parents[2]
ESP32_DIR = REPO / "fingerprint-device" / "esp32"
PROTOCOL_DIR = REPO / "fingerprint-device" / "protocol"
for _p in (str(ESP32_DIR), str(PROTOCOL_DIR), str(Path(__file__).resolve().parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import fplibMicro  # noqa: E402
from fplibMicro import Fingerprint, SensorError  # noqa: E402
from framing import (  # noqa: E402
    SerialFrame, KIND_REQUEST, KIND_RESPONSE, CMD_HELLO, CMD_STATUS, CMD_LED, CMD_ENROLL_START,
    CMD_ENROLL_PASS, CMD_GET_TEMPLATE, CMD_LOAD_TEMPLATE, CMD_VERIFY_1_1, CMD_DELETE_SLOT,
    CMD_CAPTURE_SINGLE, CMD_CANCEL, STATUS_OK, STATUS_ERROR, STATUS_TIMEOUT, STATUS_BAD_FINGER,
)
import gt521_sim as gs  # noqa: E402
from gt521_sim import GT521Sim, VirtualClock, FakeUartFactory, finger_template, CMD  # noqa: E402

ALICE, BOB = "finger-alice-R1", "finger-bob-R1"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def rig(monkeypatch):
    clock = VirtualClock()
    sim = GT521Sim(clock)
    factory = FakeUartFactory(sim)
    monkeypatch.setattr(fplibMicro, "utime", clock)
    monkeypatch.setattr(fplibMicro, "UART", factory)
    return SimpleNamespace(clock=clock, sim=sim, factory=factory)


@pytest.fixture
def sensor(rig):
    fp = Fingerprint(port=2, baud=9600, tx=17, rx=16)
    assert fp.init() is True
    fp.set_led(False)
    rig.sim.commands.clear()
    return fp


def _load_firmware_module():
    spec = importlib.util.spec_from_file_location("lifelink_esp32_main", ESP32_DIR / "main.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FIRMWARE = _load_firmware_module()


class _FakeStdout:
    def __init__(self):
        self.buffer = io.BytesIO()
        self.text = []

    def write(self, s):
        self.text.append(s)
        return len(s)

    def flush(self):
        pass


class FirmwareRig:
    """Runs the real ESP32FirmwareDaemon.handle_command and decodes its LLFP replies."""

    def __init__(self, rig, monkeypatch):
        self.rig = rig
        self.stdout = _FakeStdout()
        # main.py writes replies to sys.stdout.buffer (USB CDC); give the module its own stdout
        monkeypatch.setattr(FIRMWARE, "sys", SimpleNamespace(stdout=self.stdout, stdin=None, path=sys.path))
        monkeypatch.setattr(FIRMWARE, "utime", rig.clock)
        self.daemon = FIRMWARE.ESP32FirmwareDaemon()
        self._n = 0

    def send(self, command, payload=b""):
        self._n += 1
        rid = struct.pack("<QQ", 0xC0FFEE, self._n)
        request = SerialFrame.unpack(SerialFrame.pack(KIND_REQUEST, command, rid, payload=payload))
        before = self.stdout.buffer.tell()
        self.daemon.handle_command(request)
        raw = self.stdout.buffer.getvalue()[before:]
        reply = SerialFrame.unpack(raw)
        assert reply and "error" not in reply, raw
        total = SerialFrame.HEADER_SIZE + len(reply["payload"]) + 4
        assert len(raw) == total, "exactly one reply frame per command"
        assert reply["kind"] == KIND_RESPONSE and reply["request_id"] == rid and reply["command"] == command
        return reply


@pytest.fixture
def fw(rig, monkeypatch):
    firmware = FirmwareRig(rig, monkeypatch)
    rig.sim.commands.clear()
    return firmware


def _cmds(sim):
    return [c for c, _ in sim.commands]


# ---------------------------------------------------------------------------
# A - Driver API completeness
# ---------------------------------------------------------------------------

def _sensor_calls_in_main():
    tree = ast.parse((ESP32_DIR / "main.py").read_text())
    calls = {}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Attribute) and node.func.value.attr == "sensor"):
            calls.setdefault(node.func.attr, []).append(node)
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Attribute)
                and node.value.attr == "sensor" and not isinstance(getattr(node, "ctx", None), ast.Store)):
            calls.setdefault(node.attr, [])
    return calls


def test_a_every_main_py_sensor_call_exists_with_compatible_signature():
    calls = _sensor_calls_in_main()
    required = {"init", "set_led", "enroll_start", "is_press_finger", "capture_finger", "enroll1", "enroll2",
                "enroll3", "get_template", "set_template", "verify", "delete_id", "last_error", "led_on"}
    assert required <= set(calls), f"main.py no longer calls {required - set(calls)}"
    fp = Fingerprint()
    for name, nodes in calls.items():
        assert hasattr(fp, name), f"Fingerprint.{name} used by main.py is missing"
        member = getattr(fp, name)
        for node in nodes:
            assert callable(member), name
            args = [object()] * len(node.args)
            kwargs = {kw.arg: object() for kw in node.keywords}
            inspect.signature(member).bind(*args, **kwargs)  # raises TypeError on mismatch


def test_a_low_level_transport_methods_exist():
    for name in ("_read_response", "_read_data", "_send_data", "_send_cmd", "command"):
        assert callable(getattr(Fingerprint, name, None)), name


def test_a_no_placeholder_method_bodies():
    """No public driver method may simply `return True` / `return None` without talking to the sensor."""
    tree = ast.parse((ESP32_DIR / "fplibMicro.py").read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "Fingerprint")
    for fn in [n for n in cls.body if isinstance(n, ast.FunctionDef) and not n.name.startswith("_")]:
        body = [s for s in fn.body if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
        trivial = len(body) == 1 and isinstance(body[0], ast.Return) and (
            body[0].value is None or isinstance(body[0].value, ast.Constant))
        assert not trivial, f"Fingerprint.{fn.name} is a placeholder"


# ---------------------------------------------------------------------------
# B - Sensor UART protocol
# ---------------------------------------------------------------------------

def test_b_uart_configuration_matches_wiring(rig):
    fp = Fingerprint(port=2, baud=9600, tx=17, rx=16)
    assert fp.init() is True
    cfg = rig.factory.calls[0]
    assert (cfg["port"], cfg["baud"], cfg["tx"], cfg["rx"]) == (2, 9600, 17, 16)
    assert cfg["rxbuf"] >= 12 + 504, "RX buffer must hold a response plus a template data packet"
    assert fp.device_info is not None and len(fp.device_info) == 24
    assert rig.sim.commands[0] == (CMD["OPEN"], 1)


def test_b_command_packet_is_byte_exact():
    pkt = fplibMicro.build_command_packet(CMD["CMOS_LED"], 1)
    expected_body = struct.pack("<2s2sIH", b"\x55\xaa", b"\x01\x00", 1, 0x12)
    assert bytes(pkt) == expected_body + struct.pack("<H", gs.sum16(expected_body))
    assert bytes(fplibMicro.build_data_packet(b"\x01\x02")) == gs.data_packet(b"\x01\x02")


def test_b_valid_ack_and_nack(sensor, rig):
    assert sensor.set_led(True) is True and rig.sim.led is True
    assert sensor.capture_finger() is False  # nothing on the glass
    assert sensor.last_error == "finger_is_not_pressed"


@pytest.mark.parametrize("chunk", [1, 3, 7])
def test_b_partial_reads_are_reassembled(sensor, rig, chunk):
    rig.sim.read_chunk = chunk
    rig.sim.slots[199] = finger_template(ALICE)
    assert sensor.get_template(199) == finger_template(ALICE)


def test_b_partial_and_stalled_writes_are_completed(sensor, rig):
    rig.sim.write_chunk = 5
    rig.sim.writes_with_none = 3
    assert sensor.set_template(10, finger_template(BOB)) is True
    assert rig.sim.slots[10] == finger_template(BOB)


def test_b_noise_before_response_is_skipped(sensor, rig):
    rig.sim.next_reply_faults.append(gs.garbage_prefix)
    assert sensor.set_led(True) is True


@pytest.mark.parametrize("fault, timeout", [
    (gs.corrupt_checksum, False),
    (gs.wrong_device_id, False),
    (gs.unexpected_code, False),
    (gs.truncate(7), True),
    (gs.drop, True),
])
def test_b_malformed_or_missing_response_raises_not_false_success(sensor, rig, fault, timeout):
    rig.sim.next_reply_faults.append(fault)
    with pytest.raises(SensorError) as exc:
        sensor.set_led(True)
    assert exc.value.timeout is timeout
    assert sensor.led_on is False


def test_b_disconnect_raises_timeout(sensor, rig):
    rig.sim.alive = False
    with pytest.raises(SensorError) as exc:
        sensor.is_press_finger()
    assert exc.value.timeout


def test_b_init_fails_when_sensor_absent(rig):
    rig.sim.alive = False
    fp = Fingerprint()
    assert fp.init() is False
    assert fp.last_error


def test_b_init_restores_9600_when_sensor_left_at_other_rate(rig):
    rig.sim.sensor_baud = 115200  # e.g. after a ChangeBaudrate without a power cycle
    fp = Fingerprint(baud=9600)
    assert fp.init() is True
    assert rig.sim.sensor_baud == 9600 and rig.sim.link_baud == 9600


def test_b_no_uart_is_reported_not_faked(monkeypatch):
    monkeypatch.setattr(fplibMicro, "UART", None)
    fp = Fingerprint()
    assert fp.init() is False
    with pytest.raises(SensorError):
        fp.set_led(False)


def test_b_led_is_switched_on_before_is_press_finger(sensor, rig):
    """The sensor stops answering IsPressFinger with the backlight off; the driver must light it first."""
    rig.sim.place(ALICE)
    assert sensor.is_press_finger() is True
    assert _cmds(rig.sim)[:2] == [CMD["CMOS_LED"], CMD["IS_PRESS_FINGER"]]
    rig.sim.lift()
    assert sensor.is_press_finger() is False


# ---------------------------------------------------------------------------
# C - Enrollment through main.py
# ---------------------------------------------------------------------------

def test_c_three_pass_enrollment_returns_sensor_template(fw, rig):
    sim = rig.sim
    sim.place(ALICE)
    r1 = fw.send(CMD_ENROLL_START, b"R1")
    assert (r1["status"], r1["payload"]) == (STATUS_OK, b"Pass 1 OK")
    assert sim.led is False
    for pass_no in (2, 3):
        sim.lift()
        sim.place(ALICE)
        r = fw.send(CMD_ENROLL_PASS, bytes([pass_no]))
        assert r["status"] == STATUS_OK, r
        assert sim.led is False
    tpl = fw.send(CMD_GET_TEMPLATE)
    assert tpl["status"] == STATUS_OK and tpl["payload"] == finger_template(ALICE)
    assert fw.send(CMD_DELETE_SLOT, struct.pack("<H", 199))["status"] == STATUS_OK
    assert 199 not in sim.slots
    seq = _cmds(sim)
    assert seq.index(CMD["ENROLL_START"]) < seq.index(CMD["ENROLL1"]) < seq.index(CMD["ENROLL2"]) < seq.index(CMD["ENROLL3"])


def test_c_stale_scratch_template_does_not_block_enrollment(fw, rig):
    rig.sim.slots[199] = finger_template(BOB)
    rig.sim.place(ALICE)
    assert fw.send(CMD_ENROLL_START, b"R1")["status"] == STATUS_OK


def test_c_no_finger_at_each_stage_is_bad_finger(fw, rig):
    r = fw.send(CMD_ENROLL_START, b"R1")
    assert (r["status"], r["payload"]) == (STATUS_BAD_FINGER, b"No finger detected")
    rig.sim.place(ALICE)
    assert fw.send(CMD_ENROLL_START, b"R1")["status"] == STATUS_OK
    rig.sim.lift()
    assert fw.send(CMD_ENROLL_PASS, b"\x02")["status"] == STATUS_BAD_FINGER
    assert rig.sim.led is False


def test_c_enroll_step_out_of_order_fails(fw, rig):
    rig.sim.place(ALICE)
    r = fw.send(CMD_ENROLL_PASS, b"\x03")
    assert r["status"] == STATUS_ERROR and b"turn_err" in r["payload"]


def test_c_different_fingers_never_produce_a_template(fw, rig):
    sim = rig.sim
    sim.place(ALICE)
    fw.send(CMD_ENROLL_START, b"R1")
    sim.place(ALICE)
    fw.send(CMD_ENROLL_PASS, b"\x02")
    sim.place(BOB)
    r3 = fw.send(CMD_ENROLL_PASS, b"\x03")
    assert r3["status"] == STATUS_ERROR and b"enroll_failed" in r3["payload"]
    assert fw.send(CMD_GET_TEMPLATE)["status"] == STATUS_ERROR


def test_c_duplicate_finger_is_reported(fw, rig):
    rig.sim.slots[3] = finger_template(ALICE)
    for cmd, payload in ((CMD_ENROLL_START, b"R1"), (CMD_ENROLL_PASS, b"\x02")):
        rig.sim.place(ALICE)
        fw.send(cmd, payload)
    rig.sim.place(ALICE)
    r = fw.send(CMD_ENROLL_PASS, b"\x03")
    assert r["status"] == STATUS_ERROR and b"duplicate_finger_id_3" in r["payload"]


def test_c_invalid_pass_number_is_rejected(fw, rig):
    assert fw.send(CMD_ENROLL_PASS, b"\x07")["status"] == STATUS_ERROR
    assert CMD["ENROLL2"] not in _cmds(rig.sim) and CMD["ENROLL3"] not in _cmds(rig.sim)


def test_c_sensor_lost_mid_enrollment_is_explicit_and_recovers(fw, rig):
    rig.sim.place(ALICE)
    rig.sim.alive = False
    r = fw.send(CMD_ENROLL_START, b"R1")
    assert r["status"] == STATUS_TIMEOUT and r["payload"].startswith(b"Sensor communication error")
    assert fw.daemon.sensor_ready is False
    # Still unplugged: explicit "not ready", no sensor operation attempted as success
    assert fw.send(CMD_LED, b"\x01")["status"] == STATUS_ERROR
    # Reconnected: the next command re-initialises the sensor
    rig.sim.alive = True
    rig.sim.wedged = False
    assert fw.send(CMD_LED, b"\x00")["status"] == STATUS_OK
    assert fw.daemon.sensor_ready is True
    assert CMD["OPEN"] in _cmds(rig.sim)


def test_c_single_impression_capture_returns_template(fw, rig):
    rig.sim.place(ALICE)
    r = fw.send(CMD_CAPTURE_SINGLE, b"probe")
    assert r["status"] == STATUS_OK and r["payload"] == finger_template(ALICE)
    assert rig.sim.led is False


def test_c_single_impression_fails_explicitly_if_sensor_requires_separate_placements(fw, rig):
    """Bench notes report Enroll3 NACKs when all scans come from one placement; that must be an error."""
    rig.sim.require_separate_placements = True
    rig.sim.place(ALICE)
    r = fw.send(CMD_CAPTURE_SINGLE, b"probe")
    assert r["status"] == STATUS_ERROR
    assert b"Enroll3 enroll_failed" in r["payload"]
    assert len(r["payload"]) != 498


# ---------------------------------------------------------------------------
# D - Template operations and integrity
# ---------------------------------------------------------------------------

def test_d_template_round_trip_is_byte_exact(sensor, rig):
    tpl = bytes(range(256)) + bytes(range(242))  # every byte value, incl. 0x55 0xAA / 0x5A 0xA5
    assert len(tpl) == 498
    assert sensor.set_template(42, tpl) is True
    assert rig.sim.slots[42] == tpl
    assert sensor.get_template(42) == tpl


def test_d_empty_slot_returns_none(sensor):
    assert sensor.get_template(150) is None
    assert sensor.last_error == "is_not_used"


@pytest.mark.parametrize("fault", [gs.corrupt_data_checksum, gs.flip_template_byte(100), gs.truncate(12 + 300)])
def test_d_corrupt_or_short_data_packet_raises(sensor, rig, fault):
    rig.sim.slots[199] = finger_template(ALICE)
    rig.sim.next_reply_faults.append(fault)
    with pytest.raises(SensorError):
        sensor.get_template(199)


@pytest.mark.parametrize("bad", [b"", b"\x00" * 497, b"\x00" * 499, "x" * 498, None])
def test_d_invalid_templates_are_not_sent(sensor, rig, bad):
    assert sensor.set_template(199, bad) is False
    assert sensor.last_error == "bad_template_size"
    assert rig.sim.commands == []


def test_d_template_corrupted_in_transit_is_rejected(sensor, rig, monkeypatch):
    real = fplibMicro.build_data_packet
    monkeypatch.setattr(fplibMicro, "build_data_packet", lambda d: real(d)[:-1] + b"\x00")
    assert sensor.set_template(199, finger_template(ALICE)) is False
    assert sensor.last_error == "comm_err"
    assert 199 not in rig.sim.slots


def test_d_template_survives_sensor_to_backend_path(fw, rig):
    """GT-521F32 -> driver -> main.py -> LLFP frame -> base64 (backend route) -> bytes."""
    rig.sim.place(ALICE)
    reply = fw.send(CMD_CAPTURE_SINGLE, b"probe")
    sensor_tpl = finger_template(ALICE)
    assert reply["payload"] == sensor_tpl
    b64 = base64.b64encode(reply["payload"]).decode("utf-8")   # backend/devices/routes.py encoding
    assert base64.b64decode(b64) == sensor_tpl
    # and back: host LOAD_TEMPLATE -> firmware -> SetTemplate
    assert fw.send(CMD_LOAD_TEMPLATE, base64.b64decode(b64))["status"] == STATUS_OK
    assert rig.sim.slots[199] == sensor_tpl


def test_d_load_template_wrong_size_rejected(fw, rig):
    r = fw.send(CMD_LOAD_TEMPLATE, b"\x00" * 100)
    assert (r["status"], r["payload"]) == (STATUS_ERROR, b"Invalid template size")
    assert CMD["SET_TEMPLATE"] not in _cmds(rig.sim)


# ---------------------------------------------------------------------------
# E - Verification
# ---------------------------------------------------------------------------

def _load_and_verify(fw, rig, enrolled_finger, live_finger):
    assert fw.send(CMD_LOAD_TEMPLATE, finger_template(enrolled_finger))["status"] == STATUS_OK
    if live_finger:
        rig.sim.place(live_finger)
    else:
        rig.sim.lift()
    return fw.send(CMD_VERIFY_1_1)


def test_e_matching_finger(fw, rig):
    r = _load_and_verify(fw, rig, ALICE, ALICE)
    assert (r["status"], r["payload"]) == (STATUS_OK, b"Match")
    assert rig.sim.led is False


def test_e_different_finger_is_no_match(fw, rig):
    r = _load_and_verify(fw, rig, ALICE, BOB)
    assert (r["status"], r["payload"]) == (STATUS_ERROR, b"No match")


def test_e_no_finger(fw, rig):
    r = _load_and_verify(fw, rig, ALICE, None)
    assert r["status"] == STATUS_BAD_FINGER


def test_e_no_loaded_template_is_a_failure_not_a_no_match(fw, rig):
    rig.sim.place(ALICE)
    r = fw.send(CMD_VERIFY_1_1)
    assert r["status"] == STATUS_ERROR
    assert r["payload"] == b"Verify failed: is_not_used"


def test_e_communication_failure_during_verify(fw, rig):
    fw.send(CMD_LOAD_TEMPLATE, finger_template(ALICE))
    rig.sim.place(ALICE)
    rig.sim.alive = False
    r = fw.send(CMD_VERIFY_1_1)
    assert r["status"] == STATUS_TIMEOUT


def test_e_invalid_slot_id(sensor, fw):
    with pytest.raises(ValueError):
        sensor.verify(500)
    r = fw.send(CMD_DELETE_SLOT, struct.pack("<H", 500))
    assert r["status"] == STATUS_ERROR


def test_e_failed_load_cannot_leave_previous_template_for_verify(fw, rig, monkeypatch):
    """A previous patient's template in slot 199 must not be verified against after a failed load."""
    rig.sim.slots[199] = finger_template(BOB)
    real = fplibMicro.build_data_packet
    monkeypatch.setattr(fplibMicro, "build_data_packet", lambda d: real(d)[:-1] + b"\x00")
    assert fw.send(CMD_LOAD_TEMPLATE, finger_template(ALICE))["status"] == STATUS_ERROR
    rig.sim.place(BOB)
    assert fw.send(CMD_VERIFY_1_1)["status"] != STATUS_OK


# ---------------------------------------------------------------------------
# F - Firmware robustness and MicroPython compatibility
# ---------------------------------------------------------------------------

def test_f_every_command_gets_exactly_one_reply_and_led_ends_off(fw, rig):
    rig.sim.place(ALICE)
    for cmd, payload in [(CMD_HELLO, b""), (CMD_STATUS, b""), (CMD_LED, b"\x01"), (CMD_CAPTURE_SINGLE, b"p"),
                         (CMD_GET_TEMPLATE, b""), (CMD_DELETE_SLOT, b""), (CMD_CANCEL, b""), (0x7777, b"")]:
        fw.send(cmd, payload)
    assert rig.sim.led is False
    assert 199 not in rig.sim.slots


def test_f_status_reports_sensor_ready(fw):
    assert fw.send(CMD_STATUS)["payload"] == b"\x01\x00"


def test_f_run_loop_keeps_a_second_frame_received_in_the_same_burst():
    f1 = SerialFrame.pack(KIND_REQUEST, CMD_LED, b"\x01" * 16, payload=b"\x00")
    f2 = SerialFrame.pack(KIND_REQUEST, CMD_DELETE_SLOT, b"\x02" * 16, payload=b"\xc7\x00")
    buf = bytearray(b"xx" + f1 + f2)
    first = SerialFrame.unpack(bytes(buf))
    rest = FIRMWARE.ESP32FirmwareDaemon._drop_frame(buf, first)
    assert bytes(rest) == f2


_FIRMWARE_FILES = [ESP32_DIR / "fplibMicro.py", ESP32_DIR / "main.py", PROTOCOL_DIR / "framing.py"]
_MICROPYTHON_MODULES = {"sys", "struct", "select", "binascii", "utime", "machine", "fplibMicro", "framing"}


@pytest.mark.parametrize("path", _FIRMWARE_FILES, ids=lambda p: p.name)
def test_f_unguarded_imports_exist_on_micropython(path):
    """Top-level imports outside try/except ImportError must be modules the ESP32 port provides."""
    tree = ast.parse(path.read_text())
    for node in tree.body:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module]
            for name in names:
                assert name.split(".")[0] in _MICROPYTHON_MODULES, f"{path.name}: unguarded import {name}"


def test_f_firmware_imports_without_desktop_only_modules():
    """Imports the firmware with typing / uuid / zlib / time unavailable (as on MicroPython)."""
    script = textwrap.dedent(f"""
        import sys, binascii
        for m in ("typing", "uuid", "zlib"):
            sys.modules[m] = None
        sys.path[:0] = [{str(ESP32_DIR)!r}, {str(PROTOCOL_DIR)!r}]
        import framing, fplibMicro
        f = framing.SerialFrame.pack(framing.KIND_RESPONSE, 0x12, b"\\x01" * 16, payload=b"abc")
        assert framing.SerialFrame.unpack(f)["payload"] == b"abc"
        short = framing.SerialFrame.pack(framing.KIND_REQUEST, 1, b"\\x07")
        assert framing.SerialFrame.unpack(short)["request_id"] == b"\\x07" + b"\\x00" * 15
        print(f.hex())
    """)
    out = subprocess.run([sys.executable, "-I", "-c", script], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    reference = SerialFrame.pack(KIND_RESPONSE, 0x12, b"\x01" * 16, payload=b"abc")
    assert out.stdout.strip() == reference.hex(), "binascii.crc32 framing must equal zlib.crc32 framing"
