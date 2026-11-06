# 🏨 HotelOps — Site Reliability Monitoring System

[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-009688.svg?style=flat&logo=fastapi)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg?style=flat&logo=python)](https://python.org)
[![SQLite](https://img.shields.io/badge/SQLite-ACID_Transactions-003B57.svg?style=flat&logo=sqlite)](https://sqlite.org)
[![Pytest](https://img.shields.io/badge/Pytest-11_Passed-green.svg?style=flat&logo=pytest)](https://pytest.org)
[![SRE](https://img.shields.io/badge/Discipline-Site_Reliability_Engineering-orange.svg)](#60-second-interview-explanation)

A production-grade, beginner-friendly portfolio project simulating a real-world hospitality technology backend paired with an SRE observability engine. Built specifically for candidates interviewing for **Site Reliability Engineer (SRE)** and **Backend Platform** roles in the hospitality and travel tech industry.

---

## 🎯 60-Second Interview Elevator Pitch

> *"HotelOps is a site reliability and booking telemetry system inspired by the reservation challenges of hospitality platforms. In high-demand hotel booking engines, double-booking a suite during peak check-in windows causes severe customer dissatisfaction and financial chargebacks.
> 
> To solve this, I designed a FastAPI backend with SQLite immediate transactional locking (`BEGIN IMMEDIATE`) that strictly validates interval overlaps (`check_in < existing_check_out AND check_out > existing_check_in`) to guarantee zero race condition overbookings.
> 
> On the SRE side, I implemented decoupled **Liveness (`/health`)** and **Readiness (`/ready`)** probes, custom **ASGI observability middleware** capturing request duration down to the millisecond, structured **JSON logging** to disk, and a thread-safe **process-local metrics engine** that calculates P95 latencies and error rates without any hardcoded mock numbers.
> 
> I also built an **independent out-of-process monitoring daemon** that polls probes, detects outages, tracks downtime duration, and alerts on recovery, alongside an interactive **dark monitoring dashboard** with a built-in fault-injection chaos endpoint to test real-time incident triage runbooks."*

---

## 📐 System Architecture & Telemetry Pipeline

```
  +---------------------------------------------------------------------------------+
  |                                 CLIENT TRAFFIC                                  |
  |             (Hotel Guests, Web Dashboard, Synthetic Test Scripts)              |
  +---------------------------------------+-----------------------------------------+
                                          |
                                          v
+-----------------------------------------------------------------------------------+
|                        HotelOps FastAPI Application Process                       |
|                                                                                   |
|  +-----------------------------------------------------------------------------+  |
|  |                 SRE Observability ASGI Middleware                           |  |
|  |  * Timer: time.perf_counter() -> Duration in milliseconds                   |  |
|  |  * Dispatches structured telemetry to in-memory metrics & local file        |  |
|  |  * Injects header: 'X-Process-Time-Ms'                                      |  |
|  +--------------------------------------+--------------------------------------+  |
|                                         |                                         |
|         +-------------------------------+-------------------------------+         |
|         |                               |                               |         |
|         v                               v                               v         |
|  +--------------+               +---------------+               +---------------+ |
|  | SRE Probes   |               | Process-Local |               | Structured    | |
|  | /health      |               | Metrics Engine|               | JSON Logger   | |
|  | /ready       |               | (In-Memory)   |               | logs/app.log  | |
|  +------+-------+               +-------+-------+               +---------------+ |
|         |                               |                                         |
|         |                               |                                         |
|         v                               v                                         |
|  +--------------------------------------+---------------------------------------+ |
|  |              Hotel Business Domain (Rooms & Bookings)                        | |
|  |   * GET  /api/rooms                                                          | |
|  |   * POST /api/bookings   ──► Immediate Transactional Validation             | |
|  |   * POST /api/bookings/{id}/cancel                                           | |
|  +--------------------------------------+---------------------------------------+ |
|                                         |                                         |
+-----------------------------------------|-----------------------------------------+
                                          |
                                          v
                        +-----------------------------------+
                        |       SQLite Database Engine      |
                        |      (hotelops.db with ACID)      |
                        |  * Guaranteed conflict prevention |
                        +-----------------------------------+

+---------------------------------------------------+      +------------------------+
|       External Out-of-Process Monitor             |      |   Responsive Dark      |
|                 (monitor.py)                      |      | Monitoring Dashboard   |
|  * Runs in dedicated CLI process                  |      |     (/, static UI)     |
|  * Continuous polling of /health & /ready         |      | * Auto-refresh (5s)    |
|  * Emits Terminal Alerts on Outage & Recovery     |      | * Real collected stats |
|  * Writes audit trail to logs/monitor.log         |      | * Fault injection tool |
+---------------------------------------------------+      +------------------------+
```

---

## ⚙️ Core SRE Principles & Engineering Components

### 1. Decoupled Liveness vs. Readiness Probes
* **`/health` (Liveness):** Returns HTTP 200 as long as the web worker process is responsive. Used by process supervisors (systemd, Docker, Kubernetes) to know if the process needs a restart.
* **`/ready` (Readiness):** Executes an active database probe query (`SELECT 1`). If the database file is locked, inaccessible, or corrupted, it returns **HTTP 503 Service Unavailable**, signaling that the service should not receive live guest traffic.

### 2. Transactional Overlap Prevention (ACID Guard)
Hotel rooms cannot be double-booked. We use SQLite's immediate transaction locking (`BEGIN IMMEDIATE`) and query active reservations:
$$\text{Overlap Condition: } \text{new\_check\_in} < \text{existing\_check\_out} \quad \text{AND} \quad \text{new\_check\_out} > \text{existing\_check\_in}$$
If any active confirmed booking matches, the transaction aborts with **HTTP 409 Conflict**, preventing concurrency anomalies.

### 3. Transparent Process-Local Metrics (`/metrics-summary`)
> **Engineering Transparency:** These metrics are collected in-memory by the running Python worker since startup. They are explicitly labeled as `process_local_in_memory` and will reset if the process restarts. They do not simulate fake multi-node SLA uptime. In an enterprise production cluster, an SRE exports these via a `/metrics` Prometheus collector scraped into Grafana.

### 4. Structured JSON Logging (`logs/app.log`)
Instead of unstructured plain text strings that break automated log parsers, the application writes machine-readable JSON lines using Python's standard `logging` library:
```json
{"timestamp": "2026-11-06T12:00:00.123456+00:00", "level": "INFO", "logger": "hotelops", "message": "HTTP POST /api/bookings -> 201 (14.25ms)", "event": "http_request", "method": "POST", "path": "/api/bookings", "status_code": 201, "duration_ms": 14.25, "client_ip": "127.0.0.1"}
```

### 5. Out-of-Process Monitoring Daemon (`monitor.py`)
A self-contained script running in a separate terminal process that polls `/health` and `/ready`. If a probe fails, it sounds an immediate **`[CRITICAL ALERT]`**, measures the outage duration, and fires a **`[RECOVERY ALERT]`** as soon as the service recovers, writing audit records to `logs/monitor.log`.

### 6. Safe Fault Injection (Demo Chaos Mode)
Under `HOTELOPS_DEMO_MODE=true`, the endpoint `POST /api/demo/simulate-500` intentionally raises an HTTP 500 error simulating a downstream PMS payment gateway failure. This allows on-call engineers to practice diagnosing incidents, checking dashboards, and executing runbooks.

---

## 🚀 Quickstart Guide (Windows PowerShell)

Follow these exact Windows PowerShell commands to clone, run, test, and monitor HotelOps.

### Step 1: Open PowerShell and Navigate to the Project
```powershell
cd C:\Users\JASHMITA\.gemini\antigravity\scratch\hotelops
```

### Step 2: Install Dependencies
```powershell
python -m pip install -r requirements.txt
```

### Step 3: Run Automated Pytest Suite
Verify that all 11 unit, integration, and telemetry tests pass:
```powershell
python -m pytest tests/test_api.py -v
```
*Expected output: `11 passed`.*

You can also run the full end-to-end system verification script which spins up the server on a free port, runs live HTTP checks, and cleans up automatically:
```powershell
python verify_system.py
```
*Expected output: `13 PASSED, 0 FAILED`.*

### Step 4: Start the HotelOps API Server
In **Terminal Window 1**, start the FastAPI server:
```powershell
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```
You will see:
```
INFO:     Started server process
INFO:     Initializing HotelOps database schema and seed data...
INFO:     HotelOps API v1.0.0 ready. Demo Mode: True
INFO:     Uvicorn running on http://127.0.0.1:8000
```

### Step 5: Start the External Monitoring Daemon
Open a **new Terminal Window 2** and start the independent monitor:
```powershell
cd C:\Users\JASHMITA\.gemini\antigravity\scratch\hotelops
python monitor.py --interval 3.0
```
You will see live polling heartbeats:
```
[2026-11-06 12:35:00] [HEALTHY] /health: 200 (2.5ms) | /ready: 200 (1.8ms)
```

### Step 6: Open the SRE Dark Monitoring Dashboard
Open your web browser and navigate to:
```
http://127.0.0.1:8000
```

---

## 📡 API Endpoint Reference

| Method | Endpoint | Description | Status Codes |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | Responsive SRE Dark Monitoring Dashboard | `200` |
| `GET` | `/health` | Liveness probe: verifies process is alive | `200` |
| `GET` | `/ready` | Readiness probe: verifies SQLite connectivity | `200`, `503` |
| `GET` | `/metrics-summary` | Real collected process-local telemetry | `200` |
| `GET` | `/api/rooms` | List all hotel rooms with capacity & pricing | `200` |
| `GET` | `/api/bookings` | List all historical and active bookings | `200` |
| `POST` | `/api/bookings` | Create booking with transactional conflict lock | `201`, `400`, `404`, `409` |
| `DELETE` | `/api/bookings/{id}` | Cancel active booking and release inventory | `200`, `404` |
| `POST` | `/api/bookings/{id}/cancel` | Alternative cancel booking endpoint | `200`, `404` |
| `POST` | `/api/demo/simulate-500` | Fault injection: safe simulated 500 error | `500`, `403` |
| `GET` | `/docs` | Interactive Swagger API documentation | `200` |

---

## 🧪 PowerShell Testing & Simulation Commands

Test the system directly from PowerShell with these commands:

### 1. Query Probes
```powershell
# Liveness probe
Invoke-RestMethod -Uri http://127.0.0.1:8000/health -Method GET

# Readiness probe
Invoke-RestMethod -Uri http://127.0.0.1:8000/ready -Method GET
```

### 2. Create a Valid Booking
```powershell
$booking = @{
    room_id = 1
    guest_name = "Sophia Martinez"
    guest_email = "sophia@example.com"
    check_in = "2026-11-15"
    check_out = "2026-11-20"
} | ConvertTo-Json

Invoke-RestMethod -Uri http://127.0.0.1:8000/api/bookings -Method POST -Body $booking -ContentType "application/json"
```

### 3. Trigger Overlapping Conflict (HTTP 409)
Attempt to book the identical room for overlapping dates:
```powershell
$conflict = @{
    room_id = 1
    guest_name = "Double Booker"
    guest_email = "conflict@example.com"
    check_in = "2026-11-18"
    check_out = "2026-11-22"
} | ConvertTo-Json

try {
    Invoke-RestMethod -Uri http://127.0.0.1:8000/api/bookings -Method POST -Body $conflict -ContentType "application/json"
} catch {
    $_.Exception.Response.StatusCode
    $_.ErrorDetails.Message
}
```
*Result: HTTP 409 Conflict with descriptive message.*

### 4. Trigger Simulated Outage (HTTP 500)
```powershell
try {
    Invoke-RestMethod -Uri http://127.0.0.1:8000/api/demo/simulate-500 -Method POST
} catch {
    Write-Host "Triggered simulated incident successfully! Check dashboard and logs/app.log"
}
```

---

## 🖥️ SRE Dashboard & Screenshot Guide

When taking screenshots for your GitHub portfolio or LinkedIn post, capture these three key states:

1. **Optimal Healthy State (`http://127.0.0.1:8000`):**
   * Green pulsing status dot `OPERATIONAL`.
   * Probes OK badge.
   * Total requests counter and low average latency (&lt; 10ms).
   * Status code distribution bar showing 100% green.
2. **Transactional Conflict Handled:**
   * Click **"Trigger 409 Conflict"** button in the SRE Chaos Workbench.
   * Observe the orange feedback alert confirming double-booking was prevented.
   * Telemetry table records HTTP 409 with yellow badge.
3. **Simulated Outage Active:**
   * Click **"Simulate 500 Incident"** button.
   * Red alert banner appears: *"High Server Outage Detected"*.
   * Status indicator switches to red `OUTAGE / ALERT`.
   * Observe `monitor.py` terminal reflecting the error and latency change.

---

## 🛠️ Troubleshooting Guide

### Issue 1: "Address already in use" (Port 8000 Conflict)
* **Cause:** Another process is running on port 8000.
* **Resolution (PowerShell):**
  ```powershell
  # Find and kill the process holding port 8000
  Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force }
  # Alternatively, launch on port 8080:
  python -m uvicorn app.main:app --port 8080
  ```

### Issue 2: "database is locked" in SQLite
* **Cause:** An unclosed connection held a write lock.
* **Resolution:** In HotelOps, all database access is wrapped in a thread-safe context manager with `BEGIN IMMEDIATE` and auto-close. If a process was killed abruptly, delete or unlock `hotelops.db`:
  ```powershell
  Remove-Item hotelops.db -Force -ErrorAction SilentlyContinue
  ```

### Issue 3: PowerShell Script Execution Policy
* **Resolution:** If PowerShell prevents script activation, run:
  ```powershell
  Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
  ```

---

## ⚖️ System Limitations & Engineering Tradeoffs

Honesty and technical self-awareness are foundational Site Reliability Engineering traits. Here are the deliberate design tradeoffs in HotelOps:

1. **Process-Local Metrics Scope:**
   * *Tradeoff:* Telemetry is stored in-memory using Python's `threading.Lock` and circular buffers (`collections.deque`).
   * *Limitation:* Metrics reset whenever the server process restarts and reflect only that single worker.
   * *Production Evolution:* In a multi-replica Kubernetes cluster, each worker would expose standard Prometheus `/metrics` exposition format, scraped by Prometheus server agents and visualized holistically across pods in Grafana.
2. **Single-Node SQLite Storage:**
   * *Tradeoff:* SQLite was chosen for zero-dependency simplicity and transactional ACID compliance (`BEGIN IMMEDIATE`).
   * *Limitation:* SQLite uses file-level locking, which can cause contention under high concurrent writes across multiple worker processes.
   * *Production Evolution:* A distributed hospitality reservation platform would use PostgreSQL with row-level locks (`SELECT ... FOR UPDATE`) or CockroachDB for multi-region active-active replication.
3. **Polling vs. Event-Driven Alerting:**
   * *Tradeoff:* `monitor.py` uses HTTP polling every 3 seconds for lightweight, local out-of-process monitoring.
   * *Limitation:* Polling introduces a detection delay equal to the polling interval (up to 3 seconds) and consumes minor network overhead.
   * *Production Evolution:* Production SRE stacks employ OpenTelemetry instrumentation with streaming spans and Alertmanager webhooks routed into PagerDuty/Opsgenie.
4. **Synthetic Fault Injection Scope:**
   * *Tradeoff:* `/api/demo/simulate-500` provides an easy, self-contained way to verify 5xx detection and error-rate alerting without third-party chaos frameworks.
   * *Limitation:* It simulates application-level failures only, not kernel panics, CPU throttling, or network partitions.

---

## 📚 Incident Runbook
A complete SRE Incident Management Runbook is included in [`RUNBOOK.md`](RUNBOOK.md). It outlines triage workflows (Detect, Investigate, Mitigate, Verify) and includes a blameless post-mortem template.
