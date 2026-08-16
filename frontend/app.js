// Meridian Frontend Application Logic
let activePhcId = "PHC-001";
let footfallChartInstance = null;
let forecastChartInstance = null;
let speechRecognitionInstance = null;

document.addEventListener("DOMContentLoaded", () => {
    loadPHCDashboard(activePhcId);
    loadDistrictData();
    loadRedistributionRecommendations();
    loadFederatedData();
    loadNationalBricsData();
});

// TAB SWITCHING
function switchTab(tabId) {
    document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
    document.querySelectorAll(".nav-btn").forEach(el => el.classList.remove("active"));

    const selectedTab = document.getElementById(tabId);
    if (selectedTab) selectedTab.classList.add("active");

    const activeBtn = Array.from(document.querySelectorAll(".nav-btn")).find(btn => btn.getAttribute("onclick").includes(tabId));
    if (activeBtn) activeBtn.classList.add("active");

    if (tabId === 'forecasting-panel') updateForecastView();
}

// -------------------------------------------------------------
// 1. PHC EDGE DASHBOARD LOGIC
// -------------------------------------------------------------
async function loadPHCDashboard(phcId) {
    activePhcId = phcId;
    document.getElementById("form-phc-id").value = phcId;

    try {
        const res = await fetch(`/api/dashboard/phc/${phcId}`);
        const data = await res.json();

        // 1. Update Metrics Cards
        const totalQty = data.inventory.reduce((sum, item) => sum + item.quantity, 0);
        const criticalItems = data.inventory.filter(item => item.forecast.below_30pct_par_flag);
        
        document.getElementById("phc-total-stock").innerText = `${totalQty} units`;
        document.getElementById("phc-critical-count").innerText = `${criticalItems.length} items below 30% par`;
        document.getElementById("phc-critical-count").style.color = criticalItems.length > 0 ? "var(--accent-danger)" : "var(--accent)";

        const beds = data.bed_status;
        const occPct = beds.total_beds > 0 ? Math.round((beds.occupied_beds / beds.total_beds) * 100) : 0;
        document.getElementById("phc-bed-value").innerText = `${beds.occupied_beds} / ${beds.total_beds}`;
        document.getElementById("phc-bed-sub").innerText = `${occPct}% Occupied`;

        const staffCount = data.staff_attendance.filter(s => s.present === 1).length;
        document.getElementById("phc-staff-value").innerText = `${staffCount} Present`;

        const footfallTotal = data.patient_footfall.reduce((sum, f) => sum + f.count, 0);
        const avgFootfall = data.patient_footfall.length > 0 ? Math.round(footfallTotal / data.patient_footfall.length) : 0;
        document.getElementById("phc-footfall-value").innerText = `${avgFootfall} pts/day`;

        // 2. Render Inventory Table
        const tbody = document.querySelector("#phc-inventory-table tbody");
        tbody.innerHTML = "";
        data.inventory.forEach(item => {
            const tr = document.createElement("tr");
            const forecast = item.forecast;
            
            let statusBadge = `<span class="badge badge-success">OK</span>`;
            if (forecast.risk_level === "CRITICAL") statusBadge = `<span class="badge badge-danger">CRITICAL RISK</span>`;
            else if (forecast.below_30pct_par_flag) statusBadge = `<span class="badge badge-warning">LOW (<30%)</span>`;

            tr.innerHTML = `
                <td><strong>${item.medicine_name}</strong></td>
                <td>${item.quantity}</td>
                <td>${item.par_level}</td>
                <td>${statusBadge}</td>
                <td>${forecast.predicted_next_day_demand} / day</td>
                <td><strong>${forecast.days_of_stock_remaining} days</strong></td>
            `;
            tbody.appendChild(tr);
        });

        // 3. Render Footfall Chart
        renderFootfallChart(data.patient_footfall);

        // 4. Render Staff Attendance Table
        const staffTbody = document.querySelector("#staff-table tbody");
        staffTbody.innerHTML = "";
        data.staff_attendance.forEach(stf => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td><code>${stf.staff_token}</code></td>
                <td><code style="font-size:0.7rem;">${stf.staff_id_encrypted.substring(0, 24)}...</code></td>
                <td>${stf.present === 1 ? '<span class="badge badge-success">PRESENT</span>' : '<span class="badge badge-danger">ABSENT</span>'}</td>
                <td>${stf.date}</td>
            `;
            staffTbody.appendChild(tr);
        });

    } catch (err) {
        console.error("Error loading PHC Dashboard:", err);
    }
}

// Render Footfall Chart with Chart.js
function renderFootfallChart(footfallData) {
    const ctx = document.getElementById("footfallChart").getContext("2d");
    const labels = footfallData.map(f => f.date);
    const counts = footfallData.map(f => f.count);

    if (footfallChartInstance) footfallChartInstance.destroy();

    footfallChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Daily Patient Footfall',
                data: counts,
                borderColor: '#0284c7',
                backgroundColor: 'rgba(2, 132, 199, 0.15)',
                borderWidth: 3,
                fill: true,
                tension: 0.3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: { grid: { color: '#334155' }, ticks: { color: '#94a3b8' } },
                x: { grid: { color: '#334155' }, ticks: { color: '#94a3b8' } }
            }
        }
    });
}

// Handle Form Submission
async function handleStockUpdateSubmit(e) {
    e.preventDefault();
    const phcId = document.getElementById("form-phc-id").value;
    const medName = document.getElementById("form-medicine-name").value;
    const qty = parseInt(document.getElementById("form-quantity").value);
    const par = parseInt(document.getElementById("form-par-level").value);

    try {
        const res = await fetch("/api/inventory/update", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ phc_id: phcId, medicine_name: medName, quantity: qty, par_level: par })
        });
        const data = await res.json();
        alert(data.message);
        
        // Instant refresh
        loadPHCDashboard(phcId);
        loadDistrictData();
        loadRedistributionRecommendations();
    } catch (err) {
        alert("Failed to update inventory.");
    }
}

// Voice Entry using Web Speech API
function toggleVoiceInput() {
    const btn = document.getElementById("voice-entry-btn");
    const statusBox = document.getElementById("voice-status-box");

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

    if (!SpeechRecognition) {
        alert("Browser Web Speech API is not supported in this browser. Please type into the form directly.");
        return;
    }

    if (speechRecognitionInstance && btn.classList.contains("listening")) {
        speechRecognitionInstance.stop();
        btn.classList.remove("listening");
        btn.innerHTML = `🎙️ Speak Update (Web Speech API)`;
        statusBox.innerText = "Speech recognition stopped.";
        return;
    }

    speechRecognitionInstance = new SpeechRecognition();
    speechRecognitionInstance.continuous = false;
    speechRecognitionInstance.interimResults = false;
    speechRecognitionInstance.lang = "en-US";

    btn.classList.add("listening");
    btn.innerHTML = `🛑 Listening... Speak now`;
    statusBox.innerText = "Listening... Speak stock update e.g. 'Update ORS Packets quantity 150'";

    speechRecognitionInstance.onresult = (event) => {
        const transcript = event.results[0][0].transcript;
        statusBox.innerHTML = `Heard: "<em>${transcript}</em>"`;
        parseVoiceCommand(transcript);
        btn.classList.remove("listening");
        btn.innerHTML = `🎙️ Speak Update (Web Speech API)`;
    };

    speechRecognitionInstance.onerror = (event) => {
        statusBox.innerText = `Voice input error: ${event.error}`;
        btn.classList.remove("listening");
        btn.innerHTML = `🎙️ Speak Update (Web Speech API)`;
    };

    speechRecognitionInstance.start();
}

function parseVoiceCommand(text) {
    const lower = text.toLowerCase();
    
    // Parse quantity numbers
    const numbers = lower.match(/\d+/g);
    if (numbers && numbers.length > 0) {
        document.getElementById("form-quantity").value = numbers[0];
    }

    // Match Medicine
    if (lower.includes("ors")) document.getElementById("form-medicine-name").value = "ORS Packets";
    else if (lower.includes("paracetamol")) document.getElementById("form-medicine-name").value = "Paracetamol 500mg";
    else if (lower.includes("amoxicillin")) document.getElementById("form-medicine-name").value = "Amoxicillin 250mg";
    else if (lower.includes("insulin")) document.getElementById("form-medicine-name").value = "Insulin Vials";
    else if (lower.includes("zinc")) document.getElementById("form-medicine-name").value = "Zinc Supplements";
}


// -------------------------------------------------------------
// 2. DISTRICT AGGREGATION LOGIC
// -------------------------------------------------------------
async function loadDistrictData() {
    try {
        const res = await fetch("/api/dashboard/district");
        const data = await res.json();

        // 1. Warnings Banner & Table
        const warnings = data.critical_par_level_warnings;
        const bannerText = document.getElementById("warning-count-text");
        if (warnings.length > 0) {
            bannerText.innerHTML = `<strong style="color:#ef4444;">${warnings.length} medicine stock items</strong> are below 30% par level!`;
        } else {
            bannerText.innerText = "All district medicine stock levels are above par safety threshold.";
        }

        const tbody = document.querySelector("#district-warnings-table tbody");
        tbody.innerHTML = "";
        warnings.forEach(w => {
            const tr = document.createElement("tr");
            tr.innerHTML = `
                <td><strong>${w.phc_id}</strong></td>
                <td>${w.medicine_name}</td>
                <td>${w.quantity}</td>
                <td>${w.par_level}</td>
                <td><span class="badge badge-danger">${w.pct_of_par}%</span></td>
                <td><span class="badge badge-danger">CRITICAL LOW</span></td>
            `;
            tbody.appendChild(tr);
        });

        // 2. Aggregate DP Metrics
        const dpBox = document.getElementById("district-summary-metrics");
        const dpFootfall = data.footfall_summary.dp_noised_total_footfall;
        const dpBeds = data.bed_summary.dp_noised_occupied_beds;

        dpBox.innerHTML = `
            <div style="font-family: var(--font-mono); font-size: 0.875rem;">
                <p style="margin-bottom:8px;"><strong>True Footfall Count:</strong> ${data.footfall_summary.true_total_footfall}</p>
                <p style="margin-bottom:8px; color:#38bdf8;"><strong>Noised Aggregate Footfall (DP):</strong> ${dpFootfall.noised_count} (Noise: ${dpFootfall.noise_added})</p>
                <hr style="border-color:#334155; margin: 10px 0;">
                <p style="margin-bottom:8px;"><strong>True Occupied Beds:</strong> ${data.bed_summary.occupied_beds} / ${data.bed_summary.total_beds}</p>
                <p style="color:#38bdf8;"><strong>Noised Occupied Beds (DP):</strong> ${dpBeds.noised_count} (Noise: ${dpBeds.noise_added})</p>
            </div>
        `;

    } catch (err) {
        console.error("Error loading district data:", err);
    }
}


// -------------------------------------------------------------
// 3. REDISTRIBUTION ENGINE (HUMAN-IN-THE-LOOP) LOGIC
// -------------------------------------------------------------
async function loadRedistributionRecommendations() {
    try {
        const res = await fetch("/api/redistribution/recommendations");
        const data = await res.json();

        const recs = data.active_recommendations;
        document.getElementById("redist-count-badge").innerText = recs.length;

        const container = document.getElementById("recommendations-container");
        container.innerHTML = "";

        if (recs.length === 0) {
            container.innerHTML = `<p style="color:var(--text-muted); padding:10px;">No critical shortages detected. Inventory is balanced across district PHCs.</p>`;
        } else {
            recs.forEach((rec, idx) => {
                const num = rec.explainability_underlying_numbers;
                const card = document.createElement("div");
                card.className = "recommendation-card";
                card.innerHTML = `
                    <div class="rec-header">
                        <span class="rec-route">⚡ Transfer ${rec.recommended_quantity} units of ${rec.medicine_name}</span>
                        <span class="badge badge-warning">ETA: ${rec.eta_minutes} mins</span>
                    </div>
                    <p style="font-size:0.9rem; margin-bottom:8px;">
                        <strong>Source Donor:</strong> ${rec.source_phc} &nbsp;&rarr;&nbsp; <strong>Target Recipient:</strong> ${rec.target_phc}
                    </p>

                    <div class="rec-numbers-box">
                        <strong>UNDERLYING EXPLAINABILITY NUMBERS:</strong><br>
                        • Target (${rec.target_phc}) Current Stock: ${num.target_phc_current_stock} units | Pred. Demand: ${num.target_phc_predicted_daily_demand}/day | Days Remaining: ${num.target_phc_days_remaining}d (${num.target_phc_risk_level})<br>
                        • Donor (${rec.source_phc}) Current Stock: ${num.donor_phc_current_stock} units | Pred. Demand: ${num.donor_phc_predicted_daily_demand}/day | Surplus Capacity: ${num.donor_phc_surplus_capacity} units<br>
                        • Distance: ${num.estimated_distance_km} km | Rationale: ${num.rationale}
                    </div>

                    <div class="rec-actions">
                        <button class="btn btn-danger" onclick="respondToRecommendation('${rec.source_phc}', '${rec.target_phc}', '${rec.medicine_name}', ${rec.recommended_quantity}, 'REJECT')">
                            ❌ Reject / Override
                        </button>
                        <button class="btn btn-success" onclick="respondToRecommendation('${rec.source_phc}', '${rec.target_phc}', '${rec.medicine_name}', ${rec.recommended_quantity}, 'APPROVE')">
                            ✅ Approve Transfer & Execute DB Update
                        </button>
                    </div>
                `;
                container.appendChild(card);
            });
        }

        // Render Transfer History
        const tbody = document.querySelector("#transfer-history-table tbody");
        tbody.innerHTML = "";
        data.transfer_history_log.forEach(t => {
            const tr = document.createElement("tr");
            let badge = `<span class="badge badge-success">APPROVED</span>`;
            if (t.status === "REJECT" || t.status === "OVERRIDE") badge = `<span class="badge badge-danger">${t.status}</span>`;

            tr.innerHTML = `
                <td>#${t.id}</td>
                <td>${t.source_phc}</td>
                <td>${t.target_phc}</td>
                <td>${t.medicine_name}</td>
                <td>${t.quantity}</td>
                <td>${t.eta_mins}m</td>
                <td>${badge}</td>
                <td>${t.created_at.substring(11, 19)}</td>
            `;
            tbody.appendChild(tr);
        });

    } catch (err) {
        console.error("Error loading recommendations:", err);
    }
}

async function respondToRecommendation(source, target, med, qty, action) {
    try {
        const res = await fetch("/api/redistribution/action", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                source_phc: source,
                target_phc: target,
                medicine_name: med,
                quantity: qty,
                action: action
            })
        });
        const data = await res.json();
        alert(data.message);

        // Refresh views
        loadPHCDashboard(activePhcId);
        loadDistrictData();
        loadRedistributionRecommendations();
    } catch (err) {
        alert("Failed to execute transfer action.");
    }
}


// -------------------------------------------------------------
// 4. AI DEMAND FORECASTING & EXPLAINABILITY
// -------------------------------------------------------------
async function updateForecastView() {
    const phcId = document.getElementById("forecast-phc-select").value;
    const medName = document.getElementById("forecast-med-select").value;

    try {
        const res = await fetch(`/api/forecasting/${phcId}?medicine_name=${encodeURIComponent(medName)}`);
        const data = await res.json();

        const forecast = data.forecast;
        const exp = forecast.explainability;

        // Render Explainability Box
        const expBox = document.getElementById("explainability-box");
        expBox.innerHTML = `
            <div style="font-family: var(--font-mono); font-size: 0.85rem;">
                <p style="color:#38bdf8; margin-bottom:10px;"><strong>NumPy Linear Regression Model: y = m*x + c</strong></p>
                <p>• Fitted Slope (m): <strong>${exp.linear_model_slope_m}</strong></p>
                <p>• Fitted Intercept (c): <strong>${exp.linear_model_intercept_c}</strong></p>
                <p>• Fitted Equation: <code>${exp.formula_used}</code></p>
                <hr style="border-color:#334155; margin:12px 0;">
                <p style="color:#34d399; margin-bottom:8px;"><strong>Prediction Step-by-Step:</strong></p>
                <p>• ${exp.next_day_prediction_math}</p>
                <p>• Days Cover: ${exp.days_cover_math}</p>
                <p>• Risk Score: <strong>${forecast.stock_out_risk_score}% (${forecast.risk_level})</strong></p>
                <hr style="border-color:#334155; margin:12px 0;">
                <p style="color:#f59e0b;"><strong>Historical Daily Usage Window (14 Days):</strong></p>
                <code>[${exp.daily_usage_array.join(", ")}]</code>
            </div>
        `;

        // Render Forecast Chart
        renderForecastChart(exp.daily_usage_array, forecast.predicted_next_day_demand);

    } catch (err) {
        console.error("Error updating forecast:", err);
    }
}

function renderForecastChart(historicalData, predictedDemand) {
    const ctx = document.getElementById("forecastChart").getContext("2d");
    
    const labels = historicalData.map((_, idx) => `Day ${idx + 1}`);
    labels.push("Day 15 (Predicted)");

    const actualSeries = [...historicalData, null];
    const predictedSeries = Array(historicalData.length - 1).fill(null);
    predictedSeries.push(historicalData[historicalData.length - 1]);
    predictedSeries.push(predictedDemand);

    if (forecastChartInstance) forecastChartInstance.destroy();

    forecastChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: 'Historical Daily Usage',
                    data: actualSeries,
                    borderColor: '#0284c7',
                    borderWidth: 2,
                    pointRadius: 4
                },
                {
                    label: 'Next-Day Linear Forecast',
                    data: predictedSeries,
                    borderColor: '#ef4444',
                    borderDash: [5, 5],
                    borderWidth: 3,
                    pointRadius: 6,
                    pointBackgroundColor: '#ef4444'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: { grid: { color: '#334155' }, ticks: { color: '#94a3b8' } },
                x: { grid: { color: '#334155' }, ticks: { color: '#94a3b8' } }
            }
        }
    });
}


// -------------------------------------------------------------
// 5. FEDERATED LEARNING DEMO (FedAvg) LOGIC
// -------------------------------------------------------------
async function loadFederatedData() {
    try {
        const res = await fetch("/api/federated/train-and-aggregate");
        const data = await res.json();

        // Nodes
        data.local_nodes.forEach((node, idx) => {
            const cardEl = document.getElementById(`node${idx+1}-weights`);
            if (cardEl) {
                cardEl.innerHTML = `
                    Slope (m): <strong>${node.weights[0].toFixed(4)}</strong><br>
                    Intercept (c): <strong>${node.weights[1].toFixed(4)}</strong><br>
                    Model: <code>y = ${node.weights[0].toFixed(4)}*x + ${node.weights[1].toFixed(4)}</code>
                `;
            }
        });

        // Global Model Box
        const g = data.global_model;
        const p = data.arithmetic_proof;
        const gBox = document.getElementById("global-model-box");
        gBox.innerHTML = `
            <p style="font-size:1.1rem; color:#34d399; margin-bottom:8px;">
                <strong>Global Model Equation:</strong> ${g.formula}
            </p>
            <p style="color:#94a3b8;">
                <strong>Arithmetic Proof (np.mean across local weights):</strong><br>
                ${p.formula_proof}
            </p>
        `;
    } catch (err) {
        console.error("Error loading federated data:", err);
    }
}

async function triggerFederatedTraining() {
    await loadFederatedData();
    alert("Federated Learning training pass completed across 3 local nodes! Weights averaged into Global Model.");
}


// -------------------------------------------------------------
// 6. NATIONAL & BRICS SIMULATION LOGIC
// -------------------------------------------------------------
async function loadNationalBricsData() {
    try {
        const res = await fetch("/api/dashboard/national");
        const data = await res.json();

        const container = document.getElementById("brics-nodes-container");
        container.innerHTML = "";

        data.brics_simulation_nodes.forEach(node => {
            const card = document.createElement("div");
            card.className = `brics-card ${node.is_simulated ? 'simulated' : ''}`;
            card.innerHTML = `
                <div class="brics-country">${node.nation}</div>
                <h4 style="margin-bottom:8px;">${node.name} (${node.node_id})</h4>
                <p style="font-size:0.85rem; color:var(--text-muted); margin-bottom:12px;">
                    Federated Status: <strong>${node.status}</strong>
                </p>
                ${node.is_simulated ? '<span class="badge badge-simulated">SIMULATED BRICS PARTNER NODE</span>' : '<span class="badge badge-info">HOST NATIONAL NODE</span>'}
            `;
            container.appendChild(card);
        });

    } catch (err) {
        console.error("Error loading BRICS data:", err);
    }
}


// -------------------------------------------------------------
// 7. PRIVACY INSPECTOR TEST
// -------------------------------------------------------------
async function testPrivacyLayer() {
    const val = document.getElementById("privacy-input").value;
    try {
        const res = await fetch(`/api/privacy/demo?raw_staff_id=${encodeURIComponent(val)}`);
        const data = await res.json();

        document.getElementById("privacy-results").style.display = "block";
        document.getElementById("res-encrypted").innerText = data.fernet_encrypted_ciphertext;
        document.getElementById("res-decrypted").innerText = data.decrypted_verification;
        document.getElementById("res-token").innerText = data.sha256_token;
        document.getElementById("res-dp").innerText = JSON.stringify(data.differential_privacy_simulation, null, 2);
    } catch (err) {
        alert("Failed to run privacy test.");
    }
}
