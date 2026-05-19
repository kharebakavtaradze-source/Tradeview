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
        target_date = get_last_trading_day(offset=0)

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


# ── Non-stock exclusion cache ─────────────────────────────────────────────────
# Covers: ETF, ETN, ETV (exchange-traded vehicles), FUND (open-end funds),
# CEF (closed-end funds — Polygon's dedicated type), WARRANT (exchange-listed
# warrants, e.g. ABVEW / ARQQW / CCCXW), RIGHT (rights offerings), plus a
# hardcoded safety net for leveraged/inverse products and crypto spot ETFs that
# Polygon may list under unusual types or CS (common stock).

# Polygon security types to exclude (all are non-equity instruments)
_EXCLUDED_POLYGON_TYPES = ("ETF", "ETN", "ETV", "FUND", "CEF", "WARRANT", "RIGHT")

# Known leveraged/inverse products, crypto spot ETFs, and other non-stock
# instruments — safety net for anything misclassified or newly listed.
_HARDCODED_EXCLUSIONS: set[str] = {
    # ── Leveraged / inverse (ProShares) ──────────────────────────────────────
    "TQQQ", "SQQQ", "UPRO", "SPXU", "SPXL", "SPXS",
    "QLD",  "QID",  "SSO",  "SDS",  "UDOW", "SDOW",
    "TNA",  "TZA",  "URTY", "SRTY", "LABU", "LABD",
    "NUGT", "DUST", "JNUG", "JDST", "USLV", "DSLV",
    "UCO",  "SCO",  "BOIL", "KOLD", "UNG",  "DGAZ",
    "UGAZ", "GUSH", "DRIP", "NAIL", "SOXL", "SOXS",
    "FNGU", "FNGD", "TECL", "TECS", "DPST", "FAZ",
    "FAS",  "ERX",  "ERY",  "RETL", "SHLD",
    "ROM",  "RXL",  "DDM",  "MVV",  "UWM",  "SAA",
    "USD",  "UYG",  "EFO",  "EET",  "EZJ",  "MIDU",
    "UMDD", "URPIX","UTSL", "UBOT", "LBAY", "HIBS",
    # ── Leveraged / inverse (Direxion) ───────────────────────────────────────
    "TMF",  "TMV",  "TBF",  "TBT",  "TBX",
    "EDC",  "EDZ",  "INDL", "BRZU", "MEXI",
    "DRN",  "DRV",  "CURE", "PILL",
    "DFEN", "DDUP", "WEBL", "WEBS", "WANT", "TPOR",
    "DUSL", "BULZ", "BERZ", "HIBL", "HIBS",
    # ── Crypto spot ETFs ─────────────────────────────────────────────────────
    "GBTC", "ETHE", "IBIT", "FBTC", "BITB", "BTCO",
    "ARKB", "BRRR", "HODL", "EZBC", "DEFI",
    "ETHW", "CETH", "ETHV", "QETH", "FETH",
    "BTCW", "SBTC", "YBTC", "MAXI", "BITU", "BITX",
    "BITI", "ETHU", "METH", "SETH",
    # ── Volatility products ───────────────────────────────────────────────────
    "VXX",  "UVXY", "SVXY", "VIXY", "VIXM",
    "TVIX", "TVIZ", "XIV",  "ZIV",
    # ── Broad-market / sector ETFs that sometimes appear ────────────────────
    "SPY",  "QQQ",  "IWM",  "DIA",  "MDY",  "IJH",  "IJR",
    "XLF",  "XLE",  "XLV",  "XLU",  "XLK",  "XLI",  "XLY",
    "XLP",  "XLB",  "XLRE", "XLC",
    "GLD",  "SLV",  "GDX",  "GDXJ", "USO",  "UGA",
    "TLT",  "IEF",  "SHY",  "HYG",  "LQD",  "AGG",  "BND",
    "EEM",  "EFA",  "VWO",  "VEA",  "VTI",  "VOO",  "VXF",
    "ARKK", "ARKG", "ARKF", "ARKQ", "ARKX", "ARKW",
    # ── Nasdaq / exchange LULD test tickers ──────────────────────────────────
    # These are official exchange test symbols used during Limit Up/Limit Down
    # band adjustment tests.  They trade at artificially extreme prices (e.g.
    # ZWZZT has appeared at $12,999.87 intraday) that generate false pump
    # signals.  Polygon classifies them as CS (common stock) so they bypass
    # the Polygon type filter and must be hardcoded here.
    "ZWZZT", "ZAZZT", "ZBZX", "ZXZZT",
}

_excluded_cache: set[str] = set()
_excluded_cache_date: Optional[str] = None


