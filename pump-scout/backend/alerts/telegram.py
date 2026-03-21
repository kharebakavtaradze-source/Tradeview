"""
Telegram alert module for Pump Scout.
Uses Telegram Bot API directly via httpx — no extra library needed.
Env vars: TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
"""
import logging
import os
from datetime import datetime, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_last_sent: Optional[datetime] = None


def _get_config():
    return os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_CHAT_ID", "")


def is_configured() -> bool:
    token, chat_id = _get_config()
    return bool(token and chat_id)


async def send_message(text: str) -> bool:
    """POST a message to the configured Telegram chat. Returns True on success."""
    global _last_sent
    token, chat_id = _get_config()
    if not token or not chat_id:
        logger.warning("Telegram not configured — set TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={
                "chat_id": chat_id,
                "text": text,
                "parse_mode": "HTML",
            })
            resp.raise_for_status()
            _last_sent = datetime.now(timezone.utc)
            logger.info("Telegram alert sent")
            return True
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


def _format_alert(scan_result: dict) -> str:
    """Build the morning briefing message. Returns empty string if nothing worth sending."""
    results = scan_result.get("results", [])
    total = scan_result.get("total", len(results))
    ts = scan_result.get("scanned_at", "")
    try:
        time_str = datetime.fromisoformat(ts).strftime("%I:%M %p EST")
    except Exception:
        time_str = ts[:16] if ts else "now"

    # Group tiers (max 5 per tier)
    tiers: dict = {"FIRE": [], "ARM": [], "STEALTH": [], "SYMPATHY": []}
    for r in results:
        t = r.get("score", {}).get("tier", "")
        if t in tiers and len(tiers[t]) < 5:
            tiers[t].append(r)

    if not any(tiers[t] for t in ["FIRE", "ARM", "STEALTH"]):
        return ""

    ICONS = {"FIRE": "🔥", "ARM": "👁", "STEALTH": "🕵", "SYMPATHY": "🔗"}
    lines = [f"<b>🔍 PUMP SCOUT — {time_str}</b>\n"]

    for tier, icon in ICONS.items():
        if not tiers[tier]:
            continue
        lines.append(f"<b>{icon} {tier}:</b>")
        for r in tiers[tier]:
            sym = r["symbol"]
            price = r.get("price", 0)
            ind = r.get("indicators", {})
            score = r.get("score", {}).get("total_score", 0)
            sqz = ind.get("bb_sqz_bars", 0)
            vol = ind.get("anomaly_ratio", 0)
            stealth = ind.get("stealth", {})
            vol_ratio = stealth.get("vol_ratio", 0)
            price_chg = ind.get("price_change_pct", 0)

            if tier == "STEALTH":
                lines.append(
                    f"  <code>{sym}</code> ${price:.2f} | "
                    f"vol:{vol_ratio:.1f}x yest | price:{price_chg:+.1f}% | score:{score:.0f}"
                )
            elif sqz >= 3:
                lines.append(
                    f"  <code>{sym}</code> ${price:.2f} | sqz:{sqz}b | score:{score:.0f}"
                )
            else:
                lines.append(
                    f"  <code>{sym}</code> ${price:.2f} | vol:{vol:.1f}x | score:{score:.0f}"
                )
        lines.append("")

    # Perfect storm
    def _is_storm(r):
        conds = [
            r.get("indicators", {}).get("stealth", {}).get("is_stealth"),
            r.get("indicators", {}).get("institutional_flow", {}).get("is_institutional"),
            r.get("sympathy", {}).get("is_sympathy"),
            r.get("regime", {}).get("state") in ("ARM", "FIRE", "STEALTH_ARM"),
        ]
        return sum(bool(c) for c in conds) >= 2

    storm = [r["symbol"] for r in results if _is_storm(r)][:5]
    if storm:
        lines.append(f"⚡ <b>PERFECT STORM:</b> {', '.join(storm)}")

    lines.append(f"\n<i>Total scanned: {total} tickers</i>")
    return "\n".join(lines)


async def send_scan_alert(scan_result: dict) -> bool:
    """Send the post-scan briefing. Skips silently if nothing significant."""
    msg = _format_alert(scan_result)
    if not msg:
        logger.info("No FIRE/ARM/STEALTH — skipping Telegram alert")
        return False
    return await send_message(msg)


async def send_test_alert() -> bool:
    return await send_message(
        "✅ <b>Pump Scout connected!</b>\n"
        "Telegram alerts are configured correctly.\n"
        "You'll receive scan briefings after each scheduled scan."
    )


def get_status() -> dict:
    return {
        "configured": is_configured(),
        "last_sent": _last_sent.isoformat() if _last_sent else None,
    }
