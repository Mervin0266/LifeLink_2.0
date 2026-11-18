#!/usr/bin/env python3
"""
LifeLink 2.0 - Synthetic Demo Data Seeder
Populates local database with demo staff accounts for all three login portals,
and synthetic patient profiles with encrypted biometric templates.
"""

import sys
import uuid
import json
import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.database.connection import init_db, Database
from backend.database.crypto import TemplateCrypto
from backend.auth.security import SecurityUtils
from backend.auth.rbac import Roles
from backend.devices.mock.mock_fingerprint import MockFingerprintDevice


def seed_staff():
    print("[1/2] Seeding Staff Accounts...")
    crypto = TemplateCrypto()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    staff_users = [
        {
            "id": "staff-clinician-001",
            "username": "clinician",
            "email": "doctor@lifelink.local",
            "full_name": "Dr. Sarah Chen, MD",
            "role": Roles.CLINICIAN,
            "password": "Clinical@123"
        },
        {
            "id": "staff-hospital-002",
            "username": "registrar",
            "email": "registrar@lifelink.local",
            "full_name": "Marcus Vance (Admissions)",
            "role": Roles.REGISTRATION_STAFF,
            "password": "Hospital@123"
        },
        {
            "id": "staff-recordsadmin-003",
            "username": "recordsadmin",
            "email": "recordsadmin@lifelink.local",
            "full_name": "Elena Rostova (Records Admin)",
            "role": Roles.RECORDS_ADMIN,
            "password": "Admin@123"
        },
        {
            "id": "staff-sysadmin-004",
            "username": "sysadmin",
            "email": "sysadmin@lifelink.local",
            "full_name": "Alex Mercer (System Admin)",
            "role": Roles.SYSTEM_ADMIN,
            "password": "SysAdmin@123"
        }
    ]

    for s in staff_users:
        pw_hash = SecurityUtils.hash_password(s["password"])
        Database.execute_commit("""
        INSERT INTO staff_accounts (id, username, email, full_name, role, password_hash, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(username) DO UPDATE SET
            password_hash = excluded.password_hash,
            role = excluded.role,
            is_active = 1,
            updated_at = excluded.updated_at;
        """, (s["id"], s["username"], s["email"], s["full_name"], s["role"], pw_hash, now, now))
        print(f"      - Created {s['role']}: {s['username']} ({s['email']}) / pw: {s['password']}")


