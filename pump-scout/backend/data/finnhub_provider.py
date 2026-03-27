"""
Finnhub data provider — earnings calendar only.

Design: fetch the full earnings calendar in one API call, build a symbol→info
dict, and let the rest of the system look up individual symbols from that dict.
This avoids per-ticker API calls during the scan (which would hit rate limits
with 800+ symbols).

Requires: FINNHUB_API_KEY env var (free key at finnhub.io)
If the key is not set, all functions return empty results silently.

Rate limit (free tier): 60 requests/minute — one batch call per scan is fine.
Cache TTL: 4 hours (earnings dates don't change intraday).
"""
import logging
import os
import time
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

_FINNHUB_BASE = "https://finnhub.io/api/v1"
_EARNINGS_CACHE_TTL = 4 * 3600  # 4 hours

# In-memory cache: {key: (data, timestamp)}
_cache: dict = {}


def is_configured() -> bool:
    return bool(os.getenv("FINNHUB_API_KEY", ""))


def _get_cached(key: str):
    entry = _cache.get(key)
    if entry:
        data, ts = entry
        if time.time() - ts < _EARNINGS_CACHE_TTL:
            return data
    return None


def _set_cached(key: str, data):
    _cache[key] = (data, time.time())


async def _get(endpoint: str, params: dict) -> Optional[dict]:
    """Single authenticated GET to Finnhub. Returns parsed JSON or None."""
    api_key = os.getenv("FINNHUB_API_KEY", "")
    if not api_key:
        return None
    params["token"] = api_key
    url = f"{_FINNHUB_BASE}/{endpoint}"
    try:
        async with httpx.AsyncClient(timeout=12.0) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 429:
                logger.warning("Finnhub rate limit — retry later")
                return None
            if resp.status_code != 200:
                logger.warning(f"Finnhub {endpoint} → HTTP {resp.status_code}")
                return None
            return resp.json()
    except Exception as e:
        logger.warning(f"Finnhub request failed ({endpoint}): {e}")
        return None


async def get_earnings_calendar(days_ahead: int = 14) -> dict:
    """
    Fetch upcoming earnings for ALL symbols in one API call.
    Returns {SYMBOL: earnings_info_dict} — upper-case keys.

    Callers look up a single symbol: calendar.get("AAPL", {})
    One call covers every ticker — no per-symbol requests needed.
    Cached 4 hours.
    """
    cache_key = f"earnings_calendar_{date.today()}_{days_ahead}"
    cached = _get_cached(cache_key)
    if cached is not None:
        return cached

    if not is_configured():
        logger.info("FINNHUB_API_KEY not set — earnings calendar skipped")
        return {}

    today = date.today()
    end_date = today + timedelta(days=days_ahead)

    data = await _get("calendar/earnings", {
        "from": today.strftime("%Y-%m-%d"),
        "to":   end_date.strftime("%Y-%m-%d"),
    })

    if not data or "earningsCalendar" not in data:
        logger.warning("Finnhub earnings calendar returned no data")
        return {}

    result: dict = {}
    for e in data["earningsCalendar"]:
        sym = (e.get("symbol") or "").upper()
        if not sym:
            continue
        try:
            earnings_date = datetime.strptime(e["date"], "%Y-%m-%d").date()
        except (KeyError, ValueError):
            continue

        days_until = (earnings_date - today).days
        hour = e.get("hour", "amc")  # bmo = before market open, amc = after close

        result[sym] = {
            "has_earnings": True,
            "date": e["date"],
            "days_until": days_until,
            "hour": hour,
            "hour_label": "до открытия" if hour == "bmo" else "после закрытия",
            "eps_estimate": e.get("epsEstimate"),
            "risk": (
                "HIGH"   if days_until <= 3 else
                "MEDIUM" if days_until <= 7 else
                "LOW"
            ),
        }

    _set_cached(cache_key, result)
    logger.info(f"Finnhub earnings calendar: {len(result)} symbols with upcoming earnings")
    return result


async def get_earnings_for_symbol(symbol: str) -> dict:
    """
    Return earnings info for a single symbol.
    Pulls from the cached calendar — no extra API call.
    """
    calendar = await get_earnings_calendar()
    return calendar.get(symbol.upper(), {"has_earnings": False})
