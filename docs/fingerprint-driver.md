# ESP32 Fingerprint Driver — GT-521F32 over UART2

**Applies to:** `fingerprint-device/esp32/fplibMicro.py`, `fingerprint-device/esp32/main.py`,
`fingerprint-device/protocol/framing.py` (MicroPython firmware). Introduced by LL-002A.

## 1. Two protocol layers — do not mix them

| Link | Between | Framing | Where |
|---|---|---|---|
| LLFP | Pi 5 ↔ ESP32, USB CDC 115200 | `LLFP` magic, 28-byte header, CRC32 | `framing.py`, `main.py`, `backend/devices/fingerprint_host.py` |
| GT-521Fx2 UART | ESP32 ↔ sensor, UART2 9600 | 12-byte command/response, data packets, 16-bit sum | `fplibMicro.py` only |

## 2. Hardware configuration

`Fingerprint(port=2, baud=9600, tx=17, rx=16)`. ESP32 GPIO16 = RX2 ← sensor TX, GPIO17 = TX2 → sensor RX.
The UART is opened with `rxbuf=2048` (a 498-byte template arrives as a 504-byte data packet; the
MicroPython default 256-byte buffer truncates it) and `timeout=50` ms per read.
`init()` tries 9600 first; if the sensor was left at another rate by `ChangeBaudrate`
(it keeps that rate until power is lost) it finds it among 115200/57600/38400/19200 and
switches it back. Power: the bench notes of the reference driver report that 3V3 powered
the sensor more reliably than 5 V on their board — verify against `docs/wiring.md` on your hardware.

## 3. Sensor protocol (GT-521Fx2 datasheet, "UART protocol")

```
command  (12 B): 55 AA | 01 00 | param  LE32 | command   LE16 | checksum LE16
response (12 B): 55 AA | 01 00 | param  LE32 | 30 ACK / 31 NACK | checksum LE16
data   (4+N+2):  5A A5 | 01 00 | data (N)    | checksum LE16
checksum = 16-bit sum of all preceding bytes of the packet
```

On NACK, `param` is an error code (`NACK_ERRORS`: 0x1001 timeout … 0x1012
finger_is_not_pressed); for Enroll1–3 a value < 0x1000 is the slot of a duplicate finger.
Commands used: Open (with device-info data packet), CmosLed, IsPressFinger, CaptureFinger,
EnrollStart/1/2/3, GetTemplate, SetTemplate, Verify1_1, DeleteID, CheckEnrolled,
GetEnrollCount, ChangeBaudrate. `DeleteAll` is deliberately not exposed.

The packet layout was cross-checked against two independent implementations: the
reference MicroPython GT-521Fx2 driver from a separate bench project (not in this
repository; used on a real GT-521Fx2) and the repository's Arduino firmware (`lifelink_esp32_firmware.ino`).
It has **not** been re-verified on hardware in LL-002 (no sensor attached).

## 4. Error policy

* **Transport failure** → `SensorError` (attribute `timeout`): no reply before the deadline,
  partial/truncated packet, bad checksum, wrong start code or device ID, a response code
  that is neither ACK nor NACK, UART unavailable.
* **NACK** → method returns `False` / `None` and sets `last_error` (e.g. `verify_failed`,
  `is_not_used`, `enroll_failed`, `duplicate_finger_id_3`).
* Partial reads are accumulated; partial or stalled writes are completed or time out.
* Nothing returns success without an ACK from the sensor; there are no placeholder methods.

`main.py` catches `SensorError` per command, turns the LED off and wipes slot 199
(best effort), answers `STATUS_TIMEOUT`/`STATUS_ERROR` with `"Sensor communication error: …"`,
and marks the sensor for re-initialisation; the next sensor command re-runs `init()`.
Every LLFP command gets exactly one reply that echoes its request ID and command.

## 5. Method contracts (all called by `main.py`)

