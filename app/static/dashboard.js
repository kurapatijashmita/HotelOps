/**
 * HotelOps — SRE Monitoring Dashboard
 * Pure vanilla JavaScript with 5-second polling, interactive fault injection,
 * and live telemetry visualization.
 */

let countdownValue = 5;
let countdownTimer = null;
let lastKnownConflictDates = {
    roomId: 1,
    checkIn: "2026-12-10",
    checkOut: "2026-12-15"
};

// DOM Elements
const overallStatusBadge = document.getElementById("overallStatusBadge");
const overallStatusText = document.getElementById("overallStatusText");
const statusDot = document.getElementById("statusDot");
const refreshTimer = document.getElementById("refreshTimer");
const manualRefreshBtn = document.getElementById("manualRefreshBtn");

const cardHealthStatus = document.getElementById("cardHealthStatus");
const cardDbStatus = document.getElementById("cardDbStatus");
const probeStatusTag = document.getElementById("probeStatusTag");
const cardUptime = document.getElementById("cardUptime");
const cardUptimeSeconds = document.getElementById("cardUptimeSeconds");
const cardTotalRequests = document.getElementById("cardTotalRequests");
const cardSuccessRequests = document.getElementById("cardSuccessRequests");
const cardFailedRequests = document.getElementById("cardFailedRequests");
const cardAvgLatency = document.getElementById("cardAvgLatency");
const cardP95Latency = document.getElementById("cardP95Latency");
const cardErrorRate = document.getElementById("cardErrorRate");
const errorRateTag = document.getElementById("errorRateTag");
const card4xxRequests = document.getElementById("card4xxRequests");
const card5xxRequests = document.getElementById("card5xxRequests");

const alertBanner = document.getElementById("alertBanner");
const alertTitle = document.getElementById("alertTitle");
const alertMessage = document.getElementById("alertMessage");
const closeAlertBtn = document.getElementById("closeAlertBtn");
const actionFeedback = document.getElementById("actionFeedback");

const latencyBarsContainer = document.getElementById("latencyBarsContainer");
const dist2xx = document.getElementById("dist2xx");
const dist4xx = document.getElementById("dist4xx");
const dist5xx = document.getElementById("dist5xx");
const dist2xxPct = document.getElementById("dist2xxPct");
const dist4xxPct = document.getElementById("dist4xxPct");
const dist5xxPct = document.getElementById("dist5xxPct");

const telemetryTableBody = document.getElementById("telemetryTableBody");
const streamCounter = document.getElementById("streamCounter");

// Control buttons
const simulateErrorBtn = document.getElementById("simulateErrorBtn");
const createBookingBtn = document.getElementById("createBookingBtn");
const triggerConflictBtn = document.getElementById("triggerConflictBtn");
const runHealthProbeBtn = document.getElementById("runHealthProbeBtn");

// ---------------------------------------------------------------------------
// Telemetry Fetcher & UI Updater
// ---------------------------------------------------------------------------
async function fetchTelemetry() {
    try {
        // Parallel fetch for health, ready probe, and metrics summary
        const [metricsRes, healthRes, readyRes] = await Promise.allSettled([
            fetch("/metrics-summary", { cache: "no-store" }),
            fetch("/health", { cache: "no-store" }),
            fetch("/ready", { cache: "no-store" }),
        ]);

        let isHealthy = false;
        let isReady = false;

        if (healthRes.status === "fulfilled" && healthRes.value.ok) {
            isHealthy = true;
        }

        if (readyRes.status === "fulfilled" && readyRes.value.ok) {
            isReady = true;
        }

        // Handle metrics summary payload
        if (metricsRes.status === "fulfilled" && metricsRes.value.ok) {
            const data = await metricsRes.value.json();
            updateDashboard(data, isHealthy, isReady);
        } else {
            handleDegradedState("Unable to retrieve metrics summary");
        }
    } catch (err) {
        console.error("Telemetry fetch error:", err);
        handleDownState("Network error: API server appears offline");
    }
}

