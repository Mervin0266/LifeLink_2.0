# LifeLink 2.0 — Raspberry Pi 5 Central Terminal Deployment Package

## 1. Hardware Requirements & Topology

### Required Hardware
- **Host Terminal**: Raspberry Pi 5 (4GB or 8GB LPDDR4X RAM).
- **Power Supply**: Official Raspberry Pi 27W USB-C Power Supply (5.1V / 5.0A with PD).
  - *Caution*: Do NOT power peripherals directly from the Pi 5 USB-C port; that port is strictly for incoming mains terminal power.
- **Display**: 7-inch to 10.1-inch Touchscreen Terminal (DSI ribbon or HDMI + USB touch interface).
- **Storage**: High-end Class 10 / A2 MicroSD Card (minimum 32GB) or NVMe SSD via Raspberry Pi M.2 HAT+.
- **Wired Peripherals**:
  - **ESP32 Fingerprint Substation**: Connected to Pi 5 USB-A 3.0 port via high-grade shielded data cable.
  - **Pi Zero W Iris Camera Substation**: Connected to Pi 5 USB-A 3.0 port via Micro-USB to USB-A data cable (enumerates as USB Ethernet gadget `usb0`).
  - **Hospital Local Network (Optional)**: Cat6 Ethernet connected to the onboard Gigabit RJ45 port for cloud synchronization.

---

## 2. Operating System & Prerequisites
- **Target OS**: Raspberry Pi OS (64-bit Debian 12 Bookworm with Wayland/X11 desktop).
- **Zero Wireless Invariant**: Wi-Fi and Bluetooth radios are permanently disabled in `/boot/firmware/config.txt` (`dtoverlay=disable-wifi`, `dtoverlay=disable-bt`).
- **Python**: Python 3.11+ (system or virtual environment at `/opt/lifelink/venv`).

---

## 3. Directory Structure
```text
pi5/
├── backend/                  # Flask REST API & Core Orchestration
│   ├── app.py                # Main application factory & route registration
│   ├── config.py             # Centralized configuration & environment loader
│   ├── admin/                # Role-gated administration routes
│   ├── audit/                # Tamper-evident immutable audit logging
│   ├── auth/                 # RBAC engine, tokens, and credentials
│   ├── biometrics/           # 1:1 verification, 1:N search & fusion service
│   ├── database/             # Connection pooling & AES-256-GCM encryption
│   ├── devices/              # Hardware host clients & mock simulators
│   └── patients/             # Patient registration, retrieval & revisions
├── frontend/                 # Pure Vanilla Touchscreen UI (Monochrome Clinical Design)
│   ├── index.html            # Single-page kiosk application
│   ├── css/style.css         # Minimalist high-contrast medical stylesheet
│   └── js/
│       ├── api.js            # Fetch client for local REST endpoints
│       └── app.js            # Kiosk UI controller & state machine
├── iris-engine/              # Deep Learning Inference Pipeline
│   ├── normalizer.py         # Daugman polar rubber-sheet transformation (64x512)
│   ├── recognizer.py         # Vis-IrisFormer Vision Transformer feature extractor
│   ├── segmenter.py          # LightIrisNet MobileNetV3 boundary segmentation
│   └── service.py            # End-to-end orchestration pipeline
├── protocol/
│   └── framing.py            # LLFP binary serial protocol with CRC32
├── sync/
│   └── worker.py             # Transactional outbox cloud synchronization worker
├── database/
│   ├── schema.sql            # Unified DDL schema for SQLite and PostgreSQL
│   └── init_db.py            # Database initialization and staff seeding utility
├── kiosk/
│   └── kiosk.sh              # Locked Chromium kiosk launcher script
├── systemd/
│   ├── lifelink-backend.service # Central backend service
│   └── lifelink-kiosk.service   # Touchscreen graphical kiosk launcher
├── udev/
│   └── 99-lifelink.rules     # Deterministic USB symlinks (/dev/lifelink-fingerprint)
├── weights/
│   └── README.md             # Model weight specifications and checksums
├── requirements.txt          # Python production dependencies
├── .env.example              # Environment configuration template
├── install.sh                # End-to-end installation script
├── verify_installation.py    # Comprehensive post-installation diagnostic test
└── README.md                 # Deployment documentation
```

---

## 4. Installation Instructions

Execute the automated installer on the Raspberry Pi 5 as root:
```bash
cd pi5
sudo bash install.sh
```

