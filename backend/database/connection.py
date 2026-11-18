"""
LifeLink 2.0 - Database Connection Manager
Provides connection pooling, row formatting, and schema initialization.
Supports SQLite (developer mock/test mode) and PostgreSQL (Pi 5 production).
"""

import sqlite3
import json
import uuid
import datetime
from typing import List, Dict, Any, Optional
from backend.config import Config


class Database:
    """Connection and query executor for LifeLink local storage."""

    @staticmethod
    def get_connection():
        """Returns a database connection configured with dictionary row factory."""
        if Config.DB_TYPE == "sqlite":
            conn = sqlite3.connect(
                str(Config.DB_PATH),
                timeout=30.0,
                check_same_thread=False
            )
            conn.row_factory = sqlite3.Row
            # Enable Foreign Keys and Write-Ahead Logging for SQLite
            conn.execute("PRAGMA foreign_keys = ON;")
            conn.execute("PRAGMA journal_mode = WAL;")
            return conn
        else:
            # PostgreSQL connection for physical deployment
            import psycopg2
            from psycopg2.extras import RealDictCursor
            conn = psycopg2.connect(
                host=Config.POSTGRES_HOST,
                port=Config.POSTGRES_PORT,
                user=Config.POSTGRES_USER,
                password=Config.POSTGRES_PASSWORD,
                dbname=Config.POSTGRES_DB,
                cursor_factory=RealDictCursor
            )
            return conn

    @classmethod
    def execute_query(cls, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Executes a SELECT query and returns rows as a list of dicts."""
        conn = cls.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        finally:
            conn.close()

    @classmethod
    def execute_one(cls, query: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
        """Executes a SELECT query and returns a single row as a dict, or None."""
        conn = cls.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            row = cursor.fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    @classmethod
    def execute_commit(cls, query: str, params: tuple = ()) -> int:
        """Executes an INSERT/UPDATE/DELETE query and commits. Returns lastrowid or rowcount."""
        conn = cls.get_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params)
            conn.commit()
            return cursor.lastrowid or cursor.rowcount
        finally:
            conn.close()

    @classmethod
    def execute_script(cls, script: str):
        """Executes a multi-statement SQL script."""
        conn = cls.get_connection()
        try:
            cursor = conn.cursor()
            cursor.executescript(script)
            conn.commit()
        finally:
            conn.close()


def init_db():
    """Initializes all tables and indices in the local database."""
    schema_sql = """
    -- 1. Staff Accounts
    CREATE TABLE IF NOT EXISTS staff_accounts (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        full_name TEXT NOT NULL,
        role TEXT NOT NULL, -- clinician, registration_staff, records_admin, system_admin
        password_hash TEXT NOT NULL,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    -- 2. Patients Cache
    CREATE TABLE IF NOT EXISTS patients_cache (
        id TEXT PRIMARY KEY, -- Permanent UUID
        lifelink_id TEXT UNIQUE NOT NULL, -- e.g. LL-2026-00101
        full_name TEXT NOT NULL,
        dob TEXT NOT NULL,
        gender TEXT NOT NULL,
        blood_type TEXT,
        phone TEXT,
        address TEXT,
        photo_url TEXT,
        status TEXT NOT NULL DEFAULT 'active', -- active, archived, deletion_pending, deleted_tombstone
        version INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        synced_at TEXT
    );

    -- 3. Emergency Contacts
    CREATE TABLE IF NOT EXISTS emergency_contacts (
        id TEXT PRIMARY KEY,
        patient_id TEXT NOT NULL,
        contact_name TEXT NOT NULL,
        relationship TEXT NOT NULL,
        phone_number TEXT NOT NULL,
        is_primary INTEGER NOT NULL DEFAULT 1,
        FOREIGN KEY (patient_id) REFERENCES patients_cache (id) ON DELETE CASCADE
    );

    -- 4. Medical Records
    CREATE TABLE IF NOT EXISTS medical_records (
        id TEXT PRIMARY KEY,
        patient_id TEXT UNIQUE NOT NULL,
        allergies TEXT, -- JSON array of strings
        chronic_conditions TEXT, -- JSON array of strings
        current_medications TEXT, -- JSON array of {name, dosage, frequency}
        implanted_devices TEXT, -- JSON array of strings
        past_surgeries TEXT, -- JSON array of strings
        clinical_notes TEXT,
        provenance TEXT NOT NULL DEFAULT 'Hospital Registration',
        verified_by_staff_id TEXT,
        updated_at TEXT NOT NULL,
        FOREIGN KEY (patient_id) REFERENCES patients_cache (id) ON DELETE CASCADE
    );

    -- 5. Fingerprint Templates (Encrypted at rest)
    CREATE TABLE IF NOT EXISTS fingerprint_templates (
        id TEXT PRIMARY KEY,
        patient_id TEXT NOT NULL,
        finger_position TEXT NOT NULL, -- R1, R2, R3, R4, R5, L1, L2, L3, L4, L5
        encrypted_template BLOB NOT NULL, -- AES-256-GCM encrypted 498B template
        template_format TEXT NOT NULL DEFAULT 'GT-521F32-v2017',
        quality_score REAL NOT NULL DEFAULT 1.0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (patient_id) REFERENCES patients_cache (id) ON DELETE CASCADE,
        UNIQUE (patient_id, finger_position)
    );

    -- 6. Iris Templates (Encrypted at rest)
    CREATE TABLE IF NOT EXISTS iris_templates (
        id TEXT PRIMARY KEY,
        patient_id TEXT NOT NULL,
        eye_side TEXT NOT NULL, -- OD (Right), OS (Left)
        encrypted_template BLOB NOT NULL, -- AES-256-GCM encrypted 128x768 embedding
        model_version TEXT NOT NULL DEFAULT 'Vis-IrisFormer-v1',
        quality_score REAL NOT NULL DEFAULT 1.0,
        created_at TEXT NOT NULL,
        FOREIGN KEY (patient_id) REFERENCES patients_cache (id) ON DELETE CASCADE,
        UNIQUE (patient_id, eye_side)
    );

    -- 7. Registration Drafts
    CREATE TABLE IF NOT EXISTS registration_drafts (
        draft_id TEXT PRIMARY KEY,
        step TEXT NOT NULL DEFAULT 'fingerprint',
        data_json TEXT NOT NULL,
        created_by_staff_id TEXT NOT NULL,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    -- 8. Device Jobs
    CREATE TABLE IF NOT EXISTS device_jobs (
        job_id TEXT PRIMARY KEY,
        job_type TEXT NOT NULL, -- fingerprint_enroll, fingerprint_verify, iris_capture, camera_photo
        device_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', -- pending, running, waiting_for_input, processing, completed, failed, cancelled, timed_out
        request_payload TEXT,
        result_payload TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    -- 9. Record Revisions
    CREATE TABLE IF NOT EXISTS record_revisions (
        id TEXT PRIMARY KEY,
        patient_id TEXT NOT NULL,
        field_name TEXT NOT NULL,
        old_value TEXT,
        new_value TEXT,
        reason TEXT NOT NULL,
        edited_by_staff_id TEXT NOT NULL,
        version INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        FOREIGN KEY (patient_id) REFERENCES patients_cache (id) ON DELETE CASCADE
    );

    -- 10. Deletion Requests
    CREATE TABLE IF NOT EXISTS deletion_requests (
        id TEXT PRIMARY KEY,
        patient_id TEXT NOT NULL,
        requested_by_staff_id TEXT NOT NULL,
        approved_by_staff_id TEXT,
        reason TEXT NOT NULL,
        legal_hold_checked INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'pending_approval', -- pending_approval, approved, rejected
        created_at TEXT NOT NULL,
        processed_at TEXT,
        FOREIGN KEY (patient_id) REFERENCES patients_cache (id) ON DELETE CASCADE
    );

    -- 11. Audit Events (Tamper-evident system log)
    CREATE TABLE IF NOT EXISTS audit_events (
        id TEXT PRIMARY KEY,
        actor_id TEXT NOT NULL,
        actor_role TEXT NOT NULL,
        action TEXT NOT NULL, -- LOGIN, LOGOUT, VIEW_PATIENT, REGISTER_PATIENT, UPDATE_PATIENT, ARCHIVE_PATIENT, DELETION_REQUEST, etc.
        target_type TEXT NOT NULL, -- patient, staff, device, system
        target_id TEXT,
        details_json TEXT,
        ip_address TEXT,
        timestamp TEXT NOT NULL
    );

    -- 12. Transactional Outbox for Supabase Synchronization
    CREATE TABLE IF NOT EXISTS sync_outbox (
        id TEXT PRIMARY KEY,
        operation_id TEXT UNIQUE NOT NULL,
        table_name TEXT NOT NULL,
        record_id TEXT NOT NULL,
        action TEXT NOT NULL, -- INSERT, UPDATE, ARCHIVE, DELETE_TOMBSTONE
        payload_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending', -- pending, synced, conflict, failed
        retry_count INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        created_at TEXT NOT NULL,
        synced_at TEXT
    );

    -- 13. Sync Conflicts
    CREATE TABLE IF NOT EXISTS sync_conflicts (
        id TEXT PRIMARY KEY,
        outbox_id TEXT NOT NULL,
        table_name TEXT NOT NULL,
        record_id TEXT NOT NULL,
        local_version INTEGER NOT NULL,
        remote_version INTEGER NOT NULL,
        conflict_details TEXT NOT NULL,
        resolved INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    );

    -- Performance Indices
    CREATE INDEX IF NOT EXISTS idx_patients_lifelink_id ON patients_cache(lifelink_id);
    CREATE INDEX IF NOT EXISTS idx_patients_status ON patients_cache(status);
    CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_events(timestamp);
    CREATE INDEX IF NOT EXISTS idx_sync_status ON sync_outbox(status);
    """
    Database.execute_script(schema_sql)
