"""
APScheduler setup for automated morning scan jobs.
Runs Monday–Friday at 8:00 AM, 9:30 AM, and 12:00 PM Eastern (UTC offsets).
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from scanner.runner import run_scan
from database import save_scan
from hype_monitor.monitor import run_hype_monitor
from journal_autoclose import auto_close_journal
from ai_portfolio import ai_portfolio_decisions, generate_daily_report
from scan_candidates import fill_candidate_prices
from eod_log import run_eod_log

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


async def _run_hype_monitor():
    """Run one hype monitor cycle."""
    try:
        logger.info("Hype monitor starting...")
        await run_hype_monitor()
    except Exception as e:
        logger.error(f"Hype monitor failed: {e}", exc_info=True)


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

    # Hype monitor: every 30 min, Mon–Fri, 08:00–17:00 ET
    scheduler.add_job(
        _run_hype_monitor,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="8-16",
            minute="0,30",
            timezone=EASTERN_TZ,
        ),
        id="hype_monitor_30min",
        name="Hype Monitor (every 30min, market hours)",
        replace_existing=True,
        misfire_grace_time=120,
    )

    # 09:00 AM ET — AI Portfolio decisions
    scheduler.add_job(
        ai_portfolio_decisions,
        trigger=CronTrigger(
            day_of_week="mon-fri", hour=9, minute=0, timezone=EASTERN_TZ,
        ),
        id="ai_portfolio_decisions",
        name="AI Portfolio Decisions (9:00 AM ET)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 16:05 ET — Auto-close journal entries
    scheduler.add_job(
        auto_close_journal,
        trigger=CronTrigger(
            day_of_week="mon-fri", hour=16, minute=5, timezone=EASTERN_TZ,
        ),
        id="journal_autoclose",
        name="Journal Auto-Close (4:05 PM ET)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 16:10 ET — Fill historical prices for scan candidates
    scheduler.add_job(
        fill_candidate_prices,
        trigger=CronTrigger(
            day_of_week="mon-fri", hour=16, minute=10, timezone=EASTERN_TZ,
        ),
        id="fill_candidate_prices",
        name="Fill Candidate Prices (4:10 PM ET)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 16:30 ET — AI Portfolio daily report
    scheduler.add_job(
        generate_daily_report,
        trigger=CronTrigger(
            day_of_week="mon-fri", hour=16, minute=30, timezone=EASTERN_TZ,
        ),
        id="ai_portfolio_report",
        name="AI Portfolio Daily Report (4:30 PM ET)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 16:35 ET — Generate EOD log (after all other 4 PM jobs finish)
    scheduler.add_job(
        run_eod_log,
        trigger=CronTrigger(
            day_of_week="mon-fri", hour=16, minute=35, timezone=EASTERN_TZ,
        ),
        id="eod_log",
        name="EOD Log Generator (4:35 PM ET)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    scheduler.start()
    logger.info("Scheduler started — 3 scan jobs + hype monitor + 5 portfolio/journal/EOD jobs")


def stop_scheduler():
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
