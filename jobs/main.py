"""
jobs/main.py
─────────────
Combined scheduler entry-point for the `scheduler` Docker container.

Runs TWO jobs inside a single APScheduler instance:

  Job 1 — Weather data fetcher   (FETCH_CRON,       default every 5 min)
           Calls Open-Meteo API → POST to FastAPI /ingest → Iceberg on MinIO

  Job 2 — Iceberg compaction     (COMPACTION_CRON,  default daily 02:00 UTC)
           Rewrites small Parquet files + expires old snapshots

Both jobs share the same process so only one container is needed.
"""
from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from config.settings import settings
from jobs.compaction import run_all_jobs as run_compaction
from jobs.fetcher_job import run as run_fetch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
)
logger = logging.getLogger("scheduler_main")


def main() -> None:
    logger.info("══════════════════════════════════════════")
    logger.info("  Iceberg Lakehouse Scheduler starting…  ")
    logger.info("══════════════════════════════════════════")
    logger.info("Fetch cron      : %s  (table: %s.%s)",
                settings.fetch_cron,
                settings.fetch_namespace,
                settings.fetch_target_table)
    logger.info("Compaction cron : %s", settings.compaction_cron)

    scheduler = BlockingScheduler(timezone="UTC")

    # ── Job 1: weather fetcher ──────────────────────────────────────────────
    scheduler.add_job(
        run_fetch,
        CronTrigger.from_crontab(settings.fetch_cron),
        id="weather_fetcher",
        replace_existing=True,
        max_instances=1,          # don't overlap if a fetch takes longer than 5 min
        misfire_grace_time=60,
    )

    # ── Job 2: nightly compaction + snapshot expiry ─────────────────────────
    scheduler.add_job(
        run_compaction,
        CronTrigger.from_crontab(settings.compaction_cron),
        id="nightly_compaction",
        replace_existing=True,
        max_instances=1,
        misfire_grace_time=300,
    )

    # Run the fetcher ONCE immediately on startup so data is available right away
    logger.info("Running initial weather fetch on startup…")
    try:
        run_fetch()
    except Exception:
        logger.exception("Startup fetch failed — scheduler will still continue.")

    logger.info("Scheduler running. Next triggers:")
    for job in scheduler.get_jobs():
        logger.info("  [%s] scheduled: %s", job.id, job)

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
