"""
Toxic Microcap Filter
=====================
Scores a ticker's toxicity risk using available indicator data.

Purpose: Reduce catastrophic false positives — extreme collapse-prone junk
names — especially in the Pump Engine where more speculative names are allowed.

This filter is:
  - additive and purely read-only
  - usable in Pump Engine and research views
  - NOT applied to existing main scanner tiers or total_score

Scoring is deterministic and explainable. No ML / black-box logic.

Toxicity levels:
  LOW      (0–19)   — likely legitimate setup
  MEDIUM   (20–44)  — elevated risk, proceed with caution
  HIGH     (45–69)  — high probability of junk / pump-and-dump profile
  EXTREME  (70–100) — very likely toxic; filter from most views

Available indicator fields (from calc_all()):
  price, atr_pct, atr_ratio, anomaly_ratio, vol_z,
  price_change_pct, price_change_pct_5d,
  bullish_stack, bearish_stack, ribbon_compression,
  obv.obv_slope_5d, obv.obv_divergence,
  rsi.value, bb_width, cmf

NOT available in hot path: shares float, market cap (require reference API call)
"""

import logging

logger = logging.getLogger(__name__)


def score_toxicity(indicators: dict, price: float | None = None) -> dict:
    """
    Compute a toxicity score for a single ticker.

    Parameters
    ----------
    indicators : dict from calc_all()
    price      : current price (float), used for penny-stock heuristic.
                 Falls back to indicators.get("price") if None.

    Returns
    -------
    dict with:
        toxicity_score : int 0–100
        toxicity_level : "LOW" | "MEDIUM" | "HIGH" | "EXTREME"
        toxicity_flags : list[str]  — explainable sub-reasons
    """
    if price is None:
        price = indicators.get("price") or 0.0

    score = 0
    flags: list[str] = []

    # ── 1. Penny-stock price risk ─────────────────────────────────────────────
    if price > 0:
        if price < 1.50:
            # Should be caught by volume gate, but sanity check
            score += 30
            flags.append("sub_$1.50_price")
        elif price < 3.00:
            score += 20
            flags.append("sub_$3_price")
        elif price < 5.00:
            score += 8
            flags.append("sub_$5_price")

    # ── 2. Extreme short-term ATR (volatility regime) ─────────────────────────
    atr_pct = indicators.get("atr_pct", 0.0) or 0.0
    if atr_pct > 20:
        score += 25
        flags.append(f"extreme_atr_{atr_pct:.0f}pct")
    elif atr_pct > 12:
        score += 14
        flags.append(f"high_atr_{atr_pct:.0f}pct")
    elif atr_pct > 8:
        score += 5
        flags.append(f"elevated_atr_{atr_pct:.0f}pct")

    # ── 3. Blown-out single-day move — pump-and-dump risk ────────────────────
    price_chg_1d = abs(indicators.get("price_change_pct", 0.0) or 0.0)
    if price_chg_1d > 60:
        score += 30
        flags.append(f"extreme_1d_move_{price_chg_1d:.0f}pct")
    elif price_chg_1d > 40:
        score += 20
        flags.append(f"large_1d_move_{price_chg_1d:.0f}pct")
    elif price_chg_1d > 25:
        score += 10
        flags.append(f"big_1d_move_{price_chg_1d:.0f}pct")

    # ── 4. Extended multi-day expansion without consolidation ─────────────────
    price_chg_5d = indicators.get("price_change_pct_5d", 0.0) or 0.0
    if price_chg_5d > 80:
        score += 15
        flags.append(f"extreme_5d_expansion_{price_chg_5d:.0f}pct")
    elif price_chg_5d > 50:
        score += 8
        flags.append(f"large_5d_expansion_{price_chg_5d:.0f}pct")

    # ── 5. Suspicious volume anomaly without structural support ───────────────
    anomaly_ratio   = indicators.get("anomaly_ratio", 0.0) or 0.0
    bullish_stack   = indicators.get("bullish_stack", False)
    bearish_stack   = indicators.get("bearish_stack", False)
    ribbon_compr    = indicators.get("ribbon_compression", "NONE")
    has_structure   = bullish_stack or ribbon_compr in ("STRONG", "MEDIUM")

    if anomaly_ratio > 5.0 and not has_structure:
        score += 22
        flags.append(f"anomaly_{anomaly_ratio:.1f}x_no_structure")
    elif anomaly_ratio > 3.0 and not has_structure:
        score += 10
        flags.append(f"anomaly_{anomaly_ratio:.1f}x_weak_structure")

    # ── 6. Bearish stack with volume — distribution / dump pattern ────────────
    if bearish_stack and anomaly_ratio > 2.0:
        score += 20
        flags.append("bearish_stack_with_volume_spike")
    elif bearish_stack and price_chg_1d > 15:
        score += 14
        flags.append("bearish_stack_with_big_move")

    # ── 7. OBV divergence with strong price move — hidden selling ─────────────
    obv         = indicators.get("obv", {}) or {}
    obv_slope   = obv.get("obv_slope_5d", 0.0) or 0.0
    obv_div     = obv.get("obv_divergence", False)

    if obv_div and price_chg_1d > 15:
        score += 12
        flags.append("obv_divergence_on_big_move")
    elif obv_slope < -0.03 and price_chg_1d > 10:
        score += 8
        flags.append("falling_obv_slope_with_move")

    # ── 8. Extremely wide Bollinger Bands (post-explosion vol regime) ─────────
    bb_width = indicators.get("bb_width", 0.0) or 0.0
    if bb_width > 0.30:     # >30% of price = post-explosion territory
        score += 10
        flags.append(f"extreme_bb_width_{bb_width:.2f}")
    elif bb_width > 0.20:
        score += 4
        flags.append(f"wide_bb_{bb_width:.2f}")

    # ── 9. RSI extremes ───────────────────────────────────────────────────────
    rsi_data = indicators.get("rsi", {}) or {}
    rsi_val  = rsi_data.get("value", 50.0) or 50.0
    if rsi_val > 90:
        score += 10
        flags.append(f"extreme_rsi_{rsi_val:.0f}")
    elif rsi_val < 25:
        score += 6
        flags.append(f"oversold_rsi_{rsi_val:.0f}")

    # ── Cap and classify ──────────────────────────────────────────────────────
    score = min(100, score)

    if score >= 70:
        level = "EXTREME"
    elif score >= 45:
        level = "HIGH"
    elif score >= 20:
        level = "MEDIUM"
    else:
        level = "LOW"

    return {
        "toxicity_score": score,
        "toxicity_level": level,
        "toxicity_flags": flags,
    }


def toxicity_penalty(toxicity_score: int) -> float:
    """
    Return a penalty multiplier (0.0–1.0) for use in pump quality scoring.
    0 toxicity → 1.0 (no penalty)
    100 toxicity → 0.3 (heavy penalty)
    """
    # Linear from 1.0 at score=0 to 0.3 at score=100
    return max(0.3, 1.0 - (toxicity_score / 100) * 0.7)
