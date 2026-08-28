import numpy as np
import math
from typing import List, Dict, Any
from backend.forecasting import forecast_demand_linear_regression

def run_30day_shadow_simulation() -> Dict[str, Any]:
    """
    Simulates 30 days of real-world PHC medicine usage and compares predicted demand 
    vs actual ground-truth consumption to calculate Mean Absolute Error (MAE) 
    and Root Mean Square Error (RMSE).
    """
    np.random.seed(42) # Repeatable seed
    days = 30
    
    # Ground truth actual daily usage with a trend + Gaussian noise
    base_demand = 20
    trend = 1.2
    actual_usage = [int(max(5, base_demand + i * trend + np.random.normal(0, 3))) for i in range(days)]

    predictions = []
    errors = []

    # Run rolling window prediction for days 7 to 30
    for t in range(7, days):
        historical_window = actual_usage[:t]
        fc = forecast_demand_linear_regression(historical_window, current_stock=200)
        pred = fc["predicted_next_day_demand"]
        actual = actual_usage[t]
        
        predictions.append({
            "day": t + 1,
            "actual_consumption": actual,
            "predicted_demand": pred,
            "error": abs(actual - pred)
        })
        errors.append(actual - pred)

    abs_errors = [abs(e) for e in errors]
    mae = round(float(np.mean(abs_errors)), 2)
    rmse = round(float(np.sqrt(np.mean([e**2 for e in errors]))), 2)
    accuracy_pct = round(max(0, 100 - (mae / float(np.mean(actual_usage))) * 100), 1)

    return {
        "status": "COMPLETED",
        "simulation_duration_days": days,
        "evaluated_window_days": len(predictions),
        "mean_absolute_error_mae": mae,
        "root_mean_square_error_rmse": rmse,
        "forecast_accuracy_score_pct": accuracy_pct,
        "shadow_telemetry": predictions,
        "summary": f"30-Day Shadow Simulation completed across evaluated window. Forecast MAE = {mae} units, RMSE = {rmse} units ({accuracy_pct}% backtest accuracy)."
    }
