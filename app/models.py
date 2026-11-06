"""Pydantic models and schemas for HotelOps."""

from __future__ import annotations

from typing import List, Dict, Optional
from pydantic import BaseModel, Field, EmailStr


class RoomResponse(BaseModel):
    id: int
    room_number: str
    room_type: str
    price_per_night: float
    capacity: int


class BookingCreate(BaseModel):
    room_id: int = Field(..., description="ID of the room to book")
    guest_name: str = Field(..., min_length=2, max_length=100, description="Full name of guest")
    guest_email: str = Field(..., min_length=5, max_length=120, description="Contact email of guest")
    check_in: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Check-in date (YYYY-MM-DD)")
    check_out: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$", description="Check-out date (YYYY-MM-DD)")


class BookingResponse(BaseModel):
    id: int
    booking_reference: str
    room_id: int
    room_number: Optional[str] = None
    room_type: Optional[str] = None
    guest_name: str
    guest_email: str
    check_in: str
    check_out: str
    status: str
    created_at: str


class CancelResponse(BaseModel):
    id: int
    booking_reference: str
    status: str
    message: str


class HealthResponse(BaseModel):
    status: str
    timestamp: str
    service: str
    version: str


class ReadyResponse(BaseModel):
    status: str
    database: str
    timestamp: str


class RequestLogItem(BaseModel):
    timestamp: str
    method: str
    path: str
    status_code: int
    duration_ms: float
    client_ip: Optional[str] = None


class MetricsSummaryResponse(BaseModel):
    metric_scope: str = Field(
        default="process_local_in_memory",
        description="Scope of these metrics. In-memory to the running worker process; resets upon process restart."
    )
    disclaimer: str = Field(
        default="Process-local metrics collected since startup. Does not represent multi-node or persistent historical SLA/uptime.",
        description="Engineering transparency note"
    )
    service: str
    version: str
    uptime_seconds: float
    uptime_human: str
    total_requests: int
    successful_requests: int
    client_error_requests: int
    server_error_requests: int
    failed_requests: int
    average_latency_ms: float
    p95_latency_ms: float
    error_rate_percentage: float
    status_codes: Dict[str, int]
    recent_requests: List[RequestLogItem]
    collected_at: str
