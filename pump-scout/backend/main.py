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
from datetime import datetime, timedelta
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
    get_latest_scan_by_type,
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
    get_macro_events_latest,
    get_macro_events_history,
    get_macro_events_active,
    upsert_macro_events,
    # Historical Replay Layer
    create_replay_run,
    update_replay_run,
    get_replay_run,
    get_replay_history,
    get_replay_candidates,
    get_replay_outcomes,
    get_replay_missed_movers,
    # Pump Study AI Layer
    get_pump_ai_summary,
    save_pump_ai_summary,
)
from scanner.runner import run_scan
from scanner.massive_data import get_us_etf_symbols
from scanner.sector_map import NON_STOCK_SECURITIES
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

# ─── Non-stock exclusion helper ──────────────────────────────────────────────

async def _get_exclusion_set() -> set[str]:
    """
    Return the union of the Polygon-sourced ETF/ETN/ETV/FUND list and the
    static NON_STOCK_SECURITIES set (CEFs + ETNs).  Result is cached for 7
    days inside get_us_etf_symbols() — subsequent calls within the same day
    are essentially free.
    """
    try:
        etf_syms = await get_us_etf_symbols()
    except Exception:
        etf_syms = set()
    return etf_syms | {s.upper() for s in NON_STOCK_SECURITIES}


def _strip_non_stocks(results: list[dict], exclusions: set[str]) -> list[dict]:
    """Remove ETF / ETN / CEF / fund / leveraged / crypto entries from a result list."""
    return [r for r in results if r.get("symbol", "").upper() not in exclusions]


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


async def _fetch_live_price_v8(symbol: str, client) -> dict | None:
    """
    Fetch real-time price using Yahoo Finance v8/finance/chart (same API used by scanner).
    Returns {price, change_pct, prev_close} or None on failure.
    meta.regularMarketPrice is live even during market hours.
    """
    import httpx
    YAHOO_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json",
        "Accept-Language": "en-US,en;q=0.5",
    }
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol.upper()}"
    try:
        resp = await client.get(url, params={"interval": "1d", "range": "5d"}, headers=YAHOO_HEADERS, timeout=10.0)
        if resp.status_code != 200:
            return None
        result = resp.json().get("chart", {}).get("result") or []
        if not result:
            return None
        meta = result[0].get("meta", {})
        price = meta.get("regularMarketPrice")
        prev_close = meta.get("chartPreviousClose") or meta.get("previousClose")
        if not price:
            return None
        change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close else None
        return {"price": round(price, 4), "change_pct": change_pct, "prev_close": prev_close}
    except Exception:
        return None


@app.get("/api/prices/live")
async def get_live_prices(symbols: str = ""):
    """
    Batch real-time prices for comma-separated symbols via Yahoo Finance v8/finance/chart.
    Returns {SYMBOL: {price, change_pct, prev_close}}.
    Used by frontend to overlay live prices on EOD scan data during market hours.
    """
    import asyncio, httpx
    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()][:100]
    if not sym_list:
        return {}

    semaphore = asyncio.Semaphore(8)  # max 8 concurrent requests

    async def fetch_one(sym: str, client) -> tuple[str, dict | None]:
        async with semaphore:
            data = await _fetch_live_price_v8(sym, client)
            return sym, data

    async with httpx.AsyncClient() as client:
        tasks = [fetch_one(sym, client) for sym in sym_list]
        pairs = await asyncio.gather(*tasks, return_exceptions=True)

    result = {}
    for item in pairs:
        if isinstance(item, tuple):
            sym, data = item
            if data:
                result[sym] = data
    return result


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
    exclusions = await _get_exclusion_set()
    results = _strip_non_stocks(data.get("results", []), exclusions)
    slim = [{k: v for k, v in r.items() if k != "candles"} for r in results]
    return {
        **{k: v for k, v in data.items() if k != "results"},
        "results": slim,
    }


@app.get("/api/scan/history")
async def get_history(days: int = 30):
    """Return scan history summary for the last N days."""
    history = await get_scan_history(days=min(days, 90))
    return {"history": history, "days": days}


@app.get("/api/scan/universe/latest")
async def get_universe_scan_latest():
    """Return the latest Massive EOD universe scan results."""
    data = await get_latest_scan_by_type("massive_eod")
    if not data:
        return {
            "results": [], "scanned_at": None, "total": 0,
            "scan_type": "massive_eod",
            "message": "No EOD universe scan yet. Runs at 17:00 ET Mon–Fri.",
        }
    exclusions = await _get_exclusion_set()
    results = _strip_non_stocks(data.get("results", []), exclusions)
    slim = [{k: v for k, v in r.items() if k != "candles"} for r in results]
    return {**{k: v for k, v in data.items() if k != "results"}, "results": slim}


@app.get("/api/scan/intraday/latest")
async def get_intraday_scan_latest():
    """Return the latest Yahoo intraday validation scan results."""
    data = await get_latest_scan_by_type("yahoo_intraday")
    if not data:
        return {
            "results": [], "scanned_at": None, "total": 0,
            "scan_type": "yahoo_intraday",
            "message": "No intraday scan yet. Runs at 8:00, 9:30, 12:00 ET Mon–Fri.",
        }
    exclusions = await _get_exclusion_set()
    results = _strip_non_stocks(data.get("results", []), exclusions)
    slim = [{k: v for k, v in r.items() if k != "candles"} for r in results]
    return {**{k: v for k, v in data.items() if k != "results"}, "results": slim}


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


@app.get("/api/journal/live-prices")
async def journal_live_prices():
    """
    Return live prices + P&L% for all open journal positions.
    Uses v8/finance/chart (same API as the main scanner) — reliable from Railway.
    Called by frontend every 60s during market hours.
    """
    import asyncio, httpx
    from database import get_open_journal_entries

    entries = await get_open_journal_entries()
    if not entries:
        return {}

    entry_map = {e["symbol"]: e["entry_price"] for e in entries}
    sym_list = list(entry_map.keys())
    semaphore = asyncio.Semaphore(8)

    async def fetch_one(sym: str, client) -> tuple[str, dict | None]:
        async with semaphore:
            data = await _fetch_live_price_v8(sym, client)
            return sym, data

    async with httpx.AsyncClient() as client:
        tasks = [fetch_one(sym, client) for sym in sym_list]
        pairs = await asyncio.gather(*tasks, return_exceptions=True)

    result = {}
    for item in pairs:
        if not isinstance(item, tuple):
            continue
        sym, data = item
        if not data:
            continue
        price = data["price"]
        entry_price = entry_map.get(sym, 0)
        pct = round((price - entry_price) / entry_price * 100, 2) if entry_price else 0
        result[sym] = {"price": price, "pct": pct, "change_pct": data.get("change_pct")}

    return result


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


@app.get("/api/journal/test-autoclose")
async def test_autoclose():
    """Dry-run auto-close: shows what WOULD be closed without writing to DB."""
    from journal_autoclose import auto_close_journal
    result = await auto_close_journal(dry_run=True)
    return result


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


@app.post("/api/ai-portfolio/refresh-prices")
async def ai_portfolio_refresh_prices():
    """
    Fetch live prices for all open AI positions and update P&L.
    Safe to call any time — no AI decisions made, prices only.
    """
    from ai_portfolio import update_ai_positions_intraday
    from database import get_open_ai_positions
    positions = await get_open_ai_positions()
    if not positions:
        return {"status": "ok", "message": "No open positions to update", "updated": 0}
    await update_ai_positions_intraday()
    positions_after = await get_open_ai_positions()
    return {
        "status": "ok",
        "updated": len(positions_after),
        "message": f"Prices refreshed for {len(positions_after)} positions",
        "positions": positions_after,
    }


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
@app.get("/api/market-regime/refresh")
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


# ── EMA Ribbon Scanner helpers ────────────────────────────────────────────────

def _passes_mode(mode: str, compression: str, bullish: bool, cb: bool, anomaly: float) -> bool:
    if mode == "compression":
        return compression != "NONE"
    if mode == "breakout":
        return bool(cb) and anomaly >= 1.8
    if mode == "stack":
        return bool(bullish)
    return True  # "all"


def _ribbon_signal(cb: bool, bullish: bool, bearish: bool, compression: str, anomaly: float) -> str:
    if cb and anomaly >= 1.8:
        return "COMPRESSION_BREAKOUT"
    if cb:
        return "COMPRESSION_ALIGNED"
    if bullish:
        return "BULLISH_STACK"
    if bearish:
        return "BEARISH_STACK"
    if compression != "NONE":
        return "COMPRESSION_WATCH"
    return "NEUTRAL"


def _ribbon_quality(spread: float, signal: str, ind: dict) -> int:
    q = 0
    if spread < 1.0:   q += 35
    elif spread < 2.0: q += 25
    elif spread < 3.0: q += 15
    elif spread < 5.0: q += 5
    q += {"COMPRESSION_BREAKOUT": 30, "COMPRESSION_ALIGNED": 20,
          "BULLISH_STACK": 20, "COMPRESSION_WATCH": 10}.get(signal, 0)
    cmf = ind.get("cmf_pctl", 0) or 0
    if cmf > 70:   q += 10
    elif cmf > 50: q += 5
    if ind.get("bb_squeeze"):         q += 7
    if (ind.get("bb_sqz_bars") or 0) >= 5: q += 5
    if (ind.get("rs_score") or 0) > 5:     q += 5
    # OBV — handle both sources (scan has nested obv dict; DB row has obv_strength directly)
    obv_str = (
        ind.get("obv", {}).get("obv_strength")
        if isinstance(ind.get("obv"), dict)
        else ind.get("obv_strength")
    )
    if obv_str == "STRONG":   q += 8
    elif obv_str == "MEDIUM": q += 4
    return min(100, q)


def _ribbon_item_from_scan(r: dict, ind: dict, score_data: dict, signal: str, quality: int) -> dict:
    obv_data = ind.get("obv") or {}
    return {
        "symbol":       r["symbol"],
        "price":        r["price"],
        "sector":       r.get("sector", "Unknown"),
        "tier":         score_data.get("tier"),
        "total_score":  score_data.get("total_score"),
        "source":       "main_scan",
        "ribbon_signal":          signal,
        "ribbon_quality":         quality,
        "ema_spread_pct":         ind.get("ema_spread_pct"),
        "ribbon_compression":     ind.get("ribbon_compression", "NONE"),
        "bullish_stack":          ind.get("bullish_stack", False),
        "bearish_stack":          ind.get("bearish_stack", False),
        "compression_and_bullish": ind.get("compression_and_bullish", False),
        "ribbon_position":        ind.get("ribbon_position"),
        "ema8_slope":             ind.get("ema8_slope"),
        "ribbon_periods_count":   ind.get("ribbon_periods_count"),
        "ema8":   ind.get("ema8"),   "ema13": ind.get("ema13"),
        "ema20":  ind.get("ema20"),  "ema21": ind.get("ema21"),
        "ema34":  ind.get("ema34"),  "ema50": ind.get("ema50"),
        "ema55":  ind.get("ema55"),  "ema89": ind.get("ema89"),
        "ema200": ind.get("ema200"),
        "cmf_pctl":      ind.get("cmf_pctl", 0),
        "anomaly_ratio": ind.get("anomaly_ratio", 0),
        "bb_squeeze":    ind.get("bb_squeeze", False),
        "bb_sqz_bars":   ind.get("bb_sqz_bars", 0),
        "rs_score":      ind.get("rs_score", 0),
        "rsi":           (ind.get("rsi") or {}).get("value"),
        "obv_strength":  obv_data.get("obv_strength") if obv_data else None,
        "obv_divergence": obv_data.get("obv_divergence") if obv_data else None,
        "earnings_risk": r.get("earnings_risk", "NONE"),
        "ai_analysis":   r.get("ai_analysis"),
    }


def _ribbon_item_from_db(row: dict, signal: str, quality: int) -> dict:
    # row is already a plain dict (converted via .mappings().all())
    return {
        "symbol":       row["symbol"],
        "price":        row.get("price"),
        "sector":       row.get("sector", "Unknown"),
        "tier":         None,
        "total_score":  None,
        "source":       "ribbon_pass",
        "ribbon_signal":          signal,
        "ribbon_quality":         quality,
        "ema_spread_pct":         row.get("ema_spread_pct"),
        "ribbon_compression":     row.get("ribbon_compression", "NONE"),
        "bullish_stack":          row.get("bullish_stack", False),
        "bearish_stack":          row.get("bearish_stack", False),
        "compression_and_bullish": row.get("compression_and_bullish", False),
        "ribbon_position":        row.get("ribbon_position"),
        "ema8_slope":             row.get("ema8_slope"),
        "ribbon_periods_count":   7,
        "ema8":   row.get("ema8"),   "ema13": row.get("ema13"),
        "ema20":  row.get("ema20"),  "ema21": row.get("ema21"),
        "ema34":  row.get("ema34"),  "ema50": row.get("ema50"),
        "ema55":  row.get("ema55"),  "ema89": row.get("ema89"),
        "ema200": row.get("ema200"),
        "cmf_pctl":      row.get("cmf_pctl", 0),
        "anomaly_ratio": row.get("anomaly_ratio", 0),
        "bb_squeeze":    row.get("bb_squeeze", False),
        "bb_sqz_bars":   row.get("bb_sqz_bars", 0),
        "rs_score":      row.get("rs_score", 0),
        "rsi":           row.get("rsi"),
        "obv_strength":  row.get("obv_strength"),
        "obv_divergence": None,
        "earnings_risk": "NONE",
        "ai_analysis":   None,
    }


