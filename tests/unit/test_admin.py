"""
Unit tests for LifeLink 2.0 Admin Dashboard and Deletion Workflow.
"""

import pytest
from backend.app import create_app
from backend.auth.security import SecurityUtils
from backend.auth.rbac import Roles
from backend.database.connection import Database


@pytest.fixture
def client():
    app = create_app()
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


@pytest.fixture
def records_admin_token():
    return SecurityUtils.create_token({
        "staff_id": "staff-recordsadmin-003",
        "username": "recordsadmin",
        "role": Roles.RECORDS_ADMIN,
        "portal": "admin"
    })


@pytest.fixture
def system_admin_token():
    return SecurityUtils.create_token({
        "staff_id": "staff-sysadmin-004",
        "username": "sysadmin",
        "role": Roles.SYSTEM_ADMIN,
        "portal": "admin"
    })


def test_admin_overview_kpis(client, records_admin_token):
    headers = {"Authorization": f"Bearer {records_admin_token}"}
    resp = client.get("/api/v1/admin/overview", headers=headers)
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "success"
    assert data["kpis"]["total_patients"] >= 3
    assert data["kpis"]["total_staff"] >= 4


def test_admin_archive_patient(client, records_admin_token):
    headers = {"Authorization": f"Bearer {records_admin_token}"}
    patient_id = "pat-synthetic-003"  # Alice Johnson

    resp = client.post(f"/api/v1/admin/patients/{patient_id}/archive", json={
        "reason": "Patient relocated out of state"
    }, headers=headers)
    assert resp.status_code == 200

    # Verify status changed to archived
    p = Database.execute_one("SELECT status FROM patients_cache WHERE id = ?;", (patient_id,))
    assert p is not None
    assert p["status"] == "archived"


def test_admin_deletion_request_workflow(client, records_admin_token, system_admin_token):
    """
    Tests full multi-stage deletion workflow:
    1. Records Admin requests deletion with mandatory reason & legal hold confirmation.
    2. Status changes to deletion_pending.
    3. System Admin approves the deletion request.
    4. Biometrics zeroized, patient status set to deleted_tombstone.
    """
    ra_headers = {"Authorization": f"Bearer {records_admin_token}"}
    sa_headers = {"Authorization": f"Bearer {system_admin_token}"}
    patient_id = "pat-synthetic-002"  # John Smith

    # 1. Initiate Deletion Request
    req_resp = client.post(f"/api/v1/admin/patients/{patient_id}/deletion-requests", json={
        "reason": "Formal legal erasure request under healthcare data policy",
        "legal_hold_confirmed": True
    }, headers=ra_headers)
    assert req_resp.status_code == 202
    req_data = req_resp.get_json()
    req_id = req_data["deletion_request_id"]

    # Verify status changed to deletion_pending
    p1 = Database.execute_one("SELECT status FROM patients_cache WHERE id = ?;", (patient_id,))
    assert p1 is not None
    assert p1["status"] == "deletion_pending"

    # 2. Secondary Approval by System Admin
    app_resp = client.post(f"/api/v1/admin/deletion-requests/{req_id}/approve", headers=sa_headers)
    assert app_resp.status_code == 200

    # 3. Verify Biometrics Zeroized
    fps = Database.execute_query("SELECT id FROM fingerprint_templates WHERE patient_id = ?;", (patient_id,))
    irises = Database.execute_query("SELECT id FROM iris_templates WHERE patient_id = ?;", (patient_id,))
    assert len(fps) == 0
    assert len(irises) == 0

    # 4. Verify Deleted Tombstone Status
    p2 = Database.execute_one("SELECT status, full_name FROM patients_cache WHERE id = ?;", (patient_id,))
    assert p2 is not None
    assert p2["status"] == "deleted_tombstone"


