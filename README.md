# MERIDIAN — Federated AI Public Health Supply Chain Platform

> **Hackathon Presentation & Deployment Edition**  
> Operational Supply Chain Visibility, Linear Demand Forecasting, Human-in-the-Loop Redistribution, and Federated AI Demonstration for Public Health Facilities.

---

## 1. Project Overview

### The Public Health Supply Chain Challenge
In primary healthcare networks across developing regions, supply chains suffer from severe operational friction:
* **Asymmetric Visibility**: District and state health directorates often rely on outdated paper logs or delayed batch reports, leading to localized stock-outs while neighboring facilities hold excess inventory.
* **Emergency Stock-outs**: Critical medicines like Oral Rehydration Salts (ORS) and antibiotics experience sudden demand surges (e.g. seasonal monsoons or disease outbreaks) that deplete local inventories before central warehouses can dispatch supplies.
* **Preventable Spoilage**: High-surplus medicines near their expiration date expire unused in overstocked facilities due to lack of lateral redistribution mechanisms.
* **Data Privacy vs. Centralization**: Aggregating raw patient records into central databases introduces major data privacy and governance concerns.

### The Meridian Solution
Meridian is a unified public health supply chain platform designed for three operational tiers:
1. **National Admin**: Nationwide surveillance, network pressure monitoring, decentralized model governance (Federated Learning Demonstration), security administration, and audit oversight.
2. **District Officer**: Jurisdiction-level oversight for assigned districts, read-only operational monitoring of Primary Health Centres (PHCs), early-warning shortage detection, algorithmic donor matching, and human-in-the-loop transfer approval.
3. **PHC Staff**: Facility-edge operations for assigned health centres, daily data entry (medicine inventory, beds, equipment, RFID attendance, patient footfall), automated stock-out warnings, and peer-to-peer redistribution execution.

### Four-Section Unified Navigation
Meridian standardizes navigation across all roles into four intuitive views:
* 📊 **Dashboard**: Real-time operational KPIs, GIS facility grid, and role-scoped AI demand insights.
* 📋 **Operations**: 
  * *PHC Staff*: Fully editable daily data entry for medicines, beds, equipment, attendance, and patient footfall.
  * *District Officer*: Read-only facility surveillance across in-district health centres with live compliance status.
  * *National Admin*: Read-only nationwide district and facility surveillance with hierarchical drill-down modals.
* 🔄 **Redistribution**: 10-step auditable inter-facility transfer lifecycle with strict donor safe-stock protection.
* 💬 **Communication**: Official directives desk, signed acknowledgements, Federated Learning Demonstration panel, System Security Telemetry, and immutable audit logs.

### Core Architectural Principles
* **Human-in-the-Loop Redistribution**: AI never executes transfers automatically. Recommendations identify optimal donor-recipient pairs and verify safe buffer retention (>100% of donor 7-day demand). Transfer approval, dispatch, and delivery require human confirmation.
* **Explainable Demand Forecasting**: Linear regression ($y = mx + c$) calculated via pure NumPy over historical consumption, exposing daily burn rate, days of stock remaining, projected stock-out date, and reorder date.
* **Federated Learning Demonstration**: Simulates sample-weighted Federated Averaging (FedAvg: $w_{global} = \sum \frac{n_i}{N} w_i$) across participating health centres. Local model weights are shared for aggregation with zero transmission of raw patient records.
* **Zero-Trust Role-Based Access Control**: Strict organization-scoped data isolation enforced on the backend via PBKDF2 password hashing, HTTPOnly session cookies, and hierarchical privilege validation.

---

## 2. System Architecture

