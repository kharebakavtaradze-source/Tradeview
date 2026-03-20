"""
Pump Scout — FastAPI backend
Endpoints for scan results, ticker detail, manual scan trigger, and health.
"""
import logging
import os
from contextlib import asynccontextmanager
from typing import Optional

from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)

from database import (
    add_to_watchlist,
    get_latest_scan,
    get_scan_history,
    get_watchlist,
    init_db,
    remove_from_watchlist,
    save_scan,
)
from scanner.runner import run_scan
from scheduler import start_scheduler, stop_scheduler

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
    version="1.0.0",
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
        "version": "1.0.0",
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

    if not ticker_data:
        # Try to fetch fresh data for this specific ticker
        from scanner.yahoo import fetch_ohlcv
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

    return {**ticker_data, "source": "scan"}


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
