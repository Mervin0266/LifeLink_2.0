# LifeLink 2.0 — Engineering Fixes Applied

This document details the code fixes, diffs, and architectural improvements applied during verification to resolve defects and ensure full compliance.

---

## 1. Implementation of Wired Hardware Clients

### Files Created:
- `backend/devices/camera_host.py`: Communicates with Pi Zero W via HTTP over USB Gadget Ethernet (`192.168.55.2:5001`).
- `backend/devices/fingerprint_host.py`: Communicates with ESP32 via `pyserial` using framed `LLFP` binary packets.

### Key Implementation Diff in `backend/devices/manager.py`:
```python
@@ -36,8 +36,8 @@ class DeviceManager:
         if Config.MOCK_MODE:
             self.fingerprint = MockFingerprintDevice()
             self.camera = MockCameraDevice()
             self.mode = "MOCK"
         else:
-            # Fallback to mock
-            self.fingerprint = MockFingerprintDevice()
-            self.camera = MockCameraDevice()
+            from backend.devices.fingerprint_host import FingerprintHostClient
+            from backend.devices.camera_host import CameraHostClient
+            self.fingerprint = FingerprintHostClient()
+            self.camera = CameraHostClient()
             self.mode = "HARDWARE"
```

---

## 2. Granular JWT Rejection & Auth Error Propagation

### File Modified: `backend/auth/rbac.py`
```python
@@ -79,15 +79,25 @@ def get_current_user_and_error():
     auth_header = request.headers.get("Authorization", "")
     token = None
     if auth_header.startswith("Bearer "):
         token = auth_header.split(" ", 1)[1]
     elif "lifelink_token" in request.cookies:
         token = request.cookies.get("lifelink_token")
 
     if not token:
-        return None
+        return None, "Authentication required"
 
     payload = SecurityUtils.verify_token(token)
-    return payload
+    if not payload:
+        return None, "Invalid or expired token"
+
+    return payload, None

 def login_required(f):
     @wraps(f)
     def decorated_function(*args, **kwargs):
-        user = get_current_user()
+        user, err = get_current_user_and_error()
         if not user:
-            return jsonify({"status": "error", "message": "Authentication required"}), 401
+            return jsonify({"status": "error", "message": err or "Authentication required"}), 401
         g.current_user = user
         return f(*args, **kwargs)
```

---

## 3. Hoisting Version Increment on Clinical Updates

### File Modified: `backend/patients/routes.py`
```python
@@ -460,11 +460,14 @@ def update_patient(patient_id: str):
             for field, new_val in clinical_updates.items():
                 if field in ("allergies", "chronic_conditions", "current_medications", "implanted_devices", "past_surgeries", "clinical_notes"):
                     old_val = current_med.get(field, "")
                     serialized_new = json.dumps(new_val) if isinstance(new_val, list) else str(new_val)
                     if str(old_val) != serialized_new:
                         Database.execute_commit("""
                         INSERT INTO record_revisions (id, patient_id, field_name, old_value, new_value, reason, edited_by_staff_id, version, created_at)
                         VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                         """, (str(uuid.uuid4()), patient_id, field, str(old_val), serialized_new, reason, user["staff_id"], new_version, now))
 
                         Database.execute_commit(f"UPDATE medical_records SET {field} = ?, updated_at = ?, verified_by_staff_id = ? WHERE patient_id = ?;", (serialized_new, now, user["staff_id"], patient_id))
 
+        Database.execute_commit("UPDATE patients_cache SET version = ?, updated_at = ? WHERE id = ?;", (new_version, now, patient_id))
```

---

## 4. Single-Owner Serial and Camera Concurrency Locks (HTTP 409)

### File Modified: `backend/devices/manager.py`
```python
@@ -70,6 +70,12 @@ class DeviceManager:
+    def is_device_busy(self, device_id: str) -> bool:
+        """Checks if a peripheral has an unfinished active job."""
+        query = "SELECT job_id FROM device_jobs WHERE device_id = ? AND status IN ('pending', 'running') LIMIT 1;"
+        row = Database.execute_one(query, (device_id,))
+        return bool(row)
```

### File Modified: `backend/devices/routes.py`
```python
@@ -63,6 +63,8 @@ def fingerprint_enroll_step():
     manager = DeviceManager()
     if not job_id:
+        if manager.is_device_busy("esp32-gt521f32"):
+            return jsonify({"status": "error", "message": "Fingerprint device is busy with another active job"}), 409
         job_id = manager.create_job("fingerprint_enroll", "esp32-gt521f32", {"finger": finger_position})

@@ -113,6 +115,8 @@ def camera_capture_iris():
     manager = DeviceManager()
+    if manager.is_device_busy("pizero-cam3"):
+        return jsonify({"status": "error", "message": "Camera device is busy with another active capture session"}), 409
```

---

## 5. Mock Camera Glare Calibration

### File Modified: `backend/devices/mock/mock_camera.py`
```python
@@ -88,8 +88,9 @@ class MockCameraDevice:
         glare_x = center_x + 12
         glare_y = center_y - 12
         if quality == "glare":
-            # Excessive glare spot covering pupil/iris
-            cv2.circle(img, (glare_x, glare_y), 22, (255, 255, 255), -1)
+            # Excessive glare spot covering pupil/iris exceeding 5% threshold
+            cv2.circle(img, (glare_x, glare_y), 55, (255, 255, 255), -1)
+            cv2.circle(img, (center_x - 30, center_y), 45, (255, 255, 255), -1)
```