@app.get("/api/scan/ribbon")
async def get_ribbon_scanner(
    mode: str = "all",
    max_spread: float = 5.0,
    min_volume: int = 200000,
    bullish_only: bool = False,
):
    """
    EMA Ribbon Scanner — read-only, no new scan triggered.
    Merges two sources:
      1. Main scan results (tickers with anomaly_ratio >= 2x)
      2. ribbon_candidates table (compression setups, anomaly_ratio < 2x)

    mode: 'all' | 'compression' | 'breakout' | 'stack'
    """
    from database import get_ribbon_candidates

    scan = await get_latest_scan()
    main_results = scan.get("results", []) if scan else []

    # ETF/ETN/CEF/fund/leveraged/crypto exclusion (cached — fast after first call)
    exclusions = await _get_exclusion_set()

    def _is_etf(sym: str) -> bool:
        return sym.upper() in exclusions

    # SOURCE 2: ribbon candidates table (last 1 day)
    ribbon_rows = await get_ribbon_candidates(days_back=1)

    seen: set = set()
    all_items: list = []

    # Process main scan results
    for r in main_results:
        if _is_etf(r["symbol"]):
            continue
        ind        = r.get("indicators", {})
        score_data = r.get("score", {})
        symbol     = r["symbol"]

        spread  = ind.get("ema_spread_pct", 999.0)
        vol     = ind.get("today_vol", 0)
        comp    = ind.get("ribbon_compression", "NONE")
        bullish = ind.get("bullish_stack", False)
        bearish = ind.get("bearish_stack", False)
        cb      = ind.get("compression_and_bullish", False)
        anomaly = ind.get("anomaly_ratio", 0)

        if vol < min_volume:      continue
        if spread > max_spread:   continue
        if bullish_only and not bullish: continue
        if not _passes_mode(mode, comp, bullish, cb, anomaly): continue

        signal  = _ribbon_signal(cb, bullish, bearish, comp, anomaly)
        quality = _ribbon_quality(spread, signal, ind)
        if quality < 5:           continue

        seen.add(symbol)
        all_items.append(_ribbon_item_from_scan(r, ind, score_data, signal, quality))

    # Process ribbon_candidates (secondary pass — no volume spike)
    for row in ribbon_rows:
        symbol = row["symbol"]
        if symbol in seen:
            continue
        if _is_etf(symbol):
            continue

        spread  = row.get("ema_spread_pct", 999.0) or 999.0
        vol     = row.get("today_vol", 0) or 0
        comp    = row.get("ribbon_compression", "NONE") or "NONE"
        bullish = bool(row.get("bullish_stack", False))
        bearish = bool(row.get("bearish_stack", False))
        cb      = bool(row.get("compression_and_bullish", False))
        anomaly = row.get("anomaly_ratio", 0) or 0

        if vol < min_volume:      continue
        if spread > max_spread:   continue
        if bullish_only and not bullish: continue
        if not _passes_mode(mode, comp, bullish, cb, anomaly): continue

        signal  = _ribbon_signal(cb, bullish, bearish, comp, anomaly)
        quality = _ribbon_quality(spread, signal, row)
        if quality < 5:           continue

        seen.add(symbol)
        all_items.append(_ribbon_item_from_db(row, signal, quality))

    all_items.sort(key=lambda x: x["ribbon_quality"], reverse=True)

    summary = {
        "total":       len(all_items),
        "from_main":   sum(1 for x in all_items if x["source"] == "main_scan"),
        "from_ribbon": sum(1 for x in all_items if x["source"] == "ribbon_pass"),
        "breakouts":   sum(1 for x in all_items if x["ribbon_signal"] == "COMPRESSION_BREAKOUT"),
        "aligned":     sum(1 for x in all_items if x["ribbon_signal"] == "COMPRESSION_ALIGNED"),
        "stacks":      sum(1 for x in all_items if x.get("bullish_stack")),
        "compression": sum(1 for x in all_items if x.get("ribbon_compression") != "NONE"),
        "bearish":     sum(1 for x in all_items if x.get("bearish_stack")),
    }

    return {
        "results":    all_items,
        "count":      len(all_items),
        "summary":    summary,
        "scanned_at": scan.get("scanned_at") if scan else None,
        "filter": {
            "mode":         mode,
            "max_spread":   max_spread,
            "min_volume":   min_volume,
            "bullish_only": bullish_only,
        },
    }


@app.get("/api/scan/ignition")
async def get_ignition_scan(
    mode:         str  = "all",
    min_volume:   int  = 200_000,
    min_quality:  int  = 0,
    bullish_only: bool = False,
    max_results:  int  = 100,
    with_ai:      bool = False,
):
    """
    Unified Ignition Scanner — standalone pre-breakout detection engine.

    Combines five scoring layers (max 100 pts):
      ribbon=35  ignition=25  sector=15  hype=15  macro=10

    Unified signals:
      STRONG_BUY ≥85  |  BUY ≥65  |  WATCH ≥45  |  NEUTRAL ≥25  |  AVOID

    mode: 'all' | 'confirmed' | 'early' | 'watch'
      all       — all signals including NO_IGNITION
      confirmed — IGNITION_CONFIRMED only (ignition_quality ≥ 60)
      early     — IGNITION_CONFIRMED + EARLY_IGNITION
      watch     — all except NO_IGNITION

    with_ai: true → run Claude Haiku signal on top-10 (unified_score ≥ 65).
             Adds entry_thesis, key_risk, catalyst_type, confidence per result.
    """
    from scanner.ignition_engine import run_ignition_engine
    from database import get_ribbon_candidates

    max_results = min(max_results, 200)

    # SOURCE 1: main scan + EOD universe (merged, intraday takes priority)
    scan       = await get_latest_scan()
    eod_scan   = await get_latest_scan_by_type("massive_eod")
    main_res   = scan.get("results", [])     if scan     else []
    eod_res    = eod_scan.get("results", []) if eod_scan else []
    main_syms  = {r["symbol"] for r in main_res}
    combined   = main_res + [r for r in eod_res if r["symbol"] not in main_syms]

    # SOURCE 2: ribbon candidates (EMA compression setups, last 1 day)
    ribbon_rows = await get_ribbon_candidates(days_back=1)

    # Strip ETF / ETN / CEF / fund / leveraged / crypto
    exclusions  = await _get_exclusion_set()
    combined    = _strip_non_stocks(combined, exclusions)
    ribbon_rows = [r for r in ribbon_rows if r.get("symbol", "").upper() not in exclusions]

    result = await run_ignition_engine(
        main_results   = combined,
        ribbon_results = ribbon_rows,
        mode           = mode,
        min_volume     = min_volume,
        min_quality    = min_quality,
        bullish_only   = bullish_only,
        max_results    = max_results,
        with_ai        = with_ai,
    )

    scanned_at = (scan or eod_scan or {}).get("scanned_at") if (scan or eod_scan) else None

    return {
        **result,
        "scanned_at": scanned_at,
        "filter": {
            "mode":        mode,
            "min_volume":  min_volume,
            "min_quality": min_quality,
            "bullish_only": bullish_only,
            "max_results": max_results,
            "with_ai":     with_ai,
        },
    }


@app.get("/api/scan/new-pump")
async def get_new_pump_scan(
    min_score:  float = 0.0,
    label:      str   = "",
    sequence:   str   = "",
    max_results: int  = 200,
):
    """
    New Pump Engine — structured setup/trigger/confirmation view.
    Returns tickers from latest scan sorted by new_pump_score descending.
    Filters: min_score, label (e.g. NEW_PUMP_FIRE), sequence (e.g. FULL_FRI34_G4_B2).
    """
    scan     = await get_latest_scan()
    eod_scan = await get_latest_scan_by_type("massive_eod")
    main_res = scan.get("results", [])     if scan     else []
    eod_res  = eod_scan.get("results", []) if eod_scan else []
    main_syms = {r["symbol"] for r in main_res}
    combined  = main_res + [r for r in eod_res if r["symbol"] not in main_syms]

    exclusions = await _get_exclusion_set()
    combined   = _strip_non_stocks(combined, exclusions)

    out = []
    for r in combined:
        np = r.get("new_pump")
        if not np:
            continue
        score = np.get("new_pump_score", 0) or 0
        if score < min_score:
            continue
        if label and np.get("new_pump_label") != label:
            continue
        if sequence and np.get("new_pump_sequence_label") != sequence:
            continue
        out.append({
            "symbol":                  r.get("symbol"),
            "price":                   r.get("price"),
            "volume_today":            r.get("volume_today"),
            "tier":                    (r.get("score") or {}).get("tier"),
            "total_score":             (r.get("score") or {}).get("total_score"),
            # new pump fields
            "new_pump_score":          np.get("new_pump_score"),
            "new_pump_label":          np.get("new_pump_label"),
            "new_pump_sequence_label": np.get("new_pump_sequence_label"),
            "new_pump_setup_score":    np.get("new_pump_setup_score"),
            "new_pump_trigger_score":  np.get("new_pump_trigger_score"),
            "new_pump_confirm_score":  np.get("new_pump_confirm_score"),
            "new_pump_modifier_score": np.get("new_pump_modifier_score"),
            "has_l34":   np.get("has_l34"),
            "has_fri34": np.get("has_fri34"),
            "has_g4":    np.get("has_g4"),
            "has_b2":    np.get("has_b2"),
            "age_l34":   np.get("age_l34"),
            "age_fri34": np.get("age_fri34"),
            "age_g4":    np.get("age_g4"),
            "age_b2":    np.get("age_b2"),
        })

    _LABEL_ORDER = {
        "NEW_PUMP_FIRE": 0, "NEW_PUMP_STRONG": 1, "NEW_PUMP_SETUP": 2,
        "NEW_PUMP_TRIGGER_ONLY": 3, "NEW_PUMP_WEAK": 4, "NEW_PUMP_NONE": 5,
    }
    out.sort(key=lambda x: (
        _LABEL_ORDER.get(x["new_pump_label"] or "", 9),
        -(x["new_pump_score"] or 0),
    ))
    out = out[:min(max_results, 500)]

    scanned_at = (scan or eod_scan or {}).get("scanned_at") if (scan or eod_scan) else None
    return {
        "results":    out,
        "total":      len(out),
        "scanned_at": scanned_at,
        "filters":    {"min_score": min_score, "label": label, "sequence": sequence},
    }


@app.get("/api/scan/pump")
async def get_pump_scan(
    mode:         str  = "all",
    min_volume:   int  = 200_000,
    max_toxicity: int  = 80,
    min_quality:  int  = 0,
    bullish_only: bool = False,
    max_results:  int  = 100,
):
    """
    Pump Engine — Explosive / speculative mover detection.

    Separate from the main scanner. Scores velocity, volume wakeup, price
    behavior, theme context, and toxicity risk.  Never modifies main scanner
    tiers or total_score.

    Pump signals:
      PUMP_ACTIVE      — velocity + volume confirmed, price behavior positive
      PUMP_BUILDING    — velocity building, volume rising
      PUMP_EARLY       — early signs, incomplete confirmation
      PUMP_SPECULATIVE — speculative, lower conviction
      NO_PUMP_SIGNAL   — no meaningful pump signal

    mode: 'all' | 'active' | 'building' | 'early' | 'speculative'
    max_toxicity: 0–100; default 80 blocks only EXTREME toxicity
    min_quality: minimum pump_quality score (0–100)
    """
    from scanner.pump_engine import run_pump_engine
    from database import get_ribbon_candidates

    max_results = min(max_results, 200)

    # SOURCE 1: main scan + EOD universe (merged, intraday takes priority)
    scan       = await get_latest_scan()
    eod_scan   = await get_latest_scan_by_type("massive_eod")
    main_res   = scan.get("results", [])     if scan     else []
    eod_res    = eod_scan.get("results", []) if eod_scan else []
    main_syms  = {r["symbol"] for r in main_res}
    combined   = main_res + [r for r in eod_res if r["symbol"] not in main_syms]

    # SOURCE 2: ribbon candidates (EMA compression setups, last 1 day)
    ribbon_rows = await get_ribbon_candidates(days_back=1)

    # Strip ETF / ETN / CEF / fund / leveraged / crypto
    exclusions  = await _get_exclusion_set()
    combined    = _strip_non_stocks(combined, exclusions)
    ribbon_rows = [r for r in ribbon_rows if r.get("symbol", "").upper() not in exclusions]

    result = run_pump_engine(
        main_results   = combined,
        ribbon_results = ribbon_rows,
        mode           = mode,
        min_volume     = min_volume,
        max_toxicity   = max_toxicity,
        min_quality    = min_quality,
        bullish_only   = bullish_only,
        max_results    = max_results,
    )

    scanned_at = (scan or eod_scan or {}).get("scanned_at") if (scan or eod_scan) else None

    return {
        **result,
        "scanned_at": scanned_at,
        "filter": {
            "mode":         mode,
            "min_volume":   min_volume,
            "max_toxicity": max_toxicity,
            "min_quality":  min_quality,
            "bullish_only": bullish_only,
            "max_results":  max_results,
        },
    }


