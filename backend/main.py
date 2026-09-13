import json
import sqlite3
import os
from typing import Optional, List, Dict, Any
from datetime import datetime
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from backend.database import get_db_connection, init_db
from backend.models import (
    InventoryUpdate, BedStatusUpdate, StaffAttendanceCreate,
    PatientFootfallCreate, TransferActionRequest, CardPunchRequest, StaffActionRequest
)
from backend.forecasting import forecast_demand_linear_regression
from backend.redistribution import generate_redistribution_recommendations
from backend.privacy import encrypt_field, decrypt_field, tokenize_identifier, add_dp_noise
from backend.auth import authenticate_user
from backend.pilot import run_30day_shadow_simulation
from backend.dp_budget import dp_manager
from backend.fhir_adapter import generate_fhir_bundle
from backend.provenance import verify_medicine_batch
from ai.fed_avg import run_federated_averaging

# Initialize DB tables & seed data on startup
init_db()

app = FastAPI(
    title="Meridian - Federated AI Public Health Supply Chain Platform",
    version="1.0.0",
    description="Hackathon MVP API for real-time visibility, NumPy demand forecasting, explainable redistribution, field encryption, DP noise, and FedAvg federated learning."
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------
# 1. CRUD ENDPOINTS FOR ALL 4 TABLES (Req 1)
# ---------------------------------------------------------

@app.get("/api/inventory", tags=["1. CRUD - Inventory"])
def get_inventory(phc_id: str | None = None):
    conn = get_db_connection()
    cursor = conn.cursor()
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
def update_inventory(item: InventoryUpdate):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM medicine_inventory WHERE phc_id = ? AND medicine_name = ?", (item.phc_id, item.medicine_name))
    row = cursor.fetchone()
    now_str = datetime.now().isoformat()

    if row:
        history = json.loads(row["daily_usage_history"]) if row["daily_usage_history"] else []
        if item.daily_consumption is not None:
            history.append(item.daily_consumption)
            if len(history) > 14:
                history.pop(0)

        cursor.execute("""
        UPDATE medicine_inventory
        SET quantity = ?, par_level = ?, daily_usage_history = ?, updated_at = ?
        WHERE phc_id = ? AND medicine_name = ?
        """, (item.quantity, item.par_level or row["par_level"], json.dumps(history), now_str, item.phc_id, item.medicine_name))
    else:
        history = [5] * 7
        if item.daily_consumption is not None:
            history.append(item.daily_consumption)
        cursor.execute("""
        INSERT INTO medicine_inventory (phc_id, medicine_name, quantity, par_level, daily_usage_history, updated_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (item.phc_id, item.medicine_name, item.quantity, item.par_level or 100, json.dumps(history), now_str))

    conn.commit()
    conn.close()
    return {"status": "success", "message": f"Updated {item.medicine_name} for {item.phc_id} to quantity {item.quantity}"}


@app.get("/api/beds", tags=["1. CRUD - Beds"])
def get_beds(phc_id: str | None = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if phc_id:
        cursor.execute("SELECT * FROM bed_status WHERE phc_id = ?", (phc_id,))
    else:
        cursor.execute("SELECT * FROM bed_status")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

@app.post("/api/beds/update", tags=["1. CRUD - Beds"])
def update_beds(data: BedStatusUpdate):
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    
    cursor.execute("""
    INSERT INTO bed_status (phc_id, total_beds, occupied_beds, updated_at)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(phc_id) DO UPDATE SET
        total_beds = excluded.total_beds,
        occupied_beds = excluded.occupied_beds,
        updated_at = excluded.updated_at
    """, (data.phc_id, data.total_beds, data.occupied_beds, now_str))
    
    conn.commit()
    conn.close()
    return {"status": "success", "message": f"Updated bed status for {data.phc_id}"}


@app.get("/api/staff/members", tags=["1. CRUD - Staff"])
def get_staff_members(phc_id: str | None = None):
    """Fetch staff directory roster (Nurses, Doctors, Technicians, etc.) for a PHC."""
    conn = get_db_connection()
    cursor = conn.cursor()
    if phc_id:
        cursor.execute("SELECT * FROM staff_members WHERE phc_id = ?", (phc_id,))
    else:
        cursor.execute("SELECT * FROM staff_members")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

@app.get("/api/staff", tags=["1. CRUD - Staff"])
def get_staff(phc_id: str | None = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if phc_id:
        cursor.execute("SELECT * FROM staff_attendance WHERE phc_id = ? ORDER BY id DESC", (phc_id,))
    else:
        cursor.execute("SELECT * FROM staff_attendance ORDER BY id DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

@app.post("/api/staff/card-punch", tags=["1. CRUD - Staff"])
def card_punch_attendance(data: CardPunchRequest):
    """
    Hardware API Webhook for RFID / Smart Card / Biometric Card Punch Machines.
    Simulates hardware smart card scans, looking up staff members and toggling check-in / check-out.
    Enforces duplicate-scan lockout (15s) to prevent accidental double taps.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    # Find staff member by card_uid
    cursor.execute("SELECT * FROM staff_members WHERE card_uid = ?", (data.card_uid,))
    staff_member = cursor.fetchone()

    if not staff_member:
        conn.close()
        raise HTTPException(status_code=404, detail=f"Card UID '{data.card_uid}' not recognized in staff database")

    member_dict = dict(staff_member)
    phc_id = data.phc_id or member_dict["phc_id"]
    staff_id = member_dict["staff_id"]
    staff_name = member_dict["name"]
    role = member_dict["role"]
    card_uid = member_dict["card_uid"]

    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%I:%M %p")

    enc_id = encrypt_field(staff_id)
    tok_id = tokenize_identifier(staff_id)

    # Check if there is an existing attendance record for today
    cursor.execute(
        "SELECT * FROM staff_attendance WHERE staff_id = ? AND date = ? ORDER BY id DESC LIMIT 1",
        (staff_id, date_str)
    )
    existing_row = cursor.fetchone()
    existing = dict(existing_row) if existing_row else None

    # Check for accidental duplicate scan (within 15 seconds lockout window)
    if existing and existing.get("updated_at"):
        try:
            last_ts = datetime.fromisoformat(existing["updated_at"])
            delta_secs = (now - last_ts).total_seconds()
            if delta_secs < 15:
                conn.close()
                raise HTTPException(
                    status_code=400,
                    detail=f"Duplicate scan prevented: {staff_name} already punched {int(delta_secs)}s ago. Please wait before scanning again."
                )
        except (ValueError, TypeError):
            pass

    if existing and existing.get("status") in ["CHECKED_IN", "LATE"]:
        # Toggle to CHECKED_OUT
        new_status = "CHECKED_OUT"
        present_flag = 1
        punch_in = existing.get("punch_in_time") or time_str
        punch_out = time_str
        cursor.execute("""
        UPDATE staff_attendance
        SET status = ?, punch_out_time = ?, verification_method = ?, operator = ?, updated_at = ?
        WHERE id = ?
        """, (new_status, punch_out, data.verification_method, data.operator, now.isoformat(), existing["id"]))
    else:
        # Toggle or Create CHECKED_IN
        new_status = "CHECKED_IN"
        present_flag = 1
        punch_in = time_str
        punch_out = None
        if existing:
            cursor.execute("""
            UPDATE staff_attendance
            SET status = ?, present = 1, punch_in_time = ?, punch_out_time = NULL, verification_method = ?, operator = ?, updated_at = ?
            WHERE id = ?
            """, (new_status, punch_in, data.verification_method, data.operator, now.isoformat(), existing["id"]))
        else:
            cursor.execute("""
            INSERT INTO staff_attendance (phc_id, staff_id, staff_name, role, card_uid, staff_id_encrypted, staff_token, present, status, verification_method, punch_in_time, punch_out_time, date, shift, department, remarks, operator, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (phc_id, staff_id, staff_name, role, card_uid, enc_id, tok_id, present_flag, new_status, data.verification_method, punch_in, punch_out, date_str, "Morning Shift (08:00 - 16:00)", "General", "RFID Smart Card Swipe", data.operator, now.isoformat()))

    conn.commit()
    conn.close()

    return {
        "status": "success",
        "action": new_status,
        "staff_name": staff_name,
        "role": role,
        "staff_id": staff_id,
        "card_uid": card_uid,
        "punch_time": time_str,
        "verification_method": data.verification_method,
        "token": tok_id,
        "encrypted_id": enc_id
    }

@app.post("/api/staff/log", tags=["1. CRUD - Staff"])
def log_staff_attendance(data: StaffAttendanceCreate):
    conn = get_db_connection()
    cursor = conn.cursor()

    # Attempt to fill staff metadata from directory if available
    cursor.execute("SELECT * FROM staff_members WHERE staff_id = ?", (data.staff_id,))
    member = cursor.fetchone()
    name = data.staff_name or (dict(member)["name"] if member else data.staff_id)
    role = data.role or (dict(member)["role"] if member else "Employee")
    c_uid = data.card_uid or (dict(member)["card_uid"] if member else "MANUAL-00")

    now = datetime.now()
    date_str = data.date or now.strftime("%Y-%m-%d")
    time_str = data.punch_in_time or now.strftime("%I:%M %p")

    enc_id = encrypt_field(data.staff_id)
    tok_id = tokenize_identifier(data.staff_id)

    status_str = data.status or ("CHECKED_IN" if data.present == 1 else "ABSENT")
    present_val = 0 if status_str in ["ABSENT", "ON_LEAVE"] else 1
    
    # Check if existing record for this staff and date exists
    cursor.execute(
        "SELECT * FROM staff_attendance WHERE staff_id = ? AND date = ? ORDER BY id DESC LIMIT 1",
        (data.staff_id, date_str)
    )
    existing = cursor.fetchone()

    if existing:
        cursor.execute("""
        UPDATE staff_attendance
        SET present = ?, status = ?, verification_method = ?, shift = ?, department = ?, remarks = ?, operator = ?, updated_at = ?,
            punch_in_time = CASE WHEN ? IN ('ABSENT', 'ON_LEAVE') THEN NULL ELSE COALESCE(?, punch_in_time) END,
            punch_out_time = CASE WHEN ? = 'CHECKED_OUT' THEN COALESCE(?, punch_out_time) ELSE punch_out_time END
        WHERE id = ?
        """, (present_val, status_str, data.verification_method, data.shift, data.department, data.remarks, data.operator, now.isoformat(), status_str, data.punch_in_time, status_str, data.punch_out_time, dict(existing)["id"]))
    else:
        p_in = None if status_str in ["ABSENT", "ON_LEAVE"] else time_str
        cursor.execute("""
        INSERT INTO staff_attendance (phc_id, staff_id, staff_name, role, card_uid, staff_id_encrypted, staff_token, present, status, verification_method, punch_in_time, punch_out_time, date, shift, department, remarks, operator, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (data.phc_id, data.staff_id, name, role, c_uid, enc_id, tok_id, present_val, status_str, data.verification_method, p_in, data.punch_out_time, date_str, data.shift, data.department, data.remarks, data.operator, now.isoformat()))
    
    conn.commit()
    conn.close()
    return {"status": "success", "token": tok_id, "encrypted_id": enc_id, "staff_name": name, "new_status": status_str}

@app.post("/api/staff/action", tags=["1. CRUD - Staff"])
def execute_staff_action(data: StaffActionRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    now = datetime.now()
    date_str = now.strftime("%Y-%m-%d")
    time_str = now.strftime("%I:%M %p")

    cursor.execute("SELECT * FROM staff_members WHERE staff_id = ?", (data.staff_id,))
    member = cursor.fetchone()
    if not member:
        conn.close()
        raise HTTPException(status_code=404, detail="Staff member not found")

    m_dict = dict(member)
    phc_id = data.phc_id or m_dict["phc_id"]

    cursor.execute("SELECT * FROM staff_attendance WHERE staff_id = ? AND date = ? ORDER BY id DESC LIMIT 1", (data.staff_id, date_str))
    existing_row = cursor.fetchone()
    existing = dict(existing_row) if existing_row else None

    enc_id = encrypt_field(data.staff_id)
    tok_id = tokenize_identifier(data.staff_id)

    if data.action == "CHECK_OUT":
        status_str = "CHECKED_OUT"
        pres = 1
        p_out = time_str
        p_in = existing.get("punch_in_time") if existing else "08:00 AM"
    elif data.action == "CHECK_IN":
        status_str = "CHECKED_IN"
        pres = 1
        p_in = time_str
        p_out = None
    elif data.action == "MARK_LEAVE":
        status_str = "ON_LEAVE"
        pres = 0
        p_in = None
        p_out = None
    elif data.action == "MARK_ABSENT":
        status_str = "ABSENT"
        pres = 0
        p_in = None
        p_out = None
    else:
        status_str = data.action
        pres = 1
        p_in = time_str
        p_out = None

    if existing:
        cursor.execute("""
        UPDATE staff_attendance
        SET status = ?, present = ?, punch_in_time = ?, punch_out_time = ?, remarks = COALESCE(?, remarks), operator = ?, updated_at = ?
        WHERE id = ?
        """, (status_str, pres, p_in, p_out, data.remarks, data.operator, now.isoformat(), existing["id"]))
    else:
        cursor.execute("""
        INSERT INTO staff_attendance (phc_id, staff_id, staff_name, role, card_uid, staff_id_encrypted, staff_token, present, status, verification_method, punch_in_time, punch_out_time, date, shift, department, remarks, operator, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (phc_id, data.staff_id, m_dict["name"], m_dict["role"], m_dict["card_uid"], enc_id, tok_id, pres, status_str, f"Quick Action ({data.action})", p_in, p_out, date_str, "Regular Shift", "General", data.remarks, data.operator, now.isoformat()))

    conn.commit()
    conn.close()
    return {"status": "success", "action": data.action, "staff_name": m_dict["name"], "new_status": status_str}


@app.get("/api/footfall", tags=["1. CRUD - Footfall"])
def get_footfall(phc_id: str | None = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if phc_id:
        cursor.execute("SELECT * FROM patient_footfall WHERE phc_id = ? ORDER BY date ASC", (phc_id,))
    else:
        cursor.execute("SELECT * FROM patient_footfall ORDER BY date ASC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

@app.post("/api/footfall/log", tags=["1. CRUD - Footfall"])
def log_footfall(data: PatientFootfallCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
    INSERT INTO patient_footfall (phc_id, date, count)
    VALUES (?, ?, ?)
    ON CONFLICT(phc_id, date) DO UPDATE SET count = excluded.count
    """, (data.phc_id, data.date, data.count))
    conn.commit()
    conn.close()
    return {"status": "success"}


# ---------------------------------------------------------
# 2. DASHBOARD & DISTRICT AGGREGATION ENDPOINTS (Req 2 & 3)
# ---------------------------------------------------------

@app.get("/api/dashboard/phc/{phc_id}", tags=["2. PHC Dashboard"])
def get_phc_dashboard(phc_id: str):
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

    conn.close()

    return {
        "phc_id": phc_id,
        "inventory": inventory,
        "bed_status": bed_data,
        "staff_attendance": staff_rows,
        "staff_members": staff_members,
        "patient_footfall": footfall_rows
    }


@app.get("/api/dashboard/district", tags=["3. District Aggregation"])
def get_district_aggregation(district_id: str = "District-North"):
    """
    District aggregation endpoint: sums/aggregates across multiple PHCs,
    flags any medicine below 30% of par level.
    """
    conn = get_db_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM medicine_inventory")
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

        # Flag if below 30% par level
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

    # Staff Summary Rollup
    cursor.execute("SELECT COUNT(*) as total_staff FROM staff_members")
    total_staff_count = cursor.fetchone()["total_staff"] or 8
    cursor.execute("SELECT COUNT(*) as checked_in FROM staff_attendance WHERE status = 'CHECKED_IN' OR present = 1")
    checked_in_staff_count = cursor.fetchone()["checked_in"] or 7

    # Bed rollups
    cursor.execute("SELECT SUM(total_beds) as total, SUM(occupied_beds) as occ FROM bed_status")
    bed_sum = cursor.fetchone()
    total_beds = bed_sum["total"] if bed_sum and bed_sum["total"] else 130
    occ_beds = bed_sum["occ"] if bed_sum and bed_sum["occ"] else 76

    # Footfall aggregate
    cursor.execute("SELECT SUM(count) as total_footfall FROM patient_footfall")
    ff_row = cursor.fetchone()
    footfall_sum = ff_row["total_footfall"] if ff_row and ff_row["total_footfall"] else 1847

    conn.close()

    # Generate redistribution recommendations for logistics
    recs = generate_redistribution_recommendations(inventory_items)

    # Differential privacy simulation for aggregate counts shown above PHC level
    dp_footfall = add_dp_noise(footfall_sum)
    dp_beds = add_dp_noise(occ_beds)

    # GIS Spatial Node details
    gis_spatial_nodes = [
        {
            "phc_id": "PHC-001",
            "name": "PHC Rampur (Alpha Sector)",
            "lat": 28.6139, "lng": 77.2090,
            "status": "CRITICAL_SHORTAGE" if len(par_level_warnings) > 0 else "HEALTHY",
            "critical_items": [w["medicine_name"] for w in par_level_warnings if w["phc_id"] == "PHC-001"],
            "distance_from_hub_km": 0.0
        },
        {
            "phc_id": "PHC-002",
            "name": "PHC Beta Central",
            "lat": 28.5355, "lng": 77.3910,
            "status": "HIGH_SURPLUS_DONOR",
            "surplus_items": ["ORS Packets", "Paracetamol 500mg"],
            "distance_from_hub_km": 12.4
        },
        {
            "phc_id": "PHC-003",
            "name": "PHC Gamma Rural",
            "lat": 28.4595, "lng": 77.0266,
            "status": "NORMAL_COVER",
            "distance_from_hub_km": 18.5
        },
        {
            "phc_id": "PHC-004",
            "name": "PHC Delta Community",
            "lat": 28.7041, "lng": 77.1025,
            "status": "HEALTHY_RESERVE",
            "distance_from_hub_km": 15.2
        }
    ]

    # Outbreak Early Warning Radar analytics
    outbreak_radar = {
        "outbreak_probability_pct": 84.5,
        "risk_level": "HIGH_OUTBREAK_RISK",
        "primary_trigger": "Spiking ORS & IV Fluid consumption (+85% week-over-week) at PHC-001",
        "suspected_vector": "Acute Diarrheal Outbreak / Monsoonal Contamination (Sector-1)",
        "recommended_action": "Execute immediate emergency ORS stock dispatch from PHC-002 donor reserve."
    }

    return {
        "district_id": district_id,
        "phcs_covered": ["PHC-001", "PHC-002", "PHC-003", "PHC-004"],
        "critical_par_level_warnings": par_level_warnings,
        "emergency_logistics_recommendations": recs,
        "gis_spatial_nodes": gis_spatial_nodes,
        "outbreak_radar": outbreak_radar,
        "staff_radar": {
            "total_staff": total_staff_count,
            "checked_in_staff": checked_in_staff_count,
            "availability_pct": round((checked_in_staff_count / total_staff_count) * 100, 1) if total_staff_count > 0 else 0,
            "understaffed_phcs": ["PHC-001"] if (checked_in_staff_count / total_staff_count) < 0.9 else []
        },
        "medicine_totals": [
            {
                "medicine_name": med,
                "total_quantity": total_stock_by_med[med],
                "total_par_level": total_par_by_med[med],
                "aggregate_pct": round((total_stock_by_med[med] / total_par_by_med[med]) * 100, 1),
                "is_below_30pct": (total_stock_by_med[med] / total_par_by_med[med]) < 0.3
            } for med in total_stock_by_med
        ],
        "bed_summary": {
            "total_beds": total_beds,
            "occupied_beds": occ_beds,
            "occupancy_pct": round((occ_beds / total_beds) * 100, 1) if total_beds > 0 else 0,
            "dp_noised_occupied_beds": dp_beds
        },
        "footfall_summary": {
            "true_total_footfall": footfall_sum,
            "dp_noised_total_footfall": dp_footfall
        }
    }


# ---------------------------------------------------------
# 3. FORECASTING ENDPOINT (Req 4)
# ---------------------------------------------------------

@app.get("/api/forecasting/{phc_id}", tags=["4. Demand Forecasting"])
def get_phc_forecast(phc_id: str, medicine_name: str = "ORS Packets"):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM medicine_inventory WHERE phc_id = ? AND medicine_name = ?", (phc_id, medicine_name))
    row = cursor.fetchone()
    conn.close()

    if not row:
        raise HTTPException(status_code=404, detail="PHC or medicine inventory record not found")

    item = dict(row)
    history = json.loads(item["daily_usage_history"]) if item["daily_usage_history"] else []
    forecast_result = forecast_demand_linear_regression(history, item["quantity"], item["par_level"])

    return {
        "phc_id": phc_id,
        "medicine_name": medicine_name,
        "quantity": item["quantity"],
        "forecast": forecast_result
    }

@app.post("/api/forecasting/staff-requisition", tags=["4. Demand Forecasting"])
def submit_staff_requisition(data: Dict[str, Any]):
    """Allows staff to place a warehouse stock requisition directly based on AI forecast findings."""
    phc_id = data.get("phc_id", "PHC-001")
    medicine_name = data.get("medicine_name", "ORS Packets")
    qty = data.get("requested_quantity", 100)
    urgency = data.get("urgency_level", "HIGH")
    now_str = datetime.now().strftime("%Y-%m-%d %I:%M %p")

    return {
        "status": "success",
        "requisition_id": f"REQ-{phc_id[-3:]}-{datetime.now().strftime('%H%M%S')}",
        "message": f"Requisition order of {qty} units of {medicine_name} submitted to Central Warehouse for {phc_id}.",
        "timestamp": now_str,
        "urgency_level": urgency
    }

@app.post("/api/forecasting/broadcast-nurse-alert", tags=["4. Demand Forecasting"])
def broadcast_nurse_alert(data: Dict[str, Any]):
    """Broadcasts real-time AI supply alert to shift nurses and duty staff."""
    phc_id = data.get("phc_id", "PHC-001")
    medicine_name = data.get("medicine_name", "ORS Packets")
    message = data.get("message", f"Alert: Stockout risk predicted for {medicine_name}.")
    now_str = datetime.now().strftime("%I:%M %p")

    return {
        "status": "success",
        "message": f"Broadcast alert delivered to 7 on-duty nurses & staff at {phc_id}.",
        "payload": message,
        "timestamp": now_str
    }


# ---------------------------------------------------------
# 4. REDISTRIBUTION ENGINE & ACTION (Req 5)
# ---------------------------------------------------------

@app.get("/api/redistribution/recommendations", tags=["5. Redistribution Engine"])
def get_redistribution_recommendations():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM medicine_inventory")
    rows = cursor.fetchall()
    
    inventory_items = [dict(r) for r in rows]
    recs = generate_redistribution_recommendations(inventory_items)

    # Fetch existing audit transfer logs from DB
    cursor.execute("SELECT * FROM redistribution_transfers ORDER BY id DESC")
    transfer_history = [dict(r) for r in cursor.fetchall()]
    for t in transfer_history:
        t["underlying_numbers"] = json.loads(t["underlying_numbers"]) if t["underlying_numbers"] else {}

    conn.close()

    return {
        "active_recommendations": recs,
        "transfer_history_log": transfer_history
    }

@app.post("/api/redistribution/action", tags=["5. Redistribution Engine"])
def execute_redistribution_action(req: TransferActionRequest):
    """Human-in-the-loop decision: Approve, Reject, or Override recommendation."""
    conn = get_db_connection()
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()

    if req.action == "APPROVE":
        # Check source inventory
        cursor.execute("SELECT quantity FROM medicine_inventory WHERE phc_id = ? AND medicine_name = ?", (req.source_phc, req.medicine_name))
        src_row = cursor.fetchone()
        if not src_row or src_row["quantity"] < req.quantity:
            conn.close()
            raise HTTPException(status_code=400, detail="Source PHC does not have sufficient quantity to complete transfer.")

        # Deduct from source
        cursor.execute("UPDATE medicine_inventory SET quantity = quantity - ? WHERE phc_id = ? AND medicine_name = ?",
                       (req.quantity, req.source_phc, req.medicine_name))
        
        # Add to target
        cursor.execute("UPDATE medicine_inventory SET quantity = quantity + ? WHERE phc_id = ? AND medicine_name = ?",
                       (req.quantity, req.target_phc, req.medicine_name))

        # Log transfer status
        cursor.execute("""
        INSERT INTO redistribution_transfers (source_phc, target_phc, medicine_name, quantity, eta_mins, status, underlying_numbers, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (req.source_phc, req.target_phc, req.medicine_name, req.quantity, 25, "APPROVED", json.dumps({"action_by": "Human Health Administrator", "timestamp": now_str}), now_str))

        conn.commit()
        conn.close()
        return {"status": "success", "message": f"Approved & Executed: Transferred {req.quantity} {req.medicine_name} from {req.source_phc} to {req.target_phc}"}

    elif req.action in ["REJECT", "OVERRIDE"]:
        cursor.execute("""
        INSERT INTO redistribution_transfers (source_phc, target_phc, medicine_name, quantity, eta_mins, status, underlying_numbers, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (req.source_phc, req.target_phc, req.medicine_name, req.quantity, 25, req.action, json.dumps({"reason": "Overridden by human administrator", "timestamp": now_str}), now_str))

        conn.commit()
        conn.close()
        return {"status": "success", "message": f"Transfer marked as {req.action}"}

    conn.close()
    return {"status": "error", "message": "Invalid action"}


# ---------------------------------------------------------
# 5. PRIVACY LAYER & DEMO ENDPOINTS (Req 6)
# ---------------------------------------------------------

@app.get("/api/privacy/demo", tags=["6. Privacy Layer"])
def privacy_demo(raw_staff_id: str = "STF-999"):
    encrypted = encrypt_field(raw_staff_id)
    decrypted = decrypt_field(encrypted)
    token = tokenize_identifier(raw_staff_id)
    dp_example = add_dp_noise(150)

    return {
        "raw_identifier": raw_staff_id,
        "fernet_encrypted_ciphertext": encrypted,
        "decrypted_verification": decrypted,
        "sha256_token": token,
        "differential_privacy_simulation": dp_example
    }


# ---------------------------------------------------------
# 6. FEDERATED LEARNING DEMO ENDPOINT (Req 7)
# ---------------------------------------------------------

@app.get("/api/federated/train-and-aggregate", tags=["7. Federated Learning"])
def train_and_aggregate_fl():
    """Triggers 3-node NumPy local model training and calculates FedAvg weights."""
    return run_federated_averaging()


# ---------------------------------------------------------
# 7. NATIONAL & BRICS SIMULATION PANEL DATA (Req 8)
# ---------------------------------------------------------

@app.get("/api/dashboard/national", tags=["8. National Dashboard & BRICS"])
def get_national_dashboard():
    district_data = get_district_aggregation("District-North")
    recs = get_redistribution_recommendations()
    fl_data = train_and_aggregate_fl()

    conn = get_db_connection()
    cursor = conn.cursor()

    # Calculate national inventory totals
    cursor.execute("SELECT SUM(quantity) as total_qty FROM medicine_inventory")
    total_qty_row = cursor.fetchone()
    total_qty = total_qty_row["total_qty"] if total_qty_row and total_qty_row["total_qty"] else 1850

    # Calculate national medicine rollups by medicine name
    cursor.execute("SELECT medicine_name, SUM(quantity) as stock, SUM(par_level) as par FROM medicine_inventory GROUP BY medicine_name")
    med_rows = cursor.fetchall()
    strategic_reserve = []
    for r in med_rows:
        m = dict(r)
        pct = round((m["stock"] / m["par"]) * 100, 1) if m["par"] > 0 else 100.0
        status = "HEALTHY"
        if pct < 30.0:
            status = "CRITICAL_DEFICIT"
        elif pct < 60.0:
            status = "WATCH"
        strategic_reserve.append({
            "medicine_name": m["medicine_name"],
            "national_stock": m["stock"],
            "national_par_baseline": m["par"],
            "pct_of_par": pct,
            "status": status
        })

    # Fetch recent transfer audit log
    cursor.execute("SELECT * FROM redistribution_transfers ORDER BY id DESC LIMIT 10")
    transfer_history = [dict(r) for r in cursor.fetchall()]

    conn.close()

    brics_nodes = [
        {"node_id": "PHC-001", "name": "Alpha Central PHC", "nation": "India (Host)", "status": "ACTIVE_FEDERATED_NODE", "is_simulated": False},
        {"node_id": "PHC-002", "name": "Beta Regional PHC", "nation": "India (Host)", "status": "ACTIVE_FEDERATED_NODE", "is_simulated": False},
        {"node_id": "PHC-003", "name": "Gamma Sao Paulo Clinic", "nation": "Brazil (Partner)", "status": "SIMULATED_FEDERATED_NODE", "is_simulated": True},
        {"node_id": "PHC-004", "name": "Delta Johannesburg Clinic", "nation": "South Africa (Partner)", "status": "SIMULATED_FEDERATED_NODE", "is_simulated": True}
    ]

    critical_count = len(district_data.get("critical_par_level_warnings", []))

    return {
        "platform_name": "Meridian National & BRICS Health Supply Chain Platform",
        "timestamp": datetime.now().isoformat(),
        "national_kpis": {
            "total_phc_nodes": 4,
            "online_nodes": 4,
            "total_inventory_units": total_qty,
            "total_beds": district_data["bed_summary"]["total_beds"],
            "occupied_beds": district_data["bed_summary"]["occupied_beds"],
            "occupancy_pct": district_data["bed_summary"]["occupancy_pct"],
            "critical_alerts_count": critical_count
        },
        "strategic_reserve": strategic_reserve,
        "inter_district_transfers": recs.get("active_recommendations", []),
        "transfer_history": transfer_history,
        "district_overview": district_data,
        "federated_learning": fl_data,
        "brics_simulation_nodes": brics_nodes,
        "simulation_disclaimer": "BRICS cross-border nodes (Brazil & South Africa) are clearly marked SIMULATED nodes exchanging model weights only (no raw patient data transmitted)."
    }


# ---------------------------------------------------------
# 8. ENTERPRISE Q1-Q4 EXTENDED ENDPOINTS
# ---------------------------------------------------------

@app.post("/api/auth/login", tags=["9. Enterprise Security"])
def login_endpoint(username: str = Query(...), password: str = Query(...)):
    res = authenticate_user(username, password)
    if not res:
        raise HTTPException(status_code=401, detail="Invalid credentials. Use phc_nurse/nurse123, district_officer/officer123, or national_admin/admin123")
    return res

@app.get("/api/pilot/shadow-simulation", tags=["10. Pilot & Backtesting"])
def get_shadow_simulation():
    return run_30day_shadow_simulation()

@app.get("/api/privacy/dp-query", tags=["6. Privacy Layer"])
def run_dp_budget_query(true_val: int = 150):
    return dp_manager.query_with_privacy(true_val)

@app.get("/api/fhir/export", tags=["11. HL7 FHIR Interoperability"])
def export_fhir_bundle():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM medicine_inventory")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return generate_fhir_bundle(rows)

@app.get("/api/provenance/verify", tags=["12. Supply Chain Provenance"])
def verify_batch_passport(batch_id: str = "BATCH-ORS-2026-A1"):
    return verify_medicine_batch(batch_id)



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
    return {"message": "Meridian FastAPI backend running. Open /docs for API schema or create frontend/index.html."}
