"""
Pump Study Engine — Phase 3A: Raw Detection
============================================

Detects raw 4x pump candidates in historical price data using a sliding window.

Algorithm (per symbol)
----------------------
For each trading day t0 where scan_start <= date(t0) <= scan_end:
    start_price = close[t0]                         (EOD entry price)
    forward     = candles[t0+1 : t0+window_days+1]  (next N trading bars)
    peak_price  = max(high[j] for j in forward)
    multiple    = peak_price / start_price
    → record raw detection if multiple >= min_multiple

Also computed per detection:
    days_to_peak             : trading-day index of peak bar within forward window
    days_to_double           : first forward bar where high >= 2× start_price (None if never)
    max_drawdown_before_peak : min(low[t0+1..peak_bar]) vs start_price, as %

Phase scope
-----------
Phase 3A  ✓  Raw detection → pump_episode_detections
Phase 3B  ✗  Clustering / deduplication (not yet)
Phase 3C  ✗  Snapshots / events          (not yet)
Phase 3D  ✗  Comparison groups           (not yet)
"""

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

# Universe filters (applied when building the symbol list)
_MIN_VOLUME: int   = 100_000
_MIN_PRICE:  float = 1.0
_MAX_PRICE:  float = 500.0

# How many grouped_daily sample dates to collect the universe from
_UNIVERSE_SAMPLE_COUNT: int = 5

# ── Progress tracker ──────────────────────────────────────────────────────────

_pump_study_progress: dict = {
    "running":          False,
    "run_id":           None,
    "phase":            None,
    "symbols_total":    0,
    "symbols_done":     0,
    "raw_detections":   0,
    "error":            None,
}


def get_pump_study_progress() -> dict:
    """Return a snapshot of the current pump study progress."""
    return dict(_pump_study_progress)


# ── Candle fetch helper ───────────────────────────────────────────────────────

async def _fetch_candles_range(
    symbol: str,
    from_date: str,
    to_date: str,
) -> list[dict]:
    """
    Fetch all daily OHLCV bars for one symbol between from_date and to_date.
    No as_of_date cap — intentional for historical research.
    Returns list of {date, open, high, low, close, volume} sorted oldest→newest.
    Returns [] on any error.
    """
    try:
        from scanner.massive_data import MASSIVE_API_KEY, MASSIVE_BASE

        if not MASSIVE_API_KEY:
            return []

        url = (
            f"{MASSIVE_BASE}/v2/aggs/ticker/{symbol.upper()}"
            f"/range/1/day/{from_date}/{to_date}"
        )
        params: dict = {
            "apiKey":   MASSIVE_API_KEY,
            "adjusted": "true",
            "sort":     "asc",
            "limit":    50000,
        }

        candles: list[dict] = []
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            next_url: Optional[str] = None
            while True:
                resp = await (client.get(next_url) if next_url else client.get(url, params=params))
                if resp.status_code != 200:
                    break

                data = resp.json()
                for bar in data.get("results") or []:
                    ts = bar.get("t")
                    if not ts:
                        continue
                    bar_date = datetime.fromtimestamp(
                        ts / 1000, tz=timezone.utc
                    ).strftime("%Y-%m-%d")
                    candles.append({
                        "date":   bar_date,
                        "open":   bar.get("o"),
                        "high":   bar.get("h"),
                        "low":    bar.get("l"),
                        "close":  bar.get("c"),
                        "volume": int(bar.get("v") or 0),
                    })

                next_url = data.get("next_url")
                if not next_url:
                    break

        candles.sort(key=lambda c: c["date"])
        return candles

    except Exception as exc:
        logger.debug(f"_fetch_candles_range({symbol}, {from_date}→{to_date}): {exc}")
        return []


# ── Raw detection ─────────────────────────────────────────────────────────────

