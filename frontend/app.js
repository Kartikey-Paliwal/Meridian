// Meridian Frontend Application Logic
let activePhcId = "PHC-001";
let footfallChartInstance = null;
let forecastChartInstance = null;
let speechRecognitionInstance = null;

// Attendance module state
let currentAttendanceRosterData = [];
let currentStaffMembers = [];
let lastPunchTimes = {}; // Card UID -> timestamp (ms) for debounce/duplicate prevention

document.addEventListener("DOMContentLoaded", () => {
    // Check URL hash for initial tab route (e.g. #staff-attendance-panel)
    const initialHash = window.location.hash ? window.location.hash.replace("#", "") : "phc-dashboard";

    loadPHCDashboard(activePhcId);
    loadDistrictData();
    loadRedistributionRecommendations();
    loadFederatedData();
    loadNationalBricsData();
    loadNationalDashboard();
    loadStaffAttendancePage(activePhcId);
    startTerminalClock();

    if (initialHash && document.getElementById(initialHash)) {
        const titleMap = {
            "phc-dashboard": "PHC Edge Node",
            "staff-attendance-panel": "Nurse & Staff Attendance Management",
            "district-dashboard": "District Command & Alerts",
            "redistribution-panel": "Redistribution Engine",
            "forecasting-panel": "AI Forecasting & Math",
            "federated-panel": "Federated AI (FedAvg)",
            "national-dashboard": "National Health Command Center",
            "national-brics-panel": "BRICS Federated Layer",
            "privacy-panel": "Privacy & Encryption",
            "enterprise-panel": "Enterprise Control Center"
        };
        switchTab(initialHash, titleMap[initialHash] || null, false);
    }
});

// Support browser Back/Forward navigation with hash routing
window.addEventListener("hashchange", () => {
    const hash = window.location.hash.replace("#", "");
    if (hash && document.getElementById(hash)) {
        switchTab(hash, null, false);
    }
});

// TAB SWITCHING WITH HASH ROUTING SUPPORT
function switchTab(tabId, titleText, updateHash = true) {
    document.querySelectorAll(".tab-content").forEach(el => el.classList.remove("active"));
    document.querySelectorAll(".sidebar-btn, .nav-btn").forEach(el => el.classList.remove("active"));

    const selectedTab = document.getElementById(tabId);
    if (selectedTab) selectedTab.classList.add("active");

    const activeBtn = Array.from(document.querySelectorAll(".sidebar-btn, .nav-btn")).find(btn => btn.getAttribute("onclick") && btn.getAttribute("onclick").includes(tabId));
    if (activeBtn) activeBtn.classList.add("active");

    if (titleText) {
        const titleEl = document.getElementById("current-tab-title");
        if (titleEl) titleEl.innerText = titleText;
    }

    if (updateHash) {
        window.location.hash = tabId;
    }

    if (tabId === 'forecasting-panel') updateForecastView();
    if (tabId === 'national-dashboard') loadNationalDashboard();
    if (tabId === 'staff-attendance-panel') loadStaffAttendancePage(activePhcId);
}

// -------------------------------------------------------------
// 1. PHC EDGE DASHBOARD LOGIC
// -------------------------------------------------------------
async function loadPHCDashboard(phcId) {
    activePhcId = phcId;
    const phcFormInput = document.getElementById("form-phc-id");
    if (phcFormInput) phcFormInput.value = phcId;

    // Update main title dynamically
    const titleMap = {
        "PHC-001": "PHC Rampur — Dashboard",
        "PHC-002": "PHC Beta Central — Dashboard",
        "PHC-003": "PHC Gamma Rural — Dashboard",
        "PHC-004": "PHC Delta Community — Dashboard"
    };
    const mainTitleEl = document.getElementById("phc-main-title");
    if (mainTitleEl) mainTitleEl.innerText = titleMap[phcId] || `${phcId} — Dashboard`;

    // Update Date Header
    updateHeaderDate();

    try {
        const res = await fetch(`/api/dashboard/phc/${phcId}`);
        const data = await res.json();

        // 1. Update Metrics Cards
        const totalItems = data.inventory.length;
        const atRiskCount = data.inventory.filter(item => item.forecast.below_30pct_par_flag || item.forecast.risk_level === "CRITICAL").length;
        const criticalItems = data.inventory.filter(item => item.forecast.risk_level === "CRITICAL").length;

        const riskValEl = document.getElementById("phc-risk-value");
        if (riskValEl) riskValEl.innerHTML = `${atRiskCount} <span class="metric-total">of ${totalItems}</span>`;
        const critEl = document.getElementById("phc-critical-count");
        if (critEl) critEl.innerText = `${criticalItems} critical`;

        const beds = data.bed_status;
        const occPct = beds.total_beds > 0 ? Math.round((beds.occupied_beds / beds.total_beds) * 100) : 0;
        const bedValEl = document.getElementById("phc-bed-value");
        if (bedValEl) bedValEl.innerHTML = `${beds.occupied_beds} <span class="metric-total">/ ${beds.total_beds}</span>`;
        const bedSubEl = document.getElementById("phc-bed-sub");
        if (bedSubEl) bedSubEl.innerText = `${occPct}% full`;

        const footfallLen = data.patient_footfall.length;
        const todayCount = footfallLen > 0 ? data.patient_footfall[footfallLen - 1].count : 47;
        const prevCount = footfallLen > 1 ? data.patient_footfall[footfallLen - 2].count : 41;
        const todayEl = document.getElementById("phc-footfall-today");
        if (todayEl) todayEl.innerText = `${todayCount}`;
        const footSubEl = document.getElementById("phc-footfall-sub");
        if (footSubEl) footSubEl.innerText = `vs ${prevCount} last Sun`;

        const staffMembers = data.staff_members || [];
        const attendanceList = data.staff_attendance || [];
        const totalStaff = staffMembers.length || 8;

        // Map latest record per staff member
        const latestMap = {};
        attendanceList.forEach(rec => {
            if (!latestMap[rec.staff_id]) {
                latestMap[rec.staff_id] = rec;
            }
        });

        let presentStaff = 0;
        let onLeaveStaff = 0;
        let absentStaff = 0;

        staffMembers.forEach(mem => {
            const rec = latestMap[mem.staff_id];
            if (!rec) {
                absentStaff++;
            } else if (rec.status === "CHECKED_IN" || rec.status === "LATE" || rec.present === 1 && rec.status !== "CHECKED_OUT") {
                presentStaff++;
            } else if (rec.status === "ON_LEAVE") {
                onLeaveStaff++;
            } else {
                absentStaff++;
            }
        });

        const onDutyPct = totalStaff > 0 ? Math.round((presentStaff / totalStaff) * 100) : 0;

        // Top Metric Card on PHC Dashboard
        const staffValEl = document.getElementById("phc-staff-value");
        if (staffValEl) staffValEl.innerHTML = `${presentStaff} <span class="metric-total">/ ${totalStaff}</span>`;
        const staffSubEl = document.getElementById("phc-staff-sub");
        if (staffSubEl) staffSubEl.innerText = `${absentStaff} absent / off duty`;

        // Summary Card on PHC Dashboard (Replacement of full portal)
        const sumPresent = document.getElementById("phc-summary-present");
        if (sumPresent) sumPresent.innerHTML = `${presentStaff} <span class="metric-total">staff</span>`;
        const sumAbsent = document.getElementById("phc-summary-absent");
        if (sumAbsent) sumAbsent.innerHTML = `${absentStaff} <span class="metric-total">staff</span>`;
        const sumLeave = document.getElementById("phc-summary-leave");
        if (sumLeave) sumLeave.innerHTML = `${onLeaveStaff} <span class="metric-total">staff</span>`;
        const sumOnDuty = document.getElementById("phc-summary-onduty-pct");
        if (sumOnDuty) sumOnDuty.innerText = `${onDutyPct}%`;
        const sumOnDutySub = document.getElementById("phc-summary-onduty-sub");
        if (sumOnDutySub) sumOnDutySub.innerText = `${presentStaff} of ${totalStaff} staff on active duty`;

        // 2. Render Inventory Table
        const tbody = document.querySelector("#phc-inventory-table tbody");
        if (tbody) {
            tbody.innerHTML = "";
            data.inventory.forEach(item => {
                const tr = document.createElement("tr");
                const forecast = item.forecast;
                const unit = getUnitForMedicine(item.medicine_name);

                let statusPill = `<span class="status-pill pill-healthy"><span class="dot">●</span> Healthy</span>`;
                if (forecast.risk_level === "CRITICAL" || item.quantity < item.par_level * 0.25) {
                    statusPill = `<span class="status-pill pill-low"><span class="dot">●</span> Low stock</span>`;
                } else if (forecast.below_30pct_par_flag || item.quantity < item.par_level * 0.6) {
                    statusPill = `<span class="status-pill pill-watch"><span class="dot">●</span> Watch</span>`;
                }

                tr.innerHTML = `
                    <td class="med-name">${item.medicine_name}</td>
                    <td><span class="stock-val">${item.quantity}</span> <span class="unit-text">${unit}</span></td>
                    <td class="par-val">${item.par_level}</td>
                    <td>${statusPill}</td>
                `;
                tbody.appendChild(tr);
            });
        }

        // 3. Render Footfall Chart
        renderFootfallChart(data.patient_footfall);

    } catch (err) {
        console.error("Error loading PHC Dashboard:", err);
    }
}

