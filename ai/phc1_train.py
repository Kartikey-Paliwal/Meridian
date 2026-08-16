import numpy as np
import json

def train_local_model_phc1():
    """Local model training for PHC Node 1 (Alpha Sector). Data never leaves the node."""
    # Synthetic local usage history for PHC 1 over 14 days
    daily_usage = [12, 14, 15, 18, 22, 28, 35, 40, 42, 45, 48, 52, 55, 60]
    x = np.arange(len(daily_usage))
    
    # Train local linear model: y = slope * x + intercept
    slope, intercept = np.polyfit(x, daily_usage, 1)
    
    weights = [float(slope), float(intercept)]
    print(f"[PHC Node 1 - Alpha] Local model trained: slope={weights[0]:.4f}, intercept={weights[1]:.4f}")
    return {
        "node_id": "PHC-001 (Alpha)",
        "samples_count": len(daily_usage),
        "weights": weights,
        "raw_data_kept_private": True
    }

if __name__ == "__main__":
    result = train_local_model_phc1()
    print(json.dumps(result, indent=2))
