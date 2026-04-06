"""
Massive.com data client for EOD universe scans.

Base URL: https://api.massive.com  (Polygon-compatible API, different domain)
Auth:     ?apiKey=KEY  (standard Polygon-style query param)
Package:  httpx  (already in requirements — no extra SDK needed)

Endpoints used:
  GET /v2/aggs/grouped/locale/us/market/stocks/{date}  → all US stocks EOD
  GET /v2/aggs/ticker/{sym}/range/1/day/{from}/{to}    → individual candle history
  GET /v3/reference/tickers/{sym}                       → sector / market_cap

Used ONLY for:
  1. Nightly EOD universe scan  (fetch_grouped_daily)
  2. Per-candidate history      (fetch_candles_massive)
  3. Sector/industry enrichment (fetch_ticker_details)

Never called during intraday Yahoo validation scans.
"""
import logging
import os
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

MASSIVE_API_KEY = os.getenv("MASSIVE_API_KEY", "")
MASSIVE_BASE    = "https://api.massive.com"
_TIMEOUT        = httpx.Timeout(30.0, connect=10.0)


def _params(**extra) -> dict:
    """Base query params — always includes apiKey."""
    return {"apiKey": MASSIVE_API_KEY, **extra}


# ── Date helpers ──────────────────────────────────────────────────────────────

def get_last_trading_day(offset: int = 1) -> str:
    """
    Return a trading-day date string (YYYY-MM-DD).
    offset=1 → yesterday.  Skips weekends only.
    Holiday fallback is handled by fetch_grouped_daily (auto-retry).
    """
    d = date.today() - timedelta(days=offset)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def _prev_weekday(date_str: str) -> str:
    """Step back one weekday from a YYYY-MM-DD string."""
    d = datetime.strptime(date_str, "%Y-%m-%d").date() - timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d.strftime("%Y-%m-%d")


# ── Grouped Daily ─────────────────────────────────────────────────────────────

async def _fetch_grouped_daily_raw(target_date: str) -> dict:
    """
    Single HTTP call → ALL US stocks EOD bars for one date.
    Returns parsed + filtered dict, or {} on any error.
    """
    url = f"{MASSIVE_BASE}/v2/aggs/grouped/locale/us/market/stocks/{target_date}"

    total_raw  = skip_alpha = skip_len = skip_vol = skip_price = 0
    result: dict = {}

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.get(url, params=_params(adjusted="true", include_otc="false"))

    if resp.status_code != 200:
        logger.warning(
            f"Grouped daily HTTP {resp.status_code} for {target_date}: "
            f"{resp.text[:200]}"
        )
        return {}

    data = resp.json()
    status = data.get("status", "")
    if status not in ("OK", "DELAYED"):
        logger.warning(f"Grouped daily status={status!r} for {target_date}")

    for bar in data.get("results") or []:
        total_raw += 1
        sym   = (bar.get("T") or "").upper()
        vol   = bar.get("v") or 0
        close = bar.get("c") or 0.0

        if not sym.isalpha():      skip_alpha += 1; continue
        if len(sym) > 5:           skip_len   += 1; continue
        if vol < 100_000:          skip_vol   += 1; continue
        if not (1.0 <= close <= 1000.0): skip_price += 1; continue

        result[sym] = {
            "open":   bar.get("o"),
            "high":   bar.get("h"),
            "low":    bar.get("l"),
            "close":  close,
            "volume": int(vol),
            "vwap":   bar.get("vw"),
            "trades": bar.get("n") or 0,
            "date":   target_date,
        }

    logger.info(
        f"Grouped daily {target_date}: raw={total_raw} | "
        f"skip_alpha={skip_alpha} skip_len={skip_len} "
        f"skip_vol={skip_vol} skip_price={skip_price} | "
        f"passed={len(result)}"
    )
    if total_raw == 0:
        logger.warning(
            f"Grouped daily returned 0 rows for {target_date} — "
            "market holiday, weekend, or data not yet available"
        )
    return result


async def fetch_grouped_daily(target_date: str = None) -> dict:
    """
    Fetch EOD bars for ALL US stocks in a single API call.

    Auto-retries up to 5 previous weekdays when 0 results are returned
    (handles Good Friday, market holidays, Massive data pipeline delays).

    Returns:
        {"AAPL": {"open":..., "high":..., "low":..., "close":...,
                  "volume":..., "vwap":..., "trades":..., "date":...}, ...}
    """
    if not MASSIVE_API_KEY:
        logger.error("fetch_grouped_daily: MASSIVE_API_KEY not set")
        return {}

    if not target_date:
        target_date = get_last_trading_day(offset=1)

    attempt_date = target_date
    for attempt in range(5):
        logger.info(f"Massive grouped daily: {attempt_date} (attempt {attempt + 1}/5)")
        try:
            result = await _fetch_grouped_daily_raw(attempt_date)
            if result:
                if attempt > 0:
                    logger.info(
                        f"Found data on fallback {attempt_date} "
                        f"({attempt} day(s) before requested {target_date})"
                    )
                return result
            logger.warning(
                f"0 results for {attempt_date} — likely a holiday, trying previous day"
            )
            attempt_date = _prev_weekday(attempt_date)
        except Exception as e:
            logger.error(f"fetch_grouped_daily error on {attempt_date}: {e}")
            return {}

    logger.error(
        f"fetch_grouped_daily: no data after 5 attempts "
        f"(tried back from {target_date}) — check API key or plan"
    )
    return {}


