"""
Pump Scout — FastAPI backend
Endpoints for scan results, ticker detail, manual scan trigger, and health.
"""
import csv
import io
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any, Dict, Optional

import anthropic
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

from database import (
    add_journal_entry,
    add_to_watchlist,
    close_ai_position,
    delete_journal_entry,
    get_active_streaks,
    get_ai_portfolio_history,
    get_all_ai_positions,
    get_candidates_missed,
    get_candidates_summary,
    get_deep_analytics,
    get_journal,
    get_journal_entry,
    get_journal_stats,
    get_latest_scan,
    get_market_regime_history,
    get_market_regime_latest,
    get_open_ai_positions,
    get_portfolio_state,
    get_position_snapshots,
    get_scan_history,
    get_sector_strength_for_sector,
    get_sector_strength_latest,
    get_watchlist,
    init_db,
    mark_candidate_journaled,
    remove_from_watchlist,
    save_scan,
    update_journal_entry,
    get_eod_log,
    get_latest_eod_log,
)
from scanner.runner import run_scan
from scheduler import start_scheduler, stop_scheduler
from alerts.telegram import get_status as telegram_status
from alerts.telegram import send_scan_alert, send_test_alert
from hype_monitor.monitor import (
    get_alert_history,
    get_hype_for_ticker,
    get_latest_hype_results,
    get_status as hype_status,
    run_hype_monitor,
)
from hype_monitor.fetcher import fetch_all
from hype_monitor.velocity import calc_velocity
from hype_monitor.hype_score import calc_hype_score
from hype_monitor.divergence import detect_divergences

# ─── Lifespan ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: init DB + start scheduler. Shutdown: stop scheduler."""
    logger.info("Starting up Pump Scout backend...")
    await init_db()
    start_scheduler()
    yield
    stop_scheduler()
    logger.info("Pump Scout backend shut down.")


# ─── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Pump Scout API",
    description="Automated small-cap volume anomaly scanner",
    version="14.0",
    lifespan=lifespan,
)

# CORS — allow all origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Background scan state ────────────────────────────────────────────────────

_scan_running = False


async def _run_scan_background():
    global _scan_running
    if _scan_running:
        logger.info("Scan already running — skipping")
        return
    _scan_running = True
    try:
        result = await run_scan()
        await save_scan(result)
        logger.info("Manual scan complete and saved")
        await send_scan_alert(result)
    except Exception as e:
        logger.error(f"Background scan error: {e}", exc_info=True)
    finally:
        _scan_running = False


# ─── Routes ──────────────────────────────────────────────────────────────────

@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "scan_running": _scan_running,
        "version": "14.0",
    }


@app.get("/api/scan/latest")
async def get_latest():
    """Return the most recent scan results."""
    data = await get_latest_scan()
    if not data:
        return {
            "results": [],
            "scanned_at": None,
            "total": 0,
            "tier_counts": {},
            "message": "No scan data yet. Trigger a manual scan or wait for the scheduled run.",
        }
    # Strip heavy candle data from list response
    results = data.get("results", [])
    slim = []
    for r in results:
        entry = {k: v for k, v in r.items() if k != "candles"}
        slim.append(entry)

    return {
        **{k: v for k, v in data.items() if k != "results"},
        "results": slim,
    }


@app.get("/api/scan/history")
async def get_history(days: int = 30):
    """Return scan history summary for the last N days."""
    history = await get_scan_history(days=min(days, 90))
    return {"history": history, "days": days}


@app.get("/api/ticker/{symbol}")
async def get_ticker(symbol: str):
    """Return full detail for one ticker from the latest scan, including candles."""
    symbol = symbol.upper()
    data = await get_latest_scan()
    if not data:
        raise HTTPException(status_code=404, detail="No scan data available")

    results = data.get("results", [])
    ticker_data = next((r for r in results if r.get("symbol") == symbol), None)

    from scanner.yahoo import fetch_ohlcv

    if not ticker_data:
        # Try to fetch fresh data for this specific ticker
        from scanner.indicators import calc_all
        from scanner.wyckoff import detect_regime
        from scanner.scoring import score_ticker

        candles = await fetch_ohlcv(symbol)
        if not candles or len(candles) < 60:
            raise HTTPException(status_code=404, detail=f"Ticker {symbol} not found in latest scan")

        indicators = calc_all(candles)
        regime = detect_regime(candles)
        score = score_ticker(indicators, regime)

        return {
            "symbol": symbol,
            "price": candles[-1]["c"],
            "volume_today": candles[-1]["v"],
            "indicators": indicators,
            "regime": regime,
            "score": score,
            "candles": candles[-100:],
            "ai_analysis": None,
            "source": "live",
        }

    # Ticker found in scan — fetch fresh candles (stripped from DB to save space)
    candles = await fetch_ohlcv(symbol)
    return {
        **ticker_data,
        "candles": candles[-100:] if candles and len(candles) >= 20 else [],
        "source": "scan",
    }


