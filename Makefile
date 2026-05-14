.PHONY: up down logs dbt-run dbt-test dbt-docs test lint format clean

# ─── Docker ──────────────────────────────────────────────────────────────────
up:
	docker compose up --build -d

down:
	docker compose down -v

restart:
	docker compose down -v && docker compose up --build -d

logs:
	docker compose logs -f

ps:
	docker compose ps

# ─── dbt ─────────────────────────────────────────────────────────────────────
# dbt is a one-shot container — it runs and exits.
# Use 'run --rm' (fresh container each time) NOT 'exec' (needs running container)
dbt-run:
	docker compose run --rm dbt run --project-dir /app/dbt_project --profiles-dir /app/dbt_project

dbt-test:
	docker compose run --rm --entrypoint sh dbt -c "dbt run --project-dir /app/dbt_project --profiles-dir /app/dbt_project && dbt test --project-dir /app/dbt_project --profiles-dir /app/dbt_project"

dbt-docs:
	docker compose run --rm --no-deps dbt docs generate --project-dir /app/dbt_project --profiles-dir /app/dbt_project
	docker compose run --rm --no-deps dbt docs serve --project-dir /app/dbt_project --profiles-dir /app/dbt_project --port 8080

dbt-clean:
	docker compose run --rm --no-deps dbt clean --profiles-dir /app/dbt_project

# ─── Tests ───────────────────────────────────────────────────────────────────
test:
	docker compose exec api pytest tests/ -v --tb=short

test-local:
	pytest tests/ -v --tb=short

# ─── Code Quality ────────────────────────────────────────────────────────────
lint:
	ruff check ingestion/ config/ jobs/ dashboard/

format:
	ruff format ingestion/ config/ jobs/ dashboard/

# ─── MinIO / Storage ─────────────────────────────────────────────────────────
minio-shell:
	docker compose exec minio sh

create-bucket:
	docker compose exec minio mc alias set local http://localhost:9000 admin minio123 && \
	docker compose exec minio mc mb local/lakehouse --ignore-existing

# ─── Misc ────────────────────────────────────────────────────────────────────
clean:
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; \
	find . -name "*.pyc" -delete; \
	find . -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null; true

help:
	@echo ""
	@echo "  make up            Build and start all services"
	@echo "  make down          Stop and remove containers + volumes"
	@echo "  make logs          Tail all service logs"
	@echo "  make dbt-run       Run dbt models"
	@echo "  make dbt-test      Run dbt tests"
	@echo "  make test          Run pytest inside API container"
	@echo "  make lint          Lint source files with ruff"
	@echo "  make format        Auto-format source files with ruff"
	@echo "  make clean         Remove pycache / compiled artefacts"
	@echo ""
