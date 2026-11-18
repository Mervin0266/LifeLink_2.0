# LifeLink 2.0 — Raspberry Pi 3B+ Wired Ethernet Camera Substation Runbook

**Document:** `docs/pi3b-ethernet-camera.md`  
**Target Hardware:** Raspberry Pi 3 Model B+ connected to Raspberry Pi 5 Host  
**Physical Link:** Dedicated Wired RJ45 Ethernet (Direct Cat5e/6 or Isolated Medical Switch)  
**Status:** Validated Technical Architecture & Runbook  

---

## 1. Overview and Architectural Rationale

LifeLink 2.0 utilizes a decoupled multi-board architecture to safeguard patient privacy, guarantee low latency, and enforce clinical safety invariants:
- **Raspberry Pi 5 (Central Terminal):** Runs the patient database (PostgreSQL/SQLite), touchscreen clinical GUI, biometric template matching engines (Vis-IrisFormer / LightIrisNet), and hospital audit services.
- **Raspberry Pi 3 Model B+ (Camera Substation):** Operates as a headless, dedicated optical capture node responsible for sensor driving (Camera Module 3 Wide NoIR), synchronized 850nm NIR IR LED illumination (GPIO18), and ISO/IEC 29794-6 quality screening.
- **ESP32 Dev Module (Fingerprint Subsystem):** Operates the GT-521F32 optical fingerprint sensor over framed UART/USB serial.

### Key Rationale for Raspberry Pi 3B+ with Wired Ethernet:
1. **Robust Direct Physical Networking:** The Pi 3B+ features an onboard Microchip LAN7515 Ethernet controller delivering dedicated ~300 Mbps throughput over standard RJ45 cabling, eliminating the need for USB OTG gadget emulation.
2. **Deterministic Response Time:** Eliminates USB bus contention on the host and avoids wireless packet drops in RF-dense emergency departments.
3. **Hardware Parity & 40-Pin Header Compatibility:** Both Pi Zero W and Pi 3B+ share identical 40-pin GPIO pinouts; BCM GPIO18 (Physical Pin 12, PWM0 capable) drives the IR LED controller with zero circuit redesign.
4. **Complete RF Silence (Zero Runtime Wireless):** Onboard Wi-Fi (Cypress BCM43455) and Bluetooth 4.2 BLE are disabled at the device tree overlay level (`dtoverlay=disable-wifi`, `dtoverlay=disable-bt`), eliminating medical equipment interference and wireless attack vectors.

---

## 2. Hardware Topology & Wiring Specifications

### 2.1 Hardware Components
| Component | Model / Spec | Purpose |
|:---|:---|:---|
| **Substation SBC** | Raspberry Pi 3 Model B+ (BCM2837B0, 1.4 GHz, 1 GB LPDDR2) | Dedicated image acquisition node |
| **Camera Module** | Raspberry Pi Camera Module 3 Wide NoIR (Sony IMX708, 120° FoV) | 850nm NIR-sensitive iris & portrait capture |
| **CSI Ribbon Cable** | 15-pin 1.0mm pitch flexible flat ribbon (standard Pi 3/4 cable) | Connects camera to Pi 3B+ CSI port |
| **Illumination Array**| 850 nm High-Power NIR LED Array | Transilluminates iris pattern without pupil constriction |
| **Switching Driver** | Logic-level N-Channel MOSFET (IRLZ44N or AO3400A) | Switches LED current isolated from GPIO |
| **Network Cable** | Cat5e / Cat6 UTP patch cable (0.5m to 3.0m) | Direct point-to-point connection Pi 5 ↔ Pi 3B+ |

