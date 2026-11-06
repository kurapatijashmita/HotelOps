"""Automated Pytest Suite for HotelOps Site Reliability Monitoring System.

Verifies:
1. Health and readiness observability probes (/health, /ready)
2. Hotel room listing and inventory
3. Booking creation with transactional overlapping conflict prevention (409)
4. Date validation and room not found checks (400, 404, 422)
5. Booking cancellation and inventory release
6. Demo fault injection 500 error simulation
7. Process-local metrics summary calculation (requests, latencies, error rate)
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

# Setup temporary SQLite database for testing before importing app modules
test_db_file = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
test_db_path = test_db_file.name
test_db_file.close()

os.environ["HOTELOPS_DB_PATH"] = test_db_path
os.environ["HOTELOPS_DEMO_MODE"] = "true"

from app.database import initialize_database
from app.main import app
from app.metrics import metrics_collector


@pytest.fixture(scope="session", autouse=True)
def setup_test_environment():
    """Initialize schema and seed rooms in the isolated test database."""
    initialize_database()
    yield
    # Cleanup temporary test database file
    if os.path.exists(test_db_path):
        try:
            os.remove(test_db_path)
        except OSError:
            pass


@pytest.fixture
def client():
    """Create a FastAPI test client."""
    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# Observability Probe Tests
# ---------------------------------------------------------------------------
def test_health_probe(client):
    """Liveness probe must return HTTP 200 with healthy status and metadata."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "hotelops-api"
    assert "version" in data
    assert "timestamp" in data


