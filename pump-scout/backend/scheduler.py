"""
APScheduler setup for automated morning scan jobs.
Runs Monday–Friday at 8:00 AM, 9:30 AM, and 12:00 PM Eastern (UTC offsets).
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from scanner.runner import run_scan
from database import save_scan

logger = logging.getLogger(__name__)

EASTERN_TZ = "America/New_York"

scheduler = AsyncIOScheduler(timezone=EASTERN_TZ)


async def _run_and_save():
    """Run a scan and persist results to the database."""
    try:
        logger.info("Scheduled scan starting...")
        result = await run_scan()
        scan_id = await save_scan(result)
        logger.info(f"Scheduled scan complete — saved as scan #{scan_id}")
    except Exception as e:
        logger.error(f"Scheduled scan failed: {e}", exc_info=True)


def start_scheduler():
    """Register scan jobs and start the scheduler."""

    # 08:00 AM US/Eastern (handles EST/EDT automatically)
    scheduler.add_job(
        _run_and_save,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=8,
            minute=0,
            timezone=EASTERN_TZ,
        ),
        id="scan_0800_est",
        name="Morning Pre-Market Scan (8:00 AM ET)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 09:30 AM US/Eastern (market open)
    scheduler.add_job(
        _run_and_save,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=9,
            minute=30,
            timezone=EASTERN_TZ,
        ),
        id="scan_0930_est",
        name="Market Open Scan (9:30 AM ET)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 12:00 PM US/Eastern (midday)
    scheduler.add_job(
        _run_and_save,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=12,
            minute=0,
            timezone=EASTERN_TZ,
        ),
        id="scan_1200_est",
        name="Midday Scan (12:00 PM ET)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    scheduler.start()
    logger.info("Scheduler started — 3 daily scan jobs registered (8AM, 9:30AM, 12PM ET weekdays)")


def stop_scheduler():
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
