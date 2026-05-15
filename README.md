<div align="center">

# Iceberg Lakehouse

[![CI/CD](https://github.com/reddy63/iceberg_lakehouse/actions/workflows/deploy.yml/badge.svg)](https://github.com/reddy63/iceberg_lakehouse/actions/workflows/deploy.yml)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white)](https://www.python.org/)
[![PyIceberg](https://img.shields.io/badge/PyIceberg-0.7.0-5C6BC0)](https://py.iceberg.apache.org/)
[![dbt](https://img.shields.io/badge/dbt--duckdb-1.8-FF694B?logo=dbt&logoColor=white)](https://docs.getdbt.com/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Streamlit](https://img.shields.io/badge/Streamlit-dashboard-FF4B4B?logo=streamlit&logoColor=white)](https://streamlit.io/)
[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)

**A production-style open lakehouse pipeline — ingest → store → transform → visualise.**  
Live weather data ingested every 5 minutes, stored as Apache Iceberg tables on MinIO,  
transformed by dbt + DuckDB, and served on a Streamlit dashboard. Deployed to EC2 via GitHub Actions.

</div>

---

## How it works

```
Open-Meteo API (free, no key)
        │  24 hourly rows every 5 min
        ▼
┌─────────────────┐     POST /ingest      ┌──────────────────────────────┐
│   Scheduler     │ ───────────────────►  │  FastAPI  :8000              │
│  (APScheduler)  │                       │  • parse CSV / JSON          │
│  every 5 min    │                       │  • detect schema drift       │
└─────────────────┘                       │  • write to Iceberg (append) │
                                          └──────────────┬───────────────┘
                                                         │ PyIceberg
                                                         ▼
                                          ┌──────────────────────────────┐
                                          │  MinIO  :9000                │
                                          │  s3://lakehouse/warehouse/   │
                                          │  raw.db/weather_events/      │
                                          │  data/*.parquet              │
                                          │  (Apache Iceberg format)     │
                                          └──────────────┬───────────────┘
                                                         │ DuckDB httpfs
                                                         ▼
                                          ┌──────────────────────────────┐
                                          │  dbt  (DuckDB adapter)       │
                                          │  stg_weather  →  VIEW        │
                                          │  fct_weather_daily  →  TABLE │
                                          └──────────────┬───────────────┘
                                                         │
                                                         ▼
                                          ┌──────────────────────────────┐
                                          │  Streamlit  :8501            │
                                          │  • Table Browser (raw rows)  │
                                          │  • dbt Metrics (daily aggs)  │
                                          └──────────────────────────────┘

PostgreSQL  :5432  ── Iceberg SQL catalog (table metadata + snapshot history)
```

---

## Stack

| Layer | Technology | Purpose |
|---|---|---|
| Ingestion API | FastAPI + PyIceberg 0.7.0 | Accepts CSV/JSON, auto-detects schema, writes Iceberg |
| Object store | MinIO (S3-compatible) | Stores Parquet data files + Iceberg metadata |
| Table format | Apache Iceberg | ACID transactions, schema evolution, snapshot history |
| Catalog | PyIceberg SQL catalog → PostgreSQL | Tracks table locations and schema versions |
| Transformation | dbt-duckdb | `stg_weather` (view) → `fct_weather_daily` (daily aggregates) |
| Data source | Open-Meteo API | Free hourly weather — no API key required |
| Scheduler | APScheduler | Fetches weather every 5 min; nightly Iceberg compaction at 02:00 UTC |
| Dashboard | Streamlit + DuckDB | Table browser + daily metric charts |
| CI/CD | GitHub Actions | pytest → deploy to EC2 via rsync + docker compose |
| Tests | pytest, ruff, moto | 34 unit tests; S3 mocked with moto |

---

## Services

| Container | Port | Description |
|---|---|---|
| `ingest_api` | `8000` | FastAPI ingestion service |
| `minio` | `9000` / `9001` | Object store / web console |
| `iceberg_catalog_db` | `5432` | PostgreSQL Iceberg catalog |
| `compaction_scheduler` | — | Weather fetch + nightly compaction |
| `streamlit_dashboard` | `8501` | Streamlit UI |
| `dbt` | — | One-shot dbt run container |
| `minio-init` | — | One-shot MinIO bucket initialisation |

---

## Quickstart

**Prerequisites:** Docker + Docker Compose, Git

```bash
# 1. Clone
git clone https://github.com/reddy63/iceberg_lakehouse.git
cd iceberg_lakehouse

# 2. Configure
cp .env.example .env
# Edit .env — set your MinIO/Postgres passwords,
# and change OPEN_METEO_LATITUDE/LONGITUDE for your city

# 3. Start all 7 services
docker compose up --build -d

# 4. Run dbt transformations
make dbt-run

# 5. Open the dashboard
open http://localhost:8501
```

| Service | URL |
|---|---|
| Streamlit dashboard | http://localhost:8501 |
| FastAPI docs (Swagger) | http://localhost:8000/docs |
| MinIO console | http://localhost:9001 |

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Liveness check |
| `POST` | `/ingest` | Upload CSV or JSON → append to Iceberg table |
| `GET` | `/tables` | List all tables in a namespace (default: `raw`) |
| `GET` | `/snapshots/{table}` | List Iceberg snapshot history (time-travel) |

### Ingest example

```bash
curl -X POST http://localhost:8000/ingest \
  -F 'file=@readings.csv;type=text/csv' \
  -F 'table=sensor_data'
```

```json
{
  "table": "raw.sensor_data",
  "rows_written": 120,
  "schema_drift": {
    "has_drift": false,
    "new_columns": [],
    "removed_columns": [],
    "type_changes": {}
  },
  "columns": ["ts", "device_id", "temp_c", "humidity"]
}
```

---

## dbt Models

```
dbt_project/models/
├── staging/
│   ├── sources.yml            # declares iceberg_raw source
│   ├── schema.yml             # not_null + unique tests
│   └── stg_weather.sql        # VIEW — parses timestamps, deduplicates rows
│                              # (QUALIFY keeps latest fetch per event_ts)
└── marts/
    ├── schema.yml             # not_null tests on fct_weather_daily
    └── fct_weather_daily.sql  # TABLE — daily avg/min/max temp,
                               # humidity, wind speed, precipitation
```

```bash
make dbt-run     # run all models
make dbt-test    # run + test in one step
make dbt-docs    # generate and serve docs on :8080
```

---

## Project structure

```
iceberg_lakehouse/
├── .github/workflows/deploy.yml   # CI: pytest → rsync → EC2 deploy
├── config/
│   ├── iceberg_config.py          # catalog + namespace initialisation
│   └── settings.py                # pydantic-settings env loader
├── dashboard/
│   └── app.py                     # Streamlit UI
├── dbt_project/                   # dbt models, macros, profiles, schema tests
├── docker/
│   ├── Dockerfile.api
│   ├── Dockerfile.dbt
│   ├── Dockerfile.scheduler
│   └── Dockerfile.streamlit
├── ingestion/
│   ├── api.py                     # FastAPI routes
│   ├── fetcher.py                 # Open-Meteo client → POST /ingest
│   ├── iceberg_writer.py          # PyIceberg write + schema evolution
│   └── schema_detector.py        # Arrow schema inference + drift detection
├── jobs/
│   ├── compaction.py              # Iceberg compaction + snapshot expiry
│   ├── fetcher_job.py             # APScheduler wrapper
│   └── main.py                   # Scheduler entrypoint
├── requirements/
│   ├── prod.txt                   # Production deps — installed in Docker images
│   └── test.txt                   # Test deps (moto, pytest, ruff) — CI only
├── tests/                         # 34 pytest tests
├── .env.example                   # Environment variable template
├── docker-compose.yml
├── Makefile
└── DEPLOYMENT.md                  # EC2 setup + GitHub Secrets guide
```

---

## Make commands

```bash
make up           # build and start all services
make down         # stop and remove containers + volumes
make restart      # full rebuild
make logs         # tail all service logs
make dbt-run      # run dbt models
make dbt-test     # run + test dbt models
make test         # pytest inside the API container
make lint         # ruff check
make format       # ruff format
make clean        # remove __pycache__ / .pyc
```

---

## CI/CD

```
push to main
 │
 ├─ Run pytest  (ubuntu-latest)
 │   ├─ Start MinIO + PostgreSQL service containers
 │   ├─ pip install requirements/test.txt
 │   ├─ ruff check
 │   └─ pytest tests/ -v  →  34/34 pass
 │
 └─ Deploy to EC2  (requires pytest pass)
     ├─ rsync project files to EC2
     ├─ Add 2 GB swap  (t2.micro OOM protection)
     ├─ docker compose up --build -d
     └─ GET /health  (12 retries × 15 s)
```

**Required GitHub Secrets:**

| Secret | Description |
|---|---|
| `EC2_SSH_KEY` | Private key (PEM) for your EC2 instance |
| `EC2_HOST` | Public IP or DNS hostname |
| `EC2_USER` | SSH user (`ubuntu` for Ubuntu AMIs) |

See [DEPLOYMENT.md](DEPLOYMENT.md) for full EC2 setup instructions.

---

## License

MIT