def _detect_raw_pumps(
    symbol: str,
    candles: list[dict],
    scan_start: str,
    scan_end: str,
    window_days: int,
    min_multiple: float,
) -> list[dict]:
    """
    Sliding window 4x pump detector for a single symbol.

    Parameters
    ----------
    symbol      : ticker symbol (stored on each detection dict)
    candles     : list of {date, open, high, low, close, volume} sorted asc
    scan_start  : only consider t0 dates >= scan_start
    scan_end    : only consider t0 dates <= scan_end
    window_days : number of forward trading bars to inspect after t0
    min_multiple: minimum peak/start ratio to record a detection

    Returns
    -------
    List of raw detection dicts ready to insert into pump_episode_detections.
    cluster_id / is_canonical are left None (set during Phase 3B clustering).
    """
    detections: list[dict] = []
    n = len(candles)

    for i in range(n - 1):
        bar = candles[i]
        t0_date = bar["date"]

        if t0_date < scan_start or t0_date > scan_end:
            continue

        start_price: Optional[float] = bar["close"]
        if not start_price or start_price <= 0:
            continue

        # Forward window: bars strictly after t0
        fwd_end = min(i + window_days + 1, n)
        fwd = candles[i + 1 : fwd_end]

        if not fwd:
            continue

        # ── Find peak (highest high in forward window) ────────────────────────
        peak_local_idx: int = -1
        peak_high: float = 0.0
        for j, fbar in enumerate(fwd):
            h = fbar.get("high")
            if h and h > peak_high:
                peak_high = h
                peak_local_idx = j

        if peak_local_idx < 0 or peak_high <= 0:
            continue

        multiple = peak_high / start_price
        if multiple < min_multiple:
            continue

        # days_to_peak: 1-based trading-day count from t0 to peak bar
        days_to_peak: int = peak_local_idx + 1
        peak_date: str = fwd[peak_local_idx]["date"]

        # ── days_to_double ────────────────────────────────────────────────────
        double_target = start_price * 2.0
        days_to_double: Optional[int] = None
        for j, fbar in enumerate(fwd[: peak_local_idx + 1]):
            h = fbar.get("high")
            if h and h >= double_target:
                days_to_double = j + 1
                break

        # ── max_drawdown_before_peak ──────────────────────────────────────────
        # Worst intraday low in [t0+1, peak_bar] vs start_price, as %
        max_drawdown_before_peak: Optional[float] = None
        lows_in_window = [
            fbar["low"]
            for fbar in fwd[: peak_local_idx + 1]
            if fbar.get("low")
        ]
        if lows_in_window:
            worst_low = min(lows_in_window)
            max_drawdown_before_peak = round(
                (worst_low - start_price) / start_price * 100, 2
            )

        detections.append({
            "symbol":                   symbol,
            "window_start_date":        t0_date,
            "window_peak_date":         peak_date,
            "window_days":              window_days,
            "start_price":              round(start_price, 4),
            "peak_price":               round(peak_high, 4),
            "multiple":                 round(multiple, 4),
            "return_pct":               round((peak_high - start_price) / start_price * 100, 2),
            "days_to_peak":             days_to_peak,
            "days_to_double":           days_to_double,
            "max_drawdown_before_peak": max_drawdown_before_peak,
            # Back-filled in Phase 3B
            "cluster_id":               None,
            "is_canonical":             False,
        })

    return detections


# ── Universe builder ──────────────────────────────────────────────────────────

