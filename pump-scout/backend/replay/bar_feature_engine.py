"""
Bar Feature Engine — per-bar detailed feature computation + symbolic tagging
and sequence building for bar-level pattern discovery (V1B).

Consumes sorted OHLCV candles (oldest→newest):
  {"date": str, "open": float, "high": float, "low": float,
   "close": float, "volume": int}

All features use only candles[0..bar_idx] — no future leakage.
Outcome/label fields are NEVER computed here.

Usage:
  features = build_bar_features(candles, bar_idx=-1, splits=[])
  dataset  = build_all_bar_features(symbol, candles, splits=[])

Bar-level discovery (V1B):
  snaps = build_bar_feature_snapshots_for_episode(episode, raw_daily_rows)
  seqs  = build_bar_sequences(snaps, windows=(1, 2, 3, 5, 10))
  tags  = bars_to_tags(snap)
"""

import math
import statistics
from datetime import date, datetime
from typing import Optional

_TINY = 1e-9

# EMA periods used (Fibonacci ribbon + 20, 50 for compatibility)
_EMA_PERIODS = [8, 13, 20, 21, 34, 50, 55, 89, 200]


# ── EMA helpers ───────────────────────────────────────────────────────────────

def _ema_full_series(closes: list[float], period: int) -> list[Optional[float]]:
    """Full EMA series aligned with closes; None for warm-up bars."""
    if len(closes) < period:
        return [None] * len(closes)
    k = 2.0 / (period + 1)
    seed = sum(closes[:period]) / period
    out: list[Optional[float]] = [None] * (period - 1) + [seed]
    for c in closes[period:]:
        out.append(c * k + out[-1] * (1 - k))
    return out


def _sma(vals: list[float], period: int) -> Optional[float]:
    if len(vals) < period:
        return None
    return sum(vals[-period:]) / period


