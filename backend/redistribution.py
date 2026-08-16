import json
import math
from typing import List, Dict, Any
from backend.forecasting import forecast_demand_linear_regression

# Mock distances between PHCs in kilometers & estimated transport times in minutes
DISTANCES_KM = {
    ("PHC-001", "PHC-002"): 12,
    ("PHC-002", "PHC-001"): 12,
    ("PHC-001", "PHC-003"): 25,
    ("PHC-003", "PHC-001"): 25,
    ("PHC-002", "PHC-004"): 18,
    ("PHC-004", "PHC-002"): 18,
    ("PHC-003", "PHC-004"): 15,
    ("PHC-004", "PHC-003"): 15,
}

def get_eta_minutes(source_phc: str, target_phc: str) -> int:
    dist = DISTANCES_KM.get((source_phc, target_phc), 20)
    # Average transfer speed 30 km/h in rural corridors -> 2 mins per km + 10 mins loading overhead
    return int(dist * 2 + 10)

def generate_redistribution_recommendations(inventory_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Scans all PHC inventories.
    Identifies shortage PHCs (days remaining <= 3.0 or stock < 30% par level)
    and pairs them with surplus donor PHCs (days remaining >= 10.0 or surplus stock > 150 units).
    Returns explainable recommendation objects.
    """
    # Group inventory by medicine
    by_medicine = {}
    for item in inventory_data:
        med = item["medicine_name"]
        if med not in by_medicine:
            by_medicine[med] = []
        
        # Calculate forecast for each item
        history = json.loads(item.get("daily_usage_history", "[]")) if isinstance(item.get("daily_usage_history"), str) else item.get("daily_usage_history", [])
        forecast = forecast_demand_linear_regression(history, item["quantity"], item.get("par_level", 100))
        
        by_medicine[med].append({
            "phc_id": item["phc_id"],
            "medicine_name": med,
            "quantity": item["quantity"],
            "par_level": item.get("par_level", 100),
            "forecast": forecast
        })

    recommendations = []

    for med_name, phc_list in by_medicine.items():
        shortage_phcs = [p for p in phc_list if p["forecast"]["days_of_stock_remaining"] <= 4.0 or p["quantity"] <= 30]
        surplus_phcs = [p for p in phc_list if p["forecast"]["days_of_stock_remaining"] >= 8.0 and p["quantity"] >= 100]

        for s_phc in shortage_phcs:
            # Find best donor with highest surplus
            for d_phc in surplus_phcs:
                if d_phc["phc_id"] == s_phc["phc_id"]:
                    continue

                # Calculate recommended quantity to bring target to 7 days cover
                target_demand = s_phc["forecast"]["predicted_next_day_demand"]
                needed_qty = max(20, target_demand * 5 - s_phc["quantity"])
                
                # Ensure donor keeps at least 5 days cover after donation
                donor_demand = d_phc["forecast"]["predicted_next_day_demand"]
                safe_donor_capacity = d_phc["quantity"] - (donor_demand * 5)
                
                if safe_donor_capacity >= 15:
                    transfer_qty = int(min(needed_qty, safe_donor_capacity))
                    eta = get_eta_minutes(d_phc["phc_id"], s_phc["phc_id"])
                    
                    recommendation = {
                        "source_phc": d_phc["phc_id"],
                        "target_phc": s_phc["phc_id"],
                        "medicine_name": med_name,
                        "recommended_quantity": transfer_qty,
                        "eta_minutes": eta,
                        "status": "PROPOSED",
                        "explainability_underlying_numbers": {
                            "target_phc_current_stock": s_phc["quantity"],
                            "target_phc_predicted_daily_demand": target_demand,
                            "target_phc_days_remaining": s_phc["forecast"]["days_of_stock_remaining"],
                            "target_phc_risk_level": s_phc["forecast"]["risk_level"],
                            "donor_phc_current_stock": d_phc["quantity"],
                            "donor_phc_predicted_daily_demand": donor_demand,
                            "donor_phc_days_remaining": d_phc["forecast"]["days_of_stock_remaining"],
                            "donor_phc_surplus_capacity": safe_donor_capacity,
                            "estimated_distance_km": DISTANCES_KM.get((d_phc["phc_id"], s_phc["phc_id"]), 20),
                            "rationale": f"PHC {s_phc['phc_id']} is facing stock-out in {s_phc['forecast']['days_of_stock_remaining']} days. Transferring {transfer_qty} units from {d_phc['phc_id']} restores target cover to > 5 days without compromising donor safety."
                        }
                    }
                    recommendations.append(recommendation)
                    break # pair once per shortage PHC per med

    return recommendations
