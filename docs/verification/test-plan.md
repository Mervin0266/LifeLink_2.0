# LifeLink 2.0 — Quality Assurance & Test Strategy Plan

**System:** LifeLink 2.0 Emergency Medical Identity Platform  
**Specification Reference:** Antigravity Master Verification & Testing Mandate  
**Test Harness:** Python 3.13 / pytest 9.1 / Flask TestClient / Requests Mocking  

---

## 1. Multi-Level Testing Methodology

To satisfy medical software reliability standards (IEC 62304 / ISO 13485 alignment) and embedded hardware verification invariants, LifeLink 2.0 employs a strict 3-tier testing hierarchy:

```
+-------------------------------------------------------------------------+
| LEVEL C: Physical Target Bench Test (Embedded Deployment Gate)          |
| - Raspberry Pi 5 + Waveshare 7" Touchscreen (Debian 12 Bookworm, ARM64) |
| - Physical ESP32 via USB-UART bridge + GT-521F32 optical sensor         |
| - Pi Zero W via USB Gadget Ethernet (192.168.55.2) + IMX708 NoIR        |
| - Physical 850 nm IR LED on GPIO18 with photodiode / oscilloscope probe |
+-------------------------------------------------------------------------+
                                    ▲
+-------------------------------------------------------------------------+
| LEVEL B: Host Hardware Client & Protocol Contract Tests                 |
| - CameraHostClient (HTTP Gadget client over 192.168.55.2:5001)          |
| - FingerprintHostClient (pyserial host driver with LLFP binary framing) |
| - DeviceManager dynamic switching (MOCK_MODE=false vs MOCK_MODE=true)   |
| - Serial framing CRC32 error detection and packet corruption resilience |
+-------------------------------------------------------------------------+
                                    ▲
+-------------------------------------------------------------------------+
| LEVEL A: Unit, Security, Failure Injection, and Automated E2E           |
| - Pure software mocks (MockFingerprintDevice, MockCameraDevice)         |
| - Cryptographic template encryption at rest (Fernet/AES-256)            |
| - RBAC role-scoping, JWT forgery prevention, SQL injection immunity     |
| - Fault injection: disconnects, blur/glare rejections, 409 collisions   |
+-------------------------------------------------------------------------+
```

---

## 2. Test Category Breakdown

### Category 1: System Foundation & Cryptography (`tests/unit/test_foundation.py`)
- App factory initialization, CORS, and blueprint registration.
- PBKDF2-HMAC-SHA256 password hashing (200,000 iterations).
- AES-256 template encryption and decryption verification.
- Local SQLite / PostgreSQL database connection health.
- Static touchscreen frontend asset serving.

### Category 2: Binary Serial Protocol & Framing (`tests/unit/test_framing.py`)
- `LLFP` binary packet packing: 28-byte header (`MAGIC`, version, kind, request UUID, command, status, length).
- CRC32 checksum calculation and verification.
- Detection and graceful handling of corrupted checksums, truncated frames, and invalid magic headers.

### Category 3: Peripheral Hardware Clients (`tests/unit/test_hardware_clients.py`)
- `CameraHostClient`: Disconnected endpoint handling, status interrogation, timeout fallback, connected state reporting.
- `FingerprintHostClient`: Serial port auto-discovery, disconnected handling, operation rejection when unattached.
- `DeviceManager`: Clean mode switching between synthetic mock drivers (`MOCK_MODE=true`) and hardware clients (`MOCK_MODE=false`).

### Category 4: Camera & IR LED Lifecycle (`tests/unit/test_camera_lifecycle.py`, `tests/unit/test_ir_led.py`)
- State machine synchronization: IR LED activates strictly upon scan start (`SCANNING`) and deactivates upon completion (`IDLE`).
- Immediate LED deactivation upon operator cancellation and unhandled exceptions.
- Hardware fail-safe watchdog timer: automatic shutoff if on-time exceeds configured threshold (default 15s).
- Isolation: Patient photo capture keeps IR LED strictly OFF.
- Thread-safety of IR LED controller under concurrent invocation.

### Category 5: Biometric Pipeline & Feature Processing (`tests/unit/test_iris_engine.py`)
- Daugman rubber-sheet normalization to standard 512x64 rectangular polar unwrapping.
- Feature extraction using simulated LightIrisNet / Vis-IrisFormer backbones.
- Cosine distance matching with calibrated thresholding.

### Category 6: Clinical Workflows (`tests/unit/test_patient.py`)
- Multi-step registration draft persistence, duplicate check, and atomic commit transaction.
- Scoped medical updates with mandatory clinical rationale.

### Category 7: Security Audit & Defensive Hardening (`tests/unit/test_security_audit.py`)
- Forged, modified, and tampered JWT tokens rejected with 401 Unauthorized.
- Unauthenticated requests rejected.
- RBAC role privilege escalation: Registration staff blocked from admin overview and clinical updates (403 Forbidden).
- Parameterized query validation against SQL injection attack vectors.
- Encryption of biometric templates at rest.

### Category 8: Failure Injection & Fault Tolerance (`tests/unit/test_failure_injection.py`)
- Camera disconnect midway through iris acquisition.
- Blurred frame rejection (Laplacian variance < 50.0).
- Specular corneal glare rejection (saturated pixel ratio > 5.0%).
- IR LED safety watchdog timeout verification.
- Concurrent scan collision prevention (HTTP 409 Conflict).
- Cancellation scratch slot wipe verification.
- Serial corruption resilience.

### Category 9: End-to-End Operational Scenarios (`tests/unit/test_e2e_scenarios.py`)
- Systematic automation of all 14 mandatory operational scenarios (`E2E-01` through `E2E-14`).

### Category 10: Cloud Outbox Synchronization (`tests/unit/test_sync.py`)
- Transactional outbox polling, cloud mock dispatch, conflict handling, and retry backoff.
