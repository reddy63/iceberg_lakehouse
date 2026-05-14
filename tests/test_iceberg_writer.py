"""
tests/test_iceberg_writer.py
─────────────────────────────
Integration-style tests for ingestion/iceberg_writer.py.
Uses an in-memory SQLite catalog (from conftest.mock_catalog).
No real S3 / MinIO required.
"""
from __future__ import annotations

import pandas as pd
import pytest

from ingestion.iceberg_writer import write_dataframe
from ingestion.schema_detector import detect_schema


@pytest.fixture
def base_df() -> pd.DataFrame:
    return pd.DataFrame({
        "event_id":   ["e1", "e2"],
        "user_id":    ["u1", "u2"],
        "event_type": ["click", "purchase"],
        "amount":     [0.0, 49.99],
    })


class TestWriteDataframe:
    def test_creates_table_on_first_write(self, mock_catalog, base_df):
        schema = detect_schema(base_df)
        rows = write_dataframe(base_df, "events", "raw", mock_catalog, schema)
        assert rows == 2
        assert mock_catalog.table_exists("raw.events")

    def test_appends_on_second_write(self, mock_catalog, base_df):
        schema = detect_schema(base_df)
        write_dataframe(base_df, "events", "raw", mock_catalog, schema)
        rows = write_dataframe(base_df, "events", "raw", mock_catalog, schema)
        assert rows == 2  # second batch still returns its own count

    def test_schema_evolution_adds_column(self, mock_catalog, base_df):
        schema_v1 = detect_schema(base_df)
        write_dataframe(base_df, "events", "raw", mock_catalog, schema_v1)

        # Second write adds a new column 'currency'
        df_v2 = base_df.copy()
        df_v2["currency"] = ["USD", "EUR"]
        schema_v2 = detect_schema(df_v2)
        rows = write_dataframe(df_v2, "events", "raw", mock_catalog, schema_v2)

        tbl = mock_catalog.load_table("raw.events")
        col_names = [f.name for f in tbl.schema().fields]
        assert "currency" in col_names
        assert rows == 2

    def test_zero_rows_are_written(self, mock_catalog):
        empty_df = pd.DataFrame({"id": pd.Series([], dtype="int64")})
        schema = detect_schema(empty_df)
        rows = write_dataframe(empty_df, "empty_tbl", "raw", mock_catalog, schema)
        assert rows == 0
