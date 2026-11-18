# LifeLink 2.0 — Requirements Traceability Matrix (RTM)

**Document:** `docs/requirements-traceability.md`  
**Author:** Lead Development Engineer, LifeLink 2.0  
**Date:** 2026-10-13  
**Status:** Baseline Active  

---

| Req ID | Requirement Description | Plan Ref | Module / File | Target API / Contract | Test Coverage | Status |
|---|---|---|---|---|---|---|
| **REQ-AUTH-01** | Clinical Login portal for medical personnel | Sec 5 | `backend/auth/` | `POST /api/v1/auth/login` | `tests/unit/test_auth.py` | Implementation Ready |
| **REQ-AUTH-02** | Hospital Login portal for records staff | Sec 5 | `backend/auth/` | `POST /api/v1/auth/login` | `tests/unit/test_auth.py` | Implementation Ready |
| **REQ-AUTH-03** | Admin Login portal for records & system admins | Sec 5 | `backend/auth/` | `POST /api/v1/auth/login` | `tests/unit/test_auth.py` | Implementation Ready |
| **REQ-AUTH-04** | Individual staff accounts with secure password hashing | Sec 5 | `backend/auth/` | `POST /api/v1/auth/login` | `tests/unit/test_auth.py` | Implementation Ready |
| **REQ-AUTH-05** | Server-side role-based access control (RBAC) & field scoping | Sec 5 | `backend/auth/rbac.py` | Context middleware | `tests/security/test_rbac.py` | Implementation Ready |
| **REQ-AUTH-06** | Secure offline authentication via local credential cache | Sec 5 | `backend/auth/offline.py`| Offline verifier | `tests/unit/test_auth.py` | Implementation Ready |
| **REQ-REG-01** | Guided 10-finger enrollment (R1–R5, L1–L5) with 3 impressions | Sec 7.1 | `fingerprint-device/` | `POST /api/v1/biometrics/fingerprint/enroll-jobs` | `tests/unit/test_fingerprint.py` | Implementation Ready |
| **REQ-REG-02** | Fingerprint exception handling (injury, missing digit) | Sec 7.1 | `frontend/registration/`| `PATCH /api/v1/patients/registration-drafts/{id}` | `tests/e2e/test_registration.py` | Implementation Ready |
| **REQ-REG-03** | Guided OD (right) and OS (left) iris capture | Sec 7.2 | `iris-module/` | `POST /api/v1/biometrics/iris/capture-jobs` | `tests/unit/test_iris.py` | Implementation Ready |
| **REQ-REG-04** | Iris capture exception handling (unscannable eye, injury) | Sec 7.2 | `frontend/registration/`| `PATCH /api/v1/patients/registration-drafts/{id}` | `tests/e2e/test_registration.py` | Implementation Ready |
| **REQ-REG-05** | Patient face photo capture from wired camera | Sec 7.2 | `iris-module/camera-client/` | `POST /api/v1/camera/photo/capture` | `tests/unit/test_camera.py` | Implementation Ready |
| **REQ-REG-06** | Patient data capture: Basic, Emergency, Medical, Clinical | Sec 7.3 | `backend/patients/` | `POST /api/v1/patients/registration-drafts` | `tests/unit/test_patient.py` | Implementation Ready |
| **REQ-REG-07** | Duplicate candidate check prior to final commit | Sec 7.4 | `backend/biometrics/` | `POST /api/v1/patients/duplicate-check` | `tests/unit/test_biometrics.py` | Implementation Ready |
| **REQ-REG-08** | Atomic transactional commit in local PostgreSQL | Sec 7.4 | `backend/database/` | `POST /api/v1/patients/registration-drafts/{id}/commit` | `tests/integration/test_db.py` | Implementation Ready |
| **REQ-REG-09** | Human-friendly LifeLink ID & UUID generation | Sec 7.4 | `backend/patients/` | Auto-generated ID (`LL-YYYY-XXXXX`) | `tests/unit/test_patient.py` | Implementation Ready |
| **REQ-RET-01** | Biometric 1:N candidate identification search | Sec 8 | `backend/biometrics/` | `POST /api/v1/identify` | `tests/unit/test_biometrics.py` | Implementation Ready |
| **REQ-RET-02** | Candidate 1:1 confirmation check | Sec 8 | `backend/biometrics/` | `POST /api/v1/verify` | `tests/unit/test_biometrics.py` | Implementation Ready |
| **REQ-RET-03** | Priority emergency dashboard (allergies, meds, freshness) | Sec 8 | `frontend/retrieval/` | `GET /api/v1/patients/{id}/emergency-summary` | `tests/e2e/test_retrieval.py` | Implementation Ready |
| **REQ-RET-04** | Fallback manual search & temporary unidentified patient | Sec 8 | `backend/patients/` | `POST /api/v1/patients/unidentified` | `tests/e2e/test_retrieval.py` | Implementation Ready |
| **REQ-UPD-01** | Identity confirmation before record modification | Sec 9 | `backend/patients/` | `POST /api/v1/patients/{id}/verify-for-update` | `tests/unit/test_patient.py` | Implementation Ready |
| **REQ-UPD-02** | Field-level update permissions based on role | Sec 9 | `backend/auth/rbac.py` | `PATCH /api/v1/patients/{id}` | `tests/security/test_rbac.py` | Implementation Ready |
| **REQ-UPD-03** | Change preview diff and mandatory reason for edit | Sec 9 | `frontend/update/` | `PATCH /api/v1/patients/{id}` | `tests/e2e/test_update.py` | Implementation Ready |
| **REQ-UPD-04** | Record versioning and tamper-evident audit logging | Sec 9 | `backend/audit/` | Table `record_revisions` & `audit_events` | `tests/unit/test_audit.py` | Implementation Ready |
| **REQ-ADM-01** | Admin dashboard home KPI widgets | Sec 10.1 | `backend/admin/` | `GET /api/v1/admin/overview` | `tests/unit/test_admin.py` | Implementation Ready |
| **REQ-ADM-02** | Patient search, metadata view (no raw templates) | Sec 10.2 | `backend/admin/` | `GET /api/v1/admin/patients` | `tests/unit/test_admin.py` | Implementation Ready |
| **REQ-ADM-03** | Admin patient edit with reason and versioning | Sec 10.2 | `backend/admin/` | `PATCH /api/v1/admin/patients/{id}` | `tests/unit/test_admin.py` | Implementation Ready |
| **REQ-ADM-04** | Patient archive / deactivate flow | Sec 10.2 | `backend/admin/` | `POST /api/v1/admin/patients/{id}/archive` | `tests/unit/test_admin.py` | Implementation Ready |
| **REQ-ADM-05** | Deletion request workflow with retention & 2-person approval | Sec 10.3 | `backend/admin/` | `POST /api/v1/admin/patients/{id}/deletion-requests` | `tests/unit/test_admin.py` | Implementation Ready |
| **REQ-ADM-06** | Staff account and role administration | Sec 10.4 | `backend/admin/` | `GET/POST /api/v1/admin/staff` | `tests/unit/test_admin.py` | Implementation Ready |
| **REQ-ADM-07** | Hardware device readiness diagnostics | Sec 10.4 | `backend/devices/` | `GET /api/v1/devices/health` | `tests/unit/test_devices.py` | Implementation Ready |
| **REQ-ADM-08** | Sync monitor and conflict resolution interface | Sec 10.4 | `backend/sync/` | `GET /api/v1/admin/sync` | `tests/unit/test_sync.py` | Implementation Ready |
| **REQ-ADM-09** | Audit log explorer | Sec 10.4 | `backend/admin/` | `GET /api/v1/admin/audit` | `tests/unit/test_audit.py` | Implementation Ready |
| **REQ-HW-01** | 100% wired GT-521F32 $\leftrightarrow$ ESP32 UART link | Sec 3 | `fingerprint-device/esp32/` | Firmware serial driver | `tests/hardware/test_esp32.py` | Implementation Ready |
| **REQ-HW-02** | Framed USB serial ESP32 $\leftrightarrow$ Pi 5 with single host owner | Sec 12.1 | `fingerprint-device/host/` | Framed protocol with CRC32 | `tests/unit/test_fingerprint.py` | Implementation Ready |
| **REQ-HW-03** | 100% wired Pi Zero W $\leftrightarrow$ Pi 5 USB gadget Ethernet link | Sec 3 | `iris-module/camera-client/`| `192.168.55.0/24` HTTP | `tests/hardware/test_pizero.py` | Implementation Ready |
| **REQ-HW-04** | Zero runtime Wi-Fi / Bluetooth requirement | Sec 3 | `deploy/` | Network isolation configuration | `tests/security/test_network.py` | Implementation Ready |
| **REQ-DB-01** | Offline primary PostgreSQL persistence on Pi 5 | Sec 11 | `database/local/` | Local schema & migrations | `tests/integration/test_db.py` | Implementation Ready |
| **REQ-DB-02** | Encrypted biometric storage (pgcrypto / AES-256) | Sec 11 | `backend/biometrics/` | Encrypted columns | `tests/security/test_crypto.py` | Implementation Ready |
| **REQ-DB-03** | Durable transactional outbox for Supabase synchronization | Sec 11.3 | `sync/` | Table `sync_outbox` & worker | `tests/unit/test_sync.py` | Implementation Ready |
| **REQ-DB-04** | Concurrency versioning & conflict resolution | Sec 11.3 | `sync/` | `sync_conflicts` table | `tests/unit/test_sync.py` | Implementation Ready |
| **REQ-SEC-01** | No sensitive secrets or service keys in client JS | Sec 5, 9 | `frontend/` | Kiosk frontend architecture | `tests/security/test_secrets.py` | Implementation Ready |
| **REQ-SEC-02** | Scratch slot zeroization on GT-521F32 sensor | Sec 7.1 | `fingerprint-device/` | `DeleteID(199)` command | `tests/unit/test_fingerprint.py` | Implementation Ready |
| **REQ-TEST-01** | Deterministic `MOCK_MODE=true` for 100% testable execution | Sec 12 | `backend/devices/mock/` | Simulated devices & biometrics | All unit & integration tests | Implementation Ready |