def seed_patients():
    print("[2/2] Seeding Synthetic Patients & Encrypted Biometrics...")
    crypto = TemplateCrypto()
    mock_fp = MockFingerprintDevice()
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()

    patients = [
        {
            "id": "pat-synthetic-001",
            "lifelink_id": "LL-2026-00001",
            "full_name": "Jane Doe",
            "dob": "1988-04-12",
            "gender": "Female",
            "blood_type": "O-Positive",
            "phone": "+1-555-0192",
            "address": "404 Elm St, Medical District",
            "allergies": ["Severe Penicillin Anaphylaxis", "Latex"],
            "chronic_conditions": ["Asthma", "Mild Hypertension"],
            "current_medications": [
                {"name": "Albuterol Inhaler", "dosage": "90mcg", "frequency": "As needed for wheezing"},
                {"name": "Lisinopril", "dosage": "10mg", "frequency": "Once daily morning"}
            ],
            "implanted_devices": ["None"],
            "past_surgeries": ["Appendectomy (2015)"],
            "clinical_notes": "Patient carries EpiPen for penicillin cross-reactions.",
            "emergency_contact": {"name": "Robert Doe", "relationship": "Spouse", "phone": "+1-555-0193"}
        },
        {
            "id": "pat-synthetic-002",
            "lifelink_id": "LL-2026-00002",
            "full_name": "John Smith",
            "dob": "1975-11-20",
            "gender": "Male",
            "blood_type": "A-Negative",
            "phone": "+1-555-0245",
            "address": "120 Pine Ave, Downtown",
            "allergies": ["Sulfa Drugs"],
            "chronic_conditions": ["Atrial Fibrillation", "Type 2 Diabetes"],
            "current_medications": [
                {"name": "Apixaban (Eliquis)", "dosage": "5mg", "frequency": "Twice daily"},
                {"name": "Metformin", "dosage": "500mg", "frequency": "Twice daily with meals"}
            ],
            "implanted_devices": ["Dual-Chamber Cardiac Pacemaker (2021)"],
            "past_surgeries": ["Pacemaker implantation (2021)", "Right Knee Arthroscopy (2018)"],
            "clinical_notes": "ANTICOAGULANT ALERT: High bleed risk due to Apixaban.",
            "emergency_contact": {"name": "Linda Smith", "relationship": "Sister", "phone": "+1-555-0246"}
        },
        {
            "id": "pat-synthetic-003",
            "lifelink_id": "LL-2026-00003",
            "full_name": "Alice Johnson",
            "dob": "1995-08-30",
            "gender": "Female",
            "blood_type": "B-Positive",
            "phone": "+1-555-0378",
            "address": "77 Maple St, University Hills",
            "allergies": ["No Known Drug Allergies (NKDA)"],
            "chronic_conditions": ["None Reported"],
            "current_medications": [],
            "implanted_devices": ["None"],
            "past_surgeries": ["Wisdom Teeth Extraction (2019)"],
            "clinical_notes": "Baseline healthy trauma intake.",
            "emergency_contact": {"name": "David Johnson", "relationship": "Father", "phone": "+1-555-0379"}
        }
    ]

    for p in patients:
        # 1. Demographics
        Database.execute_commit("""
        INSERT INTO patients_cache (id, lifelink_id, full_name, dob, gender, blood_type, phone, address, photo_url, status, version, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, '', 'active', 1, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            full_name = excluded.full_name,
            status = 'active',
            updated_at = excluded.updated_at;
        """, (p["id"], p["lifelink_id"], p["full_name"], p["dob"], p["gender"], p["blood_type"], p["phone"], p["address"], now, now))

        # 2. Emergency Contact
        ec = p["emergency_contact"]
        Database.execute_commit("""
        INSERT INTO emergency_contacts (id, patient_id, contact_name, relationship, phone_number, is_primary)
        VALUES (?, ?, ?, ?, ?, 1)
        ON CONFLICT(id) DO NOTHING;
        """, (str(uuid.uuid4()), p["id"], ec["name"], ec["relationship"], ec["phone"]))

        # 3. Medical Records
        Database.execute_commit("""
        INSERT INTO medical_records (id, patient_id, allergies, chronic_conditions, current_medications, implanted_devices, past_surgeries, clinical_notes, provenance, verified_by_staff_id, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Hospital Seed', 'staff-clinician-001', ?)
        ON CONFLICT(patient_id) DO UPDATE SET
            allergies = excluded.allergies,
            chronic_conditions = excluded.chronic_conditions,
            current_medications = excluded.current_medications,
            updated_at = excluded.updated_at;
        """, (
            str(uuid.uuid4()),
            p["id"],
            json.dumps(p["allergies"]),
            json.dumps(p["chronic_conditions"]),
            json.dumps(p["current_medications"]),
            json.dumps(p["implanted_devices"]),
            json.dumps(p["past_surgeries"]),
            p["clinical_notes"],
            now
        ))

        # 4. Fingerprint Templates (10 fingers: R1..R5, L1..L5)
        for finger in ("R1", "R2", "R3", "R4", "R5", "L1", "L2", "L3", "L4", "L5"):
            raw_fp = mock_fp.generate_synthetic_template(f"{p['id']}_{finger}")
            enc_fp = crypto.encrypt(raw_fp)
            Database.execute_commit("""
            INSERT INTO fingerprint_templates (id, patient_id, finger_position, encrypted_template, template_format, quality_score, created_at)
            VALUES (?, ?, ?, ?, 'GT-521F32-v2017', 1.0, ?)
            ON CONFLICT(patient_id, finger_position) DO NOTHING;
            """, (str(uuid.uuid4()), p["id"], finger, enc_fp, now))

        # 5. Iris Templates (OD and OS)
        for eye in ("OD", "OS"):
            # Synthetic 128x768 embedding bytes
            raw_iris = (f"synthetic_iris_{p['id']}_{eye}".encode("utf-8") * 100)[:393216]
            enc_iris = crypto.encrypt(raw_iris)
            Database.execute_commit("""
            INSERT INTO iris_templates (id, patient_id, eye_side, encrypted_template, model_version, quality_score, created_at)
            VALUES (?, ?, ?, ?, 'Vis-IrisFormer-v1', 1.0, ?)
            ON CONFLICT(patient_id, eye_side) DO NOTHING;
            """, (str(uuid.uuid4()), p["id"], eye, enc_iris, now))

        print(f"      - Seeded: {p['full_name']} ({p['lifelink_id']}) with 10 fingers and OD/OS irises.")


def main():
    print("==================================================")
    print(" LifeLink 2.0 - Seeding Demo Synthetic Data")
    print("==================================================")
    init_db()
    seed_staff()
    seed_patients()
    print("==================================================")
    print(" Seeding Completed Successfully!")
    print(" Ready to launch: python scripts/run_mock.py")
    print("==================================================")


if __name__ == "__main__":
    main()
