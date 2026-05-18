"""
ABR / TZ Quality Engine — Research Only.

Ports the logical layer from Pine Script: 260519_TZ_F_WLNBB_CMB — ABR.

Computes per-bar:
  - Suffix logic (NE, wick, penetration)
  - Z8 pattern (missing from compute_tz_selected)
  - PREUP / PREDN EMA-cross signals
  - WLNBB L1-L6 raw signals (volDownAdapted path)
  - ABR quality score + tier (SP500 / NASDAQ)
  - ABR classification (A / B / B+ / R)

Anti-leakage contract:
  All computation uses only OHLCV + technical indicators.
  No outcome fields (pump_multiple, group_type, future returns) used.

RESEARCH ONLY — do not wire to Scanner V2 routing.
"""

from __future__ import annotations

import math
from typing import Optional

from scanner.manual_d_wlnbb_features import compute_tz_selected, compute_wlnbb_features


# ── EMA helpers ───────────────────────────────────────────────────────────────

def _ema_series(closes: list[float], period: int) -> list[Optional[float]]:
    """Standard EMA seeded from SMA. Returns None until period-1 bars."""
    n = len(closes)
    result: list[Optional[float]] = [None] * n
    if n < period:
        return result
    seed = sum(closes[:period]) / period
    result[period - 1] = seed
    k = 2.0 / (period + 1)
    for i in range(period, n):
        prev = result[i - 1]
        result[i] = closes[i] * k + prev * (1.0 - k) if prev is not None else None
    return result


# ── Signal score lookup ───────────────────────────────────────────────────────

_SIGNAL_SCORE_3: frozenset[str] = frozenset({
    "T4", "T3", "T6", "T11", "T12",
    "Z4", "Z6", "Z5", "Z3",
})
_SIGNAL_SCORE_2: frozenset[str] = frozenset({
    "T5", "T1G", "T9", "T1", "T2G",
    "Z2G", "Z9", "Z11", "Z10", "Z1G", "Z2", "Z1",
})


def _signal_score(sig: Optional[str]) -> int:
    if sig is None:
        return 0
    if sig in _SIGNAL_SCORE_3:
        return 3
    if sig in _SIGNAL_SCORE_2:
        return 2
    return 1


# ── Tier helpers ──────────────────────────────────────────────────────────────

def _sp500_tier(score: int) -> str:
    if score >= 6:  return "STRONG"
    if score >= 4:  return "GOOD"
    if score < 2:   return "REJECT"
    return "AVERAGE"


def _nasdaq_tier(score: int) -> str:
    if score >= 5:  return "STRONG"
    if score >= 3:  return "GOOD"
    if score < 1:   return "REJECT"
    return "AVERAGE"


# ── ABR classification ────────────────────────────────────────────────────────

def _abr(gate_ok: bool, prev2_tier: str) -> str:
    if not gate_ok:
        return "R"
    if prev2_tier == "AVERAGE":  return "A"
    if prev2_tier == "GOOD":     return "B"
    if prev2_tier == "STRONG":   return "B+"
    return "R"


# ── Main engine ───────────────────────────────────────────────────────────────

