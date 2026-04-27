"""
Manual D + WLNBB confluence research features.

Ports two Pine scripts exactly:
  - Manual D Builder  (260422_D)  — T/Z priority candle engine → D1,D3,D4,D6,D9,D11
  - WLNBB OSC         (260331_WLNBB_OSC) — Bollinger-band volume classifier → L34,L43,BE Up

RESEARCH ONLY. These fields are appended to scan results for analysis.
They do NOT affect New Pump score, decision, or routing.
No future leakage: every computation uses only bars[0..i].
"""

from __future__ import annotations
from typing import Optional

# ── Math helpers (pure Python, no numpy) ─────────────────────────────────────

def _sma_series(values: list[float], period: int) -> list[Optional[float]]:
    out: list[Optional[float]] = [None] * len(values)
    for i in range(period - 1, len(values)):
        out[i] = sum(values[i - period + 1: i + 1]) / period
    return out


def _std_series(values: list[float], period: int) -> list[Optional[float]]:
    out: list[Optional[float]] = [None] * len(values)
    for i in range(period - 1, len(values)):
        window = values[i - period + 1: i + 1]
        mean = sum(window) / period
        out[i] = (sum((x - mean) ** 2 for x in window) / period) ** 0.5
    return out


def _rsi_series(closes: list[float], period: int = 14) -> list[Optional[float]]:
    """Wilder RSI. None where insufficient data."""
    rsi: list[Optional[float]] = [None] * len(closes)
    if len(closes) <= period:
        return rsi
    gains  = [max(closes[j] - closes[j - 1], 0.0) for j in range(1, len(closes))]
    losses = [max(closes[j - 1] - closes[j], 0.0) for j in range(1, len(closes))]
    ag = sum(gains[:period]) / period
    al = sum(losses[:period]) / period
    rsi[period] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    for j in range(period + 1, len(closes)):
        ag = (ag * (period - 1) + gains[j - 1]) / period
        al = (al * (period - 1) + losses[j - 1]) / period
        rsi[j] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return rsi


# ── Part 1: T/Z priority engine ───────────────────────────────────────────────

def _zero_tz() -> dict:
    return {
        "_z7_raw": False,
        "bull_code": 0, "bear_code": 0,
        "T4": False, "T6": False, "T1G": False, "T2G": False,
        "T1": False, "T2": False, "T9": False, "T10": False,
        "T3": False, "T11": False, "T5": False, "T12": False,
        "Z4": False, "Z6": False, "Z1G": False, "Z2G": False,
        "Z1": False, "Z2": False, "Z9": False, "Z10": False,
        "Z3": False, "Z11": False, "Z5": False, "Z12": False,
        "Z7": False,
    }


def compute_tz_selected(candles: list[dict]) -> list[dict]:
    """
    Compute T/Z selected-only (priority-deduplicated) signals for every bar.

    candles: list of dicts with keys open/high/low/close/volume, oldest-first.
    Returns list of signal dicts, same length as candles.
    """
    n = len(candles)
    MIN_BODY_RATIO = 1.0  # minBodyRatio default from Pine
    MIN_TICK       = 1e-10

    result: list[dict] = []

    for i in range(n):
        if i < 1:
            result.append(_zero_tz())
            continue

        o  = candles[i]["open"];   c  = candles[i]["close"]
        h  = candles[i]["high"];   l  = candles[i]["low"]
        o1 = candles[i-1]["open"]; c1 = candles[i-1]["close"]
        h1 = candles[i-1]["high"]; l1 = candles[i-1]["low"]

        is_doji = (c == o)
        is_bull = (c > o)
        is_bear = (c < o)

        # prev1IsBear = close[1] < open[1] OR Z7_raw[1] (doji 1 bar ago)
        prev_z7 = result[i - 1]["_z7_raw"]
        prev1_is_bull = (c1 > o1)
        prev1_is_bear = (c1 < o1) or prev_z7

        # Engulfing (useWick = false)
        prev_body = abs(c1 - o1)
        prev_top  = max(o1, c1)
        prev_bot  = min(o1, c1)
        curr_body = abs(c - o)
        curr_top  = max(o, c)
        curr_bot  = min(o, c)

        prev_body_safe = max(prev_body, MIN_TICK)
        body_ratio_ok  = (curr_body / prev_body_safe) >= MIN_BODY_RATIO
        fully_engulfs  = (curr_top >= prev_top) and (prev_bot >= curr_bot) and body_ratio_ok
        is_inside      = (curr_top <= prev_top) and (curr_bot >= prev_bot)

        # prevBull / prevBear for engulfing patterns follow prev1Is* definitions
        prev_bull = prev1_is_bull
        prev_bear = prev1_is_bear

        # ── Raw bullish T patterns ────────────────────────────────────────────
        t1g_raw = (prev1_is_bear and (o > c1) and (o > o1) and (c > o1) and is_bull)
        t1_raw  = (prev1_is_bear and (o >= c1) and (o1 >= o) and (c > o1) and is_bull)
        t2g_raw = (prev1_is_bull and (o >= o1) and (o > c1) and (c > c1) and is_bull)
        t2_raw  = (prev1_is_bull and (o >= o1) and (o <= c1) and (c > c1) and is_bull)
        t3_raw  = (prev1_is_bear and is_bull
                   and (o < o1) and (o < c1) and (c < o1) and (c > c1))
        t4_raw  = (prev_bear and is_bull and fully_engulfs)
        t5_raw  = (prev1_is_bear and is_bull
                   and (o < o1) and (o < c1) and (c < o1) and (c1 >= c))
        t6_raw  = (prev_bull and is_bull and fully_engulfs)
        t9_raw  = (prev1_is_bear and is_bull and is_inside)
        t10_raw = (prev1_is_bull and is_bull and is_inside)
        t11_raw = (prev1_is_bull and is_bull and (o < o1) and (c >= o1) and (c < c1))
        t12_raw = (prev1_is_bull and is_bull and (o < o1) and (c < o1))

        # ── Raw bearish Z patterns ────────────────────────────────────────────
        z1g_raw = (prev1_is_bull and (o < c1) and (o < o1) and (c < o1) and is_bear)
        z1_raw  = (prev1_is_bull and (o <= c1) and (o > o1) and (c < o1) and is_bear)
        z2g_raw = (prev1_is_bear and (o <= o1) and (o < c1) and (c < c1) and is_bear)
        z2_raw  = (prev1_is_bear and (o <= o1) and (o >= c1) and (c < c1) and is_bear)
        z3_raw  = (prev1_is_bull and is_bear
                   and (o > o1) and (o > c1) and (c > o1) and (c < c1))
        z4_raw  = (prev_bull and is_bear and fully_engulfs)
        z5_raw  = (prev1_is_bull and is_bear
                   and (o > o1) and (o > c1) and (c > o1) and (c >= c1))
        z6_raw  = (prev_bear and is_bear and fully_engulfs)
        z9_raw  = (prev1_is_bull and is_bear and is_inside)
        z10_raw = (prev1_is_bear and is_bear and is_inside)
        z11_raw = (prev1_is_bear and (o > o1) and is_bear and ((c > c1) or (c > o1)))
        z12_raw = (prev1_is_bull and (o <= o1) and (c < o))
        z7_raw  = is_doji

        # Doji cleanup — Z7 only fires if no other T/Z pattern present
        any_bull_raw = (t1g_raw or t1_raw or t2g_raw or t2_raw or t3_raw or
                        t4_raw or t5_raw or t6_raw or t9_raw or t10_raw or
                        t11_raw or t12_raw)
        any_bear_raw = (z1g_raw or z1_raw or z2g_raw or z2_raw or z3_raw or
                        z4_raw or z5_raw or z6_raw or z9_raw or z10_raw or
                        z11_raw or z12_raw)
        z7_clean = z7_raw and not any_bull_raw and not any_bear_raw

        # ── Priority engine ───────────────────────────────────────────────────
        if   t4_raw:  bull_code = 1
        elif t6_raw:  bull_code = 2
        elif t1g_raw: bull_code = 3
        elif t2g_raw: bull_code = 4
        elif t1_raw:  bull_code = 5
        elif t2_raw:  bull_code = 6
        elif t9_raw:  bull_code = 7
        elif t10_raw: bull_code = 8
        elif t3_raw:  bull_code = 9
        elif t11_raw: bull_code = 10
        elif t5_raw:  bull_code = 11
        elif t12_raw: bull_code = 12
        else:         bull_code = 0

        if   z4_raw:   bear_code = 1
        elif z6_raw:   bear_code = 2
        elif z1g_raw:  bear_code = 3
        elif z2g_raw:  bear_code = 4
        elif z1_raw:   bear_code = 5
        elif z2_raw:   bear_code = 6
        elif z9_raw:   bear_code = 7
        elif z10_raw:  bear_code = 8
        elif z3_raw:   bear_code = 9
        elif z11_raw:  bear_code = 10
        elif z5_raw:   bear_code = 11
        elif z12_raw:  bear_code = 12
        elif z7_clean: bear_code = 13
        else:          bear_code = 0

        result.append({
            "_z7_raw":  z7_raw,
            "bull_code": bull_code,
            "bear_code": bear_code,
            # selected-only T signals
            "T4":  bull_code == 1,
            "T6":  bull_code == 2,
            "T1G": bull_code == 3,
            "T2G": bull_code == 4,
            "T1":  bull_code == 5,
            "T2":  bull_code == 6,
            "T9":  bull_code == 7,
            "T10": bull_code == 8,
            "T3":  bull_code == 9,
            "T11": bull_code == 10,
            "T5":  bull_code == 11,
            "T12": bull_code == 12,
            # selected-only Z signals
            "Z4":  bear_code == 1,
            "Z6":  bear_code == 2,
            "Z1G": bear_code == 3,
            "Z2G": bear_code == 4,
            "Z1":  bear_code == 5,
            "Z2":  bear_code == 6,
            "Z9":  bear_code == 7,
            "Z10": bear_code == 8,
            "Z3":  bear_code == 9,
            "Z11": bear_code == 10,
            "Z5":  bear_code == 11,
            "Z12": bear_code == 12,
            "Z7":  bear_code == 13,
        })

    return result


