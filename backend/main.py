import json
import sqlite3
import os
import secrets
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Query, Request, Response, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from backend.database import get_db_connection, init_db, hash_password, verify_password, get_phc_gis_data
from backend.models import (
    LoginRequest, ChangePasswordRequest, ForgotPasswordRequest, ResetPasswordRequest,
    CreateUserRequest, UpdateUserStatusRequest, AdminOverrideRequest,
    InventoryUpdate, BedStatusUpdate, StaffAttendanceCreate,
    PatientFootfallCreate, TransferActionRequest, CardPunchRequest, StaffActionRequest
)
from backend.forecasting import forecast_demand_linear_regression
from backend.redistribution import generate_redistribution_recommendations
from backend.privacy import encrypt_field, decrypt_field, tokenize_identifier, add_dp_noise
from backend.audit import log_audit_event
from backend.auth import (
    authenticate_user, destroy_session, get_current_user, require_roles,
    enforce_phc_scope, enforce_district_scope, SESSION_COOKIE_NAME
)
from backend.pilot import run_30day_shadow_simulation
from backend.dp_budget import dp_manager
from backend.fhir_adapter import generate_fhir_bundle
from backend.provenance import verify_medicine_batch
from ai.fed_avg import run_federated_averaging

# Initialize DB tables & seed data on startup
init_db()

app = FastAPI(
    title="Meridian - Federated AI Public Health Supply Chain Platform",
    version="2.0.0",
    description="Enterprise RBAC Health Supply Chain Platform with 3-tier hierarchy, strict database-level data isolation, audit logging, and NumPy linear demand forecasting."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------
# AUTHENTICATION ENDPOINTS
# ---------------------------------------------------------

@app.post("/api/auth/login", tags=["0. Authentication"])
def login_endpoint(req: LoginRequest, request: Request, response: Response):
    client_ip = request.client.host if request.client else "127.0.0.1"
    res = authenticate_user(req.username, req.password, client_ip=client_ip, remember_me=req.remember_me)
    
    max_age = 7 * 86400 if req.remember_me else 86400
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=res["session_id"],
        httponly=True,
        samesite="lax",
        max_age=max_age,
        path="/"
    )
    return res


@app.post("/api/auth/logout", tags=["0. Authentication"])
def logout_endpoint(response: Response, current_user: Dict[str, Any] = Depends(get_current_user)):
    destroy_session(current_user["session_id"], user_info=current_user)
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return {"status": "success", "message": "Successfully logged out."}


@app.get("/api/auth/me", tags=["0. Authentication"])
def get_current_user_profile(current_user: Dict[str, Any] = Depends(get_current_user)):
    return current_user


