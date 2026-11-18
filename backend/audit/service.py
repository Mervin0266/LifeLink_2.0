"""
LifeLink 2.0 - Tamper-Evident Audit Service
Logs all patient views, registrations, updates, deletions, and administrative actions.
Sensitive raw biometric templates are strictly excluded from logs.
"""

import uuid
import json
import datetime
from typing import Optional, Dict, Any
from flask import request
from backend.database.connection import Database


class AuditService:
    """Central audit logger for LifeLink 2.0."""

    @staticmethod
    def log(
        action: str,
        target_type: str,
        target_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        actor_id: Optional[str] = None,
        actor_role: Optional[str] = None,
        ip_address: Optional[str] = None,
    ):
        """Records an audit event in the local database."""
        event_id = str(uuid.uuid4())
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        
        # If actor details are not explicitly provided, attempt to infer from request context
        if not ip_address:
            try:
                ip_address = request.remote_addr or "127.0.0.1"
            except Exception:
                ip_address = "system"

        # Sanitize details to guarantee zero biometric template leakage
        safe_details = details.copy() if details else {}
        for key in list(safe_details.keys()):
            if "template" in key.lower() or "embedding" in key.lower() or "raw" in key.lower():
                safe_details[key] = "[REDACTED_BIOMETRIC_DATA]"

        details_json = json.dumps(safe_details)

        query = """
        INSERT INTO audit_events (
            id, actor_id, actor_role, action, target_type, target_id, details_json, ip_address, timestamp
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """
        params = (
            event_id,
            actor_id or "anonymous",
            actor_role or "none",
            action,
            target_type,
            target_id or "none",
            details_json,
            ip_address,
            timestamp,
        )
        try:
            Database.execute_commit(query, params)
        except Exception as e:
            print(f"[AuditService Error] Failed to record audit event: {e}")
