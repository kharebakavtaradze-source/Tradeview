"""
Pump Study Engine — Phase 3E: Pump Family Classification + Comparison Groups
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
Phase 3D  ✓  Timeline milestone events → pump_episode_events
Phase 3E  ✓  Pump family classification + comparison groups
"""

import asyncio
import json
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


# ── Phase 3D: timeline milestone detection ────────────────────────────────────

def _mk_event(
    episode_id:  int,
    run_id:      int,
    symbol:      str,
    snap:        dict,
    event_type:  str,
    value:       Optional[float],
    note:        str,
    detail:      Optional[dict] = None,
) -> dict:
    """Build a single event dict ready for save_pump_episode_events()."""
    return {
        "episode_id":     episode_id,
        "run_id":         run_id,
        "symbol":         symbol,
        "event_date":     snap["date"],
        "event_type":     event_type,
        "event_value":    value,
        "event_note":     note,
        "event_detail":   detail or {},
        "days_before_pump": snap.get("relative_day_from_start"),
    }


def _detect_timeline_events(
    episode_id:  int,
    run_id:      int,
    symbol:      str,
    episode:     dict,
    snapshots:   list[dict],
) -> list[dict]:
    """
    Detect deterministic timeline milestones for one canonical episode.

    Uses in-memory snapshots already built by _build_snapshots() — no DB reads.

    Event types (at most one per type unless noted):
      first_abnormal_volume_day   — PRE/PUMP: volume_vs_avg20 >= 2.0 or vol_z >= 2.5
      first_compression_day       — PRE:       BB squeeze active
      first_ribbon_constructive_day — PRE/PUMP: ribbon_class >= CONSTRUCTIVE
      first_ignition_day          — PRE/PUMP:  ignition_quality >= 20
      first_accumulation_like_day — PRE:       in_acc=True or wyckoff BASE/ARM/STEALTH_*
      first_spring_test_lps_day   — PRE:       SC detected inside accumulation
      breakout_day                — PUMP:      regime breakout + volume + positive return
      retest_day                  — PUMP/POST: first meaningful pullback after start
      first_vertical_expansion_day— PUMP:      large intraday range + big return + volume
      peak_day                    — PUMP:      canonical pump_peak_date (always present)
      fade_day                    — POST:      first -3% day after peak
      dump_day                    — POST:      first -8% day or -20% from peak
    """
    if not snapshots:
        return []

    pump_start = episode["pump_start_date"]
    pump_peak  = episode["pump_peak_date"]
    peak_price = episode.get("peak_price") or 0.0

    events: list[dict] = []

    # Partition snapshots by phase for targeted scans
    pre_snaps  = [s for s in snapshots if s["window_phase"] == "PRE"]
    pump_snaps = [s for s in snapshots if s["window_phase"] == "PUMP"]
    post_snaps = [s for s in snapshots if s["window_phase"] == "POST"]

    # Helper: safe float coerce
    def _f(v) -> Optional[float]:
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    # ── 1. first_abnormal_volume_day ──────────────────────────────────────────
    # Threshold: volume_vs_avg20 >= 2.0  OR  vol_z >= 2.5
    # Scan PRE first; if not found in PRE, scan PUMP.
    _abn_vol_found = False
    for snap in pre_snaps + pump_snaps:
        vr = _f(snap.get("volume_vs_avg20"))
        vz = _f(snap.get("volume_zscore"))
        if (vr is not None and vr >= 2.0) or (vz is not None and vz >= 2.5):
            events.append(_mk_event(
                episode_id, run_id, symbol, snap,
                "first_abnormal_volume_day",
                value  = vr,
                note   = f"Volume {vr:.1f}× avg-20 (z={vz:.1f})" if vr and vz else f"Volume {vr:.1f}× avg-20",
                detail = {"volume_vs_avg20": vr, "volume_zscore": vz},
            ))
            _abn_vol_found = True
            break

    # ── 2. first_compression_day ──────────────────────────────────────────────
    # PRE only: first BB squeeze bar
    for snap in pre_snaps:
        squeeze = snap.get("bb_squeeze")
        if squeeze:
            bw = _f(snap.get("bb_width"))
            events.append(_mk_event(
                episode_id, run_id, symbol, snap,
                "first_compression_day",
                value  = bw,
                note   = f"BB squeeze active, width={bw:.4f}" if bw else "BB squeeze active",
                detail = {"bb_width": bw, "bb_squeeze": True},
            ))
            break

    # ── 3. first_ribbon_constructive_day ─────────────────────────────────────
    # First day ribbon reaches CONSTRUCTIVE or CONFIRMED level (PRE preferred, then PUMP)
    _RIBBON_QUALIFY = {"RIBBON_CONFIRMED", "RIBBON_CONSTRUCTIVE"}
    for snap in pre_snaps + pump_snaps:
        rc = snap.get("ribbon_class") or ""
        if rc in _RIBBON_QUALIFY:
            events.append(_mk_event(
                episode_id, run_id, symbol, snap,
                "first_ribbon_constructive_day",
                value  = None,
                note   = f"Ribbon class reached {rc}",
                detail = {"ribbon_class": rc},
            ))
            break

    # ── 4. first_ignition_day ─────────────────────────────────────────────────
    # First day where ignition_quality >= 20 (meaningful, not noise)
    for snap in pre_snaps + pump_snaps:
        ig = (snap.get("snapshot") or {}).get("ignition") or {}
        iq = ig.get("ignition_quality") or 0
        ib = ig.get("ignition_bucket", "NONE")
        sig = ig.get("ignition_signal", "NO_IGNITION")
        if iq >= 20 and sig not in ("NO_IGNITION", "NONE", ""):
            events.append(_mk_event(
                episode_id, run_id, symbol, snap,
                "first_ignition_day",
                value  = float(iq),
                note   = f"Ignition signal: {sig} / bucket={ib} / quality={iq}",
                detail = {"ignition_signal": sig, "ignition_bucket": ib, "ignition_quality": iq},
            ))
            break

    # ── 5. first_accumulation_like_day ────────────────────────────────────────
    # PRE only: first day with Wyckoff accumulation evidence
    _ACC_STATES = {"BASE", "ARM", "STEALTH", "STEALTH_BASE", "STEALTH_ARM", "FIRE"}
    for snap in pre_snaps:
        regime = (snap.get("snapshot") or {}).get("regime") or {}
        in_acc  = regime.get("in_acc", False)
        state   = snap.get("wyckoff_state") or ""
        conf    = regime.get("confidence", 0)
        if in_acc or state in _ACC_STATES:
            events.append(_mk_event(
                episode_id, run_id, symbol, snap,
                "first_accumulation_like_day",
                value  = float(conf) if conf else None,
                note   = f"Wyckoff accumulation: state={state}, in_acc={in_acc}, confidence={conf}",
                detail = {"state": state, "in_acc": in_acc, "confidence": conf},
            ))
            break

    # ── 6. first_spring_test_lps_day ─────────────────────────────────────────
    # PRE: selling climax (SC) detected inside accumulation context — best proxy
    # for spring / test / LPS without explicit Wyckoff sub-phase labelling
    for snap in pre_snaps:
        regime = (snap.get("snapshot") or {}).get("regime") or {}
        sc     = regime.get("sc", False)
        in_acc = regime.get("in_acc", False)
        if sc and in_acc:
            tr_low = _f(regime.get("tr_low"))
            events.append(_mk_event(
                episode_id, run_id, symbol, snap,
                "first_spring_test_lps_day",
                value  = tr_low,
                note   = f"Selling climax in accumulation — spring/LPS proxy. TR low={tr_low}",
                detail = {"sc": True, "in_acc": True, "tr_low": tr_low,
                          "tr_high": _f(regime.get("tr_high"))},
            ))
            break

    # ── 7. breakout_day ───────────────────────────────────────────────────────
    # PUMP: first decisive up-move from pre-pump structure
    # Primary: regime.breakout=True + vol >= 1.5× avg + daily_return > 2%
    # Fallback: daily_return >= 5% (decisive move even without regime flag)
    for snap in pump_snaps:
        regime  = (snap.get("snapshot") or {}).get("regime") or {}
        brk     = regime.get("breakout", False)
        vr      = _f(snap.get("volume_vs_avg20"))
        dr      = _f(snap.get("daily_return_pct"))
        gap     = _f(snap.get("gap_pct"))
        primary = brk and (vr is not None and vr >= 1.5) and (dr is not None and dr > 2.0)
        fallback = dr is not None and dr >= 5.0
        if primary or fallback:
            events.append(_mk_event(
                episode_id, run_id, symbol, snap,
                "breakout_day",
                value  = dr,
                note   = (
                    f"Breakout: +{dr:.1f}%, vol {vr:.1f}× avg, gap={gap:.1f}%"
                    if vr and gap else f"Breakout: +{dr:.1f}%"
                ),
                detail = {
                    "daily_return_pct": dr, "volume_vs_avg20": vr,
                    "gap_pct": gap, "regime_breakout": brk,
                },
            ))
            break

    # ── 8. retest_day ─────────────────────────────────────────────────────────
    # First meaningful pullback after the first 3 PUMP bars while still elevated
    # Condition: daily_return <= -3% AND close still > start_price * 1.05
    start_price = episode.get("start_price") or 0.0
    retest_floor = start_price * 1.05 if start_price else 0.0
    # Skip the first 3 pump days (index 0,1,2 in pump_snaps)
    for snap in pump_snaps[3:] + post_snaps:
        dr = _f(snap.get("daily_return_pct"))
        cl = _f(snap.get("close"))
        if dr is not None and dr <= -3.0 and cl and cl > retest_floor:
            vr = _f(snap.get("volume_vs_avg20"))
            events.append(_mk_event(
                episode_id, run_id, symbol, snap,
                "retest_day",
                value  = dr,
                note   = f"Retest pullback: {dr:.1f}% while above start×1.05 ({retest_floor:.2f})",
                detail = {"daily_return_pct": dr, "close": cl, "volume_vs_avg20": vr,
                          "retest_floor": retest_floor},
            ))
            break

    # ── 9. first_vertical_expansion_day ──────────────────────────────────────
    # PUMP: first day of true price acceleration
    # Primary: intraday_range >= 8% AND daily_return >= 8% AND vol >= 2× avg
    # Fallback: daily_return >= 15% alone
    for snap in pump_snaps:
        ir  = _f(snap.get("intraday_range_pct"))
        dr  = _f(snap.get("daily_return_pct"))
        vr  = _f(snap.get("volume_vs_avg20"))
        primary  = (ir is not None and ir >= 8.0
                    and dr is not None and dr >= 8.0
                    and vr is not None and vr >= 2.0)
        fallback = dr is not None and dr >= 15.0
        if primary or fallback:
            events.append(_mk_event(
                episode_id, run_id, symbol, snap,
                "first_vertical_expansion_day",
                value  = dr,
                note   = (
                    f"Vertical expansion: +{dr:.1f}%, range={ir:.1f}%, vol {vr:.1f}× avg"
                    if ir and vr else f"Vertical expansion: +{dr:.1f}%"
                ),
                detail = {"daily_return_pct": dr, "intraday_range_pct": ir,
                          "volume_vs_avg20": vr},
            ))
            break

    # ── 10. peak_day ──────────────────────────────────────────────────────────
    # Always present: canonical pump_peak_date
    peak_snap = next((s for s in pump_snaps if s["date"] == pump_peak), None)
    if peak_snap is None:
        peak_snap = next((s for s in snapshots if s["date"] == pump_peak), None)
    if peak_snap:
        cr = _f(peak_snap.get("cum_return_pct"))
        events.append(_mk_event(
            episode_id, run_id, symbol, peak_snap,
            "peak_day",
            value  = cr,
            note   = f"Canonical peak: cum_return={cr:.1f}% from start" if cr else "Canonical peak day",
            detail = {
                "peak_price": _f(peak_snap.get("close")),
                "cum_return_pct": cr,
                "pump_multiple": round(peak_price / start_price, 4) if start_price else None,
            },
        ))

    # ── 11. fade_day ──────────────────────────────────────────────────────────
    # POST: first -3% or worse day (close near lows also qualifies)
    for snap in post_snaps:
        dr  = _f(snap.get("daily_return_pct"))
        cp  = _f(snap.get("close_position"))
        qualifies = (dr is not None and dr <= -3.0) or (cp is not None and cp <= 0.25)
        if qualifies:
            events.append(_mk_event(
                episode_id, run_id, symbol, snap,
                "fade_day",
                value  = dr,
                note   = (
                    f"Post-peak fade: {dr:.1f}%, close_position={cp:.2f}"
                    if dr and cp else f"Post-peak fade: {dr:.1f}%"
                ),
                detail = {"daily_return_pct": dr, "close_position": cp},
            ))
            break

    # ── 12. dump_day ──────────────────────────────────────────────────────────
    # POST: first severe down day (-8% daily) or -20% from peak
    for snap in post_snaps:
        dr  = _f(snap.get("daily_return_pct"))
        cl  = _f(snap.get("close"))
        # Compute return from peak
        from_peak: Optional[float] = None
        if cl and peak_price > 0:
            from_peak = round((cl - peak_price) / peak_price * 100, 2)
        severe_daily = dr is not None and dr <= -8.0
        severe_peak  = from_peak is not None and from_peak <= -20.0
        if severe_daily or severe_peak:
            events.append(_mk_event(
                episode_id, run_id, symbol, snap,
                "dump_day",
                value  = dr,
                note   = (
                    f"Dump: {dr:.1f}% daily, {from_peak:.1f}% from peak"
                    if dr and from_peak else f"Dump: {dr:.1f}% daily"
                ),
                detail = {"daily_return_pct": dr, "return_from_peak_pct": from_peak,
                          "close": cl, "peak_price": peak_price},
            ))
            break

    return events