| Method | Sensor commands | Returns |
|---|---|---|
| `init()` | Open(1) [+ ChangeBaudrate] | `True` only if Open is ACKed |
| `set_led(on)` | CmosLed | ACK |
| `is_press_finger()` | [CmosLed on] IsPressFinger | `True` if ACK and param 0 |
| `capture_finger(high_quality=True)` | CaptureFinger(1/0) | ACK |
| `enroll_start(slot)` | EnrollStart(slot) | ACK (`is_already_used` if occupied) |
| `enroll1()` / `enroll2()` / `enroll3()` | Enroll1/2/3 | ACK; Enroll3 stores the merged template in the slot |
| `get_template(slot)` | GetTemplate + 498-byte data packet | `bytes` (498) or `None` on NACK |
| `set_template(slot, tpl)` | SetTemplate + data packet + ACK | `True` only after the data ACK; wrong size → `False` without sending |
| `verify(slot)` | Verify1_1 (last capture vs slot) | `True` match; `False` + `last_error` |
| `delete_id(slot)` | DeleteID | ACK (`is_not_used` if already empty) |

Slots are validated (0–199); the firmware only uses scratch slot **199**.

## 6. Enrollment and template flow

3-pass registration (host `start_enrollment` / `advance_enrollment`):
1. `ENROLL_START`: LED on → DeleteID(199) → EnrollStart(199) → wait ≤ 4 s for a finger →
   CaptureFinger(HQ) → Enroll1 → LED off.
2. `ENROLL_PASS 2` / `3` (operator lifts and replaces the finger between passes):
   LED on → wait → CaptureFinger(HQ) → Enroll2 / Enroll3 → LED off.
3. `GET_TEMPLATE`: GetTemplate(199) → 498 bytes in the LLFP response payload.
4. Host `DELETE_SLOT` / `CANCEL` wipe slot 199.

`CAPTURE_SINGLE` (retrieval probe) performs the three scans on one placement. The
reference driver's bench notes say this sensor NACKs Enroll3 unless every scan is a
separate placement; the firmware now reports that as `"Single impression template failed:
Enroll3 enroll_failed"` instead of ignoring the Enroll2/3 results. **Verify on hardware.**

`LOAD_TEMPLATE` deletes slot 199 before SetTemplate, so a failed load cannot leave the
previous patient's template in the slot for a following `VERIFY_1_1`.
`VERIFY_1_1` answers `OK "Match"`, `ERROR "No match"` (`verify_failed`), or
`ERROR "Verify failed: <cause>"` for other failures (e.g. no template loaded).

The template travels unchanged: sensor data packet → `get_template` (checksum verified) →
LLFP payload (CRC32) → host → base64 in the API → encrypted at rest.

## 7. MicroPython compatibility

The firmware imports only `sys`, `struct`, `select`, `utime`, `machine`, `binascii`
unguarded. `framing.py` no longer requires `typing`, `uuid` or `zlib` (it uses
`binascii.crc32` on MicroPython) and no longer uses `bytes.ljust`. The run loop no longer
sleeps 5 ms between received bytes (a 530-byte LOAD_TEMPLATE frame previously took ≈2.7 s)
and keeps a second frame that arrives in the same burst.
Checked in CPython with those modules blocked; **not yet run on a real MicroPython build.**

## 8. Tests

```bash
pytest tests/unit/test_fingerprint_driver.py -v   # driver + firmware against tests/unit/gt521_sim.py
pytest tests/unit/test_framing.py -v
```
The simulator models the documented protocol and NACK codes, partial reads/writes,
corrupt/silent replies, baud mismatch and the LED-before-IsPressFinger quirk. It does not
model optics: simulated templates are deterministic per finger, real ones are not.
Bench validation: flash `main.py`, `fplibMicro.py`, `framing.py` (e.g. with `mpremote`), then
`python lifelink_hardware_diagnostic.py --esp32 --fingerprint --interactive`.
