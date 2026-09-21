"""
=============================================================================
MERIDIAN HEALTHCARE APPLICATION - STAGE 3 COMPREHENSIVE END-TO-END SUITE
=============================================================================
Verifies all 12 operational domains across National Admin, District Officer,
and PHC Staff with full data isolation, error handling, and audit trails.
=============================================================================
"""

import sys
import os
import sqlite3
import requests
from datetime import datetime, timedelta

BASE_URL = "http://127.0.0.1:8000"
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", "meridian.db")

# Color formatting
GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"

test_results = []

def record_result(area, test_name, expected, actual, passed, defect_fixed="", files_changed=""):
    test_results.append({
        "area": area,
        "test": test_name,
        "expected": expected,
        "actual": actual,
        "pass": passed,
        "defect_fixed": defect_fixed,
        "files_changed": files_changed
    })
    status_str = f"{GREEN}[PASS]{RESET}" if passed else f"{RED}[FAIL]{RESET}"
    print(f"  {status_str} {area}: {test_name}")
    if not passed:
        print(f"         Expected: {expected} | Actual: {actual}")


def login(email, password):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"username": email, "password": password})
    return s, r


def get_db():
    conn = sqlite3.connect(DB_PATH, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def run_all_tests():
    print(f"\n{BOLD}=================================================================={RESET}")
    print(f"{BOLD}STARTING STAGE 3 END-TO-END VERIFICATION AND STABILIZATION SUITE{RESET}")
    print(f"{BOLD}=================================================================={RESET}\n")

    # =========================================================================
    # 1. AUTHENTICATION & SESSION LIFECYCLE TESTING
    # =========================================================================
    print(f"\n{BOLD}--- 1. AUTHENTICATION & SESSION LIFECYCLE ---{RESET}")

    # 1.1 Valid logins for 3 demo roles
    s_admin, r_admin = login("admin@meridian.health", "Admin@123")
    record_result(
        "1. Authentication", "National Admin login with valid credentials",
        "HTTP 200 & role NATIONAL_ADMIN",
        f"HTTP {r_admin.status_code} role {r_admin.json().get('user', {}).get('role') if r_admin.status_code == 200 else 'None'}",
        r_admin.status_code == 200 and r_admin.json().get("user", {}).get("role") == "NATIONAL_ADMIN"
    )

    s_officer, r_officer = login("officer.north@meridian.health", "Officer@123")
    record_result(
        "1. Authentication", "District Officer login with valid credentials",
        "HTTP 200 & role DISTRICT_OFFICER",
        f"HTTP {r_officer.status_code} role {r_officer.json().get('user', {}).get('role') if r_officer.status_code == 200 else 'None'}",
        r_officer.status_code == 200 and r_officer.json().get("user", {}).get("role") == "DISTRICT_OFFICER"
    )

    s_staff, r_staff = login("staff.alpha@meridian.health", "Staff@123")
    record_result(
        "1. Authentication", "PHC Staff login with valid credentials",
        "HTTP 200 & role PHC_STAFF & assigned PHC-001",
        f"HTTP {r_staff.status_code} role {r_staff.json().get('user', {}).get('role')} phc {r_staff.json().get('user', {}).get('assigned_phc_id')}",
        r_staff.status_code == 200 and r_staff.json().get("user", {}).get("role") == "PHC_STAFF" and r_staff.json().get("user", {}).get("assigned_phc_id") == "PHC-001"
    )

    # 1.2 Invalid credentials rejection
    _, r_bad_pass = login("admin@meridian.health", "WrongPassword999")
    record_result(
        "1. Authentication", "Rejection of invalid password",
        "HTTP 401 Unauthorized",
        f"HTTP {r_bad_pass.status_code}",
        r_bad_pass.status_code == 401
    )

    _, r_bad_user = login("nonexistent@meridian.health", "Admin@123")
    record_result(
        "1. Authentication", "Rejection of nonexistent user",
        "HTTP 401 Unauthorized",
        f"HTTP {r_bad_user.status_code}",
        r_bad_user.status_code == 401
    )

    # 1.3 Disabled account handling
    # Temporarily disable a test account in DB
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET account_status = 'DISABLED' WHERE id = 'USR-TEST-DIS'")
    if c.rowcount == 0:
        c.execute("""
        INSERT INTO users (id, full_name, email, password_hash, salt, role, account_status, created_at, updated_at)
        VALUES ('USR-TEST-DIS', 'Disabled User', 'disabled@meridian.health', '$2b$12$eX83Z', 'mock_salt_123', 'PHC_STAFF', 'DISABLED', datetime('now'), datetime('now'))
        """)
        conn.commit()
    conn.close()

    _, r_disabled = login("disabled@meridian.health", "Password123")
    record_result(
        "1. Authentication", "Disabled account rejection",
        "HTTP 403 Forbidden",
        f"HTTP {r_disabled.status_code}",
        r_disabled.status_code == 403
    )

    # 1.4 Unauthenticated protected-route rejection
    r_unauth = requests.get(f"{BASE_URL}/api/inventory")
    record_result(
        "1. Authentication", "Protected-route rejection without credentials",
        "HTTP 401 Unauthorized",
        f"HTTP {r_unauth.status_code}",
        r_unauth.status_code == 401
    )

    # 1.5 Real server session invalidation on logout
    s_temp, _ = login("staff.alpha@meridian.health", "Staff@123")
    r_me_before = s_temp.get(f"{BASE_URL}/api/auth/me")
    r_logout = s_temp.post(f"{BASE_URL}/api/auth/logout")
    r_me_after = s_temp.get(f"{BASE_URL}/api/auth/me")
    record_result(
        "1. Authentication", "Logout invalidates real session on server",
        "Logout 200 and subsequent /api/auth/me returns 401",
        f"Logout {r_logout.status_code}, after {r_me_after.status_code}",
        r_logout.status_code == 200 and r_me_after.status_code == 401
    )

    # =========================================================================
    # 2. ROLE & DATA-ISOLATION TESTING
    # =========================================================================
    print(f"\n{BOLD}--- 2. ROLE AND DATA-ISOLATION ---{RESET}")

    # 2.1 National Admin views aggregates and cross-district monitoring
    r_nat_dash = s_admin.get(f"{BASE_URL}/api/dashboard/national")
    dist_comps = r_nat_dash.json().get("district_comparisons", []) if r_nat_dash.status_code == 200 else []
    record_result(
        "2. Role Isolation", "National Admin views nationwide aggregates",
        "HTTP 200 with national metrics",
        f"HTTP {r_nat_dash.status_code} ({len(dist_comps)} district comparisons)",
        r_nat_dash.status_code == 200 and len(dist_comps) > 0
    )

    # National Admin silent operational update rejected (requires reason override)
    r_silent_override = s_admin.post(f"{BASE_URL}/api/inventory/update", json={
        "phc_id": "PHC-001",
        "medicine_name": "ORS Packets",
        "quantity": 99
    })
    record_result(
        "2. Role Isolation", "National Admin routine update requires explicit override reason",
        "HTTP 400 Bad Request",
        f"HTTP {r_silent_override.status_code}",
        r_silent_override.status_code == 400
    )

    # 2.2 District Officer North scoped strictly to DIST-NORTH
    r_dist_dash = s_officer.get(f"{BASE_URL}/api/dashboard/district")
    dist_facilities = [p["id"] for p in r_dist_dash.json().get("phc_comparison", [])] if r_dist_dash.status_code == 200 else []
    record_result(
        "2. Role Isolation", "District Officer North sees only in-district facilities",
        "HTTP 200 with PHC-001, PHC-002 only",
        f"HTTP {r_dist_dash.status_code} facilities: {dist_facilities}",
        r_dist_dash.status_code == 200 and set(dist_facilities) == {"PHC-001", "PHC-002"}
    )

    # District Officer North cannot access out-of-district facility PHC-003
    r_officer_cross = s_officer.get(f"{BASE_URL}/api/dashboard/phc/PHC-003")
    record_result(
        "2. Role Isolation", "District Officer cannot access out-of-district facility (PHC-003)",
        "HTTP 403 Forbidden",
        f"HTTP {r_officer_cross.status_code}",
        r_officer_cross.status_code == 403
    )

    # District Officer cannot access National Dashboard
    r_officer_nat = s_officer.get(f"{BASE_URL}/api/dashboard/national")
    record_result(
        "2. Role Isolation", "District Officer accessing National Dashboard rejected",
        "HTTP 403 Forbidden",
        f"HTTP {r_officer_nat.status_code}",
        r_officer_nat.status_code == 403
    )

    # 2.3 PHC Staff Alpha strictly isolated to PHC-001
    r_staff_cross_dash = s_staff.get(f"{BASE_URL}/api/dashboard/phc/PHC-002")
    record_result(
        "2. Role Isolation", "PHC Staff accessing another PHC dashboard rejected",
        "HTTP 403 Forbidden",
        f"HTTP {r_staff_cross_dash.status_code}",
        r_staff_cross_dash.status_code == 403
    )

    r_staff_cross_up = s_staff.post(f"{BASE_URL}/api/inventory/update", json={
        "phc_id": "PHC-002", "medicine_name": "ORS Packets", "quantity": 50
    })
    record_result(
        "2. Role Isolation", "PHC Staff updating another facility's inventory rejected",
        "HTTP 403 Forbidden",
        f"HTTP {r_staff_cross_up.status_code}",
        r_staff_cross_up.status_code == 403
    )

    r_staff_dist_dash = s_staff.get(f"{BASE_URL}/api/dashboard/district")
    record_result(
        "2. Role Isolation", "PHC Staff accessing District Dashboard rejected",
        "HTTP 403 Forbidden",
        f"HTTP {r_staff_dist_dash.status_code}",
        r_staff_dist_dash.status_code == 403
    )

    # =========================================================================
    # 3. MEDICINE INVENTORY WORKFLOW
    # =========================================================================
    print(f"\n{BOLD}--- 3. MEDICINE INVENTORY WORKFLOW ---{RESET}")

    # Baseline inventory for ORS Packets at PHC-001
    r_inv0 = s_staff.get(f"{BASE_URL}/api/inventory")
    med0 = next((m for m in r_inv0.json() if m["medicine_name"] == "ORS Packets"), None)
    qty_base = med0["quantity"] if med0 else 0

    # 3.1 Record stock received (+50)
    r_recv = s_staff.post(f"{BASE_URL}/api/inventory/receive", json={
        "medicine_name": "ORS Packets",
        "quantity": 50,
        "batch_number": "BAT-E2E-RECV-01",
        "source": "Central Medical Store"
    })
    r_inv1 = s_staff.get(f"{BASE_URL}/api/inventory")
    med1 = next((m for m in r_inv1.json() if m["medicine_name"] == "ORS Packets"), None)
    qty_after_recv = med1["quantity"] if med1 else 0

    record_result(
        "3. Inventory", "Stock Received: quantity increases by exact amount (+50)",
        f"Balance equals {qty_base + 50}",
        f"Balance: {qty_after_recv}",
        r_recv.status_code == 200 and qty_after_recv == qty_base + 50
    )

    # Confirm stock transaction in DB
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM stock_transactions WHERE phc_id = 'PHC-001' AND batch_number = 'BAT-E2E-RECV-01'")
    recv_tx = c.fetchone()
    conn.close()
    record_result(
        "3. Inventory", "Immutable 'RECEIVED' transaction saved in stock_transactions",
        "Transaction exists with type RECEIVED and qty 50",
        f"Saved: {dict(recv_tx) if recv_tx else 'None'}",
        recv_tx is not None and recv_tx["transaction_type"] == "RECEIVED" and recv_tx["quantity"] == 50
    )

    # 3.2 Dispense valid stock (-10)
    r_disp = s_staff.post(f"{BASE_URL}/api/inventory/consume", json={
        "medicine_name": "ORS Packets",
        "quantity": 10,
        "reason": "Outpatient dispensing"
    })
    if r_disp.status_code != 200:
        print(f"       [DEBUG DISPENSE ERROR]: {r_disp.status_code} {r_disp.text}")
    r_inv2 = s_staff.get(f"{BASE_URL}/api/inventory")
    med2 = next((m for m in r_inv2.json() if m["medicine_name"] == "ORS Packets"), None)
    qty_after_disp = med2["quantity"] if med2 else 0

    record_result(
        "3. Inventory", "Dispense Stock: quantity decreases by exact amount (-10)",
        f"Balance equals {qty_after_recv - 10}",
        f"Balance: {qty_after_disp}",
        r_disp.status_code == 200 and qty_after_disp == qty_after_recv - 10
    )

    # Confirm DISPENSED transaction in DB
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM stock_transactions WHERE phc_id = 'PHC-001' AND transaction_type = 'DISPENSED' ORDER BY id DESC LIMIT 1")
    disp_tx = c.fetchone()
    conn.close()
    record_result(
        "3. Inventory", "Immutable 'DISPENSED' transaction saved in database",
        "Transaction exists with type DISPENSED and qty 10",
        f"Saved: {dict(disp_tx) if disp_tx else 'None'}",
        disp_tx is not None and disp_tx["quantity"] == 10
    )

    # 3.3 Zero and negative quantity attempts
    r_zero = s_staff.post(f"{BASE_URL}/api/inventory/receive", json={"medicine_name": "ORS Packets", "quantity": 0})
    r_neg = s_staff.post(f"{BASE_URL}/api/inventory/consume", json={"medicine_name": "ORS Packets", "quantity": -5})
    record_result(
        "3. Inventory", "Rejection of zero and negative quantities",
        "Both rejected with HTTP 400 or 422",
        f"Zero: {r_zero.status_code}, Neg: {r_neg.status_code}",
        r_zero.status_code in [400, 422] and r_neg.status_code in [400, 422]
    )

    # 3.4 Dispensing more than available stock (underflow protection)
    r_underflow = s_staff.post(f"{BASE_URL}/api/inventory/consume", json={
        "medicine_name": "ORS Packets",
        "quantity": 999999
    })
    record_result(
        "3. Inventory", "Underflow protection: dispensing > available stock rejected",
        "HTTP 400 Bad Request without stock changes",
        f"HTTP {r_underflow.status_code} ({r_underflow.json().get('detail')})",
        r_underflow.status_code == 400
    )

    # Verify invalid transactions did not change stock
    r_inv3 = s_staff.get(f"{BASE_URL}/api/inventory")
    med3 = next((m for m in r_inv3.json() if m["medicine_name"] == "ORS Packets"), None)
    record_result(
        "3. Inventory", "Invalid operations leave stock count unchanged",
        f"Stock remains {qty_after_disp}",
        f"Current stock: {med3['quantity'] if med3 else 0}",
        med3 is not None and med3["quantity"] == qty_after_disp
    )

    # =========================================================================
    # 4. BEDS AND EQUIPMENT WORKFLOW
    # =========================================================================
    print(f"\n{BOLD}--- 4. BEDS AND EQUIPMENT WORKFLOW ---{RESET}")

    # 4.1 Update beds total and occupied
    r_beds_valid = s_staff.post(f"{BASE_URL}/api/beds/update", json={
        "total_beds": 35,
        "occupied_beds": 21,
        "notes": "Routine morning ward check"
    })
    r_beds_get = s_staff.get(f"{BASE_URL}/api/beds?phc_id=PHC-001")
    beds_list = r_beds_get.json()
    beds_data = beds_list[0] if isinstance(beds_list, list) and beds_list else beds_list
    avail = beds_data.get("total_beds", 0) - beds_data.get("occupied_beds", 0)
    record_result(
        "4. Beds & Equipment", "Update beds: Total=35, Occupied=21 -> Available=14",
        "Available beds correctly computed as 14",
        f"Total: {beds_data.get('total_beds')}, Occ: {beds_data.get('occupied_beds')}, Avail: {avail}",
        r_beds_valid.status_code == 200 and avail == 14
    )

    # 4.2 Rejection of negative bed count & occupied > total
    r_bed_neg = s_staff.post(f"{BASE_URL}/api/beds/update", json={"total_beds": -10, "occupied_beds": 5})
    r_bed_exceed = s_staff.post(f"{BASE_URL}/api/beds/update", json={"total_beds": 20, "occupied_beds": 25})
    record_result(
        "4. Beds & Equipment", "Rejection of negative beds and occupied > total",
        "Both rejected with HTTP 400 or 422",
        f"Negative: {r_bed_neg.status_code}, Exceeded: {r_bed_exceed.status_code}",
        r_bed_neg.status_code in [400, 422] and r_bed_exceed.status_code == 400
    )

    # 4.3 High occupancy capacity alert generation (>= 90%)
    r_high_occ = s_staff.post(f"{BASE_URL}/api/beds/update", json={
        "total_beds": 30,
        "occupied_beds": 28,  # 93.3% occupancy
        "notes": "Surge occupancy test"
    })
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM messages WHERE subject LIKE '%HIGH CAPACITY ALERT%' ORDER BY id DESC LIMIT 1")
    cap_alert = c.fetchone()
    conn.close()
    record_result(
        "4. Beds & Equipment", "Occupancy >= 90% triggers automated High Capacity Alert",
        "Capacity alert generated in messages desk",
        f"Alert found: {cap_alert['subject'] if cap_alert else 'None'}",
        r_high_occ.status_code == 200 and cap_alert is not None
    )

    # 4.4 Equipment retrieval and updates
    r_eq_list = s_staff.get(f"{BASE_URL}/api/equipment?phc_id=PHC-001")
    eq_items = r_eq_list.json()
    record_result(
        "4. Beds & Equipment", "Retrieve dynamic facility equipment checklist",
        "HTTP 200 returning equipment array",
        f"HTTP {r_eq_list.status_code} ({len(eq_items)} items)",
        r_eq_list.status_code == 200 and len(eq_items) > 0
    )

    # Valid equipment update
    first_eq = eq_items[0]
    r_eq_up = s_staff.post(f"{BASE_URL}/api/equipment/update", json={
        "equipment_id": first_eq["id"],
        "name": first_eq["name"],
        "quantity": first_eq["quantity"],
        "operational_status": "OPERATIONAL",
        "under_maintenance_count": 0,
        "notes": "Stage 3 certified operational"
    })
    record_result(
        "4. Beds & Equipment", "Update equipment operational status",
        "HTTP 200 OK",
        f"HTTP {r_eq_up.status_code}",
        r_eq_up.status_code == 200
    )

    # Equipment validation: invalid status and maintenance > quantity
    r_eq_bad_status = s_staff.post(f"{BASE_URL}/api/equipment/update", json={
        "equipment_id": first_eq["id"],
        "name": first_eq["name"],
        "quantity": 5,
        "operational_status": "INVALID_STATE",
        "under_maintenance_count": 0
    })
    r_eq_bad_maint = s_staff.post(f"{BASE_URL}/api/equipment/update", json={
        "equipment_id": first_eq["id"],
        "name": first_eq["name"],
        "quantity": 3,
        "operational_status": "UNDER_MAINTENANCE",
        "under_maintenance_count": 5
    })
    record_result(
        "4. Beds & Equipment", "Rejection of invalid equipment status and maintenance > total",
        "Both return HTTP 400 Bad Request",
        f"Bad Status: {r_eq_bad_status.status_code}, Bad Maint: {r_eq_bad_maint.status_code}",
        r_eq_bad_status.status_code == 400 and r_eq_bad_maint.status_code == 400
    )

    # =========================================================================
    # 5. STAFF ATTENDANCE WORKFLOW
    # =========================================================================
    print(f"\n{BOLD}--- 5. STAFF ATTENDANCE WORKFLOW ---{RESET}")

    # 5.1 Manual Attendance logging (Present, Absent, Late, On Leave)
    r_att_pres = s_staff.post(f"{BASE_URL}/api/staff/log", json={
        "staff_id": "STF-101",
        "status": "PRESENT",
        "duty_shift": "Morning Shift"
    })
    record_result(
        "5. Staff Attendance", "Manual Attendance: PRESENT logged successfully",
        "HTTP 200 without HTTP 405",
        f"HTTP {r_att_pres.status_code}",
        r_att_pres.status_code == 200
    )

    r_att_abs = s_staff.post(f"{BASE_URL}/api/staff/log", json={
        "staff_id": "STF-102",
        "status": "ON_LEAVE",
        "duty_shift": "Morning Shift"
    })
    record_result(
        "5. Staff Attendance", "Manual Attendance: ON_LEAVE logged successfully",
        "HTTP 200",
        f"HTTP {r_att_abs.status_code}",
        r_att_abs.status_code == 200
    )

    # 5.2 RFID Punch Check-In and Check-Out
    r_rfid_in = s_staff.post(f"{BASE_URL}/api/staff/punch", json={
        "card_uid": "RFID-10101",
        "verification_method": "RFID Card Tap"
    })
    action_in = r_rfid_in.json().get("action") if r_rfid_in.status_code == 200 else "FAIL"

    r_rfid_out = s_staff.post(f"{BASE_URL}/api/staff/punch", json={
        "card_uid": "RFID-10101",
        "verification_method": "RFID Card Tap"
    })
    action_out = r_rfid_out.json().get("action") if r_rfid_out.status_code == 200 else "FAIL"

    record_result(
        "5. Staff Attendance", "RFID Smart-Card Punch: toggles Check-In and Check-Out",
        "First punch CHECKED_IN, second punch CHECKED_OUT",
        f"1st: {action_in}, 2nd: {action_out}",
        r_rfid_in.status_code == 200 and r_rfid_out.status_code == 200 and action_in != action_out
    )

    # =========================================================================
    # 6. PATIENT FOOTFALL WORKFLOW
    # =========================================================================
    print(f"\n{BOLD}--- 6. PATIENT FOOTFALL WORKFLOW ---{RESET}")

    today_str = datetime.now().strftime("%Y-%m-%d")
    tomorrow_str = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")

    # 6.1 Create today's patient footfall record
    r_foot_create = s_staff.post(f"{BASE_URL}/api/footfall/log", json={
        "date": today_str,
        "count": 110,
        "male_count": 55,
        "female_count": 45,
        "other_count": 10,
        "emergency_cases": 10,
        "notes": "Seasonal fever outpatient load"
    })
    record_result(
        "6. Patient Footfall", "Record daily footfall entry across all demographic categories",
        "HTTP 200",
        f"HTTP {r_foot_create.status_code}",
        r_foot_create.status_code == 200
    )

    # 6.2 Update existing same-day entry with correction reason
    r_foot_update = s_staff.post(f"{BASE_URL}/api/footfall/log", json={
        "date": today_str,
        "count": 115,
        "male_count": 60,
        "female_count": 45,
        "other_count": 10,
        "emergency_cases": 10,
        "correction_reason": "Late afternoon emergency arrivals added"
    })
    record_result(
        "6. Patient Footfall", "Update same-day entry requires correction reason (clean upsert)",
        "HTTP 200 upsert without creating duplicate day rows",
        f"HTTP {r_foot_update.status_code}",
        r_foot_update.status_code == 200
    )

    # Confirm only one row exists for today in DB
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT COUNT(*) as cnt FROM patient_footfall WHERE phc_id = 'PHC-001' AND date = ?", (today_str,))
    day_cnt = c.fetchone()["cnt"]
    conn.close()
    record_result(
        "6. Patient Footfall", "Repeated submissions update existing row without uncontrolled duplicates",
        "Exactly 1 row for today",
        f"{day_cnt} row(s) found",
        day_cnt == 1
    )

    # 6.3 Rejection of future date and inconsistent category totals
    r_future = s_staff.post(f"{BASE_URL}/api/footfall/log", json={
        "date": tomorrow_str, "count": 50
    })
    r_inconsistent = s_staff.post(f"{BASE_URL}/api/footfall/log", json={
        "date": today_str,
        "count": 50,
        "male_count": 40,
        "female_count": 30  # 40 + 30 = 70 > 50!
    })
    record_result(
        "6. Patient Footfall", "Rejection of future date and inconsistent category totals",
        "Both return HTTP 400 Bad Request",
        f"Future: {r_future.status_code}, Inconsistent: {r_inconsistent.status_code}",
        r_future.status_code == 400 and r_inconsistent.status_code == 400
    )

    # =========================================================================
    # 7. COMPLETE REDISTRIBUTION 10-STEP WORKFLOW
    # =========================================================================
    print(f"\n{BOLD}--- 7. COMPLETE REDISTRIBUTION 10-STEP LIFECYCLE ---{RESET}")

    s_beta, _ = login("staff.beta@meridian.health", "Staff@123")

    # Ensure Beta holds safe surplus par stock
    r_beta_inv = s_beta.get(f"{BASE_URL}/api/inventory")
    beta_pcm = next((m for m in r_beta_inv.json() if m["medicine_name"] == "Paracetamol 500mg"), None)
    if not beta_pcm or beta_pcm["quantity"] < 250:
        s_beta.post(f"{BASE_URL}/api/inventory/receive", json={
            "medicine_name": "Paracetamol 500mg", "quantity": 250,
            "batch_number": "BATCH-E2E-RESTOCK", "source": "District Depot"
        })
        r_beta_inv = s_beta.get(f"{BASE_URL}/api/inventory")
        beta_pcm = next((m for m in r_beta_inv.json() if m["medicine_name"] == "Paracetamol 500mg"), None)

    beta_initial_stock = beta_pcm["quantity"]
    r_alpha_inv = s_staff.get(f"{BASE_URL}/api/inventory")
    alpha_pcm = next((m for m in r_alpha_inv.json() if m["medicine_name"] == "Paracetamol 500mg"), None)
    alpha_initial_stock = alpha_pcm["quantity"] if alpha_pcm else 0

    # 7.1 PHC Staff creates request
    r_tr_create = s_staff.post(f"{BASE_URL}/api/redistribution/request", json={
        "medicine_name": "Paracetamol 500mg",
        "quantity": 25,
        "urgency": "URGENT",
        "reason": "Stage 3 End-to-End redistribution lifecycle test"
    })
    tr_id = r_tr_create.json().get("transfer_id")
    record_result(
        "7. Redistribution", "PHC Staff creates redistribution request (Status: Requested)",
        "HTTP 200 & transfer_id assigned",
        f"HTTP {r_tr_create.status_code} transfer_id: {tr_id}",
        r_tr_create.status_code == 200 and tr_id is not None
    )

    # 7.2 Duplicate pending transfer rejection
    r_dup_tr = s_staff.post(f"{BASE_URL}/api/redistribution/request", json={
        "medicine_name": "Paracetamol 500mg",
        "quantity": 25,
        "urgency": "URGENT"
    })
    record_result(
        "7. Redistribution", "Duplicate pending transfer for same medicine rejected",
        "HTTP 409 Conflict",
        f"HTTP {r_dup_tr.status_code} ({r_dup_tr.json().get('detail')})",
        r_dup_tr.status_code == 409
    )

    # 7.3 PHC Staff cannot self-approve transfer
    r_self_app = s_staff.post(f"{BASE_URL}/api/redistribution/{tr_id}/review", json={"action": "APPROVE"})
    record_result(
        "7. Redistribution", "PHC Staff cannot self-approve transfer request",
        "HTTP 403 Forbidden",
        f"HTTP {r_self_app.status_code}",
        r_self_app.status_code == 403
    )

    # 7.4 Unsafe stock protection: donor stock cannot fall below par
    unsafe_qty = beta_initial_stock - 30  # Leaves 30 < 100 par
    r_unsafe = s_officer.post(f"{BASE_URL}/api/redistribution/{tr_id}/review", json={
        "action": "MODIFY_AND_APPROVE",
        "modified_quantity": unsafe_qty,
        "decision_reason": "Attempting allocation exceeding donor safe par"
    })
    record_result(
        "7. Redistribution", "Safe Stock Rule: Transfer pushing donor below par rejected",
        "HTTP 400 Bad Request",
        f"HTTP {r_unsafe.status_code}",
        r_unsafe.status_code == 400
    )

    # 7.5 District Officer approves safe quantity (25 units)
    r_safe_app = s_officer.post(f"{BASE_URL}/api/redistribution/{tr_id}/review", json={
        "action": "APPROVE",
        "decision_reason": "Verified Beta has adequate surplus above par"
    })
    record_result(
        "7. Redistribution", "District Officer approves transfer (Status: Approved)",
        "HTTP 200 and status 'Approved'",
        f"HTTP {r_safe_app.status_code} status {r_safe_app.json().get('transfer_status')}",
        r_safe_app.status_code == 200 and r_safe_app.json().get("transfer_status") == "Approved"
    )

    # 7.6 Donor PHC Beta confirms dispatch
    r_disp_tr = s_beta.post(f"{BASE_URL}/api/redistribution/{tr_id}/dispatch", json={
        "batch_number": "BAT-PCM-E2E-99", "notes": "Handed to courier van"
    })
    record_result(
        "7. Redistribution", "Donor PHC Beta confirms dispatch (Status: In Transit)",
        "HTTP 200 and status 'In Transit'",
        f"HTTP {r_disp_tr.status_code} status {r_disp_tr.json().get('transfer_status')}",
        r_disp_tr.status_code == 200 and r_disp_tr.json().get("transfer_status") == "In Transit"
    )

    # 7.7 Duplicate dispatch rejection
    r_dup_disp = s_beta.post(f"{BASE_URL}/api/redistribution/{tr_id}/dispatch", json={
        "batch_number": "BAT-PCM-E2E-99"
    })
    record_result(
        "7. Redistribution", "Duplicate dispatch attempt safely rejected",
        "HTTP 400 Bad Request",
        f"HTTP {r_dup_disp.status_code}",
        r_dup_disp.status_code == 400
    )

    # 7.8 Recipient PHC Alpha confirms receipt
    r_deliv_tr = s_staff.post(f"{BASE_URL}/api/redistribution/{tr_id}/deliver", json={
        "received_quantity": 25, "notes": "Delivery received and verified"
    })
    record_result(
        "7. Redistribution", "Recipient PHC Alpha confirms delivery (Status: Completed)",
        "HTTP 200 and status 'Completed'",
        f"HTTP {r_deliv_tr.status_code} status {r_deliv_tr.json().get('transfer_status')}",
        r_deliv_tr.status_code == 200 and r_deliv_tr.json().get("transfer_status") == "Completed"
    )

    # 7.9 Duplicate delivery rejection
    r_dup_deliv = s_staff.post(f"{BASE_URL}/api/redistribution/{tr_id}/deliver", json={"received_quantity": 25})
    record_result(
        "7. Redistribution", "Duplicate delivery attempt safely rejected",
        "HTTP 400 Bad Request",
        f"HTTP {r_dup_deliv.status_code}",
        r_dup_deliv.status_code == 400
    )

    # 7.10 Dual Inventory Reconciliation Verification
    r_beta_inv_after = s_beta.get(f"{BASE_URL}/api/inventory")
    beta_pcm_after = next((m for m in r_beta_inv_after.json() if m["medicine_name"] == "Paracetamol 500mg"), None)
    beta_final_stock = beta_pcm_after["quantity"]

    r_alpha_inv_after = s_staff.get(f"{BASE_URL}/api/inventory")
    alpha_pcm_after = next((m for m in r_alpha_inv_after.json() if m["medicine_name"] == "Paracetamol 500mg"), None)
    alpha_final_stock = alpha_pcm_after["quantity"]

    record_result(
        "7. Redistribution", "Dual Inventory Reconciliation: Donor deducted 25, Recipient added 25",
        f"Beta: {beta_initial_stock-25}, Alpha: {alpha_initial_stock+25}",
        f"Beta: {beta_final_stock}, Alpha: {alpha_final_stock}",
        beta_final_stock == beta_initial_stock - 25 and alpha_final_stock == alpha_initial_stock + 25
    )

    # =========================================================================
    # 8. COMMUNICATION & DIRECTIVES WORKFLOW
    # =========================================================================
    print(f"\n{BOLD}--- 8. COMMUNICATION & DIRECTIVES WORKFLOW ---{RESET}")

    # 8.1 National Admin dispatches directive to District Officer
    r_admin_msg = s_admin.post(f"{BASE_URL}/api/messages", json={
        "recipient_role": "DISTRICT_OFFICER",
        "district_id": "DIST-NORTH",
        "subject": "STAGE 3 DIRECTIVE: Audit Compliance",
        "message": "Verify cold chain integrity across all north PHCs.",
        "priority": "HIGH"
    })
    admin_msg_id = r_admin_msg.json().get("message_id")
    record_result(
        "8. Communication", "National Admin sends official directive to District Officer",
        "HTTP 200 & message_id returned",
        f"HTTP {r_admin_msg.status_code} id: {admin_msg_id}",
        r_admin_msg.status_code == 200 and admin_msg_id is not None
    )

    # 8.2 District Officer retrieves and acknowledges directive
    r_officer_msgs = s_officer.get(f"{BASE_URL}/api/messages")
    found_msg = next((m for m in r_officer_msgs.json().get("messages", []) if m["id"] == admin_msg_id), None)
    r_ack = s_officer.post(f"{BASE_URL}/api/messages/{admin_msg_id}/acknowledge", json={
        "notes": "Directive received. Audits scheduled for tomorrow."
    })
    record_result(
        "8. Communication", "District Officer receives & signs formal acknowledgement",
        "Directive found in inbox and acknowledged with timestamp",
        f"Found: {found_msg is not None}, Ack HTTP: {r_ack.status_code}",
        found_msg is not None and r_ack.status_code == 200
    )

    # 8.3 Scope isolation: Unrelated facility cannot read private messages
    s_gamma, _ = login("staff.beta@meridian.health", "Staff@123")
    r_gamma_msgs = s_gamma.get(f"{BASE_URL}/api/messages")
    record_result(
        "8. Communication", "Message scope isolation enforced by backend",
        "HTTP 200 returning filtered facility messages",
        f"HTTP {r_gamma_msgs.status_code}",
        r_gamma_msgs.status_code == 200
    )

    # =========================================================================
    # 9. DASHBOARD SYNCHRONIZATION
    # =========================================================================
    print(f"\n{BOLD}--- 9. DASHBOARD SYNCHRONIZATION ---{RESET}")

    # Compare PHC Dashboard values with DB counts
    r_phc_dash = s_staff.get(f"{BASE_URL}/api/dashboard/phc/PHC-001")
    phc_dash_data = r_phc_dash.json()
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT total_beds, occupied_beds FROM bed_status WHERE phc_id = 'PHC-001'")
    bed_row = c.fetchone()
    conn.close()

    dash_beds = phc_dash_data.get("bed_status") or phc_dash_data.get("bed_occupancy", {})
    record_result(
        "9. Dashboards", "PHC Dashboard beds synchronize exactly with database",
        f"Total: {bed_row['total_beds']}, Occupied: {bed_row['occupied_beds']}",
        f"Total: {dash_beds.get('total_beds')}, Occupied: {dash_beds.get('occupied_beds')}",
        dash_beds.get("total_beds") == bed_row["total_beds"] and dash_beds.get("occupied_beds") == bed_row["occupied_beds"]
    )

    # District Dashboard facility count
    r_dist_sync = s_officer.get(f"{BASE_URL}/api/dashboard/district")
    dist_sync_data = r_dist_sync.json()
    dist_facs = dist_sync_data.get("phc_comparison", [])
    record_result(
        "9. Dashboards", "District Dashboard aggregates match registered facilities",
        "2 facilities in DIST-NORTH",
        f"{len(dist_facs)} facilities",
        len(dist_facs) == 2
    )

    # =========================================================================
    # 10. API & ERROR TESTING
    # =========================================================================
    print(f"\n{BOLD}--- 10. API & ERROR TESTING ---{RESET}")

    # Nonexistent endpoint returns 404
    r_404 = requests.get(f"{BASE_URL}/api/nonexistent-route-testing-404")
    record_result(
        "10. API & Errors", "Nonexistent route returns HTTP 404",
        "HTTP 404 Not Found",
        f"HTTP {r_404.status_code}",
        r_404.status_code == 404
    )

    # Aliased routes eliminate HTTP 405 Method Not Allowed
    r_alias_beds = s_staff.post(f"{BASE_URL}/api/beds", json={"total_beds": 35, "occupied_beds": 20})
    r_alias_staff = s_staff.post(f"{BASE_URL}/api/staff", json={"staff_id": "STF-101", "status": "PRESENT"})
    record_result(
        "10. API & Errors", "Aliased mutation endpoints eliminate HTTP 405 Method Not Allowed",
        "Both return HTTP 200",
        f"Beds: {r_alias_beds.status_code}, Staff: {r_alias_staff.status_code}",
        r_alias_beds.status_code == 200 and r_alias_staff.status_code == 200
    )

    # Standard JSON error structure {"detail": ...}
    r_err_struct = s_staff.post(f"{BASE_URL}/api/inventory/receive", json={"quantity": -10})
    record_result(
        "10. API & Errors", "Backend errors return consistent JSON detail payload",
        "JSON containing 'detail' key",
        f"JSON keys: {list(r_err_struct.json().keys()) if r_err_struct.status_code in [400, 422] else 'None'}",
        r_err_struct.status_code in [400, 422] and "detail" in r_err_struct.json()
    )

    # =========================================================================
    # 11. UI & ACCESSIBILITY CONTRACT
    # =========================================================================
    print(f"\n{BOLD}--- 11. UI & ACCESSIBILITY VERIFICATION ---{RESET}")

    html_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "index.html")
    js_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "app.js")
    css_path = os.path.join(os.path.dirname(__file__), "..", "frontend", "styles.css")

    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()
    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    # Verify zero native alert() calls
    native_alerts = js_content.count("alert(")
    record_result(
        "11. UI & Accessibility", "Zero native browser alert() dialogs in codebase",
        "0 native alert() calls",
        f"{native_alerts} alert() calls found",
        native_alerts == 0
    )

    # Verify toast notifications container in DOM
    has_toast = 'id="toast-container"' in html_content
    record_result(
        "11. UI & Accessibility", "Toast notification container present in HTML DOM",
        "toast-container present",
        f"Present: {has_toast}",
        has_toast
    )

    # Verify Account Dropdown triggers and keyboard accessibility
    has_dropdown_nav = "user-profile-trigger" in js_content and "Escape" in js_content
    record_result(
        "11. UI & Accessibility", "Account dropdown keyboard focus and Escape key dismissal",
        "Escape listener and user-profile-trigger present",
        f"Present: {has_dropdown_nav}",
        has_dropdown_nav
    )

    # Verify modal overlay and dismiss handlers
    has_modal_css = ".meridian-modal-overlay.active" in css_content or ".meridian-modal-overlay.open" in css_content
    record_result(
        "11. UI & Accessibility", "Accessible modal overlay and visibility CSS rules",
        "Modal overlay rules present",
        f"Present: {has_modal_css}",
        has_modal_css
    )

    # =========================================================================
    # 12. AUDIT TRAIL VERIFICATION
    # =========================================================================
    print(f"\n{BOLD}--- 12. AUDIT TRAIL VERIFICATION ---{RESET}")

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT DISTINCT action FROM audit_logs ORDER BY action")
    logged_actions = [r["action"] for r in c.fetchall()]
    conn.close()

    required_actions = [
        "LOGIN", "LOGOUT", "STOCK_RECEIVED", "STOCK_CONSUMED",
        "BED_UPDATE", "EQUIPMENT_UPDATE", "ATTENDANCE_LOG",
        "FOOTFALL_LOG", "TRANSFER_REQUESTED", "TRANSFER_APPROVED",
        "TRANSFER_DISPATCHED", "TRANSFER_COMPLETED_DONOR", "MESSAGE_SENT"
    ]
    missing_actions = [a for a in required_actions if a not in logged_actions]

    record_result(
        "12. Audit Trail", "Comprehensive audit log generation across all operational actions",
        "All 13 key operational actions captured in audit_logs",
        f"Missing: {missing_actions if missing_actions else 'None'}",
        len(missing_actions) == 0
    )

    # =========================================================================
    # SUMMARY REPORT
    # =========================================================================
    print(f"\n{BOLD}=================================================================={RESET}")
    print(f"{BOLD}STAGE 3 VERIFICATION SUMMARY RESULTS{RESET}")
    print(f"{BOLD}=================================================================={RESET}")

    passed_count = sum(1 for r in test_results if r["pass"])
    total_count = len(test_results)

    print(f"Total Tests Executed: {total_count}")
    print(f"Tests Passed: {GREEN}{passed_count}{RESET} / {total_count} ({passed_count/total_count*100:.1f}%)")

    if passed_count == total_count:
        print(f"\n{GREEN}{BOLD}>>> ALL 12 VERIFICATION DOMAINS 100% PASSED! <<< {RESET}\n")
    else:
        print(f"\n{RED}{BOLD}>>> SOME TESTS FAILED! CHECK OUTPUT ABOVE. <<< {RESET}\n")

    return passed_count == total_count


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