# ── Phase 3E: pump family classification + comparison groups ──────────────────

# All valid pump family labels (ordered from most- to least-specific)
_PUMP_FAMILIES = (
    "ACCUMULATION_TO_EXPANSION",
    "POST_COMPRESSION_BREAKOUT",
    "CATALYST_IGNITION",
    "GAP_AND_GO",
    "LOW_FLOAT_VELOCITY",
    "CHAOTIC_SPECULATIVE",
    "SECTOR_SYMPATHY",
    "UNKNOWN",
)

# Secondary scan for normal_winner comparison group:
# minimum and maximum multiple (exclusive of 4x threshold)
_NORMAL_WINNER_MIN_MULTIPLE: float = 1.40
_NORMAL_WINNER_MAX_MULTIPLE: float = 3.99

# false_positive rule: any POST snapshot with the worst close below
# start_price × this threshold qualifies the episode as a severe post-reversal.
# 2.0 means the price fell from 4x+ peak back to below 2x from start.
_POST_REVERSAL_THRESHOLD: float = 2.00

# Wyckoff state quality ordering (higher = more advanced accumulation)
_WYK_PRIORITY: dict[str, int] = {
    "FIRE":        6,
    "ARM":         5,
    "STEALTH_ARM": 4,
    "STEALTH_BASE":3,
    "BASE":        2,
    "STEALTH":     1,
    "NONE":        0,
}

