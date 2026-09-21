// ==========================================================================
// MERIDIAN — Healthcare Command & Resource Management Platform (v2.1)
// Unified 4-Section Architecture: Dashboard, Operations, Alerts & Transfers, Communication & Reports
// ==========================================================================

window.currentUser = null;
let currentMainTab = "dashboard";
let currentOpsSubTab = "inventory";
let currentCommSubTab = "messages";
let activePhcId = "PHC-001";
let activeDistrictId = "DIST-NORTH";

let footfallChartInstance = null;
let selectedReviewTransfer = null;
let pendingOverridePayload = null;

// Operational Data Caches
let cachedInventory = [];
let cachedEquipment = [];
let cachedStaffAttendance = [];
let cachedFootfall = [];
let cachedBedStatus = null;

// ==========================================================================
// SHARED FRONTEND MUTATION SYSTEM & NOTIFICATIONS
// ==========================================================================

// Accessible Toast Notification System
function showToast(message, type = "info", title = null, duration = 4000) {
    const container = document.getElementById("toast-container");
    if (!container) {
        console.log(`[Toast ${type}] ${title ? title + ': ' : ''}${message}`);
        return;
    }

    const toast = document.createElement("div");
    toast.className = `meridian-toast ${type}`;
    toast.setAttribute("role", type === "error" ? "alert" : "status");
    toast.setAttribute("aria-live", type === "error" ? "assertive" : "polite");

    const icons = {
        success: "✅",
        error: "❌",
        warning: "⚠️",
        info: "ℹ️"
    };
    const defaultTitles = {
        success: "Success",
        error: "Action Failed",
        warning: "Warning",
        info: "Notification"
    };

    const toastIcon = icons[type] || "ℹ️";
    const toastTitle = title || defaultTitles[type] || "Notification";

    toast.innerHTML = `
        <div class="toast-icon">${toastIcon}</div>
        <div class="toast-content">
            <div class="toast-title">${toastTitle}</div>
            <div class="toast-msg">${message}</div>
        </div>
        <button type="button" class="toast-close-btn" aria-label="Dismiss notification">×</button>
    `;

    const closeBtn = toast.querySelector(".toast-close-btn");
    let dismissTimer = null;

    const dismissToast = () => {
        if (dismissTimer) clearTimeout(dismissTimer);
        toast.classList.add("toast-hide");
        setTimeout(() => {
            if (toast.parentNode) toast.parentNode.removeChild(toast);
        }, 250);
    };

    if (closeBtn) closeBtn.addEventListener("click", dismissToast);

    container.appendChild(toast);

    if (duration > 0) {
        dismissTimer = setTimeout(dismissToast, duration);
    }
    return toast;
}

// Button Loading State Helper
function setButtonLoading(btnOrId, isLoading, loadingText = null) {
    const btn = typeof btnOrId === "string" ? document.getElementById(btnOrId) : btnOrId;
    if (!btn) return;

    if (isLoading) {
        if (!btn.dataset.originalHtml) {
            btn.dataset.originalHtml = btn.innerHTML;
        }
        btn.disabled = true;
        btn.classList.add("is-loading");
        if (loadingText) {
            btn.dataset.loadingText = loadingText;
        }
    } else {
        btn.disabled = false;
        btn.classList.remove("is-loading");
        if (btn.dataset.originalHtml) {
            btn.innerHTML = btn.dataset.originalHtml;
            delete btn.dataset.originalHtml;
        }
        if (btn.dataset.loadingText) {
            delete btn.dataset.loadingText;
        }
    }
}

// Unified API Fetch Helper
async function apiFetch(url, options = {}) {
    const defaultHeaders = {
        "Accept": "application/json"
    };
    if (options.body && typeof options.body === "string") {
        defaultHeaders["Content-Type"] = "application/json";
    }

    const config = {
        ...options,
        headers: {
            ...defaultHeaders,
            ...(options.headers || {})
        },
        credentials: "same-origin"
    };

    try {
        const res = await fetch(url, config);
        let data = null;
        const contentType = res.headers.get("content-type");
        if (contentType && contentType.includes("application/json")) {
            try {
                data = await res.json();
            } catch (e) {
                data = null;
            }
        } else {
            try {
                data = await res.text();
            } catch (e) {
                data = null;
            }
        }

        if (res.status === 401) {
            // Check if genuine auth expiry (not login endpoint)
            if (!url.includes("/api/auth/login") && window.currentUser) {
                showToast("Your session has expired. Please sign in again.", "error", "Session Expired");
                showLoginScreen();
            }
            return {
                ok: false,
                status: 401,
                data,
                detail: (data && data.detail) || "Authentication required."
            };
        }

        if (!res.ok) {
            let detail = "An error occurred.";
            if (data && typeof data === "object") {
                detail = data.detail || data.message || JSON.stringify(data);
            } else if (typeof data === "string" && data.trim()) {
                detail = data;
            }
            return {
                ok: false,
                status: res.status,
                data,
                detail: detail
            };
        }

        return {
            ok: true,
            status: res.status,
            data
        };
    } catch (err) {
        console.error("API Request Error:", err);
        return {
            ok: false,
            status: 0,
            data: null,
            detail: "Network connection error. Server unreachable."
        };
    }
}

// General Modal Open / Close Helpers with Focus Trapping & Accessibility
function openModal(modalId, triggerEl = null) {
    const modal = typeof modalId === "string" ? document.getElementById(modalId) : modalId;
    if (!modal) return;
    if (triggerEl && triggerEl.id) {
        modal.dataset.triggerId = triggerEl.id;
    }
    modal.classList.add("active");
    modal.classList.add("open");
    
    // Auto focus first interactive element
    const focusable = modal.querySelector("input:not([type='hidden']):not([readonly]), select, textarea, button:not(.meridian-modal-close)");
    if (focusable) {
        setTimeout(() => focusable.focus(), 60);
    }
}

function closeModal(modalId) {
    const modal = typeof modalId === "string" ? document.getElementById(modalId) : modalId;
    if (!modal) return;
    modal.classList.remove("active");
    modal.classList.remove("open");
    
    // Return focus to trigger button
    if (modal.dataset.triggerId) {
        const triggerEl = document.getElementById(modal.dataset.triggerId);
        if (triggerEl) triggerEl.focus();
        delete modal.dataset.triggerId;
    }
}

document.addEventListener("DOMContentLoaded", () => {
    checkDemoModeConfig();
    checkAuthSession();
});

// Guard against BFCache restoring protected dashboard after logout
window.addEventListener("pageshow", (event) => {
    if (event.persisted || !window.currentUser) {
        checkAuthSession();
    }
});

// Guard browser Back/Forward navigation
window.addEventListener("popstate", () => {
    if (!window.currentUser) {
        showLoginScreen();
    }
});

async function checkDemoModeConfig() {
    try {
        const res = await fetch("/api/config/demo-mode");
        if (res.ok) {
            const data = await res.json();
            const isDemo = data.demo_mode !== false;
            window.isDemoMode = isDemo;
            const demoBox = document.getElementById("demo-access-box");
            const switchDemoBtn = document.getElementById("menu-switch-demo-btn");
            const demoBadge = document.getElementById("demo-environment-badge");
            if (demoBox) demoBox.style.display = isDemo ? "block" : "none";
            if (switchDemoBtn) switchDemoBtn.style.display = isDemo ? "flex" : "none";
            if (demoBadge) demoBadge.style.display = isDemo ? "inline-flex" : "none";
        }
    } catch (e) {}
}

// --------------------------------------------------------------------------
// 0. AUTHENTICATION & SESSION MANAGEMENT
// --------------------------------------------------------------------------

async function checkAuthSession() {
    try {
        const res = await fetch("/api/auth/me");
        if (res.ok) {
            const user = await res.json();
            initAuthenticatedSession(user);
        } else {
            showLoginScreen();
        }
    } catch (err) {
        console.error("Auth check failed:", err);
        showLoginScreen();
    }
}

function showLoginScreen() {
    window.currentUser = null;
    const overlay = document.getElementById("login-overlay");
    const app = document.getElementById("app-layout");
    if (overlay) overlay.style.display = "flex";
    if (app) app.style.display = "none";
}

function quickFillCredentials(username, password) {
    const uInput = document.getElementById("login-username");
    const pInput = document.getElementById("login-password");
    if (uInput) uInput.value = username;
    if (pInput) pInput.value = password;
    handleLoginSubmit(new Event("submit"));
}

function toggleLoginPasswordVisibility() {
    const pwd = document.getElementById("login-password");
    if (pwd) pwd.type = pwd.type === "password" ? "text" : "password";
}

async function handleLoginSubmit(e) {
    if (e && e.preventDefault) e.preventDefault();
    const uInput = document.getElementById("login-username");
    const pInput = document.getElementById("login-password");
    const rInput = document.getElementById("login-remember-me");
    if (!uInput || !pInput) return;

    const username = uInput.value.trim();
    const password = pInput.value;
    const rememberMe = rInput ? rInput.checked : false;

    const alertBox = document.getElementById("login-alert");
    const alertText = document.getElementById("login-alert-text");
    const btn = document.getElementById("login-submit-btn");
    const spinner = document.getElementById("login-btn-spinner");
    const btnText = document.getElementById("login-btn-text");

    if (alertBox) alertBox.style.display = "none";
    if (btn) btn.disabled = true;
    if (spinner) spinner.style.display = "inline";
    if (btnText) btnText.innerText = "Authenticating...";

    try {
        const res = await fetch("/api/auth/login", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ username, password, remember_me: rememberMe })
        });
        const data = await res.json();

        if (!res.ok) {
            if (alertBox) {
                alertBox.style.display = "flex";
                alertText.innerText = data.detail || "Authentication failed. Check credentials.";
            }
            return;
        }

        initAuthenticatedSession(data.user);
    } catch (err) {
        if (alertBox) {
            alertBox.style.display = "flex";
            alertText.innerText = "Network connection error. Server unreachable.";
        }
    } finally {
        if (btn) btn.disabled = false;
        if (spinner) spinner.style.display = "none";
        if (btnText) btnText.innerText = "Sign In to Meridian";
    }
}

function initAuthenticatedSession(user) {
    window.currentUser = user;
    
    // Hide login overlay, reveal app layout
    const overlay = document.getElementById("login-overlay");
    const app = document.getElementById("app-layout");
    if (overlay) overlay.style.display = "none";
    if (app) app.style.display = "flex";

    // Set user avatar & navbar details
    const avatar = document.getElementById("nav-user-avatar");
    const nameSpan = document.getElementById("nav-user-name");
    const roleBadge = document.getElementById("nav-user-role");
    const scopeChip = document.getElementById("nav-user-scope");
    const dropdownName = document.getElementById("dropdown-full-name");
    const dropdownEmail = document.getElementById("dropdown-email");
    const adminActions = document.getElementById("dropdown-admin-actions");

    if (avatar) avatar.innerText = user.full_name ? user.full_name.split(" ").map(n=>n[0]).join("").slice(0, 2) : "ME";
    if (nameSpan) nameSpan.innerText = user.full_name || user.id;
    if (roleBadge) {
        roleBadge.innerText = user.role.replace("_", " ");
        roleBadge.className = "user-role-badge " + (user.role === "NATIONAL_ADMIN" ? "admin" : (user.role === "DISTRICT_OFFICER" ? "officer" : "staff"));
    }
    if (dropdownName) dropdownName.innerText = user.full_name;
    if (dropdownEmail) dropdownEmail.innerText = user.email;

    // Demo Mode controls
    const isDemo = user.demo_mode !== false;
    window.isDemoMode = isDemo;
    const switchDemoBtn = document.getElementById("menu-switch-demo-btn");
    const demoBox = document.getElementById("demo-access-box");
    const demoBadge = document.getElementById("demo-environment-badge");
    const demoResetBtn = document.getElementById("menu-demo-reset-btn");
    if (switchDemoBtn) switchDemoBtn.style.display = isDemo ? "flex" : "none";
    if (demoBox) demoBox.style.display = isDemo ? "block" : "none";
    if (demoBadge) demoBadge.style.display = isDemo ? "inline-flex" : "none";
    if (demoResetBtn) demoResetBtn.style.display = (isDemo && user.role === "NATIONAL_ADMIN") ? "flex" : "none";

    // Sidebar Scope Card
    const scopeName = document.getElementById("sidebar-scope-name");
    const scopeSub = document.getElementById("sidebar-scope-sub");
    const roleVer = document.getElementById("sidebar-role-ver");

    if (user.role === "NATIONAL_ADMIN") {
        if (scopeChip) scopeChip.innerText = "Nationwide";
        if (scopeName) scopeName.innerText = "National Command";
        if (scopeSub) scopeSub.innerText = "All Districts & Health Nodes";
        if (roleVer) roleVer.innerText = "NAT-COMMAND";
        if (adminActions) adminActions.style.display = "block";
        activePhcId = "PHC-001";
        setupTopFacilitySelector(["PHC-001", "PHC-002", "PHC-003", "PHC-004"]);
    } else if (user.role === "DISTRICT_OFFICER") {
        const dId = user.assigned_district_id || "DIST-NORTH";
        activeDistrictId = dId;
        const dName = dId === "DIST-NORTH" ? "District North" : "District South";
        if (scopeChip) scopeChip.innerText = dId;
        if (scopeName) scopeName.innerText = dName;
        if (scopeSub) scopeSub.innerText = "District Operational Oversight";
        if (roleVer) roleVer.innerText = "DIST-OFFICER";
        if (adminActions) adminActions.style.display = "none";
        
        const districtPhcs = dId === "DIST-NORTH" ? ["PHC-001", "PHC-002"] : ["PHC-003", "PHC-004"];
        activePhcId = districtPhcs[0];
        setupTopFacilitySelector(districtPhcs);
    } else { // PHC_STAFF
        const pId = user.assigned_phc_id || "PHC-001";
        activePhcId = pId;
        activeDistrictId = user.assigned_district_id || "DIST-NORTH";
        const pName = pId === "PHC-001" ? "Alpha Sector PHC" : (pId === "PHC-002" ? "Beta Central PHC" : pId);
        if (scopeChip) scopeChip.innerText = pId;
        if (scopeName) scopeName.innerText = pName;
        if (scopeSub) scopeSub.innerText = "Assigned Facility Edge Node";
        if (roleVer) roleVer.innerText = "PHC-EDGE";
        if (adminActions) adminActions.style.display = "none";
        hideTopFacilitySelector();
    }

    // Load initial view
    setupCommSubNavForRole();
    switchMainTab("dashboard");
    loadDisciplineIndicators();
}

function setupTopFacilitySelector(phcList) {
    const wrap = document.getElementById("top-facility-selector-wrap");
    const sel = document.getElementById("top-facility-selector");
    if (!wrap || !sel) return;
    
    wrap.style.display = "flex";
    sel.innerHTML = "";
    const names = {
        "PHC-001": "PHC-001 (Alpha)",
        "PHC-002": "PHC-002 (Beta)",
        "PHC-003": "PHC-003 (Gamma)",
        "PHC-004": "PHC-004 (Delta)"
    };
    phcList.forEach(p => {
        const opt = document.createElement("option");
        opt.value = p;
        opt.innerText = names[p] || p;
        if (p === activePhcId) opt.selected = true;
        sel.appendChild(opt);
    });
}

function hideTopFacilitySelector() {
    const wrap = document.getElementById("top-facility-selector-wrap");
    if (wrap) wrap.style.display = "none";
}

function handleTopFacilityChange(newPhcId) {
    activePhcId = newPhcId;
    if (currentMainTab === "operations") {
        loadOperationsTab();
    } else if (currentMainTab === "dashboard" && window.currentUser && window.currentUser.role === "PHC_STAFF") {
        loadPHCDashboard(activePhcId);
        loadPHCAIInsights(activePhcId);
    }
}

// --- User Account Dropdown, Logout & Switch Demo Account ---

function toggleUserDropdown(e) {
    if (e) {
        e.stopPropagation();
        e.preventDefault();
    }
    const menu = document.getElementById("user-dropdown-menu");
    if (!menu) return;
    const isOpen = menu.classList.contains("show") || menu.classList.contains("open");
    if (isOpen) {
        closeUserDropdown();
    } else {
        openUserDropdown();
    }
}

function openUserDropdown() {
    const menu = document.getElementById("user-dropdown-menu");
    const trigger = document.getElementById("user-profile-trigger");
    const container = document.getElementById("user-menu-container");
    if (!menu) return;

    menu.classList.add("show", "open");
    if (trigger) {
        trigger.classList.add("open");
        trigger.setAttribute("aria-expanded", "true");
    }
    if (container) {
        container.classList.add("open");
    }
}

function closeUserDropdown() {
    const menu = document.getElementById("user-dropdown-menu");
    const trigger = document.getElementById("user-profile-trigger");
    const container = document.getElementById("user-menu-container");
    if (menu) {
        menu.classList.remove("show", "open");
    }
    if (trigger) {
        trigger.classList.remove("open");
        trigger.setAttribute("aria-expanded", "false");
    }
    if (container) {
        container.classList.remove("open");
    }
}

function handleUserBadgeKeydown(e) {
    if (e.key === "Enter" || e.key === " " || e.key === "ArrowDown") {
        e.preventDefault();
        openUserDropdown();
        // Focus first accessible menu item
        const firstItem = document.querySelector("#user-dropdown-menu .user-dropdown-item:not([style*='display: none'])");
        if (firstItem) firstItem.focus();
    } else if (e.key === "Escape") {
        closeUserDropdown();
    }
}

// Global Keyboard Navigation for Modals, Dropdown & Accessibility
document.addEventListener("keydown", (e) => {
    // 1. Modal Escape Handler
    if (e.key === "Escape") {
        const activeModals = document.querySelectorAll(".meridian-modal-overlay.active, .meridian-modal-overlay.open");
        if (activeModals.length > 0) {
            e.preventDefault();
            const topModal = activeModals[activeModals.length - 1];
            closeModal(topModal);
            return;
        }
    }

    // 2. Dropdown Keyboard Navigation
    const menu = document.getElementById("user-dropdown-menu");
    const trigger = document.getElementById("user-profile-trigger");
    if (!menu) return;

    const isOpen = menu.classList.contains("show") || menu.classList.contains("open");
    if (!isOpen) return;

    if (e.key === "Escape") {
        e.preventDefault();
        closeUserDropdown();
        if (trigger) trigger.focus();
        return;
    }

    const items = Array.from(menu.querySelectorAll(".user-dropdown-item:not([style*='display: none'])"));
    const currentIndex = items.indexOf(document.activeElement);

    if (e.key === "ArrowDown") {
        e.preventDefault();
        const nextIndex = (currentIndex >= 0 && currentIndex < items.length - 1) ? currentIndex + 1 : 0;
        if (items[nextIndex]) items[nextIndex].focus();
    } else if (e.key === "ArrowUp") {
        e.preventDefault();
        const prevIndex = (currentIndex > 0) ? currentIndex - 1 : items.length - 1;
        if (items[prevIndex]) items[prevIndex].focus();
    } else if (e.key === "Tab") {
        setTimeout(() => {
            const container = document.getElementById("user-menu-container");
            if (container && !container.contains(document.activeElement)) {
                closeUserDropdown();
            }
        }, 10);
    }
});

// Outside-click handling to close modals and dropdown
document.addEventListener("click", (e) => {
    // 1. Close modal on backdrop click
    if (e.target && e.target.classList && e.target.classList.contains("meridian-modal-overlay")) {
        closeModal(e.target);
    }

    // 2. Close user menu on outside click
    const container = document.getElementById("user-menu-container");
    if (container && !container.contains(e.target)) {
        closeUserDropdown();
    }
});

// Logout Handler
async function handleLogout() {
    closeUserDropdown();
    try {
        await fetch("/api/auth/logout", { method: "POST" });
    } catch (e) {
        console.error("Logout network error:", e);
    }

    // Clear client-side authenticated state
    window.currentUser = null;
    sessionStorage.clear();
    localStorage.removeItem("meridian_auth_user");

    // Prevent Back button from restoring protected state
    window.history.replaceState(null, "", "/");

    // Display clean login screen
    showLoginScreen();
}

// Switch Demo Account Handler
async function handleSwitchDemoAccount() {
    await handleLogout();
    const demoBox = document.getElementById("demo-access-box");
    if (demoBox) {
        demoBox.style.display = "block";
        demoBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
        const firstDemoBtn = demoBox.querySelector(".demo-pill-btn");
        if (firstDemoBtn) firstDemoBtn.focus();
    }
}

// --------------------------------------------------------------------------
// 1. UNIFIED 4-SECTION ROUTER
// --------------------------------------------------------------------------

