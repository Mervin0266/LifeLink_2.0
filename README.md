# LifeLink 2.0 — Emergency Medical Identity & Patient Information Platform

LifeLink 2.0 is a biometric-assisted emergency medical patient identification and record management system built for Raspberry Pi 5 touchscreen terminals. It features **100% wired peripheral links**, **offline-first local database operations**, **hybrid Supabase cloud synchronization**, and an **enterprise Admin Dashboard**.

---

## 🚀 Quickstart (Mock Mode — No Hardware Required)

You can run and test the complete system on Windows, macOS, or Linux in developer mock mode without physical sensors or Pi hardware:

### 1. Prerequisites
- Python 3.10+ (Python 3.11–3.13 recommended)
- `pip` package manager

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Bootstrap & Seed Synthetic Data
```bash
python scripts/seed_demo.py
```
This initializes the local database and creates demo accounts:
- **Clinician Login:** `doctor@lifelink.local` / `Clinical@123`
- **Hospital Staff Login:** `registrar@lifelink.local` / `Hospital@123`
- **Records Admin Login:** `recordsadmin@lifelink.local` / `Admin@123`
- **System Admin Login:** `sysadmin@lifelink.local` / `SysAdmin@123`

### 4. Run the Kiosk Application
```bash
python scripts/run_mock.py
```
Open your browser at `http://127.0.0.1:5000` to interact with the full touchscreen UI in mock device mode.

### 5. Run the Test Suite
```bash
pytest tests/ -v
```

---

## 🔑 Key Architectural Capabilities

- **Zero Wireless Peripherals:** ESP32 communicates over USB serial; Pi Zero W camera communicates over USB gadget Ethernet (`192.168.55.0/24`). Zero Wi-Fi/Bluetooth dependencies for peripheral operation.
- **Three Dedicated Login Portals:** Role-tailored entrances for Clinical, Hospital, and Admin staff with individual accounts and server-enforced RBAC.
- **Workflow A (Register Patient):** Ten-finger enrollment (R1–R5, L1–L5) $\rightarrow$ OD & OS iris scans $\rightarrow$ patient photo $\rightarrow$ medical/clinical records $\rightarrow$ duplicate candidate check $\rightarrow$ atomic local commit $\rightarrow$ LifeLink ID generation.
- **Workflow B (Retrieve Patient):** Biometric 1:N candidate search $\rightarrow$ 1:1 confirmation $\rightarrow$ high-priority emergency summary (allergies, meds, freshness) $\rightarrow$ manual ID search fallback.
- **Workflow C (Update Patient):** Operator identity confirmation $\rightarrow$ permitted field edits $\rightarrow$ before/after change diff $\rightarrow$ mandatory audit reason $\rightarrow$ outbox sync queue.
- **Admin Dashboard:** Real-time KPI widgets $\rightarrow$ patient lifecycle management (view metadata, edit with reason, archive/deactivate) $\rightarrow$ controlled multi-stage deletion request workflow $\rightarrow$ staff administration $\rightarrow$ device readiness $\rightarrow$ sync conflict resolver $\rightarrow$ audit explorer.
- **Data Privacy & Minimization:** Biometric templates and raw eye frames are encrypted locally and NEVER uploaded to Supabase Cloud by default.

---

## 📂 Project Structure

```text
├── AGENTS.md                   # Persistent workspace rules & invariants
├── README.md                   # This document
├── requirements.txt            # Python dependencies
├── docs/                       # Architectural specs, RTM, ADRs, runbooks
├── frontend/                   # Touchscreen kiosk UI (HTML, CSS, ES6)
├── backend/                    # Flask backend APIs, auth, RBAC, services
├── fingerprint-device/         # ESP32 firmware & Pi 5 USB serial worker
├── iris-module/                # Camera daemon, LightIrisNet & Vis-IrisFormer
├── database/                   # Local PostgreSQL & Supabase migrations
├── sync/                       # Transactional outbox sync daemon
├── scripts/                    # CLI tools: bootstrap, mock, seed, backup
└── tests/                      # Pytest unit, contract, security, E2E tests
```

---

## ⚠️ Disclaimer

LifeLink 2.0 is a clinical information-retrieval and patient identification prototype. It does not provide autonomous medical diagnosis or treatment instructions. Biometric matching thresholds must be empirically validated on target clinical populations before any live patient deployment.
