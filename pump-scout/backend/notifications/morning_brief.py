"""
Morning brief — sends a Telegram summary at 09:00 ET with:
- Market regime + recommendation
- FIRE/ARM scan signals
- Open journal positions with stop-proximity warnings
- AI portfolio state
- Top 2 sectors by strength
"""
import logging
from datetime import date

logger = logging.getLogger(__name__)

_REGIME_EMOJI = {
    "RISK_ON": "🟢",
    "NEUTRAL": "🟡",
    "RISK_OFF": "🔴",
    "FEAR": "💀",
    "ROTATION_ENERGY": "⛽",
    "ROTATION_DEFENSIVE": "🏥",
}


async def send_morning_brief() -> bool:
    """Build and send the morning brief to Telegram. Returns True if sent."""
    from alerts.telegram import send_message, is_configured

    if not is_configured():
        logger.info("Morning brief skipped — Telegram not configured")
        return False

    lines = ["<b>☀️ PUMP SCOUT — MORNING BRIEF</b>", ""]

    # ── 1. Market Regime ──────────────────────────────────────────────────────
    try:
        from database import get_market_regime_latest
        regime = await get_market_regime_latest()
        if regime:
            emoji = _REGIME_EMOJI.get(regime.get("regime", ""), "⚪")
            rec = regime.get("recommendation", "")
            spy = regime.get("spy_pct", 0) or 0
            qqq = regime.get("qqq_pct", 0) or 0
            lines.append(
                f"{emoji} <b>Режим:</b> {regime.get('regime', 'UNKNOWN')} "
                f"| SPY {spy:+.1f}% QQQ {qqq:+.1f}%"
            )
            if rec:
                lines.append(f"<i>{rec}</i>")
            lines.append("")
    except Exception as e:
        logger.warning(f"morning_brief: regime lookup failed: {e}")

    # ── 2. FIRE / ARM signals from latest scan ────────────────────────────────
    try:
        from database import get_latest_scan
        scan = await get_latest_scan()
        if scan:
            results = scan.get("results", [])
            fire = [r for r in results if r.get("score", {}).get("tier") == "FIRE"][:5]
            arm  = [r for r in results if r.get("score", {}).get("tier") == "ARM"][:5]

            if fire:
                lines.append("<b>🔥 FIRE:</b>")
                for r in fire:
                    sym = r["symbol"]
                    price = r.get("price", 0)
                    score = r.get("score", {}).get("total_score", 0)
                    vol = r.get("indicators", {}).get("anomaly_ratio", 0)
                    cmf = r.get("indicators", {}).get("cmf_pctl", 0)
                    lines.append(
                        f"  <code>{sym}</code> ${price:.2f} | "
                        f"vol:{vol:.1f}x | cmf:{cmf:.0f}%ile | score:{score:.0f}"
                    )
                lines.append("")

            if arm:
                lines.append("<b>👁 ARM:</b>")
                for r in arm:
                    sym = r["symbol"]
                    price = r.get("price", 0)
                    score = r.get("score", {}).get("total_score", 0)
                    vol = r.get("indicators", {}).get("anomaly_ratio", 0)
                    cmf = r.get("indicators", {}).get("cmf_pctl", 0)
                    lines.append(
                        f"  <code>{sym}</code> ${price:.2f} | "
                        f"vol:{vol:.1f}x | cmf:{cmf:.0f}%ile | score:{score:.0f}"
                    )
                lines.append("")
    except Exception as e:
        logger.warning(f"morning_brief: scan lookup failed: {e}")

    # ── 3. Open journal positions with stop/target proximity warnings ─────────
    try:
        from database import get_open_journal_entries
        positions = await get_open_journal_entries()
        if positions:
            lines.append("<b>📔 ОТКРЫТЫЕ ПОЗИЦИИ:</b>")
            for p in positions:
                sym = p.get("symbol", "?")
                entry = p.get("entry_price", 0) or 0
                stop = p.get("stop_loss")
                target = p.get("target_price")
                curr = p.get("current_price") or entry
                curr_pct = p.get("current_pct") or 0

                line = (
                    f"  <code>{sym}</code> entry:{entry:.2f} "
                    f"now:{curr:.2f} ({curr_pct:+.1f}%)"
                )

                if stop and curr > 0:
                    dist_to_stop = (curr - stop) / curr * 100
                    if dist_to_stop <= 2:
                        line += f" 🚨 СТОП {dist_to_stop:.1f}%!"
                    elif dist_to_stop <= 5:
                        line += f" ⚠ стоп {dist_to_stop:.1f}%"

                if target and curr > 0 and curr < target:
                    dist_to_target = (target - curr) / curr * 100
                    if dist_to_target <= 3:
                        line += f" 🎯 ЦЕЛЬ {dist_to_target:.1f}%!"

                lines.append(line)
            lines.append("")
    except Exception as e:
        logger.warning(f"morning_brief: journal lookup failed: {e}")

    # ── 4. AI Portfolio state ─────────────────────────────────────────────────
    try:
        from database import get_portfolio_state
        state = await get_portfolio_state()
        if state:
            total = state.get("total_value", 1000)
            cash = state.get("cash", 1000)
            pnl = state.get("total_pnl_pct", 0) or 0
            sign = "+" if pnl >= 0 else ""
            lines.append(
                f"<b>🤖 AI ПОРТФЕЛЬ:</b> ${total:.0f} | "
                f"кэш ${cash:.0f} | PnL {sign}{pnl:.1f}%"
            )
            lines.append("")
    except Exception as e:
        logger.warning(f"morning_brief: ai portfolio lookup failed: {e}")

    # ── 5. Top 2 sectors by strength ──────────────────────────────────────────
    try:
        from database import get_sector_strength_latest
        sectors_data = await get_sector_strength_latest()
        if sectors_data:
            sectors_list = sorted(
                sectors_data.values(),
                key=lambda x: x.get("avg_score", 0),
                reverse=True,
            )
            top2 = sectors_list[:2]
            if top2:
                sectors_str = "  ".join(
                    f"{s['sector']} ({s.get('avg_score', 0):.0f})" for s in top2
                )
                lines.append(f"<b>📊 Сильные секторы:</b> {sectors_str}")
                lines.append("")
    except Exception as e:
        logger.warning(f"morning_brief: sector lookup failed: {e}")

    lines.append(f"<i>Удачного дня! 🎯 {date.today().isoformat()}</i>")

    msg = "\n".join(lines)
    ok = await send_message(msg)
    if ok:
        logger.info("Morning brief sent to Telegram")
    return ok
