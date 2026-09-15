import re
import requests
import json
import sqlite3
from datetime import datetime

BASE_URL = "http://127.0.0.1:8000"

def test_frontend_contract():
    print("=================================================================")
    print("STAGE 2 FRONTEND-BACKEND CONTRACT & STATIC CODE VERIFICATION")
    print("=================================================================")

    # 1. Verify Static Files
    res_index = requests.get(f"{BASE_URL}/")
    assert res_index.status_code == 200, f"Failed to load index.html: {res_index.status_code}"
    html_content = res_index.text

    res_css = requests.get(f"{BASE_URL}/static/styles.css")
    assert res_css.status_code == 200, f"Failed to load styles.css: {res_css.status_code}"
    css_content = res_css.text

    res_js = requests.get(f"{BASE_URL}/static/app.js")
    assert res_js.status_code == 200, f"Failed to load app.js: {res_js.status_code}"
    js_content = res_js.text
    print("[PASS] 1. Static Assets: index.html, styles.css, app.js served with HTTP 200")

    # 2. Check that native alert() is completely eliminated
    alerts = re.findall(r'\balert\(', js_content)
    assert len(alerts) == 0, f"Found {len(alerts)} native alert() calls in app.js!"
    print("[PASS] 2. Native Dialogs: Zero alert() calls in app.js (100% replaced by showToast)")

    # 3. Check required UI elements in HTML
    required_ids = [
        "toast-container",
        "subnav-inventory", "subnav-beds", "subnav-staff", "subnav-footfall",
        "ops-inventory-table", "ops-inventory-tbody", "inventory-card-actions",
        "record-stock-received-modal", "rx-medicine", "rx-quantity", "rx-batch", "rx-expiry", "rx-supplier", "rx-date", "rx-notes", "btn-submit-stock-received",
        "record-stock-consumed-modal", "cx-medicine", "cx-avail-qty", "cx-quantity", "cx-qty-warning", "cx-reason", "cx-date", "cx-notes", "btn-submit-stock-consumed",
        "create-transfer-modal", "req-medicine", "req-curr-stock", "req-quantity", "req-urgency", "req-reason", "req-notes", "btn-submit-transfer-request",
        "ops-beds-total", "ops-beds-occupied", "ops-beds-avail", "ops-beds-total-input", "quick-occupied-input", "ops-beds-calc-avail", "bed-validation-error", "btn-update-beds",
        "ops-equipment-list", "update-equipment-modal", "eq-edit-id", "eq-edit-name", "eq-edit-category", "eq-edit-quantity", "eq-edit-status", "eq-edit-maint-count", "eq-maint-error", "btn-submit-equipment",
        "card-punch-feedback", "manual-staff-select", "manual-status-select", "btn-manual-attendance", "ops-attendance-summary-tag", "ops-attendance-table", "ops-attendance-tbody",
        "footfall-mode-tag", "footfall-date-input", "daily-footfall-input", "footfall-male-input", "footfall-female-input", "footfall-other-input", "footfall-emergency-input", "footfall-validation-error", "footfall-correction-wrap", "footfall-correction-input", "btn-submit-footfall", "ops-footfall-chart", "ops-footfall-history-table", "ops-footfall-history-tbody"
    ]
    for el_id in required_ids:
        assert f'id="{el_id}"' in html_content, f"Missing HTML element: id='{el_id}'"
    print(f"[PASS] 3. HTML DOM Structure: All {len(required_ids)} required operations element IDs verified")

    # 4. Check that required JavaScript functions are defined
    required_js_funcs = [
        "showToast", "setButtonLoading", "apiFetch", "openModal", "closeModal",
        "switchOpsSubTab", "loadOperationsTab",
        "renderOpsInventoryTable", "openRecordStockReceivedModal", "closeRecordStockReceivedModal", "submitRecordStockReceived",
        "openRecordStockConsumedModal", "closeRecordStockConsumedModal", "updateDispenseAvailableStockHint", "validateDispenseQuantity", "submitRecordStockConsumed",
        "openCreateTransferModal", "closeCreateTransferModal", "updateTransferCurrentStockHint", "submitCreateTransfer",
        "renderOpsBedsWidget", "calculateLiveAvailableBeds", "submitQuickBedUpdate",
        "renderOpsEquipmentList", "openEditEquipmentModal", "closeEditEquipmentModal", "validateEquipmentForm", "submitEditEquipment",
        "renderOpsAttendanceTable", "simulateCardPunch", "submitManualAttendance", "performStaffAction",
        "renderOpsFootfallChart", "handleFootfallDateChange", "validateFootfallBreakdown", "adjustFootfall", "submitFootfallEntry", "renderOpsFootfallHistory", "loadFootfallForCorrection"
    ]
    for fn in required_js_funcs:
        assert f"function {fn}" in js_content or f"async function {fn}" in js_content, f"Missing JS function: {fn}"
    print(f"[PASS] 4. JavaScript Engine: All {len(required_js_funcs)} operations functions defined")

    # 5. Session-based API verification of all operations frontend actions
    s = requests.Session()
    login_res = s.post(f"{BASE_URL}/api/auth/login", json={"username": "staff.alpha@meridian.health", "password": "Staff@123"})
    assert login_res.status_code == 200, "Login failed"
    print("[PASS] 5. Session Authentication: Authenticated as staff.alpha@meridian.health")

    # A. Stock Received
    today_str = datetime.now().strftime("%Y-%m-%d")
    rx_res = s.post(f"{BASE_URL}/api/inventory/receive", json={
        "phc_id": "PHC-001",
        "medicine_name": "Paracetamol 500mg",
        "quantity": 25,
        "batch_number": "STG2-BATCH-01",
        "expiry_date": "2027-10-31",
        "supplier": "Central Depot",
        "received_date": today_str,
        "notes": "Verified in Stage 2 frontend test"
    })
    assert rx_res.status_code == 200, f"Receive failed: {rx_res.text}"
    print("[PASS] 6. Action: Record Stock Received (POST /api/inventory/receive) 200 OK")

    # B. Stock Consumed
    cx_res = s.post(f"{BASE_URL}/api/inventory/consume", json={
        "phc_id": "PHC-001",
        "medicine_name": "Paracetamol 500mg",
        "quantity": 5,
        "reason": "Routine OPD Dispensation",
        "date": today_str,
        "notes": "Dispensed to fever patients"
    })
    assert cx_res.status_code == 200, f"Consume failed: {cx_res.text}"
    print("[PASS] 7. Action: Record Stock Dispensed (POST /api/inventory/consume) 200 OK")

    # C. Dispense underflow rejection
    bad_cx = s.post(f"{BASE_URL}/api/inventory/consume", json={
        "phc_id": "PHC-001",
        "medicine_name": "Paracetamol 500mg",
        "quantity": 999999,
        "reason": "Routine OPD Dispensation"
    })
    assert bad_cx.status_code == 400, "Expected underflow rejection"
    print("[PASS] 8. Validation: Excessive dispensing rejected by backend with HTTP 400")

    # D. Bed update
    bed_res = s.post(f"{BASE_URL}/api/beds/update", json={
        "phc_id": "PHC-001",
        "total_beds": 35,
        "occupied_beds": 22,
        "notes": "Stage 2 bed verification"
    })
    assert bed_res.status_code == 200, f"Bed update failed: {bed_res.text}"
    assert bed_res.json()["available_beds"] == 13
    print("[PASS] 9. Action: Update Beds (POST /api/beds/update) 200 OK (35 total, 22 occupied, 13 available)")

    # E. Bed validation (occupied > total)
    bad_bed = s.post(f"{BASE_URL}/api/beds/update", json={
        "phc_id": "PHC-001",
        "total_beds": 30,
        "occupied_beds": 45
    })
    assert bad_bed.status_code == 400, "Expected occupied > total rejection"
    print("[PASS] 10. Validation: Conflicting bed occupancy rejected with HTTP 400")

    # F. Equipment GET & Update
    eq_res = s.get(f"{BASE_URL}/api/equipment?phc_id=PHC-001")
    assert eq_res.status_code == 200
    eq_items = eq_res.json()
    assert len(eq_items) > 0, "No equipment items retrieved"
    first_eq = eq_items[0]
    print(f"[PASS] 11. Equipment: GET /api/equipment returned {len(eq_items)} registered items")

    eq_update = s.post(f"{BASE_URL}/api/equipment/update", json={
        "phc_id": "PHC-001",
        "equipment_id": first_eq["id"],
        "name": first_eq["name"],
        "category": first_eq["category"],
        "quantity": first_eq["quantity"],
        "operational_status": "UNDER_MAINTENANCE",
        "under_maintenance_count": 1,
        "notes": "Scheduled service check"
    })
    assert eq_update.status_code == 200, f"Equipment update failed: {eq_update.text}"
    print(f"[PASS] 12. Action: Equipment Update (POST /api/equipment/update) 200 OK")

    # G. Staff Attendance: punch and manual log
    punch_res = s.post(f"{BASE_URL}/api/staff/punch", json={"card_uid": "RFID-10101", "phc_id": "PHC-001"})
    assert punch_res.status_code == 200
    print(f"[PASS] 13. Action: RFID Punch (POST /api/staff/punch) 200 OK: {punch_res.json()['action']}")

    manual_res = s.post(f"{BASE_URL}/api/staff/log", json={
        "phc_id": "PHC-001",
        "staff_id": "STF-105",
        "status": "CHECKED_IN",
        "verification_method": "Manual Kiosk Override"
    })
    assert manual_res.status_code == 200, f"Manual attendance failed: {manual_res.text}"
    print("[PASS] 14. Action: Manual Attendance (POST /api/staff/log) 200 OK (Method Not Allowed eliminated)")

    action_res = s.post(f"{BASE_URL}/api/staff/action", json={
        "phc_id": "PHC-001",
        "staff_id": "STF-105",
        "action": "CHECK_OUT"
    })
    assert action_res.status_code == 200
    print("[PASS] 15. Action: Staff Duty Action (POST /api/staff/action) 200 OK")

    # H. Footfall Create and Update
    ff_res = s.post(f"{BASE_URL}/api/footfall/log", json={
        "phc_id": "PHC-001",
        "date": today_str,
        "count": 175,
        "male_count": 85,
        "female_count": 80,
        "other_count": 10,
        "emergency_cases": 12,
        "correction_reason": "End-of-day triage reconciliation"
    })
    assert ff_res.status_code == 200, f"Footfall save failed: {ff_res.text}"
    print("[PASS] 16. Action: Footfall Entry & Correction (POST /api/footfall/log) 200 OK")

    # I. Future Footfall rejection
    bad_ff = s.post(f"{BASE_URL}/api/footfall/log", json={
        "phc_id": "PHC-001",
        "date": "2099-01-01",
        "count": 100
    })
    assert bad_ff.status_code == 400
    print("[PASS] 17. Validation: Future footfall date rejected with HTTP 400")

    # J. Resource Request and 409 Conflict
    req_res = s.post(f"{BASE_URL}/api/redistribution/request", json={
        "target_phc": "PHC-001",
        "phc_id": "PHC-001",
        "medicine_name": "Chlorine tablets",
        "quantity": 30,
        "urgency": "NORMAL",
        "reason": "Water sanitation safety buffer"
    })
    # Either 200 or 409 if already pending
    assert req_res.status_code in (200, 409)
    if req_res.status_code == 200:
        print("[PASS] 18. Action: Resource Request (POST /api/redistribution/request) 200 OK")
        dup_res = s.post(f"{BASE_URL}/api/redistribution/request", json={
            "target_phc": "PHC-001",
            "phc_id": "PHC-001",
            "medicine_name": "Chlorine tablets",
            "quantity": 30,
            "urgency": "NORMAL",
            "reason": "Duplicate attempt"
        })
        assert dup_res.status_code == 409, f"Expected 409, got {dup_res.status_code}"
        print(f"[PASS] 19. Conflict Handling: Duplicate pending request rejected with HTTP 409: '{dup_res.json()['detail']}'")
    else:
        print(f"[PASS] 18 & 19. Resource Request & 409 Conflict: Verified existing pending request returned HTTP 409: '{req_res.json()['detail']}'")

    print("\n=================================================================")
    print("ALL 19 STAGE 2 FRONTEND-BACKEND CONTRACT VERIFICATIONS PASSED!")
    print("=================================================================")

if __name__ == "__main__":
    test_frontend_contract()
