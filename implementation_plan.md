# Implementation Plan - Meridian Federated AI Health Supply Chain Platform

Meridian is a 4-layer federated AI platform prototype for national health supply chain management. It connects Primary Health Centres (PHCs) to district and national levels with real-time stock/bed/staff visibility, NumPy-based demand forecasting, explainable rule-based resource redistribution with human-in-the-loop approval, Fernet field encryption & differential privacy noise, custom 3-node NumPy FedAvg federated learning, and browser voice input.

## User Review Required

> [!IMPORTANT]
> **Key Architectural Choices & Hackathon MVP Scoping:**
> 1. **Tech Stack**: Backend in FastAPI (Python) + SQLite DB; Frontend in modern vanilla HTML5/CSS3/JavaScript with Chart.js & Web Speech API served directly via FastAPI static files for zero-friction setup.
> 2. **AI & Forecasting**: Uses purely `numpy.polyfit` for linear regression over daily consumption time-series data without external heavy ML frameworks (Torch/TF), keeping execution fast and explainable.
> 3. **Federated Learning**: Standalone Python scripts (`ai/phc1_train.py`, `ai/phc2_train.py`, `ai/phc3_train.py`, `ai/fed_avg.py`) with FastAPI endpoints exposing local model parameters and FedAvg results to the UI.
> 4. **Privacy**: `cryptography` (Fernet) symmetric key encryption for PII/staff identifiers, tokenization for public view, and Laplace/Uniform random noise ($\pm 1 \text{ to } \pm 3$) added to district/national aggregate counts.
> 5. **Human-in-the-Loop**: All automated redistribution recommendations require explicit user "Approve" or "Override/Reject" actions before changing inventory allocations.

---

## Proposed Architecture & File Structure

```
meridian/
├── backend/
│   ├── main.py             # FastAPI application, static mounting, & route handling
│   ├── database.py         # SQLite setup, tables creation, synthetic seed generator
│   ├── models.py           # Pydantic schemas for request/response payloads
│   ├── forecasting.py      # NumPy linear regression, stock-out risk score & math metrics
│   ├── redistribution.py   # Rule-based transfer matching, distance/ETA calculation
│   └── privacy.py          # Fernet field encryption, tokenization & DP noise generator
├── ai/
│   ├── phc1_train.py       # Local training script for PHC Node 1
│   ├── phc2_train.py       # Local training script for PHC Node 2
│   ├── phc3_train.py       # Local training script for PHC Node 3
│   └── fed_avg.py          # Federated averaging (FedAvg) script & aggregator runner
├── frontend/
│   ├── index.html          # Multi-view SPA (PHC Edge, District, National, BRICS, FL Panel)
│   ├── styles.css          # Modern dark-mode health-tech styling with glassmorphism & cards
│   └── app.js             # API integrations, Web Speech API voice entry, Chart.js graphs
├── docs/
│   └── architecture.md     # 4-layer system architecture & data workflow documentation
├── requirements.txt        # Python dependencies (fastapi, uvicorn, numpy, cryptography)
└── README.md               # Quickstart guide & hackathon pitch summary
```

---

## Key Feature Implementation Details

### 1. Database Schema (`backend/database.py`)
- `medicine_inventory`: `(id, phc_id, medicine_name, quantity, par_level, daily_consumption_json, updated_at)`
- `bed_status`: `(id, phc_id, total_beds, occupied_beds, updated_at)`
- `staff_attendance`: `(id, phc_id, staff_id_encrypted, staff_token, present, date)`
- `patient_footfall`: `(id, phc_id, date, count)`
- `redistribution_transfers`: `(id, source_phc, target_phc, medicine_name, quantity, eta_mins, status, numbers_json, created_at)`

*Seeding*: Auto-populates 4 PHCs (e.g. PHC-001 Alpha, PHC-002 Beta, PHC-003 Gamma, PHC-004 Delta) with 14 days of realistic daily consumption data (spikes simulated at PHC-001 to trigger stock-outs).

