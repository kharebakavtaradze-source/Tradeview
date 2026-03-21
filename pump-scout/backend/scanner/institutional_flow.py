"""
Institutional Flow Tracker.
Institutions can't buy millions of shares in one day — they spread
purchases over multiple days, leaving a trail of above-average volume
with quiet price action (they don't want to tip off the market).
"""


def calc_institutional_flow(candles: list) -> dict:
    """
    Detects consecutive days of above-average volume with quiet price moves.
    Streak breaks on the first non-qualifying day (looking back from today).
    """
    if len(candles) < 10:
        return {"is_institutional": False, "flow_score": 0, "days": 0, "flow_days": []}

    avg_vol_20 = sum(c["v"] for c in candles[-21:-1]) / 20

    flow_days = []
    for i in range(1, min(11, len(candles))):
        bar = candles[-i]
        prev = candles[-i - 1] if i + 1 < len(candles) else bar

        vol_ratio = bar["v"] / avg_vol_20 if avg_vol_20 > 0 else 0
        price_change = (
            abs(bar["c"] - prev["c"]) / prev["c"] * 100 if prev["c"] > 0 else 0
        )
        bar_range = bar["h"] - bar["l"]
        close_pos = (bar["c"] - bar["l"]) / bar_range if bar_range > 0 else 0.5

        is_flow_day = (
            vol_ratio >= 1.3       # volume above average
            and price_change < 5.0  # price not exploding
            and close_pos >= 0.4    # closed in upper 60% of range (subtle bullish)
        )

        if is_flow_day:
            flow_days.append({
                "days_ago": i,
                "vol_ratio": round(vol_ratio, 2),
                "price_change": round(price_change, 2),
                "close_pos": round(close_pos, 2),
            })
        else:
            break  # streak must be consecutive

    consecutive_days = len(flow_days)

    if consecutive_days < 2:
        return {
            "is_institutional": False,
            "flow_score": 0,
            "days": consecutive_days,
            "flow_days": flow_days,
        }

    # --- Score ---
    flow_score = 0

    if consecutive_days >= 7:
        flow_score += 50
    elif consecutive_days >= 5:
        flow_score += 40
    elif consecutive_days >= 3:
        flow_score += 25
    else:
        flow_score += 10

    avg_flow_vol = sum(d["vol_ratio"] for d in flow_days) / len(flow_days)
    if avg_flow_vol >= 3.0:
        flow_score += 30
    elif avg_flow_vol >= 2.0:
        flow_score += 20
    elif avg_flow_vol >= 1.5:
        flow_score += 10

    # Consistency bonus: all days closed higher than previous
    all_positive = all(
        candles[-i]["c"] >= candles[-i - 1]["c"]
        for i in range(1, consecutive_days + 1)
        if i + 1 < len(candles)
    )
    if all_positive:
        flow_score += 20

    # Acceleration bonus: today's vol ratio > oldest day in streak
    vols = [d["vol_ratio"] for d in flow_days]
    if len(vols) >= 2 and vols[0] > vols[-1]:
        flow_score += 10

    flow_score = min(flow_score, 100)

    if consecutive_days >= 5 and flow_score >= 70:
        strength = "STRONG"
    elif consecutive_days >= 3 and flow_score >= 50:
        strength = "MEDIUM"
    else:
        strength = "EARLY"

    return {
        "is_institutional": True,
        "flow_score": flow_score,
        "days": consecutive_days,
        "avg_vol_ratio": round(avg_flow_vol, 2),
        "strength": strength,
        "flow_days": flow_days,
        "interpretation": (
            f"{consecutive_days} days of quiet accumulation — "
            f"institutional buying in progress"
        ),
    }