```
                               ┌──────────────────────────────────────────────┐
                               │             MERIDIAN CLIENT (SPA)            │
                               │  Vanilla HTML5 / Modern CSS3 / JavaScript    │
                               │  Chart.js Data Viz / Accessible Modals / W3C │
                               └──────────────────────┬───────────────────────┘
                                                      │ HTTP / JSON API
                                                      │ Cookie / Bearer Auth
                               ┌──────────────────────▼───────────────────────┐
                               │           FASTAPI BACKEND SERVICE            │
                               │               (Python 3.12)                  │
                               └──────────────────────┬───────────────────────┘
                                                      │
         ┌───────────────────┬────────────────────────┼───────────────────────┬───────────────────┐
         │                   │                        │                       │                   │
┌────────▼────────┐ ┌────────▼────────┐      ┌────────▼────────┐     ┌────────▼────────┐ ┌────────▼────────┐
│ Authentication  │ │ Operations &    │      │ Redistribution  │     │ Demand Forecast │ │ Federated       │
│ & RBAC Scoping  │ │ Monitoring      │      │ Lifecycle       │     │ & Insights      │ │ Aggregator (Demo│
│ PBKDF2 / Cookie │ │ Multi-role CRUD │      │ 10-Step Workflow│     │ Linear Polyfit  │ │ Sample-Weighted │
│ Scope Guards    │ │ Read-only Views │      │ Safe-Par Guard  │     │ Explainability  │ │ FedAvg          │
└────────┬────────┘ └────────┬────────┘      └────────┬────────┘     └────────┬────────┘ └────────┬────────┘
         │                   │                        │                       │                   │
         └───────────────────┴────────────────────────┼───────────────────────┴───────────────────┘
                                                      │
                               ┌──────────────────────▼───────────────────────┐
                               │               SQLITE DATABASE                │
                               │          WAL Mode / Atomic Commits           │
                               │  Inventories, Beds, Attendance, Footfall,    │
                               │  Transfers, Messages, Audit Logs, Fed Models │
                               └──────────────────────────────────────────────┘
```

### Technology Stack
* **Frontend**: Vanilla HTML5, Vanilla CSS3 (custom CSS variables, responsive grid, zero external CSS frameworks), Vanilla JavaScript (ES6+ async/await, DOM manipulation, zero frontend frameworks).
* **Backend**: FastAPI, Uvicorn, Python 3.12, Pydantic v2.
* **Database**: SQLite with Write-Ahead Logging (`WAL`), foreign keys enabled, and performance indexes on high-frequency query fields.
* **Data Science / AI**: Pure NumPy (`np.polyfit`, `np.dot`) for linear regression forecasting and Federated Averaging without heavyweight ML dependencies.
* **Security & Privacy**: PBKDF2-HMAC-SHA256 (100,000 rounds) password hashing, Python `cryptography` (Fernet) field-level encryption, SHA-256 identification tokens, Laplace differential privacy noise simulation.

---

## 3. Local Setup & Installation

### Prerequisites
* Python 3.10, 3.11, or 3.12
* Modern web browser (Chrome, Edge, Firefox, Safari)
* Git

### Step-by-Step Instructions

#### 1. Clone the Repository
```bash
git clone https://github.com/Kartikey-Paliwal/Meridian.git
cd Meridian
```

#### 2. Configure Environment Variables
Copy the provided environment template:
```bash
cp .env.example .env
```
*(On Windows PowerShell: `Copy-Item .env.example .env`)*

#### 3. Install Python Dependencies
```bash
python -m pip install -r requirements.txt
```

#### 4. Initialize Database Schema & Seed Data
Initialize tables, schemas, indexes, and baseline demonstration records:
```bash
python -m backend.database --init
```

#### 5. Start the Application Server
```bash
python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000
```

