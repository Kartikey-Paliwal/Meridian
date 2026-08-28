import numpy as np
from typing import List, Dict, Any

def forecast_demand_linear_regression(daily_usage: List[float], current_stock: int, par_level: int = 100) -> Dict[str, Any]:
    """
    Forecasting function: linear regression over last 7-14 days of consumption to predict next-day demand.
    Formula specified in blueprint: slope, intercept = np.polyfit(x, daily_usage, 1)
    """
    if not daily_usage or len(daily_usage) == 0:
        daily_usage = [5] * 7  # Fallback default

    usage_arr = np.array(daily_usage, dtype=float)
    N = len(usage_arr)
    x = np.arange(N)

    # Calculate slope and intercept using NumPy linear regression
    if N > 1 and np.var(x) > 0:
        slope, intercept = np.polyfit(x, usage_arr, 1)
    else:
        slope = 0.0
        intercept = float(usage_arr[0])

    # Next day index is N
    next_day_index = N
    raw_predicted = slope * next_day_index + intercept
    predicted_demand = max(1, int(round(raw_predicted))) # ensure >= 1 to prevent div by zero

    # Average daily usage over window
    avg_daily_usage = float(np.mean(usage_arr))

    # Days of stock remaining based on predicted demand
    days_remaining = round(float(current_stock) / float(predicted_demand), 1)

    # Risk score calculation (0 - 100%)
    # If days remaining <= 3 days, risk is critical (> 70%)
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

    # Par level ratio check (< 30% of par level)
    par_level_ratio = round((current_stock / float(par_level)) * 100, 1) if par_level > 0 else 100.0
    below_par_flag = par_level_ratio < 30.0

    # Calculate suggested reorder quantity (aims for 10-day buffer)
    suggested_reorder_qty = max(50, (predicted_demand * 10) - current_stock)

    # Plain-language Operational Directives for Health Centre Staff
    if risk_level == "CRITICAL":
        action_directive = f"🚨 CRITICAL ACTION REQUIRED: Stock will deplete in {days_remaining} days. Issue emergency warehouse requisition for {suggested_reorder_qty} units or trigger inter-PHC stock transfer immediately."
        urgency_code = "CRITICAL_REACTION"
    elif risk_level == "HIGH":
        action_directive = f"⚠️ WARNING: Stock level is low. Place standard reorder requisition of {suggested_reorder_qty} units within 24 hours."
        urgency_code = "WARNING_REORDER"
    elif risk_level == "MODERATE":
        action_directive = f"⚡ WATCH LIST: Stock cover is moderate ({days_remaining} days remaining). Monitor daily consumption trend."
        urgency_code = "MONITOR_TREND"
    else:
        action_directive = f"🟢 HEALTHY: Ample inventory cover ({days_remaining} days remaining). No immediate staff reorder required."
        urgency_code = "OPTIMAL_SAFE"

    # 7-Day Stock Depletion Forward Projection Timeline
    depletion_timeline = []
    running_stock = float(current_stock)
    for day_step in range(1, 8):
        future_idx = N + day_step - 1
        future_pred = max(1, int(round(slope * future_idx + intercept)))
        running_stock = running_stock - future_pred
        bal = max(0, int(round(running_stock)))
        depletion_timeline.append({
            "day_step": day_step,
            "day_label": f"Day {day_step}",
            "projected_demand": future_pred,
            "projected_balance": bal,
            "is_critical_depletion": bal <= int(par_level * 0.2)
        })

    return {
        "current_stock": current_stock,
        "par_level": par_level,
        "par_level_ratio_pct": par_level_ratio,
        "below_30pct_par_flag": below_par_flag,
        "predicted_next_day_demand": predicted_demand,
        "days_of_stock_remaining": days_remaining,
        "stock_out_risk_score": risk_score,
        "risk_level": risk_level,
        "urgency_code": urgency_code,
        "suggested_reorder_qty": suggested_reorder_qty,
        "staff_action_directive": action_directive,
        "depletion_timeline": depletion_timeline,
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