@app.get("/api/sector-performance/latest")
async def sector_performance_latest():
    """Return live Finviz sector performance (daily change%). Cached up to 4 hours."""
    from scanner.sector_performance import fetch_sector_performance
    data = await fetch_sector_performance()
    sorted_data = dict(
        sorted(data.items(), key=lambda x: x[1].get("change_pct", 0), reverse=True)
    )
    return sorted_data


@app.get("/api/sector-momentum")
async def sector_momentum():
    """Return sectors ranked by today's performance with trending flag."""
    from scanner.sector_performance import fetch_sector_performance_with_momentum
    from scanner.sector_map import FINVIZ_TO_GICS
    data = await fetch_sector_performance_with_momentum()
    # Enrich with GICS names
    enriched = {}
    for fv_name, d in data.items():
        enriched[fv_name] = {**d, "gics_name": FINVIZ_TO_GICS.get(fv_name, fv_name)}
    return dict(sorted(enriched.items(), key=lambda x: x[1].get("rank_1d", 99)))


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
                    "symbol":          sym,
                    "tier":            r.get("score", {}).get("tier"),
                    "score":           round(r.get("score", {}).get("total_score", 0), 1),
                    "price":           r.get("price"),
                    "price_change_pct": r.get("indicators", {}).get("price_change_pct", 0),
                    "cmf_pctl":        r.get("indicators", {}).get("cmf_pctl", 0),
                    "vol_ratio":       r.get("indicators", {}).get("anomaly_ratio", 0),
                    "sympathy":        r.get("sympathy", {}),
                    "industry":        r.get("industry", ""),
                    "sympathy_strength": r.get("sympathy_strength", "UNKNOWN"),
                    "setup_quality":   r.get("setup_quality", {}),
                })
    tickers_detail.sort(key=lambda x: x.get("score", 0), reverse=True)

    return {**data, "tickers_detail": tickers_detail}


# ─── Admin / Maintenance routes ───────────────────────────────────────────────

@app.get("/api/admin/test-massive")
async def admin_test_massive(symbol: str = "AAPL"):
    """
    Test the Massive/Polygon connection.
    Fetches a sample from grouped daily data + ticker details for one symbol.
    Also returns universe filter classification for the requested symbol.
    """
    from scanner.massive_data import (
        fetch_grouped_daily, fetch_ticker_details, fetch_ticker_type,
        get_last_trading_day, MASSIVE_API_KEY,
    )
    from scanner.stock_universe_filter import is_common_stock, get_universe_filter_reason
    if not MASSIVE_API_KEY:
        return {"error": "MASSIVE_API_KEY not set in environment", "api_key_set": False}

    target_date = get_last_trading_day(offset=1)

    # Fetch grouped daily (all US stocks in 1 call) and return a sample
    all_bars = await fetch_grouped_daily(target_date)
    sample_syms = sorted(all_bars.keys())[:5]
    sample = [{"symbol": s, **all_bars[s]} for s in sample_syms]

    # Also test ticker details for the requested symbol
    details = await fetch_ticker_details(symbol.upper())

    # Universe filter classification for the requested symbol
    ticker_type     = await fetch_ticker_type(symbol.upper())
    meta            = {"type": ticker_type} if ticker_type else {}
    filter_reason   = get_universe_filter_reason(meta) if ticker_type else "UNKNOWN_SECURITY_TYPE"
    is_stock        = is_common_stock(meta) if ticker_type else False

    # Check DB cache
    from database import get_sector_full_from_db
    cached = await get_sector_full_from_db(symbol.upper())

    return {
        "status":         "ok" if all_bars else "error",
        "api_key_set":    True,
        "target_date":    target_date,
        "universe_count": len(all_bars),
        "sample_tickers": len(sample),
        "sample":         sample,
        "ticker_details": details,
        "db_cached":      cached,
        "universe_filter": {
            "symbol":                symbol.upper(),
            "security_type":         ticker_type,
            "is_common_stock":       is_stock,
            "universe_filter_reason": filter_reason,
        },
    }


@app.get("/api/admin/universe-filter/check")
async def admin_universe_filter_check(symbols: str = "AAPL,SPY,TQQQ,GLD"):
    """
    Audit the universe filter classification for a comma-separated list of symbols.
    Returns security_type, is_common_stock, and universe_filter_reason for each.

    Example: /api/admin/universe-filter/check?symbols=AAPL,SPY,TQQQ,GLD,GBTC
    """
    from scanner.massive_data import fetch_ticker_type
    from scanner.stock_universe_filter import is_common_stock, get_universe_filter_reason

    sym_list = [s.strip().upper() for s in symbols.split(",") if s.strip()][:30]

    import asyncio as _asyncio
    type_results = await _asyncio.gather(
        *[fetch_ticker_type(s) for s in sym_list],
        return_exceptions=True,
    )

    output = []
    for sym, t in zip(sym_list, type_results):
        if isinstance(t, Exception):
            t = None
        meta   = {"type": t} if t else {}
        reason = get_universe_filter_reason(meta) if t else "UNKNOWN_SECURITY_TYPE"
        output.append({
            "symbol":                sym,
            "security_type":         t,
            "is_common_stock":       is_common_stock(meta) if t else False,
            "universe_filter_reason": reason,
        })

    included = [r for r in output if r["is_common_stock"]]
    excluded = [r for r in output if not r["is_common_stock"]]

    return {
        "checked":  len(output),
        "included": len(included),
        "excluded": len(excluded),
        "results":  output,
    }


@app.get("/api/admin/enrich-sectors")
async def admin_enrich_sectors(background_tasks: BackgroundTasks):
    """
    Manually trigger the Massive sector/industry enrichment job.
    Runs in background — rate limited to 1 call per 15s.
    Returns immediately with count of symbols queued.
    """
    from database import get_symbols_needing_enrichment
    missing = await get_symbols_needing_enrichment(limit=200)

    async def _run():
        from scheduler import enrich_sector_cache
        await enrich_sector_cache()

    background_tasks.add_task(_run)
    return {
        "status":  "started",
        "queued":  len(missing),
        "message": f"Enriching {len(missing)} symbols in background (1 per 15s)",
    }


@app.get("/api/admin/run-universe-scan")
async def admin_run_universe_scan(background_tasks: BackgroundTasks, date: str = None):
    """
    Manually trigger the Massive EOD universe scan.
    Runs in background — fetches all US stocks and scores top 600.
    Returns immediately; check /api/scan/universe/latest for results.
    """
    from scanner.massive_data import MASSIVE_API_KEY
    if not MASSIVE_API_KEY:
        return {"error": "MASSIVE_API_KEY not set — cannot run universe scan"}

    async def _run():
        from scanner.universe_scan import run_universe_scan
        await run_universe_scan(target_date=date)

    from scanner.massive_data import get_last_trading_day
    resolved_date = date or get_last_trading_day(offset=0)

    background_tasks.add_task(_run)
    return {
        "status":      "started",
        "target_date": resolved_date,
        "message":     f"Universe scan running in background for {resolved_date}. Check /api/scan/universe/latest for results.",
    }


@app.get("/api/admin/universe-scan/status")
async def admin_universe_scan_status():
    """
    Live progress of the universe scan.
    Poll every 5s while running=true.
    Returns phase, candidates_done/total, FIRE/ARM counts, elapsed/ETA.
    """
    from scanner.universe_scan import get_progress
    return get_progress()


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


# ─── Macro Events — Trump News Bias Layer (Version Alpha) ────────────────────
#
# Read-only contextual intelligence. NEVER modifies scores, tiers, or rankings.
# Display-only layer for informational market context.

@app.get("/api/events/trump/latest")
async def trump_events_latest(limit: int = 20):
    """
    Latest Trump-related macro events (most recent first).
    Returns up to `limit` events regardless of age.
    """
    events = await get_macro_events_latest(limit=min(limit, 50))
    return {"events": events, "count": len(events)}


@app.get("/api/events/trump/history")
async def trump_events_history(days: int = 7, limit: int = 100):
    """
    Historical Trump macro events from the last N days.
    Useful for reviewing the event timeline.
    """
    events = await get_macro_events_history(days=min(days, 30), limit=min(limit, 200))
    return {"events": events, "count": len(events), "days": days}


@app.get("/api/events/trump/active-bias")
async def trump_active_bias(max_age_days: int = 3):
    """
    Aggregated active macro bias from recent Trump events (last 1–3 days).
    Returns:
      - overall_market_bias: BULLISH / BEARISH / RISK_OFF / MIXED / NEUTRAL
      - overall_volatility: LOW / MEDIUM / HIGH / VERY_HIGH
      - top_bullish_sectors, top_bearish_sectors
      - active_classes: which event categories are active
      - regime_summary: human-readable sentence
      - recent_events: raw event list feeding into the bias
    """
    from news.trump_news import compute_active_bias

    active_events = await get_macro_events_active(max_age_days=min(max_age_days, 7))
    bias = compute_active_bias(active_events, max_age_days=min(max_age_days, 7))
    return {
        **bias,
        "recent_events": active_events,
    }


@app.post("/api/events/trump/refresh")
async def trump_events_refresh(background_tasks: BackgroundTasks):
    """
    Manually trigger a Trump news fetch + classify + upsert cycle.
    Runs in background; returns immediately with {ok: true, message: str}.
    """
    async def _do_refresh():
        try:
            from news.trump_news import fetch_and_classify_events
            logger.info("Manual Trump news refresh triggered")
            events = await fetch_and_classify_events(use_manual=True)
            inserted = await upsert_macro_events(events)
            logger.info(f"Trump news refresh: {len(events)} classified, {inserted} new")
        except Exception as e:
            logger.error(f"Trump news refresh failed: {e}", exc_info=True)

    background_tasks.add_task(_do_refresh)
    return {"ok": True, "message": "News refresh started in background"}


# ─── Admin ─────────────────────────────────────────────────────────────────────

@app.get("/api/admin/rotate-data")
async def admin_rotate_data():
    """Manually trigger data rotation (same logic as the weekly Sunday job)."""
    from database import rotate_old_data
    deleted = await rotate_old_data()
    total = sum(deleted.values())
    return {"ok": True, "total_deleted": total, "breakdown": deleted}


# ─── Historical Replay Layer ──────────────────────────────────────────────────
# Research-only mode. Completely isolated from live production data.
# Results stored in replay_* tables only. Live scan/journal never touched.
#
# LIVE vs REPLAY separation:
#   - All replay data is under /api/replay/ — never mixed into /api/scan/
#   - Replay runs use a separate progress tracker (_replay_progress)
#   - No replay data is written to Scan, ScanCandidate, or Journal tables
#
# Future leakage prevention:
#   - fetch_candles_massive(as_of_date=...) cuts data at the scan date
#   - grouped_daily is fetched for the exact as_of_date
#   - No live market_regime or sector_performance data used during replay

@app.post("/api/replay/run")
async def replay_run(body: dict, background_tasks: BackgroundTasks):
    """
    Start a historical replay run.

    Single date:
        {"as_of_date": "2026-03-05"}
        {"as_of_date": "2026-03-05", "universe_mode": "approx"}

    Date range:
        {"start_date": "2026-03-01", "end_date": "2026-03-31"}
        {"start_date": "2026-03-01", "end_date": "2026-03-31", "universe_mode": "approx"}

    Returns immediately with run_id. Poll /api/replay/status for progress.
    """
    from replay.replay_engine import get_replay_progress

    # Guard: one replay at a time
    prog = get_replay_progress()
    if prog.get("running"):
        raise HTTPException(
            status_code=409,
            detail=f"Replay already running (run_id={prog.get('run_id')}). "
                   "Wait for it to finish or check /api/replay/status."
        )

    universe_mode = body.get("universe_mode", "approx")
    as_of_date    = body.get("as_of_date")
    start_date    = body.get("start_date")
    end_date      = body.get("end_date")

    # Validate inputs
    if as_of_date:
        try:
            from datetime import date as _d
            _d.fromisoformat(as_of_date)
        except ValueError:
            raise HTTPException(400, detail=f"Invalid as_of_date: {as_of_date!r} (use YYYY-MM-DD)")

        async def _run_single():
            try:
                from replay.replay_engine import run_single_day_replay
                await run_single_day_replay(as_of_date, universe_mode=universe_mode)
            except Exception as e:
                logger.error(f"Replay single-day failed: {e}", exc_info=True)

        background_tasks.add_task(_run_single)
        return {
            "ok":           True,
            "mode":         "single_day",
            "as_of_date":   as_of_date,
            "universe_mode":universe_mode,
            "message":      f"Replay started for {as_of_date}. Poll /api/replay/status for progress.",
        }

    elif start_date and end_date:
        try:
            from datetime import date as _d
            _d.fromisoformat(start_date)
            _d.fromisoformat(end_date)
        except ValueError:
            raise HTTPException(400, detail="Invalid start_date or end_date (use YYYY-MM-DD)")

        if start_date > end_date:
            raise HTTPException(400, detail="start_date must be <= end_date")

        async def _run_range():
            try:
                from replay.replay_engine import run_date_range_replay
                await run_date_range_replay(start_date, end_date, universe_mode=universe_mode)
            except Exception as e:
                logger.error(f"Replay date-range failed: {e}", exc_info=True)

        background_tasks.add_task(_run_range)
        return {
            "ok":           True,
            "mode":         "date_range",
            "start_date":   start_date,
            "end_date":     end_date,
            "universe_mode":universe_mode,
            "message":      f"Replay started for {start_date}→{end_date}. Poll /api/replay/status.",
        }

    else:
        raise HTTPException(
            400,
            detail="Provide either 'as_of_date' (single day) or 'start_date'+'end_date' (range)."
        )