def compute_abr_tz_features(candles: list[dict]) -> list[dict]:
    """
    Compute all ABR/TZ quality features for a sequence of OHLCV candles.

    Parameters
    ----------
    candles : list of dicts, oldest-first, each with keys:
              open, high, low, close, volume

    Returns
    -------
    List of per-bar feature dicts (same length as candles).
    """
    n = len(candles)
    if n == 0:
        return []

    opens   = [float(c.get("open")   or 0.0) for c in candles]
    highs   = [float(c.get("high")   or 0.0) for c in candles]
    lows    = [float(c.get("low")    or 0.0) for c in candles]
    closes  = [float(c.get("close")  or 0.0) for c in candles]
    volumes = [float(c.get("volume") or 0.0) for c in candles]

    # ── EMAs ─────────────────────────────────────────────────────────────────
    ema9   = _ema_series(closes, 9)
    ema20  = _ema_series(closes, 20)
    ema34  = _ema_series(closes, 34)
    ema50  = _ema_series(closes, 50)
    ema89  = _ema_series(closes, 89)
    ema200 = _ema_series(closes, 200)

    # ── T/Z signals (reuse existing priority engine) ──────────────────────────
    tz_series = compute_tz_selected(candles)

    # ── WLNBB (bucket + L34/L43/L64/L22/be_up) ───────────────────────────────
    wlnbb_series = compute_wlnbb_features(candles)

    # ── WLNBB volume Bollinger for L1-L6 raw signals ─────────────────────────
    _TINY = 1e-10
    ma_period = 20

    # SMA and std of volume for Bollinger
    def _sma(vals: list[float], i: int, period: int) -> Optional[float]:
        if i < period - 1:
            return None
        return sum(vals[i - period + 1: i + 1]) / period

    def _std(vals: list[float], i: int, period: int) -> Optional[float]:
        if i < period - 1:
            return None
        win = vals[i - period + 1: i + 1]
        m = sum(win) / period
        var = sum((x - m) ** 2 for x in win) / period
        return math.sqrt(var)

    # Pre-pass: compute WLNBB bucket order and volDownAdapted for each bar
    _BUCKET_ORDER = {"W": 0, "L": 1, "N": 2, "B": 3, "VB": 4}

    vol_down_adapted: list[bool] = [False] * n
    vol_up_adapted_l: list[bool] = [False] * n

    prev_bucket_str: Optional[str] = None
    for i in range(n):
        v   = volumes[i]
        mid = _sma(volumes, i, ma_period)
        std = _std(volumes, i, ma_period)

        if mid is not None and std is not None:
            vol_low = mid - std
            vol_up  = mid + std
            is_w  = v < vol_low
            is_l  = (not is_w) and (v < mid)
            is_n  = (not is_w) and (not is_l) and (v < vol_up)
            is_b  = (not is_w) and (not is_l) and (not is_n) and (v < vol_up + mid)
            is_vb = not (is_w or is_l or is_n or is_b)
            cur_b = "W" if is_w else "L" if is_l else "N" if is_n else "B" if is_b else "VB"
        else:
            cur_b = "?"

        pv = volumes[i - 1] if i > 0 else None
        vol_up_raw = (v > pv)  if pv is not None else False
        vol_down   = (v < pv)  if pv is not None else False

        if prev_bucket_str and prev_bucket_str != "?" and cur_b != "?":
            pb_ord = _BUCKET_ORDER.get(prev_bucket_str, -1)
            cb_ord = _BUCKET_ORDER.get(cur_b, -1)
            bucket_up_flag   = cb_ord > pb_ord
            bucket_down_flag = cb_ord < pb_ord
        else:
            bucket_up_flag = bucket_down_flag = False

        same_bucket = (cur_b == prev_bucket_str) if prev_bucket_str else False

        vol_down_adapted[i] = bucket_down_flag or (same_bucket and vol_down)
        vol_up_adapted_l[i] = bucket_up_flag   or (same_bucket and vol_up_raw)

        prev_bucket_str = cur_b

    # ── First pass: suffix, Z8, PREUP/PREDN, L1-L6, quality score, tier ──────
    # We need prev1/prev2 quality scores for ABR classification, so do two passes.

    pass1: list[dict] = []

    for i in range(n):
        o  = opens[i];   c  = closes[i]
        h  = highs[i];   l  = lows[i]
        pv = volumes[i]

        tz  = tz_series[i]
        wl  = wlnbb_series[i]

        # ── Suffix logic ──────────────────────────────────────────────────────
        if i == 0:
            ne_suf       = "N"
            wick_suf     = ""
            pen_suf      = ""
            close_suf    = ""
            append_close = False
        else:
            o1 = opens[i-1];  c1 = closes[i-1]
            h1 = highs[i-1];  l1 = lows[i-1]

            # NE suffix
            ne_suf = "E" if (c > h1 or c < l1) else "N"

            # Wick-extension suffix
            wick_ext_up   = h > h1
            wick_ext_down = l < l1
            if wick_ext_up and wick_ext_down:
                wick_suf = "B"
            elif wick_ext_up:
                wick_suf = "U"
            elif wick_ext_down:
                wick_suf = "D"
            else:
                wick_suf = ""

            # Penetration suffix
            prev_body_top = max(o1, c1)
            prev_body_bot = min(o1, c1)
            wick_in_upper = (h >= prev_body_top) and (h <= h1)
            wick_in_lower = (l <= prev_body_bot) and (l >= l1)
            if wick_in_upper and wick_in_lower:
                pen_suf = "H"
            elif wick_in_upper:
                pen_suf = "P"
            elif wick_in_lower:
                pen_suf = "R"
            else:
                pen_suf = ""

            # Close-position suffix (where close lands vs prev body)
            if c > prev_body_top:
                close_suf = "A"
            elif c < prev_body_bot:
                close_suf = "O"
            else:
                close_suf = "I"

            # Pine: appendClose decides whether close_suf is shown
            append_close = (
                (ne_suf == "E" and wick_suf == "B")
                or (ne_suf == "N" and (wick_suf != "" or pen_suf != ""))
            )

        # Core suffix used for scoring (matches legacy 2-3 char map)
        core_suf = ne_suf + wick_suf + pen_suf
        # Full suffix matches Pine display: appends close_suf when append_close
        full_suf = core_suf + (close_suf if append_close else "")

        # ── Z8 (missing from compute_tz_selected) ────────────────────────────
        # Z8 requires prev bar info and other Z flags NOT being set
        has_z8 = False
        if i > 0:
            o1 = opens[i-1]; c1 = closes[i-1]
            h1 = highs[i-1]; l1 = lows[i-1]
            prev_z7_raw = pass1[i-1]["_z7_raw_abr"] if i > 0 else False
            prev1_is_bull_z8 = (c1 > o1)
            is_bear_z8 = (c < o)
            z8_base = prev1_is_bull_z8 and (o > c1) and is_bear_z8 and (c >= o1)
            if z8_base:
                # Z8 only fires when no other Z signal present
                existing_z_code = tz.get("bear_code", 0)
                has_z8 = (existing_z_code == 0)

        # ── Determine primary T/Z signal name ────────────────────────────────
        bull_code = tz.get("bull_code", 0)
        bear_code = tz.get("bear_code", 0)
        # Adjust bear_code: Z7 was at 13 in existing engine;
        # in spec Z8=13, Z7=14 — remap if Z8 fires
        if has_z8 and bear_code == 0:
            effective_bear_code = 13
        else:
            effective_bear_code = bear_code
            if bear_code == 13:  # existing Z7_clean is now 14
                effective_bear_code = 14

        _T_NAMES = {1:"T4",2:"T6",3:"T1G",4:"T2G",5:"T1",6:"T2",
                    7:"T9",8:"T10",9:"T3",10:"T11",11:"T5",12:"T12"}
        _Z_NAMES = {1:"Z4",2:"Z6",3:"Z1G",4:"Z2G",5:"Z1",6:"Z2",
                    7:"Z9",8:"Z10",9:"Z3",10:"Z11",11:"Z5",12:"Z12",
                    13:"Z8",14:"Z7"}

        tz_signal: Optional[str] = None
        tz_side:   Optional[str] = None
        if bull_code > 0:
            tz_signal = _T_NAMES.get(bull_code)
            tz_side   = "T"
        elif effective_bear_code > 0:
            tz_signal = _Z_NAMES.get(effective_bear_code)
            tz_side   = "Z"

        # ── PREUP EMA-cross logic ─────────────────────────────────────────────
        def _cross_up(ema_arr: list[Optional[float]]) -> bool:
            e = ema_arr[i]
            return e is not None and opens[i] < e and closes[i] > e

        def _drop_dn(ema_arr: list[Optional[float]]) -> bool:
            e = ema_arr[i]
            return e is not None and opens[i] > e and closes[i] < e

        cu9   = _cross_up(ema9)
        cu20  = _cross_up(ema20)
        cu34  = _cross_up(ema34)
        cu50  = _cross_up(ema50)
        cu89  = _cross_up(ema89)
        cu200 = _cross_up(ema200)

        dd9   = _drop_dn(ema9)
        dd20  = _drop_dn(ema20)
        dd34  = _drop_dn(ema34)
        dd50  = _drop_dn(ema50)
        dd89  = _drop_dn(ema89)
        dd200 = _drop_dn(ema200)

        # PREUP raw signals
        raw_p66 = cu200 and (cu9 or cu20 or cu34 or cu50 or cu89)
        raw_p55 = cu89  and (cu9 or cu20 or cu34 or cu50 or cu200)
        raw_p3  = cu9 and cu20 and cu50
        raw_p2  = cu9 and cu20
        raw_p50 = cu50

        has_preup66 = raw_p66
        has_preup55 = raw_p55 and not raw_p66
        has_preup89 = cu89 and not raw_p55 and not raw_p66
        has_preup3  = raw_p3  and not raw_p55 and not raw_p66 and not cu89
        has_preup2  = raw_p2  and not raw_p3  and not raw_p55 and not raw_p66 and not cu89
        has_preup50 = raw_p50 and not raw_p2  and not raw_p3  and not raw_p55 and not raw_p66 and not cu89

        if has_preup66:   preup_primary = "P66"
        elif has_preup55: preup_primary = "P55"
        elif has_preup89: preup_primary = "P89"
        elif has_preup3:  preup_primary = "P3"
        elif has_preup2:  preup_primary = "P2"
        elif has_preup50: preup_primary = "P50"
        else:             preup_primary = None

        # PREDN raw signals
        raw_d66 = dd200 and (dd9 or dd20 or dd34 or dd50 or dd89)
        raw_d55 = dd89  and (dd9 or dd20 or dd34 or dd50 or dd200)
        raw_d3  = dd9 and dd20 and dd50
        raw_d2  = dd9 and dd20
        raw_d50 = dd50

        has_predn66 = raw_d66
        has_predn55 = raw_d55 and not raw_d66
        has_predn89 = dd89 and not raw_d55 and not raw_d66
        has_predn3  = raw_d3  and not raw_d55 and not raw_d66 and not dd89
        has_predn2  = raw_d2  and not raw_d3  and not raw_d55 and not raw_d66 and not dd89
        has_predn50 = raw_d50 and not raw_d2  and not raw_d3  and not raw_d55 and not raw_d66 and not dd89

        if has_predn66:   predn_primary = "P66"
        elif has_predn55: predn_primary = "P55"
        elif has_predn89: predn_primary = "P89"
        elif has_predn3:  predn_primary = "P3"
        elif has_predn2:  predn_primary = "P2"
        elif has_predn50: predn_primary = "P50"
        else:             predn_primary = None

        # ── WLNBB L1-L6 raw signals (volDownAdapted path) ────────────────────
        vda = vol_down_adapted[i]
        vua = vol_up_adapted_l[i]
        prev_c  = closes[i-1] if i > 0 else None
        prev_h2 = highs[i-1]  if i > 0 else None
        prev_l2 = lows[i-1]   if i > 0 else None

        up_close          = (c > prev_c)         if prev_c  is not None else False
        down_close        = (c < prev_c)          if prev_c  is not None else False
        no_new_low_close  = (c >= prev_l2)        if prev_l2 is not None else False
        no_new_high_close = (c <= prev_h2)        if prev_h2 is not None else False

        has_l1 = vda and up_close
        has_l2 = vda and no_new_low_close
        has_l3 = vua and up_close
        has_l4 = vua and no_new_high_close
        has_l5 = vda and down_close
        has_l6 = vua and down_close

        # ── ABR quality score ─────────────────────────────────────────────────
        sig_score = _signal_score(tz_signal) if tz_signal else 0

        # L score
        # Use WLNBB l34/l43/l64 from existing engine (already populated)
        has_l34_w = bool(wl.get("l34_wlnbb"))
        has_l43_w = bool(wl.get("l43_wlnbb"))
        has_l64_w = bool(wl.get("l64_wlnbb"))
        if has_l5:
            l_score = 2
        elif has_l34_w or has_l43_w:
            l_score = 1
        elif has_l64_w:
            l_score = 1
        else:
            l_score = 0

        # Suffix score — keyed on core (ne+wick+pen), close_suf is display-only
        suf = core_suf
        if suf in ("EB", "NB"):
            suf_score = 2
        elif suf in ("EU", "NU", "EDP", "NDP"):
            suf_score = 1
        elif suf in ("NH", "EH"):
            suf_score = -2
        elif suf in ("NUR", "EUR"):
            suf_score = -1
        else:
            suf_score = 0

        quality_score = sig_score + l_score + suf_score
        tier_sp500    = _sp500_tier(quality_score) if tz_signal else None
        tier_nasdaq   = _nasdaq_tier(quality_score) if tz_signal else None

        pass1.append({
            # Internal helpers
            "_z7_raw_abr":      tz.get("_z7_raw", False),
            "_tz_signal":       tz_signal,
            "_tier_sp500":      tier_sp500,
            "_tier_nasdaq":     tier_nasdaq,
            "_quality_score":   quality_score,
            # Suffix
            "tz_ne_suffix":     ne_suf,
            "tz_wick_suffix":   wick_suf,
            "tz_pen_suffix":    pen_suf,
            "tz_close_suffix":  close_suf,
            "tz_append_close":  append_close,
            "tz_core_suffix":   core_suf,
            "tz_full_suffix":   full_suf,
            # T/Z signal flags
            "tz_primary_signal": tz_signal,
            "tz_side":           tz_side,
            "has_t4":  tz.get("T4",  False),
            "has_t6":  tz.get("T6",  False),
            "has_t1g": tz.get("T1G", False),
            "has_t2g": tz.get("T2G", False),
            "has_t1":  tz.get("T1",  False),
            "has_t2":  tz.get("T2",  False),
            "has_t9":  tz.get("T9",  False),
            "has_t10": tz.get("T10", False),
            "has_t3":  tz.get("T3",  False),
            "has_t11": tz.get("T11", False),
            "has_t5":  tz.get("T5",  False),
            "has_t12": tz.get("T12", False),
            "has_z4":  tz.get("Z4",  False),
            "has_z6":  tz.get("Z6",  False),
            "has_z1g": tz.get("Z1G", False),
            "has_z2g": tz.get("Z2G", False),
            "has_z1":  tz.get("Z1",  False),
            "has_z2":  tz.get("Z2",  False),
            "has_z9":  tz.get("Z9",  False),
            "has_z10": tz.get("Z10", False),
            "has_z3":  tz.get("Z3",  False),
            "has_z11": tz.get("Z11", False),
            "has_z5":  tz.get("Z5",  False),
            "has_z12": tz.get("Z12", False),
            "has_z8":  has_z8,
            "has_z7":  (effective_bear_code == 14),
            # PREUP / PREDN
            "has_preup66": has_preup66,
            "has_preup55": has_preup55,
            "has_preup89": has_preup89,
            "has_preup3":  has_preup3,
            "has_preup2":  has_preup2,
            "has_preup50": has_preup50,
            "preup_primary": preup_primary,
            "has_predn66": has_predn66,
            "has_predn55": has_predn55,
            "has_predn89": has_predn89,
            "has_predn3":  has_predn3,
            "has_predn2":  has_predn2,
            "has_predn50": has_predn50,
            "predn_primary": predn_primary,
            # WLNBB extended (L1-L6 raw signals)
            "has_l1": has_l1,
            "has_l2": has_l2,
            "has_l3": has_l3,
            "has_l4": has_l4,
            "has_l5": has_l5,
            "has_l6": has_l6,
            # Quality score components
            "tz_signal_score":  sig_score,
            "tz_l_score":       l_score,
            "tz_suffix_score":  suf_score,
            "tz_quality_score": quality_score,
            "tz_quality_tier_sp500":  tier_sp500,
            "tz_quality_tier_nasdaq": tier_nasdaq,
        })

    # ── Second pass: prev1/prev2 fields + ABR classification ─────────────────
    result: list[dict] = []

    for i, row in enumerate(pass1):
        r = dict(row)

        prev1 = pass1[i-1] if i >= 1 else None
        prev2 = pass1[i-2] if i >= 2 else None

        r["tz_prev1_signal"]           = prev1["_tz_signal"]       if prev1 else None
        r["tz_prev1_quality_score"]    = prev1["_quality_score"]    if prev1 else None
        r["tz_prev1_quality_tier_sp500"]  = prev1["_tier_sp500"]   if prev1 else None
        r["tz_prev1_quality_tier_nasdaq"] = prev1["_tier_nasdaq"]  if prev1 else None

        r["tz_prev2_signal"]           = prev2["_tz_signal"]       if prev2 else None
        r["tz_prev2_quality_score"]    = prev2["_quality_score"]    if prev2 else None
        r["tz_prev2_quality_tier_sp500"]  = prev2["_tier_sp500"]   if prev2 else None
        r["tz_prev2_quality_tier_nasdaq"] = prev2["_tier_nasdaq"]  if prev2 else None

        # ABR classification — only when current bar has a T/Z signal
        tz_signal = row["tz_primary_signal"]
        if tz_signal is None:
            r["abr_sp500"]           = None
            r["abr_nasdaq"]          = None
            r["abr_is_a_sp500"]      = False
            r["abr_is_b_sp500"]      = False
            r["abr_is_bplus_sp500"]  = False
            r["abr_is_r_sp500"]      = False
            r["abr_is_a_nasdaq"]     = False
            r["abr_is_b_nasdaq"]     = False
            r["abr_is_bplus_nasdaq"] = False
            r["abr_is_r_nasdaq"]     = False
        else:
            p1_tier_sp   = prev1["_tier_sp500"]  if prev1 else None
            p1_tier_nas  = prev1["_tier_nasdaq"]  if prev1 else None
            p2_tier_sp   = prev2["_tier_sp500"]   if prev2 else None
            p2_tier_nas  = prev2["_tier_nasdaq"]   if prev2 else None

            gate_sp500  = (p1_tier_sp  == "STRONG")
            gate_nasdaq = (p1_tier_nas == "STRONG" or p1_tier_nas == "GOOD")

            abr_sp  = _abr(gate_sp500,  p2_tier_sp  or "")
            abr_nas = _abr(gate_nasdaq, p2_tier_nas or "")

            r["abr_sp500"]           = abr_sp
            r["abr_nasdaq"]          = abr_nas
            r["abr_is_a_sp500"]      = abr_sp  == "A"
            r["abr_is_b_sp500"]      = abr_sp  == "B"
            r["abr_is_bplus_sp500"]  = abr_sp  == "B+"
            r["abr_is_r_sp500"]      = abr_sp  == "R"
            r["abr_is_a_nasdaq"]     = abr_nas == "A"
            r["abr_is_b_nasdaq"]     = abr_nas == "B"
            r["abr_is_bplus_nasdaq"] = abr_nas == "B+"
            r["abr_is_r_nasdaq"]     = abr_nas == "R"

        # Remove internal helper fields
        r.pop("_z7_raw_abr",   None)
        r.pop("_tz_signal",    None)
        r.pop("_tier_sp500",   None)
        r.pop("_tier_nasdaq",  None)
        r.pop("_quality_score", None)

        result.append(r)

    return result


