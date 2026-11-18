# LifeLink 2.0 — Project Inventory & Subsystem Architecture

**System Version:** LifeLink 2.0 (Emergency Medical Identity & Patient Information Platform)  
**Target Environment:** Raspberry Pi 5 Touchscreen Kiosk Terminal (Debian 12 Bookworm, ARM64)  
**Host Development Verification Date:** October 14, 2026  
**Auditor:** Principal Software Quality Assurance & Systems Integration Specialist  

---

## 1. Executive Summary

LifeLink 2.0 is a mission-critical, offline-first emergency medical identification and triage platform engineered for emergency department resuscitation bays and clinical intake terminals. The platform interfaces with dedicated hardware peripherals across isolated physical buses (USB serial and USB Gadget Ethernet) with zero runtime wireless dependencies, enforces AES-256 encrypted biometric template boundaries, and synchronizes clinical audit events to Supabase cloud using a transactional outbox pattern.

This inventory documents all source directories, executable firmware, drivers, backend controllers, frontend presentation components, database migrations, and verification test suites.

---

## 2. Directory Tree & Component Categorization

```
LifeLink-gui/
├── AGENTS.md                          # Workspace invariants, zero-wireless, offline-first rules
├── README.md                          # System runbook, CLI commands, hardware wiring map
├── pytest.ini                         # Pytest configuration and test path definitions
├── .env.example                       # Environment template with explicit MOCK_MODE toggles
├── backend/                           # Core Flask Application & Microservices
│   ├── app.py                         # Application factory, blueprint registration, error handlers
│   ├── config.py                      # Hierarchical configuration (SQLite/PostgreSQL, Crypto, Ports)
│   ├── admin/                         # Administrative Dashboard Services
│   │   └── routes.py                  # KPI aggregates, deletion machine, audit log explorer, staff admin
│   ├── audit/                         # Tamper-evident Audit Logging Service
│   │   └── service.py                 # SHA-256 hash-chained audit ledger logger
│   ├── auth/                          # Security, Session Management & RBAC
│   │   ├── routes.py                  # PIN/password login routes for 3 discrete portals
│   │   ├── security.py                # PBKDF2 password hasher & HMAC-SHA256 JWT tokens
│   │   └── rbac.py                    # Granular role decorators, portal scoping, error reporting
│   ├── biometrics/                    # Biometric Pipeline & Matching Engine
│   │   ├── routes.py                  # 1:N candidate search & 1:1 confirmation API
│   │   └── service.py                 # Cross-modal fusion, threshold calibration, cosine matching
│   ├── database/                      # Data Access Layer & Cryptographic Utilities
│   │   ├── connection.py              # Thread-safe SQLite & PostgreSQL connection pool
│   │   ├── crypto.py                  # Fernet/AES-256 biometric encryption at rest
│   │   └── schema.py                  # Complete DDL tables, indexes, and transactional outbox
│   ├── devices/                       # Peripheral Hardware Orchestration
│   │   ├── camera_host.py             # Wired HTTP host client for Pi Zero W camera daemon
│   │   ├── fingerprint_host.py        # USB serial host driver for ESP32 + GT-521F32 sensor
│   │   ├── manager.py                 # Singleton device job coordinator & mode switcher
│   │   ├── routes.py                  # Peripheral endpoints: capture, enrollment, cancellation
│   │   └── mock/                      # Level A Synthetic Simulators
│   │       ├── mock_camera.py         # Synthetic eye generator, blur/glare injection, ISO quality
│   │       └── mock_fingerprint.py    # GT-521F32 template synthesizer & 3-stage enrollment mock
│   └── patients/                      # Clinical Patient Workflows
│       └── routes.py                  # Workflows A (Registration), B (Retrieval), C (Revision update)
├── frontend/                          # Touchscreen Kiosk User Interface
│   ├── index.html                     # Single-page terminal shell with modal viewport
│   ├── css/
│   │   ├── design-tokens.css          # High-contrast clinical monochrome grayscale variables
│   │   ├── layout.css                 # 1024x600 kiosk grid, 48px min touch targets
│   │   └── components.css             # Step wizards, biometric cards, modal overlays, emergency banners
│   └── js/
│       ├── api.js                     # Centralized API fetch wrapper with auto-auth headers
│       ├── state.js                   # Reactive reactive client state container
│       ├── components/                # Modular UI controllers
│       │   ├── topbar.js              # System clock, portal badge, device connectivity indicators
│       │   ├── nav.js                 # Workstation tab navigator
│       │   ├── modal.js               # Biometric guided capture and confirmation modals
│       │   └── notifications.js       # Toast notifications and clinical critical alerts
│       └── views/                     # Screen presentation controllers
│           ├── login.js               # Dual-mode PIN / password login with keypad
│           ├── workspace.js           # Emergency triage search, live vitals, clinical actions
│           ├── registration.js        # 5-step guided enrollment wizard
│           ├── retrieval.js           # Biometric matching results, prioritized emergency summary
│           └── admin.js               # Administrative KPI dashboard, audit log table, user management
├── fingerprint-device/                # ESP32 + GT-521F32 Firmware & Serial Protocol
│   ├── firmware/                      # MicroPython ESP32 firmware
│   │   ├── main.py                    # Non-blocking USB serial event loop, LLFP parser
│   │   └── gt521f32.py                # Low-level UART2 binary driver for GT-521F32 sensor
│   └── protocol/                      # Wire Framing Specification
│       └── framing.py                 # LLFP binary packet framing, CRC32 checksums, command enums
├── iris-module/                       # Raspberry Pi Zero W Camera Daemon & Pi 5 Model Inference
│   ├── camera-client/                 # Pi Zero W Picamera2 Daemon
│   │   ├── camera_service.py          # Flask HTTP service on port 5001 (Ethernet Gadget)
│   │   ├── ir_led_controller.py       # Thread-safe GPIO18 850nm IR LED driver with safety watchdog
│   │   ├── iris_capture.py            # Synchronized capture coordinator & ISO/IEC 29794-6 filter
│   │   ├── photo_capture.py           # Patient face portrait acquisition
│   │   ├── quality_filter.py          # Laplacian sharpness, specular glare ratio, exposure checks
│   │   └── camera_client.py           # Abstract client wrapper
│   └── recognition/                   # Pi 5 Biometric Deep Learning Pipelines
│       ├── models/                    # Model architecture definitions
│       │   ├── light_iris_net.py      # MobileNetV3-based lightweight iris feature extractor
│       │   └── vis_iris_former.py     # Vision Transformer embedding backbone for unconstrained iris
│       ├── pipeline.py                # Normalization, Daugman rubber-sheet unwrapping, segmentation
│       └── matcher.py                 # Cosine distance embedding comparator & calibrated thresholding
├── database/                          # Migration Scripts & Cloud Integration
│   ├── migrations/                    # Schema migrations for local SQLite / PostgreSQL
│   └── supabase/                      # Cloud Supabase schema, RLS policies, and sync triggers
├── sync/                              # Cloud Synchronization Daemon
│   └── sync_worker.py                 # Transactional outbox polling daemon with exponential backoff
├── scripts/                           # Engineering Operations & Automation
│   ├── bootstrap.py                   # Dependency resolution, virtualenv check, weight validation
│   ├── run_mock.py                    # Complete application launcher in MOCK_MODE=true on port 5000
│   └── seed_demo.py                   # Synthetic patient and clinician staff data seeder
├── tests/                             # Comprehensive Automated Test Suites
│   ├── unit/
│   │   ├── test_foundation.py         # App factory, database connectivity, template encryption
│   │   ├── test_framing.py            # LLFP serial packet framing and CRC32 corruption detection
│   │   ├── test_devices.py            # Peripheral device health, enrollment, and cancellation
│   │   ├── test_patient.py            # Patient registration, draft commits, and revisions
│   │   ├── test_iris_engine.py        # Iris normalization, unwrapping, and feature extraction
│   │   ├── test_ir_led.py             # IR LED synchronization, safety watchdog, thread safety
│   │   ├── test_camera_lifecycle.py   # Synchronized camera state transitions and API endpoints
│   │   ├── test_hardware_clients.py   # Wired CameraHostClient and FingerprintHostClient integration
│   │   ├── test_security_audit.py     # Tampered JWT, RBAC boundaries, SQLi immunity, rest encryption
│   │   ├── test_failure_injection.py  # Peripheral disconnect, blur/glare rejection, collision locks
│   │   ├── test_e2e_scenarios.py      # Full operational scenarios E2E-01 through E2E-14
│   │   └── test_sync.py               # Transactional outbox sync worker verification
└── docs/                              # System Architecture, Wiring Maps, Protocols, Verification
    ├── architecture.md
    ├── wiring.md
    ├── hardware-bom.md
    ├── pi-zero-usb-gadget.md
    ├── requirements-traceability.md
    ├── iris-repository-integration.md
    ├── source-audit.md
    └── third-party-audit.md
```

