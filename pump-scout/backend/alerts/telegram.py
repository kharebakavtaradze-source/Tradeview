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

# In-memory tier state for crossing detection {symbol: tier}
_prev_tiers: dict[str, str] = {}

TIER_RANK = {
    "PRIME_BUY":     5,
    "HIGH_CONF_BUY": 4,
    "BUY_WATCH":     3,
    "SETUP_MONITOR": 2,
    "SKIP":          1,
}

TIER_ICONS = {
    "PRIME_BUY":     "🔥",
    "HIGH_CONF_BUY": "⚡",
    "BUY_WATCH":     "👁",
    "SETUP_MONITOR": "📌",
    "SKIP":          "·",
}

READINESS_ICONS = {
    "HOT":  "🌡",
    "WARM": "♨",
    "COOL": "❄",
    "COLD": "🧊",
}


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
                "chat_id":    chat_id,
                "text":       text,
                "parse_mode": "HTML",
            })
            resp.raise_for_status()
            _last_sent = datetime.now(timezone.utc)
            logger.info("Telegram alert sent")
            return True
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False


# ── Demand composite formatter ────────────────────────────────────────────────

_FLOW_ABBREV = {
    "OBV_ACCUM":          "OBV↑",
    "LOWER_WICK_ABSORB":  "LW↑↑",
    "LOWER_WICK_PARTIAL": "LW↑",
}


def _fmt_row(r: dict) -> str:
    sym     = r.get("symbol", "?")
    price   = r.get("price") or 0.0
    score   = r.get("demand_composite_score") or 0
    ready_t = r.get("readiness_tier", "")
    ready_s = r.get("readiness_score") or 0
    ats     = r.get("ats_signal", "")
    conf    = r.get("confluence_signals") or []
    flow    = r.get("flow_signals") or []
    dryup   = r.get("dc_dryup_streak") or 0
    brk     = r.get("breakout_signal", "")

    parts = [f"  <code>{sym}</code> ${price:.2f}"]
    parts.append(f"score:{score:.0f}")
    if ready_t:
        parts.append(f"ready:{READINESS_ICONS.get(ready_t, '')}{ready_s}")
    if ats and ats != "NO_ATS":
        parts.append(f"ats:{ats.replace('ATS_', '')}")
    if conf:
        parts.append("+".join(
            c.replace("_NOW", "").replace("_RECENT", "~") for c in conf[:3]
        ))
    if flow:
        parts.append("+".join(_FLOW_ABBREV.get(s, s) for s in flow[:2]))
    if dryup:
        parts.append(f"dryup:{dryup}d")
    if brk and brk not in ("COILING", ""):
        parts.append(f"brk:{brk}")
    return " | ".join(parts)


def _format_demand_scan(scan_result: dict, new_prime: list, new_high: list) -> str:
    """Full scan briefing using demand composite tiers."""
    results  = scan_result.get("results", [])
    ts       = scan_result.get("scanned_at", "")
    total    = scan_result.get("total", len(results))
    try:
        time_str = datetime.fromisoformat(ts).strftime("%I:%M %p EST")
    except Exception:
        time_str = ts[:16] if ts else "now"

    prime = [r for r in results if r.get("demand_composite_tier") == "PRIME_BUY"][:6]
    high  = [r for r in results if r.get("demand_composite_tier") == "HIGH_CONF_BUY"][:4]

    if not prime and not high:
        return ""

    lines = [f"<b>📡 DEMAND SCAN — {time_str}</b>"]

    if prime:
        lines.append(f"\n<b>🔥 PRIME BUY ({len(prime)}):</b>")
        for r in prime:
            new_tag = " <b>NEW</b>" if r.get("symbol") in new_prime else ""
            lines.append(_fmt_row(r) + new_tag)

    if high:
        lines.append(f"\n<b>⚡ HIGH CONF BUY ({len(high)}):</b>")
        for r in high:
            new_tag = " <b>NEW</b>" if r.get("symbol") in new_high else ""
            lines.append(_fmt_row(r) + new_tag)

    lines.append(f"\n<i>Universe: {total} tickers</i>")
    return "\n".join(lines)


def _format_crossings(new_prime: list[dict], new_high: list[dict]) -> str:
    """Compact alert for NEW tier crossings — sent as a separate urgent message."""
    if not new_prime and not new_high:
        return ""
    lines = ["<b>🚨 NEW SIGNALS</b>"]
    for r in new_prime:
        lines.append(_fmt_row(r) + "  ← <b>PRIME_BUY</b>")
    for r in new_high:
        lines.append(_fmt_row(r) + "  ← <b>HIGH_CONF</b>")
    return "\n".join(lines)


async def send_scan_alert(scan_result: dict) -> bool:
    """
    Send post-scan Telegram briefing using demand composite tiers.
    Detects NEW crossings into PRIME_BUY / HIGH_CONF_BUY vs previous scan
    and sends a crossing alert first, then the full briefing.
    """
    global _prev_tiers

    results = scan_result.get("results", [])

    # Compute crossings vs previous scan
    new_prime_rows: list[dict] = []
    new_high_rows:  list[dict] = []
    cur_tiers: dict[str, str] = {}
    for r in results:
        sym  = r.get("symbol", "")
        tier = r.get("demand_composite_tier", "SKIP")
        cur_tiers[sym] = tier
        prev = _prev_tiers.get(sym, "SKIP")
        if tier == "PRIME_BUY" and TIER_RANK.get(prev, 0) < TIER_RANK["PRIME_BUY"]:
            new_prime_rows.append(r)
        elif tier == "HIGH_CONF_BUY" and TIER_RANK.get(prev, 0) < TIER_RANK["HIGH_CONF_BUY"]:
            new_high_rows.append(r)

    _prev_tiers = cur_tiers

    new_prime_syms = [r.get("symbol") for r in new_prime_rows]
    new_high_syms  = [r.get("symbol") for r in new_high_rows]

    sent = False

    # Crossing alert first (time-sensitive)
    crossing_msg = _format_crossings(new_prime_rows, new_high_rows)
    if crossing_msg:
        await send_message(crossing_msg)
        sent = True

    # Full scan briefing
    scan_msg = _format_demand_scan(scan_result, new_prime_syms, new_high_syms)
    if scan_msg:
        await send_message(scan_msg)
        sent = True

    if not sent:
        logger.info("No PRIME/HIGH signals — skipping Telegram alert")
    return sent


async def send_test_alert() -> bool:
    return await send_message(
        "✅ <b>Pump Scout connected!</b>\n"
        "Telegram alerts are configured correctly.\n"
        "You'll receive scan briefings after each scheduled scan.\n\n"
        "<i>Format: symbol | score | readiness | ats | confluence | dryup | breakout</i>"
    )


def get_status() -> dict:
    return {
        "configured":      is_configured(),
        "last_sent":       _last_sent.isoformat() if _last_sent else None,
        "tracked_symbols": len(_prev_tiers),
    }


# ── Legacy stub ───────────────────────────────────────────────────────────────

_alert_history: list[dict] = []

def get_alert_history() -> list[dict]:
    return _alert_history