async def _build_universe(
    start_date: str,
    end_date: str,
    limit: int,
) -> list[str]:
    """
    Build a de-duplicated symbol universe by sampling grouped_daily across
    the date range.  Applies volume / price / ETF filters.

    Returns symbols ranked by peak volume (highest first), capped at `limit`
    if limit > 0.
    """
    from scanner.massive_data import fetch_grouped_daily, get_us_etf_symbols

    d_start    = date.fromisoformat(start_date)
    d_end      = date.fromisoformat(end_date)
    total_days = max(1, (d_end - d_start).days)

    # Evenly-spaced sample dates across the range
    sample_count = min(_UNIVERSE_SAMPLE_COUNT, max(1, total_days // 20))
    sample_dates = [
        (d_start + timedelta(days=round(i * total_days / sample_count))).isoformat()
        for i in range(sample_count)
    ]

    etf_set: set = set()
    try:
        etf_set = await get_us_etf_symbols()
    except Exception:
        pass

    sym_vol: dict[str, float] = {}  # symbol → max volume seen across sample dates

    for sd in sample_dates:
        try:
            bars = await fetch_grouped_daily(sd)
        except Exception:
            continue
        if not bars:
            continue
        for sym, bar in bars.items():
            if sym in etf_set:
                continue
            vol   = bar.get("volume") or 0
            close = bar.get("close")  or 0
            if vol < _MIN_VOLUME or not (_MIN_PRICE <= close <= _MAX_PRICE):
                continue
            sym_vol[sym] = max(sym_vol.get(sym, 0.0), float(vol))

    ranked = sorted(sym_vol.items(), key=lambda kv: kv[1], reverse=True)
    if limit and limit > 0:
        ranked = ranked[:limit]

    symbols = [sym for sym, _ in ranked]
    logger.info(
        f"[PUMP_STUDY] universe: {len(symbols)} symbols "
        f"(sampled {len(sample_dates)} dates, limit={limit or 'none'})"
    )
    return symbols


# ── Main engine function ──────────────────────────────────────────────────────

async def run_pump_study(run_id: int, params: dict) -> None:
    """
    Phase 3A entry point.

    Params (all required unless marked optional):
        start_date      str  YYYY-MM-DD  scan window start
        end_date        str  YYYY-MM-DD  scan window end
        window_days     int  (default 14) forward look-ahead in trading bars
        min_multiple    float (default 4.0) minimum pump multiple to record
        universe_limit  int  (default 0 = no limit)

    What runs in Phase 3A:
        ✓ Universe build
        ✓ Per-symbol candle fetch
        ✓ Sliding-window raw detection
        ✓ Save to pump_episode_detections
        ✓ Update run counts + status

    What is NOT done yet (later phases):
        ✗ Clustering / deduplication
        ✗ Canonical episode creation
        ✗ PRE / PUMP / POST snapshots
        ✗ Timeline events
        ✗ Comparison groups
    """
    global _pump_study_progress

    from database import update_pump_study_run, save_pump_episode_detections

    _pump_study_progress.update({
        "running":        True,
        "run_id":         run_id,
        "phase":          "INIT",
        "symbols_total":  0,
        "symbols_done":   0,
        "raw_detections": 0,
        "error":          None,
    })

    try:
        await update_pump_study_run(run_id, {
            "status":     "running",
            "started_at": datetime.utcnow(),
        })

        start_date   = params["start_date"]
        end_date     = params["end_date"]
        window_days  = int(params.get("window_days",   14))
        min_multiple = float(params.get("min_multiple", 4.0))
        univ_limit   = int(params.get("universe_limit", 0))

        # Fetch candles with enough buffer for forward window
        fetch_from = (
            date.fromisoformat(start_date) - timedelta(days=5)
        ).isoformat()
        fetch_to = (
            date.fromisoformat(end_date) + timedelta(days=window_days * 2)
        ).isoformat()

        # ── 1. Universe ───────────────────────────────────────────────────────
        _pump_study_progress["phase"] = "UNIVERSE"
        symbols = await _build_universe(start_date, end_date, univ_limit)

        _pump_study_progress["symbols_total"] = len(symbols)
        await update_pump_study_run(run_id, {"symbols_scanned": len(symbols)})

        if not symbols:
            raise RuntimeError("Universe is empty — check date range and API key")

        # ── 2. Per-symbol detection ───────────────────────────────────────────
        _pump_study_progress["phase"] = "DETECTION"

        all_detections: list[dict] = []
        sem = asyncio.Semaphore(8)

        async def _process(sym: str) -> None:
            async with sem:
                candles = await _fetch_candles_range(sym, fetch_from, fetch_to)
                if not candles or len(candles) < window_days + 1:
                    _pump_study_progress["symbols_done"] += 1
                    return

                hits = _detect_raw_pumps(
                    sym, candles,
                    scan_start   = start_date,
                    scan_end     = end_date,
                    window_days  = window_days,
                    min_multiple = min_multiple,
                )
                all_detections.extend(hits)

                _pump_study_progress["symbols_done"]   += 1
                _pump_study_progress["raw_detections"]  = len(all_detections)

                if hits:
                    logger.debug(
                        f"[PUMP_STUDY] {sym}: {len(hits)} raw detection(s) "
                        f"(best {max(h['multiple'] for h in hits):.2f}x)"
                    )

        await asyncio.gather(*[_process(s) for s in symbols])

        # ── 3. Persist raw detections ─────────────────────────────────────────
        _pump_study_progress["phase"] = "SAVING"
        saved = await save_pump_episode_detections(run_id, all_detections)

        # ── 4. Finalise ───────────────────────────────────────────────────────
        await update_pump_study_run(run_id, {
            "status":             "detection_complete",
            "symbols_scanned":    len(symbols),
            "raw_detection_count": saved,
            "finished_at":        datetime.utcnow(),
            "notes": (
                f"Phase 3A complete: {saved} raw detections across {len(symbols)} symbols. "
                f"Clustering / snapshots / events pending (Phase 3B+)."
            ),
        })

        _pump_study_progress.update({
            "running": False,
            "phase":   "DETECTION_COMPLETE",
        })

        logger.info(
            f"[PUMP_STUDY] run_id={run_id} Phase 3A done: "
            f"{len(symbols)} symbols scanned, {saved} raw detections saved"
        )

    except Exception as exc:
        logger.error(f"[PUMP_STUDY] run_id={run_id} failed: {exc}", exc_info=True)
        _pump_study_progress.update({
            "running": False,
            "phase":   "FAILED",
            "error":   str(exc),
        })
        try:
            await update_pump_study_run(run_id, {
                "status":        "failed",
                "error_message": str(exc)[:500],
                "finished_at":   datetime.utcnow(),
            })
        except Exception:
            pass
