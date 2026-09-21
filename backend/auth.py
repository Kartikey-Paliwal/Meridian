import os
import secrets
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from fastapi import Request, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from backend.database import get_db_connection, verify_password, hash_password
from backend.audit import log_audit_event

SECRET_KEY = os.getenv("MERIDIAN_SECRET_KEY", "MERIDIAN_SECURE_HMAC_SALT_DEFAULT_2026")
SESSION_COOKIE_NAME = "meridian_session"

# In-memory sliding-window rate limiting: IP or Username -> [list of failure timestamps]
FAILED_ATTEMPTS: Dict[str, List[float]] = {}
MAX_FAILED_ATTEMPTS = 5
LOCKOUT_WINDOW_SECONDS = 300  # 5 minutes

bearer_scheme = HTTPBearer(auto_error=False)

# Username aliases for hackathon demo convenience
USERNAME_ALIASES = {
    "admin": "admin@meridian.health",
    "national_admin": "admin@meridian.health",
    "district_officer": "officer.north@meridian.health",
    "officer_north": "officer.north@meridian.health",
    "officer_south": "officer.south@meridian.health",
    "phc_nurse": "staff.alpha@meridian.health",
    "staff_alpha": "staff.alpha@meridian.health",
    "staff_beta": "staff.beta@meridian.health"
}


def check_rate_limit(identifier: str):
    """Check if identifier (IP or username) is rate limited. Raises 429 if exceeded."""
    now = time.time()
    attempts = FAILED_ATTEMPTS.get(identifier, [])
    # Filter attempts within the window
    attempts = [t for t in attempts if now - t < LOCKOUT_WINDOW_SECONDS]
    FAILED_ATTEMPTS[identifier] = attempts

    if len(attempts) >= MAX_FAILED_ATTEMPTS:
        retry_after = int(LOCKOUT_WINDOW_SECONDS - (now - attempts[0]))
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Please try again in {retry_after} seconds."
        )


def record_failed_attempt(identifier: str):
    now = time.time()
    attempts = FAILED_ATTEMPTS.get(identifier, [])
    attempts.append(now)
    FAILED_ATTEMPTS[identifier] = attempts


def clear_failed_attempts(identifier: str):
    if identifier in FAILED_ATTEMPTS:
        del FAILED_ATTEMPTS[identifier]


