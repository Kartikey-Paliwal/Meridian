import os
import requests
import urllib.request

BASE_URL = os.environ.get("MERIDIAN_BASE_URL", "http://127.0.0.1:8000")

def run_checks():
    print("---------------------------------------------------------")
    print("TESTING ACCOUNT DROPDOWN, LOGOUT & DEMO SWITCHER")
    print("---------------------------------------------------------")

    # 1. Test Demo mode config endpoint
    r_demo = requests.get(f"{BASE_URL}/api/config/demo-mode")
    assert r_demo.status_code == 200, f"demo-mode endpoint returned {r_demo.status_code}"
    assert r_demo.json().get("demo_mode") is True, f"demo_mode not True: {r_demo.json()}"
    print("[PASS] 1. /api/config/demo-mode returns demo_mode: True")

    # 2. Test Login, Profile with demo_mode, and Logout
    s = requests.Session()
    r_login = s.post(f"{BASE_URL}/api/auth/login", json={"username": "admin@meridian.health", "password": "Admin@123"})
    assert r_login.status_code == 200, "Login failed"

    r_me = s.get(f"{BASE_URL}/api/auth/me")
    assert r_me.status_code == 200, "auth/me failed"
    assert r_me.json().get("demo_mode") is True, "demo_mode not in profile"
    print("[PASS] 2. /api/auth/me includes demo_mode: True")

    # 3. Test Logout invalidation
    r_logout = s.post(f"{BASE_URL}/api/auth/logout")
    assert r_logout.status_code == 200, "Logout failed"
    print("[PASS] 3. /api/auth/logout succeeded with 200")

    r_me_after = s.get(f"{BASE_URL}/api/auth/me")
    assert r_me_after.status_code == 401, f"Expected 401 after logout, got {r_me_after.status_code}"
    print("[PASS] 4. /api/auth/me returns 401 after logout")

    # 4. Test HTML elements
    html = urllib.request.urlopen(f"{BASE_URL}/").read().decode("utf-8")
    assert 'id="user-profile-trigger"' in html, "Missing user-profile-trigger button"
    assert 'id="user-dropdown-arrow"' in html, "Missing user-dropdown-arrow"
    assert 'id="menu-switch-demo-btn"' in html, "Missing menu-switch-demo-btn"
    assert "Switch Demo Account" in html, "Missing Switch Demo Account text"
    assert "Logout" in html, "Missing Logout text"
    assert 'id="demo-access-box"' in html, "Missing demo-access-box"
    assert "Demo Access" in html, "Missing Demo Access title"
    print("[PASS] 5. HTML contains all required dropdown triggers, items, and Demo Access box")

    # 5. Test CSS rules
    css = urllib.request.urlopen(f"{BASE_URL}/static/styles.css?v=2026.4").read().decode("utf-8")
    assert ".user-dropdown-arrow" in css, "Missing .user-dropdown-arrow in CSS"
    assert "rotate(180deg)" in css, "Missing rotate(180deg) in CSS"
    assert ".user-dropdown-menu.show" in css or ".user-dropdown-menu.open" in css, "Missing show/open state in CSS"
    assert "z-index: 1050" in css, "Missing z-index: 1050 in CSS"
    print("[PASS] 6. CSS contains animated arrow, z-index 1050, and open/show states")

    # 6. Test JS functions
    js = urllib.request.urlopen(f"{BASE_URL}/static/app.js?v=2026.4").read().decode("utf-8")
    assert "toggleUserDropdown" in js, "Missing toggleUserDropdown in app.js"
    assert "closeUserDropdown" in js, "Missing closeUserDropdown in app.js"
    assert "handleSwitchDemoAccount" in js, "Missing handleSwitchDemoAccount in app.js"
    assert "handleUserBadgeKeydown" in js, "Missing handleUserBadgeKeydown in app.js"
    assert "pageshow" in js, "Missing pageshow guard in app.js"
    assert "popstate" in js, "Missing popstate guard in app.js"
    print("[PASS] 7. JavaScript contains dropdown toggles, keyboard navigation, and history guards")

    # 7. Test each demo account can log in and reach correct dashboard
    for role_name, user_email, pwd, expected_role in [
        ("National Admin", "admin@meridian.health", "Admin@123", "NATIONAL_ADMIN"),
        ("District Officer", "officer.north@meridian.health", "Officer@123", "DISTRICT_OFFICER"),
        ("PHC Staff", "staff.alpha@meridian.health", "Staff@123", "PHC_STAFF"),
    ]:
        s_user = requests.Session()
        r_log = s_user.post(f"{BASE_URL}/api/auth/login", json={"username": user_email, "password": pwd})
        assert r_log.status_code == 200, f"{role_name} login failed"
        assert r_log.json()["user"]["role"] == expected_role, f"Role mismatch for {role_name}"
        # Fetch appropriate dashboard
        if expected_role == "NATIONAL_ADMIN":
            r_dash = s_user.get(f"{BASE_URL}/api/dashboard/national")
        elif expected_role == "DISTRICT_OFFICER":
            r_dash = s_user.get(f"{BASE_URL}/api/dashboard/district?district_id=DIST-NORTH")
        else:
            r_dash = s_user.get(f"{BASE_URL}/api/dashboard/phc/PHC-001")
        assert r_dash.status_code == 200, f"{role_name} dashboard fetch failed"
        print(f"[PASS] Demo Account {role_name} logs in successfully and reaches dashboard (status {r_dash.status_code})")

    print("\n>>> ALL ACCOUNT DROPDOWN & LOGOUT CHECKS PASSED SUCCESSFULLY! <<<")

if __name__ == "__main__":
    run_checks()
