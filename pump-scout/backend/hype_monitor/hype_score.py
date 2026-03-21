"""
Hype Monitor — Hype Score Calculator
Converts mention counts and velocity into a 0–100 hype index.
"""
from typing import Any


# Mention count → base score mapping (24h window)
_COUNT_SCORE_TABLE = [
    (0, 0),
    (3, 10),
    (7, 20),
    (15, 35),
    (30, 50),
    (60, 65),
    (100, 80),
    (200, 90),
    (400, 100),
]


def _count_to_score(count: int) -> float:
    """Interpolate count into 0–100 score using the table."""
    if count <= 0:
        return 0.0
    for i, (threshold, score) in enumerate(_COUNT_SCORE_TABLE):
        if count <= threshold:
            if i == 0:
                return 0.0
            prev_t, prev_s = _COUNT_SCORE_TABLE[i - 1]
            frac = (count - prev_t) / max(threshold - prev_t, 1)
            return prev_s + frac * (score - prev_s)
    return 100.0


def _sentiment_bonus(mentions: list[dict]) -> float:
    """
    Returns a sentiment adjustment -10 to +10 based on bullish/bearish ratio
    in StockTwits messages that have explicit sentiment.
    """
    bull = sum(1 for m in mentions if m.get("sentiment") == "BULLISH")
    bear = sum(1 for m in mentions if m.get("sentiment") == "BEARISH")
    total = bull + bear
    if total < 3:
        return 0.0
    ratio = (bull - bear) / total  # -1 to +1
    return round(ratio * 10, 1)


def _velocity_bonus(velocity_2h: float) -> float:
    """Bonus points for acceleration: up to +15."""
    if velocity_2h <= 1.0:
        return 0.0
    if velocity_2h <= 2.0:
        return 5.0
    if velocity_2h <= 4.0:
        return 10.0
    return 15.0


def calc_hype_score(raw_data: dict[str, Any], velocity: dict[str, Any]) -> dict[str, Any]:
    """
    Calculate hype_index (0–100) and sub-scores.
    Uses weighted news count (SEC=1.5x, real=1.0x, unknown=0.7x, PR=0.5x).
    """
    by_source = raw_data.get("by_source", {})
    news_detail = raw_data.get("news_detail", {})

    twits_24h = velocity.get("by_source", {}).get("stocktwits", {}).get("count_24h", 0)
    reddit_24h = velocity.get("by_source", {}).get("reddit", {}).get("count_24h", 0)
    total_24h = velocity.get("count_24h", 0)

    # Use weighted news count (honours SEC/PR/real classification)
    news_weighted = news_detail.get("weighted_count", 0.0)
    # If no news_detail yet (old data path), fall back to raw count
    if news_weighted == 0.0:
        news_weighted = velocity.get("by_source", {}).get("news", {}).get("count_24h", 0)

    # Per-source base scores
    twits_score = _count_to_score(twits_24h) * 0.40
    reddit_score = _count_to_score(reddit_24h) * 0.30
    news_score = _count_to_score(news_weighted) * 0.30
    base_score = round(twits_score + reddit_score + news_score, 1)

    vel_bonus = _velocity_bonus(velocity.get("combined_velocity_2h", 0))
    sent_bonus = _sentiment_bonus(by_source.get("stocktwits", []))

    # SEC filing boost — official disclosure = something is happening
    sec_boost = 5.0 if news_detail.get("has_sec_filing") else 0.0

    raw_index = base_score + vel_bonus + sent_bonus + sec_boost
    hype_index = max(0, min(100, round(raw_index, 1)))

    if hype_index >= 75:
        tier = "VIRAL"
    elif hype_index >= 50:
        tier = "HOT"
    elif hype_index >= 25:
        tier = "WARM"
    else:
        tier = "COLD"

    return {
        "hype_index": hype_index,
        "base_score": base_score,
        "velocity_bonus": vel_bonus,
        "sentiment_bonus": sent_bonus,
        "sec_boost": sec_boost,
        "mention_counts": {
            "total": total_24h,
            "stocktwits": twits_24h,
            "reddit": reddit_24h,
            "news_raw": news_detail.get("total_count_24h", 0),
            "news_2_7d": news_detail.get("count_2_7d", 0),
            "news_weighted": round(news_weighted, 1),
        },
        "hype_tier": tier,
    }