def authenticate_user(username_or_email: str, password_raw: str, client_ip: str = "127.0.0.1", remember_me: bool = False) -> Dict[str, Any]:
    """
    Validates user credentials against SQLite database.
    Applies rate limiting, constant-time PBKDF2 hash verification, and audit logging.
    """
    normalized_id = username_or_email.strip().lower()
    canonical_email = USERNAME_ALIASES.get(normalized_id, normalized_id)

    # Rate limit check on both IP and account identifier
    check_rate_limit(client_ip)
    check_rate_limit(canonical_email)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM users WHERE LOWER(email) = ? OR LOWER(employee_id) = ?
    """, (canonical_email, normalized_id))
    user_row = cursor.fetchone()

    if not user_row:
        conn.close()
        record_failed_attempt(client_ip)
        record_failed_attempt(canonical_email)
        log_audit_event(
            user_id="ANONYMOUS",
            user_name=username_or_email,
            role="UNAUTHENTICATED",
            action="LOGIN_ATTEMPT",
            result="FAILURE",
            reason="User account not found"
        )
        raise HTTPException(status_code=401, detail="Invalid email/employee ID or password.")

    user = dict(user_row)

    # Check account status
    if user["account_status"] != "ACTIVE":
        conn.close()
        log_audit_event(
            user_id=user["id"],
            user_name=user["full_name"],
            role=user["role"],
            action="LOGIN_ATTEMPT",
            result="DENIED",
            reason="Account is disabled or deactivated"
        )
        raise HTTPException(status_code=403, detail="This account has been disabled. Please contact your administrator.")

    # Constant-time PBKDF2 hash verification
    if not verify_password(password_raw, user["password_hash"], user["salt"]):
        conn.close()
        record_failed_attempt(client_ip)
        record_failed_attempt(canonical_email)
        log_audit_event(
            user_id=user["id"],
            user_name=user["full_name"],
            role=user["role"],
            action="LOGIN_ATTEMPT",
            result="FAILURE",
            reason="Incorrect password"
        )
        raise HTTPException(status_code=401, detail="Invalid email/employee ID or password.")

    # Successful login: reset rate limit attempts
    clear_failed_attempts(client_ip)
    clear_failed_attempts(canonical_email)

    # Generate secure session token
    session_id = secrets.token_urlsafe(32)
    now = datetime.now()
    duration_days = 7 if remember_me else 1
    expires_at = (now + timedelta(days=duration_days)).isoformat()

    cursor.execute("""
    INSERT INTO sessions (session_id, user_id, created_at, expires_at, remember_me)
    VALUES (?, ?, ?, ?, ?)
    """, (session_id, user["id"], now.isoformat(), expires_at, 1 if remember_me else 0))

    cursor.execute("""
    UPDATE users SET last_login = ?, updated_at = ? WHERE id = ?
    """, (now.isoformat(), now.isoformat(), user["id"]))

    conn.commit()
    conn.close()

    log_audit_event(
        user_id=user["id"],
        user_name=user["full_name"],
        role=user["role"],
        action="LOGIN",
        district_scope=user["assigned_district_id"],
        phc_scope=user["assigned_phc_id"],
        result="SUCCESS",
        reason="User successfully authenticated"
    )

    return {
        "status": "success",
        "session_id": session_id,
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "full_name": user["full_name"],
            "email": user["email"],
            "employee_id": user["employee_id"],
            "role": user["role"],
            "account_status": user["account_status"],
            "assigned_district_id": user["assigned_district_id"],
            "assigned_phc_id": user["assigned_phc_id"],
            "must_change_password": bool(user["must_change_password"]),
            "last_login": user["last_login"]
        }
    }


def destroy_session(session_id: str, user_info: Optional[Dict[str, Any]] = None):
    """Deletes session from database and logs audit event."""
    if not session_id:
        return
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
    conn.commit()
    conn.close()

    if user_info:
        log_audit_event(
            user_id=user_info.get("id", "UNKNOWN"),
            user_name=user_info.get("full_name"),
            role=user_info.get("role", "USER"),
            action="LOGOUT",
            district_scope=user_info.get("assigned_district_id"),
            phc_scope=user_info.get("assigned_phc_id"),
            result="SUCCESS",
            reason="User initiated session termination"
        )


async def get_current_user(
    request: Request,
    auth_header: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)
) -> Dict[str, Any]:
    """
    FastAPI dependency: Resolves authenticated user from HTTP-only cookie or Bearer token.
    Enforces active session, expiry verification, and account status.
    """
    token = None
    # 1. Check HTTP-only cookie
    if SESSION_COOKIE_NAME in request.cookies:
        token = request.cookies.get(SESSION_COOKIE_NAME)
    # 2. Check Authorization Bearer header
    elif auth_header and auth_header.credentials:
        token = auth_header.credentials

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. No active session found."
        )

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT s.session_id, s.expires_at, u.* 
    FROM sessions s
    JOIN users u ON s.user_id = u.id
    WHERE s.session_id = ?
    """, (token,))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session has expired or is invalid. Please log in again."
        )

    session_data = dict(row)

    # Check session expiration
    expires_at = datetime.fromisoformat(session_data["expires_at"])
    if datetime.now() > expires_at:
        destroy_session(token)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired. Please log in again."
        )

    # Check if account is still active
    if session_data["account_status"] != "ACTIVE":
        destroy_session(token)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account has been disabled."
        )

    user_info = {
        "id": session_data["id"],
        "full_name": session_data["full_name"],
        "email": session_data["email"],
        "employee_id": session_data["employee_id"],
        "role": session_data["role"],
        "account_status": session_data["account_status"],
        "assigned_district_id": session_data["assigned_district_id"],
        "assigned_phc_id": session_data["assigned_phc_id"],
        "must_change_password": bool(session_data["must_change_password"]),
        "session_id": token
    }

    # Block access to operational endpoints if password change is pending (except password change route)
    path = request.url.path
    if user_info["must_change_password"] and not (path.endswith("/change-password") or path.endswith("/logout") or path.endswith("/me")):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Temporary password in use. Password change is mandatory before proceeding."
        )

    return user_info


