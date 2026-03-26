"""
Pattern streak tracker — detects when a ticker appears with strong signals
across multiple consecutive scans.

Telegram alerts fire on day 3 and day 5 for ARM+ tiers.
"""
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

_TIER_RANK = {
    "SKIP": 0, "WATCH": 1, "STEALTH": 2, "SYMPATHY": 3,
    "BASE": 3, "ARM": 4, "FIRE": 5,
}

# Only track tickers at ARM or higher
_MIN_TIER_RANK = 4

# Telegram alert milestones (days)
_ALERT_MILESTONES = {3, 5}


async def update_pattern_streaks(results: list) -> None:
    """
    Called after every scan with the full results list.
    Updates the pattern_streaks table and sends Telegram alerts at day 3 / day 5.
    """
    from database import get_session_factory, PatternStreak
    from sqlalchemy import select
    from alerts.telegram import send_message, is_configured

    if not results:
        return

    today = date.today()
    yesterday = today - timedelta(days=1)

    # Build lookup from scan results
    tracked = [
        r for r in results
        if _TIER_RANK.get(r.get("score", {}).get("tier", "SKIP"), 0) >= _MIN_TIER_RANK
    ]
    tracked_symbols = {r["symbol"] for r in tracked}
    result_by_symbol = {r["symbol"]: r for r in tracked}

    try:
        async with get_session_factory()() as session:

            # ── 1. Update / create streaks for tickers in today's scan ────────
            for sym, r in result_by_symbol.items():
                tier = r.get("score", {}).get("tier", "WATCH")
                score = r.get("score", {}).get("total_score", 0) or 0
                ind = r.get("indicators", {})
                cmf = ind.get("cmf_pctl", 0) or 0
                vol = ind.get("anomaly_ratio", 0) or 0
                hype_val = ind.get("hype", 0)
                hype = int(hype_val) if isinstance(hype_val, (int, float)) else 0
                wyckoff = r.get("regime", {}).get("state", "NONE")

                result_row = await session.execute(
                    select(PatternStreak).where(PatternStreak.symbol == sym)
                )
                streak = result_row.scalar_one_or_none()

                if streak is None:
                    streak = PatternStreak(
                        symbol=sym,
                        streak_start=today,
                        streak_days=1,
                        avg_score=score,
                        avg_cmf_pctl=cmf,
                        avg_vol_ratio=vol,
                        avg_hype=hype,
                        tier=tier,
                        wyckoff=wyckoff,
                        last_seen=today,
                        alerted=0,
                    )
                    session.add(streak)
                else:
                    gap = (today - streak.last_seen).days if streak.last_seen else 999

                    if gap <= 1:
                        # Consecutive — extend streak with rolling average
                        n = streak.streak_days
                        streak.streak_days = n + 1
                        streak.avg_score = (streak.avg_score * n + score) / (n + 1)
                        streak.avg_cmf_pctl = (streak.avg_cmf_pctl * n + cmf) / (n + 1)
                        streak.avg_vol_ratio = (streak.avg_vol_ratio * n + vol) / (n + 1)
                        streak.tier = tier
                        streak.wyckoff = wyckoff
                        streak.last_seen = today
                    else:
                        # Gap in appearances — reset streak
                        streak.streak_start = today
                        streak.streak_days = 1
                        streak.avg_score = score
                        streak.avg_cmf_pctl = cmf
                        streak.avg_vol_ratio = vol
                        streak.avg_hype = hype
                        streak.tier = tier
                        streak.wyckoff = wyckoff
                        streak.last_seen = today
                        streak.alerted = 0

            # ── 2. Mark stale streaks (not seen in 2+ days) ──────────────────
            stale_result = await session.execute(
                select(PatternStreak).where(PatternStreak.last_seen < yesterday)
            )
            for s in stale_result.scalars().all():
                if (today - s.last_seen).days >= 2:
                    s.streak_days = 0  # broken

            await session.commit()

            # ── 3. Send Telegram alerts for milestone days ───────────────────
            if not is_configured():
                return

            for milestone in _ALERT_MILESTONES:
                alert_result = await session.execute(
                    select(PatternStreak).where(
                        PatternStreak.streak_days == milestone,
                        PatternStreak.last_seen == today,
                    )
                )
                for streak in alert_result.scalars().all():
                    # alerted bitmask: bit 0 = day 3 alerted, bit 1 = day 5 alerted
                    bit = 0 if milestone == 3 else 1
                    if (streak.alerted >> bit) & 1:
                        continue  # already alerted for this milestone

                    msg = (
                        f"📈 <b>STREAK ALERT — {streak.symbol}</b>\n"
                        f"День {streak.streak_days} подряд! Tier: {streak.tier}\n"
                        f"  Avg Score: {streak.avg_score:.0f} | "
                        f"CMF: {streak.avg_cmf_pctl:.0f}%ile\n"
                        f"  Vol: {streak.avg_vol_ratio:.1f}x | "
                        f"Wyckoff: {streak.wyckoff}\n"
                        f"  Стрик с: {streak.streak_start}"
                    )
                    ok = await send_message(msg)
                    if ok:
                        streak.alerted = streak.alerted | (1 << bit)

            await session.commit()

    except Exception as e:
        logger.error(f"update_pattern_streaks failed: {e}", exc_info=True)
