"""
Price alert monitor — runs every 30 min during market hours (9:30–16:00 ET).

Alert thresholds:
  CRITICAL  — price within 2% of stop loss
  WARNING   — price within 5% of stop loss
  TARGET    — price within 3% of target price

4-hour cooldown per symbol to avoid spam.
"""
import logging
import time

import httpx

logger = logging.getLogger(__name__)

# In-memory cooldown: {symbol: last_alerted_unix_timestamp}
ALERT_COOLDOWN: dict = {}
_COOLDOWN_SECS = 4 * 3600  # 4 hours

_YAHOO_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.5",
}


async def _fetch_price(symbol: str) -> float | None:
    """Fetch the latest closing price for a symbol from Yahoo Finance."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol.upper()}"
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=_YAHOO_HEADERS) as client:
            resp = await client.get(url, params={"interval": "1d", "range": "5d"})
            if resp.status_code != 200:
                return None
            data = resp.json()
            closes = (
                data.get("chart", {})
                .get("result", [{}])[0]
                .get("indicators", {})
                .get("quote", [{}])[0]
                .get("close", [])
            )
            closes = [c for c in closes if c is not None]
            return float(closes[-1]) if closes else None
    except Exception as e:
        logger.warning(f"_fetch_price {symbol}: {e}")
        return None


async def check_price_alerts() -> dict:
    """
    Check all open journal positions for stop/target proximity.
    Returns a summary dict for logging.
    """
    from alerts.telegram import send_message, is_configured
    from database import get_open_journal_entries

    now = time.time()
    sent = 0
    checked = 0

    try:
        positions = await get_open_journal_entries()
    except Exception as e:
        logger.error(f"check_price_alerts: DB lookup failed: {e}")
        return {"checked": 0, "sent": 0, "error": str(e)}

    # Only care about positions that have a stop or target set
    actionable = [
        p for p in positions
        if p.get("stop_loss") or p.get("target_price")
    ]

    if not actionable:
        logger.info("Price alerts: no open positions with stop/target — skip")
        return {"checked": 0, "sent": 0}

    if not is_configured():
        logger.info("Price alerts: Telegram not configured — skip")
        return {"checked": 0, "sent": 0}

    for p in actionable:
        sym = p.get("symbol", "?")
        entry = p.get("entry_price", 0) or 0
        stop = p.get("stop_loss")
        target = p.get("target_price")

        # Respect cooldown
        last_alerted = ALERT_COOLDOWN.get(sym, 0)
        if now - last_alerted < _COOLDOWN_SECS:
            continue

        price = await _fetch_price(sym)
        if price is None:
            continue

        checked += 1
        alerts = []

        if stop:
            dist_to_stop = (price - stop) / price * 100
            if dist_to_stop <= 2:
                alerts.append(
                    f"🚨 <b>CRITICAL — {sym}</b> близко к СТОПУ!\n"
                    f"  Цена: <b>${price:.2f}</b> | Стоп: ${stop:.2f} | "
                    f"Осталось {dist_to_stop:.1f}%\n"
                    f"  Entry: ${entry:.2f}"
                )
            elif dist_to_stop <= 5:
                alerts.append(
                    f"⚠️ <b>WARNING — {sym}</b> приближается к стопу\n"
                    f"  Цена: <b>${price:.2f}</b> | Стоп: ${stop:.2f} | "
                    f"Осталось {dist_to_stop:.1f}%"
                )

        if target and price < target:
            dist_to_target = (target - price) / price * 100
            if dist_to_target <= 3:
                alerts.append(
                    f"🎯 <b>TARGET — {sym}</b> близко к цели!\n"
                    f"  Цена: <b>${price:.2f}</b> | Цель: ${target:.2f} | "
                    f"Осталось {dist_to_target:.1f}%"
                )

        if alerts:
            msg = "\n\n".join(alerts)
            ok = await send_message(msg)
            if ok:
                ALERT_COOLDOWN[sym] = now
                sent += 1
                logger.info(f"Price alert sent for {sym}")

    logger.info(f"Price alerts: checked {checked} positions, sent {sent} alerts")
    return {"checked": checked, "sent": sent}