### 2.2 CSI Ribbon Installation Warning
> [!IMPORTANT]
> The Raspberry Pi 3B+ uses a **15-pin 1.0mm pitch** CSI connector (unlike the Pi Zero's 22-pin 0.5mm pitch connector).
> - Lift the plastic collar gently on the Pi 3B+ CSI port (situated between the HDMI and 3.5mm audio jack).
> - Insert the 15-pin ribbon with the **silver contacts facing the HDMI port** and the blue stiffener facing the audio jack.
> - Press the collar down firmly to lock the ribbon in place.

### 2.3 GPIO18 IR LED Illumination Circuit
```text
  Raspberry Pi 3B+ Pinout
  Pin 12 (BCM GPIO18) ───[ 220Ω Resistor ]─── Gate (G)
                                                  │
                                             ┌────┴────┐
                                             │ IRLZ44N │ (Logic-Level N-MOSFET)
                                             └────┬────┘
                                                  │ Drain (D)
                                                  ├─── [ 850nm IR LED Array (with current limiting) ] ─── +5V / +12V Ext PSU
                                                  │
  Pin 14 (GND) ────────────────────────────── Source (S) ──────────────── Common GND (Ext PSU)
```

> [!CAUTION]
> Never connect high-current IR LEDs directly to the 3.3V or 5V header pins of the Raspberry Pi. Always use an external regulated power supply with a shared common ground and a switching transistor.

---

## 3. Network Architecture & Addressing

### 3.1 Point-to-Point Addressing Plan
```text
┌─────────────────────────────────┐                 ┌─────────────────────────────────┐
│     Raspberry Pi 5 (Host)       │  RJ45 Ethernet  │   Raspberry Pi 3B+ (Camera)     │
│   IP: 192.168.50.1 / 24         │◄───────────────►│   IP: 192.168.50.2 / 24         │
│   Backend Port: 5000            │  Direct Cable   │   Service Port: 5000            │
└─────────────────────────────────┘                 └─────────────────────────────────┘
```

- **Subnet:** `192.168.50.0/24` (`255.255.255.0`)
- **Host Endpoint (Pi 5):** `192.168.50.1`
- **Substation Endpoint (Pi 3B+):** `192.168.50.2`
- **Substation HTTP Service Port:** `5000`
- **API URL:** `http://192.168.50.2:5000`
- **Request Timeout:** `30.0 seconds`
- **Auth Token Header:** `X-Camera-Token: lifelink-wired-internal-camera-token`

### 3.2 Pi 5 Host Network Configuration
On the Raspberry Pi 5 terminal, assign static IP `192.168.50.1/24` to the Ethernet interface:

**Using NetworkManager (`nmcli`):**
```bash
sudo nmcli con add type ethernet con-name "lifelink-camera-link" ifname eth0 \
    ip4 192.168.50.1/24 ipv4.method manual
sudo nmcli con up "lifelink-camera-link"
```

---

## 4. Substation Installation & Systemd Service

### 4.1 Automated Setup on Raspberry Pi 3B+
On the Pi 3B+, transfer the `LifeLink_2.0_Deployment/pi3b/` folder and execute:
```bash
cd pi3b
sudo bash install.sh
sudo reboot
```

### 4.2 Systemd Daemon (`lifelink-camera.service`)
The installer registers `/etc/systemd/system/lifelink-camera.service`:
```ini
[Unit]
Description=LifeLink 2.0 Wired Iris Camera & 850nm IR LED Daemon (Raspberry Pi 3B+)
After=network.target local-fs.target
Wants=network.target

[Service]
Type=simple
User=pi
Group=video
WorkingDirectory=/opt/lifelink-camera
Environment=PYTHONUNBUFFERED=1
Environment=PORT=5000
Environment=HOST=0.0.0.0
Environment=IR_LED_GPIO_PIN=18
Environment=IR_LED_ACTIVE_HIGH=true
Environment=IR_LED_ENABLED=true
Environment=MAX_SCAN_TIMEOUT_SECONDS=15.0
Environment=CAMERA_DEVICE=raspberry-pi-3b-plus
Environment=DEVICE_NAME=RaspberryPi-3B-Plus-CameraModule3-NoIR
Environment=TRANSPORT_NAME=Wired-Ethernet
Environment=CAMERA_API_TOKEN=lifelink-wired-internal-camera-token
Environment=REQUIRE_AUTH=true
Environment=MOCK_MODE=false
ExecStart=/usr/bin/python3 -m camera_service
Restart=always
RestartSec=3
StandardOutput=journal
StandardError=journal
SyslogIdentifier=lifelink-camera

ProtectSystem=full
ProtectHome=read-only
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

---

## 5. Security & Safety Invariants

1. **Zero Auto-Capture Invariant:**
   The camera never captures frames, streams video, or turns on illumination upon boot, link reconnection, or idle state. All actions are button-triggered by authorized clinicians.
2. **15-Second Optical Watchdog:**
   GPIO18 illumination has a hard 15.0-second auto-off watchdog timer in both `ir_led_controller.py` and hardware PWM handling. If a scan hangs or network drops mid-capture, the LED extinguishes automatically.
3. **Token Authentication:**
   Mutating API endpoints (`/api/v1/camera/iris/capture`, `/api/v1/camera/photo/capture`, `/api/v1/camera/cancel`) require the `X-Camera-Token` header. Unauthenticated requests are rejected with `401 Unauthorized`.
4. **Portrait Separation:**
   Normal patient portrait photo capture (`/api/v1/camera/photo/capture`) explicitly enforces that the IR LED remains **OFF** throughout acquisition.
5. **ISO/IEC 29794-6 Screening:**
   Frames are screened for sharpness (Laplacian variance $\ge 50$), intensity distribution ($35 \le \mu \le 220$), maximum specular glare ratio ($\le 5\%$), and minimum iris diameter ($\ge 100$ px). The best acceptable frame is returned.

---

## 6. Verification and Health Testing

### Step 1: Run Substation Hardware Diagnostics (on Pi 3B+)
```bash
python3 /opt/lifelink-camera/verify_camera.py
```

Expected Output:
```text
=================================================================
 LifeLink 2.0: Raspberry Pi 3B+ Camera Substation Diagnostic
 Target Device:    RaspberryPi-3B-Plus-CameraModule3-NoIR
 Transport Link:   Wired-Ethernet (0.0.0.0:5000)
=================================================================
[Step 1/5] Verifying GPIO18 IR LED Controller Safety Invariants...
  [+] Controller status: {'pin': 18, 'active': False, 'mode': 'hardware'}
  [OK] Invariant Verified: IR LED starts strictly in OFF state.
  [*] Performing momentary pulse test (0.2s)...
  [OK] Invariant Verified: IR LED turned OFF cleanly after pulse.
[Step 2/5] Testing Camera Capture Interface...
  [+] Camera initialized: True (Mode: Hardware/Picamera2)
  [OK] Frame acquired successfully! Dimensions: 640x480 px, Channels: 3
[Step 3/5] Evaluating ISO/IEC 29794-6 Quality Filter...
  [+] Sharpness (Laplacian var): 84.21
  [+] Mean Intensity:            112.50
  [+] Glare Percentage:          0.4%
  [+] Est. Iris Diameter:        128 px
  [+] Quality Acceptable:        True
[Step 4/5] Testing IrisCaptureCoordinator (LED Synchronization & Quality Ranking)...
  [+] Scan Result Status: completed
  [+] Captured Attempts:  3
  [+] State Transitions:  INITIALIZING -> ILLUMINATING -> ACQUIRING -> EVALUATING -> COMPLETED
  [OK] Invariant Verified: IR LED is confirmed OFF following scan completion.
[Step 5/5] Releasing Hardware Resources...
  [OK] Hardware resources cleanly released.
=================================================================
 LifeLink 2.0: Pi 3B+ Substation Hardware Verification PASSED!
=================================================================
```

### Step 2: Test Network Connectivity from Pi 5
```bash
ping -c 3 192.168.50.2
curl -s http://192.168.50.2:5000/health
```

Expected JSON response:
```json
{
  "camera_state": "IDLE",
  "led_active": false,
  "service": "LifeLink 2.0 Wired Camera Service",
  "device": "RaspberryPi-3B-Plus-CameraModule3-NoIR",
  "transport": "Wired-Ethernet",
  "status": "ready"
}
```

### Step 3: Trigger Authenticated Capture from Pi 5
```bash
curl -X POST http://192.168.50.2:5000/api/v1/camera/iris/capture \
     -H "Content-Type: application/json" \
     -H "X-Camera-Token: lifelink-wired-internal-camera-token" \
     -d '{"eye_side": "OD"}'
```

---

## 7. Troubleshooting Matrix

| Symptom | Probable Cause | Action |
|:---|:---|:---|
| **No link light on RJ45 port** | Bad cable, loose jack, or interface disabled | Verify Cat5e/6 cable; check `ethtool eth0` or `ip link set eth0 up`. |
| **Ping unreachable (`Destination Host Unreachable`)** | IP addressing subnet mismatch | Verify Pi 5 is on `192.168.50.1/24` and Pi 3B+ is on `192.168.50.2/24`. |
| **`rpicam-hello` fails with `no cameras available`** | CSI ribbon loose or backwards | Inspect 15-pin ribbon orientation: contacts face HDMI port. Check `vcgencmd get_camera`. |
| **HTTP 401 Unauthorized** | Missing `X-Camera-Token` | Verify token in `/etc/lifelink/lifelink.env` on Pi 5 matches Pi 3B+ configuration. |
| **IR LED stays ON** | Watchdog failure or stuck GPIO | Hard shutoff: `sudo pinctrl set 18 op dl`. Inspect `ir_led_controller.py` watchdog logs. |
| **Iris frames persistently rejected** | Focus distance incorrect | Adjust M12 lens focus to sharpest iris detail at 12–15 cm clinical focal distance. |

