import numpy as np
import json
from ai.phc1_train import train_local_model_phc1
from ai.phc2_train import train_local_model_phc2
from ai.phc3_train import train_local_model_phc3

def run_federated_averaging():
    """
    Executes 3 local model training passes, extracts encrypted weight vectors,
    and runs Federated Averaging (FedAvg) using np.mean.
    """
    node1 = train_local_model_phc1()
    node2 = train_local_model_phc2()
    node3 = train_local_model_phc3()

    local_models = [node1, node2, node3]
    weight_list = [n["weights"] for n in local_models]
    
    # Federated Averaging across local model weights: np.mean(weight_list, axis=0)
    weight_matrix = np.array(weight_list)
    global_weights = np.mean(weight_matrix, axis=0)
    global_slope = float(global_weights[0])
    global_intercept = float(global_weights[1])

    # Proof of arithmetic calculation details
    slopes = [w[0] for w in weight_list]
    intercepts = [w[1] for w in weight_list]

    print("\n" + "="*60)
    print("FEDERATED LEARNING DEMO (FedAvg)")
    print("="*60)
    for idx, n in enumerate(local_models, 1):
        print(f"Node {idx} [{n['node_id']}]: Slope = {n['weights'][0]:.4f}, Intercept = {n['weights'][1]:.4f}")
    print("-" * 60)
    print(f"Global Model (Averaged): Slope = {global_slope:.4f}, Intercept = {global_intercept:.4f}")
    print(f"Arithmetic Verification: Slope Mean = ({' + '.join(f'{s:.4f}' for s in slopes)}) / 3 = {global_slope:.4f}")
    print(f"Arithmetic Verification: Intercept Mean = ({' + '.join(f'{i:.4f}' for i in intercepts)}) / 3 = {global_intercept:.4f}")
    print("="*60 + "\n")

    return {
        "algorithm": "Federated Averaging (FedAvg)",
        "num_nodes": 3,
        "local_nodes": local_models,
        "global_model": {
            "slope_m": round(global_slope, 4),
            "intercept_c": round(global_intercept, 4),
            "weights": [round(global_slope, 4), round(global_intercept, 4)],
            "formula": f"y = {round(global_slope, 4)} * x + {round(global_intercept, 4)}"
        },
        "arithmetic_proof": {
            "slopes": [round(s, 4) for s in slopes],
            "intercepts": [round(i, 4) for i in intercepts],
            "slope_sum": round(float(sum(slopes)), 4),
            "intercept_sum": round(float(sum(intercepts)), 4),
            "formula_proof": f"Global Slope = {sum(slopes):.4f} / 3 = {global_slope:.4f}; Global Intercept = {sum(intercepts):.4f} / 3 = {global_intercept:.4f}"
        }
    }

if __name__ == "__main__":
    run_federated_averaging()
