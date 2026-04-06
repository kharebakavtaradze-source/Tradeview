"""
Massive/Polygon data client for EOD universe scans.

Massive.com = rebranded Polygon.io (Oct 2025).
Package: polygon-api-client (same API, new domain branding).

Used ONLY for:
  1. Nightly EOD universe scan (fetch_grouped_daily)
  2. Individual symbol history for top candidates (fetch_candles_massive)
  3. Sector/industry enrichment (fetch_ticker_details)

Never called during intraday Yahoo validation scans.
"""
import asyncio
import logging
import os
from datetime import date, datetime, timedelta

logger = logging.getLogger(__name__)

MASSIVE_API_KEY = os.getenv("MASSIVE_API_KEY", "")


def _get_client():
    """Get synchronous Polygon/Massive REST client."""
    from polygon import RESTClient
    if not MASSIVE_API_KEY:
        raise ValueError("MASSIVE_API_KEY not set in environment")
    return RESTClient(api_key=MASSIVE_API_KEY)


def get_last_trading_day(offset: int = 1) -> str:
    """
    Return a trading-day date string.
    offset=1 → yesterday (most common: get last close).
    offset=0 → today (data may not be ready until after 5 PM ET).
    Skips weekends only — holiday fallback is handled by fetch_grouped_daily().
    """
    d = date.today() - timedelta(days=offset)
    while d.weekday() >= 5:  # Saturday=5, Sunday=6
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _prev_weekday(date_str: str) -> str:
    """Return the previous weekday before a given YYYY-MM-DD string."""
    d = datetime.strptime(date_str, "%Y-%m-%d").date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


# ── Grouped Daily ─────────────────────────────────────────────────────────────

def _sync_fetch_grouped_daily(target_date: str) -> dict:
    """
    ONE Polygon API call → ALL US stocks EOD bars.
    Runs in a thread (sync client).
    """
    client = _get_client()
    result = {}

    total_raw    = 0
    skip_alpha   = 0
    skip_len     = 0
    skip_vol     = 0
    skip_price   = 0

    for bar in client.get_grouped_daily_aggs(
        locale="us",
        market_type="stocks",
        date=target_date,
        adjusted=True,
    ):
        total_raw += 1
        sym = bar.ticker or ""

        if not sym.isalpha():
            skip_alpha += 1
            continue
        if len(sym) > 5:
            skip_len += 1
            continue

        vol   = bar.volume or 0
        close = bar.close  or 0.0

        if vol < 100_000:
            skip_vol += 1
            continue
        if not (1.0 <= close <= 1000.0):
            skip_price += 1
            continue

        result[sym] = {
            "open":   bar.open,
            "high":   bar.high,
            "low":    bar.low,
            "close":  close,
            "volume": vol,
            "vwap":   bar.vw,
            "trades": bar.transactions or 0,
            "date":   target_date,
        }

    logger.info(
        f"Grouped daily raw={total_raw} | "
        f"skip_non_alpha={skip_alpha} skip_len>{5}={skip_len} "
        f"skip_vol<100K={skip_vol} skip_price={skip_price} | "
        f"passed={len(result)}"
    )
    if total_raw == 0:
        logger.warning(
            "Grouped daily returned 0 rows — possible causes: "
            "holiday/weekend date, wrong API key, Polygon plan doesn't include grouped daily"
        )

    return result


async def fetch_grouped_daily(target_date: str = None) -> dict:
    """
    Fetch EOD bars for ALL US stocks in a single API call.

    If the requested date returns 0 results (holiday, early close, data delay),
    automatically falls back to the previous weekday — up to 5 attempts.
    This handles Good Friday, market holidays, and data pipeline delays.

    Returns:
        {
            "AAPL": {"open": 175.0, "high": 178.5, "low": 174.2,
                     "close": 177.3, "volume": 45_000_000,
                     "vwap": 176.8, "trades": 450_000, "date": "2025-01-15"},
            ...
        }
    Quality filter: volume >= 100K, price $1–$1000, alpha symbols only.
    """
    if not target_date:
        target_date = get_last_trading_day(offset=1)

    if not MASSIVE_API_KEY:
        logger.error("fetch_grouped_daily: MASSIVE_API_KEY not set")
        return {}

    attempt_date = target_date
    for attempt in range(5):
        logger.info(f"Massive: fetching grouped daily for {attempt_date} (attempt {attempt + 1})")
        try:
            result = await asyncio.to_thread(_sync_fetch_grouped_daily, attempt_date)
            if result:
                if attempt > 0:
                    logger.info(
                        f"Grouped daily: found data on fallback date {attempt_date} "
                        f"({attempt} day(s) before {target_date} — likely a holiday)"
                    )
                return result
            # 0 results — this day is a holiday or has no data yet
            logger.warning(
                f"Grouped daily: 0 results for {attempt_date} "
                f"(holiday or data not ready) — trying previous trading day"
            )
            attempt_date = _prev_weekday(attempt_date)
        except Exception as e:
            logger.error(f"fetch_grouped_daily failed for {attempt_date}: {e}")
            return {}

    logger.error(
        f"fetch_grouped_daily: no data found after 5 attempts "
        f"(tried back from {target_date})"
    )
    return {}


# ── Individual Symbol Candles ─────────────────────────────────────────────────

def _sync_fetch_candles(symbol: str, start_date: str, end_date: str) -> list:
    """Fetch daily OHLCV bars for one symbol. Runs in a thread."""
    client = _get_client()
    candles = []

    for a in client.list_aggs(
        ticker=symbol.upper(),
        multiplier=1,
        timespan="day",
        from_=start_date,
        to=end_date,
        adjusted=True,
        limit=50000,
    ):
        candles.append({
            "o": a.open,
            "h": a.high,
            "l": a.low,
            "c": a.close,
            "v": int(a.volume or 0),
            "t": a.timestamp,  # milliseconds epoch
        })

    candles.sort(key=lambda x: x["t"])
    return candles


async def fetch_candles_massive(symbol: str, days: int = 200) -> list:
    """
    Fetch up to `days` daily bars for one symbol via Massive/Polygon.
    Returns list sorted oldest→newest, same format as Yahoo candles.
    Returns [] on failure (caller should skip the symbol).
    """
    if not MASSIVE_API_KEY:
        return []

    end_date   = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=days + 60)).strftime("%Y-%m-%d")

    try:
        candles = await asyncio.to_thread(
            _sync_fetch_candles, symbol, start_date, end_date
        )
        return candles[-days:]
    except Exception as e:
        logger.warning(f"fetch_candles_massive({symbol}): {e}")
        return []


# ── Ticker Details (sector / industry enrichment) ─────────────────────────────

def _sync_fetch_ticker_details(symbol: str) -> dict:
    """Fetch reference data for one symbol. Runs in a thread."""
    client = _get_client()
    d = client.get_ticker_details(symbol.upper())
    return {
        "sector":     d.sic_description or None,
        "industry":   d.sic_description or None,
        "market_cap": d.market_cap or None,
        "exchange":   d.primary_exchange or None,
    }


async def fetch_ticker_details(symbol: str) -> dict | None:
    """
    Fetch sector, industry, market_cap for one symbol.
    Returns None on failure — caller decides what to do.
    Use ONLY for sector_cache enrichment (not hot-path).
    """
    if not MASSIVE_API_KEY:
        return None
    try:
        return await asyncio.to_thread(_sync_fetch_ticker_details, symbol)
    except Exception as e:
        logger.warning(f"fetch_ticker_details({symbol}): {e}")
        return None
