"""
ingestion/fetcher.py
─────────────────────
Pulls hourly weather data from the Open-Meteo public API (no API key required)
and POSTs it as a CSV to the FastAPI /ingest endpoint.

Open-Meteo docs: https://open-meteo.com/en/docs

Data shape (one row per hourly slot for the next 24 hours):
  event_time, temperature_2m, relative_humidity_2m, wind_speed_10m,
  precipitation, weather_code, surface_pressure,
  latitude, longitude, timezone, fetched_at
"""
from __future__ import annotations

import io
import logging
from datetime import datetime, timezone

import httpx
import pandas as pd

from config.settings import settings

logger = logging.getLogger(__name__)

# ── Open-Meteo configuration ──────────────────────────────────────────────────

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

HOURLY_VARIABLES = [
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "precipitation",
    "weather_code",
    "surface_pressure",
]


# ── Core logic ────────────────────────────────────────────────────────────────

def fetch_weather() -> pd.DataFrame:
    """
    Call the Open-Meteo forecast API and return a tidy DataFrame.
    One row per hourly timestamp for the next 24 hours.
    """
    params = {
        "latitude": settings.open_meteo_latitude,
        "longitude": settings.open_meteo_longitude,
        "hourly": ",".join(HOURLY_VARIABLES),
        "timezone": "UTC",
        "forecast_days": 1,   # keep each run small (24 rows)
    }

    logger.info(
        "Fetching Open-Meteo data — lat=%.4f lon=%.4f",
        settings.open_meteo_latitude,
        settings.open_meteo_longitude,
    )

    with httpx.Client(timeout=30) as client:
        resp = client.get(OPEN_METEO_URL, params=params)
        resp.raise_for_status()

    data = resp.json()
    hourly = data["hourly"]

    df = pd.DataFrame(hourly)
    df.rename(columns={"time": "event_time"}, inplace=True)

    # Attach location + run metadata so every row is self-describing
    df["latitude"]   = data["latitude"]
    df["longitude"]  = data["longitude"]
    df["timezone"]   = data.get("timezone", "UTC")
    df["fetched_at"] = datetime.now(tz=timezone.utc).isoformat()

    logger.info("Fetched %d rows from Open-Meteo.", len(df))
    return df


def post_to_ingest(df: pd.DataFrame) -> dict:
    """
    Serialize *df* to CSV and POST it to the local FastAPI /ingest endpoint.

    Returns the JSON response body from the API (rows_written, schema_drift, …).
    """
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    csv_bytes = buf.getvalue()

    url = (
        f"{settings.api_url}/ingest"
        f"?table={settings.fetch_target_table}"
        f"&namespace={settings.fetch_namespace}"
    )

    logger.info("POSTing %d rows → %s", len(df), url)

    with httpx.Client(timeout=60) as client:
        resp = client.post(
            url,
            files={"file": ("weather.csv", csv_bytes, "text/csv")},
        )
        resp.raise_for_status()

    result = resp.json()
    logger.info(
        "Ingest OK — rows_written=%d  drift=%s",
        result.get("rows_written", 0),
        result.get("schema_drift", {}),
    )
    return result


def run_fetch_and_ingest() -> None:
    """
    High-level entry point called by the APScheduler job.
    Fetches weather data and pushes it into Iceberg via the ingest API.
    Errors are logged but not re-raised so the scheduler keeps running.
    """
    try:
        df = fetch_weather()
        post_to_ingest(df)
    except httpx.HTTPStatusError as exc:
        logger.error(
            "HTTP error during fetch/ingest: %s — response: %s",
            exc,
            exc.response.text[:200],
        )
    except httpx.RequestError as exc:
        logger.error("Network error during fetch/ingest: %s", exc)
    except Exception:
        logger.exception("Unexpected error in run_fetch_and_ingest.")
