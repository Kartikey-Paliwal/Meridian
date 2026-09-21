"""
=============================================================================
MERIDIAN HEALTHCARE APPLICATION - STAGE 4 AI & ENTERPRISE TEST SUITE
=============================================================================
Verifies all new AI forecasting, federated learning, operations monitoring,
security administration, batch provenance, and FHIR export features.
=============================================================================
"""

import sys
import os
import sqlite3
import requests
import math

BASE_URL = "http://127.0.0.1:8000"
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "backend", "meridian.db")

# Terminal Color formatting
GREEN = "\033[92m"
RED = "\033[91m"
RESET = "\033[0m"
BOLD = "\033[1m"

test_results = []

def record_result(area, test_name, expected, actual, passed):
    test_results.append({
        "area": area,
        "test": test_name,
        "expected": expected,
        "actual": actual,
        "pass": passed
    })
    status_str = f"{GREEN}[PASS]{RESET}" if passed else f"{RED}[FAIL]{RESET}"
    print(f"  {status_str} {area}: {test_name}")
    if not passed:
        print(f"         Expected: {expected} | Actual: {actual}")

def login(email, password):
    s = requests.Session()
    r = s.post(f"{BASE_URL}/api/auth/login", json={"username": email, "password": password})
    return s, r

def run_stage4_tests():
    print(f"\n{BOLD}=================================================================={RESET}")
    print(f"{BOLD}STARTING STAGE 4 AI, FEDERATED LEARNING & ENTERPRISE SUITE{RESET}")
    print(f"{BOLD}=================================================================={RESET}\n")

    # Establish authenticated sessions
    s_admin, r_admin = login("admin@meridian.health", "Admin@123")
    s_officer, r_officer = login("officer.north@meridian.health", "Officer@123")
    s_staff, r_staff = login("staff.alpha@meridian.health", "Staff@123")

    assert r_admin.status_code == 200, "Admin login failed"
    assert r_officer.status_code == 200, "District Officer login failed"
    assert r_staff.status_code == 200, "PHC Staff login failed"

    # =========================================================================
    # 1. OPERATIONS SURVEILLANCE & MONITORING SCOPES
    # =========================================================================
    print(f"\n{BOLD}--- 1. OPERATIONS MONITORING & ROLE ISOLATION ---{RESET}")

    # 1.1 District Officer can monitor assigned district
    r = s_officer.get(f"{BASE_URL}/api/operations/district-monitoring/DIST-NORTH")
    data = r.json() if r.status_code == 200 else {}
    record_result(
        "1. Operations Monitoring", "District Officer access to assigned district monitoring",
        "HTTP 200 with phc_monitoring_records",
        f"HTTP {r.status_code} records: {len(data.get('phc_monitoring_records', []))}",
        r.status_code == 200 and len(data.get("phc_monitoring_records", [])) >= 2
    )

    # 1.2 District Officer cannot monitor unassigned district
    r_bad_dist = s_officer.get(f"{BASE_URL}/api/operations/district-monitoring/DIST-SOUTH")
    record_result(
        "1. Operations Monitoring", "District Officer rejected from unassigned district monitoring",
        "HTTP 403 Forbidden",
        f"HTTP {r_bad_dist.status_code}",
        r_bad_dist.status_code == 403
    )

    # 1.3 PHC Staff rejected from district operations monitoring
    r_staff_dist = s_staff.get(f"{BASE_URL}/api/operations/district-monitoring/DIST-NORTH")
    record_result(
        "1. Operations Monitoring", "PHC Staff rejected from district operations monitoring",
        "HTTP 403 Forbidden",
        f"HTTP {r_staff_dist.status_code}",
        r_staff_dist.status_code == 403
    )

    # 1.4 National Admin can access national operational monitoring
    r_nat_ops = s_admin.get(f"{BASE_URL}/api/operations/national-monitoring")
    data_nat = r_nat_ops.json() if r_nat_ops.status_code == 200 else {}
    record_result(
        "1. Operations Monitoring", "National Admin access to national operational surveillance",
        "HTTP 200 with district_summaries",
        f"HTTP {r_nat_ops.status_code} summaries: {len(data_nat.get('district_summaries', []))}",
        r_nat_ops.status_code == 200 and len(data_nat.get("district_summaries", [])) >= 2
    )

    # 1.5 Non-admins rejected from national operational monitoring
    r_officer_nat = s_officer.get(f"{BASE_URL}/api/operations/national-monitoring")
    r_staff_nat = s_staff.get(f"{BASE_URL}/api/operations/national-monitoring")
    record_result(
        "1. Operations Monitoring", "Non-admins rejected from national operational monitoring",
        "HTTP 403 Forbidden for both",
        f"Officer: HTTP {r_officer_nat.status_code}, Staff: HTTP {r_staff_nat.status_code}",
        r_officer_nat.status_code == 403 and r_staff_nat.status_code == 403
    )

    # =========================================================================
    # 2. MULTI-ROLE AI DEMAND INSIGHTS & EARLY WARNINGS
    # =========================================================================
    print(f"\n{BOLD}--- 2. MULTI-ROLE AI INSIGHTS & DEMAND FORECASTING ---{RESET}")

    # 2.1 PHC Staff accesses local AI demand insights
    r_phc_ai = s_staff.get(f"{BASE_URL}/api/insights/phc/PHC-001")
    data_phc_ai = r_phc_ai.json() if r_phc_ai.status_code == 200 else {}
    forecasts = data_phc_ai.get("medicine_forecasts", [])
    has_keys = all("days_to_stockout" in f and "estimated_stockout_date" in f and "safe_reorder_date" in f for f in forecasts) if forecasts else False
    record_result(
        "2. AI Insights", "PHC Staff retrieves 3-7 day linear demand forecast for assigned facility",
        "HTTP 200 with forecasts containing days_to_stockout, stockout_date, reorder_date",
        f"HTTP {r_phc_ai.status_code} items: {len(forecasts)}, schema valid: {has_keys}",
        r_phc_ai.status_code == 200 and len(forecasts) > 0 and has_keys
    )

    # 2.2 PHC Staff rejected from cross-facility AI insights
    r_phc_cross = s_staff.get(f"{BASE_URL}/api/insights/phc/PHC-003")
    record_result(
        "2. AI Insights", "PHC Staff rejected from cross-facility AI insights (PHC-003)",
        "HTTP 403 Forbidden",
        f"HTTP {r_phc_cross.status_code}",
        r_phc_cross.status_code == 403
    )

    # 2.3 District Officer can view PHCs in their district, rejected for other district PHCs
    r_dist_phc_ok = s_officer.get(f"{BASE_URL}/api/insights/phc/PHC-001")
    r_dist_phc_bad = s_officer.get(f"{BASE_URL}/api/insights/phc/PHC-003")
    record_result(
        "2. AI Insights", "District Officer authorized for assigned PHC and rejected for external PHC",
        "HTTP 200 for PHC-001 and HTTP 403 for PHC-003",
        f"PHC-001: HTTP {r_dist_phc_ok.status_code}, PHC-003: HTTP {r_dist_phc_bad.status_code}",
        r_dist_phc_ok.status_code == 200 and r_dist_phc_bad.status_code == 403
    )

    # 2.4 District Officer access to District AI early warnings
    r_dist_ai = s_officer.get(f"{BASE_URL}/api/insights/district/DIST-NORTH")
    data_dist_ai = r_dist_ai.json() if r_dist_ai.status_code == 200 else {}
    has_dist_ai = "predicted_shortages" in data_dist_ai and "transfer_recommendations" in data_dist_ai
    record_result(
        "2. AI Insights", "District Officer retrieves district shortage predictions and donor recommendations",
        "HTTP 200 with predicted_shortages and transfer_recommendations",
        f"HTTP {r_dist_ai.status_code} valid: {has_dist_ai}",
        r_dist_ai.status_code == 200 and has_dist_ai
    )

    # 2.5 District AI recommendations include donor surplus and safe buffer margin
    recs = data_dist_ai.get("transfer_recommendations", [])
    valid_recs = False
    if recs:
        r0 = recs[0]
        valid_recs = "donor_surplus" in r0 and "donor_safe_buffer_retained" in r0 and "eta_minutes" in r0
    else:
        valid_recs = True
    record_result(
        "2. AI Insights", "District donor matching verifies donor surplus and safe par retention",
        "Recommendation contains donor_surplus, safe_buffer, and eta",
        f"Verified: {valid_recs}",
        valid_recs
    )

    # 2.6 National AI insights access
    r_nat_ai = s_admin.get(f"{BASE_URL}/api/insights/national")
    data_nat_ai = r_nat_ai.json() if r_nat_ai.status_code == 200 else {}
    has_nat_ai = "predicted_shortages" in data_nat_ai and "network_pressure" in data_nat_ai and "active_escalations" in data_nat_ai
    record_result(
        "2. AI Insights", "National Admin retrieves network-wide demand intelligence",
        "HTTP 200 with network_pressure, predicted_shortages, active_escalations",
        f"HTTP {r_nat_ai.status_code} valid: {has_nat_ai}",
        r_nat_ai.status_code == 200 and has_nat_ai
    )

    # 2.7 Non-admins rejected from National AI insights
    r_non_nat = s_officer.get(f"{BASE_URL}/api/insights/national")
    record_result(
        "2. AI Insights", "District Officer rejected from National AI insights",
        "HTTP 403 Forbidden",
        f"HTTP {r_non_nat.status_code}",
        r_non_nat.status_code == 403
    )

    # =========================================================================
    # 3. FEDERATED LEARNING AGGREGATION & PRIVACY DEMONSTRATION
    # =========================================================================
    print(f"\n{BOLD}--- 3. FEDERATED LEARNING DEMONSTRATION & AGGREGATION ---{RESET}")

    # 3.1 Federated status inspection
    r_fed_status = s_admin.get(f"{BASE_URL}/api/federated/status")
    data_fed = r_fed_status.json() if r_fed_status.status_code == 200 else {}
    has_fed_meta = "active_model_version" in data_fed and "differential_privacy_budget" in data_fed and "zero_raw_records_transmitted" in data_fed
    record_result(
        "3. Federated Learning", "Federated model status telemetry accessible",
        "HTTP 200 with model version, DP budget, and zero raw records guarantee",
        f"HTTP {r_fed_status.status_code} meta valid: {has_fed_meta}",
        r_fed_status.status_code == 200 and has_fed_meta and data_fed.get("zero_raw_records_transmitted") is True
    )

    # 3.2 Non-admins rejected from triggering federated round
    r_fed_officer = s_officer.post(f"{BASE_URL}/api/federated/run-update", json={"confirm": True, "rounds": 1})
    record_result(
        "3. Federated Learning", "District Officer rejected from triggering federated update",
        "HTTP 403 Forbidden",
        f"HTTP {r_fed_officer.status_code}",
        r_fed_officer.status_code == 403
    )

    # 3.3 Confirmation required: unconfirmed request rejected with 400
    r_unconf = s_admin.post(f"{BASE_URL}/api/federated/run-update", json={"confirm": False, "rounds": 1})
    record_result(
        "3. Federated Learning", "Unconfirmed federated update rejected with 400 Bad Request",
        "HTTP 400 Bad Request",
        f"HTTP {r_unconf.status_code}",
        r_unconf.status_code == 400
    )

    # 3.4 National Admin successfully executes sample-weighted FedAvg update
    prev_ver = data_fed.get("active_model_version", "v2.4-FedAvg")
    r_fed_run = s_admin.post(f"{BASE_URL}/api/federated/run-update", json={
        "confirm": True,
        "rounds": 1,
        "notes": "Automated verification federated aggregation round"
    })
    data_fed_run = r_fed_run.json() if r_fed_run.status_code == 200 else {}
    new_ver = data_fed_run.get("new_model_version")
    has_proofs = "aggregation_details" in data_fed_run and "mathematical_proof" in data_fed_run
    record_result(
        "3. Federated Learning", "National Admin executes sample-weighted FedAvg round",
        "HTTP 200, version incremented, mathematical formulation present",
        f"HTTP {r_fed_run.status_code} new_ver: {new_ver} (prior: {prev_ver}), proofs: {has_proofs}",
        r_fed_run.status_code == 200 and new_ver is not None and has_proofs
    )

    # 3.5 Federated update event recorded in immutable audit log
    r_audit = s_admin.get(f"{BASE_URL}/api/audit-logs")
    audit_logs = r_audit.json().get("audit_logs", []) if r_audit.status_code == 200 else []
    has_fed_audit = any(l.get("action") == "FEDERATED_MODEL_ROUND" for l in audit_logs)
    record_result(
        "3. Federated Learning", "Federated update operation recorded in audit ledger",
        "Audit log contains FEDERATED_MODEL_ROUND action",
        f"Found: {has_fed_audit}",
        has_fed_audit
    )

    # =========================================================================
    # 4. MODEL EVALUATION BACKTEST & ACCURACY DRIFT
    # =========================================================================
    print(f"\n{BOLD}--- 4. MODEL EVALUATION & BACKTEST ---{RESET}")

    # 4.1 Non-admins rejected from running model evaluation
    r_eval_staff = s_staff.post(f"{BASE_URL}/api/pilot/evaluate", json={"test_days": 7})
    record_result(
        "4. Model Evaluation", "PHC Staff rejected from running model evaluation",
        "HTTP 403 Forbidden",
        f"HTTP {r_eval_staff.status_code}",
        r_eval_staff.status_code == 403
    )

    # 4.2 National Admin runs retrospective model evaluation
    r_eval = s_admin.post(f"{BASE_URL}/api/pilot/evaluate", json={"test_days": 7})
    data_eval = r_eval.json() if r_eval.status_code == 200 else {}
    mae = data_eval.get("mean_absolute_error")
    rmse = data_eval.get("root_mean_squared_error")
    comp = data_eval.get("comparison_against_prior")
    valid_math = False
    if mae is not None and rmse is not None:
        valid_math = (mae >= 0) and (rmse >= 0) and (rmse >= mae - 0.001)
    record_result(
        "4. Model Evaluation", "Model backtest returns valid MAE, RMSE and comparison status",
        "HTTP 200, non-negative MAE/RMSE, RMSE >= MAE",
        f"HTTP {r_eval.status_code} MAE: {mae}, RMSE: {rmse}, Comp: {comp}, Math Valid: {valid_math}",
        r_eval.status_code == 200 and valid_math and comp in ["IMPROVED", "UNCHANGED", "DECLINED"]
    )

    # =========================================================================
    # 5. SECURITY & SYSTEM ADMINISTRATION (ZERO SECRET LEAKAGE)
    # =========================================================================
    print(f"\n{BOLD}--- 5. SECURITY & SYSTEM ADMINISTRATION (ZERO SECRETS) ---{RESET}")

    # 5.1 Non-admins rejected from security status
    r_sec_officer = s_officer.get(f"{BASE_URL}/api/admin/security-status")
    record_result(
        "5. Security Administration", "District Officer rejected from security status",
        "HTTP 403 Forbidden",
        f"HTTP {r_sec_officer.status_code}",
        r_sec_officer.status_code == 403
    )

    # 5.2 National Admin accesses security telemetry
    r_sec = s_admin.get(f"{BASE_URL}/api/admin/security-status")
    data_sec = r_sec.json() if r_sec.status_code == 200 else {}
    has_sec_components = all(k in data_sec for k in ["auth_subsystem", "rbac_subsystem", "cryptography", "audit_and_privacy"])
    record_result(
        "5. Security Administration", "National Admin retrieves complete security subsystem telemetry",
        "HTTP 200 with auth, rbac, cryptography, audit_and_privacy",
        f"HTTP {r_sec.status_code} components present: {has_sec_components}",
        r_sec.status_code == 200 and has_sec_components
    )

    # 5.3 STRICT ZERO SECRETS CHECK: Verify no secrets, keys, or hashes are exposed
    sec_dump = str(data_sec).lower()
    suspicious_patterns = ["password_hash", "argon2", "pbkdf2", "private_key", "secret_key", "bearer ", "token_secret"]
    exposed = [p for p in suspicious_patterns if p in sec_dump]
    record_result(
        "5. Security Administration", "Strict zero-secret guarantee verified in security payload",
        "0 exposed secret tokens, keys, or password hashes",
        f"Exposed findings: {exposed}",
        len(exposed) == 0
    )

    # =========================================================================
    # 6. MEDICINE BATCH PROVENANCE LEDGER
    # =========================================================================
    print(f"\n{BOLD}--- 6. MEDICINE BATCH PROVENANCE LEDGER ---{RESET}")

    # 6.1 Authorized provenance retrieval across roles (Staff assigned, Officer in-district, Admin nationwide)
    # 1. PHC Staff accessing their assigned PHC batch
    r_prov = s_staff.get(f"{BASE_URL}/api/provenance/batch/BATCH-ORS-2026-A1?phc_id=PHC-001")
    data_prov = r_prov.json() if r_prov.status_code == 200 else {}
    has_prov_meta = "batch_metadata" in data_prov and "transaction_history" in data_prov and "ledger_checksum" in data_prov
    # 3. District Officer accessing a batch in their district
    r_prov_dist = s_officer.get(f"{BASE_URL}/api/provenance/batch/BATCH-ORS-2026-B8")
    # 5. National Admin accessing an existing batch
    r_prov_admin = s_admin.get(f"{BASE_URL}/api/provenance/batch/BATCH-ORS-2026-S1")
    all_authorized = (
        r_prov.status_code == 200
        and has_prov_meta
        and data_prov.get("integrity_status") == "VERIFIED_AUTHENTIC"
        and r_prov_dist.status_code == 200
        and r_prov_admin.status_code == 200
    )
    record_result(
        "6. Batch Provenance", "Authorized role access to verified batch provenance (Staff assigned, Officer in-district, Admin nationwide)",
        "HTTP 200 with batch_metadata, transaction_history, and SHA-256 checksum across authorized roles",
        f"Staff:{r_prov.status_code}, Officer:{r_prov_dist.status_code}, Admin:{r_prov_admin.status_code}",
        all_authorized
    )

    # 6.2 Facility & district isolation and query manipulation rejection
    # 2. PHC Staff accessing another PHC's batch
    r_prov_other_phc = s_staff.get(f"{BASE_URL}/api/provenance/batch/BATCH-ORS-2026-B8")
    # 4. District Officer accessing another district's batch
    r_prov_other_dist = s_officer.get(f"{BASE_URL}/api/provenance/batch/BATCH-ORS-2026-S1")
    # 6. Direct URL/query manipulation (PHC Staff querying unassigned facility)
    r_prov_bad = s_staff.get(f"{BASE_URL}/api/provenance/batch/BATCH-ORS-2026-A1?phc_id=PHC-003")
    all_forbidden = (
        r_prov_other_phc.status_code == 403
        and r_prov_other_dist.status_code == 403
        and r_prov_bad.status_code == 403
    )
    record_result(
        "6. Batch Provenance", "PHC Staff & District Officer rejected from out-of-scope batch & query manipulation",
        "HTTP 403 Forbidden across cross-PHC, cross-District, and query parameter manipulation",
        f"CrossPHC:{r_prov_other_phc.status_code}, CrossDistrict:{r_prov_other_dist.status_code}, QueryManip:{r_prov_bad.status_code}",
        all_forbidden
    )

    # =========================================================================
    # 7. STANDARDS-COMPATIBLE EXPORT (HL7 FHIR R4)
    # =========================================================================
    print(f"\n{BOLD}--- 7. STANDARDS-COMPATIBLE EXPORT (HL7 FHIR R4) ---{RESET}")

    # 7.1 Non-admins rejected from FHIR export
    r_fhir_staff = s_staff.get(f"{BASE_URL}/api/fhir/export")
    record_result(
        "7. Standards-Compatible Export", "PHC Staff rejected from generating FHIR bundle export",
        "HTTP 403 Forbidden",
        f"HTTP {r_fhir_staff.status_code}",
        r_fhir_staff.status_code == 403
    )

    # 7.2 National Admin generates HL7 FHIR R4 Bundle
    r_fhir = s_admin.get(f"{BASE_URL}/api/fhir/export")
    data_fhir = r_fhir.json() if r_fhir.status_code == 200 else {}
    is_fhir_bundle = data_fhir.get("resourceType") == "Bundle" and data_fhir.get("type") == "searchset"
    entries = data_fhir.get("entry", [])
    has_med_statements = any(e.get("resource", {}).get("resourceType") == "MedicationStatement" for e in entries)
    has_locations = any(e.get("resource", {}).get("resourceType") == "Location" for e in entries)
    record_result(
        "7. Standards-Compatible Export", "National Admin generates valid HL7 FHIR R4 bundle with MedicationStatement & Location",
        "HTTP 200, resourceType=Bundle, entries contains MedicationStatement and Location",
        f"HTTP {r_fhir.status_code} bundle: {is_fhir_bundle}, entries: {len(entries)}, MedStatements: {has_med_statements}, Locations: {has_locations}",
        r_fhir.status_code == 200 and is_fhir_bundle and has_med_statements and has_locations
    )

    # 7.3 Demonstration compliance disclosure present
    compliance_notice = data_fhir.get("meridian_compliance_notice", "")
    has_demo_notice = "FHIR-Compatible Demo Export" in compliance_notice
    record_result(
        "7. Standards-Compatible Export", "FHIR export contains demonstration disclosure notice",
        "meridian_compliance_notice contains 'FHIR-Compatible Demo Export'",
        f"Notice: '{compliance_notice}'",
        has_demo_notice
    )

    # 7.4 FHIR export logged in audit ledger
    r_audit2 = s_admin.get(f"{BASE_URL}/api/audit-logs")
    audit_logs2 = r_audit2.json().get("audit_logs", []) if r_audit2.status_code == 200 else []
    has_fhir_audit = any(l.get("action") == "FHIR_R4_BUNDLE_EXPORT" for l in audit_logs2)
    record_result(
        "7. Standards-Compatible Export", "FHIR export event recorded in audit ledger",
        "Audit log contains FHIR_R4_BUNDLE_EXPORT action",
        f"Found: {has_fhir_audit}",
        has_fhir_audit
    )

    # =========================================================================
    # SUMMARY & VERIFICATION
    # =========================================================================
    total = len(test_results)
    passed = sum(1 for t in test_results if t["pass"])
    failed = total - passed

    print(f"\n{BOLD}=================================================================={RESET}")
    print(f"{BOLD}STAGE 4 TEST SUITE EXECUTION SUMMARY{RESET}")
    print(f"{BOLD}=================================================================={RESET}")
    print(f"Total Tests Run: {total}")
    print(f"Passed: {GREEN}{passed}{RESET}")
    print(f"Failed: {RED}{failed}{RESET}")
    rate = (passed / total) * 100
    print(f"Pass Rate: {GREEN if failed == 0 else RED}{rate:.1f}%{RESET}\n")

    return failed == 0

if __name__ == "__main__":
    success = run_stage4_tests()
    sys.exit(0 if success else 1)
