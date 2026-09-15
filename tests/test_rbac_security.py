import requests
import json
import sys

BASE_URL = "http://127.0.0.1:8000"

def run_tests():
    print("================================================================")
    print("MERIDIAN HEALTHCARE RBAC & DATA ISOLATION VERIFICATION SUITE")
    print("================================================================")
    passed = 0
    total = 0

    def assert_test(cond, title, details=""):
        nonlocal passed, total
        total += 1
        if cond:
            passed += 1
            print(f"  [PASS] Case {total}: {title}")
        else:
            print(f"  [FAIL] Case {total}: {title} -- {details}")

    # Helper to login and get a session
    def login(username, password):
        s = requests.Session()
        res = s.post(f"{BASE_URL}/api/auth/login", json={"username": username, "password": password})
        return s, res

    # -------------------------------------------------------------
    # 1. Unauthenticated Requests
    # -------------------------------------------------------------
    print("\n--- 1. UNAUTHENTICATED PROTECTION ---")
    r1 = requests.get(f"{BASE_URL}/api/inventory")
    assert_test(r1.status_code == 401, "Unauthenticated GET /api/inventory returns 401", f"Got {r1.status_code}")

    r2 = requests.get(f"{BASE_URL}/api/dashboard/national")
    assert_test(r2.status_code == 401, "Unauthenticated GET /api/dashboard/national returns 401", f"Got {r2.status_code}")

    r3 = requests.get(f"{BASE_URL}/api/dashboard/district")
    assert_test(r3.status_code == 401, "Unauthenticated GET /api/dashboard/district returns 401", f"Got {r3.status_code}")

    r4 = requests.get(f"{BASE_URL}/api/users")
    assert_test(r4.status_code == 401, "Unauthenticated GET /api/users returns 401", f"Got {r4.status_code}")

    # -------------------------------------------------------------
    # 2. Authentication & Role Scopes
    # -------------------------------------------------------------
    print("\n--- 2. AUTHENTICATION & ROLE IDENTIFICATION ---")
    s_admin, res_admin = login("admin@meridian.health", "Admin@123")
    assert_test(res_admin.status_code == 200 and res_admin.json()["user"]["role"] == "NATIONAL_ADMIN", 
                "National Admin login successful with role NATIONAL_ADMIN")

    s_onorth, res_onorth = login("officer.north@meridian.health", "Officer@123")
    assert_test(res_onorth.status_code == 200 and res_onorth.json()["user"]["assigned_district_id"] == "DIST-NORTH",
                "District Officer North login successful assigned to DIST-NORTH")

    s_osouth, res_osouth = login("officer.south@meridian.health", "Officer@123")
    assert_test(res_osouth.status_code == 200 and res_osouth.json()["user"]["assigned_district_id"] == "DIST-SOUTH",
                "District Officer South login successful assigned to DIST-SOUTH")

    s_alpha, res_alpha = login("staff.alpha@meridian.health", "Staff@123")
    assert_test(res_alpha.status_code == 200 and res_alpha.json()["user"]["assigned_phc_id"] == "PHC-001",
                "PHC Staff Alpha login successful assigned to PHC-001")

    # -------------------------------------------------------------
    # 3. PHC Staff Data Isolation
    # -------------------------------------------------------------
    print("\n--- 3. PHC STAFF STRICT DATA ISOLATION ---")
    # staff.alpha assigned to PHC-001 attempting to access PHC-002
    r_phc_deny = s_alpha.get(f"{BASE_URL}/api/dashboard/phc/PHC-002")
    assert_test(r_phc_deny.status_code == 403, "PHC Staff (PHC-001) accessing PHC-002 is rejected with 403 Forbidden")

    # staff.alpha attempting to update PHC-002 stock
    r_inv_deny = s_alpha.post(f"{BASE_URL}/api/inventory/update", json={
        "phc_id": "PHC-002", "medicine_name": "ORS Packets", "quantity": 100
    })
    assert_test(r_inv_deny.status_code == 403, "PHC Staff updating another facility's inventory rejected with 403 Forbidden")

    # staff.alpha query inventory without params -> auto-scoped to PHC-001
    r_inv_scoped = s_alpha.get(f"{BASE_URL}/api/inventory")
    phc_ids_returned = list(set(it["phc_id"] for it in r_inv_scoped.json()))
    assert_test(r_inv_scoped.status_code == 200 and phc_ids_returned == ["PHC-001"],
                "PHC Staff GET /api/inventory automatically filtered exclusively to assigned PHC-001")

    # staff.alpha accessing district dashboard -> 403
    r_dist_deny = s_alpha.get(f"{BASE_URL}/api/dashboard/district")
    assert_test(r_dist_deny.status_code == 403, "PHC Staff accessing District Dashboard is rejected with 403 Forbidden")

    # staff.alpha accessing user management -> 403
    r_usr_deny = s_alpha.get(f"{BASE_URL}/api/users")
    assert_test(r_usr_deny.status_code == 403, "PHC Staff accessing User Management is rejected with 403 Forbidden")

    # -------------------------------------------------------------
    # 4. District Officer Data Isolation & Monitoring
    # -------------------------------------------------------------
    print("\n--- 4. DISTRICT OFFICER SCOPING & MONITORING ---")
    # officer.north (DIST-NORTH) monitoring PHC-001 (in DIST-NORTH) -> 200 OK
    r_onorth_p1 = s_onorth.get(f"{BASE_URL}/api/dashboard/phc/PHC-001")
    assert_test(r_onorth_p1.status_code == 200, "District Officer North successfully monitors in-district facility PHC-001")

    # officer.north (DIST-NORTH) monitoring PHC-002 (in DIST-NORTH) -> 200 OK
    r_onorth_p2 = s_onorth.get(f"{BASE_URL}/api/dashboard/phc/PHC-002")
    assert_test(r_onorth_p2.status_code == 200, "District Officer North successfully monitors in-district facility PHC-002")

    # officer.north attempting to monitor PHC-003 (in DIST-SOUTH) -> 403 Forbidden
    r_onorth_p3 = s_onorth.get(f"{BASE_URL}/api/dashboard/phc/PHC-003")
    assert_test(r_onorth_p3.status_code == 403, "District Officer North attempting to monitor out-of-district PHC-003 rejected with 403")

    # officer.north attempting to call national dashboard -> 403 Forbidden
    r_onorth_nat = s_onorth.get(f"{BASE_URL}/api/dashboard/national")
    assert_test(r_onorth_nat.status_code == 403, "District Officer attempting to view National Dashboard rejected with 403 Forbidden")

    # officer.north district dashboard strictly contains only in-district PHCs
    r_onorth_dist = s_onorth.get(f"{BASE_URL}/api/dashboard/district")
    dist_phc_ids = [p["id"] for p in r_onorth_dist.json()["phc_comparison"]]
    assert_test(r_onorth_dist.status_code == 200 and set(dist_phc_ids) == {"PHC-001", "PHC-002"},
                "District Officer District Dashboard strictly lists only in-district facilities (PHC-001, PHC-002)")

    # -------------------------------------------------------------
    # 5. National Admin Nationwide Oversight & Override Rules
    # -------------------------------------------------------------
    print("\n--- 5. NATIONAL ADMIN OVERSIGHT & ADMINISTRATIVE OVERRIDES ---")
    # National Admin can view National Dashboard
    r_nat = s_admin.get(f"{BASE_URL}/api/dashboard/national")
    assert_test(r_nat.status_code == 200 and r_nat.json()["national_kpis"]["total_districts"] >= 2,
                "National Admin views National Dashboard with nationwide rollups and district comparison")

    # National Admin can monitor PHC-001 and PHC-004 across districts
    r_adm_p1 = s_admin.get(f"{BASE_URL}/api/dashboard/phc/PHC-001")
    r_adm_p4 = s_admin.get(f"{BASE_URL}/api/dashboard/phc/PHC-004")
    assert_test(r_adm_p1.status_code == 200 and r_adm_p4.status_code == 200,
                "National Admin can monitor facilities across any district (PHC-001 North & PHC-004 South)")

    # National Admin attempting to silently modify PHC inventory WITHOUT override reason -> 400 Bad Request
    r_adm_no_reason = s_admin.post(f"{BASE_URL}/api/inventory/update", json={
        "phc_id": "PHC-001", "medicine_name": "ORS Packets", "quantity": 99
    })
    assert_test(r_adm_no_reason.status_code == 400,
                "National Admin silent operational update rejected with 400 (Override confirmation & reason required)")

    # National Admin modifying PHC inventory WITH override reason -> 200 OK & marked OVERRIDDEN
    r_adm_override = s_admin.post(f"{BASE_URL}/api/inventory/update", json={
        "phc_id": "PHC-001", "medicine_name": "ORS Packets", "quantity": 99,
        "override_reason": "Emergency outbreak buffer augmentation approved by Health Director"
    })
    assert_test(r_adm_override.status_code == 200 and r_adm_override.json().get("override_logged") is True,
                "National Admin operational update with explicit reason accepted and logged as OVERRIDDEN")

    # -------------------------------------------------------------
    # 6. Session Invalidation & Disabled Accounts
    # -------------------------------------------------------------
    print("\n--- 6. SESSION LIFECYCLE & ACCOUNT LOCKOUT ---")
    # Disabled account login attempt
    _, res_dis = login("disabled.user@meridian.health", "Disabled@123")
    assert_test(res_dis.status_code == 403, "Disabled account login rejected with 403 Forbidden")

    # Logout invalidation
    s_temp, _ = login("admin@meridian.health", "Admin@123")
    r_me_before = s_temp.get(f"{BASE_URL}/api/auth/me")
    assert_test(r_me_before.status_code == 200, "Session active before logout")
    s_temp.post(f"{BASE_URL}/api/auth/logout")
    r_me_after = s_temp.get(f"{BASE_URL}/api/auth/me")
    assert_test(r_me_after.status_code == 401, "Session successfully invalidated on server after logout (returns 401)")

    # -------------------------------------------------------------
    # 7. Audit Logging Verification
    # -------------------------------------------------------------
    print("\n--- 7. AUDIT TRAIL VERIFICATION ---")
    r_audit = s_admin.get(f"{BASE_URL}/api/audit-logs?limit=50")
    audit_events = r_audit.json()
    actions = [e["action"] for e in audit_events]
    results = [e["result"] for e in audit_events]

    assert_test("INVENTORY_OVERRIDE" in actions and "OVERRIDDEN" in results,
                "Audit log includes INVENTORY_OVERRIDE with result OVERRIDDEN and captured justification")
    assert_test("LOGIN" in actions and "SUCCESS" in results,
                "Audit log includes user authentications")

    # -------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------
    print("\n================================================================")
    print(f"VERIFICATION RESULTS: {passed} / {total} TESTS PASSED")
    print("================================================================")
    if passed == total:
        print(">>> ALL RBAC, SCOPE ENFORCEMENT & SECURITY TESTS SUCCEEDED! <<<")
        return True
    return False

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
