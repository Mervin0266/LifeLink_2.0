# LifeLink 2.0 — Agent Rules and Workspace Invariants

## 1. Project Invariants
- **Version:** LifeLink 2.0 (Emergency Medical Identity & Patient Information Platform).
- **Target Target:** Raspberry Pi 5 touchscreen kiosk terminal (Debian Bookworm, ARM64).
- **Zero Runtime Wireless:** ESP32 communicates exclusively via USB serial; Raspberry Pi 3B+ camera communicates exclusively via dedicated wired Ethernet (`192.168.50.0/24`) (with legacy USB gadget Ethernet `192.168.55.0/24` supported for Pi Zero W). Zero Wi-Fi/Bluetooth dependencies for hardware links.
- **Offline First:** All core patient registration, retrieval, update, and admin functions operate against local PostgreSQL when offline.
- **Biometric Data Boundary:** Biometric templates (fingerprint and iris) and raw iris images are encrypted locally and NEVER uploaded to Supabase Cloud by default.
- **Honest Engineering:** Use explicit `MOCK_MODE=true` when physical hardware or model weights are missing. Never claim biometric accuracy, hardware verification, or clinical readiness without empirical test evidence.

## 2. Directory Map
- `frontend/`: Touchscreen kiosk UI (HTML5, Vanilla CSS clinical themes, ES6 controllers).
- `backend/`: Python Flask core application, auth, RBAC, patient APIs, admin APIs, device services.
- `fingerprint-device/`: ESP32 MicroPython firmware, GT-521F32 UART driver, Pi 5 framed USB serial host worker.
- `iris-module/`: Raspberry Pi 3B+ (and legacy Pi Zero W) Picamera2 capture daemon + quality filter; Pi 5 LightIrisNet + Vis-IrisFormer inference engine.
- `database/`: Local PostgreSQL migrations + Supabase cloud migrations and RLS policies.
- `sync/`: Transactional outbox sync worker for cloud reconciliation.
- `scripts/`: Bootstrap, seed demo data, run mock mode, backup, and test commands.
- `tests/`: Unit, contract, integration, security, and E2E test suites.
- `docs/`: System documentation, architecture, ADRs, protocols, and runbooks.

## 3. Core CLI Commands
- `python scripts/bootstrap.py`: Check dependencies, setup virtualenv, and verify models.
- `python scripts/run_mock.py`: Launch complete stack in `MOCK_MODE=true` on port 5000.
- `python scripts/seed_demo.py`: Populate local database with synthetic test patients and staff accounts.
- `pytest tests/`: Run the test suite.

## 4. Safety & PII Rules
- Never commit real patient names, identifiers, or biometric samples. Use synthetic test vectors only.
- Never place Supabase service role keys or database master passwords in client-side code.
- Deletion requests require documented rationale, legal-hold validation, and secondary administrative approval. No unapproved hard-delete endpoints.