@app.get("/api/scan/run")
async def trigger_scan_get(background_tasks: BackgroundTasks):
    """Manually trigger a scan via GET. Runs in background."""
    if _scan_running:
        return {"status": "already_running", "message": "A scan is already in progress"}
    background_tasks.add_task(_run_scan_background)
    return {"status": "started", "message": "Scan started in background"}


@app.post("/api/scan/run")
async def trigger_scan(background_tasks: BackgroundTasks):
    """Manually trigger a scan via POST. Runs in background."""
    if _scan_running:
        return {"status": "already_running", "message": "A scan is already in progress"}

    background_tasks.add_task(_run_scan_background)
    return {"status": "started", "message": "Scan started in background"}


# ─── Watchlist routes ────────────────────────────────────────────────────────

@app.get("/api/watchlist")
async def list_watchlist():
    items = await get_watchlist()
    return {"watchlist": items}


@app.post("/api/watchlist/{symbol}")
async def add_watchlist(symbol: str, notes: Optional[str] = None):
    item = await add_to_watchlist(symbol.upper(), notes)
    return {"status": "added", "item": item}


@app.delete("/api/watchlist/{symbol}")
async def remove_watchlist(symbol: str):
    removed = await remove_from_watchlist(symbol.upper())
    if not removed:
        raise HTTPException(status_code=404, detail=f"{symbol} not in watchlist")
    return {"status": "removed", "symbol": symbol.upper()}


# ─── Journal routes ───────────────────────────────────────────────────────────

@app.get("/api/journal")
async def list_journal():
    entries = await get_journal()
    return {"entries": entries}


@app.get("/api/journal/stats")
async def journal_stats():
    return await get_journal_stats()


# ── ATR / R/R helpers ──────────────────────────────────────────────────────────

def _calculate_suggested_levels(entry_price: float, atr: float, tier: str) -> dict:
    """ATR-based stop and target. Guarantees minimum 2.5:1 R/R."""
    stop_multipliers = {
        "FIRE": 1.2, "ARM": 1.5, "BASE": 2.0,
        "STEALTH": 1.5, "SYMPATHY": 1.5, "WATCH": 2.0,
    }
    stop_mult = stop_multipliers.get(tier.upper(), 1.5)
    target_mult = stop_mult * 2.5  # always 2.5x stop distance → 2.5:1 R/R

    stop = round(entry_price - atr * stop_mult, 2)
    target = round(entry_price + atr * target_mult, 2)
    stop_pct = round((stop - entry_price) / entry_price * 100, 1)
    target_pct = round((target - entry_price) / entry_price * 100, 1)
    rr_ratio = round(abs(target_pct / stop_pct), 2) if stop_pct != 0 else 0

    return {
        "stop": stop, "target": target,
        "stop_pct": stop_pct, "target_pct": target_pct,
        "rr_ratio": rr_ratio, "atr_used": round(atr, 4),
        "stop_mult": stop_mult, "target_mult": target_mult,
    }


def _validate_risk_reward(entry: float, stop: float, target: float) -> dict:
    """Validate R/R ratio. Returns level: OK / WARN / BLOCK."""
    if stop >= entry:
        return {"valid": False, "level": "BLOCK",
                "error": "Stop должен быть ниже цены входа"}
    if target <= entry:
        return {"valid": False, "level": "BLOCK",
                "error": "Target должен быть выше цены входа"}
    risk = entry - stop
    reward = target - entry
    ratio = round(reward / risk, 2)
    if ratio < 1.0:
        return {"valid": False, "level": "BLOCK", "ratio": ratio,
                "error": f"R/R {ratio:.2f}:1 слишком плохой. Минимум 1:1"}
    if ratio < 2.0:
        return {"valid": True, "level": "WARN", "ratio": ratio,
                "warning": f"R/R {ratio:.2f}:1 — лучше искать минимум 2:1"}
    return {"valid": True, "level": "OK", "ratio": ratio}