### Installation Steps Executed by `install.sh`:
1. Installs APT packages (`python3-venv`, `libpq-dev`, `chromium-browser`, `unclutter`, `sqlite3`).
2. Deploys the application codebase to `/opt/lifelink`.
3. Creates Python virtual environment at `/opt/lifelink/venv`.
4. Installs Python packages from `requirements.txt`.
5. Installs `udev/99-lifelink.rules` and triggers device discovery.
6. Initializes database tables and seeds default staff accounts via `database/init_db.py`.
7. Installs and enables `lifelink-backend.service` and `lifelink-kiosk.service`.
8. Runs `verify_installation.py` to confirm zero errors before proceeding.

---

## 5. Startup & Peripheral Invariants

1. **System Boot Sequence**:
   - Raspberry Pi 5 powers on and loads systemd services.
   - `lifelink-backend.service` starts `/opt/lifelink/venv/bin/python backend/app.py` on `0.0.0.0:5000`.
   - The backend checks for ESP32 on `/dev/lifelink-fingerprint` and Pi Zero W on `http://192.168.55.2:5001`.
   - Peripherals report `READY` / `IDLE`.
   - Graphical session loads `lifelink-kiosk.service`, launching Chromium in locked fullscreen kiosk mode displaying `http://127.0.0.1:5000`.
2. **Strict Invariant — Zero Auto-Scanning**:
   - Biometric acquisition **NEVER** starts automatically on boot, page navigation, or peripheral reconnect.
   - Scanning begins **exclusively** when an authenticated clinical operator clicks "Start Scan" in the UI.
3. **Biometric Security Boundary**:
   - Biometric templates are encrypted at rest with local AES-256-GCM.
   - Biometric templates are **NEVER** transmitted to cloud databases by default.

---

## 6. Default Staff Credentials (Initial Test Mode)

| Portal | Username | Role | Default Password | Permissions |
|:---|:---|:---|:---|:---|
| **Clinical Login** | `dr_smith` | Clinician | `DoctorPass123!` | Retrieve Emergency & Clinical, Update Clinical, Register |
| **Clinical Login** | `nurse_clara` | Clinician | `NursePass123!` | Retrieve Emergency & Clinical, Update Clinical |
| **Hospital Login** | `john_reg` | Registration Staff | `RegStaffPass123!` | Register Patient, Update Demographics |
| **Admin Login** | `records_admin` | Records Admin | `RecordsAdminPass123!` | Archive, Deletion Request Review, Audit Logs |
| **Admin Login** | `admin` | System Admin | `AdminPass123!` | Staff Management, System Maintenance, Device Health |

*Warning: Change all passwords immediately upon hospital deployment.*

---

## 7. Health Checks & Verification

Run the comprehensive post-installation diagnostic suite:
```bash
/opt/lifelink/venv/bin/python /opt/lifelink/verify_installation.py
```

Query the backend health endpoint:
```bash
curl http://127.0.0.1:5000/api/v1/health
```

Query peripheral readiness:
```bash
curl http://127.0.0.1:5000/api/v1/devices/status
```

---

## 8. Service Management Commands

```bash
# Backend Service
sudo systemctl start lifelink-backend
sudo systemctl stop lifelink-backend
sudo systemctl restart lifelink-backend
sudo journalctl -u lifelink-backend -f

# Touchscreen Kiosk UI
sudo systemctl restart lifelink-kiosk
```

---

## 9. Troubleshooting

| Issue | Cause | Solution |
|:---|:---|:---|
| Fingerprint status: `DISCONNECTED` | USB cable loose or udev rule unapplied | Run `ls -l /dev/lifelink-fingerprint` and verify with `udevadm trigger`. |
| Camera status: `DISCONNECTED` | USB Ethernet link not established | Check `ifconfig usb0` on Pi 5. Verify Pi Zero W is plugged into its USB DATA port. |
| Database lock error | Multiple writers on SQLite | Switch to local PostgreSQL by setting `DB_TYPE=postgresql` in `/etc/lifelink/lifelink.env`. |
| Kiosk screen is blank | X11/Wayland display not ready | Check `DISPLAY=:0` and inspect logs with `journalctl -u lifelink-kiosk -f`. |

---

## 10. Update & Rollback Procedures

- **Update Codebase**:
  ```bash
  cd /opt/lifelink
  sudo systemctl stop lifelink-backend
  # Deploy updated backend or frontend files
  sudo /opt/lifelink/venv/bin/python database/init_db.py
  sudo systemctl start lifelink-backend
  ```
- **Rollback**:
  ```bash
  sudo systemctl stop lifelink-backend
  # Restore previous release files
  sudo systemctl start lifelink-backend
  ```
