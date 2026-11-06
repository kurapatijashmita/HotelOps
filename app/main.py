"""HotelOps API - Site Reliability Monitoring System.

FastAPI application providing hotel booking endpoints, liveness/readiness probes,
structured HTTP logging middleware, process-local metrics collection, and
safe fault injection for SRE incident simulation.
"""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any

from fastapi import FastAPI, Request, Response, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app import __version__
from app.database import (
    initialize_database,
    check_database_readiness,
    get_all_rooms,
    get_all_bookings,
    create_booking_transaction,
    cancel_booking,
    BookingConflictError,
    ResourceNotFoundError,
    ValidationError,
)
from app.logging_config import logger, log_http_transaction
from app.metrics import metrics_collector
from app.models import (
    RoomResponse,
    BookingCreate,
    BookingResponse,
    CancelResponse,
    HealthResponse,
    ReadyResponse,
    MetricsSummaryResponse,
)

# Demo Mode configuration: enabled by default for development/portfolio evaluation
DEMO_MODE_ENV = os.environ.get("HOTELOPS_DEMO_MODE", "true").lower() in ("true", "1", "yes")

STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown lifecycle management."""
    logger.info("Initializing HotelOps database schema and seed data...")
    initialize_database()
    logger.info(f"HotelOps API v{__version__} ready. Demo Mode: {DEMO_MODE_ENV}")
    yield
    logger.info("HotelOps API shutting down.")


app = FastAPI(
    title="HotelOps API",
    description="Hospitality Site Reliability Monitoring System & Booking API",
    version=__version__,
    lifespan=lifespan,
)

# Enable CORS for local testing/dashboard access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static directory for the monitoring dashboard
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# SRE Observability Middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def sre_observability_middleware(request: Request, call_next):
    """
    SRE Middleware:
    - Measures precise latency (in milliseconds)
    - Records metrics into process-local metrics collector
    - Writes structured JSON log to disk and formatted log to console
    - Adds X-Process-Time-Ms response header
    """
    start_time = time.perf_counter()
    method = request.method
    path = request.url.path
    client_ip = request.client.host if request.client else "unknown"

    try:
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        status_code = response.status_code
        
        # Record observed telemetry
        metrics_collector.record_request(
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
            client_ip=client_ip,
        )
        log_http_transaction(
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
            client_ip=client_ip,
        )

        response.headers["X-Process-Time-Ms"] = f"{duration_ms:.2f}"
        return response

    except Exception as exc:
        duration_ms = (time.perf_counter() - start_time) * 1000.0
        status_code = 500
        
        metrics_collector.record_request(
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
            client_ip=client_ip,
        )
        log_http_transaction(
            method=method,
            path=path,
            status_code=status_code,
            duration_ms=duration_ms,
            client_ip=client_ip,
            error=str(exc),
        )
        
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error occurred.",
                "error_type": type(exc).__name__,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
            headers={"X-Process-Time-Ms": f"{duration_ms:.2f}"},
        )


# ---------------------------------------------------------------------------
# Frontend Dashboard Endpoint
# ---------------------------------------------------------------------------
@app.get("/", include_in_schema=False)
async def serve_dashboard():
    """Serve the single-page SRE Dark Monitoring Dashboard."""
    index_file = STATIC_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return JSONResponse(
        content={"message": "HotelOps API is running. Static dashboard not found."},
        status_code=200,
    )


# ---------------------------------------------------------------------------
# SRE Probes & Telemetry Endpoints
# ---------------------------------------------------------------------------
@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Observability"],
    summary="Liveness probe",
)
async def health_check():
    """
    Liveness probe returning HTTP 200 if the web process is running.
    Used by orchestrators (Kubernetes/Docker/systemd) to verify process responsiveness.
    """
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "service": "hotelops-api",
        "version": __version__,
    }


@app.get(
    "/ready",
    response_model=ReadyResponse,
    tags=["Observability"],
    summary="Readiness probe",
)
async def readiness_check():
    """
    Readiness probe verifying database connectivity via a live query (SELECT 1).
    Returns HTTP 200 when ready to receive traffic, or HTTP 503 Service Unavailable
    when the database connection is degraded or unavailable.
    """
    is_ready = check_database_readiness()
    timestamp = datetime.now(timezone.utc).isoformat()
    
    if is_ready:
        return {
            "status": "ready",
            "database": "connected",
            "timestamp": timestamp,
        }
    
    logger.error("Readiness check failed: Database connectivity error.")
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Database connectivity probe failed. Service not ready.",
    )


@app.get(
    "/metrics-summary",
    response_model=MetricsSummaryResponse,
    tags=["Observability"],
    summary="Process-local metrics summary",
)
async def get_metrics_summary():
    """
    Return real-time, process-local in-memory metrics collected since process startup:
    - Total requests
    - Successful requests (2xx, 3xx)
    - Client errors (4xx) and Server errors (5xx)
    - Average and p95 latencies (in milliseconds)
    - Error rate percentage
    - Process uptime
    - Recent HTTP transactions buffer
    
    NOTE: These metrics are process-local to the running instance and are not historical
    multi-node SLA numbers.
    """
    return metrics_collector.get_summary()


# ---------------------------------------------------------------------------
# Hotel Booking Business Domain Endpoints
# ---------------------------------------------------------------------------
@app.get(
    "/api/rooms",
    response_model=List[RoomResponse],
    tags=["Rooms"],
    summary="List hotel rooms",
)
async def list_rooms():
    """Retrieve all hotel rooms with pricing and capacity."""
    return get_all_rooms()


@app.get(
    "/api/bookings",
    response_model=List[BookingResponse],
    tags=["Bookings"],
    summary="List hotel bookings",
)
async def list_bookings():
    """Retrieve all bookings in reverse chronological order."""
    return get_all_bookings()


@app.post(
    "/api/bookings",
    response_model=BookingResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["Bookings"],
    summary="Create hotel booking with transactional conflict prevention",
)
async def create_booking(booking_in: BookingCreate):
    """
    Create a new hotel room booking.
    
    Uses an immediate database transaction (`BEGIN IMMEDIATE`) to prevent race conditions
    and overlaps for the same room. If another booking overlaps with the requested dates,
    returns HTTP 409 Conflict.
    """
    try:
        new_booking = create_booking_transaction(
            room_id=booking_in.room_id,
            guest_name=booking_in.guest_name,
            guest_email=booking_in.guest_email,
            check_in=booking_in.check_in,
            check_out=booking_in.check_out,
        )
        return new_booking
    except BookingConflictError as err:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(err),
        )
    except ResourceNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        )
    except ValidationError as err:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(err),
        )


@app.delete(
    "/api/bookings/{booking_id}",
    response_model=CancelResponse,
    tags=["Bookings"],
    summary="Cancel booking (DELETE method)",
)
@app.post(
    "/api/bookings/{booking_id}/cancel",
    response_model=CancelResponse,
    tags=["Bookings"],
    summary="Cancel booking (POST method)",
)
async def cancel_booking_endpoint(booking_id: int):
    """Cancel an active booking by ID and free the room for subsequent reservations."""
    try:
        result = cancel_booking(booking_id)
        return result
    except ResourceNotFoundError as err:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(err),
        )


# ---------------------------------------------------------------------------
# SRE Demo / Fault Injection Endpoint
# ---------------------------------------------------------------------------
@app.api_route(
    "/api/demo/simulate-500",
    methods=["GET", "POST"],
    tags=["Fault Injection"],
    summary="Simulate HTTP 500 incident (Demo Mode only)",
)
async def simulate_500_error():
    """
    SRE DEMO MODE FAULT INJECTION:
    Safely triggers an intentional HTTP 500 Internal Server Error to simulate
    an active outage, exercise monitoring alerts, update the dashboard error rate,
    and verify incident triage runbooks.
    
    This endpoint is active only when `HOTELOPS_DEMO_MODE=true` (or development environment).
    """
    if not DEMO_MODE_ENV:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Demo fault injection is disabled in this environment.",
        )

    logger.error(
        "[SIMULATED INCIDENT] Triggered deliberate HTTP 500 error via /api/demo/simulate-500"
    )
    raise HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=(
            "[SIMULATED INCIDENT] HTTP 500 Internal Server Error: "
            "Downstream hospitality PMS payment gateway timeout (synthetic chaos test)."
        ),
    )
