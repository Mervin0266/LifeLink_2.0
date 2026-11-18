# LifeLink 2.0 — Complete Technical Specification, Architecture & Implementation Manual

**Project:** LifeLink 2.0 (Emergency Medical Identity & Clinical Patient Platform)  
**Target Architecture:** Raspberry Pi 5 Touchscreen Kiosk Terminal (ARM64, Debian 12 Bookworm)  
**Peripheral Nodes:** Raspberry Pi 3 Model B+ (Camera Substation), ESP32 DevKit (Fingerprint Terminal)  
**Document Revision:** 2.0.5 — Master Technical Release (Continuous Biometric Loop & BGR Color Standard)  
**Classification:** Medical Device Embedded Software Specification  

---

## Table of Contents
1. [Executive Summary & Architectural Invariants](#1-executive-summary--architectural-invariants)
2. [Hardware Topology & Electrical Interconnects](#2-hardware-topology--electrical-interconnects)
3. [Fingerprint Subsystem & LLFP Protocol](#3-fingerprint-subsystem--llfp-protocol)
4. [Camera Substation & Shared-Session Architecture](#4-camera-substation--shared-session-architecture)
5. [Deep Learning Iris Recognition Pipeline](#5-deep-learning-iris-recognition-pipeline)
6. [Security, RBAC & Cryptographic Data Boundary](#6-security-rbac--cryptographic-data-boundary)
7. [Database Architecture & Complete Schema DDL](#7-database-architecture--complete-schema-ddl)
8. [Transactional Outbox & Cloud Synchronization](#8-transactional-outbox--cloud-synchronization)
9. [End-to-End Operational Workflows](#9-end-to-end-operational-workflows)
10. [RESTful API Complete Reference](#10-restful-api-complete-reference)
11. [Frontend Touchscreen UI & Controller Architecture](#11-frontend-touchscreen-ui--controller-architecture)
12. [Full Deployment, Runbooks & Diagnostic Procedures](#12-full-deployment-runbooks--diagnostic-procedures)

---

## 1. Executive Summary & Architectural Invariants

### 1.1 Mission and Purpose
LifeLink 2.0 is an offline-first, highly resilient emergency medical identification platform engineered to provide instant, definitive identification of unconscious, non-verbal, or trauma patients presenting at emergency triage terminals. By coupling high-throughput biometrics (optical fingerprint minutiae and deep near-infrared iris recognition) with localized clinical record storage, the system ensures zero patient misidentification even in the event of hospital network blackout, natural disaster, or cyber-warfare disconnects.

### 1.2 The Five Core Invariants
The system enforces five strict architectural invariants that govern all software and hardware components:

1. **Zero Runtime Wireless Dependencies:**
   - Under no circumstances does the system communicate with biometric peripherals over Wi-Fi, Bluetooth, or BLE.
   - The ESP32 communicates exclusively via USB CDC serial (`115200 8N1`).
   - The camera substation communicates exclusively over a direct, point-to-point wired Cat5e/Cat6 Ethernet connection on isolated subnet `192.168.50.0/24`.
2. **Offline-First Determinism:**
   - All patient enrollment, multi-modal identification (1:1 and 1:N), clinical updates, and administrative audits execute against a local SQLite / PostgreSQL database.
   - Cloud connectivity is treated strictly as an asynchronous background synchronization channel.
3. **Strict Biometric Cryptographic Boundary:**
   - Raw iris images and mathematical biometric templates (fingerprint and iris) are encrypted locally using **AES-256-GCM** with unique per-template nonces.
   - Raw biometrics and templates are **NEVER uploaded to cloud databases**. Only anonymized clinical records, encounter logs, and cryptographic sync checksums cross the wide-area network boundary.
4. **No Unprompted Hardware Scanning:**
   - Camera illumination and optical fingerprint sensors remain completely idle and unpowered during boot, login, route navigation, or USB link reconnection.
   - Hardware actuation occurs exclusively upon explicit operator UI interaction.
5. **Eye Safety & 850 nm Optical Watchdog:**
   - The 850 nm near-infrared (NIR) LED array on the camera substation is driven via a dedicated hardware MOSFET switch on BCM GPIO18.
   - A hardware-guaranteed watchdog timer enforces an automatic shutoff after 15 seconds, precluding hazardous optical exposure even during software failure.

---

## 2. Hardware Topology & Electrical Interconnects

### 2.1 System Block Diagram

```text
 ┌──────────────────────────────────────────────────────────────┐
 │ GT-521F32 Optical Fingerprint Sensor                         │
 │ 450 dpi, 200-slot optical prism scanner                      │
 └──────────────────────────────┬───────────────────────────────┘
                                │ 3.3V TTL UART (115200 baud)
                                │ TX: GPIO17 (ESP32 RX2)
                                │ RX: GPIO16 (ESP32 TX2)
                                ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ ESP32 Microcontroller Node (CP2102 / CH340 Bridge)          │
 │ Framed Binary Protocol (LLFP) + 3-Pass Scratch Engine        │
 └──────────────────────────────┬───────────────────────────────┘
                                │ USB 2.0 Data Cable (CDC Serial)
                                │ Path: /dev/ttyUSB0 (symlinked via udev)
                                ▼
 ┌──────────────────────────────────────────────────────────────┐
 │ RASPBERRY PI 5 TOUCHSCREEN KIOSK (HOST)                      │
 │ Broadcom BCM2712 Quad-Core Cortex-A76 @ 2.4 GHz, 8GB RAM     │
 │                                                              │
 │  ┌────────────────────────────────────────────────────────┐  │
 │  │ Chromium Touchscreen Kiosk UI (1024x600 / 1920x1080)   │  │
 │  └───────────────────────────┬────────────────────────────┘  │
 │                              │ HTTP / WebSocket (:5000)      │
 │                              ▼                               │
 │  ┌────────────────────────────────────────────────────────┐  │
 │  │ Core Flask Application Server (Gunicorn / Waitress)    │  │
 │  │  - Auth & Strict RBAC Guard Middleware                 │  │
 │  │  - Patient Clinical Workflow Engine                    │  │
 │  │  - Shared Device Manager & In-Memory Lock Orchestrator │  │
 │  │  - Transactional Outbox Sync Worker                    │  │
 │  └───────────────┬────────────────────────────┬───────────┘  │
 │                  │                            │              │
 │                  ▼                            ▼              │
 │  ┌──────────────────────────────┐  ┌──────────────────────┐  │
 │  │ Local Relational Database    │  │ Iris Inference Engine│  │
 │  │ (SQLite / Local PostgreSQL)  │  │ - LightIrisNet       │  │
 │  │ - AES-256-GCM Template Vault │  │ - Polar Normalization│  │
 │  │ - Device Job Log & Outbox    │  │ - Vis-IrisFormer     │  │
 │  └──────────────────────────────┘  └──────────────────────┘  │
 └───────────────────────────────────────────────▲──────────────┘
                                                 │
                                                 │ RJ45 Cat5e/6 Direct Cable
                                                 │ Subnet: 192.168.50.0/24
                                                 │ HTTP JSON + MJPEG (:5000)
                                                 │
                                  ┌──────────────┴──────────────┐
                                  │ Raspberry Pi 3 Model B+     │
                                  │ Camera Substation (LAN7515) │
                                  │ Static IP: 192.168.50.2     │
                                  │                             │
                                  │ - Picamera2 Shared Session  │
                                  │ - ISO/IEC 29794-6 Quality   │
                                  │ - IR LED Watchdog (GPIO18)  │
                                  └──────────────▲──────────────┘
                                                 │
                                                 │ 15-pin 1.0mm CSI Ribbon
                                                 │
                                  ┌──────────────┴──────────────┐
                                  │ Raspberry Pi Camera Mod 3   │
                                  │ Sony IMX708 NoIR (NIR 850nm)│
                                  │ + High-Power 850nm NIR LED  │
                                  └─────────────────────────────┘
```

### 2.2 Electrical Wiring & Pinout Table

#### 2.2.1 GT-521F32 Optical Fingerprint Sensor to ESP32
The sensor connects via a 4-pin JST-SH interface directly to the ESP32:

| GT-521F32 Pin | Lead Color | ESP32 Pin | Logic Level | Description |
|---|---|---|---|---|
| **Pin 1 (GND)** | Black | **GND** | 0V | Common ground reference |
| **Pin 2 (VCC)** | Red | **VIN (5V) or 3V3** | 3.3V–5.0V DC | Power supply (peak 130mA during blue LED flash) |
| **Pin 3 (TXD)** | Green | **GPIO 16 (RX2)** | 3.3V TTL | Sensor UART data output to ESP32 |
| **Pin 4 (RXD)** | Yellow | **GPIO 17 (TX2)** | 3.3V TTL | Sensor UART data input from ESP32 |

#### 2.2.2 Raspberry Pi 3B+ IR LED Driver Circuit
The 850nm NIR LED array is powered by the 5V bus and switched via an N-channel logic-level MOSFET:

| Component | Connected To | Description |
|---|---|---|
| **Gate** | BCM GPIO18 (Pin 12) | 100 $\Omega$ series resistor + 10 k$\Omega$ pulldown to GND |
| **Drain** | NIR LED Cathode (-) | Switched ground return |
| **Source** | System GND | Ground return |
| **LED Anode (+)** | 5V DC Bus (Pins 2/4) | In series with $2.2\ \Omega$ 1W current-limiting resistor |

#### 2.2.3 Ethernet Interface Settings
- **Raspberry Pi 5 Host:**
  - Interface: `eth0`
  - IP Address: `192.168.50.1`
  - Subnet Mask: `255.255.255.0` (`/24`)
  - Broadcast: `192.168.50.255`
- **Raspberry Pi 3B+ Camera Substation:**
  - Interface: `eth0`
  - IP Address: `192.168.50.2`
  - Subnet Mask: `255.255.255.0` (`/24`)
  - Gateway: `192.168.50.1`
  - Listening Daemon: `0.0.0.0:5000`

---

## 3. Fingerprint Subsystem & LLFP Protocol

### 3.1 Non-Volatile Flash Wear Protection (Scratch Slot 199)
Standard GT-521F32 firmware assigns internal flash slots `0` through `199` for enrolled templates. Continuously writing and deleting templates across everyday enrollment cycles causes irreversible flash block degradation. 

LifeLink 2.0 solves this by implementing an in-memory / scratch-slot architecture:
1. **Scratch Slot Assignment:** Slot `199` is designated exclusively as the volatile working scratchpad.
2. **Execution Flow:**
   - 3-pass or single-impression enrollment executes strictly targeted to Slot `199`.
   - The newly generated 498-byte minutiae template is downloaded to the ESP32 RAM via command `GetTemplate(199)`.
   - The template is transmitted up to the Pi 5 over the framed serial connection.
   - Slot `199` is immediately erased using `DeleteID(199)`.
3. **Matching:** 1:1 verification and 1:N emergency identification are performed either by downloading probe minutiae and running fast minutiae comparison on Pi 5 or by loading templates into RAM buffer for sensor verification.

### 3.2 LifeLink Framed Binary Protocol (LLFP)
To ensure reliable, collision-free communication over USB serial across noisy clinical environments, all packets between Pi 5 and ESP32 are framed using the LLFP binary structure:

```
┌───────┬───────┬──────┬────────┬────────┬──────────────────────────┬────────┐
│ PRE1  │ PRE2  │ CMD  │ FLAGS  │ LEN    │ PAYLOAD                  │ CRC32  │
│ 0x55  │ 0xAA  │ 1 B  │ 1 Byte │ 2 B LE │ 0 to 1024 Bytes          │ 4 B LE │
└───────┴───────┴──────┴────────┴────────┴──────────────────────────┴────────┘
```

#### Field Specifications:
- `PRE1`, `PRE2` (`0x55`, `0xAA`): Constant synchronization preamble.
- `CMD` (1 Byte): Command identifier (e.g., `0x01` Echo, `0x10` LED Control, `0x20` Enroll Pass, `0x21` Get Template, `0x30` Identify, `0x40` Cancel).
- `FLAGS` (1 Byte): Bitmask flags (`0x01` ACK, `0x02` NACK, `0x04` Error, `0x08` Final Pass).
- `LEN` (2 Bytes, Little-Endian): Payload length $N$ ($0 \le N \le 1024$).
- `PAYLOAD` ($N$ Bytes): Variable command-specific arguments or raw minutiae bytes.
- `CRC32` (4 Bytes, Little-Endian): Standard IEEE 802.3 CRC32 computed over `CMD + FLAGS + LEN + PAYLOAD`.

---

## 4. Camera Substation & Shared-Session Architecture

### 4.1 Cooperative Shared Session & 3.0-Second Timed Window Acquisition
A major engineering challenge in embedded biometric kiosks is supporting **live aiming preview** while simultaneously permitting **instantaneous high-resolution capture** without crashing or re-initializing the camera sensor.

LifeLink 2.0 implements a non-destructive cooperative locking pattern coupled with a **continuous 3.0-second timed window acquisition loop (`SCAN_WINDOW_SECONDS = 3.0`)** on the Pi 3B+ `Picamera2` daemon:

```
[Touchscreen Kiosk UI]
       │
       ├─── 1. Start Live Preview ───► GET /api/v1/camera/stream?mode=iris
       │                                     │
       │                                     ▼
       │                        Picamera2 Streaming Loop @ ~12-15 FPS (BGR True Color)
       │                        Preview maintains non-inverting native BGR888 stream
       │
       ├─── 2. Capture Eye (OD/OS) ──► POST /api/v1/camera/iris/capture
       │                                     │
       │                                     ▼
       │                        Acquires _capture_lock (non-blocking)
       │                        Executes 3.0-Second Burst Window (Continuous Sampling)
       │                        Computes Laplacian Sharpness, Contrast & Glare per frame
       │                        Tracks and isolates the single highest-scoring BEST FRAME
       │                        Encodes best frame to JPEG with ISO/IEC quality metrics
       │                        Transmits best frame to Pi 5 for Template Extraction
       │                                     │
       │                                     ▼
       │                        [Pi 5 Template Extraction Gate]
       │                        Passes frame to Vis-IrisFormer Embedding Engine
       │                        ├─ Valid 512-D Embedding -> HTTP 200 {template_extracted: true}
       │                        │  (Stops scanning loop for this eye, advances UI)
       │                        └─ Extraction Failed -> HTTP 422 {template_extracted: false, status: "retry"}
       │                           (UI automatically triggers next 3s scan loop on Pi 3B+)
       │
       └─── 3. Stop Live Preview ────► POST /api/v1/camera/preview/stop
                                             │
                                             ▼
                                Sets _preview_stop_event (Clean IDLE state)
```

### 4.2 ISO/IEC 29794-6 Biometric Quality Screening & Best-Frame Scoring
During the 3.0-second scan window, every candidate iris frame is evaluated against ISO/IEC 29794-6 biometric standards to identify the optimal optical sample:

$$\text{Sharpness} = \text{Var}\left(\nabla^2 I_{\text{gray}}\right) \ge 50.0$$

$$\text{Mean Illumination} = \frac{1}{HW}\sum_{x,y} I(x,y) \in [35.0, 220.0]$$

$$\text{Corneal Glare Ratio} = \frac{\sum (I(x,y) \ge 245)}{HW} \times 100 \le 5.0\%$$

$$\text{Pupil-to-Iris Ratio} = \frac{r_{\text{pupil}}}{r_{\text{iris}}} \in [0.2, 0.7]$$

The frame scoring function synthesizes sharpness variance and illumination bounds to select the single best frame. If all sampled frames fail minimum thresholds or no eye is present, the camera substation returns `HTTP 422 Unprocessable Entity` containing actionable clinical diagnostics (`Image blurred`, `Improper illumination`, or `Corneal glare exceeds threshold`).

### 4.3 True-Color Camera Pipeline & Native BGR Stream Format
On Raspberry Pi OS (Debian 12 Bookworm) with `libcamera`, `Picamera2.capture_array()` outputs native BGR byte ordering.
- **Root Cause of Color Inversion:** Earlier revisions configured `format: "RGB888"` and executed `cv2.cvtColor(rgb_array, cv2.COLOR_RGB2BGR)`. This performed an unnecessary channel swap on an already BGR-aligned buffer, causing human skin to render as electric cyan/blue and reflections to render red/orange.
- **Architectural Fix:** Picamera2 main stream is explicitly configured with `format: "BGR888"` and Auto White Balance (`AwbEnable: True`). The redundant color conversion has been eliminated in `camera_client.py`. Live MJPEG streams and portrait captures now deliver natural, clinically accurate color balance.

### 4.4 ML Template Extraction Gate & Continuous Rescan Feedback
Pi 5 acts as the authoritative biometric gatekeeper:
1. When Pi 3B+ delivers the 3.0-second best frame, Pi 5's backend endpoint (`/api/v1/devices/camera/capture-iris` or `/capture-probe`) invokes `BiometricService._resolve_iris_embedding()`.
2. The image passes through `LightIrisNet` boundary segmentation, Daugman rubber-sheet polar unwrapping, and `Vis-IrisFormer` feature extraction.
3. If an embedding vector ($\mathbb{R}^{512}$) is computed successfully, Pi 5 responds with `HTTP 200` and `template_extracted: true`.
4. If segmentation or feature extraction fails (e.g. eye was closed, out of angle, or obscured), Pi 5 responds with `HTTP 422` and `template_extracted: false, status: "retry"`.
5. The kiosk frontend catches the 422 response and immediately requests a new 3.0-second scan from Pi 3B+, looping seamlessly until a clinically valid template is captured or the operator clicks "Cancel Scan".

---

## 5. Deep Learning Iris Recognition Pipeline

### 5.1 Architecture Overview
The iris biometric engine on the Raspberry Pi 5 runs locally using an optimized PyTorch / ONNX runtime pipeline:

```text
Raw NIR Iris Image (640x480)
            │
            ▼
┌──────────────────────────────────────────────┐
│ Stage 1: Segmentation (LightIrisNet)         │
│ Lightweight U-Net with MobileNetV3 backbone │
│ Predicts binary masks for pupil & iris bounds│
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ Stage 2: Normalization (Daugman Rubber-Sheet)│
│ Unrolls annular iris ring into fixed polar   │
│ rectangular coordinate tensor (64 x 512 x 1) │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ Stage 3: Feature Extraction (Vis-IrisFormer) │
│ Vision Transformer extracting fine phase and │
│ radial spatial vectors -> [128, 768] tensor  │
└──────────────────────┬───────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────┐
│ Stage 4: Matching & Thresholding             │
│ Cosine Similarity / Normalized Hamming Dist   │
│ Threshold: Cosine Sim >= 0.72 (Match Verified)│
└──────────────────────────────────────────────┘
```

### 5.2 Mathematical Normalization
The annular region between pupil boundary $(x_p(\theta), y_p(\theta))$ and limbic sclera boundary $(x_s(\theta), y_s(\theta))$ is transformed to polar coordinates $(r, \theta)$ where $r \in [0, 1]$ and $\theta \in [0, 2\pi]$:

$$x(r, \theta) = (1 - r) x_p(\theta) + r x_s(\theta)$$

$$y(r, \theta) = (1 - r) y_p(\theta) + r y_s(\theta)$$

This eliminates variations in pupil dilation, camera distance, and perspective distortion.

---

## 6. Security, RBAC & Cryptographic Data Boundary

### 6.1 Cryptographic Storage: AES-256-GCM
All biometric templates are secured at rest using authenticated symmetric encryption:
- **Algorithm:** AES-256-GCM (Galois/Counter Mode).
- **Key Derivation:** Master kiosk key derived using PBKDF2-HMAC-SHA256 (600,000 iterations) with hardware machine-id salting.
- **Nonce:** Unique 12-byte cryptographically secure random IV generated per template encryption.
- **Integrity Tag:** 16-byte authentication tag ensuring ciphertext cannot be tampered with.

```json
{
  "cipher": "aes-256-gcm",
  "iv_b64": "vj3x9K...==",
  "tag_b64": "8kLmN...==",
  "data_b64": "9pQxZ...=="
}
```

### 6.2 Role-Based Access Control (RBAC) Matrix

| Permission | Role: Clinician | Role: Registration Staff | Role: Records Admin | Role: System Admin |
|---|:---:|:---:|:---:|:---:|
| **Identify Patient (1:1 / 1:N)** | Yes | Yes | Yes | Yes |
| **View Emergency Medical Chart** | Yes | No | Yes | Yes |
| **Register New Patient** | No | Yes | Yes | Yes |
| **Update Clinical Details** | Yes | No | Yes | Yes |
| **Update Administrative Details**| No | Yes | Yes | Yes |
| **Submit Record Deletion Request**| No | No | Yes | Yes |
| **Approve Deletion (Dual Control)**| No | No | No | Yes |
| **Inspect System & Audit Logs** | No | No | Yes | Yes |
| **Configure Hardware & Drivers** | No | No | No | Yes |

---

## 7. Database Architecture & Complete Schema DDL

The local database consists of **13 interrelated relational tables** designed for high transactional consistency and strict auditability:

```sql
-- 1. Staff Accounts & RBAC
CREATE TABLE IF NOT EXISTS staff_accounts (
    id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    email TEXT UNIQUE NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('clinician', 'registration_staff', 'records_admin', 'system_admin')),
    password_hash TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 2. Patient Demographics Cache
CREATE TABLE IF NOT EXISTS patients_cache (
    id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    dob TEXT NOT NULL,
    gender TEXT NOT NULL,
    blood_type TEXT NOT NULL,
    phone TEXT,
    address TEXT,
    photo_url TEXT,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 3. Emergency Contacts
CREATE TABLE IF NOT EXISTS emergency_contacts (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients_cache(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    relationship TEXT NOT NULL,
    phone TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 4. Clinical & Medical Records
CREATE TABLE IF NOT EXISTS medical_records (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients_cache(id) ON DELETE CASCADE,
    allergies TEXT NOT NULL DEFAULT '[]', -- JSON string array
    chronic_conditions TEXT NOT NULL DEFAULT '[]', -- JSON string array
    medications TEXT NOT NULL DEFAULT '[]', -- JSON string array
    emergency_notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 5. Encrypted Fingerprint Templates
CREATE TABLE IF NOT EXISTS fingerprint_templates (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients_cache(id) ON DELETE CASCADE,
    finger_position TEXT NOT NULL, -- R1..R5, L1..L5
    encrypted_template BLOB NOT NULL,
    iv BLOB NOT NULL,
    auth_tag BLOB NOT NULL,
    created_at TEXT NOT NULL
);

-- 6. Encrypted Iris Templates
CREATE TABLE IF NOT EXISTS iris_templates (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients_cache(id) ON DELETE CASCADE,
    eye_side TEXT NOT NULL CHECK(eye_side IN ('OD', 'OS')),
    encrypted_template BLOB NOT NULL,
    iv BLOB NOT NULL,
    auth_tag BLOB NOT NULL,
    created_at TEXT NOT NULL
);

-- 7. Registration Drafts
CREATE TABLE IF NOT EXISTS registration_drafts (
    draft_id TEXT PRIMARY KEY,
    created_by TEXT NOT NULL REFERENCES staff_accounts(id),
    stage TEXT NOT NULL DEFAULT 'demographics',
    payload TEXT NOT NULL, -- JSON draft state
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 8. Peripheral Hardware Job Log
CREATE TABLE IF NOT EXISTS device_jobs (
    job_id TEXT PRIMARY KEY,
    job_type TEXT NOT NULL, -- fingerprint_enroll, iris_capture, camera_photo
    device_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending', -- pending, running, completed, failed, cancelled
    request_payload TEXT,
    result_payload TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 9. Clinical Record Revisions
CREATE TABLE IF NOT EXISTS record_revisions (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients_cache(id),
    field_name TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    revised_by TEXT NOT NULL REFERENCES staff_accounts(id),
    rationale TEXT NOT NULL,
    created_at TEXT NOT NULL
);

-- 10. Deletion Requests (Dual Control & Legal Hold)
CREATE TABLE IF NOT EXISTS deletion_requests (
    id TEXT PRIMARY KEY,
    patient_id TEXT NOT NULL REFERENCES patients_cache(id),
    requested_by TEXT NOT NULL REFERENCES staff_accounts(id),
    approved_by TEXT REFERENCES staff_accounts(id),
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'approved', 'rejected')),
    legal_hold INTEGER NOT NULL DEFAULT 0,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 11. Immutable Audit Events Log
CREATE TABLE IF NOT EXISTS audit_events (
    id TEXT PRIMARY KEY,
    actor_id TEXT NOT NULL,
    actor_username TEXT NOT NULL,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    details TEXT, -- JSON metadata
    timestamp TEXT NOT NULL
);

-- 12. Transactional Cloud Sync Outbox
CREATE TABLE IF NOT EXISTS sync_outbox (
    outbox_id TEXT PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    operation TEXT NOT NULL CHECK(operation IN ('INSERT', 'UPDATE', 'DELETE')),
    payload TEXT NOT NULL, -- Sanitized clinical JSON
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'in_flight', 'synced', 'failed')),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- 13. Sync Conflict Ledger
CREATE TABLE IF NOT EXISTS sync_conflicts (
    id TEXT PRIMARY KEY,
    outbox_id TEXT REFERENCES sync_outbox(outbox_id),
    server_version TEXT NOT NULL,
    local_version TEXT NOT NULL,
    resolved INTEGER NOT NULL DEFAULT 0,
    resolution TEXT,
    created_at TEXT NOT NULL
);
```

---

## 8. Transactional Outbox & Cloud Synchronization

```text
[Local Transaction]
        │
        ├────────────────────────┬────────────────────────┐
        ▼                        ▼                        ▼
INSERT INTO patients      INSERT INTO records      INSERT INTO sync_outbox
status = 'active'         status = 'active'        status = 'pending'
        │                        │                        │
        └────────────────────────┴────────────────────────┘
                                 │
                            [COMMIT DB]
                                 │
                                 ▼
                    [Async Sync Outbox Worker]
                                 │
                 Check Wired Hospital WAN Link
                                 │
                    ┌────────────┴────────────┐
                    ▼                         ▼
             Link Connected?           Link Severed?
                    │                         │
                    ▼                         ▼
         Upload Sanitized Payload      Sleep & Backoff
         (Zero Biometric Boundary)     (Deterministic
                    │                  Offline Operation)
                    ▼
          HTTP 200 OK Response
                    │
                    ▼
         UPDATE sync_outbox
         status = 'synced'
```

---

## 9. End-to-End Operational Workflows

### 9.1 Multi-Stage Patient Registration Workflow
1. **Operator Authentication:** Registrar logs in via `/api/v1/auth/login`. System assigns a signed JWT bearer token with `registration_staff` role.
2. **Step 1: Fingerprint Capture:**
   - Registrar selects finger slot (e.g. `R1` Right Thumb).
   - Sensor prompts finger placement; optical blue LED illuminates.
   - GT-521F32 executes 3-pass or single-impression scan into scratch slot `199`.
   - ESP32 streams minutiae over LLFP to Pi 5; template is encrypted via AES-256-GCM and staged in draft memory. Slot `199` is wiped.
3. **Step 2: Iris Capture (Continuous 3.0s Scan & Template Extraction Loop):**
   - Registrar clicks **Start Live Preview**. The Pi 3B+ initiates MJPEG video with green guidance reticles in natural BGR true color.
   - Registrar positions patient's right eye and clicks **Capture Right Eye (OD)**.
   - The kiosk enters an automated continuous scan loop:
     - Pi 3B+ evaluates frames continuously across a 3.0-second burst window, tracking Laplacian sharpness, contrast, and specular glare.
     - The single highest-quality frame is isolated and transmitted to Pi 5.
     - Pi 5 runs `Vis-IrisFormer` deep learning template extraction on the best frame.
     - **Template Extracted:** Pi 5 returns `HTTP 200` with `template_extracted: true`. The loop halts for that eye, the preview thumbnail updates with ISO metrics, and enrollment is confirmed.
     - **Extraction Failed:** Pi 5 returns `HTTP 422` with `template_extracted: false, status: "retry"`. The kiosk UI displays live attempt feedback and automatically signals Pi 3B+ to acquire the next 3.0-second window.
     - **Operator Cancellation:** The registrar can click **Cancel Scan** at any moment to abort the loop.
   - Registrar repeats the workflow for Left Eye (OS).
   - Registrar clicks **Stop Live Preview**.
4. **Step 3: Photograph Capture:**
   - Registrar starts photo preview (visible light portrait).
   - Clicks **Capture Photo**; visible portrait is acquired and saved.
5. **Step 4: Clinical & Emergency Data:**
   - Registrar inputs demographic details, blood type, known allergies, chronic conditions, and emergency next-of-kin contacts.
6. **Step 5: Review & Cryptographic Commit:**
   - System displays the holistic review summary.
   - Upon clicking **Complete Registration**, patient cache, medical records, emergency contacts, encrypted templates, and sync outbox records commit in a single atomic database transaction.

### 9.2 Emergency Biometric Identification (1:N)
1. **Trigger:** Paramedic or triage clinician enters **Emergency Patient Retrieval** screen.
2. **Execution Modes:**
   - **Fingerprint Retrieval:** Clinician clicks **Capture Fingerprint Probe**. Patient presses finger flat against optical prism. GT-521F32 captures single impression into scratch slot 199, downloads minutiae probe over LLFP to Pi 5, wipes scratch slot, and executes 1:N minutiae matching against all local encrypted templates.
   - **Iris Retrieval:** Clinician selects target eye (`OD` or `OS`) and clicks **Capture Iris Probe**.
     - Camera initiates continuous 3.0-second scan window on Pi 3B+ and transmits best frame to Pi 5.
     - Pi 5 executes `Vis-IrisFormer` template extraction. If template extraction fails, the system loops automatically across 3-second windows until a valid iris embedding is captured (or clinician clicks **Cancel Scan**).
     - Once probe embedding is acquired, Pi 5 decrypts enrolled candidate templates into memory and computes cosine similarity.
3. **Retrieval & Clinical Display:**
   - If similarity score meets or exceeds verification threshold ($\text{Cosine Sim} \ge 0.72$), an emergency match is declared.
   - Complete emergency medical chart (Blood Type, Critical Allergies, Next of Kin, Resuscitation Orders, Emergency Notes) renders on screen in under 1.2 seconds.
   - If no match is found, an immediate fallback lookup option is presented (Manual Identifier, Phone, or Trauma Admission).

---

## 10. RESTful API Complete Reference

### 10.1 Authentication Endpoints
- `POST /api/v1/auth/login`: Authenticates staff username/password. Returns JWT bearer token and user role.
- `GET /api/v1/auth/me`: Retrieves current authenticated staff profile and active permissions.
- `POST /api/v1/auth/logout`: Invalidates session token.

### 10.2 Peripheral Hardware Endpoints
- `GET /api/v1/devices/health`: Returns comprehensive operational status and health metrics for ESP32, GT-521F32, and Pi 3B+ camera daemon.
- `POST /api/v1/devices/fingerprint/enroll`: Starts multi-pass or single-pass fingerprint scan on specified finger slot (`R1`..`L5`).
- `POST /api/v1/devices/fingerprint/verify`: Performs 1:1 minutiae verification.
- `POST /api/v1/devices/fingerprint/capture-probe`: Captures single-impression minutiae template into scratch slot 199 for 1:N emergency identification.
- `POST /api/v1/devices/fingerprint/cancel`: Immediately aborts scan and extinguishes sensor optical LED.
- `GET /api/v1/devices/camera/stream?mode={iris|photo}`: Relays continuous MJPEG multipart frame stream from Pi 3B+ in native BGR true color.
- `POST /api/v1/devices/camera/capture-iris`: Executes continuous 3.0-second best frame scan, runs ML template extraction, returns `HTTP 200` with `template_extracted: true` or `HTTP 422` with `template_extracted: false, status: "retry"`.
- `POST /api/v1/devices/camera/capture-probe`: Captures probe iris image over 3.0s window with ML template validation for emergency retrieval.
- `POST /api/v1/devices/camera/capture-photo`: Captures portrait photo in native visible light.
- `POST /api/v1/devices/camera/stop-preview`: Terminates preview stream without aborting in-progress still captures.
- `POST /api/v1/devices/camera/cancel`: Cancels any active capture and forces clean IDLE state.

### 10.3 Biometric Identification Endpoints
- `POST /api/v1/biometrics/identify`: Performs 1:N candidate search against local database using decrypted candidate templates (supports `modality: "fingerprint"` or `"iris"`, threshold $\ge 0.72$).

### 10.4 Patient Records Endpoints
- `GET /api/v1/patients`: Lists active patient demographic records (supports pagination and name search).
- `GET /api/v1/patients/<id>`: Retrieves full patient profile including emergency contacts and clinical records.
- `POST /api/v1/patients`: Registers a complete new patient from staged registration wizard.
- `PUT /api/v1/patients/<id>`: Updates patient demographic or clinical details with audited rationale.
- `POST /api/v1/patients/<id>/records`: Appends new clinical consultation or encounter notes.

### 10.5 Administrative & Governance Endpoints
- `GET /api/v1/admin/staff`: Lists all staff accounts and assigned roles (SysAdmin only).
- `POST /api/v1/admin/staff`: Creates a new authorized staff credential.
- `GET /api/v1/admin/audit`: Queries immutable system audit trail with filtering by actor, action, and date.
- `POST /api/v1/admin/deletion-requests`: Submits a patient record deletion request with documented justification.
- `POST /api/v1/admin/deletion-requests/<id>/approve`: Secondary administrative authorization to execute deletion.

---

## 11. Frontend Touchscreen UI & Controller Architecture

### 11.1 Component Hierarchy
The kiosk frontend is constructed using standard ES6 JavaScript and responsive CSS optimized for capacitive glove touchscreens:
- **`app.js` (`LifeLinkApp`):** Central state machine and event router. Manages wizard step transitions, biometric polling, continuous scan retry loops (`isIrisLoopCancelled`, `isRetrievalIrisLoopCancelled`), error toasts, and auth lifecycle.
- **`api.js` (`ApiClient`):** Unified HTTP transport client. Injects JWT authentication headers, handles token expiration, and formats multi-part streaming responses.
- **`style.css`:** High-contrast clinical theme. Uses standard medical color coding (Critical Allergies in bright red, Normal status in green, Informational toasts in blue). Touch targets adhere to minimum $48\times 48$ px dimensions.

### 11.2 Biometric Scanning UI Controls
- **Live Guidance Reticles:** Overlay canvas rendering 240px elliptical target zone, iris bounding circle, and pupil guide ring for rapid subject alignment.
- **Attempt Status Feedback:** Real-time badge (`#iris-scan-feedback` and `#retrieval-iris-feedback`) showing continuous 3-second sampling attempts (`Attempt #N: Scanning best frame over 3s & extracting template...`).
- **Operator Abort Controls:** Red **"Cancel Scan"** buttons (`#btn-cancel-iris-scan` and `#btn-cancel-retrieval-iris-scan`) allowing clinical staff to immediately disengage the hardware loop if a patient moves or is uncooperative.

---

## 12. Full Deployment, Runbooks & Diagnostic Procedures

### 12.1 Deploying to Raspberry Pi 5
1. **Unpack Deployment Package:**
   ```bash
   unzip -o LifeLink_2.0_Deployment.zip -d /tmp/lifelink_update
   ```
2. **Install Core Files to Production Root (`/opt/lifelink`):**
   ```bash
   sudo cp -r /tmp/lifelink_update/pi5/* /opt/lifelink/
   ```
3. **Configure NetworkManager Static Link for Camera Substation:**
   ```bash
   sudo nmcli con add type ethernet con-name "lifelink-camera-link" ifname eth0 \
       ip4 192.168.50.1/24 ipv4.method manual
   sudo nmcli con up "lifelink-camera-link"
   ```
4. **Register & Start Systemd Services:**
   ```bash
   sudo cp /opt/lifelink/systemd/lifelink-backend.service /etc/systemd/system/
   sudo cp /opt/lifelink/systemd/lifelink-kiosk.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now lifelink-backend
   sudo systemctl enable --now lifelink-kiosk
   ```

### 12.2 Deploying to Raspberry Pi 3B+ (Camera Substation)
1. **Transfer Substation Package:**
   ```bash
   scp -r /tmp/lifelink_update/pi3b/* pi@192.168.50.2:/tmp/pi3b/
   ```
2. **Execute Automated Substation Setup on Pi 3B+:**
   ```bash
   ssh pi@192.168.50.2 "cd /tmp/pi3b && sudo bash install.sh && sudo reboot"
   ```
3. **Verify Camera Service:**
   ```bash
   curl -s http://192.168.50.2:5000/api/v1/camera/status
   ```
   *Expected Response:* `{"camera_state":"IDLE","connected":true,"status":"READY"}`

### 12.3 Diagnostic Troubleshooting Matrix

| Problem | Root Cause | Exact Resolution Command |
|---|---|---|
| **`HTTP 409: Camera device is busy`** | Abandoned job left in SQLite `device_jobs` | `sudo sqlite3 /opt/lifelink/lifelink_local.db "UPDATE device_jobs SET status = 'failed' WHERE status IN ('pending', 'running');"` |
| **`Ping 192.168.50.2 unreachable`** | Pi 5 `eth0` IP not configured or cable unlinked | `sudo nmcli con up "lifelink-camera-link"`<br>`cat /sys/class/net/eth0/carrier` (must be `1`) |
| **`ESP32 Not Found /dev/ttyUSB0`** | Missing udev rule or user not in `dialout` | `sudo usermod -a -G dialout $USER`<br>`ls -l /dev/serial/by-id/` |
| **IR LED Stays On** | Software crash prior to GPIO cleanup | `sudo pinctrl set 18 op dl` *(forces GPIO18 LOW immediately)* |
| **`rpicam-hello: no cameras available`** | CSI ribbon loose or inverted | Verify ribbon contact pins face HDMI port on Pi 3B+ board. |

