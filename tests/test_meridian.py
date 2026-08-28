import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.privacy import encrypt_field, decrypt_field, tokenize_identifier, add_dp_noise
from backend.forecasting import forecast_demand_linear_regression
from backend.auth import authenticate_user
from backend.fhir_adapter import convert_to_fhir_medication_statement
from backend.provenance import verify_medicine_batch
from ai.fed_avg import run_federated_averaging

client = TestClient(app)

def test_api_health_and_inventory():
    response = client.get("/api/inventory?phc_id=PHC-001")
    assert response.status_code == 200
    assert isinstance(response.json(), list)

def test_forecasting_calculation():
    usage = [10, 12, 14, 16, 18, 20, 22]
    res = forecast_demand_linear_regression(usage, current_stock=50)
    assert res["predicted_next_day_demand"] > 0
    assert "explainability" in res

def test_privacy_encryption():
    raw = "STF-TEST-99"
    encrypted = encrypt_field(raw)
    decrypted = decrypt_field(encrypted)
    assert decrypted == raw
    assert tokenize_identifier(raw).startswith("TOK-")

def test_dp_noise():
    res = add_dp_noise(100)
    assert "noised_count" in res
    assert abs(res["noise_added"]) <= 3

def test_fed_avg():
    res = run_federated_averaging()
    assert res["num_nodes"] == 3
    assert "global_model" in res

def test_auth_login():
    res = authenticate_user("phc_nurse", "nurse123")
    assert res is not None
    assert res["role"] == "PHC_STAFF"

def test_fhir_conversion():
    item = {"phc_id": "PHC-001", "medicine_name": "ORS Packets", "quantity": 100}
    fhir = convert_to_fhir_medication_statement(item)
    assert fhir["resourceType"] == "MedicationStatement"

def test_provenance_verification():
    res = verify_medicine_batch("BATCH-ORS-2026-A1")
    assert res["status"] == "VERIFIED_AUTHENTIC"
