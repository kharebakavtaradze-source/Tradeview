"""
APScheduler setup for automated morning scan jobs.
Runs Monday–Friday at 8:00 AM, 9:30 AM, and 12:00 PM Eastern (UTC offsets).
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from scanner.runner import run_scan
from scanner.universe_scan import run_universe_scan
from database import save_scan, rotate_old_data
from hype_monitor.monitor import run_hype_monitor
from journal_autoclose import auto_close_journal, update_journal_prices_intraday
from ai_portfolio import ai_portfolio_decisions, generate_daily_report, update_ai_positions_intraday
from scan_candidates import fill_candidate_prices
from eod_log import run_eod_log
from scanner.market_regime import detect_market_regime
from scanner.sector_performance import fetch_sector_performance
from notifications.morning_brief import send_morning_brief
from notifications.price_alerts import check_price_alerts

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


async def _run_market_regime():
    """Detect and persist today's market regime."""
    try:
        logger.info("Market regime detection starting...")
        await detect_market_regime()
    except Exception as e:
        logger.error(f"Market regime detection failed: {e}", exc_info=True)


async def _run_data_rotation():
    """Weekly data rotation — remove old rows to prevent DB bloat."""
    try:
        logger.info("Data rotation starting...")
        deleted = await rotate_old_data()
        logger.info(f"Data rotation finished: {deleted}")
    except Exception as e:
        logger.error(f"Data rotation failed: {e}", exc_info=True)


async def enrich_sector_cache() -> dict:
    """
    Nightly job: fills missing sector/industry data from Massive Reference Data.
    Rate limit: 1 call per 15 seconds (safe for 5 calls/min free plan).
    Returns {"enriched": N, "total": M} summary dict.
    """
    import asyncio as _asyncio
    from database import get_symbols_needing_enrichment, save_sector_to_db
    from scanner.massive_client import get_ticker_reference

    missing = await get_symbols_needing_enrichment(limit=200)
    if not missing:
        logger.info("sector_cache enrichment: nothing to enrich")
        return {"enriched": 0, "total": 0}

    logger.info(f"Massive enrichment: {len(missing)} symbols queued")
    enriched = 0

    for symbol in missing:
        try:
            data = await get_ticker_reference(symbol)
            if data and data.get("sector"):
                await save_sector_to_db(
                    symbol,
                    sector=data["sector"],
                    industry=data.get("industry") or "",
                    market_cap=data.get("market_cap"),
                    massive_fetched=True,
                )
                enriched += 1
                logger.debug(f"Massive enriched: {symbol} → {data['sector']} / {data.get('industry')}")
            else:
                # Mark as attempted so we don't retry forever
                # Set massive_fetched=True even with no data (API returned nothing useful)
                await save_sector_to_db(symbol, sector="Unknown", massive_fetched=True)
        except Exception as e:
            logger.warning(f"Massive enrichment failed for {symbol}: {e}")

        # 1 call per 15s = 4 calls/min — safely under 5 calls/min free limit
        await _asyncio.sleep(15)

    logger.info(f"Massive enrichment complete: {enriched}/{len(missing)} updated")
    return {"enriched": enriched, "total": len(missing)}


async def _run_sector_enrichment():
    """Wrapper for scheduler."""
    try:
        await enrich_sector_cache()
    except Exception as e:
        logger.error(f"Sector enrichment job failed: {e}", exc_info=True)


async def _run_universe_scan():
    """Run the Massive EOD universe scan and persist results."""
    try:
        logger.info("Universe scan (Massive EOD) starting...")
        result = await run_universe_scan()
        total  = result.get("total", 0)
        fire   = result.get("tier_counts", {}).get("FIRE", 0)
        arm    = result.get("tier_counts", {}).get("ARM", 0)
        logger.info(f"Universe scan complete — {total} results, {fire} FIRE, {arm} ARM")
    except Exception as e:
        logger.error(f"Universe scan failed: {e}", exc_info=True)


async def _run_sector_performance():
    """Refresh Finviz sector performance cache (clears stale 4-hour window)."""
    try:
        from scanner import sector_performance as _sp
        import scanner.sector_performance as _sp_mod
        # Force cache bypass by resetting cache time
        _sp_mod._sector_cache_time = None
        data = await fetch_sector_performance()
        logger.info(f"Sector performance refreshed: {len(data)} sectors")
    except Exception as e:
        logger.error(f"Sector performance refresh failed: {e}", exc_info=True)


