# 🏔️ Iceberg Lakehouse

A **production-grade Data Lakehouse** built on Apache Iceberg, running entirely in Docker.  
Automatically ingests live weather data from [Open-Meteo](https://open-meteo.com/) every 5 minutes,
transforms it with dbt, and visualises it in a Streamlit dashboard — with zero manual steps.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         Docker Network                          │
│                                                                 │
│  Open-Meteo API ──► Scheduler ──► POST /ingest                  │
│  (public, no key)   (every 5 min)      │                        │
│                                        ▼                        │
│  Your CSV/JSON ─────────────────► FastAPI :8000                 │
│                                        │ PyIceberg write        │
│                                        ▼                        │
│                              MinIO :9000/:9001                  │
│                          (S3-compatible, Parquet)               │
│                                        │                        │
│                          ┌─────────────┴──────────┐            │
│                          ▼                         ▼            │
│                    dbt (DuckDB)           Scheduler             │
│                    stg_events             (nightly)             │
│                    fct_events             compaction +          │
│                          │                snapshot expiry       │
│                          ▼                                      │
│                   Streamlit :8501                               │
│                   (Table Browser,                               │
│                    Time Travel,                                  │
│                    dbt Metrics)                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Services

| Service | Port | Technology | Role |
|---|---|---|---|
| `minio` | 9000, 9001 | MinIO | S3-compatible object store for Parquet files |
| `minio-init` | — | MinIO Client (mc) | One-shot: creates the `lakehouse` bucket on startup |
| `postgres` | 5432 | PostgreSQL 16 | Iceberg catalog backend (metadata) |
| `api` | 8000 | FastAPI + PyIceberg | Accepts CSV/JSON, auto-detects schema, writes Iceberg |
| `dbt` | — | dbt-core + dbt-DuckDB | Transforms raw Parquet into analytics marts |
| `dashboard` | 8501 | Streamlit + DuckDB | Interactive data explorer |
| `scheduler` | — | APScheduler | Weather fetch (every 5 min) + compaction (nightly) |

---

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| Docker | 24+ | https://docs.docker.com/engine/install/ |
| Docker Compose | v2 plugin | included with Docker Desktop |
| GNU Make | any | `sudo apt install make` |
| Git | any | `sudo apt install git` |

---

## Quick Start

```bash
# 1. Clone the repository
git clone <your-repo-url>
cd iceberg_lakehouse

# 2. Copy environment config (edit values if needed)
cp .env.example .env

# 3. Build and start all services
make up

# 4. Check everything is running
make ps

# 5. Open the dashboard
open http://localhost:8501
```

> **First run**: The scheduler automatically fetches weather data on startup.  
> Within 30 seconds you should see rows appear in the `raw.weather_events` table.

---

## Service URLs

| Service | URL |
|---|---|
| FastAPI (Swagger UI) | http://localhost:8000/docs |
| FastAPI (health check) | http://localhost:8000/health |
| MinIO web console | http://localhost:9001 (user: `minioadmin`, pass: `minioadmin`) |
| Streamlit dashboard | http://localhost:8501 |

---

## Makefile Commands

```bash
make up           # Build and start all services (detached)
make down         # Stop and remove containers + volumes
make restart      # Full rebuild and restart
make logs         # Tail all service logs
make ps           # Show running containers

make dbt-run      # Run dbt models (stg_events → fct_events)
make dbt-test     # Run dbt data quality tests
make dbt-docs     # Generate + serve dbt docs (port 8080)

make test         # Run pytest inside the API container
make test-local   # Run pytest locally (no Docker)

make lint         # Lint with ruff
make format       # Auto-format with ruff

make create-bucket # Manually create MinIO bucket (done automatically on startup)
make clean        # Remove __pycache__ and compiled artefacts
```

---

## Ingesting Your Own Data

### Upload a CSV file
```bash
curl -X POST "http://localhost:8000/ingest?table=my_table&namespace=raw" \
     -F "file=@/path/to/data.csv"
```

### Upload a JSON file
```bash
curl -X POST "http://localhost:8000/ingest?table=my_table&namespace=raw" \
     -F "file=@/path/to/data.json"
```

### Response
```json
{
  "table": "raw.my_table",
  "rows_written": 1500,
  "schema_drift": {
    "has_drift": false,
    "new_columns": [],
    "removed_columns": [],
    "type_changes": {}
  },
  "columns": ["id", "name", "amount", "created_at"]
}
```

**Schema evolution is automatic** — if your next upload has new columns, they are
added to the Iceberg table non-destructively. Existing data is unaffected.

---

## Automated Weather Ingestion

The `scheduler` service pulls hourly weather forecasts from [Open-Meteo](https://open-meteo.com/)
every **5 minutes** and pushes them to `raw.weather_events`.

### Change the location
Edit `.env`:
```bash
OPEN_METEO_LATITUDE=28.61    # New Delhi
OPEN_METEO_LONGITUDE=77.20
```
Then restart the scheduler:
```bash
docker compose restart scheduler
```

### Change the fetch interval
```bash
FETCH_CRON=*/15 * * * *   # every 15 minutes
```

---

## dbt Transformations

```
raw.weather_events / raw.events
        │
        ▼  (stg_events — VIEW)
    Clean + cast + deduplicate
        │
        ▼  (fct_events — TABLE)
    Daily aggregations per event_type + source:
    total_events, unique_users, total_amount, avg_amount
```

```bash
make dbt-run    # run transformations
make dbt-test   # check not_null, unique, accepted_values constraints
```

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `MINIO_ENDPOINT` | `http://minio:9000` | MinIO S3 API endpoint |
| `MINIO_ACCESS_KEY` | `minioadmin` | MinIO access key |
| `MINIO_SECRET_KEY` | `minioadmin` | MinIO secret key |
| `MINIO_BUCKET` | `lakehouse` | S3 bucket name |
| `CATALOG_URI` | `sqlite:///tmp/iceberg_catalog.db` | Iceberg catalog URI (SQLite or Postgres) |
| `CATALOG_WAREHOUSE` | `s3://lakehouse/warehouse` | Iceberg warehouse root |
| `API_PORT` | `8000` | FastAPI port |
| `STREAMLIT_PORT` | `8501` | Dashboard port |
| `FETCH_CRON` | `*/5 * * * *` | Weather fetch cron expression |
| `FETCH_TARGET_TABLE` | `weather_events` | Iceberg table for weather data |
| `OPEN_METEO_LATITUDE` | `52.52` | Location latitude (Berlin default) |
| `OPEN_METEO_LONGITUDE` | `13.41` | Location longitude (Berlin default) |
| `COMPACTION_CRON` | `0 2 * * *` | Nightly compaction cron |
| `SNAPSHOT_EXPIRY_DAYS` | `7` | Days to retain Iceberg snapshots |

---

## Running Tests

```bash
# All tests (requires dependencies installed)
make test-local

# Inside Docker
make test
```

Test coverage:
- `test_schema_detector.py` — 8 unit tests (type inference, drift detection)
- `test_iceberg_writer.py`  — 4 integration tests (create, append, evolve)
- `test_api.py`             — 13 integration tests (all 4 endpoints)
- `test_fetcher.py`         — 5 unit tests (weather fetch + ingest, mocked)

---

## Project Structure

```
iceberg_lakehouse/
├── .env                      # Local environment config (git-ignored)
├── .env.example              # Template — copy to .env
├── .dockerignore             # Excludes .env, caches, git from Docker builds
├── Makefile                  # Developer commands
├── docker-compose.yml        # All 7 services
├── DEPLOYMENT.md             # EC2 deployment & GitHub Secrets guide
│
├── config/
│   ├── settings.py           # Pydantic-settings: all env var definitions
│   └── iceberg_config.py     # Iceberg SqlCatalog factory (cached singleton)
│
├── docker/
│   ├── Dockerfile.api        # FastAPI service
│   ├── Dockerfile.dbt        # dbt runner
│   ├── Dockerfile.scheduler  # APScheduler (fetch + compaction)
│   └── Dockerfile.streamlit  # Dashboard
│
├── ingestion/
│   ├── api.py                # FastAPI app: /ingest /health /tables /snapshots
│   ├── iceberg_writer.py     # PyIceberg: create table, evolve schema, append
│   ├── schema_detector.py    # Arrow→Iceberg type mapping + drift reports
│   └── fetcher.py            # Open-Meteo API client + POST to /ingest
│
├── jobs/
│   ├── main.py               # Combined scheduler entry-point
│   ├── fetcher_job.py        # APScheduler wrapper for weather fetch
│   └── compaction.py         # Iceberg file compaction + snapshot expiry
│
├── dbt_project/
│   ├── dbt_project.yml
│   ├── profiles.yml          # DuckDB + MinIO S3 connection
│   └── models/
│       ├── staging/
│       │   ├── sources.yml   # Documents raw MinIO data sources
│       │   ├── schema.yml    # Data quality tests for stg_events
│       │   └── stg_events.sql
│       └── marts/
│           ├── schema.yml    # Data quality tests for fct_events
│           └── fct_events.sql
│
├── dashboard/
│   └── app.py                # Streamlit: Table Browser, Time Travel, dbt Metrics
│
├── requirements/
│   ├── api.txt
│   ├── dbt.txt
│   ├── scheduler.txt
│   └── streamlit.txt
│
└── tests/
    ├── conftest.py           # Shared fixtures (mock catalog, test client)
    ├── test_api.py           # FastAPI endpoint tests
    ├── test_iceberg_writer.py
    ├── test_schema_detector.py
    └── test_fetcher.py
```

---

## Deployment to EC2

See [DEPLOYMENT.md](./DEPLOYMENT.md) for:
- Required GitHub Secrets (`EC2_SSH_KEY`, `EC2_HOST`, `EC2_USER`)
- EC2 server setup steps
- How the CI/CD pipeline works
- Manual deployment instructions

---

## License

MIT
