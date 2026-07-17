"""
scheduler.py — APScheduler configuration for the systematic trading strategy.

Schedule (all times Eastern, Mon-Fri only):
  06:30  pre_market_scan  — full pipeline: universe → filter → score → AI → candidates staged
  09:30  exit_monitor     — check all open positions against exit rules (runs until 16:00)
  09:45  entry_monitor    — place orders for confirmed candidates (runs until 15:30)
  15:45  eod_snapshot     — capture daily NetLiquidation snapshot

Exit monitor starts at 09:30 (market open) to catch any gaps or overnight events.
Entry monitor starts at 09:45 (15-min after open) — never in the first 15 minutes.
"""

import logging
import os
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

logger = logging.getLogger(__name__)

ET = pytz.timezone("America/New_York")


def create_scheduler() -> BackgroundScheduler:
    """
    Creates and configures the APScheduler instance.
    All jobs run in Eastern Time (NYSE market hours).
    """
    from jobs import (
        job_pre_market_scan,
        job_entry_monitor,
        job_exit_monitor,
        job_eod_snapshot,
    )

    scheduler = BackgroundScheduler(timezone=ET)

    # 06:30 ET Mon-Fri — full pre-market scan
    # Runs BEFORE market open to identify candidates. No orders placed here.
    # Started at 06:30 to allow 3 hours before open (scan takes 2+ hours).
    scheduler.add_job(
        func=job_pre_market_scan,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=6,
            minute=30,
            timezone=ET,
        ),
        id="pre_market_scan",
        name="Pre-Market Scan (06:30 ET)",
        replace_existing=True,
        misfire_grace_time=600,   # 10 min grace — scan is long-running
        max_instances=1,
    )

    # 09:30–16:00 ET, every 5 min, Mon-Fri — exit monitor
    # Starts at market open to catch any immediate exits (gaps, overnight events).
    scheduler.add_job(
        func=job_exit_monitor,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="*/5",
            timezone=ET,
        ),
        id="exit_monitor",
        name="Exit Monitor (every 5 min)",
        replace_existing=True,
        misfire_grace_time=60,
        max_instances=1,          # Prevent concurrent runs (idempotent sell guards)
    )

    # 09:45–15:30 ET, every 5 min, Mon-Fri — entry monitor
    # Avoids first 15 min of trading (blueprint Section 8 time gate).
    # Stops at 15:30 to avoid entries 30 min before close.
    scheduler.add_job(
        func=job_entry_monitor,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="*/5",
            timezone=ET,
        ),
        id="entry_monitor",
        name="Entry Monitor (every 5 min)",
        replace_existing=True,
        misfire_grace_time=60,
        max_instances=1,
    )

    # 15:45 ET Mon-Fri — EOD NetLiquidation snapshot
    # Runs after market close — 15 min after the last exit monitor tick.
    scheduler.add_job(
        func=job_eod_snapshot,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=15,
            minute=45,
            timezone=ET,
        ),
        id="eod_snapshot",
        name="EOD NetLiq Snapshot (15:45 ET)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    return scheduler


def get_next_job_times(scheduler: BackgroundScheduler) -> list[dict]:
    """Returns a list of scheduled jobs and their next run times."""
    result = []
    for job in scheduler.get_jobs():
        result.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
        })
    return result
