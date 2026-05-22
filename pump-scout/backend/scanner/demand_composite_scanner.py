"""
Demand Composite Scanner — pump-scout signal fusion layer.

Combines all research signals from R154–R157 into a single composite score
with a custom ACCUMULATION_TRAP_SIGNAL (ATS) and tiered BUY recommendations.

Signal stack:
  Tier 1 — Regime quality         (price, ATR, dollar-volume buckets)
  Tier 2 — NP engine / v2 base    (existing scanner decision)
  Tier 3 — Demand bar signals      (has_l34_np_ld, has_wc_gap_ld, D-confluence)
  Tier 4 — ATS composite signal    (custom — see below)
  Tier 5 — Context modifiers       (sector, macro, sympathy, hype)
  Tier 6 — CFR_A flow signals      (OBV accumulation, lower-wick absorption)

ACCUMULATION_TRAP_SIGNAL (ATS):
  Fires when ALL 5 conditions hold on the current bar:
    1. vol_dryup_3d   — last 3 bars all < 55% of 20d avg (silence)
    2. atr_contracting — 5d ATR < 70% of 20d ATR (coiling)
    3. demand_bar     — L34/NP or lower-wick reclaim in last 5 days
    4. near_ema50     — price within −5% / +8% of EMA50 (support)
    5. not_pumped     — max gain last 10 days < 35% (not already up)
  Bonus: tight_range — 5d price range < 1.5× daily ATR

  ATS_PRIME = 5/5 | ATS_SETUP = 4/5 | ATS_WATCH = 3/5

Output tiers (demand_composite_tier):
  PRIME_BUY      score >= 13
  HIGH_CONF_BUY  score 9–12
  BUY_WATCH      score 6–8
  SETUP_MONITOR  score 3–5
  SKIP           score < 3 or hard-gate triggered
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Tier thresholds ──────────────────────────────────────────────────────────
_TIER_PRIME   = 13.0
_TIER_HIGH    = 9.0
_TIER_WATCH   = 6.0
_TIER_MONITOR = 3.0

TIER_ORDER = {
    "PRIME_BUY": 0, "HIGH_CONF_BUY": 1, "BUY_WATCH": 2,
    "SETUP_MONITOR": 3, "SKIP": 4,
}

TIER_LABELS = {
    "PRIME_BUY":      "PRIME — highest confluence, all systems go",
    "HIGH_CONF_BUY":  "HIGH CONF — strong signal stack, low FP risk",
    "BUY_WATCH":      "BUY WATCH — setup forming, wait for trigger",
    "SETUP_MONITOR":  "MONITOR — early setup, incomplete signal",
    "SKIP":           "SKIP — insufficient confluence or toxic regime",
}

# ── Regime bucket helpers (mirror cfr_selector thresholds) ───────────────────

def _price_bucket(price: float) -> str:
    if price < 0.25:  return "PRICE_MICRO_LT_050"
    if price < 1.0:   return "PRICE_SUB_1"
    if price < 3.0:   return "PRICE_1_TO_3"
    if price < 10.0:  return "PRICE_3_TO_10"
    if price < 25.0:  return "PRICE_10_TO_25"
    return "PRICE_GT_25"


def _atr_bucket(atr_pct: float) -> str:
    if atr_pct < 5.0:   return "ATR_QUIET_LT_5"
    if atr_pct < 15.0:  return "ATR_NORMAL_5_15"
    if atr_pct < 40.0:  return "ATR_ELEVATED_15_40"
    return "ATR_EXTREME_GT_40"


def _dv_bucket(dv: float) -> str:
    if dv < 50_000:      return "DV_ILLIQUID_LT_50K"
    if dv < 250_000:     return "DV_THIN_50K_250K"
    if dv < 1_000_000:   return "DV_OK_250K_1M"
    if dv < 10_000_000:  return "DV_LIQUID_1M_10M"
    return "DV_HIGH_GT_10M"


# ── EMA ──────────────────────────────────────────────────────────────────────

def _ema(values: list[float], period: int) -> list[float]:
    if len(values) < period:
        return []
    k = 2.0 / (period + 1)
    result = [sum(values[:period]) / period]
    for v in values[period:]:
        result.append(v * k + result[-1] * (1 - k))
    return result


# ── Candle metrics ────────────────────────────────────────────────────────────

def _compute_candle_metrics(candles: list[dict], avg_vol_20d: float) -> dict:
    """
    Derive all candle-level metrics for scoring and ATS.
    Operates on the last 20 bars for local context.
    """
    if len(candles) < 10:
        return {}

    bars   = candles[-20:]
    last   = bars[-1]
    price  = last.get("close") or last.get("c") or 0.0

    # ── True range / ATR ──────────────────────────────────────────────────────
    src = candles[-16:]
    trs: list[float] = []
    for i in range(1, len(src)):
        c, p = src[i], src[i - 1]
        trs.append(max(
            (c.get("high") or c.get("h") or 0) - (c.get("low") or c.get("l") or 0),
            abs((c.get("high") or c.get("h") or 0) - (p.get("close") or p.get("c") or 0)),
            abs((c.get("low")  or c.get("l") or 0) - (p.get("close") or p.get("c") or 0)),
        ))

    atr14 = (sum(trs[-14:]) / min(14, len(trs))) if trs else 0.0
    atr_pct = (atr14 / price * 100) if price > 0 else 0.0

    # ATR contraction: 5d vs 20d
    trs_all = []
    for i in range(1, len(candles)):
        c, p = candles[i], candles[i - 1]
        trs_all.append(max(
            (c.get("high") or c.get("h") or 0) - (c.get("low") or c.get("l") or 0),
            abs((c.get("high") or c.get("h") or 0) - (p.get("close") or p.get("c") or 0)),
            abs((c.get("low")  or c.get("l") or 0) - (p.get("close") or p.get("c") or 0)),
        ))
    atr5  = (sum(trs_all[-5:])  / 5)  if len(trs_all) >= 5  else atr14
    atr20 = (sum(trs_all[-20:]) / 20) if len(trs_all) >= 20 else atr14
    atr_contracting = bool(atr5 < atr20 * 0.70) if atr20 > 0 else False

    # ── Volume dryup streak ───────────────────────────────────────────────────
    vol_threshold = avg_vol_20d * 0.55 if avg_vol_20d > 0 else float("inf")
    vols = [b.get("volume") or b.get("v") or 0 for b in bars]
    dryup_streak = 0
    for v in reversed(vols):
        if v < vol_threshold:
            dryup_streak += 1
        else:
            break

    # ── EMA 50 alignment ──────────────────────────────────────────────────────
    close_series = [b.get("close") or b.get("c") or 0 for b in candles]
    ema50_series = _ema(close_series, 50)
    ema50 = ema50_series[-1] if ema50_series else None
    ema_dist_pct = ((price - ema50) / ema50 * 100) if ema50 and ema50 > 0 else None
    near_ema50 = bool(-5.0 <= ema_dist_pct <= 8.0) if ema_dist_pct is not None else False

    # ── No prior pump: max gain last 10 bars ─────────────────────────────────
    closes10 = [b.get("close") or b.get("c") or 0 for b in bars[-10:]]
    if len(closes10) >= 2 and closes10[0] > 0:
        max_gain_10d = (max(closes10) - closes10[0]) / closes10[0] * 100
    else:
        max_gain_10d = 0.0
    not_pumped = bool(max_gain_10d < 35.0)

    # ── Tight range: 5d high−low vs ATR ──────────────────────────────────────
    h5 = max((b.get("high") or b.get("h") or 0) for b in bars[-5:])
    l5 = min((b.get("low")  or b.get("l") or 0) for b in bars[-5:])
    range_pct_5d = ((h5 - l5) / price * 100) if price > 0 else 999.0
    tight_range = bool(range_pct_5d < atr_pct * 1.5) if atr_pct > 0 else False

    # ── Current bar demand close ──────────────────────────────────────────────
    cb = last
    cb_h   = cb.get("high")  or cb.get("h") or 0
    cb_l   = cb.get("low")   or cb.get("l") or 0
    cb_o   = cb.get("open")  or cb.get("o") or 0
    cb_c   = cb.get("close") or cb.get("c") or 0
    cb_r   = max(cb_h - cb_l, 1e-6)
    cb_pos = (cb_c - cb_l) / cb_r
    cb_lwk = (min(cb_o, cb_c) - cb_l) / cb_r
    has_demand_close = bool(cb_pos >= 0.50 and cb_lwk >= 0.20)

    vol_today  = last.get("volume") or last.get("v") or 0
    vol_ratio  = (vol_today / avg_vol_20d) if avg_vol_20d > 0 else 1.0
    dollar_vol = price * vol_today

    # ── Largest gap (open vs prev close) in last 5 bars ──────────────────────
    gap_pcts: list[float] = []
    for i in range(max(1, len(candles) - 5), len(candles)):
        o  = candles[i].get("open")  or candles[i].get("o")  or 0.0
        pc = candles[i-1].get("close") or candles[i-1].get("c") or 0.0
        if pc > 0 and o > 0:
            gap_pcts.append((o - pc) / pc * 100.0)
    max_gap_pct_5d = max(gap_pcts) if gap_pcts else 0.0

    # ── Max volume ratio in last 5 bars ──────────────────────────────────────
    vol_ratios_5d = [
        (b.get("volume") or b.get("v") or 0) / avg_vol_20d
        for b in bars[-5:]
        if avg_vol_20d > 0
    ]
    max_vol_ratio_5d = max(vol_ratios_5d) if vol_ratios_5d else vol_ratio

    return {
        "price":             price,
        "atr14":             atr14,
        "atr_pct":           atr_pct,
        "atr_contracting":   atr_contracting,
        "dryup_streak":      dryup_streak,
        "ema50":             ema50,
        "ema_dist_pct":      ema_dist_pct,
        "near_ema50":        near_ema50,
        "not_pumped":        not_pumped,
        "max_gain_10d":      max_gain_10d,
        "tight_range":       tight_range,
        "range_pct_5d":      range_pct_5d,
        "has_demand_close":  has_demand_close,
        "vol_ratio":         vol_ratio,
        "dollar_vol":        dollar_vol,
        "max_gap_pct_5d":    max_gap_pct_5d,
        "max_vol_ratio_5d":  max_vol_ratio_5d,
        "price_bucket":      _price_bucket(price),
        "atr_bucket":        _atr_bucket(atr_pct),
        "dv_bucket":         _dv_bucket(dollar_vol),
    }


# ── Readiness — 5-gap trigger layer ──────────────────────────────────────────

def _compute_readiness(
    m: dict,
    result: dict,
    candles: Optional[list[dict]] = None,
    bar_labels: Optional[list[dict]] = None,
) -> dict:
    """
    5-gap readiness layer — answers "is this ready to MOVE, not just to set up?"

    Gap 1 — Catalyst proxy   : was there a volume spike before the dryup? (0-2)
    Gap 2 — Breakout signal  : is volume returning / price at highs?      (0-3)
    Gap 3 — Float quality    : low float = explosive potential             (0-2)
    Gap 4 — Signal freshness : dryup too long = setup gone stale          (-2 to +2)
    Gap 5 — RS in compression: did price hold up during the dryup?        (-1 to +2)

    readiness_score: 0-10    readiness_tier: HOT|WARM|COOL|COLD
    """
    avg_vol = result.get("avg_volume_20d") or 0

    # Prefer live candle metrics; fall back to cached dc_* fields from result
    dryup     = m.get("dryup_streak")
    if dryup is None:
        dryup = result.get("dc_dryup_streak", 0)

    vol_ratio = m.get("vol_ratio")
    if vol_ratio is None:
        vol_ratio = result.get("dc_vol_ratio", 1.0)

    price = m.get("price") or result.get("price") or 1.0

    # ── Gap 1: Catalyst proxy ─────────────────────────────────────────────────
    # Did volume spike 1.5-2.5× before the dryup started?  If yes, smart money
    # bought on an event, then went quiet — classic accumulation after catalyst.
    cat_score = 0
    catalyst_proxy = False
    if dryup >= 2 and candles and len(candles) >= dryup + 5 and avg_vol > 0:
        pre_start  = max(0, len(candles) - dryup - 8)
        pre_end    = max(0, len(candles) - dryup)
        pre_bars   = candles[pre_start:pre_end]
        if pre_bars:
            max_pre = max((b.get("volume") or b.get("v") or 0) for b in pre_bars)
            if max_pre >= avg_vol * 2.5:
                cat_score = 2; catalyst_proxy = True
            elif max_pre >= avg_vol * 1.5:
                cat_score = 1; catalyst_proxy = True

    # ── Gap 2: Breakout signal ────────────────────────────────────────────────
    # Is volume returning AND price at the 5-day high?  The dryup ending with
    # price expansion = accumulation converting to markup phase.
    brk_score = 0
    breakout_signal = "COILING"
    if vol_ratio >= 2.0:
        h5 = price
        if candles and len(candles) >= 5:
            h5 = max((b.get("high") or b.get("h") or 0) for b in candles[-5:])
        if price >= h5 * 0.97:
            breakout_signal = "BREAKING";  brk_score = 3
        else:
            breakout_signal = "SURGING";   brk_score = 2
    elif vol_ratio >= 1.5:
        breakout_signal = "AWAKENING";     brk_score = 1
    elif vol_ratio >= 1.2:
        breakout_signal = "TICKING"
        # volume stirring but not yet scoring — watch list flag only

    # ── Gap 3: Float quality ──────────────────────────────────────────────────
    # Low float = small supply = explosive moves on demand.
    # Use shares_float if available; fall back to avg-dollar-volume proxy.
    flt_score = 0
    float_proxy_tier = "UNKNOWN"
    shares_float = result.get("shares_float")
    if shares_float and shares_float > 0:
        if shares_float < 5_000_000:
            flt_score = 2; float_proxy_tier = "MICRO"
        elif shares_float < 15_000_000:
            flt_score = 2; float_proxy_tier = "LOW"
        elif shares_float < 50_000_000:
            flt_score = 1; float_proxy_tier = "NORMAL"
        elif shares_float < 200_000_000:
            flt_score = 0; float_proxy_tier = "LARGE"
        else:
            flt_score = -1; float_proxy_tier = "HEAVY"
    else:
        # Proxy: low-price + low avg dollar-volume = likely low float
        avg_dv   = price * avg_vol if avg_vol > 0 else 0
        p_bucket = m.get("price_bucket") or result.get("dc_price_bucket", "")
        if p_bucket in ("PRICE_1_TO_3", "PRICE_SUB_1") and avg_dv < 2_000_000:
            flt_score = 2; float_proxy_tier = "LOW_PROXY"
        elif avg_dv < 5_000_000:
            flt_score = 1; float_proxy_tier = "SMALL_PROXY"
        elif avg_dv > 50_000_000:
            flt_score = -1; float_proxy_tier = "LARGE_PROXY"
        else:
            float_proxy_tier = "MEDIUM_PROXY"

    # ── Gap 4: Signal freshness ───────────────────────────────────────────────
    # Dryups that drag on for 10+ bars usually mean no one cares — penalise.
    frsh_score = 0
    freshness_label = "NO_DRYUP"
    if dryup >= 1:
        if dryup <= 3:
            frsh_score = 2;  freshness_label = "FRESH"
        elif dryup <= 5:
            frsh_score = 1;  freshness_label = "NORMAL"
        elif dryup <= 8:
            frsh_score = 0;  freshness_label = "AGING"
        elif dryup <= 12:
            frsh_score = -1; freshness_label = "STALE"
        else:
            frsh_score = -2; freshness_label = "DEAD"

    # ── Gap 5: Relative strength during compression ───────────────────────────
    # Did the stock HOLD UP during the dryup?  Rising / flat price while volume
    # dries up = hidden demand.  Drifting lower = weak hands, no sponsorship.
    rs_score = 0
    rs_during_dryup_pct = None
    if dryup >= 2 and candles and len(candles) >= dryup + 2:
        ref = candles[-(dryup + 1)]
        ref_close = ref.get("close") or ref.get("c") or 0
        if ref_close > 0 and price > 0:
            rs_during_dryup_pct = round((price / ref_close - 1) * 100, 1)
            if rs_during_dryup_pct > 3.0:
                rs_score = 2
            elif rs_during_dryup_pct > 0.5:
                rs_score = 1
            elif rs_during_dryup_pct < -3.0:
                rs_score = -1

    # ── Gap 6: Signal confluence (TZ / WLNBB / PREUP) ────────────────────────
    # PREUP = EMA stack aligning bullish during compression (timing signal).
    # T1/T2 bar = strong demand candle on low volume = accumulation in action.
    # L-bucket = still inside Bollinger squeeze = coiled energy.
    conf_score = 0
    confluence_signals: list[str] = []
    _labels = bar_labels  # use pre-computed labels if caller already fetched them
    if _labels is None and candles and len(candles) >= 5:
        try:
            from scanner.manual_d_wlnbb_features import compute_combined_bar_labels
            _labels = compute_combined_bar_labels(candles, last_n=5)
        except Exception:
            _labels = []
    if _labels:
        last  = _labels[-1]
        prev  = _labels[-2] if len(_labels) >= 2 else {}
        prev2 = _labels[-3] if len(_labels) >= 3 else {}
        # PREUP: EMA stack aligning bullish — differentiate by token (R42 data).
        # P55=+2.17 alpha, P2/P3/P50=neutral, P89=-0.73 alpha (already overbought).
        _preup_now = last.get("preup") or ""
        _preup_rec = prev.get("preup") or prev2.get("preup") or ""
        if _preup_now == "P55":
            conf_score += 2; confluence_signals.append("PREUP_P55")
        elif _preup_now == "P89":
            conf_score -= 1; confluence_signals.append("PREUP_P89_LATE")
        elif _preup_now:
            conf_score += 1; confluence_signals.append("PREUP_NOW")
        elif _preup_rec:
            conf_score += 1; confluence_signals.append("PREUP_RECENT")
        # T1/T2 demand bar in last 3 bars
        if any(lb.get("t_signal") in ("T1", "T2") for lb in (last, prev, prev2)):
            conf_score += 1; confluence_signals.append("T1T2_BAR")
        # T10/T11 bearish distribution bars: T10=-1.97 alpha, T11=-1.41 alpha (R42).
        _t_last = last.get("t_signal") or ""
        if _t_last in ("T10", "T11"):
            conf_score -= 2; confluence_signals.append(f"BEARISH_TZ_{_t_last}")
        elif any(lb.get("t_signal") in ("T10", "T11") for lb in (prev, prev2)):
            conf_score -= 1; confluence_signals.append("BEARISH_TZ_RECENT")
        # Still in Bollinger squeeze (L bucket)
        if last.get("bucket") == "L":
            conf_score += 1; confluence_signals.append("WLNBB_L")
        # VX-PS-R2X: RSI2 overbought at breakout has 3.27x lift in 4x+ pumps (R92).
        # VX alone appears in 92% of all episodes -- not discriminating by itself.
        # VX-PS-R2L has 0.50x lift (negative) -- dropping it.
        _vx  = last.get("vix_token")  == "VX"
        _ps  = last.get("psar_token") in ("PS", "PB")
        _r2x = last.get("rsi2_token") == "R2X"
        _r2l = last.get("rsi2_token") == "R2L"
        if _vx and _ps and _r2x:
            conf_score += 2; confluence_signals.append("VX_PS_R2X_BREAKOUT")
        # PS-R2L (no VX required): +1.03 alpha, n=174 in R42 scanner replay.
        elif _ps and _r2l and not _vx:
            conf_score += 1; confluence_signals.append("PS_R2L_SETUP")

        # Gap ≥ 100% in last 5 bars: 6.18x lift (47% of 4x+ vs 8% of 2-4x, R92).
        # Gap ≥ 50%: 2.97x lift (65% of 4x+ vs 22% of 2-4x, R92).
        _max_gap = m.get("max_gap_pct_5d", 0.0)
        if _max_gap >= 100.0:
            conf_score += 3; confluence_signals.append("GAP_GTE_100PCT")
        elif _max_gap >= 50.0:
            conf_score += 1; confluence_signals.append("GAP_GTE_50PCT")

        # Volume anomaly ≥ 100x: 2.42x lift (70% of 4x+ vs 29% of 2-4x, R92).
        # ≥ 500x: 2.95x lift (37% of 4x+ vs 13% of 2-4x, R92).
        _max_va = m.get("max_vol_ratio_5d", 0.0)
        if _max_va >= 500.0:
            conf_score += 2; confluence_signals.append("VOL_ANOMALY_500X")
        elif _max_va >= 100.0:
            conf_score += 1; confluence_signals.append("VOL_ANOMALY_100X")

    # ── Combine ───────────────────────────────────────────────────────────────
    total = cat_score + brk_score + flt_score + frsh_score + rs_score + conf_score
    readiness_score = max(0, min(10, total))

    if readiness_score >= 7:
        readiness_tier = "HOT"
    elif readiness_score >= 4:
        readiness_tier = "WARM"
    elif readiness_score >= 2:
        readiness_tier = "COOL"
    else:
        readiness_tier = "COLD"

    return {
        "readiness_score":     readiness_score,
        "readiness_tier":      readiness_tier,
        "readiness_breakdown": {
            "catalyst":    cat_score,
            "breakout":    brk_score,
            "float":       flt_score,
            "freshness":   frsh_score,
            "rs":          rs_score,
            "confluence":  conf_score,
        },
        "confluence_signals":  confluence_signals,
        "breakout_signal":     breakout_signal,
        "catalyst_proxy":      catalyst_proxy,
        "float_proxy_tier":    float_proxy_tier,
        "freshness_label":     freshness_label,
        "rs_during_dryup_pct": rs_during_dryup_pct,
    }


# ── ATS — Accumulation Trap Signal ───────────────────────────────────────────

def _compute_ats(m: dict, r: dict) -> tuple[str, list[str], list[str]]:
    """
    Compute ACCUMULATION_TRAP_SIGNAL from candle metrics (m) + scanner result (r).

    Returns (ats_signal, conditions_met, conditions_missing).
    """
    conds = {
        "vol_dryup_3d":    m.get("dryup_streak", 0) >= 3,
        "atr_contracting": m.get("atr_contracting", False),
        "demand_bar":      (
            bool(r.get("has_l34_np_ld"))
            or bool(r.get("l34_wlnbb"))
            or bool(r.get("has_wc_gap_ld"))
            or bool(r.get("core_d_l34"))
            or bool(r.get("d4_l34"))
            or m.get("has_demand_close", False)
        ),
        "near_ema50":      m.get("near_ema50", False),
        "not_pumped":      m.get("not_pumped", True),
    }

    met     = [k for k, v in conds.items() if v]
    missing = [k for k, v in conds.items() if not v]

    if m.get("tight_range"):
        met.append("tight_range_bonus")

    n_core = sum(1 for v in conds.values() if v)

    if n_core >= 5:
        signal = "ATS_PRIME"
    elif n_core >= 4:
        signal = "ATS_SETUP"
    elif n_core >= 3:
        signal = "ATS_WATCH"
    else:
        signal = "ATS_NONE"

    return signal, met, missing


# ── CFR_A flow divergence signals (Run #157) ─────────────────────────────────

def _compute_flow_signals(
    candles: list[dict],
    avg_vol_20d: float = 0,
) -> dict:
    """
    Flow divergence signals from CFR_A research (Run #157).

    Boosts:
      OBV_ACCUM          OBV net accumulation > 15% of 5d avg vol (+1.5)
      LOWER_WICK_ABSORB  avg lower-wick ≥ 30% of bar range, last 3 bars (+1.0)
      LOWER_WICK_PARTIAL avg lower-wick ≥ 20%                              (+0.5)

    Penalties (contra-signals — more common in false positives per R157):
      OBV_DISTRIB        OBV net distribution > 15% of 5d avg vol         (-0.5)
      EMA_SPREAD_WIDE    EMA9 > 12% above EMA50 — price already extended  (-1.0)
      EMA_SPREAD_ELEVATED EMA9 > 8% above EMA50                           (-0.5)

    Returns flow_score (-1.5 to +2.5), flow_signals, flow_risks.
    """
    if not candles or len(candles) < 10:
        return {"flow_score": 0.0, "flow_signals": [], "flow_risks": []}

    flow_score   = 0.0
    flow_signals: list[str] = []
    flow_risks:   list[str] = []

    # ── OBV 5-bar accumulation trend ─────────────────────────────────────────
    # Rising OBV during price compression = smart-money footprint (R157 #1 signal)
    src    = candles[-11:]
    closes = [b.get("close") or b.get("c") or 0.0 for b in src]
    vols   = [b.get("volume") or b.get("v") or 0    for b in src]

    obv  = 0.0
    obvs = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv += vols[i]
        elif closes[i] < closes[i - 1]:
            obv -= vols[i]
        obvs.append(obv)

    if len(obvs) >= 6 and avg_vol_20d > 0:
        obv_5d_net = obvs[-1] - obvs[-6]
        obv_pct    = obv_5d_net / (avg_vol_20d * 5)
        if obv_pct > 0.15:
            flow_score += 1.5; flow_signals.append("OBV_ACCUM")
        elif obv_pct < -0.15:
            flow_score -= 0.5; flow_risks.append("OBV_DISTRIB")

    # ── Lower-wick absorption (buy pressure at lows) ──────────────────────────
    # Buyers stepping in at the lows = absorption = accumulation footprint
    recent  = candles[-3:]
    lw_pcts = []
    for b in recent:
        h   = b.get("high")  or b.get("h") or 0
        l   = b.get("low")   or b.get("l") or 0
        o   = b.get("open")  or b.get("o") or 0
        c   = b.get("close") or b.get("c") or 0
        rng = max(h - l, 1e-9)
        lw_pcts.append((min(o, c) - l) / rng)

    avg_lw = sum(lw_pcts) / len(lw_pcts) if lw_pcts else 0.0
    if avg_lw >= 0.30:
        flow_score += 1.0; flow_signals.append("LOWER_WICK_ABSORB")
    elif avg_lw >= 0.20:
        flow_score += 0.5; flow_signals.append("LOWER_WICK_PARTIAL")

    # ── EMA spread penalty (contra-signal: wide spread = extended = FP risk) ─
    # avg_ema_spread_pre 0.68× lift in R157 FP — price already trending = late
    if len(candles) >= 20:
        all_c   = [b.get("close") or b.get("c") or 0.0 for b in candles]
        ema9_s  = _ema(all_c, 9)
        ema50_s = _ema(all_c, 50)
        if ema9_s and ema50_s:
            e9, e50 = ema9_s[-1], ema50_s[-1]
            if e50 > 0:
                spread = (e9 - e50) / e50 * 100
                if spread > 12.0:
                    flow_score -= 1.0; flow_risks.append("EMA_SPREAD_WIDE")
                elif spread > 8.0:
                    flow_score -= 0.5; flow_risks.append("EMA_SPREAD_ELEVATED")

    return {
        "flow_score":   round(max(-1.5, min(2.5, flow_score)), 2),
        "flow_signals": flow_signals,
        "flow_risks":   flow_risks,
    }


# ── Main composite scorer ────────────────────────────────────────────────────

def score_demand_composite(
    result: dict,
    candles: Optional[list[dict]] = None,
) -> dict:
    """
    Compute demand_composite_score (0–20) and all derived fields.

    Parameters
    ----------
    result  : scanner result dict (from new_pump_runner, with _dw spread)
    candles : OHLCV bars for candle-level metric computation
    """
    score     = 0.0
    reasons:   list[str] = []
    risks:     list[str] = []
    breakdown: dict[str, float] = {}

    price   = result.get("price") or 0.0
    avg_vol = result.get("avg_volume_20d") or 0

    # ── Bar labels — computed once, shared by readiness Gap 6 + flow section ──
    bar_labels: list[dict] = []
    if candles and len(candles) >= 5:
        try:
            from scanner.manual_d_wlnbb_features import compute_combined_bar_labels
            bar_labels = compute_combined_bar_labels(candles, last_n=5) or []
        except Exception:
            pass

    # ── Candle metrics ────────────────────────────────────────────────────────
    m: dict = {}
    if candles and len(candles) >= 10:
        try:
            m = _compute_candle_metrics(candles, avg_vol)
        except Exception as exc:
            logger.debug(f"demand_composite candle metrics failed: {exc}")

    p_bucket = m.get("price_bucket") or _price_bucket(price)
    a_bucket = m.get("atr_bucket")   or "ATR_UNKNOWN"
    dv       = m.get("dollar_vol")   or (price * avg_vol)
    d_bucket = m.get("dv_bucket")    or _dv_bucket(dv)

    # ── Hard gates — immediately → SKIP ──────────────────────────────────────
    hard_skip = False
    if p_bucket == "PRICE_GT_25":
        risks.append("price_gt25"); hard_skip = True
    if a_bucket == "ATR_EXTREME_GT_40":
        risks.append("atr_extreme"); hard_skip = True
    if (result.get("compression_expansion_state") or "") == "OVERHEATED_EXPANSION":
        risks.append("overheated_expansion"); hard_skip = True

    # ── 1. Regime quality (max 5 pts) ─────────────────────────────────────────
    reg = 0.0
    if p_bucket == "PRICE_1_TO_3":
        reg += 2.0; reasons.append("price_1_3")
    elif p_bucket == "PRICE_SUB_1" and d_bucket != "DV_ILLIQUID_LT_50K":
        reg += 1.5; reasons.append("price_sub1_liquid")
    elif p_bucket == "PRICE_3_TO_10":
        reg += 1.0; reasons.append("price_3_10")
    elif p_bucket == "PRICE_10_TO_25":
        reg += 0.5

    if a_bucket == "ATR_NORMAL_5_15":
        reg += 1.0; reasons.append("atr_normal")
    elif a_bucket == "ATR_ELEVATED_15_40":
        reg += 0.5

    if d_bucket in ("DV_OK_250K_1M", "DV_LIQUID_1M_10M", "DV_HIGH_GT_10M"):
        reg += 1.0; reasons.append("dv_liquid")
    elif d_bucket == "DV_THIN_50K_250K":
        reg += 0.5
    elif d_bucket == "DV_ILLIQUID_LT_50K":
        reg -= 2.0; risks.append("dv_illiquid")

    reg = max(-3.0, min(5.0, reg))
    breakdown["regime"] = reg
    score += reg

    # ── 2. NP engine / v2 base signal (max 4 pts) ────────────────────────────
    v2   = result.get("scanner_v2_decision") or ""
    npl  = result.get("new_pump_label") or ""
    dec  = result.get("decision") or ""

    base = 0.0
    if "BUY_CANDIDATE_HIGH" in v2:
        base = 4.0; reasons.append("v2_buy_high")
    elif "BUY_CANDIDATE" in v2:
        base = 3.0; reasons.append("v2_buy")
    elif "WATCH_HIGH" in v2:
        base = 2.5; reasons.append("v2_watch_high")
    elif "WATCH_MEDIUM" in v2:
        base = 2.0; reasons.append("v2_watch_medium")
    elif "WATCH_LOW" in v2 or npl == "NEW_PUMP_FIRE":
        base = 1.5; reasons.append("v2_watch_or_fire")
    elif npl == "NEW_PUMP_STRONG":
        base = -2.0; risks.append("np_strong_extended")
    elif npl == "NEW_PUMP_SETUP" or dec == "WATCH":
        base = 1.0; reasons.append("np_setup")

    breakdown["base_pump"] = base
    score += base

    # ── 3. Demand bar signals — R156 EXPERIMENTAL (max 5 pts) ────────────────
    dem = 0.0

    # has_l34_np_ld: R156 rank #32, 1.38× lift, -9.8pp FP (EXPERIMENTAL)
    if result.get("has_l34_np_ld"):
        dem += 2.0; reasons.append("has_l34_np_ld")

    # has_wc_gap_ld: two-bar, 1.52× lift, FP doubles on absence (EXPERIMENTAL)
    if result.get("has_wc_gap_ld"):
        dem += 2.0; reasons.append("has_wc_gap_ld")

    # L34/L43 WLNBB base signal
    if result.get("l34_wlnbb") or result.get("l43_wlnbb"):
        dem += 1.0; reasons.append("l34_l43_wlnbb")

    # D4/D6 BEUP: institutional D-confluence (EXPERIMENTAL in R156)
    if result.get("d6_beup") or result.get("d4_beup"):
        dem += 1.5; reasons.append("d4_d6_beup")
    elif result.get("d3_beup") or result.get("core_d_beup"):
        dem += 1.0; reasons.append("d3_core_beup")

    # Core D + L34 combo
    if result.get("core_d_l34") or result.get("d4_l34") or result.get("d3_l34"):
        dem += 1.0; reasons.append("core_d_l34_combo")

    # Triple D+L34+BEUP same-bar (research gold standard)
    if result.get("has_triple_d_l34_beup"):
        dem += 2.0; reasons.append("triple_d_l34_beup")

    dem = min(dem, 5.0)
    breakdown["demand_bars"] = dem
    score += dem

    # ── 4. ATS — Accumulation Trap Signal (max 5 pts) ────────────────────────
    ats_signal, ats_met, ats_missing = _compute_ats(m, result)
    ats = 0.0
    if ats_signal == "ATS_PRIME":
        ats = 5.0; reasons.append("ats_prime")
    elif ats_signal == "ATS_SETUP":
        ats = 3.0; reasons.append("ats_setup")
    elif ats_signal == "ATS_WATCH":
        ats = 1.0; reasons.append("ats_watch")

    breakdown["ats"] = ats
    score += ats

    # ── 5. Context modifiers (capped ±2 pts) ─────────────────────────────────
    ctx = 0.0
    sec_ctx  = result.get("sector_context")    or {}
    mac_ctx  = result.get("macro_context")     or {}
    news_ctx = result.get("news_hype_context") or {}
    symp_ctx = result.get("sympathy_context")  or {}

    if sec_ctx.get("sector_strength") == "SECTOR_LEADING":
        ctx += 0.5; reasons.append("sector_leading")
    if mac_ctx.get("macro_tailwind"):
        ctx += 0.5; reasons.append("macro_tailwind")
    symp = symp_ctx.get("sympathy_score") or 0
    if symp >= 0.7:
        ctx += 0.5; reasons.append("sympathy_high")
    hype = news_ctx.get("hype_tier") or "COLD"
    if hype in ("WARM", "HOT"):
        ctx += 0.5; reasons.append(f"hype_{hype.lower()}")
    elif hype == "VIRAL":
        ctx -= 1.0; risks.append("hype_viral_late")
    if mac_ctx.get("macro_headwind"):
        ctx -= 0.5; risks.append("macro_headwind")
    if mac_ctx.get("risk_mode") == "FEAR":
        ctx -= 1.0; risks.append("fear_regime")

    ctx = max(-2.0, min(2.0, ctx))
    breakdown["context"] = ctx
    score += ctx

    # ── 6. CFR_A flow divergence signals (max +2.5 / min −1.5) ──────────────
    flow = _compute_flow_signals(candles or [], avg_vol)
    flow_pts = max(-1.5, min(2.5, flow["flow_score"]))
    breakdown["flow"] = flow_pts
    score += flow_pts
    if flow["flow_signals"]:
        reasons.extend(f"flow:{s.lower()}" for s in flow["flow_signals"])
    if flow["flow_risks"]:
        risks.extend(f"flow:{r.lower()}" for r in flow["flow_risks"])

    # ── Structure penalties ───────────────────────────────────────────────────
    exp_risk = result.get("expansion_timing_risk") or ""
    if exp_risk == "HIGH":
        score -= 2.0
        risks.append("expansion_timing_risk_high")
        breakdown["expansion_penalty"] = -2.0
    if result.get("fake_trigger_risk") == "HIGH":
        score -= 1.0
        risks.append("fake_trigger_high")

    # ── Final score & tier ────────────────────────────────────────────────────
    final = round(max(0.0, min(20.0, score)), 2)

    if hard_skip:
        tier = "SKIP"
    elif final >= _TIER_PRIME:
        tier = "PRIME_BUY"
    elif final >= _TIER_HIGH:
        tier = "HIGH_CONF_BUY"
    elif final >= _TIER_WATCH:
        tier = "BUY_WATCH"
    elif final >= _TIER_MONITOR:
        tier = "SETUP_MONITOR"
    else:
        tier = "SKIP"

    # Expansion risk caps tier
    if exp_risk == "HIGH" and tier in ("PRIME_BUY", "HIGH_CONF_BUY"):
        tier = "BUY_WATCH"
        risks.append("tier_capped_expansion_risk")

    # ── Readiness layer (6 gap-fills; bar_labels pre-computed above) ──────────
    readiness = _compute_readiness(m, result, candles, bar_labels=bar_labels)

    return {
        "demand_composite_score":   final,
        "demand_composite_tier":    tier,
        "demand_tier_label":        TIER_LABELS.get(tier, tier),
        "ats_signal":               ats_signal,
        "ats_conditions_met":       ats_met,
        "ats_conditions_missing":   ats_missing,
        "demand_score_breakdown":   breakdown,
        "demand_buy_reasons":       reasons,
        "demand_risk_flags":        risks,
        # Candle-level metrics pass-through for frontend
        "dc_dryup_streak":          m.get("dryup_streak", 0),
        "dc_atr_contracting":       m.get("atr_contracting", False),
        "dc_near_ema50":            m.get("near_ema50", False),
        "dc_ema_dist_pct":          (round(m["ema_dist_pct"], 1)
                                     if m.get("ema_dist_pct") is not None else None),
        "dc_vol_ratio":             round(m.get("vol_ratio", 1.0), 2),
        "dc_range_pct_5d":          round(m.get("range_pct_5d", 0.0), 1),
        "dc_max_gain_10d":          round(m.get("max_gain_10d", 0.0), 1),
        "dc_price_bucket":          p_bucket,
        "dc_atr_bucket":            a_bucket,
        "dc_dv_bucket":             d_bucket,
        "dc_tight_range":           m.get("tight_range", False),
        # Readiness layer (includes confluence_signals, confluence sub-score)
        **readiness,
        "combined_score":           round(final + readiness["readiness_score"], 2),
        # CFR_A flow divergence signals
        "flow_signals":             flow["flow_signals"],
        "flow_risks":               flow["flow_risks"],
    }


# ── Batch application ────────────────────────────────────────────────────────

def apply_demand_composite(
    results: list[dict],
    candle_map: Optional[dict[str, list]] = None,
) -> list[dict]:
    """
    Apply demand_composite scoring to a list of scan results.
    Returns a new list sorted by tier then score descending.

    Parameters
    ----------
    results    : list of dicts from new_pump_runner / scanner_v2
    candle_map : {symbol: [candle_dict, ...]} — pass to enable ATS and full scoring
    """
    candle_map = candle_map or {}
    enriched = []
    for r in results:
        try:
            candles = candle_map.get(r.get("symbol") or "")
            dc = score_demand_composite(r, candles)
            enriched.append({**r, **dc})
        except Exception as exc:
            logger.warning(f"demand_composite failed for {r.get('symbol')}: {exc}")
            enriched.append(r)

    enriched.sort(key=lambda x: (
        TIER_ORDER.get(x.get("demand_composite_tier") or "SKIP", 4),
        -(x.get("demand_composite_score") or 0.0),
    ))
    return enriched