# Ribbon classes that count as "constructive or better"
_RIBBON_QUALIFY: frozenset = frozenset({"RIBBON_CONFIRMED", "RIBBON_CONSTRUCTIVE"})


def _compute_stats(values: list) -> dict:
    """
    Compute distribution statistics over a list of numeric values.
    Returns {count, mean, median, p25, p75, p90}.
    None values are silently skipped.
    """
    cleaned = sorted(v for v in values if v is not None)
    n = len(cleaned)
    if n == 0:
        return {
            "count": 0, "mean": None, "median": None,
            "p25": None, "p75": None, "p90": None,
        }

    mean = sum(cleaned) / n

    def pct(p: int) -> float:
        idx = min(n - 1, max(0, int(n * p / 100)))
        return round(cleaned[idx], 4)

    return {
        "count":  n,
        "mean":   round(mean, 4),
        "median": pct(50),
        "p25":    pct(25),
        "p75":    pct(75),
        "p90":    pct(90),
    }


def _build_group_stats(members: list[dict]) -> dict:
    """
    Build aggregate stats dict for one comparison group.
    Each member dict must have a 'features' sub-dict.
    Stats are computed for all major numeric fields.
    """
    feats = [m.get("features") or {} for m in members]

    def stat_for(field: str) -> dict:
        return _compute_stats([f.get(field) for f in feats])

    return {
        "pump_multiple":                stat_for("pump_multiple"),
        "days_to_peak":                 stat_for("days_to_peak"),
        "max_drawdown_before_peak":     stat_for("max_drawdown_before_peak"),
        "max_volume_anomaly":           stat_for("max_volume_anomaly"),
        "largest_gap_pct":              stat_for("largest_gap_pct"),
        "max_toxicity_score":           stat_for("max_toxicity_score"),
        "avg_toxicity_score":           stat_for("avg_toxicity_score"),
        "ignition_quality":             stat_for("ignition_quality"),
        "worst_post_return_from_start": stat_for("worst_post_return_from_start"),
    }