---

## 6. Polymorphic `.connected` Property on `CameraHostClient`

### File Modified: `backend/devices/camera_host.py`
```python
@@ -22,6 +22,11 @@ class CameraHostClient:
+    @property
+    def connected(self) -> bool:
+        """Returns True if the Pi Zero camera service is reachable."""
+        return self.get_status().get("connected", False)
```

---

## 7. MicroPython ESP32 Rx Buffer Reallocation Fix

### File Modified: `LifeLink_2.0_Deployment/esp32/firmware/main.py`
**Problem:** In MicroPython on ESP32, invoking `.clear()` or mutating a `bytearray` in place via `del rx_buf[:]` during high-throughput UART interrupts caused unhandled exceptions and memory allocation crashes.  
**Resolution:** Replaced in-place buffer clearing with immutable reallocation `rx_buf = bytearray()`.

```python
@@ -227,12 +227,12 @@ class ESP32FirmwareDaemon:
                     if len(rx_buf) >= SerialFrame.HEADER_SIZE + 4:
                         frame = SerialFrame.unpack(bytes(rx_buf))
                         if frame:
-                            rx_buf.clear()
+                            rx_buf = bytearray()
                             if "error" not in frame:
                                 self.handle_command(frame)
                         elif len(rx_buf) > 1024:
                             # Discard malformed noise
-                            rx_buf.clear()
+                            rx_buf = bytearray()
```

---

## 8. Raspberry Pi 5 Dynamic Host User & Permission Resolution

### File Modified: `LifeLink_2.0_Deployment/pi5/install.sh`
**Problem:** `install.sh` hardcoded user `pi`. On Raspberry Pi OS (Debian 12 Bookworm ARM64), the default setup user was `lifelink`. Running as `pi` failed permissions for `.Xauthority`, graphical session, dialout groups, and blocked access to `/home/lifelink/`.  
**Resolution:**
1. Dynamically inspect `TARGET_USER="${SUDO_USER:-$(logname 2>/dev/null || echo ${USER:-lifelink})}"`.
2. Automatically attach `$TARGET_USER` to `dialout,video,audio,render`.
3. Copy `verify_installation.py` into `/opt/lifelink/` to avoid restricted cross-user `$HOME` directory traversal.
4. Dynamically patch systemd units with `$TARGET_USER`.

```bash
@@ -74,12 +74,28 @@ fi
-if ! id "pi" &>/dev/null; then
-    useradd -m -s /bin/bash pi || true
-fi
-usermod -a -G dialout,video,audio pi || true
-chown -R pi:pi "$INSTALL_DIR"
+TARGET_USER="${SUDO_USER:-$(logname 2>/dev/null || echo ${USER:-lifelink})}"
+TARGET_HOME=$(eval echo "~$TARGET_USER")
+usermod -a -G dialout,video,audio "$TARGET_USER" || true
+chown -R "$TARGET_USER:$TARGET_USER" "$INSTALL_DIR"
...
+sed -i "s/^User=.*/User=$TARGET_USER/g" /etc/systemd/system/lifelink-backend.service
+sed -i "s/^Group=.*/Group=$TARGET_USER/g" /etc/systemd/system/lifelink-backend.service
+sed -i "s/^User=.*/User=$TARGET_USER/g" /etc/systemd/system/lifelink-kiosk.service
+sed -i "s|^Environment=XAUTHORITY=.*|Environment=XAUTHORITY=$TARGET_HOME/.Xauthority|g" /etc/systemd/system/lifelink-kiosk.service
```

---

## 9. Flask Application Root `sys.path` Bootstrap

### Files Modified: `backend/app.py`, `LifeLink_2.0_Deployment/pi5/backend/app.py`
**Problem:** Running `python backend/app.py` from `/opt/lifelink` assigned `sys.path[0]` to `/opt/lifelink/backend`. Top-level imports `from backend.config import Config` failed with `ModuleNotFoundError: No module named 'backend'`.  
**Resolution:** Added automatic root path discovery to the top of `backend/app.py`.

```python
@@ -5,7 +5,14 @@ and serves the touchscreen kiosk frontend.
 """
 
 import os
+import sys
 from pathlib import Path
+
+# Ensure repository/deployment root is in sys.path
+_REPO_ROOT = Path(__file__).resolve().parent.parent
+if str(_REPO_ROOT) not in sys.path:
+    sys.path.insert(0, str(_REPO_ROOT))
+
 from flask import Flask, jsonify, send_from_directory, request
 from backend.config import Config
```

---

## 10. Systemd Sandboxing & Python Path Hardening

### File Modified: `LifeLink_2.0_Deployment/pi5/systemd/lifelink-backend.service`
**Problem:** Systemd execution environment lacked `PYTHONPATH`, and sandboxing settings did not explicitly whitelist `/opt/lifelink` for database write locks.  
**Resolution:**
```ini
@@ -9,6 +9,7 @@
 Group=pi
 WorkingDirectory=/opt/lifelink
 Environment=PYTHONUNBUFFERED=1
+Environment=PYTHONPATH=/opt/lifelink
 Environment=MOCK_MODE=false
 Environment=HARDWARE_MODE=true
 Environment=DB_TYPE=sqlite
@@ -25,6 +26,7 @@
 ProtectHome=read-only
 NoNewPrivileges=true
 PrivateTmp=true
+ReadWritePaths=/opt/lifelink
```