function updateDashboard(data, isHealthy, isReady) {
    // 1. Service Health Card
    cardHealthStatus.textContent = isHealthy ? "Healthy" : "Degraded";
    cardHealthStatus.className = isHealthy ? "primary-metric text-success" : "primary-metric text-danger";
    
    cardDbStatus.textContent = isReady ? "Connected" : "Disconnected";
    cardDbStatus.className = isReady ? "text-success" : "text-danger";

    probeStatusTag.textContent = (isHealthy && isReady) ? "PROBES OK" : "PROBE ALERT";
    probeStatusTag.className = (isHealthy && isReady) ? "card-tag text-success" : "card-tag text-danger";

    // 2. Process Uptime Card
    cardUptime.textContent = data.uptime_human || "0s";
    cardUptimeSeconds.textContent = `${Math.floor(data.uptime_seconds || 0)}s elapsed`;

    // 3. Requests Card
    cardTotalRequests.textContent = data.total_requests.toLocaleString();
    cardSuccessRequests.textContent = data.successful_requests.toLocaleString();
    cardFailedRequests.textContent = data.failed_requests.toLocaleString();

    // 4. Latency Card
    cardAvgLatency.textContent = `${data.average_latency_ms.toFixed(2)} ms`;
    cardP95Latency.textContent = `${data.p95_latency_ms.toFixed(2)} ms`;

    // 5. Error Rate Card
    const errRate = data.error_rate_percentage || 0;
    cardErrorRate.textContent = `${errRate.toFixed(1)}%`;
    card4xxRequests.textContent = data.client_error_requests || 0;
    card5xxRequests.textContent = data.server_error_requests || 0;

    if (errRate === 0) {
        cardErrorRate.className = "primary-metric font-mono text-success";
        errorRateTag.textContent = "OPTIMAL";
        errorRateTag.className = "card-tag text-success";
    } else if (errRate < 5.0) {
        cardErrorRate.className = "primary-metric font-mono text-warning";
        errorRateTag.textContent = "WARNING";
        errorRateTag.className = "card-tag text-warning";
    } else {
        cardErrorRate.className = "primary-metric font-mono text-danger";
        errorRateTag.textContent = "CRITICAL";
        errorRateTag.className = "card-tag text-danger";
    }

    // Overall Status Badge
    if (!isHealthy || !isReady || (data.server_error_requests > 0 && errRate >= 20.0)) {
        statusDot.className = "status-dot unhealthy";
        overallStatusText.textContent = "OUTAGE / ALERT";
        showAlertBanner("High Server Outage Detected", `Service error rate is currently at ${errRate.toFixed(1)}%. Review active incidents.`);
    } else if (errRate >= 5.0 || data.client_error_requests > 10) {
        statusDot.className = "status-dot degraded";
        overallStatusText.textContent = "DEGRADED";
    } else {
        statusDot.className = "status-dot healthy";
        overallStatusText.textContent = "OPERATIONAL";
        // Auto hide banner if errors cleared
        if (errRate === 0) {
            hideAlertBanner();
        }
    }

    // 6. Distribution Bar
    const total = data.total_requests || 1;
    const p2xx = Math.round((data.successful_requests / total) * 100);
    const p4xx = Math.round((data.client_error_requests / total) * 100);
    const p5xx = Math.max(0, 100 - p2xx - p4xx);

    dist2xx.style.width = `${p2xx}%`;
    dist4xx.style.width = `${p4xx}%`;
    dist5xx.style.width = `${p5xx}%`;

    dist2xxPct.textContent = `${p2xx}%`;
    dist4xxPct.textContent = `${p4xx}%`;
    dist5xxPct.textContent = `${p5xx}%`;

    // 7. Latency Trend Sparkline
    renderLatencyBars(data.recent_requests || []);

    // 8. Live Request Table
    renderTelemetryTable(data.recent_requests || []);
}

function handleDegradedState(reason) {
    statusDot.className = "status-dot degraded";
    overallStatusText.textContent = "DEGRADED";
    showAlertBanner("Telemetry Warning", reason);
}

function handleDownState(reason) {
    statusDot.className = "status-dot unhealthy";
    overallStatusText.textContent = "SERVICE DOWN";
    cardHealthStatus.textContent = "OFFLINE";
    cardHealthStatus.className = "primary-metric text-danger";
    cardDbStatus.textContent = "Unreachable";
    cardDbStatus.className = "text-danger";
    showAlertBanner("Critical Incident: Service Unreachable", reason);
}

function showAlertBanner(title, msg) {
    alertTitle.textContent = title;
    alertMessage.textContent = msg;
    alertBanner.classList.remove("hidden");
}

