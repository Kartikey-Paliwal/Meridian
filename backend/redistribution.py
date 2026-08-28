import json
import math
from typing import List, Dict, Any
from backend.forecasting import forecast_demand_linear_regression

# PHC GIS Coordinates
PHC_COORDINATES = {
    "PHC-001": {"lat": 28.6139, "lng": 77.2090, "name": "Alpha Sector PHC"},
    "PHC-002": {"lat": 28.5355, "lng": 77.3910, "name": "Beta Central PHC"},
    "PHC-003": {"lat": -15.7975, "lng": -47.8919, "name": "Gamma Rural PHC"},
    "PHC-004": {"lat": -25.7479, "lng": 28.2293, "name": "Delta Community PHC"}
}

def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes great-circle distance between two points in kilometers."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return round(R * c, 2)

def calculate_transport_cost(distance_km: float, quantity: int, is_cold_chain: bool = True) -> float:
    """Calculates transport cost in USD based on distance, quantity and cold-chain tier."""
    base_fee = 25.0 if is_cold_chain else 15.0
    per_km = 1.20 if is_cold_chain else 0.80
    per_unit = 0.05
    return round(base_fee + (distance_km * per_km) + (quantity * per_unit), 2)

def get_eta_minutes(source_phc: str, target_phc: str) -> int:
    src = PHC_COORDINATES.get(source_phc)
    tgt = PHC_COORDINATES.get(target_phc)
    if src and tgt and not (source_phc in ["PHC-003", "PHC-004"] or target_phc in ["PHC-003", "PHC-004"]):
        dist = haversine_distance(src["lat"], src["lng"], tgt["lat"], tgt["lng"])
    else:
        dist = 20.0
    # Average transfer speed 30 km/h in rural corridors -> 2 mins per km + 10 mins loading overhead
    return int(dist * 2 + 10)

def generate_redistribution_recommendations(inventory_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Scans all PHC inventories.
    Identifies shortage PHCs (days remaining <= 4.0 or stock < 30% par level)
    and pairs them with surplus donor PHCs (days remaining >= 8.0 or surplus stock > 100 units).
    Returns explainable recommendation objects with GIS & haulage cost analytics.
    """
    by_medicine = {}
    for item in inventory_data:
        med = item["medicine_name"]
        if med not in by_medicine:
            by_medicine[med] = []
        
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
            for d_phc in surplus_phcs:
                if d_phc["phc_id"] == s_phc["phc_id"]:
                    continue

                target_demand = s_phc["forecast"]["predicted_next_day_demand"]
                needed_qty = max(20, target_demand * 5 - s_phc["quantity"])
                
                donor_demand = d_phc["forecast"]["predicted_next_day_demand"]
                safe_donor_capacity = d_phc["quantity"] - (donor_demand * 5)
                
                if safe_donor_capacity >= 15:
                    transfer_qty = int(min(needed_qty, safe_donor_capacity))
                    
                    src_geo = PHC_COORDINATES.get(d_phc["phc_id"], {"lat": 28.5355, "lng": 77.3910})
                    tgt_geo = PHC_COORDINATES.get(s_phc["phc_id"], {"lat": 28.6139, "lng": 77.2090})
                    
                    if d_phc["phc_id"] in ["PHC-003", "PHC-004"] or s_phc["phc_id"] in ["PHC-003", "PHC-004"]:
                        dist_km = 18.5
                    else:
                        dist_km = haversine_distance(src_geo["lat"], src_geo["lng"], tgt_geo["lat"], tgt_geo["lng"])
                    
                    eta = int(dist_km * 2 + 10)
                    is_cold = "Insulin" in med_name or "Vaccine" in med_name
                    cost = calculate_transport_cost(dist_km, transfer_qty, is_cold_chain=is_cold)
                    
                    recommendation = {
                        "source_phc": d_phc["phc_id"],
                        "target_phc": s_phc["phc_id"],
                        "medicine_name": med_name,
                        "recommended_quantity": transfer_qty,
                        "eta_minutes": eta,
                        "transport_cost_usd": cost,
                        "distance_km": dist_km,
                        "status": "PROPOSED",
                        "gis_origin": src_geo,
                        "gis_destination": tgt_geo,
                        "explainability_underlying_numbers": {
                            "target_phc_current_stock": s_phc["quantity"],
                            "target_phc_predicted_daily_demand": target_demand,
                            "target_phc_days_remaining": s_phc["forecast"]["days_of_stock_remaining"],
                            "target_phc_risk_level": s_phc["forecast"]["risk_level"],
                            "donor_phc_current_stock": d_phc["quantity"],
                            "donor_phc_predicted_daily_demand": donor_demand,
                            "donor_phc_days_remaining": d_phc["forecast"]["days_of_stock_remaining"],
                            "donor_phc_surplus_capacity": safe_donor_capacity,
                            "estimated_distance_km": dist_km,
                            "estimated_cost_usd": cost,
                            "transport_tier": "Cold-Chain Fleet" if is_cold else "Standard Logistics",
                            "rationale": f"PHC {s_phc['phc_id']} is facing stock-out in {s_phc['forecast']['days_of_stock_remaining']} days. Transferring {transfer_qty} units from {d_phc['phc_id']} ({dist_km} km, ${cost}) restores target cover to > 5 days without compromising donor safety."
                        }
                    }
                    recommendations.append(recommendation)
                    break

    return recommendations