### 2. FastAPI Endpoints (`backend/main.py`)
- **CRUD Endpoints**: `/api/inventory`, `/api/beds`, `/api/staff`, `/api/footfall`
- **Dashboard Data**: `/api/dashboard/phc/{phc_id}`, `/api/dashboard/district/{district_id}`, `/api/dashboard/national`
- **Forecasting Endpoint**: `/api/forecasting/{phc_id}`
- **Redistribution Engine**: `/api/redistribution/recommendations`, POST `/api/redistribution/action` (approve/reject)
- **Privacy & Tokenization**: `/api/privacy/tokenize`, `/api/privacy/decrypt-test`
- **Federated AI Panel**: `/api/federated/train-and-aggregate`

### 3. Forecasting Engine (`backend/forecasting.py`)
- Fits $y = m \cdot x + c$ using `np.polyfit(x, daily_usage, 1)`.
- Calculates:
  - `slope` (daily consumption trend direction)
  - `predicted_next_day_demand = max(0, round(slope * N + intercept))`
  - `days_of_stock_remaining = round(current_stock / predicted_demand, 1)`
  - `stock_out_risk_score` (0-100% risk)
- Prepares explainability payload showing raw array, formula parameters, and step-by-step math.

### 4. Redistribution Engine (`backend/redistribution.py`)
- Evaluates PHCs where predicted days of stock < 3 days.
- Scans nearby PHCs with stock > 14 days of cover.
- Recommends quantity = `(Target Par Level - Current Stock)` while keeping donor PHC above safety threshold.
- Calculates estimated transfer time based on mock spatial coordinates.
- Attaches explainability audit numbers to every recommendation.

### 5. Privacy & DP Layer (`backend/privacy.py`)
- Uses `cryptography.fernet.Fernet` to encrypt sensitive fields (`staff_id`, patient details).
- Replaces identifiers with deterministic SHA-256 tokens (`staff_token`) for storage/display.
- Adds random Laplace/Uniform noise ($\pm 1 \text{ to } \pm 3$) on all aggregate counts rendered above PHC level.

### 6. Federated Learning Demo (`ai/`)
- `phc1_train.py`, `phc2_train.py`, `phc3_train.py` load local PHC time-series arrays, fit `np.polyfit`, and output local weights $[m_i, c_i]$.
- `fed_avg.py` computes $W_{\text{global}} = \frac{1}{K} \sum W_i$ using `np.mean(weight_matrix, axis=0)`.
- System displays exact weights before and after averaging to visually prove federated aggregation.

### 7. Modern SPA Frontend (`frontend/`)
- Multi-tab navigation:
  - **PHC Edge Dashboard**: Live stock cards, stock update form, Web Speech voice input button, bed gauge, footfall chart, staff status.
  - **District Command View**: Aggregated stock heatmap, par-level warning flags (<30%), risk alerts.
  - **Redistribution Center**: Human-in-the-loop recommendation queue with side-by-side math audit and Approve/Reject buttons.
  - **National & BRICS Simulation**: National rollups + BRICS Federated simulation panel (partner nodes labelled as Brazil, South Africa, India).
  - **Federated AI Panel**: Local model weights $[m, c]$ per node vs. aggregated global weights visualizer.

---

## Verification Plan

### Automated Verification
- Execute FastAPI `/docs` OpenAPI schema check.
- Run Python test scripts verifying:
  1. DB creation & seed validity.
  2. Polyfit forecasting outputs & bounds.
  3. Redistribution calculation correctness.
  4. Encryption/Decryption and DP noise generation bounds.
  5. 3-node FedAvg script execution & arithmetic correctness (`np.mean`).

### Manual Verification
- Test UI stock update form and confirm instantaneous DB update and chart refresh.
- Test Web Speech API voice command parsing (speech-to-form input).
- Validate human-in-the-loop recommendation workflow (Approve transfer $\rightarrow$ stock updates on source & destination PHCs).
- Inspect privacy view to verify patient/staff PII ciphertexts.
