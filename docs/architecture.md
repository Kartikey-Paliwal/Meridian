# Meridian Architectural Design & Workflow

Meridian is a 4-layer federated AI platform engineered for national public health resource visibility, demand forecasting, explainable stock redistribution, privacy protection, and cross-border federated learning.

## Four-Layer Network Model

```
+-----------------------------------------------------------------------------------+
|                        LAYER 4: BRICS FEDERATED LAYER                             |
|  [Brazil Node]            [India (Host) Node]           [South Africa Node]       |
|  (Simulated)                                            (Simulated)               |
|                                                                                   |
|           \                       |                       /                       |
|            +----> Encrypted Model Weight Updates (FedAvg) <---+                   |
+-----------------------------------------------------------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------------------+
|                        LAYER 3: NATIONAL PLATFORM                                 |
|  - Command Dashboard & National Stock Rollups                                     |
|  - Privacy Layer (Fernet Field Encryption + SHA-256 Tokens + DP Noise)            |
|  - Global Model Aggregator (np.mean FedAvg Server)                               |
+-----------------------------------------------------------------------------------+
                                    |
                                    v
+-----------------------------------------------------------------------------------+
|                     LAYER 2: DISTRICT AGGREGATION & DECISION                      |
|  - District Stock Heatmap & Par-level Warnings (<30% threshold flag)              |
|  - NumPy Polyfit Demand Forecasting (Slope, Intercept, Days of Cover)            |
|  - Explainable Resource Redistribution Engine (Human-in-the-Loop Approval)         |
+-----------------------------------------------------------------------------------+
                                    ^
                                    | Data Rollup / Sync
+-----------------------------------------------------------------------------------+
|                        LAYER 1: PHC EDGE NODES                                    |
|  - Local Storage (SQLite) & Stock/Bed/Staff/Footfall Logging                      |
|  - Browser Web Speech API Voice-to-Form Data Entry                               |
|  - Local Model Training (NumPy polyfit over local consumption series)             |
+-----------------------------------------------------------------------------------+
```

## Key Modules & Math Specifications

1. **Demand Forecasting Model**:
   - Time series window: 7–14 days daily consumption array.
   - Formula: $\text{slope}, \text{intercept} = \text{np.polyfit}(x, \text{daily\_usage}, 1)$.
   - Next-day prediction: $\hat{y}_{N} = \max(1, \text{round}(\text{slope} \cdot N + \text{intercept}))$.
   - Days of cover remaining: $\frac{\text{Current Stock}}{\hat{y}_{N}}$.

2. **Resource Redistribution Engine**:
   - Scans PHCs where days of cover $\le 3.0$ days or stock $< 30\%$ of par level.
   - Pairs with surplus donor PHCs ($\ge 8.0$ days cover & stock $> 100$ units).
   - Solves transfer quantity $Q_{\text{transfer}} = \min(\text{Target Deficit}, \text{Donor Safe Capacity})$.
   - Human-in-the-Loop requirement: Requires explicitly clicking "Approve" or "Reject" before DB inventory is modified.

3. **Privacy Layer**:
   - Field-level encryption for sensitive PII (`staff_id`, patient info) using `cryptography` Fernet symmetric encryption.
   - Deterministic SHA-256 tokenization (`TOK-XXXX`) for display.
   - Bounded Laplace/Uniform random noise ($\pm 1 \text{ to } \pm 3$) appended to aggregate count queries above PHC level.

4. **Federated Learning (FedAvg)**:
   - 3 local nodes train separate NumPy linear models on local datasets.
   - Local weight vectors $W_i = [m_i, c_i]$ are shared with the aggregator.
   - Global weight vector computed as $W_{\text{global}} = \frac{1}{3} \sum_{i=1}^3 W_i = \text{np.mean}(W_{\text{matrix}}, \text{axis}=0)$.