---

## 3. Subsystem Line-of-Code & File Inventory Metrics

| Subsystem | Primary Languages | File Count | Core Role |
| :--- | :--- | :--- | :--- |
| **Backend Core** | Python | 14 files | Business logic, authentication, RBAC, REST APIs, job orchestrator |
| **Frontend UI** | HTML5, Vanilla CSS, ES6 | 13 files | Monochrome clinical touchscreen interface, modal controllers |
| **Fingerprint Subsystem** | MicroPython, Python | 5 files | GT-521F32 UART driver, ESP32 USB serial framed binary protocol |
| **Iris Camera Daemon** | Python (Picamera2) | 7 files | Pi Zero W daemon, GPIO18 IR LED synchronization, quality filter |
| **Iris Recognition Engine**| Python (PyTorch/CV2) | 4 files | Daugman unwrapping, LightIrisNet, Vis-IrisFormer, cosine matcher |
| **Database & Sync** | Python, SQL | 4 files | Local connection pool, crypto engine, transactional outbox worker |
| **Scripts & Tooling** | Python | 3 files | Bootstrap environment setup, mock launcher, synthetic seeder |
| **Verification & Tests** | Python (pytest) | 12 files | 77 automated test cases spanning unit, security, fault injection, E2E |
| **Documentation** | Markdown | 20 files | Architecture, BOM, wiring, test plans, formal audit reports |

**Total Production & Verification Files:** 82 source artifacts.