function hideAlertBanner() {
    alertBanner.classList.add("hidden");
}

closeAlertBtn.addEventListener("click", hideAlertBanner);

// ---------------------------------------------------------------------------
// Render Visual Latency Trend
// ---------------------------------------------------------------------------
function renderLatencyBars(requests) {
    latencyBarsContainer.innerHTML = "";
    const samples = requests.slice(0, 24).reverse(); // Oldest to newest of recent

    if (samples.length === 0) {
        latencyBarsContainer.innerHTML = '<span class="text-muted" style="margin: auto; font-size: 0.8rem;">No recent requests recorded.</span>';
        return;
    }

    const maxLatency = Math.max(...samples.map(r => r.duration_ms), 10.0);

    samples.forEach(req => {
        const col = document.createElement("div");
        col.className = "spark-bar-col";
        col.title = `${req.method} ${req.path} -> ${req.status_code} (${req.duration_ms}ms)`;

        const bar = document.createElement("div");
        bar.className = "spark-bar";
        if (req.status_code >= 500) {
            bar.classList.add("error-bar");
        }

        const pct = Math.max(6, Math.min(100, (req.duration_ms / maxLatency) * 100));
        bar.style.height = `${pct}%`;

        col.appendChild(bar);
        latencyBarsContainer.appendChild(col);
    });
}

// ---------------------------------------------------------------------------
// Render Telemetry Table
// ---------------------------------------------------------------------------
function renderTelemetryTable(requests) {
    streamCounter.textContent = `Showing latest ${requests.length} requests`;

    if (!requests || requests.length === 0) {
        telemetryTableBody.innerHTML = `
            <tr>
                <td colspan="6" class="text-center text-muted">No transactions observed yet. Click any button above to generate traffic!</td>
            </tr>
        `;
        return;
    }

    let rowsHtml = "";
    requests.forEach(req => {
        // Status badge color
        let badgeClass = "badge-2xx";
        if (req.status_code >= 400 && req.status_code < 500) {
            badgeClass = "badge-4xx";
        } else if (req.status_code >= 500) {
            badgeClass = "badge-5xx";
        }

        // Format timestamp
        const timePart = req.timestamp ? req.timestamp.replace("T", " ").replace("Z", "") : "--";

        rowsHtml += `
            <tr>
                <td>${timePart}</td>
                <td><span class="badge badge-method">${escapeHtml(req.method)}</span></td>
                <td><strong>${escapeHtml(req.path)}</strong></td>
                <td><span class="badge ${badgeClass}">${req.status_code}</span></td>
                <td>${req.duration_ms.toFixed(2)} ms</td>
                <td class="text-muted">${escapeHtml(req.client_ip || "unknown")}</td>
            </tr>
        `;
    });

    telemetryTableBody.innerHTML = rowsHtml;
}

function escapeHtml(str) {
    if (!str) return "";
    return String(str)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}

function showActionFeedback(message, isError = false) {
    actionFeedback.textContent = message;
    actionFeedback.className = isError ? "action-feedback text-danger" : "action-feedback text-success";
    actionFeedback.classList.remove("hidden");
    setTimeout(() => {
        actionFeedback.classList.add("hidden");
    }, 6000);
}

// ---------------------------------------------------------------------------
// SRE Workbench Interactive Actions
// ---------------------------------------------------------------------------

// 1. Simulate 500 Incident
simulateErrorBtn.addEventListener("click", async () => {
    simulateErrorBtn.disabled = true;
    try {
        const res = await fetch("/api/demo/simulate-500", { method: "POST" });
        const data = await res.json();
        if (res.status === 500) {
            showActionFeedback(`💥 [SIMULATED INCIDENT] HTTP 500 triggered! Error: ${data.detail}`, true);
        } else {
            showActionFeedback(`Response ${res.status}: ${JSON.stringify(data)}`);
        }
    } catch (err) {
        showActionFeedback(`Triggered error call: ${err.message}`, true);
    } finally {
        simulateErrorBtn.disabled = false;
        fetchTelemetry(); // Immediate refresh
    }
});

