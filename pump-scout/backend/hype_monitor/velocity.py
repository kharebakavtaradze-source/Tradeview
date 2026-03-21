"""
Hype Monitor — Velocity Calculator
Measures the acceleration of social mentions over time windows.
"""
from datetime import datetime, timezone, timedelta
from typing import Any


def _count_in_window(mentions: list[dict], hours: float) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    return sum(1 for m in mentions if m.get("ts") and m["ts"] >= cutoff)


def _velocity_ratio(count_short: int, count_long: int, short_hours: float, long_hours: float) -> float:
    """
    Velocity = short-window rate / long-window baseline rate.
    e.g. 2h rate vs 24h average rate.
    Returns 0 if no data.
    """
    if count_long == 0:
        return 0.0
    short_rate = count_short / max(short_hours, 0.1)
    long_rate = count_long / max(long_hours, 0.1)
    if long_rate == 0:
        return 0.0
    return round(short_rate / long_rate, 2)


def calc_velocity(raw_data: dict[str, Any]) -> dict[str, Any]:
    """
    Calculate velocity metrics from fetched social data.

    Returns:
        velocity_2h  - 2h rate vs 24h baseline (acceleration)
        velocity_6h  - 6h rate vs 24h baseline
        count_2h, count_6h, count_24h  - raw counts
        by_source    - per-source velocities
        combined     - weighted combined velocity (twits 40%, reddit 30%, news 30%)
    """
    by_source = raw_data.get("by_source", {})
    twits = by_source.get("stocktwits", [])
    reddit = by_source.get("reddit", [])
    news = by_source.get("news", [])
    all_mentions = raw_data.get("mentions", [])

    # Overall counts
    count_2h = _count_in_window(all_mentions, 2)
    count_6h = _count_in_window(all_mentions, 6)
    count_24h = _count_in_window(all_mentions, 24)

    vel_2h = _velocity_ratio(count_2h, count_24h, 2, 24)
    vel_6h = _velocity_ratio(count_6h, count_24h, 6, 24)

    # Per-source velocities
    def source_velocity(source_list: list) -> dict:
        c2 = _count_in_window(source_list, 2)
        c6 = _count_in_window(source_list, 6)
        c24 = _count_in_window(source_list, 24)
        return {
            "count_2h": c2,
            "count_6h": c6,
            "count_24h": c24,
            "velocity_2h": _velocity_ratio(c2, c24, 2, 24),
            "velocity_6h": _velocity_ratio(c6, c24, 6, 24),
        }

    twits_v = source_velocity(twits)
    reddit_v = source_velocity(reddit)
    news_v = source_velocity(news)

    # Weighted combined velocity (2h)
    combined_vel_2h = (
        twits_v["velocity_2h"] * 0.4
        + reddit_v["velocity_2h"] * 0.3
        + news_v["velocity_2h"] * 0.3
    )

    return {
        "count_2h": count_2h,
        "count_6h": count_6h,
        "count_24h": count_24h,
        "velocity_2h": vel_2h,
        "velocity_6h": vel_6h,
        "combined_velocity_2h": round(combined_vel_2h, 2),
        "by_source": {
            "stocktwits": twits_v,
            "reddit": reddit_v,
            "news": news_v,
        },
    }