async def get_us_etf_symbols() -> set[str]:
    """
    Fetch all non-stock securities from Polygon reference API.
    Covers ETF, ETN, ETV, FUND, CEF, WARRANT, RIGHT types + hardcoded
    leveraged/inverse/crypto safety net. Cached in memory for 7 days.
    Returns set of uppercase ticker strings.

    Kept as get_us_etf_symbols() for backwards-compat with all call sites.
    """
    global _excluded_cache, _excluded_cache_date

    today = date.today().isoformat()
    if _excluded_cache and _excluded_cache_date:
        cache_age = (date.today() - date.fromisoformat(_excluded_cache_date)).days
        if cache_age < 7:
            logger.info(f"Exclusion cache hit: {len(_excluded_cache)} symbols (age {cache_age}d)")
            return _excluded_cache

    logger.info(f"Building exclusion list from Polygon: types={_EXCLUDED_POLYGON_TYPES}")
    excluded: set[str] = set(_HARDCODED_EXCLUSIONS)  # start with safety net

    MAX_PAGES = 5          # 5 pages × 1000 = 5000 per type — more than enough
    per_req_timeout = httpx.Timeout(10.0, connect=5.0)

    async with httpx.AsyncClient(timeout=per_req_timeout) as client:
        for sec_type in _EXCLUDED_POLYGON_TYPES:
            url    = f"{MASSIVE_BASE}/v3/reference/tickers"
            params = _params(type=sec_type, market="stocks", active="true", limit=1000)
            page   = 0
            type_count = 0

            while url and page < MAX_PAGES:
                page += 1
                try:
                    resp = await client.get(url, params=params)
                    if resp.status_code != 200:
                        logger.warning(f"Exclusion list HTTP {resp.status_code} (type={sec_type} page={page})")
                        break
                    data = resp.json()
                    for t in data.get("results") or []:
                        sym = (t.get("ticker") or "").upper()
                        if sym:
                            excluded.add(sym)
                            type_count += 1
                    next_url = data.get("next_url")
                    if next_url:
                        url    = next_url
                        params = {"apiKey": MASSIVE_API_KEY}
                    else:
                        break
                except Exception as e:
                    logger.warning(f"Exclusion list fetch error (type={sec_type} page={page}): {e}")
                    break

            logger.info(f"  {sec_type}: {type_count} symbols fetched")

    if len(excluded) > len(_HARDCODED_EXCLUSIONS):
        _excluded_cache      = excluded
        _excluded_cache_date = today
        logger.info(f"Exclusion cache refreshed: {len(excluded)} total symbols "
                    f"(ETF/ETN/ETV/FUND/CEF/WARRANT/RIGHT + {len(_HARDCODED_EXCLUSIONS)} hardcoded)")
    else:
        logger.warning("Polygon returned 0 results — using hardcoded exclusions only")
        _excluded_cache      = excluded   # still use the hardcoded set
        _excluded_cache_date = today

    return _excluded_cache


async def fetch_candles_massive(symbol: str, days: int = 200, as_of_date: Optional[str] = None) -> list:
    """
    Fetch up to `days` daily OHLCV bars for one symbol.
    Handles Massive pagination via next_url.
    Returns list sorted oldest→newest, same format as Yahoo candles.
    Returns [] on failure.

    as_of_date (YYYY-MM-DD): if provided, data is cut at this date.
        Used by Historical Replay mode to prevent future leakage.
        Live scans leave this None and get today's data as before.
    """
    if not MASSIVE_API_KEY:
        return []

    # ── Time cutoff (future-leakage prevention for replay mode) ──────────────
    _cutoff = date.fromisoformat(as_of_date) if as_of_date else date.today()
    end_date   = _cutoff.strftime("%Y-%m-%d")
    start_date = (_cutoff - timedelta(days=days + 60)).strftime("%Y-%m-%d")
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

# EQUITY_TYPES: canonical allowlist imported from stock_universe_filter.
# Re-exported here for backwards-compatibility with existing import sites.
from scanner.stock_universe_filter import COMMON_STOCK_TYPES as EQUITY_TYPES  # noqa: E402


async def fetch_ticker_type(symbol: str) -> str | None:
    """
    Fetch the Polygon security type for one symbol (e.g. 'CS', 'ETF', 'CEF').
    Used as a per-symbol safeguard against instruments misclassified as CS.
    Returns None on any failure (caller should treat as unknown / allow through).
    """
    if not MASSIVE_API_KEY:
        return None

    url = f"{MASSIVE_BASE}/v3/reference/tickers/{symbol.upper()}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(6.0, connect=3.0)) as client:
            resp = await client.get(url, params=_params())
        if resp.status_code != 200:
            return None
        return (resp.json().get("results") or {}).get("type") or None
    except Exception:
        return None


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
