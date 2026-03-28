"""
Scoring engine: combines indicator data + Wyckoff regime into a composite score.
"""
import logging

logger = logging.getLogger(__name__)


def score_ticker(indicators: dict, regime: dict, symbol: str = "") -> dict:
    anomaly_ratio = indicators.get("anomaly_ratio", 0)
    cmf_pctl = indicators.get("cmf_pctl", 0)
    cmf_val = indicators.get("cmf", 0)
    sqz_bars = indicators.get("bb_sqz_bars", 0)
    in_acc = regime.get("in_acc", False)
    price_change_pct_signed = indicators.get("price_change_pct", 0)
    price_change_pct = abs(price_change_pct_signed)
    state = regime.get("state", "NONE")
    stealth = indicators.get("stealth", {})
    vol_ratio = stealth.get("vol_ratio", 0)  # today_vol / yesterday_vol

    # --- Volume Anomaly Score (0–100) ---
    if anomaly_ratio >= 10:
        vol_score = 100
    elif anomaly_ratio >= 5:
        vol_score = 80
    elif anomaly_ratio >= 3:
        vol_score = 60
    elif anomaly_ratio >= 2:
        vol_score = 40
    else:
        vol_score = 0

    # --- Accumulation Score (0–100) ---
    accum_score = 0

    # CMF component (max 30)
    if cmf_pctl >= 80:
        accum_score += 30
    elif cmf_pctl >= 60:
        accum_score += 20
    elif cmf_val > 0:
        accum_score += 10

    # Squeeze component (max 30)
    if sqz_bars >= 10:
        accum_score += 30
    elif sqz_bars >= 5:
        accum_score += 20
    elif sqz_bars >= 3:
        accum_score += 10

    # Accumulation regime bonus (max 30)
    if in_acc:
        accum_score += 30

    accum_score = min(accum_score, 100)

    # --- RSI Divergence bonus (max +20 to accum_score) ---
    rsi_data = indicators.get("rsi", {})
    if rsi_data.get("has_divergence"):
        div_strength = rsi_data.get("div_strength", 0)
        rsi_bonus = 20 if div_strength >= 10 else 15 if div_strength >= 5 else 10
        accum_score = min(accum_score + rsi_bonus, 100)

    # --- OBV bonus (max +25 to accum_score) ---
    # OBV confirms accumulation: rising OBV = smart money buying
    # OBV divergence (OBV up, price flat) = our key stealth pattern
    obv = indicators.get("obv", {})
    obv_strength = obv.get("obv_strength", "WEAK")
    obv_divergence = obv.get("obv_divergence", False)
    if obv_strength == "STRONG":
        accum_score = min(accum_score + 15, 100)
    elif obv_strength == "MEDIUM":
        accum_score = min(accum_score + 8, 100)
    if obv_divergence:
        accum_score = min(accum_score + 10, 100)

    # --- Gap bonus (up to +15 to vol_score, penalty for gap down) ---
    gap = indicators.get("gap", {})
    gap_type = gap.get("gap_type", "NONE")
    if gap_type == "GAP_UP_STRONG":
        vol_score = min(vol_score + 15, 100)
    elif gap_type == "GAP_UP":
        vol_score = min(vol_score + 8, 100)
    elif gap_type == "GAP_DOWN_STRONG":
        vol_score = max(vol_score - 20, 0)
    elif gap_type == "GAP_DOWN":
        vol_score = max(vol_score - 10, 0)

    # --- Stealth Bonus ---
    stealth_bonus = 0
    if stealth.get("is_stealth"):
        stealth_bonus = stealth.get("stealth_score", 0) * 0.3

    # --- Quiet Factor (multiplier) ---
    if price_change_pct < 1.0 and anomaly_ratio > 3.0:
        quiet_factor = 1.5
    elif price_change_pct < 3.0 and anomaly_ratio > 2.0:
        quiet_factor = 1.2
    else:
        quiet_factor = 1.0

    # OBV divergence nudge: when quiet_factor is already elevated, push it a bit more
    if obv_divergence and quiet_factor > 1.0:
        quiet_factor = min(1.5, quiet_factor + 0.1)

    # --- Institutional Flow Bonus ---
    inst = indicators.get("institutional_flow", {})
    inst_bonus = inst.get("flow_score", 0) * 0.2 if inst.get("is_institutional") else 0

    # --- Composite Score ---
    total_score = (vol_score * 0.4 + accum_score * 0.3 + stealth_bonus * 0.3) * quiet_factor
    total_score = min(total_score + inst_bonus, 100)

    # Stealth floor: stealth signal always at least WATCH
    if stealth.get("is_stealth") and total_score < 25:
        total_score = 25

    # --- RSI overbought penalty ---
    rsi_value = rsi_data.get("value", 50) or 50
    if rsi_value > 70:
        total_score *= 0.7   # overbought — significantly reduce
    elif rsi_value > 65:
        total_score *= 0.85  # approaching overbought

    # --- Weak money-flow penalty ---
    if cmf_pctl < 20:
        total_score *= 0.8

    # --- Distribution penalty ---
    # Stocks in distribution are being sold by smart money — heavy penalty
    if regime.get("in_dist"):
        total_score *= 0.6

    # --- OBV NEGATIVE penalty (secondary signal, lighter than CMF) ---
    if obv_strength == "NEGATIVE":
        total_score *= 0.85

    total_score = round(min(total_score, 100), 2)

    # --- Tier ---
    # Step 1: score-based tier
    if total_score > 80:
        tier = "FIRE"
    elif total_score > 60:
        tier = "ARM"
    elif total_score > 40:
        tier = "BASE"
    elif stealth.get("is_stealth") and stealth.get("stealth_score", 0) >= 50:
        tier = "STEALTH"
    elif total_score > 25:
        tier = "WATCH"
    else:
        tier = "SKIP"

    # Step 2: Wyckoff state can upgrade tier but never downgrade
    _TIER_RANK = {"SKIP": 0, "WATCH": 1, "STEALTH": 2, "SYMPATHY": 3, "BASE": 3, "ARM": 4, "FIRE": 5}
    _STATE_MIN = {
        "FIRE": "FIRE",
        "ARM": "ARM",
        "BASE": "BASE",
        "STEALTH": "STEALTH",
        "STEALTH_BASE": "STEALTH",
        "STEALTH_ARM": "STEALTH",
    }
    if state in _STATE_MIN:
        candidate = _STATE_MIN[state]
        if _TIER_RANK.get(candidate, 0) > _TIER_RANK.get(tier, 0):
            tier = candidate

    # Step 3: Strong institutional flow upgrades BASE/WATCH to ARM
    if (
        inst.get("is_institutional")
        and inst.get("days", 0) >= 5
        and inst.get("flow_score", 0) >= 70
        and tier in ("BASE", "WATCH")
    ):
        tier = "ARM"

    # Step 4: Hard caps from penalty conditions
    # Distribution stocks can never be FIRE
    if regime.get("in_dist") and tier == "FIRE":
        tier = "ARM"
    # Overbought stocks (RSI > 70) can never be FIRE
    if rsi_value > 70 and tier == "FIRE":
        tier = "ARM"

    original_tier = tier

    # Step 5: CEF/ETN downgrade
    # Volume signals in closed-end funds / ETNs are driven by NAV/distribution
    # mechanics, not institutional accumulation — cap at WATCH
    cef_warning = False
    cef_note = None
    if symbol:
        from scanner.sector_map import NON_STOCK_SECURITIES
        if symbol.upper() in NON_STOCK_SECURITIES:
            cef_warning = True
            cef_note = (
                "Closed-end fund or ETN — volume signals may reflect "
                "NAV/distribution mechanics, not institutional accumulation."
            )
            if tier in ("FIRE", "ARM"):
                tier = "WATCH"
                total_score = round(total_score * 0.6, 2)
                logger.info(
                    f"CEF downgrade: {symbol} {original_tier}→{tier} "
                    f"score {total_score:.1f}"
                )

    # Step 6: Score vs Wyckoff confidence conflict
    # High score with low structure confidence = volume-driven, not confirmed
    wyckoff_confidence = regime.get("confidence", 0)
    score_conflict = False
    score_conflict_note = None
    if total_score >= 75 and wyckoff_confidence < 50:
        score_conflict = True
        score_conflict_note = (
            f"Score {total_score:.0f} driven by volume/stealth but Wyckoff "
            f"confidence only {wyckoff_confidence}% — structure not fully "
            f"confirmed, treat as ARM."
        )
        if tier == "FIRE":
            tier = "ARM"
            total_score = round(total_score * 0.88, 2)
            logger.info(
                f"Conflict downgrade: {symbol} {original_tier}→{tier} "
                f"score {total_score:.1f} confidence {wyckoff_confidence}%"
            )

    return {
        "total_score": total_score,
        "vol_score": vol_score,
        "accum_score": accum_score,
        "stealth_bonus": round(stealth_bonus, 2),
        "inst_bonus": round(inst_bonus, 2),
        "quiet_factor": quiet_factor,
        "tier": tier,
        "cef_warning": cef_warning,
        "cef_note": cef_note,
        "score_conflict": score_conflict,
        "score_conflict_note": score_conflict_note,
    }
