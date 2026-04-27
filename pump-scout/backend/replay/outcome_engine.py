"""
Outcome Engine
==============
Computes forward returns for replay candidates and detects missed movers.

All data fetched here is FORWARD of the scan date, which is intentional —
we're measuring what happened AFTER the signal, not predicting the future
during the scan itself.

The scan date forms a strict boundary:
  - scan pipeline: data up to and including as_of_date  (no future leakage)
  - outcome engine: data from as_of_date + 1 onward     (measuring results)

Outcome labels
--------------
SUCCESSFUL_BREAKOUT  : return_5d >= +8%  AND max_drawdown <= -5%
EARLY_WINNER         : return_3d >= +5%  AND return_5d >= +5%
LATE_SIGNAL          : entry price already extended; max_gain < 3% and return_5d < 0
FAILED_BREAKOUT      : return_5d < -5%
NO_FOLLOW_THROUGH    : -5% <= return_5d < +3%  (flat / weak)
FALSE_POSITIVE       : return_5d < -10%

Missed mover detection
-----------------------
After scanning, we look at all stocks that had a strong forward move
(5d return >= MISSED_THRESHOLD) but were NOT in the candidate list.
We then try to diagnose why they were missed.

Why-missed codes
----------------
filtered_by_volume_gate    : volume < MIN_VOLUME on scan date
filtered_by_price_gate     : price outside MIN/MAX on scan date
no_structural_signal       : in universe but scored SKIP (weak indicators)
no_ignition                : passed scoring but no ignition/ribbon signal
not_in_universe            : not in grouped daily for that date (delisted?)
no_grouped_daily_bar       : present in universe but had no EOD bar
other                      : catch-all
"""
import asyncio
import logging
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

# ── Outcome thresholds (easy to tune in one place) ──────────────────────────
_SUCCESSFUL_BREAKOUT_RETURN   =  8.0   # 5d return %
_SUCCESSFUL_MAX_DD            = -5.0   # max drawdown % (must be better than this)
_EARLY_WINNER_RETURN_3D       =  5.0
_EARLY_WINNER_RETURN_5D       =  5.0
_FAILED_BREAKOUT_RETURN       = -5.0
_NO_FOLLOW_THROUGH_MAX        =  3.0
_FALSE_POSITIVE_RETURN        = -10.0

# Strong mover threshold for missed-opportunity detection
_MISSED_THRESHOLD_5D          = 10.0  # tickers with 5d return >= this are "strong movers"

# Horizons (trading-day approximations via calendar days: 1d≈1, 3d≈5cal, 5d≈7cal, 10d≈14cal)
_HORIZONS = {
    "1d":  1,
    "3d":  5,
    "5d":  7,
    "10d": 14,
}


# ── Forward price helper ──────────────────────────────────────────────────────

async def _fetch_forward_candles(symbol: str, as_of_date: str, max_cal_days: int = 20) -> list:
    """
    Fetch candles from as_of_date+1 to as_of_date+max_cal_days.
    Returns sorted candles, empty list on error.

    Uses fetch_candles_massive with no as_of_date cap so we get the actual
    future data (this is intentional — we're computing outcomes here).
    """
    try:
        from scanner.massive_data import fetch_candles_massive, MASSIVE_API_KEY
        import httpx

        if not MASSIVE_API_KEY:
            return []

        start = (date.fromisoformat(as_of_date) + timedelta(days=1)).strftime("%Y-%m-%d")
        end   = (date.fromisoformat(as_of_date) + timedelta(days=max_cal_days)).strftime("%Y-%m-%d")

        url = (
            f"https://api.massive.com/v2/aggs/ticker/{symbol.upper()}"
            f"/range/1/day/{start}/{end}"
        )
        params = {"apiKey": MASSIVE_API_KEY, "adjusted": "true", "sort": "asc", "limit": 50}

        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
            resp = await client.get(url, params=params)

        if resp.status_code != 200:
            return []

        data = resp.json()
        candles = [
            {"t": b.get("t"), "o": b.get("o"), "h": b.get("h"),
             "l": b.get("l"), "c": b.get("c"), "v": int(b.get("v") or 0)}
            for b in (data.get("results") or [])
        ]
        candles.sort(key=lambda x: x["t"])
        return candles

    except Exception as exc:
        logger.debug(f"_fetch_forward_candles {symbol} from {as_of_date}: {exc}")
        return []


