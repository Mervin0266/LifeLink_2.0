# LifeLink 2.0 — Level C Physical Hardware Bench Test Plan

**Scope:** Deployment and verification on physical hardware components in bench and resuscitation bay environments.  
**Target Hardware:**
1. **Host Terminal:** Raspberry Pi 5 (8GB RAM), Debian 12 Bookworm (ARM64), 7" DSI/HDMI Capacitive Touchscreen (1024x600).
2. **Iris Camera Subsystem:** Raspberry Pi Zero W, Sony IMX708 NoIR (Camera Module 3 NoIR), 850 nm High-Power IR LED module on GPIO18 (Pin 12) with MOSFET driver.
3. **Fingerprint Subsystem:** ESP32 DevKit V1 (USB-UART bridge at `/dev/serial/by-id/...`), Waveshare GT-521F32 optical fingerprint sensor on UART2 (GPIO16 RX / GPIO17 TX).

---

## 1. Bench Wiring & Hardware Sanity Check

```
+-------------------------------------------------------------------------------+
| RASPBERRY PI 5 (Host Kiosk)                                                   |
| - Port 5000: Flask Core, SQLite/PostgreSQL, Chromium Kiosk Mode (1024x600)    |
| - USB Port 1: Micro-USB / Type-C to Pi Zero W (USB Gadget Ethernet Mode)     |
|   IP: 192.168.55.1/24 (Pi 5 usb0) <-----> 192.168.55.2/24 (Pi Zero usb0)    |
| - USB Port 2: USB Type-A to Micro-USB to ESP32 DevKit (Serial at 115,200 baud)|
|   Device: /dev/serial/by-id/usb-Silicon_Labs_CP2102... or /dev/ttyUSB0        |
+-------------------------------------------------------------------------------+
       │                                                      │
       │ USB Gadget Ethernet                                  │ USB Serial
       ▼                                                      ▼
+-------------------------------------+  +-------------------------------------+
| RASPBERRY PI ZERO W (Camera Daemon) |  | ESP32 DEVKIT (UART Bridge)         |
| - Port 5001: camera_service.py      |  | - MicroPython / C Firmware (main.py)|
| - CSI Port: IMX708 NoIR Ribbon      |  | - Pin 16 (RX2) <-> GT-521F32 TX     |
| - Pin 12 (GPIO18): IR LED Gate (via |  | - Pin 17 (TX2) <-> GT-521F32 RX     |
|   2N7002 / IRLZ44N N-MOSFET)        |  | - 3.3V / 5V & GND                   |
| - Pin 6: GND                        |  +-------------------------------------+
+-------------------------------------+                     │
                   │                                        ▼
                   ▼                             +--------------------+
         +--------------------+                  | GT-521F32 SENSOR   |
         | 850 nm IR LED      |                  | Optical Prism & LED|
         | Constant Current   |                  +--------------------+
         +--------------------+
```

---

## 2. Test Cases & Physical Acceptance Criteria

### Test HW-C01: Pi Zero W USB Gadget Ethernet Auto-Discovery
- **Objective:** Verify Pi 5 establishes wired network link to Pi Zero W with zero wireless interfaces.
- **Procedure:**
  1. Boot Pi Zero W with `dtoverlay=dwc2` and `modules-load=dwc2,g_ether`.
  2. Connect Pi Zero USB OTG port to Pi 5 USB 3.0 port.
  3. Run `ip link show usb0` and `ping -c 3 192.168.55.2`.
- **Acceptance Criteria:** Round-trip latency < 1.5ms, 0% packet loss, service responds at `http://192.168.55.2:5001/api/v1/camera/health`.

### Test HW-C02: 850 nm IR LED Optical Synchronization & Oscilloscope Probe
- **Objective:** Verify IR LED activates strictly during active scanning and powers off immediately upon completion.
- **Procedure:**
  1. Attach oscilloscope channel 1 to Pi Zero W GPIO18 (Pin 12).
  2. Point infrared viewing card or phone camera (without IR cut filter) at 850 nm emitter.
  3. From kiosk terminal UI, click "Scan Iris (Right Eye)".
  4. Measure rise time, duration of HIGH signal, and fall time.
- **Acceptance Criteria:**
  - Signal remains 0.0V (LOW) before click.
  - Switches to 3.3V (HIGH) within 15ms of request initiation.
  - Returns to 0.0V (LOW) within 30ms of frame transmission.
  - Optical emission visible on IR card exclusively during scan.

### Test HW-C03: Hardware Safety Watchdog Fail-Safe Trigger
- **Objective:** Verify physical IR LED cannot overheat or cause ocular hazard if daemon hangs.
- **Procedure:**
  1. Initiate scan session with simulated client hang (SIGSTOP applied to client process).
  2. Observe GPIO18 voltage on oscilloscope.
- **Acceptance Criteria:** GPIO18 automatically drops to 0.0V (LOW) at exactly 15.0 seconds (watchdog timeout limit).

### Test HW-C04: ESP32 Serial Auto-Discovery & Hot-Plug Recovery
- **Objective:** Verify hot-plugging the ESP32 USB cable cleanly reconnects without daemon restart.
- **Procedure:**
  1. Check device status: `GET /api/v1/devices/health` -> `fingerprint_device.connected: true`.
  2. Unplug physical USB cable from Pi 5.
  3. Query health endpoint -> `fingerprint_device.connected: false`.
  4. Re-insert USB cable into any Pi 5 port.
  5. Wait 3 seconds and query health endpoint.
- **Acceptance Criteria:** Status automatically returns to `connected: true` without errors.

### Test HW-C05: GT-521F32 3-Stage Guided Enrollment
- **Objective:** Verify physical optical finger acquisition and template download.
- **Procedure:**
  1. Click "Enroll Right Index (R1)" on kiosk touch screen.
  2. Observe GT-521F32 optical backlight turns ON.
  3. Place finger on optical prism for Pass 1, lift, place for Pass 2, lift, place for Pass 3.
  4. Observe optical backlight turns OFF immediately upon Pass 3 capture.
- **Acceptance Criteria:** 498-byte template successfully downloaded, scratch slot 199 zeroized on sensor, encrypted in local database.
