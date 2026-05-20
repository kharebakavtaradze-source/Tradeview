"""
APScheduler setup — all schedule times shown in GMT+4 (= ET + 8h).

PREMARKET (GMT+4):
  17:00  Morning Brief
  17:10  Hype Monitor #1
  17:15  AI Portfolio Decisions (before market open)

MARKET SESSION (GMT+4):
  17:30–00:00 every 30 min  Price Alerts, AI Positions, Journal Prices
  20:10  Hype Monitor #2
  23:20  Hype Monitor #3 (pre-close, next-day prep)

POST-CLOSE (GMT+4):
  00:10  Journal Auto-Close
  00:15  Fill Candidate Prices
  00:20  Market Regime Detection
  00:25  Finviz Sector Performance
  00:30  AI Portfolio Daily Report
  00:35  EOD Log Generator

NIGHT (GMT+4):
  06:00  Massive EOD Universe Scan (Pipeline 1)
  after  Sector/Industry Enrichment (triggered on scan success)

WEEKLY:
  Sun 10:00  Data Rotation
"""
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from scanner.universe_scan import run_universe_scan
from database import rotate_old_data, upsert_macro_events
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


async def _run_trump_news_refresh():
    """Fetch Trump-related news, classify events, upsert to DB."""
    try:
        from news.trump_news import fetch_and_classify_events
        logger.info("Trump news bias refresh starting...")
        events = await fetch_and_classify_events(use_manual=False)
        inserted = await upsert_macro_events(events)
        logger.info(f"Trump news refresh complete — {len(events)} classified, {inserted} new")
    except Exception as e:
        logger.error(f"Trump news refresh failed: {e}", exc_info=True)


async def _run_universe_cache_sync():
    """
    Nightly Massive reference sync — builds UniverseCache (CS / ADR / ADRC).
    Runs at 21:00 ET, one hour before EOD universe scan (22:00 ET), so that
    sector_resolver fallback and ETF-exclusion lists are fresh for the scan.
    """
    try:
        logger.info("Universe cache sync (Massive reference) starting…")
        from scanner.massive_reference import sync_universe_cache
        count = await sync_universe_cache(save_to_db=True)
        logger.info(f"Universe cache sync complete — {count} tickers cached")
    except Exception as e:
        logger.error(f"Universe cache sync failed: {e}", exc_info=True)