def require_roles(allowed_roles: List[str]):
    """Role-hierarchy guard dependency with normalized string matching."""
    norm_allowed = set()
    for r in allowed_roles:
        norm_allowed.add(r)
        norm_allowed.add(r.upper().replace(" ", "_"))
        norm_allowed.add(r.title().replace("_", " "))

    async def role_checker(current_user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
        u_role = current_user.get("role", "")
        u_norm = u_role.upper().replace(" ", "_")
        if u_role not in norm_allowed and u_norm not in norm_allowed:
            log_audit_event(
                user_id=current_user["id"],
                user_name=current_user["full_name"],
                role=current_user["role"],
                action="PERMISSION_CHECK",
                result="DENIED",
                reason=f"Role '{current_user['role']}' not in allowed roles: {allowed_roles}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: Insufficient permissions for role '{current_user['role']}'."
            )
        return current_user
    return role_checker


def enforce_phc_scope(current_user: Dict[str, Any], phc_id: str):
    """
    Enforces that PHC staff only accesses their assigned PHC,
    and District Officer only accesses PHCs located within their assigned district.
    """
    role = current_user["role"]

    if role == "NATIONAL_ADMIN":
        return  # National Admin has nationwide monitoring visibility

    if role == "PHC_STAFF":
        if current_user["assigned_phc_id"] != phc_id:
            log_audit_event(
                user_id=current_user["id"],
                user_name=current_user["full_name"],
                role=role,
                action="PHC_ACCESS_CHECK",
                target_record=phc_id,
                phc_scope=phc_id,
                result="DENIED",
                reason=f"PHC Staff assigned to '{current_user['assigned_phc_id']}' attempted to access '{phc_id}'"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: You are only authorized to access your assigned facility ({current_user['assigned_phc_id']})."
            )
        return

    if role == "DISTRICT_OFFICER":
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT district_id FROM phcs WHERE id = ?", (phc_id,))
        row = cursor.fetchone()
        conn.close()

        if not row or row["district_id"] != current_user["assigned_district_id"]:
            log_audit_event(
                user_id=current_user["id"],
                user_name=current_user["full_name"],
                role=role,
                action="PHC_ACCESS_CHECK",
                target_record=phc_id,
                district_scope=current_user["assigned_district_id"],
                phc_scope=phc_id,
                result="DENIED",
                reason=f"District Officer assigned to '{current_user['assigned_district_id']}' attempted to access PHC '{phc_id}'"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: Facility '{phc_id}' does not belong to your assigned district ({current_user['assigned_district_id']})."
            )
        return

    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access forbidden.")


def enforce_district_scope(current_user: Dict[str, Any], district_id: str):
    """
    Enforces that District Officers can only view or manage their assigned district.
    """
    role = current_user["role"]
    if role == "NATIONAL_ADMIN":
        return

    if role == "DISTRICT_OFFICER":
        if current_user["assigned_district_id"] != district_id:
            log_audit_event(
                user_id=current_user["id"],
                user_name=current_user["full_name"],
                role=role,
                action="DISTRICT_ACCESS_CHECK",
                target_record=district_id,
                district_scope=current_user["assigned_district_id"],
                result="DENIED",
                reason=f"District Officer assigned to '{current_user['assigned_district_id']}' attempted to access district '{district_id}'"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden: You are only authorized for district ({current_user['assigned_district_id']})."
            )
        return

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Access forbidden: PHC staff cannot access district management."
    )
