"""
=============================================================================
MERIDIAN HEALTHCARE PLATFORM - STAGE 4 DEMO READINESS TEST SUITE
=============================================================================
Verifies:
1. Health check endpoint (GET /api/health)
2. Demo mode configuration (GET /api/config/demo-mode)
3. Role-based access control on Demo Reset endpoint (POST /api/admin/demo-reset)
4. Predictable baseline dataset restoration after demo reset
5. Standalone CLI reset script execution (backend/reset_demo.py)
6. Security enforcement when DEMO_MODE is disabled
7. Frontend contract verification for Demo Environment indicators and modals
=============================================================================
"""

import sys
import os
import subprocess
import requests
import json

BASE_URL = "http://127.0.0.1:8000"
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# ANSI terminal formatting
GREEN = "\033[92m"
RED = "\033[91m"
BOLD = "\033[1m"
RESET = "\033[0m"

passed_tests = 0
failed_tests = 0

def record_check(description: str, condition: bool, details: str = ""):
    global passed_tests, failed_tests
    if condition:
        passed_tests += 1
        print(f"  {GREEN}[PASS]{RESET} {description}")
    else:
        failed_tests += 1
        print(f"  {RED}[FAIL]{RESET} {description} - {details}")

def login(email, password):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"username": email, "password": password})
    return s, r

