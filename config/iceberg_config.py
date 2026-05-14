"""
config/iceberg_config.py
────────────────────────
Build and return a PyIceberg SqlCatalog (or REST catalog) configured from env.
Centralised here so every service gets an identical catalog object.
"""
from __future__ import annotations

import logging
from functools import lru_cache

from pyiceberg.catalog.sql import SqlCatalog

from config.settings import settings

logger = logging.getLogger(__name__)


def _s3_properties() -> dict[str, str]:
    """Common S3 / MinIO connection properties for PyIceberg."""
    return {
        "s3.endpoint": settings.minio_endpoint,
        "s3.access-key-id": settings.minio_access_key,
        "s3.secret-access-key": settings.minio_secret_key,
        "s3.path-style-access": "true",  # required for MinIO
    }


@lru_cache
def get_catalog() -> SqlCatalog:
    """
    Return a cached PyIceberg SqlCatalog backed by SQLite (local dev) or
    Postgres (staging / prod) depending on CATALOG_URI in .env.
    """
    props = {
        "uri": settings.catalog_uri,
        "warehouse": settings.catalog_warehouse,
        **_s3_properties(),
    }
    logger.info("Connecting to Iceberg catalog at %s", settings.catalog_uri)
    catalog = SqlCatalog(settings.catalog_name, **props)
    return catalog


# ── Namespace helpers ─────────────────────────────────────────────────────────

def ensure_namespace(catalog: SqlCatalog, namespace: str = "raw") -> None:
    """Create namespace if it doesn't exist (idempotent)."""
    existing = [ns[0] for ns in catalog.list_namespaces()]
    if namespace not in existing:
        catalog.create_namespace(namespace)
        logger.info("Created namespace: %s", namespace)
