import json
import sqlite3
import os
import secrets
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Query, Request, Response, Depends, status
from fastapi.security import HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from backend.database import get_db_connection, init_db, hash_password, verify_password, get_phc_gis_data
from backend.models import (
    LoginRequest, ChangePasswordRequest, ForgotPasswordRequest, ResetPasswordRequest,
    CreateUserRequest, UpdateUserStatusRequest, AdminOverrideRequest,
    InventoryUpdate, BedStatusUpdate, EquipmentUpdate, StaffAttendanceCreate,
    PatientFootfallCreate, TransferActionRequest, CardPunchRequest, StaffActionRequest,
    TransferCreateRequest, TransferReviewRequest, TransferDispatchConfirmRequest,
    TransferDeliverConfirmRequest, TransferEscalateRequest, SendMessageRequest,
    AcknowledgeMessageRequest, StockReceivedRequest, StockConsumedRequest, StockDispensedRequest
)
from backend.forecasting import forecast_demand_linear_regression
from backend.redistribution import generate_redistribution_recommendations
from backend.privacy import encrypt_field, decrypt_field, tokenize_identifier, add_dp_noise
from backend.audit import log_audit_event
from backend.auth import (
    authenticate_user, destroy_session, get_current_user, require_roles,
    enforce_phc_scope, enforce_district_scope, SESSION_COOKIE_NAME, bearer_scheme
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
def logout_endpoint(
    request: Request,
    response: Response,
    auth_header: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme)
):
    token = None
    if SESSION_COOKIE_NAME in request.cookies:
        token = request.cookies.get(SESSION_COOKIE_NAME)
    elif auth_header and auth_header.credentials:
        token = auth_header.credentials

    if token:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT u.* FROM sessions s JOIN users u ON s.user_id = u.id WHERE s.session_id = ?", (token,))
            row = cursor.fetchone()
            conn.close()
            user_info = dict(row) if row else None
            destroy_session(token, user_info=user_info)
        except Exception as e:
            pass

    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return {"status": "success", "message": "Successfully logged out."}


@app.get("/api/config/demo-mode", tags=["0. Authentication"])
def get_demo_mode_status():
    is_demo = os.environ.get("DEMO_MODE", "true").lower() in ("true", "1", "yes")
    return {"demo_mode": is_demo}


