"""
Historical Replay Engine
=========================
Runs the universe scan pipeline on past dates, storing results in isolated
replay tables that never touch live production data.

FUTURE LEAKAGE PREVENTION
--------------------------
The single modification that makes this safe:
  fetch_candles_massive(symbol, as_of_date=as_of_date)

This cuts the Massive API candle response at as_of_date so that indicators
and scoring only see data that existed on that day. Everything else
(calc_all, score_ticker, detect_regime) is a pure function of the candles —
no external state, no network call, no today() dependency.

LIVE/REPLAY ISOLATION
---------------------
- All results go to replay_* tables (ReplayRun, ReplaySignalCandidate, etc.)
- Live Scan / ScanCandidate / Journal tables are never written to
- `_replay_progress` is a separate dict from universe_scan's `_progress`
- Replay endpoints are under /api/replay/ — not mixed with /api/scan/

UNIVERSE MODE
-------------
approx (default):
    Uses the Massive grouped-daily snapshot for as_of_date as the universe.
    Candle history is cut at as_of_date.
    Sector/industry data comes from the cached SectorCache table (best-effort;
    may not reflect exactly what was true on that date, but sector classification
    rarely changes and this is a research tool).
    NOTE: This approximation can introduce mild survivor bias because current
    Polygon coverage may include tickers that were delisted before as_of_date
    (though they would have no grouped_daily bar for that date if truly delisted).

strict (future extension):
    A truly bias-free universe would require a historical reference data snapshot
    (e.g. Polygon Snapshot API with historical tickers).  Not yet implemented.
    For now, strict mode falls back to approx with an explicit note in the run.
"""
import asyncio
import json
import logging
from datetime import date, datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── Module-level progress tracker (replaces universe_scan._progress for replay) ─
# Separate dict — never shared with or written into the live scanner's _progress.
_replay_progress: dict = {
    "running":          False,
    "run_id":           None,
    "mode":             None,          # single_day | date_range
    "current_date":     None,
    "days_total":       0,
    "days_completed":   0,
    "symbols_scanned":  0,
    "candidates_found": 0,
    "outcomes_computed":0,
    "missed_found":     0,
    "error":            None,
    "started_at":       None,
    "elapsed_secs":     0,
}


def get_replay_progress() -> dict:
    """Return a copy of the current replay progress dict."""
    p = dict(_replay_progress)
    if p.get("running") and p.get("started_at"):
        p["elapsed_secs"] = round(
            (datetime.utcnow() - p["started_at"]).total_seconds()
        )
    return p


def _upd(**kwargs):
    _replay_progress.update(kwargs)


# ── Trading day helpers ───────────────────────────────────────────────────────

def _is_weekday(d: date) -> bool:
    return d.weekday() < 5   # Mon–Fri


def _trading_days_in_range(start: str, end: str) -> list[str]:
    """Return sorted list of weekday YYYY-MM-DD strings between start and end (inclusive)."""
    s = date.fromisoformat(start)
    e = date.fromisoformat(end)
    days = []
    cur = s
    while cur <= e:
        if _is_weekday(cur):
            days.append(cur.isoformat())
        cur += timedelta(days=1)
    return days


# ── Main entry points ─────────────────────────────────────────────────────────

