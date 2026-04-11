"""
Pump Engine v1 — Explosive / Speculative Mover Discovery
=========================================================
A SEPARATE analytical engine designed to surface pump-style, news-driven,
sympathy-play, and explosive-velocity candidates that the structured
breakout engine tends to miss.

DESIGN PRINCIPLE:
  Engine A (main scanner): ribbon + ignition + sector structure → orderly setups
  Engine B (pump engine) : velocity + volume wake-up + behavior → explosive setups

CRITICAL:
  - Never modifies total_score, tier, or main scanner output
  - Completely additive — separate scoring dimension
  - Uses same raw indicator data but different weighting
  - Allows looser structure than main engine
  - Suppresses obvious junk via toxicity filter

Pump Score Weights (sum to 100%):
  velocity_expansion_score   × 0.30  — price movement velocity + ATR expansion
  volume_wakeup_score        × 0.20  — abnormal volume relative to history
  price_behavior_score       × 0.20  — close near high, continuation quality
  theme_context_score        × 0.15  — sector/ribbon context (simplified)
  toxicity_adjustment        × 0.15  — penalty for toxic profiles

Pump Signals:
  PUMP_ACTIVE      — already moving, volume confirmed, price expanding (momentum)
  PUMP_BUILDING    — accumulating energy, not yet explosive
  PUMP_EARLY       — early signs, potential setup forming
  PUMP_SPECULATIVE — speculative context only, weak confirmation
  NO_PUMP_SIGNAL   — no meaningful pump characteristics

Pump Buckets:
  LOW_FLOAT_VELOCITY    — low price + extreme velocity (micro/nano-cap pump)
  MULTI_DAY_EXPANSION   — strong 5d expansion + recent volume
  VOLUME_WAKEUP         — abnormal volume spike, price just starting to move
  SPECULATIVE_BREAKOUT  — compression + velocity but volume lagging
  NEWS_SYMPATHY         — sector/theme hot (if context available)
  NONE
"""

import logging

from scanner.ribbon_engine import classify_ribbon
from scanner.toxic_filter  import score_toxicity, toxicity_penalty

logger = logging.getLogger(__name__)


# ── Scoring helpers ───────────────────────────────────────────────────────────

def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def _velocity_expansion_score(indicators: dict) -> tuple[float, list[str]]:
    """
    Score short- and medium-term price + volatility expansion.
    Returns (score 0-100, reasons list).
    """
    price_chg_1d = indicators.get("price_change_pct",    0.0) or 0.0
    price_chg_5d = indicators.get("price_change_pct_5d", 0.0) or 0.0
    atr_ratio    = indicators.get("atr_ratio",           1.0) or 1.0
    ema8_slope   = indicators.get("ema8_slope",          "FLAT")
    bb_pctl      = indicators.get("bb_pctl",              0.5) or 0.5

    score   = 0.0
    reasons = []

    # 1-day move
    if price_chg_1d >= 15:
        score += 35; reasons.append(f"+{price_chg_1d:.1f}% today")
    elif price_chg_1d >= 8:
        score += 22; reasons.append(f"+{price_chg_1d:.1f}% today")
    elif price_chg_1d >= 4:
        score += 12; reasons.append(f"+{price_chg_1d:.1f}% today")
    elif price_chg_1d >= 1.5:
        score += 5

    # 5-day expansion (multi-day move)
    if price_chg_5d >= 30:
        score += 30; reasons.append(f"+{price_chg_5d:.1f}% (5d)")
    elif price_chg_5d >= 15:
        score += 18; reasons.append(f"+{price_chg_5d:.1f}% (5d)")
    elif price_chg_5d >= 8:
        score += 10; reasons.append(f"+{price_chg_5d:.1f}% (5d)")

    # ATR expansion (range is expanding = volatile = pump-like)
    if atr_ratio >= 2.0:
        score += 20; reasons.append(f"ATR {atr_ratio:.1f}x expanded")
    elif atr_ratio >= 1.5:
        score += 12; reasons.append(f"ATR {atr_ratio:.1f}x expanded")
    elif atr_ratio >= 1.2:
        score += 5

    # EMA slope acceleration
    if ema8_slope == "RISING":
        score += 8; reasons.append("EMA8 rising")

    # Bollinger band position (near top = price holding expansion)
    if bb_pctl >= 0.85:
        score += 8; reasons.append("price at BB top")
    elif bb_pctl >= 0.70:
        score += 4

    return _clamp(score), reasons


