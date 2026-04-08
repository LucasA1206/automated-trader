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
    Jobs run in Eastern Time (NYSE market hours).
    """
    from jobs import job_morning_scan_and_buy, job_afternoon_sell

    scheduler = BackgroundScheduler(timezone=ET)

    # 09:20 ET Mon-Fri — market scan + buy orders (40min before open)
    scheduler.add_job(
        func=job_morning_scan_and_buy,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=9,
            minute=20,
            timezone=ET,
        ),
        id="morning_scan_buy",
        name="Morning Scan & Buy",
        replace_existing=True,
        misfire_grace_time=300,  # 5min grace window
    )

    # 15:30 ET Mon-Fri — sell all positions (30min before close)
    scheduler.add_job(
        func=job_afternoon_sell,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=15,
            minute=30,
            timezone=ET,
        ),
        id="afternoon_sell",
        name="Afternoon Sell-All",
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
