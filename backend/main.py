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
    PatientFootfallCreate, TransferActionRequest
)
from backend.forecasting import forecast_demand_linear_regression
from backend.redistribution import generate_redistribution_recommendations
from backend.privacy import encrypt_field, decrypt_field, tokenize_identifier, add_dp_noise
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


@app.get("/api/staff", tags=["1. CRUD - Staff"])
def get_staff(phc_id: str | None = None):
    conn = get_db_connection()
    cursor = conn.cursor()
    if phc_id:
        cursor.execute("SELECT * FROM staff_attendance WHERE phc_id = ?", (phc_id,))
    else:
        cursor.execute("SELECT * FROM staff_attendance")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows

@app.post("/api/staff/log", tags=["1. CRUD - Staff"])
def log_staff_attendance(data: StaffAttendanceCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    enc_id = encrypt_field(data.staff_id)
    tok_id = tokenize_identifier(data.staff_id)
    
    cursor.execute("""
    INSERT INTO staff_attendance (phc_id, staff_id, staff_id_encrypted, staff_token, present, date)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (data.phc_id, data.staff_id, enc_id, tok_id, data.present, data.date))
    
    conn.commit()
    conn.close()
    return {"status": "success", "token": tok_id, "encrypted_id": enc_id}


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

    cursor.execute("SELECT * FROM staff_attendance WHERE phc_id = ?", (phc_id,))
    staff_rows = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM patient_footfall WHERE phc_id = ? ORDER BY date ASC", (phc_id,))
    footfall_rows = [dict(r) for r in cursor.fetchall()]

    conn.close()

    return {
        "phc_id": phc_id,
        "inventory": inventory,
        "bed_status": bed_data,
        "staff_attendance": staff_rows,
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

    # Bed rollups
    cursor.execute("SELECT SUM(total_beds) as total, SUM(occupied_beds) as occ FROM bed_status")
    bed_sum = cursor.fetchone()
    total_beds = bed_sum["total"] or 0
    occ_beds = bed_sum["occ"] or 0

    # Footfall aggregate
    cursor.execute("SELECT SUM(count) as total_footfall FROM patient_footfall")
    footfall_sum = cursor.fetchone()["total_footfall"] or 0

    conn.close()

    # Differential privacy simulation for aggregate counts shown above PHC level
    dp_footfall = add_dp_noise(footfall_sum)
    dp_beds = add_dp_noise(occ_beds)

    return {
        "district_id": district_id,
        "phcs_covered": ["PHC-001", "PHC-002", "PHC-003", "PHC-004"],
        "critical_par_level_warnings": par_level_warnings,
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

    brics_nodes = [
        {"node_id": "PHC-001", "name": "Alpha Central PHC", "nation": "India (Host)", "status": "ACTIVE_FEDERATED_NODE", "is_simulated": False},
        {"node_id": "PHC-002", "name": "Beta Regional PHC", "nation": "India (Host)", "status": "ACTIVE_FEDERATED_NODE", "is_simulated": False},
        {"node_id": "PHC-003", "name": "Gamma Sao Paulo Clinic", "nation": "Brazil (Partner)", "status": "SIMULATED_FEDERATED_NODE", "is_simulated": True},
        {"node_id": "PHC-004", "name": "Delta Johannesburg Clinic", "nation": "South Africa (Partner)", "status": "SIMULATED_FEDERATED_NODE", "is_simulated": True}
    ]

    return {
        "platform_name": "Meridian National & BRICS Health Supply Chain Platform",
        "timestamp": datetime.now().isoformat(),
        "district_overview": district_data,
        "active_redistribution_recommendations": recs["active_recommendations"],
        "federated_learning": fl_data,
        "brics_simulation_nodes": brics_nodes,
        "simulation_disclaimer": "BRICS cross-border nodes (Brazil & South Africa) are clearly marked SIMULATED nodes exchanging model weights only (no raw patient data transmitted)."
    }


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
