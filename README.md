# LifeLink 2.0 — Multi-Device Deployment Suite

## Overview
LifeLink 2.0 is an emergency medical identity and patient record platform engineered for fully wired, offline-first deployment on a Raspberry Pi 5 touchscreen kiosk terminal with dedicated USB hardware peripherals.

This deployment directory contains three independent, device-specific packages:

```text
LifeLink_2.0_Deployment/
├── pi5/                       # Raspberry Pi 5 Central Touchscreen Kiosk
├── pi-zero/                   # Raspberry Pi Zero W Wired Camera Peripheral
├── esp32/                     # ESP32 GT-521F32 Fingerprint Peripheral Firmware
├── deployment-manifest.json   # Cryptographic SHA-256 build manifest
├── deployment-validation.md   # Comprehensive test & verification report
└── README.md                  # Master deployment guide (this file)
```

---

## 1. Device-to-Folder Mapping & Hardware Topology

| Target Device | Deployment Folder | Primary Role | Physical Interconnect | Operating System / Runtime |
|:---|:---|:---|:---|:---|
| **Raspberry Pi 5** | `pi5/` | Central Kiosk Terminal (Flask backend, monochrome GUI, local DB, iris AI engine, sync) | Master Host (27W USB-C power, DSI/HDMI display) | Debian 12 Bookworm (64-bit ARM64) |
| **Raspberry Pi Zero W** | `pi-zero/` | Dedicated Iris & Portrait Camera Peripheral (IMX708 NoIR, GPIO18 850nm IR LED) | Pi Zero USB Data port ↔ Pi 5 USB-A (USB Gadget Ethernet `192.168.55.2`) | Raspberry Pi OS Lite (32/64-bit) |
| **ESP32 DevKit** | `esp32/` | Dedicated Fingerprint Peripheral (GT-521F32 UART sensor driver & LLFP protocol) | ESP32 Micro-USB ↔ Pi 5 USB-A (USB Serial 115200 baud `/dev/lifelink-fingerprint`) | MicroPython v1.20+ (Xtensa) |

### Physical Interconnect Diagram
```text
  GT-521F32 Fingerprint Sensor
        │  UART (TX: GPIO17, RX: GPIO16, 5V/GND)
        ▼
   [ ESP32 DevKit ] ───────── USB Serial Cable ───────────────┐
   (firmware from esp32/)                                     │
                                                              │
  Camera Module 3 Wide NoIR                                   ▼
        │  15-pin CSI Ribbon                        [ RASPBERRY PI 5 ]
        ▼                                           (software from pi5/)
 [ Raspberry Pi Zero W ] ─── USB Gadget Ethernet ──► - Monochrome Kiosk GUI
 (daemon from pi-zero/)       (192.168.55.2:5001)     - Flask Backend (:5000)
        │                                             - Local SQLite / Postgres
        └── GPIO18 ──► 850nm IR LED Driver            - Iris AI Inference Engine
                                                      - Sync Outbox Worker
```

---

## 2. Step-by-Step Deployment Procedure

### Device 1: Flash ESP32 Fingerprint Peripheral
*Perform on developer workstation or directly from Pi 5:*
1. Connect ESP32 to USB port.
2. Navigate to `esp32/` and flash:
   ```bash
   cd esp32
   pip install -r requirements.txt
   chmod +x host-tools/flash.sh
   ./host-tools/flash.sh /dev/ttyUSB0
   ```
3. Verify diagnostic handshake:
   ```bash
   python host-tools/test_handshake.py --port /dev/ttyUSB0
   ```
4. Disconnect from workstation and plug into Raspberry Pi 5 USB-A port.

---

### Device 2: Install Raspberry Pi Zero W Camera Peripheral
1. Copy `pi-zero/` directory to the Pi Zero W (via MicroSD or temporary SSH):
   ```bash
   cd pi-zero
   sudo bash install.sh
   sudo reboot
   ```
2. Connect a Micro-USB cable from the Pi Zero W **USB Data Port** (labeled `USB`, NOT `PWR IN`) to a Raspberry Pi 5 USB-A port.
3. Test local hardware diagnostics on Pi Zero W:
   ```bash
   python3 /opt/lifelink-camera/verify_camera.py
   ```

---

### Device 3: Install Raspberry Pi 5 Central Terminal
1. Copy `pi5/` directory to the Raspberry Pi 5:
   ```bash
   cd pi5
   sudo bash install.sh
   ```
2. The installation script automatically initializes the local database, creates staff accounts, configures udev rules, registers systemd units, and runs `verify_installation.py`.
3. Start the backend:
   ```bash
   sudo systemctl start lifelink-backend
   ```
4. Verify overall system health:
   ```bash
   curl http://127.0.0.1:5000/api/v1/health
   curl http://127.0.0.1:5000/api/v1/devices/status
   ```
5. On reboot, the Pi 5 automatically boots into fullscreen Chromium kiosk mode.

---

## 3. Core Architectural Invariants

1. **Zero Wireless Hardware Links**: All hardware links are strictly physical (USB serial for ESP32; USB gadget Ethernet for Pi Zero W). No Wi-Fi or Bluetooth dependencies.
2. **Offline-First Operation**: All core patient registration, emergency retrieval, clinical update, and administration operate against local storage when disconnected from the WAN.
3. **No Automatic Scanning**: The camera and fingerprint sensor **NEVER** initiate scanning upon boot, login, page navigation, or USB reconnection. Scanning occurs strictly upon operator button clicks.
4. **Local Biometric Boundary**: Biometric templates (fingerprint and iris) are encrypted locally using AES-256-GCM and are **NEVER** transmitted to cloud databases by default.
5. **850 nm IR LED Optical Safety**: IR LED illuminates strictly during active iris acquisition; turns OFF immediately upon completion, error, or after a 15-second safety timeout.

---

## 4. Verification and Validation
- **Manifest**: Check file integrity against `deployment-manifest.json`.
- **Validation Report**: Detailed automated test logs and physical bench gates are documented in `deployment-validation.md`.