def _extract_episode_features(
    ep_dict: dict,
    snaps:   list[dict],
    evs:     list[dict],
) -> dict:
    """
    Derive the key comparison feature vector for one episode.

    Must be called while snapshots are still in memory (inside the episode loop)
    because it reads indicator sub-dicts from snap["snapshot"].

    Features stored (None when unavailable):
      pump_multiple, pump_return_pct, days_to_peak, days_to_double,
      max_drawdown_before_peak, max_volume_anomaly, largest_gap_pct,
      first_pump_gap_pct, had_ribbon, had_ignition, had_compression,
      strongest_wyckoff_state, max_toxicity_score, avg_toxicity_score,
      worst_post_return_from_start, ignition_quality, ignition_bucket,
      sector, industry
    """
    pre_snaps  = [s for s in snaps if s["window_phase"] == "PRE"]
    pump_snaps = [s for s in snaps if s["window_phase"] == "PUMP"]
    post_snaps = [s for s in snaps if s["window_phase"] == "POST"]
    event_types = {e["event_type"] for e in evs}

    # ── Volume anomaly ────────────────────────────────────────────────────────
    vol_ratios = [
        s["volume_vs_avg20"] for s in pump_snaps
        if s.get("volume_vs_avg20") is not None
    ]
    max_vol_anomaly = round(max(vol_ratios), 3) if vol_ratios else None

    # ── Gap ───────────────────────────────────────────────────────────────────
    gap_pcts = [abs(s.get("gap_pct") or 0) for s in pump_snaps if s.get("gap_pct")]
    largest_gap     = round(max(gap_pcts), 3) if gap_pcts else None
    first_pump_gap  = pump_snaps[0].get("gap_pct") if pump_snaps else None
    if first_pump_gap is not None:
        first_pump_gap = round(first_pump_gap, 3)

    # ── Structural signals ────────────────────────────────────────────────────
    had_ribbon = any(
        (s.get("ribbon_class") or "") in _RIBBON_QUALIFY
        for s in pre_snaps + pump_snaps
    )
    had_ignition   = "first_ignition_day"   in event_types
    had_compression = "first_compression_day" in event_types

    # ── Wyckoff: strongest state seen in PRE + early PUMP ────────────────────
    wyk_states = [
        s.get("wyckoff_state") or "NONE"
        for s in pre_snaps + pump_snaps
    ]
    strongest_wyckoff = max(wyk_states, key=lambda s: _WYK_PRIORITY.get(s, 0))
    if strongest_wyckoff == "NONE":
        strongest_wyckoff = None

    # ── Toxicity ──────────────────────────────────────────────────────────────
    tox_scores: list[float] = []
    for s in pump_snaps:
        tox = (s.get("snapshot") or {}).get("toxicity") or {}
        ts  = tox.get("toxicity_score")
        if ts is not None:
            tox_scores.append(float(ts))
    max_tox = max(tox_scores)                                   if tox_scores else None
    avg_tox = round(sum(tox_scores) / len(tox_scores), 1)      if tox_scores else None

    # ── POST reversal: worst close in POST vs start_price ────────────────────
    start_price = ep_dict.get("start_price") or 0.0
    worst_post_return_from_start: Optional[float] = None
    if post_snaps and start_price > 0:
        post_closes = [s["close"] for s in post_snaps if s.get("close")]
        if post_closes:
            worst_close = min(post_closes)
            worst_post_return_from_start = round(
                (worst_close - start_price) / start_price * 100, 2
            )

    # ── Ignition ──────────────────────────────────────────────────────────────
    ignition_quality: Optional[float] = None
    ignition_bucket:  Optional[str]   = None
    for e in evs:
        if e["event_type"] == "first_ignition_day":
            ignition_quality = e.get("event_value")
            ignition_bucket  = (e.get("event_detail") or {}).get("ignition_bucket")
            break

    return {
        "pump_multiple":                ep_dict.get("pump_multiple"),
        "pump_return_pct":              ep_dict.get("pump_return_pct"),
        "days_to_peak":                 ep_dict.get("days_to_peak"),
        "days_to_double":               ep_dict.get("days_to_double"),
        "max_drawdown_before_peak":     ep_dict.get("max_drawdown_before_peak"),
        "max_volume_anomaly":           max_vol_anomaly,
        "largest_gap_pct":              largest_gap,
        "first_pump_gap_pct":           first_pump_gap,
        "had_ribbon":                   had_ribbon,
        "had_ignition":                 had_ignition,
        "had_compression":              had_compression,
        "strongest_wyckoff_state":      strongest_wyckoff,
        "max_toxicity_score":           max_tox,
        "avg_toxicity_score":           avg_tox,
        "worst_post_return_from_start": worst_post_return_from_start,
        "ignition_quality":             ignition_quality,
        "ignition_bucket":              ignition_bucket,
        # Not yet enriched (pending future phases)
        "sector":                       ep_dict.get("sector"),
        "industry":                     ep_dict.get("industry"),
    }


