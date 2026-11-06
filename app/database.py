"""Database layer for HotelOps.

Provides SQLite initialization, connection management, schema migrations,
seed data, and transactional validation for hotel room bookings to prevent
race conditions and overlapping dates.
"""

from __future__ import annotations

import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Generator, List, Optional, Dict, Any

# Default database location in the project root or configured via env var
DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent / "hotelops.db"
DB_PATH = Path(os.environ.get("HOTELOPS_DB_PATH", str(DEFAULT_DB_PATH)))


class BookingConflictError(Exception):
    """Raised when an attempt is made to book an already occupied room."""
    pass


class ResourceNotFoundError(Exception):
    """Raised when a requested room or booking does not exist."""
    pass


class ValidationError(Exception):
    """Raised when booking dates or parameters are invalid."""
    pass


def get_db_path() -> Path:
    """Return the current active database path."""
    return DB_PATH


@contextmanager
def get_connection(timeout: float = 10.0) -> Generator[sqlite3.Connection, None, None]:
    """Provide a transactional SQLite database connection with row factory."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=timeout)
    conn.row_factory = sqlite3.Row
    # Enforce foreign keys in SQLite
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
    finally:
        conn.close()


def initialize_database() -> None:
    """Create database tables if they do not exist and seed initial rooms."""
    with get_connection() as conn:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rooms (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_number TEXT UNIQUE NOT NULL,
                    room_type TEXT NOT NULL,
                    price_per_night REAL NOT NULL,
                    capacity INTEGER NOT NULL
                );
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS bookings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    booking_reference TEXT UNIQUE NOT NULL,
                    room_id INTEGER NOT NULL REFERENCES rooms(id),
                    guest_name TEXT NOT NULL,
                    guest_email TEXT NOT NULL,
                    check_in TEXT NOT NULL,
                    check_out TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'confirmed',
                    created_at TEXT NOT NULL
                );
                """
            )
            # Create index for fast conflict checking on room_id and dates
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bookings_conflict 
                ON bookings(room_id, status, check_in, check_out);
                """
            )

        # Seed initial hotel rooms if table is empty
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) AS count FROM rooms;")
        row = cursor.fetchone()
        if row and row["count"] == 0:
            initial_rooms = [
                ("101", "Standard King", 149.00, 2),
                ("102", "Deluxe Double", 179.00, 4),
                ("201", "Ocean View Suite", 249.00, 2),
                ("202", "Executive Suite", 319.00, 4),
                ("301", "Presidential Penthouse", 599.00, 6),
            ]
            with conn:
                conn.executemany(
                    """
                    INSERT INTO rooms (room_number, room_type, price_per_night, capacity)
                    VALUES (?, ?, ?, ?);
                    """,
                    initial_rooms,
                )


def check_database_readiness() -> bool:
    """Execute a simple query to verify database connectivity for readiness probe."""
    try:
        with get_connection(timeout=2.0) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1;")
            result = cursor.fetchone()
            return result is not None and result[0] == 1
    except Exception:
        return False


def get_all_rooms() -> List[Dict[str, Any]]:
    """Fetch all available hotel rooms."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, room_number, room_type, price_per_night, capacity
            FROM rooms
            ORDER BY room_number ASC;
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def get_room_by_id(room_id: int) -> Optional[Dict[str, Any]]:
    """Fetch a single room by primary key."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, room_number, room_type, price_per_night, capacity FROM rooms WHERE id = ?;",
            (room_id,),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def get_all_bookings() -> List[Dict[str, Any]]:
    """Fetch all bookings ordered by creation date descending."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT b.id, b.booking_reference, b.room_id, r.room_number, r.room_type,
                   b.guest_name, b.guest_email, b.check_in, b.check_out, b.status, b.created_at
            FROM bookings b
            JOIN rooms r ON b.room_id = r.id
            ORDER BY b.id DESC;
            """
        )
        return [dict(row) for row in cursor.fetchall()]


def create_booking_transaction(
    room_id: int,
    guest_name: str,
    guest_email: str,
    check_in: str,
    check_out: str,
) -> Dict[str, Any]:
    """
    Create a booking within an immediate SQLite transaction.
    
    Prevents overlapping bookings for the same room.
    Two date intervals [A_start, A_end) and [B_start, B_end) overlap if:
      A_start < B_end AND B_start < A_end
    """
    # Basic date order check
    if check_in >= check_out:
        raise ValidationError("check_out date must be strictly after check_in date.")

    # Validate ISO date format YYYY-MM-DD
    try:
        datetime.strptime(check_in, "%Y-%m-%d")
        datetime.strptime(check_out, "%Y-%m-%d")
    except ValueError:
        raise ValidationError("Dates must be in YYYY-MM-DD format.")

    with get_connection() as conn:
        # Use BEGIN IMMEDIATE to acquire a write lock upfront and avoid race conditions
        conn.execute("BEGIN IMMEDIATE;")
        cursor = conn.cursor()

        # Check room exists
        cursor.execute("SELECT id, room_number FROM rooms WHERE id = ?;", (room_id,))
        room = cursor.fetchone()
        if not room:
            conn.rollback()
            raise ResourceNotFoundError(f"Room with id {room_id} not found.")

        # Check for overlapping active bookings
        cursor.execute(
            """
            SELECT id, booking_reference, check_in, check_out
            FROM bookings
            WHERE room_id = ?
              AND status = 'confirmed'
              AND check_in < ?
              AND check_out > ?;
            """,
            (room_id, check_out, check_in),
        )
        conflicts = cursor.fetchall()
        if conflicts:
            conn.rollback()
            conflict_ref = conflicts[0]["booking_reference"]
            raise BookingConflictError(
                f"Room {room['room_number']} is already booked from "
                f"{conflicts[0]['check_in']} to {conflicts[0]['check_out']} "
                f"(Conflict Ref: {conflict_ref})."
            )

        # Generate unique booking reference
        booking_ref = f"HOTEL-{uuid.uuid4().hex[:8].upper()}"
        created_at = datetime.now(timezone.utc).isoformat()

        cursor.execute(
            """
            INSERT INTO bookings (
                booking_reference, room_id, guest_name, guest_email, check_in, check_out, status, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'confirmed', ?);
            """,
            (booking_ref, room_id, guest_name, guest_email, check_in, check_out, created_at),
        )
        new_id = cursor.lastrowid
        conn.commit()

        return {
            "id": new_id,
            "booking_reference": booking_ref,
            "room_id": room_id,
            "room_number": room["room_number"],
            "guest_name": guest_name,
            "guest_email": guest_email,
            "check_in": check_in,
            "check_out": check_out,
            "status": "confirmed",
            "created_at": created_at,
        }


def cancel_booking(booking_id: int) -> Dict[str, Any]:
    """Cancel an active booking."""
    with get_connection() as conn:
        with conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, status, booking_reference FROM bookings WHERE id = ?;", (booking_id,))
            booking = cursor.fetchone()
            if not booking:
                raise ResourceNotFoundError(f"Booking with id {booking_id} not found.")
            if booking["status"] == "cancelled":
                return {
                    "id": booking["id"],
                    "booking_reference": booking["booking_reference"],
                    "status": "cancelled",
                    "message": "Booking is already cancelled.",
                }
            cursor.execute(
                "UPDATE bookings SET status = 'cancelled' WHERE id = ?;",
                (booking_id,),
            )
            return {
                "id": booking["id"],
                "booking_reference": booking["booking_reference"],
                "status": "cancelled",
                "message": "Booking successfully cancelled.",
            }
