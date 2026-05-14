"""
jobs/fetcher_job.py
────────────────────
Thin APScheduler-compatible wrapper around the weather fetcher.

Kept separate from ingestion/fetcher.py so the job layer stays decoupled
from the ingestion logic.
"""
from __future__ import annotations

import logging

from ingestion.fetcher import run_fetch_and_ingest

logger = logging.getLogger("fetcher_job")


def run() -> None:
    """Called by APScheduler every FETCH_CRON interval."""
    logger.info("── Weather fetch job triggered ──")
    run_fetch_and_ingest()
    logger.info("── Weather fetch job complete ──")
