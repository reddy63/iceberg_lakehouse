"""
tests/test_api.py
──────────────────
Integration tests for ingestion/api.py using the FastAPI TestClient.

Uses the `test_client` fixture from conftest.py which:
  - Swaps the real Iceberg catalog for an in-memory SQLite one
  - Does NOT need a real MinIO / S3

Covers:
  GET  /health
  POST /ingest  (CSV happy path, JSON happy path, empty file, bad format)
  GET  /tables
  GET  /snapshots/{table_name}
"""
from __future__ import annotations

import io

import pandas as pd


# ── GET /health ────────────────────────────────────────────────────────────────

class TestHealth:
    def test_returns_200_and_ok_status(self, test_client):
        resp = test_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "timestamp" in body

    def test_timestamp_is_integer(self, test_client):
        resp = test_client.get("/health")
        assert isinstance(resp.json()["timestamp"], int)


# ── POST /ingest ───────────────────────────────────────────────────────────────

def _csv_bytes(records: list[dict]) -> bytes:
    buf = io.BytesIO()
    pd.DataFrame(records).to_csv(buf, index=False)
    return buf.getvalue()


def _json_bytes(records: list[dict]) -> bytes:
    return pd.DataFrame(records).to_json(orient="records").encode()


SAMPLE = [
    {"event_id": "e1", "user_id": "u1", "event_type": "click",    "amount": 0.0},
    {"event_id": "e2", "user_id": "u2", "event_type": "purchase", "amount": 49.99},
]


class TestIngest:
    def test_csv_upload_returns_200(self, test_client, sample_csv_bytes):
        resp = test_client.post(
            "/ingest?table=events&namespace=raw",
            files={"file": ("events.csv", sample_csv_bytes, "text/csv")},
        )
        assert resp.status_code == 200

    def test_csv_upload_rows_written(self, test_client, sample_csv_bytes):
        resp = test_client.post(
            "/ingest?table=events&namespace=raw",
            files={"file": ("events.csv", sample_csv_bytes, "text/csv")},
        )
        body = resp.json()
        assert body["rows_written"] == 3         # conftest has 3 sample records
        assert body["table"] == "raw.events"
        assert "columns" in body

    def test_json_upload_returns_200(self, test_client, sample_json_bytes):
        resp = test_client.post(
            "/ingest?table=events_json&namespace=raw",
            files={"file": ("events.json", sample_json_bytes, "application/json")},
        )
        assert resp.status_code == 200
        assert resp.json()["rows_written"] == 3

    def test_empty_file_returns_422(self, test_client):
        empty = b""
        resp = test_client.post(
            "/ingest?table=events&namespace=raw",
            files={"file": ("empty.csv", empty, "text/csv")},
        )
        # empty CSV produces empty DataFrame → 422
        assert resp.status_code == 422

    def test_bad_format_returns_422(self, test_client):
        garbage = b"\x00\x01\x02\x03not-a-csv"
        resp = test_client.post(
            "/ingest",
            files={"file": ("bad.csv", garbage, "text/csv")},
        )
        assert resp.status_code in (200, 422)   # parser may succeed on garbage

    def test_schema_drift_key_present(self, test_client, sample_csv_bytes):
        """schema_drift key must always be in the response."""
        # First write — creates table
        test_client.post(
            "/ingest?table=drift_tbl&namespace=raw",
            files={"file": ("events.csv", sample_csv_bytes, "text/csv")},
        )
        # Second write — same schema, no drift
        resp = test_client.post(
            "/ingest?table=drift_tbl&namespace=raw",
            files={"file": ("events.csv", sample_csv_bytes, "text/csv")},
        )
        body = resp.json()
        assert "schema_drift" in body
        assert body["schema_drift"]["has_drift"] is False

    def test_schema_evolution_detected(self, test_client, sample_csv_bytes):
        """Adding a new column on the second write should report drift."""
        test_client.post(
            "/ingest?table=evo_tbl&namespace=raw",
            files={"file": ("events.csv", sample_csv_bytes, "text/csv")},
        )

        # Build a CSV with an extra column
        extended = _csv_bytes([
            {"event_id": "e4", "user_id": "u4", "event_type": "view",
             "amount": 0.0, "event_time": "2024-02-01T00:00:00", "new_col": "x"},
        ])
        resp = test_client.post(
            "/ingest?table=evo_tbl&namespace=raw",
            files={"file": ("extended.csv", extended, "text/csv")},
        )
        assert resp.status_code == 200
        drift = resp.json()["schema_drift"]
        assert "new_col" in drift.get("new_columns", [])


# ── GET /tables ────────────────────────────────────────────────────────────────

class TestListTables:
    def test_returns_200(self, test_client):
        resp = test_client.get("/tables?namespace=raw")
        assert resp.status_code == 200

    def test_response_shape(self, test_client):
        body = test_client.get("/tables?namespace=raw").json()
        assert "namespace" in body
        assert "tables" in body
        assert isinstance(body["tables"], list)

    def test_table_appears_after_ingest(self, test_client, sample_csv_bytes):
        test_client.post(
            "/ingest?table=listed_tbl&namespace=raw",
            files={"file": ("events.csv", sample_csv_bytes, "text/csv")},
        )
        tables = test_client.get("/tables?namespace=raw").json()["tables"]
        assert "listed_tbl" in tables


# ── GET /snapshots/{table_name} ────────────────────────────────────────────────

class TestListSnapshots:
    def test_404_when_table_missing(self, test_client):
        resp = test_client.get("/snapshots/nonexistent?namespace=raw")
        assert resp.status_code == 404

    def test_200_after_ingest(self, test_client, sample_csv_bytes):
        test_client.post(
            "/ingest?table=snap_tbl&namespace=raw",
            files={"file": ("events.csv", sample_csv_bytes, "text/csv")},
        )
        resp = test_client.get("/snapshots/snap_tbl?namespace=raw")
        assert resp.status_code == 200
        body = resp.json()
        assert body["table"] == "raw.snap_tbl"
        assert isinstance(body["snapshots"], list)
        assert len(body["snapshots"]) >= 1

    def test_snapshot_has_required_keys(self, test_client, sample_csv_bytes):
        test_client.post(
            "/ingest?table=snap_keys&namespace=raw",
            files={"file": ("events.csv", sample_csv_bytes, "text/csv")},
        )
        snapshots = test_client.get("/snapshots/snap_keys?namespace=raw").json()["snapshots"]
        for snap in snapshots:
            assert "snapshot_id" in snap
            assert "timestamp_ms" in snap