def _classify_pump_family(
    ep_dict:  dict,
    features: dict,
    evs:      list[dict],
) -> tuple[str, str]:
    """
    Assign exactly one deterministic pump family to a canonical episode.

    Priority (first matching rule wins):
      1. ACCUMULATION_TO_EXPANSION  — strong Wyckoff + structural convergence
      2. POST_COMPRESSION_BREAKOUT  — BB squeeze before move + breakout
      3. CATALYST_IGNITION           — early strong ignition signal
      4. GAP_AND_GO                  — large gap on first PUMP day, no prior base
      5. LOW_FLOAT_VELOCITY          — fast peak (≤5 days) + high volume shock
      6. CHAOTIC_SPECULATIVE         — high toxicity, no structure
      7. SECTOR_SYMPATHY             — sector-aligned (requires sector data; skipped)
      8. UNKNOWN                     — fallback

    Returns (family_label, explanation_string).
    """
    event_types    = {e["event_type"] for e in evs}
    days_to_peak   = features.get("days_to_peak") or 999
    max_vol        = features.get("max_volume_anomaly") or 0.0
    had_ribbon     = features.get("had_ribbon", False)
    had_ignition   = features.get("had_ignition", False)
    had_compression = features.get("had_compression", False)
    strongest_wyk  = features.get("strongest_wyckoff_state") or "NONE"
    first_gap      = features.get("first_pump_gap_pct") or 0.0
    max_tox        = features.get("max_toxicity_score") or 0
    avg_tox        = features.get("avg_toxicity_score") or 0
    ign_qual       = features.get("ignition_quality") or 0
    ign_bucket     = features.get("ignition_bucket") or "NONE"
    ign_evt        = next(
        (e for e in evs if e["event_type"] == "first_ignition_day"), None
    )

    # ── 1. ACCUMULATION_TO_EXPANSION ─────────────────────────────────────────
    # Convergence of multiple accumulation signals before the explosive move.
    acc_score = 0
    if "first_accumulation_like_day"   in event_types: acc_score += 2
    if "first_spring_test_lps_day"     in event_types: acc_score += 2
    if "first_ribbon_constructive_day" in event_types: acc_score += 1
    if had_ribbon:                                      acc_score += 1
    if strongest_wyk in ("FIRE", "ARM"):                acc_score += 2
    if strongest_wyk in ("STEALTH_ARM", "STEALTH_BASE"): acc_score += 1
    if had_compression and "breakout_day" in event_types: acc_score += 1

    if acc_score >= 5:
        return (
            "ACCUMULATION_TO_EXPANSION",
            f"Convergent accumulation: state={strongest_wyk}, ribbon={had_ribbon}, "
            f"spring={'yes' if 'first_spring_test_lps_day' in event_types else 'no'}, "
            f"acc_score={acc_score}",
        )

    # ── 2. POST_COMPRESSION_BREAKOUT ─────────────────────────────────────────
    # BB squeeze in PRE followed by breakout (+optional ribbon confirmation).
    pcb_score = 0
    if had_compression:                                 pcb_score += 3
    if "breakout_day" in event_types:                   pcb_score += 2
    if "first_ribbon_constructive_day" in event_types:  pcb_score += 1
    if had_ribbon:                                      pcb_score += 1
    if acc_score >= 2:                                  pcb_score += 1

    if pcb_score >= 5 and had_compression:
        return (
            "POST_COMPRESSION_BREAKOUT",
            f"Squeeze before move: compression={had_compression}, "
            f"breakout={'yes' if 'breakout_day' in event_types else 'no'}, "
            f"ribbon={had_ribbon}, pcb_score={pcb_score}",
        )

    # ── 3. CATALYST_IGNITION ─────────────────────────────────────────────────
    # Early strong ignition signal — quality >= 30, preferably in PRE phase.
    if had_ignition and ign_qual >= 30:
        ign_rel_day = ign_evt.get("days_before_pump") if ign_evt else None
        is_early    = ign_rel_day is not None and ign_rel_day <= 2
        if is_early or ign_qual >= 50:
            return (
                "CATALYST_IGNITION",
                f"Early strong ignition: quality={ign_qual:.0f}, bucket={ign_bucket}, "
                f"days_from_start={ign_rel_day}",
            )

    # ── 4. GAP_AND_GO ─────────────────────────────────────────────────────────
    # Large gap on first PUMP day with minimal prior base-building.
    if abs(first_gap) >= 8.0:
        return (
            "GAP_AND_GO",
            f"Extreme gap start: first_pump_gap={first_gap:.1f}%",
        )
    if abs(first_gap) >= 5.0 and not had_compression:
        return (
            "GAP_AND_GO",
            f"Gap-led move: first_pump_gap={first_gap:.1f}%, no prior compression",
        )

    # ── 5. LOW_FLOAT_VELOCITY ────────────────────────────────────────────────
    # Short-duration explosive move with high volume anomaly — classic microcap.
    if days_to_peak <= 3:
        return (
            "LOW_FLOAT_VELOCITY",
            f"Ultra-fast peak: {days_to_peak} trading days to peak",
        )
    if days_to_peak <= 5 and max_vol >= 4.0:
        return (
            "LOW_FLOAT_VELOCITY",
            f"High-velocity: peak in {days_to_peak} days, vol_anomaly={max_vol:.1f}x avg",
        )

    # ── 6. CHAOTIC_SPECULATIVE ────────────────────────────────────────────────
    # Explosive but structurally dirty: high toxicity and no prior structural setup.
    no_structure = (
        not had_ribbon
        and not had_ignition
        and "first_accumulation_like_day" not in event_types
    )
    chaotic = no_structure and (avg_tox >= 40 or max_tox >= 60 or max_vol >= 5.0)
    if chaotic:
        return (
            "CHAOTIC_SPECULATIVE",
            f"Unstructured explosive move: avg_tox={avg_tox}, max_tox={max_tox}, "
            f"vol={max_vol:.1f}x avg, no prior setup",
        )

    # ── 7. SECTOR_SYMPATHY ────────────────────────────────────────────────────
    # Cannot be determined without sector context (always None in Phase 3E).
    # Reserved for future enrichment.

    # ── Late-catch: partial evidence rules ────────────────────────────────────
    if had_ignition:
        return (
            "CATALYST_IGNITION",
            f"Ignition-assisted (moderate): quality={ign_qual:.0f}, bucket={ign_bucket}",
        )
    if acc_score >= 2:
        return (
            "ACCUMULATION_TO_EXPANSION",
            f"Partial accumulation evidence: acc_score={acc_score}",
        )
    if had_compression:
        return (
            "POST_COMPRESSION_BREAKOUT",
            "Compression detected before move (limited breakout confirmation)",
        )

    return ("UNKNOWN", "Insufficient or mixed evidence for family classification")


