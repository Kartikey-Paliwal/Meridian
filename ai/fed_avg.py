import numpy as np
import json
from datetime import datetime
from ai.phc1_train import train_local_model_phc1
from ai.phc2_train import train_local_model_phc2
from ai.phc3_train import train_local_model_phc3

def run_federated_averaging(new_version: str = "v2.5-FedAvg"):
    """
    Executes local model training on private node datasets without transmitting raw operational records.
    Collects only local weight vectors and sample sizes, then computes sample-weighted Federated Averaging (FedAvg).
    Clearly labeled as a Federated Learning Demonstration.
    """
    start_time = datetime.now()

    # 1. Decentralized local node execution (Raw data never leaves facility)
    node1 = train_local_model_phc1()
    node2 = train_local_model_phc2()
    node3 = train_local_model_phc3()

    local_models = [node1, node2, node3]
    
    # 2. Weighted Aggregation based on local valid training sample counts
    total_samples = sum(n.get("samples_count", 1) for n in local_models)
    
    weighted_slopes = []
    weighted_intercepts = []
    node_summaries = []

    for n in local_models:
        n_samples = n.get("samples_count", 1)
        w_factor = n_samples / float(total_samples) if total_samples > 0 else (1.0 / len(local_models))
        slope = float(n["weights"][0])
        intercept = float(n["weights"][1])
        
        weighted_slopes.append(slope * w_factor)
        weighted_intercepts.append(intercept * w_factor)

        node_summaries.append({
            "node_id": n["node_id"],
            "status": "SUCCESS",
            "samples_count": n_samples,
            "sample_weight_pct": round(w_factor * 100, 1),
            "local_slope": round(slope, 4),
            "local_intercept": round(intercept, 4),
            "raw_records_shared": False
        })

    global_slope = float(sum(weighted_slopes))
    global_intercept = float(sum(weighted_intercepts))
    completion_time = datetime.now()

    # Proof formatting
    proof_slope_str = " + ".join([f"({n['local_slope']} * {n['sample_weight_pct']}%)" for n in node_summaries])
    proof_intercept_str = " + ".join([f"({n['local_intercept']} * {n['sample_weight_pct']}%)" for n in node_summaries])

    tech_details = {
        "aggregation_formula": "Global_Param = Sum(Weight_i * Param_i)",
        "slope_weighted_math": f"Global Slope = {proof_slope_str} = {global_slope:.4f}",
        "intercept_weighted_math": f"Global Intercept = {proof_intercept_str} = {global_intercept:.4f}",
        "sample_counts": {n["node_id"]: n["samples_count"] for n in node_summaries}
    }

    aggregation_details = {
        "method": "Sample-Weighted FedAvg (w_i = n_i / N)",
        "participating_nodes_count": len(local_models),
        "total_training_samples": total_samples,
        "raw_phc_records_shared": False,
        "nodes": node_summaries
    }

    math_proof = {
        "formulation": "Global_Param = Sum(w_i * Param_i) where w_i = n_i / N",
        "slope_proof": f"Global Slope = {proof_slope_str} = {global_slope:.4f}",
        "intercept_proof": f"Global Intercept = {proof_intercept_str} = {global_intercept:.4f}",
        "arithmetic_details": tech_details
    }

    return {
        "status": "COMPLETED",
        "algorithm": "Federated Averaging (Weighted FedAvg Demonstration)",
        "demonstration_notice": "Federated Learning Demonstration — NumPy Decentralized Baseline",
        "model_version": new_version,
        "new_model_version": new_version,
        "aggregation_method": "Sample-Weighted FedAvg (w_i = n_i / N)",
        "aggregation_details": aggregation_details,
        "mathematical_proof": math_proof,
        "participating_nodes_count": len(local_models),
        "num_nodes": len(local_models),
        "successful_contributors": len(local_models),
        "failed_contributors": 0,
        "total_training_samples": total_samples,
        "raw_phc_records_shared": False,
        "privacy_guarantee": (
            "Participating PHCs train local forecasting models using their own operational data. "
            "Raw PHC records remain within their authorised scope. Only permitted model updates are sent for aggregation into a shared forecasting model."
        ),
        "start_time": start_time.isoformat(),
        "completion_time": completion_time.isoformat(),
        "duration_ms": round((completion_time - start_time).total_seconds() * 1000, 2),
        "formula": f"y = {round(global_slope, 4)} * x + {round(global_intercept, 4)}",
        "equation": f"y = {round(global_slope, 4)} * x + {round(global_intercept, 4)}",
        "global_model": {
            "slope_m": round(global_slope, 4),
            "intercept_c": round(global_intercept, 4),
            "weights": [round(global_slope, 4), round(global_intercept, 4)],
            "equation": f"y = {round(global_slope, 4)} * x + {round(global_intercept, 4)}",
            "formula": f"y = {round(global_slope, 4)} * x + {round(global_intercept, 4)}",
            "status": "APPROVED_ACTIVE"
        },
        "participating_nodes": node_summaries,
        "technical_details": tech_details
    }

if __name__ == "__main__":
    res = run_federated_averaging()
    print(json.dumps(res, indent=2))