# ── Part 2: Manual D features ─────────────────────────────────────────────────

def compute_manual_d_features(
    candles: list[dict],
    use_rsi_filter:    bool = True,
    rsi_length:        int  = 14,
    rsi_compare_bars:  int  = 2,
) -> list[dict]:
    """
    Compute D1,D3,D4,D6,D9,D11 for every bar.
    Uses selected-only T/Z signals (priority-deduplicated).

    Returns list same length as candles. Each dict has:
      d1_raw, d1, d3_raw, d3, d4_raw, d4,
      d6_raw, d6, d9_raw, d9, d11_raw, d11, rsi_pass
    """
    n = len(candles)
    closes = [b["close"] for b in candles]
    opens  = [b["open"]  for b in candles]

    rsi_s = _rsi_series(closes, rsi_length)
    tz    = compute_tz_selected(candles)

    def _t(sig: str, bar_i: int, lag: int = 0) -> bool:
        idx = bar_i - lag
        if idx < 0:
            return False
        return tz[idx].get(sig, False)

    result: list[dict] = []

    for i in range(n):
        # RSI filter: rsiValue > rsiValue[rsiCompareBars]
        rsi_now = rsi_s[i]
        rsi_ref = rsi_s[i - rsi_compare_bars] if i >= rsi_compare_bars else None
        if not use_rsi_filter:
            rsi_pass = True
        elif rsi_now is not None and rsi_ref is not None:
            rsi_pass = rsi_now > rsi_ref
        else:
            rsi_pass = False

        # ── D1 ────────────────────────────────────────────────────────────────
        # close[3] > open[3] = bull candle 3 bars ago (raw direction check)
        bull_3_ago = (i >= 3 and closes[i - 3] > opens[i - 3])
        d1_raw = (
            (_t("T2", i, 2) and _t("T2", i))    or
            (_t("T2", i, 3) and _t("T3", i))    or
            (_t("T2G", i, 2) and _t("T2G", i))  or
            (bull_3_ago and _t("T3", i))         or
            (_t("T10", i, 2) and _t("T10", i))  or
            (_t("T11", i, 2) and _t("T11", i))  or
            (_t("T12", i, 2) and _t("T12", i))
        )

        # ── D3 ────────────────────────────────────────────────────────────────
        d3_raw = _t("T1", i)

        # ── D4 ────────────────────────────────────────────────────────────────
        d4_raw = _t("T4", i)

        # ── D6 ────────────────────────────────────────────────────────────────
        d6_raw = _t("T6", i)

        # ── D9 ────────────────────────────────────────────────────────────────
        # D9_raw = (T9[1] OR T5[1]) AND (T2G OR T2)
        # t9_from_D* clauses exist in Pine but are NOT part of D9_raw as defined.
        d9_raw = (
            (_t("T9", i, 1) or _t("T5", i, 1)) and
            (_t("T2G", i) or _t("T2", i))
        )

        # ── D11 ───────────────────────────────────────────────────────────────
        # D11_raw = ((Z1G[1] OR Z2G[1] OR Z4[1] OR Z6[1] OR Z1G[2] OR Z2G[2]) AND T1G) OR T1G
        # Simplifies to T1G always, but we keep full form for future branching.
        d11_raw = (
            (
                (_t("Z1G", i, 1) or _t("Z2G", i, 1) or
                 _t("Z4",  i, 1) or _t("Z6",  i, 1) or
                 _t("Z1G", i, 2) or _t("Z2G", i, 2))
                and _t("T1G", i)
            )
            or _t("T1G", i)
        )

        result.append({
            "d1_raw":  d1_raw,
            "d3_raw":  d3_raw,
            "d4_raw":  d4_raw,
            "d6_raw":  d6_raw,
            "d9_raw":  d9_raw,
            "d11_raw": d11_raw,
            "rsi_pass": rsi_pass,
            "d1":  d1_raw  and rsi_pass,
            "d3":  d3_raw  and rsi_pass,
            "d4":  d4_raw  and rsi_pass,
            "d6":  d6_raw  and rsi_pass,
            "d9":  d9_raw  and rsi_pass,
            "d11": d11_raw and rsi_pass,
        })

    return result