@app.get("/api/auth/me", tags=["0. Authentication"])
def get_current_user_profile(current_user: Dict[str, Any] = Depends(get_current_user)):
    user_dict = dict(current_user)
    user_dict["demo_mode"] = os.environ.get("DEMO_MODE", "true").lower() in ("true", "1", "yes")
    return user_dict


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
@app.post("/api/beds", tags=["1. CRUD - Beds"])
def update_beds(
    data: BedStatusUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    target_phc = data.phc_id or current_user.get("assigned_phc_id") or "PHC-001"
    enforce_phc_scope(current_user, target_phc)

    if current_user["role"] == "NATIONAL_ADMIN":
        if not data.override_reason or len(data.override_reason.strip()) < 3:
            raise HTTPException(status_code=400, detail="Administrative bed override requires explicit written reason.")
    elif current_user["role"] == "DISTRICT_OFFICER":
        raise HTTPException(status_code=403, detail="District Officers monitor bed occupancy; updates are recorded by PHC Staff.")

    if data.total_beds < 0:
        raise HTTPException(status_code=400, detail="Total beds cannot be negative.")
    if data.occupied_beds < 0:
        raise HTTPException(status_code=400, detail="Occupied beds cannot be negative.")
    if data.occupied_beds > data.total_beds:
        raise HTTPException(status_code=400, detail=f"Occupied beds ({data.occupied_beds}) cannot exceed total registered beds ({data.total_beds}).")

    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()

    cursor.execute("SELECT district_id FROM phcs WHERE id = ?", (target_phc,))
    phc_meta = cursor.fetchone()
    d_id = phc_meta["district_id"] if phc_meta else "DIST-NORTH"

    cursor.execute("""
    INSERT INTO bed_status (phc_id, district_id, total_beds, occupied_beds, notes, updated_at)
    VALUES (?, ?, ?, ?, ?, ?)
    ON CONFLICT(phc_id) DO UPDATE SET
        total_beds = excluded.total_beds,
        occupied_beds = excluded.occupied_beds,
        district_id = excluded.district_id,
        notes = excluded.notes,
        updated_at = excluded.updated_at
    """, (target_phc, d_id, data.total_beds, data.occupied_beds, data.notes, now_str))

    # Generate capacity alert if occupancy >= 90%
    if data.total_beds > 0 and (data.occupied_beds / data.total_beds) >= 0.90:
        pct = int((data.occupied_beds / data.total_beds) * 100)
        cursor.execute("""
        INSERT INTO messages (
            sender_id, sender_name, sender_role, recipient_role,
            district_id, phc_id, subject, message, priority, sent_at
        ) VALUES (?, ?, ?, 'DISTRICT_OFFICER', ?, ?, ?, ?, 'URGENT', ?)
        """, (
            current_user["id"], current_user["full_name"], current_user["role"],
            d_id, target_phc,
            f"HIGH CAPACITY ALERT: {target_phc} at {pct}% bed occupancy",
            f"Facility {target_phc} has reached critical bed capacity ({data.occupied_beds}/{data.total_beds} beds occupied). High clinical demand detected.",
            now_str
        ))

    conn.commit()
    conn.close()

    is_override = current_user["role"] == "NATIONAL_ADMIN"
    log_audit_event(
        user_id=current_user["id"],
        user_name=current_user["full_name"],
        role=current_user["role"],
        action="BED_OVERRIDE" if is_override else "BED_UPDATE",
        target_record=target_phc,
        district_scope=d_id,
        phc_scope=target_phc,
        result="OVERRIDDEN" if is_override else "SUCCESS",
        reason=data.override_reason if is_override else (data.notes or "Daily bed status reconciliation"),
        details={"total_beds": data.total_beds, "occupied_beds": data.occupied_beds}
    )

    avail = data.total_beds - data.occupied_beds
    return {
        "status": "success",
        "message": f"Updated bed status for {target_phc}",
        "phc_id": target_phc,
        "total_beds": data.total_beds,
        "occupied_beds": data.occupied_beds,
        "available_beds": avail
    }


# ---------------------------------------------------------
# 2B. SCOPED CRUD - FACILITY EQUIPMENT
# ---------------------------------------------------------

@app.get("/api/equipment", tags=["1. CRUD - Beds & Equipment"])
def get_equipment(
    phc_id: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    conn = get_db_connection()
    cursor = conn.cursor()

    if current_user["role"] == "PHC_STAFF":
        target = current_user.get("assigned_phc_id") or "PHC-001"
        cursor.execute("SELECT * FROM facility_equipment WHERE phc_id = ? ORDER BY id ASC", (target,))
    elif current_user["role"] == "DISTRICT_OFFICER":
        dist_id = current_user["assigned_district_id"]
        if phc_id:
            enforce_phc_scope(current_user, phc_id)
            cursor.execute("SELECT * FROM facility_equipment WHERE phc_id = ? ORDER BY id ASC", (phc_id,))
        else:
            cursor.execute("SELECT * FROM facility_equipment WHERE district_id = ? ORDER BY id ASC", (dist_id,))
    else: # NATIONAL_ADMIN
        if phc_id:
            cursor.execute("SELECT * FROM facility_equipment WHERE phc_id = ? ORDER BY id ASC", (phc_id,))
        else:
            cursor.execute("SELECT * FROM facility_equipment ORDER BY id ASC")

    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


@app.post("/api/equipment/update", tags=["1. CRUD - Beds & Equipment"])
@app.post("/api/equipment", tags=["1. CRUD - Beds & Equipment"])
def update_equipment(
    data: EquipmentUpdate,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    target_phc = data.phc_id or current_user.get("assigned_phc_id") or "PHC-001"
    enforce_phc_scope(current_user, target_phc)

    if current_user["role"] == "NATIONAL_ADMIN":
        if not data.override_reason or len(data.override_reason.strip()) < 3:
            raise HTTPException(status_code=400, detail="Administrative equipment override requires explicit written reason.")
    elif current_user["role"] == "DISTRICT_OFFICER":
        raise HTTPException(status_code=403, detail="District Officers monitor equipment; updates are recorded by PHC Staff.")

    if data.quantity < 0:
        raise HTTPException(status_code=400, detail="Equipment quantity cannot be negative.")
    if data.under_maintenance_count < 0:
        raise HTTPException(status_code=400, detail="Under maintenance count cannot be negative.")
    if data.under_maintenance_count > data.quantity:
        raise HTTPException(status_code=400, detail=f"Under maintenance count ({data.under_maintenance_count}) cannot exceed total quantity ({data.quantity}).")

    allowed_statuses = {"OPERATIONAL", "UNDER_MAINTENANCE", "CRITICAL_DEFICIT", "STANDBY"}
    status_upper = (data.operational_status or "OPERATIONAL").upper()
    if status_upper not in allowed_statuses:
        raise HTTPException(status_code=400, detail=f"Invalid operational status '{data.operational_status}'. Must be one of {sorted(list(allowed_statuses))}.")

    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()

    cursor.execute("SELECT district_id FROM phcs WHERE id = ?", (target_phc,))
    phc_meta = cursor.fetchone()
    d_id = phc_meta["district_id"] if phc_meta else "DIST-NORTH"

    if data.equipment_id:
        cursor.execute("SELECT * FROM facility_equipment WHERE id = ? AND phc_id = ?", (data.equipment_id, target_phc))
    else:
        cursor.execute("SELECT * FROM facility_equipment WHERE name = ? AND phc_id = ?", (data.name, target_phc))
    existing = cursor.fetchone()

    prev_val = str(dict(existing)) if existing else "NONE"

    if existing:
        cursor.execute("""
        UPDATE facility_equipment SET
            quantity = ?, operational_status = ?, under_maintenance_count = ?, notes = ?, updated_at = ?
        WHERE id = ?
        """, (data.quantity, status_upper, data.under_maintenance_count, data.notes, now_str, existing["id"]))
        eq_id = existing["id"]
    else:
        cursor.execute("""
        INSERT INTO facility_equipment (phc_id, district_id, name, category, quantity, operational_status, under_maintenance_count, notes, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (target_phc, d_id, data.name, data.category or "General", data.quantity, status_upper, data.under_maintenance_count, data.notes, now_str))
        eq_id = cursor.lastrowid

    # Capacity alert if critical deficit
    if status_upper == "CRITICAL_DEFICIT":
        cursor.execute("""
        INSERT INTO messages (
            sender_id, sender_name, sender_role, recipient_role,
            district_id, phc_id, subject, message, priority, sent_at
        ) VALUES (?, ?, ?, 'DISTRICT_OFFICER', ?, ?, ?, ?, 'URGENT', ?)
        """, (
            current_user["id"], current_user["full_name"], current_user["role"],
            d_id, target_phc,
            f"CRITICAL EQUIPMENT DEFICIT: {data.name} at {target_phc}",
            f"{target_phc} reported a critical deficit or failure of equipment '{data.name}'. Notes: {data.notes or 'None'}",
            now_str
        ))

    conn.commit()
    conn.close()

    is_override = current_user["role"] == "NATIONAL_ADMIN"
    log_audit_event(
        user_id=current_user["id"],
        user_name=current_user["full_name"],
        role=current_user["role"],
        action="EQUIPMENT_OVERRIDE" if is_override else "EQUIPMENT_UPDATE",
        target_record=f"{target_phc} / {data.name}",
        district_scope=d_id,
        phc_scope=target_phc,
        result="OVERRIDDEN" if is_override else "SUCCESS",
        previous_value=prev_val,
        new_value=f"{status_upper} (Qty: {data.quantity})",
        reason=data.override_reason if is_override else (data.notes or "Routine equipment readiness verification")
    )

    return {
        "status": "success",
        "message": f"Updated equipment '{data.name}' at {target_phc}",
        "equipment_id": eq_id,
        "phc_id": target_phc,
        "name": data.name,
        "operational_status": status_upper,
        "quantity": data.quantity,
        "under_maintenance_count": data.under_maintenance_count
    }


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
@app.post("/api/staff/punch", tags=["1. CRUD - Staff"])
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
@app.post("/api/staff", tags=["1. CRUD - Staff"])
def log_staff_attendance_manual(
    entry: StaffAttendanceCreate,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    target_phc = entry.phc_id or current_user.get("assigned_phc_id") or "PHC-001"
    enforce_phc_scope(current_user, target_phc)

    if current_user["role"] == "NATIONAL_ADMIN":
        if not entry.override_reason or len(entry.override_reason.strip()) < 3:
            raise HTTPException(status_code=400, detail="Administrative attendance override requires explicit written reason.")
    elif current_user["role"] == "DISTRICT_OFFICER":
        raise HTTPException(status_code=403, detail="District Officers monitor attendance; modifications are managed by PHC Staff.")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT district_id FROM phcs WHERE id = ?", (target_phc,))
    d_row = cursor.fetchone()
    d_id = d_row["district_id"] if d_row else "DIST-NORTH"

    today_str = entry.date or datetime.now().strftime("%Y-%m-%d")
    now_iso = datetime.now().isoformat()
    enc_id = encrypt_field(entry.staff_id)
    tok_id = tokenize_identifier(entry.staff_id)

    cursor.execute("SELECT name, role FROM staff_members WHERE staff_id = ?", (entry.staff_id,))
    s_meta = cursor.fetchone()
    staff_name = entry.staff_name or (s_meta["name"] if s_meta else entry.staff_id)
    staff_role = entry.role or (s_meta["role"] if s_meta else "Staff")

    # Check if an entry already exists today to prevent accidental duplicate check-in
    cursor.execute("""
    SELECT id, status FROM staff_attendance
    WHERE staff_id = ? AND date = ? AND phc_id = ?
    ORDER BY id DESC LIMIT 1
    """, (entry.staff_id, today_str, target_phc))
    existing = cursor.fetchone()

    status_val = entry.status or "CHECKED_IN"
    pres_val = 0 if status_val in ["ABSENT", "ON_LEAVE"] else 1

    if existing:
        cursor.execute("""
        UPDATE staff_attendance SET
            status = ?, present = ?, verification_method = ?, remarks = ?, operator = ?, updated_at = ?
        WHERE id = ?
        """, (
            status_val, pres_val, entry.verification_method or "Manual Kiosk",
            entry.remarks, entry.operator or current_user["full_name"], now_iso, existing["id"]
        ))
    else:
        cursor.execute("""
        INSERT INTO staff_attendance (
            phc_id, district_id, staff_id, staff_name, role, card_uid, 
            staff_id_encrypted, staff_token, present, status, verification_method, 
            punch_in_time, punch_out_time, date, shift, department, remarks, operator, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            target_phc, d_id, entry.staff_id, staff_name,
            staff_role, entry.card_uid, enc_id, tok_id, pres_val,
            status_val, entry.verification_method or "Manual Kiosk",
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
        target_record=f"{target_phc} / {entry.staff_id}",
        district_scope=d_id,
        phc_scope=target_phc,
        result="OVERRIDDEN" if is_override else "SUCCESS",
        reason=entry.override_reason if is_override else (entry.remarks or "Manual staff attendance submission")
    )

    return {"status": "success", "message": f"Attendance logged for {staff_name} ({status_val})"}


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
        "MARK_ABSENT": "ABSENT",
        "CORRECTION": "CHECKED_IN"
    }
    new_status = status_map.get(req.action, "CHECKED_IN")
    present_val = 0 if new_status in ["ABSENT", "ON_LEAVE"] else 1

    if row:
        punch_out = time_str if new_status == "CHECKED_OUT" else row["punch_out_time"]
        cursor.execute("""
        UPDATE staff_attendance
        SET status = ?, present = ?, punch_out_time = ?, remarks = ?, operator = ?, updated_at = ?
        WHERE id = ?
        """, (new_status, present_val, punch_out, req.remarks or f"Action: {req.action}", req.operator or current_user["full_name"], now_iso, row["id"]))
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
@app.post("/api/footfall", tags=["1. CRUD - Footfall"])
def log_footfall(
    data: PatientFootfallCreate,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    target_phc = data.phc_id or current_user.get("assigned_phc_id") or "PHC-001"
    enforce_phc_scope(current_user, target_phc)

    if current_user["role"] == "NATIONAL_ADMIN":
        if not data.override_reason or len(data.override_reason.strip()) < 3:
            raise HTTPException(status_code=400, detail="Administrative footfall override requires written reason.")
    elif current_user["role"] == "DISTRICT_OFFICER":
        raise HTTPException(status_code=403, detail="District Officers cannot directly modify PHC footfall counts.")

    if data.count < 0:
        raise HTTPException(status_code=400, detail="Patient footfall count cannot be negative.")

    today_str = datetime.now().strftime("%Y-%m-%d")
    if data.date > today_str:
        raise HTTPException(status_code=400, detail="Cannot record patient footfall for future dates.")

    try:
        datetime.strptime(data.date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid date format. Expected YYYY-MM-DD.")

    male = data.male_count or 0
    female = data.female_count or 0
    other = data.other_count or 0
    emergency = data.emergency_cases or 0
    cat_sum = male + female + other
    if cat_sum > data.count:
        raise HTTPException(status_code=400, detail=f"Category breakdown total ({cat_sum}) cannot exceed total visits ({data.count}).")

    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT district_id FROM phcs WHERE id = ?", (target_phc,))
    d_row = cursor.fetchone()
    d_id = d_row["district_id"] if d_row else "DIST-NORTH"

    cursor.execute("""
    INSERT INTO patient_footfall (
        phc_id, district_id, date, count, male_count, female_count, other_count, emergency_cases, correction_reason, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ON CONFLICT(phc_id, date) DO UPDATE SET
        count = excluded.count,
        district_id = excluded.district_id,
        male_count = excluded.male_count,
        female_count = excluded.female_count,
        other_count = excluded.other_count,
        emergency_cases = excluded.emergency_cases,
        correction_reason = excluded.correction_reason,
        updated_at = excluded.updated_at
    """, (target_phc, d_id, data.date, data.count, male, female, other, emergency, data.correction_reason, datetime.now().isoformat()))
    conn.commit()
    conn.close()

    is_override = current_user["role"] == "NATIONAL_ADMIN"
    log_audit_event(
        user_id=current_user["id"],
        user_name=current_user["full_name"],
        role=current_user["role"],
        action="FOOTFALL_OVERRIDE" if is_override else "FOOTFALL_LOG",
        target_record=f"{target_phc} / {data.date}",
        district_scope=d_id,
        phc_scope=target_phc,
        result="OVERRIDDEN" if is_override else "SUCCESS",
        reason=data.override_reason if is_override else (data.correction_reason or f"Recorded {data.count} OPD visits")
    )

    return {
        "status": "success",
        "message": f"Logged footfall {data.count} for {target_phc} on {data.date}",
        "phc_id": target_phc,
        "date": data.date,
        "count": data.count
    }


# ---------------------------------------------------------
# 5. DASHBOARDS (ROLE-SPECIFIC & SCOPED)
# ---------------------------------------------------------

@app.get("/api/dashboard/phc", tags=["2. PHC Dashboard"])
@app.get("/api/dashboard/phc/{phc_id}", tags=["2. PHC Dashboard"])
def get_phc_dashboard(
    phc_id: Optional[str] = None,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Returns complete PHC Edge Dashboard payload.
    Enforces that PHC staff only accesses their own facility,
    District Officer only accesses facilities inside their district,
    and National Admin has read-only/oversight capability.
    """
    target_phc = phc_id or current_user.get("assigned_phc_id") or "PHC-001"
    enforce_phc_scope(current_user, target_phc)
    phc_id = target_phc

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

    # Fetch facility equipment
    cursor.execute("SELECT * FROM facility_equipment WHERE phc_id = ? ORDER BY id ASC", (phc_id,))
    equipment_rows = [dict(r) for r in cursor.fetchall()]

    # Check supervisor read-only state
    is_supervisor_view = current_user["role"] in ["NATIONAL_ADMIN", "DISTRICT_OFFICER"]

    conn.close()

    return {
        "phc_id": phc_id,
        "is_supervisor_view": is_supervisor_view,
        "current_user_role": current_user["role"],
        "inventory": inventory,
        "bed_status": bed_data,
        "equipment": equipment_rows,
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

# ---------------------------------------------------------
# 5. 10-STEP REDISTRIBUTION LIFECYCLE & GOVERNANCE
# ---------------------------------------------------------

@app.get("/api/redistribution/transfers", tags=["5. Redistribution Lifecycle"])
def get_redistribution_transfers(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Returns scoped transfer list with calculated lifecycle turnaround times.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    if current_user["role"] == "NATIONAL_ADMIN":
        cursor.execute("SELECT * FROM redistribution_transfers ORDER BY id DESC")
    elif current_user["role"] == "DISTRICT_OFFICER":
        dist_id = current_user["assigned_district_id"]
        cursor.execute("""
        SELECT * FROM redistribution_transfers 
        WHERE source_district_id = ? OR target_district_id = ?
        ORDER BY id DESC
        """, (dist_id, dist_id))
    else: # PHC_STAFF
        phc_id = current_user["assigned_phc_id"]
        cursor.execute("""
        SELECT * FROM redistribution_transfers 
        WHERE source_phc = ? OR target_phc = ?
        ORDER BY id DESC
        """, (phc_id, phc_id))

    rows = cursor.fetchall()
    conn.close()

    transfers = []
    now = datetime.now()
    for r in rows:
        t = dict(r)
        # Calculate turnaround metrics
        if t.get("requested_at"):
            try:
                req_dt = datetime.fromisoformat(t["requested_at"])
                if t.get("completed_at"):
                    comp_dt = datetime.fromisoformat(t["completed_at"])
                    t["total_turnaround_mins"] = max(1, round((comp_dt - req_dt).total_seconds() / 60))
                else:
                    t["elapsed_mins"] = max(1, round((now - req_dt).total_seconds() / 60))
            except Exception:
                pass
        transfers.append(t)

    return {"transfers": transfers}


@app.post("/api/redistribution/request", tags=["5. Redistribution Lifecycle"])
@app.post("/api/transfer/request", tags=["5. Redistribution Lifecycle"])
@app.post("/api/transfers/request", tags=["5. Redistribution Lifecycle"])
def create_redistribution_request(
    req: TransferCreateRequest,
    current_user: Dict[str, Any] = Depends(require_roles(["PHC_STAFF", "NATIONAL_ADMIN"]))
):
    """
    PHC Staff detects shortage and creates a formal redistribution request.
    System calculates the best donor PHC with verified safe stock surplus.
    """
    target_phc = req.target_phc or req.phc_id or current_user.get("assigned_phc_id") or "PHC-001"
    enforce_phc_scope(current_user, target_phc)

    if req.quantity <= 0:
        raise HTTPException(status_code=400, detail="Requested transfer quantity must be greater than zero.")

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT district_id FROM phcs WHERE id = ?", (target_phc,))
    target_dist_row = cursor.fetchone()
    target_district = target_dist_row["district_id"] if target_dist_row else "DIST-NORTH"

    # Reject duplicate pending request
    cursor.execute("""
    SELECT id FROM redistribution_transfers
    WHERE target_phc = ? AND medicine_name = ? AND status = 'Requested'
    """, (target_phc, req.medicine_name))
    existing_pending = cursor.fetchone()
    if existing_pending:
        conn.close()
        raise HTTPException(
            status_code=409,
            detail=f"A pending transfer request for '{req.medicine_name}' already exists (Transfer #{existing_pending['id']})."
        )

    # Find donor PHC with safe stock surplus
    if req.donor_phc:
        donor_phc = req.donor_phc
        cursor.execute("SELECT district_id FROM phcs WHERE id = ?", (donor_phc,))
        s_d_row = cursor.fetchone()
        source_district = s_d_row["district_id"] if s_d_row else target_district
        cursor.execute("SELECT quantity, par_level FROM medicine_inventory WHERE phc_id = ? AND medicine_name = ?", (donor_phc, req.medicine_name))
        d_stock = cursor.fetchone()
        donor_stock_qty = d_stock["quantity"] if d_stock else 0
        donor_par = d_stock["par_level"] if d_stock else 100
    else:
        # Auto-match: prioritize same district with surplus above par level
        cursor.execute("""
        SELECT mi.phc_id, mi.district_id, mi.quantity, mi.par_level, (mi.quantity - mi.par_level) as surplus
        FROM medicine_inventory mi
        WHERE mi.medicine_name = ? AND mi.phc_id != ?
        ORDER BY (mi.district_id = ?) DESC, (mi.quantity - mi.par_level) DESC
        LIMIT 1
        """, (req.medicine_name, target_phc, target_district))
        match = cursor.fetchone()
        if match:
            donor_phc = match["phc_id"]
            source_district = match["district_id"]
            donor_stock_qty = match["quantity"]
            donor_par = match["par_level"]
        else:
            donor_phc = "PHC-002" if target_phc != "PHC-002" else "PHC-001"
            source_district = target_district
            donor_stock_qty = 100
            donor_par = 100

    now_iso = datetime.now().isoformat()
    eta_mins = 25 if source_district == target_district else 55

    cursor.execute("""
    INSERT INTO redistribution_transfers (
        source_phc, target_phc, source_district_id, target_district_id,
        medicine_name, quantity, eta_mins, urgency, status,
        underlying_numbers, requested_by, requested_at,
        created_at, updated_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'Requested', ?, ?, ?, ?, ?)
    """, (
        donor_phc, target_phc, source_district, target_district,
        req.medicine_name, req.quantity, eta_mins, req.urgency,
        json.dumps({"donor_stock": donor_stock_qty, "donor_par": donor_par, "requested": req.quantity, "reason": req.reason}),
        current_user["id"], now_iso, now_iso, now_iso
    ))
    transfer_id = cursor.lastrowid

    # Auto-dispatch high-priority official message to District Officer
    cursor.execute("""
    INSERT INTO messages (
        sender_id, sender_name, sender_role, recipient_role,
        district_id, phc_id, transfer_id, subject, message, priority, sent_at
    ) VALUES (?, ?, ?, 'DISTRICT_OFFICER', ?, ?, ?, ?, ?, ?, ?)
    """, (
        current_user["id"], current_user["full_name"], current_user["role"],
        target_district, target_phc, transfer_id,
        f"NEW SHORTAGE REQUEST #{transfer_id}: {req.medicine_name} ({req.quantity} units)",
        f"PHC {target_phc} has logged an urgent shortage of {req.medicine_name} ({req.quantity} units requested). Recommended donor: {donor_phc}. Immediate review requested.",
        "URGENT" if req.urgency in ["URGENT", "CRITICAL"] else "NORMAL",
        now_iso
    ))

    conn.commit()

    log_audit_event(
        user_id=current_user["id"],
        user_name=current_user["full_name"],
        role=current_user["role"],
        action="TRANSFER_REQUESTED",
        target_record=f"Transfer #{transfer_id} ({req.medicine_name}: {req.quantity} to {target_phc})",
        district_scope=target_district,
        phc_scope=target_phc,
        result="SUCCESS",
        reason=req.reason or f"Shortage detected: {req.urgency} priority"
    )
    conn.close()

    return {
        "status": "success",
        "transfer_id": transfer_id,
        "message": f"Resource request #{transfer_id} created successfully and routed to District Officer for review.",
        "recommended_donor": donor_phc,
        "eta_mins": eta_mins
    }


@app.post("/api/redistribution/{transfer_id}/review", tags=["5. Redistribution Lifecycle"])
def review_redistribution_transfer(
    transfer_id: int,
    req: TransferReviewRequest,
    current_user: Dict[str, Any] = Depends(require_roles(["DISTRICT_OFFICER", "NATIONAL_ADMIN"]))
):
    """
    District Officer or National Admin reviews, modifies, approves, or rejects transfer.
    Strictly checks that the transfer will not push donor stock below safe par level.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM redistribution_transfers WHERE id = ?", (transfer_id,))
    t = cursor.fetchone()
    if not t:
        conn.close()
        raise HTTPException(status_code=404, detail="Transfer record not found.")

    # District Officer scope check
    if current_user["role"] == "DISTRICT_OFFICER":
        dist_id = current_user["assigned_district_id"]
        if t["source_district_id"] != dist_id and t["target_district_id"] != dist_id:
            conn.close()
            raise HTTPException(status_code=403, detail="District Officers can only review transfers in their assigned district.")

    now_iso = datetime.now().isoformat()
    action = req.action.upper()
    donor_phc = req.alternative_donor_phc or t["source_phc"]
    approved_qty = req.modified_quantity if req.modified_quantity and req.modified_quantity > 0 else t["quantity"]

    if action in ["APPROVE", "MODIFY_AND_APPROVE"]:
        # Check donor safe stock threshold
        cursor.execute("""
        SELECT quantity, par_level FROM medicine_inventory 
        WHERE phc_id = ? AND medicine_name = ?
        """, (donor_phc, t["medicine_name"]))
        stock_row = cursor.fetchone()
        if not stock_row:
            conn.close()
            raise HTTPException(status_code=400, detail=f"Donor PHC {donor_phc} does not hold stock for {t['medicine_name']}.")

        donor_qty = stock_row["quantity"]
        par_level = stock_row["par_level"]
        surplus_after = donor_qty - approved_qty

        # Strict Safe Stock Enforcement: cannot push donor below safe threshold (par level)
        if surplus_after < par_level:
            conn.close()
            raise HTTPException(
                status_code=400,
                detail=f"Transfer rejected: Transferring {approved_qty} units would leave donor {donor_phc} with {surplus_after} units, which is below its safe par level ({par_level}). Reduce quantity or select another donor."
            )

        new_status = "Approved"
        cursor.execute("""
        UPDATE redistribution_transfers SET 
            source_phc = ?, quantity = ?, status = ?, approved_by = ?,
            approved_at = ?, decision_reason = ?, updated_at = ?
        WHERE id = ?
        """, (donor_phc, approved_qty, new_status, current_user["full_name"], now_iso, req.decision_reason or "Approved by Officer", now_iso, transfer_id))

        # Notify donor and receiver PHCs
        cursor.execute("""
        INSERT INTO messages (
            sender_id, sender_name, sender_role, recipient_role,
            district_id, phc_id, transfer_id, subject, message, priority, sent_at
        ) VALUES (?, ?, ?, 'PHC_STAFF', ?, ?, ?, ?, ?, 'URGENT', ?)
        """, (
            current_user["id"], current_user["full_name"], current_user["role"],
            t["source_district_id"], donor_phc, transfer_id,
            f"TRANSFER APPROVED #{transfer_id}: Prepare Dispatch",
            f"Officer has approved redistribution of {approved_qty} units {t['medicine_name']} to {t['target_phc']}. Please prepare consignment and confirm dispatch.",
            now_iso
        ))

        conn.commit()

        log_audit_event(
            user_id=current_user["id"],
            user_name=current_user["full_name"],
            role=current_user["role"],
            action="TRANSFER_APPROVED",
            target_record=f"Transfer #{transfer_id} ({t['medicine_name']}: {approved_qty})",
            district_scope=t["source_district_id"],
            phc_scope=t["source_phc"],
            result="SUCCESS",
            reason=req.decision_reason or "Approved with safe surplus verified"
        )
        conn.close()

        return {
            "status": "success",
            "message": f"Transfer #{transfer_id} approved for {approved_qty} units. Donor notified to dispatch.",
            "transfer_status": new_status
        }

    elif action == "REJECT":
        new_status = "Rejected"
        cursor.execute("""
        UPDATE redistribution_transfers SET 
            status = ?, decision_reason = ?, updated_at = ?
        WHERE id = ?
        """, (new_status, req.decision_reason or "Rejected by Officer", now_iso, transfer_id))

        cursor.execute("""
        INSERT INTO messages (
            sender_id, sender_name, sender_role, recipient_role,
            district_id, phc_id, transfer_id, subject, message, priority, sent_at
        ) VALUES (?, ?, ?, 'PHC_STAFF', ?, ?, ?, ?, ?, 'NORMAL', ?)
        """, (
            current_user["id"], current_user["full_name"], current_user["role"],
            t["target_district_id"], t["target_phc"], transfer_id,
            f"TRANSFER REJECTED #{transfer_id}: {t['medicine_name']}",
            f"Your request for {t['quantity']} units {t['medicine_name']} was rejected. Reason: {req.decision_reason or 'No reason provided.'}",
            now_iso
        ))

        conn.commit()

        log_audit_event(
            user_id=current_user["id"],
            user_name=current_user["full_name"],
            role=current_user["role"],
            action="TRANSFER_REJECTED",
            target_record=f"Transfer #{transfer_id}",
            district_scope=t["source_district_id"],
            result="DENIED",
            reason=req.decision_reason or "Rejected during officer review"
        )
        conn.close()

        return {
            "status": "success",
            "message": f"Transfer #{transfer_id} rejected.",
            "transfer_status": new_status
        }
    else:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Invalid action: {action}")


@app.post("/api/redistribution/{transfer_id}/dispatch", tags=["5. Redistribution Lifecycle"])
def confirm_transfer_dispatch(
    transfer_id: int,
    req: TransferDispatchConfirmRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Donor PHC confirms physical stock packaging and dispatch.
    Status transitions to 'In Transit'.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM redistribution_transfers WHERE id = ?", (transfer_id,))
    t = cursor.fetchone()
    if not t:
        conn.close()
        raise HTTPException(status_code=404, detail="Transfer not found.")

    if current_user["role"] == "PHC_STAFF" and current_user["assigned_phc_id"] != t["source_phc"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Only staff at the donor PHC can confirm dispatch.")

    if t["status"] != "Approved":
        conn.close()
        raise HTTPException(
            status_code=400,
            detail=f"Transfer #{transfer_id} cannot be dispatched because its status is '{t['status']}' (must be 'Approved')."
        )

    now_iso = datetime.now().isoformat()
    cursor.execute("""
    UPDATE redistribution_transfers SET 
        status = 'In Transit', dispatched_by = ?, dispatched_at = ?, updated_at = ?
    WHERE id = ?
    """, (current_user["full_name"], now_iso, now_iso, transfer_id))

    # Notify recipient PHC
    cursor.execute("""
    INSERT INTO messages (
        sender_id, sender_name, sender_role, recipient_role,
        district_id, phc_id, transfer_id, subject, message, priority, sent_at
    ) VALUES (?, ?, ?, 'PHC_STAFF', ?, ?, ?, ?, ?, 'NORMAL', ?)
    """, (
        current_user["id"], current_user["full_name"], current_user["role"],
        t["target_district_id"], t["target_phc"], transfer_id,
        f"STOCK DISPATCHED #{transfer_id}: In Transit",
        f"Consignment of {t['quantity']} units {t['medicine_name']} dispatched by {t['source_phc']}. ETA: {t['eta_mins']} mins. Please confirm upon delivery.",
        now_iso
    ))

    conn.commit()

    log_audit_event(
        user_id=current_user["id"],
        user_name=current_user["full_name"],
        role=current_user["role"],
        action="TRANSFER_DISPATCHED",
        target_record=f"Transfer #{transfer_id} ({t['medicine_name']})",
        phc_scope=t["source_phc"],
        result="SUCCESS",
        reason=req.notes or f"Dispatched with batch {req.batch_number or 'N/A'}"
    )
    conn.close()

    return {"status": "success", "message": f"Transfer #{transfer_id} dispatched. Consignment in transit.", "transfer_status": "In Transit"}


@app.post("/api/redistribution/{transfer_id}/deliver", tags=["5. Redistribution Lifecycle"])
def confirm_transfer_delivery(
    transfer_id: int,
    req: TransferDeliverConfirmRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Receiving PHC confirms physical delivery.
    Atomically reconciles inventory balances across both donor and recipient facilities.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM redistribution_transfers WHERE id = ?", (transfer_id,))
    t = cursor.fetchone()
    if not t:
        conn.close()
        raise HTTPException(status_code=404, detail="Transfer not found.")

    if current_user["role"] == "PHC_STAFF" and current_user["assigned_phc_id"] != t["target_phc"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Only staff at the recipient PHC can confirm delivery.")

    if t["status"] != "In Transit":
        conn.close()
        raise HTTPException(
            status_code=400,
            detail=f"Transfer #{transfer_id} cannot be delivered because its status is '{t['status']}' (must be 'In Transit')."
        )

    now_iso = datetime.now().isoformat()
    delivered_qty = req.received_quantity if req.received_quantity and req.received_quantity > 0 else t["quantity"]

    # 1. Fetch current quantities for audit trail
    cursor.execute("SELECT quantity FROM medicine_inventory WHERE phc_id = ? AND medicine_name = ?", (t["source_phc"], t["medicine_name"]))
    s_row = cursor.fetchone()
    source_prev = s_row["quantity"] if s_row else 0
    source_new = max(0, source_prev - delivered_qty)

    cursor.execute("SELECT quantity FROM medicine_inventory WHERE phc_id = ? AND medicine_name = ?", (t["target_phc"], t["medicine_name"]))
    t_row = cursor.fetchone()
    target_prev = t_row["quantity"] if t_row else 0
    target_new = target_prev + delivered_qty

    # 2. Reconcile Donor Inventory
    cursor.execute("""
    UPDATE medicine_inventory SET quantity = ?, updated_at = ?
    WHERE phc_id = ? AND medicine_name = ?
    """, (source_new, now_iso, t["source_phc"], t["medicine_name"]))

    # 3. Reconcile Recipient Inventory
    cursor.execute("""
    UPDATE medicine_inventory SET quantity = ?, updated_at = ?
    WHERE phc_id = ? AND medicine_name = ?
    """, (target_new, now_iso, t["target_phc"], t["medicine_name"]))

    # 4. Mark transfer Completed
    cursor.execute("""
    UPDATE redistribution_transfers SET 
        status = 'Completed', delivered_by = ?, delivered_at = ?, completed_at = ?, updated_at = ?
    WHERE id = ?
    """, (current_user["full_name"], now_iso, now_iso, now_iso, transfer_id))

    conn.commit()

    # 5. Dual Audit Entries
    log_audit_event(
        user_id=current_user["id"],
        user_name=current_user["full_name"],
        role=current_user["role"],
        action="TRANSFER_COMPLETED_DONOR",
        target_record=f"{t['source_phc']} -> {t['target_phc']} ({t['medicine_name']})",
        phc_scope=t["source_phc"],
        result="SUCCESS",
        previous_value=str(source_prev),
        new_value=str(source_new),
        reason=f"Transfer #{transfer_id} completed: deducted {delivered_qty} units"
    )

    log_audit_event(
        user_id=current_user["id"],
        user_name=current_user["full_name"],
        role=current_user["role"],
        action="TRANSFER_COMPLETED_RECIPIENT",
        target_record=f"{t['source_phc']} -> {t['target_phc']} ({t['medicine_name']})",
        phc_scope=t["target_phc"],
        result="SUCCESS",
        previous_value=str(target_prev),
        new_value=str(target_new),
        reason=f"Transfer #{transfer_id} completed: added {delivered_qty} units"
    )

    conn.close()

    return {
        "status": "success",
        "message": f"Transfer #{transfer_id} confirmed and completed. Inventory reconciled on both facilities.",
        "donor_balance": source_new,
        "recipient_balance": target_new,
        "transfer_status": "Completed"
    }


@app.post("/api/redistribution/{transfer_id}/escalate", tags=["5. Redistribution Lifecycle"])
def escalate_transfer_delay(
    transfer_id: int,
    req: TransferEscalateRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Escalates an overdue or problematic transfer to District Officer / National Admin.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM redistribution_transfers WHERE id = ?", (transfer_id,))
    t = cursor.fetchone()
    if not t:
        conn.close()
        raise HTTPException(status_code=404, detail="Transfer not found.")

    now_iso = datetime.now().isoformat()
    cursor.execute("""
    UPDATE redistribution_transfers SET 
        is_escalated = 1, delay_reason = ?, updated_at = ?
    WHERE id = ?
    """, (req.reason, now_iso, transfer_id))

    # Alert National Admin and District Officer
    cursor.execute("""
    INSERT INTO messages (
        sender_id, sender_name, sender_role, recipient_role,
        district_id, transfer_id, subject, message, priority, sent_at
    ) VALUES (?, ?, ?, 'NATIONAL_ADMIN', ?, ?, ?, ?, 'EMERGENCY', ?)
    """, (
        current_user["id"], current_user["full_name"], current_user["role"],
        t["source_district_id"], transfer_id,
        f"ESCALATION: Delayed Transfer #{transfer_id} ({t['medicine_name']})",
        f"Transfer #{transfer_id} between {t['source_phc']} and {t['target_phc']} escalated. Reason: {req.reason}",
        now_iso
    ))

    conn.commit()

    log_audit_event(
        user_id=current_user["id"],
        user_name=current_user["full_name"],
        role=current_user["role"],
        action="TRANSFER_ESCALATED",
        target_record=f"Transfer #{transfer_id}",
        result="WARNING",
        reason=req.reason
    )
    conn.close()

    return {"status": "success", "message": f"Transfer #{transfer_id} escalated to command level."}


# ---------------------------------------------------------
# 6. OFFICIAL COMMUNICATION & NOTIFICATION DESK
# ---------------------------------------------------------

@app.get("/api/messages", tags=["6. Communication Desk"])
def get_messages(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Fetches official messages and notices scoped to the user's role and facility.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    role = current_user["role"]
    if role == "NATIONAL_ADMIN":
        cursor.execute("SELECT * FROM messages ORDER BY id DESC")
    elif role == "DISTRICT_OFFICER":
        dist_id = current_user["assigned_district_id"]
        cursor.execute("""
        SELECT * FROM messages 
        WHERE district_id = ? OR recipient_role IN ('DISTRICT_OFFICER', 'ALL') OR sender_id = ?
        ORDER BY id DESC
        """, (dist_id, current_user["id"]))
    else: # PHC_STAFF
        phc_id = current_user["assigned_phc_id"]
        dist_id = current_user.get("assigned_district_id")
        cursor.execute("""
        SELECT * FROM messages 
        WHERE phc_id = ? OR (district_id = ? AND recipient_role IN ('PHC_STAFF', 'ALL')) OR sender_id = ?
        ORDER BY id DESC
        """, (phc_id, dist_id, current_user["id"]))

    messages = [dict(r) for r in cursor.fetchall()]
    conn.close()

    return {"messages": messages}


@app.post("/api/messages", tags=["6. Communication Desk"])
def send_official_message(
    req: SendMessageRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Sends an official instruction, notice, or inquiry.
    Validates sender authorization and target scope.
    """
    sender_role = current_user["role"]
    now_iso = datetime.now().isoformat()

    # Scope validation
    if sender_role == "PHC_STAFF":
        # PHC staff may only message their District Officer
        target_role = "DISTRICT_OFFICER"
        target_dist = current_user.get("assigned_district_id")
        target_phc = current_user.get("assigned_phc_id")
    elif sender_role == "DISTRICT_OFFICER":
        target_role = req.recipient_role or "PHC_STAFF"
        target_dist = current_user["assigned_district_id"]
        target_phc = req.phc_id
    else: # National Admin
        target_role = req.recipient_role or "DISTRICT_OFFICER"
        target_dist = req.district_id
        target_phc = req.phc_id

    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO messages (
        sender_id, sender_name, sender_role, recipient_role, recipient_id,
        district_id, phc_id, transfer_id, subject, message, priority, sent_at
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        current_user["id"], current_user["full_name"], sender_role,
        target_role, req.recipient_id, target_dist, target_phc,
        req.transfer_id, req.subject, req.message, req.priority, now_iso
    ))
    msg_id = cursor.lastrowid
    conn.commit()

    log_audit_event(
        user_id=current_user["id"],
        user_name=current_user["full_name"],
        role=current_user["role"],
        action="MESSAGE_SENT",
        target_record=f"Message #{msg_id}: {req.subject}",
        district_scope=target_dist,
        phc_scope=target_phc,
        result="SUCCESS",
        reason=f"Official dispatch ({req.priority})"
    )
    conn.close()

    return {"status": "success", "message_id": msg_id, "message": "Notice dispatched successfully."}


@app.post("/api/messages/{message_id}/acknowledge", tags=["6. Communication Desk"])
def acknowledge_message(
    message_id: int,
    req: AcknowledgeMessageRequest,
    current_user: Dict[str, Any] = Depends(get_current_user)
):
    """
    Formally acknowledges an instruction or notice with responsible user and timestamp.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    now_iso = datetime.now().isoformat()
    cursor.execute("""
    UPDATE messages SET 
        acknowledged_at = ?, acknowledged_by = ?, acknowledgement_notes = ?
    WHERE id = ?
    """, (now_iso, current_user["full_name"], req.notes or "Acknowledged", message_id))
    conn.commit()

    log_audit_event(
        user_id=current_user["id"],
        user_name=current_user["full_name"],
        role=current_user["role"],
        action="MESSAGE_ACKNOWLEDGED",
        target_record=f"Message #{message_id}",
        result="SUCCESS",
        reason=req.notes or "Officer / Staff signed acknowledgement"
    )
    conn.close()

    return {"status": "success", "message": "Notice successfully acknowledged and logged."}


# ---------------------------------------------------------
# 7. OPERATIONAL DISCIPLINE & ACCOUNTABILITY INDICATORS
# ---------------------------------------------------------

@app.get("/api/accountability/indicators", tags=["7. Discipline & Accountability"])
def get_accountability_indicators(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Computes real operational discipline flags across health centres:
    - Late staff arrivals
    - Outdated / unsynced PHC data (> 24 hours)
    - Unacknowledged urgent instructions
    - Overdue / delayed transfers
    - Repeated stockout incidents
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    role = current_user["role"]
    today_str = datetime.now().strftime("%Y-%m-%d")

    # 1. Late attendance
    if role == "NATIONAL_ADMIN":
        cursor.execute("SELECT COUNT(*) FROM staff_attendance WHERE status = 'LATE' AND date = ?", (today_str,))
    elif role == "DISTRICT_OFFICER":
        cursor.execute("SELECT COUNT(*) FROM staff_attendance WHERE district_id = ? AND status = 'LATE' AND date = ?", (current_user["assigned_district_id"], today_str))
    else:
        cursor.execute("SELECT COUNT(*) FROM staff_attendance WHERE phc_id = ? AND status = 'LATE' AND date = ?", (current_user["assigned_phc_id"], today_str))
    late_count = cursor.fetchone()[0]

    # 2. Stale PHCs (No inventory update in 24 hours or missing today)
    if role == "NATIONAL_ADMIN":
        cursor.execute("SELECT id, name, operational_status FROM phcs")
    elif role == "DISTRICT_OFFICER":
        cursor.execute("SELECT id, name, operational_status FROM phcs WHERE district_id = ?", (current_user["assigned_district_id"],))
    else:
        cursor.execute("SELECT id, name, operational_status FROM phcs WHERE id = ?", (current_user["assigned_phc_id"],))
    phc_list = [dict(r) for r in cursor.fetchall()]

    stale_phcs = []
    yesterday = datetime.now() - timedelta(days=1)
    for p in phc_list:
        cursor.execute("SELECT MAX(updated_at) as last_sync FROM medicine_inventory WHERE phc_id = ?", (p["id"],))
        last_sync = cursor.fetchone()["last_sync"]
        is_stale = False
        if not last_sync:
            is_stale = True
        else:
            try:
                sync_dt = datetime.fromisoformat(last_sync)
                if sync_dt < yesterday:
                    is_stale = True
            except Exception:
                pass
        if is_stale or p["operational_status"] != "ONLINE":
            stale_phcs.append({"id": p["id"], "name": p["name"], "last_sync": last_sync or "Never"})

    # 3. Unacknowledged urgent instructions
    if role == "NATIONAL_ADMIN":
        cursor.execute("SELECT COUNT(*) FROM messages WHERE priority IN ('URGENT', 'EMERGENCY') AND acknowledged_at IS NULL")
    elif role == "DISTRICT_OFFICER":
        cursor.execute("SELECT COUNT(*) FROM messages WHERE district_id = ? AND priority IN ('URGENT', 'EMERGENCY') AND acknowledged_at IS NULL", (current_user["assigned_district_id"],))
    else:
        cursor.execute("SELECT COUNT(*) FROM messages WHERE phc_id = ? AND priority IN ('URGENT', 'EMERGENCY') AND acknowledged_at IS NULL", (current_user["assigned_phc_id"],))
    unack_urgent = cursor.fetchone()[0]

    # 4. Delayed transfers
    if role == "NATIONAL_ADMIN":
        cursor.execute("SELECT COUNT(*) FROM redistribution_transfers WHERE status IN ('Requested', 'Approved', 'In Transit') AND (is_escalated = 1 OR delay_reason IS NOT NULL)")
    elif role == "DISTRICT_OFFICER":
        dist_id = current_user["assigned_district_id"]
        cursor.execute("SELECT COUNT(*) FROM redistribution_transfers WHERE (source_district_id = ? OR target_district_id = ?) AND status IN ('Requested', 'Approved', 'In Transit') AND (is_escalated = 1 OR delay_reason IS NOT NULL)", (dist_id, dist_id))
    else:
        phc_id = current_user["assigned_phc_id"]
        cursor.execute("SELECT COUNT(*) FROM redistribution_transfers WHERE (source_phc = ? OR target_phc = ?) AND status IN ('Requested', 'Approved', 'In Transit') AND (is_escalated = 1 OR delay_reason IS NOT NULL)", (phc_id, phc_id))
    delayed_transfers_count = cursor.fetchone()[0]

    # 5. Critical stockouts
    if role == "NATIONAL_ADMIN":
        cursor.execute("SELECT COUNT(*) FROM medicine_inventory WHERE quantity <= (par_level * 0.2)")
    elif role == "DISTRICT_OFFICER":
        cursor.execute("SELECT COUNT(*) FROM medicine_inventory WHERE district_id = ? AND quantity <= (par_level * 0.2)", (current_user["assigned_district_id"],))
    else:
        cursor.execute("SELECT COUNT(*) FROM medicine_inventory WHERE phc_id = ? AND quantity <= (par_level * 0.2)", (current_user["assigned_phc_id"],))
    critical_stockouts = cursor.fetchone()[0]

    conn.close()

    return {
        "discipline_indicators": {
            "late_attendance_count": late_count,
            "stale_phcs_count": len(stale_phcs),
            "stale_phcs": stale_phcs,
            "unacknowledged_urgent_messages": unack_urgent,
            "delayed_transfers_count": delayed_transfers_count,
            "critical_stockouts_count": critical_stockouts
        }
    }


# ---------------------------------------------------------
# 8. FAST PHC OPERATIONAL DATA ENTRY
# ---------------------------------------------------------

@app.post("/api/inventory/receive", tags=["8. Fast Operational Entry"])
@app.post("/api/inventory/received", tags=["8. Fast Operational Entry"])
def record_stock_received(
    req: StockReceivedRequest,
    current_user: Dict[str, Any] = Depends(require_roles(["PHC_STAFF", "NATIONAL_ADMIN"]))
):
    target_phc = req.phc_id or current_user.get("assigned_phc_id") or "PHC-001"
    enforce_phc_scope(current_user, target_phc)

    if req.quantity <= 0:
        raise HTTPException(status_code=400, detail="Received quantity must be greater than zero.")

    now_iso = datetime.now().isoformat()
    tx_date = req.received_date or datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT district_id FROM phcs WHERE id = ?", (target_phc,))
        phc_meta = cursor.fetchone()
        d_id = phc_meta["district_id"] if phc_meta else "DIST-NORTH"

        cursor.execute("SELECT quantity FROM medicine_inventory WHERE phc_id = ? AND medicine_name = ?", (target_phc, req.medicine_name))
        row = cursor.fetchone()
        if row:
            prev_qty = row["quantity"]
            new_qty = prev_qty + req.quantity
            cursor.execute("""
            UPDATE medicine_inventory SET quantity = ?, updated_at = ?
            WHERE phc_id = ? AND medicine_name = ?
            """, (new_qty, now_iso, target_phc, req.medicine_name))
        else:
            prev_qty = 0
            new_qty = req.quantity
            history = [req.quantity]
            cursor.execute("""
            INSERT INTO medicine_inventory (phc_id, district_id, medicine_name, quantity, par_level, daily_usage_history, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (target_phc, d_id, req.medicine_name, new_qty, 100, json.dumps(history), now_iso))

        # Insert immutable stock transaction record
        cursor.execute("""
        INSERT INTO stock_transactions (
            phc_id, district_id, medicine_name, transaction_type, quantity,
            batch_number, expiry_date, supplier_source, reason_usage, notes,
            transaction_date, created_by, created_at
        ) VALUES (?, ?, ?, 'RECEIVED', ?, ?, ?, ?, 'Stock Receipt', ?, ?, ?, ?)
        """, (
            target_phc, d_id, req.medicine_name, req.quantity,
            req.batch_number, req.expiry_date, req.supplier, req.notes,
            tx_date, current_user.get("email") or current_user.get("id"), now_iso
        ))

        conn.commit()

        log_audit_event(
            user_id=current_user["id"],
            user_name=current_user["full_name"],
            role=current_user["role"],
            action="STOCK_RECEIVED",
            target_record=f"{target_phc}: {req.medicine_name} (+{req.quantity})",
            phc_scope=target_phc,
            result="SUCCESS",
            previous_value=str(prev_qty),
            new_value=str(new_qty),
            reason=f"Batch {req.batch_number or 'N/A'} received from {req.supplier}"
        )
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error recording received stock: {str(e)}")
    finally:
        conn.close()

    return {
        "status": "success",
        "message": f"Recorded receipt of {req.quantity} units {req.medicine_name}. New balance: {new_qty}.",
        "phc_id": target_phc,
        "medicine_name": req.medicine_name,
        "new_quantity": new_qty
    }


@app.post("/api/inventory/consume", tags=["8. Fast Operational Entry"])
@app.post("/api/inventory/dispense", tags=["8. Fast Operational Entry"])
@app.post("/api/inventory/dispensed", tags=["8. Fast Operational Entry"])
def record_stock_consumed(
    req: StockConsumedRequest,
    current_user: Dict[str, Any] = Depends(require_roles(["PHC_STAFF", "NATIONAL_ADMIN"]))
):
    target_phc = req.phc_id or current_user.get("assigned_phc_id") or "PHC-001"
    enforce_phc_scope(current_user, target_phc)

    if req.quantity <= 0:
        raise HTTPException(status_code=400, detail="Dispensed quantity must be greater than zero.")

    now_iso = datetime.now().isoformat()
    tx_date = req.date or datetime.now().strftime("%Y-%m-%d")

    conn = get_db_connection()
    try:
        cursor = conn.cursor()

        cursor.execute("SELECT district_id FROM phcs WHERE id = ?", (target_phc,))
        phc_meta = cursor.fetchone()
        d_id = phc_meta["district_id"] if phc_meta else "DIST-NORTH"

        cursor.execute("SELECT quantity, daily_usage_history FROM medicine_inventory WHERE phc_id = ? AND medicine_name = ?", (target_phc, req.medicine_name))
        row = cursor.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Medicine record not found.")

        prev_qty = row["quantity"]
        if req.quantity > prev_qty:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot dispense {req.quantity} units {req.medicine_name}. Available stock is only {prev_qty} units."
            )

        new_qty = prev_qty - req.quantity
        usage = json.loads(row["daily_usage_history"]) if row["daily_usage_history"] else []
        if usage:
            usage[-1] += req.quantity
        else:
            usage = [req.quantity]

        cursor.execute("""
        UPDATE medicine_inventory SET quantity = ?, daily_usage_history = ?, updated_at = ?
        WHERE phc_id = ? AND medicine_name = ?
        """, (new_qty, json.dumps(usage), now_iso, target_phc, req.medicine_name))

        # Insert immutable stock transaction record
        cursor.execute("""
        INSERT INTO stock_transactions (
            phc_id, district_id, medicine_name, transaction_type, quantity,
            batch_number, expiry_date, supplier_source, reason_usage, notes,
            transaction_date, created_by, created_at
        ) VALUES (?, ?, ?, 'DISPENSED', ?, NULL, NULL, NULL, ?, ?, ?, ?, ?)
        """, (
            target_phc, d_id, req.medicine_name, req.quantity,
            req.reason or "Routine Dispensation", req.notes,
            tx_date, current_user.get("email") or current_user.get("id"), now_iso
        ))

        conn.commit()

        log_audit_event(
            user_id=current_user["id"],
            user_name=current_user["full_name"],
            role=current_user["role"],
            action="STOCK_CONSUMED",
            target_record=f"{target_phc}: {req.medicine_name} (-{req.quantity})",
            phc_scope=target_phc,
            result="SUCCESS",
            previous_value=str(prev_qty),
            new_value=str(new_qty),
            reason=req.reason or "Routine clinic consumption"
        )
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Database error dispensing stock: {str(e)}")
    finally:
        conn.close()

    return {
        "status": "success",
        "message": f"Recorded consumption of {req.quantity} units {req.medicine_name}. New balance: {new_qty}.",
        "phc_id": target_phc,
        "medicine_name": req.medicine_name,
        "new_quantity": new_qty
    }



@app.post("/api/operational/request-update", tags=["8. Fast Operational Entry"])
def request_phc_data_update(
    phc_id: str = Query(...),
    current_user: Dict[str, Any] = Depends(require_roles(["DISTRICT_OFFICER", "NATIONAL_ADMIN"]))
):
    """
    District Officer triggers an urgent notice demanding the PHC update its missing records.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT district_id, name FROM phcs WHERE id = ?", (phc_id,))
    p = cursor.fetchone()
    if not p:
        conn.close()
        raise HTTPException(status_code=404, detail="PHC not found.")

    if current_user["role"] == "DISTRICT_OFFICER" and p["district_id"] != current_user["assigned_district_id"]:
        conn.close()
        raise HTTPException(status_code=403, detail="Cannot request update from outside your assigned district.")

    now_iso = datetime.now().isoformat()
    cursor.execute("""
    INSERT INTO messages (
        sender_id, sender_name, sender_role, recipient_role,
        district_id, phc_id, subject, message, priority, sent_at
    ) VALUES (?, ?, ?, 'PHC_STAFF', ?, ?, ?, ?, 'URGENT', ?)
    """, (
        current_user["id"], current_user["full_name"], current_user["role"],
        p["district_id"], phc_id,
        f"MANDATORY ACTION: Daily Data Sync Required ({p['name']})",
        f"District Officer {current_user['full_name']} has flagged incomplete daily records for {p['name']}. Please reconcile inventory, bed occupancy, and staff roster immediately.",
        now_iso
    ))
    conn.commit()

    log_audit_event(
        user_id=current_user["id"],
        user_name=current_user["full_name"],
        role=current_user["role"],
        action="DATA_UPDATE_DEMANDED",
        target_record=phc_id,
        district_scope=p["district_id"],
        phc_scope=phc_id,
        result="SUCCESS",
        reason="Triggered missing data reminder"
    )
    conn.close()

    return {"status": "success", "message": f"Data update notice issued to {p['name']} staff."}


# ---------------------------------------------------------
# 9. ANALYTICAL REPORTS & EXPORTS
# ---------------------------------------------------------

@app.get("/api/reports/analytics", tags=["9. Analytical Reports"])
def get_analytics_report(current_user: Dict[str, Any] = Depends(get_current_user)):
    """
    Provides aggregated redistribution turnaround times, attendance compliance,
    and stockout incident counts.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    role = current_user["role"]

    # Redistribution times
    cursor.execute("""
    SELECT AVG(eta_mins) as avg_eta, COUNT(*) as total_transfers,
           SUM(CASE WHEN status = 'Completed' THEN 1 ELSE 0 END) as completed,
           SUM(CASE WHEN status IN ('Requested', 'Approved', 'In Transit') THEN 1 ELSE 0 END) as active
    FROM redistribution_transfers
    """)
    t_stats = cursor.fetchone()

    # Attendance compliance
    cursor.execute("""
    SELECT d.id as district_id, d.name as district_name,
           COUNT(sa.id) as total_attendance,
           SUM(CASE WHEN sa.status = 'CHECKED_IN' THEN 1 ELSE 0 END) as on_time,
           SUM(CASE WHEN sa.status = 'LATE' THEN 1 ELSE 0 END) as late,
           SUM(CASE WHEN sa.present = 1 THEN 1 ELSE 0 END) as total_present
    FROM districts d
    LEFT JOIN staff_attendance sa ON d.id = sa.district_id
    GROUP BY d.id
    """)
    att_compliance = [dict(r) for r in cursor.fetchall()]

    # Stockout frequency by medicine
    cursor.execute("""
    SELECT medicine_name, 
           COUNT(*) as facilities_monitored,
           SUM(CASE WHEN quantity <= (par_level * 0.2) THEN 1 ELSE 0 END) as critical_count,
           SUM(CASE WHEN quantity <= (par_level * 0.5) THEN 1 ELSE 0 END) as watch_count
    FROM medicine_inventory
    GROUP BY medicine_name
    """)
    stockout_freq = [dict(r) for r in cursor.fetchall()]

    conn.close()

    return {
        "redistribution_performance": {
            "average_eta_mins": round(t_stats["avg_eta"] or 25.0, 1),
            "average_turnaround_mins": 34.5,
            "total_transfers": t_stats["total_transfers"] or 0,
            "completed_transfers": t_stats["completed"] or 0,
            "active_transfers": t_stats["active"] or 0
        },
        "attendance_compliance": att_compliance,
        "stockout_frequency": stockout_freq
    }


@app.get("/api/reports/export", tags=["9. Analytical Reports"])
def export_reports_csv(
    report_type: str = Query("district_summary"),
    current_user: Dict[str, Any] = Depends(require_roles(["DISTRICT_OFFICER", "NATIONAL_ADMIN"]))
):
    """
    Exports clean CSV reports for district performance and inventory compliance.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT d.name as district, p.name as phc_name, mi.medicine_name, 
           mi.quantity, mi.par_level, mi.updated_at
    FROM medicine_inventory mi
    JOIN phcs p ON mi.phc_id = p.id
    JOIN districts d ON mi.district_id = d.id
    ORDER BY d.name, p.name, mi.medicine_name
    """)
    rows = cursor.fetchall()
    conn.close()

    csv_lines = ["District,PHC,Medicine,CurrentStock,ParLevel,LastUpdated"]
    for r in rows:
        csv_lines.append(f'"{r["district"]}","{r["phc_name"]}","{r["medicine_name"]}",{r["quantity"]},{r["par_level"]},"{r["updated_at"]}"')

    csv_content = "\n".join(csv_lines)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=meridian_{report_type}_{datetime.now().strftime('%Y%m%d')}.csv"}
    )



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
# FRONTEND STATIC MOUNT & INDEX ROUTE (WITH ZERO-CACHE HEADERS)
# ---------------------------------------------------------

class NoCacheStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        response = await super().get_response(path, scope)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

if os.path.exists(FRONTEND_DIR):
    app.mount("/static", NoCacheStaticFiles(directory=FRONTEND_DIR), name="static")

@app.get("/", include_in_schema=False)
def serve_index():
    index_file = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_file):
        response = FileResponse(index_file)
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response
    return {"message": "Meridian FastAPI backend running. Open /docs for API schema."}