def _volume_wakeup_score(indicators: dict) -> tuple[float, list[str]]:
    """Score abnormal volume relative to recent history."""
    anomaly_ratio = indicators.get("anomaly_ratio", 0.0) or 0.0
    vol_z         = indicators.get("vol_z",         0.0) or 0.0
    today_vol     = indicators.get("today_vol",     0)   or 0
    avg_vol_5     = indicators.get("avg_vol_5",     1)   or 1
    avg_vol_20    = indicators.get("avg_vol_20",    1)   or 1

    score   = 0.0
    reasons = []

    # Anomaly ratio (vs 20-day avg)
    if anomaly_ratio >= 5.0:
        score += 45; reasons.append(f"volume {anomaly_ratio:.1f}x anomaly")
    elif anomaly_ratio >= 3.0:
        score += 30; reasons.append(f"volume {anomaly_ratio:.1f}x anomaly")
    elif anomaly_ratio >= 2.0:
        score += 18; reasons.append(f"volume {anomaly_ratio:.1f}x avg")
    elif anomaly_ratio >= 1.5:
        score += 8;  reasons.append(f"volume {anomaly_ratio:.1f}x avg")

    # Volume Z-score
    if vol_z >= 3.0:
        score += 25; reasons.append(f"vol z-score {vol_z:.1f}")
    elif vol_z >= 2.0:
        score += 15; reasons.append(f"vol z-score {vol_z:.1f}")
    elif vol_z >= 1.5:
        score += 8

    # Absolute volume threshold (actual liquidity)
    if today_vol >= 2_000_000:
        score += 15; reasons.append(f"{today_vol/1e6:.1f}M shares")
    elif today_vol >= 1_000_000:
        score += 10; reasons.append(f"{today_vol/1e6:.1f}M shares")
    elif today_vol >= 500_000:
        score += 5

    return _clamp(score), reasons


def _price_behavior_score(indicators: dict) -> tuple[float, list[str]]:
    """Score price continuation quality — can the name hold its gains?"""
    stealth       = indicators.get("stealth", {}) or {}
    close_pos     = stealth.get("close_position",  0.5) or 0.5
    obv           = indicators.get("obv",          {})  or {}
    obv_div       = obv.get("obv_divergence",       False)
    obv_strength  = obv.get("obv_strength",        "WEAK")
    obv_slope_5d  = obv.get("obv_slope_5d",        0.0) or 0.0
    cmf           = indicators.get("cmf",          0.0) or 0.0
    rsi_data      = indicators.get("rsi",          {})  or {}
    rsi_val       = rsi_data.get("value",          50)  or 50
    rsi_div       = rsi_data.get("has_divergence", False)
    bb_pctl       = indicators.get("bb_pctl",      0.5) or 0.5
    bearish_stack = indicators.get("bearish_stack", False)
    above_ema20   = indicators.get("above_ema20",  False)

    score   = 0.0
    reasons = []

    # Close position (where did price close relative to day range?)
    if close_pos >= 0.80:
        score += 20; reasons.append("closed near high")
    elif close_pos >= 0.60:
        score += 12; reasons.append("strong close")
    elif close_pos <= 0.30:
        score -= 15; reasons.append("closed near low (reversal risk)")

    # OBV confirmation
    if not obv_div and obv_strength in ("STRONG", "MEDIUM") and obv_slope_5d > 0:
        score += 18; reasons.append("OBV confirming")
    elif obv_div:
        score -= 15; reasons.append("OBV diverging (distribution risk)")

    # CMF (money flow)
    if cmf > 0.15:
        score += 15; reasons.append("strong CMF inflow")
    elif cmf > 0.05:
        score += 8;  reasons.append("positive CMF")
    elif cmf < -0.10:
        score -= 12; reasons.append("negative CMF")

    # Price structure
    if above_ema20 and not bearish_stack:
        score += 12; reasons.append("above EMA20")
    if bearish_stack:
        score -= 20; reasons.append("bearish structure")

    # RSI positioning (not too extended, not too weak)
    if 40 <= rsi_val <= 70:
        score += 10; reasons.append(f"RSI {rsi_val:.0f} healthy")
    elif rsi_val > 80:
        score -= 8;  reasons.append(f"RSI {rsi_val:.0f} extended")
    if rsi_div:
        score -= 10; reasons.append("RSI divergence")

    return _clamp(score), reasons


