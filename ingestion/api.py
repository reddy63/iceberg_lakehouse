"""
ingestion/api.py
────────────────
FastAPI application exposing:
  POST /ingest          – upload CSV or JSON, detect schema, write to Iceberg
  GET  /health          – liveness probe
  GET  /tables          – list all Iceberg tables in the catalog
  GET  /snapshots/{tbl} – list snapshots for time-travel
"""
from __future__ import annotations

import io
import logging
import time
from typing import Annotated

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config.iceberg_config import ensure_namespace, get_catalog
from ingestion.iceberg_writer import write_dataframe
from ingestion.schema_detector import detect_schema, detect_drift

logger = logging.getLogger("ingest_api")
logging.basicConfig(level=logging.INFO)

app = FastAPI(
    title="Iceberg Lakehouse – Ingest API",
    description="Upload CSV/JSON files; schema is auto-detected and evolved in Iceberg.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Startup ────────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup_event() -> None:
    catalog = get_catalog()
    ensure_namespace(catalog, "raw")
    logger.info("Iceberg catalog ready.")


# ── Routes ─────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["ops"])
async def health() -> dict:
    return {"status": "ok", "timestamp": int(time.time())}


@app.post("/ingest", tags=["ingest"])
async def ingest(
    file: Annotated[UploadFile, File(description="CSV or JSON file to ingest")],
    table: str = Query(default="events", description="Target Iceberg table name"),
    namespace: str = Query(default="raw", description="Iceberg namespace"),
) -> JSONResponse:
    """
    Upload a CSV or JSON file. The API will:
    1. Parse the file into a Pandas DataFrame.
    2. Detect (or infer) the Arrow schema.
    3. Detect schema drift vs the existing Iceberg table (if any).
    4. Evolve the table schema automatically for additive changes.
    5. Append the records.
    """
    content_type = file.content_type or ""
    raw_bytes = await file.read()

    # ── Parse ────────────────────────────────────────────────────────────────
    try:
        if "json" in content_type or file.filename.endswith(".json"):
            df = pd.read_json(io.BytesIO(raw_bytes))
        else:
            df = pd.read_csv(io.BytesIO(raw_bytes))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Could not parse file: {exc}") from exc

    if df.empty:
        raise HTTPException(status_code=422, detail="Uploaded file produced an empty DataFrame.")

    # ── Schema detection & drift check ───────────────────────────────────────
    inferred_schema = detect_schema(df)
    catalog = get_catalog()
    full_name = f"{namespace}.{table}"

    drift_report: dict = {}
    if catalog.table_exists(full_name):
        iceberg_table = catalog.load_table(full_name)
        drift_report = detect_drift(iceberg_table.schema(), inferred_schema)

    # ── Write to Iceberg ─────────────────────────────────────────────────────
    rows_written = write_dataframe(
        df=df,
        table_name=table,
        namespace=namespace,
        catalog=catalog,
        inferred_schema=inferred_schema,
    )

    return JSONResponse(
        status_code=200,
        content={
            "table": full_name,
            "rows_written": rows_written,
            "schema_drift": drift_report,
            "columns": list(df.columns),
        },
    )


@app.get("/tables", tags=["catalog"])
async def list_tables(namespace: str = Query(default="raw")) -> dict:
    catalog = get_catalog()
    try:
        tables = [t[1] for t in catalog.list_tables(namespace)]
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"namespace": namespace, "tables": tables}


@app.get("/snapshots/{table_name}", tags=["catalog"])
async def list_snapshots(table_name: str, namespace: str = Query(default="raw")) -> dict:
    catalog = get_catalog()
    full_name = f"{namespace}.{table_name}"
    if not catalog.table_exists(full_name):
        raise HTTPException(status_code=404, detail=f"Table {full_name} not found.")
    tbl = catalog.load_table(full_name)
    snapshots = [
        {"snapshot_id": s.snapshot_id, "timestamp_ms": s.timestamp_ms}
        for s in tbl.history()
    ]
    return {"table": full_name, "snapshots": snapshots}
