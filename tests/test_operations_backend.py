import requests
import json
import sqlite3
from datetime import datetime, timedelta

BASE_URL = "http://127.0.0.1:8000"

def get_db():
    conn = sqlite3.connect("backend/meridian.db")
    conn.row_factory = sqlite3.Row
    return conn

def login(email, password):
    session = requests.Session()
    res = session.post(f"{BASE_URL}/api/auth/login", json={"username": email, "password": password})
    assert res.status_code == 200, f"Login failed for {email}: {res.text}"
    return session

def test_operations_backend():
    print("=================================================================")
    print("MERIDIAN FACILITY OPERATIONS BACKEND VERIFICATION SUITE")
    print("=================================================================")

    # 1. Login with PHC Staff (Alpha Sector, PHC-001)
    s_alpha = login("staff.alpha@meridian.health", "Staff@123")
    print("[PASS] 1. Authentication: PHC Staff Alpha logged in successfully")

    # Login with PHC Staff (Beta Central, PHC-002) for scope enforcement
    s_beta = login("staff.beta@meridian.health", "Staff@123")
    print("[PASS] 2. Authentication: PHC Staff Beta logged in successfully")

    # -------------------------------------------------------------
    # 2. MEDICINE INVENTORY - RECEIVE & DISPENSE
    # -------------------------------------------------------------
    print("\n--- A. MEDICINE INVENTORY (RECEIVE, DISPENSE, TRANSACTIONS) ---")
    
    # Check initial stock
    db = get_db()
    row = db.execute("SELECT quantity FROM medicine_inventory WHERE phc_id = 'PHC-001' AND medicine_name = 'ORS Packets'").fetchone()
    initial_qty = row["quantity"] if row else 0
    db.close()

    # Receive Stock
    res = s_alpha.post(f"{BASE_URL}/api/inventory/receive", json={
        "phc_id": "PHC-001",
        "medicine_name": "ORS Packets",
        "quantity": 50,
        "batch_number": "BATCH-TEST-001",
        "expiry_date": "2027-12-31",
        "supplier": "State Medical Depot",
        "received_date": datetime.now().strftime("%Y-%m-%d"),
        "notes": "Emergency buffer replenishment"
    })
    assert res.status_code == 200, f"Receive failed: {res.text}"
    data = res.json()
    assert data["new_quantity"] == initial_qty + 50, f"Expected {initial_qty + 50}, got {data['new_quantity']}"
    print(f"[PASS] Stock Received: +50 units ORS Packets (Balance: {data['new_quantity']})")

    # Verify transaction logged in stock_transactions table
    db = get_db()
    tx = db.execute("""
    SELECT * FROM stock_transactions 
    WHERE phc_id = 'PHC-001' AND medicine_name = 'ORS Packets' AND transaction_type = 'RECEIVED'
    ORDER BY id DESC LIMIT 1
    """).fetchone()
    assert tx is not None, "Stock transaction was not recorded in stock_transactions table"
    assert tx["quantity"] == 50
    assert tx["batch_number"] == "BATCH-TEST-001"
    db.close()
    print("[PASS] Stock Transaction table: Verified immutable 'RECEIVED' transaction logged")

    # Dispense Stock (Valid)
    res = s_alpha.post(f"{BASE_URL}/api/inventory/consume", json={
        "phc_id": "PHC-001",
        "medicine_name": "ORS Packets",
        "quantity": 10,
        "reason": "Pediatric OPD dehydration cases",
        "date": datetime.now().strftime("%Y-%m-%d"),
        "notes": "Oral rehydration for acute gastroenteritis"
    })
    assert res.status_code == 200, f"Consume failed: {res.text}"
    data = res.json()
    assert data["new_quantity"] == initial_qty + 40
    print(f"[PASS] Stock Dispensed: -10 units ORS Packets (Balance: {data['new_quantity']})")

    # Verify transaction logged in stock_transactions table
    db = get_db()
    tx = db.execute("""
    SELECT * FROM stock_transactions 
    WHERE phc_id = 'PHC-001' AND medicine_name = 'ORS Packets' AND transaction_type = 'DISPENSED'
    ORDER BY id DESC LIMIT 1
    """).fetchone()
    assert tx is not None
    assert tx["quantity"] == 10
    db.close()
    print("[PASS] Stock Transaction table: Verified immutable 'DISPENSED' transaction logged")

    # Reject Dispensing More Than Available Stock (Underflow Prevention)
    res = s_alpha.post(f"{BASE_URL}/api/inventory/consume", json={
        "phc_id": "PHC-001",
        "medicine_name": "ORS Packets",
        "quantity": 999999,
        "reason": "Exorbitant dispensation attempt"
    })
    assert res.status_code == 400, f"Expected 400 for excessive dispensation, got {res.status_code}: {res.text}"
    print(f"[PASS] Stock Underflow Rejection: Attempting to dispense 999999 returned HTTP 400 ('{res.json()['detail']}')")

    # Reject Invalid Quantities (<= 0)
    res = s_alpha.post(f"{BASE_URL}/api/inventory/receive", json={"phc_id": "PHC-001", "medicine_name": "ORS Packets", "quantity": 0})
    assert res.status_code == 400 or res.status_code == 422
    res = s_alpha.post(f"{BASE_URL}/api/inventory/consume", json={"phc_id": "PHC-001", "medicine_name": "ORS Packets", "quantity": -5})
    assert res.status_code == 400 or res.status_code == 422
    print("[PASS] Validation: Non-positive quantities properly rejected")

    # Reject Cross-PHC Inventory Update
    res = s_alpha.post(f"{BASE_URL}/api/inventory/receive", json={"phc_id": "PHC-002", "medicine_name": "ORS Packets", "quantity": 10})
    assert res.status_code == 403, f"Expected 403 for unauthorized facility, got {res.status_code}"
    print("[PASS] Scope Enforcement: Staff Alpha updating Facility Beta rejected with HTTP 403 Forbidden")

    # -------------------------------------------------------------
    # 3. RESOURCE REQUEST & DUPLICATE 409 CONFLICT
    # -------------------------------------------------------------
    print("\n--- B. RESOURCE REDISTRIBUTION REQUEST (409 DUPLICATE CHECK) ---")
    
    # Create request
    test_med = "Iron folic acid"
    db = get_db()
    db.execute("DELETE FROM redistribution_transfers WHERE target_phc = 'PHC-001' AND medicine_name = ?", (test_med,))
    db.commit()
    db.close()

    res = s_alpha.post(f"{BASE_URL}/api/redistribution/request", json={
        "medicine_name": test_med,
        "quantity": 30,
        "urgency": "URGENT",
        "reason": "Maternal health anemia spike"
    })
    assert res.status_code == 200, f"Create transfer failed: {res.text}"
    print(f"[PASS] Resource Request created for {test_med} (HTTP 200)")

    # Attempt Duplicate Request for same medicine while pending
    res_dup = s_alpha.post(f"{BASE_URL}/api/redistribution/request", json={
        "medicine_name": test_med,
        "quantity": 20,
        "urgency": "URGENT",
        "reason": "Duplicate attempt"
    })
    assert res_dup.status_code == 409, f"Expected 409 Conflict, got {res_dup.status_code}: {res_dup.text}"
    print(f"[PASS] Duplicate Request Prevention: Duplicate request for {test_med} rejected with HTTP 409 Conflict ('{res_dup.json()['detail']}')")

    # -------------------------------------------------------------
    # 4. BEDS & EQUIPMENT
    # -------------------------------------------------------------
    print("\n--- C. BEDS & EQUIPMENT (ALIASES, VALIDATION & ALERTS) ---")

    # Update beds via POST /api/beds (frontend alias)
    res = s_alpha.post(f"{BASE_URL}/api/beds", json={
        "total_beds": 35,
        "occupied_beds": 20,
        "notes": "Post-ward expansion update"
    })
    assert res.status_code == 200, f"POST /api/beds failed with {res.status_code}: {res.text}"
    data = res.json()
    assert data["total_beds"] == 35 and data["occupied_beds"] == 20 and data["available_beds"] == 15
    print("[PASS] Beds Update via POST /api/beds: 200 OK (Occupied: 20, Avail: 15, Total: 35)")

    # Update beds via POST /api/beds/update (canonical route)
    res = s_alpha.post(f"{BASE_URL}/api/beds/update", json={
        "total_beds": 35,
        "occupied_beds": 22
    })
    assert res.status_code == 200
    print("[PASS] Beds Update via POST /api/beds/update: 200 OK")

    # Reject Negative Beds
    res = s_alpha.post(f"{BASE_URL}/api/beds", json={"total_beds": 30, "occupied_beds": -2})
    assert res.status_code == 400 or res.status_code == 422
    print("[PASS] Bed Validation: Negative occupied beds rejected")

    # Reject Occupied > Total
    res = s_alpha.post(f"{BASE_URL}/api/beds", json={"total_beds": 30, "occupied_beds": 35})
    assert res.status_code == 400, f"Expected 400 for occupied > total, got {res.status_code}"
    print("[PASS] Bed Validation: Occupied exceeding total beds rejected with HTTP 400")

    # Trigger Capacity Alert (Occupied >= 90%)
    res = s_alpha.post(f"{BASE_URL}/api/beds", json={"total_beds": 30, "occupied_beds": 28})
    assert res.status_code == 200
    db = get_db()
    alert = db.execute("SELECT * FROM messages WHERE subject LIKE '%HIGH CAPACITY ALERT%' ORDER BY id DESC LIMIT 1").fetchone()
    assert alert is not None, "Capacity alert message was not created"
    db.close()
    print(f"[PASS] Capacity Alert Generated: High bed occupancy (28/30) triggered alert '{alert['subject']}'")

    # GET Equipment
    res = s_alpha.get(f"{BASE_URL}/api/equipment")
    assert res.status_code == 200
    eq_list = res.json()
    assert len(eq_list) >= 4, f"Expected at least 4 equipment items, got {len(eq_list)}"
    print(f"[PASS] Equipment GET /api/equipment: Retrieved {len(eq_list)} equipment items")

    # Update Equipment via POST /api/equipment and POST /api/equipment/update
    res = s_alpha.post(f"{BASE_URL}/api/equipment", json={
        "name": "Central Medical Oxygen Cylinders",
        "quantity": 6,
        "operational_status": "OPERATIONAL",
        "under_maintenance_count": 0,
        "notes": "Pressure manifold verified at 150 bar"
    })
    assert res.status_code == 200, f"Equipment update failed: {res.text}"
    print("[PASS] Equipment Update via POST /api/equipment: 200 OK")

    res = s_alpha.post(f"{BASE_URL}/api/equipment/update", json={
        "name": "Diesel Generator Fuel Level (Reserve)",
        "quantity": 1,
        "operational_status": "STANDBY",
        "under_maintenance_count": 0,
        "notes": "Tank refilled to 95%"
    })
    assert res.status_code == 200
    print("[PASS] Equipment Update via POST /api/equipment/update: 200 OK")

    # Equipment Validation: Invalid Status
    res = s_alpha.post(f"{BASE_URL}/api/equipment", json={
        "name": "Neonatal Radiant Warmer (Zone B)",
        "quantity": 1,
        "operational_status": "BROKEN_INVALID_ENUM"
    })
    assert res.status_code == 400
    print("[PASS] Equipment Validation: Unapproved status enum rejected with HTTP 400")

    # -------------------------------------------------------------
    # 5. STAFF ATTENDANCE
    # -------------------------------------------------------------
    print("\n--- D. STAFF ATTENDANCE (RFID, MANUAL, METHODS & ALIASES) ---")

    # Test RFID Card Punch via /api/staff/punch (alias)
    res = s_alpha.post(f"{BASE_URL}/api/staff/punch", json={"card_uid": "RFID-10101", "phc_id": "PHC-001"})
    assert res.status_code == 200, f"RFID punch failed: {res.text}"
    punch1 = res.json()
    print(f"[PASS] RFID Punch via /api/staff/punch: {punch1['action']} for {punch1['staff_name']}")

    # Test RFID Card Punch via /api/staff/card-punch (canonical)
    res = s_alpha.post(f"{BASE_URL}/api/staff/card-punch", json={"card_uid": "RFID-10101", "phc_id": "PHC-001"})
    assert res.status_code == 200
    punch2 = res.json()
    assert punch2["action"] != punch1["action"], "Toggle check-in/out failed"
    print(f"[PASS] RFID Punch via /api/staff/card-punch: Toggled to {punch2['action']} for {punch2['staff_name']}")

    # Test Manual Attendance via POST /api/staff (FIX FOR PREVIOUS 405 Method Not Allowed!)
    res = s_alpha.post(f"{BASE_URL}/api/staff", json={
        "staff_id": "STF-105",
        "status": "CHECKED_IN",
        "verification_method": "Manual Kiosk Override",
        "remarks": "Manual check-in test"
    })
    assert res.status_code == 200, f"POST /api/staff returned {res.status_code} (previously 405!): {res.text}"
    print("[PASS] Manual Attendance via POST /api/staff: 200 OK (HTTP 405 eliminated!)")

    # Test Manual Attendance via POST /api/staff/log
    res = s_alpha.post(f"{BASE_URL}/api/staff/log", json={
        "staff_id": "STF-106",
        "status": "ON_LEAVE",
        "remarks": "Medical leave sanctioned"
    })
    assert res.status_code == 200
    print("[PASS] Manual Attendance via POST /api/staff/log: 200 OK")

    # Test Staff Action (Check-out / Correction)
    res = s_alpha.post(f"{BASE_URL}/api/staff/action", json={
        "staff_id": "STF-105",
        "action": "CHECK_OUT",
        "remarks": "Shift completed"
    })
    assert res.status_code == 200
    print("[PASS] Staff Action POST /api/staff/action: 200 OK")

    # -------------------------------------------------------------
    # 6. PATIENT FOOTFALL
    # -------------------------------------------------------------
    print("\n--- E. PATIENT FOOTFALL (ALIASES, VALIDATION & RECENT HISTORY) ---")

    today_str = datetime.now().strftime("%Y-%m-%d")

    # Test Footfall via POST /api/footfall (FIX FOR PREVIOUS 405 Method Not Allowed!)
    res = s_alpha.post(f"{BASE_URL}/api/footfall", json={
        "date": today_str,
        "count": 165,
        "male_count": 80,
        "female_count": 75,
        "other_count": 10,
        "emergency_cases": 8
    })
    assert res.status_code == 200, f"POST /api/footfall returned {res.status_code} (previously 405!): {res.text}"
    print("[PASS] Patient Footfall via POST /api/footfall: 200 OK (HTTP 405 eliminated!)")

    # Test Footfall via POST /api/footfall/log
    res = s_alpha.post(f"{BASE_URL}/api/footfall/log", json={
        "date": today_str,
        "count": 170,
        "male_count": 85,
        "female_count": 75,
        "other_count": 10,
        "correction_reason": "Evening triage count added"
    })
    assert res.status_code == 200
    print("[PASS] Patient Footfall via POST /api/footfall/log: 200 OK (Clean upsert on existing date)")

    # Reject Future Date
    future_date = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
    res = s_alpha.post(f"{BASE_URL}/api/footfall", json={
        "date": future_date,
        "count": 50
    })
    assert res.status_code == 400, f"Expected 400 for future date, got {res.status_code}"
    print(f"[PASS] Future Date Guard: Date {future_date} rejected with HTTP 400 ('{res.json()['detail']}')")

    # Reject Inconsistent Demographics (Male + Female + Other > Total)
    res = s_alpha.post(f"{BASE_URL}/api/footfall", json={
        "date": today_str,
        "count": 100,
        "male_count": 70,
        "female_count": 60,
        "other_count": 10
    })
    assert res.status_code == 400, f"Expected 400 for breakdown exceeding total, got {res.status_code}"
    print(f"[PASS] Demographic Consistency: Category sum (140) exceeding total visits (100) rejected with HTTP 400")

    # -------------------------------------------------------------
    # 7. PHC DASHBOARD AGGREGATION & EQUIPMENT
    # -------------------------------------------------------------
    print("\n--- F. PHC DASHBOARD INTEGRATION ---")
    res = s_alpha.get(f"{BASE_URL}/api/dashboard/phc/PHC-001")
    assert res.status_code == 200
    dash = res.json()
    assert "equipment" in dash, "Equipment missing in PHC dashboard payload"
    assert len(dash["equipment"]) >= 4
    assert dash["bed_status"]["total_beds"] == 30
    assert dash["bed_status"]["occupied_beds"] == 28
    print(f"[PASS] PHC Dashboard: Equipment array returned ({len(dash['equipment'])} items) with updated bed status")

    print("\n=================================================================")
    print("ALL OPERATIONS BACKEND ROUTES & VALIDATIONS PASSED (100%)!")
    print("=================================================================")

if __name__ == "__main__":
    test_operations_backend()