# ── Part 3: WLNBB features ────────────────────────────────────────────────────

def compute_wlnbb_features(
    candles:       list[dict],
    ma_period:     int  = 20,
    seq_bars:      int  = 7,
    use_cross_mode: bool = True,
) -> list[dict]:
    """
    Compute WLNBB signals for every bar.
    Ports: WLNBB_OSC bucket classification + L34 / L43 / BE Up logic.

    Returns list same length as candles. Each dict has:
      bucket, l34_raw (=l34_wlnbb), l43_raw (=l43_wlnbb),
      be_up (=be_up_wlnbb), break_up_wlnbb, bx_up_wlnbb, be_up_bo, be_up_bx
    """
    n = len(candles)
    vols   = [float(b["volume"]) for b in candles]
    closes = [b["close"] for b in candles]
    opens  = [b["open"]  for b in candles]
    highs  = [b["high"]  for b in candles]

    sma_v = _sma_series(vols, ma_period)
    std_v = _std_series(vols, ma_period)

    result: list[dict] = []
    # Persistent state for BO/BX tracking (matches Pine var declarations)
    setup_body_high: Optional[float] = None
    setup_body_low:  Optional[float] = None
    setup_bar:       Optional[int]   = None
    bx_body_high:    Optional[float] = None
    bx_body_low:     Optional[float] = None
    bx_bar:          Optional[int]   = None

    for i in range(n):
        v  = vols[i]
        c  = closes[i]
        o  = opens[i]
        h  = highs[i]

        mid = sma_v[i]
        std = std_v[i]

        # ── WLNBB bucket classification ───────────────────────────────────────
        if mid is not None and std is not None:
            vol_mid = mid
            vol_up  = mid + std          # 1σ upper
            vol_low = mid - std          # 1σ lower
            is_w  = v < vol_low
            is_l  = (not is_w) and (v < vol_mid)
            is_n  = (not is_w) and (not is_l) and (v < vol_up)
            is_b  = (not is_w) and (not is_l) and (not is_n) and (v < vol_up + vol_mid)
            is_vb = not (is_w or is_l or is_n or is_b)
        else:
            is_w = is_l = is_n = is_b = is_vb = False
            vol_mid = vol_up = vol_low = None

        _bucket_order = {"W": 0, "L": 1, "N": 2, "B": 3, "VB": 4}
        bucket = ("W" if is_w else "L" if is_l else "N" if is_n
                  else "B" if is_b else "VB" if is_vb else "?")

        prev = result[i - 1] if i > 0 else None
        prev_bucket = prev["bucket"] if prev else None
        pv = vols[i - 1] if i > 0 else None

        same_bucket = (bucket == prev_bucket) if prev_bucket else False
        vol_up_raw  = (v > pv)  if pv is not None else False
        vol_down    = (v < pv)  if pv is not None else False

        if prev_bucket and prev_bucket != "?" and bucket != "?":
            pb_ord = _bucket_order.get(prev_bucket, -1)
            cb_ord = _bucket_order.get(bucket, -1)
            bucket_up   = cb_ord > pb_ord
            bucket_down = cb_ord < pb_ord
        else:
            bucket_up = bucket_down = False

        vol_up_adapted = bucket_up   or (same_bucket and vol_up_raw)

        # ── L conditions ──────────────────────────────────────────────────────
        prev_c  = closes[i - 1] if i > 0 else None
        prev_h  = highs[i - 1]  if i > 0 else None

        up_close         = (c > prev_c)          if prev_c is not None else False
        down_close       = (c < prev_c)           if prev_c is not None else False
        no_new_high_close = (c <= prev_h)          if prev_h is not None else False

        l3_raw = vol_up_adapted and up_close
        l4_raw = vol_up_adapted and no_new_high_close
        l6_raw = vol_up_adapted and down_close

        l34_raw  = l3_raw and l4_raw and (c >= o)
        l64_base = l6_raw and l4_raw
        l43_raw  = l64_base and (c > o)
        l22      = l3_raw and l4_raw and (c < o)

        # ── BO tracking (from last L34 or L22) ───────────────────────────────
        if l34_raw:
            setup_body_high = c
            setup_body_low  = o
            setup_bar       = i
        if l22:
            setup_body_high = o  # L22 stores open as high (bear body)
            setup_body_low  = c
            setup_bar       = i

        has_setup = (setup_body_high is not None and setup_body_low is not None)
        break_up  = False
        if has_setup and setup_bar is not None and i > setup_bar:
            prev_c_bo = closes[i - 1] if i > 0 else None
            if prev_c_bo is not None:
                if use_cross_mode:
                    # crossover: prev close <= setupBodyHigh AND current close > setupBodyHigh
                    break_up = (prev_c_bo <= setup_body_high and c > setup_body_high) and (c > o)
                else:
                    break_up = (c > setup_body_high) and (c > o)
        be_up_bo = break_up and (o <= setup_body_low) if has_setup else False

        # ── BX tracking (from last L43) ───────────────────────────────────────
        if l43_raw:
            bx_body_high = c
            bx_body_low  = o
            bx_bar       = i

        has_bx = (bx_body_high is not None and bx_body_low is not None)
        bx_up  = False
        if has_bx and bx_bar is not None and i > bx_bar:
            prev_c_bx = closes[i - 1] if i > 0 else None
            if prev_c_bx is not None:
                if use_cross_mode:
                    bx_up = (prev_c_bx <= bx_body_high and c > bx_body_high) and (c > o)
                else:
                    bx_up = (c > bx_body_high) and (c > o)
        be_up_bx = bx_up and (o <= bx_body_low) if has_bx else False

        be_up = be_up_bo or be_up_bx

        result.append({
            "bucket":         bucket,
            "l34_wlnbb":      l34_raw,
            "l43_wlnbb":      l43_raw,
            "be_up_wlnbb":    be_up,
            "break_up_wlnbb": break_up,
            "bx_up_wlnbb":    bx_up,
            "be_up_bo":       be_up_bo,
            "be_up_bx":       be_up_bx,
        })

    return result


# ── Part 4: Confluence assembly ───────────────────────────────────────────────

