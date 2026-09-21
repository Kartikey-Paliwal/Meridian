"""
=============================================================================
MERIDIAN HEALTHCARE - MEDICINE BATCH PROVENANCE RBAC & SCOPING TEST SUITE
=============================================================================
Explicit verification of:
1. PHC Staff accessing their assigned PHC batch
2. PHC Staff accessing another PHC's batch
3. District Officer accessing a batch in their district
4. District Officer accessing another district's batch
5. National Admin accessing an existing batch
6. Direct URL/query manipulation
7. Unauthenticated access protection (HTTP 401)
8. Genuinely nonexistent batch (HTTP 404)
=============================================================================
"""

import os
import sys
import requests

BASE_URL = os.environ.get("MERIDIAN_BASE_URL", "http://127.0.0.1:8000")

# ANSI colors
GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"

def login(email, password):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"username": email, "password": password})
    assert r.status_code == 200, f"Login failed for {email}: {r.text}"
    return s

def run_tests():
    print(f"\n{BOLD}=================================================================={RESET}")
    print(f"{BOLD}STARTING MEDICINE BATCH PROVENANCE SCOPING SUITE{RESET}")
    print(f"{BOLD}=================================================================={RESET}\n")

    s_admin = login("admin@meridian.health", "Admin@123")
    s_officer = login("officer.north@meridian.health", "Officer@123")
    s_staff = login("staff.alpha@meridian.health", "Staff@123")

    passed = 0
    total = 0

    def check(cond, title, expected, actual):
        nonlocal passed, total
        total += 1
        status_str = f"{GREEN}[PASS]{RESET}" if cond else f"{RED}[FAIL]{RESET}"
        if cond:
            passed += 1
            print(f"  {status_str} Test {total}: {title}")
        else:
            print(f"  {status_str} Test {total}: {title}")
            print(f"         Expected: {expected} | Actual: {actual}")

    # 1. PHC Staff accessing their assigned PHC batch (BATCH-ORS-2026-A1 belongs to PHC-001)
    r1 = s_staff.get(f"{BASE_URL}/api/provenance/batch/BATCH-ORS-2026-A1")
    check(
        r1.status_code == 200 and r1.json().get("integrity_status") == "VERIFIED_AUTHENTIC",
        "PHC Staff accessing assigned PHC batch (BATCH-ORS-2026-A1)",
        "HTTP 200 VERIFIED_AUTHENTIC",
        f"HTTP {r1.status_code}"
    )

    # 2. PHC Staff accessing another PHC's batch (BATCH-ORS-2026-B8 belongs to PHC-002)
    r2 = s_staff.get(f"{BASE_URL}/api/provenance/batch/BATCH-ORS-2026-B8")
    check(
        r2.status_code == 403,
        "PHC Staff accessing another PHC's batch (BATCH-ORS-2026-B8) rejected with 403",
        "HTTP 403 Forbidden",
        f"HTTP {r2.status_code}"
    )

    # 3. District Officer accessing a batch in their district (BATCH-ORS-2026-B8 in PHC-002 / DIST-NORTH)
    r3 = s_officer.get(f"{BASE_URL}/api/provenance/batch/BATCH-ORS-2026-B8")
    check(
        r3.status_code == 200 and r3.json().get("integrity_status") == "VERIFIED_AUTHENTIC",
        "District Officer accessing in-district batch (BATCH-ORS-2026-B8)",
        "HTTP 200 VERIFIED_AUTHENTIC",
        f"HTTP {r3.status_code}"
    )

    # 4. District Officer accessing another district's batch (BATCH-ORS-2026-S1 in PHC-003 / DIST-SOUTH)
    r4 = s_officer.get(f"{BASE_URL}/api/provenance/batch/BATCH-ORS-2026-S1")
    check(
        r4.status_code == 403,
        "District Officer accessing out-of-district batch (BATCH-ORS-2026-S1) rejected with 403",
        "HTTP 403 Forbidden",
        f"HTTP {r4.status_code}"
    )

    # 5. National Admin accessing an existing batch nationwide (BATCH-ORS-2026-S1 in DIST-SOUTH)
    r5 = s_admin.get(f"{BASE_URL}/api/provenance/batch/BATCH-ORS-2026-S1")
    check(
        r5.status_code == 200 and r5.json().get("integrity_status") == "VERIFIED_AUTHENTIC",
        "National Admin accessing existing batch nationwide (BATCH-ORS-2026-S1)",
        "HTTP 200 VERIFIED_AUTHENTIC",
        f"HTTP {r5.status_code}"
    )

    # 6. Direct URL/query manipulation (PHC Staff attempting query param override ?phc_id=PHC-003)
    r6 = s_staff.get(f"{BASE_URL}/api/provenance/batch/BATCH-ORS-2026-A1?phc_id=PHC-003")
    check(
        r6.status_code == 403,
        "Direct URL/query manipulation (?phc_id=PHC-003) rejected with 403",
        "HTTP 403 Forbidden",
        f"HTTP {r6.status_code}"
    )

    # 7. Unauthenticated access rejected with 401
    r7 = requests.get(f"{BASE_URL}/api/provenance/batch/BATCH-ORS-2026-A1")
    check(
        r7.status_code == 401,
        "Unauthenticated access rejected with 401",
        "HTTP 401 Unauthorized",
        f"HTTP {r7.status_code}"
    )

    # 8. Genuinely nonexistent batch returns 404
    r8 = s_admin.get(f"{BASE_URL}/api/provenance/batch/NONEXISTENT-BATCH-999")
    check(
        r8.status_code == 404,
        "Genuinely nonexistent batch returns 404",
        "HTTP 404 Not Found",
        f"HTTP {r8.status_code}"
    )

    print(f"\n{BOLD}=================================================================={RESET}")
    print(f"{BOLD}BATCH PROVENANCE TEST EXECUTION SUMMARY: {passed} / {total} PASSED{RESET}")
    print(f"{BOLD}=================================================================={RESET}\n")

    return passed == total

if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
