# LifeLink 2.0 — Raspberry Pi Zero W Camera Peripheral Deployment Package

## 1. Hardware Requirements & Interconnect

### Required Hardware
- **Processor Board**: Raspberry Pi Zero W (or Pi Zero 2 W).
- **Camera Module**: Raspberry Pi Camera Module 3 Wide NoIR (Sony IMX708 sensor, 120° FoV, IR-sensitive).
- **Camera Cable**: 15-pin to 22-pin camera ribbon cable (Pi Zero CSI connector).
- **Illumination Array**: 850 nm Infrared LED illuminator driven via switching MOSFET or constant-current driver.
- **Physical Pin Connection**:
  - Control signal: Raspberry Pi Zero **GPIO18** (Physical Pin 12, PWM0 capable).
  - Power: Regulated external 5V/12V for high-current LED array. Common GND with Pi Zero.
  - *Caution*: Never power high-current IR LEDs directly from Pi GPIO pins.
- **Data Interconnect**: Micro-USB to USB-A data cable connected to the Pi Zero **USB Data Port** (labeled `USB`, NOT `PWR IN`). The other end connects to a Raspberry Pi 5 USB-A host port.

---

## 2. Operating System & Prerequisites
- **Target OS**: Raspberry Pi OS Lite (32-bit or 64-bit Bookworm / Bullseye).
- **Network Mode**: USB Gadget Ethernet (`g_ether` on `dwc2`) assigned static IP `192.168.55.2/24`.
- **Zero Wireless**: Wi-Fi and Bluetooth are disabled during operation; communication is strictly wired USB.

---

## 3. Directory Structure
```text
pi-zero/
├── camera_service.py         # Lightweight Flask REST daemon (port 5001)
├── camera_client.py          # Picamera2 wrapper with auto-fallback
├── config.py                 # Peripheral configuration & thresholds
├── ir_led_controller.py      # Thread-safe GPIO18 850nm controller with safety watchdog
├── iris_capture.py           # Multi-frame acquisition, quality ranking, LED synchronization
├── photo_capture.py          # Patient portrait acquisition (IR LED strictly OFF)
├── quality.py                # ISO/IEC 29794-6 image quality metrics
├── quality_checker.py        # Frame evaluation wrapper
├── usb_communication.py      # Structured JSON formatting for wired transfers
├── main.py                   # Service launcher entry point
├── verify_camera.py          # Local diagnostic verification tool
├── requirements.txt          # Python dependencies
├── install.sh                # Complete installation script
├── systemd/
│   └── lifelink-camera.service # Systemd daemon definition
└── README.md                 # Deployment documentation
```

---

## 4. Installation Instructions

Execute the automated installer as root:
```bash
cd pi-zero
sudo bash install.sh
```

### What `install.sh` Does:
1. Installs `python3-picamera2`, `python3-opencv`, `python3-gpiozero`, and `gpiod`.
2. Appends `dtoverlay=dwc2` to `/boot/firmware/config.txt` (or `/boot/config.txt`).
3. Adds `g_ether` to `/etc/modules`.
4. Configures static IP `192.168.55.2/24` on `usb0` via `/etc/network/interfaces.d/usb0`.
5. Deploys application files to `/opt/lifelink-camera`.
6. Configures user `pi` with `video` and `gpio` group permissions.
7. Registers and enables `lifelink-camera.service` systemd daemon.
8. Forces GPIO18 to OUTPUT LOW (OFF).

Reboot the Pi Zero W after installation:
```bash
sudo reboot
```

---

## 5. Startup & Operational Invariants

1. **Automatic Boot & Connection**:
   - The Pi Zero W powers up from the Pi 5 USB-A host port.
   - The Linux kernel loads `g_ether`, enumerating as an Ethernet gadget (`usb0`).
   - `lifelink-camera.service` starts automatically on `192.168.55.2:5001`.
   - The camera service enters `STATE_IDLE`.
2. **Strict Invariant — Zero Auto-Capture**:
   - The camera **NEVER** captures images or activates illumination upon boot, USB reconnection, or login.
   - Image capture is initiated **only** when Pi 5 issues an authenticated `POST /api/v1/camera/iris/capture` or `POST /api/v1/camera/photo/capture` command triggered by a clinical operator.
3. **IR LED Illumination Safety Invariant**:
   - IR LED is **strictly OFF** when idle.
   - IR LED switches **ON** only after camera initialization during iris capture.
   - IR LED switches **OFF** immediately upon capture completion, cancellation, error, or after a maximum safety timeout of 15 seconds enforced by hardware/software watchdogs.
   - IR LED is **strictly OFF** during ordinary patient portrait photo capture.

---

## 6. Verification & Health-Check Commands

Run local hardware diagnostics:
```bash
python3 /opt/lifelink-camera/verify_camera.py
```

Check service status from Pi Zero W:
```bash
sudo systemctl status lifelink-camera.service
```

Query camera and IR LED status over the wired network (from Pi 5 or Pi Zero W):
```bash
curl http://192.168.55.2:5001/health
curl http://192.168.55.2:5001/camera/led/status
```

Expected response:
```json
{
  "camera_state": "IDLE",
  "led_active": false,
  "service": "LifeLink 2.0 Wired Camera Service",
  "status": "ready"
}
```

Trigger a test iris capture:
```bash
curl -X POST http://192.168.55.2:5001/api/v1/camera/iris/capture \
     -H "Content-Type: application/json" \
     -d '{"eye_side": "OD"}'
```

---

## 7. Troubleshooting

| Issue | Root Cause | Solution |
|:---|:---|:---|
| Pi 5 cannot ping `192.168.55.2` | Wrong USB port on Pi Zero | Connect cable to inner micro-USB port (labeled `USB`, not `PWR IN`). |
| Camera service fails to bind IP | `usb0` interface not yet up | Service automatically retries; verify `ifconfig usb0` on Pi Zero. |
| Picamera2 initialization error | Loose CSI ribbon cable | Reseat ribbon cable on Pi Zero connector with contacts facing PCB. |
| Quality filter constantly rejects | Lens out of focus or bad lighting | Adjust M12 lens focus for 10-15 cm subject distance. |
| IR LED does not illuminate | Inverted active logic | Set `IR_LED_ACTIVE_HIGH=false` in `/opt/lifelink-camera/config.py` if driver is active-low. |

---

## 8. Update & Rollback Procedures

- **Update**:
  ```bash
  cd /opt/lifelink-camera
  sudo git pull   # or copy new .py files
  sudo systemctl restart lifelink-camera.service
  ```
- **Rollback**:
  ```bash
  sudo systemctl stop lifelink-camera.service
  # Restore backup files from /opt/lifelink-camera/
  sudo systemctl start lifelink-camera.service
  ```
