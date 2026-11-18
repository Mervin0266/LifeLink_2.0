# LifeLink 2.0 — Requirements Traceability Matrix (RTM)

**System Version:** LifeLink 2.0  
**Verification Level:** Level A (Host & Synthetic Emulation) + Level B (Driver Integration Contracts)  
**Status:** 100% Traceable / All Verification Criteria Covered  

---

## 1. System Invariants Traceability

| Invariant ID | Requirement Specification | Implementation Location | Test Verification Reference | Status |
| :--- | :--- | :--- | :--- | :--- |
| **INV-01** | **Strict Version Naming:** System must be strictly identified as "LifeLink 2.0". No regression to 1.0 or unapproved 3.0 references. | `frontend/index.html`, `backend/app.py`, `backend/config.py`, `AGENTS.md` | `test_frontend_serving`, `test_health_endpoint` | **VERIFIED** |
| **INV-02** | **Zero Runtime Wireless:** Pi 5 to ESP32 must operate exclusively over USB Serial. Pi 5 to Pi Zero W camera must operate exclusively over USB Gadget Ethernet (`192.168.55.0/24`). Zero Wi-Fi/Bluetooth dependencies for hardware links. | `backend/devices/camera_host.py`, `backend/devices/fingerprint_host.py`, `iris-module/camera-client/config.py` | `test_e2e_14_full_platform_regression_integrity`, `test_hardware_clients.py` | **VERIFIED** |
| **INV-03** | **Offline-First Resilience:** All patient registrations, biometric identification, emergency views, and updates operate against local SQLite / PostgreSQL with zero cloud reliance. | `backend/database/connection.py`, `backend/patients/routes.py`, `backend/biometrics/service.py` | `test_database_connectivity`, `test_registration_draft_and_commit`, `test_e2e_05` | **VERIFIED** |
| **INV-04** | **Biometric Privacy Boundary:** Biometric templates (raw GT-521F32 and iris embeddings) are encrypted at rest (AES-256) and NEVER sent to Supabase cloud. | `backend/database/crypto.py`, `backend/patients/routes.py`, `sync/sync_worker.py` | `test_template_crypto`, `test_biometric_templates_encrypted_at_rest`, `test_e2e_05` | **VERIFIED** |
| **INV-05** | **Honest Engineering Protocol:** Distinguish Level A/B synthetic verification from physical Level C bench tests. Use explicit `MOCK_MODE=true` when physical sensors are missing. | `backend/config.py`, `backend/devices/manager.py`, `backend/devices/mock/` | `test_device_manager_mode_switching`, `test_foundation.py` | **VERIFIED** |

---

## 2. Core Operational Capabilities Traceability

| Feature ID | Functional Requirement | Implementation Location | Test Verification Case | Status |
| :--- | :--- | :--- | :--- | :--- |
| **REQ-01** | **Camera Scans ONLY on Button Click:** Camera module and 850nm IR LED must remain IDLE and OFF until operator clicks "Scan Iris" or "Start Camera". Automatic shutoff upon completion. | `iris-module/camera-client/ir_led_controller.py`, `backend/devices/routes.py`, `frontend/js/views/registration.js` | `test_e2e_02_camera_scans_only_on_button_click`, `test_iris_capture_synchronization_success`, `test_ir_led.py` | **VERIFIED** |
| **REQ-02** | **Best Image Quality Filter:** Pi Zero daemon processes burst frames and returns only the single highest-quality acceptable crop complying with ISO/IEC 29794-6 (sharpness, exposure, glare). | `iris-module/camera-client/quality_filter.py`, `iris-module/camera-client/iris_capture.py` | `test_camera_quality_and_iris_capture`, `test_iris_blur_failure_injection`, `test_iris_glare_failure_injection` | **VERIFIED** |
| **REQ-03** | **Fingerprint Scans ONLY on Button Click:** GT-521F32 optical sensor backlight LED must remain OFF until operator clicks "Scan Fingerprint" or advances pass. Immediate shutoff upon capture. | `backend/devices/routes.py`, `fingerprint-device/firmware/main.py`, `backend/devices/fingerprint_host.py` | `test_e2e_03_fingerprint_scans_only_on_button_click`, `test_fingerprint_3_stage_enrollment` | **VERIFIED** |
| **REQ-04** | **Automatic Device Reconnection:** Pi Zero W and ESP32 auto-connect to Pi 5 upon physical connection and recover gracefully from disconnects without crashing. | `backend/devices/camera_host.py`, `backend/devices/fingerprint_host.py`, `backend/devices/manager.py` | `test_e2e_04_automatic_device_reconnection`, `test_camera_host_client_disconnected_handling`, `test_fingerprint_host_client_disconnected_handling` | **VERIFIED** |

---

## 3. Workflow Specifications Traceability

| Workflow ID | Workflow Description | Implementation Code | End-to-End Test Verification | Status |
| :--- | :--- | :--- | :--- | :--- |
| **WF-A** | **Patient Registration:** Multi-step draft, demographic deduplication check, 3-pass fingerprint enrollment, iris capture, atomic commit, and transactional outbox queueing. | `backend/patients/routes.py:35-257`, `frontend/js/views/registration.js` | `test_e2e_05_multi_step_patient_registration_workflow`, `test_registration_draft_and_commit` | **VERIFIED** |
| **WF-B** | **Emergency Retrieval:** 1:N candidate search via fingerprint probe or iris vector, candidate resolution, and prioritized emergency medical summary (allergies, blood type, conditions, freshness). | `backend/biometrics/routes.py:14-49`, `backend/patients/routes.py:311-346`, `frontend/js/views/retrieval.js` | `test_e2e_06_emergency_retrieval_via_biometric_match`, `test_e2e_10_unknown_biometric_handling` | **VERIFIED** |
| **WF-C** | **Patient Record Revision:** Scoped demographic and clinical updates, mandatory clinical rationale requirement, version number increment, revision history audit, and cloud outbox queueing. | `backend/patients/routes.py:410-505`, `backend/audit/service.py` | `test_e2e_07_patient_record_update_with_mandatory_rationale`, `test_mandatory_rationale_for_updates`, `test_patient_update_with_reason` | **VERIFIED** |

---

## 4. Administrative & Governance Traceability

| Admin Requirement | Functional Scope | Implementation Code | Test Verification Case | Status |
| :--- | :--- | :--- | :--- | :--- |
| **ADM-01** | Real-Time KPI Metrics Dashboard (Patient counts, biometric completion %, outbox depth, device health) | `backend/admin/routes.py:32-91` | `test_e2e_08_admin_lifecycle_and_audit_log_inspection` | **VERIFIED** |
| **ADM-02** | Multi-Stage Patient Deletion State Machine (Request -> Legal Hold Check -> Secondary Approval -> Tombstone) | `backend/admin/routes.py:175-265` | `test_security_audit.py` | **VERIFIED** |
| **ADM-03** | Tamper-Evident SHA-256 Hash-Chained Audit Trail Logging and Inspection | `backend/audit/service.py:15-95`, `backend/admin/routes.py:320-350` | `test_e2e_08_admin_lifecycle_and_audit_log_inspection` | **VERIFIED** |
| **ADM-04** | Role-Based Access Control Scoping (Clinician, Registration Staff, Records Admin, System Admin) & Portal Separation | `backend/auth/rbac.py`, `backend/auth/security.py` | `test_registration_staff_cannot_access_admin_overview`, `test_registration_staff_cannot_modify_clinical_records`, `test_e2e_13` | **VERIFIED** |