def compute_d_wlnbb_confluence(candles: list[dict]) -> dict:
    """
    Compute Manual D + WLNBB confluence features for the LAST bar of candles.

    Includes:
      - Phase 3: same-bar confluences (original + _same suffix + secondary)
      - Phase 4: L34/L43 → D window (1-3 bars before current)
      - Phase 5: D → BE Up window (1-5 bars before current)
      - Phase 6: d_confluence_type_v2 (22-level) + family/timing/core_signal/
                 wlnbb_signal/window_explanation metadata

    Research-only: no future leakage.
    """
    if not candles:
        return _empty_confluence()

    d_series     = compute_manual_d_features(candles)
    wlnbb_series = compute_wlnbb_features(candles)

    i  = len(candles) - 1
    ld = d_series[i]
    lw = wlnbb_series[i]

    # ── Current-bar D signals ─────────────────────────────────────────────────
    d1  = ld["d1"];  d3  = ld["d3"];  d4  = ld["d4"]
    d6  = ld["d6"];  d9  = ld["d9"];  d11 = ld["d11"]
    d_core_any      = d3 or d4 or d6
    d_secondary_any = d1 or d9 or d11

    # ── Current-bar WLNBB signals ─────────────────────────────────────────────
    l34  = lw["l34_wlnbb"]
    l43  = lw["l43_wlnbb"]
    beup = lw["be_up_wlnbb"]

    # ── Lookback helpers (prev 1..n bars into pre-computed series) ────────────
    def _d_in_prev(key: str, n: int) -> bool:
        for k in range(1, n + 1):
            j = i - k
            if j >= 0 and d_series[j].get(key):
                return True
        return False

    def _w_in_prev(key: str, n: int) -> bool:
        for k in range(1, n + 1):
            j = i - k
            if j >= 0 and wlnbb_series[j].get(key):
                return True
        return False

    def _d_offset(key: str, n: int) -> Optional[int]:
        for k in range(1, n + 1):
            j = i - k
            if j >= 0 and d_series[j].get(key):
                return k
        return None

    def _w_offset(key: str, n: int) -> Optional[int]:
        for k in range(1, n + 1):
            j = i - k
            if j >= 0 and wlnbb_series[j].get(key):
                return k
        return None

    # ── Phase 3: Same-bar confluences ─────────────────────────────────────────
    # Core D × WLNBB (original fields, backward-compat)
    d3_l34  = d3 and l34;   d4_l34  = d4 and l34;   d6_l34  = d6 and l34
    d3_l43  = d3 and l43;   d4_l43  = d4 and l43;   d6_l43  = d6 and l43
    d3_beup = d3 and beup;  d4_beup = d4 and beup;  d6_beup = d6 and beup

    # _same suffix aliases for core (equal to originals; named to contrast window fields)
    d3_l34_same = d3_l34;  d4_l34_same = d4_l34;  d6_l34_same = d6_l34
    d3_l43_same = d3_l43;  d4_l43_same = d4_l43;  d6_l43_same = d6_l43
    d3_beup_same = d3_beup; d4_beup_same = d4_beup; d6_beup_same = d6_beup

    # Secondary D × WLNBB same-bar
    d1_l34_same  = d1 and l34;  d9_l34_same  = d9 and l34;  d11_l34_same  = d11 and l34
    d1_l43_same  = d1 and l43;  d9_l43_same  = d9 and l43;  d11_l43_same  = d11 and l43
    d1_beup_same = d1 and beup; d9_beup_same = d9 and beup; d11_beup_same = d11 and beup

    # Triple: D + L34 + BE_UP same-bar (research/reporting only — does not affect scoring)
    d3_l34_beup_same  = d3 and l34 and beup
    d4_l34_beup_same  = d4 and l34 and beup
    d6_l34_beup_same  = d6 and l34 and beup
    core_d_l34_beup_same = d3_l34_beup_same or d4_l34_beup_same or d6_l34_beup_same

    d1_l34_beup_same  = d1 and l34 and beup
    d9_l34_beup_same  = d9 and l34 and beup
    d11_l34_beup_same = d11 and l34 and beup
    secondary_d_l34_beup_same = d1_l34_beup_same or d9_l34_beup_same or d11_l34_beup_same

    # Aggregate booleans
    core_d_l34  = d_core_any and l34
    core_d_l43  = d_core_any and l43
    core_d_beup = d_core_any and beup
    secondary_d_confluence = d_secondary_any and (l34 or l43 or beup)

    # _same aggregate aliases
    core_d_same      = d_core_any
    secondary_d_same = d_secondary_any
    core_d_l34_same  = core_d_l34
    core_d_l43_same  = core_d_l43
    core_d_beup_same = core_d_beup

    # ── Phase 4: L34/L43 → D window (L34/L43 fired 1-3 bars before D now) ─────
    _l34_prev3 = _w_in_prev("l34_wlnbb", 3)
    _l43_prev3 = _w_in_prev("l43_wlnbb", 3)

    l34_then_d3_3b     = d3  and _l34_prev3
    l34_then_d4_3b     = d4  and _l34_prev3
    l34_then_d6_3b     = d6  and _l34_prev3
    l34_then_d1_3b     = d1  and _l34_prev3
    l34_then_d9_3b     = d9  and _l34_prev3
    l34_then_d11_3b    = d11 and _l34_prev3
    l34_then_core_d_3b = d_core_any and _l34_prev3

    l43_then_d3_3b     = d3  and _l43_prev3
    l43_then_d4_3b     = d4  and _l43_prev3
    l43_then_d6_3b     = d6  and _l43_prev3
    l43_then_d1_3b     = d1  and _l43_prev3
    l43_then_d9_3b     = d9  and _l43_prev3
    l43_then_d11_3b    = d11 and _l43_prev3
    l43_then_core_d_3b = d_core_any and _l43_prev3

    # ── Phase 5: D → BE Up window (D fired 1-5 bars before BE Up now) ─────────
    d3_then_beup_5b          = beup and _d_in_prev("d3",  5)
    d4_then_beup_5b          = beup and _d_in_prev("d4",  5)
    d6_then_beup_5b          = beup and _d_in_prev("d6",  5)
    d1_then_beup_5b          = beup and _d_in_prev("d1",  5)
    d9_then_beup_5b          = beup and _d_in_prev("d9",  5)
    d11_then_beup_5b         = beup and _d_in_prev("d11", 5)
    core_d_then_beup_5b      = beup and (
        _d_in_prev("d3", 5) or _d_in_prev("d4", 5) or _d_in_prev("d6", 5)
    )
    secondary_d_then_beup_5b = beup and (
        _d_in_prev("d1", 5) or _d_in_prev("d9", 5) or _d_in_prev("d11", 5)
    )
    secondary_d_window = (
        (d1_then_beup_5b or d9_then_beup_5b or d11_then_beup_5b) or
        (l34_then_d1_3b  or l34_then_d9_3b  or l34_then_d11_3b) or
        (l43_then_d1_3b  or l43_then_d9_3b  or l43_then_d11_3b)
    )

    # ── Phase 6: d_confluence_type_v2 (22-level priority) ────────────────────
    # Order: D_THEN_BEUP_5B > SAME_BAR_BEUP > L34_THEN_D_3B > SAME_BAR_L34 >
    #        L43_THEN_D_3B > SAME_BAR_L43 > SECONDARY_WINDOW > SECONDARY_SAME >
    #        D_ONLY > NONE
    if   d4_then_beup_5b:        type_v2 = "D4_THEN_BEUP_5B"
    elif d6_then_beup_5b:        type_v2 = "D6_THEN_BEUP_5B"
    elif d3_then_beup_5b:        type_v2 = "D3_THEN_BEUP_5B"
    elif d4_beup:                type_v2 = "D4_BEUP"
    elif d6_beup:                type_v2 = "D6_BEUP"
    elif d3_beup:                type_v2 = "D3_BEUP"
    elif l34_then_d4_3b:         type_v2 = "L34_THEN_D4_3B"
    elif l34_then_d6_3b:         type_v2 = "L34_THEN_D6_3B"
    elif l34_then_d3_3b:         type_v2 = "L34_THEN_D3_3B"
    elif d4_l34:                 type_v2 = "D4_L34"
    elif d6_l34:                 type_v2 = "D6_L34"
    elif d3_l34:                 type_v2 = "D3_L34"
    elif l43_then_d4_3b:         type_v2 = "L43_THEN_D4_3B"
    elif l43_then_d6_3b:         type_v2 = "L43_THEN_D6_3B"
    elif l43_then_d3_3b:         type_v2 = "L43_THEN_D3_3B"
    elif d4_l43:                 type_v2 = "D4_L43"
    elif d6_l43:                 type_v2 = "D6_L43"
    elif d3_l43:                 type_v2 = "D3_L43"
    elif secondary_d_window:     type_v2 = "SECONDARY_D_WINDOW"
    elif secondary_d_confluence: type_v2 = "SECONDARY_D_CONFLUENCE"
    elif d_core_any or d_secondary_any: type_v2 = "D_ONLY"
    else:                        type_v2 = "NONE"

    # Triple confluence type: D + L34 + BE_UP same-bar (independent field, does not replace type_v2)
    if   d4_l34_beup_same:           triple_type = "D4_L34_BEUP_SAME"
    elif d6_l34_beup_same:           triple_type = "D6_L34_BEUP_SAME"
    elif d3_l34_beup_same:           triple_type = "D3_L34_BEUP_SAME"
    elif secondary_d_l34_beup_same:  triple_type = "SECONDARY_D_L34_BEUP_SAME"
    else:                            triple_type = "NONE"
    has_triple_d_l34_beup = triple_type != "NONE"

    # Family
    _FAMILY_MAP = {
        "D4_THEN_BEUP_5B": "D_THEN_BEUP",   "D6_THEN_BEUP_5B": "D_THEN_BEUP",   "D3_THEN_BEUP_5B": "D_THEN_BEUP",
        "D4_BEUP":         "SAME_BAR_BEUP",  "D6_BEUP":         "SAME_BAR_BEUP",  "D3_BEUP":         "SAME_BAR_BEUP",
        "L34_THEN_D4_3B":  "L34_THEN_D",     "L34_THEN_D6_3B":  "L34_THEN_D",     "L34_THEN_D3_3B":  "L34_THEN_D",
        "D4_L34":          "SAME_BAR_L34",   "D6_L34":          "SAME_BAR_L34",   "D3_L34":          "SAME_BAR_L34",
        "L43_THEN_D4_3B":  "L43_THEN_D",     "L43_THEN_D6_3B":  "L43_THEN_D",     "L43_THEN_D3_3B":  "L43_THEN_D",
        "D4_L43":          "SAME_BAR_L43",   "D6_L43":          "SAME_BAR_L43",   "D3_L43":          "SAME_BAR_L43",
        "SECONDARY_D_WINDOW":     "SECONDARY",
        "SECONDARY_D_CONFLUENCE": "SECONDARY",
        "D_ONLY": "D_ONLY", "NONE": "NONE",
    }
    family = _FAMILY_MAP.get(type_v2, "NONE")

    # Timing
    _TIMING_MAP = {
        "D4_THEN_BEUP_5B": "D_THEN_BEUP_5B", "D6_THEN_BEUP_5B": "D_THEN_BEUP_5B", "D3_THEN_BEUP_5B": "D_THEN_BEUP_5B",
        "D4_BEUP":         "SAME_BAR",        "D6_BEUP":         "SAME_BAR",        "D3_BEUP":         "SAME_BAR",
        "L34_THEN_D4_3B":  "BASE_THEN_D_3B",  "L34_THEN_D6_3B":  "BASE_THEN_D_3B",  "L34_THEN_D3_3B":  "BASE_THEN_D_3B",
        "D4_L34":          "SAME_BAR",        "D6_L34":          "SAME_BAR",        "D3_L34":          "SAME_BAR",
        "L43_THEN_D4_3B":  "BASE_THEN_D_3B",  "L43_THEN_D6_3B":  "BASE_THEN_D_3B",  "L43_THEN_D3_3B":  "BASE_THEN_D_3B",
        "D4_L43":          "SAME_BAR",        "D6_L43":          "SAME_BAR",        "D3_L43":          "SAME_BAR",
        "SECONDARY_D_WINDOW":     "BASE_THEN_D_3B",
        "SECONDARY_D_CONFLUENCE": "SAME_BAR",
        "D_ONLY": "NONE", "NONE": "NONE",
    }
    timing = _TIMING_MAP.get(type_v2, "NONE")

    # Core signal
    _CORE_SIG_MAP = {
        "D4_THEN_BEUP_5B": "D4", "D4_BEUP": "D4", "L34_THEN_D4_3B": "D4", "D4_L34": "D4", "L43_THEN_D4_3B": "D4", "D4_L43": "D4",
        "D6_THEN_BEUP_5B": "D6", "D6_BEUP": "D6", "L34_THEN_D6_3B": "D6", "D6_L34": "D6", "L43_THEN_D6_3B": "D6", "D6_L43": "D6",
        "D3_THEN_BEUP_5B": "D3", "D3_BEUP": "D3", "L34_THEN_D3_3B": "D3", "D3_L34": "D3", "L43_THEN_D3_3B": "D3", "D3_L43": "D3",
    }
    core_sig = _CORE_SIG_MAP.get(type_v2)
    if core_sig is None:
        if d1: core_sig = "D1"
        elif d9: core_sig = "D9"
        elif d11: core_sig = "D11"
        else: core_sig = "NONE"

    # WLNBB signal
    _WLNBB_SIG_MAP = {
        "D4_THEN_BEUP_5B": "BE_UP", "D6_THEN_BEUP_5B": "BE_UP", "D3_THEN_BEUP_5B": "BE_UP",
        "D4_BEUP": "BE_UP", "D6_BEUP": "BE_UP", "D3_BEUP": "BE_UP",
        "L34_THEN_D4_3B": "L34", "L34_THEN_D6_3B": "L34", "L34_THEN_D3_3B": "L34",
        "D4_L34": "L34", "D6_L34": "L34", "D3_L34": "L34",
        "L43_THEN_D4_3B": "L43", "L43_THEN_D6_3B": "L43", "L43_THEN_D3_3B": "L43",
        "D4_L43": "L43", "D6_L43": "L43", "D3_L43": "L43",
    }
    wlnbb_sig = _WLNBB_SIG_MAP.get(type_v2)
    if wlnbb_sig is None:
        if type_v2 == "SECONDARY_D_WINDOW":
            if d1_then_beup_5b or d9_then_beup_5b or d11_then_beup_5b:  wlnbb_sig = "BE_UP"
            elif l34_then_d1_3b or l34_then_d9_3b or l34_then_d11_3b:   wlnbb_sig = "L34"
            elif l43_then_d1_3b or l43_then_d9_3b or l43_then_d11_3b:   wlnbb_sig = "L43"
            else:                                                          wlnbb_sig = "NONE"
        elif type_v2 == "SECONDARY_D_CONFLUENCE":
            if beup:   wlnbb_sig = "BE_UP"
            elif l34:  wlnbb_sig = "L34"
            elif l43:  wlnbb_sig = "L43"
            else:      wlnbb_sig = "NONE"
        else:
            wlnbb_sig = "NONE"

    # Window explanation (human-readable)
    if   type_v2 == "D4_THEN_BEUP_5B":
        off = _d_offset("d4", 5); expl = f"D4 fired {off}b before BE Up" if off else "D4 then BE Up (window)"
    elif type_v2 == "D6_THEN_BEUP_5B":
        off = _d_offset("d6", 5); expl = f"D6 fired {off}b before BE Up" if off else "D6 then BE Up (window)"
    elif type_v2 == "D3_THEN_BEUP_5B":
        off = _d_offset("d3", 5); expl = f"D3 fired {off}b before BE Up" if off else "D3 then BE Up (window)"
    elif type_v2 == "D4_BEUP":          expl = "D4 + BE Up same bar"
    elif type_v2 == "D6_BEUP":          expl = "D6 + BE Up same bar"
    elif type_v2 == "D3_BEUP":          expl = "D3 + BE Up same bar"
    elif type_v2 == "L34_THEN_D4_3B":
        off = _w_offset("l34_wlnbb", 3); expl = f"L34 fired {off}b before D4" if off else "L34 then D4 (window)"
    elif type_v2 == "L34_THEN_D6_3B":
        off = _w_offset("l34_wlnbb", 3); expl = f"L34 fired {off}b before D6" if off else "L34 then D6 (window)"
    elif type_v2 == "L34_THEN_D3_3B":
        off = _w_offset("l34_wlnbb", 3); expl = f"L34 fired {off}b before D3" if off else "L34 then D3 (window)"
    elif type_v2 == "D4_L34":           expl = "D4 + L34 same bar"
    elif type_v2 == "D6_L34":           expl = "D6 + L34 same bar"
    elif type_v2 == "D3_L34":           expl = "D3 + L34 same bar"
    elif type_v2 == "L43_THEN_D4_3B":
        off = _w_offset("l43_wlnbb", 3); expl = f"L43 fired {off}b before D4" if off else "L43 then D4 (window)"
    elif type_v2 == "L43_THEN_D6_3B":
        off = _w_offset("l43_wlnbb", 3); expl = f"L43 fired {off}b before D6" if off else "L43 then D6 (window)"
    elif type_v2 == "L43_THEN_D3_3B":
        off = _w_offset("l43_wlnbb", 3); expl = f"L43 fired {off}b before D3" if off else "L43 then D3 (window)"
    elif type_v2 == "D4_L43":           expl = "D4 + L43 same bar"
    elif type_v2 == "D6_L43":           expl = "D6 + L43 same bar"
    elif type_v2 == "D3_L43":           expl = "D3 + L43 same bar"
    elif type_v2 == "SECONDARY_D_WINDOW":     expl = "Secondary D in window confluence"
    elif type_v2 == "SECONDARY_D_CONFLUENCE": expl = "Secondary D + WLNBB same bar"
    elif type_v2 == "D_ONLY":                 expl = "D signal present, no WLNBB"
    else:                                      expl = ""

    # ── Legacy d_confluence_type (v1, same-bar only, kept for backward compat) ─
    if   d4_beup:                d_confluence_type = "D4_BEUP"
    elif d6_beup:                d_confluence_type = "D6_BEUP"
    elif d3_beup:                d_confluence_type = "D3_BEUP"
    elif d4_l34:                 d_confluence_type = "D4_L34"
    elif d6_l34:                 d_confluence_type = "D6_L34"
    elif d3_l34:                 d_confluence_type = "D3_L34"
    elif d4_l43:                 d_confluence_type = "D4_L43"
    elif d6_l43:                 d_confluence_type = "D6_L43"
    elif d3_l43:                 d_confluence_type = "D3_L43"
    elif secondary_d_confluence: d_confluence_type = "SECONDARY_D_CONFLUENCE"
    else:                        d_confluence_type = "NONE"

    active_d: list[str] = [s for s, v in [("D1",d1),("D3",d3),("D4",d4),("D6",d6),("D9",d9),("D11",d11)] if v]
    active_wlnbb: list[str] = []
    if l34:  active_wlnbb.append("L34")
    if l43:  active_wlnbb.append("L43")
    if beup: active_wlnbb.append("BE_UP")

    return {
        # ── D signals ─────────────────────────────────────────────────────────
        "d1": d1, "d3": d3, "d4": d4, "d6": d6, "d9": d9, "d11": d11,
        "d_core_any": d_core_any, "d_secondary_any": d_secondary_any,
        "active_d_signals": active_d,
        # ── WLNBB signals ─────────────────────────────────────────────────────
        "l34_wlnbb": l34, "l43_wlnbb": l43, "be_up_wlnbb": beup,
        "break_up_wlnbb": lw["break_up_wlnbb"], "bx_up_wlnbb": lw["bx_up_wlnbb"],
        "active_wlnbb_signals": active_wlnbb,
        # ── Phase 3: Same-bar confluences (original, backward-compat) ─────────
        "d3_l34": d3_l34, "d4_l34": d4_l34, "d6_l34": d6_l34,
        "d3_l43": d3_l43, "d4_l43": d4_l43, "d6_l43": d6_l43,
        "d3_beup": d3_beup, "d4_beup": d4_beup, "d6_beup": d6_beup,
        "core_d_l34": core_d_l34, "core_d_l43": core_d_l43, "core_d_beup": core_d_beup,
        "secondary_d_confluence": secondary_d_confluence,
        # ── Phase 3: Same-bar confluences (_same suffix) ───────────────────────
        "d3_l34_same": d3_l34_same, "d4_l34_same": d4_l34_same, "d6_l34_same": d6_l34_same,
        "d3_l43_same": d3_l43_same, "d4_l43_same": d4_l43_same, "d6_l43_same": d6_l43_same,
        "d3_beup_same": d3_beup_same, "d4_beup_same": d4_beup_same, "d6_beup_same": d6_beup_same,
        "d1_l34_same": d1_l34_same, "d9_l34_same": d9_l34_same, "d11_l34_same": d11_l34_same,
        "d1_l43_same": d1_l43_same, "d9_l43_same": d9_l43_same, "d11_l43_same": d11_l43_same,
        "d1_beup_same": d1_beup_same, "d9_beup_same": d9_beup_same, "d11_beup_same": d11_beup_same,
        "core_d_same": core_d_same, "secondary_d_same": secondary_d_same,
        "core_d_l34_same": core_d_l34_same, "core_d_l43_same": core_d_l43_same, "core_d_beup_same": core_d_beup_same,
        # ── Phase 4: L34/L43 → D window (1-3 bars) ───────────────────────────
        "l34_then_d3_3b": l34_then_d3_3b, "l34_then_d4_3b": l34_then_d4_3b, "l34_then_d6_3b": l34_then_d6_3b,
        "l34_then_d1_3b": l34_then_d1_3b, "l34_then_d9_3b": l34_then_d9_3b, "l34_then_d11_3b": l34_then_d11_3b,
        "l34_then_core_d_3b": l34_then_core_d_3b,
        "l43_then_d3_3b": l43_then_d3_3b, "l43_then_d4_3b": l43_then_d4_3b, "l43_then_d6_3b": l43_then_d6_3b,
        "l43_then_d1_3b": l43_then_d1_3b, "l43_then_d9_3b": l43_then_d9_3b, "l43_then_d11_3b": l43_then_d11_3b,
        "l43_then_core_d_3b": l43_then_core_d_3b,
        # ── Phase 5: D → BE Up window (1-5 bars) ─────────────────────────────
        "d3_then_beup_5b": d3_then_beup_5b, "d4_then_beup_5b": d4_then_beup_5b, "d6_then_beup_5b": d6_then_beup_5b,
        "d1_then_beup_5b": d1_then_beup_5b, "d9_then_beup_5b": d9_then_beup_5b, "d11_then_beup_5b": d11_then_beup_5b,
        "core_d_then_beup_5b": core_d_then_beup_5b,
        "secondary_d_then_beup_5b": secondary_d_then_beup_5b,
        "secondary_d_window": secondary_d_window,
        # ── Phase 6: d_confluence_type_v2 + metadata ──────────────────────────
        "d_confluence_type_v2":      type_v2,
        "d_confluence_family":       family,
        "d_confluence_timing":       timing,
        "d_confluence_core_signal":  core_sig,
        "d_confluence_wlnbb_signal": wlnbb_sig,
        "window_explanation":        expl,
        # ── Triple: D + L34 + BE_UP same-bar (research/reporting only) ────────
        "d3_l34_beup_same":  d3_l34_beup_same,
        "d4_l34_beup_same":  d4_l34_beup_same,
        "d6_l34_beup_same":  d6_l34_beup_same,
        "core_d_l34_beup_same": core_d_l34_beup_same,
        "d1_l34_beup_same":  d1_l34_beup_same,
        "d9_l34_beup_same":  d9_l34_beup_same,
        "d11_l34_beup_same": d11_l34_beup_same,
        "secondary_d_l34_beup_same": secondary_d_l34_beup_same,
        "d_triple_confluence_type": triple_type,
        "has_triple_d_l34_beup":    has_triple_d_l34_beup,
        # ── Legacy v1 (kept for backward compat) ──────────────────────────────
        "d_confluence_type": d_confluence_type,
    }


