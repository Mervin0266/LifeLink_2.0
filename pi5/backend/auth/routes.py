"""
LifeLink 2.0 - Authentication Routes
Endpoints for role-based portal login, logout, and session verification.
"""

from flask import Blueprint, request, jsonify, g
from backend.database.connection import Database
from backend.auth.security import SecurityUtils
from backend.auth.rbac import (
    PORTAL_ROLES,
    ROLE_PERMISSIONS,
    login_required,
    get_current_user
)
from backend.audit.service import AuditService

auth_bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")


@auth_bp.route("/login", methods=["POST"])
def login():
    """
    Role-tailored portal login.
    Request Body:
        portal: 'clinical' | 'hospital' | 'admin'
        username_or_email: string
        password: string
    """
    data = request.get_json() or {}
    portal = data.get("portal", "").strip().lower()
    identifier = (data.get("username_or_email") or data.get("username") or data.get("email") or "").strip()
    password = data.get("password", "")

    if not portal or not identifier or not password:
        return jsonify({
            "status": "error",
            "message": "Portal, username/email, and password are required"
        }), 400

    if portal not in PORTAL_ROLES:
        return jsonify({
            "status": "error",
            "message": f"Invalid login portal: '{portal}'. Must be 'clinical', 'hospital', or 'admin'"
        }), 400

    # Look up staff account by username or email
    query = """
    SELECT id, username, email, full_name, role, password_hash, is_active
    FROM staff_accounts
    WHERE username = ? OR email = ?;
    """
    staff = Database.execute_one(query, (identifier, identifier))

    if not staff:
        AuditService.log(
            action="LOGIN_FAILED",
            target_type="staff",
            target_id=identifier,
            details={"portal": portal, "reason": "user_not_found"}
        )
        return jsonify({"status": "error", "message": "Invalid credentials"}), 401

    if not staff["is_active"]:
        AuditService.log(
            action="LOGIN_BLOCKED",
            target_type="staff",
            target_id=staff["id"],
            details={"portal": portal, "reason": "account_deactivated"}
        )
        return jsonify({"status": "error", "message": "Account has been deactivated"}), 403

    # Verify password hash
    if not SecurityUtils.verify_password(password, staff["password_hash"]):
        AuditService.log(
            action="LOGIN_FAILED",
            target_type="staff",
            target_id=staff["id"],
            details={"portal": portal, "reason": "bad_password"}
        )
        return jsonify({"status": "error", "message": "Invalid credentials"}), 401

    # Verify role compatibility with the requested entrance portal
    allowed_roles = PORTAL_ROLES[portal]
    if staff["role"] not in allowed_roles:
        AuditService.log(
            action="LOGIN_PORTAL_MISMATCH",
            target_type="staff",
            target_id=staff["id"],
            details={
                "portal": portal,
                "user_role": staff["role"],
                "reason": "portal_role_disallowed"
            }
        )
        return jsonify({
            "status": "error",
            "message": f"Account with role '{staff['role']}' is not authorized to log in via the '{portal}' portal."
        }), 403

    # Issue session token
    permissions = list(ROLE_PERMISSIONS.get(staff["role"], []))
    payload = {
        "staff_id": staff["id"],
        "username": staff["username"],
        "full_name": staff["full_name"],
        "role": staff["role"],
        "portal": portal,
    }
    token = SecurityUtils.create_token(payload)

    AuditService.log(
        action="LOGIN_SUCCESS",
        target_type="staff",
        target_id=staff["id"],
        details={"portal": portal, "role": staff["role"]},
        actor_id=staff["id"],
        actor_role=staff["role"]
    )

    response = jsonify({
        "status": "success",
        "message": f"Welcome, {staff['full_name']}",
        "token": token,
        "user": {
            "id": staff["id"],
            "username": staff["username"],
            "full_name": staff["full_name"],
            "role": staff["role"],
            "portal": portal,
            "permissions": permissions,
        }
    })
    response.set_cookie("lifelink_token", token, httponly=True, samesite="Strict")
    return response, 200


@auth_bp.route("/logout", methods=["POST"])
@login_required
def logout():
    """Terminates active session."""
    user = g.current_user
    AuditService.log(
        action="LOGOUT",
        target_type="staff",
        target_id=user["staff_id"],
        actor_id=user["staff_id"],
        actor_role=user["role"]
    )
    response = jsonify({"status": "success", "message": "Successfully logged out"})
    response.delete_cookie("lifelink_token")
    return response, 200


@auth_bp.route("/me", methods=["GET"])
@login_required
def me():
    """Returns current user details and permissions."""
    user = g.current_user
    permissions = list(ROLE_PERMISSIONS.get(user["role"], []))
    return jsonify({
        "status": "success",
        "user": {
            "id": user["staff_id"],
            "username": user["username"],
            "full_name": user["full_name"],
            "role": user["role"],
            "portal": user["portal"],
            "permissions": permissions,
        }
    }), 200
