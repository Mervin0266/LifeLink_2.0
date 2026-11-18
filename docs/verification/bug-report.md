# LifeLink 2.0 — Defect & Bug Analysis Report

**Audit Objective:** Systematic discovery, logging, and root-cause analysis of defects found during end-to-end verification and device deployment.  
**Total Defects Identified:** 9  
**Total Defects Resolved:** 9  
**Remaining Open Defects:** 0  

---

## Defect Summary Table

| Defect ID | Severity | Subsystem | Description | Resolution Status |
| :--- | :--- | :--- | :--- | :--- |
| **BUG-001** | **CRITICAL** | Device Orchestration | Missing physical wired host clients (`CameraHostClient`, `FingerprintHostClient`) causing backend to remain stuck in mock mode. | **FIXED** |
| **BUG-002** | **HIGH** | Auth / RBAC | RBAC middleware returned generic "Authentication required" for forged/tampered JWT tokens instead of distinguishing invalid/expired tokens. | **FIXED** |
| **BUG-003** | **HIGH** | Clinical Patient API | `PATCH /api/v1/patients/<id>` omitted incrementing `patients_cache.version` when exclusively updating clinical medical records. | **FIXED** |
| **BUG-004** | **MEDIUM** | Peripheral Manager | Lack of serial bus and camera single-owner concurrency guards allowed concurrent scan requests to collide instead of returning HTTP 409 Conflict. | **FIXED** |
| **BUG-005** | **MEDIUM** | Mock Camera | Synthetic glare simulation generated a highlight area (1.26%) below the 5% rejection threshold, causing low-quality glare test to pass unexpectedly. | **FIXED** |
| **BUG-006** | **LOW** | Host Drivers | `CameraHostClient` lacked direct boolean `.connected` property accessor expected by the unified device manager. | **FIXED** |
| **BUG-007** | **HIGH** | Pi 5 Deployment | Target system user hardcoded to legacy `pi` instead of dynamic host user (`lifelink`) on Raspberry Pi OS Bookworm. | **FIXED** |
| **BUG-008** | **MEDIUM** | Pi 5 Deployment | Post-install validation script executed from restricted `$HOME` directory resulting in `Permission denied`. | **FIXED** |
| **BUG-009** | **CRITICAL** | Backend Core | Flask application executed via systemd failed module import `from backend.config import Config` (`sys.path` root omission). | **FIXED** |

---

## Detailed Defect Descriptions & Root Cause Analysis

### BUG-001: Missing Physical Wired Host Drivers
- **Severity:** CRITICAL
- **Symptom:** Setting `MOCK_MODE=false` in `.env` resulted in `DeviceManager` logging a fallback warning and falling back to synthetic software mocks.
- **Root Cause:** While the Pi Zero W daemon (`camera_service.py`) and ESP32 MicroPython firmware existed, the host-side communication drivers on the Pi 5 (`backend/devices/camera_host.py` and `backend/devices/fingerprint_host.py`) had not been implemented.
- **Impact:** System could not be tested against physical peripherals or wired hardware communication contracts.
- **Fix:** Implemented `CameraHostClient` using resilient HTTP sessions over USB Gadget Ethernet (`192.168.55.2:5001`) and `FingerprintHostClient` using `pyserial` with `LLFP` 28-byte packet framing and CRC32 verification.

### BUG-002: Indistinguishable JWT Rejection Error
- **Severity:** HIGH
- **Symptom:** Forged or tampered tokens passed in the `Authorization: Bearer <token>` header returned `{"message": "Authentication required"}` rather than identifying invalid or expired signatures.
- **Root Cause:** `backend/auth/rbac.py` used `get_current_user()`, which returned `None` for both missing headers and signature verification failures.
- **Impact:** API consumers and audit loggers could not distinguish an unauthenticated request from an active token tampering attempt.
- **Fix:** Refactored `rbac.py` to introduce `get_current_user_and_error()` that explicitly differentiates missing credentials from invalid/expired signatures and returns descriptive 401 error payloads.

### BUG-003: Clinical Revision Version Counter Stagnation
- **Severity:** HIGH
- **Symptom:** Submitting clinical updates (e.g., changes to critical allergies or medications) without demographic changes updated `medical_records` but failed to increment `patients_cache.version`.
- **Root Cause:** In `backend/patients/routes.py`, `UPDATE patients_cache SET version = ?` was nested strictly inside the `if demographics_updates:` block.
- **Impact:** Patient cache version remained stagnant, causing transactional outbox conflicts and audit sync discrepancies.
- **Fix:** Hoisted the version update statement to execute whenever `demographics_updates` OR `clinical_updates` occur.