// Utility to get unit string per medicine
function getUnitForMedicine(name) {
    const n = name.toLowerCase();
    if (n.includes("ors")) return "packets";
    if (n.includes("paracetamol")) return "tabs";
    if (n.includes("amoxicillin")) return "caps";
    if (n.includes("iv") || n.includes("fluids")) return "bottles";
    if (n.includes("iron") || n.includes("folic") || n.includes("zinc") || n.includes("chlorine")) return "tabs";
    if (n.includes("insulin")) return "vials";
    return "units";
}

// Utility to update top-right header date display
function updateHeaderDate() {
    const now = new Date();
    const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    const dateStr = `${days[now.getDay()]}, ${months[now.getMonth()]} ${now.getDate()}`;
    const dateEl = document.getElementById("current-date-display");
    if (dateEl) dateEl.innerText = dateStr;
}

// Render Footfall Chart with Chart.js matching reference image
function renderFootfallChart(footfallData) {
    const canvas = document.getElementById("footfallChart");
    if (!canvas) return;
    const ctx = canvas.getContext("2d");

    const daysOfWeek = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
    const labels = footfallData.map(f => {
        const d = new Date(f.date);
        return isNaN(d.getDay()) ? f.date : daysOfWeek[d.getDay()];
    });
    const counts = footfallData.map(f => f.count);

    if (footfallChartInstance) footfallChartInstance.destroy();

    footfallChartInstance = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Patient Footfall',
                data: counts,
                borderColor: '#0F766E',
                backgroundColor: 'rgba(15, 118, 110, 0.03)',
                borderWidth: 2.2,
                tension: 0.4,
                pointBackgroundColor: '#0F766E',
                pointBorderColor: '#0F766E',
                pointRadius: 4.5,
                pointHoverRadius: 6.5,
                fill: true
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: { 
                    grid: { color: '#F1F5F9' }, 
                    ticks: { color: '#6B7280', font: { family: 'Inter', size: 11 } } 
                },
                x: { 
                    grid: { display: false }, 
                    ticks: { color: '#6B7280', font: { family: 'Inter', size: 11 } } 
                }
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


async function triggerEmergencyDispatch(sourcePhc, targetPhc, medicineName, quantity) {
    try {
        const res = await fetch("/api/redistribution/action", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                source_phc: sourcePhc,
                target_phc: targetPhc,
                medicine_name: medicineName,
                quantity: quantity,
                action: "APPROVE"
            })
        });

        const data = await res.json();
        if (data.status === "success") {
            alert(`🚨 EMERGENCY DISPATCH EXECUTED & NOTIFICATION SENT!\n\n${data.message}\n\nBoth ${sourcePhc} (Donor) and ${targetPhc} (Recipient) Medical Officers have been notified.`);
            loadDistrictData();
            loadPHCDashboard(activePhcId);
            loadRedistributionRecommendations();
        } else {
            alert("Dispatch failed: " + (data.detail || data.message));
        }
    } catch (err) {
        alert("Error executing emergency dispatch.");
    }
}

