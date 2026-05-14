"""
jobs/compaction.py
───────────────────
APScheduler-driven job that runs nightly to:
  1. Merge (compact) small Parquet files in each Iceberg table.
  2. Expire old snapshots beyond the configured retention window.

Run standalone:  python -m jobs.compaction
Docker CMD:      python -m jobs.compaction
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config.iceberg_config import get_catalog
from config.settings import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
logger = logging.getLogger("compaction")


# ── Core job logic ────────────────────────────────────────────────────────────

def compact_table(namespace: str, table_name: str) -> None:
    """Rewrite small files for a single table (bin-packing compaction)."""
    catalog = get_catalog()
    full_name = f"{namespace}.{table_name}"

    if not catalog.table_exists(full_name):
        logger.warning("Table %s does not exist – skipping compaction.", full_name)
        return

    table = catalog.load_table(full_name)
    logger.info("Starting compaction for %s …", full_name)

    # PyIceberg ≥0.7 exposes table.rewrite_data_files()
    result = table.rewrite_data_files()
    logger.info(
        "Compaction complete for %s: %d files rewritten.", full_name, result.rewritten_files_count
    )


def expire_snapshots(namespace: str, table_name: str) -> None:
    """Remove snapshots older than SNAPSHOT_EXPIRY_DAYS."""
    catalog = get_catalog()
    full_name = f"{namespace}.{table_name}"

    if not catalog.table_exists(full_name):
        return

    table = catalog.load_table(full_name)
    expiry_ts = datetime.now(tz=timezone.utc) - timedelta(days=settings.snapshot_expiry_days)
    expiry_ms = int(expiry_ts.timestamp() * 1000)

    logger.info(
        "Expiring snapshots older than %s for %s …",
        expiry_ts.isoformat(),
        full_name,
    )
    table.expire_snapshots().expire_older_than(expiry_ms).commit()
    logger.info("Snapshot expiry committed for %s.", full_name)


def run_all_jobs() -> None:
    """Iterate every table in every namespace and run compaction + expiry."""
    catalog = get_catalog()
    namespaces = [ns[0] for ns in catalog.list_namespaces()]

    for namespace in namespaces:
        tables = [t[1] for t in catalog.list_tables(namespace)]
        for table_name in tables:
            try:
                compact_table(namespace, table_name)
                expire_snapshots(namespace, table_name)
            except Exception:
                logger.exception("Job failed for %s.%s", namespace, table_name)


# ── Scheduler entry-point ─────────────────────────────────────────────────────

def main() -> None:
    logger.info("Compaction scheduler starting up…")
    logger.info("Cron schedule: %s", settings.compaction_cron)
    logger.info("Snapshot expiry window: %d days", settings.snapshot_expiry_days)

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        run_all_jobs,
        CronTrigger.from_crontab(settings.compaction_cron),
        id="nightly_compaction",
        replace_existing=True,
    )

    # Also run immediately on startup for convenience
    logger.info("Running initial compaction pass on startup…")
    try:
        run_all_jobs()
    except Exception:
        logger.exception("Startup compaction pass failed – scheduler will still proceed.")

    logger.info("Scheduler started. Waiting for next trigger…")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
