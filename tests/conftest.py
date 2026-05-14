"""
tests/conftest.py
──────────────────
Shared pytest fixtures for the Iceberg Lakehouse test suite.

Fixtures:
  - sample_csv_df:    a small Pandas DataFrame simulating a CSV upload
  - sample_json_df:   same data from a JSON source
  - mock_catalog:     in-memory SqlCatalog backed by SQLite + moto S3 mock
  - test_client:      FastAPI TestClient with env vars patched
"""
from __future__ import annotations

import io
import os
from typing import Generator

import boto3
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from moto import mock_aws
from pyiceberg.catalog.sql import SqlCatalog

# ── Sample data ───────────────────────────────────────────────────────────────

SAMPLE_RECORDS = [
    {"event_id": "e1", "user_id": "u1", "event_type": "click",    "amount": 0.0,   "event_time": "2024-01-01T10:00:00"},
    {"event_id": "e2", "user_id": "u2", "event_type": "purchase", "amount": 49.99, "event_time": "2024-01-01T11:30:00"},
    {"event_id": "e3", "user_id": "u1", "event_type": "view",     "amount": 0.0,   "event_time": "2024-01-02T09:15:00"},
]


@pytest.fixture
def sample_csv_df() -> pd.DataFrame:
    return pd.DataFrame(SAMPLE_RECORDS)


@pytest.fixture
def sample_json_df() -> pd.DataFrame:
    return pd.DataFrame(SAMPLE_RECORDS)


@pytest.fixture
def sample_csv_bytes() -> bytes:
    df = pd.DataFrame(SAMPLE_RECORDS)
    buf = io.BytesIO()
    df.to_csv(buf, index=False)
    return buf.getvalue()


@pytest.fixture
def sample_json_bytes() -> bytes:
    df = pd.DataFrame(SAMPLE_RECORDS)
    return df.to_json(orient="records").encode()


# ── Mocked MinIO / S3 ─────────────────────────────────────────────────────────

@pytest.fixture
def aws_credentials():
    """Override real AWS creds with moto dummy values."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"


@pytest.fixture
def mock_s3(aws_credentials):
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="lakehouse")
        yield client


# ── In-memory Iceberg catalog (SQLite) ────────────────────────────────────────

@pytest.fixture
def mock_catalog(tmp_path) -> SqlCatalog:
    """SQLite-backed catalog writing to a temp directory (no real S3 needed)."""
    catalog = SqlCatalog(
        "test_catalog",
        **{
            "uri": f"sqlite:///{tmp_path}/test_catalog.db",
            "warehouse": f"file://{tmp_path}/warehouse",
        },
    )
    catalog.create_namespace("raw")
    return catalog


# ── FastAPI test client ────────────────────────────────────────────────────────

@pytest.fixture
def test_client(mock_catalog, monkeypatch) -> Generator[TestClient, None, None]:
    """TestClient with catalog dependency overridden to use the in-memory mock."""
    from config import iceberg_config
    monkeypatch.setattr(iceberg_config, "get_catalog", lambda: mock_catalog)

    from ingestion.api import app
    with TestClient(app) as client:
        yield client