// -------------------------------------------------------------
// 2. DISTRICT AGGREGATION LOGIC
// -------------------------------------------------------------
async function loadDistrictData() {
    try {
        const res = await fetch("/api/dashboard/district");
        const data = await res.json();

        // 1. Emergency Logistics Dispatch Banner Update
        const recs = data.emergency_logistics_recommendations || [];
        if (recs.length > 0) {
            const topRec = recs[0];
            const targetEl = document.getElementById("disp-target-phc");
            if (targetEl) targetEl.innerText = `${topRec.target_phc} (Shortage Node)`;
            
            const shortEl = document.getElementById("disp-shortage-item");
            if (shortEl) shortEl.innerHTML = `${topRec.medicine_name}: <strong>${topRec.explainability_underlying_numbers.target_phc_current_stock} units left</strong> (< 30% Par)`;

            const sourceEl = document.getElementById("disp-source-phc");
            if (sourceEl) sourceEl.innerText = `${topRec.source_phc} (Nearest Donor)`;

            const donorStockEl = document.getElementById("disp-donor-stock");
            if (donorStockEl) donorStockEl.innerHTML = `Surplus Stock: <strong>${topRec.explainability_underlying_numbers.donor_phc_current_stock} units available</strong>`;

            const matrixEl = document.getElementById("disp-matrix-info");
            if (matrixEl) matrixEl.innerHTML = `Distance: <strong>${topRec.distance_km} km</strong> | Fleet ETA: <strong>${topRec.eta_minutes} mins</strong>`;

            const fleetEl = document.getElementById("disp-fleet-tag");
            if (fleetEl) fleetEl.innerText = `${topRec.explainability_underlying_numbers.transport_tier} · Cost: $${topRec.transport_cost_usd}`;

            const actionBtn = document.querySelector(".btn-emergency-dispatch");
            if (actionBtn) {
                actionBtn.onclick = () => triggerEmergencyDispatch(topRec.source_phc, topRec.target_phc, topRec.medicine_name, topRec.recommended_quantity);
                actionBtn.innerText = `⚡ ONE-CLICK EMERGENCY DISPATCH ${topRec.recommended_quantity} ${topRec.medicine_name.toUpperCase()} FROM ${topRec.source_phc} TO ${topRec.target_phc}`;
            }
        }

        // 2. Outbreak Early Warning Radar Update
        const radar = data.outbreak_radar;
        if (radar) {
            const badge = document.getElementById("outbreak-probability-badge");
            if (badge) badge.innerText = `${radar.outbreak_probability_pct}% Outbreak Probability`;
            
            const body = document.getElementById("outbreak-radar-body");
            if (body) {
                body.innerHTML = `
                    <div style="display:flex; align-items:center; gap:12px; margin-bottom:10px;">
                        <div class="outbreak-score-circle">${Math.round(radar.outbreak_probability_pct)}%</div>
                        <div>
                            <div style="font-weight:700; color:var(--text-primary); font-size:0.95rem;">${radar.risk_level.replace('_', ' ')}</div>
                            <div style="font-size:0.8rem; color:var(--text-muted);">${radar.primary_trigger}</div>
                        </div>
                    </div>
                    <div class="code-block" style="font-size:0.75rem;">
                        <strong>Suspected Vector:</strong> ${radar.suspected_vector}<br>
                        <strong>Action Recommendation:</strong> ${radar.recommended_action}
                    </div>
                `;
            }
        }

        // 3. District Staff Radar Update
        const staffRadar = data.staff_radar;
        if (staffRadar) {
            const staffBadge = document.getElementById("district-staff-badge");
            if (staffBadge) staffBadge.innerText = `${staffRadar.availability_pct}% On Duty`;
            const totalStaffEl = document.getElementById("dist-total-staff");
            if (totalStaffEl) totalStaffEl.innerText = `${staffRadar.total_staff} Registered`;
            const checkedInEl = document.getElementById("dist-checkedin-staff");
            if (checkedInEl) checkedInEl.innerText = `${staffRadar.checked_in_staff} On Duty`;
        }

        // 4. GIS Spatial Health Nodes Grid
        const gisNodesBox = document.getElementById("gis-nodes-container");
        if (gisNodesBox && data.gis_spatial_nodes) {
            gisNodesBox.innerHTML = "";
            data.gis_spatial_nodes.forEach(node => {
                const isCritical = node.status === "CRITICAL_SHORTAGE";
                const isDonor = node.status === "HIGH_SURPLUS_DONOR";
                let badgeClass = "badge-info";
                let badgeText = "NORMAL";
                if (isCritical) { badgeClass = "badge-danger"; badgeText = "CRITICAL SHORTAGE"; }
                else if (isDonor) { badgeClass = "badge-success"; badgeText = "SURPLUS DONOR"; }

                const card = document.createElement("div");
                card.className = `gis-node-card ${isCritical ? 'critical-border' : isDonor ? 'donor-border' : ''}`;
                card.innerHTML = `
                    <div class="gis-node-header">
                        <span style="font-weight:700; font-size:0.85rem;">📍 ${node.phc_id}</span>
                        <span class="badge ${badgeClass}">${badgeText}</span>
                    </div>
                    <div class="gis-node-name">${node.name}</div>
                    <div style="font-size:0.75rem; color:var(--text-muted); font-family:var(--font-mono); margin-top:4px;">
                        Lat: ${node.lat}, Lng: ${node.lng}<br>
                        Distance from Hub: ${node.distance_from_hub_km} km
                    </div>
                `;
                gisNodesBox.appendChild(card);
            });
        }

        // 5. Warnings Banner & Table
        const warnings = data.critical_par_level_warnings;
        const tbody = document.querySelector("#district-warnings-table tbody");
        if (tbody) {
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
        }

        // 6. Aggregate DP Metrics
        const dpBox = document.getElementById("district-summary-metrics");
        if (dpBox) {
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
        }

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

        // 1. Render Explainability Box
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

        // 2. Render Staff Action Directives & Prescriptive Advice (USER REQUIREMENT)
        const directiveBadge = document.getElementById("staff-directive-badge");
        if (directiveBadge) {
            let bClass = "badge-success";
            if (forecast.risk_level === "CRITICAL") bClass = "badge-danger";
            else if (forecast.risk_level === "HIGH") bClass = "badge-warning";
            else if (forecast.risk_level === "MODERATE") bClass = "badge-info";
            directiveBadge.className = `badge ${bClass}`;
            directiveBadge.innerText = `STAFF URGENCY: ${forecast.risk_level}`;
        }

        const directiveText = document.getElementById("staff-directive-text");
        if (directiveText) {
            directiveText.innerHTML = `
                <strong style="font-size:0.95rem;">${forecast.staff_action_directive}</strong>
                <div style="font-size:0.8rem; color:var(--text-muted); margin-top:6px;">
                    Current Stock: <strong>${forecast.current_stock} units</strong> | Predicted Daily Demand: <strong>${forecast.predicted_next_day_demand} units/day</strong> | Days Cover: <strong>${forecast.days_of_stock_remaining} days</strong>
                </div>
            `;
        }

        const reqBtn = document.getElementById("btn-submit-requisition");
        if (reqBtn) {
            reqBtn.innerText = `📦 Submit Requisition Order (${forecast.suggested_reorder_qty} units) to Central Warehouse`;
        }

        // 3. Render 7-Day Depletion Timeline Table
        const timelineTbody = document.querySelector("#depletion-timeline-table tbody");
        if (timelineTbody && forecast.depletion_timeline) {
            timelineTbody.innerHTML = "";
            forecast.depletion_timeline.forEach(step => {
                const tr = document.createElement("tr");
                let statusPill = `<span class="badge badge-success">🟢 OPTIMAL</span>`;
                let actionText = "Normal Cover";
                if (step.is_critical_depletion) {
                    statusPill = `<span class="badge badge-danger">🔴 STOCKOUT / LOW</span>`;
                    actionText = "Reorder Threshold Reached!";
                } else if (step.projected_balance < forecast.par_level * 0.5) {
                    statusPill = `<span class="badge badge-warning">🟡 WATCH</span>`;
                    actionText = "Prepare Requisition";
                }

                tr.innerHTML = `
                    <td><strong>${step.day_label}</strong></td>
                    <td>${step.projected_demand} units/day</td>
                    <td><strong>${step.projected_balance} units</strong></td>
                    <td>${statusPill}</td>
                    <td><span style="font-size:0.775rem; color:var(--text-muted);">${actionText}</span></td>
                `;
                timelineTbody.appendChild(tr);
            });
        }

        // 4. Render Forecast Chart
        renderForecastChart(exp.daily_usage_array, forecast.predicted_next_day_demand);

    } catch (err) {
        console.error("Error updating forecast:", err);
    }
}