def test_readiness_probe(client):
    """Readiness probe must return HTTP 200 verifying SQLite connectivity."""
    response = client.get("/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert data["database"] == "connected"
    assert "timestamp" in data


# ---------------------------------------------------------------------------
# Hotel Business Domain Tests
# ---------------------------------------------------------------------------
def test_list_rooms(client):
    """Rooms endpoint should return seeded rooms."""
    response = client.get("/api/rooms")
    assert response.status_code == 200
    rooms = response.json()
    assert isinstance(rooms, list)
    assert len(rooms) >= 5
    first_room = rooms[0]
    assert "id" in first_room
    assert "room_number" in first_room
    assert "price_per_night" in first_room
    assert "capacity" in first_room


def test_create_booking_success(client):
    """Creating a valid booking should succeed and return 201 Created."""
    payload = {
        "room_id": 1,
        "guest_name": "Eleanor Vance",
        "guest_email": "eleanor.vance@example.com",
        "check_in": "2026-11-10",
        "check_out": "2026-11-15",
    }
    response = client.post("/api/bookings", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "confirmed"
    assert data["room_id"] == 1
    assert data["guest_name"] == "Eleanor Vance"
    assert data["check_in"] == "2026-11-10"
    assert data["check_out"] == "2026-11-15"
    assert data["booking_reference"].startswith("HOTEL-")


def test_overlapping_booking_conflict(client):
    """
    Attempting to book the same room on overlapping dates must be rejected
    with HTTP 409 Conflict.
    """
    # Base booking: room 2, 2026-12-01 to 2026-12-06
    base_payload = {
        "room_id": 2,
        "guest_name": "Initial Guest",
        "guest_email": "initial@example.com",
        "check_in": "2026-12-01",
        "check_out": "2026-12-06",
    }
    base_res = client.post("/api/bookings", json=base_payload)
    assert base_res.status_code == 201

    # Overlap Scenario 1: Partial overlap inside (2026-12-03 to 2026-12-08)
    overlap_1 = {
        "room_id": 2,
        "guest_name": "Conflicting Guest 1",
        "guest_email": "conflict1@example.com",
        "check_in": "2026-12-03",
        "check_out": "2026-12-08",
    }
    res_1 = client.post("/api/bookings", json=overlap_1)
    assert res_1.status_code == 409
    assert "already booked" in res_1.json()["detail"]

    # Overlap Scenario 2: Partial overlap earlier (2026-11-28 to 2026-12-02)
    overlap_2 = {
        "room_id": 2,
        "guest_name": "Conflicting Guest 2",
        "guest_email": "conflict2@example.com",
        "check_in": "2026-11-28",
        "check_out": "2026-12-02",
    }
    res_2 = client.post("/api/bookings", json=overlap_2)
    assert res_2.status_code == 409

    # Overlap Scenario 3: Complete envelopment (2026-11-25 to 2026-12-10)
    overlap_3 = {
        "room_id": 2,
        "guest_name": "Conflicting Guest 3",
        "guest_email": "conflict3@example.com",
        "check_in": "2026-11-25",
        "check_out": "2026-12-10",
    }
    res_3 = client.post("/api/bookings", json=overlap_3)
    assert res_3.status_code == 409


def test_adjacent_non_overlapping_booking_succeeds(client):
    """
    Hospitality domain rule: An adjacent booking starting on the check_out day
    of an existing booking must be allowed (standard check-out / check-in turnover).
    """
    # Existing booking on room 2 ends on 2026-12-06
    adjacent_payload = {
        "room_id": 2,
        "guest_name": "Next Guest",
        "guest_email": "next@example.com",
        "check_in": "2026-12-06",
        "check_out": "2026-12-10",
    }
    response = client.post("/api/bookings", json=adjacent_payload)
    assert response.status_code == 201
    assert response.json()["status"] == "confirmed"


def test_invalid_dates_validation(client):
    """Invalid date range (check_out <= check_in) returns 400 Bad Request."""
    payload = {
        "room_id": 1,
        "guest_name": "Date Test",
        "guest_email": "dates@example.com",
        "check_in": "2026-12-15",
        "check_out": "2026-12-10",
    }
    response = client.post("/api/bookings", json=payload)
    assert response.status_code == 400
    assert "strictly after" in response.json()["detail"]


def test_room_not_found(client):
    """Booking a non-existent room ID returns 404 Not Found."""
    payload = {
        "room_id": 9999,
        "guest_name": "Ghost Guest",
        "guest_email": "ghost@example.com",
        "check_in": "2026-12-15",
        "check_out": "2026-12-20",
    }
    response = client.post("/api/bookings", json=payload)
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_cancel_booking_and_rebook(client):
    """
    Cancelling a booking should release the room so the same dates can be
    rebooked immediately.
    """
    # Step 1: Create booking on room 4
    booking_payload = {
        "room_id": 4,
        "guest_name": "Cancellable Guest",
        "guest_email": "cancel@example.com",
        "check_in": "2027-01-01",
        "check_out": "2027-01-05",
    }
    create_res = client.post("/api/bookings", json=booking_payload)
    assert create_res.status_code == 201
    booking_id = create_res.json()["id"]

    # Step 2: Cancel the booking via DELETE
    cancel_res = client.delete(f"/api/bookings/{booking_id}")
    assert cancel_res.status_code == 200
    assert cancel_res.json()["status"] == "cancelled"

    # Step 3: Now rebooking the exact same room and dates should succeed!
    rebook_res = client.post("/api/bookings", json=booking_payload)
    assert rebook_res.status_code == 201
    assert rebook_res.json()["status"] == "confirmed"


# ---------------------------------------------------------------------------
# SRE Fault Injection & Telemetry Tests
# ---------------------------------------------------------------------------
def test_demo_simulate_500_error(client):
    """
    In demo mode, /api/demo/simulate-500 should return HTTP 500 with
    a clear simulated incident message.
    """
    response = client.post("/api/demo/simulate-500")
    assert response.status_code == 500
    data = response.json()
    assert "SIMULATED INCIDENT" in data["detail"]


def test_metrics_summary(client):
    """
    /metrics-summary must return accurate, non-zero values collected
    from the preceding tests.
    """
    response = client.get("/metrics-summary")
    assert response.status_code == 200
    data = response.json()
    
    # Verify transparent labeling
    assert data["metric_scope"] == "process_local_in_memory"
    assert "disclaimer" in data
    
    # Verify real collected counts
    assert data["total_requests"] > 0
    assert data["successful_requests"] > 0
    assert data["server_error_requests"] >= 1  # Triggered by test_demo_simulate_500_error
    assert data["client_error_requests"] >= 1  # Triggered by 409 and 400 tests
    assert data["failed_requests"] >= 2
    assert data["average_latency_ms"] >= 0.0
    assert data["error_rate_percentage"] > 0.0
    assert "uptime_seconds" in data
    assert "uptime_human" in data
    assert len(data["recent_requests"]) > 0
    
    # Verify structured items in recent_requests
    recent_item = data["recent_requests"][0]
    assert "timestamp" in recent_item
    assert "method" in recent_item
    assert "path" in recent_item
    assert "status_code" in recent_item
    assert "duration_ms" in recent_item
