# LifeLink 2.0 — ESP32 Fingerprint Peripheral Deployment Package

## 1. Hardware Requirements & Pinout

### Required Components
- **Microcontroller**: ESP32 DevKitC (ESP32-WROOM-32D / ESP32-WROOM-32U).
- **Biometric Sensor**: ADH-Tech GT-521F32 Optical UART Fingerprint Module.
- **Interconnect Cable**: High-quality shielded Micro-USB to USB-A data cable (connecting ESP32 to Raspberry Pi 5 USB-A host port).
- **Power**: Sensor powered via regulated 3.3V / 5.0V (verify GT-521F32 module voltage spec; maximum peak current during optical flash: ~130mA).

### Physical Wiring (ESP32 <-> GT-521F32)
| GT-521F32 Pin | Wire Color | ESP32 DevKit Pin | Function |
|:---|:---|:---|:---|
| Pin 1 (VCC) | Red | 5V / VIN (or 3V3 per module) | Power Supply |
| Pin 2 (GND) | Black | GND | Common System Ground |
| Pin 3 (TXD) | Yellow | GPIO16 (RX2) | Sensor UART Transmit to ESP32 |
| Pin 4 (RXD) | Green / White | GPIO17 (TX2) | Sensor UART Receive from ESP32 |

---

## 2. Required Operating System & Firmware
- **ESP32 Firmware**: MicroPython v1.20+ generic ESP32 binary (`esp32-20230426-v1.20.0.bin` or newer).
- **Host Tools OS**: Linux (Raspberry Pi OS Bookworm ARM64) or Windows/macOS with Python 3.9+.

---

## 3. Directory Structure
```text
esp32/
├── firmware/
│   ├── boot.py               # ESP32 startup script (disables noisy logs, triggers gc)
│   ├── framing.py            # LLFP binary protocol encoder/decoder with CRC32
│   ├── fplibMicro.py         # Full GT-521F32 UART driver with 2048B buffer
│   └── main.py               # Non-blocking USB serial event loop and state machine
├── host-tools/
│   ├── flash.sh              # Flashing & auto-verification script
│   └── test_handshake.py     # Standalone serial protocol diagnostic utility
├── firmware_version.txt      # Build metadata and protocol invariants
├── requirements.txt          # Host tool Python dependencies
└── README.md                 # Deployment documentation
```

---

## 4. Installation & Flashing Instructions

### Step 1: Install Host Tools on Raspberry Pi 5 or Workstation
```bash
cd esp32
pip install -r requirements.txt
```

### Step 2: Upload LifeLink Firmware
Run the automated flashing script:
```bash
chmod +x host-tools/flash.sh
./host-tools/flash.sh /dev/ttyUSB0
```
*Note: If no serial port is specified, `flash.sh` auto-detects CP2102/CH340/FTDI devices.*

### Step 3 (Optional): MicroPython Initial Flashing (New/Blank ESP32)
If your ESP32 does not yet have MicroPython installed:
```bash
esptool.py --port /dev/ttyUSB0 erase_flash
esptool.py --port /dev/ttyUSB0 --chip esp32 write_flash -z 0x1000 esp32-20230426-v1.20.0.bin
./host-tools/flash.sh /dev/ttyUSB0
```

---

## 5. Automatic Startup & Peripheral Invariants

1. **Boot Lifecycle**:
   - ESP32 boots upon receiving USB 5V power from Raspberry Pi 5.
   - `boot.py` configures memory management.
   - `main.py` opens `UART(2, baudrate=115200, tx=17, rx=16, rxbuf=2048)` and initializes the GT-521F32 sensor (`open_device()`).
   - The sensor enters `STATE_IDLE`. Sensor LED is turned **OFF**.
2. **Strict Invariant — Zero Auto-Scanning**:
   - The sensor **NEVER** initiates fingerprint capture on boot, reboot, or serial reconnection.
   - Capture occurs **exclusively** upon receiving an explicit `CMD_ENROLL_START`, `CMD_ENROLL_PASS`, or `CMD_CAPTURE` packet triggered by an authenticated clinical operator clicking the UI button.
3. **Template Scratch Cleanup**:
   - Temporary sensor slot 199 is used for intermediate template operations and is wiped with `CMD_DELETE_SLOT` immediately upon completion or cancellation.

---

## 6. Health Checks & Diagnostics

Run the Python diagnostic tool:
```bash
python host-tools/test_handshake.py --port /dev/ttyUSB0
```

Expected diagnostic output:
```text
[*] Opening serial connection to ESP32 on /dev/ttyUSB0 @ 115200 baud...
[*] Sending CMD_HELLO (0x01)...
[+] CMD_HELLO SUCCESS! Device Identifier: LifeLink-ESP32-Fingerprint-v2.0
[*] Sending CMD_STATUS (0x02)...
[+] CMD_STATUS SUCCESS! Hardware State: READY
[*] Testing LED state cycle (Momentary check)...
[+] Invariant Verified: Fingerprint LED is OFF in idle state.
[+] Invariant Verified: Sensor does not scan automatically.
```

---

## 7. Troubleshooting

| Symptom | Cause | Solution |
|:---|:---|:---|
| `CMD_HELLO` times out | Wrong baud rate or wrong serial port | Verify port with `ls /dev/serial/by-id/` and check permissions (`sudo usermod -a -G dialout pi`). |
| Status reports `UART_ERROR` | Inverted RX/TX wires | Swap GPIO16 and GPIO17 connections on the GT-521F32 harness. |
| Template transfer truncated | Default MicroPython UART buffer overflow | Confirm `rxbuf=2048` is set in `fplibMicro.py`. |
| Blue sensor LED remains lit | Hardware freeze during enrollment | Run `python host-tools/test_handshake.py` to reset LED to OFF. |

---

## 8. Update & Rollback Procedures

- **Update**: Edit or update files in `firmware/` and re-run `./host-tools/flash.sh`.
- **Rollback**: To revert to a known good state, copy previous `fplibMicro.py` and `main.py` versions into `firmware/` and re-run `flash.sh`.