async function handleStaffRequisitionSubmit() {
    const phcId = document.getElementById("forecast-phc-select").value;
    const medName = document.getElementById("forecast-med-select").value;

    try {
        const res = await fetch("/api/forecasting/staff-requisition", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                phc_id: phcId,
                medicine_name: medName,
                requested_quantity: 160,
                urgency_level: "HIGH"
            })
        });

        const data = await res.json();
        alert(`📦 STAFF REQUISITION SUBMITTED SUCCESSFULLY!\n\n${data.message}\nRequisition ID: ${data.requisition_id}\nTimestamp: ${data.timestamp}`);
    } catch (err) {
        alert("Error submitting staff requisition order.");
    }
}

function handleEmergencyTransferTrigger() {
    switchTab('redistribution-panel', 'Redistribution Engine');
}

async function handleBroadcastNurseAlert() {
    const phcId = document.getElementById("forecast-phc-select").value;
    const medName = document.getElementById("forecast-med-select").value;

    try {
        const res = await fetch("/api/forecasting/broadcast-nurse-alert", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                phc_id: phcId,
                medicine_name: medName,
                message: `Supply Warning: ${medName} stock cover is low at ${phcId}. Prepare shift handoff inventory audit.`
            })
        });

        const data = await res.json();
        alert(`📢 NURSE BROADCAST ALERT DELIVERED!\n\n${data.message}\nTimestamp: ${data.timestamp}`);
    } catch (err) {
        alert("Error broadcasting nurse alert.");
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
// 7. NATIONAL HEALTH COMMAND CENTER LOGIC
// -------------------------------------------------------------
async function loadNationalDashboard() {
    try {
        const res = await fetch("/api/dashboard/national");
        const data = await res.json();

        // 1. National KPIs
        const kpis = data.national_kpis;
        if (kpis) {
            const nodesVal = document.getElementById("nat-nodes-value");
            if (nodesVal) nodesVal.innerHTML = `${kpis.total_phc_nodes} <span class="metric-total">Active</span>`;
            const nodesSub = document.getElementById("nat-nodes-sub");
            if (nodesSub) nodesSub.innerText = `${kpis.online_nodes} of ${kpis.total_phc_nodes} Online`;

            const bedsVal = document.getElementById("nat-beds-value");
            if (bedsVal) bedsVal.innerHTML = `${kpis.occupied_beds} <span class="metric-total">/ ${kpis.total_beds}</span>`;
            const bedsSub = document.getElementById("nat-beds-sub");
            if (bedsSub) bedsSub.innerText = `${kpis.occupancy_pct}% Occupied`;

            const medsVal = document.getElementById("nat-meds-value");
            if (medsVal) medsVal.innerHTML = `${kpis.total_inventory_units.toLocaleString()} <span class="metric-total">units</span>`;

            const alertsVal = document.getElementById("nat-alerts-value");
            if (alertsVal) alertsVal.innerHTML = `${kpis.critical_alerts_count} <span class="metric-total">shortages</span>`;
            const alertsSub = document.getElementById("nat-alerts-sub");
            if (alertsSub) alertsSub.innerText = kpis.critical_alerts_count > 0 ? "Action required" : "All optimal";
        }

        // 2. National Strategic Reserve Table
        const reserveTbody = document.querySelector("#national-strategic-reserve-table tbody");
        if (reserveTbody && data.strategic_reserve) {
            reserveTbody.innerHTML = "";
            data.strategic_reserve.forEach(med => {
                const tr = document.createElement("tr");
                let statusBadge = `<span class="badge badge-success">🟢 OPTIMAL RESERVE</span>`;
                if (med.status === "CRITICAL_DEFICIT") {
                    statusBadge = `<span class="badge badge-danger">🔴 CRITICAL DEFICIT</span>`;
                } else if (med.status === "WATCH") {
                    statusBadge = `<span class="badge badge-warning">🟡 WATCH LIST</span>`;
                }

                tr.innerHTML = `
                    <td><strong>${med.medicine_name}</strong></td>
                    <td><span class="stock-val">${med.national_stock}</span> <span class="unit-text">units</span></td>
                    <td class="par-val">${med.national_par_baseline} units</td>
                    <td><strong>${med.pct_of_par}%</strong></td>
                    <td>${statusBadge}</td>
                `;
                reserveTbody.appendChild(tr);
            });
        }

        // 3. National Inter-District Transfers Table
        const transfersTbody = document.querySelector("#national-transfers-table tbody");
        if (transfersTbody && data.transfer_history) {
            transfersTbody.innerHTML = "";
            if (data.transfer_history.length === 0) {
                transfersTbody.innerHTML = `<tr><td colspan="7" style="color:var(--text-muted); padding:12px;">No inter-district transfers executed yet.</td></tr>`;
            } else {
                data.transfer_history.forEach(t => {
                    const tr = document.createElement("tr");
                    let statusBadge = `<span class="badge badge-success">${t.status}</span>`;
                    if (t.status === "REJECTED") statusBadge = `<span class="badge badge-danger">${t.status}</span>`;

                    tr.innerHTML = `
                        <td><code>#TR-${t.id}</code></td>
                        <td><strong>${t.source_phc}</strong></td>
                        <td><strong>${t.target_phc}</strong></td>
                        <td>${t.medicine_name}</td>
                        <td><strong>${t.quantity} units</strong></td>
                        <td>${t.eta_mins} mins</td>
                        <td>${statusBadge}</td>
                    `;
                    transfersTbody.appendChild(tr);
                });
            }
        }

    } catch (err) {
        console.error("Error loading National Dashboard:", err);
    }
}


// -------------------------------------------------------------
// 8. ENTERPRISE CONTROL CENTER HANDLERS (Q1-Q4 ROADMAP)
// -------------------------------------------------------------
async function runShadowPilotSimulation() {
    try {
        const res = await fetch("/api/pilot/shadow-simulation");
        const data = await res.json();
        document.getElementById("shadow-pilot-results").innerText = JSON.stringify(data, null, 2);
    } catch (err) {
        alert("Failed to run shadow simulation.");
    }
}

async function exportFHIRBundle() {
    try {
        const res = await fetch("/api/fhir/export");
        const data = await res.json();
        document.getElementById("fhir-export-results").innerText = JSON.stringify(data, null, 2);
    } catch (err) {
        alert("Failed to export FHIR bundle.");
    }
}

async function verifyBatchPassport() {
    const bId = document.getElementById("batch-id-input").value;
    try {
        const res = await fetch(`/api/provenance/verify?batch_id=${encodeURIComponent(bId)}`);
        const data = await res.json();
        const box = document.getElementById("provenance-results");
        box.style.display = "block";
        box.innerText = JSON.stringify(data, null, 2);
    } catch (err) {
        alert("Failed to verify batch provenance.");
    }
}

async function testRBACAuth() {
    const val = document.getElementById("rbac-role-select").value;
    const parts = val.split(":");
    const user = parts[0];
    const pwd = parts[1];

    try {
        const res = await fetch(`/api/auth/login?username=${encodeURIComponent(user)}&password=${encodeURIComponent(pwd)}`, {
            method: "POST"
        });
        const data = await res.json();
        const box = document.getElementById("rbac-results");
        box.style.display = "block";
        box.innerText = JSON.stringify(data, null, 2);
    } catch (err) {
        alert("Authentication failed.");
    }
}

// -------------------------------------------------------------
// 9. RFID SMART CARD TERMINAL & NURSE ATTENDANCE HANDLERS
// -------------------------------------------------------------
let terminalClockInterval = null;

function startTerminalClock() {
    if (terminalClockInterval) clearInterval(terminalClockInterval);
    terminalClockInterval = setInterval(() => {
        const clockEl = document.getElementById("terminal-screen-clock");
        if (clockEl) {
            const now = new Date();
            clockEl.innerText = now.toLocaleTimeString();
        }
    }, 1000);
}

// -------------------------------------------------------------
// DEDICATED STAFF ATTENDANCE PAGE LOADER & STATE CONTROLLER
// -------------------------------------------------------------
async function loadStaffAttendancePage(phcId) {
    const targetPhc = phcId || activePhcId || "PHC-001";
    activePhcId = targetPhc;

    const selectEl = document.getElementById("attendance-phc-select");
    if (selectEl) selectEl.value = targetPhc;

    const dateDisplay = document.getElementById("attendance-date-display");
    const screenDate = document.getElementById("terminal-screen-date");
    const now = new Date();
    const dateFormatted = now.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric', year: 'numeric' });
    if (dateDisplay) dateDisplay.innerText = dateFormatted;
    if (screenDate) screenDate.innerText = `TERMINAL READY • ${dateFormatted}`;

    try {
        const [membersRes, attendanceRes] = await Promise.all([
            fetch(`/api/staff/members?phc_id=${targetPhc}`),
            fetch(`/api/staff?phc_id=${targetPhc}`)
        ]);

        const members = await membersRes.json();
        const attendanceRecords = await attendanceRes.json();
        currentStaffMembers = members || [];

        // Build status map (latest record per staff_id)
        const latestStatusMap = {};
        (attendanceRecords || []).forEach(rec => {
            if (!latestStatusMap[rec.staff_id]) {
                latestStatusMap[rec.staff_id] = rec;
            }
        });

        // Compute summary metrics across registered members
        let presentCount = 0;
        let absentCount = 0;
        let leaveCount = 0;
        let checkedOutCount = 0;

        const compositeRoster = currentStaffMembers.map(mem => {
            const rec = latestStatusMap[mem.staff_id];
            const status = rec ? rec.status : "ABSENT";
            if (status === "CHECKED_IN" || status === "LATE" || (rec && rec.present === 1 && status !== "CHECKED_OUT")) {
                presentCount++;
            } else if (status === "ON_LEAVE") {
                leaveCount++;
            } else if (status === "CHECKED_OUT") {
                checkedOutCount++;
            } else {
                absentCount++;
            }

            return {
                staff_id: mem.staff_id,
                name: mem.name,
                role: mem.role,
                card_uid: mem.card_uid,
                status: status,
                punch_in_time: rec ? rec.punch_in_time : "--",
                punch_out_time: rec ? rec.punch_out_time : "--",
                shift: rec && rec.shift ? rec.shift : "Morning Shift (08:00 - 16:00)",
                department: rec && rec.department ? rec.department : getDeptForRole(mem.role),
                verification_method: rec && rec.verification_method ? rec.verification_method : "N/A",
                last_updated: rec && rec.updated_at ? formatTimeAgo(rec.updated_at) : (rec && rec.punch_in_time ? rec.punch_in_time : "Today"),
                encrypted_id: rec ? rec.staff_id_encrypted : "",
                token: rec ? rec.staff_token : ("TOK-" + mem.staff_id.replace(/[^A-Z0-9]/g, '')),
                remarks: rec ? rec.remarks : ""
            };
        });

        currentAttendanceRosterData = compositeRoster;

        const totalStaff = currentStaffMembers.length;
        const onDutyPct = totalStaff > 0 ? Math.round((presentCount / totalStaff) * 100) : 0;

        // 1. Update Attendance Overview 5 KPI Cards
        const statTotal = document.getElementById("att-stat-total");
        if (statTotal) statTotal.innerHTML = `${totalStaff} <span class="unit">personnel</span>`;

        const statPresent = document.getElementById("att-stat-present");
        if (statPresent) statPresent.innerHTML = `${presentCount} <span class="unit">staff</span>`;

        const statAbsent = document.getElementById("att-stat-absent");
        if (statAbsent) statAbsent.innerHTML = `${absentCount} <span class="unit">staff</span>`;

        const statLeave = document.getElementById("att-stat-leave");
        if (statLeave) statLeave.innerHTML = `${leaveCount} <span class="unit">staff</span>`;

        const statOnDuty = document.getElementById("att-stat-onduty");
        if (statOnDuty) statOnDuty.innerText = `${onDutyPct}%`;
        const statOnDutySub = document.getElementById("att-stat-onduty-sub");
        if (statOnDutySub) statOnDutySub.innerText = `${presentCount} of ${totalStaff} staff active on duty`;

        // 2. Synchronize Summary Card on PHC Edge Dashboard
        const sumPresent = document.getElementById("phc-summary-present");
        if (sumPresent) sumPresent.innerHTML = `${presentCount} <span class="metric-total">staff</span>`;
        const sumAbsent = document.getElementById("phc-summary-absent");
        if (sumAbsent) sumAbsent.innerHTML = `${absentCount} <span class="metric-total">staff</span>`;
        const sumLeave = document.getElementById("phc-summary-leave");
        if (sumLeave) sumLeave.innerHTML = `${leaveCount} <span class="metric-total">staff</span>`;
        const sumOnDuty = document.getElementById("phc-summary-onduty-pct");
        if (sumOnDuty) sumOnDuty.innerText = `${onDutyPct}%`;
        const sumOnDutySub = document.getElementById("phc-summary-onduty-sub");
        if (sumOnDutySub) sumOnDutySub.innerText = `${presentCount} of ${totalStaff} staff on active duty`;

        // Top metric on PHC Dashboard
        const staffValEl = document.getElementById("phc-staff-value");
        if (staffValEl) staffValEl.innerHTML = `${presentCount} <span class="metric-total">/ ${totalStaff}</span>`;
        const staffSubEl = document.getElementById("phc-staff-sub");
        if (staffSubEl) staffSubEl.innerText = `${absentStaff} absent / off duty`;

        // 3. Populate Quick-Tap Demo Badges
        const quickBadgesBox = document.getElementById("rfid-quick-badges");
        if (quickBadgesBox) {
            quickBadgesBox.innerHTML = "";
            currentStaffMembers.forEach(mem => {
                const rec = latestStatusMap[mem.staff_id];
                const isPresent = rec && (rec.status === "CHECKED_IN" || rec.status === "LATE");
                const isLeave = rec && rec.status === "ON_LEAVE";
                const isCheckedOut = rec && rec.status === "CHECKED_OUT";

                let statusDot = isPresent ? "🟢" : (isLeave ? "🟡" : (isCheckedOut ? "🔵" : "🔴"));
                const btn = document.createElement("button");
                btn.className = "rfid-badge-btn";
                btn.innerHTML = `
                    <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                        <div>
                            <strong>${mem.name}</strong>
                            <div style="font-size:0.7rem; color:var(--text-muted);">${mem.role}</div>
                        </div>
                        <span style="font-size:0.8rem;">${statusDot}</span>
                    </div>
                    <div style="display:flex; justify-content:space-between; margin-top:4px; font-family:var(--font-mono); font-size:0.7rem;">
                        <span style="color:#38BDF8;">${mem.card_uid}</span>
                        <span style="color:var(--text-muted);">${mem.staff_id}</span>
                    </div>
                `;
                btn.onclick = () => triggerCardPunch(mem.card_uid);
                quickBadgesBox.appendChild(btn);
            });
        }

        // 4. Populate Manual Entry Dropdown
        const kioskSelect = document.getElementById("kiosk-staff-select");
        if (kioskSelect) {
            kioskSelect.innerHTML = `<option value="" disabled selected>-- Select Staff Member / Nurse --</option>`;
            currentStaffMembers.forEach(mem => {
                const opt = document.createElement("option");
                opt.value = mem.staff_id;
                opt.textContent = `${mem.name} (${mem.role}) — ${mem.staff_id}`;
                kioskSelect.appendChild(opt);
            });
        }

        // 5. Render Live Roster Table
        filterAttendanceRoster();

        // 6. Render Privacy Audit Log
        renderPrivacyAuditLog(attendanceRecords || []);

    } catch (err) {
        console.error("Error loading Staff Attendance page:", err);
    }
}

// -------------------------------------------------------------
// LIVE ATTENDANCE ROSTER FILTER & RENDER FUNCTIONS
// -------------------------------------------------------------
function filterAttendanceRoster() {
    const searchEl = document.getElementById("att-filter-search");
    const statusEl = document.getElementById("att-filter-status");
    const shiftEl = document.getElementById("att-filter-shift");

    const search = searchEl ? searchEl.value.trim().toLowerCase() : "";
    const status = statusEl ? statusEl.value : "ALL";
    const shift = shiftEl ? shiftEl.value : "ALL";

    let filtered = currentAttendanceRosterData.filter(item => {
        // Search filter
        if (search) {
            const matchesSearch = item.name.toLowerCase().includes(search) ||
                                  item.staff_id.toLowerCase().includes(search) ||
                                  item.role.toLowerCase().includes(search) ||
                                  item.card_uid.toLowerCase().includes(search);
            if (!matchesSearch) return false;
        }

        // Status filter
        if (status !== "ALL") {
            if (status === "CHECKED_IN" && item.status !== "CHECKED_IN") return false;
            if (status === "CHECKED_OUT" && item.status !== "CHECKED_OUT") return false;
            if (status === "LATE" && item.status !== "LATE") return false;
            if (status === "ON_LEAVE" && item.status !== "ON_LEAVE") return false;
            if (status === "ABSENT" && item.status !== "ABSENT") return false;
        }

        // Shift filter
        if (shift !== "ALL") {
            const shiftOrDept = (item.shift + " " + item.department).toLowerCase();
            if (!shiftOrDept.includes(shift.toLowerCase())) return false;
        }

        return true;
    });

    renderAttendanceRoster(filtered);
}

function renderAttendanceRoster(records) {
    const tbody = document.getElementById("staff-roster-tbody");
    const emptyState = document.getElementById("staff-roster-empty");
    const tableEl = document.getElementById("staff-roster-table");

    if (!tbody) return;
    tbody.innerHTML = "";

    if (!records || records.length === 0) {
        if (emptyState) emptyState.style.display = "block";
        if (tableEl) tableEl.style.display = "none";
        return;
    }

    if (emptyState) emptyState.style.display = "none";
    if (tableEl) tableEl.style.display = "table";

    records.forEach(stf => {
        const tr = document.createElement("tr");

        let statusBadge = "";
        let actionButtons = "";

        if (stf.status === "CHECKED_IN") {
            statusBadge = `<span class="badge-status badge-present">● Present</span>`;
            actionButtons = `
                <button class="btn-table-action danger" onclick="handleStaffQuickAction('${stf.staff_id}', 'CHECK_OUT')">Check Out</button>
                <button class="btn-table-action" onclick="handleStaffQuickAction('${stf.staff_id}', 'MARK_LEAVE')">Leave</button>
            `;
        } else if (stf.status === "LATE") {
            statusBadge = `<span class="badge-status badge-late">⏱️ Late</span>`;
            actionButtons = `
                <button class="btn-table-action danger" onclick="handleStaffQuickAction('${stf.staff_id}', 'CHECK_OUT')">Check Out</button>
                <button class="btn-table-action" onclick="handleStaffQuickAction('${stf.staff_id}', 'MARK_LEAVE')">Leave</button>
            `;
        } else if (stf.status === "CHECKED_OUT") {
            statusBadge = `<span class="badge-status badge-checked-out">↩ Checked Out</span>`;
            actionButtons = `
                <button class="btn-table-action primary" onclick="handleStaffQuickAction('${stf.staff_id}', 'CHECK_IN')">Check In</button>
                <button class="btn-table-action" onclick="handleStaffQuickAction('${stf.staff_id}', 'MARK_LEAVE')">Leave</button>
            `;
        } else if (stf.status === "ON_LEAVE") {
            statusBadge = `<span class="badge-status badge-leave">🏖️ On Leave</span>`;
            actionButtons = `
                <button class="btn-table-action primary" onclick="handleStaffQuickAction('${stf.staff_id}', 'CHECK_IN')">Return to Duty</button>
            `;
        } else {
            statusBadge = `<span class="badge-status badge-absent">✕ Absent</span>`;
            actionButtons = `
                <button class="btn-table-action primary" onclick="handleStaffQuickAction('${stf.staff_id}', 'CHECK_IN')">Check In</button>
                <button class="btn-table-action" onclick="handleStaffQuickAction('${stf.staff_id}', 'MARK_LEAVE')">Sanction Leave</button>
            `;
        }

        tr.innerHTML = `
            <td><code>${stf.staff_id}</code></td>
            <td>
                <strong>${stf.name}</strong><br>
                <small style="font-family:var(--font-mono); color:var(--text-muted);">${stf.card_uid}</small>
            </td>
            <td><span style="font-size:0.8rem; color:var(--text-secondary);">${stf.role}</span></td>
            <td>${statusBadge}</td>
            <td><span style="font-size:0.8rem; font-family:var(--font-mono); font-weight:600;">${stf.punch_in_time || '--'}</span></td>
            <td><span style="font-size:0.8rem; font-family:var(--font-mono); color:var(--text-muted);">${stf.punch_out_time || '--'}</span></td>
            <td>
                <span style="font-size:0.8rem; font-weight:600;">${stf.department}</span><br>
                <small style="font-size:0.7rem; color:var(--text-muted);">${stf.shift}</small>
            </td>
            <td><span class="badge badge-secondary" style="font-size:0.7rem;">${stf.verification_method}</span></td>
            <td><span style="font-size:0.75rem; color:var(--text-muted); font-family:var(--font-mono);">${stf.last_updated}</span></td>
            <td style="text-align:right;">
                <div style="display:inline-flex; gap:6px; justify-content:flex-end;">
                    ${actionButtons}
                </div>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function resetAttendanceFilters() {
    const s = document.getElementById("att-filter-search");
    const st = document.getElementById("att-filter-status");
    const sh = document.getElementById("att-filter-shift");
    const d = document.getElementById("att-filter-date");
    if (s) s.value = "";
    if (st) st.value = "ALL";
    if (sh) sh.value = "ALL";
    if (d) d.value = "";
    filterAttendanceRoster();
}

function refreshStaffAttendanceData() {
    loadStaffAttendancePage(activePhcId);
}

function handleAttendancePhcChange(newPhcId) {
    activePhcId = newPhcId;
    const phcSelect = document.getElementById("phc-select");
    if (phcSelect) phcSelect.value = newPhcId;
    loadStaffAttendancePage(newPhcId);
    loadPHCDashboard(newPhcId);
}

// -------------------------------------------------------------
// PRIVACY-PRESERVED AUDIT LOG RENDERER
// -------------------------------------------------------------
function renderPrivacyAuditLog(records) {
    const tbody = document.getElementById("staff-audit-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    if (!records || records.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:var(--text-muted); padding:20px;">No audit events recorded yet.</td></tr>`;
        return;
    }

    records.slice(0, 15).forEach(rec => {
        const tr = document.createElement("tr");

        let actionPill = `<span class="badge badge-success">CHECK-IN</span>`;
        if (rec.status === "CHECKED_OUT") actionPill = `<span class="badge badge-info">CHECK-OUT</span>`;
        else if (rec.status === "ON_LEAVE") actionPill = `<span class="badge badge-warning">LEAVE_LOGGED</span>`;
        else if (rec.status === "LATE") actionPill = `<span class="badge badge-purple">LATE_ENTRY</span>`;
        else if (rec.status === "ABSENT") actionPill = `<span class="badge badge-danger">ABSENT_FLAG</span>`;

        const cipherSnippet = (rec.staff_id_encrypted || '').substring(0, 20) + '...';
        const timestamp = rec.updated_at ? formatTime(rec.updated_at) : (rec.date + " " + (rec.punch_in_time || "08:00 AM"));

        tr.innerHTML = `
            <td><span style="font-size:0.75rem; font-family:var(--font-mono);">${timestamp}</span></td>
            <td>
                <strong style="font-family:var(--font-mono); color:var(--accent-teal);">${rec.staff_token || 'TOK-ANON'}</strong><br>
                <code style="font-size:0.68rem; color:var(--text-muted);">${cipherSnippet}</code>
            </td>
            <td>${actionPill}</td>
            <td><span class="badge badge-secondary" style="font-size:0.7rem;">${rec.verification_method || 'RFID Reader'}</span></td>
            <td><span style="font-size:0.75rem; font-family:var(--font-mono);">${rec.operator || 'TERMINAL-PHC-GATE1'}</span></td>
            <td><span style="font-size:0.75rem; color:var(--text-secondary);">${rec.remarks || 'Routine shift punch'}</span></td>
            <td><span class="badge badge-success" style="font-size:0.7rem;">VERIFIED</span></td>
        `;
        tbody.appendChild(tr);
    });
}

// -------------------------------------------------------------
// RFID CARD PUNCH WITH 15-SECOND ACCIDENTAL DUPLICATE LOCKOUT
// -------------------------------------------------------------
async function triggerCardPunch(cardUid) {
    const ledEl = document.getElementById("terminal-led");
    const msgEl = document.getElementById("terminal-screen-msg");
    const dupBanner = document.getElementById("terminal-duplicate-banner");
    const dupMsg = document.getElementById("terminal-duplicate-msg");
    const verBox = document.getElementById("terminal-verification-box");

    // Client-side 15-second duplicate punch lockout
    const nowMs = Date.now();
    if (lastPunchTimes[cardUid] && (nowMs - lastPunchTimes[cardUid]) < 15000) {
        const remainingSecs = Math.ceil((15000 - (nowMs - lastPunchTimes[cardUid])) / 1000);
        if (dupBanner && dupMsg) {
            dupMsg.innerText = `Duplicate scan prevented: Card UID ${cardUid} was just scanned. Please wait ${remainingSecs}s before punching again.`;
            dupBanner.style.display = "flex";
            setTimeout(() => { if (dupBanner) dupBanner.style.display = "none"; }, 4000);
        }
        if (ledEl) ledEl.className = "led-ring yellow";
        if (msgEl) msgEl.innerText = `⚠️ DUPLICATE SCAN PREVENTED (${remainingSecs}s lockout)`;
        playTerminalChime(false);
        return;
    }

    if (ledEl) ledEl.className = "led-ring yellow";
    if (msgEl) msgEl.innerText = "READING CARD UID: " + cardUid + "...";

    try {
        const res = await fetch("/api/staff/card-punch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                card_uid: cardUid,
                phc_id: activePhcId,
                verification_method: "RFID Smart Card Punch",
                operator: "TERMINAL-PHC-GATE1"
            })
        });

        const result = await res.json();

        if (res.ok && result.status === "success") {
            lastPunchTimes[cardUid] = Date.now();
            if (dupBanner) dupBanner.style.display = "none";
            if (ledEl) ledEl.className = "led-ring green";
            if (msgEl) {
                msgEl.innerText = `✅ CARD ACCEPTED: ${result.staff_name.toUpperCase()} (${result.role}) - ${result.action} AT ${result.punch_time}`;
            }

            // Show verification result card
            if (verBox) {
                const initials = result.staff_name.split(" ").map(w => w[0]).join("").substring(0, 2);
                const avatarEl = document.getElementById("terminal-ver-avatar");
                const nameEl = document.getElementById("terminal-ver-name");
                const roleEl = document.getElementById("terminal-ver-role");
                const tokenEl = document.getElementById("terminal-ver-token");
                if (avatarEl) avatarEl.innerText = initials;
                if (nameEl) nameEl.innerText = result.staff_name;
                if (roleEl) roleEl.innerText = `${result.role} • ${result.action} at ${result.punch_time}`;
                if (tokenEl) tokenEl.innerText = `TOKEN: ${result.token}`;
                verBox.style.display = "flex";
            }

            playTerminalChime(true);
            await loadStaffAttendancePage(activePhcId);
            await loadPHCDashboard(activePhcId);
            await loadDistrictData();
        } else {
            if (ledEl) ledEl.className = "led-ring red";
            const errDetail = result.detail || "Card UID not registered";
            if (msgEl) msgEl.innerText = `❌ REJECTED: ${errDetail}`;
            if (errDetail.includes("Duplicate") && dupBanner && dupMsg) {
                dupMsg.innerText = errDetail;
                dupBanner.style.display = "flex";
                setTimeout(() => { if (dupBanner) dupBanner.style.display = "none"; }, 4000);
            }
            playTerminalChime(false);
        }
    } catch (err) {
        if (ledEl) ledEl.className = "led-ring red";
        if (msgEl) msgEl.innerText = "❌ ERROR CONNECTING TO RFID CARD TERMINAL";
        playTerminalChime(false);
    }
}