async def _run_universe_scan():
    """
    Run the Massive EOD universe scan and persist results.
    On success, triggers sector/industry enrichment as a dependent step
    (not a parallel cron) to ensure enrichment always runs after fresh data.
    """
    try:
        logger.info("Universe scan (Massive EOD) starting...")
        result = await run_universe_scan()
        total  = result.get("total", 0)
        fire   = result.get("tier_counts", {}).get("FIRE", 0)
        arm    = result.get("tier_counts", {}).get("ARM", 0)
        logger.info(f"Universe scan complete — {total} results, {fire} FIRE, {arm} ARM")
        # Trigger sector enrichment only after a successful scan (dependency-based)
        if total > 0:
            logger.info("Universe scan succeeded — starting sector/industry enrichment")
            await _run_sector_enrichment()
        else:
            logger.warning("Universe scan returned 0 results — skipping sector enrichment")
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

    # ── PREMARKET ──────────────────────────────────────────────────────────────

    # 09:00 ET (17:00 GMT+4) — Morning Brief Telegram
    scheduler.add_job(
        send_morning_brief,
        trigger=CronTrigger(day_of_week="mon-fri", hour=9, minute=0, timezone=EASTERN_TZ),
        id="morning_brief",
        name="Morning Brief Telegram (09:00 ET / 17:00 GMT+4)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 09:10 ET (17:10 GMT+4) — Hype Monitor #1
    scheduler.add_job(
        _run_hype_monitor,
        trigger=CronTrigger(day_of_week="mon-fri", hour=9, minute=10, timezone=EASTERN_TZ),
        id="hype_monitor_1",
        name="Hype Monitor #1 (09:10 ET / 17:10 GMT+4)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 09:15 ET (17:15 GMT+4) — AI Portfolio Decisions (before market open)
    scheduler.add_job(
        ai_portfolio_decisions,
        trigger=CronTrigger(day_of_week="mon-fri", hour=9, minute=15, timezone=EASTERN_TZ),
        id="ai_portfolio_decisions",
        name="AI Portfolio Decisions (09:15 ET / 17:15 GMT+4)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # ── MARKET SESSION ─────────────────────────────────────────────────────────

    # Every 5 min, 09:30–16:00 ET — AI position price update + auto-stop/target
    scheduler.add_job(
        update_ai_positions_intraday,
        trigger=CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/5", timezone=EASTERN_TZ),
        id="ai_positions_intraday_5min",
        name="AI Portfolio Price Update (every 5min, 17:30–00:00 GMT+4)",
        replace_existing=True,
        misfire_grace_time=120,
    )

    # 16:05 ET — post-close final price snapshot for AI positions
    scheduler.add_job(
        update_ai_positions_intraday,
        trigger=CronTrigger(day_of_week="mon-fri", hour="16", minute="5", timezone=EASTERN_TZ),
        id="ai_positions_post_close",
        name="AI Portfolio Post-Close Price Snapshot (00:05 GMT+4)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # Every 5 min, 09:30–16:00 ET — persist live prices to journal DB
    scheduler.add_job(
        update_journal_prices_intraday,
        trigger=CronTrigger(day_of_week="mon-fri", hour="9-15", minute="*/5", timezone=EASTERN_TZ),
        id="journal_live_prices_5min",
        name="Journal Live Prices (every 5min, 17:30–00:00 GMT+4)",
        replace_existing=True,
        misfire_grace_time=120,
    )

    # Every 30 min, 09:30–16:00 ET — price alerts
    scheduler.add_job(
        check_price_alerts,
        trigger=CronTrigger(day_of_week="mon-fri", hour="9-15", minute="0,30", timezone=EASTERN_TZ),
        id="price_alerts_30min",
        name="Price Alerts (every 30min, 17:30–00:00 GMT+4)",
        replace_existing=True,
        misfire_grace_time=120,
    )

    # 12:10 ET (20:10 GMT+4) — Hype Monitor #2
    scheduler.add_job(
        _run_hype_monitor,
        trigger=CronTrigger(day_of_week="mon-fri", hour=12, minute=10, timezone=EASTERN_TZ),
        id="hype_monitor_2",
        name="Hype Monitor #2 (12:10 ET / 20:10 GMT+4)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 15:20 ET (23:20 GMT+4) — Hype Monitor #3 (pre-close, next-day prep)
    scheduler.add_job(
        _run_hype_monitor,
        trigger=CronTrigger(day_of_week="mon-fri", hour=15, minute=20, timezone=EASTERN_TZ),
        id="hype_monitor_3",
        name="Hype Monitor #3 (15:20 ET / 23:20 GMT+4)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # ── POST-CLOSE ─────────────────────────────────────────────────────────────

    # 16:10 ET (00:10 GMT+4) — Journal Auto-Close (slightly after close, prices settled)
    scheduler.add_job(
        auto_close_journal,
        trigger=CronTrigger(day_of_week="mon-fri", hour=16, minute=10, timezone=EASTERN_TZ),
        id="journal_autoclose",
        name="Journal Auto-Close (16:10 ET / 00:10 GMT+4)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 16:15 ET (00:15 GMT+4) — Fill historical prices for scan candidates
    scheduler.add_job(
        fill_candidate_prices,
        trigger=CronTrigger(day_of_week="mon-fri", hour=16, minute=15, timezone=EASTERN_TZ),
        id="fill_candidate_prices",
        name="Fill Candidate Prices (16:15 ET / 00:15 GMT+4)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 16:20 ET (00:20 GMT+4) — Market Regime Detection
    scheduler.add_job(
        _run_market_regime,
        trigger=CronTrigger(day_of_week="mon-fri", hour=16, minute=20, timezone=EASTERN_TZ),
        id="market_regime_1620_et",
        name="Market Regime Detection (16:20 ET / 00:20 GMT+4)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 16:25 ET (00:25 GMT+4) — Finviz sector performance refresh
    scheduler.add_job(
        _run_sector_performance,
        trigger=CronTrigger(day_of_week="mon-fri", hour=16, minute=25, timezone=EASTERN_TZ),
        id="sector_performance_1625_et",
        name="Finviz Sector Performance (16:25 ET / 00:25 GMT+4)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 16:30 ET (00:30 GMT+4) — AI Portfolio daily report
    scheduler.add_job(
        generate_daily_report,
        trigger=CronTrigger(day_of_week="mon-fri", hour=16, minute=30, timezone=EASTERN_TZ),
        id="ai_portfolio_report",
        name="AI Portfolio Daily Report (16:30 ET / 00:30 GMT+4)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # 16:35 ET (00:35 GMT+4) — EOD Log Generator
    scheduler.add_job(
        run_eod_log,
        trigger=CronTrigger(day_of_week="mon-fri", hour=16, minute=35, timezone=EASTERN_TZ),
        id="eod_log",
        name="EOD Log Generator (16:35 ET / 00:35 GMT+4)",
        replace_existing=True,
        misfire_grace_time=300,
    )

    # ── NIGHT ──────────────────────────────────────────────────────────────────

    # 21:00 ET (05:00 GMT+4 next day) — Universe Cache Sync (Massive reference)
    # Must run before EOD scan (22:00 ET) so sector_resolver and ETF exclusion are fresh.
    scheduler.add_job(
        _run_universe_cache_sync,
        trigger=CronTrigger(day_of_week="mon-fri", hour=21, minute=0, timezone=EASTERN_TZ),
        id="universe_cache_sync",
        name="Universe Cache Sync — Massive Reference (21:00 ET / 05:00 GMT+4)",
        replace_existing=True,
        misfire_grace_time=1800,
    )

    # 22:00 ET (06:00 GMT+4 next day) — Massive EOD Universe Scan
    # Sector/Industry Enrichment is triggered automatically on scan success (not a parallel cron)
    scheduler.add_job(
        _run_universe_scan,
        trigger=CronTrigger(day_of_week="mon-fri", hour=22, minute=0, timezone=EASTERN_TZ),
        id="universe_scan_eod",
        name="Massive EOD Universe Scan (22:00 ET / 06:00 GMT+4)",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    # ── MACRO EVENTS — Trump News Bias Layer (Version Alpha) ──────────────────

    # Every 4 hours — refresh Trump news from RSS feeds
    scheduler.add_job(
        _run_trump_news_refresh,
        trigger=CronTrigger(hour="*/4", minute=30, timezone=EASTERN_TZ),
        id="trump_news_refresh",
        name="Trump News Bias Refresh (every 4h)",
        replace_existing=True,
        misfire_grace_time=600,
    )

    # ── WEEKLY ─────────────────────────────────────────────────────────────────

    # Sunday 02:00 ET (10:00 GMT+4) — Data Rotation
    scheduler.add_job(
        _run_data_rotation,
        trigger=CronTrigger(day_of_week="sun", hour=2, minute=0, timezone=EASTERN_TZ),
        id="weekly_data_rotation",
        name="Weekly Data Rotation (Sun 02:00 ET / 10:00 GMT+4)",
        replace_existing=True,
        misfire_grace_time=3600,
    )

    scheduler.start()
    logger.info(
        "Scheduler started (all times GMT+4) — "
        "PIPELINE 1: Universe cache sync 05:00 GMT+4 → EOD scan 06:00 GMT+4 + enrichment | "
        "PIPELINE 2: Intraday scans 16:00, 17:30, 20:00 GMT+4 | "
        "Hype: 17:10, 20:10, 23:20 GMT+4 | "
        "AI decisions 17:15 GMT+4 (pre-open) | "
        "Post-close 00:10–00:35 GMT+4 | "
        "Trump news bias every 4h | Sun 10:00 rotation"
    )


def stop_scheduler():
    """Gracefully shut down the scheduler."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")
