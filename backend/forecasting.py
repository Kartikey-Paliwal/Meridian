import numpy as np
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

def forecast_demand_linear_regression(
    daily_usage: List[float],
    current_stock: int,
    par_level: int = 100,
    horizon_days: int = 7,
    medicine_name: str = "Medicine",
    global_weights: Optional[List[float]] = None
) -> Dict[str, Any]:
    """
    Transparent Linear Demand Forecasting baseline using NumPy linear regression.
    Evaluates consumption history, projects demand across horizon, calculates safe reorder dates,
    and returns explicit formula math and human-in-the-loop operational directives.
    """
    now = datetime.now()

    # Data sufficiency guard (minimum 3 historical data points required)
    if not daily_usage or len(daily_usage) < 3:
        return {
            "forecast_type": "Linear Demand Forecast",
            "model_source": "Local linear model",
            "status": "INSUFFICIENT_DATA",
            "insufficient_data": True,
            "message": "Insufficient data for a reliable forecast",
            "current_stock": current_stock,
            "par_level": par_level,
            "predicted_next_day_demand": 0,
            "days_of_stock_remaining": 999.0,
            "stock_out_risk_score": 0,
            "risk_level": "UNKNOWN",
            "urgency_code": "INSUFFICIENT_DATA",
            "reliability": "Insufficient data for a reliable forecast",
            "forecast_horizon_days": horizon_days,
            "generated_time": now.isoformat(),
            "explanation": {
                "what": "Demand cannot be reliably estimated due to missing operational data.",
                "why": f"Only {len(daily_usage) if daily_usage else 0} historical records available (minimum 3 required).",
                "recommended_action": "Record daily medicine dispensation to enable automated forecasting.",
                "data_period": f"{len(daily_usage) if daily_usage else 0} days recorded"
            }
        }

    usage_arr = np.array(daily_usage, dtype=float)
    N = len(usage_arr)
    x = np.arange(N)

    # Determine coefficients (Local NumPy polyfit or Global Federated weights)
    used_global = False
    if global_weights and len(global_weights) == 2:
        slope = float(global_weights[0])
        intercept = float(global_weights[1])
        used_global = True
        model_source = "Federated global model"
    else:
        if N > 1 and np.var(x) > 0:
            slope, intercept = np.polyfit(x, usage_arr, 1)
        else:
            slope = 0.0
            intercept = float(usage_arr[0])
        model_source = "Local linear model"

    # Next day prediction
    next_day_index = N
    raw_predicted = slope * next_day_index + intercept
    predicted_demand = max(1, int(round(raw_predicted)))

    # Average daily usage
    avg_daily_usage = round(float(np.mean(usage_arr)), 1)

    # Days of stock remaining
    days_remaining = round(float(current_stock) / float(predicted_demand), 1)

    # Estimated stock-out and reorder dates
    if days_remaining <= 60:
        stockout_dt = now + timedelta(days=days_remaining)
        estimated_stockout_date = stockout_dt.strftime("%Y-%m-%d")
        reorder_dt = max(now, stockout_dt - timedelta(days=3))
        recommended_reorder_date = reorder_dt.strftime("%Y-%m-%d")
    else:
        estimated_stockout_date = "Safe (>60 days)"
        recommended_reorder_date = "Standard cycle"

    # Risk level classification
    if days_remaining <= 1:
        risk_score = 95
        risk_level = "CRITICAL"
    elif days_remaining <= 3:
        risk_score = 75
        risk_level = "HIGH"
    elif days_remaining <= 7:
        risk_score = 40
        risk_level = "MODERATE"
    else:
        risk_score = 10
        risk_level = "LOW"

    par_level_ratio = round((current_stock / float(par_level)) * 100, 1) if par_level > 0 else 100.0
    below_par_flag = par_level_ratio < 30.0

    suggested_reorder_qty = max(50, (predicted_demand * 10) - current_stock)

    # Reliability indicator based on sample window size
    if N >= 14:
        reliability = "High (14-day continuous telemetry)"
    elif N >= 7:
        reliability = "Moderate (7-day operational baseline)"
    else:
        reliability = "Low (Limited historical window)"

    # Horizon demand projection
    depletion_timeline = []
    running_stock = float(current_stock)
    horizon_total_demand = 0

    for day_step in range(1, horizon_days + 1):
        future_idx = N + day_step - 1
        future_pred = max(1, int(round(slope * future_idx + intercept)))
        horizon_total_demand += future_pred
        running_stock = running_stock - future_pred
        bal = max(0, int(round(running_stock)))
        depletion_timeline.append({
            "day_step": day_step,
            "day_label": f"Day {day_step}",
            "projected_demand": future_pred,
            "projected_balance": bal,
            "is_critical_depletion": bal <= int(par_level * 0.2)
        })

    # Plain-language operational directive
    if risk_level == "CRITICAL":
        action_directive = f"{medicine_name} stock may fall below safe level in {int(days_remaining)} days. Average daily consumption increased over the last {N} days. Consider requesting {suggested_reorder_qty} units immediately."
        urgency_code = "CRITICAL_REACTION"
    elif risk_level == "HIGH":
        action_directive = f"{medicine_name} reserves are depleting. Stock will reach critical par in {int(days_remaining)} days. Recommended reorder of {suggested_reorder_qty} units by {recommended_reorder_date}."
        urgency_code = "WARNING_REORDER"
    elif risk_level == "MODERATE":
        action_directive = f"Watch list: {medicine_name} has {days_remaining} days of cover based on {N}-day consumption trends."
        urgency_code = "MONITOR_TREND"
    else:
        action_directive = f"Stock level healthy. {medicine_name} has {days_remaining} days of cover at current consumption rates."
        urgency_code = "OPTIMAL_SAFE"

    return {
        "forecast_type": "Linear Demand Forecast",
        "model_source": model_source,
        "status": "COMPLETED",
        "insufficient_data": False,
        "current_stock": current_stock,
        "par_level": par_level,
        "par_level_ratio_pct": par_level_ratio,
        "below_30pct_par_flag": below_par_flag,
        "predicted_next_day_demand": predicted_demand,
        "expected_demand_horizon": horizon_total_demand,
        "days_of_stock_remaining": days_remaining,
        "estimated_stock_out_date": estimated_stockout_date,
        "recommended_reorder_date": recommended_reorder_date,
        "stock_out_risk_score": risk_score,
        "risk_level": risk_level,
        "urgency_code": urgency_code,
        "suggested_reorder_qty": suggested_reorder_qty,
        "reliability": reliability,
        "forecast_horizon_days": horizon_days,
        "generated_time": now.isoformat(),
        "staff_action_directive": action_directive,
        "depletion_timeline": depletion_timeline,
        "explanation": {
            "what_is_predicted": f"{medicine_name} next-day demand: ~{predicted_demand} units. Total {horizon_days}-day demand: ~{horizon_total_demand} units.",
            "when_it_may_happen": f"Stock depletion estimated around {estimated_stockout_date}.",
            "why_it_is_predicted": f"Linear trend based on {N}-day average of {avg_daily_usage} units/day (slope = {slope:+.2f}).",
            "data_period_used": f"Last {N} days of operational consumption history",
            "recommended_action": f"Request {suggested_reorder_qty} units by {recommended_reorder_date} to prevent stockout.",
            "model_provenance": model_source
        },
        "explainability": {
            "historical_window_days": N,
            "daily_usage_array": daily_usage,
            "linear_model_slope_m": round(float(slope), 4),
            "linear_model_intercept_c": round(float(intercept), 4),
            "formula_used": f"y = {round(float(slope), 4)} * x + {round(float(intercept), 4)}",
            "next_day_prediction_math": f"predicted = max(1, round({round(float(slope), 4)} * {N} + {round(float(intercept), 4)})) = {predicted_demand}",
            "days_cover_math": f"{current_stock} units / {predicted_demand} predicted daily demand = {days_remaining} days"
        }
    }
