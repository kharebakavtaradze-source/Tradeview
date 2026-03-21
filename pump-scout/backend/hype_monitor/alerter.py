"""
Hype Monitor — Telegram Alerter
Formats and sends hype divergence alerts with per-type cooldown deduplication.
"""
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

from alerts.telegram import send_message

logger = logging.getLogger(__name__)

# Cooldown per (ticker, divergence_type): datetime of last sent
_last_sent: dict[tuple[str, str], datetime] = {}

_COOLDOWNS = {
    "SILENT_VOLUME": timedelta(hours=2),
    "VELOCITY_SPIKE": timedelta(hours=1),
    "PEAK_FADING": timedelta(hours=3),
    "HYPE_NO_VOLUME": timedelta(hours=2),
}

_DEFAULT_COOLDOWN = timedelta(hours=2)


def _is_on_cooldown(ticker: str, div_type: str) -> bool:
    key = (ticker, div_type)
    last = _last_sent.get(key)
    if not last:
        return False
    cooldown = _COOLDOWNS.get(div_type, _DEFAULT_COOLDOWN)
    return datetime.now(timezone.utc) - last < cooldown


def _mark_sent(ticker: str, div_type: str):
    _last_sent[(ticker, div_type)] = datetime.now(timezone.utc)


def _format_hype_alert(
    ticker: str,
    hype_score: dict[str, Any],
    velocity: dict[str, Any],
    divergences: list[dict[str, Any]],
    scan_result: dict[str, Any],
    ai_analysis: dict[str, Any] | None = None,
) -> str:
    """Build an HTML-formatted Telegram message for a hype alert."""
    score = scan_result.get("score", {})
    indicators = scan_result.get("indicators", {})
    tier = score.get("tier", "WATCH")
    total_score = score.get("total_score", 0)
    price = scan_result.get("price", 0)
    price_chg = indicators.get("price_change_pct", 0)
    vol_ratio = indicators.get("anomaly_ratio", 0)
    hype_index = hype_score.get("hype_index", 0)
    hype_tier = hype_score.get("hype_tier", "COLD")
    counts = hype_score.get("mention_counts", {})
    vel_2h = velocity.get("combined_velocity_2h", 0)

    div_labels = " | ".join(d["label"] for d in divergences)

    lines = [
        f"<b>🔥 HYPE ALERT — {ticker}</b>",
        f"<b>{div_labels}</b>",
        f"",
        f"Tier: <b>{tier}</b> | Score: {total_score:.0f} | ${price:.2f} ({price_chg:+.1f}%)",
        f"Vol: {vol_ratio:.1f}x | Hype: <b>{hype_index:.0f}/100</b> ({hype_tier})",
        f"Mentions 24h: {counts.get('total', 0)} "
        f"(ST:{counts.get('stocktwits', 0)} / R:{counts.get('reddit', 0)} / N:{counts.get('news', 0)})",
        f"Velocity 2h: {vel_2h:.1f}x",
    ]

    for d in divergences:
        lines.append(f"")
        lines.append(f"<b>{d['label']}</b> [{d['severity']}]")
        lines.append(f"<i>{d['description']}</i>")

    if ai_analysis and ai_analysis.get("summary"):
        lines.append(f"")
        lines.append(f"🤖 <b>AI:</b> {ai_analysis['summary']}")
        rec = ai_analysis.get("recommendation", "")
        risk = ai_analysis.get("risk_level", "")
        if rec or risk:
            lines.append(f"→ {rec} | Risk: {risk}")

    return "\n".join(lines)


async def send_hype_alerts(
    ticker: str,
    hype_score: dict[str, Any],
    velocity: dict[str, Any],
    divergences: list[dict[str, Any]],
    scan_result: dict[str, Any],
    ai_analysis: dict[str, Any] | None = None,
) -> list[str]:
    """
    Send Telegram alerts for divergences not on cooldown.
    Returns list of divergence types that were alerted.
    """
    if not divergences:
        return []

    # Filter to non-cooldown HIGH/MEDIUM divergences
    to_alert = [
        d for d in divergences
        if not _is_on_cooldown(ticker, d["type"])
        and d.get("severity") in ("HIGH", "MEDIUM")
    ]

    if not to_alert:
        return []

    msg = _format_hype_alert(ticker, hype_score, velocity, to_alert, scan_result, ai_analysis)
    sent = await send_message(msg)

    alerted = []
    if sent:
        for d in to_alert:
            _mark_sent(ticker, d["type"])
            alerted.append(d["type"])
        logger.info(f"Hype alert sent for {ticker}: {alerted}")
    else:
        logger.warning(f"Hype alert send failed for {ticker}")

    return alerted


async def send_hype_summary(hype_results: list[dict[str, Any]]) -> bool:
    """
    Send a brief summary of all monitored tickers at the end of a cycle.
    Only sends if there are HOT/VIRAL tickers.
    """
    hot = [r for r in hype_results if r.get("hype_score", {}).get("hype_tier") in ("HOT", "VIRAL")]
    if not hot:
        return False

    lines = ["<b>📊 HYPE MONITOR SUMMARY</b>", ""]
    for r in sorted(hot, key=lambda x: -x.get("hype_score", {}).get("hype_index", 0))[:10]:
        ticker = r.get("ticker", "?")
        h = r.get("hype_score", {})
        divs = r.get("divergences", [])
        div_str = " · ".join(d["type"] for d in divs) if divs else "—"
        lines.append(
            f"<code>{ticker}</code> {h.get('hype_index', 0):.0f}/100 ({h.get('hype_tier', '')}) "
            f"| {div_str}"
        )

    return await send_message("\n".join(lines))