def start_scheduler():
    """Register scan jobs and start the scheduler."""

    # 16:20 ET — Finviz sector performance refresh (after close)
    scheduler.add_job(
        _run_sector_performance,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=16,
            minute=20,
            timezone=EASTERN_TZ,
        ),
        id="sector_performance_1620_et",
        name="Finviz Sector Performance (4:20 PM ET)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 16:15 ET — Market Regime Detection (after close, uses previous-day closing prices)
    scheduler.add_job(
        _run_market_regime,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=16,
            minute=15,
            timezone=EASTERN_TZ,
        ),
        id="market_regime_1615_est",
        name="Market Regime Detection (4:15 PM ET)",
        replace_existing=True,
        misfire_grace_time=300,
    )

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

    # Hype monitor: 3x daily at 9:00, 12:00, 15:00 ET (Mon–Fri)
    scheduler.add_job(
        _run_hype_monitor,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="9,12,15",
            minute="0",
            timezone=EASTERN_TZ,
        ),
        id="hype_monitor_3x_daily",
        name="Hype Monitor (3x daily: 9 AM, 12 PM, 3 PM ET)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 09:00 AM ET — Morning Brief (Telegram summary)
    scheduler.add_job(
        send_morning_brief,
        trigger=CronTrigger(
            day_of_week="mon-fri", hour=9, minute=0, timezone=EASTERN_TZ,
        ),
        id="morning_brief",
        name="Morning Brief Telegram (9:00 AM ET)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 09:45 AM ET — AI Portfolio decisions (after market-open scan settles)
    scheduler.add_job(
        ai_portfolio_decisions,
        trigger=CronTrigger(
            day_of_week="mon-fri", hour=9, minute=45, timezone=EASTERN_TZ,
        ),
        id="ai_portfolio_decisions",
        name="AI Portfolio Decisions (9:45 AM ET)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Every 5 min, 9:30–16:00 ET — update AI position prices + auto-stop/target
    scheduler.add_job(
        update_ai_positions_intraday,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="*/5",
            timezone=EASTERN_TZ,
        ),
        id="ai_positions_intraday_5min",
        name="AI Portfolio Intraday Price Update (every 5min)",
        replace_existing=True,
        misfire_grace_time=120,
    )

    # Price alerts: every 30 min, Mon–Fri, 9:30–16:00 ET
    scheduler.add_job(
        check_price_alerts,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="30,0",
            timezone=EASTERN_TZ,
        ),
        id="price_alerts_30min",
        name="Price Alerts Near Stop/Target (every 30min)",
        replace_existing=True,
        misfire_grace_time=120,
    )

    # Every 5 min, 9:30–16:00 ET — persist live prices to journal DB
    scheduler.add_job(
        update_journal_prices_intraday,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour="9-15",
            minute="*/5",
            timezone=EASTERN_TZ,
        ),
        id="journal_live_prices_5min",
        name="Journal Live Price Update (every 5min, market hours)",
        replace_existing=True,
        misfire_grace_time=120,
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

    # Sunday 02:00 ET — Weekly data rotation
    scheduler.add_job(
        _run_data_rotation,
        trigger=CronTrigger(
            day_of_week="sun",
            hour=2,
            minute=0,
            timezone=EASTERN_TZ,
        ),
        id="weekly_data_rotation",
        name="Weekly Data Rotation (Sun 2:00 AM ET)",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # 17:00 ET Mon–Fri — Massive EOD Universe Scan (primary signal source)
    scheduler.add_job(
        _run_universe_scan,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=17,
            minute=0,
            timezone=EASTERN_TZ,
        ),
        id="universe_scan_eod",
        name="Massive EOD Universe Scan (5:00 PM ET)",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # 22:00 ET Mon–Fri — Massive sector/industry enrichment (free plan: 1 per 15s)
    scheduler.add_job(
        _run_sector_enrichment,
        trigger=CronTrigger(
            day_of_week="mon-fri",
            hour=22,
            minute=0,
            timezone=EASTERN_TZ,
        ),
        id="sector_cache_enrichment",
        name="Massive Sector/Industry Enrichment (10:00 PM ET)",
        replace_existing=True,
        misfire_grace_time=1800,
    )

    scheduler.start()
    logger.info(
        "Scheduler started — "
        "PIPELINE 1: Massive EOD universe scan at 17:00 ET | "
        "PIPELINE 2: Yahoo intraday validation at 8:00, 9:30, 12:00 ET | "
        "Hype monitor 3x daily | Morning brief | Price alerts | "
        "Portfolio/journal/EOD jobs | Regime 16:15 | Sector perf 16:20 | "
        "Sector enrichment 22:00 | Weekly rotation Sun 2:00"
    )


def stop_scheduler():
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
