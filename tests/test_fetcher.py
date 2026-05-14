"""
tests/test_fetcher.py
──────────────────────
Unit tests for ingestion/fetcher.py.

Uses httpx mock transport so no real network calls are made.
"""
from __future__ import annotations


import httpx
import pandas as pd
import pytest

from ingestion.fetcher import fetch_weather, post_to_ingest, run_fetch_and_ingest


# ── Helpers ───────────────────────────────────────────────────────────────────

FAKE_OPEN_METEO_RESPONSE = {
    "latitude": 52.52,
    "longitude": 13.41,
    "timezone": "UTC",
    "hourly": {
        "time": ["2024-01-01T00:00", "2024-01-01T01:00"],
        "temperature_2m": [2.1, 1.8],
        "relative_humidity_2m": [85, 88],
        "wind_speed_10m": [5.2, 4.9],
        "precipitation": [0.0, 0.1],
        "weather_code": [1, 2],
        "surface_pressure": [1013.0, 1012.5],
    },
}

FAKE_INGEST_RESPONSE = {
    "table": "raw.weather_events",
    "rows_written": 2,
    "schema_drift": {"has_drift": False},
    "columns": ["event_time", "temperature_2m"],
}


def _mock_response(status: int, **kwargs) -> httpx.Response:
    """Build an httpx.Response with a synthetic request attached.

    httpx.Response.raise_for_status() requires response.request to be set;
    responses created outside a real transport don't have it by default.
    """
    resp = httpx.Response(status, **kwargs)
    resp.request = httpx.Request("GET", "http://mock")
    return resp


# ── Tests: fetch_weather ───────────────────────────────────────────────────────

class TestFetchWeather:
    def test_returns_dataframe_with_correct_columns(self, monkeypatch):
        """fetch_weather() should return a tidy DataFrame with all expected columns."""

        def fake_get(self, *args, **kwargs):
            return _mock_response(200, json=FAKE_OPEN_METEO_RESPONSE)

        monkeypatch.setattr(httpx.Client, "get", fake_get)

        df = fetch_weather()

        assert isinstance(df, pd.DataFrame)
        assert len(df) == 2
        assert "event_time" in df.columns
        assert "temperature_2m" in df.columns
        assert "fetched_at" in df.columns
        assert "latitude" in df.columns

    def test_raises_on_http_error(self, monkeypatch):
        """fetch_weather() should propagate HTTP errors for the caller to handle."""

        def fake_get(self, *args, **kwargs):
            return _mock_response(500, text="Internal Server Error")

        monkeypatch.setattr(httpx.Client, "get", fake_get)

        with pytest.raises(httpx.HTTPStatusError):
            fetch_weather()


# ── Tests: post_to_ingest ─────────────────────────────────────────────────────

class TestPostToIngest:
    def test_posts_csv_and_returns_result(self, monkeypatch):
        """post_to_ingest() should POST CSV bytes and return the parsed JSON."""

        def fake_post(self, *args, **kwargs):
            return _mock_response(200, json=FAKE_INGEST_RESPONSE)

        monkeypatch.setattr(httpx.Client, "post", fake_post)

        df = pd.DataFrame(FAKE_OPEN_METEO_RESPONSE["hourly"])
        result = post_to_ingest(df)

        assert result["rows_written"] == 2
        assert result["table"] == "raw.weather_events"

    def test_raises_on_api_error(self, monkeypatch):
        """post_to_ingest() should propagate API errors."""

        def fake_post(self, *args, **kwargs):
            return _mock_response(422, json={"detail": "bad request"})

        monkeypatch.setattr(httpx.Client, "post", fake_post)

        df = pd.DataFrame({"col": [1, 2]})
        with pytest.raises(httpx.HTTPStatusError):
            post_to_ingest(df)


# ── Tests: run_fetch_and_ingest ───────────────────────────────────────────────

class TestRunFetchAndIngest:
    def test_swallows_network_errors(self, monkeypatch):
        """run_fetch_and_ingest() should not raise — errors are only logged."""

        def boom(self, *args, **kwargs):
            raise httpx.ConnectError("unreachable")

        monkeypatch.setattr(httpx.Client, "get", boom)

        # Should not raise
        run_fetch_and_ingest()

    def test_full_happy_path(self, monkeypatch):
        """run_fetch_and_ingest() calls fetch then post without error."""
        calls = []

        def fake_fetch():
            calls.append("fetch")
            return pd.DataFrame({"event_time": ["2024-01-01T00:00"]})

        def fake_post(df):
            calls.append("post")
            return FAKE_INGEST_RESPONSE

        monkeypatch.setattr("ingestion.fetcher.fetch_weather", fake_fetch)
        monkeypatch.setattr("ingestion.fetcher.post_to_ingest", fake_post)

        run_fetch_and_ingest()
        assert calls == ["fetch", "post"]