def _stdev_pop(vals: list[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = sum(vals) / len(vals)
    return math.sqrt(sum((x - m) ** 2 for x in vals) / len(vals))


def _percentrank(series: list[float], current: float) -> float:
    if not series:
        return 50.0
    below = sum(1 for x in series if x < current)
    return below / len(series) * 100.0


def _clipped_mean(vals: list[float], pct: float = 0.10) -> float:
    """Trim pct from each tail before taking mean (handles outlier distortion)."""
    if not vals:
        return 0.0
    n = len(vals)
    k = max(0, int(n * pct))
    trimmed = sorted(vals)[k: n - k] if k > 0 else sorted(vals)
    return sum(trimmed) / len(trimmed) if trimmed else 0.0


# ── BB helpers ────────────────────────────────────────────────────────────────

def _bb_width(closes: list[float], period: int = 20, mult: float = 2.0) -> Optional[float]:
    if len(closes) < period:
        return None
    basis = sum(closes[-period:]) / period
    sd = _stdev_pop(closes[-period:])
    if basis <= 0:
        return None
    return (basis + mult * sd - (basis - mult * sd)) / basis


# ── ATR helper ────────────────────────────────────────────────────────────────

def _atr_series(candles: list[dict], period: int = 14) -> list[Optional[float]]:
    """ATR series aligned with candles; None for first period-1 bars."""
    trs: list[float] = []
    for i in range(len(candles)):
        h = candles[i]["high"]
        l = candles[i]["low"]
        if i == 0:
            trs.append(h - l)
        else:
            pc = candles[i - 1]["close"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))

    out: list[Optional[float]] = []
    for i in range(len(trs)):
        if i < period - 1:
            out.append(None)
        elif i == period - 1:
            out.append(sum(trs[:period]) / period)
        else:
            out.append((out[-1] * (period - 1) + trs[i]) / period)  # type: ignore[operator]
    return out


# ── Split context helpers ─────────────────────────────────────────────────────

def _classify_bar_split_context(
    bar_date: str,
    splits: list[dict],
    lookback_days: int = 90,
) -> dict:
    """Classify split context for a single bar date."""
    result = {
        "has_split_near_bar":         False,
        "has_reverse_split_near_bar": False,
        "has_forward_split_near_bar": False,
        "split_days_from_bar":        None,
        "nearest_split_date":         None,
        "nearest_split_type":         None,
        "nearest_split_ratio":        None,
        "reverse_split_0_5d_before":  False,
        "reverse_split_6_15d_before": False,
        "reverse_split_16_30d_before": False,
        "reverse_split_31_60d_before": False,
        "reverse_split_after_bar":    False,
        "split_context":              "NO_SPLIT",
        "split_artifact_risk":        False,
    }

    if not splits or not bar_date:
        return result

    try:
        bd = date.fromisoformat(bar_date)
    except Exception:
        return result

    nearby: list[dict] = []
    for s in splits:
        try:
            sd = date.fromisoformat(s["execution_date"])
            delta = (bd - sd).days  # positive = split was in the past
            if -30 <= delta <= lookback_days:
                nearby.append({**s, "_delta": delta})
        except Exception:
            continue

    if not nearby:
        return result

    nearest = min(nearby, key=lambda x: abs(x["_delta"]))
    result["has_split_near_bar"]   = True
    result["nearest_split_date"]   = nearest["execution_date"]
    result["nearest_split_type"]   = nearest.get("split_type")
    result["nearest_split_ratio"]  = nearest.get("ratio")
    result["split_days_from_bar"]  = nearest["_delta"]

    rev_splits = [s for s in nearby if s.get("split_type") == "REVERSE_SPLIT"]
    fwd_splits = [s for s in nearby if s.get("split_type") == "FORWARD_SPLIT"]

    result["has_reverse_split_near_bar"] = bool(rev_splits)
    result["has_forward_split_near_bar"] = bool(fwd_splits)

    for rs in rev_splits:
        d = rs["_delta"]
        if 0 <= d <= 5:    result["reverse_split_0_5d_before"]   = True
        if 6 <= d <= 15:   result["reverse_split_6_15d_before"]  = True
        if 16 <= d <= 30:  result["reverse_split_16_30d_before"] = True
        if 31 <= d <= 60:  result["reverse_split_31_60d_before"] = True
        if d < 0:          result["reverse_split_after_bar"]     = True

    # Context bucket
    if result["reverse_split_0_5d_before"] or result["reverse_split_6_15d_before"]:
        ctx = "RECENT_REVERSE_SPLIT"
    elif result["reverse_split_16_30d_before"] or result["reverse_split_31_60d_before"]:
        ctx = "OLD_REVERSE_SPLIT"
    elif fwd_splits:
        ctx = "FORWARD_SPLIT"
    elif rev_splits and result["reverse_split_after_bar"]:
        ctx = "FORWARD_SPLIT"  # reverse split in future = doesn't affect this bar
    else:
        ctx = "NO_SPLIT"

    # Artifact risk: reverse split within ±3 days of bar
    if any(abs(rs["_delta"]) <= 3 for rs in rev_splits):
        result["split_artifact_risk"] = True
        ctx = "SPLIT_ARTIFACT_RISK"

    result["split_context"] = ctx
    return result


# ── Main bar feature builder ──────────────────────────────────────────────────

def build_bar_features(
    candles: list[dict],
    bar_idx: int = -1,
    splits: Optional[list[dict]] = None,
    symbol: str = "",
    existing_signals: Optional[dict] = None,
) -> dict:
    """
    Build detailed features for a single bar.

    Parameters
    ----------
    candles         : OHLCV list sorted oldest→newest, dict format
    bar_idx         : which bar to describe (-1 = last)
    splits          : pre-loaded split rows for this symbol
    symbol          : ticker (stored on output, not used in computation)
    existing_signals: dict of signals from scanner (np, d, wlnbb, etc.)

    Returns
    -------
    Flat dict with ~150 features. Outcome fields are NOT included.
    Anti-leakage: uses only candles[0..bar_idx].
    """
    if not candles:
        return {}

    n = len(candles)
    if bar_idx < 0:
        bar_idx = n + bar_idx
    bar_idx = max(0, min(bar_idx, n - 1))

    # Slice to avoid future leakage
    hist = candles[: bar_idx + 1]
    bar  = hist[-1]
    prev = hist[-2] if len(hist) >= 2 else None

    o  = float(bar.get("open")   or 0)
    h  = float(bar.get("high")   or 0)
    l  = float(bar.get("low")    or 0)
    c  = float(bar.get("close")  or 0)
    v  = int(  bar.get("volume") or 0)
    bar_date = bar.get("date") or ""

    po = float(prev["open"]   or 0) if prev else o
    ph = float(prev["high"]   or 0) if prev else h
    pl = float(prev["low"]    or 0) if prev else l
    pc = float(prev["close"]  or 0) if prev else c
    pv = int(  prev["volume"] or 0) if prev else v

    closes  = [float(x.get("close")  or 0) for x in hist]
    opens   = [float(x.get("open")   or 0) for x in hist]
    highs   = [float(x.get("high")   or 0) for x in hist]
    lows    = [float(x.get("low")    or 0) for x in hist]
    volumes = [int(  x.get("volume") or 0) for x in hist]

    feat: dict = {"symbol": symbol, "date": bar_date}

    # ── Basic OHLCV ────────────────────────────────────────────────────────────
    feat.update({
        "open":         o,  "high": h,  "low": l,  "close": c, "volume": v,
        "dollar_volume": round(c * v, 0),
        "prev_open":    po, "prev_high": ph, "prev_low": pl,
        "prev_close":   pc, "prev_volume": pv,
    })

    # ── Candle anatomy ─────────────────────────────────────────────────────────
    bar_range   = max(h - l, _TINY)
    body        = abs(c - o)
    upper_wick  = h - max(c, o)
    lower_wick  = min(c, o) - l

    body_pct       = body / bar_range
    upper_wick_pct = upper_wick / bar_range
    lower_wick_pct = lower_wick / bar_range
    range_pct      = bar_range / max(pc, _TINY) * 100
    close_pos      = (c - l) / bar_range
    open_pos       = (o - l) / bar_range

    is_green = c > o
    is_red   = c < o
    is_doji  = body_pct < 0.10

    # Wide/narrow vs recent bars
    if len(closes) >= 6:
        recent_ranges = [
            float(highs[i] - lows[i]) / max(closes[i], _TINY) * 100
            for i in range(max(0, len(closes) - 6), len(closes) - 1)
        ]
        avg_recent_range = sum(recent_ranges) / len(recent_ranges) if recent_ranges else range_pct
        is_wide_range   = range_pct > avg_recent_range * 1.5
        is_narrow_range = range_pct < avg_recent_range * 0.5
    else:
        is_wide_range   = False
        is_narrow_range = False

    is_inside_bar  = (h <= ph and l >= pl) if prev else False
    is_outside_bar = (h > ph and l < pl) if prev else False

    # Engulfing patterns
    is_bullish_engulfing = (
        prev is not None and pc < po  # prev was red
        and is_green and o < pc and c > po  # current green swallows prev body
    )
    is_bearish_engulfing = (
        prev is not None and pc > po  # prev was green
        and is_red and o > pc and c < po
    )

    is_strong_close = close_pos >= 0.70
    is_weak_close   = close_pos <= 0.30

    breaks_prev_high       = h > ph if prev else False
    breaks_prev_low        = l < pl if prev else False
    closes_above_prev_high = c > ph if prev else False
    closes_below_prev_low  = c < pl if prev else False
    close_reclaims_prev_close = c > pc if prev else False
    close_loses_prev_close    = c < pc if prev else False

    # Reclaim bar: low tests below prev close, close back above
    is_reclaim_bar        = (l < pc and c > pc) if prev else False
    is_failed_reclaim_bar = (l < pc and c < pc and prev and open_pos < close_pos) if prev else False

    feat.update({
        "body_pct":           round(body_pct, 4),
        "upper_wick_pct":     round(upper_wick_pct, 4),
        "lower_wick_pct":     round(lower_wick_pct, 4),
        "range_pct":          round(range_pct, 3),
        "close_position_in_range":  round(close_pos, 4),
        "open_position_in_range":   round(open_pos, 4),
        "body_to_range_ratio":      round(body_pct, 4),
        "is_green":           is_green,
        "is_red":             is_red,
        "is_doji":            is_doji,
        "is_wide_range":      is_wide_range,
        "is_narrow_range":    is_narrow_range,
        "is_inside_bar":      is_inside_bar,
        "is_outside_bar":     is_outside_bar,
        "is_bullish_engulfing":  is_bullish_engulfing,
        "is_bearish_engulfing":  is_bearish_engulfing,
        "is_strong_close":    is_strong_close,
        "is_weak_close":      is_weak_close,
        "is_reclaim_bar":     is_reclaim_bar,
        "is_failed_reclaim_bar": is_failed_reclaim_bar,
        "breaks_prev_high":         breaks_prev_high,
        "breaks_prev_low":          breaks_prev_low,
        "closes_above_prev_high":   closes_above_prev_high,
        "closes_below_prev_low":    closes_below_prev_low,
        "close_reclaims_prev_close": close_reclaims_prev_close,
        "close_loses_prev_close":   close_loses_prev_close,
    })

    # ── Gap features ──────────────────────────────────────────────────────────
    gap_pct      = (o - pc) / max(pc, _TINY) * 100 if prev else 0.0
    gap_up_pct   = max(gap_pct, 0.0)
    gap_down_pct = min(gap_pct, 0.0)
    gap_abs_pct  = abs(gap_pct)
    has_gap_up   = gap_pct >= 2.0
    has_gap_down = gap_pct <= -2.0

    # Gap fill: did price trade back into gap zone same day?
    gap_filled_same_day = False
    gap_fill_ratio      = 0.0
    if has_gap_up and prev:
        gap_zone_high = o
        gap_zone_low  = ph
        if l <= gap_zone_low:
            gap_filled_same_day = True
            gap_fill_ratio      = 1.0
        elif l < gap_zone_high:
            gap_fill_ratio = (gap_zone_high - l) / max(gap_zone_high - gap_zone_low, _TINY)
    elif has_gap_down and prev:
        gap_zone_low  = o
        gap_zone_high = pl
        if h >= gap_zone_high:
            gap_filled_same_day = True
            gap_fill_ratio      = 1.0
        elif h > gap_zone_low:
            gap_fill_ratio = (h - gap_zone_low) / max(gap_zone_high - gap_zone_low, _TINY)

    gap_hold   = has_gap_up and not gap_filled_same_day and is_green
    gap_failed = has_gap_up and gap_fill_ratio >= 0.8 and is_red

    # Gap down reclaim same day = gap down but closed back above prev close
    gap_down_reclaim_same_day = has_gap_down and close_reclaims_prev_close
    gap_up_failed_same_day    = has_gap_up and not is_strong_close and close_pos < 0.40

    # Gap relative to EMAs (computed after EMA section)
    feat.update({
        "gap_up_pct":              round(gap_up_pct, 3),
        "gap_down_pct":            round(gap_down_pct, 3),
        "gap_abs_pct":             round(gap_abs_pct, 3),
        "has_gap_up":              has_gap_up,
        "has_gap_down":            has_gap_down,
        "gap_filled_same_day":     gap_filled_same_day,
        "gap_fill_ratio":          round(gap_fill_ratio, 3),
        "gap_hold":                gap_hold,
        "gap_failed":              gap_failed,
        "gap_down_reclaim_same_day": gap_down_reclaim_same_day,
        "gap_up_failed_same_day":  gap_up_failed_same_day,
    })

    # ── EMA context ───────────────────────────────────────────────────────────
    ema_vals: dict[int, Optional[float]] = {}
    ema_series_map: dict[int, list[Optional[float]]] = {}
    for p in _EMA_PERIODS:
        if len(closes) >= p:
            series = _ema_full_series(closes, p)
            ema_vals[p]    = series[-1]
            ema_series_map[p] = series
        else:
            ema_vals[p]    = None
            ema_series_map[p] = [None] * len(closes)

    # Convenient aliases
    e8   = ema_vals.get(8)
    e13  = ema_vals.get(13)
    e20  = ema_vals.get(20)
    e21  = ema_vals.get(21)
    e34  = ema_vals.get(34)
    e50  = ema_vals.get(50)
    e55  = ema_vals.get(55)
    e89  = ema_vals.get(89)
    e200 = ema_vals.get(200)

    def _vs_ema(val: Optional[float]) -> Optional[float]:
        if val is None or val <= 0:
            return None
        return round((c - val) / val * 100, 3)

    feat.update({
        "ema8":   round(e8,  4) if e8  is not None else None,
        "ema13":  round(e13, 4) if e13 is not None else None,
        "ema20":  round(e20, 4) if e20 is not None else None,
        "ema21":  round(e21, 4) if e21 is not None else None,
        "ema34":  round(e34, 4) if e34 is not None else None,
        "ema50":  round(e50, 4) if e50 is not None else None,
        "ema55":  round(e55, 4) if e55 is not None else None,
        "ema89":  round(e89, 4) if e89 is not None else None,
        "ema200": round(e200,4) if e200 is not None else None,
        "close_vs_ema8_pct":   _vs_ema(e8),
        "close_vs_ema13_pct":  _vs_ema(e13),
        "close_vs_ema20_pct":  _vs_ema(e20),
        "close_vs_ema21_pct":  _vs_ema(e21),
        "close_vs_ema34_pct":  _vs_ema(e34),
        "close_vs_ema50_pct":  _vs_ema(e50),
        "close_vs_ema55_pct":  _vs_ema(e55),
        "close_vs_ema89_pct":  _vs_ema(e89),
        "close_vs_ema200_pct": _vs_ema(e200),
    })

    # EMA crossing (open below, close above — or vice versa)
    def _crossed_up(period: int) -> bool:
        s = ema_series_map.get(period, [])
        if len(s) < 2 or s[-1] is None or s[-2] is None:
            return False
        prev_c = closes[-2] if len(closes) >= 2 else 0
        return prev_c <= s[-2] and c > s[-1]  # type: ignore[operator]

    def _crossed_down(period: int) -> bool:
        s = ema_series_map.get(period, [])
        if len(s) < 2 or s[-1] is None or s[-2] is None:
            return False
        prev_c = closes[-2] if len(closes) >= 2 else 0
        return prev_c >= s[-2] and c < s[-1]  # type: ignore[operator]

    def _open_below_close_above(period: int) -> bool:
        ev = ema_vals.get(period)
        if ev is None:
            return False
        return o < ev and c > ev

    crossed_periods = [8, 13, 20, 34, 50, 89, 200]
    crossed_up_flags:   dict[int, bool] = {p: _crossed_up(p)   for p in crossed_periods}
    crossed_down_flags: dict[int, bool] = {p: _crossed_down(p) for p in crossed_periods}
    crossed_up_count   = sum(crossed_up_flags.values())
    crossed_down_count = sum(crossed_down_flags.values())

    feat.update({
        "open_below_close_above_ema8":   _open_below_close_above(8),
        "open_below_close_above_ema13":  _open_below_close_above(13),
        "open_below_close_above_ema20":  _open_below_close_above(20),
        "open_below_close_above_ema34":  _open_below_close_above(34),
        "open_below_close_above_ema50":  _open_below_close_above(50),
        "open_below_close_above_ema89":  _open_below_close_above(89),
        "open_below_close_above_ema200": _open_below_close_above(200),
        "crossed_ema8":   crossed_up_flags[8],
        "crossed_ema13":  crossed_up_flags[13],
        "crossed_ema20":  crossed_up_flags[20],
        "crossed_ema34":  crossed_up_flags[34],
        "crossed_ema50":  crossed_up_flags[50],
        "crossed_ema89":  crossed_up_flags[89],
        "crossed_ema200": crossed_up_flags[200],
        "crossed_up_count":      crossed_up_count,
        "crossed_down_count":    crossed_down_count,
        "ema_cross_count_total": crossed_up_count + crossed_down_count,
    })

    # EMA50 special cases
    low_below_ema50_close_above = (e50 is not None and l < e50 and c > e50)
    high_above_ema50_close_below = (e50 is not None and h > e50 and c < e50)
    ema50_reclaim_bar  = low_below_ema50_close_above
    ema50_reject_bar   = high_above_ema50_close_below

    feat.update({
        "low_below_ema50_close_above":   low_below_ema50_close_above,
        "high_above_ema50_close_below":  high_above_ema50_close_below,
        "ema50_reclaim_bar":             ema50_reclaim_bar,
        "ema50_reject_bar":              ema50_reject_bar,
    })

    # Gap into EMA zones
    if has_gap_up:
        feat["gap_into_ema8"]   = e8  is not None and ph < e8  <= o
        feat["gap_into_ema20"]  = e20 is not None and ph < e20 <= o
        feat["gap_into_ema34"]  = e34 is not None and ph < e34 <= o
        feat["gap_into_ema50"]  = e50 is not None and ph < e50 <= o
        feat["gap_over_ema50"]  = e50 is not None and o > e50
        feat["gap_under_ema50"] = e50 is not None and o < e50
        feat["gap_over_prev_high"]  = True
        feat["gap_below_prev_low"]  = False
    elif has_gap_down:
        feat["gap_into_ema8"]   = False
        feat["gap_into_ema20"]  = False
        feat["gap_into_ema34"]  = False
        feat["gap_into_ema50"]  = e50 is not None and pl > e50 >= o
        feat["gap_over_ema50"]  = False
        feat["gap_under_ema50"] = e50 is not None and o < e50
        feat["gap_over_prev_high"]  = False
        feat["gap_below_prev_low"]  = True
    else:
        for k in ["gap_into_ema8","gap_into_ema20","gap_into_ema34","gap_into_ema50",
                  "gap_over_ema50","gap_under_ema50","gap_over_prev_high","gap_below_prev_low"]:
            feat[k] = False

    # EMA ribbon state
    ribbon_vals = [(p, ema_vals[p]) for p in [8, 13, 21, 34, 55, 89, 200] if ema_vals.get(p) is not None]
    if len(ribbon_vals) >= 3:
        rv = [v for _, v in ribbon_vals]
        ema_max = max(rv)
        ema_min = min(rv)
        ema_spread = (ema_max - ema_min) / max(c, _TINY) * 100

        above_all  = all(c > v for _, v in ribbon_vals)
        below_all  = all(c < v for _, v in ribbon_vals)
        emav_sorted_asc = [v for _, v in sorted(ribbon_vals, key=lambda x: x[0])]

        bull_ordered = all(emav_sorted_asc[i] > emav_sorted_asc[i+1] for i in range(len(emav_sorted_asc)-1))
        bear_ordered = all(emav_sorted_asc[i] < emav_sorted_asc[i+1] for i in range(len(emav_sorted_asc)-1))

        ema_stack_state = (
            "BULL" if (above_all and bull_ordered) else
            "BEAR" if (below_all and bear_ordered) else
            "MIXED"
        )

        if ema_spread < 1.0:
            ribbon_compression = "STRONG"
        elif ema_spread < 2.5:
            ribbon_compression = "MEDIUM"
        elif ema_spread < 5.0:
            ribbon_compression = "WEAK"
        else:
            ribbon_compression = "NONE"
    else:
        ema_spread         = None
        ema_stack_state    = "UNKNOWN"
        ribbon_compression = "NONE"

    # Rolling 20-day EMA spread history (clipped mean to avoid outlier distortion)
    ema_spreads_20d: list[float] = []
    if len(closes) >= 25:
        for _i in range(max(0, len(closes) - 20), len(closes)):
            _rv = []
            for p in [8, 13, 21, 34, 55, 89, 200]:
                s = ema_series_map.get(p)
                if s and _i < len(s) and s[_i] is not None:
                    _rv.append(s[_i])
            if len(_rv) >= 3:
                _ema_spread = (max(_rv) - min(_rv)) / max(closes[_i], _TINY) * 100
                ema_spreads_20d.append(_ema_spread)

    min_ema_spread_20d      = min(ema_spreads_20d) if ema_spreads_20d else None
    avg_ema_spread_20d      = sum(ema_spreads_20d) / len(ema_spreads_20d) if ema_spreads_20d else None
    clipped_avg_ema_spread_20d = round(_clipped_mean(ema_spreads_20d), 4) if ema_spreads_20d else None
    ema_ribbon_compression  = ribbon_compression

    # Count consecutive bull-stack bars
    ema_cluster_reclaim_count = min(crossed_up_count, 3)
    ema_cluster_reject_count  = min(crossed_down_count, 3)

    feat.update({
        "ema_spread":                round(ema_spread, 3) if ema_spread is not None else None,
        "min_ema_spread_20d":        round(min_ema_spread_20d, 3) if min_ema_spread_20d is not None else None,
        "avg_ema_spread_20d":        round(avg_ema_spread_20d, 3) if avg_ema_spread_20d is not None else None,
        "clipped_avg_ema_spread_20d": clipped_avg_ema_spread_20d,
        "ema_ribbon_compression":    ema_ribbon_compression,
        "ema_stack_state":           ema_stack_state,
        "ema_cluster_reclaim_count": ema_cluster_reclaim_count,
        "ema_cluster_reject_count":  ema_cluster_reject_count,
    })

    # ── Volume features ───────────────────────────────────────────────────────
    avg_vol_20 = (
        sum(volumes[-21:-1]) / 20 if len(volumes) >= 21
        else (sum(volumes[:-1]) / max(len(volumes) - 1, 1) if len(volumes) > 1 else v)
    )
    avg_vol_5  = (
        sum(volumes[-6:-1]) / 5 if len(volumes) >= 6
        else avg_vol_20
    )
    avg_vol_3  = (
        sum(volumes[-4:-1]) / 3 if len(volumes) >= 4
        else avg_vol_20
    )

    vol_z = 0.0
    if len(volumes) >= 5:
        window_v = volumes[-21:-1] if len(volumes) >= 21 else volumes[:-1]
        if window_v:
            m_v = sum(window_v) / len(window_v)
            sd_v = _stdev_pop(window_v)
            vol_z = (v - m_v) / max(sd_v, _TINY)

    dv = c * v
    dollar_volumes = [float(x.get("close") or 0) * int(x.get("volume") or 0) for x in hist]
    avg_dv_20 = (
        sum(dollar_volumes[-21:-1]) / 20 if len(dollar_volumes) >= 21
        else (sum(dollar_volumes[:-1]) / max(len(dollar_volumes) - 1, 1))
    )
    dv_z = 0.0
    if len(dollar_volumes) >= 5:
        window_dv = dollar_volumes[-21:-1] if len(dollar_volumes) >= 21 else dollar_volumes[:-1]
        if window_dv:
            m_dv = sum(window_dv) / len(window_dv)
            sd_dv = _stdev_pop(window_dv)
            dv_z = (dv - m_dv) / max(sd_dv, _TINY)

    relative_volume_20d        = v / max(avg_vol_20, _TINY)
    relative_dollar_volume_20d = dv / max(avg_dv_20, _TINY)
    volume_vs_prev_bar         = v / max(pv, _TINY)
    volume_vs_prev_3bar_avg    = v / max(avg_vol_3, _TINY)
    volume_vs_prev_5bar_avg    = v / max(avg_vol_5, _TINY)

    # Dry-up: volume < 0.6 × 20d avg
    DRYUP_THRESHOLD = 0.6
    ABNORMAL_THRESHOLD = 2.0

    def _count_dryup(n_bars: int) -> int:
        win = volumes[-n_bars - 1:-1] if len(volumes) > n_bars else volumes[:-1]
        avg = sum(win) / max(len(win), 1)
        return sum(1 for x in win if x < avg * DRYUP_THRESHOLD)

    def _count_abnormal(n_bars: int) -> int:
        win = volumes[-n_bars - 1:-1] if len(volumes) > n_bars else volumes[:-1]
        avg = sum(win) / max(len(win), 1)
        return sum(1 for x in win if x > avg * ABNORMAL_THRESHOLD)

    dryup_count_5d   = _count_dryup(5)
    dryup_count_10d  = _count_dryup(10)
    dryup_count_20d  = _count_dryup(20)
    abnormal_volume_count_5d  = _count_abnormal(5)
    abnormal_volume_count_10d = _count_abnormal(10)
    abnormal_volume_count_20d = _count_abnormal(20)

    extreme_volume_anomaly = vol_z > 4.0

    # Dry-up streak (consecutive bars before this one)
    volume_dryup_streak = 0
    if len(volumes) >= 2:
        win_avg = sum(volumes[-21:-1]) / 20 if len(volumes) >= 21 else avg_vol_20
        for _i in range(len(volumes) - 2, -1, -1):
            if volumes[_i] < win_avg * DRYUP_THRESHOLD:
                volume_dryup_streak += 1
            else:
                break

    # Expansion after dry-up
    prev_dryup = dryup_count_5d >= 2 or volume_dryup_streak >= 2
    volume_expansion_after_dryup        = prev_dryup and relative_volume_20d >= 2.0
    dollar_volume_expansion_after_dryup = prev_dryup and relative_dollar_volume_20d >= 2.0

    feat.update({
        "volume_z":                     round(vol_z, 3),
        "dollar_volume_z":              round(dv_z, 3),
        "relative_volume_20d":          round(relative_volume_20d, 3),
        "relative_dollar_volume_20d":   round(relative_dollar_volume_20d, 3),
        "volume_vs_prev_bar":           round(volume_vs_prev_bar, 3),
        "volume_vs_prev_3bar_avg":      round(volume_vs_prev_3bar_avg, 3),
        "volume_vs_prev_5bar_avg":      round(volume_vs_prev_5bar_avg, 3),
        "volume_dryup_streak":          volume_dryup_streak,
        "dryup_count_5d":               dryup_count_5d,
        "dryup_count_10d":              dryup_count_10d,
        "dryup_count_20d":              dryup_count_20d,
        "abnormal_volume_count_5d":     abnormal_volume_count_5d,
        "abnormal_volume_count_10d":    abnormal_volume_count_10d,
        "abnormal_volume_count_20d":    abnormal_volume_count_20d,
        "extreme_volume_anomaly":       extreme_volume_anomaly,
        "volume_expansion_after_dryup":        volume_expansion_after_dryup,
        "dollar_volume_expansion_after_dryup": dollar_volume_expansion_after_dryup,
    })

    # ── Approximate delta volume ──────────────────────────────────────────────
    approx_delta_body           = v * ((c - o) / bar_range)
    approx_delta_close_location = v * (2 * close_pos - 1)

    delta_z = 0.0
    _delta_series_hist = [
        int(x.get("volume") or 0) * (
            2 * ((float(x.get("close") or 0) - float(x.get("low") or 0))
                 / max(float(x.get("high") or 0) - float(x.get("low") or 0), _TINY)) - 1
        )
        for x in hist[:-1]
    ]
    if len(_delta_series_hist) >= 5:
        _dm = sum(_delta_series_hist) / len(_delta_series_hist)
        _ds = _stdev_pop(_delta_series_hist) if len(_delta_series_hist) >= 2 else _TINY
        delta_z = (approx_delta_close_location - _dm) / max(_ds, _TINY)

    positive_delta_bar = approx_delta_close_location > 0
    negative_delta_bar = approx_delta_close_location < 0

    # Delta divergence: high delta but price struggled
    delta_divergence_positive = (
        approx_delta_close_location > 0
        and close_pos < 0.40  # delta says buy pressure, price closed weak
    )
    delta_divergence_negative = (
        approx_delta_close_location < 0
        and close_pos > 0.60  # delta says sell pressure, price closed strong
    )

    positive_delta_small_body = positive_delta_bar and body_pct < 0.30
    negative_delta_recovery   = negative_delta_bar and lower_wick_pct > 0.30 and close_pos > 0.50

    # Delta ignition: large positive delta with range expansion
    range_expansion = is_wide_range
    delta_ignition = (
        delta_z > 2.0
        and vol_z > 2.0
        and close_pos > 0.75
        and range_expansion
    )

    # Delta absorption: selling pressure absorbed — body small, strong lower wick, closes mid+
    delta_absorption = (
        (is_red or body_pct < 0.25)
        and lower_wick_pct > 0.30
        and close_pos > 0.50
        and approx_delta_close_location > -abs(approx_delta_body) * 0.5
    )

    feat.update({
        "approx_delta_body":           round(approx_delta_body, 0),
        "approx_delta_close_location": round(approx_delta_close_location, 0),
        "approx_delta_z":              round(delta_z, 3),
        "positive_delta_bar":          positive_delta_bar,
        "negative_delta_bar":          negative_delta_bar,
        "delta_divergence_positive":   delta_divergence_positive,
        "delta_divergence_negative":   delta_divergence_negative,
        "positive_delta_small_body":   positive_delta_small_body,
        "negative_delta_recovery":     negative_delta_recovery,
        "delta_ignition":              delta_ignition,
        "delta_absorption":            delta_absorption,
    })

    # ── Compression / volatility ──────────────────────────────────────────────
    bb_w = _bb_width(closes)
    bb_width = bb_w if bb_w is not None else None

    # BB width percentile over last 60 bars
    bb_width_pcts: list[float] = []
    for _i in range(max(20, len(closes) - 60), len(closes) - 1):
        _w = _bb_width(closes[:_i + 1])
        if _w is not None:
            bb_width_pcts.append(_w)
    bb_width_percentile = _percentrank(bb_width_pcts, bb_w) if bb_w is not None and bb_width_pcts else 50.0
    compression_active  = bb_width_percentile < 25.0 if bb_w is not None else False

    # Min BB width in 20d
    min_bb_width_20d = min(
        (bw for bw in bb_width_pcts[-20:] if bw is not None), default=None
    )

    # ATR
    atr_s   = _atr_series(hist)
    atr_val = atr_s[-1]
    atr_pct = (atr_val / max(c, _TINY) * 100) if atr_val is not None else None

    # ATR contraction: current ATR < 80% of 20d average ATR
    atr_vals_20d = [x for x in atr_s[-21:-1] if x is not None]
    avg_atr_20d  = sum(atr_vals_20d) / len(atr_vals_20d) if atr_vals_20d else None
    atr_contraction_active = (
        atr_val is not None and avg_atr_20d is not None and atr_val < avg_atr_20d * 0.80
    )

    # Count compression days in last 20 bars
    compression_days_20d = sum(1 for bw in bb_width_pcts[-20:] if bw is not None and _percentrank(bb_width_pcts, bw) < 25)
    atr_contraction_days_20d = 0
    if avg_atr_20d:
        atr_contraction_days_20d = sum(
            1 for av in atr_vals_20d if av < avg_atr_20d * 0.80
        )

    # Range contraction
    range_vals_20d = [
        (float(x.get("high") or 0) - float(x.get("low") or 0)) / max(float(x.get("close") or 1), _TINY) * 100
        for x in hist[-21:-1]
    ]
    avg_range_20d = sum(range_vals_20d) / len(range_vals_20d) if range_vals_20d else range_pct
    range_contraction_days_20d = sum(1 for r in range_vals_20d if r < avg_range_20d * 0.70)

    # Expansion bar: range expands significantly vs recent
    expansion_bar = range_pct > avg_range_20d * 1.5 if avg_range_20d > 0 else False
    expansion_after_compression = expansion_bar and compression_active

    # Overheated: extreme range + high close position after a run
    # Count consecutive up days
    consec_up = 0
    for _i in range(len(closes) - 1, 0, -1):
        if closes[_i] > closes[_i - 1]:
            consec_up += 1
        else:
            break

    # Expansion risk levels
    overheated_expansion = expansion_bar and consec_up >= 3 and close_pos > 0.80
    high_expansion_risk  = expansion_bar and (vol_z > 3 or consec_up >= 5)

    feat.update({
        "bb_width":                  round(bb_width, 6) if bb_width is not None else None,
        "bb_width_percentile":       round(bb_width_percentile, 1),
        "min_bb_width_20d":          round(min_bb_width_20d, 6) if min_bb_width_20d is not None else None,
        "compression_active":        compression_active,
        "compression_days_20d":      compression_days_20d,
        "atr_pct":                   round(atr_pct, 3) if atr_pct is not None else None,
        "atr_contraction_active":    atr_contraction_active,
        "atr_contraction_days_20d":  atr_contraction_days_20d,
        "range_contraction_days_20d": range_contraction_days_20d,
        "expansion_bar":             expansion_bar,
        "expansion_after_compression": expansion_after_compression,
        "high_expansion_risk":       high_expansion_risk,
        "overheated_expansion":      overheated_expansion,
    })

    # ── Gap after patterns (requires history context) ─────────────────────────
    feat["gap_after_dryup"]         = has_gap_up and dryup_count_5d >= 2
    feat["gap_after_d_confluence"]  = False  # filled from existing_signals below
    feat["gap_after_l34"]           = False  # filled from existing_signals below

    # ── Existing signal context ───────────────────────────────────────────────
    sig = existing_signals or {}
    feat.update({
        "has_l34":                    sig.get("has_l34", False),
        "has_l43":                    sig.get("has_l43", False),
        "has_l22":                    sig.get("has_l22", False),
        "has_l64":                    sig.get("has_l64", False),
        "has_fri34":                  sig.get("has_fri34", False),
        "has_fri64":                  sig.get("has_fri64", False),
        "has_beup":                   sig.get("has_beup", False),
        "has_d_confluence":           sig.get("has_d_confluence", False),
        "d_confluence_type":          sig.get("d_confluence_type"),
        "d_confluence_family":        sig.get("d_confluence_family"),
        "structure_phase":            sig.get("structure_phase"),
        "structure_score":            sig.get("structure_score"),
        "compression_expansion_state": sig.get("compression_expansion_state"),
        "expansion_timing_risk":      sig.get("expansion_timing_risk"),
        "scanner_v2_decision":        sig.get("scanner_v2_decision"),
        "np_sequence_type":           sig.get("np_sequence_type"),
        "np_is_setup":                sig.get("np_is_setup", False),
        "np_is_trigger":              sig.get("np_is_trigger", False),
        "np_is_confirm":              sig.get("np_is_confirm", False),
        "wlnbb_state":                sig.get("wlnbb_state"),
    })

    if sig.get("has_l34") and has_gap_up:
        feat["gap_after_l34"] = True
    if sig.get("has_d_confluence") and has_gap_up:
        feat["gap_after_d_confluence"] = True

    # ── Split context ─────────────────────────────────────────────────────────
    split_ctx = _classify_bar_split_context(bar_date, splits or [])
    feat.update(split_ctx)

    return feat


# ── Dataset builder ───────────────────────────────────────────────────────────

def build_all_bar_features(
    symbol: str,
    candles: list[dict],
    splits: Optional[list[dict]] = None,
    existing_signals_by_date: Optional[dict[str, dict]] = None,
    min_bars: int = 30,
) -> list[dict]:
    """
    Build bar features for every bar in candles (oldest→newest).
    Returns a list of feature dicts, one per bar (bars < min_bars omitted).

    existing_signals_by_date: {"2025-01-15": {"has_l34": True, ...}, ...}
    """
    results: list[dict] = []
    sp = splits or []
    sbd = existing_signals_by_date or {}

    for i in range(min_bars, len(candles)):
        bar_date = candles[i].get("date") or ""
        sig = sbd.get(bar_date)
        feat = build_bar_features(
            candles=candles,
            bar_idx=i,
            splits=sp,
            symbol=symbol,
            existing_signals=sig,
        )
        if feat:
            results.append(feat)

    return results


# ── Pre-window aggregate builder ──────────────────────────────────────────────

def build_pre_window_bar_summary(
    bar_features_window: list[dict],
) -> dict:
    """
    Aggregate per-bar features over a pre-pump window into episode-level stats.
    The window should contain only bars strictly before breakout.
    Returns a flat summary dict suitable for pattern matching.
    """
    if not bar_features_window:
        return {}

    n = len(bar_features_window)

    def _bool_count(key: str) -> int:
        return sum(1 for f in bar_features_window if f.get(key))

    def _mean(key: str) -> Optional[float]:
        vals = [f[key] for f in bar_features_window if f.get(key) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    def _max(key: str) -> Optional[float]:
        vals = [f[key] for f in bar_features_window if f.get(key) is not None]
        return max(vals) if vals else None

    def _min(key: str) -> Optional[float]:
        vals = [f[key] for f in bar_features_window if f.get(key) is not None]
        return min(vals) if vals else None

    # Streaks (look for longest consecutive run of a boolean flag being True)
    def _max_streak(key: str) -> int:
        best = cur = 0
        for f in bar_features_window:
            if f.get(key):
                cur += 1
                best = max(best, cur)
            else:
                cur = 0
        return best

    return {
        "bar_count":                   n,
        # Candle anatomy counts
        "bullish_engulfing_count":     _bool_count("is_bullish_engulfing"),
        "bearish_engulfing_count":     _bool_count("is_bearish_engulfing"),
        "inside_bar_count":            _bool_count("is_inside_bar"),
        "outside_bar_count":           _bool_count("is_outside_bar"),
        "reclaim_bar_count":           _bool_count("is_reclaim_bar"),
        "strong_close_count":          _bool_count("is_strong_close"),
        "expansion_bar_count":         _bool_count("expansion_bar"),
        "wide_range_bar_count":        _bool_count("is_wide_range"),
        "narrow_range_bar_count":      _bool_count("is_narrow_range"),
        "green_bar_count":             _bool_count("is_green"),
        # Gap counts
        "gap_up_count":                _bool_count("has_gap_up"),
        "gap_down_count":              _bool_count("has_gap_down"),
        "gap_hold_count":              _bool_count("gap_hold"),
        "gap_failed_count":            _bool_count("gap_failed"),
        "gap_down_reclaim_count":      _bool_count("gap_down_reclaim_same_day"),
        # EMA counts
        "ema50_reclaim_bar_count":     _bool_count("ema50_reclaim_bar"),
        "ema50_reject_bar_count":      _bool_count("ema50_reject_bar"),
        "ema_cluster_reclaim_events":  _bool_count("open_below_close_above_ema50"),
        "bull_stack_count":            _bool_count("is_strong_close"),
        "days_above_ema50":            sum(
            1 for f in bar_features_window if (f.get("close_vs_ema50_pct") or -99) > 0
        ),
        # Volume / delta counts
        "dryup_bar_count":             _bool_count("volume_dryup_streak"),
        "abnormal_volume_count":       _bool_count("extreme_volume_anomaly"),
        "delta_ignition_count":        _bool_count("delta_ignition"),
        "delta_absorption_count":      _bool_count("delta_absorption"),
        "volume_expansion_after_dryup_count": _bool_count("volume_expansion_after_dryup"),
        # Compression counts
        "compression_active_count":    _bool_count("compression_active"),
        "atr_contraction_active_count": _bool_count("atr_contraction_active"),
        "expansion_after_compression_count": _bool_count("expansion_after_compression"),
        # Split counts
        "split_artifact_bar_count":    _bool_count("split_artifact_risk"),
        # Averages
        "avg_body_pct":                _mean("body_pct"),
        "avg_lower_wick_pct":          _mean("lower_wick_pct"),
        "avg_upper_wick_pct":          _mean("upper_wick_pct"),
        "avg_volume_z":                _mean("volume_z"),
        "avg_close_vs_ema50_pct":      _mean("close_vs_ema50_pct"),
        "avg_close_vs_ema200_pct":     _mean("close_vs_ema200_pct"),
        "avg_bb_width_percentile":     _mean("bb_width_percentile"),
        "avg_relative_volume_20d":     _mean("relative_volume_20d"),
        # Max values
        "max_volume_z":                _max("volume_z"),
        "max_delta_z":                 _max("approx_delta_z"),
        "max_bb_width_percentile":     _max("bb_width_percentile"),
        "max_dryup_streak":            max(
            (f.get("volume_dryup_streak") or 0 for f in bar_features_window), default=0
        ),
        "max_dryup_10d":               max(
            (f.get("dryup_count_10d") or 0 for f in bar_features_window), default=0
        ),
        "min_bb_width":                _min("bb_width"),
        "min_ema_spread":              _min("clipped_avg_ema_spread_20d"),
        # Streaks
        "max_compression_streak":      _max_streak("compression_active"),
        "max_bull_ema_stack_streak":   _max_streak("is_strong_close"),
    }


# ── Symbolic tag constants ─────────────────────────────────────────────────────

TAG_STRONG_CLOSE       = "STRONG_CLOSE"
TAG_WEAK_CLOSE         = "WEAK_CLOSE"
TAG_LOWER_WICK_RECLAIM = "LOWER_WICK_RECLAIM"
TAG_GAP_UP             = "GAP_UP"
TAG_GAP_UP_HOLD        = "GAP_UP_HOLD"
TAG_GAP_DOWN           = "GAP_DOWN"
TAG_GAP_DOWN_RECLAIM   = "GAP_DOWN_RECLAIM"
TAG_EMA50_RECLAIM      = "EMA50_RECLAIM"
TAG_EMA_BULL_STACK     = "EMA_BULL_STACK"
TAG_DRYUP              = "DRYUP"
TAG_VOLUME_SPIKE       = "VOL_SPIKE"
TAG_DELTA_IGNITION     = "DELTA_IGNITION"
TAG_DELTA_ABSORPTION   = "DELTA_ABSORPTION"
TAG_BB_COMPRESSION     = "BB_COMPRESS"
TAG_EXPANSION          = "EXPANSION"
TAG_BULL_ENGULF        = "BULL_ENGULF"
TAG_INSIDE_BAR         = "INSIDE_BAR"
TAG_RECLAIM_BAR        = "RECLAIM_BAR"
TAG_WIDE_RANGE         = "WIDE_RANGE"
TAG_L34                = "L34"
TAG_NP_SETUP           = "NP_SETUP"
TAG_NP_TRIGGER         = "NP_TRIGGER"
TAG_FLAT               = "FLAT"

# 260521 Line3/4/5 tags
TAG_BODY_X             = "BODY_X"      # extra-large body (>1.5× avg)
TAG_BODY_S             = "BODY_S"      # small body (<0.5× avg)
TAG_WICK_TB            = "WICK_TB"     # top wick dominant (≥50% of range)
TAG_WICK_BB            = "WICK_BB"     # bottom wick dominant (≥50% of range)
TAG_WICK_J             = "WICK_J"      # doji / spinning top (body ≤20% of range)
TAG_WICK_F             = "WICK_F"      # full body, small wicks
TAG_GAP_G2             = "GAP_G2"      # gap 0.5–1.0 ATR
TAG_GAP_G3             = "GAP_G3"      # gap >1.0 ATR
TAG_RANGE_V            = "RANGE_V"     # volatile range (>1.5 ATR)
TAG_RANGE_C            = "RANGE_C"     # compressed range (<0.5 ATR)
TAG_VIX_X              = "VIX_X"       # Williams VIX-Fix spike
TAG_VIX_R              = "VIX_R"       # Williams VIX-Fix range
TAG_PSAR_BULL          = "PSAR_BULL"   # Parabolic SAR bullish (close > SAR)
TAG_PSAR_BEAR          = "PSAR_BEAR"   # Parabolic SAR bearish (close ≤ SAR)
TAG_RSI2_X             = "RSI2_X"      # RSI2 reclaim above 20
TAG_RSI2_D             = "RSI2_D"      # RSI2 drop below 80
TAG_RSI2_L             = "RSI2_L"      # RSI2 oversold (< 20)
TAG_RSI2_H             = "RSI2_H"      # RSI2 overbought (> 80)

ALL_TAGS = [
    TAG_STRONG_CLOSE, TAG_WEAK_CLOSE, TAG_LOWER_WICK_RECLAIM,
    TAG_GAP_UP, TAG_GAP_UP_HOLD, TAG_GAP_DOWN, TAG_GAP_DOWN_RECLAIM,
    TAG_EMA50_RECLAIM, TAG_EMA_BULL_STACK,
    TAG_DRYUP, TAG_VOLUME_SPIKE,
    TAG_DELTA_IGNITION, TAG_DELTA_ABSORPTION,
    TAG_BB_COMPRESSION, TAG_EXPANSION,
    TAG_BULL_ENGULF, TAG_INSIDE_BAR, TAG_RECLAIM_BAR, TAG_WIDE_RANGE,
    TAG_L34, TAG_NP_SETUP, TAG_NP_TRIGGER,
    # 260521
    TAG_BODY_X, TAG_BODY_S,
    TAG_WICK_TB, TAG_WICK_BB, TAG_WICK_J, TAG_WICK_F,
    TAG_GAP_G2, TAG_GAP_G3,
    TAG_RANGE_V, TAG_RANGE_C,
    TAG_VIX_X, TAG_VIX_R,
    TAG_PSAR_BULL, TAG_PSAR_BEAR,
    TAG_RSI2_X, TAG_RSI2_D, TAG_RSI2_L, TAG_RSI2_H,
]


# ── Symbolic tag conversion ────────────────────────────────────────────────────

def bars_to_tags(bar_features: dict) -> list[str]:
    """
    Convert a bar feature dict to a sorted list of symbolic tag strings.

    Accepts both build_bar_features() output (with keys like is_strong_close,
    ema50_reclaim_bar) and build_bar_feature_snapshots_for_episode() snapshots
    (which map DB column names like strong_close_near_high, dryup_day).

    Returns a deduplicated, sorted list of tag strings.
    Returns [TAG_FLAT] when no tags apply.
    """
    tags: list[str] = []

    # ── Close position ─────────────────────────────────────────────────────────
    cp = (
        bar_features.get("close_position_in_range")
        or bar_features.get("close_position_in_bar")
        or 0.5
    )
    sc = bar_features.get("is_strong_close") or bar_features.get("strong_close_near_high") or (cp >= 0.70)
    wc = bar_features.get("is_weak_close")   or bar_features.get("weak_close_near_low")   or (cp <= 0.30)

    if sc:
        tags.append(TAG_STRONG_CLOSE)
    if wc:
        tags.append(TAG_WEAK_CLOSE)

    # Lower wick reclaim: strong lower shadow + closes above midpoint
    lw = bar_features.get("lower_wick_pct") or 0.0
    if lw >= 0.30 and cp >= 0.50:
        tags.append(TAG_LOWER_WICK_RECLAIM)

    # ── Gap patterns ───────────────────────────────────────────────────────────
    gap_pct  = bar_features.get("gap_pct") or 0.0
    gap_up   = bar_features.get("has_gap_up")   or (gap_pct >= 2.0)
    gap_down = bar_features.get("has_gap_down") or (gap_pct <= -2.0)

    if gap_up:
        tags.append(TAG_GAP_UP)
    if gap_down:
        tags.append(TAG_GAP_DOWN)

    gap_hold       = bar_features.get("gap_hold")                  or (gap_up and sc)
    gap_dn_reclaim = (
        bar_features.get("gap_down_reclaim_same_day")
        or (gap_down and bar_features.get("close_reclaims_prev_close", False))
    )
    if gap_hold:
        tags.append(TAG_GAP_UP_HOLD)
    if gap_dn_reclaim:
        tags.append(TAG_GAP_DOWN_RECLAIM)

    # ── EMA patterns ───────────────────────────────────────────────────────────
    ema50_rec = (
        bar_features.get("ema50_reclaim_bar")
        or bar_features.get("low_below_ema50_close_above")
    )
    if ema50_rec:
        tags.append(TAG_EMA50_RECLAIM)

    if bar_features.get("ema_stack_state") == "BULL":
        tags.append(TAG_EMA_BULL_STACK)

    # ── Volume / dry-up ────────────────────────────────────────────────────────
    rvol       = bar_features.get("relative_volume_20d") or bar_features.get("volume_vs_avg20") or 1.0
    is_dryup   = bar_features.get("is_dryup") or bar_features.get("dryup_day")   or (rvol < 0.5)
    is_vol_spk = bar_features.get("is_abnormal_volume") or bar_features.get("abnormal_volume_day") or (rvol >= 3.0)

    if is_dryup:
        tags.append(TAG_DRYUP)
    if is_vol_spk:
        tags.append(TAG_VOLUME_SPIKE)

    # ── Delta patterns ─────────────────────────────────────────────────────────
    if bar_features.get("delta_ignition"):
        tags.append(TAG_DELTA_IGNITION)
    if bar_features.get("delta_absorption"):
        tags.append(TAG_DELTA_ABSORPTION)

    # ── Compression ────────────────────────────────────────────────────────────
    comp_state  = bar_features.get("compression_state") or ""
    comp_active = bar_features.get("compression_active") or (comp_state in ("STRONG", "MEDIUM"))
    if comp_active:
        tags.append(TAG_BB_COMPRESSION)

    # ── Candle structure ───────────────────────────────────────────────────────
    if bar_features.get("expansion_bar"):
        tags.append(TAG_EXPANSION)
    if bar_features.get("is_bullish_engulfing") or bar_features.get("bullish_engulfing"):
        tags.append(TAG_BULL_ENGULF)
    if bar_features.get("is_inside_bar") or bar_features.get("inside_bar"):
        tags.append(TAG_INSIDE_BAR)
    if bar_features.get("is_reclaim_bar") or bar_features.get("reclaim_bar"):
        tags.append(TAG_RECLAIM_BAR)
    if bar_features.get("is_wide_range") or bar_features.get("wide_range_bar"):
        tags.append(TAG_WIDE_RANGE)

    # ── Scanner signal context ─────────────────────────────────────────────────
    if bar_features.get("has_l34"):
        tags.append(TAG_L34)
    if bar_features.get("np_is_setup"):
        tags.append(TAG_NP_SETUP)
    if bar_features.get("np_is_trigger"):
        tags.append(TAG_NP_TRIGGER)

    # ── 260521 Line3/4/5 ──────────────────────────────────────────────────────
    body = bar_features.get("body_class",  "") or ""
    wick = bar_features.get("wick_class",  "") or ""
    gap  = bar_features.get("gap_class",   "") or ""
    rng  = bar_features.get("range_class", "") or ""
    vix  = bar_features.get("vix_token",   "") or ""
    psar = bar_features.get("psar_token",  "") or ""
    rsi2 = bar_features.get("rsi2_token",  "") or ""

    if body == "X":   tags.append(TAG_BODY_X)
    if body == "S":   tags.append(TAG_BODY_S)
    if wick == "TB":  tags.append(TAG_WICK_TB)
    if wick == "BB":  tags.append(TAG_WICK_BB)
    if wick == "J":   tags.append(TAG_WICK_J)
    if wick == "F":   tags.append(TAG_WICK_F)
    if gap  == "G2":  tags.append(TAG_GAP_G2)
    if gap  == "G3":  tags.append(TAG_GAP_G3)
    if rng  == "V":   tags.append(TAG_RANGE_V)
    if rng  == "C":   tags.append(TAG_RANGE_C)
    if vix  == "VX":  tags.append(TAG_VIX_X)
    if vix  == "VR":  tags.append(TAG_VIX_R)
    if psar == "PB":  tags.append(TAG_PSAR_BULL)
    if psar == "PS":  tags.append(TAG_PSAR_BEAR)
    if rsi2 == "R2X": tags.append(TAG_RSI2_X)
    if rsi2 == "R2D": tags.append(TAG_RSI2_D)
    if rsi2 == "R2L": tags.append(TAG_RSI2_L)
    if rsi2 == "R2H": tags.append(TAG_RSI2_H)

    result = sorted(set(tags))
    return result if result else [TAG_FLAT]


# ── Bar snapshot builder (from DB daily rows) ─────────────────────────────────

def build_bar_feature_snapshots_for_episode(
    episode: dict,
    raw_daily_rows: list[dict],
) -> list[dict]:
    """
    Build bar feature snapshots from already-computed raw_pattern_daily_features rows.

    Uses DB-stored bar features rather than recomputing from raw candles, so it
    does NOT require fetching OHLCV from an external API.

    Parameters
    ----------
    episode        : episode dict (from raw_pattern_episode_features).
                     Must contain episode_id (or id), symbol, group_type.
    raw_daily_rows : rows from raw_pattern_daily_features for this episode.
                     May include PRE/PUMP/POST phases — only PRE is used.
                     Rows are sorted by relative_day_from_start ascending
                     (most negative = oldest = furthest from breakout).

    Returns
    -------
    List of snapshot dicts, one per PRE-phase bar, sorted oldest→newest.
    Each snapshot has OHLCV, days_to_breakout (positive integer),
    episode_id, group_type, bar feature fields, and symbolic tags.

    Anti-leakage: group_type and episode_id are NOT used as pattern conditions.
    They are metadata for grouping results during mining only.
    """
    episode_id = episode.get("episode_id") or episode.get("id")
    symbol     = episode.get("symbol") or ""
    group_type = episode.get("group_type") or "unknown"

    # PRE-phase rows only, sorted oldest→newest (most-negative rel day first)
    pre_rows = sorted(
        [r for r in raw_daily_rows if r.get("phase") == "PRE"],
        key=lambda r: (r.get("relative_day_from_start") or 0),
    )

    snapshots: list[dict] = []
    for row in pre_rows:
        # relative_day_from_start is negative for PRE bars (e.g. -5 = 5 days before breakout)
        rel_day = row.get("relative_day_from_start") or 0
        days_to_breakout = abs(rel_day)

        # Overflow features stored as JSON
        fj: dict = row.get("feature_json") or {}
        if isinstance(fj, str):
            import json as _json
            try:
                fj = _json.loads(fj)
            except Exception:
                fj = {}

        snap: dict = {
            # Identity
            "episode_id":       episode_id,
            "symbol":           symbol,
            "group_type":       group_type,
            "date":             row.get("date") or "",
            # OHLCV
            "open":             row.get("open"),
            "high":             row.get("high"),
            "low":              row.get("low"),
            "close":            row.get("close"),
            "volume":           row.get("volume"),
            "phase":            "PRE",
            "days_to_breakout": days_to_breakout,
            # Candle anatomy (from DB columns → normalized names)
            "close_position_in_range": row.get("close_position_in_bar"),
            "body_pct":                row.get("body_pct"),
            "lower_wick_pct":          row.get("lower_wick_pct"),
            "upper_wick_pct":          row.get("upper_wick_pct"),
            "gap_pct":                 row.get("gap_pct"),
            "is_strong_close":         row.get("strong_close_near_high"),
            "is_weak_close":           row.get("weak_close_near_low"),
            "is_wide_range":           row.get("wide_range_bar"),
            "is_narrow_range":         row.get("narrow_range_bar"),
            "is_bullish_engulfing":    row.get("bullish_engulfing"),
            "is_inside_bar":           row.get("inside_bar"),
            "is_outside_bar":          row.get("outside_bar"),
            "is_reclaim_bar":          row.get("reclaim_bar"),
            "expansion_bar":           row.get("expansion_bar"),
            # Volume (DB columns → normalized names)
            "relative_volume_20d":     row.get("volume_vs_avg20"),
            "volume_z":                row.get("volume_zscore"),
            "is_dryup":                row.get("dryup_day"),
            "is_abnormal_volume":      row.get("abnormal_volume_day"),
            # Compression / volatility (DB columns)
            "compression_state":       row.get("compression_state"),
            "bb_width":                row.get("bb_width"),
            "ema_spread_pct":          row.get("ema_spread_pct"),
            # Extras from feature_json (populated by build_bar_features via pump_study_engine)
            "ema50_reclaim_bar":        fj.get("ema50_reclaim_bar"),
            "delta_ignition":           fj.get("delta_ignition"),
            "delta_absorption":         fj.get("delta_absorption"),
            "has_l34":                  fj.get("has_l34"),
            "np_is_setup":              fj.get("np_is_setup"),
            "np_is_trigger":            fj.get("np_is_trigger"),
            "ema_stack_state":          fj.get("ema_stack_state"),
            "gap_hold":                 fj.get("gap_hold"),
            "gap_down_reclaim_same_day": fj.get("gap_down_reclaim_same_day"),
            # Custom D/L/WLNBB signal flags (pre-computed by upstream process)
            "has_l43":     fj.get("has_l43"),
            "has_l22":     fj.get("has_l22"),
            "has_l64":     fj.get("has_l64"),
            "has_fri34":   fj.get("has_fri34"),
            "has_fri64":   fj.get("has_fri64"),
            "has_d3_beup": fj.get("has_d3_beup"),
            "has_d4_beup": fj.get("has_d4_beup"),
            "has_d6_beup": fj.get("has_d6_beup"),
            "has_d4_l34":  fj.get("has_d4_l34"),
            "has_d3_l34":  fj.get("has_d3_l34"),
            "has_vbo":     fj.get("has_vbo"),
            "has_lvbo":    fj.get("has_lvbo"),
            "has_ld":      fj.get("has_ld"),
            # ABR/TZ quality fields (research-only)
            "abr_sp500":               fj.get("abr_sp500"),
            "abr_nasdaq":              fj.get("abr_nasdaq"),
            "tz_quality_tier_sp500":   fj.get("tz_quality_tier_sp500"),
            "tz_quality_tier_nasdaq":  fj.get("tz_quality_tier_nasdaq"),
            "tz_quality_score":        fj.get("tz_quality_score"),
            "preup_primary":           fj.get("preup_primary"),
            "predn_primary":           fj.get("predn_primary"),
            "abr_z8":                  fj.get("has_z8"),
            "abr_l1":                  fj.get("has_l1"),
            "abr_l2":                  fj.get("has_l2"),
            "abr_l3":                  fj.get("has_l3"),
            "abr_l4":                  fj.get("has_l4"),
            "abr_l5":                  fj.get("has_l5"),
            "abr_l6":                  fj.get("has_l6"),
            # 260521 Line3/4/5 token fields
            "body_class":  fj.get("body_class",  "") or "",
            "wick_class":  fj.get("wick_class",  "") or "",
            "gap_class":   fj.get("gap_class",   "") or "",
            "range_class": fj.get("range_class", "") or "",
            "vix_token":   fj.get("vix_token",   "") or "",
            "psar_token":  fj.get("psar_token",  "") or "",
            "rsi2_token":  fj.get("rsi2_token",  "") or "",
        }

        snap["tags"]          = bars_to_tags(snap)
        snap["tag_signature"] = "+".join(snap["tags"])
        # Flow tags initialised as empty — populated by build_bar_flow_features()
        snap["flow_tags"]              = [TAG_FLAT]
        snap["flow_tag_signature"]     = TAG_FLAT
        snap["combined_tags"]          = snap["tags"][:]
        snap["combined_tag_signature"] = snap["tag_signature"]
        # Custom signal tags — populated by build_custom_signal_tags()
        snap["custom_tags"]                        = ["CUSTOM_FLAT"]
        snap["custom_tag_signature"]               = "CUSTOM_FLAT"
        snap["flow_custom_combined_tags"]          = ["FLAT"]
        snap["flow_custom_combined_tag_signature"] = "FLAT"

        snapshots.append(snap)

    # Compute V1C flow features across the full sequence
    build_bar_flow_features(snapshots)

    # Compute custom signal tags (single-bar flags + multi-bar composites)
    try:
        from replay.custom_signal_engine import build_custom_signal_tags
        build_custom_signal_tags(snapshots)
    except Exception:
        pass  # Custom signal engine optional — fails gracefully

    return snapshots


# ── Bar sequence builder ───────────────────────────────────────────────────────

def build_bar_sequences(
    bar_snapshots: list[dict],
    windows: tuple = (1, 2, 3, 5, 10),
    tag_mode: str = "price",
) -> list[dict]:
    """
    Build rolling-window sequence features from bar snapshots for one episode.

    Signature encoding by window size:
      window=1 : the bar's own tag_signature (tags joined by "+")
      window≤3 : ordered bar signatures joined by "→"  (preserves bar order)
      window>3  : sorted tag-set across all bars (unordered bag-of-tags)

    Parameters
    ----------
    bar_snapshots : list from build_bar_feature_snapshots_for_episode(),
                    sorted oldest→newest (days_to_breakout descending).
    windows       : window sizes to generate sequences for.
    tag_mode      : "price"    — V1B price-action tags only
                    "flow"     — V1C flow/delta tags only
                    "combined" — V1B + V1C combined tags

    Returns
    -------
    Flat list of BarSequenceFeature dicts. Every (window_size, position)
    combination generates one entry. Most-recent windows (nearest breakout)
    have the smallest days_to_breakout_end values.
    """
    if not bar_snapshots:
        return []

    episode_id = bar_snapshots[0].get("episode_id")
    symbol     = bar_snapshots[0].get("symbol") or ""
    group_type = bar_snapshots[0].get("group_type") or ""

    # Choose which tag field to use for signatures
    if tag_mode == "flow":
        sig_key = "flow_tag_signature"
    elif tag_mode == "combined":
        sig_key = "combined_tag_signature"
    elif tag_mode == "custom":
        sig_key = "custom_tag_signature"
    elif tag_mode == "flow_custom_combined":
        sig_key = "flow_custom_combined_tag_signature"
    else:
        sig_key = "tag_signature"

    sequences: list[dict] = []

    for w in windows:
        if len(bar_snapshots) < w:
            continue

        for start_i in range(len(bar_snapshots) - w + 1):
            window_bars = bar_snapshots[start_i: start_i + w]
            bar_tags    = [b.get(sig_key.replace("_signature", "s"), b.get("tags", [TAG_FLAT]))
                          for b in window_bars]
            # Resolve tags list for each bar based on tag_mode
            if tag_mode == "flow":
                bar_tags = [b.get("flow_tags") or [TAG_FLAT] for b in window_bars]
            elif tag_mode == "combined":
                bar_tags = [b.get("combined_tags") or [TAG_FLAT] for b in window_bars]
            elif tag_mode == "custom":
                bar_tags = [b.get("custom_tags") or ["CUSTOM_FLAT"] for b in window_bars]
            elif tag_mode == "flow_custom_combined":
                bar_tags = [b.get("flow_custom_combined_tags") or [TAG_FLAT] for b in window_bars]
            else:
                bar_tags = [b.get("tags") or [TAG_FLAT] for b in window_bars]

            start_date  = window_bars[0].get("date") or ""
            end_date    = window_bars[-1].get("date") or ""
            days_start  = window_bars[0].get("days_to_breakout") or 0
            days_end    = window_bars[-1].get("days_to_breakout") or 0

            # Sequence signature
            bar_sigs = ["+".join(sorted(set(bt))) if bt else TAG_FLAT for bt in bar_tags]
            if w == 1:
                sig = bar_sigs[0]
            elif w <= 3:
                sig = "→".join(bar_sigs)
            else:
                all_tags = sorted(set(t for bt in bar_tags for t in bt))
                sig = "+".join(all_tags) if all_tags else TAG_FLAT

            # Per-tag count across the window
            tag_counts: dict[str, int] = {}
            for bt in bar_tags:
                for t in bt:
                    tag_counts[t] = tag_counts.get(t, 0) + 1

            sequences.append({
                "episode_id":             episode_id,
                "symbol":                 symbol,
                "group_type":             group_type,
                "window_size":            w,
                "start_date":             start_date,
                "end_date":               end_date,
                "days_to_breakout_start": days_start,
                "days_to_breakout_end":   days_end,
                "sequence_signature":     sig,
                "bar_tags":               bar_tags,
                "tag_counts":             tag_counts,
                "tag_mode":               tag_mode,
            })

    return sequences


# ── V1C: Flow / Delta proxy feature engine ────────────────────────────────────
#
# All features derived from OHLCV only — NOT true bid/ask delta.
# Values approximate accumulation/distribution pressure using:
#   CLV (close location value), signed volume proxy, OBV, ADL, CMF.
# Anti-leakage: uses only bars in the pre-window sequence (oldest→newest).
# ─────────────────────────────────────────────────────────────────────────────

# V1C flow tag constants
TAG_CLOSE_HIGH             = "CLOSE_HIGH"
TAG_CLOSE_LOW              = "CLOSE_LOW"
TAG_BUY_PRESSURE_HIGH      = "BUY_PRESSURE_HIGH"
TAG_BUY_PRESSURE_LOW       = "BUY_PRESSURE_LOW"
TAG_LOWER_WICK_ABSORPTION  = "LOWER_WICK_ABSORPTION"
TAG_UPPER_WICK_SUPPLY      = "UPPER_WICK_SUPPLY"
TAG_HIGH_EFFORT_LOW_RESULT = "HIGH_EFFORT_LOW_RESULT"
TAG_LOW_EFFORT_HIGH_RESULT = "LOW_EFFORT_HIGH_RESULT"
TAG_EFFORT_RESULT_BULL     = "EFFORT_RESULT_BULL"
TAG_EFFORT_RESULT_BEAR     = "EFFORT_RESULT_BEAR"
TAG_OBV_ACCUM_3D           = "OBV_ACCUM_3D"
TAG_OBV_DISTRIB_3D         = "OBV_DISTRIB_3D"
TAG_ADL_ACCUM_3D           = "ADL_ACCUM_3D"
TAG_ADL_DISTRIB_3D         = "ADL_DISTRIB_3D"
TAG_CMF_POSITIVE           = "CMF_POSITIVE"
TAG_CMF_NEGATIVE           = "CMF_NEGATIVE"
TAG_CMF_TURN_UP            = "CMF_TURN_UP"
TAG_CMF_TURN_DOWN          = "CMF_TURN_DOWN"
TAG_GAP_DOWN_RECLAIM_FLOW  = "GAP_DOWN_RECLAIM_FLOW"
TAG_GAP_UP_HOLD_FLOW       = "GAP_UP_HOLD_FLOW"
TAG_GAP_UP_FADE_FLOW       = "GAP_UP_FADE_FLOW"
TAG_GAP_DOWN_FAIL_FLOW     = "GAP_DOWN_FAIL_FLOW"
TAG_DELTA_PROXY_BULL       = "DELTA_PROXY_BULL"
TAG_DELTA_PROXY_BEAR       = "DELTA_PROXY_BEAR"
TAG_DELTA_PROXY_ABSORPTION = "DELTA_PROXY_ABSORPTION"

ALL_FLOW_TAGS = [
    TAG_CLOSE_HIGH, TAG_CLOSE_LOW,
    TAG_BUY_PRESSURE_HIGH, TAG_BUY_PRESSURE_LOW,
    TAG_LOWER_WICK_ABSORPTION, TAG_UPPER_WICK_SUPPLY,
    TAG_HIGH_EFFORT_LOW_RESULT, TAG_LOW_EFFORT_HIGH_RESULT,
    TAG_EFFORT_RESULT_BULL, TAG_EFFORT_RESULT_BEAR,
    TAG_OBV_ACCUM_3D, TAG_OBV_DISTRIB_3D,
    TAG_ADL_ACCUM_3D, TAG_ADL_DISTRIB_3D,
    TAG_CMF_POSITIVE, TAG_CMF_NEGATIVE, TAG_CMF_TURN_UP, TAG_CMF_TURN_DOWN,
    TAG_GAP_DOWN_RECLAIM_FLOW, TAG_GAP_UP_HOLD_FLOW,
    TAG_GAP_UP_FADE_FLOW, TAG_GAP_DOWN_FAIL_FLOW,
    TAG_DELTA_PROXY_BULL, TAG_DELTA_PROXY_BEAR, TAG_DELTA_PROXY_ABSORPTION,
]


def _slope(series: list[float], n: int) -> Optional[float]:
    """Linear slope of the last n values (positive = upward)."""
    if len(series) < n:
        return None
    seg = series[-n:]
    if len(seg) < 2:
        return None
    xs = list(range(len(seg)))
    xm = sum(xs) / len(xs)
    ym = sum(seg) / len(seg)
    denom = sum((x - xm) ** 2 for x in xs)
    if denom < _TINY:
        return 0.0
    return sum((xs[i] - xm) * (seg[i] - ym) for i in range(len(seg))) / denom


def _z_score(series: list[float], current: float) -> float:
    if len(series) < 3:
        return 0.0
    m = sum(series) / len(series)
    sd = _stdev_pop(series)
    return (current - m) / max(sd, _TINY)


def build_bar_flow_features(snapshots: list[dict]) -> list[dict]:
    """
    Augment bar snapshots (oldest→newest) with V1C flow/delta proxy features.

    This function processes the full sorted pre-window sequence in one pass
    so that rolling series (OBV, ADL, CMF) are computed correctly without
    future leakage. Each snapshot dict is augmented in-place and returned.

    Inputs required per snapshot (from build_bar_feature_snapshots_for_episode):
      open, high, low, close, volume, gap_pct, lower_wick_pct, upper_wick_pct,
      relative_volume_20d (or volume_z), close_position_in_range.

    IMPORTANT: All features are OHLCV-derived proxies, NOT true bid/ask delta.
    """
    if not snapshots:
        return snapshots

    # Running cumulative series
    obv_series: list[float] = []
    adl_series: list[float] = []
    clv_vol_series: list[float] = []   # for CMF numerator
    vol_series: list[float] = []       # for CMF denominator

    prev_close: Optional[float] = None
    prev_cmf_5_local: Optional[float] = None  # carried across iterations for turn detection

    for i, snap in enumerate(snapshots):
        h = float(snap.get("high")   or 0)
        l = float(snap.get("low")    or 0)
        c = float(snap.get("close")  or 0)
        o = float(snap.get("open")   or c)
        v = float(snap.get("volume") or 0)
        pc = prev_close if prev_close is not None else c

        bar_range = max(h - l, _TINY)

        # ── 1. CLV (Close Location Value) ─────────────────────────────────────
        clv = ((c - l) - (h - c)) / bar_range  # range -1..+1

        if clv >= 0.5:
            close_location_bucket = "CLOSE_HIGH"
        elif clv <= -0.5:
            close_location_bucket = "CLOSE_LOW"
        else:
            close_location_bucket = "CLOSE_MID"

        # ── 2. Buy pressure ratio (0..1) ──────────────────────────────────────
        buy_pressure_ratio = (c - l) / bar_range  # same as close_position_in_range

        if buy_pressure_ratio >= 0.70:
            buy_pressure_bucket = "BUY_PRESSURE_HIGH"
        elif buy_pressure_ratio <= 0.30:
            buy_pressure_bucket = "BUY_PRESSURE_LOW"
        else:
            buy_pressure_bucket = "BUY_PRESSURE_NEUTRAL"

        # ── 3. Money flow volume proxy ────────────────────────────────────────
        money_flow_volume = clv * v  # signed; positive = buying pressure

        # ── 4. Signed volume proxy (volume * CLV) ────────────────────────────
        signed_volume_proxy = v * clv  # equivalent to money_flow_volume

        # ── 5. OBV delta ──────────────────────────────────────────────────────
        if c > pc:
            obv_delta = v
        elif c < pc:
            obv_delta = -v
        else:
            obv_delta = 0.0

        obv_cumsum = (obv_series[-1] if obv_series else 0.0) + obv_delta
        obv_series.append(obv_cumsum)

        # ── 6. ADL delta ──────────────────────────────────────────────────────
        adl_delta  = clv * v
        adl_cumsum = (adl_series[-1] if adl_series else 0.0) + adl_delta
        adl_series.append(adl_cumsum)

        # ── 7. CMF components ─────────────────────────────────────────────────
        clv_vol_series.append(clv * v)
        vol_series.append(v)

        def _cmf(n: int) -> Optional[float]:
            if len(clv_vol_series) < n:
                return None
            denom = sum(vol_series[-n:])
            if denom < _TINY:
                return None
            return sum(clv_vol_series[-n:]) / denom

        cmf_5  = _cmf(5)
        cmf_10 = _cmf(10)

        # CMF turn detection (vs previous bar's CMF via local variable)
        cmf_turn_up   = False
        cmf_turn_down = False
        if prev_cmf_5_local is not None and cmf_5 is not None:
            cmf_turn_up   = prev_cmf_5_local <= 0 < cmf_5
            cmf_turn_down = prev_cmf_5_local >= 0 > cmf_5

        # OBV and ADL slopes
        obv_slope_3  = _slope(obv_series, 3)
        obv_slope_5  = _slope(obv_series, 5)
        adl_slope_3  = _slope(adl_series, 3)
        adl_slope_5  = _slope(adl_series, 5)

        # Z-scores for signed_volume_proxy
        hist_svp = [s.get("signed_volume_proxy", 0.0) for s in snapshots[:i]]
        svp_z = _z_score(hist_svp, signed_volume_proxy) if len(hist_svp) >= 3 else 0.0

        # ── 8. Effort vs result ───────────────────────────────────────────────
        rel_vol = float(snap.get("relative_volume_20d") or snap.get("volume_vs_avg20") or 1.0)
        close_return_pct = (c / max(pc, _TINY) - 1) * 100
        intraday_return_pct = (c / max(o, _TINY) - 1) * 100
        gap_pct = float(snap.get("gap_pct") or 0.0)

        lw = float(snap.get("lower_wick_pct") or 0.0)
        uw = float(snap.get("upper_wick_pct") or 0.0)
        lower_wick_dominance = lw - uw
        upper_wick_dominance = uw - lw

        # ── Assign flow features to snapshot ─────────────────────────────────
        snap.update({
            # CLV / pressure
            "clv":                    round(clv, 4),
            "close_location_bucket":  close_location_bucket,
            "buy_pressure_ratio":     round(buy_pressure_ratio, 4),
            "buy_pressure_bucket":    buy_pressure_bucket,
            # Money flow
            "money_flow_volume_proxy": round(money_flow_volume, 1),
            # OBV
            "obv_delta":              round(obv_delta, 1),
            "obv_cumsum":             round(obv_cumsum, 1),
            "obv_slope_3":            round(obv_slope_3, 2) if obv_slope_3 is not None else None,
            "obv_slope_5":            round(obv_slope_5, 2) if obv_slope_5 is not None else None,
            # ADL
            "adl_delta":              round(adl_delta, 1),
            "adl_cumsum":             round(adl_cumsum, 1),
            "adl_slope_3":            round(adl_slope_3, 2) if adl_slope_3 is not None else None,
            "adl_slope_5":            round(adl_slope_5, 2) if adl_slope_5 is not None else None,
            # CMF
            "cmf_5":                  round(cmf_5, 4) if cmf_5 is not None else None,
            "cmf_10":                 round(cmf_10, 4) if cmf_10 is not None else None,
            "cmf_turn_up":            cmf_turn_up,
            "cmf_turn_down":          cmf_turn_down,
            # Signed volume proxy (OHLCV-derived, NOT true bid/ask delta)
            "signed_volume_proxy":    round(signed_volume_proxy, 1),
            "signed_volume_z":        round(svp_z, 3),
            # Effort vs result
            "close_return_pct":       round(close_return_pct, 3),
            "intraday_return_pct":    round(intraday_return_pct, 3),
            "lower_wick_dominance":   round(lower_wick_dominance, 4),
            "upper_wick_dominance":   round(upper_wick_dominance, 4),
        })

        prev_close = c
        prev_cmf_5_local = cmf_5  # carry forward for next iteration's turn detection

    # Second pass: compute flow tags (needs all flow fields to be present)
    for snap in snapshots:
        flow_tags = bars_to_flow_tags(snap)
        price_tags = snap.get("tags") or [TAG_FLAT]
        combined_tags = sorted(set(price_tags + flow_tags))
        if not combined_tags:
            combined_tags = [TAG_FLAT]

        snap["flow_tags"]              = flow_tags
        snap["flow_tag_signature"]     = "+".join(flow_tags) if flow_tags else TAG_FLAT
        snap["combined_tags"]          = combined_tags
        snap["combined_tag_signature"] = "+".join(combined_tags)

    return snapshots


def bars_to_flow_tags(snap: dict) -> list[str]:
    """
    Convert a snapshot (augmented by build_bar_flow_features) to V1C flow tags.

    Returns sorted list of flow tag strings; [TAG_FLAT] when no tags apply.
    IMPORTANT: All tags are derived from OHLCV proxies, NOT true bid/ask delta.
    """
    tags: list[str] = []

    clv           = snap.get("clv", 0.0) or 0.0
    bpr           = snap.get("buy_pressure_ratio", 0.5) or 0.5
    lw            = snap.get("lower_wick_pct", 0.0) or 0.0
    uw            = snap.get("upper_wick_pct", 0.0) or 0.0
    rel_vol       = snap.get("relative_volume_20d") or snap.get("volume_vs_avg20") or 1.0
    close_ret     = snap.get("close_return_pct", 0.0) or 0.0
    intraday_ret  = snap.get("intraday_return_pct", 0.0) or 0.0
    gap_pct       = snap.get("gap_pct", 0.0) or 0.0
    svp_z         = snap.get("signed_volume_z", 0.0) or 0.0
    obv_slope_3   = snap.get("obv_slope_3")
    adl_slope_3   = snap.get("adl_slope_3")
    cmf_5         = snap.get("cmf_5")
    cmf_turn_up   = snap.get("cmf_turn_up", False)
    cmf_turn_down = snap.get("cmf_turn_down", False)

    # CLV / close location
    if clv >= 0.5:
        tags.append(TAG_CLOSE_HIGH)
    if clv <= -0.5:
        tags.append(TAG_CLOSE_LOW)

    # Buy pressure
    if bpr >= 0.70:
        tags.append(TAG_BUY_PRESSURE_HIGH)
    if bpr <= 0.30:
        tags.append(TAG_BUY_PRESSURE_LOW)

    # Wick pressure
    if lw >= 0.35 and clv >= 0:
        tags.append(TAG_LOWER_WICK_ABSORPTION)
    if uw >= 0.35 and clv <= 0:
        tags.append(TAG_UPPER_WICK_SUPPLY)

    # Effort vs result
    if rel_vol >= 2.0 and abs(close_ret) <= 3.0:
        tags.append(TAG_HIGH_EFFORT_LOW_RESULT)
    if rel_vol <= 0.8 and abs(close_ret) >= 5.0:
        tags.append(TAG_LOW_EFFORT_HIGH_RESULT)
    if rel_vol >= 1.5 and close_ret > 3.0 and clv >= 0.5:
        tags.append(TAG_EFFORT_RESULT_BULL)
    if rel_vol >= 1.5 and close_ret < -3.0 and clv <= -0.5:
        tags.append(TAG_EFFORT_RESULT_BEAR)

    # OBV
    if obv_slope_3 is not None and obv_slope_3 > 0:
        tags.append(TAG_OBV_ACCUM_3D)
    if obv_slope_3 is not None and obv_slope_3 < 0:
        tags.append(TAG_OBV_DISTRIB_3D)

    # ADL
    if adl_slope_3 is not None and adl_slope_3 > 0:
        tags.append(TAG_ADL_ACCUM_3D)
    if adl_slope_3 is not None and adl_slope_3 < 0:
        tags.append(TAG_ADL_DISTRIB_3D)

    # CMF
    if cmf_5 is not None:
        if cmf_5 > 0.15:
            tags.append(TAG_CMF_POSITIVE)
        if cmf_5 < -0.15:
            tags.append(TAG_CMF_NEGATIVE)
    if cmf_turn_up:
        tags.append(TAG_CMF_TURN_UP)
    if cmf_turn_down:
        tags.append(TAG_CMF_TURN_DOWN)

    # Gap-adjusted flow tags
    if gap_pct <= -3 and intraday_ret > 3 and clv >= 0.5 and bpr >= 0.7:
        tags.append(TAG_GAP_DOWN_RECLAIM_FLOW)
    if gap_pct >= 3 and intraday_ret >= -2 and clv >= 0.3:
        tags.append(TAG_GAP_UP_HOLD_FLOW)
    if gap_pct >= 3 and intraday_ret < -3 and clv <= -0.3:
        tags.append(TAG_GAP_UP_FADE_FLOW)
    if gap_pct <= -3 and intraday_ret < -2 and clv <= -0.3:
        tags.append(TAG_GAP_DOWN_FAIL_FLOW)

    # Delta proxy (OHLCV-derived signed volume, NOT true bid/ask delta)
    if svp_z >= 1.5 and clv >= 0.4:
        tags.append(TAG_DELTA_PROXY_BULL)
    if svp_z <= -1.5 and clv <= -0.4:
        tags.append(TAG_DELTA_PROXY_BEAR)
    if svp_z >= 1.0 and lw >= 0.35 and clv >= 0:
        tags.append(TAG_DELTA_PROXY_ABSORPTION)

    result = sorted(set(tags))
    return result if result else [TAG_FLAT]