def _empty_confluence() -> dict:
    return {
        # D signals
        "d1": False, "d3": False, "d4": False, "d6": False, "d9": False, "d11": False,
        "d_core_any": False, "d_secondary_any": False, "active_d_signals": [],
        # WLNBB signals
        "l34_wlnbb": False, "l43_wlnbb": False, "be_up_wlnbb": False,
        "break_up_wlnbb": False, "bx_up_wlnbb": False, "active_wlnbb_signals": [],
        # Phase 3: same-bar (original)
        "d3_l34": False, "d4_l34": False, "d6_l34": False,
        "d3_l43": False, "d4_l43": False, "d6_l43": False,
        "d3_beup": False, "d4_beup": False, "d6_beup": False,
        "core_d_l34": False, "core_d_l43": False, "core_d_beup": False,
        "secondary_d_confluence": False,
        # Phase 3: same-bar (_same suffix)
        "d3_l34_same": False, "d4_l34_same": False, "d6_l34_same": False,
        "d3_l43_same": False, "d4_l43_same": False, "d6_l43_same": False,
        "d3_beup_same": False, "d4_beup_same": False, "d6_beup_same": False,
        "d1_l34_same": False, "d9_l34_same": False, "d11_l34_same": False,
        "d1_l43_same": False, "d9_l43_same": False, "d11_l43_same": False,
        "d1_beup_same": False, "d9_beup_same": False, "d11_beup_same": False,
        "core_d_same": False, "secondary_d_same": False,
        "core_d_l34_same": False, "core_d_l43_same": False, "core_d_beup_same": False,
        # Phase 4: L34/L43 → D window
        "l34_then_d3_3b": False, "l34_then_d4_3b": False, "l34_then_d6_3b": False,
        "l34_then_d1_3b": False, "l34_then_d9_3b": False, "l34_then_d11_3b": False,
        "l34_then_core_d_3b": False,
        "l43_then_d3_3b": False, "l43_then_d4_3b": False, "l43_then_d6_3b": False,
        "l43_then_d1_3b": False, "l43_then_d9_3b": False, "l43_then_d11_3b": False,
        "l43_then_core_d_3b": False,
        # Phase 5: D → BE Up window
        "d3_then_beup_5b": False, "d4_then_beup_5b": False, "d6_then_beup_5b": False,
        "d1_then_beup_5b": False, "d9_then_beup_5b": False, "d11_then_beup_5b": False,
        "core_d_then_beup_5b": False, "secondary_d_then_beup_5b": False,
        "secondary_d_window": False,
        # Phase 6: type_v2 + metadata
        "d_confluence_type_v2":      "NONE",
        "d_confluence_family":       "NONE",
        "d_confluence_timing":       "NONE",
        "d_confluence_core_signal":  "NONE",
        "d_confluence_wlnbb_signal": "NONE",
        "window_explanation":        "",
        # Triple: D + L34 + BE_UP same-bar
        "d3_l34_beup_same": False, "d4_l34_beup_same": False, "d6_l34_beup_same": False,
        "core_d_l34_beup_same": False,
        "d1_l34_beup_same": False, "d9_l34_beup_same": False, "d11_l34_beup_same": False,
        "secondary_d_l34_beup_same": False,
        "d_triple_confluence_type": "NONE",
        "has_triple_d_l34_beup":    False,
        # Legacy v1
        "d_confluence_type": "NONE",
    }


