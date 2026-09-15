import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import requests
from backend.privacy import encrypt_field, decrypt_field, tokenize_identifier, add_dp_noise
from backend.forecasting import forecast_demand_linear_regression
from backend.auth import authenticate_user
from backend.fhir_adapter import convert_to_fhir_medication_statement
from backend.provenance import verify_medicine_batch
from ai.fed_avg import run_federated_averaging

BASE_URL = "http://127.0.0.1:8000"

def test_api_health_and_inventory():
    s = requests.Session()
    r_login = s.post(f"{BASE_URL}/api/auth/login", json={"username": "staff.alpha@meridian.health", "password": "Staff@123"})
    assert r_login.status_code == 200, f"Login failed: {r_login.text}"
    response = s.get(f"{BASE_URL}/api/inventory")
    assert response.status_code == 200, f"Inventory failed: {response.text}"
    assert isinstance(response.json(), list)
    print("  [PASS] 1. API Health & Inventory test passed")

def test_forecasting_calculation():
    usage = [10, 12, 14, 16, 18, 20, 22]
    res = forecast_demand_linear_regression(usage, current_stock=50)
    assert res["predicted_next_day_demand"] > 0
    assert "explainability" in res
    print("  [PASS] 2. Forecasting Calculation test passed")

def test_privacy_encryption():
    raw = "STF-TEST-99"
    encrypted = encrypt_field(raw)
    decrypted = decrypt_field(encrypted)
    assert decrypted == raw
    assert tokenize_identifier(raw).startswith("TOK-")
    print("  [PASS] 3. Privacy Encryption test passed")

def test_dp_noise():
    res = add_dp_noise(100)
    assert "noised_count" in res
    assert abs(res["noise_added"]) <= 3
    print("  [PASS] 4. Differential Privacy Noise test passed")

def test_fed_avg():
    res = run_federated_averaging()
    assert res["num_nodes"] == 3
    assert "global_model" in res
    print("  [PASS] 5. Federated Averaging test passed")

def test_auth_login():
    res = authenticate_user("staff.alpha@meridian.health", "Staff@123")
    assert res is not None
    assert res["user"]["role"] == "PHC_STAFF"
    print("  [PASS] 6. Authentication Login test passed")

def test_fhir_conversion():
    item = {"phc_id": "PHC-001", "medicine_name": "ORS Packets", "quantity": 100}
    fhir = convert_to_fhir_medication_statement(item)
    assert fhir["resourceType"] == "MedicationStatement"
    print("  [PASS] 7. FHIR Conversion test passed")

def test_provenance_verification():
    res = verify_medicine_batch("BATCH-ORS-2026-A1")
    assert res["status"] == "VERIFIED_AUTHENTIC"
    print("  [PASS] 8. Provenance Verification test passed")

if __name__ == "__main__":
    print("=================================================================")
    print("RUNNING MERIDIAN CORE COMPONENT TESTS")
    print("=================================================================")
    test_api_health_and_inventory()
    test_forecasting_calculation()
    test_privacy_encryption()
    test_dp_noise()
    test_fed_avg()
    test_auth_login()
    test_fhir_conversion()
    test_provenance_verification()
    print("=================================================================")
    print("ALL CORE TESTS PASSED SUCCESSFULLY!")
    print("=================================================================")
