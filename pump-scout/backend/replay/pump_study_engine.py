"""
Pump Study Engine — Phase 3C: PRE/PUMP/POST Snapshots
======================================================

Detects raw 4x pump candidates in historical price data using a sliding window,
clusters overlapping detections, and builds daily indicator snapshots for each
canonical episode across three phases: PRE, PUMP, POST.

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
Phase 3B  ✓  Clustering → pump_clusters + pump_episodes; back-fill detections
Phase 3C  ✓  PRE / PUMP / POST daily snapshots → pump_episode_snapshots
Phase 3D  ✗  Timeline events / comparison groups (not yet)
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

# Two raw detections for the same symbol are merged into one cluster when their
# [window_start, window_peak] intervals overlap or are within this many calendar
# days of each other.  Catches consecutive start-dates that all observe the same
# underlying explosive move.
_CLUSTER_PROXIMITY_DAYS: int = 5

# ── Progress tracker ──────────────────────────────────────────────────────────

_pump_study_progress: dict = {
    "running":        False,
    "run_id":         None,
    "phase":          None,
    "symbols_total":  0,
    "symbols_done":   0,
    "raw_detections": 0,
    "clusters":       0,
    "episodes":       0,
    "error":          None,
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


# ── Clustering ────────────────────────────────────────────────────────────────

def _cluster_detections(
    symbol: str,
    detections: list[dict],
    proximity_days: int = _CLUSTER_PROXIMITY_DAYS,
) -> list[dict]:
    """
    Group overlapping / near-overlapping raw detections for one symbol.

    Merge rule
    ----------
    Detections A and B belong to the same cluster when their date windows
    [window_start, window_peak] overlap or come within `proximity_days`
    calendar days of each other:

        A.start  <=  B.peak  + proximity_days
        AND
        B.start  <=  A.peak  + proximity_days

    This collapses the flood of consecutive start-dates that all "see" the
    same underlying explosive move into a single cluster.

    Canonical selection
    -------------------
    The canonical detection is the one with the **earliest window_start_date**
    in the cluster — the first trading day from which the move is observable.
    Among equal start dates the highest multiple wins (tiebreak).

    Returns
    -------
    List of cluster dicts.  Each dict contains:
        cluster_id           : "{symbol}_{canonical_start_date}"
        symbol
        cluster_start_date   : earliest start across all detections in cluster
        cluster_end_date     : latest peak  across all detections in cluster
        canonical_start_date : canonical detection's window_start_date
        canonical_peak_date  : canonical detection's window_peak_date
        raw_detection_count  : total raw hits merged
        canonical            : the canonical detection dict (reference)
        detections           : all raw detection dicts in this cluster
                               (cluster_id and is_canonical already set on each)
    """
    if not detections:
        return []

    # Sort by start date (ascending) then multiple (descending) for determinism
    sorted_dets = sorted(
        detections,
        key=lambda d: (d["window_start_date"], -d["multiple"]),
    )

    # Greedy interval-merge with proximity extension
    prox = timedelta(days=proximity_days)
    clusters: list[dict] = []

    for det in sorted_dets:
        det_start = date.fromisoformat(det["window_start_date"])
        det_peak  = date.fromisoformat(det["window_peak_date"])

        merged = False
        for cl in clusters:
            cl_start = date.fromisoformat(cl["_start"])
            cl_peak  = date.fromisoformat(cl["_peak"])

            near_overlap = (
                det_start <= cl_peak  + prox
                and cl_start <= det_peak + prox
            )
            if near_overlap:
                cl["_dets"].append(det)
                # Extend the cluster envelope if this detection reaches further
                if det["window_peak_date"] > cl["_peak"]:
                    cl["_peak"] = det["window_peak_date"]
                merged = True
                break   # greedy: first matching cluster wins

        if not merged:
            clusters.append({
                "_start": det["window_start_date"],
                "_peak":  det["window_peak_date"],
                "_dets":  [det],
            })

    # Finalise: choose canonical, assign cluster_id, back-fill detection dicts
    result: list[dict] = []
    for cl in clusters:
        dets_in = cl["_dets"]

        # Canonical = earliest start; tiebreak = highest multiple
        canonical = min(
            dets_in,
            key=lambda d: (d["window_start_date"], -d["multiple"]),
        )

        cluster_id = f"{symbol}_{canonical['window_start_date']}"

        # Back-fill cluster_id / is_canonical on every detection in this cluster
        for d in dets_in:
            d["cluster_id"]   = cluster_id
            d["is_canonical"] = (d is canonical)

        result.append({
            "cluster_id":           cluster_id,
            "symbol":               symbol,
            "cluster_start_date":   cl["_start"],
            "cluster_end_date":     cl["_peak"],
            "canonical_start_date": canonical["window_start_date"],
            "canonical_peak_date":  canonical["window_peak_date"],
            "raw_detection_count":  len(dets_in),
            "canonical":            canonical,
            "detections":           dets_in,
        })

    return result


# ── Episode builder ───────────────────────────────────────────────────────────

def _build_episode_from_cluster(run_id: int, cluster: dict) -> dict:
    """
    Build a pump_episodes row dict from a cluster's canonical detection.

    Fields that require candle data / later analysis (pump_type, had_ribbon,
    sector, etc.) are left None / False — they will be enriched in Phase 3C+.
    """
    canon = cluster["canonical"]
    return {
        "run_id":                   run_id,
        "cluster_id":               cluster["cluster_id"],
        "symbol":                   cluster["symbol"],
        "pump_start_date":          canon["window_start_date"],
        "pump_peak_date":           canon["window_peak_date"],
        "pump_window_days":         canon["window_days"],
        "start_price":              canon["start_price"],
        "peak_price":               canon["peak_price"],
        "pump_multiple":            canon["multiple"],
        "pump_return_pct":          canon["return_pct"],
        "days_to_peak":             canon["days_to_peak"],
        "days_to_double":           canon["days_to_double"],
        "max_drawdown_before_peak": canon["max_drawdown_before_peak"],
        # Enriched in Phase 3C+
        "pump_type":                None,
        "was_in_universe":          True,
        "was_flagged_by_scanner":   False,
        "filter_reason":            None,
        "had_ribbon":               False,
        "had_ignition":             False,
        "strongest_wyckoff_state":  None,
        "strongest_retest_before":  None,
        "max_volume_anomaly":       None,
        "largest_gap_pct":          None,
        "sector":                   None,
        "industry":                 None,
        "summary":                  {},
    }


# ── Phase 3C: snapshot helpers ───────────────────────────────────────────────

# PRE window: N trading days before canonical_start_date
_PRE_WINDOW_DAYS: int  = 40
# POST window: N trading days after canonical_peak_date
_POST_WINDOW_DAYS: int = 15
# Minimum candles needed for calc_all() (Bollinger / CMF need ~20)
_MIN_CANDLES_INDICATORS: int = 20
# Minimum candles needed for detect_regime() (Wyckoff needs ~60)
_MIN_CANDLES_REGIME: int = 60


def _to_scanner_fmt(candle: dict) -> dict:
    """
    Convert a candle dict from _fetch_candles_range format to scanner format.

    _fetch_candles_range → {date, open, high, low, close, volume}
    calc_all() expects  → {o, h, l, c, v}
    """
    return {
        "o": candle.get("open"),
        "h": candle.get("high"),
        "l": candle.get("low"),
        "c": candle.get("close"),
        "v": candle.get("volume"),
    }


def _build_snapshots(
    episode_id: int,
    run_id:     int,
    symbol:     str,
    episode:    dict,
    all_candles: list[dict],
) -> list[dict]:
    """
    Build daily PRE/PUMP/POST indicator snapshots for one canonical episode.

    PRE  = _PRE_WINDOW_DAYS  trading days before pump_start_date (exclusive)
    PUMP = pump_start_date through pump_peak_date (inclusive on both ends)
    POST = _POST_WINDOW_DAYS trading days after  pump_peak_date  (exclusive)

    For each day in the combined window we:
      1. Convert a trailing slice of candles (ending on that day) to scanner fmt
      2. Call calc_all()       → core indicators (needs >= _MIN_CANDLES_INDICATORS bars)
      3. Call detect_regime()  → wyckoff state   (needs >= _MIN_CANDLES_REGIME bars)
      4. Call classify_ribbon()→ ribbon class
      5. Call calc_ignition()  → ignition bucket
      6. Call score_toxicity() → toxicity score / level
      7. Call score_pump()     → pump_bucket

    Fields that do not exist in the current codebase
    (sequence_type, structural_bias, retest_*, bearish_state, bearish_quality,
     bullish_quality, accumulation_bonus_hint, distribution_penalty_hint,
     MACD_state, sector, industry, market_regime) are stored as None —
    pending future enrichment in a later phase.

    Parameters
    ----------
    episode_id  : DB id for the saved PumpEpisode row
    run_id      : associated run id
    symbol      : ticker
    episode     : dict with pump_start_date / pump_peak_date / start_price
    all_candles : complete candle list for this symbol fetched during detection
                  (sorted asc, format: {date, open, high, low, close, volume})

    Returns
    -------
    List of snapshot dicts ready for save_pump_episode_snapshots().
    """
    from scanner.indicators   import calc_all
    from scanner.wyckoff      import detect_regime
    from scanner.ribbon_engine import classify_ribbon
    from scanner.early_ignition import calc_ignition
    from scanner.toxic_filter  import score_toxicity
    from scanner.pump_engine   import score_pump

    pump_start = episode["pump_start_date"]
    pump_peak  = episode["pump_peak_date"]
    start_price = episode.get("start_price") or 0.0

    # Index candles by date for O(1) lookup
    date_to_idx: dict[str, int] = {c["date"]: i for i, c in enumerate(all_candles)}

    # Identify the continuous trading-day sequence in all_candles
    all_dates = [c["date"] for c in all_candles]

    # Find indices for start and peak in the candle list
    start_idx = date_to_idx.get(pump_start)
    peak_idx  = date_to_idx.get(pump_peak)

    if start_idx is None or peak_idx is None:
        logger.warning(
            f"[PUMP_STUDY][3C] {symbol}: episode dates not in candle range "
            f"(start={pump_start}, peak={pump_peak})"
        )
        return []

    # Build the three windows as index slices into all_dates
    pre_start_idx  = max(0, start_idx - _PRE_WINDOW_DAYS)
    post_end_idx   = min(len(all_dates) - 1, peak_idx + _POST_WINDOW_DAYS)

    window_dates = all_dates[pre_start_idx : post_end_idx + 1]

    snapshots: list[dict] = []

    for d in window_dates:
        idx = date_to_idx[d]
        candle = all_candles[idx]

        # ── Determine phase and relative offsets ──────────────────────────────
        if d < pump_start:
            phase = "PRE"
        elif d <= pump_peak:
            phase = "PUMP"
        else:
            phase = "POST"

        # relative_day_from_start: negative = before start, 0 = start day, positive = after
        # Compute as trading-day offset from start_idx
        rel_from_start = idx - start_idx

        # relative_day_from_peak: negative = before peak, 0 = peak day, positive = after
        rel_from_peak  = idx - peak_idx

        # ── Build trailing candle slice for indicator computation ─────────────
        # Use all candles up to and including this bar (gives indicators full history)
        trailing_raw = all_candles[: idx + 1]
        trailing_sc  = [_to_scanner_fmt(c) for c in trailing_raw]

        # ── Raw OHLCV for this bar ────────────────────────────────────────────
        o_price = candle.get("open")
        h_price = candle.get("high")
        l_price = candle.get("low")
        c_price = candle.get("close")
        volume  = candle.get("volume")

        # ── Derived price fields ──────────────────────────────────────────────
        # gap_pct: open vs prior close
        gap_pct: Optional[float] = None
        if idx > 0 and o_price and all_candles[idx - 1].get("close"):
            prior_close = all_candles[idx - 1]["close"]
            if prior_close:
                gap_pct = round((o_price - prior_close) / prior_close * 100, 4)

        intraday_range_pct: Optional[float] = None
        if h_price and l_price and l_price > 0:
            intraday_range_pct = round((h_price - l_price) / l_price * 100, 4)

        close_position_in_bar: Optional[float] = None
        if h_price and l_price and c_price and (h_price - l_price) > 0:
            close_position_in_bar = round(
                (c_price - l_price) / (h_price - l_price), 4
            )

        daily_return_pct: Optional[float] = None
        if c_price and o_price and o_price > 0:
            daily_return_pct = round((c_price - o_price) / o_price * 100, 4)

        cum_return_pct: Optional[float] = None
        if c_price and start_price and start_price > 0:
            cum_return_pct = round((c_price - start_price) / start_price * 100, 4)

        # ── Indicators ────────────────────────────────────────────────────────
        indicators: dict = {}
        regime:     dict = {}
        ribbon_class:    Optional[str] = None
        ignition:        dict = {}
        toxicity:        dict = {}
        pump_result:     dict = {}

        n_trailing = len(trailing_sc)

        if n_trailing >= _MIN_CANDLES_INDICATORS:
            try:
                indicators = calc_all(trailing_sc) or {}
            except Exception as exc:
                logger.debug(f"[PUMP_STUDY][3C] {symbol}/{d} calc_all: {exc}")
                indicators = {}

            try:
                ribbon_class = classify_ribbon(indicators)
            except Exception:
                ribbon_class = None

            try:
                toxicity = score_toxicity(indicators, price=c_price or 0.0) or {}
            except Exception:
                toxicity = {}

            try:
                pump_result = score_pump(indicators, price=c_price or 0.0) or {}
            except Exception:
                pump_result = {}

        if n_trailing >= _MIN_CANDLES_REGIME:
            try:
                regime = detect_regime(trailing_sc) or {}
            except Exception as exc:
                logger.debug(f"[PUMP_STUDY][3C] {symbol}/{d} detect_regime: {exc}")
                regime = {}

            if indicators and regime:
                try:
                    ignition = calc_ignition(indicators, regime) or {}
                except Exception:
                    ignition = {}

        # ── Extract individual indicator fields ───────────────────────────────
        rsi_data  = indicators.get("rsi", {}) or {}
        obv_data  = indicators.get("obv", {}) or {}

        # volume_vs_avg20: vol_z and avg_vol_20 from calc_all
        avg_vol_20      = indicators.get("avg_vol_20") or None
        volume_vs_avg20: Optional[float] = None
        if volume and avg_vol_20 and avg_vol_20 > 0:
            volume_vs_avg20 = round(volume / avg_vol_20, 4)

        # ── Full snapshot dict ────────────────────────────────────────────────
        # snapshot_json stores the raw indicator sub-dicts for deep-dive queries
        snapshot_detail = {
            "indicators":    indicators,
            "regime":        regime,
            "ignition":      ignition,
            "toxicity":      toxicity,
            "pump":          pump_result,
        }

        snapshots.append({
            "episode_id":             episode_id,
            "run_id":                 run_id,
            "symbol":                 symbol,
            "date":                   d,
            "window_phase":           phase,
            "relative_day_from_start": rel_from_start,
            "relative_day_from_peak":  rel_from_peak,
            # OHLCV
            "open":                   o_price,
            "high":                   h_price,
            "low":                    l_price,
            "close":                  c_price,
            "volume":                 volume,
            # Derived price fields
            "gap_pct":                gap_pct,
            "intraday_range_pct":     intraday_range_pct,
            "close_position":         close_position_in_bar,
            "daily_return_pct":       daily_return_pct,
            "cum_return_pct":         cum_return_pct,
            # Volume
            "volume_vs_avg20":        volume_vs_avg20,
            "volume_zscore":          indicators.get("vol_z"),
            # Volatility
            "atr_pct":                indicators.get("atr_pct"),
            "bb_width":               indicators.get("bb_width"),
            "bb_squeeze":             indicators.get("bb_squeeze"),
            # Momentum
            "rsi":                    rsi_data.get("value"),
            "cmf":                    indicators.get("cmf"),
            # Structure
            "ribbon_class":           ribbon_class,
            "wyckoff_state":          regime.get("state"),
            # snapshot_json stores all sub-dicts for deep inspection
            "snapshot":               snapshot_detail,
        })

    return snapshots


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
    Phase 3C entry point.

    Params:
        start_date      str   YYYY-MM-DD  scan window start
        end_date        str   YYYY-MM-DD  scan window end
        window_days     int   (default 14) forward look-ahead in trading bars
        min_multiple    float (default 4.0) minimum pump multiple to record
        universe_limit  int   (default 0 = no limit)

    Execution order
    ---------------
    1. Build symbol universe
    2. Per-symbol (parallel, Semaphore 8):
         a. Fetch candles  (kept in candle_map for Phase 3C)
         b. Detect raw pumps → in-memory hits
         c. Cluster hits → in-memory clusters
         d. Back-fill cluster_id / is_canonical on hit dicts (in memory)
    3. Save enriched detections (cluster_id + is_canonical already set)
    4. Save cluster records (canonical_episode_id = None initially)
    5. Build episode dicts from each cluster's canonical detection
    6. Save episodes → receive inserted IDs
    7. Back-fill canonical_episode_id on each cluster row
    8. Build PRE/PUMP/POST daily snapshots for each episode (Phase 3C)
    9. Save snapshots in batches
    10. Update run counts + advance status to snapshots_complete

    Not done yet (Phase 3D+):
        ✗ Timeline milestone events
        ✗ Comparison groups
    """
    global _pump_study_progress

    from database import (
        update_pump_study_run,
        save_pump_episode_detections,
        save_pump_clusters,
        save_pump_episodes,
        save_pump_episode_snapshots,
        update_pump_cluster_episode_id,
    )

    _pump_study_progress.update({
        "running":        True,
        "run_id":         run_id,
        "phase":          "INIT",
        "symbols_total":  0,
        "symbols_done":   0,
        "raw_detections": 0,
        "clusters":       0,
        "episodes":       0,
        "snapshots":      0,
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

        # Candle fetch range:
        #   - PRE window needs _PRE_WINDOW_DAYS trading days before start_date
        #     AND detect_regime() needs _MIN_CANDLES_REGIME bars of history.
        #     We fetch 100 calendar days before start to safely cover both.
        #   - POST window needs _POST_WINDOW_DAYS trading days after peak_date,
        #     and the peak can be at most window_days*2 trading bars after end_date.
        fetch_from = (
            date.fromisoformat(start_date) - timedelta(days=100)
        ).isoformat()
        fetch_to = (
            date.fromisoformat(end_date) + timedelta(days=window_days * 2 + 30)
        ).isoformat()

        # ── 1. Universe ───────────────────────────────────────────────────────
        _pump_study_progress["phase"] = "UNIVERSE"
        symbols = await _build_universe(start_date, end_date, univ_limit)
        _pump_study_progress["symbols_total"] = len(symbols)

        if not symbols:
            raise RuntimeError("Universe is empty — check date range and API key")

        # ── 2. Per-symbol: detect + cluster (parallel) ────────────────────────
        _pump_study_progress["phase"] = "DETECTION"

        # asyncio is single-threaded; list.extend / dict assignment are safe here.
        all_detections: list[dict] = []
        all_clusters:   list[dict] = []
        # Keep full candle lists for snapshot building in Phase 3C
        candle_map: dict[str, list[dict]] = {}

        sem = asyncio.Semaphore(8)

        async def _process(sym: str) -> None:
            async with sem:
                candles = await _fetch_candles_range(sym, fetch_from, fetch_to)
                if not candles or len(candles) < window_days + 1:
                    _pump_study_progress["symbols_done"] += 1
                    return

                # Phase 3A: raw detection
                hits = _detect_raw_pumps(
                    sym, candles,
                    scan_start   = start_date,
                    scan_end     = end_date,
                    window_days  = window_days,
                    min_multiple = min_multiple,
                )
                if not hits:
                    _pump_study_progress["symbols_done"] += 1
                    return

                # Phase 3B: cluster + back-fill cluster_id/is_canonical in memory
                clusters = _cluster_detections(sym, hits)
                all_detections.extend(hits)
                all_clusters.extend(clusters)

                # Phase 3C: retain candles for snapshot building
                candle_map[sym] = candles

                _pump_study_progress["symbols_done"]   += 1
                _pump_study_progress["raw_detections"]  = len(all_detections)
                _pump_study_progress["clusters"]        = len(all_clusters)

                logger.debug(
                    f"[PUMP_STUDY] {sym}: {len(hits)} detections → "
                    f"{len(clusters)} cluster(s)"
                )

        await asyncio.gather(*[_process(s) for s in symbols])

        # ── 3. Save enriched raw detections ───────────────────────────────────
        _pump_study_progress["phase"] = "SAVING_DETECTIONS"
        saved_det = await save_pump_episode_detections(run_id, all_detections)

        # ── 4. Save cluster records ────────────────────────────────────────────
        _pump_study_progress["phase"] = "SAVING_CLUSTERS"
        cluster_rows = [
            {
                "run_id":               run_id,
                "cluster_id":           cl["cluster_id"],
                "symbol":               cl["symbol"],
                "cluster_start_date":   cl["cluster_start_date"],
                "cluster_end_date":     cl["cluster_end_date"],
                "canonical_start_date": cl["canonical_start_date"],
                "canonical_peak_date":  cl["canonical_peak_date"],
                "raw_detection_count":  cl["raw_detection_count"],
            }
            for cl in all_clusters
        ]
        await save_pump_clusters(cluster_rows)

        # ── 5 & 6. Build + save canonical episodes ────────────────────────────
        _pump_study_progress["phase"] = "SAVING_EPISODES"
        episode_dicts = [
            _build_episode_from_cluster(run_id, cl) for cl in all_clusters
        ]
        episode_ids: list[int] = await save_pump_episodes(run_id, episode_dicts)
        _pump_study_progress["episodes"] = len(episode_ids)

        # ── 7. Back-fill canonical_episode_id on cluster rows ─────────────────
        _pump_study_progress["phase"] = "BACKFILL_CLUSTERS"
        for cl, ep_id in zip(all_clusters, episode_ids):
            await update_pump_cluster_episode_id(run_id, cl["cluster_id"], ep_id)

        # ── 8 & 9. Build + save PRE/PUMP/POST snapshots (Phase 3C) ───────────
        _pump_study_progress["phase"] = "SNAPSHOTS"
        total_snapshots = 0

        for cl, ep_id in zip(all_clusters, episode_ids):
            sym = cl["symbol"]
            sym_candles = candle_map.get(sym)
            if not sym_candles:
                continue

            # Reconstruct episode dict needed by _build_snapshots
            canon = cl["canonical"]
            ep_dict = {
                "pump_start_date": canon["window_start_date"],
                "pump_peak_date":  canon["window_peak_date"],
                "start_price":     canon["start_price"],
            }

            snaps = _build_snapshots(ep_id, run_id, sym, ep_dict, sym_candles)
            if snaps:
                saved_snaps = await save_pump_episode_snapshots(snaps)
                total_snapshots += saved_snaps
                _pump_study_progress["snapshots"] = total_snapshots

        # ── 10. Finalise run ──────────────────────────────────────────────────
        await update_pump_study_run(run_id, {
            "status":              "snapshots_complete",
            "symbols_scanned":     len(symbols),
            "raw_detection_count": saved_det,
            "cluster_count":       len(all_clusters),
            "episode_count":       len(episode_ids),
            "snapshot_count":      total_snapshots,
            "finished_at":         datetime.utcnow(),
            "notes": (
                f"Phase 3C complete: {len(symbols)} symbols, "
                f"{saved_det} raw detections, {len(all_clusters)} clusters, "
                f"{len(episode_ids)} episodes, {total_snapshots} snapshots. "
                f"Timeline events / comparison groups pending (Phase 3D+)."
            ),
        })

        _pump_study_progress.update({
            "running": False,
            "phase":   "SNAPSHOTS_COMPLETE",
        })

        logger.info(
            f"[PUMP_STUDY] run_id={run_id} Phase 3C done: "
            f"{len(symbols)} symbols, {saved_det} detections, "
            f"{len(all_clusters)} clusters, {len(episode_ids)} episodes, "
            f"{total_snapshots} snapshots"
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