# ── Pre-window count helpers (for pump study / replay) ────────────────────────

_D_COUNT_FIELDS = [
    "d1", "d3", "d4", "d6", "d9", "d11",
    "d_core_any", "d_secondary_any",
    # same-bar (original)
    "d3_l34", "d4_l34", "d6_l34",
    "d3_l43", "d4_l43", "d6_l43",
    "d3_beup", "d4_beup", "d6_beup",
    "core_d_l34", "core_d_l43", "core_d_beup",
    # same-bar (_same suffix)
    "d3_l34_same", "d4_l34_same", "d6_l34_same",
    "d3_l43_same", "d4_l43_same", "d6_l43_same",
    "d3_beup_same", "d4_beup_same", "d6_beup_same",
    "core_d_l34_same", "core_d_l43_same", "core_d_beup_same",
    # window L34/L43 → D (3 bars)
    "l34_then_d3_3b", "l34_then_d4_3b", "l34_then_d6_3b",
    "l43_then_d3_3b", "l43_then_d4_3b", "l43_then_d6_3b",
    "l34_then_core_d_3b", "l43_then_core_d_3b",
    # window D → BE Up (5 bars)
    "d3_then_beup_5b", "d4_then_beup_5b", "d6_then_beup_5b",
    "core_d_then_beup_5b",
    # triple: D + L34 + BE_UP same-bar
    "d3_l34_beup_same", "d4_l34_beup_same", "d6_l34_beup_same",
    "core_d_l34_beup_same",
    "d1_l34_beup_same", "d9_l34_beup_same", "d11_l34_beup_same",
    "secondary_d_l34_beup_same",
]


