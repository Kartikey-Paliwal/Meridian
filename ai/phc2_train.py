import numpy as np
import json

def train_local_model_phc2():
    """Local model training for PHC Node 2 (Beta Central). Data never leaves the node."""
    # Synthetic local usage history for PHC 2 over 14 days
    daily_usage = [10, 8, 9, 11, 10, 9, 10, 12, 11, 10, 9, 8, 10, 11]
    x = np.arange(len(daily_usage))
    
    # Train local linear model: y = slope * x + intercept
    slope, intercept = np.polyfit(x, daily_usage, 1)
    
    weights = [float(slope), float(intercept)]
    print(f"[PHC Node 2 - Beta] Local model trained: slope={weights[0]:.4f}, intercept={weights[1]:.4f}")
    return {
        "node_id": "PHC-002 (Beta)",
        "samples_count": len(daily_usage),
        "weights": weights,
        "raw_data_kept_private": True
    }

if __name__ == "__main__":
    result = train_local_model_phc2()
    print(json.dumps(result, indent=2))
