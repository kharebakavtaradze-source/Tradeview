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

# Hard ceiling on pump_multiple recorded in raw detections.  Multiples above
# this threshold indicate corrupted candle data (e.g. a sub-penny open that
# the universe filter missed because the stock traded higher on sample dates).
# No real stock has ever returned 10 000× in a 14-day window.
_MAX_RAW_MULTIPLE: float = 10_000.0

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


# ── Date helper ───────────────────────────────────────────────────────────────

def _date_add(date_str: str, days: int) -> str:
    """Add `days` to a YYYY-MM-DD string and return YYYY-MM-DD."""
    from datetime import date, timedelta
    d = date.fromisoformat(date_str)
    return (d + timedelta(days=days)).isoformat()


# ── Sector resolution helper ──────────────────────────────────────────────────

async def _resolve_sector_for_symbol(symbol: str) -> tuple[str | None, str | None]:
    """
    Look up sector/industry for a symbol from SectorCache or UniverseCache.
    Returns (sector, industry) or (None, None) if not found.
    """
    try:
        from database import get_session_factory, SectorCache, UniverseCache
        from scanner.sector_resolver import resolve_sector
        from sqlalchemy import select as _sa_select

        async with get_session_factory()() as session:
            # Try SectorCache first
            row = (await session.execute(
                _sa_select(SectorCache).where(SectorCache.symbol == symbol.upper())
            )).scalar_one_or_none()
            if row and row.sector and row.sector not in ("Unknown", "UNKNOWN", ""):
                return row.sector, row.industry

            # Try UniverseCache
            urow = (await session.execute(
                _sa_select(UniverseCache).where(UniverseCache.symbol == symbol.upper())
            )).scalar_one_or_none()
            if urow:
                sector, industry, _ = resolve_sector(
                    symbol=symbol,
                    raw_sector=getattr(urow, "sector", None),
                    raw_industry=getattr(urow, "industry", None),
                    sic_code=getattr(urow, "sic_code", None),
                    sic_description=getattr(urow, "sic_description", None),
                )
                if sector and sector not in ("Unknown", "UNKNOWN"):
                    return sector, industry
    except Exception:
        pass
    return None, None


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
        if multiple > _MAX_RAW_MULTIPLE:
            logger.debug(
                f"[PUMP_STUDY] {symbol} {t0_date}: multiple={multiple:.1f}× "
                f"exceeds _MAX_RAW_MULTIPLE — skipping (corrupt candle data)"
            )
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
      7. Call new_pump_engine.analyze() → structural NP signal state

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
    try:
        from scanner.new_pump_engine import analyze as _np_analyze
        _np_available = True
    except ImportError:
        _np_available = False

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

        # ── New Pump Engine per-day analysis ─────────────────────────────────
        new_pump_result: dict = {}
        if _np_available and n_trailing >= _MIN_CANDLES_REGIME:
            try:
                new_pump_result = _np_analyze(trailing_raw[-200:]) or {}
            except Exception as exc:
                logger.debug(f"[PUMP_STUDY][3C] {symbol}/{d} new_pump_engine: {exc}")

        # ── Full snapshot dict ────────────────────────────────────────────────
        # snapshot_json stores the raw indicator sub-dicts for deep-dive queries
        snapshot_detail = {
            "indicators":    indicators,
            "regime":        regime,
            "ignition":      ignition,
            "toxicity":      toxicity,
            "new_pump":      new_pump_result,
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

    # ── 3. first_accumulation_like_day ────────────────────────────────────────
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
    "CATALYST_DRIVEN",
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



# ── Raw Pattern Study helpers ─────────────────────────────────────────────────

_RIBBON_COMPRESSION_SCORE: dict[str, float] = {
    "STRONG": 1.0, "MEDIUM": 0.67, "WEAK": 0.33, "NONE": 0.0,
}


def _build_ema_feature_json(
    ind: dict,
    close: Optional[float],
    compr_state: Optional[str],
) -> dict:
    """Build feature_json EMA payload from snapshot indicators. No upstream fabrication."""
    def _vs_pct(ema_val: Optional[float]) -> Optional[float]:
        if close is not None and ema_val is not None and ema_val != 0:
            return round((close - ema_val) / abs(ema_val) * 100, 3)
        return None

    ema8   = ind.get("ema8")
    ema13  = ind.get("ema13")
    ema21  = ind.get("ema21")
    ema34  = ind.get("ema34")
    ema50  = ind.get("ema50")
    ema89  = ind.get("ema89")
    ema200 = ind.get("ema200")

    above_ema200: Optional[bool] = (
        bool(close > ema200) if (close is not None and ema200 is not None) else None
    )

    return {
        # Raw EMA values
        "ema8":   ema8,
        "ema13":  ema13,
        "ema21":  ema21,
        "ema34":  ema34,
        "ema50":  ema50,
        "ema89":  ema89,
        "ema200": ema200,
        # Stack / ribbon flags
        "bullish_stack": ind.get("bullish_stack"),
        "bearish_stack": ind.get("bearish_stack"),
        "above_ema50":   ind.get("above_ema50"),
        "ema8_slope":    ind.get("ema8_slope"),
        # Derived: % distance from close to each key EMA
        "close_vs_ema8_pct":   _vs_pct(ema8),
        "close_vs_ema21_pct":  _vs_pct(ema21),
        "close_vs_ema50_pct":  _vs_pct(ema50),
        "close_vs_ema200_pct": _vs_pct(ema200),
        # Derived: above/below long-term anchor
        "above_ema200": above_ema200,
        # Derived: numeric compression score (STRONG=1.0 → NONE=0.0)
        "ema_compression_score": _RIBBON_COMPRESSION_SCORE.get(compr_state) if compr_state else None,
        # Cross-bar flags filled by _fill_prev_bar_flags
        "ema50_reclaim_day": None,
        "ema21_support_day": None,
    }


def snapshot_to_raw_daily_feature(
    snap: dict,
    episode: dict,
    raw_run_id: int,
    trailing_avg_range_pct: float | None = None,
) -> dict:
    """
    Convert one Pump Study snapshot row (as returned by _snapshot_to_dict /
    get_pump_episode_snapshots) into a raw_pattern_daily_features row dict,
    ready for save_raw_pattern_daily_features().

    Parameters
    ----------
    snap                  : snapshot dict (includes a "snapshot" sub-dict with
                            snapshot_json contents: indicators, regime, pump, etc.)
    episode               : pump_episodes row dict (supplies sector/industry)
    raw_run_id            : id of the raw_pattern_run this row belongs to
    trailing_avg_range_pct: optional pre-computed trailing mean of
                            intraday_range_pct over the prior N bars;
                            required for wide_range_bar / narrow_range_bar;
                            pass None to leave those fields null until the
                            caller loop provides context

    Source mapping
    --------------
    Direct from snapshot columns:
        phase, relative_day_from_start, relative_day_from_peak
        open, high, low, close, volume
        gap_pct, intraday_range_pct, close_position_in_bar (← close_position)
        volume_vs_avg20, volume_zscore
        atr_pct, bb_width

    From snapshot_json.indicators:
        atr             ← indicators.atr
        bb_squeeze_bars ← indicators.bb_sqz_bars
        ema_spread_pct  ← indicators.ema_spread_pct
        compression_state ← indicators.ribbon_compression (STRONG|MEDIUM|WEAK|NONE)
        atr_expansion_state derived from indicators.atr_ratio

    From pump_episodes:
        sector, industry

    Derived here (single-bar, no cross-bar context needed):
        dollar_volume, body_pct, upper_wick_pct, lower_wick_pct
        strong_close_near_high, weak_close_near_low
        doji_like, abnormal_volume_day, dryup_day
        atr_expansion_state

    Derived here (require trailing_avg_range_pct from caller):
        wide_range_bar, narrow_range_bar, expansion_bar

    Null for now (data not available in snapshot pipeline):
        exchange, market_cap, float_shares, market_regime
        volume_vs_avg5, volume_vs_avg10, dollar_volume, dollar_volume_vs_avg20 (see note)
        distance_to_range_high/low/mid (requires 52w range not stored)
        bullish_engulfing, bearish_engulfing, inside_bar, outside_bar,
        reclaim_bar (require previous-bar context — added by caller loop)
    """
    # ── Unpack raw OHLCV ──────────────────────────────────────────────────────
    o: Optional[float] = snap.get("open")
    h: Optional[float] = snap.get("high")
    l: Optional[float] = snap.get("low")
    c: Optional[float] = snap.get("close")
    v: Optional[int]   = snap.get("volume")

    bar_range: Optional[float] = (h - l) if (h is not None and l is not None) else None

    # ── Unpack snapshot_json sub-dicts ────────────────────────────────────────
    sj   = snap.get("snapshot") or {}
    ind  = sj.get("indicators") or {}
    reg  = sj.get("regime")     or {}

    # ── Direct snapshot column fields ─────────────────────────────────────────
    close_pos     = snap.get("close_position")        # already 0–1 in snapshot
    vol_vs_avg20  = snap.get("volume_vs_avg20")
    vol_z         = snap.get("volume_zscore")
    intra_range   = snap.get("intraday_range_pct")

    # ── From snapshot_json.indicators ─────────────────────────────────────────
    atr_abs       = ind.get("atr")
    atr_ratio     = ind.get("atr_ratio")
    bb_sqz_bars   = ind.get("bb_sqz_bars")
    ema_spread    = ind.get("ema_spread_pct")
    compr_state   = ind.get("ribbon_compression")     # STRONG|MEDIUM|WEAK|NONE

    # ── Derived: ATR expansion state ──────────────────────────────────────────
    if atr_ratio is not None:
        if atr_ratio > 1.10:
            atr_exp = "EXPANDING"
        elif atr_ratio < 0.90:
            atr_exp = "CONTRACTING"
        else:
            atr_exp = "NEUTRAL"
    else:
        atr_exp = None

    # ── Derived: dollar volume ────────────────────────────────────────────────
    dollar_vol: Optional[float] = (c * v) if (c is not None and v) else None

    # ── Derived: candle anatomy ───────────────────────────────────────────────
    body_pct: Optional[float] = None
    upper_wick_pct: Optional[float] = None
    lower_wick_pct: Optional[float] = None

    if bar_range and bar_range > 0 and o is not None and c is not None:
        body_pct       = round(abs(c - o) / bar_range, 4)
        upper_wick_pct = round((h - max(o, c)) / bar_range, 4)         # type: ignore[operator]
        lower_wick_pct = round((min(o, c) - l) / bar_range, 4)         # type: ignore[operator]

    # ── Derived: close-position classifications ───────────────────────────────
    strong_close = (close_pos >= 0.80) if close_pos is not None else None
    weak_close   = (close_pos <= 0.20) if close_pos is not None else None
    doji_like    = (body_pct  <  0.10) if body_pct  is not None else None

    # ── Derived: volume flags ─────────────────────────────────────────────────
    abnormal_vol = (
        (vol_vs_avg20 is not None and vol_vs_avg20 >= 2.0) or
        (vol_z        is not None and vol_z         >= 2.5)
    ) if (vol_vs_avg20 is not None or vol_z is not None) else None

    dryup = (vol_vs_avg20 < 0.5) if vol_vs_avg20 is not None else None

    # ── Derived: wide/narrow range bar (requires trailing context) ────────────
    wide_bar      = None
    narrow_bar    = None
    expansion_bar = None

    if trailing_avg_range_pct and intra_range is not None:
        wide_bar   = intra_range > 1.5 * trailing_avg_range_pct
        narrow_bar = intra_range < 0.5 * trailing_avg_range_pct
        expansion_bar = bool(
            wide_bar and strong_close and
            vol_vs_avg20 is not None and vol_vs_avg20 > 1.5
        )

    # ── Derived: extreme anomaly flag ─────────────────────────────────────────
    # Wide EMA spread + extreme volume = penalised in NP engine; track for study
    extreme_anomaly = None
    if vol_z is not None:
        extreme_anomaly = bool(
            vol_z > 4.0 or
            (trailing_avg_range_pct and intra_range is not None
             and intra_range > 3.0 * trailing_avg_range_pct)
        )

    # ── Assemble output row ───────────────────────────────────────────────────
    return {
        # Identity / window context
        "run_id":                  raw_run_id,
        "episode_id":              snap.get("episode_id"),
        "symbol":                  snap.get("symbol"),
        "date":                    snap.get("date"),
        "phase":                   snap.get("window_phase"),
        "relative_day_from_start": snap.get("relative_day_from_start"),
        "relative_day_from_peak":  snap.get("relative_day_from_peak"),

        # Instrument context (episode supplies sector/industry; rest unavailable)
        "sector":        episode.get("sector"),
        "industry":      episode.get("industry"),
        "exchange":      None,      # not stored in pipeline
        "market_cap":    None,      # requires reference API
        "float_shares":  None,      # requires reference API
        "market_regime": None,      # broad market context not computed

        # Raw OHLCV
        "open":         o,
        "high":         h,
        "low":          l,
        "close":        c,
        "volume":       v,
        "dollar_volume": round(dollar_vol, 2) if dollar_vol is not None else None,

        # Candle anatomy — direct
        "gap_pct":            snap.get("gap_pct"),
        "intraday_range_pct": intra_range,
        # Candle anatomy — derived
        "body_pct":               body_pct,
        "upper_wick_pct":         upper_wick_pct,
        "lower_wick_pct":         lower_wick_pct,
        "close_position_in_bar":  close_pos,
        "wide_range_bar":         wide_bar,
        "narrow_range_bar":       narrow_bar,
        "strong_close_near_high": strong_close,
        "weak_close_near_low":    weak_close,

        # Volume / liquidity — direct
        "volume_vs_avg20": vol_vs_avg20,
        "volume_zscore":   vol_z,
        # Volume / liquidity — deferred (need trailing series from caller)
        "volume_vs_avg5":          None,
        "volume_vs_avg10":         None,
        "dollar_volume_vs_avg20":  None,
        # Volume / liquidity — derived
        "abnormal_volume_day": abnormal_vol,
        "dryup_day":           dryup,

        # Volatility / compression — direct
        "atr_pct":    snap.get("atr_pct"),
        "bb_width":   snap.get("bb_width"),
        # Volatility / compression — from snapshot_json
        "atr":                atr_abs,
        "atr_expansion_state": atr_exp,
        "bb_squeeze_bars":    bb_sqz_bars,
        "ema_spread_pct":     ema_spread,
        "compression_state":  compr_state,

        # Distance context — null (52w range not stored; added by caller from episode window)
        "distance_to_range_high": None,
        "distance_to_range_low":  None,
        "distance_to_mid_range":  None,

        # Candle pattern flags — null here (require prev-bar; set by caller loop)
        "bullish_engulfing": None,
        "bearish_engulfing": None,
        "inside_bar":        None,
        "outside_bar":       None,
        "doji_like":         doji_like,
        "reclaim_bar":       None,
        "expansion_bar":     expansion_bar,

        # Overflow — EMA ribbon details + NP-relevant context flags
        "feature_json": {
            **_build_ema_feature_json(ind, c, compr_state),
            # New Pump context fields (derivable without NP engine re-run)
            "bull_stack_active":    ind.get("bullish_stack"),
            "above_ema200":         (bool(c > ind["ema200"])
                                     if (c is not None and ind.get("ema200")) else None),
            "volume_z":             vol_z,
            "dollar_volume":        round(dollar_vol, 2) if dollar_vol is not None else None,
            "ema_spread_pct":       ema_spread,
            "expansion_bar":        expansion_bar,
            "extreme_anomaly_flag": extreme_anomaly,
        },
    }


def _fill_prev_bar_flags(row: dict, snap: dict, prev_snap: dict) -> None:
    """
    Fill cross-bar candle pattern flags that require the previous bar.
    Modifies *row* in-place; both snap and prev_snap are snapshot dicts.
    """
    ph = prev_snap.get("high")
    pl = prev_snap.get("low")
    po = prev_snap.get("open")
    pc = prev_snap.get("close")

    h  = snap.get("high")
    l  = snap.get("low")
    o  = snap.get("open")
    c  = snap.get("close")

    if None in (ph, pl, po, pc, h, l, o, c):
        return  # leave flags None when any OHLC is missing

    prev_bearish  = pc < po
    prev_bullish  = pc > po
    today_bullish = c  > o
    today_bearish = c  < o

    # Bullish engulfing: prev bearish; today bullish body engulfs prev body
    row["bullish_engulfing"] = bool(
        prev_bearish and today_bullish
        and min(o, c) <= min(po, pc)
        and max(o, c) >= max(po, pc)
    )

    # Bearish engulfing: prev bullish; today bearish body engulfs prev body
    row["bearish_engulfing"] = bool(
        prev_bullish and today_bearish
        and min(o, c) <= min(po, pc)
        and max(o, c) >= max(po, pc)
    )

    # Inside bar: today's range entirely within prev bar's range
    row["inside_bar"]  = bool(h <= ph and l >= pl)

    # Outside bar: today's range completely engulfs prev bar's range
    row["outside_bar"] = bool(h > ph and l < pl)

    # Reclaim bar: gapped down but closed above prev close
    gap = snap.get("gap_pct")
    row["reclaim_bar"] = bool(gap is not None and gap < 0 and c > pc)

    # EMA cross-bar flags — stored inside feature_json
    fj = row.get("feature_json")
    if isinstance(fj, dict):
        ind      = (snap.get("snapshot") or {}).get("indicators") or {}
        prev_ind = (prev_snap.get("snapshot") or {}).get("indicators") or {}
        curr_ema50 = ind.get("ema50")
        prev_ema50 = prev_ind.get("ema50")
        curr_ema21 = ind.get("ema21")
        if curr_ema50 is not None and prev_ema50 is not None:
            fj["ema50_reclaim_day"] = bool(c > curr_ema50 and pc < prev_ema50)
        if curr_ema21 is not None:
            # Support: bar touched or pierced ema21 from above but closed at/above it bullishly
            fj["ema21_support_day"] = bool(l <= curr_ema21 and c >= curr_ema21 and today_bullish)


def _compute_per_bar_custom_flags(snaps: list[dict]) -> list[dict]:
    """
    Compute per-bar D/WLNBB/NP custom signal boolean flags for injection into
    feature_json.  Returns one flag-dict per snap (same length as snaps).

    Flags computed:
      has_l34, has_l43, has_l22, has_l64  — WLNBB bucket signals
      has_fri34, has_fri64                — BLUE + L34/L64
      has_d3_beup, has_d4_beup, has_d6_beup — Manual-D × BE-Up same-bar (core)
      has_d1_beup, has_d9_beup, has_d11_beup — Manual-D × BE-Up same-bar (secondary)
      has_d4_l34, has_d3_l34              — Manual-D × L34 same-bar (core)
      has_d1_l34, has_d9_l34, has_d11_l34 — Manual-D × L34 same-bar (secondary)
      has_d1_l43, has_d9_l43, has_d11_l43 — Manual-D × L43 same-bar (secondary)
      has_vbo                             — be_up_wlnbb AND bucket in (B, VB)
      has_lvbo                            — break_up_wlnbb AND bucket == N
      has_ld                              — quiet day, close upper-half, lower wick ≥20%
      has_wc_gap_ld                       — two-bar: prev weak-close → gap-up + lower-wick reclaim
      has_l34_np_ld                       — L34 + NP setup state + lower-wick reclaim same bar
      np_is_setup                         — NP-engine L34 or FRI34 on this bar
      np_is_trigger                       — NP-engine G4 on this bar
    """
    if not snaps:
        return []

    candles = [
        {
            "open":   float(s.get("open")   or 0.0),
            "high":   float(s.get("high")   or 0.0),
            "low":    float(s.get("low")    or 0.0),
            "close":  float(s.get("close")  or 0.0),
            "volume": float(s.get("volume") or 0.0),
        }
        for s in snaps
    ]

    # WLNBB + Manual-D series (oldest→newest)
    try:
        from scanner.manual_d_wlnbb_features import (
            compute_wlnbb_features,
            compute_manual_d_features,
        )
        wlnbb_series = compute_wlnbb_features(candles)
        d_series     = compute_manual_d_features(candles)
    except Exception:
        logger.warning("[CustomFlags] manual_d_wlnbb_features unavailable — skipping")
        return [{} for _ in snaps]

    # NP-engine signal history: L34/FRI34/G4 bar index sets
    np_l34_set = np_fri34_set = np_g4_set = frozenset()
    try:
        from scanner.new_pump_engine import _build_signal_history
        hist = _build_signal_history(candles)
        np_l34_set   = frozenset(hist["l34_bars"])
        np_fri34_set = frozenset(hist["fri34_bars"])
        np_g4_set    = frozenset(hist["g4_bars"])
    except Exception:
        logger.warning("[CustomFlags] new_pump_engine unavailable — NP flags skipped")

    # FRI64 = BLUE + L64; BLUE reuses NP-engine's volume-z / RSI-range3 logic
    np_fri64_set: set[int] = set()
    try:
        from scanner.new_pump_engine import _compute_rsi, _sma, _std
        closes  = [b["close"]  for b in candles]
        volumes = [b["volume"] for b in candles]
        rsi_s   = _compute_rsi(closes)
        for i in range(1, len(candles)):
            if not wlnbb_series[i].get("l64_wlnbb"):
                continue
            vol_win = volumes[max(0, i - 19): i + 1]
            v_mid   = _sma(vol_win, 20)
            v_std   = _std(vol_win, 20)
            if v_mid is None or v_std is None or v_std <= 0:
                continue
            volume_z = (volumes[i] - v_mid) / v_std
            if i >= 2:
                rv = [rsi_s[j] for j in (i - 2, i - 1, i) if rsi_s[j] is not None]
                if len(rv) == 3 and volume_z >= 1.1 and (max(rv) - min(rv)) <= 5.0:
                    np_fri64_set.add(i)
    except Exception:
        pass

    # ABR/TZ quality series
    abr_series: list[dict] = []
    try:
        from replay.abr_tz_engine import compute_abr_tz_features
        abr_series = compute_abr_tz_features(candles)
    except Exception:
        logger.warning("[CustomFlags] abr_tz_engine unavailable — ABR fields skipped")

    # 260521 Line3/4/5: body/wick/gap/range/VIX-Fix/PSAR/RSI2
    bar_labels_260521: list[dict] = []
    try:
        from scanner.manual_d_wlnbb_features import compute_combined_bar_labels
        bar_labels_260521 = compute_combined_bar_labels(candles, last_n=len(candles))
    except Exception:
        logger.warning("[CustomFlags] compute_combined_bar_labels L3/4/5 unavailable — skipped")

    result: list[dict] = []
    for i, w in enumerate(wlnbb_series):
        d    = d_series[i]
        l34  = w.get("l34_wlnbb",      False)
        l43  = w.get("l43_wlnbb",      False)
        l22  = w.get("l22_wlnbb",      False)
        l64  = w.get("l64_wlnbb",      False)
        beup = w.get("be_up_wlnbb",    False)
        bup  = w.get("break_up_wlnbb", False)
        bkt  = w.get("bucket",         "?")
        d1   = d.get("d1",  False)
        d3   = d.get("d3",  False)
        d4   = d.get("d4",  False)
        d6   = d.get("d6",  False)
        d9   = d.get("d9",  False)
        d11  = d.get("d11", False)

        # has_ld / has_wc_gap_ld pre-computation
        _cb  = candles[i]
        _rng = max(_cb["high"] - _cb["low"], 1e-6)
        _pos = (_cb["close"] - _cb["low"]) / _rng          # 0=low, 1=high
        _lwk = (min(_cb["open"], _cb["close"]) - _cb["low"]) / _rng

        # Two-bar: prev weak-close → cur gap-up + lower-wick reclaim
        if i > 0:
            _pb   = candles[i - 1]
            _pb_r = max(_pb["high"] - _pb["low"], 1e-6)
            _pb_pos = (_pb["close"] - _pb["low"]) / _pb_r      # prev close position
            _gap_up = _cb["open"] > _pb["close"] * 1.002       # ≥0.2% gap up
            _wc_gap_ld = bool(
                _pb_pos <= 0.35                                 # prev bar weak close
                and _gap_up
                and _pos >= 0.50 and _lwk >= 0.20              # cur bar lower-wick reclaim
            )
        else:
            _wc_gap_ld = False

        flags: dict = {
            "has_l34":        bool(l34),
            "has_l43":        bool(l43),
            "has_l22":        bool(l22),
            "has_l64":        bool(l64),
            "has_fri34":      bool(i in np_fri34_set),
            "has_fri64":      bool(i in np_fri64_set),
            # core D × WLNBB
            "has_d3_beup":    bool(d3 and beup),
            "has_d4_beup":    bool(d4 and beup),
            "has_d6_beup":    bool(d6 and beup),
            "has_d4_l34":     bool(d4 and l34),
            "has_d3_l34":     bool(d3 and l34),
            # secondary D × WLNBB
            "has_d1_beup":    bool(d1  and beup),
            "has_d9_beup":    bool(d9  and beup),
            "has_d11_beup":   bool(d11 and beup),
            "has_d1_l34":     bool(d1  and l34),
            "has_d9_l34":     bool(d9  and l34),
            "has_d11_l34":    bool(d11 and l34),
            "has_d1_l43":     bool(d1  and l43),
            "has_d9_l43":     bool(d9  and l43),
            "has_d11_l43":    bool(d11 and l43),
            "has_vbo":        bool(beup and bkt in ("B", "VB")),
            "has_lvbo":       bool(bup  and bkt == "N"),
            # has_ld: Low-volume lower-wick Demand absorption bar.
            # Quiet day (bucket N) where price probed lower but recovered,
            # closing in the upper half with a meaningful lower wick.
            # Classic supply-exhaustion / dryup-test that precedes setups.
            "has_ld":         bool(bkt == "N" and not beup and not bup
                                   and _pos >= 0.50 and _lwk >= 0.20),
            # has_wc_gap_ld: Two-bar pattern. Prev bar weak-close → cur bar gaps
            # up and reclaims lower wick (demand). R154: rel=0.814, Tier-1 clean.
            "has_wc_gap_ld":  _wc_gap_ld,
            # has_l34_np_ld: L34 setup + NP engine in setup state + lower-wick
            # reclaim on same bar. R155 #1 PRICE_ACTION: rel=0.766, 10×4x, 3×FP.
            "has_l34_np_ld":  bool(l34
                                   and (i in np_l34_set or i in np_fri34_set)
                                   and _pos >= 0.50 and _lwk >= 0.20),
            "np_is_setup":    bool(i in np_l34_set or i in np_fri34_set),
            "np_is_trigger":  bool(i in np_g4_set),
        }
        if i < len(abr_series) and abr_series[i]:
            flags.update(abr_series[i])

        # Inject 260521 L3/4/5 token fields
        if i < len(bar_labels_260521):
            lbl = bar_labels_260521[i]
            flags["body_class"]  = lbl.get("body_class",  "") or ""
            flags["wick_class"]  = lbl.get("wick_class",  "") or ""
            flags["gap_class"]   = lbl.get("gap_class",   "") or ""
            flags["range_class"] = lbl.get("range_class", "") or ""
            flags["vix_token"]   = lbl.get("vix_token",   "") or ""
            flags["psar_token"]  = lbl.get("psar_token",  "") or ""
            flags["rsi2_token"]  = lbl.get("rsi2_token",  "") or ""

        result.append(flags)

    return result


async def build_raw_pattern_daily_features(
    raw_run_id: int,
    pump_study_run_id: int,
) -> int:
    """
    Iterate all pump episodes for *pump_study_run_id*, convert every daily
    snapshot into a raw_pattern_daily_features row via
    snapshot_to_raw_daily_feature(), fill trailing-context and cross-bar
    fields, bulk-save the rows, and update raw_daily_count on the run.

    Returns the total number of feature rows saved.
    """
    from collections import deque

    from database import (
        get_pump_episodes,
        get_pump_episode_snapshots,
        save_raw_pattern_daily_features,
        update_raw_pattern_run,
    )

    _TRAIL_N = 10   # bars for trailing intraday-range average (wide/narrow bar)
    _DVOL_N  = 20   # bars for dollar-volume trailing average

    episodes = await get_pump_episodes(pump_study_run_id, limit=10_000)
    total_rows = 0

    for ep in episodes:
        episode_id = ep["id"]
        snaps = await get_pump_episode_snapshots(episode_id)
        if not snaps:
            continue

        # Episode-wide price range for distance_to_range_* fields
        ep_high: Optional[float] = None
        ep_low:  Optional[float] = None
        for s in snaps:
            sh = s.get("high")
            sl = s.get("low")
            if sh is not None:
                ep_high = sh if ep_high is None else max(ep_high, sh)
            if sl is not None:
                ep_low  = sl if ep_low  is None else min(ep_low,  sl)
        ep_mid = (
            (ep_high + ep_low) / 2
            if (ep_high is not None and ep_low is not None)
            else None
        )

        range_history: deque = deque(maxlen=_TRAIL_N)
        dvol_history:  deque = deque(maxlen=_DVOL_N)

        rows: list[dict]         = []
        prev_snap: Optional[dict] = None

        for snap in snaps:
            trailing_avg = (
                sum(range_history) / len(range_history)
                if range_history else None
            )

            row = snapshot_to_raw_daily_feature(
                snap, ep, raw_run_id,
                trailing_avg_range_pct=trailing_avg,
            )

            # volume_vs_avg5 from snapshot_json.indicators.avg_vol_5
            sj   = snap.get("snapshot") or {}
            ind  = sj.get("indicators") or {}
            avg5 = ind.get("avg_vol_5")
            sv   = snap.get("volume")
            if avg5 and sv and avg5 > 0:
                row["volume_vs_avg5"] = round(sv / avg5, 3)

            # dollar_volume_vs_avg20 from trailing dollar-volume history
            dvol = row.get("dollar_volume")
            if dvol is not None and dvol > 0 and len(dvol_history) == _DVOL_N:
                dvol_avg = sum(dvol_history) / _DVOL_N
                if dvol_avg > 0:
                    row["dollar_volume_vs_avg20"] = round(dvol / dvol_avg, 3)

            # Distance fields relative to the episode's full price range
            sc = snap.get("close")
            if sc is not None and ep_high is not None and ep_low is not None:
                ep_range = ep_high - ep_low
                if ep_range > 0:
                    row["distance_to_range_high"] = round((ep_high - sc) / ep_range, 4)
                    row["distance_to_range_low"]  = round((sc - ep_low)  / ep_range, 4)
                    if ep_mid is not None:
                        row["distance_to_mid_range"] = round((sc - ep_mid) / ep_range, 4)

            # Cross-bar pattern flags
            if prev_snap is not None:
                _fill_prev_bar_flags(row, snap, prev_snap)

            # Advance trailing histories (after row is built so bar N is not in its own avg)
            intra = snap.get("intraday_range_pct")
            if intra is not None:
                range_history.append(intra)
            if dvol is not None and dvol > 0:
                dvol_history.append(dvol)

            rows.append(row)
            prev_snap = snap

        if rows:
            # Inject per-bar custom signal flags into each row's feature_json
            try:
                custom_flags = _compute_per_bar_custom_flags(snaps)
                for row, flags in zip(rows, custom_flags):
                    if flags:
                        fj = row.get("feature_json")
                        if fj is None:
                            fj = {}
                            row["feature_json"] = fj
                        fj.update(flags)
            except Exception as exc:
                logger.warning("[CustomFlags] injection failed for ep %s: %s", episode_id, exc)

            saved = await save_raw_pattern_daily_features(raw_run_id, rows)
            total_rows += saved

    await update_raw_pattern_run(raw_run_id, {"raw_daily_count": total_rows})
    return total_rows


async def build_raw_pattern_episode_features_timing(
    raw_run_id: int,
    pump_study_run_id: int,
) -> int:
    """
    Phase 2B-1: compute timing / base aggregate fields for each episode and
    persist one raw_pattern_episode_features row per episode.

    Fields populated (all others left None for later phases):
        Identity:   run_id, episode_id, symbol, group_type, pump_multiple, pump_type
        Timing:     pre_days, pump_days, post_days, days_in_base,
                    days_from_first_abnormal_volume_to_breakout,
                    days_from_breakout_to_peak,
                    days_from_first_compression_to_breakout

    Sources:
        - raw_pattern_daily_features  (phase counts, abnormal_volume_day,
                                       compression_state / bb_squeeze_bars)
        - pump_episodes               (group_type, pump_multiple, pump_type)
        - pump_episode_events         (breakout_day, peak_day dates)

    Returns the total number of episode feature rows saved.
    """
    from database import (
        get_pump_episodes,
        get_pump_comparison_members,
        get_raw_pattern_daily_features,
        get_pump_episode_events,
        save_raw_pattern_episode_features,
        update_raw_pattern_run,
    )

    # ── Build episode_id → group_name from Pump Study comparison members ──
    # Priority: false_positive wins over 4x_pump (it is a more specific label
    # for the same episode).  missed_mover has no episode_id and is skipped.
    _GROUP_PRIORITY = {"false_positive": 0, "4x_pump": 1, "normal_winner": 2, "missed_mover": 3}
    ps_members = await get_pump_comparison_members(pump_study_run_id)
    episode_group: dict[int, str] = {}
    for m in ps_members:
        eid   = m.get("episode_id")
        gname = m.get("group_name")
        if eid is None or not gname:
            continue
        existing = episode_group.get(eid)
        if existing is None or _GROUP_PRIORITY.get(gname, 99) < _GROUP_PRIORITY.get(existing, 99):
            episode_group[eid] = gname

    episodes   = await get_pump_episodes(pump_study_run_id, limit=10_000)
    total_rows = 0

    rows_to_save: list[dict] = []

    for ep in episodes:
        episode_id = ep["id"]

        # ── Fetch daily features for this episode ──────────────────────────
        daily = await get_raw_pattern_daily_features(
            raw_run_id, episode_id=episode_id, limit=2000
        )

        if not daily:
            continue

        # ── Phase counts ───────────────────────────────────────────────────
        pre_days  = sum(1 for r in daily if r.get("phase") == "PRE")
        pump_days = sum(1 for r in daily if r.get("phase") == "PUMP")
        post_days = sum(1 for r in daily if r.get("phase") == "POST")
        days_in_base = pre_days  # PRE window = base/accumulation window

        # ── Sort PRE rows by date for ordinal lookups ──────────────────────
        pre_rows = sorted(
            (r for r in daily if r.get("phase") == "PRE"),
            key=lambda r: r.get("date") or "",
        )

        # ── First abnormal volume day in PRE or PUMP ───────────────────────
        first_abnormal_date: Optional[str] = None
        for r in sorted(daily, key=lambda r: r.get("date") or ""):
            if r.get("abnormal_volume_day"):
                first_abnormal_date = r.get("date")
                break

        # ── First compression day in PRE ───────────────────────────────────
        # Compression: compression_state in (STRONG, MEDIUM) or bb_squeeze_bars >= 3
        first_compression_date: Optional[str] = None
        for r in pre_rows:
            cs   = r.get("compression_state") or ""
            sqz  = r.get("bb_squeeze_bars")
            if cs in ("STRONG", "MEDIUM") or (sqz is not None and sqz >= 3):
                first_compression_date = r.get("date")
                break

        # ── Breakout / peak dates from episode timeline events ─────────────
        evs = await get_pump_episode_events(episode_id)
        breakout_date: Optional[str] = None
        peak_date:     Optional[str] = None
        for ev in evs:
            et = ev.get("event_type")
            ed = ev.get("event_date")
            if et == "breakout_day" and breakout_date is None:
                breakout_date = str(ed) if ed else None
            elif et == "peak_day" and peak_date is None:
                peak_date = str(ed) if ed else None

        # ── Derived day-delta fields ───────────────────────────────────────
        def _day_delta(d1: Optional[str], d2: Optional[str]) -> Optional[int]:
            """Calendar days from d1 to d2. Returns None when either is missing."""
            if not d1 or not d2:
                return None
            try:
                return (date.fromisoformat(d2) - date.fromisoformat(d1)).days
            except (ValueError, TypeError):
                return None

        days_abnvol_to_breakout  = _day_delta(first_abnormal_date, breakout_date)
        days_breakout_to_peak    = _day_delta(breakout_date, peak_date)
        days_compr_to_breakout   = _day_delta(first_compression_date, breakout_date)

        rows_to_save.append({
            "run_id":       raw_run_id,
            "episode_id":   episode_id,
            "symbol":       ep.get("symbol"),
            "group_type":   episode_group.get(episode_id),
            "pump_multiple": ep.get("pump_multiple"),
            "pump_type":    ep.get("pump_type"),
            "sector":       ep.get("sector"),
            "industry":     ep.get("industry"),
            # Timing
            "pre_days":                                   pre_days  or None,
            "pump_days":                                  pump_days or None,
            "post_days":                                  post_days or None,
            "days_in_base":                               days_in_base or None,
            "days_from_first_abnormal_volume_to_breakout": days_abnvol_to_breakout,
            "days_from_breakout_to_peak":                  days_breakout_to_peak,
            "days_from_first_compression_to_breakout":     days_compr_to_breakout,
        })

    if rows_to_save:
        await save_raw_pattern_episode_features(raw_run_id, rows_to_save)
        total_rows = len(rows_to_save)

    await update_raw_pattern_run(raw_run_id, {"episode_feature_count": total_rows})
    return total_rows


async def build_raw_pattern_episode_features_candle(
    raw_run_id: int,
    pump_study_run_id: int,
) -> int:
    """
    Phase 2B-2: compute PRE-window candle anatomy and pattern-count aggregates
    and patch them onto existing raw_pattern_episode_features rows.

    Fields patched:
        Candle anatomy:  avg_body_pct_pre, avg_upper_wick_pct_pre,
                         avg_lower_wick_pct_pre, wide_range_bar_count_pre,
                         narrow_range_bar_count_pre, strong_close_count_pre
        Pattern counts:  bullish_engulfing_count_pre, bearish_engulfing_count_pre,
                         inside_bar_count_pre, outside_bar_count_pre,
                         reclaim_bar_count_pre, expansion_bar_count_pre

    Reads from raw_pattern_daily_features (PRE phase only).
    Updates existing rows via update_raw_pattern_episode_features().
    Returns the number of episodes patched.
    """
    from database import (
        get_pump_episodes,
        get_raw_pattern_daily_features,
        update_raw_pattern_episode_features,
    )

    def _mean(vals: list) -> Optional[float]:
        cleaned = [v for v in vals if v is not None]
        return round(sum(cleaned) / len(cleaned), 4) if cleaned else None

    def _count_true(vals: list) -> int:
        return sum(1 for v in vals if v)

    episodes = await get_pump_episodes(pump_study_run_id, limit=10_000)
    patched  = 0

    for ep in episodes:
        episode_id = ep["id"]

        pre_rows = await get_raw_pattern_daily_features(
            raw_run_id, episode_id=episode_id, phase="PRE", limit=500
        )
        if not pre_rows:
            continue

        # ── Candle anatomy averages ────────────────────────────────────────
        avg_body        = _mean([r.get("body_pct")         for r in pre_rows])
        avg_upper_wick  = _mean([r.get("upper_wick_pct")   for r in pre_rows])
        avg_lower_wick  = _mean([r.get("lower_wick_pct")   for r in pre_rows])

        # ── Candle classification counts ───────────────────────────────────
        wide_count   = _count_true(r.get("wide_range_bar")       for r in pre_rows)
        narrow_count = _count_true(r.get("narrow_range_bar")     for r in pre_rows)
        strong_count = _count_true(r.get("strong_close_near_high") for r in pre_rows)

        # ── Pattern counts ─────────────────────────────────────────────────
        bull_eng  = _count_true(r.get("bullish_engulfing") for r in pre_rows)
        bear_eng  = _count_true(r.get("bearish_engulfing") for r in pre_rows)
        inside    = _count_true(r.get("inside_bar")        for r in pre_rows)
        outside   = _count_true(r.get("outside_bar")       for r in pre_rows)
        reclaim   = _count_true(r.get("reclaim_bar")       for r in pre_rows)
        expansion = _count_true(r.get("expansion_bar")     for r in pre_rows)

        await update_raw_pattern_episode_features(raw_run_id, episode_id, {
            "avg_body_pct_pre":           avg_body,
            "avg_upper_wick_pct_pre":     avg_upper_wick,
            "avg_lower_wick_pct_pre":     avg_lower_wick,
            "wide_range_bar_count_pre":   wide_count   or None,
            "narrow_range_bar_count_pre": narrow_count or None,
            "strong_close_count_pre":     strong_count or None,
            "bullish_engulfing_count_pre": bull_eng  or None,
            "bearish_engulfing_count_pre": bear_eng  or None,
            "inside_bar_count_pre":        inside    or None,
            "outside_bar_count_pre":       outside   or None,
            "reclaim_bar_count_pre":       reclaim   or None,
            "expansion_bar_count_pre":     expansion or None,
        })
        patched += 1

    return patched


async def build_raw_pattern_episode_features_volume_compression(
    raw_run_id: int,
    pump_study_run_id: int,
) -> int:
    """
    Phase 2B-3: compute PRE-window volume and compression/volatility aggregates
    and patch them onto existing raw_pattern_episode_features rows.

    Fields patched:
        Volume:       max_volume_anomaly_pre, median_volume_anomaly_pre,
                      abnormal_volume_day_count_pre, dryup_day_count_pre,
                      max_dollar_volume_pre
        Compression:  had_compression, compression_days_pre, min_bb_width_pre,
                      avg_atr_pct_pre, atr_contraction_days_pre

    Reads from raw_pattern_daily_features (PRE phase only).
    Patches existing rows via update_raw_pattern_episode_features().
    Returns the number of episodes patched.
    """
    from database import (
        get_pump_episodes,
        get_raw_pattern_daily_features,
        update_raw_pattern_episode_features,
    )

    def _median(vals: list) -> Optional[float]:
        cleaned = sorted(v for v in vals if v is not None)
        n = len(cleaned)
        if n == 0:
            return None
        mid = n // 2
        return round((cleaned[mid - 1] + cleaned[mid]) / 2, 4) if n % 2 == 0 else round(cleaned[mid], 4)

    def _mean(vals: list) -> Optional[float]:
        cleaned = [v for v in vals if v is not None]
        return round(sum(cleaned) / len(cleaned), 4) if cleaned else None

    def _max(vals: list) -> Optional[float]:
        cleaned = [v for v in vals if v is not None]
        return round(max(cleaned), 4) if cleaned else None

    def _min(vals: list) -> Optional[float]:
        cleaned = [v for v in vals if v is not None]
        return round(min(cleaned), 4) if cleaned else None

    def _count_true(vals: list) -> int:
        return sum(1 for v in vals if v)

    def _is_compressed(row: dict) -> bool:
        cs  = row.get("compression_state") or ""
        sqz = row.get("bb_squeeze_bars")
        return cs in ("STRONG", "MEDIUM") or (sqz is not None and sqz >= 3)

    episodes = await get_pump_episodes(pump_study_run_id, limit=10_000)
    patched  = 0

    for ep in episodes:
        episode_id = ep["id"]

        pre_rows = await get_raw_pattern_daily_features(
            raw_run_id, episode_id=episode_id, phase="PRE", limit=500
        )
        if not pre_rows:
            continue

        # ── Volume ────────────────────────────────────────────────────────
        vol_anomalies = [r.get("volume_vs_avg20") for r in pre_rows]
        max_vol_anom    = _max(vol_anomalies)
        median_vol_anom = _median(vol_anomalies)
        abnormal_count  = _count_true(r.get("abnormal_volume_day") for r in pre_rows)
        dryup_count     = _count_true(r.get("dryup_day")           for r in pre_rows)
        max_dvol        = _max([r.get("dollar_volume") for r in pre_rows])

        # ── Compression / volatility ──────────────────────────────────────
        compr_flags     = [_is_compressed(r) for r in pre_rows]
        had_compr       = any(compr_flags)
        compr_days      = sum(compr_flags)
        min_bb          = _min([r.get("bb_width")   for r in pre_rows])
        avg_atr         = _mean([r.get("atr_pct")   for r in pre_rows])
        atr_contr_days  = sum(
            1 for r in pre_rows if r.get("atr_expansion_state") == "CONTRACTING"
        )

        await update_raw_pattern_episode_features(raw_run_id, episode_id, {
            "max_volume_anomaly_pre":        max_vol_anom,
            "median_volume_anomaly_pre":     median_vol_anom,
            "abnormal_volume_day_count_pre": abnormal_count or None,
            "dryup_day_count_pre":           dryup_count    or None,
            "max_dollar_volume_pre":         max_dvol,
            "had_compression":               had_compr      or None,
            "compression_days_pre":          compr_days     or None,
            "min_bb_width_pre":              min_bb,
            "avg_atr_pct_pre":               avg_atr,
            "atr_contraction_days_pre":      atr_contr_days or None,
        })
        patched += 1

    return patched


async def build_raw_pattern_episode_features_structure(
    raw_run_id: int,
    pump_study_run_id: int,
) -> int:
    """
    Phase 2B-4: compute PRE-window structure/sequence aggregates and patch
    them onto existing raw_pattern_episode_features rows.

    Fields patched:
        had_accumulation_like, accumulation_like_day_count, had_spring_test_lps
        had_breakout_retest, retest_count, avg_retest_quality (null — no source)
        strongest_wyckoff_state, strongest_sequence_type, strongest_structural_bias

    Sources:
        pump_episode_events         — had_accumulation_like, had_spring_test_lps
        pump_episodes.strongest_wyckoff_state / pump_type — re-used directly
        pump_episode_snapshots (PRE) — accumulation_like_day_count,
                                       in_dist scan for structural bias

    Returns the number of episodes patched.
    """
    from database import (
        get_pump_episodes,
        get_pump_episode_events,
        get_pump_episode_snapshots,
        update_raw_pattern_episode_features,
    )

    # Priority ranking for Wyckoff states (higher = stronger)
    _STATE_RANK: dict[str, int] = {
        "FIRE": 5, "ARM": 4, "STEALTH_ARM": 3,
        "BASE": 2, "STEALTH": 1, "NONE": 0,
    }

    episodes = await get_pump_episodes(pump_study_run_id, limit=10_000)
    patched  = 0

    for ep in episodes:
        episode_id = ep["id"]

        # ── Boolean milestones from timeline events ────────────────────────
        evs         = await get_pump_episode_events(episode_id)
        event_types = {e["event_type"] for e in evs}

        had_acc_like = "first_accumulation_like_day" in event_types
        had_spring   = "first_spring_test_lps_day"   in event_types

        # ── Episode-level computed fields (already stored during enrichment) ─
        # strongest_wyckoff_state and pump_type are computed by Phase 3D/3E
        ep_wyckoff   = ep.get("strongest_wyckoff_state")
        ep_pump_type = ep.get("pump_type")

        # ── PRE snapshots: accumulation day count + distribution scan ─────
        pre_snaps = await get_pump_episode_snapshots(episode_id, phase="PRE")

        acc_day_count    = 0
        in_dist_any      = False
        scan_best_state  = None
        scan_best_rank   = -1

        for s in pre_snaps:
            reg = (s.get("snapshot") or {}).get("regime") or {}
            if reg.get("in_acc"):
                acc_day_count += 1
            if reg.get("in_dist"):
                in_dist_any = True
            # Fallback Wyckoff state scan (supplements episode-level if missing)
            state = reg.get("state") or s.get("wyckoff_state")
            if state:
                rank = _STATE_RANK.get(state, 0)
                if rank > scan_best_rank:
                    scan_best_rank  = rank
                    scan_best_state = state

        # Prefer episode-level value (computed over full window); fallback to PRE scan
        strongest_state = ep_wyckoff or scan_best_state

        # ── Structural bias ────────────────────────────────────────────────
        if had_acc_like or acc_day_count > 0:
            structural_bias: Optional[str] = "BULLISH"
        elif in_dist_any:
            structural_bias = "BEARISH"
        elif pre_snaps:
            structural_bias = "NEUTRAL"  # data present, no directional signal
        else:
            structural_bias = None

        await update_raw_pattern_episode_features(raw_run_id, episode_id, {
            "had_accumulation_like":       had_acc_like or None,
            "accumulation_like_day_count": acc_day_count or None,
            "had_spring_test_lps":         had_spring or None,
            "had_breakout_retest":         None,   # no stored source
            "retest_count":                None,   # no stored source
            "avg_retest_quality":          None,   # no stored source
            "strongest_wyckoff_state":     strongest_state,
            "strongest_sequence_type":     ep_pump_type,
            "strongest_structural_bias":   structural_bias,
        })
        patched += 1

    return patched


# Features extracted into each member's features_json and compared across groups.
# Ordered PRIMARY first so the comparison table is meaningful at a glance.
_COMPARISON_FEATURES = [
    # ── PRIMARY: New Pump signal presence / timing ──
    "had_valid_recent_setup",
    "had_valid_recent_trigger",
    "had_valid_recent_confirm",
    "had_valid_full_sequence",
    "best_new_pump_label_rank",       # numeric rank: FIRE=0…NONE=5
    "days_from_last_setup_to_breakout",
    "days_from_last_trigger_to_breakout",
    "days_from_g4_to_b2",
    # ── PRIMARY: NP count-based PRE-window aggregates ──
    "l34_count_pre",
    "fri34_count_pre",
    "g4_count_pre",
    "b2_count_pre",
    "isolated_g4_count_pre",
    "isolated_b2_count_pre",
    "full_fri34_g4_b2_count_pre",
    "valid_setup_days_pre",
    "valid_full_sequence_days_pre",
    # ── SECONDARY: NP count details ──
    "setup_only_l34_count_pre",
    "setup_only_fri34_count_pre",
    "trigger_after_l34_count_pre",
    "trigger_after_fri34_count_pre",
    "full_l34_g4_b2_count_pre",
    "confirm_after_g4_count_pre",
    "valid_trigger_days_pre",
    "valid_confirm_days_pre",
    # ── PRIMARY: sequence / duration ──
    "days_from_breakout_to_peak",
    "compression_days_pre",
    "days_from_first_compression_to_breakout",
    "days_from_first_abnormal_volume_to_breakout",
    "dryup_day_count_pre",
    "days_in_base",
    "atr_contraction_days_pre",
    # ── PRIMARY: EMA ribbon (computed from daily ema_spread_pct) ──
    "avg_ema_spread_pre",
    "min_ema_spread_pre",
    # ── PRIMARY: EMA ribbon episode aggregates ──
    "had_bull_stack_pre",
    "bull_stack_days_pre",
    "max_bull_stack_days_pre",
    "days_above_ema50_pre",
    "days_above_ema200_pre",
    "ema50_reclaim_count_pre",
    # ── SECONDARY: EMA position metrics ──
    "avg_close_vs_ema50_pct_pre",
    "avg_close_vs_ema200_pct_pre",
    # ── PRIMARY: structure / wyckoff ──
    "had_accumulation_like",
    "accumulation_like_day_count",
    "had_spring_test_lps",
    "reclaim_bar_count_pre",
    # ── SECONDARY: structure quality ──
    "had_breakout_retest",
    "retest_count",
    "avg_retest_quality",
    # ── SECONDARY: volume / context ──
    "max_volume_anomaly_pre",
    "median_volume_anomaly_pre",
    "abnormal_volume_day_count_pre",
    "extreme_anomaly_day_count_pre",
    "max_dollar_volume_pre",
    "median_dollar_volume_pre",
    # ── SECONDARY: candle / bar patterns ──
    "bullish_engulfing_count_pre",
    "expansion_bar_count_pre",
    "strong_close_count_pre",
    "wide_range_bar_count_pre",
    # ── LOW_SIGNAL: raw candle anatomy + binary / always-on ──
    "had_compression",
    "avg_body_pct_pre",
    "avg_upper_wick_pct_pre",
    "avg_lower_wick_pct_pre",
    "bearish_engulfing_count_pre",
    "inside_bar_count_pre",
    "outside_bar_count_pre",
    # ── SECONDARY: split / corporate action context ──
    "has_split_near_episode",
    "has_reverse_split_near_episode",
    "split_event_count",
    "reverse_split_event_count",
    "nearest_split_ratio",
    "nearest_split_days_from_breakout",
    "reverse_split_0_5d_before_breakout",
    "reverse_split_6_15d_before_breakout",
    "reverse_split_16_30d_before_breakout",
    "reverse_split_31_60d_before_breakout",
    "split_during_pump_window",
    "split_after_peak_30d",
    "split_artifact_risk",
    # ── PRIMARY: Scanner v2 / NP structure phase ──
    "had_confirmed_structure_pre",
    "had_triggered_structure_pre",
    "max_structure_score_pre",
    "avg_structure_score_pre",
    "had_accumulation_ready_pre",
    "had_overheated_expansion_pre",
    "high_expansion_risk_day_count_pre",
    "had_d6_beup_pre",
    "had_d4_beup_pre",
    "d_confluence_day_count_pre",
    "had_np_buy_candidate_pre",
    "buy_candidate_day_count_pre",
    # ── SECONDARY: structure detail ──
    "had_early_structure_pre",
    "had_setup_phase_pre",
    "had_impulse_only_pre",
    "had_degraded_pre",
    "had_expansion_start_pre",
    "had_d_confluence_pre",
    "had_core_d_beup_pre",
    "had_core_d_l34_pre",
    "had_l34_then_d4_3b_pre",
    "had_d4_then_beup_5b_pre",
    "had_d3_beup_pre",
    "had_d3_beup_toxic_pre",
    "had_np_watch_pre",
    "had_np_avoid_pre",
    "watch_day_count_pre",
    "avoid_day_count_pre",
    "max_np_structure_score_pre",
    "had_late_confirm_sequence_pre",
    "had_expansion_risk_flag_pre",
    "had_setup_only_l34_mid_avoid_pre",
    # ── PRIMARY: Demand Scanner at breakout ──
    "had_prime_buy_pre",
    "had_ats_prime_pre",
    "demand_prime_at_breakout",
    "demand_high_at_breakout",
    "demand_watch_or_better_at_breakout",
    "ats_prime_at_breakout",
    "ats_setup_or_better_at_breakout",
    "split_capped_demand_at_breakout",
    "illiquidity_capped_demand_at_breakout",
    # ── SECONDARY: Demand Scanner numeric scores ──
    "demand_score_at_breakout",
    "ats_score_at_breakout",
    "readiness_at_breakout",
]

# Priority tier for each feature.  Used to populate stats_json["priority"]
# and to drive UI badge rendering.  Post-factum outcome labels are NOT in
# _COMPARISON_FEATURES — they must never be treated as early signals.
_FEATURE_PRIORITY: dict[str, str] = {
    # PRIMARY — New Pump signal separators
    "had_valid_recent_setup":                      "PRIMARY",
    "had_valid_recent_trigger":                    "PRIMARY",
    "had_valid_recent_confirm":                    "PRIMARY",
    "had_valid_full_sequence":                     "PRIMARY",
    "best_new_pump_label_rank":                    "PRIMARY",
    "days_from_last_setup_to_breakout":            "PRIMARY",
    "days_from_last_trigger_to_breakout":          "PRIMARY",
    "days_from_g4_to_b2":                          "PRIMARY",
    # PRIMARY — NP count-based aggregates
    "l34_count_pre":                               "PRIMARY",
    "fri34_count_pre":                             "PRIMARY",
    "g4_count_pre":                                "PRIMARY",
    "b2_count_pre":                                "PRIMARY",
    "isolated_g4_count_pre":                       "PRIMARY",
    "isolated_b2_count_pre":                       "PRIMARY",
    "full_fri34_g4_b2_count_pre":                  "PRIMARY",
    "valid_setup_days_pre":                        "PRIMARY",
    "valid_full_sequence_days_pre":                "PRIMARY",
    # SECONDARY — NP count details
    "setup_only_l34_count_pre":                    "SECONDARY",
    "setup_only_fri34_count_pre":                  "SECONDARY",
    "trigger_after_l34_count_pre":                 "SECONDARY",
    "trigger_after_fri34_count_pre":               "SECONDARY",
    "full_l34_g4_b2_count_pre":                    "SECONDARY",
    "confirm_after_g4_count_pre":                  "SECONDARY",
    "valid_trigger_days_pre":                      "SECONDARY",
    "valid_confirm_days_pre":                      "SECONDARY",
    # PRIMARY — core sequence/duration separators
    "days_from_breakout_to_peak":                  "PRIMARY",
    "compression_days_pre":                        "PRIMARY",
    "days_from_first_compression_to_breakout":     "PRIMARY",
    "days_from_first_abnormal_volume_to_breakout": "PRIMARY",
    "dryup_day_count_pre":                         "PRIMARY",
    "days_in_base":                                "PRIMARY",
    "atr_contraction_days_pre":                    "PRIMARY",
    # PRIMARY — EMA ribbon compression
    "avg_ema_spread_pre":                          "PRIMARY",
    "min_ema_spread_pre":                          "PRIMARY",
    # PRIMARY — EMA ribbon episode aggregates
    "had_bull_stack_pre":                          "PRIMARY",
    "bull_stack_days_pre":                         "PRIMARY",
    "max_bull_stack_days_pre":                     "PRIMARY",
    "days_above_ema50_pre":                        "PRIMARY",
    "days_above_ema200_pre":                       "PRIMARY",
    "ema50_reclaim_count_pre":                     "PRIMARY",
    # SECONDARY — EMA position metrics
    "avg_close_vs_ema50_pct_pre":                  "SECONDARY",
    "avg_close_vs_ema200_pct_pre":                 "SECONDARY",
    # PRIMARY — structure depth
    "had_accumulation_like":                       "PRIMARY",
    "accumulation_like_day_count":                 "PRIMARY",
    "had_spring_test_lps":                         "PRIMARY",
    "reclaim_bar_count_pre":                       "PRIMARY",
    # SECONDARY — structure quality
    "had_breakout_retest":                         "SECONDARY",
    "retest_count":                                "SECONDARY",
    "avg_retest_quality":                          "SECONDARY",
    # SECONDARY — volume / context
    "max_volume_anomaly_pre":                      "SECONDARY",
    "median_volume_anomaly_pre":                   "SECONDARY",
    "abnormal_volume_day_count_pre":               "SECONDARY",
    "extreme_anomaly_day_count_pre":               "SECONDARY",
    "max_dollar_volume_pre":                       "SECONDARY",
    "median_dollar_volume_pre":                    "SECONDARY",
    # SECONDARY — candle patterns
    "bullish_engulfing_count_pre":                 "SECONDARY",
    "expansion_bar_count_pre":                     "SECONDARY",
    "strong_close_count_pre":                      "SECONDARY",
    "wide_range_bar_count_pre":                    "SECONDARY",
    # LOW_SIGNAL — noisy, always-on, or weak discriminators
    "had_compression":                             "LOW_SIGNAL",
    "avg_body_pct_pre":                            "LOW_SIGNAL",
    "avg_upper_wick_pct_pre":                      "LOW_SIGNAL",
    "avg_lower_wick_pct_pre":                      "LOW_SIGNAL",
    "bearish_engulfing_count_pre":                 "LOW_SIGNAL",
    "inside_bar_count_pre":                        "LOW_SIGNAL",
    "outside_bar_count_pre":                       "LOW_SIGNAL",
    # SECONDARY — split context
    "has_split_near_episode":               "SECONDARY",
    "has_reverse_split_near_episode":       "SECONDARY",
    "split_event_count":                    "SECONDARY",
    "reverse_split_event_count":            "SECONDARY",
    "nearest_split_ratio":                  "SECONDARY",
    "nearest_split_days_from_breakout":     "SECONDARY",
    "reverse_split_0_5d_before_breakout":   "SECONDARY",
    "reverse_split_6_15d_before_breakout":  "SECONDARY",
    "reverse_split_16_30d_before_breakout": "SECONDARY",
    "reverse_split_31_60d_before_breakout": "SECONDARY",
    "split_during_pump_window":             "SECONDARY",
    "split_after_peak_30d":                "SECONDARY",
    "split_artifact_risk":                  "SECONDARY",
    # PRIMARY — structure phase
    "had_confirmed_structure_pre":         "PRIMARY",
    "had_triggered_structure_pre":         "PRIMARY",
    "max_structure_score_pre":             "PRIMARY",
    "avg_structure_score_pre":             "PRIMARY",
    "had_accumulation_ready_pre":          "PRIMARY",
    "had_overheated_expansion_pre":        "PRIMARY",
    "high_expansion_risk_day_count_pre":   "PRIMARY",
    "had_d6_beup_pre":                     "PRIMARY",
    "had_d4_beup_pre":                     "PRIMARY",
    "d_confluence_day_count_pre":          "PRIMARY",
    "had_np_buy_candidate_pre":            "PRIMARY",
    "buy_candidate_day_count_pre":         "PRIMARY",
    # SECONDARY — structure detail
    "had_early_structure_pre":             "SECONDARY",
    "had_setup_phase_pre":                 "SECONDARY",
    "had_impulse_only_pre":                "SECONDARY",
    "had_degraded_pre":                    "SECONDARY",
    "had_expansion_start_pre":             "SECONDARY",
    "had_d_confluence_pre":                "SECONDARY",
    "had_core_d_beup_pre":                 "SECONDARY",
    "had_core_d_l34_pre":                  "SECONDARY",
    "had_l34_then_d4_3b_pre":              "SECONDARY",
    "had_d4_then_beup_5b_pre":             "SECONDARY",
    "had_d3_beup_pre":                     "SECONDARY",
    "had_d3_beup_toxic_pre":               "SECONDARY",
    "had_np_watch_pre":                    "SECONDARY",
    "had_np_avoid_pre":                    "SECONDARY",
    "watch_day_count_pre":                 "SECONDARY",
    "avoid_day_count_pre":                 "SECONDARY",
    "max_np_structure_score_pre":          "SECONDARY",
    "had_late_confirm_sequence_pre":       "SECONDARY",
    "had_expansion_risk_flag_pre":         "SECONDARY",
    "had_setup_only_l34_mid_avoid_pre":    "SECONDARY",
}

# Binary features where always_on_flag is meaningful
_BINARY_FEATURES = {
    "had_compression", "had_accumulation_like",
    "had_spring_test_lps", "had_breakout_retest",
    "had_bull_stack_pre",
    "had_valid_recent_setup", "had_valid_recent_trigger",
    "had_valid_recent_confirm", "had_valid_full_sequence",
    "has_split_near_episode", "has_reverse_split_near_episode",
    "reverse_split_0_5d_before_breakout", "reverse_split_6_15d_before_breakout",
    "reverse_split_16_30d_before_breakout", "reverse_split_31_60d_before_breakout",
    "split_during_pump_window", "split_after_peak_30d", "split_artifact_risk",
    "had_confirmed_structure_pre", "had_triggered_structure_pre",
    "had_early_structure_pre", "had_setup_phase_pre",
    "had_impulse_only_pre", "had_degraded_pre",
    "had_accumulation_ready_pre", "had_expansion_start_pre",
    "had_overheated_expansion_pre",
    "had_d_confluence_pre", "had_core_d_beup_pre", "had_core_d_l34_pre",
    "had_d6_beup_pre", "had_d4_beup_pre", "had_d3_beup_pre",
    "had_l34_then_d4_3b_pre", "had_d4_then_beup_5b_pre", "had_d3_beup_toxic_pre",
    "had_np_buy_candidate_pre", "had_np_watch_pre", "had_np_avoid_pre",
    "had_late_confirm_sequence_pre", "had_expansion_risk_flag_pre",
    "had_setup_only_l34_mid_avoid_pre",
    # Demand Scanner booleans — NULL treated as False in aggregation
    "had_prime_buy_pre", "had_ats_prime_pre",
    "demand_prime_at_breakout", "demand_high_at_breakout",
    "demand_watch_or_better_at_breakout",
    "ats_prime_at_breakout", "ats_setup_or_better_at_breakout",
    "split_capped_demand_at_breakout", "illiquidity_capped_demand_at_breakout",
}

_COMPARISON_GROUPS = ["4x_pump", "normal_winner", "false_positive", "missed_mover"]


# ── Split context helpers ─────────────────────────────────────────────────────

_SPLIT_CONTEXT_PRIORITY = [
    "SPLIT_ARTIFACT_RISK",
    "SPLIT_DURING_PUMP",
    "RECENT_REVERSE_SPLIT",
    "OLD_REVERSE_SPLIT",
    "FORWARD_SPLIT",
    "NO_SPLIT",
]


def _classify_split_context(
    episode_splits: list[dict],
    pump_start_date: Optional[str],
    pump_peak_date:  Optional[str],
    breakout_date:   Optional[str],
    split_artifact_risk: bool,
) -> str:
    if not episode_splits:
        return "NO_SPLIT"
    if split_artifact_risk:
        return "SPLIT_ARTIFACT_RISK"
    has_during_pump = any(
        s.get("split_type") in ("REVERSE_SPLIT", "FORWARD_SPLIT")
        and pump_start_date and pump_peak_date
        and pump_start_date <= (s.get("execution_date") or "") <= pump_peak_date
        for s in episode_splits
    )
    if has_during_pump:
        return "SPLIT_DURING_PUMP"
    if breakout_date:
        for s in episode_splits:
            if s.get("split_type") != "REVERSE_SPLIT":
                continue
            ed = s.get("execution_date") or ""
            d = (date.fromisoformat(breakout_date) - date.fromisoformat(ed)).days if ed else None
            if d is not None and 0 <= d <= 30:
                return "RECENT_REVERSE_SPLIT"
            if d is not None and 31 <= d <= 90:
                return "OLD_REVERSE_SPLIT"
    has_forward = any(s.get("split_type") == "FORWARD_SPLIT" for s in episode_splits)
    if has_forward:
        return "FORWARD_SPLIT"
    has_reverse = any(s.get("split_type") == "REVERSE_SPLIT" for s in episode_splits)
    if has_reverse:
        return "OLD_REVERSE_SPLIT"
    return "NO_SPLIT"


async def build_raw_pattern_episode_features_splits(
    raw_run_id: int,
    pump_study_run_id: int,
) -> int:
    """
    Phase 2B-8: fetch split/corporate-action history for each episode symbol,
    compute split context and artifact-risk fields, and patch episode feature rows.

    Fields populated:
        has_split_near_episode, has_reverse_split_near_episode,
        has_forward_split_near_episode, split_event_count,
        reverse_split_event_count, forward_split_event_count,
        nearest_split_date, nearest_split_type, nearest_split_ratio,
        nearest_split_days_from_breakout, nearest_split_days_from_pump_start,
        nearest_split_days_from_peak,
        reverse_split_0_5d_before_breakout, reverse_split_6_15d_before_breakout,
        reverse_split_16_30d_before_breakout, reverse_split_31_60d_before_breakout,
        reverse_split_after_breakout, split_during_pump_window, split_after_peak_30d,
        split_context, split_artifact_risk, split_artifact_reason,
        split_adjusted_move_estimate, raw_move_pct
    """
    from database import (
        get_pump_episodes,
        get_raw_pattern_daily_features,
        get_pump_episode_events,
        get_stock_splits_for_symbols,
        update_raw_pattern_episode_features,
    )
    from scanner.massive_reference import fetch_and_cache_splits_batch

    episodes = await get_pump_episodes(pump_study_run_id, limit=10_000)
    if not episodes:
        return 0

    # ── Compute per-episode date windows ──────────────────────────────────────
    # window = [earliest PRE date - 90d,  latest POST date + 30d]
    ep_windows: dict[int, tuple[str, str]] = {}
    ep_breakout: dict[int, Optional[str]] = {}
    for ep in episodes:
        eid = ep["id"]
        daily = await get_raw_pattern_daily_features(raw_run_id, episode_id=eid, limit=2000)
        if not daily:
            continue
        all_dates = sorted(r.get("date") or "" for r in daily if r.get("date"))
        if not all_dates:
            continue
        win_start = (date.fromisoformat(all_dates[0]) - timedelta(days=90)).isoformat()
        win_end   = (date.fromisoformat(all_dates[-1]) + timedelta(days=30)).isoformat()
        ep_windows[eid] = (win_start, win_end)

        # breakout date from events
        evs = await get_pump_episode_events(eid)
        breakout_date: Optional[str] = None
        for ev in evs:
            if ev.get("event_type") == "breakout_day" and breakout_date is None:
                breakout_date = str(ev["event_date"]) if ev.get("event_date") else None
        ep_breakout[eid] = breakout_date

    # ── Batch-fetch splits for all symbols in widest combined window ──────────
    symbol_to_ep: dict[str, list[int]] = {}
    for ep in episodes:
        eid = ep["id"]
        if eid not in ep_windows:
            continue
        sym = (ep.get("symbol") or "").upper()
        symbol_to_ep.setdefault(sym, []).append(eid)

    # Compute widest window per symbol
    symbol_windows: dict[str, tuple[str, str]] = {}
    for sym, eids in symbol_to_ep.items():
        all_starts = [ep_windows[e][0] for e in eids if e in ep_windows]
        all_ends   = [ep_windows[e][1] for e in eids if e in ep_windows]
        if not all_starts:
            continue
        symbol_windows[sym] = (min(all_starts), max(all_ends))

    # Fetch and cache splits; fall back to DB cache if API fails
    global_since = min(v[0] for v in symbol_windows.values()) if symbol_windows else date.today().isoformat()
    global_until = max(v[1] for v in symbol_windows.values()) if symbol_windows else date.today().isoformat()

    try:
        cached_splits = await fetch_and_cache_splits_batch(
            list(symbol_windows.keys()), since=global_since, until=global_until
        )
    except Exception:
        cached_splits = {}

    # Fallback: read from DB for any symbols not fetched
    missing = [s for s in symbol_windows if s not in cached_splits or not cached_splits[s]]
    if missing:
        try:
            db_splits = await get_stock_splits_for_symbols(missing, since=global_since, until=global_until)
            for sym, rows in db_splits.items():
                if rows:
                    cached_splits[sym] = rows
        except Exception:
            pass

    # ── Patch each episode ────────────────────────────────────────────────────
    patched = 0
    ep_by_id = {ep["id"]: ep for ep in episodes}

    for eid, (win_start, win_end) in ep_windows.items():
        ep        = ep_by_id.get(eid)
        if not ep:
            continue
        sym       = (ep.get("symbol") or "").upper()
        all_splits = cached_splits.get(sym, [])

        # Filter to this episode's window
        ep_splits = [
            s for s in all_splits
            if win_start <= (s.get("execution_date") or "") <= win_end
        ]

        pump_start = ep.get("pump_start_date") or ""
        pump_peak  = ep.get("pump_peak_date")  or ""
        breakout   = ep_breakout.get(eid)
        pump_mult  = ep.get("pump_multiple") or 1.0

        # Counts
        rev_splits = [s for s in ep_splits if s.get("split_type") == "REVERSE_SPLIT"]
        fwd_splits = [s for s in ep_splits if s.get("split_type") == "FORWARD_SPLIT"]

        # Nearest split (by proximity to breakout, else pump_start)
        ref_date = breakout or pump_start
        nearest: Optional[dict] = None
        if ep_splits and ref_date:
            def _dist(s: dict) -> int:
                ed = s.get("execution_date") or ""
                try:
                    return abs((date.fromisoformat(ref_date) - date.fromisoformat(ed)).days)
                except Exception:
                    return 9999
            nearest = min(ep_splits, key=_dist)
        elif ep_splits:
            nearest = ep_splits[-1]

        nearest_date  = nearest["execution_date"] if nearest else None
        nearest_type  = nearest.get("split_type") if nearest else None
        nearest_ratio = nearest.get("ratio") if nearest else None

        def _delta(d1: Optional[str], d2: Optional[str]) -> Optional[int]:
            if not d1 or not d2:
                return None
            try:
                return (date.fromisoformat(d2) - date.fromisoformat(d1)).days
            except Exception:
                return None

        nd_from_breakout    = _delta(nearest_date, breakout)    if nearest_date else None
        nd_from_pump_start  = _delta(nearest_date, pump_start)  if nearest_date else None
        nd_from_peak        = _delta(nearest_date, pump_peak)   if nearest_date else None

        # Reverse-split timing buckets (days_before_breakout = positive means before breakout)
        rs_0_5   = any(
            breakout and (0 <= (_delta(s["execution_date"], breakout) or -1) <= 5)
            for s in rev_splits if s.get("execution_date")
        )
        rs_6_15  = any(
            breakout and (6 <= (_delta(s["execution_date"], breakout) or -1) <= 15)
            for s in rev_splits if s.get("execution_date")
        )
        rs_16_30 = any(
            breakout and (16 <= (_delta(s["execution_date"], breakout) or -1) <= 30)
            for s in rev_splits if s.get("execution_date")
        )
        rs_31_60 = any(
            breakout and (31 <= (_delta(s["execution_date"], breakout) or -1) <= 60)
            for s in rev_splits if s.get("execution_date")
        )
        rs_after = any(
            breakout and ((_delta(s["execution_date"], breakout) or 1) < 0)
            for s in rev_splits if s.get("execution_date")
        )
        split_during = any(
            pump_start and pump_peak
            and pump_start <= (s.get("execution_date") or "") <= pump_peak
            for s in ep_splits
        )
        split_after_30 = any(
            pump_peak and ((_delta(pump_peak, s["execution_date"]) or -1) >= 0)
            and ((_delta(pump_peak, s["execution_date"]) or -1) <= 30)
            for s in ep_splits if s.get("execution_date")
        )

        # Artifact risk: reverse split within ±2 days of pump window AND ratio ≈ pump_multiple
        artifact_risk   = False
        artifact_reason = None
        for rs in rev_splits:
            ed    = rs.get("execution_date") or ""
            ratio = rs.get("ratio") or 1.0
            adj   = rs.get("adjustment_factor") or ratio
            # price-adjustment = split_from/split_to; for 1-for-10 RS: adj=10
            price_jump_from_split = adj if adj > 1 else (1 / ratio if ratio < 1 else 1.0)
            in_window = (
                pump_start and pump_peak
                and (date.fromisoformat(pump_start) - timedelta(days=2)).isoformat() <= ed
                <= (date.fromisoformat(pump_peak) + timedelta(days=2)).isoformat()
            )
            ratio_match = price_jump_from_split > 1 and abs(price_jump_from_split - pump_mult) / pump_mult < 0.35
            if in_window and ratio_match:
                artifact_risk   = True
                artifact_reason = (
                    f"Reverse split {rs.get('split_from')}-for-{rs.get('split_to')} "
                    f"({price_jump_from_split:.1f}× price adjust) on {ed} within pump window "
                    f"matches observed {pump_mult:.1f}× move"
                )
                break
            if in_window and not ratio_match:
                artifact_risk   = True
                artifact_reason = (
                    f"Reverse split {rs.get('split_from')}-for-{rs.get('split_to')} on {ed} "
                    f"occurred inside pump window (pump={pump_mult:.1f}×, split adj={price_jump_from_split:.1f}×)"
                )

        raw_move  = round((pump_mult - 1) * 100, 1) if pump_mult else None
        adj_est   = None
        if artifact_risk and nearest_ratio and nearest_ratio < 1:
            price_jump = (1 / nearest_ratio)
            adj_est = round(raw_move / price_jump, 1) if raw_move else None

        split_ctx = _classify_split_context(ep_splits, pump_start, pump_peak, breakout, artifact_risk)

        patch = {
            "has_split_near_episode":           bool(ep_splits),
            "has_reverse_split_near_episode":   bool(rev_splits),
            "has_forward_split_near_episode":   bool(fwd_splits),
            "split_event_count":                len(ep_splits),
            "reverse_split_event_count":        len(rev_splits),
            "forward_split_event_count":        len(fwd_splits),
            "nearest_split_date":               nearest_date,
            "nearest_split_type":               nearest_type,
            "nearest_split_ratio":              nearest_ratio,
            "nearest_split_days_from_breakout": nd_from_breakout,
            "nearest_split_days_from_pump_start": nd_from_pump_start,
            "nearest_split_days_from_peak":     nd_from_peak,
            "reverse_split_0_5d_before_breakout":   rs_0_5,
            "reverse_split_6_15d_before_breakout":  rs_6_15,
            "reverse_split_16_30d_before_breakout":  rs_16_30,
            "reverse_split_31_60d_before_breakout":  rs_31_60,
            "reverse_split_after_breakout":         rs_after,
            "split_during_pump_window":             split_during,
            "split_after_peak_30d":                split_after_30,
            "split_context":                        split_ctx,
            "split_artifact_risk":                  artifact_risk,
            "split_artifact_reason":                artifact_reason,
            "split_adjusted_move_estimate":         adj_est,
            "raw_move_pct":                         raw_move,
        }
        await update_raw_pattern_episode_features(raw_run_id, eid, patch)
        patched += 1

    return patched


async def build_split_impact_analysis(run_id: int) -> dict:
    """
    Aggregate split-impact stats from completed raw_pattern_episode_features.

    Returns:
        performance_by_split_context: breakdown by split_context bucket
        performance_by_reverse_split_timing: breakdown by RS timing bucket
        split_artifact_candidates: list of high-risk episodes
        split_impact_summary: narrative findings
    """
    from database import get_raw_pattern_episode_features, get_raw_pattern_run, get_pump_episodes

    run = await get_raw_pattern_run(run_id)
    if not run:
        raise ValueError(f"Raw pattern run {run_id} not found")
    if run.get("status") != "complete":
        raise ValueError(f"Run {run_id} not complete")

    episodes = await get_raw_pattern_episode_features(run_id, limit=5000)
    ps_run_id = run.get("pump_study_run_id")

    # Load pump episode performance data (pump_multiple, return_pct, days_to_peak)
    pump_eps: dict[int, dict] = {}
    if ps_run_id:
        try:
            raw_pump = await get_pump_episodes(ps_run_id, limit=10_000)
            pump_eps = {ep["id"]: ep for ep in raw_pump}
        except Exception:
            pass

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _group_stats(group: list[dict]) -> dict:
        count = len(group)
        if count == 0:
            return {"episode_count": 0}
        g4     = sum(1 for e in group if e.get("group_type") == "4x_pump")
        nw     = sum(1 for e in group if e.get("group_type") == "normal_winner")
        fp     = sum(1 for e in group if e.get("group_type") == "false_positive")
        mm     = sum(1 for e in group if e.get("group_type") == "missed_mover")
        total_classified = g4 + nw + fp + mm
        fp_rate = round(fp / total_classified, 3) if total_classified else None

        returns = [
            pump_eps[e["episode_id"]].get("pump_return_pct")
            for e in group
            if e.get("episode_id") and e["episode_id"] in pump_eps
            and pump_eps[e["episode_id"]].get("pump_return_pct") is not None
        ]
        days_list = [
            pump_eps[e["episode_id"]].get("days_to_peak")
            for e in group
            if e.get("episode_id") and e["episode_id"] in pump_eps
            and pump_eps[e["episode_id"]].get("days_to_peak") is not None
        ]
        avg_ret  = round(sum(returns) / len(returns), 1)  if returns  else None
        med_ret  = round(sorted(returns)[len(returns) // 2], 1) if returns else None
        avg_days = round(sum(days_list) / len(days_list), 1) if days_list else None

        return {
            "episode_count":     count,
            "4x_pump_count":     g4,
            "normal_winner_count": nw,
            "false_positive_count": fp,
            "missed_mover_count":  mm,
            "false_positive_rate": fp_rate,
            "avg_pump_return_pct": avg_ret,
            "median_pump_return_pct": med_ret,
            "avg_days_to_peak":    avg_days,
        }

    # ── performance_by_split_context ─────────────────────────────────────────
    ctx_groups: dict[str, list[dict]] = {}
    for e in episodes:
        ctx = e.get("split_context") or "NO_SPLIT"
        ctx_groups.setdefault(ctx, []).append(e)

    perf_by_ctx = {}
    for ctx in ["NO_SPLIT", "RECENT_REVERSE_SPLIT", "OLD_REVERSE_SPLIT",
                "FORWARD_SPLIT", "SPLIT_DURING_PUMP", "SPLIT_ARTIFACT_RISK"]:
        perf_by_ctx[ctx] = _group_stats(ctx_groups.get(ctx, []))

    # ── performance_by_reverse_split_timing ──────────────────────────────────
    def _timing_bucket(e: dict) -> str:
        if e.get("reverse_split_0_5d_before_breakout"):   return "RS_0_5D_BEFORE_BREAKOUT"
        if e.get("reverse_split_6_15d_before_breakout"):  return "RS_6_15D_BEFORE_BREAKOUT"
        if e.get("reverse_split_16_30d_before_breakout"): return "RS_16_30D_BEFORE_BREAKOUT"
        if e.get("reverse_split_31_60d_before_breakout"): return "RS_31_60D_BEFORE_BREAKOUT"
        if e.get("reverse_split_after_breakout"):          return "RS_AFTER_BREAKOUT"
        if e.get("split_during_pump_window") and e.get("has_reverse_split_near_episode"): return "RS_DURING_PUMP"
        return "NO_REVERSE_SPLIT"

    timing_groups: dict[str, list[dict]] = {}
    for e in episodes:
        bkt = _timing_bucket(e)
        timing_groups.setdefault(bkt, []).append(e)

    perf_by_timing = {}
    for bkt in ["NO_REVERSE_SPLIT", "RS_0_5D_BEFORE_BREAKOUT", "RS_6_15D_BEFORE_BREAKOUT",
                "RS_16_30D_BEFORE_BREAKOUT", "RS_31_60D_BEFORE_BREAKOUT",
                "RS_AFTER_BREAKOUT", "RS_DURING_PUMP"]:
        perf_by_timing[bkt] = _group_stats(timing_groups.get(bkt, []))

    # ── split_artifact_candidates ─────────────────────────────────────────────
    artifacts = [e for e in episodes if e.get("split_artifact_risk")]
    artifact_candidates = []
    for e in sorted(artifacts, key=lambda x: -(x.get("raw_move_pct") or 0))[:30]:
        pep = pump_eps.get(e.get("episode_id") or -1) or {}
        artifact_candidates.append({
            "symbol":                    e.get("symbol"),
            "group_type":                e.get("group_type"),
            "pump_start":                pep.get("pump_start_date"),
            "peak_date":                 pep.get("pump_peak_date"),
            "raw_move_pct":              e.get("raw_move_pct"),
            "split_date":                e.get("nearest_split_date"),
            "split_type":                e.get("nearest_split_type"),
            "split_ratio":               e.get("nearest_split_ratio"),
            "split_artifact_reason":     e.get("split_artifact_reason"),
            "split_adjusted_move_estimate": e.get("split_adjusted_move_estimate"),
        })

    # ── split_impact_summary ──────────────────────────────────────────────────
    total = len(episodes)
    total_4x  = sum(1 for e in episodes if e.get("group_type") == "4x_pump")
    total_fp  = sum(1 for e in episodes if e.get("group_type") == "false_positive")

    rs_4x     = sum(1 for e in episodes if e.get("has_reverse_split_near_episode") and e.get("group_type") == "4x_pump")
    rs_fp     = sum(1 for e in episodes if e.get("has_reverse_split_near_episode") and e.get("group_type") == "false_positive")
    artifacts_total = sum(1 for e in episodes if e.get("split_artifact_risk"))
    rs_overrep = (rs_fp / total_fp > rs_4x / total_4x * 1.5) if total_4x > 0 and total_fp > 0 else False

    summary_lines = [
        f"Total episodes: {total} | 4x_pump: {total_4x} | false_positive: {total_fp}",
        f"Reverse split near episode: {rs_4x}/{total_4x} 4x_pumps, {rs_fp}/{total_fp} false_positives",
        f"Split artifact risk: {artifacts_total} episodes flagged",
        f"RS overrepresented in false_positives vs 4x_pumps: {'YES' if rs_overrep else 'NO'}",
    ]
    if len(ctx_groups.get("RECENT_REVERSE_SPLIT", [])) > 0:
        rs_rec = ctx_groups["RECENT_REVERSE_SPLIT"]
        rs_rec_fp_rate = perf_by_ctx["RECENT_REVERSE_SPLIT"].get("false_positive_rate")
        summary_lines.append(
            f"Recent RS (0-30d before breakout): {len(rs_rec)} episodes, "
            f"fp_rate={rs_rec_fp_rate}" if rs_rec_fp_rate is not None else
            f"Recent RS (0-30d before breakout): {len(rs_rec)} episodes"
        )
    scanner_v2_recs = []
    if rs_overrep:
        scanner_v2_recs.append({
            "suggested_flag": "reverse_split_risk",
            "suggested_score_delta": -15,
            "evidence": f"RS {rs_fp}/{total_fp} ({100*rs_fp//total_fp if total_fp else 0}%) in false_positives vs {rs_4x}/{total_4x} ({100*rs_4x//total_4x if total_4x else 0}%) in 4x_pumps",
            "sample_size": total,
            "confidence": "MEDIUM" if total > 50 else "LOW",
        })
    if artifacts_total > 0:
        scanner_v2_recs.append({
            "suggested_flag": "split_artifact_exclusion",
            "suggested_score_delta": None,
            "evidence": f"{artifacts_total} episodes flagged as potential split artifacts — exclude from calibration",
            "sample_size": artifacts_total,
            "confidence": "HIGH" if artifacts_total > 5 else "MEDIUM",
        })

    return {
        "ok":          True,
        "run_id":      run_id,
        "total_episodes": total,
        "performance_by_split_context":       perf_by_ctx,
        "performance_by_reverse_split_timing": perf_by_timing,
        "split_artifact_candidates":          artifact_candidates,
        "split_impact_summary":               summary_lines,
        "scanner_v2_split_patch_recommendations": scanner_v2_recs,
    }


# ── Structure phase rank maps ─────────────────────────────────────────────────

_STRUCTURE_PHASE_RANK = {
    "CONFIRMED_STRUCTURE": 0,
    "TRIGGERED_STRUCTURE": 1,
    "EARLY_STRUCTURE":     2,
    "SETUP_PHASE":         3,
    "IMPULSE_ONLY":        4,
    "DEGRADED":            5,
    "BROKEN_STRUCTURE":    6,
    "UNKNOWN":             7,
    "NONE":                8,
}

_EXPANSION_RISK_RANK = {"HIGH": 0, "MEDIUM": 1, "LOW": 2, "UNKNOWN": 3, "NONE": 4}

_D_BEST_TYPE_RANK = {
    "D6_BEUP":                0,
    "D1_BEUP":                1,   # R35 +6.45% 5d 85.7% WR
    "L34_THEN_D4_3B":         2,
    "D4_BEUP":                3,
    "D4_L34":                 4,
    "D11_L34":                5,   # R35 +4.87% 5d 56.5% WR
    "D3_L34":                 6,
    "D4_THEN_BEUP_5B":        7,
    "D3_BEUP":                8,
    "D6_L34":                 9,
    "D11_BEUP":               10,
    "D9_BEUP":                11,
    "D1_L34":                 12,
    "D9_L34":                 13,
    "D1_L43":                 14,
    "D11_L43":                15,
    "D9_L43":                 16,
    "SECONDARY_D_CONFLUENCE": 17,
    "NONE":                   18,
}


def _build_demand_result_from_snapshot(
    snap: dict,
    feature_json: dict | None,
    ep: dict,
) -> tuple[dict, list[str]]:
    """
    Reconstruct a demand-scorer-compatible result dict from a pump study snapshot
    + optional feature_json from raw_pattern_daily_features.
    Returns (result_dict, missing_inputs_list).
    """
    sj       = snap.get("snapshot") or {} if snap else {}
    np_data  = sj.get("new_pump") or {}
    fj       = feature_json or {}
    missing  = []

    result: dict = {
        "price":                        snap.get("close") if snap else None,
        "compression_expansion_state":  np_data.get("compression_expansion_state"),
        "new_pump_label":               np_data.get("decision"),
        "decision":                     np_data.get("decision"),
        "expansion_timing_risk":        np_data.get("expansion_timing_risk"),
        "fake_trigger_risk":            np_data.get("fake_trigger_risk"),
        "scanner_v2_decision":          np_data.get("decision"),  # best proxy
        # D-WLNBB / custom flags from feature_json
        "l34_wlnbb":           fj.get("l34_wlnbb"),
        "l43_wlnbb":           fj.get("l43_wlnbb"),
        "l64_wlnbb":           fj.get("l64_wlnbb"),
        "d6_beup":             fj.get("d6_beup"),
        "d4_beup":             fj.get("d4_beup"),
        "d3_beup":             fj.get("d3_beup"),
        "core_d_beup":         fj.get("core_d_beup"),
        "core_d_l34":          fj.get("core_d_l34"),
        "d4_l34":              fj.get("d4_l34"),
        "d3_l34":              fj.get("d3_l34"),
        "has_l34_np_ld":       fj.get("has_l34_np_ld"),
        "has_wc_gap_ld":       fj.get("has_wc_gap_ld"),
        "has_triple_d_l34_beup": fj.get("has_triple_d_l34_beup"),
        # Context fields not available from historical snapshots — scorer handles None
        "sector_context":      None,
        "macro_context":       None,
        "news_hype_context":   None,
        "sympathy_context":    None,
    }

    if not snap:
        missing.append("no_snapshot")
    if not feature_json:
        missing += ["l34_wlnbb", "d6_beup", "has_l34_np_ld", "has_wc_gap_ld"]
    if result.get("compression_expansion_state") is None:
        missing.append("compression_expansion_state")

    return result, missing


async def build_raw_pattern_episode_features_structural_v2(
    raw_run_id: int,
    pump_study_run_id: int,
    lookback_days: int = 200,
) -> int:
    """
    Phase 2B-7: Extract Scanner v2 / NP structural fields from PRE-window
    pump_episode_snapshots.new_pump and per-day D/WLNBB confluence computation.

    Structure fields: from snapshot.new_pump (structure_phase, structure_score,
        compression_expansion_state, expansion_timing_risk, decision, decision_flags)
    D/WLNBB fields: computed per PRE day via compute_d_wlnbb_confluence on
        fetched candle history.

    Returns number of episodes patched.
    """
    from database import (
        get_pump_episodes,
        get_raw_pattern_daily_features,
        get_run_snapshots,
        get_pump_episode_events,
        update_raw_pattern_episode_features,
    )

    try:
        from scanner.manual_d_wlnbb_features import compute_d_wlnbb_confluence
        _dw_available = True
    except ImportError:
        _dw_available = False
        logger.warning("[StructV2] manual_d_wlnbb_features not importable — D/WLNBB fields skipped")

    episodes = await get_pump_episodes(pump_study_run_id, limit=10_000)
    patched  = 0

    def _mode(vals: list) -> Optional[str]:
        """Most frequent non-None/NONE/UNKNOWN value."""
        from collections import Counter
        filtered = [v for v in vals if v and v not in ("NONE", "UNKNOWN")]
        if not filtered:
            return None
        return Counter(filtered).most_common(1)[0][0]

    def _mean_int(vals: list) -> Optional[float]:
        cleaned = [v for v in vals if v is not None]
        return round(sum(cleaned) / len(cleaned), 2) if cleaned else None

    for ep in episodes:
        episode_id = ep["id"]
        symbol     = (ep.get("symbol") or "").upper()
        pump_start = ep.get("pump_start_date")
        if not symbol or not pump_start:
            continue

        # ── Read PRE snapshots for structure / decision fields ────────────────
        pre_snaps = await get_run_snapshots(
            run_id=pump_study_run_id, episode_id=episode_id, phase="PRE"
        )

        structure_phases:  list[str]   = []
        structure_scores:  list[int]   = []
        ce_states:         list[str]   = []
        exp_risks:         list[str]   = []
        decisions:         list[str]   = []
        all_flags:         list[str]   = []

        for snap in pre_snaps:
            np = (snap.get("snapshot") or {}).get("new_pump") or {}
            sp  = np.get("structure_phase")
            ss  = np.get("structure_score")
            ce  = np.get("compression_expansion_state")
            er  = np.get("expansion_timing_risk")
            dec = np.get("decision")
            dfl = np.get("decision_flags") or []

            if sp:  structure_phases.append(sp)
            if ss is not None: structure_scores.append(ss)
            if ce:  ce_states.append(ce)
            if er:  exp_risks.append(er)
            if dec: decisions.append(dec)
            if isinstance(dfl, list):
                all_flags.extend(dfl)

        # Structure aggregates
        dom_sp   = _mode(structure_phases)
        best_sp  = None
        for phase_name, _ in sorted(_STRUCTURE_PHASE_RANK.items(), key=lambda x: x[1]):
            if phase_name in structure_phases:
                best_sp = phase_name
                break

        max_ss   = max(structure_scores)  if structure_scores else None
        avg_ss   = _mean_int(structure_scores)

        # Expansion risk — worst seen
        best_er  = None
        for er_name, _ in sorted(_EXPANSION_RISK_RANK.items(), key=lambda x: x[1]):
            if er_name in exp_risks:
                best_er = er_name
                break
        high_er_count = sum(1 for r in exp_risks if r == "HIGH")

        # Decision counts
        buy_count   = sum(1 for d in decisions if d and d.startswith("BUY_CANDIDATE"))
        watch_count = sum(1 for d in decisions if d and d.startswith("WATCH"))
        avoid_count = sum(1 for d in decisions if d and d.startswith("AVOID"))
        max_ss_in_buy = None
        if buy_count > 0:
            buy_indices = [i for i, d in enumerate(decisions) if d and d.startswith("BUY_CANDIDATE")]
            buy_scores  = [structure_scores[i] for i in buy_indices if i < len(structure_scores)]
            max_ss_in_buy = max(buy_scores) if buy_scores else None

        # ── D/WLNBB fields from candle re-fetch ──────────────────────────────
        d_types:    list[str] = []
        d_families: list[str] = []

        if _dw_available:
            try:
                start_fetch = str(date.fromisoformat(pump_start) - timedelta(days=lookback_days * 2))
            except (ValueError, TypeError):
                start_fetch = None

            if start_fetch:
                all_candles = await _fetch_candles_range(symbol, start_fetch, pump_start)
                if len(all_candles) >= 10:
                    # Build date index
                    candle_date_idx = {c["date"]: i for i, c in enumerate(all_candles) if c.get("date")}
                    sorted_pre = sorted(pre_snaps, key=lambda s: s.get("date") or "")

                    for snap in sorted_pre:
                        row_date = snap.get("date") or ""
                        cidx = candle_date_idx.get(row_date)
                        if cidx is None:
                            continue
                        window = all_candles[max(0, cidx - 199): cidx + 1]
                        if len(window) < 10:
                            continue
                        try:
                            dw = compute_d_wlnbb_confluence(window)
                        except Exception:
                            continue
                        dt = dw.get("d_confluence_type_v2") or dw.get("d_confluence_type") or "NONE"
                        df = dw.get("d_confluence_family") or "NONE"
                        if dt and dt != "NONE":
                            d_types.append(dt)
                        if df and df != "NONE":
                            d_families.append(df)

        # D/WLNBB aggregates
        dom_dt    = _mode(d_types)
        dom_df    = _mode(d_families)
        d_day_cnt = len(d_types)  # days with any confluence
        best_dt   = None
        for dtype, _ in sorted(_D_BEST_TYPE_RANK.items(), key=lambda x: x[1]):
            if dtype in d_types:
                best_dt = dtype
                break

        # ── Build patch dict ──────────────────────────────────────────────────
        patch = {
            # Structure
            "dominant_structure_phase_pre":      dom_sp,
            "best_structure_phase_pre":          best_sp,
            "max_structure_score_pre":           max_ss,
            "avg_structure_score_pre":           avg_ss,
            "had_confirmed_structure_pre":       "CONFIRMED_STRUCTURE" in structure_phases or None,
            "had_triggered_structure_pre":       "TRIGGERED_STRUCTURE" in structure_phases or None,
            "had_early_structure_pre":           "EARLY_STRUCTURE" in structure_phases or None,
            "had_setup_phase_pre":               "SETUP_PHASE" in structure_phases or None,
            "had_impulse_only_pre":              "IMPULSE_ONLY" in structure_phases or None,
            "had_degraded_pre":                  "DEGRADED" in structure_phases or None,
            # Compression / expansion
            "had_accumulation_ready_pre":        "ACCUMULATION_READY" in ce_states or None,
            "had_expansion_start_pre":           "EXPANSION_START" in ce_states or None,
            "had_overheated_expansion_pre":      "OVERHEATED_EXPANSION" in ce_states or None,
            "max_expansion_timing_risk_pre":     best_er,
            "high_expansion_risk_day_count_pre": high_er_count or None,
            # D/WLNBB
            "had_d_confluence_pre":              bool(d_types) or None,
            "had_core_d_beup_pre":               any("BEUP" in t for t in d_types) or None,
            "had_core_d_l34_pre":                any("L34" in t for t in d_types) or None,
            "had_d6_beup_pre":                   any(t in ("D6_BEUP", "D6_BEUP_SAME") for t in d_types) or None,
            "had_d4_beup_pre":                   any(t in ("D4_BEUP", "D4_BEUP_SAME") for t in d_types) or None,
            "had_d3_beup_pre":                   any(t in ("D3_BEUP", "D3_BEUP_SAME") for t in d_types) or None,
            "had_l34_then_d4_3b_pre":            "L34_THEN_D4_3B" in d_types or None,
            "had_d4_then_beup_5b_pre":           "D4_THEN_BEUP_5B" in d_types or None,
            "had_d3_beup_toxic_pre":             any(t in ("D3_BEUP", "D3_BEUP_SAME", "D3_THEN_BEUP_5B") for t in d_types) or None,
            "dominant_d_confluence_type_pre":    dom_dt,
            "dominant_d_confluence_family_pre":  dom_df,
            "d_confluence_day_count_pre":        d_day_cnt or None,
            "d_confluence_best_type_pre":        best_dt,
            # Decision / routing
            "had_np_buy_candidate_pre":          bool(buy_count) or None,
            "had_np_watch_pre":                  bool(watch_count) or None,
            "had_np_avoid_pre":                  bool(avoid_count) or None,
            "max_np_structure_score_pre":        max_ss_in_buy,
            "buy_candidate_day_count_pre":       buy_count or None,
            "watch_day_count_pre":               watch_count or None,
            "avoid_day_count_pre":               avoid_count or None,
            # Flags
            "had_late_confirm_sequence_pre":     bool(
                any(sp in ("CONFIRMED_STRUCTURE",) for sp in structure_phases)
                and "CONFIRM_AFTER_G4" in str(all_flags)
            ) or None,
            "had_expansion_risk_flag_pre":       (
                "expansion_timing_risk_high" in all_flags or "HIGH" in exp_risks
            ) or None,
            "had_setup_only_l34_mid_avoid_pre":  (
                "l34_setup_only_mid_score_avoid" in all_flags
            ) or None,
        }

        # Convert False booleans to None (keep True as True — meaningful signal)
        for k, v in patch.items():
            if v is False:
                patch[k] = None

        if any(v is not None for v in patch.values()):
            await update_raw_pattern_episode_features(raw_run_id, episode_id, patch)
            patched += 1

    return patched


async def build_raw_pattern_episode_features_ema(
    raw_run_id: int,
    pump_study_run_id: int,
) -> int:
    """
    Phase 2B-5: compute PRE-window EMA ribbon episode aggregates from
    raw_pattern_daily_features.feature_json and patch episode feature rows.

    Fields patched:
        had_bull_stack_pre, bull_stack_days_pre
        days_above_ema50_pre, days_above_ema200_pre
        ema50_reclaim_count_pre
        avg_close_vs_ema50_pct_pre, avg_close_vs_ema200_pct_pre

    Requires raw_pattern_daily_features to already have feature_json populated
    (from build_raw_pattern_daily_features Phase 2B-1).
    Returns the number of episodes patched.
    """
    from database import (
        get_pump_episodes,
        get_raw_pattern_daily_features,
        update_raw_pattern_episode_features,
    )

    def _mean(vals: list) -> Optional[float]:
        cleaned = [v for v in vals if v is not None]
        return round(sum(cleaned) / len(cleaned), 3) if cleaned else None

    episodes = await get_pump_episodes(pump_study_run_id, limit=10_000)
    patched  = 0

    for ep in episodes:
        episode_id = ep["id"]
        pre_rows = await get_raw_pattern_daily_features(
            raw_run_id, episode_id=episode_id, phase="PRE", limit=500
        )
        if not pre_rows:
            continue

        fjs = [r.get("feature_json") or {} for r in pre_rows]

        bull_stack_days     = sum(1 for fj in fjs if fj.get("bullish_stack"))
        days_above_ema50    = sum(1 for fj in fjs if fj.get("above_ema50"))
        days_above_ema200   = sum(1 for fj in fjs if fj.get("above_ema200"))
        ema50_reclaim_count = sum(1 for fj in fjs if fj.get("ema50_reclaim_day"))

        avg_vs_ema50  = _mean([fj.get("close_vs_ema50_pct")  for fj in fjs])
        avg_vs_ema200 = _mean([fj.get("close_vs_ema200_pct") for fj in fjs])

        await update_raw_pattern_episode_features(raw_run_id, episode_id, {
            "had_bull_stack_pre":          bool(bull_stack_days) or None,
            "bull_stack_days_pre":         bull_stack_days     or None,
            "days_above_ema50_pre":        days_above_ema50    or None,
            "days_above_ema200_pre":       days_above_ema200   or None,
            "ema50_reclaim_count_pre":     ema50_reclaim_count or None,
            "avg_close_vs_ema50_pct_pre":  avg_vs_ema50,
            "avg_close_vs_ema200_pct_pre": avg_vs_ema200,
        })
        patched += 1

    return patched


# ── Shared NP sequence resolver ───────────────────────────────────────────────
# Single source of truth for sequence-type classification.
# Used by both best-state assignment and per-day count accumulation.

# FRI34 = BLUE & L34 (filtered/selective version of L34).
# Implication: when FRI34 fires, L34 also fires on the same bar.
# Priority order places FRI34 variants above L34 because FRI34 has a stricter gate.
# Count buckets are mutually exclusive: FRI34 variants count only when FRI34 is present;
# L34 variants count only when FRI34 is NOT present (matching resolver priority).
#
# Note: this priority list is a TAXONOMIC classifier (most-specific structural match wins)
# and intentionally differs from the empirical weighting in new_pump_engine._sequence_bonus
# (which downweights FULL_* because replay showed FULL underperforms TRIGGER_AFTER).
# Every FULL_* state structurally contains a TRIGGER_AFTER_* state, so reordering would
# collapse the B2-firing signal into the TRIGGER_AFTER buckets — we keep them separate.
_NP_SEQ_PRIORITY: list[str] = [
    "FULL_FRI34_G4_B2",    # 0 — strongest (FRI34 is more selective)
    "FULL_L34_G4_B2",      # 1
    "TRIGGER_AFTER_FRI34", # 2
    "TRIGGER_AFTER_L34",   # 3
    "SETUP_ONLY_FRI34",    # 4
    "SETUP_ONLY_L34",      # 5
    "CONFIRM_AFTER_G4",    # 6
    "ISOLATED_G4",         # 7
    "ISOLATED_B2",         # 8
    "NONE",                # 9 — weakest / absent
]
_NP_SEQ_RANK: dict[str, int] = {s: i for i, s in enumerate(_NP_SEQ_PRIORITY)}


def _np_sequence_state(
    has_l34:   bool, has_fri34: bool, has_g4: bool, has_b2: bool,
    fired_l34: bool, fired_fri34: bool, fired_g4: bool, fired_b2: bool,
) -> str:
    """
    Classify one day's NP signal state by the highest-priority sequence it satisfies.
    Evaluated in _NP_SEQ_PRIORITY order — first match wins.
    FRI34-based variants outrank L34-based at every tier (more selective filter).
    """
    if fired_b2 and has_g4 and has_fri34:              return "FULL_FRI34_G4_B2"
    if fired_b2 and has_g4 and has_l34:                return "FULL_L34_G4_B2"
    if fired_g4 and has_fri34:                         return "TRIGGER_AFTER_FRI34"
    if fired_g4 and has_l34:                           return "TRIGGER_AFTER_L34"
    if fired_fri34 and not has_g4:                     return "SETUP_ONLY_FRI34"
    if fired_l34  and not has_g4:                      return "SETUP_ONLY_L34"
    if fired_b2 and has_g4:                            return "CONFIRM_AFTER_G4"
    if fired_g4 and not has_l34 and not has_fri34:     return "ISOLATED_G4"
    if fired_b2 and not has_l34 and not has_fri34:     return "ISOLATED_B2"
    return "NONE"


async def build_raw_pattern_episode_features_new_pump(
    raw_run_id: int,
    pump_study_run_id: int,
    lookback_days: int = 200,
) -> int:
    """
    Phase 2B-6: Run new_pump_engine.analyze() on the PRE-window candle history
    for each episode and patch NP signal aggregate fields onto
    raw_pattern_episode_features rows.

    Fields patched (all into extra NP columns):
        had_valid_recent_setup, had_valid_recent_trigger,
        had_valid_recent_confirm, had_valid_full_sequence
        best_new_pump_label_rank  (FIRE=0, STRONG=1, SETUP=2, TRIGGER_ONLY=3, WEAK=4, NONE=5)
        best_new_pump_sequence_type
        days_from_last_setup_to_breakout
        days_from_last_trigger_to_breakout
        days_from_g4_to_b2
        max_bull_stack_days_pre    (max consecutive bull-stack run in PRE)
        extreme_anomaly_day_count_pre
        median_dollar_volume_pre

    Uses _fetch_candles_range → new_pump_engine.analyze() per episode.
    Skips episodes where candle fetch fails. Returns number of patched episodes.
    """
    from database import (
        get_pump_episodes,
        get_raw_pattern_daily_features,
        get_pump_episode_events,
        update_raw_pattern_episode_features,
    )

    _NP_LABEL_RANK = {
        "NEW_PUMP_FIRE": 0, "NEW_PUMP_STRONG": 1, "NEW_PUMP_SETUP": 2,
        "NEW_PUMP_TRIGGER_ONLY": 3, "NEW_PUMP_WEAK": 4, "NEW_PUMP_NONE": 5,
    }
    _FRESHNESS = {
        "setup":   10,   # _MAX_SETUP_AGE
        "trigger":  5,   # _MAX_TRIGGER_AGE
        "confirm":  5,   # _MAX_CONFIRM_AGE
    }

    def _median(vals: list) -> Optional[float]:
        cleaned = sorted(v for v in vals if v is not None)
        n = len(cleaned)
        if n == 0:
            return None
        mid = n // 2
        return round((cleaned[mid - 1] + cleaned[mid]) / 2 if n % 2 == 0 else cleaned[mid], 2)

    try:
        from scanner.new_pump_engine import analyze as np_analyze
    except ImportError:
        logger.warning("[RawNP] new_pump_engine not importable — skipping NP episode phase")
        return 0

    episodes   = await get_pump_episodes(pump_study_run_id, limit=10_000)
    patched    = 0

    for ep in episodes:
        episode_id  = ep["id"]
        symbol      = ep.get("symbol") or ""
        pump_start  = ep.get("pump_start_date")
        if not symbol or not pump_start:
            continue

        # ── Fetch candle history ending at pump_start ─────────────────────
        from datetime import date, timedelta
        try:
            end_date   = pump_start if isinstance(pump_start, str) else str(pump_start)
            start_date = str(
                date.fromisoformat(end_date) - timedelta(days=lookback_days * 2)
            )
        except (ValueError, TypeError):
            continue

        candles = await _fetch_candles_range(symbol, start_date, end_date)
        if len(candles) < 60:
            await update_raw_pattern_episode_features(
                raw_run_id, episode_id, {"np_skip_reason": "insufficient_candles"}
            )
            continue

        # ── Build bars list in NP engine format ───────────────────────────
        bars = [
            {"open": c["open"], "high": c["high"],
             "low": c["low"],  "close": c["close"], "volume": c["volume"]}
            for c in candles[-200:]
        ]

        try:
            np_result = np_analyze(bars)
        except Exception as exc:
            logger.debug(f"[RawNP] NP analyze failed {symbol}: {exc}")
            await update_raw_pattern_episode_features(
                raw_run_id, episode_id, {"np_skip_reason": "np_analysis_failed"}
            )
            continue

        # ── Extract per-episode NP aggregate fields ────────────────────────
        lbl      = np_result.get("new_pump_label") or "NEW_PUMP_NONE"
        lbl_rank = _NP_LABEL_RANK.get(lbl, 5)

        age_l34   = np_result.get("age_l34")
        age_fri34 = np_result.get("age_fri34")
        age_g4    = np_result.get("age_g4")
        age_b2    = np_result.get("age_b2")
        has_l34   = np_result.get("has_l34", False)
        has_fri34 = np_result.get("has_fri34", False)
        has_g4    = np_result.get("has_g4", False)
        has_b2    = np_result.get("has_b2", False)

        valid_setup   = bool(has_l34 or has_fri34) and (
            (age_l34   is not None and age_l34   <= _FRESHNESS["setup"]) or
            (age_fri34 is not None and age_fri34 <= _FRESHNESS["setup"])
        )
        valid_trigger = bool(has_g4) and age_g4 is not None and age_g4 <= _FRESHNESS["trigger"]
        valid_confirm = bool(has_b2) and age_b2 is not None and age_b2 <= _FRESHNESS["confirm"]
        valid_full    = valid_setup and valid_trigger and valid_confirm

        # G4→B2 gap
        days_g4_to_b2: Optional[int] = None
        if age_g4 is not None and age_b2 is not None and age_b2 < age_g4:
            days_g4_to_b2 = age_g4 - age_b2

        # Timing relative to breakout (using breakout event if available)
        evs = await get_pump_episode_events(episode_id)
        breakout_ev = next((e for e in evs if e["event_type"] == "breakout_day"), None)
        days_setup_to_breakout:   Optional[int] = None
        days_trigger_to_breakout: Optional[int] = None
        if breakout_ev:
            dbp = breakout_ev.get("days_before_pump")  # positive = N days before pump start
            if dbp is not None:
                if (has_l34 or has_fri34) and age_l34 is not None:
                    days_setup_to_breakout = int(dbp) + int(age_l34)
                if has_g4 and age_g4 is not None:
                    days_trigger_to_breakout = int(dbp) + int(age_g4)

        # Extra aggregates from daily features (PRE window)
        pre_rows = await get_raw_pattern_daily_features(
            raw_run_id, episode_id=episode_id, phase="PRE", limit=500
        )
        fjs = [r.get("feature_json") or {} for r in pre_rows]

        # Max consecutive bull-stack run
        max_run = cur_run = 0
        for fj in fjs:
            if fj.get("bull_stack_active") or fj.get("bullish_stack"):
                cur_run += 1
                max_run = max(max_run, cur_run)
            else:
                cur_run = 0

        extreme_anom_count = sum(1 for fj in fjs if fj.get("extreme_anomaly_flag"))
        dvols = [fj.get("dollar_volume") for fj in fjs if fj.get("dollar_volume")]
        median_dvol = _median(dvols) if dvols else None

        # ── Rolling per-PRE-day NP count aggregates ───────────────────────────
        # best_seq tracks the highest-priority sequence type seen across all PRE
        # days, using _np_sequence_state/_NP_SEQ_RANK — the single shared resolver.
        candle_date_idx = {c["date"]: i for i, c in enumerate(candles) if c.get("date")}
        sorted_pre      = sorted(pre_rows, key=lambda r: r.get("date") or "")

        best_seq_rank  = _NP_SEQ_RANK["NONE"]
        best_seq_label = "NONE"
        # best_lbl_rank tracks the best label seen across PRE days, so it is
        # consistent with the rolling-loop counts (not the stale at-pump-start snapshot).
        best_lbl_rank  = _NP_LABEL_RANK.get("NEW_PUMP_NONE", 5)

        cnt_l34 = cnt_fri34 = cnt_g4 = cnt_b2 = 0
        cnt_setup_only_l34 = cnt_setup_only_fri34 = 0
        cnt_trig_after_l34 = cnt_trig_after_fri34 = 0
        cnt_full_l34_g4_b2 = cnt_full_fri34_g4_b2 = 0
        cnt_isolated_g4 = cnt_isolated_b2 = 0
        cnt_confirm_after_g4 = 0
        cnt_valid_setup = cnt_valid_trigger = cnt_valid_confirm = cnt_valid_full = 0
        # Accumulated "has fired somewhere in the PRE window so far" flags.
        # Subtype conditions use these instead of w_has_* (200-bar lookback) so that
        # base counts are the guaranteed foundation of every subtype count.
        pre_fired_any_l34 = pre_fired_any_fri34 = False
        pre_fired_any_g4  = pre_fired_any_b2    = False

        for row in sorted_pre:
            row_date = row.get("date") or ""
            cidx = candle_date_idx.get(row_date)
            if cidx is None:
                continue
            window = candles[max(0, cidx - 199): cidx + 1]
            if len(window) < 10:
                continue
            w_bars = [
                {"open": c["open"], "high": c["high"],
                 "low":  c["low"],  "close": c["close"], "volume": c["volume"]}
                for c in window
            ]
            try:
                wr = np_analyze(w_bars)
            except Exception:
                continue

            w_age_l34   = wr.get("age_l34")
            w_age_fri34 = wr.get("age_fri34")
            w_age_g4    = wr.get("age_g4")
            w_age_b2    = wr.get("age_b2")
            w_has_l34   = wr.get("has_l34",   False)
            w_has_fri34 = wr.get("has_fri34", False)
            w_has_g4    = wr.get("has_g4",    False)
            w_has_b2    = wr.get("has_b2",    False)

            # Signal fired on the last bar (age == 0)
            fired_l34   = w_has_l34   and w_age_l34   == 0
            fired_fri34 = w_has_fri34 and w_age_fri34 == 0
            fired_g4    = w_has_g4    and w_age_g4    == 0
            fired_b2    = w_has_b2    and w_age_b2    == 0

            # Update best sequence type via shared resolver
            day_seq  = _np_sequence_state(
                w_has_l34, w_has_fri34, w_has_g4, w_has_b2,
                fired_l34, fired_fri34, fired_g4, fired_b2,
            )
            day_rank = _NP_SEQ_RANK.get(day_seq, 9)
            if day_rank < best_seq_rank:
                best_seq_rank  = day_rank
                best_seq_label = day_seq

            # Track best NP label across PRE days (consistent with rolling counts)
            day_lbl      = wr.get("new_pump_label") or "NEW_PUMP_NONE"
            day_lbl_rank = _NP_LABEL_RANK.get(day_lbl, 5)
            if day_lbl_rank < best_lbl_rank:
                best_lbl_rank = day_lbl_rank

            # Base counts: raw PRE-window firing events (age == 0 on that PRE day).
            # Update accumulated flags immediately so subtype conditions below can
            # see "has fired in PRE window including today."
            if fired_l34:   cnt_l34   += 1; pre_fired_any_l34   = True
            if fired_fri34: cnt_fri34 += 1; pre_fired_any_fri34 = True
            if fired_g4:    cnt_g4    += 1; pre_fired_any_g4    = True
            if fired_b2:    cnt_b2    += 1; pre_fired_any_b2    = True

            # Sub-category counts use accumulated PRE-window flags (not the 200-bar
            # lookback w_has_*) so every subtype count is guaranteed to be supported
            # by the corresponding base counts.
            # FRI34 variants take precedence over L34 variants (resolver priority).
            if fired_fri34 and not pre_fired_any_g4:
                cnt_setup_only_fri34 += 1
            elif fired_l34 and not pre_fired_any_g4:
                cnt_setup_only_l34 += 1

            if fired_g4 and pre_fired_any_fri34:
                cnt_trig_after_fri34 += 1
            elif fired_g4 and pre_fired_any_l34:
                cnt_trig_after_l34 += 1

            if fired_b2 and pre_fired_any_g4 and pre_fired_any_fri34:
                cnt_full_fri34_g4_b2 += 1
            elif fired_b2 and pre_fired_any_g4 and pre_fired_any_l34:
                cnt_full_l34_g4_b2 += 1

            if fired_g4 and not pre_fired_any_l34 and not pre_fired_any_fri34: cnt_isolated_g4 += 1
            if fired_b2 and not pre_fired_any_l34 and not pre_fired_any_fri34: cnt_isolated_b2 += 1

            if fired_b2 and pre_fired_any_g4: cnt_confirm_after_g4 += 1

            # Valid-freshness day counts
            w_vs = bool(w_has_l34 or w_has_fri34) and (
                (w_age_l34   is not None and w_age_l34   <= _FRESHNESS["setup"]) or
                (w_age_fri34 is not None and w_age_fri34 <= _FRESHNESS["setup"])
            )
            w_vt = bool(w_has_g4) and w_age_g4 is not None and w_age_g4 <= _FRESHNESS["trigger"]
            w_vc = bool(w_has_b2) and w_age_b2 is not None and w_age_b2 <= _FRESHNESS["confirm"]
            if w_vs: cnt_valid_setup    += 1
            if w_vt: cnt_valid_trigger  += 1
            if w_vc: cnt_valid_confirm  += 1
            if w_vs and w_vt and w_vc: cnt_valid_full += 1

        # ── Consistency guard: best_seq_label must be supported by counts ────
        # Without this, the resolver can report e.g. FULL_FRI34_G4_B2 on a day
        # where has_fri34 was true only because FRI34 fired before the PRE window
        # began — producing best = FULL_FRI34_* while cnt_full_fri34_g4_b2 = 0.
        _SEQ_COUNT_MAP = {
            "FULL_FRI34_G4_B2":    cnt_full_fri34_g4_b2,
            "FULL_L34_G4_B2":      cnt_full_l34_g4_b2,
            "TRIGGER_AFTER_FRI34": cnt_trig_after_fri34,
            "TRIGGER_AFTER_L34":   cnt_trig_after_l34,
            "SETUP_ONLY_FRI34":    cnt_setup_only_fri34,
            "SETUP_ONLY_L34":      cnt_setup_only_l34,
            "CONFIRM_AFTER_G4":    cnt_confirm_after_g4,
            "ISOLATED_G4":         cnt_isolated_g4,
            "ISOLATED_B2":         cnt_isolated_b2,
        }
        if best_seq_label in _SEQ_COUNT_MAP and _SEQ_COUNT_MAP[best_seq_label] == 0:
            # Downgrade to the highest-priority sequence whose count is > 0
            for lbl in _NP_SEQ_PRIORITY:
                if _SEQ_COUNT_MAP.get(lbl, 0) > 0:
                    best_seq_label = lbl
                    best_seq_rank  = _NP_SEQ_RANK[lbl]
                    break
            else:
                best_seq_label = "NONE"
                best_seq_rank  = _NP_SEQ_RANK["NONE"]

        await update_raw_pattern_episode_features(raw_run_id, episode_id, {
            "had_valid_recent_setup":          valid_setup   or None,
            "had_valid_recent_trigger":        valid_trigger or None,
            "had_valid_recent_confirm":        valid_confirm or None,
            "had_valid_full_sequence":         valid_full    or None,
            # Both derived from rolling PRE-window loop, not stale at-pump-start snapshot
            "best_new_pump_label_rank":        best_lbl_rank,
            "best_new_pump_sequence_type":     best_seq_label,
            "days_from_last_setup_to_breakout":   days_setup_to_breakout,
            "days_from_last_trigger_to_breakout": days_trigger_to_breakout,
            "days_from_g4_to_b2":              days_g4_to_b2,
            "max_bull_stack_days_pre":         max_run or None,
            "extreme_anomaly_day_count_pre":   extreme_anom_count or None,
            "median_dollar_volume_pre":        median_dvol,
            "np_skip_reason":                  None,   # explicitly clear on success
            # count fields — 0 when absent, never null
            "l34_count_pre":                  cnt_l34,
            "fri34_count_pre":                cnt_fri34,
            "g4_count_pre":                   cnt_g4,
            "b2_count_pre":                   cnt_b2,
            "setup_only_l34_count_pre":       cnt_setup_only_l34,
            "setup_only_fri34_count_pre":     cnt_setup_only_fri34,
            "trigger_after_l34_count_pre":    cnt_trig_after_l34,
            "trigger_after_fri34_count_pre":  cnt_trig_after_fri34,
            "full_l34_g4_b2_count_pre":       cnt_full_l34_g4_b2,
            "full_fri34_g4_b2_count_pre":     cnt_full_fri34_g4_b2,
            "isolated_g4_count_pre":          cnt_isolated_g4,
            "isolated_b2_count_pre":          cnt_isolated_b2,
            "confirm_after_g4_count_pre":     cnt_confirm_after_g4,
            "valid_setup_days_pre":           cnt_valid_setup,
            "valid_trigger_days_pre":         cnt_valid_trigger,
            "valid_confirm_days_pre":         cnt_valid_confirm,
            "valid_full_sequence_days_pre":   cnt_valid_full,
        })
        patched += 1
        await asyncio.sleep(0)   # yield control in the event loop

    logger.info(f"[RawNP] NP episode features patched: {patched}/{len(episodes)}")
    return patched


async def build_raw_pattern_episode_features_demand(
    raw_run_id: int,
    pump_study_run_id: int,
) -> int:
    """
    PART 1+2+3: Compute Demand Scanner fields at/near breakout for each episode.

    For each episode:
    - Finds the breakout evaluation bar (last PRE bar ≈ pump_start_date)
    - Gets the matching pump_episode_snapshot + feature_json
    - Reconstructs scorer input from snapshot new_pump fields + D-WLNBB feature_json
    - Calls score_demand_composite()
    - Writes demand fields to raw_pattern_episode_features
    - Also resolves and writes sector/industry if currently null (PART 3)
    """
    import json as _json
    from scanner.demand_composite_scanner import score_demand_composite

    from database import (
        get_pump_episodes,
        get_raw_pattern_daily_features,
        get_run_snapshots,
        update_raw_pattern_episode_features,
        update_pump_episode_enrichment,
    )

    episodes = await get_pump_episodes(pump_study_run_id, limit=10_000)
    patched  = 0

    for ep in episodes:
        episode_id = ep.get("id")
        symbol     = ep.get("symbol", "")
        pump_start = ep.get("pump_start_date") or ep.get("pump_peak_date")
        if not episode_id or not symbol:
            continue

        patch: dict = {}

        # ── PART 3: sector / industry resolution ────────────────────────────────
        if not ep.get("sector"):
            sec, ind = await _resolve_sector_for_symbol(symbol)
            if sec:
                patch["sector"]   = sec
                patch["industry"] = ind

        # ── Find breakout bar ────────────────────────────────────────────────────
        # Primary: last PRE bar (closest bar before pump_start)
        pre_bars = await get_raw_pattern_daily_features(
            raw_run_id, episode_id=episode_id, phase="PRE", limit=200
        )
        pump_bars_df = await get_raw_pattern_daily_features(
            raw_run_id, episode_id=episode_id, phase="PUMP", limit=5
        )

        breakout_bar: dict | None = None
        if pre_bars:
            breakout_bar = sorted(pre_bars, key=lambda x: x.get("date", ""))[-1]
        elif pump_bars_df:
            breakout_bar = sorted(pump_bars_df, key=lambda x: x.get("date", ""))[0]

        if not breakout_bar:
            patch.update({
                "demand_compute_status": "MISSING_INPUT",
                "demand_missing_inputs": _json.dumps(["no_bars_found"]),
            })
            if any(v is not None for v in patch.values()):
                await update_raw_pattern_episode_features(raw_run_id, episode_id, patch)
            continue

        breakout_date = breakout_bar.get("date", "")
        feature_json  = breakout_bar.get("feature_json") or {}
        if isinstance(feature_json, str):
            try:
                feature_json = _json.loads(feature_json)
            except Exception:
                feature_json = {}

        # ── Get matching snapshot ────────────────────────────────────────────────
        all_snaps = await get_run_snapshots(
            run_id=pump_study_run_id, episode_id=episode_id, phase="PRE"
        )
        breakout_snap: dict | None = None
        if all_snaps:
            # Exact date match first
            breakout_snap = next(
                (s for s in all_snaps if s.get("snap_date") == breakout_date), None
            )
            if not breakout_snap:
                # Fallback: last PRE snapshot
                breakout_snap = sorted(
                    all_snaps, key=lambda x: x.get("snap_date", "")
                )[-1]

        if not breakout_snap:
            pump_snaps = await get_run_snapshots(
                run_id=pump_study_run_id, episode_id=episode_id, phase="PUMP"
            )
            breakout_snap = pump_snaps[0] if pump_snaps else None

        # ── Build result dict ────────────────────────────────────────────────────
        result_dict, missing_inputs = _build_demand_result_from_snapshot(
            breakout_snap, feature_json, ep
        )

        # ── Fetch recent candles for readiness computation ───────────────────────
        candles: list[dict] = []
        if pump_start:
            try:
                fetch_start = _date_add(pump_start, -30)
                candles = await _fetch_candles_range(symbol, fetch_start, pump_start)
            except Exception:
                pass

        # ── Score ────────────────────────────────────────────────────────────────
        try:
            scored = score_demand_composite(result_dict, candles if candles else None)

            tier   = scored.get("demand_composite_tier") or ""
            ats    = scored.get("ats_signal") or ""
            r_tier = scored.get("readiness_tier") or ""

            # ATS score from breakdown
            breakdown = scored.get("demand_score_breakdown") or {}
            ats_score = breakdown.get("ats") or 0.0

            patch.update({
                "demand_score_at_breakout":              scored.get("demand_composite_score"),
                "demand_tier_at_breakout":               tier or None,
                "ats_at_breakout":                       ats or None,
                "ats_score_at_breakout":                 ats_score or None,
                "ats_conditions_met_at_breakout":        _json.dumps(scored.get("ats_conditions_met") or []),
                "ats_conditions_missing_at_breakout":    _json.dumps(scored.get("ats_conditions_missing") or []),
                "readiness_at_breakout":                 scored.get("readiness_score"),
                "readiness_tier_at_breakout":            r_tier or None,
                "demand_action_at_breakout":             tier or None,
                "demand_reasons_at_breakout":            _json.dumps(scored.get("demand_buy_reasons") or []),
                "demand_risk_flags_at_breakout":         _json.dumps(scored.get("demand_risk_flags") or []),
                "demand_compute_status":                 "PARTIAL" if missing_inputs else "OK",
                "demand_missing_inputs":                 _json.dumps(missing_inputs) if missing_inputs else None,
                # Comparison booleans (NULL = false in aggregation)
                "demand_prime_at_breakout":              True if tier == "PRIME_BUY" else None,
                "demand_high_at_breakout":               True if tier == "HIGH_CONF_BUY" else None,
                "demand_watch_or_better_at_breakout":    True if tier in ("PRIME_BUY", "HIGH_CONF_BUY", "BUY_WATCH") else None,
                "ats_prime_at_breakout":                 True if ats == "ATS_PRIME" else None,
                "ats_setup_or_better_at_breakout":       True if ats in ("ATS_PRIME", "ATS_SETUP") else None,
                "split_capped_demand_at_breakout":       True if "split" in " ".join(scored.get("demand_risk_flags") or []).lower() else None,
                "illiquidity_capped_demand_at_breakout": True if "illiquid" in " ".join(scored.get("demand_risk_flags") or []).lower() else None,
                # had_*_pre: True if any PRE bar had this tier (updated below)
                "had_prime_buy_pre":  None,
                "had_ats_prime_pre":  None,
            })

            # ── TZ bar label at breakout ─────────────────────────────────────────
            try:
                from scanner.manual_d_wlnbb_features import compute_combined_bar_labels
                _TZ_T_PRIO = ["T4","T6","T1G","T2G","T1","T2","T9","T10","T3","T11","T5","T12"]
                _TZ_Z_PRIO = ["Z4","Z6","Z1G","Z2G","Z1","Z2","Z9","Z10","Z3","Z11","Z5","Z12","Z7"]
                if candles:
                    _lbls = compute_combined_bar_labels(candles, last_n=1)
                    if _lbls:
                        _l = _lbls[0]
                        patch.update({
                            "tz_t_signal_at_breakout": _l.get("t_signal") or None,
                            "tz_z_signal_at_breakout": _l.get("z_signal") or None,
                            "preup_token_at_breakout": _l.get("preup")    or None,
                            "predn_token_at_breakout": _l.get("predn")    or None,
                            "line3_at_breakout":       _l.get("line3")    or None,
                            "line4_at_breakout":       _l.get("line4")    or None,
                            "line5_at_breakout":       _l.get("line5")    or None,
                        })
                    # PRE-window TZ counts: strong T signals + PREUP bars
                    if len(candles) > 1:
                        _pre_lbls = compute_combined_bar_labels(candles, last_n=min(20, len(candles) - 1))
                        _pre_lbls = _pre_lbls[:-1]  # exclude the last (breakout) bar
                        _strong_tz = sum(
                            1 for b in _pre_lbls
                            if b.get("t_signal") in ("T4", "T6", "T1G", "T2G")
                        )
                        _preup_cnt = sum(1 for b in _pre_lbls if b.get("preup"))
                        patch["strong_tz_count_pre"] = _strong_tz
                        patch["preup_count_pre"]      = _preup_cnt
                    # 15-bar best TZ signal
                    if len(candles) >= 2:
                        _n15 = min(15, len(candles))
                        _lbls_15 = compute_combined_bar_labels(candles, last_n=_n15)
                        _all_t = [b.get("t_signal") for b in _lbls_15 if b.get("t_signal")]
                        _all_z = [b.get("z_signal") for b in _lbls_15 if b.get("z_signal")]
                        _best_t = min((_s for _s in _all_t if _s in _TZ_T_PRIO), key=lambda _s: _TZ_T_PRIO.index(_s), default=None)
                        _best_z = min((_s for _s in _all_z if _s in _TZ_Z_PRIO), key=lambda _s: _TZ_Z_PRIO.index(_s), default=None)
                        patch["best_tz_t_signal_15bar"] = _best_t
                        patch["best_tz_z_signal_15bar"] = _best_z
            except Exception:
                pass

        except Exception as exc:
            patch.update({
                "demand_compute_status": "ERROR",
                "demand_missing_inputs": _json.dumps([str(exc)[:200]]),
            })

        # ── had_*_pre: scan all PRE bars ─────────────────────────────────────────
        # Score each PRE bar and check if any reached PRIME_BUY / ATS_PRIME
        had_prime  = False
        had_ats_p  = False
        if pre_bars:
            all_pre_snaps = sorted(
                await get_run_snapshots(run_id=pump_study_run_id, episode_id=episode_id, phase="PRE"),
                key=lambda x: x.get("snap_date", ""),
            )
            snap_by_date = {s.get("snap_date"): s for s in all_pre_snaps}
            for bar in pre_bars:
                bdate  = bar.get("date", "")
                fj_bar = bar.get("feature_json") or {}
                if isinstance(fj_bar, str):
                    try: fj_bar = _json.loads(fj_bar)
                    except: fj_bar = {}
                snap_bar = snap_by_date.get(bdate)
                if not snap_bar:
                    continue
                try:
                    r_bar, _ = _build_demand_result_from_snapshot(snap_bar, fj_bar, ep)
                    s_bar    = score_demand_composite(r_bar, None)
                    if s_bar.get("demand_composite_tier") == "PRIME_BUY":
                        had_prime = True
                    if s_bar.get("ats_signal") == "ATS_PRIME":
                        had_ats_p = True
                    if had_prime and had_ats_p:
                        break
                except Exception:
                    pass

        patch["had_prime_buy_pre"] = True if had_prime else None
        patch["had_ats_prime_pre"] = True if had_ats_p else None

        if any(v is not None for v in patch.values()):
            await update_raw_pattern_episode_features(raw_run_id, episode_id, patch)
            # Write key demand + TZ fields back to pump_episodes so pump study frontend
            # can display them without joining to raw_pattern_episode_features
            pump_ep_patch = {}
            for fld in (
                "demand_score_at_breakout", "demand_tier_at_breakout",
                "ats_at_breakout", "readiness_at_breakout", "readiness_tier_at_breakout",
                "tz_t_signal_at_breakout", "tz_z_signal_at_breakout",
                "preup_token_at_breakout", "line5_at_breakout",
                "best_tz_t_signal_15bar", "best_tz_z_signal_15bar",
            ):
                if fld in patch and patch[fld] is not None:
                    pump_ep_patch[fld] = patch[fld]
            if pump_ep_patch:
                try:
                    await update_pump_episode_enrichment(episode_id, pump_ep_patch)
                except Exception as _pe:
                    logger.debug(f"[RawDemand] pump_ep write-back failed ep={episode_id}: {_pe}")
            patched += 1

    logger.info(f"[RawDemand] Demand episode features patched: {patched}/{len(episodes)}")
    return patched


async def build_raw_pattern_comparisons(
    raw_run_id: int,
    pump_study_run_id: int,
) -> int:
    """
    Phase 3: Build cross-group comparison rows from existing
    raw_pattern_episode_features.

    For each group in _COMPARISON_GROUPS:
      1. Collect all episode feature rows where group_type matches.
      2. Save one comparison member row per episode (features_json = snapshot
         of all comparison feature values for that episode).
      3. For each feature in _COMPARISON_FEATURES compute distribution stats
         over the group and save one raw_pattern_comparisons row.

    Updates raw_pattern_runs.comparison_count with the total comparison rows
    saved (= len(groups) × len(features) with at least one member).

    Returns the total number of comparison stat rows saved.
    """
    from database import (
        get_raw_pattern_daily_features,
        get_raw_pattern_episode_features,
        save_raw_pattern_comparison_members,
        save_raw_pattern_comparison_rows,
        update_raw_pattern_run,
    )

    # ── Pre-compute EMA spread aggregates from daily rows (zero schema change) ──
    all_pre_daily = await get_raw_pattern_daily_features(
        raw_run_id, phase="PRE", limit=100_000
    )
    _ema_spread_lookup: dict[int, list[float]] = {}
    for dr in all_pre_daily:
        eid = dr.get("episode_id")
        val = dr.get("ema_spread_pct")
        if eid is not None and val is not None:
            _ema_spread_lookup.setdefault(eid, []).append(float(val))
    _ema_agg: dict[int, dict] = {
        eid: {
            "avg_ema_spread_pre": round(sum(vals) / len(vals), 3),
            "min_ema_spread_pre": round(min(vals), 3),
        }
        for eid, vals in _ema_spread_lookup.items()
    }

    total_comp_rows = 0

    for group_name in _COMPARISON_GROUPS:
        ep_features = await get_raw_pattern_episode_features(
            raw_run_id, group_type=group_name, limit=5000
        )
        if not ep_features:
            continue

        # Augment with EMA spread aggregates derived from daily rows
        for ef in ep_features:
            eid = ef.get("episode_id")
            if eid in _ema_agg:
                ef.update(_ema_agg[eid])

        # ── Member rows ────────────────────────────────────────────────────
        members = [
            {
                "symbol":     ef.get("symbol"),
                "episode_id": ef.get("episode_id"),
                "features":   {f: ef.get(f) for f in _COMPARISON_FEATURES},
            }
            for ef in ep_features
        ]
        await save_raw_pattern_comparison_members(raw_run_id, group_name, members)

        # ── Per-feature stats ──────────────────────────────────────────────
        comp_rows: list[dict] = []
        for feat in _COMPARISON_FEATURES:
            raw_vals = [ef.get(feat) for ef in ep_features]
            numeric  = []
            if feat in _BINARY_FEATURES:
                # For boolean columns, NULL means False — count over full group size
                # so rates reflect the true proportion, not just the non-null subset.
                for v in raw_vals:
                    numeric.append(1 if v is True else 0)
            else:
                # For numeric features, skip NULLs (missing data ≠ zero)
                for v in raw_vals:
                    if v is None:
                        continue
                    numeric.append(1 if v is True else (0 if v is False else v))

            stats = _compute_stats(numeric)
            if stats["count"] == 0:
                continue

            median = stats["median"] or 0.0
            mean   = stats["mean"]   or 0.0
            p25    = stats["p25"]    or 0.0
            p75    = stats["p75"]    or 0.0

            # ── Diagnostic flags ─────────────────────────────────────────
            iqr = p75 - p25

            # Low-variance: IQR is small relative to median (or absolute)
            low_variance_flag = bool(
                iqr < max(abs(median) * 0.15, 0.5)
            )

            # Always-on: binary feature where >90% of values are True/1
            always_on_flag = bool(
                feat in _BINARY_FEATURES and mean > 0.90
            )

            # Outlier-risk: mean is heavily distorted relative to median
            outlier_risk_flag = bool(
                abs(mean - median) / max(abs(median), 0.001) > 0.50
            )

            priority = _FEATURE_PRIORITY.get(feat, "LOW_SIGNAL")
            # Override to LOW_SIGNAL if diagnostics indicate poor signal
            if always_on_flag or (low_variance_flag and not always_on_flag):
                if priority not in ("PRIMARY",):
                    priority = "LOW_SIGNAL"

            comp_rows.append({
                "group_name":   group_name,
                "feature_name": feat,
                "member_count": len(ep_features),
                "mean_value":   stats["mean"],
                "median_value": stats["median"],
                "p25_value":    stats["p25"],
                "p75_value":    stats["p75"],
                "p90_value":    stats["p90"],
                "stats_json": {
                    "priority":           priority,
                    "low_variance_flag":  low_variance_flag,
                    "always_on_flag":     always_on_flag,
                    "outlier_risk_flag":  outlier_risk_flag,
                    "iqr":                round(iqr, 4),
                    "pct_nonzero":        round(
                        sum(1 for x in numeric if x != 0) / len(numeric), 3
                    ) if numeric else 0.0,
                },
            })

        if comp_rows:
            saved = await save_raw_pattern_comparison_rows(raw_run_id, comp_rows)
            total_comp_rows += saved

    await update_raw_pattern_run(raw_run_id, {"comparison_count": total_comp_rows})
    return total_comp_rows


async def repair_raw_pattern_group_types(
    raw_run_id: int,
    pump_study_run_id: int,
) -> dict:
    """
    Repair an existing raw-pattern run where group_type was not assigned.

    Steps:
      1. Re-derive episode_id → group_name from pump_comparison_members.
      2. Patch group_type on every raw_pattern_episode_features row for this run.
      3. Clear stale comparison rows (members + stats) for the run.
      4. Rebuild comparisons via build_raw_pattern_comparisons().

    Returns a dict with patch counts.
    """
    from database import (
        get_pump_comparison_members,
        get_raw_pattern_episode_features,
        update_raw_pattern_episode_features,
        clear_raw_pattern_comparisons,
        update_raw_pattern_run,
    )

    _GROUP_PRIORITY = {"false_positive": 0, "4x_pump": 1, "normal_winner": 2, "missed_mover": 3}

    # Build lookup
    ps_members = await get_pump_comparison_members(pump_study_run_id)
    episode_group: dict[int, str] = {}
    for m in ps_members:
        eid   = m.get("episode_id")
        gname = m.get("group_name")
        if eid is None or not gname:
            continue
        existing = episode_group.get(eid)
        if existing is None or _GROUP_PRIORITY.get(gname, 99) < _GROUP_PRIORITY.get(existing, 99):
            episode_group[eid] = gname

    # Patch episode feature rows
    ep_rows  = await get_raw_pattern_episode_features(raw_run_id, limit=10_000)
    patched  = 0
    skipped  = 0
    for row in ep_rows:
        eid   = row.get("episode_id")
        gname = episode_group.get(eid)
        if gname and row.get("group_type") != gname:
            await update_raw_pattern_episode_features(raw_run_id, eid, {"group_type": gname})
            patched += 1
        elif not gname:
            skipped += 1

    # Clear stale comparison data and rebuild
    await clear_raw_pattern_comparisons(raw_run_id)
    new_comp_rows = await build_raw_pattern_comparisons(raw_run_id, pump_study_run_id)

    return {
        "episodes_patched":  patched,
        "episodes_skipped":  skipped,
        "comparison_rows":   new_comp_rows,
    }


def extract_top_schemes(episodes: list[dict]) -> dict:
    """
    Deterministic top pre-pump scheme extraction from episode feature vectors.

    Classifies each episode into one of 5 canonical pre-pump sequence templates
    using ONLY pre-breakout features.  peak / fade / dump are excluded entirely.
    Each episode is assigned to the FIRST matching template (most-specific first).

    Returns a summary dict with:
      schemes          — top schemes sorted by 4x_pump absolute count
      absent_groups    — groups with zero episodes in this run
      total_episodes   — total input episode count
      analyzed_episodes — episodes that matched at least one scheme
      note             — validation disclaimer
    """
    import statistics as _stats

    _ALL_GROUPS = ["4x_pump", "normal_winner", "false_positive", "missed_mover"]

    # ── Feature helpers — pre-pump fields ONLY ─────────────────────────────
    def _c(ef):  return (ef.get("compression_days_pre") or 0) > 0 or bool(ef.get("had_compression"))
    def _d(ef):  return (ef.get("dryup_day_count_pre") or 0) > 0
    def _v(ef):  return (ef.get("abnormal_volume_day_count_pre") or 0) > 0
    def _r(ef):  return (ef.get("reclaim_bar_count_pre") or 0) > 0
    def _a(ef):  return bool(ef.get("had_accumulation_like"))
    def _s(ef):  return bool(ef.get("had_spring_test_lps"))
    def _e(ef):  return (ef.get("expansion_bar_count_pre") or 0) > 0

    # Checked in order — most specific scheme first.
    # All helpers use pre-pump fields only; peak/fade/dump excluded.
    TEMPLATES: list[dict] = [
        {
            # Full textbook pre-pump playbook — all 5 components present
            "scheme_id": "S0",
            "label":     "Full Pre-Pump (Comp+Dryup+Accum+Spring+Vol)",
            "steps":     ["compression", "dryup", "accumulation_like", "spring_test_lps", "abnormal_volume", "breakout"],
            "check":     lambda ef: _c(ef) and _d(ef) and _a(ef) and _s(ef) and _v(ef),
        },
        {
            "scheme_id": "S1",
            "label":     "Compression → Dryup → Vol → Reclaim",
            "steps":     ["compression", "dryup", "abnormal_volume", "reclaim", "breakout"],
            "check":     lambda ef: _c(ef) and _d(ef) and _v(ef) and _r(ef),
        },
        {
            "scheme_id": "S2",
            "label":     "Accumulation → Spring/LPS → Vol",
            "steps":     ["accumulation_like", "spring_test_lps", "abnormal_volume", "breakout"],
            "check":     lambda ef: _a(ef) and _s(ef) and _v(ef),
        },
        {
            "scheme_id": "S3",
            "label":     "Accumulation → Vol → Reclaim",
            "steps":     ["accumulation_like", "abnormal_volume", "reclaim", "expansion"],
            "check":     lambda ef: _a(ef) and _v(ef) and _r(ef) and not _s(ef),
        },
        {
            "scheme_id": "S4",
            "label":     "Compression → Vol Wake-up → Breakout",
            "steps":     ["compression", "abnormal_volume", "breakout"],
            "check":     lambda ef: _c(ef) and _v(ef) and not _d(ef) and not _a(ef),
        },
        {
            "scheme_id": "S5",
            "label":     "Dryup → Vol → Expansion",
            "steps":     ["dryup", "abnormal_volume", "expansion"],
            "check":     lambda ef: _d(ef) and _v(ef) and _e(ef) and not _c(ef) and not _a(ef),
        },
    ]

    # ── Per-scheme accumulators ────────────────────────────────────────────
    by_group:    dict[str, dict[str, list]] = {t["scheme_id"]: {} for t in TEMPLATES}
    timing_eps:  dict[str, list]            = {t["scheme_id"]: [] for t in TEMPLATES}
    group_totals: dict[str, int]            = {}
    matched = 0

    for ep in episodes:
        gt = ep.get("group_type") or "unknown"
        group_totals[gt] = group_totals.get(gt, 0) + 1
        for tmpl in TEMPLATES:
            try:
                if tmpl["check"](ep):
                    by_group[tmpl["scheme_id"]].setdefault(gt, []).append(ep)
                    timing_eps[tmpl["scheme_id"]].append(ep)
                    matched += 1
                    break   # first-match only
            except Exception:
                pass

    # ── Timing median helper ───────────────────────────────────────────────
    def _med(vals: list):
        cleaned = [v for v in vals if v is not None]
        return round(_stats.median(cleaned), 1) if cleaned else None

    n4x    = group_totals.get("4x_pump",       0)
    nfp    = group_totals.get("false_positive",0)
    nnw    = group_totals.get("normal_winner", 0)
    absent = [g for g in _ALL_GROUPS if group_totals.get(g, 0) == 0]

    # ── Summarise each scheme ──────────────────────────────────────────────
    results: list[dict] = []
    for tmpl in TEMPLATES:
        sid   = tmpl["scheme_id"]
        teps  = timing_eps[sid]
        f4x   = len(by_group[sid].get("4x_pump",       []))
        ffp   = len(by_group[sid].get("false_positive", []))
        fnw   = len(by_group[sid].get("normal_winner",  []))
        ftotal = sum(len(v) for v in by_group[sid].values())

        if ftotal == 0:
            continue

        share_4x = round(f4x / n4x, 3) if n4x > 0 else None
        share_fp = round(ffp / nfp, 3) if nfp > 0 else None
        share_nw = round(fnw / nnw, 3) if nnw > 0 else None
        sep_str  = (round(share_4x / share_fp, 2)
                    if share_4x and share_fp and share_fp > 0
                    else None)
        sep_nw   = (round(share_4x / share_nw, 2)
                    if share_4x and share_nw and share_nw > 0
                    else None)

        breakdown = {g: len(by_group[sid].get(g, []))
                     for g in _ALL_GROUPS if group_totals.get(g, 0) > 0}

        notes: list[str] = []
        if nfp == 0:
            notes.append("false_positive absent — separator_strength unavailable")
        if n4x == 0:
            notes.append("4x_pump absent — share_of_4x_pumps unavailable")
        if nnw == 0:
            notes.append("normal_winner absent — share_of_normal_winners unavailable")

        results.append({
            "scheme_id":                  sid,
            "scheme_label":               tmpl["label"],
            "ordered_steps":              tmpl["steps"],
            "frequency_count":            ftotal,
            "group_breakdown":            breakdown,
            "share_of_4x_pumps":            share_4x,
            "share_of_false_positives":     share_fp,
            "share_of_normal_winners":      share_nw,
            "separator_strength":           sep_str,
            "separator_vs_normal_winner":   sep_nw,
            "typical_timing": {
                "compression_lead_days":        _med([e.get("compression_days_pre")                         for e in teps]),
                "accumulation_days":            _med([e.get("accumulation_like_day_count")                  for e in teps]),
                "compression_to_breakout_days": _med([e.get("days_from_first_compression_to_breakout")      for e in teps]),
                "vol_to_breakout_days":         _med([e.get("days_from_first_abnormal_volume_to_breakout")  for e in teps]),
                "breakout_to_peak_days":        _med([e.get("days_from_breakout_to_peak")                   for e in teps]),
                "days_in_base":                 _med([e.get("days_in_base")                                 for e in teps]),
                # EMA ribbon episode aggregates
                "avg_days_above_ema50":         _med([e.get("days_above_ema50_pre")   for e in teps]),
                "avg_ema_spread_pre":           _med([e.get("avg_ema_spread_pre")     for e in teps]),
                "bull_stack_pct":               (
                    round(sum(1 for e in teps if e.get("had_bull_stack_pre")) / len(teps), 2)
                    if teps else None
                ),
            },
            "notes": notes or None,
        })

    # Sort: primary by 4x_pump absolute count, then total
    results.sort(key=lambda r: (
        -len(by_group[r["scheme_id"]].get("4x_pump", [])),
        -(r["frequency_count"] or 0),
    ))

    return {
        "schemes":            results[:5],
        "absent_groups":      absent,
        "total_episodes":     len(episodes),
        "analyzed_episodes":  matched,
        "note": (
            "Pre-breakout features only. peak/fade/dump excluded. "
            "Each episode assigned to first matching scheme (most specific wins)."
        ),
    }


def generate_engine_patch_plan(comparisons: list[dict]) -> dict:
    """
    Deterministic Scanner v2 patch-plan derived from raw pattern comparison medians.

    Reads comparison medians (group × feature) and classifies each feature:
        BOOST    — 4x_pump median >= 1.4× false_positive median
        INCREASE — 4x_pump modestly higher (1.15–1.4×)
        PENALIZE — false_positive median > 4x_pump (contra-signal)
        REDUCE   — little separation, outlier distortion, or no data
        IGNORE   — always-on binary or low-variance across all groups

    Falls back to normal_winner separation when false_positive data is absent.
    Delta bonuses are NOT included — delta is not yet available upstream.
    """
    # ── Pivot: feature → group → {median, flags} ─────────────────────────────
    pivot: dict[str, dict[str, dict]] = {}
    for c in comparisons:
        fn  = c.get("feature_name")
        gn  = c.get("group_name")
        if not fn or not gn:
            continue
        st = c.get("stats") or {}
        pivot.setdefault(fn, {})[gn] = {
            "median":       c.get("median_value"),
            "n":            c.get("member_count") or 0,
            "priority":     st.get("priority", "UNKNOWN"),
            "low_variance": st.get("low_variance_flag", False),
            "always_on":    st.get("always_on_flag",    False),
            "outlier_risk": st.get("outlier_risk_flag", False),
        }

    def _sep(a, b):
        if a is None or b is None or abs(b) < 0.001:
            return None
        return round(a / b, 2)

    _BOOST_THRESH    = 1.40
    _INCREASE_THRESH = 1.15
    _PENALIZE_THRESH = 0.70

    verdicts: list[dict] = []
    for feat, groups in pivot.items():
        g4x = groups.get("4x_pump",       {})
        gfp = groups.get("false_positive", {})
        gnw = groups.get("normal_winner",  {})

        m4x = g4x.get("median")
        mfp = gfp.get("median")
        mnw = gnw.get("median")

        priority     = g4x.get("priority") or "UNKNOWN"
        low_variance = g4x.get("low_variance", False)
        always_on    = g4x.get("always_on",    False)
        outlier_risk = g4x.get("outlier_risk", False)

        if g4x.get("n", 0) == 0 or m4x is None:
            continue

        sep_fp = _sep(m4x, mfp)
        sep_nw = _sep(m4x, mnw)

        if low_variance or always_on:
            verdict = "IGNORE"
            reason  = "always-on or low-variance — no discriminating power"
        elif sep_fp is not None and sep_fp >= _BOOST_THRESH:
            verdict = "BOOST"
            reason  = f"4x_pump median {sep_fp}× higher than false_positive"
        elif sep_fp is not None and sep_fp >= _INCREASE_THRESH:
            verdict = "INCREASE"
            reason  = f"4x_pump {sep_fp}× higher than false_positive (moderate)"
        elif sep_fp is not None and sep_fp <= _PENALIZE_THRESH:
            verdict = "PENALIZE"
            inv = round(1 / sep_fp, 2) if sep_fp != 0 else "∞"
            reason  = f"false_positive median {inv}× higher — contra-signal"
        elif mfp is None and sep_nw is not None and sep_nw >= _BOOST_THRESH:
            verdict = "BOOST"
            reason  = f"4x_pump {sep_nw}× vs normal_winner (fp unavailable)"
        elif mfp is None and sep_nw is not None and sep_nw >= _INCREASE_THRESH:
            verdict = "INCREASE"
            reason  = f"4x_pump {sep_nw}× vs normal_winner (moderate, fp unavailable)"
        elif outlier_risk and priority != "PRIMARY":
            verdict = "REDUCE"
            reason  = "outlier distortion in non-primary feature — weight lightly"
        else:
            verdict = "REDUCE"
            reason  = "no meaningful group separation — reduce weight"

        verdicts.append({
            "feature":    feat,
            "priority":   priority,
            "verdict":    verdict,
            "reason":     reason,
            "sep_vs_fp":  sep_fp,
            "sep_vs_nw":  sep_nw,
            "median_4x":  m4x,
            "median_fp":  mfp,
            "median_nw":  mnw,
        })

    _V_ORDER = {"BOOST": 0, "INCREASE": 1, "PENALIZE": 2, "REDUCE": 3, "IGNORE": 4}
    _P_ORDER = {"PRIMARY": 0, "SECONDARY": 1, "LOW_SIGNAL": 2, "UNKNOWN": 3}
    verdicts.sort(key=lambda v: (
        _V_ORDER.get(v["verdict"], 99),
        _P_ORDER.get(v["priority"], 99),
        -(v["sep_vs_fp"] or v["sep_vs_nw"] or 0),
    ))

    boost_set    = {v["feature"] for v in verdicts if v["verdict"] == "BOOST"}
    increase_set = {v["feature"] for v in verdicts if v["verdict"] == "INCREASE"}
    penalize_set = {v["feature"] for v in verdicts if v["verdict"] == "PENALIZE"}
    reduce_set   = {v["feature"] for v in verdicts if v["verdict"] == "REDUCE"}
    ignore_set   = {v["feature"] for v in verdicts if v["verdict"] == "IGNORE"}

    def _gather(candidates):
        b = [f for f in candidates if f in boost_set or f in increase_set]
        r = [f for f in candidates if f in penalize_set or f in reduce_set or f in ignore_set]
        return b, r

    seq_feats   = ["compression_days_pre", "days_from_first_compression_to_breakout",
                   "days_from_breakout_to_peak", "dryup_day_count_pre", "days_in_base",
                   "days_from_first_abnormal_volume_to_breakout"]
    compr_feats = ["compression_days_pre", "had_compression", "atr_contraction_days_pre",
                   "avg_ema_spread_pre", "min_ema_spread_pre"]
    vol_feats   = ["max_volume_anomaly_pre", "median_volume_anomaly_pre",
                   "abnormal_volume_day_count_pre", "dryup_day_count_pre"]
    struct_feats = ["had_accumulation_like", "accumulation_like_day_count",
                    "had_spring_test_lps", "reclaim_bar_count_pre"]
    ema_feats   = ["ema50_reclaim_count_pre", "had_bull_stack_pre", "days_above_ema50_pre",
                   "bull_stack_days_pre", "avg_close_vs_ema50_pct_pre"]
    noise_feats = ["avg_body_pct_pre", "avg_upper_wick_pct_pre", "avg_lower_wick_pct_pre",
                   "bearish_engulfing_count_pre", "inside_bar_count_pre", "outside_bar_count_pre"]

    seq_b,    seq_r    = _gather(seq_feats)
    compr_b,  compr_r  = _gather(compr_feats)
    vol_b,    vol_r    = _gather(vol_feats)
    struct_b, struct_r = _gather(struct_feats)
    ema_b,    ema_r    = _gather(ema_feats)
    noise_b,  noise_r  = _gather(noise_feats)

    ema_available = any(f in pivot for f in ema_feats)

    recommendations = [
        {
            "area":      "sequence_duration_weights",
            "priority":  1,
            "action":    "BOOST" if seq_b else "NEUTRAL",
            "boost":     seq_b,
            "reduce":    seq_r,
            "rationale": (
                f"Timing sequence features are PRIMARY separators. "
                + (f"Boost: {seq_b}. " if seq_b else "")
                + (f"Reduce: {seq_r}." if seq_r else "")
            ),
        },
        {
            "area":      "compression_persistence",
            "priority":  2,
            "action":    "BOOST" if compr_b else "NEUTRAL",
            "boost":     compr_b,
            "reduce":    compr_r,
            "rationale": (
                "Duration metrics (compression_days_pre, atr_contraction_days_pre) separate "
                "better than the binary had_compression. "
                "had_compression is always-on — use day count instead. "
                + (f"Boost: {compr_b}." if compr_b else "")
            ),
        },
        {
            "area":      "volume_sweet_spot",
            "priority":  3,
            "action":    "BOOST" if vol_b else "REDUCE",
            "boost":     vol_b,
            "reduce":    vol_r,
            "rationale": (
                "Volume anomaly is useful but needs calibration. "
                "dryup_day_count_pre (quiet before storm) is often a better signal than "
                "raw max_volume_anomaly. "
                + (f"Boost: {vol_b}. " if vol_b else "")
                + (f"Reduce: {vol_r}." if vol_r else "")
            ),
        },
        {
            "area":      "accumulation_spring_reclaim",
            "priority":  4,
            "action":    "BOOST" if struct_b else "NEUTRAL",
            "boost":     struct_b,
            "reduce":    struct_r,
            "rationale": (
                "Wyckoff structure quality (accumulation_like_day_count, had_spring_test_lps, "
                "reclaim_bar_count_pre) are primary separators. "
                "had_accumulation_like binary may be always-on — prefer day_count. "
                + (f"Boost: {struct_b}." if struct_b else "")
            ),
        },
        {
            "area":      "ema_ribbon_quality",
            "priority":  5,
            "action":    "BOOST" if ema_b else ("PENDING_DATA" if not ema_available else "NEUTRAL"),
            "boost":     ema_b,
            "reduce":    ema_r,
            "delta_available": False,
            "rationale": (
                (
                    f"EMA ribbon episode fields available. "
                    + (f"Boost: {ema_b}. " if ema_b else "Insufficient run count for EMA separation — rerun with more episodes. ")
                    + "Delta bonuses deferred — delta feature extraction not yet in pipeline."
                ) if ema_available else
                "EMA episode fields not yet populated — run pipeline to generate data."
            ),
        },
        {
            "area":      "body_wick_noise_reduction",
            "priority":  6,
            "action":    "REDUCE",
            "boost":     noise_b,
            "reduce":    noise_r or noise_feats,
            "rationale": (
                "Single-bar candle anatomy (body_pct, wick_pct) rarely separates 4x_pump from "
                "sub-4x winners. Scanner v2 priority_scorer already excludes these. "
                + (f"Confirmed low-signal: {noise_r}." if noise_r else "")
            ),
        },
        {
            "area":      "scanner_v2_structural",
            "priority":  7,
            "action":    "BOOST" if (
                any(f in boost_set | increase_set for f in [
                    "had_valid_recent_setup", "had_valid_recent_trigger",
                    "full_fri34_g4_b2_count_pre", "l34_count_pre", "g4_count_pre",
                ])
            ) else "NEUTRAL",
            "boost":     [f for f in [
                "had_valid_recent_setup", "had_valid_recent_trigger",
                "had_valid_full_sequence", "full_fri34_g4_b2_count_pre",
                "l34_count_pre", "g4_count_pre", "b2_count_pre",
            ] if f in boost_set | increase_set],
            "reduce":    [f for f in [
                "setup_only_l34_count_pre", "confirm_after_g4_count_pre",
                "isolated_g4_count_pre", "isolated_b2_count_pre",
            ] if f in penalize_set | reduce_set],
            "rationale": (
                "Scanner v2 structural signals (L34 setup, G4 trigger, B2 confirm, "
                "d_confluence type, structure_phase, compression_expansion_state). "
                "Promote features that separate 4x_pump from false_positive in the NP "
                "signal chain. Confirm_after_g4 and isolated signals are late/noisy — reduce."
            ),
        },
    ]

    return {
        "feature_verdicts": verdicts,
        "recommendations":  recommendations,
        "summary": {
            "boost_count":        len(boost_set),
            "increase_count":     len(increase_set),
            "penalize_count":     len(penalize_set),
            "reduce_count":       len(reduce_set),
            "ignore_count":       len(ignore_set),
            "ema_data_available": ema_available,
            "delta_available":    False,
            "note": (
                "Deterministic plan — no AI. Based on comparison medians only. "
                "Validate counts per group before applying to Scanner v2. "
                "Targets: d_confluence weights, structure_score thresholds, "
                "compression_expansion_state gates, expansion_timing_risk filters."
            ),
        },
    }


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

    return {
        "pump_multiple":                ep_dict.get("pump_multiple"),
        "pump_return_pct":              ep_dict.get("pump_return_pct"),
        "days_to_peak":                 ep_dict.get("days_to_peak"),
        "days_to_double":               ep_dict.get("days_to_double"),
        "max_drawdown_before_peak":     ep_dict.get("max_drawdown_before_peak"),
        "max_volume_anomaly":           max_vol_anomaly,
        "largest_gap_pct":              largest_gap,
        "first_pump_gap_pct":           first_pump_gap,
        "had_compression":              had_compression,
        "strongest_wyckoff_state":      strongest_wyckoff,
        "max_toxicity_score":           max_tox,
        "avg_toxicity_score":           avg_tox,
        "worst_post_return_from_start": worst_post_return_from_start,
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
      3. CATALYST_DRIVEN             — abnormal volume surge with no base
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
    had_compression = features.get("had_compression", False)
    strongest_wyk  = features.get("strongest_wyckoff_state") or "NONE"
    first_gap      = features.get("first_pump_gap_pct") or 0.0
    max_tox        = features.get("max_toxicity_score") or 0
    avg_tox        = features.get("avg_toxicity_score") or 0

    # ── 1. ACCUMULATION_TO_EXPANSION ─────────────────────────────────────────
    # Convergence of multiple accumulation signals before the explosive move.
    acc_score = 0
    if "first_accumulation_like_day"   in event_types: acc_score += 2
    if "first_spring_test_lps_day"     in event_types: acc_score += 2
    if strongest_wyk in ("FIRE", "ARM"):                acc_score += 2
    if strongest_wyk in ("STEALTH_ARM", "STEALTH_BASE"): acc_score += 1
    if had_compression and "breakout_day" in event_types: acc_score += 1
    if "first_abnormal_volume_day"     in event_types: acc_score += 1

    if acc_score >= 4:
        return (
            "ACCUMULATION_TO_EXPANSION",
            f"Convergent accumulation: state={strongest_wyk}, "
            f"spring={'yes' if 'first_spring_test_lps_day' in event_types else 'no'}, "
            f"acc_score={acc_score}",
        )

    # ── 2. POST_COMPRESSION_BREAKOUT ─────────────────────────────────────────
    # BB squeeze in PRE followed by breakout.
    pcb_score = 0
    if had_compression:                 pcb_score += 3
    if "breakout_day" in event_types:   pcb_score += 2
    if acc_score >= 2:                  pcb_score += 1

    if pcb_score >= 4 and had_compression:
        return (
            "POST_COMPRESSION_BREAKOUT",
            f"Squeeze before move: compression={had_compression}, "
            f"breakout={'yes' if 'breakout_day' in event_types else 'no'}, "
            f"pcb_score={pcb_score}",
        )

    # ── 3. CATALYST_DRIVEN ───────────────────────────────────────────────────
    # High abnormal volume surge in PRE without structural base — externally driven.
    if "first_abnormal_volume_day" in event_types and max_vol >= 3.0 and not had_compression:
        return (
            "CATALYST_DRIVEN",
            f"Catalyst-driven surge: max_vol_anomaly={max_vol:.1f}x, no compression base",
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
    no_structure = "first_accumulation_like_day" not in event_types
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
    try:
        from scanner.sector_map import NON_STOCK_SECURITIES
        etf_set = etf_set | NON_STOCK_SECURITIES
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

        # Group B — normal_winner: promote 1.40–3.99x windows into real pump_episode
        # rows so downstream Raw Pattern Study receives snapshots, daily features,
        # episode features, and comparisons identical to 4x_pump.
        # Secondary detection uses already-loaded candle_map — no extra API calls.
        _pump_study_progress["phase"] = "NORMAL_WINNER"
        group_b: list[dict] = []
        nw_ep_dicts_to_save: list[dict] = []
        nw_best_hits_ordered: list[dict] = []

        for sym, candles in candle_map.items():
            all_nw_hits = _detect_raw_pumps(
                sym, candles,
                scan_start   = start_date,
                scan_end     = end_date,
                window_days  = window_days,
                min_multiple = _NORMAL_WINNER_MIN_MULTIPLE,
            )
            sub4x = [h for h in all_nw_hits if h["multiple"] < 4.0]
            if not sub4x:
                continue
            best = max(sub4x, key=lambda h: h["multiple"])
            nw_best_hits_ordered.append(best)
            nw_ep_dicts_to_save.append({
                "run_id":                   run_id,
                "cluster_id":               None,
                "symbol":                   sym,
                "pump_start_date":          best["window_start_date"],
                "pump_peak_date":           best["window_peak_date"],
                "pump_window_days":         best["window_days"],
                "start_price":              best["start_price"],
                "peak_price":               best["peak_price"],
                "pump_multiple":            best["multiple"],
                "pump_return_pct":          best["return_pct"],
                "days_to_peak":             best["days_to_peak"],
                "days_to_double":           best.get("days_to_double"),
                "max_drawdown_before_peak": best.get("max_drawdown_before_peak"),
                "pump_type":                "NORMAL_WINNER",
                "was_in_universe":          True,
                "was_flagged_by_scanner":   False,
                "filter_reason":            None,
                "had_ribbon":               False,
                "had_ignition":             False,
                "sector":                   None,
                "industry":                 None,
                "summary":                  {},
            })

        nw_ep_ids: list[int] = []
        if nw_ep_dicts_to_save:
            nw_ep_ids = await save_pump_episodes(run_id, nw_ep_dicts_to_save)

        for nw_epd, nw_ep_id, nw_best in zip(
            nw_ep_dicts_to_save, nw_ep_ids, nw_best_hits_ordered
        ):
            sym         = nw_epd["symbol"]
            sym_candles = candle_map.get(sym)

            ep_dict_nw = {
                "pump_start_date":          nw_epd["pump_start_date"],
                "pump_peak_date":           nw_epd["pump_peak_date"],
                "start_price":              nw_epd["start_price"],
                "peak_price":               nw_epd["peak_price"],
                "pump_multiple":            nw_epd["pump_multiple"],
                "pump_return_pct":          nw_epd["pump_return_pct"],
                "days_to_peak":             nw_epd["days_to_peak"],
                "days_to_double":           nw_epd.get("days_to_double"),
                "max_drawdown_before_peak": nw_epd.get("max_drawdown_before_peak"),
                "sector":                   None,
                "industry":                 None,
            }

            nw_snaps: list[dict] = []
            nw_evs:   list[dict] = []
            if sym_candles:
                nw_snaps = _build_snapshots(nw_ep_id, run_id, sym, ep_dict_nw, sym_candles)
                if nw_snaps:
                    await save_pump_episode_snapshots(nw_snaps)
                    total_snapshots += len(nw_snaps)
                if nw_snaps:
                    nw_evs = _detect_timeline_events(
                        nw_ep_id, run_id, sym, ep_dict_nw, nw_snaps
                    )
                    if nw_evs:
                        await save_pump_episode_events(nw_evs)
                        total_events += len(nw_evs)

            nw_features = _extract_episode_features(ep_dict_nw, nw_snaps, nw_evs)

            await update_pump_episode_enrichment(nw_ep_id, {
                "pump_type":               "NORMAL_WINNER",
                "strongest_wyckoff_state": nw_features.get("strongest_wyckoff_state"),
                "max_volume_anomaly":      nw_features.get("max_volume_anomaly"),
                "largest_gap_pct":         nw_features.get("largest_gap_pct"),
                "summary_json":            json.dumps({"family_reason": "normal_winner sub-4x window"}),
            })

            group_b.append({
                "run_id":          run_id,
                "group_name":      "normal_winner",
                "symbol":          sym,
                "episode_id":      nw_ep_id,
                "pump_multiple":   nw_epd["pump_multiple"],
                "pump_return_pct": nw_epd["pump_return_pct"],
                "days_to_peak":    nw_epd["days_to_peak"],
                "pump_type":       "NORMAL_WINNER",
                "features":        nw_features,
            })

            _pump_study_progress["snapshots"] = total_snapshots
            _pump_study_progress["events"]    = total_events

            logger.debug(
                f"[PUMP_STUDY][NW] {sym} ep={nw_ep_id}: "
                f"multiple={nw_epd['pump_multiple']:.2f}x, "
                f"snaps={len(nw_snaps)}, evs={len(nw_evs)}"
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