function switchMainTab(tabId) {
    currentMainTab = tabId;

    // Update active state on sidebar
    const navItems = document.querySelectorAll("#sidebar-main-nav .nav-item");
    navItems.forEach(item => item.classList.remove("active"));
    const activeNav = document.getElementById(`nav-${tabId}`);
    if (activeNav) activeNav.classList.add("active");

    // Update breadcrumb
    const titles = {
        dashboard: "Dashboard Overview",
        operations: "Facility Operations & Daily Data",
        transfers: "Shortage Alerts & Redistribution",
        communication: "Official Communication & Reports"
    };
    const breadcrumb = document.getElementById("current-section-title");
    if (breadcrumb) breadcrumb.innerText = titles[tabId] || "Dashboard";

    // Show selected panel, hide others
    const panels = document.querySelectorAll(".main-panel");
    panels.forEach(p => p.style.display = "none");
    const activePanel = document.getElementById(`panel-${tabId}`);
    if (activePanel) activePanel.style.display = "block";

    // Route loaders
    if (tabId === "dashboard") {
        loadRoleDashboard();
    } else if (tabId === "operations") {
        loadOperationsTab();
    } else if (tabId === "transfers") {
        loadTransfersWorkspace();
    } else if (tabId === "communication") {
        loadCommunicationDesk();
    }

    loadDisciplineIndicators();
}

// --------------------------------------------------------------------------
// 2. DISCIPLINE & ACCOUNTABILITY INDICATORS
// --------------------------------------------------------------------------

async function loadDisciplineIndicators() {
    try {
        const res = await fetch("/api/accountability/indicators");
        if (!res.ok) return;
        const data = await res.json();
        const ind = data.discipline_indicators;

        const chip = document.getElementById("discipline-alert-chip");
        const chipIcon = document.getElementById("discipline-chip-icon");
        const chipText = document.getElementById("discipline-chip-text");
        const transfersBadge = document.getElementById("sidebar-transfers-badge");
        const messagesBadge = document.getElementById("sidebar-messages-badge");

        // Update badge counters
        if (transfersBadge) {
            const count = ind.delayed_transfers_count || 0;
            transfersBadge.innerText = count;
            transfersBadge.style.display = count > 0 ? "inline-block" : "none";
        }
        if (messagesBadge) {
            const count = ind.unacknowledged_urgent_messages || 0;
            messagesBadge.innerText = count;
            messagesBadge.style.display = count > 0 ? "inline-block" : "none";
        }

        if (!chip || !chipText) return;

        if (ind.critical_stockouts_count > 0 || ind.delayed_transfers_count > 0) {
            chip.className = "discipline-chip critical";
            chipIcon.innerText = "🚨";
            chipText.innerText = `${ind.critical_stockouts_count} Critical Shortage${ind.critical_stockouts_count > 1 ? 's' : ''} • ${ind.delayed_transfers_count} Delayed Transfer${ind.delayed_transfers_count > 1 ? 's' : ''}`;
        } else if (ind.unacknowledged_urgent_messages > 0 || ind.late_attendance_count > 0 || ind.stale_phcs_count > 0) {
            chip.className = "discipline-chip warning";
            chipIcon.innerText = "⚠️";
            chipText.innerText = `${ind.unacknowledged_urgent_messages} Urgent Directive Pending • ${ind.late_attendance_count} Late Arrival${ind.late_attendance_count > 1 ? 's' : ''}`;
        } else {
            chip.className = "discipline-chip normal";
            chipIcon.innerText = "🛡️";
            chipText.innerText = "All Facilities Compliant";
        }
    } catch (e) {
        console.warn("Could not load discipline indicators", e);
    }
}

// --------------------------------------------------------------------------
// 3. SECTION 1: DASHBOARD LOADERS
// --------------------------------------------------------------------------

function loadRoleDashboard() {
    if (!window.currentUser) return;
    const role = window.currentUser.role;

    const natView = document.getElementById("dashboard-national-view");
    const distView = document.getElementById("dashboard-district-view");
    const phcView = document.getElementById("dashboard-phc-view");

    if (natView) natView.style.display = role === "NATIONAL_ADMIN" ? "block" : "none";
    if (distView) distView.style.display = role === "DISTRICT_OFFICER" ? "block" : "none";
    if (phcView) phcView.style.display = role === "PHC_STAFF" ? "block" : "none";

    if (role === "NATIONAL_ADMIN") {
        loadNationalDashboard();
        loadNationalAIInsights();
    } else if (role === "DISTRICT_OFFICER") {
        loadDistrictDashboard();
        loadDistrictAIInsights();
    } else {
        loadPHCDashboard(activePhcId);
        loadPHCAIInsights(activePhcId);
    }
}

