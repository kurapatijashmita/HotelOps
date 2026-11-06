# HotelOps — Hotel Booking and Monitoring System

HotelOps is a small web application that combines hotel room bookings with a dashboard for monitoring how the backend is running. It was built as a learning project to explore Python APIs, databases, HTTP errors, and basic site reliability concepts.

## What it does

- Lists hotel rooms and existing bookings.
- Creates and cancels bookings.
- Checks whether a room is already booked for the requested dates and returns **409 Conflict** when dates overlap.
- Displays recent requests, response times, and HTTP status codes on a dashboard.
- Provides `/health` and `/ready` endpoints for checking the application and database.
- Includes a demo button that intentionally produces an HTTP 500 response for testing error monitoring.
- Includes a separate monitoring script that checks the application's health.

## Technologies

Python, FastAPI, SQLite, HTML, CSS, JavaScript, and pytest.

## How the system works

1. A user or test script sends a request to the FastAPI backend.
2. For bookings, the backend checks the SQLite database for overlapping dates before saving a reservation.
3. The application records request information such as status code and response time.
4. The dashboard displays these measurements so errors and slow requests are easier to spot.

## Run locally

Install Python 3.10 or newer. Open a terminal in the project folder and run:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open **http://127.0.0.1:8000** to view the dashboard.

For interactive API documentation, open **http://127.0.0.1:8000/docs**.

To start the separate health monitor, open another terminal in the same folder:

```powershell
python monitor.py --interval 3.0
```

## Try the features

On the dashboard, you can create a test booking, try an overlapping booking to see a 409 response, check the health probes, or simulate a 500 error. The charts and request history help show how these actions affect the recorded metrics.

The 500-error button is for local testing, not a real production outage.

## Run tests

```powershell
python -m pytest tests/test_api.py -v
python verify_system.py
```

These commands run the included API tests and system verification script. Results depend on your local environment.

## Main files

| File or folder | Purpose |
| --- | --- |
| `app/main.py` | Main FastAPI application |
| `app/database.py` | Database setup and access |
| `app/models.py` | Data models |
| `app/metrics.py` | Request measurements |
| `app/logging_config.py` | Application logging |
| `app/static/` | Dashboard HTML, CSS, and JavaScript |
| `monitor.py` | Separate health-check monitor |
| `tests/` | Automated tests |
| `RUNBOOK.md` | Basic troubleshooting guide |

## Screenshots

Add screenshots of the dashboard here, ideally showing the normal dashboard, a booking conflict, and a simulated server error.

## Limitations

This is a local demonstration project, not a deployed hotel reservation service. It uses SQLite and stores monitoring metrics in memory, so those metrics reset when the server restarts. The simulated error is intended for testing only.

## Project background

The initial implementation was generated with AI development assistance. The repository is being used for hands-on learning, testing, and further improvements to backend development and monitoring.