@app.post("/api/auth/change-password", tags=["0. Authentication"])
def change_password_endpoint(req: ChangePasswordRequest, current_user: Dict[str, Any] = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash, salt FROM users WHERE id = ?", (current_user["id"],))
    row = cursor.fetchone()
    
    if not row or not verify_password(req.old_password, row["password_hash"], row["salt"]):
        conn.close()
        log_audit_event(
            user_id=current_user["id"],
            user_name=current_user["full_name"],
            role=current_user["role"],
            action="PASSWORD_CHANGE",
            result="FAILURE",
            reason="Incorrect current password provided"
        )
        raise HTTPException(status_code=400, detail="Current password does not match records.")

    new_hash, new_salt = hash_password(req.new_password)
    now_str = datetime.now().isoformat()
    cursor.execute("""
    UPDATE users 
    SET password_hash = ?, salt = ?, must_change_password = 0, updated_at = ?
    WHERE id = ?
    """, (new_hash, new_salt, now_str, current_user["id"]))
    conn.commit()
    conn.close()

    log_audit_event(
        user_id=current_user["id"],
        user_name=current_user["full_name"],
        role=current_user["role"],
        action="PASSWORD_CHANGE",
        district_scope=current_user["assigned_district_id"],
        phc_scope=current_user["assigned_phc_id"],
        result="SUCCESS",
        reason="Password changed successfully; must_change_password cleared"
    )
    return {"status": "success", "message": "Password updated successfully."}


@app.post("/api/auth/forgot-password", tags=["0. Authentication"])
def forgot_password_endpoint(req: ForgotPasswordRequest):
    email_clean = req.email.strip().lower()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, full_name, role FROM users WHERE LOWER(email) = ?", (email_clean,))
    user = cursor.fetchone()

    if not user:
        conn.close()
        return {"status": "success", "message": "If the account exists, a reset token has been generated."}

    token = secrets.token_urlsafe(24)
    now = datetime.now()
    expires_at = (now + timedelta(minutes=15)).isoformat()

    cursor.execute("""
    INSERT INTO password_reset_tokens (token, user_id, expires_at, used, created_at)
    VALUES (?, ?, ?, 0, ?)
    """, (token, user["id"], expires_at, now.isoformat()))
    conn.commit()
    conn.close()

    log_audit_event(
        user_id=user["id"],
        user_name=user["full_name"],
        role=user["role"],
        action="PASSWORD_RESET_TOKEN_REQUEST",
        result="SUCCESS",
        reason="15-minute password reset token generated"
    )

    return {
        "status": "success",
        "message": "Password reset token generated (valid for 15 minutes).",
        "demo_reset_token": token
    }


@app.post("/api/auth/reset-password", tags=["0. Authentication"])
def reset_password_endpoint(req: ResetPasswordRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    SELECT r.token, r.user_id, r.expires_at, r.used, u.full_name, u.role 
    FROM password_reset_tokens r
    JOIN users u ON r.user_id = u.id
    WHERE r.token = ? AND r.used = 0
    """, (req.token,))
    row = cursor.fetchone()

    if not row:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid or previously used reset token.")

    if datetime.now() > datetime.fromisoformat(row["expires_at"]):
        conn.close()
        raise HTTPException(status_code=400, detail="Reset token has expired.")

    new_hash, new_salt = hash_password(req.new_password)
    now_str = datetime.now().isoformat()

    cursor.execute("""
    UPDATE users SET password_hash = ?, salt = ?, must_change_password = 0, updated_at = ? WHERE id = ?
    """, (new_hash, new_salt, now_str, row["user_id"]))
    cursor.execute("UPDATE password_reset_tokens SET used = 1 WHERE token = ?", (req.token,))
    conn.commit()
    conn.close()

    log_audit_event(
        user_id=row["user_id"],
        user_name=row["full_name"],
        role=row["role"],
        action="PASSWORD_RESET_COMPLETED",
        result="SUCCESS",
        reason="Password reset completed via verified token"
    )

    return {"status": "success", "message": "Password has been successfully reset. Please log in with your new password."}


# ---------------------------------------------------------
# DISTRICTS & PHCS DIRECTORY
# ---------------------------------------------------------

@app.get("/api/districts", tags=["Directory"])
def get_districts(current_user: Dict[str, Any] = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()

    if current_user["role"] == "NATIONAL_ADMIN":
        cursor.execute("SELECT * FROM districts ORDER BY name ASC")
    elif current_user["role"] == "DISTRICT_OFFICER":
        cursor.execute("SELECT * FROM districts WHERE id = ?", (current_user["assigned_district_id"],))
    else: # PHC Staff
        cursor.execute("""
        SELECT d.* FROM districts d
        JOIN phcs p ON p.district_id = d.id
        WHERE p.id = ?
        """, (current_user["assigned_phc_id"],))

    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


@app.get("/api/phcs", tags=["Directory"])
def get_phcs(
    district_id: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    conn = get_db_connection()
    cursor = conn.cursor()

    if current_user["role"] == "NATIONAL_ADMIN":
        if district_id:
            cursor.execute("SELECT * FROM phcs WHERE district_id = ? ORDER BY name ASC", (district_id,))
        else:
            cursor.execute("SELECT * FROM phcs ORDER BY name ASC")
    elif current_user["role"] == "DISTRICT_OFFICER":
        cursor.execute("SELECT * FROM phcs WHERE district_id = ? ORDER BY name ASC", (current_user["assigned_district_id"],))
    else: # PHC Staff
        cursor.execute("SELECT * FROM phcs WHERE id = ?", (current_user["assigned_phc_id"],))

    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


# ---------------------------------------------------------
# USER MANAGEMENT & ACCESS CONTROL
# ---------------------------------------------------------

@app.get("/api/users", tags=["User Management"])
def get_users_list(current_user: Dict[str, Any] = Depends(require_roles(["NATIONAL_ADMIN", "DISTRICT_OFFICER"]))):
    conn = get_db_connection()
    cursor = conn.cursor()

    if current_user["role"] == "NATIONAL_ADMIN":
        cursor.execute("""
        SELECT id, full_name, email, employee_id, role, account_status, 
               assigned_district_id, assigned_phc_id, must_change_password, 
               last_login, created_at, updated_at
        FROM users ORDER BY created_at DESC
        """)
    else: # District Officer: view only PHC staff within their district
        cursor.execute("""
        SELECT id, full_name, email, employee_id, role, account_status, 
               assigned_district_id, assigned_phc_id, must_change_password, 
               last_login, created_at, updated_at
        FROM users 
        WHERE assigned_district_id = ? AND role = 'PHC_STAFF'
        ORDER BY created_at DESC
        """, (current_user["assigned_district_id"],))

    users = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return users


@app.post("/api/users", tags=["User Management"])
def create_user(req: CreateUserRequest, current_user: Dict[str, Any] = Depends(require_roles(["NATIONAL_ADMIN", "DISTRICT_OFFICER"]))):
    # Enforce role hierarchy in creation:
    # National Admin can create District Officers
    # District Officer can create PHC Staff within their district
    if current_user["role"] == "DISTRICT_OFFICER":
        if req.role != "PHC_STAFF":
            raise HTTPException(status_code=403, detail="District Officers may only create PHC Staff accounts.")
        # Force district assignment to the officer's district
        req.assigned_district_id = current_user["assigned_district_id"]
        # Verify assigned_phc_id belongs to officer's district
        if req.assigned_phc_id:
            conn = get_db_connection()
            c = conn.cursor()
            c.execute("SELECT district_id FROM phcs WHERE id = ?", (req.assigned_phc_id,))
            p = c.fetchone()
            conn.close()
            if not p or p["district_id"] != current_user["assigned_district_id"]:
                raise HTTPException(status_code=400, detail="Target PHC does not belong to your assigned district.")

    if current_user["role"] == "NATIONAL_ADMIN":
        if req.role not in ["DISTRICT_OFFICER", "PHC_STAFF"]:
            raise HTTPException(status_code=400, detail="Invalid role specified.")

    new_id = f"USR-{secrets.token_hex(4).upper()}"
    raw_pass = req.initial_password or "Meridian@2026"
    pwd_hash, salt = hash_password(raw_pass)
    now_str = datetime.now().isoformat()

    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
        INSERT INTO users (
            id, full_name, email, employee_id, password_hash, salt, role,
            account_status, assigned_district_id, assigned_phc_id,
            must_change_password, created_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, 1, ?, ?, ?)
        """, (
            new_id, req.full_name, req.email.strip().lower(),
            req.employee_id or f"EMP-{new_id}", pwd_hash, salt,
            req.role, req.assigned_district_id, req.assigned_phc_id,
            current_user["id"], now_str, now_str
        ))
        conn.commit()
    except sqlite3.IntegrityError as e:
        conn.close()
        raise HTTPException(status_code=400, detail="An account with this email or employee ID already exists.")
    conn.close()

    log_audit_event(
        user_id=current_user["id"],
        user_name=current_user["full_name"],
        role=current_user["role"],
        action="USER_CREATED",
        target_record=new_id,
        district_scope=req.assigned_district_id,
        phc_scope=req.assigned_phc_id,
        result="SUCCESS",
        reason=f"Created new {req.role} account ({req.email})"
    )

    return {
        "status": "success",
        "message": f"User account created for {req.full_name}. Temporary password set (change required on first login).",
        "user_id": new_id
    }


@app.patch("/api/users/{user_id}/status", tags=["User Management"])
def update_user_status(
    user_id: str,
    req: UpdateUserStatusRequest,
    current_user: Dict[str, Any] = Depends(require_roles(["NATIONAL_ADMIN", "DISTRICT_OFFICER"]))
):
    if user_id == current_user["id"]:
        raise HTTPException(status_code=400, detail="You cannot modify the status of your own account.")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
    target = cursor.fetchone()

    if not target:
        conn.close()
        raise HTTPException(status_code=404, detail="Target user not found.")

    target_user = dict(target)

    # Permission check
    if current_user["role"] == "DISTRICT_OFFICER":
        if target_user["role"] != "PHC_STAFF" or target_user["assigned_district_id"] != current_user["assigned_district_id"]:
            conn.close()
            raise HTTPException(status_code=403, detail="You may only manage status of PHC Staff within your assigned district.")

    if target_user["role"] == "NATIONAL_ADMIN":
        conn.close()
        raise HTTPException(status_code=403, detail="National Admin accounts cannot be deactivated through this interface.")

    now_str = datetime.now().isoformat()
    cursor.execute("UPDATE users SET account_status = ?, updated_at = ? WHERE id = ?", (req.account_status, now_str, user_id))
    
    # If disabling, immediately invalidate any active sessions
    if req.account_status == "DISABLED":
        cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))

    conn.commit()
    conn.close()

    log_audit_event(
        user_id=current_user["id"],
        user_name=current_user["full_name"],
        role=current_user["role"],
        action="USER_STATUS_UPDATED",
        target_record=user_id,
        district_scope=target_user["assigned_district_id"],
        phc_scope=target_user["assigned_phc_id"],
        result="SUCCESS",
        reason=f"Account status set to {req.account_status}"
    )

    return {"status": "success", "message": f"User {target_user['full_name']} is now {req.account_status}."}


# ---------------------------------------------------------
# AUDIT LOGS ENDPOINTS
# ---------------------------------------------------------

@app.get("/api/audit-logs", tags=["Audit Logs"])
def get_audit_logs(
    limit: int = 100,
    current_user: Dict[str, Any] = Depends(require_roles(["NATIONAL_ADMIN", "DISTRICT_OFFICER"]))
):
    conn = get_db_connection()
    cursor = conn.cursor()

    if current_user["role"] == "NATIONAL_ADMIN":
        cursor.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,))
    else: # District Officer: only view district-level events
        cursor.execute("""
        SELECT * FROM audit_logs 
        WHERE district_scope = ? OR user_id = ?
        ORDER BY id DESC LIMIT ?
        """, (current_user["assigned_district_id"], current_user["id"], limit))

    logs = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return logs