function triggerCardScanInput() {
    const inputEl = document.getElementById("rfid-input-field");
    if (inputEl && inputEl.value.trim()) {
        const uid = inputEl.value.trim();
        triggerCardPunch(uid);
        inputEl.value = "";
    }
}

// -------------------------------------------------------------
// MANUAL ATTENDANCE ENTRY HANDLER WITH VALIDATION & FEEDBACK
// -------------------------------------------------------------
async function handleManualAttendanceSubmit(event) {
    event.preventDefault();
    const staffId = document.getElementById("kiosk-staff-select").value;
    const statusVal = document.getElementById("kiosk-status-select").value;
    const shiftVal = document.getElementById("kiosk-shift-select").value;
    const deptVal = document.getElementById("kiosk-dept-select") ? document.getElementById("kiosk-dept-select").value : "General";
    const methodVal = document.getElementById("kiosk-method-select").value;
    const remarksInput = document.getElementById("kiosk-remarks-input");
    const remarksVal = remarksInput ? remarksInput.value.trim() : "";
    const alertBox = document.getElementById("kiosk-alert-feedback");
    const alertMsg = document.getElementById("kiosk-alert-msg");

    if (!staffId) {
        if (alertBox && alertMsg) {
            alertMsg.innerText = "Please select a staff member from the roster.";
            alertBox.className = "att-inline-alert error";
            setTimeout(() => { alertBox.className = "att-inline-alert"; }, 4000);
        }
        return;
    }

    try {
        const isPresent = (statusVal === "ABSENT" || statusVal === "ON_LEAVE") ? 0 : 1;
        const res = await fetch("/api/staff/log", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                phc_id: activePhcId,
                staff_id: staffId,
                present: isPresent,
                status: statusVal,
                shift: shiftVal,
                department: deptVal,
                verification_method: methodVal,
                remarks: remarksVal || `Manual status update: ${statusVal}`,
                operator: "Supervisor Kiosk"
            })
        });

        const data = await res.json();
        if (res.ok && data.status === "success") {
            if (alertBox && alertMsg) {
                alertMsg.innerText = `✅ Attendance successfully recorded for ${data.staff_name || staffId}: ${statusVal} (${shiftVal})`;
                alertBox.className = "att-inline-alert success";
                setTimeout(() => { alertBox.className = "att-inline-alert"; }, 4000);
            }
            if (remarksInput) remarksInput.value = "";
            playTerminalChime(true);
            await loadStaffAttendancePage(activePhcId);
            await loadPHCDashboard(activePhcId);
            await loadDistrictData();
        } else {
            if (alertBox && alertMsg) {
                alertMsg.innerText = `❌ Error: ${data.detail || "Failed to log attendance"}`;
                alertBox.className = "att-inline-alert error";
                setTimeout(() => { alertBox.className = "att-inline-alert"; }, 4000);
            }
            playTerminalChime(false);
        }
    } catch (err) {
        if (alertBox && alertMsg) {
            alertMsg.innerText = "❌ Network error submitting manual attendance.";
            alertBox.className = "att-inline-alert error";
            setTimeout(() => { alertBox.className = "att-inline-alert"; }, 4000);
        }
        playTerminalChime(false);
    }
}

