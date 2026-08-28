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
    loadNationalDashboard();
    startTerminalClock();
});

// TAB SWITCHING
function switchTab(tabId, titleText) {
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

    if (tabId === 'forecasting-panel') updateForecastView();
    if (tabId === 'national-dashboard') loadNationalDashboard();
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
        const totalStaff = Math.max(staffMembers.length, 5);
        const checkedInStaff = data.staff_attendance.filter(s => s.status === "CHECKED_IN" || s.present === 1).length;
        const absentStaff = Math.max(0, totalStaff - checkedInStaff);

        const staffValEl = document.getElementById("phc-staff-value");
        if (staffValEl) staffValEl.innerHTML = `${checkedInStaff} <span class="metric-total">/ ${totalStaff}</span>`;
        const staffSubEl = document.getElementById("phc-staff-sub");
        if (staffSubEl) staffSubEl.innerText = `${absentStaff} absent / off duty`;

        // Populate Quick-Tap RFID Staff Badges
        const quickBadgesBox = document.getElementById("rfid-quick-badges");
        if (quickBadgesBox && staffMembers.length > 0) {
            quickBadgesBox.innerHTML = "";
            staffMembers.forEach(mem => {
                const btn = document.createElement("button");
                btn.className = "rfid-badge-btn";
                btn.innerHTML = `💳 <strong>${mem.name}</strong> (${mem.role})<br><small style="font-family:var(--font-mono); color:var(--text-accent);">${mem.card_uid}</small>`;
                btn.onclick = () => triggerCardPunch(mem.card_uid);
                quickBadgesBox.appendChild(btn);
            });
        }

        // Populate Kiosk Staff Select Dropdown
        const kioskSelect = document.getElementById("kiosk-staff-select");
        if (kioskSelect && staffMembers.length > 0) {
            kioskSelect.innerHTML = `<option value="" disabled selected>-- Select Staff Member / Nurse --</option>`;
            staffMembers.forEach(mem => {
                const opt = document.createElement("option");
                opt.value = mem.staff_id;
                opt.textContent = `${mem.name} (${mem.role}) — ${mem.staff_id}`;
                kioskSelect.appendChild(opt);
            });
        }

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

        // 4. Render Staff Attendance Table
        const staffTbody = document.querySelector("#staff-table tbody");
        if (staffTbody) {
            staffTbody.innerHTML = "";
            data.staff_attendance.forEach(stf => {
                const tr = document.createElement("tr");
                const isCheckedIn = stf.status === "CHECKED_IN" || stf.present === 1;
                const statusBadge = isCheckedIn 
                    ? '<span class="badge badge-success">🟢 CHECKED IN</span>' 
                    : '<span class="badge badge-danger">🔴 CHECKED OUT / ABSENT</span>';

                tr.innerHTML = `
                    <td>
                        <strong>${stf.staff_name || stf.staff_id}</strong><br>
                        <span style="font-size:0.75rem; color:var(--text-muted);">${stf.role || 'Healthcare Staff'}</span>
                    </td>
                    <td><span class="card-uid-pill">${stf.card_uid || 'N/A'}</span></td>
                    <td>${statusBadge}</td>
                    <td>
                        <span style="font-size:0.8rem; font-family:var(--font-mono);">In: ${stf.punch_in_time || '08:00 AM'}</span><br>
                        <span style="font-size:0.75rem; color:var(--text-muted); font-family:var(--font-mono);">Out: ${stf.punch_out_time || '--'}</span>
                    </td>
                    <td><span class="badge badge-secondary" style="font-size:0.7rem;">${stf.verification_method || 'RFID Card'}</span></td>
                    <td><code style="font-size:0.7rem;">${(stf.staff_id_encrypted || '').substring(0, 20)}...</code></td>
                    <td><code style="font-size:0.75rem;">${stf.staff_token || ''}</code></td>
                `;
                staffTbody.appendChild(tr);
            });
        }

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

async function triggerCardPunch(cardUid) {
    const ledEl = document.getElementById("terminal-led");
    const msgEl = document.getElementById("terminal-screen-msg");

    if (ledEl) ledEl.className = "led-ring yellow";
    if (msgEl) msgEl.innerText = "READING CARD UID: " + cardUid + "...";

    try {
        const res = await fetch("/api/staff/card-punch", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                card_uid: cardUid,
                phc_id: activePhcId,
                verification_method: "RFID Smart Card Punch"
            })
        });

        const result = await res.json();

        if (res.ok && result.status === "success") {
            if (ledEl) ledEl.className = "led-ring green";
            if (msgEl) {
                msgEl.innerText = `✅ CARD ACCEPTED: ${result.staff_name.toUpperCase()} (${result.role}) - ${result.action} AT ${result.punch_time}`;
            }
            playTerminalChime(true);
            await loadPHCDashboard(activePhcId);
        } else {
            if (ledEl) ledEl.className = "led-ring red";
            if (msgEl) msgEl.innerText = `❌ REJECTED: ${result.detail || "Card UID not registered"}`;
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

async function handleManualAttendanceSubmit(event) {
    event.preventDefault();
    const staffId = document.getElementById("kiosk-staff-select").value;
    const statusVal = document.getElementById("kiosk-status-select").value;
    const shiftVal = document.getElementById("kiosk-shift-select").value;
    const methodVal = document.getElementById("kiosk-method-select").value;

    if (!staffId) {
        alert("Please select a staff member");
        return;
    }

    try {
        const isPresent = statusVal === "ABSENT" ? 0 : 1;
        const res = await fetch("/api/staff/log", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                phc_id: activePhcId,
                staff_id: staffId,
                present: isPresent,
                status: statusVal,
                verification_method: `${methodVal} (${shiftVal})`
            })
        });

        const data = await res.json();
        if (data.status === "success") {
            alert(`Attendance logged successfully for ${data.staff_name || staffId}`);
            loadPHCDashboard(activePhcId);
        }
    } catch (err) {
        alert("Error submitting manual attendance check-in.");
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

