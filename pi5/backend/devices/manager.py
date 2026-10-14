"""
LifeLink 2.0 - Device Job Manager & Orchestrator
Coordinates hardware operations, enforces single-owner serial access,
tracks asynchronous job lifecycles in the database, and switches cleanly
between MOCK_MODE and physical HARDWARE_MODE.
"""

import uuid
import datetime
import json
import base64
from typing import Dict, Any, Optional
from backend.config import Config
from backend.database.connection import Database
from backend.devices.mock.mock_fingerprint import MockFingerprintDevice
from backend.devices.mock.mock_camera import MockCameraDevice


class DeviceManager:
    """Singleton orchestrator for biometric peripherals and device jobs."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(DeviceManager, cls).__new__(cls)
            cls._instance._init_devices()
        return cls._instance

    def _init_devices(self):
        """Initializes device drivers or mock simulators based on Config."""
        if Config.MOCK_MODE:
            self.fingerprint = MockFingerprintDevice()
            self.camera = MockCameraDevice()
            self.mode = "MOCK"
        else:
            from backend.devices.fingerprint_host import FingerprintHostClient
            from backend.devices.camera_host import CameraHostClient
            self.fingerprint = FingerprintHostClient()
            self.camera = CameraHostClient()
            self.mode = "HARDWARE"

    def get_health(self) -> Dict[str, Any]:
        """Returns consolidated peripheral readiness and system health."""
        fp_status = self.fingerprint.get_status()
        cam_status = self.camera.get_status()

        # Database health check
        db_healthy = False
        try:
            res = Database.execute_one("SELECT 1 as alive;")
            db_healthy = bool(res and res.get("alive") == 1)
        except Exception:
            db_healthy = False

        return {
            "mode": self.mode,
            "mock_mode": Config.MOCK_MODE,
            "fingerprint_device": fp_status,
            "camera_device": cam_status,
            "local_database": {
                "healthy": db_healthy,
                "type": Config.DB_TYPE
            },
            "cloud_sync": {
                "enabled": Config.SYNC_ENABLED,
                "supabase_url": Config.SUPABASE_URL if Config.SYNC_ENABLED else "disabled"
            },
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat()
        }

    def is_device_busy(self, device_id: str) -> bool:
        """Checks if a peripheral has an unfinished active job."""
        query = "SELECT job_id FROM device_jobs WHERE device_id = ? AND status IN ('pending', 'running') LIMIT 1;"
        row = Database.execute_one(query, (device_id,))
        return bool(row)

    def create_job(self, job_type: str, device_id: str, payload: Optional[Dict[str, Any]] = None) -> str:
        """Creates and persists a new asynchronous device job."""
        job_id = str(uuid.uuid4())
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        query = """
        INSERT INTO device_jobs (job_id, job_type, device_id, status, request_payload, created_at, updated_at)
        VALUES (?, ?, ?, 'pending', ?, ?, ?);
        """
        Database.execute_commit(query, (job_id, job_type, device_id, json.dumps(payload or {}), now, now))
        return job_id

    def update_job_status(self, job_id: str, status: str, result_payload: Optional[Dict[str, Any]] = None):
        """Updates the state and outcome of an active device job."""
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        query = """
        UPDATE device_jobs
        SET status = ?, result_payload = ?, updated_at = ?
        WHERE job_id = ?;
        """
        Database.execute_commit(query, (status, json.dumps(result_payload or {}), now, job_id))

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Retrieves job state from the database."""
        query = "SELECT * FROM device_jobs WHERE job_id = ?;"
        job = Database.execute_one(query, (job_id,))
        if job and job.get("result_payload"):
            try:
                job["result"] = json.loads(job["result_payload"])
            except Exception:
                job["result"] = {}
        return job

    def cancel_job(self, job_id: str) -> bool:
        """Safely terminates an active hardware job and resets peripheral state."""
        job = self.get_job(job_id)
        if not job or job["status"] in ("completed", "failed", "cancelled"):
            return False

        # Reset devices
        self.fingerprint.wipe_scratch_slot(199)
        self.fingerprint.set_led(False)
        self.update_job_status(job_id, "cancelled", {"reason": "operator_cancelled"})
        return True
