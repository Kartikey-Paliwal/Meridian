# MERIDIAN — Federated AI Public Health Supply Chain Platform

> **Hackathon MVP Prototype** | Track: National-Scale Health Resource & Supply Chain Visibility, Demand Forecasting, and Federated AI for BRICS Nations.

Meridian is a 4-layer federated AI platform that provides real-time visibility into medicine inventory, hospital bed occupancy, staff attendance, and patient footfall across Primary Health Centres (PHCs), forecasts near-term consumption using NumPy linear regression, recommends explainable resource redistribution with human-in-the-loop approval, protects privacy via Fernet field encryption & differential privacy noise, and aggregates local models via 3-node NumPy FedAvg.

---

## Technical Features

1. **FastAPI Backend & SQLite Database**: CRUD endpoints for `medicine_inventory`, `bed_status`, `staff_attendance`, `patient_footfall`, and `redistribution_transfers`. Auto-generates interactive API docs at `http://localhost:8000/docs`.
2. **PHC Edge Dashboard**: Real-time stock management, voice-to-form stock updates via browser Web Speech API (`SpeechRecognition`), bed occupancy tracking, patient footfall trend chart, and encrypted staff attendance log.
3. **District Aggregation & Heatmap**: Aggregates stock across PHCs, flags any item below **30% of par level baseline**, applies differential privacy noise to aggregate count rollups.
4. **Demand Forecasting Engine**: Computes linear regression over 7-14 day consumption arrays using `np.polyfit(x, daily_usage, 1)` without external ML libraries. Exposes slope, intercept, days-of-stock cover, stock-out risk score, and step-by-step formula math for complete audit transparency.
5. **Resource Redistribution Engine**: Matches predicted shortage PHCs to surplus donor PHCs, calculates transfer quantity and transport ETA, attaches underlying explainability numbers, and enforces **Human-in-the-Loop** explicit "Approve/Reject" actions before modifying DB allocations.
6. **Privacy Layer**: Encrypts sensitive staff/patient identifiers using Python `cryptography` (Fernet), stores SHA-256 tokens (`TOK-XXXX`), and injects bounded random noise ($\pm 1 \text{ to } \pm 3$) into district/national aggregate counts.
7. **Federated Learning Demo**: 3 Python scripts (`ai/phc1_train.py`, `ai/phc2_train.py`, `ai/phc3_train.py`) train local `np.polyfit` models on private local datasets. `ai/fed_avg.py` averages local weights using `np.mean(weights, axis=0)` into a Global Model and outputs explicit arithmetic proofs.
8. **National Command Dashboard & BRICS Simulation**: National rollups, active redistribution management, federated model panel, and clearly marked **SIMULATED BRICS PARTNER NODES** (Brazil & South Africa).

---

## Project Structure

```
meridian/
├── backend/
│   ├── main.py             # FastAPI app, static server, & routes
│   ├── database.py         # SQLite connection, tables, & synthetic seed data
│   ├── models.py           # Pydantic schemas for API requests
│   ├── forecasting.py      # NumPy linear regression & explainability math
│   ├── redistribution.py   # Rule-based transfer matching & ETA engine
│   └── privacy.py          # Fernet encryption, SHA-256 tokens, & DP noise
├── ai/
│   ├── phc1_train.py       # Local training script for PHC Node 1
│   ├── phc2_train.py       # Local training script for PHC Node 2
│   ├── phc3_train.py       # Local training script for PHC Node 3
│   └── fed_avg.py          # Federated Averaging (FedAvg) script
├── frontend/
│   ├── index.html          # SPA dashboard with multi-tab view
│   ├── styles.css          # Glassmorphism dark-mode health-tech styling
│   └── app.js             # Web Speech API, Chart.js, & API integration
├── docs/
│   └── architecture.md     # System architecture & mathematical specs
├── requirements.txt        # Python dependencies
└── README.md
```

---

## Quickstart Guide

### 1. Install Dependencies
```bash
python -m pip install -r requirements.txt
```

### 2. Run the Server
```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### 3. Open in Browser
- **Web Dashboard**: `http://localhost:8000/`
- **Interactive OpenAPI Documentation**: `http://localhost:8000/docs`

---

## 3-Minute Demo Script

1. **PHC Edge View**: Open `http://localhost:8000/`. Observe PHC-001 (Alpha Sector) facing an ORS stock crisis (15 units remaining, demand spiking). Click **"Speak Update"** or type into the form to update ORS quantity.
2. **District Command**: Switch to **District Command & Alerts**. Observe the red flag alert for ORS Packets at PHC-001 (<30% par level) and the differential privacy noised aggregate count.
3. **Redistribution Engine**: Switch to **Redistribution Engine**. Inspect the active recommendation: transfer 160 units of ORS from PHC-002 (surplus donor) to PHC-001 (shortage target). Inspect the **underlying explainability numbers box**. Click **"Approve Transfer & Execute DB Update"**. Verify that stock updates on both PHCs in real time!
4. **AI Demand Forecasting**: Switch to **AI Forecasting & Math**. View the historical daily usage curve vs. next-day linear forecast. Inspect the exact linear equation $y = m \cdot x + c$ and step-by-step formula math.
5. **Federated Learning**: Switch to **Federated AI (FedAvg)**. Click **"Run Federated Training & Aggregation"**. Observe the 3 local model weight vectors $[m_i, c_i]$ and the arithmetic proof averaging them into the Global Model.
6. **National & BRICS Simulation**: Switch to **National & BRICS Layer**. Point out the clearly labelled **SIMULATED BRICS PARTNER NODES** (Brazil & South Africa) demonstrating cross-border model weight sharing without transmitting raw patient data.
