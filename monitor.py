"""HotelOps External Site Reliability Monitor.

An out-of-process monitoring daemon that polls /health and /ready probes,
tracks uptime and outages, detects service degradation or crashes,
prints alerts in the terminal, and logs outages to `logs/monitor.log`.

Designed to run completely independently from the FastAPI API process.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Tuple, Optional, Dict, Any

DEFAULT_BASE_URL = os.environ.get("HOTELOPS_BASE_URL", "http://127.0.0.1:8000")
LOGS_DIR = Path(__file__).resolve().parent / "logs"
MONITOR_LOG_FILE = LOGS_DIR / "monitor.log"


class TerminalColors:
    """ANSI color codes for terminal alert output."""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    GREEN = "\033[92m"
    YELLOW = "\033[93m"
    RED = "\033[91m"
    CYAN = "\033[96m"
    GRAY = "\033[90m"


def write_monitor_log(event_type: str, details: Dict[str, Any]) -> None:
    """Append a structured log record to logs/monitor.log."""
    MONITOR_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "monitor_event": event_type,
        **details,
    }
    with open(MONITOR_LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")


def probe_endpoint(url: str, timeout: float = 2.0) -> Tuple[bool, int, float, str]:
    """
    Probe an HTTP endpoint using standard library urllib.
    Returns: (is_success, status_code, latency_ms, message_or_error)
    """
    start = time.perf_counter()
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "HotelOps-SRE-Monitor/1.0"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            latency_ms = (time.perf_counter() - start) * 1000.0
            status_code = response.getcode()
            body = response.read().decode("utf-8", errors="replace")
            return (True, status_code, latency_ms, body)
    except urllib.error.HTTPError as err:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return (False, err.code, latency_ms, f"HTTP Error {err.code}: {err.reason}")
    except urllib.error.URLError as err:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return (False, 0, latency_ms, f"Network Failure: {err.reason}")
    except Exception as exc:
        latency_ms = (time.perf_counter() - start) * 1000.0
        return (False, 0, latency_ms, f"Exception: {str(exc)}")


def run_monitor(
    base_url: str = DEFAULT_BASE_URL,
    poll_interval: float = 3.0,
    max_polls: Optional[int] = None,
) -> None:
    """
    Continuous monitoring loop.
    Polls /health and /ready and triggers terminal alerts on state transitions.
    """
    health_url = f"{base_url.rstrip('/')}/health"
    ready_url = f"{base_url.rstrip('/')}/ready"

    print(f"{TerminalColors.CYAN}{TerminalColors.BOLD}======================================================{TerminalColors.RESET}")
    print(f"{TerminalColors.CYAN}{TerminalColors.BOLD}  HotelOps — SRE Out-of-Process Monitor Daemon       {TerminalColors.RESET}")
    print(f"{TerminalColors.CYAN}======================================================{TerminalColors.RESET}")
    print(f"Target Service : {TerminalColors.BOLD}{base_url}{TerminalColors.RESET}")
    print(f"Polling Rate   : Every {poll_interval}s")
    print(f"Log Destination: {MONITOR_LOG_FILE}")
    print(f"Press {TerminalColors.BOLD}Ctrl+C{TerminalColors.RESET} to stop monitoring.\n")

    current_state = "UNKNOWN"
    outage_start_time: Optional[float] = None
    polls_count = 0

    try:
        while True:
            polls_count += 1
            now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            # Check liveness and readiness probes
            h_ok, h_status, h_lat, h_msg = probe_endpoint(health_url)
            r_ok, r_status, r_lat, r_msg = probe_endpoint(ready_url)

            is_overall_healthy = h_ok and r_ok

            if is_overall_healthy:
                total_lat = h_lat + r_lat
                if current_state == "DOWN":
                    # RECOVERY TRANSITION
                    outage_duration = time.time() - (outage_start_time or time.time())
                    print(
                        f"\n{TerminalColors.GREEN}{TerminalColors.BOLD}"
                        f"[{now_str}] [RECOVERY ALERT] SERVICE RESTORED! "
                        f"Probes are 200 OK after {outage_duration:.1f}s outage."
                        f"{TerminalColors.RESET}"
                    )
                    write_monitor_log("SERVICE_RECOVERED", {
                        "outage_duration_seconds": round(outage_duration, 2),
                        "health_status": h_status,
                        "ready_status": r_status,
                        "health_latency_ms": round(h_lat, 2),
                        "ready_latency_ms": round(r_lat, 2),
                    })
                    outage_start_time = None

                current_state = "HEALTHY"
                print(
                    f"{TerminalColors.GRAY}[{now_str}]{TerminalColors.RESET} "
                    f"{TerminalColors.GREEN}[HEALTHY]{TerminalColors.RESET} "
                    f"/health: {h_status} ({h_lat:.1f}ms) | "
                    f"/ready: {r_status} ({r_lat:.1f}ms)"
                )

            else:
                # SERVICE DEGRADED OR DOWN
                failure_reason = []
                if not h_ok:
                    failure_reason.append(f"/health failed (status={h_status}: {h_msg})")
                if not r_ok:
                    failure_reason.append(f"/ready failed (status={r_status}: {r_msg})")
                
                reason_str = " | ".join(failure_reason)

                if current_state != "DOWN":
                    # OUTAGE TRANSITION
                    outage_start_time = time.time()
                    print(
                        f"\n{TerminalColors.RED}{TerminalColors.BOLD}"
                        f"[{now_str}] [CRITICAL ALERT] SERVICE OUTAGE DETECTED!\n"
                        f"Reason: {reason_str}"
                        f"{TerminalColors.RESET}"
                    )
                    write_monitor_log("SERVICE_OUTAGE_DETECTED", {
                        "reason": reason_str,
                        "health_status": h_status,
                        "ready_status": r_status,
                        "health_message": h_msg,
                        "ready_message": r_msg,
                    })
                else:
                    elapsed = time.time() - (outage_start_time or time.time())
                    print(
                        f"{TerminalColors.GRAY}[{now_str}]{TerminalColors.RESET} "
                        f"{TerminalColors.RED}[DOWN]{TerminalColors.RESET} "
                        f"Ongoing outage ({elapsed:.1f}s elapsed) - {reason_str}"
                    )

                current_state = "DOWN"

            if max_polls and polls_count >= max_polls:
                print(f"\nCompleted {polls_count} poll iterations. Exiting cleanly.")
                break

            time.sleep(poll_interval)

    except KeyboardInterrupt:
        print(f"\n{TerminalColors.CYAN}Monitor stopped by operator. Exiting...{TerminalColors.RESET}")
        sys.exit(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="HotelOps External SRE Monitoring Poller")
    parser.add_argument(
        "--url",
        default=DEFAULT_BASE_URL,
        help=f"Base URL of HotelOps API (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=3.0,
        help="Polling interval in seconds (default: 3.0)",
    )
    parser.add_argument(
        "--max-polls",
        type=int,
        default=None,
        help="Optional maximum number of polls to execute before exiting (useful for automated testing)",
    )
    args = parser.parse_args()

    run_monitor(base_url=args.url, poll_interval=args.interval, max_polls=args.max_polls)