// -------------------------------------------------------------
// TABLE QUICK ACTIONS (CHECK-OUT, LEAVE, RETURN TO DUTY)
// -------------------------------------------------------------
async function handleStaffQuickAction(staffId, action) {
    try {
        const res = await fetch("/api/staff/action", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                staff_id: staffId,
                action: action,
                phc_id: activePhcId,
                remarks: `Quick table action: ${action}`,
                operator: "Table Roster Quick-Action"
            })
        });

        const data = await res.json();
        if (res.ok && data.status === "success") {
            playTerminalChime(true);
            await loadStaffAttendancePage(activePhcId);
            await loadPHCDashboard(activePhcId);
            await loadDistrictData();
        } else {
            alert(`Action failed: ${data.detail || "Unknown error"}`);
        }
    } catch (err) {
        alert("Error executing staff action.");
    }
}

// -------------------------------------------------------------
// HELPER UTILITIES
// -------------------------------------------------------------
function getDeptForRole(role) {
    if (!role) return "General Ward";
    if (role.includes("ICU")) return "Intensive Care Unit (ICU)";
    if (role.includes("Emergency") || role.includes("Trauma")) return "Emergency & Trauma";
    if (role.includes("Pharmacist")) return "Central Pharmacy";
    if (role.includes("Lab")) return "Pathology Lab";
    if (role.includes("Pediatric")) return "Pediatrics";
    if (role.includes("Transport") || role.includes("Ambulance") || role.includes("Paramedic")) return "Ambulance Logistics";
    if (role.includes("OPD")) return "General OPD";
    return "General Ward";
}

function formatTimeAgo(isoString) {
    if (!isoString) return "Today";
    try {
        const d = new Date(isoString);
        if (isNaN(d.getTime())) return "Today";
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch (e) {
        return "Today";
    }
}

function formatTime(isoString) {
    if (!isoString) return "Today";
    try {
        const d = new Date(isoString);
        if (isNaN(d.getTime())) return isoString;
        return d.toLocaleDateString() + " " + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
    } catch (e) {
        return isoString;
    }
}

function playTerminalChime(isSuccess) {
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        
        osc.type = "sine";
        osc.frequency.setValueAtTime(isSuccess ? 880 : 220, ctx.currentTime);
        gain.gain.setValueAtTime(0.1, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + 0.3);
        
        osc.start();
        osc.stop(ctx.currentTime + 0.3);
    } catch (e) {
        // AudioContext audio output
    }
}


