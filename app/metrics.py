"""Process-local in-memory metrics collector for HotelOps.

Maintains real-time HTTP metrics, status code distributions, latency percentiles,
and recent request history. All values are thread-safe and collected in-memory.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional


def format_uptime_human(seconds: float) -> str:
    """Format elapsed seconds into human-readable d/h/m/s representation."""
    total_sec = int(seconds)
    days, rem = divmod(total_sec, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, sec = divmod(rem, 60)
    
    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0 or days > 0:
        parts.append(f"{hours}h")
    if minutes > 0 or hours > 0 or days > 0:
        parts.append(f"{minutes}m")
    parts.append(f"{sec}s")
    return " ".join(parts)


class ProcessMetrics:
    """
    Thread-safe in-memory metrics collector.
    
    NOTE FOR SRE INTERVIEWS:
    These are process-local metrics scoped to a single worker instance.
    They reset whenever the application restarts and do not persist across crashes.
    In production environments, SREs export these as Prometheus metrics to be
    scraped by a centralized monitoring cluster and visualized in Grafana.
    """

    def __init__(self, service_name: str = "hotelops-api", version: str = "1.0.0") -> None:
        self.service_name = service_name
        self.version = version
        self._lock = threading.Lock()
        self.start_time = time.time()
        
        # Counters
        self.total_requests: int = 0
        self.successful_requests: int = 0  # 2xx and 3xx
        self.client_error_requests: int = 0  # 4xx
        self.server_error_requests: int = 0  # 5xx
        self.status_codes: Dict[str, int] = {}
        
        # Latency tracking
        self.total_latency_ms: float = 0.0
        self.recent_latencies: deque = deque(maxlen=1000)
        
        # Recent request stream buffer (latest 50 requests)
        self.recent_requests: deque = deque(maxlen=50)

    def record_request(
        self,
        method: str,
        path: str,
        status_code: int,
        duration_ms: float,
        client_ip: Optional[str] = None,
    ) -> None:
        """Record an observed HTTP transaction."""
        now_iso = datetime.now(timezone.utc).isoformat()
        status_str = str(status_code)

        with self._lock:
            self.total_requests += 1
            self.total_latency_ms += duration_ms
            self.recent_latencies.append(duration_ms)
            
            # Categorize status codes
            if 200 <= status_code < 400:
                self.successful_requests += 1
            elif 400 <= status_code < 500:
                self.client_error_requests += 1
            elif status_code >= 500:
                self.server_error_requests += 1

            self.status_codes[status_str] = self.status_codes.get(status_str, 0) + 1

            self.recent_requests.appendleft({
                "timestamp": now_iso,
                "method": method,
                "path": path,
                "status_code": status_code,
                "duration_ms": round(duration_ms, 2),
                "client_ip": client_ip or "unknown",
            })

    def get_summary(self) -> Dict[str, Any]:
        """Compute and return the metrics snapshot."""
        with self._lock:
            uptime = time.time() - self.start_time
            total = self.total_requests
            failed = self.client_error_requests + self.server_error_requests
            
            avg_lat = (self.total_latency_ms / total) if total > 0 else 0.0
            
            # Calculate p95 latency from recent samples
            if self.recent_latencies:
                sorted_lats = sorted(self.recent_latencies)
                idx = int(0.95 * len(sorted_lats))
                p95_lat = sorted_lats[min(idx, len(sorted_lats) - 1)]
            else:
                p95_lat = 0.0

            error_rate = ((failed / total) * 100.0) if total > 0 else 0.0
            
            # Snapshot of recent requests
            recent_copy = list(self.recent_requests)
            status_copy = dict(self.status_codes)

        return {
            "metric_scope": "process_local_in_memory",
            "disclaimer": (
                "Process-local metrics collected since startup. Resets on process restart. "
                "Does not represent multi-node or persistent historical SLA/uptime."
            ),
            "service": self.service_name,
            "version": self.version,
            "uptime_seconds": round(uptime, 2),
            "uptime_human": format_uptime_human(uptime),
            "total_requests": total,
            "successful_requests": self.successful_requests,
            "client_error_requests": self.client_error_requests,
            "server_error_requests": self.server_error_requests,
            "failed_requests": failed,
            "average_latency_ms": round(avg_lat, 2),
            "p95_latency_ms": round(p95_lat, 2),
            "error_rate_percentage": round(error_rate, 2),
            "status_codes": status_copy,
            "recent_requests": recent_copy,
            "collected_at": datetime.now(timezone.utc).isoformat(),
        }


# Global metrics instance for the application process
metrics_collector = ProcessMetrics()
