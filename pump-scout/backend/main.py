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
    delete_journal_entry,
    get_journal,
    get_journal_stats,
    get_latest_scan,
    get_scan_history,
    get_watchlist,
    init_db,
    remove_from_watchlist,
    save_scan,
    update_journal_entry,
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
    version="9.0.0",
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
        "version": "9.0.0",
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


@app.post("/api/journal")
async def create_journal_entry(data: Dict[str, Any]):
    if not data.get("symbol") or not data.get("entry_price"):
        raise HTTPException(status_code=400, detail="symbol and entry_price are required")
    entry = await add_journal_entry(data)
    return {"status": "added", "entry": entry}


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


@app.get("/api/journal/stats")
async def journal_stats():
    return await get_journal_stats()


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
    """Send journal data to Claude for pattern analysis."""
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
    return {
        "ticker": ticker,
        "hype_score": hype_score,
        "velocity": velocity,
        "divergences": divergences,
        "ai_analysis": None,
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