@app.get("/api/journal/suggest-levels")
async def suggest_levels(symbol: str, entry: float, tier: str = "ARM"):
    """Return ATR-based suggested stop and target for a symbol."""
    symbol = symbol.upper()
    atr = None

    # Look up ATR from the latest scan result for this symbol
    try:
        scan = await get_latest_scan()
        if scan:
            for r in scan.get("results", []):
                if r.get("symbol") == symbol:
                    atr = r.get("indicators", {}).get("atr")
                    break
    except Exception:
        pass

    if not atr or atr <= 0:
        # Fallback: estimate ATR as 3% of entry price
        atr = round(entry * 0.03, 4)

    levels = _calculate_suggested_levels(entry, atr, tier)
    return {"symbol": symbol, "entry": entry, "tier": tier, **levels}


@app.get("/api/journal/adaptive-weights")
async def adaptive_weights_endpoint():
    """Return adaptive scoring weights based on closed journal trades."""
    from scanner.adaptive_weights import get_adaptive_weights
    return await get_adaptive_weights()


@app.get("/api/journal/{entry_id}")
async def get_single_journal_entry(entry_id: int):
    entry = await get_journal_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Journal entry {entry_id} not found")
    return entry


@app.post("/api/journal")
async def create_journal_entry(data: Dict[str, Any]):
    if not data.get("symbol") or not data.get("entry_price"):
        raise HTTPException(status_code=400, detail="symbol and entry_price are required")

    # R/R validation — block entries with ratio < 1.0 unless user explicitly overrides
    entry_p = float(data["entry_price"])
    stop_p = data.get("stop_loss")
    target_p = data.get("target_price")
    rr_result = None
    if stop_p and target_p:
        rr_result = _validate_risk_reward(entry_p, float(stop_p), float(target_p))
        if rr_result["level"] == "BLOCK" and not data.get("override_rr"):
            raise HTTPException(status_code=400, detail=rr_result["error"])

    entry = await add_journal_entry(data)
    # Mark today's scan candidate as journaled (non-fatal)
    try:
        await mark_candidate_journaled(data["symbol"])
    except Exception:
        pass

    response: dict = {"status": "added", "entry": entry}
    if rr_result and rr_result.get("level") == "WARN":
        response["warning"] = rr_result.get("warning")
        response["rr_ratio"] = rr_result.get("ratio")
    return response


@app.put("/api/journal/{entry_id}")
async def update_entry(entry_id: int, data: Dict[str, Any]):
    entry = await update_journal_entry(entry_id, data)
    if not entry:
        raise HTTPException(status_code=404, detail=f"Journal entry {entry_id} not found")
    return {"status": "updated", "entry": entry}


