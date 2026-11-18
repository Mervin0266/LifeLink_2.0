"""
LifeLink 2.0 - Role-Based Access Control (RBAC)
Enforces granular permission scoping, role verification, and login portal validation.
"""

from functools import wraps
from typing import List, Set
from flask import request, jsonify, g
from backend.auth.security import SecurityUtils


class Roles:
    CLINICIAN = "clinician"
    REGISTRATION_STAFF = "registration_staff"
    RECORDS_ADMIN = "records_admin"
    SYSTEM_ADMIN = "system_admin"

    ALL = {CLINICIAN, REGISTRATION_STAFF, RECORDS_ADMIN, SYSTEM_ADMIN}


class Permissions:
    REGISTER_PATIENT = "register_patient"
    RETRIEVE_EMERGENCY = "retrieve_emergency"
    RETRIEVE_CLINICAL = "retrieve_clinical"
    RETRIEVE_DEMOGRAPHICS = "retrieve_demographics"
    UPDATE_CLINICAL = "update_clinical"
    UPDATE_DEMOGRAPHICS = "update_demographics"
    ARCHIVE_PATIENT = "archive_patient"
    REQUEST_DELETION = "request_deletion"
    APPROVE_DELETION = "approve_deletion"
    MANAGE_STAFF = "manage_staff"
    VIEW_AUDIT_LOGS = "view_audit_logs"
    VIEW_DEVICE_HEALTH = "view_device_health"
    MANAGE_SYNC = "manage_sync"


# Role to Permissions Mapping Matrix
ROLE_PERMISSIONS = {
    Roles.CLINICIAN: {
        Permissions.RETRIEVE_EMERGENCY,
        Permissions.RETRIEVE_CLINICAL,
        Permissions.RETRIEVE_DEMOGRAPHICS,
        Permissions.UPDATE_CLINICAL,
        Permissions.REGISTER_PATIENT,
        Permissions.VIEW_DEVICE_HEALTH,
    },
    Roles.REGISTRATION_STAFF: {
        Permissions.REGISTER_PATIENT,
        Permissions.RETRIEVE_DEMOGRAPHICS,
        Permissions.UPDATE_DEMOGRAPHICS,
        Permissions.VIEW_DEVICE_HEALTH,
    },
    Roles.RECORDS_ADMIN: {
        Permissions.RETRIEVE_DEMOGRAPHICS,
        Permissions.UPDATE_DEMOGRAPHICS,
        Permissions.ARCHIVE_PATIENT,
        Permissions.REQUEST_DELETION,
        Permissions.VIEW_AUDIT_LOGS,
        Permissions.VIEW_DEVICE_HEALTH,
        Permissions.MANAGE_SYNC,
    },
    Roles.SYSTEM_ADMIN: {
        Permissions.MANAGE_STAFF,
        Permissions.APPROVE_DELETION,
        Permissions.VIEW_AUDIT_LOGS,
        Permissions.VIEW_DEVICE_HEALTH,
        Permissions.MANAGE_SYNC,
    },
}

# Login Portal Compatibility Mapping
PORTAL_ROLES = {
    "clinical": {Roles.CLINICIAN},
    "hospital": {Roles.REGISTRATION_STAFF},
    "admin": {Roles.RECORDS_ADMIN, Roles.SYSTEM_ADMIN},
}


def get_current_user_and_error():
    """Extracts and verifies JWT token from Authorization header or cookie.
    Returns (payload, error_message).
    """
    auth_header = request.headers.get("Authorization", "")
    token = None
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1]
    elif "lifelink_token" in request.cookies:
        token = request.cookies.get("lifelink_token")

    if not token:
        return None, "Authentication required"

    payload = SecurityUtils.verify_token(token)
    if not payload:
        return None, "Invalid or expired token"

    return payload, None


def get_current_user():
    """Extracts and verifies JWT token from Authorization header or cookie."""
    user, _ = get_current_user_and_error()
    return user


def login_required(f):
    """Requires an authenticated session."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user, err = get_current_user_and_error()
        if not user:
            return jsonify({"status": "error", "message": err or "Authentication required"}), 401
        g.current_user = user
        return f(*args, **kwargs)
    return decorated_function


def require_role(*allowed_roles):
    """Requires the user to have one of the specified roles."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user, err = get_current_user_and_error()
            if not user:
                return jsonify({"status": "error", "message": err or "Authentication required"}), 401
            g.current_user = user
            if user.get("role") not in allowed_roles:
                return jsonify({
                    "status": "error",
                    "message": f"Forbidden: role '{user.get('role')}' lacks permission for this resource"
                }), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator


def require_permission(permission: str):
    """Requires the user to have a specific permission."""
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            user, err = get_current_user_and_error()
            if not user:
                return jsonify({"status": "error", "message": err or "Authentication required"}), 401
            g.current_user = user
            user_role = user.get("role", "")
            user_perms = ROLE_PERMISSIONS.get(user_role, set())
            if permission not in user_perms:
                return jsonify({
                    "status": "error",
                    "message": f"Forbidden: role '{user_role}' lacks permission '{permission}'"
                }), 403
            return f(*args, **kwargs)
        return decorated_function
    return decorator
