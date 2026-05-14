"""
ingestion/schema_detector.py
─────────────────────────────
Infer PyArrow / Iceberg schema from a Pandas DataFrame and detect schema drift
between the inferred schema and an existing Iceberg table schema.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import pandas as pd
import pyarrow as pa
from pyiceberg.schema import Schema
from pyiceberg.types import (
    BooleanType,
    DateType,
    DoubleType,
    FloatType,
    IntegerType,
    LongType,
    StringType,
    TimestampType,
    NestedField,
)

logger = logging.getLogger(__name__)

# ── Arrow → Iceberg type mapping ───────────────────────────────────────────────
_ARROW_TO_ICEBERG: dict[str, object] = {
    "int8": IntegerType(),
    "int16": IntegerType(),
    "int32": IntegerType(),
    "int64": LongType(),
    "uint8": IntegerType(),
    "uint16": IntegerType(),
    "uint32": LongType(),
    "uint64": LongType(),
    "float": FloatType(),
    "double": DoubleType(),
    "bool": BooleanType(),
    "boolean": BooleanType(),
    "date32[day]": DateType(),
    "date64[ms]": DateType(),
    "timestamp[us]": TimestampType(),
    "timestamp[ms]": TimestampType(),
    "timestamp[ns]": TimestampType(),
    "timestamp[us, tz=UTC]": TimestampType(),
}


def _arrow_type_to_iceberg(arrow_type: pa.DataType) -> object:
    key = str(arrow_type)
    return _ARROW_TO_ICEBERG.get(key, StringType())


# ── Public API ─────────────────────────────────────────────────────────────────

def detect_schema(df: pd.DataFrame) -> Schema:
    """
    Infer an Iceberg Schema from a Pandas DataFrame.

    Columns with object dtype are attempted to parse as timestamps;
    everything else falls back to StringType.
    """
    arrow_schema = pa.Schema.from_pandas(df, preserve_index=False)
    fields: list[NestedField] = []

    for i, arrow_field in enumerate(arrow_schema, start=1):
        iceberg_type = _arrow_type_to_iceberg(arrow_field.type)
        fields.append(
            NestedField(
                field_id=i,
                name=arrow_field.name,
                field_type=iceberg_type,
                required=False,
            )
        )

    schema = Schema(*fields)
    logger.debug("Detected schema: %s", schema)
    return schema


@dataclass
class DriftReport:
    new_columns: list[str] = field(default_factory=list)
    removed_columns: list[str] = field(default_factory=list)
    type_changes: dict[str, tuple[str, str]] = field(default_factory=dict)  # col → (old, new)

    @property
    def has_drift(self) -> bool:
        return bool(self.new_columns or self.removed_columns or self.type_changes)

    def to_dict(self) -> dict:
        return {
            "has_drift": self.has_drift,
            "new_columns": self.new_columns,
            "removed_columns": self.removed_columns,
            "type_changes": {k: list(v) for k, v in self.type_changes.items()},
        }


def detect_drift(existing_schema: Schema, new_schema: Schema) -> dict:
    """
    Compare existing Iceberg table schema against a freshly inferred schema.

    Returns a serialisable drift report dict.
    """
    existing_cols: dict[str, str] = {f.name: str(f.field_type) for f in existing_schema.fields}
    new_cols: dict[str, str] = {f.name: str(f.field_type) for f in new_schema.fields}

    report = DriftReport(
        new_columns=[c for c in new_cols if c not in existing_cols],
        removed_columns=[c for c in existing_cols if c not in new_cols],
        type_changes={
            col: (existing_cols[col], new_cols[col])
            for col in existing_cols
            if col in new_cols and existing_cols[col] != new_cols[col]
        },
    )

    if report.has_drift:
        logger.warning("Schema drift detected: %s", report)
    else:
        logger.info("No schema drift detected.")

    return report.to_dict()