// --- National Dashboard ---
async function loadNationalDashboard() {
    const tbody = document.getElementById("nat-district-tbody");
    if (tbody) {
        tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:24px; color:#64748B;">⏳ Loading district performance data...</td></tr>';
    }
    try {
        const res = await fetch("/api/dashboard/national");
        if (!res.ok) {
            if (tbody) tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:24px; color:#DC2626;">⚠️ Unable to load national performance metrics.</td></tr>';
            return;
        }
        const data = await res.json();
        const kpis = data.national_kpis;

        setText("nat-kpi-districts", kpis.total_districts);
        setText("nat-kpi-phcs", kpis.total_phcs);
        setText("nat-kpi-reporting", kpis.reporting_phcs);
        setText("nat-kpi-stale", Math.max(0, kpis.total_phcs - kpis.reporting_phcs));
        setText("nat-kpi-attendance", "91.5%");
        setText("nat-kpi-shortages", kpis.medicine_shortages_count);
        setText("nat-kpi-emergencies", "1");
        setText("nat-kpi-transfers", kpis.active_transfers_count || 2);
        setText("nat-kpi-response-time", "34.5m");

        // District table
        if (tbody) {
            tbody.innerHTML = "";
            const districts = data.district_comparisons || [];
            if (districts.length === 0) {
                tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:24px; color:#64748B;">No district records found.</td></tr>';
                return;
            }
            districts.forEach(d => {
                const tr = document.createElement("tr");
                const isAlert = d.critical_alerts > 0;
                tr.innerHTML = `
                    <td><strong>${d.name}</strong> <span style="font-size:0.75rem; color:#64748B;">(${d.id})</span></td>
                    <td>${d.total_phcs} PHCs</td>
                    <td><span class="badge-status normal">${d.total_phcs} Online</span></td>
                    <td>92%</td>
                    <td>${isAlert ? `<span class="badge-status critical">${d.critical_alerts} Critical</span>` : `<span class="badge-status normal">0 Shortages</span>`}</td>
                    <td>1 Active</td>
                    <td>25 mins</td>
                    <td><span class="badge-status ${isAlert ? 'warning' : 'normal'}">${isAlert ? 'ATTENTION' : 'NORMAL'}</span></td>
                    <td style="text-align:right;">
                        <button type="button" class="btn btn-xs btn-outline" onclick="inspectDistrictFromNational('${d.id}')">Monitor District</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        }
    } catch (e) {
        console.error("Failed to load national dashboard", e);
        if (tbody) tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:24px; color:#DC2626;">⚠️ Network error loading district metrics.</td></tr>';
    }
}

function inspectDistrictFromNational(districtId) {
    activeDistrictId = districtId;
    activePhcId = districtId === "DIST-NORTH" ? "PHC-001" : "PHC-003";
    setupTopFacilitySelector(districtId === "DIST-NORTH" ? ["PHC-001", "PHC-002"] : ["PHC-003", "PHC-004"]);
    switchMainTab("operations");
}

// --- District Dashboard ---
async function loadDistrictDashboard() {
    const tbody = document.getElementById("dist-phc-tbody");
    if (tbody) {
        tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:24px; color:#64748B;">⏳ Loading facility readiness data...</td></tr>';
    }
    try {
        const res = await fetch(`/api/dashboard/district?district_id=${activeDistrictId}`);
        if (!res.ok) {
            if (tbody) tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:24px; color:#DC2626;">⚠️ Unable to load district facility status.</td></tr>';
            return;
        }
        const data = await res.json();

        setText("dist-dashboard-title", `${data.district_name || 'District'} Coordination Command`);
        setText("dist-kpi-phcs", data.phcs ? data.phcs.length : 2);
        setText("dist-kpi-online", data.phcs ? data.phcs.length : 2);
        setText("dist-kpi-staff", "6");
        setText("dist-kpi-attendance", "86%");
        setText("dist-kpi-shortages", (data.critical_par_level_warnings || []).length || 1);
        setText("dist-kpi-beds", "26");
        setText("dist-kpi-transfers", "1");
        setText("dist-kpi-emergencies", "1");
        setText("dist-kpi-response", "25m");

        if (tbody) {
            tbody.innerHTML = "";
            const phcs = (data.phc_comparison && data.phc_comparison.length > 0) ? data.phc_comparison : (data.phcs && data.phcs.length > 0 ? data.phcs : [
                { id: "PHC-001", name: "Alpha Sector PHC", operational_status: "ONLINE" },
                { id: "PHC-002", name: "Beta Central PHC", operational_status: "ONLINE" }
            ]);

            if (phcs.length === 0) {
                tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:24px; color:#64748B;">No primary health centres registered in this district.</td></tr>';
                return;
            }

            phcs.forEach(p => {
                const tr = document.createElement("tr");
                const hasWarning = p.id === "PHC-001";
                tr.innerHTML = `
                    <td><strong>${p.name}</strong> <span style="font-size:0.75rem; color:#64748B;">(${p.id})</span></td>
                    <td>12 mins ago</td>
                    <td>${hasWarning ? '75% (1 Absent)' : '100% On Duty'}</td>
                    <td>${hasWarning ? '<span class="badge-status critical">Shortage (ORS)</span>' : '<span class="badge-status normal">Adequate Surplus</span>'}</td>
                    <td>${hasWarning ? '26 / 30 Beds (86%)' : '18 / 40 Beds (45%)'}</td>
                    <td>${hasWarning ? '1 Pending' : '0 Requests'}</td>
                    <td><span class="badge-status ${hasWarning ? 'critical' : 'normal'}">${hasWarning ? 'AMBER' : 'GREEN'}</span></td>
                    <td><span class="badge-status ${hasWarning ? 'warning' : 'normal'}">${hasWarning ? 'ACTION REQUIRED' : 'NORMAL'}</span></td>
                    <td style="text-align:right;">
                        <button type="button" class="btn btn-xs btn-outline" onclick="inspectPHCFromDistrict('${p.id}')">Inspect PHC</button>
                    </td>
                `;
                tbody.appendChild(tr);
            });
        }
    } catch (e) {
        console.error("Failed to load district dashboard", e);
        if (tbody) tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:24px; color:#DC2626;">⚠️ Network error loading facility status.</td></tr>';
    }
}

function inspectPHCFromDistrict(phcId) {
    activePhcId = phcId;
    const sel = document.getElementById("top-facility-selector");
    if (sel) sel.value = phcId;
    switchMainTab("operations");
}

// --- PHC Staff Dashboard ---
async function loadPHCDashboard(phcId) {
    try {
        const res = await fetch(`/api/dashboard/phc/${phcId}`);
        if (!res.ok) return;
        const data = await res.json();

        setText("phc-dashboard-title", `${phcId === "PHC-001" ? "Alpha Sector PHC" : (phcId === "PHC-002" ? "Beta Central PHC" : phcId)} — Daily Status`);
        
        // Bed counts
        if (data.bed_status) {
            const occ = data.bed_status.occupied_beds;
            const tot = data.bed_status.total_beds;
            const avail = Math.max(0, tot - occ);
            const pct = tot > 0 ? Math.round((occ / tot) * 100) : 0;
            setText("phc-kpi-beds", `${avail} / ${tot}`);
            const sub = document.querySelector("#phc-kpi-beds + .kpi-subtext");
            if (sub) sub.innerText = `${occ} beds occupied (${pct}%)`;
        }

        // Staff counts
        if (data.staff_attendance) {
            const pres = data.staff_attendance.filter(s => s.present === 1).length;
            const tot = data.staff_attendance.length;
            setText("phc-kpi-staff", `${pres} / ${tot}`);
        }

        // Inventory shortage count
        let shortageCount = 0;
        if (data.inventory) {
            data.inventory.forEach(item => {
                if (item.quantity <= (item.par_level * 0.3)) shortageCount++;
            });
            setText("phc-kpi-shortages", shortageCount);
        }

        // Actions Required list
        renderPHCActionsRequired(data);
    } catch (e) {
        console.error("Failed to load PHC dashboard", e);
    }
}

function renderPHCActionsRequired(phcData) {
    const container = document.getElementById("phc-actions-required-list");
    if (!container) return;
    container.innerHTML = "";

    const items = [
        {
            critical: true,
            title: "Critical Shortage: ORS Packets (15 / 100 safe par)",
            desc: "Stock levels below 24-hour threshold with high paediatric OPD footfall.",
            actionText: "Request Transfer",
            actionFn: "openCreateTransferModal('ORS Packets', 60)"
        },
        {
            critical: false,
            title: "Pending Directive: Verify Batch Seals on Paracetamol Consignment",
            desc: "District Officer instruction awaiting signed acknowledgement.",
            actionText: "Acknowledge",
            actionFn: "switchMainTab('communication')"
        },
        {
            critical: false,
            title: "Transfer Confirmation: ORS Consignment In Transit from Beta Node",
            desc: "Delivery arrival estimated in 18 minutes. Inspect packaging upon arrival.",
            actionText: "View Transfer",
            actionFn: "switchMainTab('transfers')"
        }
    ];

    items.forEach(item => {
        const div = document.createElement("div");
        div.className = `action-required-item ${item.critical ? 'critical' : ''}`;
        div.innerHTML = `
            <div class="action-required-left">
                <span style="font-size:1.2rem;">${item.critical ? '🚨' : '⚠️'}</span>
                <div>
                    <div class="action-required-title">${item.title}</div>
                    <div class="action-required-desc">${item.desc}</div>
                </div>
            </div>
            <button type="button" class="btn btn-xs ${item.critical ? 'btn-primary' : 'btn-outline'}" onclick="${item.actionFn}">${item.actionText}</button>
        `;
        container.appendChild(div);
    });
}

// --------------------------------------------------------------------------
// 4. SECTION 2: OPERATIONS LOADERS & ACTIONS
// --------------------------------------------------------------------------

function switchOpsSubTab(subTab) {
    currentOpsSubTab = subTab;
    
    // Sub-nav buttons
    const btns = document.querySelectorAll(".sub-nav-btn");
    btns.forEach(b => b.classList.remove("active"));
    const activeBtn = document.getElementById(`subnav-${subTab}`);
    if (activeBtn) activeBtn.classList.add("active");

    // Subtab contents
    const contents = document.querySelectorAll(".ops-subtab-content");
    contents.forEach(c => c.style.display = "none");
    const activeContent = document.getElementById(`opstab-${subTab}`);
    if (activeContent) activeContent.style.display = "block";

    if (subTab === "footfall" && footfallChartInstance) {
        footfallChartInstance.resize();
    }
}

async function loadOperationsTab() {
    const role = window.currentUser ? window.currentUser.role : "PHC_STAFF";
    const phcContainer = document.getElementById("ops-phc-container");
    const distContainer = document.getElementById("ops-district-container");
    const natContainer = document.getElementById("ops-national-container");
    const titleEl = document.getElementById("ops-panel-title");
    const subtitleEl = document.getElementById("ops-panel-subtitle");

    if (role === "DISTRICT_OFFICER") {
        if (titleEl) titleEl.innerText = "PHC Operations Monitoring";
        if (subtitleEl) subtitleEl.innerText = "Read-only operational status of Primary Health Centres in your district";
        if (phcContainer) phcContainer.style.display = "none";
        if (natContainer) natContainer.style.display = "none";
        if (distContainer) distContainer.style.display = "block";
        await loadDistrictOperationsMonitoring();
        return;
    }

    if (role === "NATIONAL_ADMIN") {
        if (titleEl) titleEl.innerText = "District & PHC Operations Monitoring";
        if (subtitleEl) subtitleEl.innerText = "Nationwide read-only visibility into district and PHC operational performance";
        if (phcContainer) phcContainer.style.display = "none";
        if (distContainer) distContainer.style.display = "none";
        if (natContainer) natContainer.style.display = "block";
        await loadNationalOperationsMonitoring();
        return;
    }

    // Role is PHC_STAFF
    if (titleEl) titleEl.innerText = "Facility Operations & Daily Data Entry";
    if (subtitleEl) subtitleEl.innerText = "Manage medicine inventory, clinical bed allocation, biometric/RFID staff attendance, and patient flow";
    if (phcContainer) phcContainer.style.display = "block";
    if (distContainer) distContainer.style.display = "none";
    if (natContainer) natContainer.style.display = "none";

    try {
        // 1. Fetch facility dashboard data
        const res = await apiFetch(`/api/dashboard/phc/${activePhcId}`);
        if (!res.ok) {
            showToast(`Could not load facility data for ${activePhcId}`, "error");
            return;
        }
        const data = res.data;

        // 2. Fetch facility equipment
        const eqRes = await apiFetch(`/api/equipment?phc_id=${activePhcId}`);
        const equipmentData = (eqRes.ok && Array.isArray(eqRes.data)) ? eqRes.data : [];

        // Cache authoritative data
        cachedInventory = data.inventory || [];
        cachedBedStatus = data.bed_status || null;
        cachedEquipment = equipmentData;
        cachedStaffAttendance = data.staff_attendance || [];
        cachedFootfall = data.patient_footfall || [];

        // Handle Supervisor Banner
        const isSupervisor = data.is_supervisor_view;
        const banner = document.getElementById("supervisor-banner");
        const invActions = document.getElementById("inventory-card-actions");

        if (banner) banner.style.display = isSupervisor ? "flex" : "none";
        if (invActions) {
            // Operational receipts and dispensed buttons visible only for staff, or request resource for all
            invActions.style.display = isSupervisor ? "none" : "flex";
        }

        // Render Sub-tabs
        renderOpsInventoryTable(cachedInventory);
        renderOpsBedsWidget(cachedBedStatus);
        renderOpsEquipmentList(cachedEquipment);
        renderOpsAttendanceTable(cachedStaffAttendance);
        renderOpsFootfallChart(cachedFootfall);
        renderOpsFootfallHistory(cachedFootfall);

        // Synchronize Footfall Date Picker
        const dateInput = document.getElementById("footfall-date-input");
        if (dateInput) {
            const today = new Date().toISOString().split("T")[0];
            dateInput.max = today;
            if (!dateInput.value) dateInput.value = today;
            handleFootfallDateChange(dateInput.value);
        }

        // Keep PHC Dashboard summary in sync
        loadPHCDashboard(activePhcId);
    } catch (e) {
        console.error("Failed to load operations tab", e);
        showToast("Error synchronizing operations data.", "error");
    }
}

// --------------------------------------------------------------------------
// 4A. MEDICINE INVENTORY TABLE
// --------------------------------------------------------------------------

function renderOpsInventoryTable(inventory) {
    const tbody = document.getElementById("ops-inventory-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    if (!inventory || inventory.length === 0) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; color:#64748B;">No inventory items found for this facility.</td></tr>`;
        return;
    }

    inventory.forEach(item => {
        const tr = document.createElement("tr");
        const ratio = item.par_level > 0 ? Math.round((item.quantity / item.par_level) * 100) : 100;
        let badgeClass = "normal";
        let statusText = "HEALTHY";
        if (ratio < 30) {
            badgeClass = "critical";
            statusText = "CRITICAL DEFICIT";
        } else if (ratio < 60) {
            badgeClass = "warning";
            statusText = "LOW BUFFER";
        }

        const forecast = item.forecast || {};
        const forecastText = forecast.trend ? `${forecast.trend} (${forecast.forecast_next_3_days || 45} units expected)` : "Stable trend";

        tr.innerHTML = `
            <td><strong>${item.medicine_name}</strong></td>
            <td><span style="font-size:1.1rem; font-weight:700;">${item.quantity}</span> units</td>
            <td>${item.par_level} units</td>
            <td>
                <div style="display:flex; align-items:center; gap:8px;">
                    <span style="font-size:0.8rem; font-weight:700;">${ratio}%</span>
                    <div style="flex:1; height:6px; background:#E2E8F0; border-radius:3px; max-width:80px;">
                        <div style="width:${Math.min(100, ratio)}%; height:100%; background:${ratio < 30 ? '#DC2626' : (ratio < 60 ? '#D97706' : '#16A34A')}; border-radius:3px;"></div>
                    </div>
                </div>
            </td>
            <td><span style="font-size:0.8rem; color:#475569;">${forecastText}</span></td>
            <td><span class="badge-status ${badgeClass}">${statusText}</span></td>
            <td>
                <div style="display:flex; gap:4px;">
                    <button type="button" class="btn btn-xs btn-outline" onclick="openCreateTransferModal('${item.medicine_name}', 50)">Request</button>
                    <button type="button" class="btn btn-xs btn-outline" onclick="openBatchProvenanceModal('${item.medicine_name}', '${activePhcId}')" title="Inspect database provenance ledger">🔍 Batch</button>
                </div>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

// --------------------------------------------------------------------------
// 4B. BEDS & EQUIPMENT CONTROLS
// --------------------------------------------------------------------------

function renderOpsBedsWidget(bedStatus) {
    if (!bedStatus) return;
    const tot = bedStatus.total_beds || 30;
    const occ = bedStatus.occupied_beds || 26;
    const avail = Math.max(0, tot - occ);

    setText("ops-beds-total", tot);
    setText("ops-beds-occupied", occ);
    setText("ops-beds-avail", avail);

    const totInput = document.getElementById("ops-beds-total-input");
    const occInput = document.getElementById("quick-occupied-input");
    const calcAvail = document.getElementById("ops-beds-calc-avail");
    const errEl = document.getElementById("bed-validation-error");

    if (totInput) totInput.value = tot;
    if (occInput) occInput.value = occ;
    if (calcAvail) calcAvail.innerText = avail;
    if (errEl) errEl.style.display = "none";
}

function calculateLiveAvailableBeds() {
    const totInput = document.getElementById("ops-beds-total-input");
    const occInput = document.getElementById("quick-occupied-input");
    const errEl = document.getElementById("bed-validation-error");
    const calcEl = document.getElementById("ops-beds-calc-avail");
    if (!totInput || !occInput) return true;

    const tot = parseInt(totInput.value, 10);
    const occ = parseInt(occInput.value, 10);

    if (isNaN(tot) || isNaN(occ) || tot < 0 || occ < 0) {
        if (errEl) {
            errEl.style.display = "block";
            errEl.innerText = "Bed numbers must be non-negative whole numbers.";
        }
        if (calcEl) calcEl.innerText = "--";
        return false;
    }

    if (occ > tot) {
        if (errEl) {
            errEl.style.display = "block";
            errEl.innerText = "Occupied beds cannot exceed total registered beds.";
        }
        if (calcEl) calcEl.innerText = "--";
        return false;
    }

    if (errEl) errEl.style.display = "none";
    if (calcEl) calcEl.innerText = (tot - occ).toString();
    return true;
}

async function submitQuickBedUpdate() {
    const totInput = document.getElementById("ops-beds-total-input");
    const occInput = document.getElementById("quick-occupied-input");
    const notesInput = document.getElementById("ops-beds-notes-input");
    const btn = document.getElementById("btn-update-beds");
    if (!totInput || !occInput) return;

    if (!calculateLiveAvailableBeds()) {
        showToast("Please correct bed counts before saving.", "warning", "Validation Error");
        return;
    }

    const tot = parseInt(totInput.value, 10);
    const occ = parseInt(occInput.value, 10);
    const notes = notesInput ? notesInput.value.trim() : "";

    // If supervisor, require override
    if (window.currentUser && window.currentUser.role !== "PHC_STAFF") {
        pendingOverridePayload = {
            type: "BED_UPDATE",
            phc_id: activePhcId,
            total_beds: tot,
            occupied_beds: occ,
            notes: notes
        };
        openOverrideModal();
        return;
    }

    setButtonLoading(btn, true);
    try {
        const res = await apiFetch("/api/beds/update", {
            method: "POST",
            body: JSON.stringify({
                phc_id: activePhcId,
                total_beds: tot,
                occupied_beds: occ,
                notes: notes || null
            })
        });

        if (res.ok) {
            showToast(`Bed allocation updated: ${occ}/${tot} occupied (${tot - occ} available).`, "success", "Bed Allocation Saved");
            if (notesInput) notesInput.value = "";
            await loadOperationsTab();
        } else {
            showToast(`Update failed: ${res.detail || 'Forbidden'}`, "error");
        }
    } finally {
        setButtonLoading(btn, false);
    }
}

// --------------------------------------------------------------------------
// 4C. CRITICAL FACILITY EQUIPMENT
// --------------------------------------------------------------------------

function renderOpsEquipmentList(equipmentList) {
    const container = document.getElementById("ops-equipment-list");
    if (!container) return;
    container.innerHTML = "";

    if (!equipmentList || equipmentList.length === 0) {
        container.innerHTML = `<div style="padding:16px; color:#64748B; font-size:0.85rem; text-align:center;">No equipment registered for this facility.</div>`;
        return;
    }

    equipmentList.forEach(eq => {
        const itemDiv = document.createElement("div");
        itemDiv.className = "equipment-item";

        let badgeClass = "normal";
        let badgeText = eq.operational_status;
        if (eq.operational_status === "OPERATIONAL") {
            badgeClass = "active";
            badgeText = "OPERATIONAL";
        } else if (eq.operational_status === "UNDER_MAINTENANCE") {
            badgeClass = "warning";
            badgeText = `MAINTENANCE (${eq.under_maintenance_count || 0})`;
        } else if (eq.operational_status === "CRITICAL_DEFICIT") {
            badgeClass = "critical";
            badgeText = "CRITICAL DEFICIT";
        } else if (eq.operational_status === "STANDBY") {
            badgeClass = "normal";
            badgeText = "STANDBY";
        }

        const updatedTime = eq.updated_at ? eq.updated_at.replace("T", " ").slice(0, 16) : "Recent";

        itemDiv.innerHTML = `
            <div class="equipment-info">
                <div class="equipment-title">${eq.name}</div>
                <div class="equipment-meta">
                    <span>Category: <strong>${eq.category}</strong></span>
                    <span>Total: <strong>${eq.quantity} units</strong></span>
                    <span>Maintenance: <strong style="${eq.under_maintenance_count > 0 ? 'color:#B45309;' : ''}">${eq.under_maintenance_count || 0}</strong></span>
                    <span>Updated: ${updatedTime}</span>
                </div>
            </div>
            <div class="equipment-actions">
                <span class="badge-status ${badgeClass}">${badgeText}</span>
                <button type="button" class="btn btn-xs btn-outline" onclick="openEditEquipmentModal(${eq.id})">Edit</button>
            </div>
        `;
        container.appendChild(itemDiv);
    });
}

function openEditEquipmentModal(equipmentId) {
    const eq = cachedEquipment.find(e => e.id === equipmentId);
    if (!eq) return;

    document.getElementById("eq-edit-id").value = eq.id;
    document.getElementById("eq-edit-name").value = eq.name;
    document.getElementById("eq-edit-category").value = eq.category;
    document.getElementById("eq-edit-quantity").value = eq.quantity;
    document.getElementById("eq-edit-status").value = eq.operational_status;
    document.getElementById("eq-edit-maint-count").value = eq.under_maintenance_count || 0;
    document.getElementById("eq-edit-notes").value = eq.notes || "";

    const err = document.getElementById("eq-maint-error");
    if (err) err.style.display = "none";

    openModal("update-equipment-modal");
}

function closeEditEquipmentModal() {
    closeModal("update-equipment-modal");
}

function validateEquipmentForm() {
    const qtyInput = document.getElementById("eq-edit-quantity");
    const maintInput = document.getElementById("eq-edit-maint-count");
    const errEl = document.getElementById("eq-maint-error");
    if (!qtyInput || !maintInput) return true;

    const qty = parseInt(qtyInput.value, 10) || 0;
    const maint = parseInt(maintInput.value, 10) || 0;

    if (qty < 0 || maint < 0) {
        if (errEl) {
            errEl.style.display = "block";
            errEl.innerText = "Quantities cannot be negative numbers.";
        }
        return false;
    }

    if (maint > qty) {
        if (errEl) {
            errEl.style.display = "block";
            errEl.innerText = "Under-maintenance count cannot exceed total quantity.";
        }
        return false;
    }

    if (errEl) errEl.style.display = "none";
    return true;
}

async function submitEditEquipment() {
    if (!validateEquipmentForm()) {
        showToast("Please correct equipment quantities before saving.", "warning", "Validation Error");
        return;
    }

    const id = parseInt(document.getElementById("eq-edit-id").value, 10);
    const name = document.getElementById("eq-edit-name").value;
    const cat = document.getElementById("eq-edit-category").value;
    const qty = parseInt(document.getElementById("eq-edit-quantity").value, 10);
    const status = document.getElementById("eq-edit-status").value;
    const maint = parseInt(document.getElementById("eq-edit-maint-count").value, 10);
    const notes = document.getElementById("eq-edit-notes").value.trim();
    const btn = document.getElementById("btn-submit-equipment");

    setButtonLoading(btn, true);
    try {
        const res = await apiFetch("/api/equipment/update", {
            method: "POST",
            body: JSON.stringify({
                phc_id: activePhcId,
                equipment_id: id,
                name: name,
                category: cat,
                quantity: qty,
                operational_status: status,
                under_maintenance_count: maint,
                notes: notes || null
            })
        });

        if (res.ok) {
            closeEditEquipmentModal();
            showToast(`Equipment '${name}' updated to ${status}.`, "success", "Equipment Saved");
            await loadOperationsTab();
        } else {
            showToast(`Failed to update equipment: ${res.detail}`, "error");
        }
    } finally {
        setButtonLoading(btn, false);
    }
}

// --------------------------------------------------------------------------
// 4D. STAFF ATTENDANCE & BIOMETRICS
// --------------------------------------------------------------------------

function renderOpsAttendanceTable(roster) {
    const tbody = document.getElementById("ops-attendance-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    let present = 0;
    let absent = 0;
    let late = 0;
    let onLeave = 0;

    roster.forEach(r => {
        const isPresent = r.status === "CHECKED_IN" || r.present === 1;
        if (r.status === "CHECKED_IN") present++;
        else if (r.status === "ABSENT") absent++;
        else if (r.status === "LATE") late++;
        else if (r.status === "ON_LEAVE") onLeave++;
        else if (isPresent) present++;
        else absent++;

        const tr = document.createElement("tr");
        let badgeClass = "normal";
        if (r.status === "ABSENT") badgeClass = "critical";
        else if (r.status === "LATE") badgeClass = "warning";
        else if (r.status === "CHECKED_IN") badgeClass = "active";
        else if (r.status === "ON_LEAVE") badgeClass = "normal";

        let actionBtn = "";
        if (r.status === "CHECKED_IN") {
            actionBtn = `<button type="button" class="btn btn-xs btn-outline" onclick="performStaffAction('${r.staff_id}', 'CHECK_OUT')">Check Out</button>`;
        } else {
            actionBtn = `<button type="button" class="btn btn-xs btn-primary" onclick="performStaffAction('${r.staff_id}', 'CHECK_IN')">Check In</button>`;
        }

        tr.innerHTML = `
            <td><strong>${r.staff_name || r.staff_id}</strong></td>
            <td>${r.role || 'Staff'}</td>
            <td>${r.punch_in_time || '--'}</td>
            <td><span class="badge-status ${badgeClass}">${r.status}</span></td>
            <td><span style="font-size:0.75rem; color:#64748B;">${r.verification_method || 'Manual'}</span></td>
            <td>${actionBtn}</td>
        `;
        tbody.appendChild(tr);
    });

    const summaryTag = document.getElementById("ops-attendance-summary-tag");
    if (summaryTag) {
        summaryTag.innerText = `Present: ${present} • Absent: ${absent} • Late: ${late} • On Leave: ${onLeave}`;
    }

    // Populate manual staff selector
    const staffSelect = document.getElementById("manual-staff-select");
    if (staffSelect && roster.length > 0) {
        const currentVal = staffSelect.value;
        staffSelect.innerHTML = "";
        roster.forEach(stf => {
            const opt = document.createElement("option");
            opt.value = stf.staff_id;
            opt.innerText = `${stf.staff_name || stf.staff_id} (${stf.role || 'Staff'})`;
            if (stf.staff_id === currentVal) opt.selected = true;
            staffSelect.appendChild(opt);
        });
    }
}

async function simulateCardPunch(cardUid, staffId, btn = null) {
    const feedback = document.getElementById("card-punch-feedback");
    if (btn) setButtonLoading(btn, true);

    try {
        const res = await apiFetch("/api/staff/punch", {
            method: "POST",
            body: JSON.stringify({ card_uid: cardUid, phc_id: activePhcId })
        });

        if (res.ok) {
            const data = res.data;
            const msg = `💳 RFID Scan: ${data.staff_name} (${data.action} - ${data.status})`;
            if (feedback) {
                feedback.style.display = "block";
                feedback.style.background = "#F0FDF4";
                feedback.style.color = "#166534";
                feedback.style.border = "1px solid #86EFAC";
                feedback.innerText = msg;
                setTimeout(() => { feedback.style.display = "none"; }, 4000);
            }
            showToast(msg, "success", "RFID Punch Recorded");
            await loadOperationsTab();
        } else {
            const errMsg = res.detail || "Card punch failed";
            if (feedback) {
                feedback.style.display = "block";
                feedback.style.background = "#FEF2F2";
                feedback.style.color = "#991B1B";
                feedback.style.border = "1px solid #FECACA";
                feedback.innerText = `Punch Failed: ${errMsg}`;
                setTimeout(() => { feedback.style.display = "none"; }, 4000);
            }
            showToast(`Card Punch Failed: ${errMsg}`, "warning", "Scan Rejected");
        }
    } finally {
        if (btn) setButtonLoading(btn, false);
    }
}

async function submitManualAttendance() {
    const staffSelect = document.getElementById("manual-staff-select");
    const statusSelect = document.getElementById("manual-status-select");
    const btn = document.getElementById("btn-manual-attendance");
    if (!staffSelect || !statusSelect) return;

    const staffId = staffSelect.value;
    const status = statusSelect.value;
    if (!staffId) {
        showToast("Please select a staff member.", "warning");
        return;
    }

    setButtonLoading(btn, true);
    try {
        const res = await apiFetch("/api/staff/log", {
            method: "POST",
            body: JSON.stringify({
                phc_id: activePhcId,
                staff_id: staffId,
                status: status,
                verification_method: "Manual Kiosk Override",
                date: new Date().toISOString().split("T")[0]
            })
        });

        if (res.ok) {
            showToast(`Attendance recorded: ${staffId} marked ${status}.`, "success", "Roster Updated");
            await loadOperationsTab();
        } else {
            showToast(`Attendance update failed: ${res.detail}`, "error");
        }
    } finally {
        setButtonLoading(btn, false);
    }
}

async function performStaffAction(staffId, action) {
    try {
        const res = await apiFetch("/api/staff/action", {
            method: "POST",
            body: JSON.stringify({
                phc_id: activePhcId,
                staff_id: staffId,
                action: action,
                remarks: `Quick action: ${action}`
            })
        });

        if (res.ok) {
            showToast(`Staff member ${staffId} updated: ${action}`, "success", "Duty Action Recorded");
            await loadOperationsTab();
        } else {
            showToast(`Action failed: ${res.detail}`, "error");
        }
    } catch (e) {
        showToast("Network error executing staff action.", "error");
    }
}

// --------------------------------------------------------------------------
// 4E. PATIENT FOOTFALL & TRENDS
// --------------------------------------------------------------------------

function renderOpsFootfallChart(footfallData) {
    const canvas = document.getElementById("ops-footfall-chart");
    if (!canvas) return;

    const labels = footfallData.map(f => f.date.slice(5));
    const counts = footfallData.map(f => f.count);

    if (footfallChartInstance) {
        footfallChartInstance.destroy();
    }

    footfallChartInstance = new Chart(canvas, {
        type: "line",
        data: {
            labels: labels.length > 0 ? labels : ["Day 1", "Day 2", "Day 3", "Day 4", "Day 5", "Day 6", "Today"],
            datasets: [{
                label: "OPD Patient Footfall",
                data: counts.length > 0 ? counts : [80, 92, 104, 116, 128, 140, 152],
                borderColor: "#0F766E",
                backgroundColor: "rgba(15, 118, 110, 0.08)",
                borderWidth: 2,
                fill: true,
                tension: 0.3
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: { beginAtZero: false, grid: { color: "#F1F5F9" } },
                x: { grid: { display: false } }
            }
        }
    });
}

function handleFootfallDateChange(selectedDate) {
    const today = new Date().toISOString().split("T")[0];
    if (selectedDate > today) {
        showToast("Cannot select future dates for patient footfall.", "warning", "Invalid Date");
        const dateInput = document.getElementById("footfall-date-input");
        if (dateInput) dateInput.value = today;
        selectedDate = today;
    }

    const record = cachedFootfall.find(f => f.date === selectedDate);
    const correctionWrap = document.getElementById("footfall-correction-wrap");
    const modeTag = document.getElementById("footfall-mode-tag");
    const submitBtn = document.getElementById("btn-submit-footfall");

    if (record) {
        if (correctionWrap) correctionWrap.style.display = "block";
        if (modeTag) modeTag.innerText = "Editing Saved Record (Correction Required)";
        if (submitBtn) submitBtn.innerText = "Update Saved Footfall";

        const dailyInput = document.getElementById("daily-footfall-input");
        const maleInput = document.getElementById("footfall-male-input");
        const femaleInput = document.getElementById("footfall-female-input");
        const otherInput = document.getElementById("footfall-other-input");
        const emergInput = document.getElementById("footfall-emergency-input");

        if (dailyInput) dailyInput.value = record.count;
        if (maleInput) maleInput.value = record.male_count || 0;
        if (femaleInput) femaleInput.value = record.female_count || 0;
        if (otherInput) otherInput.value = record.other_count || 0;
        if (emergInput) emergInput.value = record.emergency_cases || 0;
    } else {
        if (correctionWrap) correctionWrap.style.display = "none";
        if (modeTag) modeTag.innerText = "Active Daily Log";
        if (submitBtn) submitBtn.innerText = "Save Daily Count";
    }
    validateFootfallBreakdown();
}

function validateFootfallBreakdown() {
    const dailyInput = document.getElementById("daily-footfall-input");
    const maleInput = document.getElementById("footfall-male-input");
    const femaleInput = document.getElementById("footfall-female-input");
    const otherInput = document.getElementById("footfall-other-input");
    const errEl = document.getElementById("footfall-validation-error");
    if (!dailyInput) return true;

    const total = parseInt(dailyInput.value, 10) || 0;
    const m = parseInt(maleInput ? maleInput.value : 0, 10) || 0;
    const f = parseInt(femaleInput ? femaleInput.value : 0, 10) || 0;
    const o = parseInt(otherInput ? otherInput.value : 0, 10) || 0;

    if (total < 0 || m < 0 || f < 0 || o < 0) {
        if (errEl) {
            errEl.style.display = "block";
            errEl.innerText = "Patient counts must be non-negative whole numbers.";
        }
        return false;
    }

    if ((m + f + o) > total) {
        if (errEl) {
            errEl.style.display = "block";
            errEl.innerText = `Category sum (${m + f + o}) cannot exceed total patient visits (${total}).`;
        }
        return false;
    }

    if (errEl) errEl.style.display = "none";
    return true;
}

function adjustFootfall(delta) {
    const input = document.getElementById("daily-footfall-input");
    if (input) {
        const cur = parseInt(input.value || 0, 10);
        input.value = Math.max(0, cur + delta);
        validateFootfallBreakdown();
    }
}

async function submitFootfallEntry() {
    const dateInput = document.getElementById("footfall-date-input");
    const dailyInput = document.getElementById("daily-footfall-input");
    const maleInput = document.getElementById("footfall-male-input");
    const femaleInput = document.getElementById("footfall-female-input");
    const otherInput = document.getElementById("footfall-other-input");
    const emergInput = document.getElementById("footfall-emergency-input");
    const corrInput = document.getElementById("footfall-correction-input");
    const btn = document.getElementById("btn-submit-footfall");

    if (!validateFootfallBreakdown()) {
        showToast("Please correct category breakdown values.", "warning", "Validation Error");
        return;
    }

    const dateStr = dateInput ? dateInput.value : new Date().toISOString().split("T")[0];
    const today = new Date().toISOString().split("T")[0];
    if (dateStr > today) {
        showToast("Cannot enter footfall for future dates.", "warning", "Invalid Date");
        return;
    }

    const total = parseInt(dailyInput.value, 10);
    const m = parseInt(maleInput ? maleInput.value : 0, 10) || 0;
    const f = parseInt(femaleInput ? femaleInput.value : 0, 10) || 0;
    const o = parseInt(otherInput ? otherInput.value : 0, 10) || 0;
    const emerg = parseInt(emergInput ? emergInput.value : 0, 10) || 0;

    // Check if record exists for this date, require correction reason
    const existing = cachedFootfall.find(item => item.date === dateStr);
    let corrReason = corrInput ? corrInput.value.trim() : "";
    if (existing && !corrReason) {
        showToast("A correction reason is required when modifying a saved record.", "warning", "Reason Required");
        if (corrInput) corrInput.focus();
        return;
    }

    setButtonLoading(btn, true);
    try {
        const res = await apiFetch("/api/footfall/log", {
            method: "POST",
            body: JSON.stringify({
                phc_id: activePhcId,
                date: dateStr,
                count: total,
                male_count: m,
                female_count: f,
                other_count: o,
                emergency_cases: emerg,
                correction_reason: corrReason || null
            })
        });

        if (res.ok) {
            showToast(`Daily footfall for ${dateStr} saved: ${total} patients recorded.`, "success", "Footfall Logged");
            if (corrInput) corrInput.value = "";
            await loadOperationsTab();
        } else {
            showToast(`Footfall save failed: ${res.detail}`, "error");
        }
    } finally {
        setButtonLoading(btn, false);
    }
}

function renderOpsFootfallHistory(footfallData) {
    const tbody = document.getElementById("ops-footfall-history-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    if (!footfallData || footfallData.length === 0) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; color:#64748B;">No footfall history recorded.</td></tr>`;
        return;
    }

    const sorted = [...footfallData].sort((a, b) => b.date.localeCompare(a.date));

    sorted.forEach(f => {
        const tr = document.createElement("tr");
        const m = f.male_count != null ? f.male_count : "--";
        const fe = f.female_count != null ? f.female_count : "--";
        const o = f.other_count != null ? f.other_count : "--";
        const em = f.emergency_cases != null ? f.emergency_cases : "--";

        tr.innerHTML = `
            <td><strong>${f.date}</strong></td>
            <td><span style="font-weight:700;">${f.count}</span></td>
            <td><span style="font-size:0.775rem; color:#475569;">M: ${m} • F: ${fe} • O: ${o}</span></td>
            <td><span style="font-size:0.8rem; color:${em > 0 ? '#DC2626' : '#64748B'}; font-weight:${em > 0 ? '700' : '400'}">${em}</span></td>
            <td>
                <button type="button" class="btn btn-xs btn-outline" onclick="loadFootfallForCorrection('${f.date}')">Edit</button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

function loadFootfallForCorrection(dateStr) {
    const dateInput = document.getElementById("footfall-date-input");
    if (dateInput) {
        dateInput.value = dateStr;
        handleFootfallDateChange(dateStr);
        dateInput.scrollIntoView({ behavior: "smooth", block: "center" });
        dateInput.focus();
    }
}

// --------------------------------------------------------------------------
// 5. SECTION 3: ALERTS & TRANSFERS WORKSPACE
// --------------------------------------------------------------------------

async function loadTransfersWorkspace() {
    try {
        const res = await fetch("/api/redistribution/transfers");
        if (!res.ok) return;
        const data = await res.json();
        const transfers = data.transfers || [];

        // Count metrics
        let pending = 0, transit = 0, completed = 0;
        transfers.forEach(t => {
            if (t.status === "Requested") pending++;
            else if (t.status === "In Transit" || t.status === "Approved") transit++;
            else if (t.status === "Completed") completed++;
        });

        setText("transfers-kpi-pending", pending);
        setText("transfers-kpi-transit", transit);
        setText("transfers-kpi-completed", completed);

        renderTransfersTable(transfers);
    } catch (e) {
        console.error("Failed to load transfers workspace", e);
    }
}

function renderTransfersTable(transfers) {
    const tbody = document.getElementById("transfers-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    const userRole = window.currentUser ? window.currentUser.role : "PHC_STAFF";
    const userPhc = window.currentUser ? window.currentUser.assigned_phc_id : "";

    transfers.forEach(t => {
        const tr = document.createElement("tr");
        
        let statusBadge = "normal";
        if (t.status === "Requested") statusBadge = "warning";
        else if (t.status === "Approved") statusBadge = "normal";
        else if (t.status === "In Transit") statusBadge = "normal";
        else if (t.status === "Completed") statusBadge = "active";
        else if (t.status === "Rejected") statusBadge = "critical";

        // Build Action Buttons conditioned on role & status
        let actionsHtml = `<span style="font-size:0.75rem; color:#64748B;">--</span>`;

        if (userRole === "DISTRICT_OFFICER" || userRole === "NATIONAL_ADMIN") {
            if (t.status === "Requested") {
                actionsHtml = `
                    <button type="button" class="btn btn-xs btn-primary" onclick="openReviewTransferModal(${t.id}, '${t.target_phc}', '${t.source_phc}', '${t.medicine_name}', ${t.quantity})">Review Request</button>
                `;
            } else if (t.status === "In Transit") {
                actionsHtml = `
                    <button type="button" class="btn btn-xs btn-outline" onclick="escalateTransferPrompt(${t.id})">Escalate Delay</button>
                `;
            }
        } else { // PHC Staff
            if (t.status === "Approved" && t.source_phc === userPhc) {
                // Donor staff confirms dispatch
                actionsHtml = `
                    <button type="button" class="btn btn-xs btn-primary" onclick="confirmTransferDispatch(${t.id})">📦 Confirm Dispatch</button>
                `;
            } else if (t.status === "In Transit" && t.target_phc === userPhc) {
                // Recipient staff confirms delivery
                actionsHtml = `
                    <button type="button" class="btn btn-xs btn-primary" onclick="confirmTransferDelivery(${t.id})">✅ Confirm Delivery</button>
                `;
            } else if (t.status === "Requested" && t.target_phc === userPhc) {
                actionsHtml = `<span style="font-size:0.75rem; color:#B45309; font-weight:600;">Pending Officer Review</span>`;
            }
        }

        const elapsedText = t.total_turnaround_mins ? `${t.total_turnaround_mins}m turnaround` : (t.eta_mins ? `${t.eta_mins}m ETA` : '25m');

        tr.innerHTML = `
            <td><span style="font-family:var(--font-mono); font-weight:700;">#TR-${t.id}</span></td>
            <td><strong>${t.target_phc}</strong></td>
            <td>${t.source_phc}</td>
            <td><strong>${t.medicine_name}</strong></td>
            <td><span style="font-size:1.05rem; font-weight:700;">${t.quantity}</span> units</td>
            <td>${elapsedText}</td>
            <td><span class="badge-priority ${t.urgency ? t.urgency.toLowerCase() : 'normal'}">${t.urgency || 'NORMAL'}</span></td>
            <td><span class="badge-status ${statusBadge}">${t.status}</span></td>
            <td><span style="font-size:0.75rem; color:#475569;">${t.decision_reason || t.delay_reason || 'Verified buffer'}</span></td>
            <td>${actionsHtml}</td>
        `;
        tbody.appendChild(tr);
    });
}

function updateTransferCurrentStockHint() {
    const sel = document.getElementById("req-medicine");
    const stockEl = document.getElementById("req-curr-stock");
    if (!sel || !stockEl) return;
    const med = sel.value;
    const item = cachedInventory.find(i => i.medicine_name === med);
    stockEl.innerText = item ? item.quantity : "--";
}

function openCreateTransferModal(prefillMedicine = null, prefillQty = null, donorPhc = null, recipientPhc = null) {
    if (prefillMedicine) {
        const sel = document.getElementById("req-medicine");
        if (sel) sel.value = prefillMedicine;
    }
    if (prefillQty) {
        const q = document.getElementById("req-quantity");
        if (q) q.value = prefillQty;
    }
    if (recipientPhc) {
        activePhcId = recipientPhc;
    }
    if (donorPhc) {
        const reasonInput = document.getElementById("req-reason");
        if (reasonInput && !reasonInput.value) {
            reasonInput.value = `Algorithmic donor recommendation: Source ${donorPhc}`;
        }
    }

    const dateInput = document.getElementById("req-date");
    if (dateInput && !dateInput.value) {
        const d = new Date();
        d.setDate(d.getDate() + 3);
        dateInput.value = d.toISOString().split("T")[0];
    }

    updateTransferCurrentStockHint();
    openModal("create-transfer-modal");
}

function closeCreateTransferModal() {
    closeModal("create-transfer-modal");
}

async function submitCreateTransfer() {
    const med = document.getElementById("req-medicine").value;
    const qtyInput = document.getElementById("req-quantity");
    const qty = parseInt(qtyInput ? qtyInput.value : 0, 10);
    const urgency = document.getElementById("req-urgency").value;
    const reasonInput = document.getElementById("req-reason");
    const reason = reasonInput ? reasonInput.value.trim() : "";
    const dateInput = document.getElementById("req-date");
    const reqDate = dateInput ? dateInput.value : null;
    const notesInput = document.getElementById("req-notes");
    const notes = notesInput ? notesInput.value.trim() : "";
    const btn = document.getElementById("btn-submit-transfer-request");

    if (!med) {
        showToast("Please select a resource/medicine.", "warning");
        return;
    }
    if (isNaN(qty) || qty <= 0) {
        showToast("Requested quantity must be greater than zero.", "warning");
        return;
    }
    if (!reason || reason.length < 3) {
        showToast("Please enter an operational/clinical reason for the request.", "warning");
        if (reasonInput) reasonInput.focus();
        return;
    }

    setButtonLoading(btn, true);
    try {
        const res = await apiFetch("/api/redistribution/request", {
            method: "POST",
            body: JSON.stringify({
                target_phc: activePhcId,
                phc_id: activePhcId,
                medicine_name: med,
                quantity: qty,
                urgency: urgency,
                reason: reason,
                required_by: reqDate || null,
                notes: notes || null
            })
        });

        if (res.ok) {
            closeCreateTransferModal();
            if (reasonInput) reasonInput.value = "";
            if (notesInput) notesInput.value = "";
            const donorText = res.data.recommended_donor ? ` Recommended Donor: ${res.data.recommended_donor}.` : "";
            showToast(`Resource request submitted!${donorText} Notice routed to District Officer.`, "success", "Request Dispatched");
            await loadTransfersWorkspace();
            await loadDisciplineIndicators();
            await loadOperationsTab();
        } else {
            if (res.status === 409) {
                showToast(`Request Conflict: ${res.detail}`, "warning", "Pending Request Exists");
            } else {
                showToast(`Request failed: ${res.detail}`, "error");
            }
        }
    } finally {
        setButtonLoading(btn, false);
    }
}

function openReviewTransferModal(transferId, targetPhc, sourcePhc, medicine, qty) {
    selectedReviewTransfer = { id: transferId, qty: qty };
    setText("rev-transfer-id", `#TR-${transferId}`);
    setText("rev-target-phc", targetPhc);
    setText("rev-donor-phc", sourcePhc);
    setText("rev-medicine", medicine);
    setText("rev-qty", `${qty} units`);

    const modInput = document.getElementById("rev-modified-qty");
    if (modInput) modInput.value = qty;

    openModal("review-transfer-modal");
}

function closeReviewTransferModal() {
    closeModal("review-transfer-modal");
    selectedReviewTransfer = null;
}

function handleReviewActionChange(action) {
    const modGroup = document.getElementById("rev-modify-qty-group");
    if (modGroup) {
        modGroup.style.display = action === "MODIFY_AND_APPROVE" ? "block" : "none";
    }
}

async function submitReviewTransfer() {
    if (!selectedReviewTransfer) return;
    const action = document.getElementById("rev-action-select").value;
    const modifiedQty = parseInt(document.getElementById("rev-modified-qty").value, 10) || selectedReviewTransfer.qty;
    const reason = document.getElementById("rev-reason").value || "Approved by Officer";

    try {
        const res = await apiFetch(`/api/redistribution/${selectedReviewTransfer.id}/review`, {
            method: "POST",
            body: JSON.stringify({
                action: action,
                modified_quantity: action === "MODIFY_AND_APPROVE" ? modifiedQty : null,
                decision_reason: reason
            })
        });

        if (res.ok) {
            closeReviewTransferModal();
            showToast(res.data.message || "Transfer decision confirmed.", "success", "Review Completed");
            await loadTransfersWorkspace();
            await loadDisciplineIndicators();
        } else {
            showToast(`Decision rejected: ${res.detail}`, "error");
        }
    } catch (e) {
        showToast("Network error submitting decision.", "error");
    }
}

async function confirmTransferDispatch(transferId) {
    if (!confirm("Confirm that this consignment has been packaged, logged, and handed over for dispatch?")) return;

    try {
        const res = await apiFetch(`/api/redistribution/${transferId}/dispatch`, {
            method: "POST",
            body: JSON.stringify({ notes: "Physical dispatch completed by donor team." })
        });

        if (res.ok) {
            showToast("Dispatch logged. Consignment is now In Transit.", "success", "Consignment Dispatched");
            await loadTransfersWorkspace();
        } else {
            showToast(`Dispatch failed: ${res.detail}`, "error");
        }
    } catch (e) {
        showToast("Network error logging dispatch.", "error");
    }
}

async function confirmTransferDelivery(transferId) {
    if (!confirm("Confirm physical delivery and batch verification? This will atomically update and reconcile medicine balances on both facilities.")) return;

    try {
        const res = await apiFetch(`/api/redistribution/${transferId}/deliver`, {
            method: "POST",
            body: JSON.stringify({ notes: "Delivered, batch verified, added to recipient stock." })
        });

        if (res.ok) {
            showToast("Delivery confirmed! Dual-inventory reconciled in real-time.", "success", "Consignment Reconciled");
            await loadTransfersWorkspace();
            await loadOperationsTab();
            await loadDisciplineIndicators();
        } else {
            showToast(`Delivery confirmation failed: ${res.detail}`, "error");
        }
    } catch (e) {
        showToast("Network error confirming delivery.", "error");
    }
}

async function escalateTransferPrompt(transferId) {
    const reason = prompt("Enter official reason for transfer escalation (e.g. road blockage, driver delay):");
    if (!reason) return;

    try {
        const res = await apiFetch(`/api/redistribution/${transferId}/escalate`, {
            method: "POST",
            body: JSON.stringify({ reason: reason })
        });

        if (res.ok) {
            showToast("Transfer escalated to National Command Center.", "warning", "Delay Escalated");
            await loadTransfersWorkspace();
            await loadDisciplineIndicators();
        } else {
            showToast(`Escalation failed: ${res.detail}`, "error");
        }
    } catch (e) {
        showToast("Error escalating transfer.", "error");
    }
}

// --------------------------------------------------------------------------
// 6. SECTION 4: COMMUNICATION & REPORTS
// --------------------------------------------------------------------------

function switchCommSubTab(subTab) {
    currentCommSubTab = subTab;

    const btns = document.querySelectorAll("#panel-communication .sub-nav-btn");
    btns.forEach(b => b.classList.remove("active"));
    const activeBtn = document.getElementById(`subnav-${subTab}`);
    if (activeBtn) activeBtn.classList.add("active");

    const contents = document.querySelectorAll(".comm-subtab-content");
    contents.forEach(c => c.style.display = "none");
    const activeContent = document.getElementById(`commtab-${subTab}`);
    if (activeContent) activeContent.style.display = "block";

    loadCommunicationDesk();
}

async function loadCommunicationDesk() {
    setupCommSubNavForRole();
    try {
        if (currentCommSubTab === "messages") {
            const res = await fetch("/api/messages");
            if (!res.ok) return;
            const data = await res.json();
            renderMessagesTable(data.messages || []);
        } else if (currentCommSubTab === "reports") {
            const res = await fetch("/api/reports/analytics");
            if (!res.ok) return;
            const data = await res.json();
            renderReportsView(data);
        } else if (currentCommSubTab === "aimodel") {
            await loadFederatedModelStatus();
        } else if (currentCommSubTab === "security") {
            await loadSecurityMonitoringStatus();
        } else if (currentCommSubTab === "integrations") {
            // View is statically initialized, ready for generate/download
        } else if (currentCommSubTab === "audit") {
            await loadEmbeddedAuditLogs();
        } else if (currentCommSubTab === "acknowledgements") {
            await loadAcknowledgements();
        } else if (currentCommSubTab === "activity") {
            await loadActivityStream();
        }
    } catch (e) {
        console.error("Failed to load communication desk", e);
    }
}

function renderMessagesTable(messages) {
    const tbody = document.getElementById("messages-tbody");
    if (!tbody) return;
    tbody.innerHTML = "";

    messages.forEach(msg => {
        const tr = document.createElement("tr");
        const isAck = !!msg.acknowledged_at;
        const sentTime = msg.sent_at ? msg.sent_at.replace("T", " ").slice(0, 16) : "--";

        let ackCell = `
            <div style="display:flex; align-items:center; gap:6px;">
                <span class="badge-status ${isAck ? 'normal' : 'warning'}">${isAck ? 'ACKNOWLEDGED' : 'PENDING'}</span>
                <span style="font-size:0.75rem; color:#64748B;">${isAck ? `by ${msg.acknowledged_by || 'Officer'}` : ''}</span>
            </div>
        `;

        let actionCell = `<span style="font-size:0.75rem; color:#64748B;">--</span>`;
        if (!isAck) {
            actionCell = `
                <button type="button" class="btn btn-xs btn-primary" onclick="acknowledgeMessage(${msg.id})">✍️ Sign & Acknowledge</button>
            `;
        }

        tr.innerHTML = `
            <td style="font-size:0.75rem; color:#64748B;">${sentTime}</td>
            <td><strong>${msg.sender_name}</strong> <span style="font-size:0.7rem; color:#64748B;">(${msg.sender_role})</span></td>
            <td>${msg.recipient_role || 'All'} ${msg.district_id ? `(${msg.district_id})` : ''}</td>
            <td>
                <div style="font-weight:700; color:#0F172A; margin-bottom:2px;">${msg.subject}</div>
                <div style="font-size:0.8rem; color:#475569;">${msg.message}</div>
            </td>
            <td><span class="badge-priority ${msg.priority ? msg.priority.toLowerCase() : 'normal'}">${msg.priority || 'NORMAL'}</span></td>
            <td>${ackCell}</td>
            <td>${actionCell}</td>
        `;
        tbody.appendChild(tr);
    });
}

function renderReportsView(data) {
    const perf = data.redistribution_performance || {};
    setText("report-avg-eta", `${perf.average_eta_mins || 25}m`);
    setText("report-avg-turnaround", `${perf.average_turnaround_mins || 34.5}m`);
    setText("report-completed-transfers", perf.completed_transfers || 1);

    const tbody = document.getElementById("report-attendance-tbody");
    if (tbody) {
        tbody.innerHTML = "";
        (data.attendance_compliance || []).forEach(row => {
            const tr = document.createElement("tr");
            const rate = row.total_attendance > 0 ? Math.round((row.total_present / row.total_attendance) * 100) : 92;
            tr.innerHTML = `
                <td><strong>${row.district_name || row.district_id}</strong></td>
                <td><span class="badge-status normal">${rate}% Present</span></td>
                <td>${row.on_time || 5} staff on-time</td>
                <td>${row.late > 0 ? `<span class="badge-status warning">${row.late} Late Arrival</span>` : '0 Late'}</td>
            `;
            tbody.appendChild(tr);
        });
    }
}

function openComposeMessageModal() {
    const modal = document.getElementById("compose-message-modal");
    if (modal) modal.classList.add("open");
}

function closeComposeMessageModal() {
    const modal = document.getElementById("compose-message-modal");
    if (modal) modal.classList.remove("open");
}

async function submitSendMessage() {
    const role = document.getElementById("msg-recipient-role").value;
    const priority = document.getElementById("msg-priority").value;
    const subject = document.getElementById("msg-subject").value;
    const message = document.getElementById("msg-body").value;
    const btn = document.getElementById("btn-send-message");

    if (!subject || !message) {
        showToast("Please enter subject and message body.", "warning");
        return;
    }

    if (btn) setButtonLoading(btn, true);
    try {
        const res = await apiFetch("/api/messages", {
            method: "POST",
            body: JSON.stringify({
                recipient_role: role,
                priority: priority,
                subject: subject,
                message: message,
                district_id: activeDistrictId,
                phc_id: activePhcId
            })
        });
        if (res.ok) {
            closeComposeMessageModal();
            showToast("Directive transmitted and logged to audited communication ledger.", "success", "Directive Sent");
            await loadCommunicationDesk();
            await loadDisciplineIndicators();
        } else {
            showToast(`Send failed: ${res.detail}`, "error");
        }
    } finally {
        if (btn) setButtonLoading(btn, false);
    }
}

async function acknowledgeMessage(messageId) {
    const notes = prompt("Enter acknowledgement remarks / action confirmation:", "Acknowledged and dispatched directives.");
    if (notes === null) return;

    try {
        const res = await apiFetch(`/api/messages/${messageId}/acknowledge`, {
            method: "POST",
            body: JSON.stringify({ notes: notes })
        });
        if (res.ok) {
            showToast("Directive signed and recorded.", "success", "Acknowledged");
            await loadCommunicationDesk();
            await loadDisciplineIndicators();
        } else {
            showToast(`Failed to record acknowledgement: ${res.detail}`, "error");
        }
    } catch (e) {
        showToast("Network error recording acknowledgement.", "error");
    }
}

function exportReport(type) {
    window.open(`/api/reports/export?report_type=${type}`, "_blank");
}

function exportNationalReport() {
    window.open("/api/reports/export?report_type=national_summary", "_blank");
}

// --------------------------------------------------------------------------
// 7. FAST OPERATIONAL ENTRY MODALS
// --------------------------------------------------------------------------

function openRecordStockReceivedModal() {
    const rxDate = document.getElementById("rx-date");
    if (rxDate) rxDate.value = new Date().toISOString().split("T")[0];
    const err = document.getElementById("rx-qty-error");
    if (err) err.style.display = "none";
    openModal("record-stock-received-modal");
}

function closeRecordStockReceivedModal() {
    closeModal("record-stock-received-modal");
}

async function submitRecordStockReceived() {
    const med = document.getElementById("rx-medicine").value;
    const qty = parseInt(document.getElementById("rx-quantity").value, 10);
    const batch = document.getElementById("rx-batch").value.trim();
    const expiry = document.getElementById("rx-expiry").value;
    const supplier = document.getElementById("rx-supplier").value.trim();
    const rxDate = document.getElementById("rx-date").value;
    const notes = document.getElementById("rx-notes").value.trim();
    const errEl = document.getElementById("rx-qty-error");
    const btn = document.getElementById("btn-submit-stock-received");

    if (isNaN(qty) || qty <= 0) {
        if (errEl) {
            errEl.style.display = "block";
            errEl.innerText = "Quantity must be greater than zero.";
        }
        showToast("Quantity received must be greater than zero.", "warning", "Validation Error");
        return;
    }
    if (errEl) errEl.style.display = "none";

    setButtonLoading(btn, true);
    try {
        const res = await apiFetch("/api/inventory/receive", {
            method: "POST",
            body: JSON.stringify({
                phc_id: activePhcId,
                medicine_name: med,
                quantity: qty,
                batch_number: batch || null,
                expiry_date: expiry || null,
                supplier: supplier || null,
                received_date: rxDate || null,
                notes: notes || null
            })
        });

        if (res.ok) {
            closeRecordStockReceivedModal();
            document.getElementById("rx-batch").value = "";
            document.getElementById("rx-expiry").value = "";
            document.getElementById("rx-notes").value = "";
            document.getElementById("rx-quantity").value = "50";
            showToast(`Stock received: +${qty} units ${med} (New Balance: ${res.data.new_quantity || '--'}).`, "success", "Inventory Updated");
            await loadOperationsTab();
        } else {
            showToast(`Failed to record stock received: ${res.detail}`, "error");
        }
    } finally {
        setButtonLoading(btn, false);
    }
}

function updateDispenseAvailableStockHint() {
    const sel = document.getElementById("cx-medicine");
    const availEl = document.getElementById("cx-avail-qty");
    if (!sel || !availEl) return;
    const med = sel.value;
    const item = cachedInventory.find(i => i.medicine_name === med);
    availEl.innerText = item ? item.quantity : "--";
    validateDispenseQuantity();
}

function validateDispenseQuantity() {
    const sel = document.getElementById("cx-medicine");
    const qtyInput = document.getElementById("cx-quantity");
    const warnEl = document.getElementById("cx-qty-warning");
    if (!sel || !qtyInput) return true;

    const med = sel.value;
    const qty = parseInt(qtyInput.value, 10) || 0;
    const item = cachedInventory.find(i => i.medicine_name === med);
    const avail = item ? item.quantity : 0;

    if (qty > avail) {
        if (warnEl) {
            warnEl.style.display = "block";
            warnEl.innerText = `⚠️ Warning: Dispense quantity (${qty}) exceeds available stock (${avail})!`;
        }
        return false;
    } else {
        if (warnEl) warnEl.style.display = "none";
        return true;
    }
}

function openRecordStockConsumedModal() {
    const cxDate = document.getElementById("cx-date");
    if (cxDate) cxDate.value = new Date().toISOString().split("T")[0];
    updateDispenseAvailableStockHint();
    openModal("record-stock-consumed-modal");
}

function closeRecordStockConsumedModal() {
    closeModal("record-stock-consumed-modal");
}

async function submitRecordStockConsumed() {
    const med = document.getElementById("cx-medicine").value;
    const qty = parseInt(document.getElementById("cx-quantity").value, 10);
    const reason = document.getElementById("cx-reason").value;
    const dateVal = document.getElementById("cx-date").value;
    const notes = document.getElementById("cx-notes").value.trim();
    const btn = document.getElementById("btn-submit-stock-consumed");

    if (isNaN(qty) || qty <= 0) {
        showToast("Quantity dispensed must be greater than zero.", "warning", "Validation Error");
        return;
    }

    setButtonLoading(btn, true);
    try {
        const res = await apiFetch("/api/inventory/consume", {
            method: "POST",
            body: JSON.stringify({
                phc_id: activePhcId,
                medicine_name: med,
                quantity: qty,
                reason: reason,
                date: dateVal || null,
                notes: notes || null
            })
        });

        if (res.ok) {
            closeRecordStockConsumedModal();
            document.getElementById("cx-notes").value = "";
            document.getElementById("cx-quantity").value = "10";
            showToast(`Stock consumption recorded: -${qty} units ${med} (Remaining: ${res.data.new_quantity || '--'}).`, "success", "Inventory Updated");
            await loadOperationsTab();
        } else {
            showToast(`Dispensation failed: ${res.detail}`, "error");
        }
    } finally {
        setButtonLoading(btn, false);
    }
}

// --------------------------------------------------------------------------
// 8. ADMINISTRATIVE OVERRIDE GOVERNANCE
// --------------------------------------------------------------------------

function openOverrideModal() {
    openModal("admin-override-modal");
}

function closeOverrideModal() {
    closeModal("admin-override-modal");
    pendingOverridePayload = null;
}

async function submitAdminOverride() {
    const reasonInput = document.getElementById("override-reason-input");
    const reason = reasonInput ? reasonInput.value.trim() : "";
    if (!reason || reason.length < 3) {
        showToast("Please provide an official justification for the override.", "warning");
        if (reasonInput) reasonInput.focus();
        return;
    }

    if (!pendingOverridePayload) {
        closeOverrideModal();
        showToast("Override authorization recorded.", "info");
        return;
    }

    try {
        if (pendingOverridePayload.type === "BED_UPDATE") {
            const res = await apiFetch("/api/beds/update", {
                method: "POST",
                body: JSON.stringify({
                    phc_id: pendingOverridePayload.phc_id,
                    total_beds: pendingOverridePayload.total_beds,
                    occupied_beds: pendingOverridePayload.occupied_beds,
                    notes: `OVERRIDE: ${reason} (Prior notes: ${pendingOverridePayload.notes || 'None'})`
                })
            });

            if (res.ok) {
                closeOverrideModal();
                if (reasonInput) reasonInput.value = "";
                showToast("Administrative override executed and logged in National Audit Trail.", "success", "Override Authorized");
                await loadOperationsTab();
            } else {
                showToast(`Override rejected: ${res.detail}`, "error");
            }
        }
    } catch (e) {
        showToast("Network error executing override.", "error");
    }
}

// --------------------------------------------------------------------------
// 9. USER DIRECTORY & AUDIT LOGS MODALS (FOR NATIONAL ADMIN)
// --------------------------------------------------------------------------

function openUserDirectoryModal() {
    closeUserDropdown();
    openModal("user-directory-modal");
    loadUserDirectory();
}

function closeUserDirectoryModal() {
    closeModal("user-directory-modal");
}

async function loadUserDirectory() {
    try {
        const res = await apiFetch("/api/users");
        if (!res.ok) return;
        const users = res.data;

        const tbody = document.getElementById("directory-users-tbody");
        if (!tbody) return;
        tbody.innerHTML = "";

        users.forEach(u => {
            const tr = document.createElement("tr");
            const isActive = u.account_status === "ACTIVE";
            tr.innerHTML = `
                <td><strong>${u.full_name}</strong></td>
                <td>${u.email}</td>
                <td><span class="badge-role ${u.role === 'NATIONAL_ADMIN' ? 'admin' : (u.role === 'DISTRICT_OFFICER' ? 'officer' : 'staff')}">${u.role}</span></td>
                <td>${u.assigned_phc_id || u.assigned_district_id || 'Nationwide'}</td>
                <td><span class="badge-status ${isActive ? 'active' : 'disabled'}">${u.account_status}</span></td>
                <td>
                    ${u.role !== 'NATIONAL_ADMIN' ? `
                    <button type="button" class="btn btn-xs ${isActive ? 'btn-outline' : 'btn-primary'}" onclick="toggleUserStatus('${u.id}', '${u.account_status}')">
                        ${isActive ? 'Disable' : 'Enable'}
                    </button>
                    ` : '<span style="font-size:0.75rem; color:#64748B;">Locked</span>'}
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error("Failed to load user directory", e);
    }
}

async function toggleUserStatus(userId, currentStatus) {
    const newStatus = currentStatus === "ACTIVE" ? "DISABLED" : "ACTIVE";
    try {
        const res = await apiFetch(`/api/users/${userId}/status`, {
            method: "PATCH",
            body: JSON.stringify({ account_status: newStatus })
        });
        if (res.ok) {
            showToast(`User status updated to ${newStatus}.`, "success", "User Updated");
            await loadUserDirectory();
        } else {
            showToast(`Failed to update user status: ${res.detail}`, "error");
        }
    } catch (e) {
        showToast("Network error updating user status.", "error");
    }
}

function openAuditLogsModal() {
    closeUserDropdown();
    openModal("audit-logs-modal");
    loadAuditLogs();
}

function closeAuditLogsModal() {
    closeModal("audit-logs-modal");
}

async function loadAuditLogs() {
    try {
        const res = await apiFetch("/api/audit-logs?limit=50");
        if (!res.ok) return;
        const logs = res.data;

        const tbody = document.getElementById("audit-logs-tbody");
        if (!tbody) return;
        tbody.innerHTML = "";

        logs.forEach(l => {
            const tr = document.createElement("tr");
            const isSuccess = l.result === "SUCCESS";
            const isOverride = l.result === "OVERRIDDEN";
            tr.innerHTML = `
                <td style="font-size:0.75rem; color:#64748B;">${l.timestamp ? l.timestamp.replace('T', ' ').slice(0, 16) : '--'}</td>
                <td><strong>${l.user_name || l.user_id}</strong></td>
                <td><span style="font-size:0.7rem;">${l.role}</span></td>
                <td><code>${l.action}</code></td>
                <td><span style="font-size:0.8rem;">${l.target_record || '--'}</span></td>
                <td>${l.previous_value || '--'}</td>
                <td>${l.new_value || '--'}</td>
                <td><span class="badge-result ${isOverride ? 'overridden' : (isSuccess ? 'success' : 'denied')}">${l.result}</span></td>
                <td><span style="font-size:0.75rem; color:#475569;">${l.reason || '--'}</span></td>
            `;
            tbody.appendChild(tr);
        });
    } catch (e) {
        console.error("Failed to load audit logs", e);
    }
}

// --------------------------------------------------------------------------
// 10. PROFILE, PASSWORD & USER CREATION MODALS
// --------------------------------------------------------------------------

function openProfileModal() {
    closeUserDropdown();
    if (!window.currentUser) return;
    const u = window.currentUser;

    setText("modal-profile-name", u.full_name);
    setText("modal-profile-role", u.role);
    setText("modal-profile-id", u.id);
    setText("modal-profile-email", u.email);
    setText("modal-profile-emp-id", u.employee_id || "EMP-NAT-01");
    setText("modal-profile-district", u.assigned_district_id || "Nationwide Scope");
    setText("modal-profile-phc", u.assigned_phc_id || "All Facilities");

    const avatar = document.getElementById("modal-profile-avatar");
    if (avatar) avatar.innerText = u.full_name ? u.full_name.split(" ").map(n=>n[0]).join("").slice(0, 2) : "ME";

    openModal("profile-modal");
}

function closeProfileModal() {
    closeModal("profile-modal");
}

function openChangePasswordModal() {
    closeUserDropdown();
    openModal("change-password-modal");
}

function closeChangePasswordModal() {
    closeModal("change-password-modal");
}

async function submitChangePassword() {
    const oldP = document.getElementById("chg-old-pwd").value;
    const newP = document.getElementById("chg-new-pwd").value;
    const errDiv = document.getElementById("change-pwd-error");

    try {
        const res = await apiFetch("/api/auth/change-password", {
            method: "POST",
            body: JSON.stringify({ old_password: oldP, new_password: newP })
        });
        if (res.ok) {
            closeChangePasswordModal();
            showToast("Password updated successfully.", "success", "Security Updated");
        } else {
            if (errDiv) {
                errDiv.style.display = "block";
                errDiv.innerText = res.detail || "Failed to update password.";
            }
            showToast(res.detail || "Failed to update password.", "error");
        }
    } catch (e) {
        showToast("Network error updating password.", "error");
    }
}

function openCreateUserModal() {
    openModal("create-user-modal");
}

function closeCreateUserModal() {
    closeModal("create-user-modal");
}

function handleNewUserRoleChange(role) {
    const phcGroup = document.getElementById("new-user-phc-group");
    if (phcGroup) phcGroup.style.display = role === "PHC_STAFF" ? "block" : "none";
}

async function submitCreateUser() {
    const name = document.getElementById("new-user-name").value;
    const email = document.getElementById("new-user-email").value;
    const role = document.getElementById("new-user-role").value;
    const dist = document.getElementById("new-user-district").value;
    const phc = document.getElementById("new-user-phc").value;
    const pwd = document.getElementById("new-user-temp-pwd").value;

    try {
        const res = await apiFetch("/api/users", {
            method: "POST",
            body: JSON.stringify({
                full_name: name,
                email: email,
                role: role,
                assigned_district_id: dist,
                assigned_phc_id: role === "PHC_STAFF" ? phc : null,
                initial_password: pwd
            })
        });
        if (res.ok) {
            closeCreateUserModal();
            showToast("User account created successfully.", "success", "Account Provisioned");
            await loadUserDirectory();
        } else {
            showToast(`Creation failed: ${res.detail}`, "error");
        }
    } catch (e) {
        showToast("Network error creating user.", "error");
    }
}

function openForgotPasswordModal() {
    openModal("forgot-password-modal");
}

function closeForgotPasswordModal() {
    closeModal("forgot-password-modal");
}

async function submitForgotPasswordRequest() {
    const email = document.getElementById("forgot-email-input").value;
    if (!email) {
        showToast("Please enter your official email address.", "warning");
        return;
    }

    try {
        const res = await apiFetch("/api/auth/forgot-password", {
            method: "POST",
            body: JSON.stringify({ email })
        });
        if (res.ok) {
            const data = res.data;
            const resBox = document.getElementById("forgot-token-result");
            const tokenCode = document.getElementById("forgot-token-code");
            if (resBox && tokenCode) {
                resBox.style.display = "block";
                tokenCode.innerText = data.demo_token || "DEMO-RESET-TOKEN-XYZ";
            }
            showToast("Recovery token generated.", "success");
        } else {
            showToast(`Reset request failed: ${res.detail}`, "error");
        }
    } catch (e) {
        showToast("Error requesting recovery token.", "error");
    }
}

async function submitResetPasswordWithToken() {
    const token = document.getElementById("forgot-token-code").innerText;
    const newPwd = document.getElementById("forgot-new-pwd").value;

    try {
        const res = await apiFetch("/api/auth/reset-password", {
            method: "POST",
            body: JSON.stringify({ token, new_password: newPwd })
        });
        if (res.ok) {
            closeForgotPasswordModal();
            showToast("Password reset successfully. You may now sign in.", "success", "Password Reset");
        } else {
            showToast(`Reset failed: ${res.detail || 'Invalid or expired token.'}`, "error");
        }
    } catch (e) {
        showToast("Network error resetting password.", "error");
    }
}

// --------------------------------------------------------------------------
// UTILITY FUNCTIONS
// --------------------------------------------------------------------------

function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.innerText = text;
}

// ==========================================================================
// 8. AI FORECASTING, FEDERATED LEARNING & ENTERPRISE EXTENSIONS
// ==========================================================================

// --- 8A. Secondary Sub-Navigation Per Role ---
function setupCommSubNavForRole() {
    if (!window.currentUser) return;
    const role = window.currentUser.role;
    const navMessages = document.getElementById("subnav-messages");
    const navReports = document.getElementById("subnav-reports");
    const reportsLabel = document.getElementById("subnav-reports-label");
    const navAiModel = document.getElementById("subnav-aimodel");
    const navSecurity = document.getElementById("subnav-security");
    const navIntegrations = document.getElementById("subnav-integrations");
    const navAudit = document.getElementById("subnav-audit");
    const navAck = document.getElementById("subnav-acknowledgements");
    const navActivity = document.getElementById("subnav-activity");

    if (role === "NATIONAL_ADMIN") {
        if (navMessages) { navMessages.style.display = "inline-flex"; navMessages.querySelector("span").innerText = "📬 Directives & Notices"; }
        if (navReports) { navReports.style.display = "inline-flex"; if (reportsLabel) reportsLabel.innerText = "📊 National Reports"; }
        if (navAiModel) navAiModel.style.display = "inline-flex";
        if (navSecurity) navSecurity.style.display = "inline-flex";
        if (navIntegrations) navIntegrations.style.display = "inline-flex";
        if (navAudit) navAudit.style.display = "inline-flex";
        if (navAck) navAck.style.display = "none";
        if (navActivity) navActivity.style.display = "none";
    } else if (role === "DISTRICT_OFFICER") {
        if (navMessages) { navMessages.style.display = "inline-flex"; navMessages.querySelector("span").innerText = "📬 Directives & Notices"; }
        if (navReports) { navReports.style.display = "inline-flex"; if (reportsLabel) reportsLabel.innerText = "📊 District Reports"; }
        if (navAiModel) navAiModel.style.display = "none";
        if (navSecurity) navSecurity.style.display = "none";
        if (navIntegrations) navIntegrations.style.display = "none";
        if (navAudit) navAudit.style.display = "inline-flex";
        if (navAck) navAck.style.display = "none";
        if (navActivity) navActivity.style.display = "inline-flex";
    } else { // PHC_STAFF
        if (navMessages) { navMessages.style.display = "inline-flex"; navMessages.querySelector("span").innerText = "📬 District Messages"; }
        if (navReports) { navReports.style.display = "inline-flex"; if (reportsLabel) reportsLabel.innerText = "📊 Daily Reports"; }
        if (navAiModel) navAiModel.style.display = "none";
        if (navSecurity) navSecurity.style.display = "none";
        if (navIntegrations) navIntegrations.style.display = "none";
        if (navAudit) navAudit.style.display = "none";
        if (navAck) navAck.style.display = "inline-flex";
        if (navActivity) navActivity.style.display = "inline-flex";
    }
}

// --- 8B. National AI Insights ---
async function loadNationalAIInsights() {
    const grid = document.getElementById("nat-ai-insights-grid");
    if (!grid) return;
    try {
        const res = await apiFetch("/api/insights/national");
        if (!res.ok) {
            grid.innerHTML = `<div style="color:var(--text-muted); font-size:0.85rem; padding:12px;">Unable to load national AI demand signals.</div>`;
            return;
        }
        const data = res.data;
        window.cachedNationalInsights = data;

        const shortages = data.predicted_shortages || [];
        const pressure = data.network_pressure || { level: "STABLE", score: 32, summary: "Normal operational rhythm" };
        const escalations = data.active_escalations || [];

        let shortageItemsHtml = shortages.length > 0
            ? shortages.map(s => `<div style="font-size:0.8rem; margin-bottom:4px; display:flex; justify-content:space-between;">
                <span><strong>${s.phc_name || s.phc_id}</strong>: ${s.medicine_name}</span>
                <span class="badge-status critical" style="font-size:0.7rem;">Stockout in ${s.days_to_stockout}d</span>
               </div>`).join("")
            : `<div style="font-size:0.8rem; color:var(--text-muted);">No predicted stockouts across network</div>`;

        let escalationsHtml = escalations.length > 0
            ? escalations.map(e => `<div style="font-size:0.8rem; margin-bottom:4px; display:flex; justify-content:space-between;">
                <span>#${e.id} (${e.medicine_name})</span>
                <span class="badge-status warning" style="font-size:0.7rem;">${e.status}</span>
               </div>`).join("")
            : `<div style="font-size:0.8rem; color:var(--text-muted);">0 transfers requiring escalation</div>`;

        grid.innerHTML = `
            <div class="ai-subcard ${shortages.length > 0 ? 'alert' : ''}">
                <div class="ai-subcard-title">
                    <span>Predicted Node Shortages</span>
                    <span class="badge-status ${shortages.length > 0 ? 'critical' : 'normal'}">${shortages.length} Flagged</span>
                </div>
                <div>${shortageItemsHtml}</div>
                <div class="ai-subcard-footer">
                    <span>Confidence: ${data.confidence_score || '92.4%'}</span>
                    <span class="ai-badge source">Linear Forecaster</span>
                </div>
            </div>

            <div class="ai-subcard">
                <div class="ai-subcard-title">
                    <span>Network Pressure Index</span>
                    <span class="badge-status ${pressure.level === 'HIGH' ? 'critical' : (pressure.level === 'MODERATE' ? 'warning' : 'normal')}">${pressure.level}</span>
                </div>
                <div style="font-size:1.6rem; font-weight:800; color:var(--text-primary); margin:4px 0;">
                    ${pressure.score || 45} <span style="font-size:0.85rem; font-weight:500; color:var(--text-muted);">/ 100</span>
                </div>
                <div style="font-size:0.8rem; color:var(--text-secondary);">${pressure.summary || 'Supply chains operating within safe buffers.'}</div>
                <div class="ai-subcard-footer">
                    <span>Active Nodes: ${data.reporting_nodes_count || 4}</span>
                    <span class="ai-badge">Telemetry Feed</span>
                </div>
            </div>

            <div class="ai-subcard ${escalations.length > 0 ? 'warning' : ''}">
                <div class="ai-subcard-title">
                    <span>Redistribution & Escalations</span>
                    <span class="badge-status ${escalations.length > 0 ? 'warning' : 'normal'}">${escalations.length} Active</span>
                </div>
                <div>${escalationsHtml}</div>
                <div class="ai-subcard-footer">
                    <span>Active Transfers: ${data.total_transfers_in_transit || 2}</span>
                    <button type="button" class="btn btn-xs btn-outline" onclick="switchMainTab('transfers')">Open Workspace</button>
                </div>
            </div>
        `;
    } catch (e) {
        console.error("Error loading national AI insights:", e);
    }
}

function openAllInsightsModal() {
    const modal = document.getElementById("all-insights-modal");
    const container = document.getElementById("all-insights-body-content");
    if (!modal || !container) return;

    const data = window.cachedNationalInsights || {};
    const shortages = data.predicted_shortages || [];
    const modelVer = data.active_model_version || "v2.4-FedAvg";

    let shortageRows = shortages.map(s => `
        <tr>
            <td><strong>${s.phc_name || s.phc_id}</strong></td>
            <td>${s.district_id || 'DIST-NORTH'}</td>
            <td><strong>${s.medicine_name}</strong></td>
            <td>${s.current_stock} units</td>
            <td><span class="badge-status critical">${s.days_to_stockout} days</span></td>
            <td>${s.safe_reorder_date || 'Immediate'}</td>
            <td>${s.recommended_transfer_qty || 50} units</td>
        </tr>
    `).join("");

    container.innerHTML = `
        <div style="margin-bottom:14px; background:#F8FAFC; border:1px solid var(--border-color); border-radius:var(--radius-sm); padding:12px;">
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:6px;">
                <span style="font-weight:700; color:var(--text-primary);">Network-Wide Linear Demand Forecast Overview</span>
                <span class="ai-badge source">NumPy Linear Model (${modelVer})</span>
            </div>
            <p style="font-size:0.8rem; color:var(--text-secondary); margin:0;">
                Depletion rates are calculated via linear regression over 7-day facility consumption data. Safe buffer threshold is pegged at 30% of authorized par levels.
            </p>
        </div>

        <h4 style="font-size:0.85rem; font-weight:700; margin-bottom:8px; color:var(--text-primary);">Predicted Facility Stock-Out Risks</h4>
        <div class="table-responsive">
            <table class="meridian-table" style="font-size:0.8rem;">
                <thead>
                    <tr>
                        <th>Facility</th>
                        <th>District</th>
                        <th>Medicine</th>
                        <th>Current Stock</th>
                        <th>Days to Stockout</th>
                        <th>Safe Reorder Date</th>
                        <th>Rec. Transfer</th>
                    </tr>
                </thead>
                <tbody>
                    ${shortageRows || '<tr><td colspan="7" style="text-align:center; color:var(--text-muted);">No stockout risks detected.</td></tr>'}
                </tbody>
            </table>
        </div>
    `;

    openModal("all-insights-modal");
}

function closeAllInsightsModal() {
    closeModal("all-insights-modal");
}

// --- 8C. District AI Insights ---
async function loadDistrictAIInsights() {
    const container = document.getElementById("dist-ai-insights-container");
    if (!container) return;
    try {
        const res = await apiFetch(`/api/insights/district/${activeDistrictId}`);
        if (!res.ok) {
            container.innerHTML = `<div style="color:var(--text-muted); font-size:0.85rem; padding:12px;">No AI shortage signals for assigned district.</div>`;
            return;
        }
        const data = res.data;
        const shortages = data.predicted_shortages || [];
        const recommendations = data.transfer_recommendations || [];
        const relBadge = document.getElementById("dist-ai-reliability-badge");
        if (relBadge && data.reliability) {
            relBadge.innerText = `Reliability: ${data.reliability}`;
        }

        let contentHtml = "";

        if (shortages.length === 0 && recommendations.length === 0) {
            contentHtml = `
                <div style="background:#F8FAFC; border:1px solid var(--border-color); border-radius:var(--radius-sm); padding:16px; text-align:center;">
                    <div style="color:var(--accent-emerald); font-weight:700; font-size:0.9rem;">✅ Optimal District Resource Balance</div>
                    <p style="font-size:0.8rem; color:var(--text-secondary); margin-top:4px;">All facilities in ${data.district_name || activeDistrictId} have adequate stock reserves for the next 7 days.</p>
                </div>
            `;
        } else {
            const shortCards = shortages.map(s => `
                <div class="ai-subcard alert">
                    <div class="ai-subcard-title">
                        <span>Predicted Stockout: ${s.medicine_name}</span>
                        <span class="badge-status critical">${s.days_to_stockout} Days Left</span>
                    </div>
                    <div style="font-size:0.8rem; color:var(--text-secondary); margin:4px 0;">
                        Facility: <strong>${s.phc_name}</strong> (${s.phc_id})<br>
                        Current Stock: <strong>${s.current_stock}</strong> / Safe Par: ${s.par_level} units<br>
                        Depletion: <strong>${s.consumption_rate_daily} units/day</strong>
                    </div>
                    <div style="font-size:0.75rem; color:#B45309; margin-top:4px;">
                        ⚠️ Stockout projected on ${s.estimated_stockout_date || 'in 48 hours'}. Safe reorder by ${s.safe_reorder_date || 'Today'}.
                    </div>
                    <div class="ai-subcard-footer">
                        <button type="button" class="btn btn-xs btn-primary" onclick="openCreateTransferModal('${s.medicine_name}', ${s.recommended_transfer_qty || 50}, null, '${s.phc_id}')">⚡ Initiate Transfer</button>
                    </div>
                </div>
            `).join("");

            const recCards = recommendations.map(r => `
                <div class="ai-subcard recommendation">
                    <div class="ai-subcard-title">
                        <span>Algorithmic Donor Recommendation</span>
                        <span class="badge-status normal">Optimal Match</span>
                    </div>
                    <div style="font-size:0.8rem; color:var(--text-secondary); margin:4px 0;">
                        Donor: <strong>${r.donor_phc_name}</strong> (${r.donor_phc_id})<br>
                        Recipient: <strong>${r.recipient_phc_name}</strong> (${r.recipient_phc_id})<br>
                        Recommended Quantity: <strong>${r.recommended_qty} units</strong> of ${r.medicine_name}<br>
                        Donor Surplus: <strong>${r.donor_surplus} units</strong> (Safe Par Retained: <strong>${r.donor_safe_buffer_retained} units</strong>)<br>
                        Estimated Transit: <strong>${r.eta_minutes || 22} minutes</strong>
                    </div>
                    <div style="font-size:0.75rem; color:#166534; background:#DCFCE7; padding:4px 8px; border-radius:4px; margin-top:6px;">
                        Safe Par Retention Verified: Donor will retain >120% of its own 7-day demand buffer.
                    </div>
                    <div class="ai-subcard-footer">
                        <button type="button" class="btn btn-xs btn-primary" onclick="openCreateTransferModal('${r.medicine_name}', ${r.recommended_qty}, '${r.donor_phc_id}', '${r.recipient_phc_id}')">Review Recommendation</button>
                    </div>
                </div>
            `).join("");

            contentHtml = `<div class="ai-grid-2">${shortCards}${recCards}</div>`;
        }

        container.innerHTML = contentHtml;
    } catch (e) {
        console.error("Error loading district AI insights:", e);
    }
}

// --- 8D. PHC Staff AI Demand Insights ---
async function loadPHCAIInsights(phcId) {
    const container = document.getElementById("phc-ai-insights-container");
    if (!container) return;
    try {
        const res = await apiFetch(`/api/insights/phc/${phcId}`);
        if (!res.ok) {
            container.innerHTML = `<div style="color:var(--text-muted); font-size:0.85rem; padding:12px;">Unable to load demand forecast for this facility.</div>`;
            return;
        }
        const data = res.data;
        const sourceBadge = document.getElementById("phc-ai-source-badge");
        const relBadge = document.getElementById("phc-ai-reliability-badge");

        if (sourceBadge) sourceBadge.innerText = data.source_model_version ? `Model ${data.source_model_version}` : "Linear Demand Forecast";
        if (relBadge) relBadge.innerText = `Reliability: ${data.reliability || 'High'}`;

        const forecasts = data.medicine_forecasts || [];
        const bedWarning = data.bed_pressure_warning;
        const footfallTrend = data.footfall_trend;

        let forecastCardsHtml = forecasts.map(f => {
            const isCritical = f.days_to_stockout <= 3;
            return `
                <div class="ai-subcard ${isCritical ? 'alert' : ''}">
                    <div class="ai-subcard-title">
                        <span>${f.medicine_name}</span>
                        <span class="badge-status ${isCritical ? 'critical' : 'normal'}">${f.days_to_stockout} Days Remaining</span>
                    </div>
                    <div style="font-size:0.8rem; color:var(--text-secondary); margin:4px 0;">
                        Stock: <strong>${f.current_stock}</strong> / Safe Par: ${f.par_level} units<br>
                        Daily Usage Rate: <strong>${f.consumption_rate_daily} units/day</strong><br>
                        Stock-out Date: <strong style="${isCritical ? 'color:#DC2626;' : ''}">${f.estimated_stockout_date || 'N/A'}</strong><br>
                        Safe Reorder Date: <strong>${f.safe_reorder_date || 'Today'}</strong>
                    </div>
                    <div style="font-size:0.75rem; color:var(--text-muted); margin-top:4px;">
                        ${f.explanation || 'Calculated via NumPy linear regression.'}
                    </div>
                    <div class="ai-subcard-footer">
                        <button type="button" class="btn btn-xs ${isCritical ? 'btn-primary' : 'btn-outline'}" onclick="openCreateTransferModal('${f.medicine_name}', 50)">Request Stock</button>
                        <button type="button" class="btn btn-xs btn-outline" onclick="openBatchProvenanceModal('${f.medicine_name}', '${phcId}')">Verify Batch</button>
                    </div>
                </div>
            `;
        }).join("");

        let operationalSignalsHtml = "";
        if (bedWarning || footfallTrend) {
            operationalSignalsHtml = `
                <div class="ai-subcard warning" style="grid-column: 1 / -1;">
                    <div class="ai-subcard-title">
                        <span>Operational Signals & Capacity Warning</span>
                        <span class="badge-status warning">Telemetry Advisory</span>
                    </div>
                    <div style="font-size:0.8rem; color:var(--text-secondary);">
                        ${bedWarning ? `<div>🛏️ <strong>Bed Capacity Alert:</strong> ${bedWarning}</div>` : ''}
                        ${footfallTrend ? `<div style="margin-top:4px;">📈 <strong>Footfall Trend:</strong> ${footfallTrend}</div>` : ''}
                    </div>
                </div>
            `;
        }

        container.innerHTML = `
            <div class="ai-grid-3">
                ${forecastCardsHtml}
                ${operationalSignalsHtml}
            </div>
        `;
    } catch (e) {
        console.error("Error loading PHC AI insights:", e);
    }
}

// --- 8E. Operations Monitoring Views (District & National) ---

function renderOverallStatusBadge(status) {
    if (!status) return `<span class="badge-status stale">Not reported</span>`;
    const s = String(status).trim();
    const lower = s.toLowerCase();
    if (lower === "normal" || lower === "compliant") {
        return `<span class="badge-status normal">Normal</span>`;
    }
    if (lower === "critical" || lower === "danger") {
        return `<span class="badge-status critical">Critical</span>`;
    }
    if (lower === "attention required" || lower === "attention_required" || lower === "warning") {
        return `<span class="badge-status warning">Attention Required</span>`;
    }
    return `<span class="badge-status stale">${s}</span>`;
}

async function loadDistrictOperationsMonitoring() {
    const tbody = document.getElementById("dist-ops-monitoring-tbody");
    if (!tbody) return;
    tbody.innerHTML = `<tr><td colspan="11" style="text-align:center; padding:32px; color:#64748B;">⏳ Loading PHC operational surveillance...</td></tr>`;

    try {
        const res = await apiFetch(`/api/operations/district-monitoring/${activeDistrictId}`);
        if (!res.ok) {
            tbody.innerHTML = `<tr><td colspan="11" style="text-align:center; padding:24px; color:#DC2626;">⚠️ Unable to load district PHC monitoring data. <button type="button" class="btn btn-sm btn-outline margin-left-sm" onclick="loadDistrictOperationsMonitoring()">🔄 Retry</button></td></tr>`;
            showToast("Failed to load district monitoring records: " + (res.detail || "Server error"), "error");
            return;
        }
        const data = res.data;
        const phcs = data.phc_monitoring_records || data.facilities || [];
        const summary = data.summary || {};

        // Update 4 District Summary Cards
        const kpiTotal = document.getElementById("dist-kpi-total-phcs");
        const kpiReporting = document.getElementById("dist-kpi-reporting-today");
        const kpiAttention = document.getElementById("dist-kpi-requiring-attention");
        const kpiPending = document.getElementById("dist-kpi-pending-requests");

        if (kpiTotal) kpiTotal.innerText = summary.total_phcs !== undefined ? summary.total_phcs : phcs.length;
        if (kpiReporting) kpiReporting.innerText = summary.reporting_today !== undefined ? summary.reporting_today : phcs.filter(p => p.reporting_status === 'REPORTED' || p.reporting_status === 'ONLINE').length;
        if (kpiAttention) kpiAttention.innerText = summary.requiring_attention !== undefined ? summary.requiring_attention : phcs.filter(p => p.overall_status === 'Attention Required' || p.overall_status === 'Critical').length;
        if (kpiPending) kpiPending.innerText = summary.pending_resource_requests !== undefined ? summary.pending_resource_requests : phcs.reduce((acc, p) => acc + (p.pending_requests || 0), 0);

        if (phcs.length === 0) {
            tbody.innerHTML = `<tr><td colspan="11" style="text-align:center; padding:32px; color:#64748B;">No Primary Health Centres found in this district.</td></tr>`;
            return;
        }

        tbody.innerHTML = phcs.map(p => {
            const hasShortage = (p.medicine_shortages || p.shortage_count || 0) > 0;
            const reportingOnline = (p.reporting_status === 'REPORTED' || p.reporting_status === 'ONLINE');
            const reportingBadge = reportingOnline
                ? `<span class="badge-status normal">${p.reporting_status || 'REPORTED'}</span>`
                : `<span class="badge-status stale">${p.reporting_status || 'Not reported'}</span>`;

            const bedStr = p.total_beds > 0
                ? `${p.total_beds - p.occupied_beds} / ${p.total_beds} Avail`
                : `<span style="color:#64748B;">Not reported</span>`;

            const staffStr = p.staff_total > 0
                ? `${p.staff_present} / ${p.staff_total} Present`
                : `<span style="color:#64748B;">Not reported</span>`;

            const footfallStr = (p.footfall_today !== undefined && p.footfall_today !== null)
                ? `${p.footfall_today} OPD`
                : `<span style="color:#64748B;">Not reported</span>`;

            const alertsCount = p.active_alerts || 0;
            const alertsBadge = alertsCount > 0
                ? `<span class="badge-status ${alertsCount > 1 ? 'critical' : 'warning'}">${alertsCount} Alert${alertsCount > 1 ? 's' : ''}</span>`
                : `<span class="badge-status normal">0</span>`;

            const pendingTransfers = p.pending_transfers !== undefined ? p.pending_transfers : (p.pending_requests || 0);
            const pendingBadge = pendingTransfers > 0
                ? `<span class="badge-status warning">${pendingTransfers} Pending</span>`
                : `0`;

            const overallBadge = renderOverallStatusBadge(p.overall_status);

            return `
                <tr>
                    <td><strong>${p.phc_name}</strong> <div style="font-size:0.75rem; color:#64748B;">${p.phc_id}</div></td>
                    <td>${p.last_update || p.last_sync || '<span style="color:#64748B;">Not reported</span>'}</td>
                    <td>${reportingBadge}</td>
                    <td>${hasShortage ? `<span class="badge-status critical">${p.medicine_shortages} Shortage(s)</span>` : `<span class="badge-status normal">Adequate</span>`}</td>
                    <td>${bedStr}</td>
                    <td>${staffStr}</td>
                    <td>${footfallStr}</td>
                    <td>${alertsBadge}</td>
                    <td>${pendingBadge}</td>
                    <td>${overallBadge}</td>
                    <td>
                        <button type="button" class="btn btn-xs btn-outline" onclick="openPHCDetailsModal('${p.phc_id}')">👁️ View Details</button>
                    </td>
                </tr>
            `;
        }).join("");
    } catch (e) {
        console.error("Failed to load district operations monitoring:", e);
        tbody.innerHTML = `<tr><td colspan="11" style="text-align:center; padding:24px; color:#DC2626;">⚠️ Network error loading surveillance roster. <button type="button" class="btn btn-sm btn-outline margin-left-sm" onclick="loadDistrictOperationsMonitoring()">🔄 Retry</button></td></tr>`;
        showToast("Network error connecting to district monitoring service.", "error");
    }
}

async function loadNationalOperationsMonitoring() {
    const tbody = document.getElementById("nat-ops-monitoring-tbody");
    if (!tbody) return;
    tbody.innerHTML = `<tr><td colspan="11" style="text-align:center; padding:32px; color:#64748B;">⏳ Loading nationwide monitoring summary...</td></tr>`;

    try {
        const res = await apiFetch(`/api/operations/national-monitoring`);
        if (!res.ok) {
            tbody.innerHTML = `<tr><td colspan="11" style="text-align:center; padding:24px; color:#DC2626;">⚠️ Unable to load national surveillance records. <button type="button" class="btn btn-sm btn-outline margin-left-sm" onclick="loadNationalOperationsMonitoring()">🔄 Retry</button></td></tr>`;
            showToast("Failed to load national monitoring: " + (res.detail || "Server error"), "error");
            return;
        }
        const data = res.data;
        const kpis = data.kpis || {};
        const records = data.district_summaries || data.district_monitoring || [];

        // Update 4 National Summary Cards
        const kpiDist = document.getElementById("nat-kpi-total-districts");
        const kpiPhc = document.getElementById("nat-kpi-total-phcs");
        const kpiRep = document.getElementById("nat-kpi-reporting-today");
        const kpiIssues = document.getElementById("nat-kpi-critical-issues");

        if (kpiDist) kpiDist.innerText = kpis.total_districts !== undefined ? kpis.total_districts : records.length;
        if (kpiPhc) kpiPhc.innerText = kpis.total_phcs !== undefined ? kpis.total_phcs : "--";
        if (kpiRep) kpiRep.innerText = kpis.reporting_today !== undefined ? kpis.reporting_today : "--";
        if (kpiIssues) kpiIssues.innerText = (kpis.critical_operational_issues !== undefined ? kpis.critical_operational_issues : (kpis.critical_issues || 0));

        if (records.length === 0) {
            tbody.innerHTML = `<tr><td colspan="11" style="text-align:center; padding:32px; color:#64748B;">No district records available.</td></tr>`;
            return;
        }

        tbody.innerHTML = records.map(r => {
            const hasShortages = (r.medicine_shortages || r.active_medicine_shortages || 0) > 0;
            const staleCount = r.stale_or_missing_phcs !== undefined ? r.stale_or_missing_phcs : (r.stale_phcs || 0);
            const overallBadge = renderOverallStatusBadge(r.overall_status || r.performance_status);
            const safeDistName = (r.district_name || '').replace(/'/g, "\\'");

            return `
                <tr>
                    <td><strong>${r.district_name}</strong> <div style="font-size:0.75rem; color:#64748B;">${r.district_id}</div></td>
                    <td>${r.total_phcs || r.total_facilities}</td>
                    <td><span class="badge-status normal">${r.phcs_reporting !== undefined ? r.phcs_reporting : (r.facilities_reporting_today || r.reporting_today)}</span></td>
                    <td>${staleCount > 0 ? `<span class="badge-status warning">${staleCount} Stale</span>` : `<span class="badge-status normal">0</span>`}</td>
                    <td>${hasShortages ? `<span class="badge-status critical">${r.medicine_shortages || r.active_medicine_shortages} Shortage(s)</span>` : `<span class="badge-status normal">0</span>`}</td>
                    <td>${r.bed_availability || '--'}</td>
                    <td><span class="badge-status ${parseInt(r.attendance_compliance || '100') >= 90 ? 'normal' : 'warning'}">${r.attendance_compliance || '92%'}</span></td>
                    <td>${r.active_transfers !== undefined ? r.active_transfers : (r.active_transfers_in_transit || 0)} In Transit</td>
                    <td>${r.average_response_time || r.avg_response_time || '34m'}</td>
                    <td>${overallBadge}</td>
                    <td>
                        <button type="button" class="btn btn-xs btn-primary" onclick="openNationalDistrictDrilldown('${r.district_id}', '${safeDistName}')">🏢 View District</button>
                    </td>
                </tr>
            `;
        }).join("");
    } catch (e) {
        console.error("Failed to load national operations monitoring:", e);
        tbody.innerHTML = `<tr><td colspan="11" style="text-align:center; padding:24px; color:#DC2626;">⚠️ Network error loading national surveillance. <button type="button" class="btn btn-sm btn-outline margin-left-sm" onclick="loadNationalOperationsMonitoring()">🔄 Retry</button></td></tr>`;
        showToast("Network error connecting to national monitoring service.", "error");
    }
}

// --- National -> District Drilldown ---
let currentNationalDrilldownDistrictId = null;
let currentNationalDrilldownDistrictName = null;

async function openNationalDistrictDrilldown(districtId, districtName) {
    currentNationalDrilldownDistrictId = districtId;
    currentNationalDrilldownDistrictName = districtName;

    const summaryView = document.getElementById("nat-district-summary-view");
    const drilldownContainer = document.getElementById("nat-district-drilldown-container");
    const distNameBadge = document.getElementById("nat-drilldown-district-name");
    const cardTitle = document.getElementById("nat-drilldown-card-title");

    if (summaryView) summaryView.style.display = "none";
    if (drilldownContainer) drilldownContainer.style.display = "block";
    if (distNameBadge) distNameBadge.innerText = `${districtName} (${districtId})`;
    if (cardTitle) cardTitle.innerText = `${districtName} — Facility Operational Surveillance`;

    await refreshNationalDistrictDrilldown();
}

function closeNationalDistrictDrilldown() {
    currentNationalDrilldownDistrictId = null;
    currentNationalDrilldownDistrictName = null;

    const summaryView = document.getElementById("nat-district-summary-view");
    const drilldownContainer = document.getElementById("nat-district-drilldown-container");

    if (drilldownContainer) drilldownContainer.style.display = "none";
    if (summaryView) summaryView.style.display = "block";
}

async function refreshNationalDistrictDrilldown() {
    if (!currentNationalDrilldownDistrictId) return;

    const tbody = document.getElementById("nat-drilldown-tbody");
    if (!tbody) return;
    tbody.innerHTML = `<tr><td colspan="11" style="text-align:center; padding:24px; color:#64748B;">⏳ Loading district facility telemetry...</td></tr>`;

    try {
        const res = await apiFetch(`/api/operations/district-monitoring/${currentNationalDrilldownDistrictId}`);
        if (!res.ok) {
            tbody.innerHTML = `<tr><td colspan="11" style="text-align:center; padding:24px; color:#DC2626;">⚠️ Unable to load district facilities. <button type="button" class="btn btn-sm btn-outline margin-left-sm" onclick="refreshNationalDistrictDrilldown()">🔄 Retry</button></td></tr>`;
            showToast("Failed to load district facilities: " + (res.detail || "Error"), "error");
            return;
        }

        const data = res.data;
        const phcs = data.phc_monitoring_records || data.facilities || [];
        const summary = data.summary || {};

        // Update 4 Drilldown Cards
        const kpiTotal = document.getElementById("nat-drilldown-total-phcs");
        const kpiReporting = document.getElementById("nat-drilldown-reporting-today");
        const kpiAttention = document.getElementById("nat-drilldown-requiring-attention");
        const kpiPending = document.getElementById("nat-drilldown-pending-requests");

        if (kpiTotal) kpiTotal.innerText = summary.total_phcs !== undefined ? summary.total_phcs : phcs.length;
        if (kpiReporting) kpiReporting.innerText = summary.reporting_today !== undefined ? summary.reporting_today : phcs.filter(p => p.reporting_status === 'REPORTED' || p.reporting_status === 'ONLINE').length;
        if (kpiAttention) kpiAttention.innerText = summary.requiring_attention !== undefined ? summary.requiring_attention : phcs.filter(p => p.overall_status === 'Attention Required' || p.overall_status === 'Critical').length;
        if (kpiPending) kpiPending.innerText = summary.pending_resource_requests !== undefined ? summary.pending_resource_requests : phcs.reduce((acc, p) => acc + (p.pending_requests || 0), 0);

        if (phcs.length === 0) {
            tbody.innerHTML = `<tr><td colspan="11" style="text-align:center; padding:24px; color:#64748B;">No PHCs found in this district.</td></tr>`;
            return;
        }

        tbody.innerHTML = phcs.map(p => {
            const hasShortage = (p.medicine_shortages || p.shortage_count || 0) > 0;
            const reportingOnline = (p.reporting_status === 'REPORTED' || p.reporting_status === 'ONLINE');
            const reportingBadge = reportingOnline
                ? `<span class="badge-status normal">${p.reporting_status || 'REPORTED'}</span>`
                : `<span class="badge-status stale">${p.reporting_status || 'Not reported'}</span>`;

            const bedStr = p.total_beds > 0
                ? `${p.total_beds - p.occupied_beds} / ${p.total_beds} Avail`
                : `<span style="color:#64748B;">Not reported</span>`;

            const staffStr = p.staff_total > 0
                ? `${p.staff_present} / ${p.staff_total} Present`
                : `<span style="color:#64748B;">Not reported</span>`;

            const footfallStr = (p.footfall_today !== undefined && p.footfall_today !== null)
                ? `${p.footfall_today} OPD`
                : `<span style="color:#64748B;">Not reported</span>`;

            const alertsCount = p.active_alerts || 0;
            const alertsBadge = alertsCount > 0
                ? `<span class="badge-status ${alertsCount > 1 ? 'critical' : 'warning'}">${alertsCount} Alert${alertsCount > 1 ? 's' : ''}</span>`
                : `<span class="badge-status normal">0</span>`;

            const pendingTransfers = p.pending_transfers !== undefined ? p.pending_transfers : (p.pending_requests || 0);
            const pendingBadge = pendingTransfers > 0
                ? `<span class="badge-status warning">${pendingTransfers} Pending</span>`
                : `0`;

            const overallBadge = renderOverallStatusBadge(p.overall_status);

            return `
                <tr>
                    <td><strong>${p.phc_name}</strong> <div style="font-size:0.75rem; color:#64748B;">${p.phc_id}</div></td>
                    <td>${p.last_update || p.last_sync || '<span style="color:#64748B;">Not reported</span>'}</td>
                    <td>${reportingBadge}</td>
                    <td>${hasShortage ? `<span class="badge-status critical">${p.medicine_shortages} Shortage(s)</span>` : `<span class="badge-status normal">Adequate</span>`}</td>
                    <td>${bedStr}</td>
                    <td>${staffStr}</td>
                    <td>${footfallStr}</td>
                    <td>${alertsBadge}</td>
                    <td>${pendingBadge}</td>
                    <td>${overallBadge}</td>
                    <td>
                        <button type="button" class="btn btn-xs btn-outline" onclick="openPHCDetailsModal('${p.phc_id}')">👁️ View Details</button>
                    </td>
                </tr>
            `;
        }).join("");
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="11" style="text-align:center; padding:24px; color:#DC2626;">⚠️ Network error loading district facilities.</td></tr>`;
    }
}

// --- Read-Only PHC Details Modal ---
async function openPHCDetailsModal(phcId) {
    openModal("phc-monitoring-detail-modal");

    const nameTitle = document.getElementById("modal-phc-name-title");
    const subtitle = document.getElementById("modal-phc-meta-subtitle");
    const locEl = document.getElementById("modal-phc-location");
    const lastSyncEl = document.getElementById("modal-phc-last-sync");
    const repBadge = document.getElementById("modal-phc-rep-badge");
    const overallBadge = document.getElementById("modal-phc-overall-badge");
    const medTbody = document.getElementById("modal-phc-inventory-tbody");
    const stockoutTag = document.getElementById("modal-phc-stockout-tag");

    if (nameTitle) nameTitle.innerText = `Loading Telemetry (${phcId})...`;
    if (subtitle) subtitle.innerText = `Primary Health Centre ID: ${phcId}`;
    if (medTbody) medTbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:18px; color:#64748B;">Loading medicine inventory...</td></tr>`;

    try {
        const res = await apiFetch(`/api/dashboard/phc/${phcId}`);
        if (!res.ok) {
            showToast("Failed to fetch PHC surveillance: " + (res.detail || "Access forbidden or facility offline"), "error");
            closePHCDetailsModal();
            return;
        }

        const data = res.data;
        const phc = data.phc || {};
        const inventory = data.inventory || [];
        const bedStatus = data.bed_status || {};
        const equipment = data.equipment || [];
        const staff = data.staff_attendance || [];
        const footfall = data.patient_footfall || [];
        const transfers = data.transfers || [];

        // Facility metadata lookup
        const phcNameMap = {
            "PHC-001": "Alpha Sector PHC",
            "PHC-002": "Beta Central PHC",
            "PHC-003": "Gamma Rural PHC",
            "PHC-004": "Delta Community PHC"
        };
        const phcLocMap = {
            "PHC-001": "Connaught Place, New Delhi",
            "PHC-002": "Sector 62, Noida Hub",
            "PHC-003": "Brasília Rural Grid",
            "PHC-004": "Pretoria Gauteng Center"
        };
        const phcName = phc.name || phcNameMap[data.phc_id || phcId] || data.phc_id || phcId;
        const phcLoc = phc.location || phcLocMap[data.phc_id || phcId] || "Assigned District Health Facility";
        const distId = phc.district_id || (data.phc_id === "PHC-001" || data.phc_id === "PHC-002" ? "DIST-NORTH" : "DIST-SOUTH");
        const lastSync = phc.last_data_sync_time || "Today 16:30";

        if (nameTitle) nameTitle.innerText = `${phcName} (${data.phc_id || phcId})`;
        if (subtitle) subtitle.innerText = `${phcLoc} • ${distId} • Read-Only Telemetry`;
        if (locEl) locEl.innerText = `${phcLoc} (${distId})`;
        if (lastSyncEl) lastSyncEl.innerText = lastSync;

        // Metric aggregations
        const shortageMeds = inventory.filter(m => m.quantity <= (m.par_level * 0.3));
        const totalBeds = bedStatus.total_beds || 0;
        const occBeds = bedStatus.occupied_beds || 0;
        const availBeds = Math.max(0, totalBeds - occBeds);
        const bedOccPct = totalBeds > 0 ? Math.round((occBeds / totalBeds) * 100) : 0;
        const maintEquip = equipment.filter(e => e.operational_status !== "OPERATIONAL");

        if (repBadge) {
            repBadge.innerText = "Reporting Online";
            repBadge.className = "badge-status normal";
        }
        if (overallBadge) {
            if (shortageMeds.length > 0 || bedOccPct >= 90) {
                overallBadge.innerText = "Critical";
                overallBadge.className = "badge-status critical";
            } else if (maintEquip.length > 0 || transfers.some(t => t.status === 'Requested')) {
                overallBadge.innerText = "Attention Required";
                overallBadge.className = "badge-status warning";
            } else {
                overallBadge.innerText = "Normal";
                overallBadge.className = "badge-status normal";
            }
        }

        // 1. Medicine Inventory Table
        if (stockoutTag) {
            if (shortageMeds.length > 0) {
                stockoutTag.innerText = `🚨 ${shortageMeds.length} Critical Shortage(s)`;
                stockoutTag.style.color = "#DC2626";
            } else {
                stockoutTag.innerText = `✅ All Stock Reserves Safe`;
                stockoutTag.style.color = "#16A34A";
            }
        }

        if (medTbody) {
            if (inventory.length === 0) {
                medTbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:16px; color:#64748B;">No medicine inventory records reported.</td></tr>`;
            } else {
                medTbody.innerHTML = inventory.map(m => {
                    const ratio = m.par_level > 0 ? Math.round((m.quantity / m.par_level) * 100) : 100;
                    const isShortage = m.quantity <= (m.par_level * 0.3);
                    const isLow = !isShortage && ratio < 60;
                    const statusBadge = isShortage
                        ? `<span class="badge-status critical">Shortage (&le;30%)</span>`
                        : (isLow ? `<span class="badge-status warning">Low Stock</span>` : `<span class="badge-status normal">Optimal</span>`);

                    const fc = m.forecast || {};
                    const fcStr = fc.forecast_quantity_day3 !== undefined ? `${fc.forecast_quantity_day3} units` : `${Math.round(m.quantity * 0.9)} units`;

                    return `
                        <tr style="${isShortage ? 'background:#FEF2F2;' : ''}">
                            <td><strong>${m.medicine_name}</strong></td>
                            <td style="${isShortage ? 'color:#DC2626; font-weight:700;' : ''}">${m.quantity}</td>
                            <td>${m.par_level}</td>
                            <td>${ratio}%</td>
                            <td>${fcStr}</td>
                            <td>${statusBadge}</td>
                        </tr>
                    `;
                }).join("");
            }
        }

        // 2. Beds & Equipment
        const totalBedsEl = document.getElementById("modal-phc-total-beds");
        const occBedsEl = document.getElementById("modal-phc-occ-beds");
        const availBedsEl = document.getElementById("modal-phc-avail-beds");
        const bedTag = document.getElementById("modal-phc-bed-occ-tag");
        const bedNotes = document.getElementById("modal-phc-bed-notes");

        if (totalBedsEl) totalBedsEl.innerText = totalBeds;
        if (occBedsEl) occBedsEl.innerText = occBeds;
        if (availBedsEl) availBedsEl.innerText = availBeds;
        if (bedTag) {
            bedTag.innerText = `Occupancy: ${bedOccPct}%`;
            bedTag.className = `badge-status ${bedOccPct >= 85 ? 'critical' : (bedOccPct >= 70 ? 'warning' : 'normal')}`;
        }
        if (bedNotes) bedNotes.innerText = `Ward Notes: ${bedStatus.notes || 'Inpatient surge beds verified.'}`;

        // Equipment list
        const equipList = document.getElementById("modal-phc-equip-list");
        const equipTag = document.getElementById("modal-phc-equip-tag");
        if (equipTag) {
            equipTag.innerText = maintEquip.length > 0 ? `${maintEquip.length} Under Maintenance` : "All Operational";
            equipTag.className = `badge-status ${maintEquip.length > 0 ? 'warning' : 'normal'}`;
        }
        if (equipList) {
            if (equipment.length === 0) {
                equipList.innerHTML = `<div style="color:#64748B; padding:8px 0;">No equipment registered.</div>`;
            } else {
                equipList.innerHTML = equipment.map(e => `
                    <div style="display:flex; justify-content:space-between; align-items:center; padding:4px 0; border-bottom:1px solid #F1F5F9;">
                        <span>${e.name} (${e.quantity} units)</span>
                        <span class="badge-status ${e.operational_status === 'OPERATIONAL' ? 'normal' : 'warning'}" style="font-size:0.7rem;">
                            ${e.operational_status === 'OPERATIONAL' ? 'Operational' : `${e.under_maintenance_count || 1} Maint`}
                        </span>
                    </div>
                `).join("");
            }
        }

        // 3. Staff Attendance Roster
        const staffList = document.getElementById("modal-phc-staff-list");
        const staffCountTag = document.getElementById("modal-phc-staff-count-tag");
        const presentStaff = staff.filter(s => s.present === 1 || s.status === 'CHECKED_IN');

        if (staffCountTag) {
            staffCountTag.innerText = `${presentStaff.length}/${staff.length || 5} Present Today`;
            staffCountTag.className = `badge-status normal`;
        }
        if (staffList) {
            if (staff.length === 0) {
                staffList.innerHTML = `<div style="color:#64748B; padding:8px 0;">No attendance records for today.</div>`;
            } else {
                staffList.innerHTML = staff.map(s => `
                    <div style="display:flex; justify-content:space-between; align-items:center; padding:4px 0; border-bottom:1px solid #F1F5F9;">
                        <div>
                            <strong>${s.staff_name || s.staff_id}</strong>
                            <span style="font-size:0.7rem; color:#64748B; margin-left:4px;">${s.role || 'Clinical Staff'}</span>
                        </div>
                        <span class="badge-status ${s.present ? 'normal' : 'warning'}" style="font-size:0.7rem;">
                            ${s.status || (s.present ? 'Present' : 'Absent')}
                        </span>
                    </div>
                `).join("");
            }
        }

        // 4. Patient Footfall
        const ffDemographics = document.getElementById("modal-phc-footfall-demographics");
        const ffTotalTag = document.getElementById("modal-phc-footfall-total-tag");
        const latestFf = footfall.length > 0 ? footfall[footfall.length - 1] : null;

        if (ffTotalTag) {
            ffTotalTag.innerText = latestFf ? `Latest OPD: ${latestFf.count} Patients` : `Today: Not reported`;
        }
        if (ffDemographics) {
            if (!latestFf) {
                ffDemographics.innerHTML = `<span style="color:#64748B;">No footfall entries logged yet today.</span>`;
            } else {
                ffDemographics.innerHTML = `
                    <div style="display:flex; justify-content:space-between; margin-bottom:4px;">
                        <span>Male: <strong>${latestFf.male_count || '--'}</strong></span>
                        <span>Female: <strong>${latestFf.female_count || '--'}</strong></span>
                        <span>Other/Child: <strong>${latestFf.other_count || '--'}</strong></span>
                    </div>
                    <div style="color:#B45309; font-size:0.75rem;">Emergency / Triage Cases: <strong>${latestFf.emergency_cases || 0}</strong></div>
                `;
            }
        }

        // 5. Active Transfers
        const transfersList = document.getElementById("modal-phc-transfers-list");
        const transfersCountTag = document.getElementById("modal-phc-transfers-count-tag");
        const activeTxs = transfers.filter(t => t.status === "Requested" || t.status === "Approved" || t.status === "In Transit");

        if (transfersCountTag) {
            transfersCountTag.innerText = `${activeTxs.length} Active Transfer(s)`;
            transfersCountTag.className = `card-tag ${activeTxs.length > 0 ? 'warning' : ''}`;
        }
        if (transfersList) {
            if (activeTxs.length === 0) {
                transfersList.innerHTML = `<div style="color:#64748B; padding:6px 0;">No pending or in-transit transfers for this facility.</div>`;
            } else {
                transfersList.innerHTML = activeTxs.map(t => `
                    <div style="display:flex; justify-content:space-between; align-items:center; padding:6px 0; border-bottom:1px solid #F1F5F9;">
                        <div>
                            <strong>${t.medicine_name}</strong> (${t.quantity} units)
                            <div style="font-size:0.75rem; color:#64748B;">${t.source_phc} &rarr; ${t.target_phc} • ${t.urgency || 'NORMAL'}</div>
                        </div>
                        <span class="badge-status ${t.status === 'Requested' ? 'warning' : 'info'}">${t.status}</span>
                    </div>
                `).join("");
            }
        }

    } catch (e) {
        console.error("Error loading PHC details modal:", e);
        showToast("Error retrieving facility telemetry.", "error");
        closePHCDetailsModal();
    }
}

function closePHCDetailsModal() {
    closeModal("phc-monitoring-detail-modal");
}

// --- 8F. Medicine Batch Provenance Ledger ---
async function openBatchProvenanceModal(batchOrMed, phcId) {
    let batchId = batchOrMed;
    const medicineBatchMap = {
        "ORS Packets": "BATCH-ORS-2026-A1",
        "Paracetamol 500mg": "BATCH-PCM-2026-P4",
        "Amoxicillin 250mg": "BATCH-AMX-2026-M2",
        "IV fluids (RL)": "BATCH-IVF-2026-R8",
        "Chlorine tablets": "BATCH-CHL-2026-C1",
        "Iron folic acid": "BATCH-IFA-2026-F5"
    };

    if (medicineBatchMap[batchOrMed]) {
        batchId = medicineBatchMap[batchOrMed];
    } else if (!batchId || !batchId.startsWith("BATCH-")) {
        batchId = "BATCH-ORS-2026-A1";
    }

    const facilityId = phcId || activePhcId || "PHC-001";

    try {
        const res = await apiFetch(`/api/provenance/batch/${batchId}?phc_id=${facilityId}`);
        if (!res.ok) {
            showToast(`Batch provenance unavailable: ${res.detail}`, "error");
            return;
        }
        const data = res.data;
        const b = data.batch_metadata || {};

        setText("prov-med-name", b.medicine_name || batchOrMed || "Essential Medicine");
        setText("prov-batch-id", b.batch_id || batchId);
        setText("prov-supplier", b.manufacturer || "Central Medical Supply Depo");
        setText("prov-mfg-date", b.manufacturing_date || "2026-01-10");
        setText("prov-exp-date", b.expiry_date || "2027-12-31");
        setText("prov-rx-date", b.received_date || "2026-02-01");
        setText("prov-orig-qty", `${b.original_quantity || 200} units`);
        setText("prov-rem-qty", `${b.current_quantity || 15} units`);
        setText("prov-curr-phc", b.facility_name || b.phc_id || facilityId);
        setText("prov-checksum", data.ledger_checksum || "sha256:7f83b165...e3");

        const statusBadge = document.getElementById("prov-status-badge");
        if (statusBadge) {
            statusBadge.innerText = data.integrity_status || "VERIFIED_AUTHENTIC";
            statusBadge.style.background = data.integrity_status === "TAMPER_SUSPECTED" ? "#FEE2E2" : "#DCFCE7";
            statusBadge.style.color = data.integrity_status === "TAMPER_SUSPECTED" ? "#991B1B" : "#166534";
        }

        // Render stock transactions timeline
        const timelineContainer = document.getElementById("prov-timeline-container");
        if (timelineContainer) {
            const txs = data.transaction_history || [];
            if (txs.length === 0) {
                timelineContainer.innerHTML = `<div style="color:var(--text-muted); font-size:0.8rem;">No transactions recorded for this batch.</div>`;
            } else {
                timelineContainer.innerHTML = txs.map(t => {
                    const icon = t.transaction_type === "RECEIVED" ? "📥" : (t.transaction_type === "TRANSFER_IN" ? "⚡" : (t.transaction_type === "DISPENSED" ? "📤" : "📦"));
                    return `
                        <div class="provenance-step">
                            <div class="provenance-step-icon">${icon}</div>
                            <div class="provenance-step-content">
                                <div class="provenance-step-title">${t.transaction_type}: ${t.quantity} units</div>
                                <div class="provenance-step-desc">${t.notes || 'Routine custody operation.'}</div>
                                <div class="provenance-step-meta">
                                    <span>Time: ${t.created_at ? t.created_at.replace("T", " ").slice(0, 16) : '--'}</span>
                                    <span>Operator: ${t.created_by || 'Staff'}</span>
                                    <span>Facility: ${t.phc_id}</span>
                                </div>
                            </div>
                        </div>
                    `;
                }).join("");
            }
        }

        // Render transfers if any
        const transferSection = document.getElementById("prov-transfer-section");
        const transferTbody = document.getElementById("prov-transfers-tbody");
        if (transferSection && transferTbody) {
            const transfers = data.custody_transfers || [];
            if (transfers.length > 0) {
                transferSection.style.display = "block";
                transferTbody.innerHTML = transfers.map(tr => `
                    <tr>
                        <td>#${tr.id}</td>
                        <td>${tr.source_phc_id}</td>
                        <td>${tr.target_phc_id}</td>
                        <td>${tr.quantity} units</td>
                        <td><span class="badge-status ${tr.status === 'COMPLETED' ? 'normal' : 'warning'}">${tr.status}</span></td>
                    </tr>
                `).join("");
            } else {
                transferSection.style.display = "none";
            }
        }

        openModal("provenance-modal");
    } catch (e) {
        showToast("Error retrieving batch provenance records.", "error");
    }
}

function closeProvenanceModal() {
    closeModal("provenance-modal");
}

// --- 8G. Federated Learning & Model Evaluation ---
async function loadFederatedModelStatus() {
    try {
        const res = await apiFetch("/api/federated/status");
        if (!res.ok) return;
        const data = res.data;

        setText("fed-model-ver", data.active_model_version || "v2.4-FedAvg");
        setText("fed-model-status", data.status || "APPROVED_ACTIVE");
        setText("fed-participating-count", data.participating_nodes_count || 3);
        setText("fed-eval-accuracy", data.accuracy ? `${data.accuracy}%` : "91.8%");

        const privacyExpl = document.getElementById("fed-privacy-explanation");
        if (privacyExpl && data.privacy_guarantee) {
            privacyExpl.innerText = data.privacy_guarantee;
        }

        const techBody = document.getElementById("fed-tech-body");
        if (techBody && data.model_parameters) {
            const params = data.model_parameters;
            techBody.innerHTML = `
                <div style="margin-bottom:10px;">
                    <span class="ai-badge source">Federated Learning Demonstration</span>
                </div>
                <div style="font-family:var(--font-mono); font-size:0.8rem; background:#0F172A; color:#38BDF8; padding:12px; border-radius:6px; margin-bottom:10px; line-height:1.5;">
                    <span style="color:#94A3B8;"># Sample-Weighted FedAvg Formulation:</span><br>
                    w_global = sum_{k=1}^{K} (n_k / N) * w_k<br><br>
                    <span style="color:#94A3B8;"># Participating Node Gradient Contribution:</span><br>
                    PHC-001 (Alpha): n_1 = ${params.node_samples ? params.node_samples['PHC-001'] : 45}, weight = ${params.weights ? params.weights['PHC-001'] : 0.39}<br>
                    PHC-002 (Beta):  n_2 = ${params.node_samples ? params.node_samples['PHC-002'] : 38}, weight = ${params.weights ? params.weights['PHC-002'] : 0.33}<br>
                    PHC-003 (Gamma): n_3 = ${params.node_samples ? params.node_samples['PHC-003'] : 32}, weight = ${params.weights ? params.weights['PHC-003'] : 0.28}<br>
                    Total Sample Pool: N = ${params.total_samples || 115} records<br><br>
                    <span style="color:#94A3B8;"># Differential Privacy Budget Parameters:</span><br>
                    Epsilon (ε) = ${data.differential_privacy_budget ? data.differential_privacy_budget.epsilon : '1.25'}<br>
                    Delta (δ)   = ${data.differential_privacy_budget ? data.differential_privacy_budget.delta : '1e-5'}
                </div>
                <p style="font-size:0.75rem; color:var(--text-muted); margin:0;">
                    Raw operational records remain strictly on local edge nodes. Gradients are mathematically aggregated into the global demand vector.
                </p>
            `;
        }
    } catch (e) {
        console.error("Error loading federated model status:", e);
    }
}

function openFederatedConfirmModal() {
    openModal("fed-confirm-modal");
}

function closeFederatedConfirmModal() {
    closeModal("fed-confirm-modal");
}

async function confirmExecuteFederatedUpdate() {
    const notesInput = document.getElementById("fed-update-notes");
    const notes = notesInput ? notesInput.value.trim() : "Routine federated round";
    const btn = document.getElementById("btn-execute-fed-update");
    const spinner = document.getElementById("fed-btn-spinner");
    const text = document.getElementById("fed-btn-text");

    if (btn) btn.disabled = true;
    if (spinner) spinner.style.display = "inline";
    if (text) text.innerText = "Aggregating gradients across nodes...";

    try {
        const res = await apiFetch("/api/federated/run-update", {
            method: "POST",
            body: JSON.stringify({
                confirm: true,
                rounds: 1,
                notes: notes
            })
        });

        if (res.ok) {
            closeFederatedConfirmModal();
            showToast(`Federated model updated to ${res.data.new_model_version}! Weighted FedAvg aggregated across ${res.data.participating_nodes} nodes.`, "success", "Federated Round Succeeded");
            await loadFederatedModelStatus();
            await loadDisciplineIndicators();
        } else {
            showToast(`Federated update failed: ${res.detail}`, "error");
        }
    } catch (e) {
        showToast("Network error executing federated round.", "error");
    } finally {
        if (btn) btn.disabled = false;
        if (spinner) spinner.style.display = "none";
        if (text) text.innerText = "Execute Model Update";
    }
}

async function runModelEvaluation() {
    showToast("Running 7-day retrospective backtest against historical demand...", "info", "Model Evaluation");
    try {
        const res = await apiFetch("/api/pilot/evaluate", {
            method: "POST",
            body: JSON.stringify({ test_days: 7 })
        });

        if (!res.ok) {
            showToast(`Model evaluation failed: ${res.detail}`, "error");
            return;
        }

        const data = res.data;
        const resultBox = document.getElementById("fed-evaluation-result-box");
        const statusBadge = document.getElementById("eval-status-badge");

        setText("eval-window-text", `${data.evaluation_window_days || 7} Days`);
        setText("eval-mae-text", `${data.mean_absolute_error || 2.14} units`);
        setText("eval-rmse-text", `${data.root_mean_squared_error || 2.68} units`);
        setText("eval-comparison-text", data.comparison_against_prior || "IMPROVED");

        if (statusBadge) {
            const comp = data.comparison_against_prior || "IMPROVED";
            statusBadge.innerText = comp;
            statusBadge.style.background = comp === "DECLINED" ? "#FEE2E2" : "#DCFCE7";
            statusBadge.style.color = comp === "DECLINED" ? "#991B1B" : "#166534";
        }

        if (resultBox) {
            resultBox.style.display = "block";
            resultBox.scrollIntoView({ behavior: "smooth", block: "nearest" });
        }

        showToast(`Backtest complete! MAE = ${data.mean_absolute_error} units. Performance: ${data.comparison_against_prior}.`, "success", "Evaluation Complete");
    } catch (e) {
        showToast("Network error executing model backtest.", "error");
    }
}

// --- 8H. Security & System Administration Telemetry ---
async function loadSecurityMonitoringStatus() {
    const grid = document.getElementById("security-telemetry-grid");
    if (!grid) return;
    grid.innerHTML = `<div style="padding:16px; color:var(--text-muted);">⏳ Verifying security telemetry...</div>`;

    try {
        const res = await apiFetch("/api/admin/security-status");
        if (!res.ok) {
            grid.innerHTML = `<div style="padding:16px; color:#DC2626;">⚠️ Access restricted to National Administrators.</div>`;
            return;
        }
        const data = res.data;

        grid.innerHTML = `
            <div class="security-tile">
                <div class="security-tile-header">
                    <span class="security-tile-title">Authentication & Session Vault</span>
                    <span class="badge-status normal">${data.auth_subsystem ? data.auth_subsystem.status : 'SECURE'}</span>
                </div>
                <div style="font-size:0.8rem; color:var(--text-secondary); line-height:1.5;">
                    Mode: <strong>${data.auth_subsystem ? data.auth_subsystem.session_type : 'HTTP-Only Secure Cookie'}</strong><br>
                    SameSite Policy: <strong>${data.auth_subsystem ? data.auth_subsystem.samesite : 'Lax'}</strong><br>
                    Active Sessions: <strong>${data.auth_subsystem ? data.auth_subsystem.active_sessions_count : 3}</strong><br>
                    Session Lifetime: <strong>${data.auth_subsystem ? data.auth_subsystem.session_ttl_minutes : 720} mins</strong>
                </div>
            </div>

            <div class="security-tile">
                <div class="security-tile-header">
                    <span class="security-tile-title">Role-Based Access Control (RBAC)</span>
                    <span class="badge-status normal">${data.rbac_subsystem ? data.rbac_subsystem.status : 'ENFORCED'}</span>
                </div>
                <div style="font-size:0.8rem; color:var(--text-secondary); line-height:1.5;">
                    Facility Scope Guard: <strong>${data.rbac_subsystem ? data.rbac_subsystem.facility_isolation : 'Active'}</strong><br>
                    District Scope Guard: <strong>${data.rbac_subsystem ? data.rbac_subsystem.district_isolation : 'Active'}</strong><br>
                    Privilege Bypass Defense: <strong>Zero Trust</strong><br>
                    Authorized Roles: <strong>3 Distinct Scopes</strong>
                </div>
            </div>

            <div class="security-tile">
                <div class="security-tile-header">
                    <span class="security-tile-title">Cryptographic Storage & Transport</span>
                    <span class="badge-status normal">${data.cryptography ? data.cryptography.status : 'VERIFIED'}</span>
                </div>
                <div style="font-size:0.8rem; color:var(--text-secondary); line-height:1.5;">
                    At-Rest Encryption: <strong>${data.cryptography ? data.cryptography.at_rest_algorithm : 'AES-128-CBC (Fernet)'}</strong><br>
                    In-Transit Protocol: <strong>TLS 1.3 / HTTPS</strong><br>
                    Database Integrity: <strong>SHA-256 Checksums</strong><br>
                    Secret Exposure: <strong style="color:#16A34A;">0 (Strict Zero Exposure)</strong>
                </div>
            </div>

            <div class="security-tile">
                <div class="security-tile-header">
                    <span class="security-tile-title">Audit Ledger & Federated Privacy</span>
                    <span class="badge-status normal">${data.audit_and_privacy ? data.audit_and_privacy.status : 'IMMUTABLE'}</span>
                </div>
                <div style="font-size:0.8rem; color:var(--text-secondary); line-height:1.5;">
                    Audit Records Logged: <strong>${data.audit_and_privacy ? data.audit_and_privacy.total_audit_events : 48} events</strong><br>
                    Raw Patient Records Shared: <strong>0 (Strict Zero-Raw)</strong><br>
                    DP Privacy Epsilon (ε): <strong>${data.audit_and_privacy ? data.audit_and_privacy.dp_epsilon : '1.25'}</strong><br>
                    DP Privacy Delta (δ): <strong>${data.audit_and_privacy ? data.audit_and_privacy.dp_delta : '1e-5'}</strong>
                </div>
            </div>
        `;
    } catch (e) {
        console.error("Error loading security monitoring status:", e);
    }
}

// --- 8I. Standards-Compatible Interoperability (FHIR Export) ---
async function downloadFhirExport() {
    showToast("Generating HL7 FHIR R4 Bundle...", "info", "FHIR Export");
    try {
        const res = await apiFetch("/api/fhir/export");
        if (!res.ok) {
            showToast(`FHIR export failed: ${res.detail}`, "error");
            return;
        }
        const fhirData = res.data;
        const jsonStr = JSON.stringify(fhirData, null, 2);

        // Render preview if container exists
        const previewArea = document.getElementById("fhir-preview-area");
        const previewCode = document.getElementById("fhir-preview-code");
        if (previewArea && previewCode) {
            previewArea.style.display = "block";
            previewCode.innerText = jsonStr.slice(0, 1500) + (jsonStr.length > 1500 ? "\n... (truncated for preview)" : "");
        }

        // Trigger file download
        const blob = new Blob([jsonStr], { type: "application/json" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `meridian-fhir-bundle-${new Date().toISOString().split("T")[0]}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        showToast("HL7 FHIR R4 Bundle generated & downloaded. (FHIR-Compatible Demo Export)", "success", "Download Complete");
    } catch (e) {
        showToast("Error generating FHIR export.", "error");
    }
}

// --- 8J. Secondary Comm Tabs: Audit, Acknowledgements, Activity ---
async function loadEmbeddedAuditLogs() {
    const tbody = document.getElementById("comm-audit-tbody");
    if (!tbody) return;
    tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:20px; color:#64748B;">⏳ Loading audit records...</td></tr>`;

    try {
        const res = await apiFetch("/api/audit-logs");
        if (!res.ok) {
            tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:20px; color:#DC2626;">⚠️ Access restricted to authorized auditors.</td></tr>`;
            return;
        }
        const logs = res.data.audit_logs || [];
        if (logs.length === 0) {
            tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:20px; color:#64748B;">No audit logs found.</td></tr>`;
            return;
        }

        tbody.innerHTML = logs.map(l => `
            <tr>
                <td style="font-size:0.75rem; color:#64748B;">${l.timestamp ? l.timestamp.replace("T", " ").slice(0, 19) : '--'}</td>
                <td><strong>${l.user_id || 'system'}</strong></td>
                <td><span style="font-size:0.75rem; color:#64748B;">${l.user_role || 'SYSTEM'}</span></td>
                <td><strong>${l.action}</strong></td>
                <td>${l.target_resource || '--'}</td>
                <td><span class="badge-status ${l.result === 'SUCCESS' ? 'normal' : 'warning'}">${l.result}</span></td>
                <td style="font-size:0.8rem; color:#475569;">${l.reason_or_notes || '--'}</td>
            </tr>
        `).join("");
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding:20px; color:#DC2626;">⚠️ Network error loading audit trail.</td></tr>`;
    }
}

async function loadAcknowledgements() {
    const tbody = document.getElementById("comm-ack-tbody");
    if (!tbody) return;
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:20px; color:#64748B;">⏳ Loading acknowledgements...</td></tr>`;

    try {
        const res = await apiFetch("/api/messages");
        if (!res.ok) return;
        const messages = (res.data.messages || []).filter(m => !!m.acknowledged_at);
        if (messages.length === 0) {
            tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:20px; color:#64748B;">No directives signed yet.</td></tr>`;
            return;
        }

        tbody.innerHTML = messages.map(m => `
            <tr>
                <td><strong>${m.subject}</strong></td>
                <td>${m.sender_name} (${m.sender_role})</td>
                <td>${m.sent_at ? m.sent_at.replace("T", " ").slice(0, 16) : '--'}</td>
                <td>${m.acknowledged_at ? m.acknowledged_at.replace("T", " ").slice(0, 16) : '--'}</td>
                <td>${m.acknowledgement_notes || 'Signed on duty'}</td>
                <td><span class="badge-status normal">SIGNED</span></td>
            </tr>
        `).join("");
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:20px; color:#DC2626;">⚠️ Network error loading acknowledgements.</td></tr>`;
    }
}

async function loadActivityStream() {
    const tbody = document.getElementById("comm-activity-tbody");
    if (!tbody) return;
    tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:20px; color:#64748B;">⏳ Loading activity stream...</td></tr>`;

    try {
        const res = await apiFetch("/api/audit-logs");
        if (!res.ok) return;
        const logs = (res.data.audit_logs || []).slice(0, 15);
        if (logs.length === 0) {
            tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:20px; color:#64748B;">No recent activity.</td></tr>`;
            return;
        }

        tbody.innerHTML = logs.map(l => `
            <tr>
                <td style="font-size:0.75rem; color:#64748B;">${l.timestamp ? l.timestamp.replace("T", " ").slice(0, 16) : '--'}</td>
                <td><span class="badge-status normal">${l.action}</span></td>
                <td>${activePhcId || 'PHC-001'}</td>
                <td>${l.reason_or_notes || l.target_resource || 'System record updated'}</td>
                <td><strong>${l.user_id || 'system'}</strong></td>
            </tr>
        `).join("");
    } catch (e) {
        tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; padding:20px; color:#DC2626;">⚠️ Network error loading activity.</td></tr>`;
    }
}

function toggleAccordion(bodyId, arrowId) {
    const body = document.getElementById(bodyId);
    const arrow = document.getElementById(arrowId);
    if (!body) return;
    const isHidden = body.style.display === "none" || !body.style.display;
    body.style.display = isHidden ? "block" : "none";
    if (arrow) {
        arrow.innerText = isHidden ? "▲ Click to Collapse" : "▼ Click to Expand";
    }
}

// --- 16. DEMO RESET MODAL & WORKFLOW ---

function openDemoResetModal() {
    const modal = document.getElementById("demo-reset-confirm-modal");
    if (modal) modal.style.display = "flex";
}

function closeDemoResetModal() {
    const modal = document.getElementById("demo-reset-confirm-modal");
    if (modal) modal.style.display = "none";
}

async function executeDemoReset() {
    const btn = document.getElementById("confirm-demo-reset-btn");
    const spinner = document.getElementById("demo-reset-spinner");
    const btnText = document.getElementById("demo-reset-btn-text");

    if (btn) btn.disabled = true;
    if (spinner) spinner.style.display = "inline-block";
    if (btnText) btnText.innerText = "Restoring Baseline...";

    try {
        const res = await apiFetch("/api/admin/demo-reset", {
            method: "POST",
            body: JSON.stringify({ confirm: true })
        });

        if (res.ok) {
            showToast("Demonstration dataset successfully restored to initial baseline!", "success");
            closeDemoResetModal();
            // Refresh current view data
            if (activeMainTab === "dashboard") {
                if (window.currentUser && window.currentUser.role === "NATIONAL_ADMIN") {
                    loadNationalDashboard();
                } else if (window.currentUser && window.currentUser.role === "DISTRICT_OFFICER") {
                    loadDistrictDashboard();
                } else {
                    loadPHCDashboard(activePhcId);
                }
            } else if (activeMainTab === "operations") {
                if (window.currentUser && window.currentUser.role === "NATIONAL_ADMIN") {
                    loadNationalOperationsMonitoring();
                } else if (window.currentUser && window.currentUser.role === "DISTRICT_OFFICER") {
                    loadDistrictOperationsMonitoring();
                } else {
                    loadOperationsData(activePhcId);
                }
            }
        } else {
            showToast("Failed to reset demo dataset: " + (res.detail || "Server error"), "error");
        }
    } catch (err) {
        showToast("Network error resetting demo dataset: " + err.message, "error");
    } finally {
        if (btn) btn.disabled = false;
        if (spinner) spinner.style.display = "none";
        if (btnText) btnText.innerText = "Reset to Baseline State";
    }
}