@app.get("/api/replay/status")
async def replay_status():
    """Live progress of the currently running (or last completed) replay."""
    from replay.replay_engine import get_replay_progress
    return get_replay_progress()


@app.get("/api/replay/history")
async def replay_history(limit: int = 20):
    """List of past replay runs, newest first."""
    runs = await get_replay_history(limit=min(limit, 50))
    return {"runs": runs, "count": len(runs)}


@app.get("/api/replay/{run_id}")
async def replay_get_run(run_id: int):
    """Full detail for one replay run."""
    run = await get_replay_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Replay run {run_id} not found")
    return run


@app.get("/api/replay/{run_id}/candidates")
async def replay_get_candidates(run_id: int, limit: int = 500):
    """All signal candidates found during a replay run, sorted by score."""
    run = await get_replay_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Replay run {run_id} not found")
    candidates = await get_replay_candidates(run_id, limit=min(limit, 1000))
    return {"run_id": run_id, "candidates": candidates, "count": len(candidates)}


@app.get("/api/replay/{run_id}/outcomes")
async def replay_get_outcomes(run_id: int):
    """Forward outcome rows for all candidates in a replay run."""
    run = await get_replay_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Replay run {run_id} not found")
    outcomes = await get_replay_outcomes(run_id)
    return {"run_id": run_id, "outcomes": outcomes, "count": len(outcomes)}


@app.get("/api/replay/{run_id}/missed")
async def replay_get_missed(run_id: int):
    """Missed mover analysis for a replay run."""
    run = await get_replay_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Replay run {run_id} not found")
    missed = await get_replay_missed_movers(run_id)
    return {"run_id": run_id, "missed_movers": missed, "count": len(missed)}


@app.get("/api/replay/{run_id}/summary")
async def replay_get_summary(run_id: int):
    """
    Aggregated summary for one replay run: outcome distribution,
    avg returns by horizon, best/worst setups, missed movers count.
    """
    run = await get_replay_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Replay run {run_id} not found")

    candidates = await get_replay_candidates(run_id, limit=5000)
    outcomes   = await get_replay_outcomes(run_id)
    missed     = await get_replay_missed_movers(run_id)

    # Aggregate by horizon
    from collections import defaultdict
    by_horizon: dict = defaultdict(list)
    for o in outcomes:
        if o.get("return_pct") is not None:
            by_horizon[o["horizon"]].append(o["return_pct"])

    avg_returns = {}
    for h, vals in by_horizon.items():
        avg_returns[h] = round(sum(vals) / len(vals), 2) if vals else None

    # Outcome label distribution (5d only)
    label_dist: dict = defaultdict(int)
    for o in outcomes:
        if o.get("horizon") == "5d" and o.get("outcome_label"):
            label_dist[o["outcome_label"]] += 1

    # Best / worst 5 by 5d return
    five_d = [o for o in outcomes if o.get("horizon") == "5d" and o.get("return_pct") is not None]
    five_d.sort(key=lambda x: x["return_pct"], reverse=True)
    best5  = [{"symbol": o["symbol"], "return_5d": o["return_pct"], "label": o.get("outcome_label")} for o in five_d[:5]]
    worst5 = [{"symbol": o["symbol"], "return_5d": o["return_pct"], "label": o.get("outcome_label")} for o in five_d[-5:]]

    # Tier distribution of candidates
    tier_dist: dict = defaultdict(int)
    for c in candidates:
        tier_dist[c.get("tier", "?")] += 1

    return {
        "run_id":            run_id,
        "run":               run,
        "total_candidates":  len(candidates),
        "total_outcomes":    len(outcomes),
        "missed_movers":     len(missed),
        "avg_returns":       avg_returns,
        "outcome_labels":    dict(label_dist),
        "tier_distribution": dict(tier_dist),
        "best_5":            best5,
        "worst_5":           worst5,
    }


# ── Research Bundle endpoints ─────────────────────────────────────────────────
# Read-only reporting layer. Never modifies live scanner, scoring, or journal.

@app.get("/api/replay/{run_id}/research-bundle")
async def replay_research_bundle(run_id: int):
    """
    Build and return the full structured research bundle for a replay run.
    Covers: summary, performance by bucket, false positives, missed movers,
    pattern review, and suggested experiments (proposals only).
    """
    run = await get_replay_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Replay run {run_id} not found")

    from replay.research_bundle import build_research_bundle
    try:
        bundle = await build_research_bundle(run_id)
        return bundle
    except Exception as exc:
        logger.error(f"[BUNDLE] run_id={run_id} build failed: {exc}", exc_info=True)
        raise HTTPException(500, detail=f"Bundle build failed: {str(exc)[:200]}")


@app.get("/api/replay/{run_id}/research-bundle/markdown")
async def replay_research_bundle_markdown(run_id: int):
    """
    Return the research bundle as a human-readable Markdown report.
    Suitable for pasting into AI chat or saving as a .md file.
    """
    from fastapi.responses import PlainTextResponse
    run = await get_replay_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Replay run {run_id} not found")

    from replay.research_bundle import build_research_bundle, render_research_bundle_markdown
    try:
        bundle   = await build_research_bundle(run_id)
        markdown = render_research_bundle_markdown(bundle)
        return PlainTextResponse(content=markdown, media_type="text/markdown")
    except Exception as exc:
        logger.error(f"[BUNDLE/MD] run_id={run_id} failed: {exc}", exc_info=True)
        raise HTTPException(500, detail=f"Markdown render failed: {str(exc)[:200]}")