def _theme_context_score(indicators: dict, ribbon_class: str,
                          sector_context: dict | None = None) -> tuple[float, list[str]]:
    """
    Score theme/context support. Simplified without live sector API calls.
    Uses ribbon class, sector context if provided, and structural alignment.
    """
    score   = 0.0
    reasons = []

    # Ribbon quality as proxy for structural theme alignment
    rb_boost = {
        "RIBBON_CONFIRMED":    30,
        "RIBBON_CONSTRUCTIVE": 20,
        "RIBBON_EARLY":        10,
        "RIBBON_WEAK":          0,
        "RIBBON_NONE":         -5,
    }
    boost = rb_boost.get(ribbon_class, 0)
    score += boost
    if boost > 10:
        reasons.append(f"ribbon {ribbon_class.replace('RIBBON_', '').lower()}")

    # Sector context (if passed from caller)
    if sector_context:
        sector_change = sector_context.get("change_pct", 0.0) or 0.0
        if sector_change > 2.0:
            score += 20; reasons.append(f"sector +{sector_change:.1f}% today")
        elif sector_change > 0.5:
            score += 10; reasons.append(f"sector {sector_change:+.1f}%")
        elif sector_change < -1.5:
            score -= 15; reasons.append(f"sector {sector_change:.1f}% headwind")

    # Institutional flow bonus
    inst_flow = indicators.get("institutional_flow", {}) or {}
    if inst_flow.get("is_institutional"):
        score += 15; reasons.append("institutional flow")

    return _clamp(score), reasons


# ── Main pump scorer ──────────────────────────────────────────────────────────