### BUG-004: Lack of Concurrent Scan Collision Guard
- **Severity:** MEDIUM
- **Symptom:** Attempting to start a second iris capture or fingerprint enrollment while a previous job was in progress resulted in undefined behavior on the serial port or camera sensor.
- **Root Cause:** `backend/devices/manager.py` did not check for active jobs (`pending` or `running`) prior to spawning new hardware jobs.
- **Impact:** Potential race condition and packet corruption across the physical serial bus and camera pipeline.
- **Fix:** Added `is_device_busy(device_id)` to `DeviceManager` and updated `routes.py` to reject concurrent requests with HTTP 409 Conflict.

### BUG-005: Glare Area Below Rejection Threshold
- **Severity:** MEDIUM
- **Symptom:** Failure injection test for corneal glare failed because `evaluate_quality` passed the image as acceptable.
- **Root Cause:** In `MockCameraDevice.generate_synthetic_eye_image`, the glare highlight circle radius was set to 22 pixels, which covered only 1.26% of the 400x300 image area, falling well below the 5.0% rejection threshold.
- **Impact:** Low-quality images with significant corneal reflections would not be filtered out in simulated testing.
- **Fix:** Increased simulated glare patches to radius 55 + radius 45, yielding ~13% saturated pixels to properly trigger ISO/IEC 29794-6 rejection.

### BUG-006: Inconsistent Device Connectivity Attribute
- **Severity:** LOW
- **Symptom:** Calling `.connected` on `CameraHostClient` threw an `AttributeError`.
- **Root Cause:** `CameraHostClient` exposed `get_status()["connected"]` but omitted the `@property def connected` present on other device classes.
- **Impact:** Inconsistent polymorphic interface between mock and hardware drivers.
- **Fix:** Added `@property def connected(self) -> bool` to `CameraHostClient`.

### BUG-007: Target System User & Permission Mismatch on Pi 5 (Debian 12 Bookworm)
- **Severity:** HIGH
- **Symptom:** Running `install.sh` under user `lifelink` created legacy user `pi`, set ownership of `/opt/lifelink` to `pi:pi`, and configured systemd services to run as `User=pi`.
- **Root Cause:** Script hardcoded Debian legacy default username `pi`. On Raspberry Pi OS Bookworm, the setup wizard creates arbitrary user accounts (here: `lifelink` UID 1000). The graphical desktop session and hardware access groups belonged to `lifelink`.
- **Impact:** Systemd kiosk service failed to open display (`.Xauthority` belonging to `lifelink`), and user `lifelink` lacked write access to local SQLite databases in `/opt/lifelink`.
- **Fix:** Refactored `install.sh` to dynamically detect `TARGET_USER="${SUDO_USER:-$(logname 2>/dev/null || echo ${USER:-lifelink})}"`, grant peripheral groups (`dialout,video,audio,render`), and update systemd unit definitions dynamically via `sed`.

### BUG-008: Installation Validation Script Host Path Access Block
- **Severity:** MEDIUM
- **Symptom:** `[8/8] Executing installation validation script...` terminated with `/opt/lifelink/venv/bin/python: can't open file '/home/lifelink/LifeLink_2.0/LifeLink_2.0_Deployment/pi5/verify_installation.py': [Errno 13] Permission denied`.
- **Root Cause:** `install.sh` executed `sudo -u pi "$INSTALL_DIR/venv/bin/python" "$SCRIPT_DIR/verify_installation.py"`. Because `$SCRIPT_DIR` was inside `/home/lifelink/`, the foreign user `pi` was blocked by Linux filesystem permissions (`750` / `700` home directory security).
- **Impact:** Post-installation diagnostic verification failed despite valid deployment files.
- **Fix:** Updated `install.sh` to copy `verify_installation.py` directly into `/opt/lifelink/` during the file deployment stage and execute it as `$TARGET_USER` directly within `/opt/lifelink/`.

### BUG-009: Flask Application Root `sys.path` Module Resolution Failure
- **Severity:** CRITICAL
- **Symptom:** Starting backend service via `systemctl start lifelink-backend` resulted in immediate service crash. `curl http://127.0.0.1:5000/api/v1/health` failed with `curl: (7) Failed to connect to 127.0.0.1 port 5000: Connection refused`.
- **Root Cause:** Running `python backend/app.py` sets `sys.path[0]` to the directory containing `app.py` (`/opt/lifelink/backend`). The top-level package `/opt/lifelink` was not in `sys.path`. Top-level imports `from backend.config import Config` immediately failed with `ModuleNotFoundError: No module named 'backend'`.
- **Impact:** Backend service crashed on startup in production deployment on Raspberry Pi 5.
- **Fix:** (1) Injected `_REPO_ROOT = Path(__file__).resolve().parent.parent; sys.path.insert(0, str(_REPO_ROOT))` at the top of `backend/app.py` before backend package imports. (2) Added `Environment=PYTHONPATH=/opt/lifelink` and `ReadWritePaths=/opt/lifelink` to `lifelink-backend.service`.
