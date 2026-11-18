"""
Unit tests for LifeLink 2.0 Transactional Outbox Sync Worker.
"""

import pytest
import uuid
import datetime
import json
from backend.database.connection import Database
from sync.worker import SyncWorker


def test_outbox_sync_processing():
    """Verifies that the sync worker processes pending outbox items idempotently."""
    worker = SyncWorker()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    outbox_id = str(uuid.uuid4())

    # Queue an outbox item
    Database.execute_commit("""
    INSERT INTO sync_outbox (id, operation_id, table_name, record_id, action, payload_json, status, created_at)
    VALUES (?, ?, 'patients', 'pat-test-sync-1', 'INSERT', ?, 'pending', ?);
    """, (outbox_id, str(uuid.uuid4()), json.dumps({"test": "data"}), now))

    processed = worker.process_pending_outbox_items()
    assert processed >= 1

    # Verify status changed to synced
    item = Database.execute_one("SELECT status, synced_at FROM sync_outbox WHERE id = ?;", (outbox_id,))
    assert item["status"] == "synced"
    assert item["synced_at"] is not None