#### 6. Open the Application
Navigate to:
* **Web Application**: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
* **Interactive OpenAPI Docs**: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
* **System Health Check**: [http://127.0.0.1:8000/api/health](http://127.0.0.1:8000/api/health)

---

## 4. Demo Accounts & Role Matrix

When `DEMO_MODE=true` is enabled, quick 1-click login buttons appear in the **Demo Access** box on the login screen. You can also manually sign in with these documented credentials:

| Role | Name | Email / Username | Password | Assigned Scope | Key Capabilities |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **National Admin** | Dr. Sunita Deshmukh | `admin@meridian.health` | `Admin@123` | Nationwide (All Facilities) | Nationwide monitoring, AI Model & Privacy, Security Administration, FHIR Export, Audit Ledger, Demo Reset |
| **District Officer** | Vikramaditya Rao | `officer.north@meridian.health` | `Officer@123` | District North (PHC-001 & PHC-002) | Read-only PHC Operations Monitoring, District AI Insights, Redistribution Approval, Directives Desk |
| **District Officer** | Maria Santos | `officer.south@meridian.health` | `Officer@123` | District South (PHC-003 & PHC-004) | District South surveillance and transfer governance |
| **PHC Staff** | Nurse Anita Sharma | `staff.alpha@meridian.health` | `Staff@123` | PHC-001 (Alpha Sector) | Editable Daily Operations, Inventory, Beds, Equipment, Attendance, Footfall, Resource Requests |
| **PHC Staff** | Dr. Amit Patel | `staff.beta@meridian.health` | `Staff@123` | PHC-002 (Beta Central) | Donor facility operations, transfer dispatch confirmation |

---

## 5. Main Redistribution Demonstration Scenario

The database initializes with a predictable, real-world supply chain scenario ready to demonstrate:

```
┌──────────────────────────────────────┐               ┌──────────────────────────────────────┐
│       PHC-001 (Alpha Sector)         │               │        PHC-002 (Beta Central)        │
│          CRITICAL DEFICIT            │               │             SAFE SURPLUS             │
│  ORS Packets: 15 units (Par: 100)    │               │  ORS Packets: 320 units (Par: 100)   │
│  Daily Consumption: 60 units/day     │               │  Daily Consumption: 10 units/day     │
│  Days Remaining: 0.3 days (~6 hrs)   │               │  Days Remaining: 32.0 days           │
│  Projected Stock-out: TODAY          │               │  Safe Retainable Buffer: >200 units  │
└──────────────────┬───────────────────┘               └──────────────────▲───────────────────┘
                   │                                                      │
                   │ 1. Request 60 ORS Packets                            │ 3. Dispatch 60 ORS
                   ▼                                                      │
┌─────────────────────────────────────────────────────────────────────────┴───────────────────┐
│                           DISTRICT OFFICER (North Capital District)                         │
│  - Reviews Algorithmic Recommendation                                                       │
│  - Verifies Donor Safe Par Retention (Beta retains 260 units > 100 par level)               │
│  - Formally Approves Transfer #1 (Status: Approved)                                         │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
                   │
                   ▼ 4. Deliver & Batch Seal Inspection
┌─────────────────────────────────────────────────────────────────────────────────────────────┐
│                             ATOMIC INVENTORY RECONCILIATION                                 │
│  - PHC-002 (Beta) stock decremented: 320 -> 260 (-60 units)                                 │
│  - PHC-001 (Alpha) stock incremented:  15 ->  75 (+60 units)                                 │
│  - Complete lifecycle recorded in immutable audit log                                       │
└─────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Safe Demo Reset Mechanism
You can reset the demonstration environment back to this exact initial baseline at any time:

* **Command Line**:
  ```bash
  python backend/reset_demo.py
  ```
  *(Alternative: `python -m backend.database --reset`)*

* **Web UI**:
  Log in as **National Admin** (`admin@meridian.health`), click the account avatar in the top right navbar, and select **"🔄 Reset Demo Dataset"**. Confirm the prompt to restore all inventories, transfers, bed statuses, attendance records, and footfall data to baseline.

*Creates an immutable `DEMO_DATA_RESET` audit log entry.*

---

## 6. Five-to-Seven-Minute Hackathon Presentation Script

Follow this structured script during your demo:

### Step 1: Introduction & Login (0:00 - 0:45)
1. Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/) in your browser.
2. Highlight the **Demo Environment** indicator in the top navbar and the **Demo Access** area on the login card.
3. Explain the problem: *"In rural public healthcare, decentralized facilities experience severe stock-outs of life-saving medicines while neighboring facilities hold surpluses. Meridian creates real-time visibility, predictive demand forecasting, and accountable lateral redistribution across three administrative tiers."*
4. Click **"🏥 PHC Staff (Alpha)"** to sign in as Nurse Anita Sharma.

### Step 2: PHC Edge Operations & Stock Crisis (0:45 - 1:45)
5. Point out the jurisdiction card: **Alpha Sector PHC (PHC-001)**.
6. Navigate to **Operations**:
   * Show editable daily operations: inventory records, bed occupancy (26/30 occupied), facility equipment checklist, RFID staff attendance punch, and patient footfall entries.
   * Highlight **ORS Packets**: current quantity is **15 units** against a par level of 100.
7. Navigate to **Dashboard**:
   * Inspect **PHC AI Demand Insights**: show the **0.3 days remaining (~6 hours)** prediction.
   * Explain: *"NumPy linear regression calculated over 14 days of consumption detected an accelerating burn rate (60 units/day) and projected an imminent stock-out."*
8. Navigate to **Redistribution**:
   * Show that **Transfer #1** (60 units of ORS Packets from PHC-002 to PHC-001) is currently pending review with urgency **CRITICAL**.

### Step 3: District Officer Governance & Approval (1:45 - 3:00)
9. Click the user avatar in the top right navbar and select **"Switch Demo Account"**.
10. Click **"📊 District Officer (N)"** to sign in as Vikramaditya Rao.
11. Observe the jurisdiction switch to **North Capital District**.
12. Navigate to **Operations**:
    * Show that the District Officer sees **read-only PHC monitoring** across both Alpha and Beta facilities. Notice that routine data-entry controls are hidden.
13. Navigate to **Dashboard**:
    * Show **District AI Resource Surveillance**: point out the algorithmic recommendation: donor PHC-002 has **320 units**, recipient PHC-001 needs **60 units**, ETA is **25 minutes**.
    * Point out the green badge: *"Safe Par Retention Verified: Donor will retain 260 units (>100 par level)."*
14. Navigate to **Redistribution**:
    * Open **Transfer #1** and click **"Approve Transfer"**.
    * Status transitions to **Approved**.

### Step 4: Physical Dispatch & Delivery (3:00 - 4:15)
15. Switch account to **"🏥 PHC Staff (Beta)"** (Dr. Amit Patel).
    * Navigate to **Redistribution**. Locate Transfer #1.
    * Click **"Confirm Dispatch"**. Status transitions to **In Transit**.
16. Switch account back to **"🏥 PHC Staff (Alpha)"** (Nurse Anita Sharma).
    * Navigate to **Redistribution**. Locate Transfer #1.
    * Click **"Confirm Delivery"**. Confirm physical receipt and batch seal inspection.
    * Status transitions to **Completed**.
17. Navigate to **Operations** &rarr; **Medicine Inventory**:
    * Verify inventory balances: **Alpha ORS stock increased from 15 to 75 units** (+60).
    * Switch to Beta and verify: **Beta ORS stock decreased from 320 to 260 units** (-60). Both inventories updated atomically.

### Step 5: National Oversight, AI Model & Audit Trail (4:15 - 5:30)
18. Switch account to **"🏛️ National Admin"** (Dr. Sunita Deshmukh).
19. Navigate to **Operations**:
    * Show nationwide surveillance: district summaries for North Capital and Southern Corridor, total bed occupancy (54/130 available), and reporting compliance.
    * Click any facility to drill down into the read-only inspection modal.
20. Navigate to **Communication** &rarr; **AI Model & Privacy**:
    * Highlight the section: **Federated Learning Demonstration**.
    * Explain: *"Three health centre nodes train decentralized linear regression models on private operational data. Only model weight vectors are shared. Zero raw patient records leave local nodes."*
    * Click **"⚡ Run Federated Model Update"** to demonstrate real-time weighted FedAvg aggregation.
    * Expand **Technical Details** to display the aggregated mathematical proof ($y = 1.8421x + 14.6528$) and MAE/RMSE backtest results.
21. Navigate to **System Audit Logs**:
    * Show the end-to-end immutable audit trail capturing every action: `TRANSFER_REQUESTED`, `TRANSFER_APPROVED`, `TRANSFER_DISPATCHED`, `TRANSFER_COMPLETED_DONOR`, and `TRANSFER_COMPLETED_RECIPIENT`.
22. Conclude: *"Meridian reduces inter-facility redistribution turnaround from days to minutes, prevents stock-outs, and ensures complete human accountability."*

---

## 7. Running Automated Test Suites

Meridian contains comprehensive automated test suites verifying all security, operations, AI, and enterprise capabilities. Run them locally using:

```bash
# 1. Stage 4 Demo Readiness & Deployment Suite (40 tests)
python tests/test_stage4_demo_readiness.py

# 2. Stage 4 AI Features & Federated Learning Suite (28 tests)
python tests/test_stage4_ai_features.py

# 3. Stage 3 End-to-End Workflow Verification (59 tests)
python tests/test_stage3_e2e.py

# 4. Operations Surveillance & Scoping Suite (18 tests)
python tests/test_operations_monitoring.py

# 5. Operations Frontend-Backend Contract Suite (19 tests)
python tests/test_operations_frontend_contract.py

# 6. Operations Backend Routes & Aliases (100% pass)
python tests/test_operations_backend.py

# 7. Role-Based Access Control & Scoping Suite (38 tests)
python tests/test_rbac_security.py

# 8. Account Dropdown & Demo Switcher Suite (10 tests)
python tests/test_account_dropdown.py

# 9. Batch Provenance Ledger Scoping Suite (8 tests)
python tests/test_batch_provenance.py

# 10. Core Meridian Mathematical & Encryption Suite (8 tests)
python tests/test_meridian.py
```

*Total Automated Test Coverage: Over 230 passing tests.*

---

## 8. Limitations & Ethical Disclosures

* **Demand Forecasting Methodology**: Meridian's demand prediction engine uses pure NumPy linear regression (`np.polyfit`) over 7-14 day operational consumption histories. It is intended as an operational supply-chain trend heuristic, not a complex epidemiological or clinical forecasting model.
* **Federated Learning Demonstration**: The federated learning module is an algorithmic demonstration of decentralized parameter aggregation using sample-weighted FedAvg. It operates on simulated facility nodes within SQLite rather than a globally distributed multi-server edge network.
* **Standards Export (HL7 FHIR R4)**: The FHIR export feature outputs demonstration-compatible JSON bundles containing `MedicationStatement` and `Location` resources for interoperability evaluation. Meridian is not formally certified under the Ayushman Bharat Digital Mission (ABDM) or ONC health IT certification programs.
* **Clinical Non-Intervention**: Meridian is strictly an administrative logistics and resource coordination platform. It does not provide medical advice, diagnosis, triage, or clinical decision support.

---

## 9. Deployment Readiness & Production Configuration

### Production Startup Command
In a production environment, run Uvicorn behind a process supervisor (e.g. systemd or Docker) with multi-worker concurrency:

```bash
python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Production Checklist
1. **Disable Demo Mode**: Set `DEMO_MODE=false` in the environment to hide all demo accounts, disable the demo reset endpoint (`POST /api/admin/demo-reset`), and enforce standard authentication.
2. **Rotate Cryptographic Secrets**: Generate a cryptographically secure 64-character hex key for `MERIDIAN_SECRET_KEY`:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
3. **Enforce HTTPS & Secure Cookies**: Set `SECURE_COOKIES=true` in production to enforce `Secure; HttpOnly; SameSite=Lax` session cookie attributes over TLS.
4. **Restrict CORS Origins**: Set `ALLOWED_ORIGINS=https://meridian.health.gov` instead of `*`.
5. **Persistent Storage & WAL Backups**:
   Ensure `MERIDIAN_DB_PATH` points to a persistent, replicated storage volume. For live backups of SQLite with WAL enabled:
   ```bash
   sqlite3 backend/meridian.db ".backup /var/backups/meridian_$(date +%Y%m%d_%H%M%S).db"
   ```
6. **Health Monitoring**: Configure container orchestrators (Docker Compose, Kubernetes, or AWS ECS) to poll the unauthenticated health check path:
   * **Path**: `GET /api/health`
   * **Expected Response**: HTTP 200 `{"status": "healthy", "database": "connected", "version": "2.0.0", "timestamp": "..."}`

---

## 10. License & Acknowledgements

* **License**: Open Source under the MIT License.
* **Author**: Kartikey Paliwal & The Meridian Project Team.