def run_tests():
    print(f"\n{BOLD}=================================================================={RESET}")
    print(f"{BOLD}RUNNING STAGE 4 DEMO READINESS & DEPLOYMENT VERIFICATION SUITE{RESET}")
    print(f"{BOLD}=================================================================={RESET}\n")

    # -------------------------------------------------------------------------
    # 1. HEALTH CHECK ENDPOINT (GET /api/health)
    # -------------------------------------------------------------------------
    print(f"{BOLD}--- 1. HEALTH CHECK ENDPOINT ---{RESET}")
    r_health = requests.get(f"{BASE_URL}/api/health")
    record_check("Health endpoint returns HTTP 200", r_health.status_code == 200, f"Status: {r_health.status_code}")
    
    h_data = r_health.json() if r_health.status_code == 200 else {}
    record_check("Health reports status == healthy", h_data.get("status") == "healthy", f"Got: {h_data.get('status')}")
    record_check("Health reports database == connected", h_data.get("database") == "connected", f"Got: {h_data.get('database')}")
    record_check("Health reports valid application version", h_data.get("version") == "2.0.0", f"Got: {h_data.get('version')}")
    record_check("Health response includes ISO timestamp", bool(h_data.get("timestamp")), "Timestamp missing")
    
    # Check zero leak of secrets
    forbidden_keys = ["password", "secret", "token", "path", "user", "connection", "meridian.db"]
    raw_text = json.dumps(h_data).lower()
    has_leak = any(k in raw_text for k in forbidden_keys)
    record_check("Health response contains zero secrets or internal paths", not has_leak, f"Leaked content: {raw_text}")

    # -------------------------------------------------------------------------
    # 2. DEMO MODE CONFIGURATION
    # -------------------------------------------------------------------------
    print(f"\n{BOLD}--- 2. DEMO MODE CONFIGURATION ---{RESET}")
    r_demo = requests.get(f"{BASE_URL}/api/config/demo-mode")
    record_check("Demo mode config endpoint returns HTTP 200", r_demo.status_code == 200)
    d_data = r_demo.json() if r_demo.status_code == 200 else {}
    record_check("Demo mode is enabled by default in demo environment", d_data.get("demo_mode") is True, f"Got: {d_data}")

    # -------------------------------------------------------------------------
    # 3. DEMO RESET AUTHORIZATION & SCOPE ENFORCEMENT
    # -------------------------------------------------------------------------
    print(f"\n{BOLD}--- 3. DEMO DATASET RESET RBAC & CONFIRMATION ---{RESET}")
    s_unauth = requests.Session()
    r_unauth = s_unauth.post(f"{BASE_URL}/api/admin/demo-reset", json={"confirm": True})
    record_check("Unauthenticated demo reset rejected with HTTP 401", r_unauth.status_code == 401, f"Got: {r_unauth.status_code}")

    s_staff, r_staff_login = login("staff.alpha@meridian.health", "Staff@123")
    record_check("PHC Staff logs in successfully", r_staff_login.status_code == 200)
    r_staff_reset = s_staff.post(f"{BASE_URL}/api/admin/demo-reset", json={"confirm": True})
    record_check("PHC Staff rejected from demo reset with HTTP 403", r_staff_reset.status_code == 403, f"Got: {r_staff_reset.status_code}")

    s_officer, r_officer_login = login("officer.north@meridian.health", "Officer@123")
    record_check("District Officer logs in successfully", r_officer_login.status_code == 200)
    r_officer_reset = s_officer.post(f"{BASE_URL}/api/admin/demo-reset", json={"confirm": True})
    record_check("District Officer rejected from demo reset with HTTP 403", r_officer_reset.status_code == 403, f"Got: {r_officer_reset.status_code}")

    s_admin, r_admin_login = login("admin@meridian.health", "Admin@123")
    record_check("National Admin logs in successfully", r_admin_login.status_code == 200)
    
    r_admin_unconfirmed = s_admin.post(f"{BASE_URL}/api/admin/demo-reset", json={"confirm": False})
    record_check("National Admin unconfirmed reset rejected with HTTP 400", r_admin_unconfirmed.status_code == 400, f"Got: {r_admin_unconfirmed.status_code}")

    r_admin_reset = s_admin.post(f"{BASE_URL}/api/admin/demo-reset", json={"confirm": True})
    record_check("National Admin confirmed reset succeeds with HTTP 200", r_admin_reset.status_code == 200, f"Got: {r_admin_reset.status_code}")

    # -------------------------------------------------------------------------
    # 4. PREDICTABLE BASELINE DATASET VERIFICATION
    # -------------------------------------------------------------------------
    print(f"\n{BOLD}--- 4. PREDICTABLE BASELINE DATASET VERIFICATION ---{RESET}")
    r_inv_alpha = s_admin.get(f"{BASE_URL}/api/inventory?phc_id=PHC-001")
    raw_alpha = r_inv_alpha.json()
    alpha_list = raw_alpha if isinstance(raw_alpha, list) else raw_alpha.get("inventory", [])
    items_alpha = {item["medicine_name"]: item["quantity"] for item in alpha_list}
    record_check("Alpha Node ORS Packets at predictable shortage (15 units)", items_alpha.get("ORS Packets") == 15, f"Got: {items_alpha.get('ORS Packets')}")
    record_check("Alpha Node Paracetamol at low stock (25 units)", items_alpha.get("Paracetamol 500mg") == 25, f"Got: {items_alpha.get('Paracetamol 500mg')}")

    r_inv_beta = s_admin.get(f"{BASE_URL}/api/inventory?phc_id=PHC-002")
    raw_beta = r_inv_beta.json()
    beta_list = raw_beta if isinstance(raw_beta, list) else raw_beta.get("inventory", [])
    items_beta = {item["medicine_name"]: item["quantity"] for item in beta_list}
    record_check("Beta Node ORS Packets at predictable safe surplus (320 units)", items_beta.get("ORS Packets") == 320, f"Got: {items_beta.get('ORS Packets')}")

    # Check transfers
    r_transfers = s_admin.get(f"{BASE_URL}/api/redistribution/transfers")
    transfers = r_transfers.json().get("transfers", [])
    has_requested = any(t["status"] == "Requested" and t["medicine_name"] == "ORS Packets" and t["source_phc"] == "PHC-002" and t["target_phc"] == "PHC-001" for t in transfers)
    has_in_transit = any(t["status"] == "In Transit" and t.get("is_escalated") == 1 for t in transfers)
    has_completed = any(t["status"] == "Completed" for t in transfers)
    has_approved = any(t["status"] == "Approved" for t in transfers)

    record_check("Seeded pending resource request (Requested, ORS Packets, 60 units)", has_requested)
    record_check("Seeded delayed transfer (In Transit, is_escalated=1)", has_in_transit)
    record_check("Seeded completed transfer (Completed)", has_completed)
    record_check("Seeded approved transfer (Approved awaiting dispatch)", has_approved)

    # Check audit log entry
    r_audit = s_admin.get(f"{BASE_URL}/api/audit-logs")
    logs = r_audit.json().get("audit_logs", [])
    reset_logs = [l for l in logs if l.get("action") == "DEMO_DATA_RESET"]
    record_check("Demo reset operation logged in immutable audit ledger", len(reset_logs) > 0, f"Found: {len(reset_logs)} entries")

    # -------------------------------------------------------------------------
    # 5. STANDALONE CLI RESET SCRIPT EXECUTION
    # -------------------------------------------------------------------------
    print(f"\n{BOLD}--- 5. STANDALONE CLI RESET SCRIPT EXECUTION ---{RESET}")
    cli_cmd = [sys.executable, os.path.join(PROJECT_ROOT, "backend", "reset_demo.py")]
    proc = subprocess.run(cli_cmd, capture_output=True, text=True, cwd=PROJECT_ROOT)
    record_check("backend/reset_demo.py runs cleanly with exit code 0", proc.returncode == 0, f"Code: {proc.returncode}, Err: {proc.stderr}")
    record_check("backend/reset_demo.py output confirms baseline restoration", "Demonstration dataset restored to baseline state" in proc.stdout, f"Stdout: {proc.stdout[:200]}")

    # -------------------------------------------------------------------------
    # 6. DEMO MODE DISABLED (PRODUCTION) BEHAVIOR
    # -------------------------------------------------------------------------
    print(f"\n{BOLD}--- 6. DEMO MODE DISABLED (PRODUCTION) BEHAVIOR ---{RESET}")
    from fastapi import HTTPException
    from backend.main import reset_demo_data_endpoint
    from backend.models import DemoResetRequest

    os.environ["DEMO_MODE"] = "false"
    try:
        reset_demo_data_endpoint(
            req=DemoResetRequest(confirm=True),
            current_user={"id": "USR-NAT-001", "role": "NATIONAL_ADMIN", "full_name": "Admin"}
        )
        record_check("Endpoint disabled when DEMO_MODE=false", False, "Expected HTTPException 403")
    except HTTPException as e:
        record_check("Endpoint disabled when DEMO_MODE=false raises HTTP 403", e.status_code == 403, f"Got: {e.status_code}")
    finally:
        os.environ["DEMO_MODE"] = "true"

    # -------------------------------------------------------------------------
    # 7. FRONTEND CONTRACT & ZERO NATIVE ALERT VERIFICATION
    # -------------------------------------------------------------------------
    print(f"\n{BOLD}--- 7. FRONTEND CONTRACT & UI READINESS ---{RESET}")
    html_path = os.path.join(PROJECT_ROOT, "frontend", "index.html")
    with open(html_path, "r", encoding="utf-8") as f:
        html_content = f.read()

    css_path = os.path.join(PROJECT_ROOT, "frontend", "styles.css")
    with open(css_path, "r", encoding="utf-8") as f:
        css_content = f.read()

    js_path = os.path.join(PROJECT_ROOT, "frontend", "app.js")
    with open(js_path, "r", encoding="utf-8") as f:
        js_content = f.read()

    record_check("HTML contains #demo-environment-badge element", 'id="demo-environment-badge"' in html_content)
    record_check("HTML contains #menu-demo-reset-btn element in dropdown", 'id="menu-demo-reset-btn"' in html_content)
    record_check("HTML contains #demo-reset-confirm-modal element", 'id="demo-reset-confirm-modal"' in html_content)
    record_check("CSS defines .demo-environment-badge styles", ".demo-environment-badge" in css_content)
    record_check("JS defines executeDemoReset handler", "executeDemoReset" in js_content)
    record_check("JS defines openDemoResetModal and closeDemoResetModal", "openDemoResetModal" in js_content and "closeDemoResetModal" in js_content)
    
    # Verify zero native alert dialogs
    import re
    alert_matches = re.findall(r"(?<![a-zA-Z0-9_])alert\s*\(", js_content)
    record_check("Frontend contains zero native browser alert() dialogs", len(alert_matches) == 0, f"Found: {len(alert_matches)}")

    # -------------------------------------------------------------------------
    # 7. ENVIRONMENT TEMPLATE (.env.example) VERIFICATION
    # -------------------------------------------------------------------------
    print(f"\n{BOLD}--- 7. ENVIRONMENT TEMPLATE VERIFICATION ---{RESET}")
    env_example_path = os.path.join(PROJECT_ROOT, ".env.example")
    record_check(".env.example exists in repository root", os.path.exists(env_example_path))
    
    if os.path.exists(env_example_path):
        with open(env_example_path, "r", encoding="utf-8") as f:
            env_content = f.read()
        record_check(".env.example documents DEMO_MODE", "DEMO_MODE" in env_content)
        record_check(".env.example documents MERIDIAN_SECRET_KEY", "MERIDIAN_SECRET_KEY" in env_content)
        record_check(".env.example documents SECURE_COOKIES", "SECURE_COOKIES" in env_content)
        record_check(".env.example documents MERIDIAN_DB_PATH", "MERIDIAN_DB_PATH" in env_content)
        record_check(".env.example documents ALLOWED_ORIGINS", "ALLOWED_ORIGINS" in env_content)

    # -------------------------------------------------------------------------
    # SUMMARY
    # -------------------------------------------------------------------------
    total_tests = passed_tests + failed_tests
    print(f"\n{BOLD}=================================================================={RESET}")
    print(f"{BOLD}STAGE 4 DEMO READINESS EXECUTION SUMMARY{RESET}")
    print(f"{BOLD}=================================================================={RESET}")
    print(f"Total Tests Run: {total_tests}")
    print(f"Passed: {GREEN}{passed_tests}{RESET}")
    print(f"Failed: {RED}{failed_tests}{RESET}")
    pass_rate = round((passed_tests / total_tests) * 100, 1) if total_tests > 0 else 0
    print(f"Pass Rate: {BOLD}{pass_rate}%{RESET}\n")

    if failed_tests > 0:
        sys.exit(1)

if __name__ == "__main__":
    run_tests()