async def run_single_day_replay(
    as_of_date: str,
    universe_mode: str = "approx",
) -> int:
    """
    Run a replay scan for a single historical date.
    Returns the replay_run_id.

    Raises if another replay is already running.
    """
    if _replay_progress["running"]:
        raise RuntimeError("A replay is already in progress. Wait for it to finish.")

    from database import (
        create_replay_run, update_replay_run,
        save_replay_candidates,
    )
    from replay.outcome_engine import compute_outcomes_for_run, detect_missed_movers

    _upd(running=True, mode="single_day", current_date=as_of_date,
         days_total=1, days_completed=0, symbols_scanned=0,
         candidates_found=0, outcomes_computed=0, missed_found=0,
         error=None, started_at=datetime.utcnow())

    run_id = await create_replay_run({
        "mode":          "single_day",
        "as_of_date":    as_of_date,
        "universe_mode": universe_mode if universe_mode == "approx" else "approx",  # strict → approx for now
        "total_days":    1,
        "notes":         "strict mode treated as approx (historical reference data not yet available)"
                         if universe_mode == "strict" else None,
    })
    _upd(run_id=run_id)
    logger.info(f"[REPLAY] run_id={run_id} starting single_day {as_of_date}")

    try:
        # Scan
        candidates = await _scan_one_date(as_of_date)
        _upd(candidates_found=len(candidates))

        # Persist candidates
        await save_replay_candidates(run_id, as_of_date, candidates)

        # Compute forward outcomes
        outcomes = await compute_outcomes_for_run(run_id, as_of_date, candidates)
        _upd(outcomes_computed=len(outcomes))

        # Detect missed movers
        missed = await detect_missed_movers(run_id, as_of_date, candidates)
        _upd(missed_found=len(missed))

        _upd(days_completed=1)
        await update_replay_run(run_id, {
            "status":               "completed",
            "finished_at":          datetime.utcnow(),
            "total_symbols":        _replay_progress["symbols_scanned"],
            "total_candidates":     len(candidates),
            "outcomes_computed":    len(outcomes),
            "missed_movers_found":  len(missed),
            "days_completed":       1,
        })
        logger.info(
            f"[REPLAY] run_id={run_id} completed: "
            f"{len(candidates)} candidates, {len(outcomes)} outcomes, "
            f"{len(missed)} missed movers"
        )

    except Exception as exc:
        logger.error(f"[REPLAY] run_id={run_id} failed: {exc}", exc_info=True)
        _upd(error=str(exc))
        await update_replay_run(run_id, {
            "status":        "failed",
            "finished_at":   datetime.utcnow(),
            "error_message": str(exc)[:500],
        })
        raise

    finally:
        _upd(running=False)

    return run_id


async def run_date_range_replay(
    start_date: str,
    end_date: str,
    universe_mode: str = "approx",
) -> int:
    """
    Run replay for every trading day in [start_date, end_date].
    Returns the replay_run_id for the parent run record.

    Processes dates sequentially (one per day) to avoid API rate limits.
    """
    if _replay_progress["running"]:
        raise RuntimeError("A replay is already in progress. Wait for it to finish.")

    trading_days = _trading_days_in_range(start_date, end_date)
    if not trading_days:
        raise ValueError(f"No trading days found between {start_date} and {end_date}")

    from database import (
        create_replay_run, update_replay_run,
        save_replay_candidates,
    )
    from replay.outcome_engine import compute_outcomes_for_run, detect_missed_movers

    _upd(running=True, mode="date_range", days_total=len(trading_days),
         days_completed=0, symbols_scanned=0, candidates_found=0,
         outcomes_computed=0, missed_found=0,
         error=None, started_at=datetime.utcnow())

    run_id = await create_replay_run({
        "mode":          "date_range",
        "start_date":    start_date,
        "end_date":      end_date,
        "universe_mode": universe_mode if universe_mode == "approx" else "approx",
        "total_days":    len(trading_days),
    })
    _upd(run_id=run_id)
    logger.info(
        f"[REPLAY] run_id={run_id} starting date_range "
        f"{start_date}→{end_date} ({len(trading_days)} days)"
    )

    total_candidates = total_outcomes = total_missed = total_symbols = 0

    try:
        for i, day in enumerate(trading_days):
            _upd(current_date=day, days_completed=i)
            logger.info(f"[REPLAY] run_id={run_id} day {i+1}/{len(trading_days)}: {day}")

            try:
                candidates = await _scan_one_date(day)
            except Exception as e:
                logger.warning(f"[REPLAY] scan failed for {day}: {e} — skipping")
                continue

            total_symbols    += _replay_progress.get("symbols_scanned", 0)
            total_candidates += len(candidates)
            _upd(candidates_found=total_candidates)

            await save_replay_candidates(run_id, day, candidates)

            outcomes = await compute_outcomes_for_run(run_id, day, candidates)
            total_outcomes += len(outcomes)
            _upd(outcomes_computed=total_outcomes)

            missed = await detect_missed_movers(run_id, day, candidates)
            total_missed += len(missed)
            _upd(missed_found=total_missed)

            # Partial progress update
            await update_replay_run(run_id, {
                "days_completed":     i + 1,
                "total_symbols":      total_symbols,
                "total_candidates":   total_candidates,
                "outcomes_computed":  total_outcomes,
                "missed_movers_found": total_missed,
            })

        _upd(days_completed=len(trading_days))
        await update_replay_run(run_id, {
            "status":               "completed",
            "finished_at":          datetime.utcnow(),
            "days_completed":       len(trading_days),
            "total_symbols":        total_symbols,
            "total_candidates":     total_candidates,
            "outcomes_computed":    total_outcomes,
            "missed_movers_found":  total_missed,
        })
        logger.info(
            f"[REPLAY] run_id={run_id} range complete: "
            f"{len(trading_days)} days, {total_candidates} candidates, "
            f"{total_outcomes} outcomes, {total_missed} missed movers"
        )

    except Exception as exc:
        logger.error(f"[REPLAY] run_id={run_id} range failed: {exc}", exc_info=True)
        _upd(error=str(exc))
        await update_replay_run(run_id, {
            "status":        "failed",
            "finished_at":   datetime.utcnow(),
            "error_message": str(exc)[:500],
        })
        raise

    finally:
        _upd(running=False)

    return run_id


