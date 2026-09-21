import requests
import json

BASE_URL = "http://127.0.0.1:8000"

def test_operations_monitoring():
    print("=================================================================")
    print("TEST SUITE: DISTRICT & NATIONAL OPERATIONS MONITORING (RBAC & UI)")
    print("=================================================================")

    # 1. Unauthenticated Security Checks
    res = requests.get(f"{BASE_URL}/api/operations/district-monitoring/DIST-NORTH")
    assert res.status_code == 401, f"Expected 401 for unauthenticated district monitoring, got {res.status_code}"
    print("[PASS] 1. Unauthenticated access to /api/operations/district-monitoring/DIST-NORTH correctly returned HTTP 401")

    res = requests.get(f"{BASE_URL}/api/operations/national-monitoring")
    assert res.status_code == 401, f"Expected 401 for unauthenticated national monitoring, got {res.status_code}"
    print("[PASS] 2. Unauthenticated access to /api/operations/national-monitoring correctly returned HTTP 401")

    # 2. PHC Staff Role Tests (staff.alpha@meridian.health)
    s_phc = requests.Session()
    login_phc = s_phc.post(f"{BASE_URL}/api/auth/login", json={"username": "staff.alpha@meridian.health", "password": "Staff@123"})
    assert login_phc.status_code == 200
    print("[PASS] 3. Authenticated as PHC Staff (staff.alpha@meridian.health)")

    res_phc_dist = s_phc.get(f"{BASE_URL}/api/operations/district-monitoring/DIST-NORTH")
    assert res_phc_dist.status_code == 403, f"Expected 403 for PHC staff accessing district monitoring, got {res_phc_dist.status_code}"
    print("[PASS] 4. PHC Staff forbidden (HTTP 403) from accessing /api/operations/district-monitoring/DIST-NORTH")

    res_phc_nat = s_phc.get(f"{BASE_URL}/api/operations/national-monitoring")
    assert res_phc_nat.status_code == 403, f"Expected 403 for PHC staff accessing national monitoring, got {res_phc_nat.status_code}"
    print("[PASS] 5. PHC Staff forbidden (HTTP 403) from accessing /api/operations/national-monitoring")

    # 3. District Officer Role Tests (officer.north@meridian.health - assigned DIST-NORTH)
    s_dist = requests.Session()
    login_dist = s_dist.post(f"{BASE_URL}/api/auth/login", json={"username": "officer.north@meridian.health", "password": "Officer@123"})
    assert login_dist.status_code == 200
    print("[PASS] 6. Authenticated as District Officer North (officer.north@meridian.health)")

    # Access assigned district
    res_dist_north = s_dist.get(f"{BASE_URL}/api/operations/district-monitoring/DIST-NORTH")
    assert res_dist_north.status_code == 200, f"District Officer North failed to load assigned district: {res_dist_north.text}"
    data_north = res_dist_north.json()
    assert "summary" in data_north, "Missing summary object in district monitoring response"
    assert "total_phcs" in data_north["summary"], "Missing total_phcs in summary"
    assert "reporting_today" in data_north["summary"], "Missing reporting_today in summary"
    assert "requiring_attention" in data_north["summary"], "Missing requiring_attention in summary"
    assert "pending_resource_requests" in data_north["summary"], "Missing pending_resource_requests in summary"

    records = data_north.get("phc_monitoring_records", [])
    assert len(records) == 2, f"Expected 2 facilities in DIST-NORTH, got {len(records)}"
    for r in records:
        assert "overall_status" in r, f"Missing overall_status in record: {r.get('phc_id')}"
        assert r["overall_status"] in ["Normal", "Attention Required", "Critical", "Missing or Stale Data"]
        assert "medicine_status" in r
        assert "bed_availability" in r
        assert "staff_attendance" in r
        assert "patient_footfall" in r
    print(f"[PASS] 7. District Officer North successfully loaded DIST-NORTH monitoring: {len(records)} PHCs, summary: {data_north['summary']}")

    # Prevent cross-district access (attempt to view DIST-SOUTH)
    res_dist_south = s_dist.get(f"{BASE_URL}/api/operations/district-monitoring/DIST-SOUTH")
    assert res_dist_south.status_code == 403, f"Expected 403 for unauthorized district DIST-SOUTH, got {res_dist_south.status_code}"
    print("[PASS] 8. District Officer North forbidden (HTTP 403) from accessing another district (DIST-SOUTH)")

    # Prevent District Officer from accessing national monitoring
    res_dist_nat = s_dist.get(f"{BASE_URL}/api/operations/national-monitoring")
    assert res_dist_nat.status_code == 403, f"Expected 403 for District Officer accessing national monitoring, got {res_dist_nat.status_code}"
    print("[PASS] 9. District Officer forbidden (HTTP 403) from accessing /api/operations/national-monitoring")

    # Read-only PHC details via dashboard endpoint
    res_phc_details = s_dist.get(f"{BASE_URL}/api/dashboard/phc/PHC-001")
    assert res_phc_details.status_code == 200, f"District Officer failed to view facility details: {res_phc_details.text}"
    phc_data = res_phc_details.json()
    assert phc_data["is_supervisor_view"] is True, "Expected is_supervisor_view=True for supervisor session"
    assert "inventory" in phc_data
    assert "bed_status" in phc_data
    assert "equipment" in phc_data
    assert "staff_attendance" in phc_data
    print("[PASS] 10. District Officer loaded read-only PHC details for assigned facility PHC-001 (is_supervisor_view=True)")

    # Prevent District Officer from loading PHC details for facility outside their district (PHC-003 is in DIST-SOUTH)
    res_unauth_phc = s_dist.get(f"{BASE_URL}/api/dashboard/phc/PHC-003")
    assert res_unauth_phc.status_code == 403, f"Expected 403 for PHC outside district, got {res_unauth_phc.status_code}"
    print("[PASS] 11. District Officer forbidden (HTTP 403) from viewing PHC details outside assigned district (PHC-003)")

    # 4. National Admin Role Tests (admin@meridian.health)
    s_admin = requests.Session()
    login_admin = s_admin.post(f"{BASE_URL}/api/auth/login", json={"username": "admin@meridian.health", "password": "Admin@123"})
    assert login_admin.status_code == 200
    print("[PASS] 12. Authenticated as National Admin (admin@meridian.health)")

    res_nat = s_admin.get(f"{BASE_URL}/api/operations/national-monitoring")
    assert res_nat.status_code == 200, f"National Admin failed to load national monitoring: {res_nat.text}"
    nat_data = res_nat.json()
    assert "kpis" in nat_data, "Missing kpis in national monitoring response"
    kpis = nat_data["kpis"]
    assert "total_districts" in kpis
    assert "total_phcs" in kpis
    assert "reporting_today" in kpis
    assert "critical_operational_issues" in kpis
    assert kpis["total_districts"] == 2
    assert kpis["total_phcs"] == 4

    dist_summaries = nat_data.get("district_summaries", [])
    assert len(dist_summaries) == 2, f"Expected 2 districts in summary, got {len(dist_summaries)}"
    for d in dist_summaries:
        assert "overall_status" in d, f"Missing overall_status in district: {d.get('district_id')}"
        assert "bed_availability" in d
        assert "attendance_compliance" in d
        assert "stale_or_missing_phcs" in d
    print(f"[PASS] 13. National Admin loaded nationwide monitoring: 4 compact KPI values verified ({kpis})")

    # National Admin drilldown (National -> District -> PHC)
    res_drilldown_north = s_admin.get(f"{BASE_URL}/api/operations/district-monitoring/DIST-NORTH")
    assert res_drilldown_north.status_code == 200, f"National Admin failed to drill down into DIST-NORTH: {res_drilldown_north.text}"
    res_drilldown_south = s_admin.get(f"{BASE_URL}/api/operations/district-monitoring/DIST-SOUTH")
    assert res_drilldown_south.status_code == 200, f"National Admin failed to drill down into DIST-SOUTH: {res_drilldown_south.text}"
    print("[PASS] 14. National Admin drill-down: can access any district monitoring roster (DIST-NORTH & DIST-SOUTH)")

    # National Admin PHC details drill-down
    res_nat_phc = s_admin.get(f"{BASE_URL}/api/dashboard/phc/PHC-003")
    assert res_nat_phc.status_code == 200
    assert res_nat_phc.json()["is_supervisor_view"] is True
    print("[PASS] 15. National Admin PHC drilldown: loaded read-only PHC details for PHC-003 (is_supervisor_view=True)")

    # 5. Frontend Contract & DOM Verification
    res_index = requests.get(f"{BASE_URL}/")
    assert res_index.status_code == 200
    html = res_index.text

    # Verify required elements for District Officer and National Admin
    required_ids = [
        "ops-panel-title", "ops-panel-subtitle",
        "ops-phc-container", "ops-district-container", "ops-national-container",
        # District 4 Summary Cards
        "dist-kpi-total-phcs", "dist-kpi-reporting-today", "dist-kpi-requiring-attention", "dist-kpi-pending-requests",
        "dist-ops-monitoring-table", "dist-ops-monitoring-tbody",
        # National 4 Summary Cards
        "nat-kpi-total-districts", "nat-kpi-total-phcs", "nat-kpi-reporting-today", "nat-kpi-critical-issues",
        "nat-district-summary-view", "nat-ops-monitoring-table", "nat-ops-monitoring-tbody",
        # National Drilldown Container
        "nat-district-drilldown-container", "nat-drilldown-district-name",
        "nat-drilldown-total-phcs", "nat-drilldown-reporting-today", "nat-drilldown-requiring-attention", "nat-drilldown-pending-requests",
        "nat-drilldown-table", "nat-drilldown-tbody",
        # Read-Only PHC Details Modal
        "phc-monitoring-detail-modal", "modal-phc-name-title", "modal-phc-meta-subtitle",
        "modal-phc-location", "modal-phc-last-sync",
        "modal-phc-inventory-table", "modal-phc-inventory-tbody",
        "modal-phc-total-beds", "modal-phc-occ-beds", "modal-phc-avail-beds",
        "modal-phc-equip-list", "modal-phc-staff-list", "modal-phc-footfall-demographics", "modal-phc-transfers-list"
    ]
    for el_id in required_ids:
        assert f'id="{el_id}"' in html, f"Missing required element in index.html: id='{el_id}'"
    print(f"[PASS] 16. HTML DOM Verification: All {len(required_ids)} required operations element IDs verified")

    # Verify JS functions exist
    res_js = requests.get(f"{BASE_URL}/static/app.js")
    assert res_js.status_code == 200
    js = res_js.text
    required_fns = [
        "loadDistrictOperationsMonitoring", "loadNationalOperationsMonitoring",
        "openNationalDistrictDrilldown", "closeNationalDistrictDrilldown", "refreshNationalDistrictDrilldown",
        "openPHCDetailsModal", "closePHCDetailsModal", "renderOverallStatusBadge"
    ]
    for fn in required_fns:
        assert f"function {fn}" in js or f"async function {fn}" in js, f"Missing required JS function: {fn}"
    print(f"[PASS] 17. JavaScript Functions: All {len(required_fns)} required monitoring functions verified")

    # Verify zero alert() in app.js
    import re
    alerts = re.findall(r'\balert\(', js)
    assert len(alerts) == 0, f"Found native alert() calls in app.js: {len(alerts)}"
    print("[PASS] 18. Zero native alert() dialogs in app.js (clean toast notifications preserved)")

    print("\n=================================================================")
    print("ALL 18 OPERATIONS MONITORING TESTS COMPLETED WITH 100% SUCCESS!")
    print("=================================================================")

if __name__ == "__main__":
    test_operations_monitoring()