@app.get("/api/replay/{run_id}/research-bundle/download")
async def replay_research_bundle_download(run_id: int, format: str = "json"):
    """
    Download the research bundle as a JSON or Markdown file.
    ?format=json  (default) — downloads bundle.json
    ?format=markdown         — downloads bundle.md
    """
    import json as _json
    from fastapi.responses import Response
    run = await get_replay_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Replay run {run_id} not found")

    from replay.research_bundle import build_research_bundle, render_research_bundle_markdown
    try:
        bundle = await build_research_bundle(run_id)
        if format == "markdown":
            content  = render_research_bundle_markdown(bundle)
            filename = f"replay_{run_id}_research_bundle.md"
            return Response(
                content=content,
                media_type="text/markdown",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
        else:
            content  = _json.dumps(bundle, indent=2, default=str)
            filename = f"replay_{run_id}_research_bundle.json"
            return Response(
                content=content,
                media_type="application/json",
                headers={"Content-Disposition": f'attachment; filename="{filename}"'},
            )
    except Exception as exc:
        logger.error(f"[BUNDLE/DL] run_id={run_id} failed: {exc}", exc_info=True)
        raise HTTPException(500, detail=f"Download failed: {str(exc)[:200]}")


@app.delete("/api/replay/{run_id}")
async def delete_replay_run_endpoint(run_id: int):
    """
    Permanently delete a replay run and all its linked child records.

    Cascade order:
        replay_signal_candidates → replay_outcomes → replay_missed_movers
        → replay_runs

    Returns deleted row counts per table.
    """
    from database import delete_replay_run
    try:
        counts = await delete_replay_run(run_id)
    except ValueError:
        raise HTTPException(404, detail=f"Replay run {run_id} not found")
    except Exception as exc:
        logger.error("delete_replay_run run_id=%s error: %s", run_id, exc)
        raise HTTPException(500, detail=str(exc))
    return {
        "ok":      True,
        "run_id":  run_id,
        "deleted": counts,
    }


# ─────────────────────────────────────────────────────────────────────────────
#  4× PUMP STUDY API  —  Phase 4
#  All endpoints are replay-only.  No live scanner logic is touched.
# ─────────────────────────────────────────────────────────────────────────────

def _build_pump_study_markdown(run: dict, episodes: list[dict]) -> str:
    """
    Deterministic markdown summary of a pump study run.
    Pure data — no AI, no external calls.
    """
    lines: list[str] = [
        f"# 4× Pump Study — Run {run['id']}",
        "",
        f"**Date range:** {run['start_date']} → {run['end_date']}  ",
        f"**Status:** {run['status']}  ",
        f"**Window:** {run['window_days']} trading days  "
        f"|  **Min multiple:** {run['min_multiple']}×  ",
        f"**Symbols scanned:** {run.get('symbols_scanned', 0)}  "
        f"|  **Episodes:** {run.get('episode_count', 0)}  ",
        f"**Snapshots:** {run.get('snapshot_count', 0)}  "
        f"|  **Events:** {run.get('event_count', 0)}  ",
        "",
    ]

    if run.get("error_message"):
        lines += [f"> **Error:** {run['error_message']}", ""]
    if run.get("notes"):
        lines += [f"> {run['notes']}", ""]

    # Pump family distribution
    family_counts: dict[str, int] = {}
    for ep in episodes:
        fam = ep.get("pump_type") or "UNKNOWN"
        family_counts[fam] = family_counts.get(fam, 0) + 1

    if family_counts:
        lines += ["## Pump Family Distribution", "", "| Family | Count |", "|---|---|"]
        for fam, cnt in sorted(family_counts.items(), key=lambda x: -x[1]):
            lines.append(f"| {fam} | {cnt} |")
        lines.append("")

    # Episode table (capped at 200 rows for readability)
    if episodes:
        lines += [
            "## Canonical Episodes",
            "",
            "| # | Symbol | Family | Start | Peak | Multiple | Days | "
            "Drawdown | Ribbon | Ignition | Wyckoff |",
            "|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        shown = episodes[:200]
        for i, ep in enumerate(shown, 1):
            dd = ep.get("max_drawdown_before_peak")
            dd_str = f"{dd:.1f}%" if dd is not None else "—"
            lines.append(
                f"| {i} | **{ep['symbol']}** | {ep.get('pump_type') or '?'} "
                f"| {ep['pump_start_date']} | {ep['pump_peak_date']} "
                f"| {ep['pump_multiple']:.2f}× | {ep.get('days_to_peak') or '?'} "
                f"| {dd_str} "
                f"| {'✓' if ep.get('had_ribbon') else '—'} "
                f"| {'✓' if ep.get('had_ignition') else '—'} "
                f"| {ep.get('strongest_wyckoff_state') or '—'} |"
            )
        if len(episodes) > 200:
            lines.append(
                f"| — | *(+{len(episodes) - 200} more — use /export?format=json)* "
                "| | | | | | | | | |"
            )
        lines.append("")

    lines += [
        "---",
        f"*Pump Scout deterministic export — no AI. Run ID: {run['id']}.  "
        f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}*",
    ]
    return "\n".join(lines)


# ── 1. Launch a new pump study run ────────────────────────────────────────────

@app.post("/api/replay/pump-study/run")
async def pump_study_start(body: dict, background_tasks: BackgroundTasks):
    """
    Launch a new 4× pump study background run.

    Body (JSON):
        start_date     str    YYYY-MM-DD  required
        end_date       str    YYYY-MM-DD  required
        window_days    int    default 14
        min_multiple   float  default 4.0
        universe_limit int    default 0   (0 = no limit)

    Returns immediately with run_id.
    Poll GET /api/replay/pump-study/{run_id} for progress.
    """
    from datetime import date as _d
    from database import create_pump_study_run
    from replay.pump_study_engine import get_pump_study_progress

    prog = get_pump_study_progress()
    if prog.get("running"):
        raise HTTPException(
            status_code=409,
            detail=(
                f"A pump study is already running (run_id={prog.get('run_id')}). "
                "Wait for it to finish or check its status."
            ),
        )

    start_date = body.get("start_date")
    end_date   = body.get("end_date")
    if not start_date or not end_date:
        raise HTTPException(400, detail="start_date and end_date are required")

    try:
        _d.fromisoformat(start_date)
        _d.fromisoformat(end_date)
    except ValueError:
        raise HTTPException(400, detail="Invalid date format — use YYYY-MM-DD")

    if start_date > end_date:
        raise HTTPException(400, detail="start_date must be <= end_date")

    params = {
        "start_date":     start_date,
        "end_date":       end_date,
        "window_days":    int(body.get("window_days",    14)),
        "min_multiple":   float(body.get("min_multiple", 4.0)),
        "universe_limit": int(body.get("universe_limit", 0)),
    }

    run_id = await create_pump_study_run(params)

    async def _run_bg():
        try:
            from replay.pump_study_engine import run_pump_study
            await run_pump_study(run_id, params)
        except Exception as exc:
            logger.error(
                f"[PUMP_STUDY] run_id={run_id} background task failed: {exc}",
                exc_info=True,
            )

    background_tasks.add_task(_run_bg)

    return {
        "ok":      True,
        "run_id":  run_id,
        "status":  "running",
        "params":  params,
        "message": (
            f"Pump study launched (run_id={run_id}). "
            f"Poll GET /api/replay/pump-study/{run_id} for live progress."
        ),
    }


# ── 2. List all pump study runs ───────────────────────────────────────────────

@app.get("/api/replay/pump-study/runs")
async def pump_study_list_runs(limit: int = 20):
    """
    List all pump study runs, most recent first.
    Each row includes status, counts, and date range.
    """
    from database import get_pump_study_runs
    runs = await get_pump_study_runs(limit=limit)
    return {"ok": True, "runs": runs, "count": len(runs)}


# ── 3. Run metadata + live progress ──────────────────────────────────────────

@app.get("/api/replay/pump-study/{run_id}")
async def pump_study_run_detail(run_id: int):
    """
    Run metadata, counts, and live progress (if run is still active).

    Response shape:
        run:      PumpStudyRun fields
        progress: live in-memory progress dict (only when this run is active)
    """
    from database import get_pump_study_run
    from replay.pump_study_engine import get_pump_study_progress

    run = await get_pump_study_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Pump study run {run_id} not found")

    prog = get_pump_study_progress()
    progress = prog if prog.get("run_id") == run_id else None

    return {"ok": True, "run": run, "progress": progress}


# ── 4. Canonical episodes ─────────────────────────────────────────────────────

@app.get("/api/replay/pump-study/{run_id}/episodes")
async def pump_study_episodes(
    run_id:       int,
    symbol:       Optional[str]   = None,
    pump_type:    Optional[str]   = None,
    min_multiple: Optional[float] = None,
    caught_only:  bool = False,
    missed_only:  bool = False,
    limit:        int  = 200,
):
    """
    List canonical pump episodes for a run.

    Query params:
        symbol        ticker filter (case-insensitive)
        pump_type     family label filter (e.g. ACCUMULATION_TO_EXPANSION)
        min_multiple  minimum pump multiple
        caught_only   only scanner-flagged episodes
        missed_only   only episodes NOT flagged by scanner
        limit         max rows (default 200)
    """
    from database import get_pump_study_run, get_pump_episodes

    run = await get_pump_study_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Run {run_id} not found")

    episodes = await get_pump_episodes(
        run_id,
        limit        = min(limit, 2000),
        symbol       = symbol.upper() if symbol else None,
        pump_type    = pump_type,
        min_multiple = min_multiple,
        caught_only  = caught_only,
        missed_only  = missed_only,
    )
    return {"ok": True, "run_id": run_id, "episodes": episodes, "count": len(episodes)}


# ── 5. Episode detail (summary + snapshots + events + cluster) ────────────────

@app.get("/api/replay/pump-study/{run_id}/episodes/{episode_id}")
async def pump_study_episode_detail(run_id: int, episode_id: int):
    """
    Full episode detail for one canonical episode.

    Response shape:
        episode:   PumpEpisode fields (enriched with pump_type, features)
        snapshots: all daily PRE/PUMP/POST snapshots (ordered by date)
        events:    all timeline milestone events (ordered by date)
        cluster:   cluster metadata for this episode
    """
    from database import (
        get_pump_study_run,
        get_pump_episode,
        get_pump_episode_snapshots,
        get_pump_episode_events,
        get_pump_clusters,
        get_pump_cluster_detections,
    )

    run = await get_pump_study_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Run {run_id} not found")

    episode = await get_pump_episode(episode_id)
    if not episode or episode.get("run_id") != run_id:
        raise HTTPException(404, detail=f"Episode {episode_id} not found in run {run_id}")

    snapshots = await get_pump_episode_snapshots(episode_id)
    events    = await get_pump_episode_events(episode_id)

    clusters = await get_pump_clusters(run_id)
    cluster  = next(
        (c for c in clusters if c.get("canonical_episode_id") == episode_id), None
    )

    # Enrich cluster with its raw detection rows
    if cluster:
        cluster["raw_detections"] = await get_pump_cluster_detections(
            run_id, cluster["cluster_id"]
        )

    return {
        "ok":       True,
        "episode":  episode,
        "snapshots": snapshots,
        "events":   events,
        "cluster":  cluster,
    }


# ── 6. Daily snapshots (run-level, with filters) ──────────────────────────────

@app.get("/api/replay/pump-study/{run_id}/daily-snapshots")
async def pump_study_daily_snapshots(
    run_id:     int,
    episode_id: Optional[int] = None,
    phase:      Optional[str] = None,
    limit:      int = 5000,
):
    """
    Daily PRE/PUMP/POST indicator snapshots for a run (or one episode).

    Query params:
        episode_id   filter to a specific episode
        phase        PRE | PUMP | POST
        limit        max rows (default 5000)
    """
    from database import get_pump_study_run, get_run_snapshots

    run = await get_pump_study_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Run {run_id} not found")

    if phase and phase.upper() not in ("PRE", "PUMP", "POST"):
        raise HTTPException(400, detail="phase must be PRE, PUMP, or POST")

    snapshots = await get_run_snapshots(
        run_id,
        episode_id = episode_id,
        phase      = phase.upper() if phase else None,
        limit      = min(limit, 20000),
    )
    return {
        "ok":        True,
        "run_id":    run_id,
        "snapshots": snapshots,
        "count":     len(snapshots),
    }


# ── 7. Timeline milestone events ──────────────────────────────────────────────

@app.get("/api/replay/pump-study/{run_id}/timeline")
async def pump_study_timeline(run_id: int, episode_id: Optional[int] = None):
    """
    Timeline milestone events for a run (or one episode).

    Query params:
        episode_id   filter to a specific episode
    """
    from database import get_pump_study_run, get_pump_study_timeline

    run = await get_pump_study_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Run {run_id} not found")

    events = await get_pump_study_timeline(run_id, episode_id=episode_id)
    return {
        "ok":       True,
        "run_id":   run_id,
        "events":   events,
        "count":    len(events),
    }


# ── 8. Cluster mapping ────────────────────────────────────────────────────────

@app.get("/api/replay/pump-study/{run_id}/clusters")
async def pump_study_clusters(run_id: int):
    """
    Raw detection clustering results — one row per cluster per symbol.
    Each cluster maps to one canonical episode via canonical_episode_id.
    Raw detections are nested under each cluster for full auditability.
    """
    from database import (
        get_pump_study_run,
        get_pump_clusters,
        get_pump_episode_detections,
    )

    run = await get_pump_study_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Run {run_id} not found")

    clusters = await get_pump_clusters(run_id)
    raw_dets = await get_pump_episode_detections(run_id)

    # Index raw detections by cluster_id for O(1) grouping
    det_by_cluster: dict[str, list] = {}
    for d in raw_dets:
        cid = d.get("cluster_id")
        if cid:
            det_by_cluster.setdefault(cid, []).append(d)

    for cl in clusters:
        cl["raw_detections"] = det_by_cluster.get(cl["cluster_id"], [])

    return {
        "ok":             True,
        "run_id":         run_id,
        "clusters":       clusters,
        "cluster_count":  len(clusters),
        "raw_det_count":  len(raw_dets),
    }


# ── 9. Comparison groups + members ───────────────────────────────────────────

@app.get("/api/replay/pump-study/{run_id}/comparisons")
async def pump_study_comparisons(run_id: int):
    """
    Comparison groups with aggregate stats and individual member rows.

    Groups:
        4x_pump       all canonical episodes
        normal_winner sub-4x moves from the same symbol universe
        false_positive episodes with severe POST reversal
        missed_mover  universe symbols with no 4x detection

    Response shape:
        groups[].stats    aggregate distribution stats (mean/median/p25/p75/p90)
        groups[].members  individual member rows with features_json
    """
    from database import (
        get_pump_study_run,
        get_pump_comparison_groups,
        get_pump_comparison_members,
    )

    run = await get_pump_study_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Run {run_id} not found")

    groups  = await get_pump_comparison_groups(run_id)
    members = await get_pump_comparison_members(run_id)

    # Nest members under their group by group_name
    members_by_group: dict[str, list] = {}
    for m in members:
        members_by_group.setdefault(m["group_name"], []).append(m)

    for g in groups:
        g["members"] = members_by_group.get(g["group_name"], [])

    return {
        "ok":            True,
        "run_id":        run_id,
        "groups":        groups,
        "total_members": len(members),
    }


# ── 10. Export ────────────────────────────────────────────────────────────────

@app.get("/api/replay/pump-study/{run_id}/export")
async def pump_study_export(run_id: int, format: str = "json"):
    """
    Download a pump study export.

    ?format=json      Full structured JSON bundle (run + episodes + clusters +
                      comparison groups + timeline events).
                      Note: daily snapshots are large; fetch them separately via
                      /daily-snapshots if needed.
    ?format=csv       Flat CSV of canonical episodes (one row per episode).
    ?format=markdown  Deterministic markdown summary — no AI, no external calls.
    """
    from fastapi.responses import Response
    from database import (
        get_pump_study_run,
        get_pump_episodes,
        get_pump_clusters,
        get_pump_comparison_groups,
        get_pump_comparison_members,
        get_pump_study_timeline,
    )

    run = await get_pump_study_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Run {run_id} not found")

    fmt = format.lower()
    if fmt not in ("json", "csv", "markdown"):
        raise HTTPException(400, detail="format must be json, csv, or markdown")

    episodes = await get_pump_episodes(run_id, limit=10000)

    # ── CSV ───────────────────────────────────────────────────────────────────
    if fmt == "csv":
        fieldnames = [
            "id", "symbol", "pump_type",
            "pump_start_date", "pump_peak_date", "pump_window_days",
            "start_price", "peak_price",
            "pump_multiple", "pump_return_pct",
            "days_to_peak", "days_to_double", "max_drawdown_before_peak",
            "had_ribbon", "had_ignition",
            "strongest_wyckoff_state", "max_volume_anomaly", "largest_gap_pct",
            "was_in_universe", "was_flagged_by_scanner",
            "sector", "industry",
        ]
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(episodes)
        return Response(
            content=buf.getvalue(),
            media_type="text/csv",
            headers={
                "Content-Disposition":
                    f'attachment; filename="pump_study_{run_id}_episodes.csv"'
            },
        )

    # ── Markdown ──────────────────────────────────────────────────────────────
    if fmt == "markdown":
        content = _build_pump_study_markdown(run, episodes)
        return Response(
            content=content,
            media_type="text/markdown",
            headers={
                "Content-Disposition":
                    f'attachment; filename="pump_study_{run_id}_summary.md"'
            },
        )

    # ── JSON (full structured bundle) ────────────────────────────────────────
    clusters = await get_pump_clusters(run_id)
    groups   = await get_pump_comparison_groups(run_id)
    members  = await get_pump_comparison_members(run_id)
    timeline = await get_pump_study_timeline(run_id)

    bundle = {
        "export_type":        "pump_study_4x",
        "run":                run,
        "episodes":           episodes,
        "clusters":           clusters,
        "comparison_groups":  groups,
        "comparison_members": members,
        "timeline_events":    timeline,
        "note":               (
            "Daily snapshots omitted from JSON export (can be large). "
            f"Fetch per episode via /api/replay/pump-study/{run_id}/daily-snapshots"
            "?episode_id=<id>"
        ),
        "exported_at": datetime.utcnow().isoformat() + "Z",
    }
    return Response(
        content=json.dumps(bundle, indent=2, default=str),
        media_type="application/json",
        headers={
            "Content-Disposition":
                f'attachment; filename="pump_study_{run_id}_full.json"'
        },
    )


@app.delete("/api/replay/pump-study/{run_id}")
async def delete_pump_study_run_endpoint(run_id: int):
    """
    Permanently delete a pump-study run and all its linked child records.

    Cascade order:
        pump_episode_snapshots → pump_episode_events → pump_episode_detections
        → pump_comparison_members → pump_comparison_groups → pump_clusters
        → pump_episodes → pump_study_ai_summaries → pump_study_runs

    Returns deleted row counts per table.
    """
    from database import delete_pump_study_run
    try:
        counts = await delete_pump_study_run(run_id)
    except ValueError:
        raise HTTPException(404, detail=f"Pump study run {run_id} not found")
    except Exception as exc:
        logger.error("delete_pump_study_run run_id=%s error: %s", run_id, exc)
        raise HTTPException(500, detail=str(exc))
    return {
        "ok":      True,
        "run_id":  run_id,
        "deleted": counts,
    }


@app.delete("/api/replay/raw-pattern-study/{run_id}")
async def delete_raw_pattern_study_run_endpoint(run_id: int):
    """
    Permanently delete a raw-pattern-study run and all its child records.

    Cascade order:
        raw_pattern_comparison_members → raw_pattern_comparisons
        → raw_pattern_episode_features → raw_pattern_daily_features
        → raw_pattern_ai_summaries → raw_pattern_runs
    """
    from database import delete_raw_pattern_run
    try:
        counts = await delete_raw_pattern_run(run_id)
    except ValueError:
        raise HTTPException(404, detail=f"Raw pattern run {run_id} not found")
    except Exception as exc:
        logger.error("delete_raw_pattern_run run_id=%s error: %s", run_id, exc)
        raise HTTPException(500, detail=str(exc))
    return {
        "ok":      True,
        "run_id":  run_id,
        "deleted": counts,
    }


async def _build_research_context_text(run_id: int) -> str:
    """
    Build a compact, AI-prompt-ready research context string from a completed
    Raw Pattern Study run.  Returns empty string on any failure.
    """
    from collections import Counter
    from database import (
        get_raw_pattern_run,
        get_raw_pattern_episode_features,
        get_raw_pattern_comparisons,
        get_raw_pattern_ai_summary,
    )
    from replay.pump_study_engine import extract_top_schemes, generate_engine_patch_plan

    try:
        run = await get_raw_pattern_run(run_id)
        if not run or run.get("status") != "complete":
            return ""

        episodes = await get_raw_pattern_episode_features(run_id, limit=2000)
        comps    = await get_raw_pattern_comparisons(run_id)

        group_counts = dict(Counter(
            ep.get("group_type") for ep in episodes if ep.get("group_type")
        ))
        schemes  = extract_top_schemes(episodes).get("schemes", [])[:5]
        verdicts = generate_engine_patch_plan(comps).get("feature_verdicts", [])

        lines = [
            f"=== RAW PATTERN STUDY CONTEXT (Run #{run_id}, "
            f"{run.get('start_date')} to {run.get('end_date')}, {len(episodes)} episodes) ===",
            "SAMPLE: " + ", ".join(f"{k}={v}" for k, v in sorted(group_counts.items()))
            + " (missed_mover=excluded/no-anchor)",
        ]

        if schemes:
            lines.append("\nTOP DISCRIMINATING SCHEMES (4× rate vs false positive rate):")
            for s in schemes:
                gm    = s.get("group_match") or {}
                p4x   = (gm.get("4x_pump")       or {}).get("pct", 0)
                pfp   = (gm.get("false_positive") or {}).get("pct", 0)
                ratio = s.get("separator_ratio")
                badge = s.get("separator_badge") or (f"{ratio:.2f}×" if ratio else "—")
                lines.append(f"  {s.get('label', s.get('scheme_id'))}: 4x={p4x:.0f}%, fp={pfp:.0f}% [{badge}]")

        for vt in ("BOOST", "INCREASE", "PENALIZE", "REDUCE"):
            feats = [v["feature"] for v in verdicts if v.get("verdict") == vt]
            if feats:
                tag = "WEIGHT HIGHER" if vt in ("BOOST", "INCREASE") else "WEIGHT LOWER"
                lines.append(f"{tag} ({vt}): {', '.join(feats[:7])}")

        timing_keys = {"days_in_base", "pre_days", "pump_days"}
        timing_4x: dict[str, float] = {}
        for c in comps:
            fn = c.get("feature_name")
            if fn in timing_keys and c.get("group_name") == "4x_pump" and c.get("median_value") is not None:
                timing_4x[fn] = c["median_value"]
        if timing_4x:
            lines.append("\nKEY 4× MEDIANS: " + ", ".join(
                f"{k}={v:.0f}d" for k, v in timing_4x.items()
            ))

        cached_ai = await get_raw_pattern_ai_summary(run_id)
        if cached_ai and not cached_ai.get("parse_failed"):
            rec = (cached_ai.get("analysis") or {}).get("recommendation") or cached_ai.get("recommendation") or ""
            if rec:
                lines.append(f"\nAI RECOMMENDATION: {rec}")

        lines.append("=== END CONTEXT ===")
        return "\n".join(lines)

    except Exception as exc:
        logger.warning("_build_research_context_text run_id=%s failed: %s", run_id, exc)
        return ""


def _repair_json(raw: str) -> str:
    """
    Lightweight single-pass JSON repair.
    Handles the most common model failure modes:
      - trailing comma before } or ]
      - unterminated string at end of output (truncation)
      - accidental markdown code fences (```json ... ```)
    Returns a repaired string — caller still must json.loads() it.
    """
    import re

    # Strip markdown fences
    s = raw.strip()
    if s.startswith("```"):
        lines = s.splitlines()
        # drop first line (```json or ```) and last line if it's ```
        start = 1
        end   = len(lines) - 1 if lines[-1].strip() == "```" else len(lines)
        s = "\n".join(lines[start:end]).strip()

    # Remove trailing commas before } or ]
    s = re.sub(r",\s*([}\]])", r"\1", s)

    # If string appears truncated (odd number of unescaped quotes → unterminated string),
    # try to close it cleanly by appending closing punctuation.
    # Count unescaped double-quotes
    unescaped = len(re.findall(r'(?<!\\)"', s))
    if unescaped % 2 != 0:
        # Unterminated string — close it, then close any open structures
        s = s.rstrip()
        # Close the open string
        s += '"'
        # Count unclosed { and [ by simple depth tracking
        depth_brace   = s.count("{") - s.count("}")
        depth_bracket = s.count("[") - s.count("]")
        # Close innermost open arrays first, then objects
        s += "]" * max(0, depth_bracket) + "}" * max(0, depth_brace)

    return s


@app.delete("/api/replay/pump-study/{run_id}/ai-summary")
async def pump_study_delete_ai_summary(run_id: int):
    """
    Delete a stored AI summary so it can be regenerated.
    Used by the frontend Retry button to clear a cached parse_failed row.
    """
    from database import PumpStudyAISummary, get_session_factory
    from sqlalchemy import select as sa_select

    async with get_session_factory()() as session:
        result = await session.execute(
            sa_select(PumpStudyAISummary).where(PumpStudyAISummary.run_id == run_id)
        )
        row = result.scalar_one_or_none()
        if row:
            await session.delete(row)
            await session.commit()
    return {"ok": True, "deleted": True, "run_id": run_id}


@app.get("/api/replay/pump-study/{run_id}/ai-summary")
async def pump_study_ai_summary(run_id: int, raw_pattern_run_id: Optional[int] = None):
    """
    Lazy AI pattern-analysis for a completed pump-study run.

    On first request: builds a deterministic evidence bundle from stored DB
    data, calls Claude, stores the result, and returns it.
    On subsequent requests: returns the cached row immediately.

    Evidence is 100% price/volume/indicator-derived.  No external news or
    catalyst data is ingested.  The model is explicitly instructed to flag
    this limitation and not invent catalysts.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")

    from database import (
        get_pump_study_run,
        get_pump_episodes,
        get_pump_comparison_groups,
        get_pump_study_timeline,
        get_pump_ai_summary,
        save_pump_ai_summary,
    )

    run = await get_pump_study_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")

    terminal = ("completed", "comparison_complete")
    if run.get("status") not in terminal:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Run {run_id} status is '{run.get('status')}'. "
                "AI summary requires a completed run."
            ),
        )

    # ── Return cached result if available (skip when research context requested) ─
    cached = await get_pump_ai_summary(run_id) if not raw_pattern_run_id else None
    if cached:
        # If previous attempt failed to parse, surface that clearly so UI can retry
        if cached.get("parse_failed"):
            return {
                "ok":          False,
                "parse_failed": True,
                "run_id":      run_id,
                "message":     "AI summary could not be parsed — model returned malformed JSON.",
                "parse_error": cached.get("parse_error"),
                "raw_text":    (cached.get("raw_response") or "")[:500],
                "model_used":  cached.get("model_used"),
                "cached":      True,
            }
        cached["ok"]           = True
        cached["cached"]       = True
        cached["generated_at"] = cached.get("created_at")
        return cached

    # ── Build deterministic evidence bundle ───────────────────────────────────
    episodes = await get_pump_episodes(run_id, limit=500)
    groups   = await get_pump_comparison_groups(run_id)
    events   = await get_pump_study_timeline(run_id)

    # Event type frequencies across all episodes
    event_freq: dict[str, int] = {}
    for ev in events:
        t = ev.get("event_type", "unknown")
        event_freq[t] = event_freq.get(t, 0) + 1

    # Catch / miss breakdown
    caught = sum(1 for ep in episodes if ep.get("caught_by_scanner") is True)
    missed = sum(1 for ep in episodes if ep.get("caught_by_scanner") is False)
    total  = caught + missed

    # Family distribution
    family_counts: dict[str, int] = {}
    for ep in episodes:
        k = ep.get("pump_type") or "UNKNOWN"
        family_counts[k] = family_counts.get(k, 0) + 1

    # Group stats index (group_name → stats dict)
    group_stats = {g["group_name"]: g.get("stats", {}) for g in groups}

    evidence = {
        "run_params": {
            "date_range":    f"{run.get('start_date')} to {run.get('end_date')}",
            "min_multiple":  run.get("min_multiple"),
            "window_days":   run.get("window_days"),
            "episode_count": run.get("episode_count"),
        },
        "catch_rate": {
            "caught":   caught,
            "missed":   missed,
            "rate_pct": round(caught / max(1, total) * 100, 1),
        },
        "family_distribution": family_counts,
        "event_type_frequency": event_freq,
        "group_stats": group_stats,
        "data_limitations": {
            "catalyst_news_available": False,
            "note": (
                "No external news or catalyst data was ingested. "
                "Analysis is limited to price, volume, and indicator-derived features."
            ),
        },
    }

    # ── Prompt (compact — reduces token count and truncation risk) ────────────
    evidence_compact = json.dumps(evidence, separators=(",", ":"), default=str)

    research_section = ""
    if raw_pattern_run_id:
        ctx_text = await _build_research_context_text(raw_pattern_run_id)
        if ctx_text:
            research_section = f"PRIOR RESEARCH CONTEXT:\n{ctx_text}\n\n"
            logger.info("pump_study_ai_summary run_id=%s: injecting Raw Pattern Study #%s context",
                        run_id, raw_pattern_run_id)

    prompt = (
        research_section
        + "EVIDENCE (price/volume/indicator only, no news):\n"
        f"{evidence_compact}\n\n"
        "Answer 6 questions using ONLY the evidence. "
        "Keep each array item under 15 words. No newlines inside strings.\n"
        "Q1: Patterns before 4x pumps (cite event_type_frequency counts).\n"
        "Q2: Earliest signals (reference event types).\n"
        "Q3: 4x_pump vs false_positive (cite group_stats numbers).\n"
        "Q4: 4x_pump vs normal_winner (cite group_stats numbers).\n"
        "Q5: Closest existing engine — one of: "
        "Pump Engine|Ignition Engine|Ribbon Engine|Base Scanner.\n"
        "Q6: Engine to build next — EXACTLY one of: "
        "Build Catalyst Ignition Engine|"
        "Build Low-Float Velocity Engine|"
        "Build Post-Compression Expansion Engine|"
        "Build Sector Sympathy Engine|"
        "Build Hybrid Pump Engine|"
        "Improve existing Pump Engine with specific changes.\n\n"
        "Rules: no invented catalysts. Note data limitations. "
        "If group_stats empty, say insufficient data.\n\n"
        "Output ONLY this JSON object — no markdown, no prose, no code fences:\n"
        '{"patterns":["..."],'
        '"earliest_signals":["..."],'
        '"true_vs_false_positive":["..."],'
        '"true_vs_normal_winner":["..."],'
        '"closest_existing_engine":"...",'
        '"recommendation":"EXACT option",'
        '"recommendation_rationale":"1 sentence",'
        '"limitations":["..."]}'
    )

    _MODEL = "claude-haiku-4-5-20251001"

    # ── Call Claude ───────────────────────────────────────────────────────────
    raw_text = ""
    try:
        ai_client = anthropic.AsyncAnthropic(api_key=api_key, timeout=60.0)
        response  = await ai_client.messages.create(
            model      = _MODEL,
            max_tokens = 1200,
            system     = (
                "You are a quantitative research assistant. "
                "Output only a single valid JSON object — "
                "no markdown fences, no prose, no newlines inside string values."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = response.content[0].text.strip()
    except Exception as exc:
        logger.error("pump_study_ai_summary: API call failed: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc))

    # ── Safe JSON parse with one repair attempt ───────────────────────────────
    analysis = None
    parse_err = None
    try:
        analysis = json.loads(raw_text)
    except json.JSONDecodeError as exc1:
        logger.warning("pump_study_ai_summary: initial JSON parse failed (%s); attempting repair", exc1)
        try:
            repaired  = _repair_json(raw_text)
            analysis  = json.loads(repaired)
            logger.info("pump_study_ai_summary: JSON repair succeeded")
        except json.JSONDecodeError as exc2:
            parse_err = str(exc2)
            logger.error("pump_study_ai_summary: JSON repair also failed: %s", exc2)

    # ── Persist ───────────────────────────────────────────────────────────────
    if analysis is None:
        # Store the failure for audit; do NOT crash the route
        await save_pump_ai_summary(run_id, {
            "analysis":      {},
            "recommendation": "",
            "evidence":      evidence,
            "limitations":   "",
            "model_used":    _MODEL,
            "parse_failed":  True,
            "raw_response":  raw_text,
            "parse_error":   parse_err,
        })
        return {
            "ok":          False,
            "parse_failed": True,
            "run_id":      run_id,
            "message":     "AI summary could not be parsed — model returned malformed JSON.",
            "parse_error": parse_err,
            "raw_text":    raw_text[:500] if raw_text else "",
            "model_used":  _MODEL,
            "cached":      False,
        }

    limitations_text = "\n".join(analysis.get("limitations", []))
    await save_pump_ai_summary(run_id, {
        "analysis":       analysis,
        "recommendation": analysis.get("recommendation", ""),
        "evidence":       evidence,
        "limitations":    limitations_text,
        "model_used":     _MODEL,
        "parse_failed":   False,
        "raw_response":   None,
        "parse_error":    None,
    })

    return {
        "ok":      True,
        "run_id":  run_id,
        "analysis": analysis,
        "evidence_summary": {
            "episodes_analyzed": len(episodes),
            "event_types_found": len(event_freq),
            "groups_found":      len(groups),
        },
        "model_used":    _MODEL,
        "generated_at":  datetime.utcnow().isoformat() + "Z",
        "cached":        False,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Raw Pattern Study endpoints
# ══════════════════════════════════════════════════════════════════════════════

def _raw_pattern_markdown(run: dict, episodes: list[dict], comps: list[dict]) -> str:
    """Deterministic markdown summary of a raw-pattern study run."""
    lines = [
        f"# Raw Pattern Study — Run {run['id']}",
        f"",
        f"**Status:** {run.get('status')}  ",
        f"**Pump Study Run:** {run.get('pump_study_run_id')}  ",
        f"**Episodes analysed:** {run.get('episode_feature_count', 0)}  ",
        f"**Daily feature rows:** {run.get('raw_daily_count', 0)}  ",
        f"**Comparison rows:** {run.get('comparison_count', 0)}  ",
        f"",
    ]
    # Group summary
    from collections import Counter
    group_counts = Counter(ep.get("group_type") for ep in episodes)
    if group_counts:
        lines += ["## Group Breakdown", ""]
        for g, n in sorted(group_counts.items()):
            lines.append(f"- **{g}**: {n} episodes")
        lines.append("")
    # Comparison highlights: median per feature per group
    if comps:
        lines += ["## Feature Medians by Group", ""]
        feat_groups: dict[str, dict[str, Any]] = {}
        for c in comps:
            feat_groups.setdefault(c["feature_name"], {})[c["group_name"]] = c.get("median_value")
        for feat, groups in sorted(feat_groups.items()):
            parts = "  |  ".join(f"{g}: {v}" for g, v in sorted(groups.items()) if v is not None)
            if parts:
                lines.append(f"- **{feat}**: {parts}")
    return "\n".join(lines)


# ── 1. Launch ─────────────────────────────────────────────────────────────────

@app.post("/api/replay/raw-pattern-study/run")
async def raw_pattern_study_start(body: dict, background_tasks: BackgroundTasks):
    """
    Launch a new Raw Pattern Study run tied to an existing pump study run.

    Body (JSON):
        pump_study_run_id   int    required
        notes               str    optional

    Returns immediately with raw_run_id.
    Poll GET /api/replay/raw-pattern-study/{run_id} for status.
    """
    from database import create_raw_pattern_run, get_pump_study_run, update_raw_pattern_run

    psrun_id = body.get("pump_study_run_id")
    if not psrun_id:
        raise HTTPException(400, detail="pump_study_run_id is required")

    ps_run = await get_pump_study_run(int(psrun_id))
    if not ps_run:
        raise HTTPException(404, detail=f"Pump study run {psrun_id} not found")

    notes  = body.get("notes")
    run_id = await create_raw_pattern_run(
        pump_study_run_id=int(psrun_id),
        start_date=ps_run.get("start_date"),
        end_date=ps_run.get("end_date"),
        notes=notes,
    )

    async def _run(raw_run_id: int, pump_study_run_id: int) -> None:
        from database import update_raw_pattern_run as _upd
        from replay.pump_study_engine import (
            build_raw_pattern_daily_features,
            build_raw_pattern_episode_features_timing,
            build_raw_pattern_episode_features_candle,
            build_raw_pattern_episode_features_volume_compression,
            build_raw_pattern_episode_features_structure,
            build_raw_pattern_episode_features_ema,
            build_raw_pattern_comparisons,
        )
        try:
            await _upd(raw_run_id, {"status": "running",
                                    "started_at": datetime.utcnow()})
            await build_raw_pattern_daily_features(raw_run_id, pump_study_run_id)
            await build_raw_pattern_episode_features_timing(raw_run_id, pump_study_run_id)
            await build_raw_pattern_episode_features_candle(raw_run_id, pump_study_run_id)
            await build_raw_pattern_episode_features_volume_compression(raw_run_id, pump_study_run_id)
            await build_raw_pattern_episode_features_structure(raw_run_id, pump_study_run_id)
            await build_raw_pattern_episode_features_ema(raw_run_id, pump_study_run_id)
            await build_raw_pattern_comparisons(raw_run_id, pump_study_run_id)
            await _upd(raw_run_id, {"status": "complete",
                                    "finished_at": datetime.utcnow()})
        except Exception as exc:
            logger.error("raw_pattern_study run_id=%s failed: %s", raw_run_id, exc)
            await _upd(raw_run_id, {"status": "error",
                                    "error_message": str(exc)[:500],
                                    "finished_at": datetime.utcnow()})

    background_tasks.add_task(_run, run_id, int(psrun_id))

    return {
        "ok":                 True,
        "raw_run_id":         run_id,
        "pump_study_run_id":  int(psrun_id),
        "status":             "running",
        "message":            f"Raw Pattern Study launched. Poll GET /api/replay/raw-pattern-study/{run_id}",
    }


# ── 2. List runs ──────────────────────────────────────────────────────────────

@app.get("/api/replay/raw-pattern-study/runs")
async def raw_pattern_study_list_runs(
    pump_study_run_id: Optional[int] = None,
    limit: int = 20,
):
    """List raw-pattern-study runs, most recent first."""
    from database import get_raw_pattern_runs
    runs = await get_raw_pattern_runs(pump_study_run_id=pump_study_run_id, limit=limit)
    return {"ok": True, "count": len(runs), "runs": runs}


# ── 3. Run detail ─────────────────────────────────────────────────────────────

@app.get("/api/replay/raw-pattern-study/{run_id}")
async def raw_pattern_study_detail(run_id: int):
    """Return metadata and counts for one raw-pattern-study run."""
    from database import get_raw_pattern_run
    run = await get_raw_pattern_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Raw pattern run {run_id} not found")
    return {"ok": True, "run": run}


# ── 4. Episode features ───────────────────────────────────────────────────────

@app.get("/api/replay/raw-pattern-study/{run_id}/episodes")
async def raw_pattern_study_episodes(
    run_id: int,
    group_type: Optional[str] = None,
    limit: int = 1000,
):
    """Return raw_pattern_episode_features rows for a run."""
    from database import get_raw_pattern_run, get_raw_pattern_episode_features
    run = await get_raw_pattern_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Raw pattern run {run_id} not found")
    episodes = await get_raw_pattern_episode_features(
        run_id, group_type=group_type, limit=limit
    )
    return {"ok": True, "run_id": run_id, "count": len(episodes), "episodes": episodes}


# ── 5. Daily features ─────────────────────────────────────────────────────────

@app.get("/api/replay/raw-pattern-study/{run_id}/daily-features")
async def raw_pattern_study_daily_features(
    run_id: int,
    episode_id: Optional[int] = None,
    phase: Optional[str] = None,
    limit: int = 2000,
):
    """Return raw_pattern_daily_features rows for a run."""
    from database import get_raw_pattern_run, get_raw_pattern_daily_features
    run = await get_raw_pattern_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Raw pattern run {run_id} not found")
    rows = await get_raw_pattern_daily_features(
        run_id, episode_id=episode_id, phase=phase, limit=limit
    )
    return {"ok": True, "run_id": run_id, "count": len(rows), "rows": rows}


# ── 6. Comparisons ────────────────────────────────────────────────────────────

@app.get("/api/replay/raw-pattern-study/{run_id}/comparisons")
async def raw_pattern_study_comparisons(
    run_id: int,
    group_name: Optional[str] = None,
    feature_name: Optional[str] = None,
):
    """
    Return comparison stats and member rows for a run.

    Response:
        comparisons  — list of (group_name, feature_name) stat rows
        members      — list of member rows (per-episode feature snapshots)
    """
    from database import (
        get_raw_pattern_run,
        get_raw_pattern_comparisons,
        get_raw_pattern_comparison_members,
    )
    run = await get_raw_pattern_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Raw pattern run {run_id} not found")
    comps   = await get_raw_pattern_comparisons(run_id, group_name=group_name,
                                                feature_name=feature_name)
    members = await get_raw_pattern_comparison_members(run_id, group_name=group_name,
                                                       limit=5000)
    return {
        "ok":          True,
        "run_id":      run_id,
        "comparisons": comps,
        "members":     members,
    }


# ── 7. Export ─────────────────────────────────────────────────────────────────

@app.get("/api/replay/raw-pattern-study/{run_id}/export")
async def raw_pattern_study_export(run_id: int, format: str = "json"):
    """
    Download a raw-pattern-study export.

    format=json     — full structured export (run + episodes + comparisons)
    format=csv      — flat episode feature rows
    format=markdown — deterministic text summary
    """
    if format not in ("json", "csv", "markdown"):
        raise HTTPException(400, detail="format must be one of: json, csv, markdown")

    from database import (
        get_raw_pattern_run,
        get_raw_pattern_episode_features,
        get_raw_pattern_comparisons,
        get_raw_pattern_comparison_members,
    )

    run = await get_raw_pattern_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Raw pattern run {run_id} not found")

    episodes = await get_raw_pattern_episode_features(run_id, limit=5000)
    comps    = await get_raw_pattern_comparisons(run_id)

    if format == "csv":
        if not episodes:
            raise HTTPException(404, detail="No episode features found for this run")
        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=list(episodes[0].keys()))
        writer.writeheader()
        writer.writerows(episodes)
        buf.seek(0)
        return StreamingResponse(
            iter([buf.getvalue()]),
            media_type="text/csv",
            headers={"Content-Disposition":
                     f'attachment; filename="raw_pattern_{run_id}_episodes.csv"'},
        )

    if format == "markdown":
        content = _raw_pattern_markdown(run, episodes, comps)
        return StreamingResponse(
            iter([content]),
            media_type="text/markdown",
            headers={"Content-Disposition":
                     f'attachment; filename="raw_pattern_{run_id}_summary.md"'},
        )

    # json (default)
    from replay.pump_study_engine import extract_top_schemes, generate_engine_patch_plan
    from database import get_raw_pattern_ai_summary
    members     = await get_raw_pattern_comparison_members(run_id, limit=5000)
    engine_data = generate_engine_patch_plan(comps)
    ai_summary  = await get_raw_pattern_ai_summary(run_id)
    payload = json.dumps({
        "export_type":      "raw_pattern_study",
        "run":              run,
        "episodes":         episodes,
        "comparisons":      comps,
        "members":          members,
        "top_schemes":      extract_top_schemes(episodes).get("schemes", []),
        "feature_verdicts": engine_data.get("feature_verdicts", []),
        "engine_plan":      engine_data,
        "ai_summary":       ai_summary,
        "exported_at":      datetime.utcnow().isoformat() + "Z",
    }, default=str)
    return StreamingResponse(
        iter([payload]),
        media_type="application/json",
        headers={"Content-Disposition":
                 f'attachment; filename="raw_pattern_{run_id}_full.json"'},
    )


# ── 8. AI summary ─────────────────────────────────────────────────────────────

@app.get("/api/replay/raw-pattern-study/{run_id}/ai-summary")
async def raw_pattern_study_ai_summary(run_id: int):
    """
    Lazy AI pattern-analysis for a completed raw-pattern study run.

    On first call: builds a deterministic evidence bundle from raw_pattern_comparisons
    and raw_pattern_episode_features, calls Claude, stores the result, returns it.
    On subsequent calls: returns the cached row immediately.

    Evidence is 100% price/volume/indicator-derived.  No catalyst or news data.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(503, detail="ANTHROPIC_API_KEY not configured")

    from database import (
        get_raw_pattern_run,
        get_raw_pattern_episode_features,
        get_raw_pattern_comparisons,
        get_raw_pattern_ai_summary,
        save_raw_pattern_ai_summary,
    )

    run = await get_raw_pattern_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Raw pattern run {run_id} not found")
    if run.get("status") != "complete":
        raise HTTPException(409, detail=f"Run {run_id} status is '{run.get('status')}'. AI summary requires a completed run.")

    # ── Return cached result ──────────────────────────────────────────────────
    cached = await get_raw_pattern_ai_summary(run_id)
    if cached:
        if cached.get("parse_failed"):
            return {
                "ok": False, "parse_failed": True, "run_id": run_id, "cached": True,
                "message": "AI summary could not be parsed — model returned malformed JSON.",
                "parse_error": cached.get("parse_error"),
                "raw_text": (cached.get("raw_response") or "")[:500],
                "model_used": cached.get("model_used"),
            }
        cached.update({"ok": True, "cached": True, "generated_at": cached.get("created_at")})
        return cached

    # ── Build evidence bundle ─────────────────────────────────────────────────
    episodes = await get_raw_pattern_episode_features(run_id, limit=2000)
    comps    = await get_raw_pattern_comparisons(run_id)

    # Group counts — explicitly note absent groups
    from collections import Counter
    group_counts = dict(Counter(ep.get("group_type") for ep in episodes if ep.get("group_type")))
    all_groups   = ["4x_pump", "normal_winner", "false_positive", "missed_mover"]
    absent_groups = [g for g in all_groups if g not in group_counts]

    # Pivot comparisons: { feature → { group → stats + flags } }
    pivot: dict[str, dict] = {}
    feature_meta: dict[str, dict] = {}   # { feature → {priority, flags} } — one entry per feature
    for c in comps:
        fn    = c.get("feature_name")
        gn    = c.get("group_name")
        extra = c.get("stats") or {}          # stats_json unpacked by DB layer
        if fn and gn:
            pivot.setdefault(fn, {})[gn] = {
                "median": c.get("median_value"),
                "mean":   c.get("mean_value"),
                "p25":    c.get("p25_value"),
                "p75":    c.get("p75_value"),
                "n":      c.get("member_count"),
            }
            # Keep first-seen meta per feature (same priority/flags across groups)
            if fn not in feature_meta and extra:
                feature_meta[fn] = {
                    "priority":          extra.get("priority", "UNKNOWN"),
                    "low_variance":      extra.get("low_variance_flag", False),
                    "always_on":         extra.get("always_on_flag",    False),
                    "outlier_risk":      extra.get("outlier_risk_flag", False),
                }

    # Separate features by priority tier for a focused evidence view
    primary_features   = [f for f, m in feature_meta.items() if m.get("priority") == "PRIMARY"]
    secondary_features = [f for f, m in feature_meta.items() if m.get("priority") == "SECONDARY"]
    flagged_features   = [f for f, m in feature_meta.items()
                          if m.get("low_variance") or m.get("always_on") or m.get("outlier_risk")]

    evidence = {
        "run_params": {
            "date_range":            f"{run.get('start_date')} to {run.get('end_date')}",
            "pump_study_run_id":     run.get("pump_study_run_id"),
            "episode_feature_count": run.get("episode_feature_count"),
            "comparison_count":      run.get("comparison_count"),
        },
        "group_counts":        group_counts,
        "absent_groups":       absent_groups,
        "primary_features":    primary_features,
        "secondary_features":  secondary_features,
        "flagged_low_signal":  flagged_features,
        "feature_meta":        feature_meta,
        "feature_stats_by_group": pivot,
        "data_limitations": {
            "catalyst_news_available": False,
            "post_factum_labels_excluded": ["peak_day", "fade_day", "dump_day"],
            "missed_mover_excluded": True,
            "missed_mover_exclusion_reason": (
                "missed_mover has no deterministic event anchor dates "
                "(no pump_start_date / peak_date), so no PRE-window feature extraction "
                "is structurally possible. It is formally excluded from episode-feature "
                "comparison. Do not treat its absence as missing data."
            ),
            "note": (
                "No external news or catalyst data. "
                "peak_day/fade_day/dump_day are outcome labels — not usable as early signals. "
                "Analysis limited to pre-breakout price, volume, and sequence features."
            ),
        },
    }

    evidence_compact = json.dumps(evidence, separators=(",", ":"), default=str)

    _MODEL = "claude-haiku-4-5-20251001"

    prompt = (
        "You are a quantitative research assistant. "
        "All evidence below is price/volume/sequence only — no news, no catalysts.\n\n"
        "CRITICAL RULES:\n"
        "  - peak_day, fade_day, dump_day are POST-FACTUM outcome labels. "
        "Never use them as early discovery signals.\n"
        "  - If a group listed in absent_groups is missing from the data, say so explicitly "
        "instead of drawing conclusions about it.\n"
        "  - missed_mover is FORMALLY EXCLUDED from episode-feature comparison because it has "
        "no deterministic anchor dates. Do NOT treat it as absent data — acknowledge this "
        "structural exclusion explicitly in the limitations array.\n"
        "  - Focus Q1–Q3 on PRIMARY features listed in primary_features.\n"
        "  - Each array item must be under 25 words. No newlines inside strings.\n\n"
        "EVIDENCE:\n"
        f"{evidence_compact}\n\n"
        "Answer 5 questions using ONLY the evidence above:\n"
        "Q1 (repeated_patterns): Which pre-breakout sequence/duration/structure patterns "
        "appear most consistently before 4x_pump? Emphasise PRIMARY features: "
        "compression_days_pre, days_from_first_compression_to_breakout, "
        "days_from_breakout_to_peak, dryup_day_count_pre, had_accumulation_like, "
        "had_spring_test_lps, had_bull_stack_pre, days_above_ema50_pre, "
        "avg_ema_spread_pre, ema50_reclaim_count_pre.\n"
        "Q2 (separators_vs_normal_winner): Which PRIMARY features show the largest median "
        "gap between 4x_pump and normal_winner? Include EMA ribbon fields: "
        "had_bull_stack_pre, days_above_ema50_pre, avg_ema_spread_pre, "
        "ema50_reclaim_count_pre. If normal_winner is absent, state that.\n"
        "Q3 (separators_vs_false_positive): Which PRIMARY features show the largest median "
        "gap between 4x_pump and false_positive? If false_positive is absent, state that.\n"
        "Q4 (noisy_features): Which features are low-signal — low variance, near-identical "
        "medians across groups, always-on binary, or extreme outlier distortion? "
        "Do NOT list peak_day/fade_day/dump_day as noisy — they are excluded by design.\n"
        "Q5 (pump_engine_changes): List 3–5 specific changes to improve the current Pump "
        "Engine scoring: sequence-duration weights, compression persistence, "
        "accumulation/reclaim bonuses, volume sweet-spot, reduce body/wick noise reliance.\n\n"
        "Output ONLY this JSON — no markdown, no prose, no code fences:\n"
        '{"repeated_patterns":["..."],'
        '"separators_vs_normal_winner":["..."],'
        '"separators_vs_false_positive":["..."],'
        '"noisy_features":["..."],'
        '"pump_engine_changes":["..."],'
        '"recommendation":"one sentence",'
        '"limitations":["..."]}'
    )

    # ── Call Claude ───────────────────────────────────────────────────────────
    raw_text = ""
    try:
        ai_client = anthropic.AsyncAnthropic(api_key=api_key, timeout=60.0)
        response  = await ai_client.messages.create(
            model      = _MODEL,
            max_tokens = 1400,
            system     = (
                "You are a quantitative research assistant. "
                "Output only a single valid JSON object — "
                "no markdown fences, no prose, no newlines inside string values."
            ),
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = response.content[0].text.strip()
    except Exception as exc:
        logger.error("raw_pattern_ai_summary run_id=%s: API call failed: %s", run_id, exc)
        raise HTTPException(500, detail=str(exc))

    # ── Safe JSON parse with one repair attempt ───────────────────────────────
    analysis  = None
    parse_err = None
    try:
        analysis = json.loads(raw_text)
    except json.JSONDecodeError as exc1:
        logger.warning("raw_pattern_ai_summary: initial JSON parse failed (%s); attempting repair", exc1)
        try:
            analysis = json.loads(_repair_json(raw_text))
            logger.info("raw_pattern_ai_summary: JSON repair succeeded")
        except json.JSONDecodeError as exc2:
            parse_err = str(exc2)
            logger.error("raw_pattern_ai_summary: JSON repair also failed: %s", exc2)

    # ── Persist ───────────────────────────────────────────────────────────────
    if analysis is None:
        await save_raw_pattern_ai_summary(run_id, {
            "analysis": {}, "recommendation": "", "evidence": evidence,
            "limitations": "", "model_used": _MODEL,
            "parse_failed": True, "raw_response": raw_text, "parse_error": parse_err,
        })
        return {
            "ok": False, "parse_failed": True, "run_id": run_id, "cached": False,
            "message": "AI summary could not be parsed — model returned malformed JSON.",
            "parse_error": parse_err, "raw_text": raw_text[:500] if raw_text else "",
            "model_used": _MODEL,
        }

    limitations_text = "\n".join(analysis.get("limitations", []))
    await save_raw_pattern_ai_summary(run_id, {
        "analysis":       analysis,
        "recommendation": analysis.get("recommendation", ""),
        "evidence":       evidence,
        "limitations":    limitations_text,
        "model_used":     _MODEL,
        "parse_failed":   False,
        "raw_response":   None,
        "parse_error":    None,
    })

    return {
        "ok":          True,
        "run_id":      run_id,
        "analysis":    analysis,
        "evidence_summary": {
            "groups":         list(group_counts.keys()),
            "features_compared": len(pivot),
            "episodes_analyzed": len(episodes),
        },
        "model_used":    _MODEL,
        "generated_at":  datetime.utcnow().isoformat() + "Z",
        "cached":        False,
    }


# ── 9. Repair ─────────────────────────────────────────────────────────────────

@app.post("/api/replay/raw-pattern-study/{run_id}/repair")
async def raw_pattern_study_repair(run_id: int):
    """
    Repair a completed raw-pattern run where group_type was empty and
    comparison_count is 0.

    Resolves episode → group mappings from pump_comparison_members,
    patches group_type on raw_pattern_episode_features rows,
    clears stale comparison rows, and rebuilds comparisons.
    Safe to call multiple times (idempotent).
    """
    from database import get_raw_pattern_run
    from replay.pump_study_engine import repair_raw_pattern_group_types

    run = await get_raw_pattern_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Raw pattern run {run_id} not found")
    if not run.get("pump_study_run_id"):
        raise HTTPException(400, detail="Run has no pump_study_run_id — cannot resolve groups.")

    result = await repair_raw_pattern_group_types(run_id, run["pump_study_run_id"])
    return {"ok": True, "run_id": run_id, "pump_study_run_id": run["pump_study_run_id"], **result}


# ── 10. Top pre-pump schemes ───────────────────────────────────────────────────

@app.get("/api/replay/raw-pattern-study/{run_id}/top-schemes")
async def raw_pattern_study_top_schemes(run_id: int):
    """
    Deterministic extraction of the top 3–5 repeated pre-pump sequence schemes
    from stored episode features for a completed raw-pattern run.

    Uses ONLY pre-breakout features.  peak / fade / dump are excluded entirely.
    No AI — purely deterministic counting and ranking.
    """
    from database import get_raw_pattern_run, get_raw_pattern_episode_features
    from replay.pump_study_engine import extract_top_schemes

    run = await get_raw_pattern_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Raw pattern run {run_id} not found")
    if run.get("status") != "complete":
        raise HTTPException(400, detail="Run is not complete yet.")

    episodes = await get_raw_pattern_episode_features(run_id, limit=5000)
    result   = extract_top_schemes(episodes)
    return {"ok": True, "run_id": run_id, **result}


@app.get("/api/replay/raw-pattern-study/{run_id}/engine-patch-plan")
async def raw_pattern_study_engine_patch_plan(run_id: int):
    """
    Deterministic Pump Engine patch plan derived from comparison medians.

    Classifies each comparison feature as BOOST / INCREASE / PENALIZE / REDUCE / IGNORE
    based on the separation ratio between 4x_pump and false_positive (or normal_winner
    when false_positive is absent).

    Also returns 7 domain-area recommendations covering:
      sequence_duration_weights, compression_persistence, volume_sweet_spot,
      accumulation_spring_reclaim, ema_ribbon_quality, body_wick_noise_reduction,
      toxicity_penalty.

    Purely deterministic — no AI, no external calls.
    Delta bonuses are excluded (delta not yet available in pipeline).
    """
    from database import get_raw_pattern_run, get_raw_pattern_comparisons
    from replay.pump_study_engine import generate_engine_patch_plan

    run = await get_raw_pattern_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Raw pattern run {run_id} not found")
    if run.get("status") != "complete":
        raise HTTPException(400, detail="Run is not complete yet.")

    comps  = await get_raw_pattern_comparisons(run_id)
    result = generate_engine_patch_plan(comps)
    return {"ok": True, "run_id": run_id, **result}


@app.get("/api/replay/raw-pattern-study/{run_id}/research-context")
async def raw_pattern_research_context(run_id: int):
    """
    Export a compact, AI-prompt-ready research context from a completed
    Raw Pattern Study run.  Includes top schemes, feature verdicts, key
    timing medians, and the cached AI recommendation.

    Used by the Scanner AI Analyst and Pump Study AI to inject prior
    quantitative research findings into their prompts.
    """
    from database import get_raw_pattern_run
    run = await get_raw_pattern_run(run_id)
    if not run:
        raise HTTPException(404, detail=f"Raw pattern run {run_id} not found")
    if run.get("status") != "complete":
        raise HTTPException(400, detail="Run must be complete to export research context.")

    context_text = await _build_research_context_text(run_id)
    if not context_text:
        raise HTTPException(500, detail="Failed to build research context — run may have no comparison data.")

    return {
        "ok":           True,
        "run_id":       run_id,
        "date_range":   f"{run.get('start_date')} to {run.get('end_date')}",
        "context_text": context_text,
    }
