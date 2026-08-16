import numpy as np
import json

def train_local_model_phc3():
    """Local model training for PHC Node 3 (Gamma Rural). Data never leaves the node."""
    # Synthetic local usage history for PHC 3 over 14 days
    daily_usage = [15, 16, 17, 19, 20, 22, 23, 25, 26, 28, 30, 31, 33, 35]
    x = np.arange(len(daily_usage))
    
    # Train local linear model: y = slope * x + intercept
    slope, intercept = np.polyfit(x, daily_usage, 1)
    
    weights = [float(slope), float(intercept)]
    print(f"[PHC Node 3 - Gamma] Local model trained: slope={weights[0]:.4f}, intercept={weights[1]:.4f}")
    return {
        "node_id": "PHC-003 (Gamma / Brazil Simulated)",
        "samples_count": len(daily_usage),
        "weights": weights,
        "raw_data_kept_private": True
    }

if __name__ == "__main__":
    result = train_local_model_phc3()
    print(json.dumps(result, indent=2))
