"""
Scoring engine: combines indicator data + Wyckoff regime into a composite score.
"""


def score_ticker(indicators: dict, regime: dict) -> dict:
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

    # --- Composite Score ---
    total_score = (vol_score * 0.4 + accum_score * 0.3 + stealth_bonus * 0.3) * quiet_factor

    # Stealth floor: stealth signal always at least WATCH
    if stealth.get("is_stealth") and total_score < 25:
        total_score = 25

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
    elif vol_ratio >= 2.0 and -7.0 <= price_change_pct_signed <= 7.0:
        tier = "GOGA"
    else:
        tier = "SKIP"

    # Step 2: Wyckoff state can upgrade tier but never downgrade
    _TIER_RANK = {"SKIP": 0, "GOGA": 1, "WATCH": 2, "STEALTH": 3, "BASE": 4, "ARM": 5, "FIRE": 6}
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

    return {
        "total_score": total_score,
        "vol_score": vol_score,
        "accum_score": accum_score,
        "stealth_bonus": round(stealth_bonus, 2),
        "quiet_factor": quiet_factor,
        "tier": tier,
    }
