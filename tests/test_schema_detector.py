"""
tests/test_schema_detector.py
──────────────────────────────
Unit tests for ingestion/schema_detector.py
"""
from __future__ import annotations

import pandas as pd
from pyiceberg.types import LongType, StringType, DoubleType, TimestampType

from ingestion.schema_detector import detect_schema, detect_drift


class TestDetectSchema:
    def test_basic_types(self):
        df = pd.DataFrame({
            "id":        [1, 2, 3],
            "name":      ["a", "b", "c"],
            "score":     [1.1, 2.2, 3.3],
        })
        schema = detect_schema(df)
        names = {f.name: f.field_type for f in schema.fields}

        assert isinstance(names["id"],    LongType)
        assert isinstance(names["name"],  StringType)
        assert isinstance(names["score"], DoubleType)

    def test_timestamp_column(self):
        df = pd.DataFrame({
            "event_time": pd.to_datetime(["2024-01-01", "2024-01-02"]),
        })
        schema = detect_schema(df)
        names = {f.name: f.field_type for f in schema.fields}
        assert isinstance(names["event_time"], TimestampType)

    def test_all_string_fallback(self):
        df = pd.DataFrame({"col": ["x", "y", "z"]})
        schema = detect_schema(df)
        assert isinstance(schema.fields[0].field_type, StringType)

    def test_field_ids_are_sequential(self):
        df = pd.DataFrame({"a": [1], "b": [2], "c": [3]})
        schema = detect_schema(df)
        ids = [f.field_id for f in schema.fields]
        assert ids == [1, 2, 3]

    def test_empty_dataframe_raises(self):
        """detect_schema on an empty df should still produce a schema (zero fields or columns)."""
        df = pd.DataFrame()
        schema = detect_schema(df)
        assert len(schema.fields) == 0


class TestDetectDrift:
    def _make_schema(self, columns: dict):
        df = pd.DataFrame({k: [v] for k, v in columns.items()})
        return detect_schema(df)

    def test_no_drift(self):
        s = self._make_schema({"id": 1, "name": "a"})
        report = detect_drift(s, s)
        assert report["has_drift"] is False
        assert report["new_columns"] == []
        assert report["removed_columns"] == []

    def test_new_column_detected(self):
        old = self._make_schema({"id": 1})
        new = self._make_schema({"id": 1, "score": 1.5})
        report = detect_drift(old, new)
        assert report["has_drift"] is True
        assert "score" in report["new_columns"]

    def test_removed_column_detected(self):
        old = self._make_schema({"id": 1, "score": 1.5})
        new = self._make_schema({"id": 1})
        report = detect_drift(old, new)
        assert report["has_drift"] is True
        assert "score" in report["removed_columns"]

    def test_type_change_detected(self):
        old = self._make_schema({"id": 1})          # LongType
        new = self._make_schema({"id": "string"})   # StringType
        report = detect_drift(old, new)
        assert report["has_drift"] is True
        assert "id" in report["type_changes"]