def compute_d_wlnbb_pre_counts(
    candles: list[dict],
    signal_bar_idx: int,
    lookback: int = 20,
) -> dict:
    """
    Count D / WLNBB confluence events in the `lookback` bars BEFORE signal_bar_idx.
    Uses full candle history up to signal_bar_idx so window fields (l34_then_d4_3b
    etc.) have correct cross-bar lookback.

    signal_bar_idx: 0-based index of the signal bar (exclusive upper bound).
    lookback: number of bars before signal to examine.
    Returns dict of {field}_count_pre keys.
    """
    start = max(0, signal_bar_idx - lookback)
    end   = signal_bar_idx  # exclusive

    if start >= end or not candles:
        return {f"{f}_count_pre": 0 for f in _D_COUNT_FIELDS}

    full_candles = candles[:signal_bar_idx]
    if not full_candles:
        return {f"{f}_count_pre": 0 for f in _D_COUNT_FIELDS}

    d_series     = compute_manual_d_features(full_candles)
    wlnbb_series = compute_wlnbb_features(full_candles)

    counts: dict[str, int] = {f: 0 for f in _D_COUNT_FIELDS}

    for bar_i in range(start, min(end, len(full_candles))):
        d    = d_series[bar_i]
        w    = wlnbb_series[bar_i]
        l34_ = w["l34_wlnbb"];  l43_ = w["l43_wlnbb"];  beup_ = w["be_up_wlnbb"]
        d3_  = d["d3"];  d4_  = d["d4"];  d6_  = d["d6"]
        d1_  = d["d1"];  d9_  = d["d9"];  d11_ = d["d11"]
        dcore_ = d3_ or d4_ or d6_

        def _dp(key: str, n: int) -> bool:
            for k in range(1, n + 1):
                j = bar_i - k
                if j >= 0 and d_series[j].get(key):
                    return True
            return False

        def _wp(key: str, n: int) -> bool:
            for k in range(1, n + 1):
                j = bar_i - k
                if j >= 0 and wlnbb_series[j].get(key):
                    return True
            return False

        bar_fields: dict = {
            "d1": d1_, "d3": d3_, "d4": d4_, "d6": d6_, "d9": d9_, "d11": d11_,
            "d_core_any": dcore_, "d_secondary_any": d1_ or d9_ or d11_,
            # same-bar (original)
            "d3_l34": d3_ and l34_, "d4_l34": d4_ and l34_, "d6_l34": d6_ and l34_,
            "d3_l43": d3_ and l43_, "d4_l43": d4_ and l43_, "d6_l43": d6_ and l43_,
            "d3_beup": d3_ and beup_, "d4_beup": d4_ and beup_, "d6_beup": d6_ and beup_,
            "core_d_l34": dcore_ and l34_, "core_d_l43": dcore_ and l43_, "core_d_beup": dcore_ and beup_,
            # same-bar (_same — equal to originals)
            "d3_l34_same": d3_ and l34_, "d4_l34_same": d4_ and l34_, "d6_l34_same": d6_ and l34_,
            "d3_l43_same": d3_ and l43_, "d4_l43_same": d4_ and l43_, "d6_l43_same": d6_ and l43_,
            "d3_beup_same": d3_ and beup_, "d4_beup_same": d4_ and beup_, "d6_beup_same": d6_ and beup_,
            "core_d_l34_same": dcore_ and l34_, "core_d_l43_same": dcore_ and l43_, "core_d_beup_same": dcore_ and beup_,
            # window L34/L43 → D
            "l34_then_d3_3b": d3_ and _wp("l34_wlnbb", 3),
            "l34_then_d4_3b": d4_ and _wp("l34_wlnbb", 3),
            "l34_then_d6_3b": d6_ and _wp("l34_wlnbb", 3),
            "l43_then_d3_3b": d3_ and _wp("l43_wlnbb", 3),
            "l43_then_d4_3b": d4_ and _wp("l43_wlnbb", 3),
            "l43_then_d6_3b": d6_ and _wp("l43_wlnbb", 3),
            "l34_then_core_d_3b": dcore_ and _wp("l34_wlnbb", 3),
            "l43_then_core_d_3b": dcore_ and _wp("l43_wlnbb", 3),
            # window D → BE Up
            "d3_then_beup_5b": beup_ and _dp("d3", 5),
            "d4_then_beup_5b": beup_ and _dp("d4", 5),
            "d6_then_beup_5b": beup_ and _dp("d6", 5),
            "core_d_then_beup_5b": beup_ and (_dp("d3", 5) or _dp("d4", 5) or _dp("d6", 5)),
            # triple: D + L34 + BE_UP same-bar
            "d3_l34_beup_same":  d3_ and l34_ and beup_,
            "d4_l34_beup_same":  d4_ and l34_ and beup_,
            "d6_l34_beup_same":  d6_ and l34_ and beup_,
            "core_d_l34_beup_same": (d3_ or d4_ or d6_) and l34_ and beup_,
            "d1_l34_beup_same":  d1_ and l34_ and beup_,
            "d9_l34_beup_same":  d9_ and l34_ and beup_,
            "d11_l34_beup_same": d11_ and l34_ and beup_,
            "secondary_d_l34_beup_same": (d1_ or d9_ or d11_) and l34_ and beup_,
        }

        for f in _D_COUNT_FIELDS:
            if bar_fields.get(f):
                counts[f] += 1

    return {f"{f}_count_pre": counts[f] for f in _D_COUNT_FIELDS}
