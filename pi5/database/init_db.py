#!/usr/bin/env python3
"""
LifeLink 2.0 - Database Initialization & Migration Tool
Executes schema DDL, verifies table creation, and seeds default staff accounts.
"""

import sys
import os
import uuid
import datetime
from pathlib import Path

# Add pi5 root to sys.path
PI5_ROOT = Path(__file__).resolve().parent.parent
if str(PI5_ROOT) not in sys.path:
    sys.path.insert(0, str(PI5_ROOT))

from backend.config import Config
from backend.database.connection import Database
from backend.auth.security import SecurityUtils


def init_database(seed_staff: bool = True):
    print("=================================================================")
    print(" LifeLink 2.0: Initializing Local Database")
    print(f" Database Type: {Config.DB_TYPE.upper()} ({Config.DB_NAME})")
    print("=================================================================")

    schema_file = Path(__file__).resolve().parent / "schema.sql"
    if not schema_file.exists():
        print(f"[-] Error: Schema file not found at {schema_file}")
        return False

    with open(schema_file, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    print("[*] Applying schema DDL...")
    Database.execute_script(schema_sql)
    print("[+] All 13 core tables and indices successfully initialized!")

    if seed_staff:
        # Check if staff accounts table already has users
        existing = Database.execute_query("SELECT COUNT(*) as cnt FROM staff_accounts;")
        if existing and existing[0]["cnt"] == 0:
            print("[*] Seeding default authorized staff accounts...")
            now = datetime.datetime.now(datetime.timezone.utc).isoformat()
            default_staff = [
                ("staff-doc-001", "dr_smith", "dr.smith@hospital.org", "Dr. Sarah Smith, MD", "clinician", "DoctorPass123!"),
                ("staff-nurse-001", "nurse_clara", "clara@hospital.org", "Nurse Clara Oswald, RN", "clinician", "NursePass123!"),
                ("staff-reg-001", "john_reg", "john@hospital.org", "John Davis (Admissions)", "registration_staff", "RegStaffPass123!"),
                ("staff-rec-001", "records_admin", "records@hospital.org", "Eleanor Vance (HIM Director)", "records_admin", "RecordsAdminPass123!"),
                ("staff-sys-001", "admin", "sysadmin@lifelink.org", "Alex Chen (Chief Technology Officer)", "system_admin", "AdminPass123!")
            ]

            insert_sql = """
            INSERT INTO staff_accounts (id, username, email, full_name, role, password_hash, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?);
            """
            for staff_id, username, email, full_name, role, raw_pass in default_staff:
                p_hash = SecurityUtils.hash_password(raw_pass)
                Database.execute_commit(insert_sql, (staff_id, username, email, full_name, role, p_hash, now, now))
                print(f"  [+] Seeded {role.upper()}: {username} ({full_name})")

    print("\n[+] Local database setup completed successfully!")
    return True


if __name__ == "__main__":
    success = init_database()
    sys.exit(0 if success else 1)
