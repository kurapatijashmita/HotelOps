"""Verification script for HotelOps SRE Monitoring System.

Checks port availability (8000 or alternative 8765), starts only the HotelOps
uvicorn server process, runs comprehensive live HTTP verification tests, tests
the monitor logic, verifies logs and metrics updates, and terminates ONLY the
spawned server process by PID.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, Any

PROJECT_DIR = Path(__file__).resolve().parent
LOGS_DIR = PROJECT_DIR / "logs"
APP_LOG = LOGS_DIR / "app.log"
MONITOR_LOG = LOGS_DIR / "monitor.log"


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Check if a TCP port is currently occupied."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def select_port() -> int:
    """Select port 8000 if free; otherwise fallback to 8765 (or an available port)."""
    if not is_port_in_use(8000):
        return 8000
    print("[PORT CHECK] Port 8000 is occupied. Falling back to alternative port 8765.")
    if not is_port_in_use(8765):
        return 8765
    # Find any free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def make_request(
    url: str,
    method: str = "GET",
    data: Any = None,
    headers: Dict[str, str] = None,
    timeout: float = 5.0,
) -> Dict[str, Any]:
    """Perform HTTP request returning status, headers, body and parsed json."""
    req_headers = headers or {}
    encoded_data = None
    if data is not None:
        if isinstance(data, (dict, list)):
            encoded_data = json.dumps(data).encode("utf-8")
            req_headers["Content-Type"] = "application/json"
        elif isinstance(data, str):
            encoded_data = data.encode("utf-8")

    req = urllib.request.Request(url, data=encoded_data, headers=req_headers, method=method)
    start_time = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            body = response.read().decode("utf-8", errors="replace")
            parsed_json = None
            try:
                parsed_json = json.loads(body)
            except Exception:
                pass
            return {
                "ok": True,
                "status_code": response.getcode(),
                "duration_ms": duration_ms,
                "headers": dict(response.headers),
                "body": body,
                "json": parsed_json,
                "error": None,
            }
    except urllib.error.HTTPError as err:
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        err_body = err.read().decode("utf-8", errors="replace")
        parsed_json = None
        try:
            parsed_json = json.loads(err_body)
        except Exception:
            pass
        return {
            "ok": False,
            "status_code": err.code,
            "duration_ms": duration_ms,
            "headers": dict(err.headers),
            "body": err_body,
            "json": parsed_json,
            "error": str(err),
        }
    except Exception as exc:
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        return {
            "ok": False,
            "status_code": 0,
            "duration_ms": duration_ms,
            "headers": {},
            "body": "",
            "json": None,
            "error": str(exc),
        }


def run_verification():
    port = select_port()
    base_url = f"http://127.0.0.1:{port}"
    print(f"\n=======================================================")
    print(f"  HotelOps Live Verification Suite (Target Port: {port})")
    print(f"=======================================================\n")

    # Start uvicorn subprocess strictly
    server_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    ]
    print(f"Starting HotelOps server: {' '.join(server_cmd)}")
    env = os.environ.copy()
    env["HOTELOPS_DEMO_MODE"] = "true"

    server_proc = subprocess.Popen(
        server_cmd,
        cwd=str(PROJECT_DIR),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    test_results = []

    def record_check(name: str, passed: bool, details: str):
        status_text = "PASS" if passed else "FAIL"
        print(f"[{status_text}] {name}: {details}")
        test_results.append({"name": name, "passed": passed, "details": details})

    try:
        # Wait for server to bind
        bound = False
        for _ in range(25):
            time.sleep(0.3)
            if is_port_in_use(port):
                bound = True
                break
        if not bound:
            record_check("Server Startup", False, f"Server failed to bind to {base_url} within 7.5s")
            return test_results
        
        record_check("Server Startup", True, f"Server PID {server_proc.pid} bound to {base_url}")

        # 1. Health Probe
        res = make_request(f"{base_url}/health")
        passed = res["status_code"] == 200 and res.get("json", {}).get("status") == "healthy"
        record_check("GET /health (Liveness)", passed, f"Status={res['status_code']}, Body={res['body']}")

        # 2. Readiness Probe
        res = make_request(f"{base_url}/ready")
        passed = res["status_code"] == 200 and res.get("json", {}).get("database") == "connected"
        record_check("GET /ready (Readiness)", passed, f"Status={res['status_code']}, Body={res['body']}")

        # 3. Dashboard HTML & Assets
        dash_res = make_request(f"{base_url}/")
        dash_passed = dash_res["status_code"] == 200 and "HotelOps" in dash_res["body"]
        record_check("GET / (Dashboard HTML)", dash_passed, f"Status={dash_res['status_code']}, Length={len(dash_res['body'])}")

        css_res = make_request(f"{base_url}/static/styles.css")
        record_check("GET /static/styles.css", css_res["status_code"] == 200, f"Status={css_res['status_code']}")

        js_res = make_request(f"{base_url}/static/dashboard.js")
        record_check("GET /static/dashboard.js", js_res["status_code"] == 200, f"Status={js_res['status_code']}")

        # 4. Metrics Summary (Initial)
        metrics_before = make_request(f"{base_url}/metrics-summary")
        before_passed = metrics_before["status_code"] == 200 and metrics_before.get("json", {}).get("metric_scope") == "process_local_in_memory"
        initial_total = metrics_before.get("json", {}).get("total_requests", 0)
        record_check("GET /metrics-summary (Initial)", before_passed, f"Total requests before tests: {initial_total}")

        # 5. Booking Creation
        booking_payload = {
            "room_id": 1,
            "guest_name": "Verification Guest",
            "guest_email": "verify@hotelops.io",
            "check_in": "2026-12-15",
            "check_out": "2026-12-20",
        }
        book_res = make_request(f"{base_url}/api/bookings", method="POST", data=booking_payload)
        book_passed = book_res["status_code"] == 201 and "booking_reference" in book_res.get("json", {})
        book_ref = book_res.get("json", {}).get("booking_reference", "NONE")
        record_check("POST /api/bookings (Create)", book_passed, f"Status={book_res['status_code']}, Reference={book_ref}")

        # 6. Double-Booking Prevention (Transactional Conflict)
        conflict_payload = {
            "room_id": 1,
            "guest_name": "Double Booking Attempter",
            "guest_email": "conflict@hotelops.io",
            "check_in": "2026-12-18",
            "check_out": "2026-12-22",
        }
        conflict_res = make_request(f"{base_url}/api/bookings", method="POST", data=conflict_payload)
        conflict_passed = conflict_res["status_code"] == 409 and "already booked" in conflict_res["body"]
        record_check("POST /api/bookings (Overlapping Conflict Guard)", conflict_passed, f"Status={conflict_res['status_code']} (Expected 409), Body={conflict_res['body']}")

        # 7. Simulated HTTP 500 Fault Injection
        err_res = make_request(f"{base_url}/api/demo/simulate-500", method="POST")
        err_passed = err_res["status_code"] == 500 and "SIMULATED INCIDENT" in err_res["body"]
        record_check("POST /api/demo/simulate-500 (Fault Injection)", err_passed, f"Status={err_res['status_code']} (Expected 500), Body={err_res['body']}")

        # 8. Updated Metrics Summary Verification
        metrics_after = make_request(f"{base_url}/metrics-summary")
        m_json = metrics_after.get("json", {})
        after_total = m_json.get("total_requests", 0)
        client_errs = m_json.get("client_error_requests", 0)
        server_errs = m_json.get("server_error_requests", 0)
        err_rate = m_json.get("error_rate_percentage", 0.0)
        recent_count = len(m_json.get("recent_requests", []))
        
        metrics_updated = (
            after_total > initial_total
            and client_errs >= 1  # From the 409 conflict
            and server_errs >= 1  # From the 500 simulation
            and err_rate > 0.0
            and recent_count > 0
        )
        record_check(
            "Metrics Dynamic Update",
            metrics_updated,
            f"Total: {initial_total} -> {after_total}, 4xx: {client_errs}, 5xx: {server_errs}, ErrorRate: {err_rate:.1f}%, RecentReqs: {recent_count}",
        )

        # 9. Verify Structured Log Writing
        time.sleep(0.5)  # allow I/O flush
        if APP_LOG.exists():
            log_content = APP_LOG.read_text(encoding="utf-8")
            log_lines = [line for line in log_content.strip().splitlines() if line]
            has_json_logs = False
            has_recent_endpoints = False
            for line in log_lines[-10:]:
                try:
                    entry = json.loads(line)
                    if "status_code" in entry and "duration_ms" in entry:
                        has_json_logs = True
                        if "/api/demo/simulate-500" in entry.get("path", ""):
                            has_recent_endpoints = True
                except Exception:
                    pass
            log_passed = has_json_logs and has_recent_endpoints
            record_check("Structured Logging (logs/app.log)", log_passed, f"Total log lines: {len(log_lines)}, JSON formatted: {has_json_logs}")
        else:
            record_check("Structured Logging (logs/app.log)", False, "logs/app.log does not exist")

        # 10. Independent Monitor Script Verification
        from monitor import probe_endpoint
        h_ok, h_status, h_lat, h_msg = probe_endpoint(f"{base_url}/health")
        r_ok, r_status, r_lat, r_msg = probe_endpoint(f"{base_url}/ready")
        monitor_passed = h_ok and (h_status == 200) and r_ok and (r_status == 200)
        record_check(
            "Independent Monitor Prober (monitor.py)",
            monitor_passed,
            f"/health: status={h_status} ({h_lat:.2f}ms), /ready: status={r_status} ({r_lat:.2f}ms)",
        )

    finally:
        # STRICT CLEANUP: Terminate ONLY the spawned server process
        print(f"\n[CLEANUP] Stopping HotelOps server process (PID {server_proc.pid})...")
        server_proc.terminate()
        try:
            server_proc.wait(timeout=3.0)
            print("[CLEANUP] Server stopped cleanly.")
        except subprocess.TimeoutExpired:
            server_proc.kill()
            print("[CLEANUP] Server process killed after timeout.")

    return test_results


if __name__ == "__main__":
    results = run_verification()
    passed_count = sum(1 for r in results if r["passed"])
    failed_count = sum(1 for r in results if not r["passed"])
    print(f"\n=======================================================")
    print(f"  Verification Summary: {passed_count} PASSED, {failed_count} FAILED")
    print(f"=======================================================\n")
    if failed_count > 0:
        sys.exit(1)
    sys.exit(0)
