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
    from jobs import job_morning_scan_and_buy, job_afternoon_sell, job_snapshot_net_liq

    scheduler = BackgroundScheduler(timezone=ET)

    # 09:30 ET Mon-Fri — morning scan + buy orders (market open)
    # Runs daily: checks how many position slots need filling (e.g. after
    # take-profit or stop-loss exits the previous day) and buys replacements.
    scheduler.add_job(
        func=job_morning_scan_and_buy,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=9,
            minute=30,
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

    # 15:45 ET Mon-Fri — capture end-of-day NetLiquidation snapshot
    # Runs 15 minutes after the sell-all so positions are settled.
    scheduler.add_job(
        func=job_snapshot_net_liq,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=15,
            minute=45,
            timezone=ET,
        ),
        id="snapshot_net_liq",
        name="Daily NetLiq Snapshot",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Monitor Swing Trades (every 5 mins during market hours)
    from jobs import job_monitor_swing_trades
    scheduler.add_job(
        func=job_monitor_swing_trades,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="*/5",
            timezone=ET,
        ),
        id="monitor_swing_trades",
        name="Monitor Swing Trades",
        replace_existing=True,
        misfire_grace_time=60,
        max_instances=1,       # Prevent concurrent runs that can duplicate sells
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