# ---------------------------------------------------------
# 1. SCOPED CRUD - INVENTORY
# ---------------------------------------------------------

@app.get("/api/inventory", tags=["1. CRUD - Inventory"])
def get_inventory(
    phc_id: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    conn = get_db_connection()
    cursor = conn.cursor()

    # Enforce data isolation
    if current_user["role"] == "PHC_STAFF":
        target_phc = current_user["assigned_phc_id"]
        cursor.execute("SELECT * FROM medicine_inventory WHERE phc_id = ?", (target_phc,))
    elif current_user["role"] == "DISTRICT_OFFICER":
        dist_id = current_user["assigned_district_id"]
        if phc_id:
            enforce_phc_scope(current_user, phc_id)
            cursor.execute("SELECT * FROM medicine_inventory WHERE phc_id = ?", (phc_id,))
        else:
            cursor.execute("SELECT * FROM medicine_inventory WHERE district_id = ?", (dist_id,))
    else: # NATIONAL_ADMIN
        if phc_id:
            cursor.execute("SELECT * FROM medicine_inventory WHERE phc_id = ?", (phc_id,))
        else:
            cursor.execute("SELECT * FROM medicine_inventory")

    rows = cursor.fetchall()
    conn.close()

    result = []
    for r in rows:
        item = dict(r)
        item["daily_usage_history"] = json.loads(item["daily_usage_history"]) if item["daily_usage_history"] else []
        result.append(item)
    return result


@app.post("/api/inventory/update", tags=["1. CRUD - Inventory"])
def update_inventory(
    item: InventoryUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    # Enforce PHC Scope
    enforce_phc_scope(current_user, item.phc_id)

    # If National Admin: require explicit confirmation & written override reason
    if current_user["role"] == "NATIONAL_ADMIN":
        if not item.override_reason or len(item.override_reason.strip()) < 3:
            raise HTTPException(
                status_code=400,
                detail="National Admin administrative override requires explicit confirmation and a written reason."
            )
    elif current_user["role"] == "DISTRICT_OFFICER":
        raise HTTPException(
            status_code=403,
            detail="District Officers monitor inventory and approve transfers; direct stock modifications must be recorded by PHC Staff."
        )

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM medicine_inventory WHERE phc_id = ? AND medicine_name = ?", (item.phc_id, item.medicine_name))
    row = cursor.fetchone()
    now_str = datetime.now().isoformat()

    # Determine district_id for table row
    cursor.execute("SELECT district_id FROM phcs WHERE id = ?", (item.phc_id,))
    phc_meta = cursor.fetchone()
    d_id = phc_meta["district_id"] if phc_meta else "DIST-NORTH"

    if row:
        history = json.loads(row["daily_usage_history"]) if row["daily_usage_history"] else []
        if item.daily_consumption is not None:
            history.append(item.daily_consumption)
            if len(history) > 14:
                history.pop(0)

        cursor.execute("""
        UPDATE medicine_inventory
        SET quantity = ?, par_level = ?, daily_usage_history = ?, district_id = ?, updated_at = ?
        WHERE phc_id = ? AND medicine_name = ?
        """, (item.quantity, item.par_level or row["par_level"], json.dumps(history), d_id, now_str, item.phc_id, item.medicine_name))
    else:
        history = [5] * 7
        if item.daily_consumption is not None:
            history.append(item.daily_consumption)
        cursor.execute("""
        INSERT INTO medicine_inventory (phc_id, district_id, medicine_name, quantity, par_level, daily_usage_history, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (item.phc_id, d_id, item.medicine_name, item.quantity, item.par_level or 100, json.dumps(history), now_str))

    conn.commit()
    conn.close()

    is_override = current_user["role"] == "NATIONAL_ADMIN"
    log_audit_event(
        user_id=current_user["id"],
        user_name=current_user["full_name"],
        role=current_user["role"],
        action="INVENTORY_OVERRIDE" if is_override else "INVENTORY_UPDATE",
        target_record=f"{item.phc_id} / {item.medicine_name}",
        district_scope=d_id,
        phc_scope=item.phc_id,
        result="OVERRIDDEN" if is_override else "SUCCESS",
        reason=item.override_reason if is_override else "Routine PHC stock recording",
        details={"quantity": item.quantity, "par_level": item.par_level}
    )

    return {
        "status": "success",
        "message": f"Updated {item.medicine_name} for {item.phc_id} to {item.quantity} units.",
        "override_logged": is_override
    }


# ---------------------------------------------------------
# 2. SCOPED CRUD - BEDS
# ---------------------------------------------------------

@app.get("/api/beds", tags=["1. CRUD - Beds"])
def get_beds(
    phc_id: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    conn = get_db_connection()
    cursor = conn.cursor()

    if current_user["role"] == "PHC_STAFF":
        cursor.execute("SELECT * FROM bed_status WHERE phc_id = ?", (current_user["assigned_phc_id"],))
    elif current_user["role"] == "DISTRICT_OFFICER":
        dist_id = current_user["assigned_district_id"]
        if phc_id:
            enforce_phc_scope(current_user, phc_id)
            cursor.execute("SELECT * FROM bed_status WHERE phc_id = ?", (phc_id,))
        else:
            cursor.execute("SELECT * FROM bed_status WHERE district_id = ?", (dist_id,))
    else: # NATIONAL_ADMIN
        if phc_id:
            cursor.execute("SELECT * FROM bed_status WHERE phc_id = ?", (phc_id,))
        else:
            cursor.execute("SELECT * FROM bed_status")

    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


@app.post("/api/beds/update", tags=["1. CRUD - Beds"])
def update_beds(
    data: BedStatusUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    enforce_phc_scope(current_user, data.phc_id)

    if current_user["role"] == "NATIONAL_ADMIN":
        if not data.override_reason or len(data.override_reason.strip()) < 3:
            raise HTTPException(status_code=400, detail="Administrative bed override requires explicit written reason.")
    elif current_user["role"] == "DISTRICT_OFFICER":
        raise HTTPException(status_code=403, detail="District Officers monitor bed occupancy; updates are recorded by PHC Staff.")

    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()

    cursor.execute("SELECT district_id FROM phcs WHERE id = ?", (data.phc_id,))
    phc_meta = cursor.fetchone()
    d_id = phc_meta["district_id"] if phc_meta else "DIST-NORTH"

    cursor.execute("""
    INSERT INTO bed_status (phc_id, district_id, total_beds, occupied_beds, updated_at)
    VALUES (?, ?, ?, ?, ?)
    ON CONFLICT(phc_id) DO UPDATE SET
        total_beds = excluded.total_beds,
        occupied_beds = excluded.occupied_beds,
        district_id = excluded.district_id,
        updated_at = excluded.updated_at
    """, (data.phc_id, d_id, data.total_beds, data.occupied_beds, now_str))

    conn.commit()
    conn.close()

    is_override = current_user["role"] == "NATIONAL_ADMIN"
    log_audit_event(
        user_id=current_user["id"],
        user_name=current_user["full_name"],
        role=current_user["role"],
        action="BED_OVERRIDE" if is_override else "BED_UPDATE",
        target_record=data.phc_id,
        district_scope=d_id,
        phc_scope=data.phc_id,
        result="OVERRIDDEN" if is_override else "SUCCESS",
        reason=data.override_reason if is_override else "Daily bed status reconciliation",
        details={"total_beds": data.total_beds, "occupied_beds": data.occupied_beds}
    )

    return {"status": "success", "message": f"Updated bed status for {data.phc_id}"}


# ---------------------------------------------------------
# 3. SCOPED CRUD - STAFF & ATTENDANCE
# ---------------------------------------------------------

@app.get("/api/staff/members", tags=["1. CRUD - Staff"])
def get_staff_members(
    phc_id: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    conn = get_db_connection()
    cursor = conn.cursor()

    if current_user["role"] == "PHC_STAFF":
        cursor.execute("SELECT * FROM staff_members WHERE phc_id = ?", (current_user["assigned_phc_id"],))
    elif current_user["role"] == "DISTRICT_OFFICER":
        if phc_id:
            enforce_phc_scope(current_user, phc_id)
            cursor.execute("SELECT * FROM staff_members WHERE phc_id = ?", (phc_id,))
        else:
            cursor.execute("SELECT * FROM staff_members WHERE district_id = ?", (current_user["assigned_district_id"],))
    else:
        if phc_id:
            cursor.execute("SELECT * FROM staff_members WHERE phc_id = ?", (phc_id,))
        else:
            cursor.execute("SELECT * FROM staff_members")

    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


@app.get("/api/staff", tags=["1. CRUD - Staff"])
def get_staff_attendance(
    phc_id: Optional[str] = None,
    date: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    conn = get_db_connection()
    cursor = conn.cursor()
    query = "SELECT * FROM staff_attendance WHERE 1=1"
    params = []

    if current_user["role"] == "PHC_STAFF":
        query += " AND phc_id = ?"
        params.append(current_user["assigned_phc_id"])
    elif current_user["role"] == "DISTRICT_OFFICER":
        if phc_id:
            enforce_phc_scope(current_user, phc_id)
            query += " AND phc_id = ?"
            params.append(phc_id)
        else:
            query += " AND district_id = ?"
            params.append(current_user["assigned_district_id"])
    else: # National Admin
        if phc_id:
            query += " AND phc_id = ?"
            params.append(phc_id)

    if date:
        query += " AND date = ?"
        params.append(date)

    query += " ORDER BY id DESC"
    cursor.execute(query, params)
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


@app.post("/api/staff/card-punch", tags=["1. CRUD - Staff"])
def process_rfid_punch(
    data: CardPunchRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    phc_target = data.phc_id or current_user.get("assigned_phc_id") or "PHC-001"
    enforce_phc_scope(current_user, phc_target)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM staff_members WHERE card_uid = ? AND phc_id = ?", (data.card_uid, phc_target))
    member_row = cursor.fetchone()

    if not member_row:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Card UID '{data.card_uid}' not recognized for facility {phc_target}.")

    member = dict(member_row)
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%I:%M %p")

    cursor.execute("""
    SELECT * FROM staff_attendance WHERE staff_id = ? AND date = ? ORDER BY id DESC LIMIT 1
    """, (member["staff_id"], date_str))
    existing = cursor.fetchone()

    if existing and existing["status"] == "CHECKED_IN":
        # Process check-out
        cursor.execute("""
        UPDATE staff_attendance
        SET status = 'CHECKED_OUT', punch_out_time = ?, updated_at = ?
        WHERE id = ?
        """, (time_str, now.isoformat(), existing["id"]))
        action_desc = "CHECKED_OUT"
    else:
        # Process check-in
        enc_id = encrypt_field(member["staff_id"])
        tok_id = tokenize_identifier(member["staff_id"])
        cursor.execute("SELECT district_id FROM phcs WHERE id = ?", (phc_target,))
        d_row = cursor.fetchone()
        d_id = d_row["district_id"] if d_row else "DIST-NORTH"

        cursor.execute("""
        INSERT INTO staff_attendance (
            phc_id, district_id, staff_id, staff_name, role, card_uid, 
            staff_id_encrypted, staff_token, present, status, verification_method, 
            punch_in_time, date, operator, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, 'CHECKED_IN', ?, ?, ?, ?, ?)
        """, (
            phc_target, d_id, member["staff_id"], member["name"], member["role"],
            data.card_uid, enc_id, tok_id, data.verification_method or "RFID Card Punch",
            time_str, date_str, data.operator or "TERMINAL-GATE1", now.isoformat()
        ))
        action_desc = "CHECKED_IN"

    conn.commit()
    conn.close()

    log_audit_event(
        user_id=current_user["id"],
        user_name=current_user["full_name"],
        role=current_user["role"],
        action="RFID_PUNCH",
        target_record=f"{phc_target} / {member['staff_id']}",
        phc_scope=phc_target,
        result="SUCCESS",
        reason=f"RFID tap: {action_desc} at {time_str}"
    )

    return {
        "status": "success",
        "action": action_desc,
        "staff_name": member["name"],
        "role": member["role"],
        "timestamp": time_str
    }


@app.post("/api/staff/log", tags=["1. CRUD - Staff"])
def log_staff_attendance_manual(
    entry: StaffAttendanceCreate,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    enforce_phc_scope(current_user, entry.phc_id)

    if current_user["role"] == "NATIONAL_ADMIN":
        if not entry.override_reason or len(entry.override_reason.strip()) < 3:
            raise HTTPException(status_code=400, detail="Administrative attendance override requires explicit written reason.")
    elif current_user["role"] == "DISTRICT_OFFICER":
        raise HTTPException(status_code=403, detail="District Officers monitor attendance; modifications are managed by PHC Staff.")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT district_id FROM phcs WHERE id = ?", (entry.phc_id,))
    d_row = cursor.fetchone()
    d_id = d_row["district_id"] if d_row else "DIST-NORTH"

    today_str = entry.date or datetime.now().strftime("%Y-%m-%d")
    now_iso = datetime.now().isoformat()
    enc_id = encrypt_field(entry.staff_id)
    tok_id = tokenize_identifier(entry.staff_id)

    cursor.execute("""
    INSERT INTO staff_attendance (
        phc_id, district_id, staff_id, staff_name, role, card_uid, 
        staff_id_encrypted, staff_token, present, status, verification_method, 
        punch_in_time, punch_out_time, date, shift, department, remarks, operator, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        entry.phc_id, d_id, entry.staff_id, entry.staff_name or entry.staff_id,
        entry.role or "Staff", entry.card_uid, enc_id, tok_id, entry.present,
        entry.status or "CHECKED_IN", entry.verification_method or "Manual Kiosk",
        entry.punch_in_time or "08:30 AM", entry.punch_out_time, today_str,
        entry.shift or "Morning Shift", entry.department or "General",
        entry.remarks, entry.operator or current_user["full_name"], now_iso
    ))
    conn.commit()
    conn.close()

    is_override = current_user["role"] == "NATIONAL_ADMIN"
    log_audit_event(
        user_id=current_user["id"],
        user_name=current_user["full_name"],
        role=current_user["role"],
        action="ATTENDANCE_OVERRIDE" if is_override else "ATTENDANCE_LOG",
        target_record=f"{entry.phc_id} / {entry.staff_id}",
        district_scope=d_id,
        phc_scope=entry.phc_id,
        result="OVERRIDDEN" if is_override else "SUCCESS",
        reason=entry.override_reason if is_override else "Manual staff attendance submission"
    )

    return {"status": "success", "message": f"Attendance logged for {entry.staff_id}"}


@app.post("/api/staff/action", tags=["1. CRUD - Staff"])
def perform_staff_action(
    req: StaffActionRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    phc_target = req.phc_id or current_user.get("assigned_phc_id") or "PHC-001"
    enforce_phc_scope(current_user, phc_target)

    if current_user["role"] == "NATIONAL_ADMIN":
        if not req.override_reason or len(req.override_reason.strip()) < 3:
            raise HTTPException(status_code=400, detail="Administrative staff action requires explicit written override reason.")
    elif current_user["role"] == "DISTRICT_OFFICER":
        raise HTTPException(status_code=403, detail="District Officers cannot alter PHC staff shifts or operational status.")

    conn = get_db_connection()
    cursor = conn.cursor()
    today_str = datetime.now().strftime("%Y-%m-%d")
    now_iso = datetime.now().isoformat()
    time_str = datetime.now().strftime("%I:%M %p")

    cursor.execute("""
    SELECT * FROM staff_attendance WHERE staff_id = ? AND date = ? ORDER BY id DESC LIMIT 1
    """, (req.staff_id, today_str))
    row = cursor.fetchone()

    status_map = {
        "CHECK_OUT": "CHECKED_OUT",
        "CHECK_IN": "CHECKED_IN",
        "MARK_LEAVE": "ON_LEAVE",
        "MARK_ABSENT": "ABSENT"
    }
    new_status = status_map.get(req.action, "CHECKED_IN")
    present_val = 0 if new_status in ["ABSENT", "ON_LEAVE"] else 1

    if row:
        cursor.execute("""
        UPDATE staff_attendance
        SET status = ?, present = ?, remarks = ?, operator = ?, updated_at = ?
        WHERE id = ?
        """, (new_status, present_val, req.remarks, req.operator or current_user["full_name"], now_iso, row["id"]))
    else:
        cursor.execute("SELECT * FROM staff_members WHERE staff_id = ?", (req.staff_id,))
        m = cursor.fetchone()
        name = m["name"] if m else req.staff_id
        role = m["role"] if m else "Staff"
        enc_id = encrypt_field(req.staff_id)
        tok_id = tokenize_identifier(req.staff_id)

        cursor.execute("SELECT district_id FROM phcs WHERE id = ?", (phc_target,))
        d_meta = cursor.fetchone()
        d_id = d_meta["district_id"] if d_meta else "DIST-NORTH"

        cursor.execute("""
        INSERT INTO staff_attendance (
            phc_id, district_id, staff_id, staff_name, role, staff_id_encrypted, staff_token,
            present, status, verification_method, date, remarks, operator, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'Supervisor Action', ?, ?, ?, ?)
        """, (
            phc_target, d_id, req.staff_id, name, role, enc_id, tok_id,
            present_val, new_status, today_str, req.remarks, req.operator or current_user["full_name"], now_iso
        ))

    conn.commit()
    conn.close()

    is_override = current_user["role"] == "NATIONAL_ADMIN"
    log_audit_event(
        user_id=current_user["id"],
        user_name=current_user["full_name"],
        role=current_user["role"],
        action=f"STAFF_ACTION_{req.action}",
        target_record=f"{phc_target} / {req.staff_id}",
        phc_scope=phc_target,
        result="OVERRIDDEN" if is_override else "SUCCESS",
        reason=req.override_reason if is_override else req.remarks
    )

    return {"status": "success", "message": f"Updated {req.staff_id} to {new_status}."}


# ---------------------------------------------------------
# 4. SCOPED CRUD - FOOTFALL
# ---------------------------------------------------------

@app.get("/api/footfall", tags=["1. CRUD - Footfall"])
def get_patient_footfall(
    phc_id: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    conn = get_db_connection()
    cursor = conn.cursor()

    if current_user["role"] == "PHC_STAFF":
        cursor.execute("SELECT * FROM patient_footfall WHERE phc_id = ? ORDER BY date ASC", (current_user["assigned_phc_id"],))
    elif current_user["role"] == "DISTRICT_OFFICER":
        if phc_id:
            enforce_phc_scope(current_user, phc_id)
            cursor.execute("SELECT * FROM patient_footfall WHERE phc_id = ? ORDER BY date ASC", (phc_id,))
        else:
            cursor.execute("SELECT * FROM patient_footfall WHERE district_id = ? ORDER BY date ASC", (current_user["assigned_district_id"],))
    else:
        if phc_id:
            cursor.execute("SELECT * FROM patient_footfall WHERE phc_id = ? ORDER BY date ASC", (phc_id,))
        else:
            cursor.execute("SELECT * FROM patient_footfall ORDER BY date ASC")

    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


@app.post("/api/footfall/log", tags=["1. CRUD - Footfall"])
def log_footfall(
    data: PatientFootfallCreate,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    enforce_phc_scope(current_user, data.phc_id)

    if current_user["role"] == "NATIONAL_ADMIN":
        if not data.override_reason or len(data.override_reason.strip()) < 3:
            raise HTTPException(status_code=400, detail="Administrative footfall override requires written reason.")
    elif current_user["role"] == "DISTRICT_OFFICER":
        raise HTTPException(status_code=403, detail="District Officers cannot directly modify PHC footfall counts.")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT district_id FROM phcs WHERE id = ?", (data.phc_id,))
    d_row = cursor.fetchone()
    d_id = d_row["district_id"] if d_row else "DIST-NORTH"

    cursor.execute("""
    INSERT INTO patient_footfall (phc_id, district_id, date, count)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(phc_id, date) DO UPDATE SET count = excluded.count, district_id = excluded.district_id
    """, (data.phc_id, d_id, data.date, data.count))
    conn.commit()
    conn.close()

    is_override = current_user["role"] == "NATIONAL_ADMIN"
    log_audit_event(
        user_id=current_user["id"],
        user_name=current_user["full_name"],
        role=current_user["role"],
        action="FOOTFALL_OVERRIDE" if is_override else "FOOTFALL_LOG",
        target_record=f"{data.phc_id} / {data.date}",
        district_scope=d_id,
        phc_scope=data.phc_id,
        result="OVERRIDDEN" if is_override else "SUCCESS",
        reason=data.override_reason if is_override else f"Recorded {data.count} OPD visits"
    )

    return {"status": "success", "message": f"Logged footfall {data.count} for {data.phc_id} on {data.date}"}


# ---------------------------------------------------------
# 5. DASHBOARDS (ROLE-SPECIFIC & SCOPED)
# ---------------------------------------------------------

@app.get("/api/dashboard/phc/{phc_id}", tags=["2. PHC Dashboard"])
def get_phc_dashboard(
    phc_id: str,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Returns complete PHC Edge Dashboard payload.
    Enforces that PHC staff only accesses their own facility,
    District Officer only accesses facilities inside their district,
    and National Admin has read-only/oversight capability.
    """
    enforce_phc_scope(current_user, phc_id)

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM medicine_inventory WHERE phc_id = ?", (phc_id,))
    inventory_rows = cursor.fetchall()
    
    inventory = []
    for r in inventory_rows:
        item = dict(r)
        history = json.loads(item["daily_usage_history"]) if item["daily_usage_history"] else []
        forecast = forecast_demand_linear_regression(history, item["quantity"], item["par_level"])
        item["daily_usage_history"] = history
        item["forecast"] = forecast
        inventory.append(item)

    cursor.execute("SELECT * FROM bed_status WHERE phc_id = ?", (phc_id,))
    bed_row = cursor.fetchone()
    bed_data = dict(bed_row) if bed_row else {"phc_id": phc_id, "total_beds": 0, "occupied_beds": 0}

    cursor.execute("SELECT * FROM staff_attendance WHERE phc_id = ? ORDER BY id DESC", (phc_id,))
    staff_rows = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM staff_members WHERE phc_id = ?", (phc_id,))
    staff_members = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM patient_footfall WHERE phc_id = ? ORDER BY date ASC", (phc_id,))
    footfall_rows = [dict(r) for r in cursor.fetchall()]

    # Fetch active and recent transfers involving this PHC
    cursor.execute("""
    SELECT * FROM redistribution_transfers 
    WHERE source_phc = ? OR target_phc = ?
    ORDER BY id DESC LIMIT 10
    """, (phc_id, phc_id))
    transfers = [dict(r) for r in cursor.fetchall()]

    # Check supervisor read-only state
    is_supervisor_view = current_user["role"] in ["NATIONAL_ADMIN", "DISTRICT_OFFICER"]

    conn.close()

    return {
        "phc_id": phc_id,
        "is_supervisor_view": is_supervisor_view,
        "current_user_role": current_user["role"],
        "inventory": inventory,
        "bed_status": bed_data,
        "staff_attendance": staff_rows,
        "staff_members": staff_members,
        "patient_footfall": footfall_rows,
        "transfers": transfers
    }


@app.get("/api/dashboard/district", tags=["3. District Aggregation"])
def get_district_aggregation(
    district_id: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(require_roles(["NATIONAL_ADMIN", "DISTRICT_OFFICER"]))
):
    """
    District aggregation endpoint: strictly scoped to the officer's assigned district
    or the district selected by National Admin.
    """
    # Enforce district data isolation
    if current_user["role"] == "DISTRICT_OFFICER":
        target_district = current_user["assigned_district_id"]
    else: # National Admin can view any district
        target_district = district_id or "DIST-NORTH"

    conn = get_db_connection()
    cursor = conn.cursor()

    # Get District metadata
    cursor.execute("SELECT * FROM districts WHERE id = ?", (target_district,))
    dist_meta = cursor.fetchone()
    district_name = dist_meta["name"] if dist_meta else target_district

    # Fetch all PHCs belonging to this district
    cursor.execute("SELECT * FROM phcs WHERE district_id = ?", (target_district,))
    district_phcs = [dict(r) for r in cursor.fetchall()]
    phc_ids = [p["id"] for p in district_phcs]

    if not phc_ids:
        conn.close()
        return {
            "district_id": target_district,
            "district_name": district_name,
            "phcs": [],
            "inventory_summary": [],
            "critical_par_level_warnings": []
        }

    # Query inventory strictly for this district's PHCs
    placeholders = ",".join("?" for _ in phc_ids)
    cursor.execute(f"SELECT * FROM medicine_inventory WHERE phc_id IN ({placeholders})", phc_ids)
    inventory_rows = cursor.fetchall()

    inventory_items = []
    par_level_warnings = []
    total_stock_by_med = {}
    total_par_by_med = {}

    for r in inventory_rows:
        item = dict(r)
        p_id = item["phc_id"]
        med = item["medicine_name"]
        qty = item["quantity"]
        par = item["par_level"]
        history = json.loads(item["daily_usage_history"]) if item["daily_usage_history"] else []

        forecast = forecast_demand_linear_regression(history, qty, par)
        item["forecast"] = forecast

        if forecast["below_30pct_par_flag"]:
            par_level_warnings.append({
                "phc_id": p_id,
                "medicine_name": med,
                "quantity": qty,
                "par_level": par,
                "pct_of_par": forecast["par_level_ratio_pct"],
                "warning": f"CRITICAL LOW STOCK: {qty}/{par} ({forecast['par_level_ratio_pct']}%)"
            })

        total_stock_by_med[med] = total_stock_by_med.get(med, 0) + qty
        total_par_by_med[med] = total_par_by_med.get(med, 0) + par
        inventory_items.append(item)

    # Bed rollups for district PHCs
    cursor.execute(f"SELECT SUM(total_beds) as total, SUM(occupied_beds) as occ FROM bed_status WHERE phc_id IN ({placeholders})", phc_ids)
    bed_sum = cursor.fetchone()
    total_beds = bed_sum["total"] or 0
    occ_beds = bed_sum["occ"] or 0

    # Staff count for district PHCs
    cursor.execute(f"SELECT COUNT(*) as total_staff FROM staff_members WHERE phc_id IN ({placeholders})", phc_ids)
    total_staff = cursor.fetchone()["total_staff"] or 0
    cursor.execute(f"SELECT COUNT(*) as present FROM staff_attendance WHERE phc_id IN ({placeholders}) AND present = 1 AND date = ?", (*phc_ids, datetime.now().strftime("%Y-%m-%d")))
    present_staff = cursor.fetchone()["present"] or 0

    # Footfall aggregate for district PHCs
    cursor.execute(f"SELECT SUM(count) as total_footfall FROM patient_footfall WHERE phc_id IN ({placeholders})", phc_ids)
    ff_row = cursor.fetchone()
    footfall_sum = ff_row["total_footfall"] or 0

    # Pending redistribution transfers inside this district
    cursor.execute(f"""
    SELECT * FROM redistribution_transfers 
    WHERE (source_phc IN ({placeholders}) OR target_phc IN ({placeholders}))
    ORDER BY id DESC LIMIT 10
    """, (*phc_ids, *phc_ids))
    district_transfers = [dict(r) for r in cursor.fetchall()]

    conn.close()

    # Differential privacy simulation on rollups
    dp_footfall = add_dp_noise(footfall_sum)
    dp_beds = add_dp_noise(occ_beds)

    # Scoped redistribution recommendations
    district_recs = generate_redistribution_recommendations(inventory_items)

    # PHC comparison metrics table
    phc_comparison = []
    for phc in district_phcs:
        p_items = [it for it in inventory_items if it["phc_id"] == phc["id"]]
        p_crit = sum(1 for it in p_items if it["forecast"]["below_30pct_par_flag"])
        phc_comparison.append({
            "id": phc["id"],
            "name": phc["name"],
            "operational_status": phc["operational_status"],
            "total_items_tracked": len(p_items),
            "critical_stockouts": p_crit,
            "status_badge": "CRITICAL" if p_crit > 0 else "OPERATIONAL"
        })

    return {
        "district_id": target_district,
        "district_name": district_name,
        "total_phcs": len(district_phcs),
        "online_phcs": sum(1 for p in district_phcs if p["operational_status"] == "ONLINE"),
        "offline_phcs": sum(1 for p in district_phcs if p["operational_status"] != "ONLINE"),
        "total_shortages": len(par_level_warnings),
        "bed_summary": {
            "total_beds": total_beds,
            "occupied_beds": occ_beds,
            "occupancy_pct": round((occ_beds / total_beds) * 100, 1) if total_beds > 0 else 0.0,
            "dp_noised_occupied": dp_beds
        },
        "personnel_summary": {
            "total_staff": total_staff,
            "present_today": present_staff,
            "attendance_rate_pct": round((present_staff / total_staff) * 100, 1) if total_staff > 0 else 100.0
        },
        "footfall_summary": {
            "total_patient_footfall": footfall_sum,
            "dp_noised_footfall": dp_footfall
        },
        "critical_par_level_warnings": par_level_warnings,
        "phc_comparison": phc_comparison,
        "active_recommendations": district_recs,
        "recent_transfers": district_transfers
    }


@app.get("/api/dashboard/national", tags=["8. National Dashboard & BRICS"])
def get_national_dashboard(current_user: Dict[str, Any] = Depends(require_roles(["NATIONAL_ADMIN"]))):
    """
    National Command Dashboard: Exclusively accessible to National Admin.
    Aggregates data across all registered districts and PHCs nationwide.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Total districts and PHCs
    cursor.execute("SELECT COUNT(*) FROM districts")
    total_districts = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM phcs")
    total_phcs = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM phcs WHERE operational_status = 'ONLINE'")
    reporting_phcs = cursor.fetchone()[0]

    # Nationwide medicine stock totals & rollups
    cursor.execute("SELECT SUM(quantity) as total_qty FROM medicine_inventory")
    total_inventory_units = cursor.fetchone()["total_qty"] or 0

    cursor.execute("""
    SELECT medicine_name, SUM(quantity) as stock, SUM(par_level) as par 
    FROM medicine_inventory 
    GROUP BY medicine_name
    """)
    med_rows = cursor.fetchall()
    strategic_reserve = []
    shortage_count = 0
    for r in med_rows:
        m = dict(r)
        pct = round((m["stock"] / m["par"]) * 100, 1) if m["par"] > 0 else 100.0
        status_label = "HEALTHY"
        if pct < 30.0:
            status_label = "CRITICAL_DEFICIT"
            shortage_count += 1
        elif pct < 60.0:
            status_label = "WATCH"
        strategic_reserve.append({
            "medicine_name": m["medicine_name"],
            "national_stock": m["stock"],
            "national_par_baseline": m["par"],
            "pct_of_par": pct,
            "status": status_label
        })

    # Total nationwide beds
    cursor.execute("SELECT SUM(total_beds) as total, SUM(occupied_beds) as occ FROM bed_status")
    b_row = cursor.fetchone()
    total_beds = b_row["total"] or 0
    occ_beds = b_row["occ"] or 0

    # Total staff present today
    today_str = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("SELECT COUNT(*) as present FROM staff_attendance WHERE present = 1 AND date = ?", (today_str,))
    staff_present = cursor.fetchone()["present"] or 0

    # Active and recent transfers
    cursor.execute("SELECT * FROM redistribution_transfers ORDER BY id DESC LIMIT 10")
    recent_transfers = [dict(r) for r in cursor.fetchall()]

    # District comparison table
    cursor.execute("SELECT * FROM districts ORDER BY name ASC")
    district_list = [dict(r) for r in cursor.fetchall()]

    district_comparisons = []
    for d in district_list:
        d_id = d["id"]
        cursor.execute("SELECT COUNT(*) as count FROM phcs WHERE district_id = ?", (d_id,))
        p_count = cursor.fetchone()["count"]

        cursor.execute("SELECT SUM(quantity) as qty FROM medicine_inventory WHERE district_id = ?", (d_id,))
        inv_sum = cursor.fetchone()["qty"] or 0

        cursor.execute("SELECT SUM(total_beds) as total, SUM(occupied_beds) as occ FROM bed_status WHERE district_id = ?", (d_id,))
        b_sum = cursor.fetchone()
        d_total_beds = b_sum["total"] or 0
        d_occ_beds = b_sum["occ"] or 0

        # Critical alerts in district
        cursor.execute("""
        SELECT COUNT(*) as alerts 
        FROM medicine_inventory 
        WHERE district_id = ? AND quantity <= (par_level * 0.3)
        """, (d_id,))
        d_alerts = cursor.fetchone()["alerts"] or 0

        district_comparisons.append({
            "id": d_id,
            "name": d["name"],
            "code": d["code"],
            "total_phcs": p_count,
            "total_stock": inv_sum,
            "total_beds": d_total_beds,
            "occupied_beds": d_occ_beds,
            "bed_occupancy_pct": round((d_occ_beds / d_total_beds) * 100, 1) if d_total_beds > 0 else 0,
            "critical_alerts": d_alerts,
            "status": "ATTENTION" if d_alerts > 0 else "NORMAL"
        })

    # Nationwide trend data (aggregated patient footfall by date)
    cursor.execute("""
    SELECT date, SUM(count) as total_footfall 
    FROM patient_footfall 
    GROUP BY date 
    ORDER BY date ASC
    """)
    trend_rows = [dict(r) for r in cursor.fetchall()]

    # Recent important audit activity
    cursor.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 10")
    recent_audit = [dict(r) for r in cursor.fetchall()]

    conn.close()

    # All inventory for global redistribution recommendations
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM medicine_inventory")
    all_inv = [dict(r) for r in c.fetchall()]
    conn.close()
    recs = generate_redistribution_recommendations(all_inv)

    return {
        "platform_name": "Meridian National Health Command Center",
        "timestamp": datetime.now().isoformat(),
        "national_kpis": {
            "total_districts": total_districts,
            "total_phcs": total_phcs,
            "reporting_phcs": reporting_phcs,
            "medicine_shortages_count": shortage_count,
            "total_beds": total_beds,
            "occupied_beds": occ_beds,
            "available_beds": max(0, total_beds - occ_beds),
            "staff_present_today": staff_present,
            "active_transfers_count": len(recs),
            "total_inventory_units": total_inventory_units
        },
        "district_comparisons": district_comparisons,
        "strategic_reserve": strategic_reserve,
        "nationwide_trends": trend_rows,
        "active_recommendations": recs,
        "recent_transfers": recent_transfers,
        "recent_activity": recent_audit
    }


# ---------------------------------------------------------
# 6. REDISTRIBUTION ENGINE & ACTIONS
# ---------------------------------------------------------

@app.get("/api/redistribution/recommendations", tags=["5. Redistribution Engine"])
def get_redistribution_recommendations_endpoint(current_user: Dict[str, Any] = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()

    if current_user["role"] == "PHC_STAFF":
        cursor.execute("SELECT * FROM medicine_inventory")
        all_inv = [dict(r) for r in cursor.fetchall()]
        all_recs = generate_redistribution_recommendations(all_inv)
        # Filter where user's PHC is donor or receiver
        user_phc = current_user["assigned_phc_id"]
        scoped_recs = [r for r in all_recs if r["source_phc"] == user_phc or r["target_phc"] == user_phc]
        conn.close()
        return {"active_recommendations": scoped_recs}

    elif current_user["role"] == "DISTRICT_OFFICER":
        dist_id = current_user["assigned_district_id"]
        cursor.execute("SELECT * FROM medicine_inventory WHERE district_id = ?", (dist_id,))
        dist_inv = [dict(r) for r in cursor.fetchall()]
        dist_recs = generate_redistribution_recommendations(dist_inv)
        conn.close()
        return {"active_recommendations": dist_recs}

    else: # National Admin
        cursor.execute("SELECT * FROM medicine_inventory")
        all_inv = [dict(r) for r in cursor.fetchall()]
        all_recs = generate_redistribution_recommendations(all_inv)
        conn.close()
        return {"active_recommendations": all_recs}


@app.post("/api/redistribution/action", tags=["5. Redistribution Engine"])
def act_on_redistribution(
    req: TransferActionRequest,
    current_user: Dict[str, Any] = Depends(require_roles(["NATIONAL_ADMIN", "DISTRICT_OFFICER"]))
):
    """
    District Officer or National Admin Human-In-The-Loop approval/rejection.
    PHC Staff cannot approve district-level transfers.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Verify District Officer can only approve transfers inside their district
    if current_user["role"] == "DISTRICT_OFFICER":
        cursor.execute("SELECT district_id FROM phcs WHERE id = ?", (req.source_phc,))
        s_d = cursor.fetchone()
        cursor.execute("SELECT district_id FROM phcs WHERE id = ?", (req.target_phc,))
        t_d = cursor.fetchone()

        if not s_d or not t_d or s_d["district_id"] != current_user["assigned_district_id"] or t_d["district_id"] != current_user["assigned_district_id"]:
            conn.close()
            raise HTTPException(status_code=403, detail="District Officers may only approve transfers within their assigned district.")

    now_str = datetime.now().isoformat()
    eta_mins = 25

    if req.action == "APPROVE":
        cursor.execute("""
        SELECT quantity FROM medicine_inventory WHERE phc_id = ? AND medicine_name = ?
        """, (req.source_phc, req.medicine_name))
        donor_stock = cursor.fetchone()

        if not donor_stock or donor_stock["quantity"] < req.quantity:
            conn.close()
            raise HTTPException(status_code=400, detail=f"Insufficient donor inventory at {req.source_phc}.")

        # Deduct from donor
        cursor.execute("""
        UPDATE medicine_inventory SET quantity = quantity - ?, updated_at = ?
        WHERE phc_id = ? AND medicine_name = ?
        """, (req.quantity, now_str, req.source_phc, req.medicine_name))

        # Add to target
        cursor.execute("""
        UPDATE medicine_inventory SET quantity = quantity + ?, updated_at = ?
        WHERE phc_id = ? AND medicine_name = ?
        """, (req.quantity, now_str, req.target_phc, req.medicine_name))

        cursor.execute("""
        INSERT INTO redistribution_transfers (
            source_phc, target_phc, medicine_name, quantity, eta_mins, 
            status, underlying_numbers, approved_by, decision_reason, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'APPROVED_IN_TRANSIT', ?, ?, ?, ?, ?)
        """, (
            req.source_phc, req.target_phc, req.medicine_name, req.quantity, eta_mins,
            f"Transfer of {req.quantity} units {req.medicine_name}",
            current_user["full_name"], req.decision_reason or "Approved via Human-in-the-Loop review",
            now_str, now_str
        ))
        conn.commit()

        log_audit_event(
            user_id=current_user["id"],
            user_name=current_user["full_name"],
            role=current_user["role"],
            action="TRANSFER_APPROVED",
            target_record=f"{req.source_phc} -> {req.target_phc} ({req.medicine_name})",
            district_scope=current_user.get("assigned_district_id"),
            result="SUCCESS",
            reason=req.decision_reason or "Transfer approved and inventory balances reconciled"
        )
        conn.close()
        return {
            "status": "success",
            "message": f"Transfer of {req.quantity} units {req.medicine_name} approved! DB updated in real-time.",
            "transfer_status": "APPROVED_IN_TRANSIT"
        }

    else: # REJECT
        cursor.execute("""
        INSERT INTO redistribution_transfers (
            source_phc, target_phc, medicine_name, quantity, eta_mins, 
            status, approved_by, decision_reason, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'REJECTED_BY_OFFICER', ?, ?, ?, ?)
        """, (
            req.source_phc, req.target_phc, req.medicine_name, req.quantity, 0,
            current_user["full_name"], req.decision_reason or "Rejected by Officer review",
            now_str, now_str
        ))
        conn.commit()

        log_audit_event(
            user_id=current_user["id"],
            user_name=current_user["full_name"],
            role=current_user["role"],
            action="TRANSFER_REJECTED",
            target_record=f"{req.source_phc} -> {req.target_phc} ({req.medicine_name})",
            district_scope=current_user.get("assigned_district_id"),
            result="DENIED",
            reason=req.decision_reason or "Transfer rejected during supervisor audit"
        )
        conn.close()
        return {"status": "success", "message": f"Transfer recommendation rejected.", "transfer_status": "REJECTED"}


# ---------------------------------------------------------
# 7. FORECASTING & AI
# ---------------------------------------------------------

@app.get("/api/forecasting/{phc_id}", tags=["4. Demand Forecasting"])
def get_phc_forecasting(phc_id: str, current_user: Dict[str, Any] = Depends(get_current_user)):
    enforce_phc_scope(current_user, phc_id)

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM medicine_inventory WHERE phc_id = ?", (phc_id,))
    rows = cursor.fetchall()
    conn.close()

    result = []
    for r in rows:
        item = dict(r)
        history = json.loads(item["daily_usage_history"]) if item["daily_usage_history"] else []
        forecast = forecast_demand_linear_regression(history, item["quantity"], item["par_level"])
        item["daily_usage_history"] = history
        item["forecast"] = forecast
        result.append(item)

    return {"phc_id": phc_id, "forecasts": result}


@app.get("/api/federated/train-and-aggregate", tags=["7. Federated Learning"])
def train_and_aggregate_fl(current_user: Dict[str, Any] = Depends(get_current_user)):
    return run_federated_averaging()


# ---------------------------------------------------------
# 8. PRIVACY, FHIR, & EXTENDED PLATFORM ENDPOINTS
# ---------------------------------------------------------

@app.get("/api/privacy/demo", tags=["6. Privacy Layer"])
def privacy_demo(identifier: str = "NURSE-042", current_user: Dict[str, Any] = Depends(get_current_user)):
    encrypted = encrypt_field(identifier)
    decrypted = decrypt_field(encrypted)
    token = tokenize_identifier(identifier)
    return {
        "raw_identifier": identifier,
        "fernet_encrypted": encrypted,
        "fernet_decrypted": decrypted,
        "tokenized_sha256": token
    }


@app.get("/api/privacy/dp-query", tags=["6. Privacy Layer"])
def run_dp_budget_query(true_val: int = 150, current_user: Dict[str, Any] = Depends(get_current_user)):
    return dp_manager.query_with_privacy(true_val)


@app.get("/api/fhir/export", tags=["11. HL7 FHIR Interoperability"])
def export_fhir_bundle(current_user: Dict[str, Any] = Depends(get_current_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM medicine_inventory")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return generate_fhir_bundle(rows)


@app.get("/api/provenance/verify", tags=["12. Supply Chain Provenance"])
def verify_batch_passport(batch_id: str = "BATCH-ORS-2026-A1", current_user: Dict[str, Any] = Depends(get_current_user)):
    return verify_medicine_batch(batch_id)


@app.get("/api/pilot/shadow-simulation", tags=["10. Pilot & Backtesting"])
def get_shadow_simulation(current_user: Dict[str, Any] = Depends(get_current_user)):
    return run_30day_shadow_simulation()


# ---------------------------------------------------------
# FRONTEND STATIC MOUNT & INDEX ROUTE
# ---------------------------------------------------------

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

if os.path.exists(FRONTEND_DIR):
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/", include_in_schema=False)
def serve_index():
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        return FileResponse(index_file)
    return {"message": "Meridian FastAPI backend running. Open /docs for API schema."}
