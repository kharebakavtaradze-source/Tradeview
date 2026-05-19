"""
Demand Composite Scanner — pump-scout signal fusion layer.

Combines all research signals from R154–R156 into a single composite score
with a custom ACCUMULATION_TRAP_SIGNAL (ATS) and tiered BUY recommendations.

Signal stack:
  Tier 1 — Regime quality         (price, ATR, dollar-volume buckets)
  Tier 2 — NP engine / v2 base    (existing scanner decision)
  Tier 3 — Demand bar signals      (has_l34_np_ld, has_wc_gap_ld, D-confluence)
  Tier 4 — ATS composite signal    (custom — see below)
  Tier 5 — Context modifiers       (sector, macro, sympathy, hype)

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

    return {
        "price":            price,
        "atr14":            atr14,
        "atr_pct":          atr_pct,
        "atr_contracting":  atr_contracting,
        "dryup_streak":     dryup_streak,
        "ema50":            ema50,
        "ema_dist_pct":     ema_dist_pct,
        "near_ema50":       near_ema50,
        "not_pumped":       not_pumped,
        "max_gain_10d":     max_gain_10d,
        "tight_range":      tight_range,
        "range_pct_5d":     range_pct_5d,
        "has_demand_close": has_demand_close,
        "vol_ratio":        vol_ratio,
        "dollar_vol":       dollar_vol,
        "price_bucket":     _price_bucket(price),
        "atr_bucket":       _atr_bucket(atr_pct),
        "dv_bucket":        _dv_bucket(dollar_vol),
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
    elif "WATCH_LOW" in v2 or npl in ("NEW_PUMP_FIRE", "NEW_PUMP_STRONG"):
        base = 1.5; reasons.append("v2_watch_or_fire")
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
