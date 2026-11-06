# 📖 HotelOps Incident Runbook: Hospitality SRE Response Guide

> **Target Audience:** Site Reliability Engineers, On-Call Operators, and Incident Commanders.  
> **Service:** HotelOps Booking API & Telemetry Engine  
> **Service Level Objective (SLO):** Availability &ge; 99.9%, HTTP Error Rate &lt; 1.0%, Latency P95 &lt; 100ms.

---

## 1. Incident Severity Matrix

| Severity | Impact Description | Detection Trigger | Target Response |
| :--- | :--- | :--- | :--- |
| **SEV-1 (Critical)** | Complete service outage or database unreachable. Guests cannot search or book rooms. | `monitor.py` outputs `[CRITICAL ALERT]`, `/health` or `/ready` probe returns 503 or connection timeout. | Immediate paging (&lt; 5 min) |
| **SEV-2 (High)** | Elevated error rate (&ge; 5%) or PMS/booking conflicts. Partial booking failures. | Dashboard turns RED (`CRITICAL ERROR RATE`), 5xx spike in `logs/app.log`. | &lt; 15 min triage |
| **SEV-3 (Moderate)** | High request latency (P95 &gt; 250ms) or repetitive 409 conflict spam. | Dashboard warning banner, elevated `duration_ms` in `/metrics-summary`. | &lt; 1 hour investigation |

---

## 2. Standard Triage Workflow (DIMV)

```
[ DETECT ] ──► [ INVESTIGATE ] ──► [ MITIGATE ] ──► [ VERIFY ] ──► [ POST-MORTEM ]
```

### Phase 1: DETECT
Alerts surface through two primary mechanisms:
1. **External Monitor Alert:** Terminal output from `monitor.py` displaying `[CRITICAL ALERT] SERVICE OUTAGE DETECTED!`
2. **Dashboard Visual Indicators:** Status indicator switches from green `OPERATIONAL` to red `OUTAGE / ALERT` with alert banner.

### Phase 2: INVESTIGATE
Open Windows PowerShell and run the following diagnostic commands:

#### Step 1: Probe Health & Readiness Probes
```powershell
# Probe Liveness (Process alive?)
Invoke-RestMethod -Uri http://127.0.0.1:8000/health -Method GET

# Probe Readiness (Database connected?)
Invoke-RestMethod -Uri http://127.0.0.1:8000/ready -Method GET
```
* **Interpretation:**
  * If `/health` fails: Web process has crashed or hung.
  * If `/health` is 200 but `/ready` is 503: Database lock, disk exhaustion, or SQLite corrupted.

#### Step 2: Query Process Metrics Summary
```powershell
Invoke-RestMethod -Uri http://127.0.0.1:8000/metrics-summary -Method GET | Select-Object -Property service, uptime_human, total_requests, error_rate_percentage, status_codes
```
* Check `error_rate_percentage` and breakdown of `5xx` vs `4xx` responses.

#### Step 3: Inspect Structured Error Logs
Filter recent error lines from the local JSON application log:
```powershell
Get-Content logs/app.log -Tail 30 | Select-String '"level": "ERROR"'
```
* Look for stack traces, `[SIMULATED INCIDENT]` chaos tags, or `sqlite3.OperationalError` (database locked).

---

## 3. Mitigation & Recovery Procedures

### Scenario A: Deliberate Chaos / Fault Injection Triggered (HTTP 500)
* **Symptom:** Logs show `[SIMULATED INCIDENT] Triggered deliberate HTTP 500 error via /api/demo/simulate-500`.
* **Action:**
  1. Confirm the 500 errors were originating from `/api/demo/simulate-500`.
  2. If running in production or staging, disable demo mode by setting the environment variable:
     ```powershell
     $env:HOTELOPS_DEMO_MODE = "false"
     ```
  3. Send synthetic valid traffic (create test booking) to verify normal transaction flow resumes.

### Scenario B: Database Locked or Connectivity Failure (`/ready` fails with 503)
* **Symptom:** `/ready` returns 503 Service Unavailable; log shows `sqlite3.OperationalError: database is locked`.
* **Action:**
  1. Check for orphaned zombie Python processes holding open file locks on `hotelops.db`:
     ```powershell
     Get-Process -Name python -ErrorAction SilentlyContinue
     ```
  2. Terminate zombie processes if necessary:
     ```powershell
     Stop-Process -Name python -Force
     ```
  3. Restart the FastAPI service cleanly:
     ```powershell
     python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
     ```

### Scenario C: Web Worker Crashed / Unresponsive (Connection Refused)
* **Symptom:** `monitor.py` reports `Network Failure: connection refused`.
* **Action:**
  1. Restart the application:
     ```powershell
     cd C:\Users\JASHMITA\.gemini\antigravity\scratch\hotelops
     python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
     ```
  2. Observe `monitor.py` terminal. It should automatically detect recovery:
     ```
     [RECOVERY ALERT] SERVICE RESTORED! Probes are 200 OK after Xs outage.
     ```

---

## 4. Post-Incident Verification
Before closing an incident ticket:
1. Confirm `/health` returns HTTP 200.
2. Confirm `/ready` returns HTTP 200 with `"database": "connected"`.
3. Check `monitor.py` reports steady `[HEALTHY]` heartbeat logs.
4. Open the dark dashboard at `http://127.0.0.1:8000` and confirm the status badge displays green `OPERATIONAL`.
5. Check `logs/monitor.log` has recorded the recovery entry:
   ```json
   {"monitor_event": "SERVICE_RECOVERED", "outage_duration_seconds": 14.2}
   ```

---

## 5. Blameless Post-Mortem Template

```markdown
# Incident Post-Mortem: [INCIDENT-ID]

**Date:** YYYY-MM-DD  
**Incident Commander:** [Name]  
**Severity:** SEV-[1/2/3]  
**Duration of Outage:** [X minutes / seconds]  

### 1. Summary
A brief 2-sentence description of what occurred and guest/customer impact.

### 2. Timeline (UTC)
- **12:00:00** - Initial anomaly / trigger.
- **12:01:15** - `monitor.py` detected probe failure and alerted on-call.
- **12:03:00** - Triage began; inspected `logs/app.log`.
- **12:05:30** - Root cause identified; mitigation executed.
- **12:06:45** - Probes verified healthy; recovery logged.

### 3. Root Cause
Detailed explanation of why the failure occurred (5 Whys methodology).

### 4. What Went Well vs. Where We Got Lucky vs. Action Items
- [ ] Action item 1 (Prevent recurrence) - Owner: [Name] - Due: [Date]
- [ ] Action item 2 (Improve alert latency) - Owner: [Name] - Due: [Date]
```