def _label_outcome(return_5d: Optional[float], max_gain: Optional[float],
                   max_dd: Optional[float]) -> str:
    """Assign an explainable outcome label based on forward return metrics."""
    if return_5d is None:
        return "NO_DATA"
    if return_5d <= _FALSE_POSITIVE_RETURN:
        return "FALSE_POSITIVE"
    if return_5d <= _FAILED_BREAKOUT_RETURN:
        return "FAILED_BREAKOUT"
    if return_5d >= _SUCCESSFUL_BREAKOUT_RETURN and (max_dd is None or max_dd >= _SUCCESSFUL_MAX_DD):
        return "SUCCESSFUL_BREAKOUT"
    if (max_gain is not None and max_gain >= _EARLY_WINNER_RETURN_3D and
            return_5d >= _EARLY_WINNER_RETURN_5D):
        return "EARLY_WINNER"
    if return_5d < _NO_FOLLOW_THROUGH_MAX:
        return "NO_FOLLOW_THROUGH"
    return "LATE_SIGNAL"


async def compute_outcomes_for_run(
    run_id: int,
    as_of_date: str,
    candidates: list[dict],
) -> list[dict]:
    """
    For each candidate, fetch forward candles and compute outcome rows.
    Saves outcomes to replay_outcomes table.
    Returns list of outcome dicts.
    """
    if not candidates:
        return []

    from database import save_replay_outcomes, get_replay_candidates

    # Get persisted candidate IDs (needed for FK in outcome rows)
    persisted = await get_replay_candidates(run_id, limit=5000)
    id_map = {c["symbol"]: c["id"] for c in persisted if c["scan_date"] == as_of_date}

    # Also get SPY forward candles for alpha calculation
    spy_forwards = await _fetch_forward_candles("SPY", as_of_date, max_cal_days=20)

    def _spy_return(cal_days: int) -> Optional[float]:
        """Return SPY return at approximately cal_days calendar days forward."""
        candles = [c for c in spy_forwards if c["t"] is not None]
        if len(candles) >= max(1, cal_days // 2):
            idx = min(len(candles) - 1, max(0, cal_days // 2 - 1))
            entry = spy_forwards[0]["o"] if spy_forwards else None
            exit_p = candles[idx]["c"]
            if entry and entry > 0:
                return round((exit_p - entry) / entry * 100, 2)
        return None

    all_outcomes: list[dict] = []
    sem = asyncio.Semaphore(6)

    async def _process_candidate(cand: dict):
        async with sem:
            symbol = cand["symbol"]
            entry_price = cand.get("price")
            cand_id = id_map.get(symbol)
            if not cand_id:
                return

            forwards = await _fetch_forward_candles(symbol, as_of_date, max_cal_days=20)
            if not forwards:
                return

            closes = [c["c"] for c in forwards]
            highs  = [c["h"] for c in forwards]
            lows   = [c["l"] for c in forwards]

            for horizon, cal_days in _HORIZONS.items():
                idx = min(len(forwards) - 1, max(0, cal_days - 1))
                if idx >= len(forwards):
                    continue

                exit_price = forwards[idx]["c"]
                ret = None
                if entry_price and entry_price > 0:
                    ret = round((exit_price - entry_price) / entry_price * 100, 2)

                # Max gain / max drawdown within the window
                window_highs = highs[:idx + 1]
                window_lows  = lows[:idx + 1]
                max_gain = None
                max_dd   = None
                if entry_price and entry_price > 0:
                    if window_highs:
                        max_gain = round((max(window_highs) - entry_price) / entry_price * 100, 2)
                    if window_lows:
                        max_dd = round((min(window_lows) - entry_price) / entry_price * 100, 2)

                # ── MFE fields ────────────────────────────────────────────────
                max_high_val  = None
                max_gain_day  = None
                max_gain_date = None
                giveback_pct  = None
                if entry_price and entry_price > 0 and window_highs:
                    _peak_val = max(window_highs)
                    _peak_idx = window_highs.index(_peak_val)
                    max_high_val  = _peak_val
                    max_gain_day  = _peak_idx  # 0-based day offset within window
                    _t = forwards[_peak_idx].get("t")
                    if _t:
                        from datetime import datetime, timezone as _tz
                        max_gain_date = datetime.fromtimestamp(
                            _t / 1000, tz=_tz.utc
                        ).strftime("%Y-%m-%d")
                    if max_gain is not None and ret is not None:
                        giveback_pct = round(max_gain - ret, 2)

                # ── Hit-threshold fields (10d only) ───────────────────────────
                hit_5pct = hit_10pct = hit_20pct = hit_50pct = hit_100pct = None
                hit_5d   = hit_10d  = hit_20d   = hit_50d   = hit_100d   = None
                if horizon == "10d" and entry_price and entry_price > 0 and window_highs:
                    for _di, _h in enumerate(window_highs):
                        _g = (_h - entry_price) / entry_price * 100
                        if hit_5d   is None and _g >= 5:    hit_5d   = _di; hit_5pct   = True
                        if hit_10d  is None and _g >= 10:   hit_10d  = _di; hit_10pct  = True
                        if hit_20d  is None and _g >= 20:   hit_20d  = _di; hit_20pct  = True
                        if hit_50d  is None and _g >= 50:   hit_50d  = _di; hit_50pct  = True
                        if hit_100d is None and _g >= 100:  hit_100d = _di; hit_100pct = True
                    hit_5pct   = bool(hit_5pct);   hit_10pct = bool(hit_10pct)
                    hit_20pct  = bool(hit_20pct);  hit_50pct = bool(hit_50pct)
                    hit_100pct = bool(hit_100pct)

                spy_ret = _spy_return(cal_days)
                alpha = round(ret - spy_ret, 2) if (ret is not None and spy_ret is not None) else None

                # Only label at 5d horizon (primary)
                label = _label_outcome(ret, max_gain, max_dd) if horizon == "5d" else None

                all_outcomes.append({
                    "replay_candidate_id": cand_id,
                    "replay_run_id":       run_id,
                    "scan_date":           as_of_date,
                    "symbol":              symbol,
                    "horizon":             horizon,
                    "entry_price":         entry_price,
                    "exit_price":          exit_price,
                    "return_pct":          ret,
                    "max_gain_pct":        max_gain,
                    "max_drawdown_pct":    max_dd,
                    "alpha_vs_spy":        alpha,
                    "outcome_label":       label,
                    # MFE
                    "max_high":            max_high_val,
                    "max_gain_day":        max_gain_day,
                    "max_gain_date":       max_gain_date,
                    "giveback_pct":        giveback_pct,
                    "hit_5pct":            hit_5pct,
                    "hit_10pct":           hit_10pct,
                    "hit_20pct":           hit_20pct,
                    "hit_50pct":           hit_50pct,
                    "hit_100pct":          hit_100pct,
                    "hit_5pct_day":        hit_5d,
                    "hit_10pct_day":       hit_10d,
                    "hit_20pct_day":       hit_20d,
                    "hit_50pct_day":       hit_50d,
                    "hit_100pct_day":      hit_100d,
                })

    await asyncio.gather(*[_process_candidate(c) for c in candidates])

    if all_outcomes:
        await save_replay_outcomes(all_outcomes)

    logger.info(
        f"[OUTCOME] run_id={run_id} {as_of_date}: "
        f"{len(all_outcomes)} outcome rows for {len(candidates)} candidates"
    )
    return all_outcomes


async def detect_missed_movers(
    run_id: int,
    as_of_date: str,
    candidates: list[dict],
) -> list[dict]:
    """
    Find stocks that made a strong forward move (>= MISSED_THRESHOLD_5D %)
    but were NOT in the candidate list.

    We examine the top-volume stocks from grouped_daily for that date and
    check their 5d forward return.  Candidates that were already found
    are excluded.  For each missed mover we diagnose why.

    Returns list of missed mover dicts (also persisted to replay_missed_movers).
    """
    from scanner.massive_data import fetch_grouped_daily, fetch_ticker_type, get_us_etf_symbols
    from scanner.stock_universe_filter import is_common_stock, get_universe_filter_reason
    from database import save_replay_missed_movers

    try:
        from scanner.sector_map import NON_STOCK_SECURITIES
    except Exception:
        NON_STOCK_SECURITIES = set()

    logger.info(f"[MISSED] run_id={run_id} detecting missed movers for {as_of_date}")

    # Universe for the date
    all_bars = await fetch_grouped_daily(as_of_date)
    if not all_bars:
        return []

    etf_set: set = set()
    try:
        etf_set = await get_us_etf_symbols()
    except Exception:
        pass

    _REGIME_ETFS = {"SPY", "QQQ", "XLE", "XLV", "XLU", "GLD", "IWM"}
    MIN_VOLUME, MIN_PRICE, MAX_PRICE = 100_000, 1.50, 500.0  # must match replay_engine MIN_VOLUME

    # Symbols that the scanner DID find
    found_symbols = {c["symbol"] for c in candidates}

    # Check top-volume universe stocks for forward returns
    universe_syms = [
        sym for sym, bar in all_bars.items()
        if sym not in _REGIME_ETFS
        and sym not in etf_set
        and sym not in NON_STOCK_SECURITIES
        and bar.get("volume", 0) >= 50_000   # looser gate here — we want to catch what was missed
        and MIN_PRICE <= bar.get("close", 0) <= MAX_PRICE
    ]

    missed_movers: list[dict] = []
    sem = asyncio.Semaphore(6)
    checked = 0

    async def _check(sym: str):
        nonlocal checked
        async with sem:
            if sym in found_symbols:
                return   # already caught — not a miss

            bar = all_bars.get(sym, {})
            entry_price = bar.get("close")
            if not entry_price:
                return

            forwards = await _fetch_forward_candles(sym, as_of_date, max_cal_days=10)
            if not forwards or len(forwards) < 3:
                return

            # Approximate 5d return (use bar index 4 or last available)
            idx_5d = min(len(forwards) - 1, 4)
            exit_5d = forwards[idx_5d]["c"]
            ret_5d = round((exit_5d - entry_price) / entry_price * 100, 2) if entry_price > 0 else None

            if ret_5d is None or ret_5d < _MISSED_THRESHOLD_5D:
                return   # not a strong mover — not interesting

            # 3d return
            idx_3d = min(len(forwards) - 1, 2)
            ret_3d = round((forwards[idx_3d]["c"] - entry_price) / entry_price * 100, 2)
            # 10d return (if available)
            idx_10d = min(len(forwards) - 1, 9)
            ret_10d = round((forwards[idx_10d]["c"] - entry_price) / entry_price * 100, 2) if len(forwards) > 5 else None

            # Hard allowlist: confirm this is a common stock before recording
            # as a missed mover.  ETFs/funds that evaded the bulk exclusion
            # list should not appear in missed-mover research output.
            # Only called here (after threshold check) — not for the full universe.
            try:
                ticker_type = await fetch_ticker_type(sym)
                if ticker_type is not None:
                    meta = {"type": ticker_type}
                    if not is_common_stock(meta):
                        reason = get_universe_filter_reason(meta)
                        logger.info(
                            f"[MISSED] {sym} excluded: "
                            f"type={ticker_type!r} universe_filter_reason={reason}"
                        )
                        return
            except Exception:
                pass   # type lookup failure → allow through (conservative)

            # Diagnose why missed
            why = _diagnose_why_missed(sym, bar, all_bars, found_symbols,
                                        etf_set, NON_STOCK_SECURITIES, MIN_VOLUME, MIN_PRICE, MAX_PRICE)

            missed_movers.append({
                "scan_date":        as_of_date,
                "symbol":           sym,
                "price_on_date":    entry_price,
                "future_return_3d": ret_3d,
                "future_return_5d": ret_5d,
                "future_return_10d":ret_10d,
                "why_missed":       why,
                "details": {
                    "volume_on_date":  bar.get("volume"),
                    "open":            bar.get("open"),
                    "close":           bar.get("close"),
                },
            })

    await asyncio.gather(*[_check(s) for s in universe_syms])

    # Sort by 5d return descending — most impressive misses first
    missed_movers.sort(key=lambda m: m.get("future_return_5d") or 0, reverse=True)

    if missed_movers:
        await save_replay_missed_movers(run_id, missed_movers)

    logger.info(
        f"[MISSED] run_id={run_id} {as_of_date}: "
        f"{len(missed_movers)} missed movers (>={_MISSED_THRESHOLD_5D}% 5d)"
    )
    return missed_movers


def _diagnose_why_missed(
    symbol: str,
    bar: dict,
    all_bars: dict,
    found_symbols: set,
    etf_set: set,
    non_stock: set,
    min_vol: int,
    min_price: float,
    max_price: float,
) -> str:
    """Return a why_missed code for one symbol."""
    if symbol not in all_bars:
        return "not_in_universe"
    if symbol in etf_set or symbol in non_stock:
        return "filtered_as_non_equity"
    vol = bar.get("volume", 0)
    close = bar.get("close", 0)
    if vol < min_vol:
        return "filtered_by_volume_gate"
    if not (min_price <= close <= max_price):
        return "filtered_by_price_gate"
    # Was in universe but not scored FIRE/ARM/BASE.
    # Sub-classify using scan-day bar anatomy (open/close only — no history fetch).
    o = bar.get("open") or 0
    c = bar.get("close") or 0
    if o > 0:
        ratio = c / o
        if ratio >= 1.25:
            return "NSS_PARABOLIC"       # already running ≥25% on scan day — engine one cycle late
        if ratio <= 0.93:
            return "NSS_SPRING_REVERSAL" # bearish bar (Wyckoff spring) — L34 bull-candle gate misses it
        if abs(c - o) / o < 0.015:
            return "NSS_QUIET_BASE"      # near-flat, extreme compression — nothing fires
    return "NSS_BREAKOUT_ORPHAN"         # moderate bar, no L34/G4/B2 condition met
