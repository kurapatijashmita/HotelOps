# HotelOps — Running and Troubleshooting

This guide covers the basic checks to use when running HotelOps locally.

## Start the application

From the project folder:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open http://127.0.0.1:8000 in your browser.

## Check whether it is working

Open these URLs:

- `http://127.0.0.1:8000/health` — checks that the application responds.
- `http://127.0.0.1:8000/ready` — checks that the application can access its database.
- `http://127.0.0.1:8000/metrics-summary` — shows collected request measurements.
- `http://127.0.0.1:8000/docs` — shows the API documentation.

A **200** response normally indicates a successful check. A **503** from `/ready` means the application is not ready to handle requests.

## Run the separate monitor

Open a second terminal in the project folder:

```powershell
python monitor.py --interval 3.0
```

The script checks the health endpoints and reports when the service becomes unavailable or recovers.

## Common situations

### The webpage does not open

Check that the server terminal is still running and that the address is `http://127.0.0.1:8000`.
