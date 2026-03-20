"""
Scoring engine: combines indicator data + Wyckoff regime into a composite score.
"""


def score_ticker(indicators: dict, regime: dict) -> dict:
    anomaly_ratio = indicators.get("anomaly_ratio", 0)
    cmf_pctl = indicators.get("cmf_pctl", 0)
    cmf_val = indicators.get("cmf", 0)
    sqz_bars = indicators.get("bb_sqz_bars", 0)
    in_acc = regime.get("in_acc", False)
    price_change_pct = abs(indicators.get("price_change_pct", 0))
    state = regime.get("state", "NONE")

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

    # --- Quiet Factor (multiplier) ---
    if price_change_pct < 1.0 and anomaly_ratio > 3.0:
        quiet_factor = 1.5
    elif price_change_pct < 3.0 and anomaly_ratio > 2.0:
        quiet_factor = 1.2
    else:
        quiet_factor = 1.0

    # --- Composite Score ---
    total_score = (vol_score * 0.5 + accum_score * 0.5) * quiet_factor
    total_score = round(min(total_score, 100), 2)

    # --- Tier ---
    # State from regime overrides tier for FIRE/ARM
    if state == "FIRE" or total_score > 80:
        tier = "FIRE"
    elif state == "ARM" or total_score > 60:
        tier = "ARM"
    elif state == "BASE" or total_score > 40:
        tier = "BASE"
    elif total_score > 25:
        tier = "WATCH"
    else:
        tier = "SKIP"

    return {
        "total_score": total_score,
        "vol_score": vol_score,
        "accum_score": accum_score,
        "quiet_factor": quiet_factor,
        "tier": tier,
    }