def test_admin_staff_management_lifecycle(client, system_admin_token, records_admin_token):
    """
    Tests full staff account management lifecycle:
    1. Create new staff user with initial credentials.
    2. Edit user info (full name, role, email, status).
    3. Update user password and verify login with new password.
    4. Protect self: system admin cannot delete or deactivate own active account.
    5. Delete staff user and verify removal.
    6. Verify RBAC prevents unauthorized roles (records admin) from managing staff.
    """
    import uuid
    uid = uuid.uuid4().hex[:6]
    initial_user = f"nurse_clara_{uid}"
    initial_email = f"clara_{uid}@lifelink.local"
    updated_user = f"lead_clara_{uid}"
    updated_email = f"lead_clara_{uid}@lifelink.local"

    sa_headers = {"Authorization": f"Bearer {system_admin_token}"}
    ra_headers = {"Authorization": f"Bearer {records_admin_token}"}

    # 1. Create new staff member
    new_staff_data = {
        "username": initial_user,
        "email": initial_email,
        "full_name": "Nurse Clara Oswald",
        "role": Roles.CLINICIAN,
        "password": "InitialPassword@123"
    }
    create_resp = client.post("/api/v1/admin/staff", json=new_staff_data, headers=sa_headers)
    assert create_resp.status_code == 201
    create_res = create_resp.get_json()
    assert create_res["status"] == "success"
    staff_id = create_res["staff_id"]

    # Verify user can log in with initial credentials
    login_resp = client.post("/api/v1/auth/login", json={
        "portal": "clinical",
        "username_or_email": initial_user,
        "password": "InitialPassword@123"
    })
    assert login_resp.status_code == 200

    # 2. Update staff user details and reset password
    update_data = {
        "username": updated_user,
        "email": updated_email,
        "full_name": "Lead Nurse Clara Oswald",
        "role": Roles.REGISTRATION_STAFF,
        "is_active": 1,
        "password": "UpdatedPassword@456"
    }
    update_resp = client.put(f"/api/v1/admin/staff/{staff_id}", json=update_data, headers=sa_headers)
    assert update_resp.status_code == 200

    # Verify updated database record
    staff_row = Database.execute_one("SELECT * FROM staff_accounts WHERE id = ?;", (staff_id,))
    assert staff_row is not None
    assert staff_row["username"] == updated_user
    assert staff_row["email"] == updated_email
    assert staff_row["role"] == Roles.REGISTRATION_STAFF

    # Verify old password no longer works
    old_login = client.post("/api/v1/auth/login", json={
        "portal": "hospital",
        "username_or_email": updated_user,
        "password": "InitialPassword@123"
    })
    assert old_login.status_code == 401

    # Verify new password works
    new_login = client.post("/api/v1/auth/login", json={
        "portal": "hospital",
        "username_or_email": updated_user,
        "password": "UpdatedPassword@456"
    })
    assert new_login.status_code == 200

    # 3. Test self-protection: System Admin cannot deactivate own active account
    self_update = client.put("/api/v1/admin/staff/staff-sysadmin-004", json={
        "username": "sysadmin",
        "email": "sysadmin@lifelink.local",
        "full_name": "System Administrator",
        "role": Roles.SYSTEM_ADMIN,
        "is_active": 0
    }, headers=sa_headers)
    assert self_update.status_code == 400
    assert "Cannot deactivate your own" in self_update.get_json()["message"]

    # 4. Test self-protection: System Admin cannot delete own active account
    self_delete = client.delete("/api/v1/admin/staff/staff-sysadmin-004", headers=sa_headers)
    assert self_delete.status_code == 400
    assert "Cannot delete your own" in self_delete.get_json()["message"]

    # 5. Non-admin RBAC check: records admin cannot delete or update staff
    ra_delete = client.delete(f"/api/v1/admin/staff/{staff_id}", headers=ra_headers)
    assert ra_delete.status_code == 403

    # 6. Delete staff account
    del_resp = client.delete(f"/api/v1/admin/staff/{staff_id}", headers=sa_headers)
    assert del_resp.status_code == 200

    # Verify staff account removed from database
    deleted_row = Database.execute_one("SELECT * FROM staff_accounts WHERE id = ?;", (staff_id,))
    assert deleted_row is None