def _feature_json_fields() -> list[str]:
    """Return the list of field names written into feature_json by this engine."""
    return [
        "tz_ne_suffix", "tz_wick_suffix", "tz_pen_suffix",
        "tz_close_suffix", "tz_append_close",
        "tz_core_suffix", "tz_full_suffix",
        "tz_primary_signal", "tz_side",
        "has_t4", "has_t6", "has_t1g", "has_t2g", "has_t1", "has_t2",
        "has_t9", "has_t10", "has_t3", "has_t11", "has_t5", "has_t12",
        "has_z4", "has_z6", "has_z1g", "has_z2g", "has_z1", "has_z2",
        "has_z9", "has_z10", "has_z3", "has_z11", "has_z5", "has_z12",
        "has_z8", "has_z7",
        "has_preup66", "has_preup55", "has_preup89", "has_preup3", "has_preup2", "has_preup50",
        "preup_primary",
        "has_predn66", "has_predn55", "has_predn89", "has_predn3", "has_predn2", "has_predn50",
        "predn_primary",
        "has_l1", "has_l2", "has_l3", "has_l4", "has_l5", "has_l6",
        "tz_signal_score", "tz_l_score", "tz_suffix_score", "tz_quality_score",
        "tz_quality_tier_sp500", "tz_quality_tier_nasdaq",
        "tz_prev1_signal", "tz_prev1_quality_score",
        "tz_prev1_quality_tier_sp500", "tz_prev1_quality_tier_nasdaq",
        "tz_prev2_signal", "tz_prev2_quality_score",
        "tz_prev2_quality_tier_sp500", "tz_prev2_quality_tier_nasdaq",
        "abr_sp500", "abr_nasdaq",
        "abr_is_a_sp500", "abr_is_b_sp500", "abr_is_bplus_sp500", "abr_is_r_sp500",
        "abr_is_a_nasdaq", "abr_is_b_nasdaq", "abr_is_bplus_nasdaq", "abr_is_r_nasdaq",
    ]