# ── US ETF Symbol Cache ───────────────────────────────────────────────────────

_etf_cache: set[str] = set()
_etf_cache_date: Optional[str] = None


async def get_us_etf_symbols() -> set[str]:
    """
    Fetch all US-listed ETF symbols from Polygon reference API.
    Cached in memory for 7 days — call once per universe scan.
    Returns set of uppercase ticker strings e.g. {"SPY", "QQQ", "ARKK", ...}.
    """
    global _etf_cache, _etf_cache_date

    today = date.today().isoformat()
    # Refresh weekly
    if _etf_cache and _etf_cache_date:
        cache_age = (date.today() - date.fromisoformat(_etf_cache_date)).days
        if cache_age < 7:
            logger.info(f"ETF cache hit: {len(_etf_cache)} symbols (age {cache_age}d)")
            return _etf_cache

    logger.info("Fetching US ETF symbol list from Polygon reference API…")
    etfs: set[str] = set()

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        url = f"{MASSIVE_BASE}/v3/reference/tickers"
        params = _params(type="ETF", market="stocks", active="true", limit=1000)
        fetched = 0

        while url:
            try:
                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    logger.warning(f"ETF list HTTP {resp.status_code}")
                    break
                data = resp.json()
                for t in data.get("results") or []:
                    sym = (t.get("ticker") or "").upper()
                    if sym:
                        etfs.add(sym)
                fetched += len(data.get("results") or [])
                # Pagination
                next_url = data.get("next_url")
                if next_url:
                    url = next_url
                    params = _params()   # apiKey already embedded in next_url? add anyway
                else:
                    break
            except Exception as e:
                logger.warning(f"ETF list fetch error: {e}")
                break

    if etfs:
        _etf_cache = etfs
        _etf_cache_date = today
        logger.info(f"ETF cache refreshed: {len(etfs)} US ETFs loaded")
    else:
        logger.warning("ETF list returned 0 results — using stale cache if available")

    return _etf_cache


async def fetch_candles_massive(symbol: str, days: int = 200) -> list:
    """
    Fetch up to `days` daily OHLCV bars for one symbol.
    Handles Massive pagination via next_url.
    Returns list sorted oldest→newest, same format as Yahoo candles.
    Returns [] on failure.
    """
    if not MASSIVE_API_KEY:
        return []

    end_date   = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=days + 60)).strftime("%Y-%m-%d")
    url = f"{MASSIVE_BASE}/v2/aggs/ticker/{symbol.upper()}/range/1/day/{start_date}/{end_date}"

    candles: list = []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            next_url: Optional[str] = None
            while True:
                if next_url:
                    # next_url already includes apiKey from Massive
                    resp = await client.get(next_url)
                else:
                    resp = await client.get(
                        url,
                        params=_params(adjusted="true", sort="asc", limit=50000),
                    )

                if resp.status_code != 200:
                    logger.warning(f"Candles HTTP {resp.status_code} for {symbol}")
                    break

                data = resp.json()
                for bar in data.get("results") or []:
                    candles.append({
                        "o": bar.get("o"),
                        "h": bar.get("h"),
                        "l": bar.get("l"),
                        "c": bar.get("c"),
                        "v": int(bar.get("v") or 0),
                        "t": bar.get("t"),   # milliseconds epoch
                    })

                next_url = data.get("next_url")
                if not next_url:
                    break  # no more pages

        candles.sort(key=lambda x: x["t"])
        return candles[-days:]

    except Exception as e:
        logger.warning(f"fetch_candles_massive({symbol}): {e}")
        return []


# ── Ticker Details (sector / market_cap enrichment) ───────────────────────────

async def fetch_ticker_details(symbol: str) -> dict | None:
    """
    Fetch sector (sic_description), market_cap, exchange for one symbol.
    Use ONLY for sector_cache enrichment — not in the hot scan path.
    Returns None on failure.
    """
    if not MASSIVE_API_KEY:
        return None

    url = f"{MASSIVE_BASE}/v3/reference/tickers/{symbol.upper()}"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, params=_params())

        if resp.status_code == 404:
            logger.debug(f"Ticker details: {symbol} not found")
            return None
        if resp.status_code != 200:
            logger.warning(f"Ticker details HTTP {resp.status_code} for {symbol}")
            return None

        r = resp.json().get("results") or {}
        return {
            "sector":     r.get("sic_description") or None,
            "industry":   r.get("sic_description") or None,
            "market_cap": r.get("market_cap")       or None,
            "exchange":   r.get("primary_exchange") or None,
        }
    except Exception as e:
        logger.warning(f"fetch_ticker_details({symbol}): {e}")
        return None
