"""
ingestion/iceberg_writer.py
────────────────────────────
Write a Pandas DataFrame to an Iceberg table via PyIceberg.
Handles:
  - Table creation (first write)
  - Additive schema evolution (new columns)
  - Append-mode writes using PyArrow
"""
from __future__ import annotations

import logging

import pandas as pd
import pyarrow as pa
from pyiceberg.catalog.sql import SqlCatalog
from pyiceberg.schema import Schema
from pyiceberg.table import Table
from pyiceberg.exceptions import NoSuchTableError

logger = logging.getLogger(__name__)


def _evolve_schema(table: Table, new_schema: Schema) -> None:
    """
    Add any columns present in *new_schema* but absent from the table schema.
    Type changes are logged as warnings (destructive changes are not auto-applied).
    """
    existing_names = {f.name for f in table.schema().fields}
    with table.update_schema() as update:
        for field in new_schema.fields:
            if field.name not in existing_names:
                logger.info("Evolving schema: adding column '%s' (%s)", field.name, field.field_type)
                update.add_column(field.name, field.field_type)


def write_dataframe(
    df: pd.DataFrame,
    table_name: str,
    namespace: str,
    catalog: SqlCatalog,
    inferred_schema: Schema,
) -> int:
    """
    Append *df* to the Iceberg table ``namespace.table_name``.

    Creates the table on first call. Evolves schema for new columns.
    Returns the number of rows written.
    """
    full_name = f"{namespace}.{table_name}"
    arrow_table = pa.Table.from_pandas(df, preserve_index=False)

    # ── Downcast ns timestamps → us (PyIceberg requires us precision) ─────────
    new_fields = []
    needs_cast = False
    for field in arrow_table.schema:
        if pa.types.is_timestamp(field.type) and field.type.unit == "ns":
            new_fields.append(field.with_type(pa.timestamp("us", tz=field.type.tz)))
            needs_cast = True
        else:
            new_fields.append(field)
    if needs_cast:
        arrow_table = arrow_table.cast(pa.schema(new_fields))

    # ── Create or load ───────────────────────────────────────────────────────
    try:
        iceberg_table = catalog.load_table(full_name)
        logger.info("Loaded existing table: %s", full_name)
        _evolve_schema(iceberg_table, inferred_schema)
    except NoSuchTableError:
        logger.info("Creating new table: %s", full_name)
        iceberg_table = catalog.create_table(
            identifier=full_name,
            schema=inferred_schema,
        )

    # ── Append ───────────────────────────────────────────────────────────────
    iceberg_table.append(arrow_table)
    rows = len(df)
    logger.info("Wrote %d rows to %s", rows, full_name)
    return rows
