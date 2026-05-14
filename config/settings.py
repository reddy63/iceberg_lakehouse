"""
config/settings.py
──────────────────
Centralised environment variable loading via pydantic-settings.
All services import `settings` from here; no raw os.getenv() calls elsewhere.
"""
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ── MinIO / S3 ─────────────────────────────────────────────────────────
    minio_endpoint: str = "http://minio:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "lakehouse"

    # ── Iceberg catalog ────────────────────────────────────────────────────
    catalog_name: str = "local"
    catalog_uri: str = "sqlite:///tmp/iceberg_catalog.db"
    catalog_warehouse: str = "s3://lakehouse/warehouse"

    # ── Postgres (optional REST catalog backend) ───────────────────────────
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_db: str = "iceberg_catalog"
    postgres_user: str = "iceberg"
    postgres_password: str = "iceberg"

    # ── API ────────────────────────────────────────────────────────────────
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "info"

    # ── Compaction scheduler ────────────────────────────────────────────────
    compaction_cron: str = "0 2 * * *"
    snapshot_expiry_days: int = 7

    # ── Weather fetcher ───────────────────────────────────────────────────────
    # URL of the FastAPI service as seen from inside Docker (scheduler → api)
    api_url: str = "http://api:8000"
    fetch_cron: str = "*/5 * * * *"     # every 5 minutes
    fetch_target_table: str = "weather_events"
    fetch_namespace: str = "raw"

    # Open-Meteo location (defaults: Berlin, Germany)
    open_meteo_latitude: float = 52.52
    open_meteo_longitude: float = 13.41

    # ── Convenience: s3 endpoint url for boto3 / pyarrow ──────────────────
    @property
    def s3_endpoint_url(self) -> str:
        return self.minio_endpoint

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


@lru_cache
def get_settings() -> Settings:
    """Cached singleton – import and call once per process."""
    return Settings()


# Module-level alias for ergonomic imports:  from config.settings import settings
settings = get_settings()