# ── Core: scan one historical date ────────────────────────────────────────────

async def _scan_one_date(as_of_date: str) -> list[dict]:
    """
    Run the full universe scan pipeline for one historical date.

    Returns a list of candidate dicts (same shape as live ScanCandidate rows).

    LEAKAGE PREVENTION:
      All calls to fetch_candles_massive use as_of_date= so the API returns
      candles only up to and including as_of_date.  The grouped_daily call
      uses the exact date, so only EOD bars for that date are used for
      universe construction.  No live data is fetched.
    """
    from scanner.massive_data import (
        fetch_grouped_daily,
        fetch_candles_massive,
        fetch_ticker_type,
        get_us_etf_symbols,
    )
    from scanner.stock_universe_filter import is_common_stock, get_universe_filter_reason
    from scanner.indicators import calc_all
    from scanner.scoring import score_ticker
    from scanner.wyckoff import detect_regime
    from scanner.early_ignition import calc_ignition

    # Try to import sector_map NON_STOCK_SECURITIES; safe fallback if unavailable
    try:
        from scanner.sector_map import NON_STOCK_SECURITIES
    except Exception:
        NON_STOCK_SECURITIES = set()

    # Try to get cached sector info (best-effort; does not affect leakage)
    try:
        from database import get_sector_from_db
        _get_sector = get_sector_from_db
    except Exception:
        _get_sector = None

    logger.info(f"[REPLAY] _scan_one_date {as_of_date}")

    # ── Step 1: Universe for as_of_date ──────────────────────────────────────
    all_bars = await fetch_grouped_daily(as_of_date)
    if not all_bars:
        logger.warning(f"[REPLAY] No grouped daily data for {as_of_date}")
        return []

    # ── Step 2: Filter ────────────────────────────────────────────────────────
    MIN_PRICE, MAX_PRICE, MIN_VOLUME = 1.50, 500.0, 200_000
    _REGIME_ETFS = {"SPY", "QQQ", "XLE", "XLV", "XLU", "GLD", "IWM"}

    etf_symbols: set = set()
    try:
        etf_symbols = await get_us_etf_symbols()
    except Exception:
        pass

    filtered = {}
    for sym, bar in all_bars.items():
        if sym in _REGIME_ETFS:
            continue
        if sym.upper() in etf_symbols or sym.upper() in NON_STOCK_SECURITIES:
            continue
        if bar.get("volume", 0) < MIN_VOLUME:
            continue
        if not (MIN_PRICE <= bar.get("close", 0) <= MAX_PRICE):
            continue
        filtered[sym] = bar

    # ── Step 3: Pre-rank by dollar-vol × move bonus ───────────────────────────
    def _pre_score(b):
        c = b.get("close", 0)
        o = b.get("open") or c
        dv = c * b.get("volume", 0)
        mv = abs(c - o) / o * 100 if o > 0 else 0
        return dv * (1 + mv / 10)

    ranked = sorted(filtered.items(), key=lambda kv: _pre_score(kv[1]), reverse=True)[:2000]
    _upd(symbols_scanned=len(ranked))

    # ── Step 4: Get SPY candles (for regime context + relative strength) ──────
    spy_candles = []
    try:
        spy_candles = await fetch_candles_massive("SPY", days=200, as_of_date=as_of_date)
    except Exception:
        pass

    # Simple neutral regime (we don't replay market_regime from DB for now)
    # Using NEUTRAL avoids any live-data dependency in scoring.
    replay_regime = {"regime": "NEUTRAL", "spy_pct": 0.0}

    # ── Step 5: Fetch candles + score (batched) ───────────────────────────────
    BATCH_SIZE = 40
    candidates: list[dict] = []

    async def _process(sym: str, eod: dict) -> Optional[dict]:
        try:
            # Hard allowlist: verify this is a common stock before fetching
            # full candle history.  Saves API calls for ETFs/funds that slip
            # through the bulk exclusion list.
            # None = type lookup failed → allow through (conservative).
            ticker_type = await fetch_ticker_type(sym)
            if ticker_type is not None:
                meta = {"type": ticker_type}
                if not is_common_stock(meta):
                    reason = get_universe_filter_reason(meta)
                    logger.debug(
                        f"[REPLAY] {sym} excluded: "
                        f"type={ticker_type!r} universe_filter_reason={reason}"
                    )
                    return None

            candles = await fetch_candles_massive(sym, days=200, as_of_date=as_of_date)
            if not candles or len(candles) < 30:
                return None

            indicators = calc_all(candles)
            if not indicators:
                return None

            scored = score_ticker(indicators, replay_regime)
            tier = scored.get("tier", "SKIP")
            if tier not in ("FIRE", "ARM", "BASE"):
                return None

            wyckoff = {}
            try:
                wyckoff = detect_regime(candles)
            except Exception:
                pass

            # Compute ignition signal (calc_all does NOT include this — must call separately)
            ignition_result = {}
            try:
                ignition_result = calc_ignition(indicators, wyckoff)
            except Exception:
                pass

            # Sector from cache (best-effort, not time-sensitive for training)
            sector = None
            if _get_sector:
                try:
                    s = await _get_sector(sym)
                    sector = s.get("sector") if s else None
                except Exception:
                    pass

            snapshot = {**indicators, **scored, "wyckoff": wyckoff, **ignition_result}
            # Remove non-serialisable items from snapshot (keep it JSON-safe)
            clean_snapshot = {
                k: v for k, v in snapshot.items()
                if isinstance(v, (int, float, str, bool, type(None), list, dict))
            }

            return {
                "symbol":          sym,
                "price":           eod.get("close", 0),
                "tier":            tier,
                "total_score":     scored.get("total_score", 0),
                "wyckoff_state":   wyckoff.get("state", ""),
                "ignition_signal": ignition_result.get("ignition_signal", "NO_IGNITION"),
                "ribbon_signal":   bool(indicators.get("compression_and_bullish", False)),
                "sector":          sector,
                "snapshot":        clean_snapshot,
            }
        except Exception as exc:
            logger.debug(f"[REPLAY] {sym} on {as_of_date} skipped: {exc}")
            return None

    # Process in batches with a semaphore to stay polite to the Massive API
    sem = asyncio.Semaphore(8)

    async def _bounded(sym, eod):
        async with sem:
            return await _process(sym, eod)

    for i in range(0, len(ranked), BATCH_SIZE):
        batch = ranked[i: i + BATCH_SIZE]
        results = await asyncio.gather(*[_bounded(s, b) for s, b in batch])
        for r in results:
            if r:
                candidates.append(r)

    logger.info(
        f"[REPLAY] {as_of_date}: scored {len(ranked)} → "
        f"{len(candidates)} candidates (FIRE/ARM/BASE)"
    )
    return candidates