@app.delete("/api/journal/{entry_id}")
async def delete_entry(entry_id: int):
    deleted = await delete_journal_entry(entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Journal entry {entry_id} not found")
    return {"status": "deleted"}


@app.get("/api/journal/export")
async def export_journal():
    entries = await get_journal()
    output = io.StringIO()
    fields = ["id", "symbol", "added_at", "entry_price", "entry_date", "exit_price",
              "exit_date", "tier", "score", "outcome", "gain_pct", "notes", "tags"]
    writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for e in entries:
        row = {**e, "tags": ",".join(e.get("tags") or [])}
        writer.writerow(row)
    output.seek(0)
    return StreamingResponse(
        io.BytesIO(output.getvalue().encode()),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=pump_scout_journal.csv"},
    )


@app.post("/api/journal/insights")
async def journal_insights():
    """Send journal data to Claude for pattern analysis (legacy endpoint)."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")
    entries = await get_journal()
    stats = await get_journal_stats()
    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=30.0)
    prompt = (
        f"Trade journal stats: {json.dumps(stats)}\n\n"
        f"Recent trades (last 20): {json.dumps(entries[:20])}\n\n"
        "Provide concise coaching insights:\n"
        "1. WIN PATTERNS — what setups are working?\n"
        "2. MISTAKE PATTERNS — what to avoid?\n"
        "3. FOCUS — top 2 things to improve?\n"
        "Keep it under 300 words, be direct and specific."
    )
    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            system="You are a trading coach analyzing a trader's journal for actionable patterns.",
            messages=[{"role": "user", "content": prompt}],
        )
        return {"insights": response.content[0].text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/journal/insights")
async def journal_insights_cumulative():
    """Cumulative AI insights from closed trades (6h cache)."""
    from journal_autoclose import get_cumulative_insights
    result = await get_cumulative_insights()
    return result


# Deep analytics cache
_deep_analytics_cache: dict = {}
_DEEP_ANALYTICS_TTL = 3600  # 1 hour

import time as _time

@app.get("/api/journal/deep-analytics")
async def journal_deep_analytics():
    """Full signal performance breakdown (1h cache)."""
    now = _time.time()
    if _deep_analytics_cache.get("result") and now - _deep_analytics_cache.get("ts", 0) < _DEEP_ANALYTICS_TTL:
        return {**_deep_analytics_cache["result"], "from_cache": True}
    result = await get_deep_analytics()
    _deep_analytics_cache["result"] = result
    _deep_analytics_cache["ts"] = now
    return result


@app.get("/api/journal/snapshots/{entry_id}")
async def journal_snapshots(entry_id: int):
    """Return daily position snapshots for a journal entry."""
    snaps = await get_position_snapshots(entry_id)
    return {"journal_id": entry_id, "snapshots": snaps}


# ─── Scan Candidates routes ────────────────────────────────────────────────────

@app.get("/api/candidates/missed")
async def candidates_missed():
    """Return scan candidates not journaled and their forward performance."""
    return await get_candidates_missed()


@app.get("/api/candidates/summary")
async def candidates_summary():
    """Return aggregate stats by tier for scan candidates."""
    return {"summary": await get_candidates_summary()}


# ─── AI Portfolio routes ───────────────────────────────────────────────────────

@app.get("/api/ai-portfolio/state")
async def ai_portfolio_state():
    return await get_portfolio_state()


@app.get("/api/ai-portfolio/positions")
async def ai_portfolio_positions():
    return {"positions": await get_open_ai_positions()}


@app.get("/api/ai-portfolio/history")
async def ai_portfolio_history_route():
    positions = await get_all_ai_positions(50)
    history = await get_ai_portfolio_history(30)
    return {"positions": positions, "history": history}


@app.get("/api/ai-portfolio/report/latest")
async def ai_portfolio_latest_report():
    state = await get_portfolio_state()
    return {
        "total_value": state["total_value"],
        "cash": state["cash"],
        "total_pnl_pct": state["total_pnl_pct"],
        "report": state.get("daily_report"),
        "decisions": state.get("decisions_json"),
    }


@app.get("/api/ai-portfolio/report/{report_date}")
async def ai_portfolio_report_by_date(report_date: str):
    """Return AI portfolio state for a specific date (YYYY-MM-DD)."""
    from sqlalchemy import select
    from database import AIPortfolioState, get_session_factory
    import json as _json
    async with get_session_factory()() as session:
        result = await session.execute(
            select(AIPortfolioState).where(AIPortfolioState.date == report_date)
        )
        state = result.scalar_one_or_none()
    if not state:
        raise HTTPException(status_code=404, detail=f"No portfolio data for {report_date}")
    return {
        "date": state.date,
        "total_value": state.total_value,
        "cash": state.cash,
        "total_pnl_pct": state.total_pnl_pct or 0,
        "report": _json.loads(state.daily_report) if state.daily_report else None,
        "decisions": _json.loads(state.decisions_json) if state.decisions_json else None,
    }


@app.post("/api/ai-portfolio/run-now")
async def ai_portfolio_run_now(background_tasks: BackgroundTasks):
    """Manually trigger AI portfolio decisions."""
    from ai_portfolio import ai_portfolio_decisions as run_decisions
    background_tasks.add_task(run_decisions)
    return {"status": "started", "message": "AI portfolio decisions running in background"}


# ─── Hype Monitor routes (specific routes BEFORE parameterized {symbol}) ───────

@app.get("/api/hype/status")
async def hype_monitor_status():
    """Return hype monitor status and latest cycle summary."""
    return hype_status()


@app.get("/api/hype/results")
async def hype_monitor_results():
    """Return full results from the latest hype monitor cycle."""
    return {"results": get_latest_hype_results()}


@app.get("/api/hype/run")
@app.post("/api/hype/run")
async def trigger_hype_monitor(background_tasks: BackgroundTasks):
    """Manually trigger a hype monitor cycle (GET or POST)."""
    background_tasks.add_task(run_hype_monitor)
    return {"status": "started", "message": "Hype monitor cycle started in background"}


@app.get("/api/hype/alerts/history")
async def hype_alert_history():
    """Return recent hype alert history."""
    return {"alerts": get_alert_history()}


@app.get("/api/hype/{symbol}")
async def hype_for_ticker(symbol: str):
    """
    Return hype data for a specific ticker.
    If not in the monitor cache, fetches live data immediately — never returns 404.
    """
    ticker = symbol.upper()
    result = get_hype_for_ticker(ticker)
    if result:
        return result

    # Live fetch for tickers not yet in the monitor cache
    raw = await fetch_all(ticker)
    velocity = calc_velocity(raw)
    hype_score = calc_hype_score(raw, velocity)
    divergences = detect_divergences(hype_score, velocity, {})
    news_detail = raw.get("news_detail", {})
    return {
        "ticker": ticker,
        "hype_score": hype_score,
        "velocity": velocity,
        "divergences": divergences,
        "ai_analysis": None,
        "news": {
            **news_detail,
            "catalyst_summary": news_detail.get("catalyst_summary", ""),
        },
        "source": "live",
    }


# ─── Alert routes ─────────────────────────────────────────────────────────────

@app.get("/api/alerts/status")
async def alerts_status():
    return telegram_status()


@app.get("/api/alerts/test")
async def alerts_test():
    sent = await send_test_alert()
    if not sent:
        status = telegram_status()
        if not status["configured"]:
            raise HTTPException(status_code=503, detail="Telegram not configured — set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
        raise HTTPException(status_code=500, detail="Telegram send failed — check logs")
    return {"status": "sent", "message": "Test alert delivered to Telegram"}


# ─── Market Regime routes ──────────────────────────────────────────────────────

@app.get("/api/market-regime")
async def market_regime_latest():
    """Return the latest market regime with ETF details."""
    regime = await get_market_regime_latest()
    if not regime:
        # No saved regime yet — try to detect on-the-fly
        try:
            from scanner.market_regime import detect_market_regime
            regime = await detect_market_regime()
        except Exception as e:
            logger.warning(f"On-the-fly regime detection failed: {e}")
            return {"regime": "NEUTRAL", "recommendation": "No data yet.", "strong_sectors": [], "weak_sectors": [], "etf_details": {}}
    return regime


@app.get("/api/market-regime/history")
async def market_regime_history():
    """Return the last 30 days of market regime data."""
    return await get_market_regime_history(days=30)


@app.post("/api/market-regime/refresh")
async def market_regime_refresh(background_tasks: BackgroundTasks):
    """Manually trigger market regime detection (runs in background)."""
    from scanner.market_regime import detect_market_regime
    background_tasks.add_task(detect_market_regime)
    return {"status": "started", "message": "Market regime detection started in background"}


@app.get("/api/sector-strength")
async def sector_strength_latest():
    """Return today's sector strength table sorted by avg_score."""
    data = await get_sector_strength_latest()
    # If empty, try to get from latest scan
    if not data:
        scan = await get_latest_scan()
        if scan and scan.get("sector_strength"):
            data = scan["sector_strength"]
    sectors = sorted(data.values(), key=lambda x: x.get("avg_score", 0), reverse=True)
    return {"sectors": sectors}


@app.get("/api/sector-strength/{sector}")
async def sector_strength_by_sector(sector: str):
    """Return tickers in a specific sector with their scores."""
    data = await get_sector_strength_for_sector(sector)
    if not data:
        raise HTTPException(status_code=404, detail=f"No data for sector: {sector}")

    # Enrich with latest scan data for each ticker
    scan = await get_latest_scan()
    tickers_detail = []
    if scan:
        results_by_symbol = {r["symbol"]: r for r in scan.get("results", [])}
        for sym in data.get("tickers", []):
            r = results_by_symbol.get(sym)
            if r:
                tickers_detail.append({
                    "symbol": sym,
                    "tier": r.get("score", {}).get("tier"),
                    "score": round(r.get("score", {}).get("total_score", 0), 1),
                    "price": r.get("price"),
                    "price_change_pct": r.get("indicators", {}).get("price_change_pct", 0),
                    "cmf_pctl": r.get("indicators", {}).get("cmf_pctl", 0),
                    "vol_ratio": r.get("indicators", {}).get("anomaly_ratio", 0),
                    "sympathy": r.get("sympathy", {}),
                })
    tickers_detail.sort(key=lambda x: x.get("score", 0), reverse=True)

    return {**data, "tickers_detail": tickers_detail}


# ─── EOD Log routes ────────────────────────────────────────────────────────────

@app.get("/api/eod-log/latest")
async def eod_log_latest():
    """Return the most recent EOD log as plain Markdown text (file download)."""
    from fastapi.responses import PlainTextResponse
    log = await get_latest_eod_log()
    if not log:
        raise HTTPException(status_code=404, detail="No EOD logs generated yet.")
    filename = f"pump-scout-eod-{log['log_date']}.md"
    return PlainTextResponse(
        content=log["content"],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/eod-log/{log_date}")
async def eod_log_by_date(log_date: str):
    """Return EOD log for a specific date (YYYY-MM-DD) as plain Markdown."""
    from fastapi.responses import PlainTextResponse
    log = await get_eod_log(log_date)
    if not log:
        raise HTTPException(status_code=404, detail=f"No EOD log for {log_date}.")
    filename = f"pump-scout-eod-{log_date}.md"
    return PlainTextResponse(
        content=log["content"],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/api/eod-log/generate-now")
async def eod_log_generate_now(background_tasks: BackgroundTasks):
    """Manually trigger EOD log generation (runs in background)."""
    from eod_log import run_eod_log
    background_tasks.add_task(run_eod_log)
    return {"status": "started", "message": "EOD log generation started in background"}


# ─── Pattern Streak routes ─────────────────────────────────────────────────────

@app.get("/api/streaks/active")
async def active_streaks(min_days: int = 2):
    """Return active pattern streaks — tickers that appeared in ARM+ scans consecutively."""
    streaks = await get_active_streaks(min_days=min_days)
    return {"streaks": streaks, "count": len(streaks)}


# ─── Notification test routes ──────────────────────────────────────────────────

@app.get("/api/notifications/test-morning-brief")
async def test_morning_brief():
    """Send a test morning brief to Telegram immediately."""
    from notifications.morning_brief import send_morning_brief
    ok = await send_morning_brief()
    if not ok:
        raise HTTPException(status_code=500, detail="Morning brief send failed — check Telegram config and logs")
    return {"status": "sent", "message": "Morning brief delivered to Telegram"}


@app.get("/api/notifications/test-price-alert")
async def test_price_alert():
    """Run a price alert check immediately (ignores cooldown)."""
    from notifications.price_alerts import check_price_alerts, ALERT_COOLDOWN
    # Clear cooldowns so the test actually sends
    ALERT_COOLDOWN.clear()
    result = await check_price_alerts()
    return {"status": "done", **result}


# ─── Earnings routes ───────────────────────────────────────────────────────────

@app.get("/api/earnings/upcoming")
async def earnings_upcoming(days: int = 14):
    """
    Return upcoming earnings for tracked symbols (recent scan + open journal).
    Sorted by days_until. Returns all calendar symbols if no tracked set available.
    """
    from data.finnhub_provider import get_earnings_calendar, is_configured
    if not is_configured():
        return {"earnings": [], "count": 0, "note": "FINNHUB_API_KEY not configured"}

    calendar = await get_earnings_calendar(days_ahead=days)
    if not calendar:
        return {"earnings": [], "count": 0}

    # Tracked = recent scan results + open journal positions
    tracked: set = set()
    open_symbols: set = set()
    try:
        scan = await get_latest_scan()
        if scan:
            tracked.update(r["symbol"] for r in scan.get("results", []))
    except Exception:
        pass
    try:
        from database import get_open_journal_entries
        positions = await get_open_journal_entries()
        open_symbols = {p["symbol"] for p in positions}
        tracked.update(open_symbols)
    except Exception:
        pass

    earnings = [
        {"symbol": sym, "in_journal": sym in open_symbols, **info}
        for sym, info in calendar.items()
        if not tracked or sym in tracked
    ]
    earnings.sort(key=lambda x: x["days_until"])
    return {"earnings": earnings, "count": len(earnings)}


@app.get("/api/earnings/{symbol}")
async def earnings_for_symbol(symbol: str):
    """Return next earnings date/info for a specific symbol."""
    from data.finnhub_provider import get_earnings_for_symbol, is_configured
    if not is_configured():
        return {"has_earnings": False, "note": "FINNHUB_API_KEY not configured"}
    return await get_earnings_for_symbol(symbol.upper())


# ─── Admin ─────────────────────────────────────────────────────────────────────

@app.get("/api/admin/rotate-data")
async def admin_rotate_data():
    """Manually trigger data rotation (same logic as the weekly Sunday job)."""
    from database import rotate_old_data
    deleted = await rotate_old_data()
    total = sum(deleted.values())
    return {"ok": True, "total_deleted": total, "breakdown": deleted}