def score_pump(
    indicators: dict,
    price: float | None = None,
    sector_context: dict | None = None,
) -> dict:
    """
    Score a single ticker on the pump/explosive mover dimension.

    Parameters
    ----------
    indicators     : output of calc_all() from indicators.py
    price          : current price (float)
    sector_context : optional dict with {change_pct, sector_class, ...}

    Returns
    -------
    dict with all pump fields (see module docstring for full shape)
    """
    price = price or indicators.get("price") or 0.0

    # ── Compute sub-scores ────────────────────────────────────────────────────
    ribbon_class                        = classify_ribbon(indicators)
    toxicity                            = score_toxicity(indicators, price)
    v_score,  v_reasons                 = _velocity_expansion_score(indicators)
    vol_score, vol_reasons              = _volume_wakeup_score(indicators)
    beh_score, beh_reasons              = _price_behavior_score(indicators)
    theme_score, theme_reasons          = _theme_context_score(indicators, ribbon_class, sector_context)

    tox_score = toxicity["toxicity_score"]
    tox_mult  = toxicity_penalty(tox_score)

    # ── Weighted pump quality (0-100) ─────────────────────────────────────────
    raw_quality = (
        v_score    * 0.30 +
        vol_score  * 0.20 +
        beh_score  * 0.20 +
        theme_score * 0.15 +
        (100 - tox_score) * 0.15
    )
    pump_quality = int(_clamp(raw_quality * tox_mult))

    # ── Pump signal classification ────────────────────────────────────────────
    anomaly   = indicators.get("anomaly_ratio",    0.0) or 0.0
    price_chg = indicators.get("price_change_pct", 0.0) or 0.0

    if pump_quality >= 55 and anomaly >= 2.5 and price_chg >= 6.0:
        pump_signal = "PUMP_ACTIVE"
    elif pump_quality >= 40 and (anomaly >= 1.5 or price_chg >= 3.0):
        pump_signal = "PUMP_BUILDING"
    elif pump_quality >= 28:
        pump_signal = "PUMP_EARLY"
    elif pump_quality >= 15:
        pump_signal = "PUMP_SPECULATIVE"
    else:
        pump_signal = "NO_PUMP_SIGNAL"

    # ── Pump bucket ───────────────────────────────────────────────────────────
    price_chg_5d = indicators.get("price_change_pct_5d", 0.0) or 0.0
    atr_ratio    = indicators.get("atr_ratio",            1.0) or 1.0

    if price < 5.0 and atr_ratio >= 1.5 and price_chg >= 8.0:
        pump_bucket = "LOW_FLOAT_VELOCITY"
    elif price_chg_5d >= 20 and anomaly >= 2.0:
        pump_bucket = "MULTI_DAY_EXPANSION"
    elif anomaly >= 2.5 and abs(price_chg) < 5.0:
        pump_bucket = "VOLUME_WAKEUP"
    elif ribbon_class in ("RIBBON_CONFIRMED", "RIBBON_CONSTRUCTIVE") and v_score >= 30:
        pump_bucket = "SPECULATIVE_BREAKOUT"
    elif sector_context and sector_context.get("change_pct", 0) > 2.0 and anomaly >= 1.5:
        pump_bucket = "NEWS_SYMPATHY"
    elif pump_quality >= 20:
        pump_bucket = "VOLUME_WAKEUP"
    else:
        pump_bucket = "NONE"

    # ── Confirmations and warnings ────────────────────────────────────────────
    confirmations: list[str] = []
    warnings:      list[str] = []

    for r in v_reasons[:3]:
        confirmations.append(r)
    for r in vol_reasons[:2]:
        confirmations.append(r)
    for r in beh_reasons[:2]:
        if not r.startswith("closed near low") and not r.startswith("OBV div") and not r.startswith("bearish"):
            confirmations.append(r)
    for r in theme_reasons[:1]:
        confirmations.append(r)

    # Negative behavior reasons → warnings
    for r in beh_reasons:
        if any(kw in r for kw in ("low", "diverg", "bearish", "extended", "reversal")):
            warnings.append(r)

    if toxicity["toxicity_level"] in ("HIGH", "EXTREME"):
        warnings.append(f"toxicity {toxicity['toxicity_level'].lower()} ({tox_score})")
    for f in toxicity["toxicity_flags"][:2]:
        if f not in " ".join(warnings):
            warnings.append(f)

    if anomaly >= 5.0:
        confirmations = [c for c in confirmations if "volume" not in c.lower()][:3]
        warnings.insert(0, f"extreme volume spike ({anomaly:.1f}x) — verify catalyst")

    # Build human-readable reason
    if pump_signal == "NO_PUMP_SIGNAL":
        pump_reason = "No meaningful pump characteristics detected"
    else:
        parts = confirmations[:2]
        pump_reason = " + ".join(parts) if parts else f"{pump_signal} setup detected"

    return {
        "pump_signal":        pump_signal,
        "pump_bucket":        pump_bucket,
        "pump_quality":       pump_quality,
        "pump_reason":        pump_reason,
        "pump_confirmations": confirmations[:6],
        "pump_warnings":      warnings[:4],
        "ribbon_class":       ribbon_class,
        "toxicity_score":     tox_score,
        "toxicity_level":     toxicity["toxicity_level"],
        "toxicity_flags":     toxicity["toxicity_flags"],
        # Sub-scores for debugging / research
        "_velocity_score":    round(v_score,    1),
        "_volume_score":      round(vol_score,  1),
        "_behavior_score":    round(beh_score,  1),
        "_theme_score":       round(theme_score, 1),
    }


# ── Pump engine runner ────────────────────────────────────────────────────────

_SIGNAL_ORDER = {
    "PUMP_ACTIVE":      0,
    "PUMP_BUILDING":    1,
    "PUMP_EARLY":       2,
    "PUMP_SPECULATIVE": 3,
    "NO_PUMP_SIGNAL":   4,
}