// 2. Create Test Booking
createBookingBtn.addEventListener("click", async () => {
    createBookingBtn.disabled = true;
    try {
        // Generate random future dates
        const randomDays = Math.floor(Math.random() * 30) + 1;
        const checkInDate = new Date();
        checkInDate.setDate(checkInDate.getDate() + randomDays);
        const checkOutDate = new Date(checkInDate);
        checkOutDate.setDate(checkOutDate.getDate() + 3);

        const checkInStr = checkInDate.toISOString().split("T")[0];
        const checkOutStr = checkOutDate.toISOString().split("T")[0];

        // Pick room 101 or 102
        const roomId = (Math.random() > 0.5) ? 1 : 2;

        const payload = {
            room_id: roomId,
            guest_name: "Alice Montgomery",
            guest_email: "alice.m@example.com",
            check_in: checkInStr,
            check_out: checkOutStr,
        };

        const res = await fetch("/api/bookings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        });

        const data = await res.json();
        if (res.ok) {
            showActionFeedback(`✅ Booking created! Ref: ${data.booking_reference} (Room ${data.room_number}, ${data.check_in} -> ${data.check_out})`);
        } else {
            showActionFeedback(`❌ Booking failed (${res.status}): ${data.detail}`, true);
        }
    } catch (err) {
        showActionFeedback(`Booking request error: ${err.message}`, true);
    } finally {
        createBookingBtn.disabled = false;
        fetchTelemetry();
    }
});

// 3. Trigger Conflict 409
triggerConflictBtn.addEventListener("click", async () => {
    triggerConflictBtn.disabled = true;
    try {
        // Step A: Ensure base booking exists for fixed dates
        const fixedPayload = {
            room_id: 3, // Ocean View Suite
            guest_name: "Dr. Evelyn Reed",
            guest_email: "evelyn.reed@example.com",
            check_in: "2026-11-20",
            check_out: "2026-11-25",
        };

        // Attempt 1: book it (or might already be booked)
        await fetch("/api/bookings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(fixedPayload),
        });

        // Step B: Now intentionally book overlapping dates (2026-11-22 to 2026-11-27)
        const conflictPayload = {
            room_id: 3,
            guest_name: "Marcus Vance",
            guest_email: "marcus.v@example.com",
            check_in: "2026-11-22",
            check_out: "2026-11-27",
        };

        const conflictRes = await fetch("/api/bookings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(conflictPayload),
        });

        const conflictData = await conflictRes.json();
        if (conflictRes.status === 409) {
            showActionFeedback(`🛡️ [TRANSACTIONAL GUARD] HTTP 409 Conflict prevented double-booking: ${conflictData.detail}`);
        } else {
            showActionFeedback(`Result: HTTP ${conflictRes.status}: ${JSON.stringify(conflictData)}`);
        }
    } catch (err) {
        showActionFeedback(`Conflict test error: ${err.message}`, true);
    } finally {
        triggerConflictBtn.disabled = false;
        fetchTelemetry();
    }
});

// 4. Run Probes Directly
runHealthProbeBtn.addEventListener("click", async () => {
    runHealthProbeBtn.disabled = true;
    try {
        const [hRes, rRes] = await Promise.all([fetch("/health"), fetch("/ready")]);
        const hData = await hRes.json();
        const rData = await rRes.json();
        showActionFeedback(`🩺 Probes Checked: /health (${hRes.status}) [${hData.status}], /ready (${rRes.status}) [DB: ${rData.database}]`);
    } catch (err) {
        showActionFeedback(`Probes check failed: ${err.message}`, true);
    } finally {
        runHealthProbeBtn.disabled = false;
        fetchTelemetry();
    }
});

// ---------------------------------------------------------------------------
// 5-Second Auto Refresh Loop & Manual Trigger
// ---------------------------------------------------------------------------
function resetCountdown() {
    countdownValue = 5;
    refreshTimer.textContent = `${countdownValue}s`;
}

function startPollingLoop() {
    fetchTelemetry();
    resetCountdown();

    if (countdownTimer) clearInterval(countdownTimer);

    countdownTimer = setInterval(() => {
        countdownValue -= 1;
        if (countdownValue <= 0) {
            resetCountdown();
            fetchTelemetry();
        } else {
            refreshTimer.textContent = `${countdownValue}s`;
        }
    }, 1000);
}

manualRefreshBtn.addEventListener("click", () => {
    fetchTelemetry();
    resetCountdown();
});

// Start loop upon page load
window.addEventListener("DOMContentLoaded", startPollingLoop);
