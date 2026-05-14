"""
dashboard/app.py
────────────────
Streamlit app for the Iceberg Lakehouse.

Tabs:
  1. Table Browser  – list tables, preview rows via DuckDB → Parquet on MinIO
  2. Time Travel    – query any historical snapshot by ID or timestamp
  3. dbt Metrics    – render fct_weather_daily aggregations with Plotly charts
"""
from __future__ import annotations

import os

import duckdb
import pandas as pd
import plotly.express as px
import streamlit as st

# ─── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Iceberg Lakehouse Dashboard",
    page_icon="🏔️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─── MinIO / S3 connection via DuckDB httpfs ───────────────────────────────────
MINIO_ENDPOINT    = os.getenv("MINIO_ENDPOINT", "http://minio:9000").replace("http://", "")
MINIO_ACCESS_KEY  = os.getenv("MINIO_ACCESS_KEY", "minioadmin")
MINIO_SECRET_KEY  = os.getenv("MINIO_SECRET_KEY", "minioadmin")
MINIO_BUCKET      = os.getenv("MINIO_BUCKET", "lakehouse")
WAREHOUSE_PATH    = f"s3://{MINIO_BUCKET}/warehouse"
API_URL           = os.getenv("API_URL", "http://api:8000")


@st.cache_resource
def get_duckdb_conn() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs;")
    con.execute("INSTALL parquet; LOAD parquet;")
    con.execute(f"SET s3_endpoint='{MINIO_ENDPOINT}';")
    con.execute(f"SET s3_access_key_id='{MINIO_ACCESS_KEY}';")
    con.execute(f"SET s3_secret_access_key='{MINIO_SECRET_KEY}';")
    con.execute("SET s3_use_ssl=false;")
    con.execute("SET s3_url_style='path';")
    return con


def query_parquet(namespace: str, table: str, limit: int = 500) -> pd.DataFrame:
    con = get_duckdb_conn()
    path = f"{WAREHOUSE_PATH}/{namespace}.db/{table}/data/*.parquet"
    return con.execute(
        f"SELECT * FROM read_parquet('{path}', union_by_name=true, hive_partitioning=true) LIMIT {limit}"
    ).df()


# ─── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.image("https://iceberg.apache.org/assets/images/iceberg-logo.png", width=180)
    st.title("🏔️ Lakehouse")
    st.markdown("---")
    namespace = st.text_input("Namespace", value="raw")
    table_name = st.text_input("Table", value="weather_events")
    row_limit = st.slider("Row preview limit", 50, 2000, 500, step=50)
    st.markdown("---")
    st.caption("MinIO endpoint: " + MINIO_ENDPOINT)

# ─── Tabs ──────────────────────────────────────────────────────────────────────
tab_browse, tab_timetravel, tab_metrics = st.tabs(
    ["📂 Table Browser", "⏪ Time Travel", "📊 dbt Metrics"]
)

# ── Tab 1: Table Browser ──────────────────────────────────────────────────────
with tab_browse:
    st.header("Table Browser")
    if st.button("🔄 Load Table", key="btn_load"):
        with st.spinner("Reading Parquet files from MinIO…"):
            try:
                df = query_parquet(namespace, table_name, row_limit)
                st.success(f"Loaded {len(df):,} rows × {len(df.columns)} columns")
                st.dataframe(df, use_container_width=True)

                with st.expander("Column types"):
                    st.json({c: str(t) for c, t in zip(df.columns, df.dtypes)})
            except Exception as e:
                st.error(f"Error reading table: {e}")

# ── Tab 2: Time Travel ────────────────────────────────────────────────────────
with tab_timetravel:
    st.header("Time Travel")
    st.info(
        "Fetch snapshots via the Ingest API, then query a specific snapshot's Parquet data.",
        icon="ℹ️",
    )

    import httpx  # lightweight, already in api requirements

    if st.button("Fetch Snapshots", key="btn_snapshots"):
        try:
            resp = httpx.get(f"{API_URL}/snapshots/{table_name}", params={"namespace": namespace}, timeout=10)
            snapshots = resp.json().get("snapshots", [])
            if snapshots:
                st.dataframe(pd.DataFrame(snapshots), use_container_width=True)
            else:
                st.warning("No snapshots found.")
        except Exception as e:
            st.error(f"API unreachable: {e}")

    snapshot_id = st.text_input("Snapshot ID (for manual Parquet path override)", value="")
    if snapshot_id and st.button("Query Snapshot", key="btn_query_snapshot"):
        st.warning("Direct snapshot queries require Iceberg REST catalog support – coming soon.")

# ── Tab 3: dbt Metrics ────────────────────────────────────────────────────────
with tab_metrics:
    st.header("dbt Metrics – fct_weather_daily")

    DBT_DB_PATH = os.getenv("DBT_DB_PATH", "/app/dbt_target/lakehouse_dev.duckdb")

    if st.button("Load Metrics", key="btn_metrics"):
        with st.spinner("Loading fct_weather_daily…"):
            try:
                dbt_con = duckdb.connect(DBT_DB_PATH, read_only=True)
                fct = dbt_con.execute(
                    "SELECT * FROM fct_weather_daily ORDER BY event_date DESC"
                ).df()
                dbt_con.close()

                col1, col2, col3 = st.columns(3)
                col1.metric("Avg Daily Temp", f"{fct['avg_temperature_2m'].mean():.1f} °C")
                col2.metric("Max Wind Speed", f"{fct['max_wind_speed'].max():.1f} km/h")
                col3.metric("Total Precipitation", f"{fct['total_precipitation'].sum():.1f} mm")

                st.subheader("Temperature Highs and Lows")
                fig = px.line(
                    fct.sort_values("event_date"),
                    x="event_date",
                    y=["max_temperature_2m", "min_temperature_2m"],
                    labels={"value": "Temperature (°C)", "variable": "Metric"},
                    template="plotly_dark",
                )
                st.plotly_chart(fig, use_container_width=True)

                st.subheader("Daily Precipitation")
                fig2 = px.bar(
                    fct.sort_values("event_date"),
                    x="event_date",
                    y="total_precipitation",
                    labels={"total_precipitation": "Precipitation (mm)"},
                    template="plotly_dark",
                    color_discrete_sequence=["#1f77b4"]
                )
                st.plotly_chart(fig2, use_container_width=True)

            except Exception as e:
                st.error(f"Could not load fct_weather_daily: {e}")