def run_pump_engine(
    main_results:   list[dict],
    ribbon_results: list[dict] | None = None,
    mode:           str  = "all",
    min_volume:     int  = 200_000,
    max_toxicity:   int  = 80,
    min_quality:    int  = 0,
    bullish_only:   bool = False,
    max_results:    int  = 100,
) -> dict:
    """
    Run the pump engine on a merged set of scan candidates.

    Parameters
    ----------
    main_results    : list of scan candidate dicts from get_latest_scan()
    ribbon_results  : optional additional ribbon candidate rows
    mode            : "all" | "active" | "building" | "early" | "speculative"
    min_volume      : minimum today_vol filter
    max_toxicity    : maximum toxicity_score (0–100); default 80 allows all but EXTREME
    min_quality     : minimum pump_quality filter (0–100)
    bullish_only    : if True, exclude bearish-stack candidates
    max_results     : result limit

    Returns
    -------
    dict with "candidates", "counts", "total" keys
    """
    # ── Merge sources (main takes priority over ribbon) ───────────────────────
    seen: set[str] = set()
    merged: list[dict] = []

    def _add(r: dict, source: str):
        sym = (r.get("symbol") or "").upper()
        if not sym or sym in seen:
            return
        seen.add(sym)
        # Normalise indicators access
        ind = r.get("indicators") or r.get("_indicators") or {}
        merged.append({
            "symbol":           sym,
            "price":            r.get("price") or 0.0,
            "tier":             (r.get("score") or {}).get("tier") or r.get("tier"),
            "total_score":      (r.get("score") or {}).get("total_score") or r.get("total_score"),
            "sector":           r.get("sector", "Unknown"),
            "industry":         r.get("industry", ""),
            "today_vol":        ind.get("today_vol") or r.get("today_vol") or r.get("volume_today") or 0,
            "anomaly_ratio":    ind.get("anomaly_ratio", 0.0),
            "price_change_pct": ind.get("price_change_pct", 0.0),
            "source":           source,
            "_indicators":      ind,
        })

    for r in main_results:
        _add(r, "main_scan")
    for r in (ribbon_results or []):
        _add(r, "ribbon_pass")

    # ── Volume pre-filter ─────────────────────────────────────────────────────
    # Pump engine uses a slightly lower bar than main scan to catch nascent movers
    pump_min_vol = max(100_000, min_volume)
    filtered = [r for r in merged if (r["today_vol"] or 0) >= pump_min_vol]

    # ── Score each candidate ──────────────────────────────────────────────────
    scored: list[dict] = []
    for r in filtered:
        ind   = r["_indicators"]
        price = r["price"]

        if bullish_only and ind.get("bearish_stack"):
            continue

        pump = score_pump(ind, price)

        # Apply filters
        if pump["toxicity_score"] > max_toxicity:
            continue
        if pump["pump_quality"] < min_quality:
            continue

        mode_map = {
            "active":      {"PUMP_ACTIVE"},
            "building":    {"PUMP_ACTIVE", "PUMP_BUILDING"},
            "early":       {"PUMP_ACTIVE", "PUMP_BUILDING", "PUMP_EARLY"},
            "speculative": {"PUMP_ACTIVE", "PUMP_BUILDING", "PUMP_EARLY", "PUMP_SPECULATIVE"},
            "all":         {"PUMP_ACTIVE", "PUMP_BUILDING", "PUMP_EARLY", "PUMP_SPECULATIVE", "NO_PUMP_SIGNAL"},
        }
        allowed = mode_map.get(mode, mode_map["all"])
        if pump["pump_signal"] not in allowed:
            continue

        # Clean up internal keys
        pump.pop("_velocity_score", None)
        pump.pop("_volume_score",   None)
        pump.pop("_behavior_score", None)
        pump.pop("_theme_score",    None)

        scored.append({
            "symbol":              r["symbol"],
            "price":               price,
            "sector":              r["sector"],
            "industry":            r["industry"],
            "tier":                r["tier"],
            "total_score":         r["total_score"],
            "source":              r["source"],
            "today_vol":           r["today_vol"],
            "anomaly_ratio":       r["anomaly_ratio"],
            "price_change_pct":    r["price_change_pct"],
            "ignition_signal":     ind.get("ignition_signal", "NO_IGNITION"),
            **pump,
        })

    # ── Sort: signal priority → quality desc ─────────────────────────────────
    scored.sort(key=lambda x: (
        _SIGNAL_ORDER.get(x["pump_signal"], 99),
        -x["pump_quality"],
    ))

    # ── Count by signal ───────────────────────────────────────────────────────
    counts: dict[str, int] = {
        "PUMP_ACTIVE":      0,
        "PUMP_BUILDING":    0,
        "PUMP_EARLY":       0,
        "PUMP_SPECULATIVE": 0,
        "NO_PUMP_SIGNAL":   0,
    }
    for s in scored:
        counts[s["pump_signal"]] = counts.get(s["pump_signal"], 0) + 1

    result = scored[:max_results]

    logger.info(
        f"[PUMP] scanned={len(merged)} filtered={len(filtered)} scored={len(scored)} "
        f"returned={len(result)} mode={mode}"
    )

    return {
        "candidates": result,
        "counts":     counts,
        "total":      len(scored),
        "scanned":    len(merged),
    }