def _build_normal_winner_members(
    run_id:      int,
    candle_map:  dict[str, list[dict]],
    start_date:  str,
    end_date:    str,
    window_days: int,
) -> list[dict]:
    """
    Derive normal_winner comparison group members via a secondary detection pass.

    Definition
    ----------
    A normal_winner is the strongest single window per symbol where
    _NORMAL_WINNER_MIN_MULTIPLE (1.40) <= multiple < 4.0 during the scan period.

    Data source: candle_map (already loaded for 4x detection) — no extra API calls.
    Since candle_map only contains symbols that had at least one 4x+ hit, this
    group represents "other strong-but-sub-4x windows from the same stocks."
    This is useful for comparing what a strong non-4x move looks like in the same
    universe vs. the detected 4x episodes.

    Note: A symbol can appear in both 4x_pump and normal_winner groups because
    they capture DIFFERENT time windows (different t0 dates).

    Features stored are detection-level only (no snapshot-derived indicators,
    since running a second indicator pass would double the computation cost).
    """
    members: list[dict] = []

    for sym, candles in candle_map.items():
        # Detect all moves >= _NORMAL_WINNER_MIN_MULTIPLE in the same scan window
        all_hits = _detect_raw_pumps(
            sym, candles,
            scan_start   = start_date,
            scan_end     = end_date,
            window_days  = window_days,
            min_multiple = _NORMAL_WINNER_MIN_MULTIPLE,
        )
        # Keep only sub-4x windows (exclude windows that are 4x+ detections)
        sub4x = [h for h in all_hits if h["multiple"] < 4.0]
        if not sub4x:
            continue

        # One representative per symbol: highest multiple in the sub-4x set
        best = max(sub4x, key=lambda h: h["multiple"])

        members.append({
            "run_id":          run_id,
            "group_name":      "normal_winner",
            "symbol":          sym,
            "episode_id":      None,
            "pump_multiple":   best["multiple"],
            "pump_return_pct": best["return_pct"],
            "days_to_peak":    best["days_to_peak"],
            "pump_type":       None,
            "features": {
                "pump_multiple":            best["multiple"],
                "pump_return_pct":          best["return_pct"],
                "days_to_peak":             best["days_to_peak"],
                "max_drawdown_before_peak": best.get("max_drawdown_before_peak"),
                "start_price":              best["start_price"],
                "peak_price":               best["peak_price"],
                "window_start_date":        best["window_start_date"],
                "window_peak_date":         best["window_peak_date"],
                # Indicator-level features not computed (no snapshot pass for sub-4x)
            },
        })

    return members


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
    Phase 3E entry point (final deterministic engine phase).

    Params:
        start_date      str   YYYY-MM-DD  scan window start
        end_date        str   YYYY-MM-DD  scan window end
        window_days     int   (default 14) forward look-ahead in trading bars
        min_multiple    float (default 4.0) minimum pump multiple to record
        universe_limit  int   (default 0 = no limit)

    Execution order
    ---------------
    1.  Build symbol universe
    2.  Per-symbol (parallel, Semaphore 8):
          a. Fetch candles  (kept in candle_map)
          b. Detect raw pumps → in-memory hits
          c. Cluster hits → in-memory clusters
          d. Back-fill cluster_id / is_canonical on hit dicts (in memory)
    3.  Save enriched detections (cluster_id + is_canonical already set)
    4.  Save cluster records (canonical_episode_id = None initially)
    5.  Build episode dicts from each cluster's canonical detection
    6.  Save episodes → receive inserted IDs
    7.  Back-fill canonical_episode_id on each cluster row
    8.  Per episode (sequential):
          a. Build PRE/PUMP/POST snapshots (Phase 3C)
          b. Detect timeline milestones from in-memory snapshots (Phase 3D)
          c. Extract feature vector + classify pump family (Phase 3E)
          d. Back-fill pump_type + enriched fields on episode row
    9.  Build 4 comparison groups from in-memory episode data (Phase 3E):
          4x_pump       — all canonical episodes
          normal_winner — secondary scan for 1.40–3.99x moves (same symbols)
          false_positive — 4x episodes with severe POST reversal
          missed_mover  — universe symbols with no 4x hit
    10. Save comparison groups + members
    11. Update run counts; advance status to comparison_complete
    """
    global _pump_study_progress

    from database import (
        update_pump_study_run,
        save_pump_episode_detections,
        save_pump_clusters,
        save_pump_episodes,
        save_pump_episode_snapshots,
        save_pump_episode_events,
        update_pump_cluster_episode_id,
        update_pump_episode_enrichment,
        save_pump_comparison_group,
        save_pump_comparison_members,
    )

    _pump_study_progress.update({
        "running":              True,
        "run_id":               run_id,
        "phase":                "INIT",
        "symbols_total":        0,
        "symbols_done":         0,
        "raw_detections":       0,
        "clusters":             0,
        "episodes":             0,
        "snapshots":            0,
        "events":               0,
        "comparison_members":   0,
        "error":                None,
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

        # ── 8–11. Per-episode: snapshots (3C), events (3D), family+features (3E) ─
        _pump_study_progress["phase"] = "ENRICH"
        total_snapshots = 0
        total_events    = 0

        # all_ep_data accumulates per-episode enrichment for comparison groups
        all_ep_data: list[dict] = []

        for cl, ep_id in zip(all_clusters, episode_ids):
            sym = cl["symbol"]
            sym_candles = candle_map.get(sym)

            canon = cl["canonical"]
            ep_dict = {
                "pump_start_date":          canon["window_start_date"],
                "pump_peak_date":           canon["window_peak_date"],
                "start_price":              canon["start_price"],
                "peak_price":               canon["peak_price"],
                "pump_multiple":            canon["multiple"],
                "pump_return_pct":          canon["return_pct"],
                "days_to_peak":             canon["days_to_peak"],
                "days_to_double":           canon.get("days_to_double"),
                "max_drawdown_before_peak": canon.get("max_drawdown_before_peak"),
                "sector":                   None,
                "industry":                 None,
            }

            snaps: list[dict] = []
            evs:   list[dict] = []

            if sym_candles:
                # Phase 3C: PRE/PUMP/POST indicator snapshots
                snaps = _build_snapshots(ep_id, run_id, sym, ep_dict, sym_candles)
                if snaps:
                    await save_pump_episode_snapshots(snaps)
                    total_snapshots += len(snaps)

                # Phase 3D: timeline milestone events (from in-memory snapshots)
                if snaps:
                    evs = _detect_timeline_events(ep_id, run_id, sym, ep_dict, snaps)
                    if evs:
                        await save_pump_episode_events(evs)
                        total_events += len(evs)

            # Phase 3E: feature extraction + family classification
            features = _extract_episode_features(ep_dict, snaps, evs)
            family, family_reason = _classify_pump_family(ep_dict, features, evs)

            # Back-fill enriched fields onto the saved PumpEpisode row
            await update_pump_episode_enrichment(ep_id, {
                "pump_type":               family,
                "had_ribbon":              features.get("had_ribbon", False),
                "had_ignition":            features.get("had_ignition", False),
                "strongest_wyckoff_state": features.get("strongest_wyckoff_state"),
                "max_volume_anomaly":      features.get("max_volume_anomaly"),
                "largest_gap_pct":         features.get("largest_gap_pct"),
                "summary_json":            json.dumps({"family_reason": family_reason}),
            })

            all_ep_data.append({
                "episode_id":    ep_id,
                "symbol":        sym,
                "ep_dict":       ep_dict,
                "features":      features,
                "family":        family,
                "family_reason": family_reason,
            })

            _pump_study_progress["snapshots"] = total_snapshots
            _pump_study_progress["events"]    = total_events

            logger.debug(
                f"[PUMP_STUDY][3E] {sym} ep={ep_id}: family={family}, "
                f"snaps={len(snaps)}, evs={len(evs)}"
            )

        # ── 12. Build + save comparison groups (Phase 3E) ────────────────────
        _pump_study_progress["phase"] = "COMPARISON"
        total_comparison_members = 0

        # Group A — 4x_pump: all canonical episodes from this run
        group_a = [
            {
                "run_id":          run_id,
                "group_name":      "4x_pump",
                "symbol":          ed["symbol"],
                "episode_id":      ed["episode_id"],
                "pump_multiple":   ed["features"].get("pump_multiple"),
                "pump_return_pct": ed["features"].get("pump_return_pct"),
                "days_to_peak":    ed["features"].get("days_to_peak"),
                "pump_type":       ed["family"],
                "features":        ed["features"],
            }
            for ed in all_ep_data
        ]

        # Group B — normal_winner: secondary scan on candle_map for 1.40–3.99x moves.
        # Same symbols as 4x_pump (only 4x symbols have candles), but different
        # time windows — useful for comparing strong-but-sub-4x behaviour.
        group_b = _build_normal_winner_members(
            run_id, candle_map, start_date, end_date, window_days,
        )

        # Group C — false_positive: canonical 4x episodes where the worst POST
        # close fell back below start_price × _POST_REVERSAL_THRESHOLD (default 2.0×).
        # These pumped to 4x+ then rapidly reversed most gains — "short-lived" pumps.
        group_c = [
            {
                "run_id":          run_id,
                "group_name":      "false_positive",
                "symbol":          ed["symbol"],
                "episode_id":      ed["episode_id"],
                "pump_multiple":   ed["features"].get("pump_multiple"),
                "pump_return_pct": ed["features"].get("pump_return_pct"),
                "days_to_peak":    ed["features"].get("days_to_peak"),
                "pump_type":       ed["family"],
                "features": {
                    **ed["features"],
                    "classification_note": (
                        f"POST reversal below {_POST_REVERSAL_THRESHOLD}× start: "
                        f"worst_post_return={ed['features'].get('worst_post_return_from_start'):.1f}%"
                        if ed["features"].get("worst_post_return_from_start") is not None
                        else "POST reversal"
                    ),
                },
            }
            for ed in all_ep_data
            if (
                ed["features"].get("worst_post_return_from_start") is not None
                and ed["features"]["worst_post_return_from_start"]
                    < (_POST_REVERSAL_THRESHOLD - 1.0) * 100
                # e.g., < 100 means price fell below 2× start (returned < 100% from start)
            )
        ]

        # Group D — missed_mover: universe symbols with no 4x detection.
        # These passed volume/price filters but produced no 4x+ hit during the scan
        # window. They represent the baseline "non-mover" universe population.
        # Feature data is minimal (no candles loaded for them).
        candle_map_syms = set(candle_map.keys())
        group_d = [
            {
                "run_id":          run_id,
                "group_name":      "missed_mover",
                "symbol":          sym,
                "episode_id":      None,
                "pump_multiple":   None,
                "pump_return_pct": None,
                "days_to_peak":    None,
                "pump_type":       None,
                "features": {
                    "in_universe":        True,
                    "had_4x_detection":   False,
                    "classification_note": "In universe; no 4x+ move detected in scan window",
                },
            }
            for sym in symbols
            if sym not in candle_map_syms
        ]

        # Save all four groups
        for grp_name, grp_members in [
            ("4x_pump",       group_a),
            ("normal_winner", group_b),
            ("false_positive", group_c),
            ("missed_mover",  group_d),
        ]:
            if not grp_members:
                logger.info(
                    f"[PUMP_STUDY][3E] group '{grp_name}' is empty — skipping"
                )
                continue

            stats  = _build_group_stats(grp_members)
            grp_id = await save_pump_comparison_group(run_id, {
                "group_name":   grp_name,
                "member_count": len(grp_members),
                "stats":        stats,
            })
            for m in grp_members:
                m["group_id"] = grp_id
            await save_pump_comparison_members(grp_members)
            total_comparison_members += len(grp_members)

            logger.info(
                f"[PUMP_STUDY][3E] group '{grp_name}': {len(grp_members)} members saved"
            )

        # ── 13. Finalise run ──────────────────────────────────────────────────
        family_counts: dict[str, int] = {}
        for ed in all_ep_data:
            fam = ed["family"]
            family_counts[fam] = family_counts.get(fam, 0) + 1

        await update_pump_study_run(run_id, {
            "status":              "comparison_complete",
            "symbols_scanned":     len(symbols),
            "raw_detection_count": saved_det,
            "cluster_count":       len(all_clusters),
            "episode_count":       len(episode_ids),
            "snapshot_count":      total_snapshots,
            "event_count":         total_events,
            "finished_at":         datetime.utcnow(),
            "notes": (
                f"Phase 3E complete: {len(symbols)} symbols, "
                f"{saved_det} raw detections, {len(all_clusters)} clusters, "
                f"{len(episode_ids)} episodes, {total_snapshots} snapshots, "
                f"{total_events} events, {total_comparison_members} comparison members. "
                f"Families: {family_counts}."
            ),
        })

        _pump_study_progress.update({
            "running":            False,
            "phase":              "COMPARISON_COMPLETE",
            "comparison_members": total_comparison_members,
        })

        logger.info(
            f"[PUMP_STUDY] run_id={run_id} Phase 3E done: "
            f"{len(symbols)} symbols, {saved_det} detections, "
            f"{len(all_clusters)} clusters, {len(episode_ids)} episodes, "
            f"{total_snapshots} snapshots, {total_events} events, "
            f"{total_comparison_members} comparison members. "
            f"Families: {family_counts}"
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
