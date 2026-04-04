"""
Sector Sympathy Scanner.
When one ticker in a sector pumps, others in the same sector that
haven't moved yet often follow within 1-3 days.
"""
import asyncio
import logging

import httpx

logger = logging.getLogger(__name__)

# In-process memory cache — fast path, avoid DB for hot-path tickers
_sector_cache: dict   = {}
_industry_cache: dict = {}   # symbol → industry string (populated from DB/Yahoo)

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# Import canonical sector map; also expose as _KNOWN_SECTORS for backwards compat
from scanner.sector_map import SECTOR_MAP as _KNOWN_SECTORS


async def _fetch_sector_api(ticker: str, client: httpx.AsyncClient) -> tuple[str, str]:
    """Fetch sector AND industry from Yahoo Finance assetProfile.
    Returns (sector, industry). Tries query2 then query1."""
    from scanner.sector_map import FINVIZ_TO_GICS
    for host in ("query2.finance.yahoo.com", "query1.finance.yahoo.com"):
        url = f"https://{host}/v10/finance/quoteSummary/{ticker}?modules=assetProfile"
        try:
            resp = await client.get(url, headers=_HEADERS)
            if resp.status_code == 200:
                data = resp.json()
                result = data.get("quoteSummary", {}).get("result") or [{}]
                profile = result[0].get("assetProfile", {})
                raw_sector = profile.get("sector") or ""
                industry = profile.get("industry") or ""
                # Normalize sector to GICS name if Yahoo returns Finviz-style name
                sector = FINVIZ_TO_GICS.get(raw_sector, raw_sector)
                if sector:
                    return sector, industry
        except Exception:
            continue
    return "Unknown", ""


async def get_sector(ticker: str) -> str:
    """
    Fetch sector for a ticker.
    Priority: known map → in-memory cache → DB cache → Yahoo API.
    """
    ticker = ticker.upper()

    if ticker in _KNOWN_SECTORS:
        return _KNOWN_SECTORS[ticker]

    if ticker in _sector_cache:
        return _sector_cache[ticker]

    # Try DB cache (avoids API calls across restarts)
    try:
        from database import get_sector_full_from_db
        cached_row = await get_sector_full_from_db(ticker)
        if cached_row and cached_row.get("sector") and cached_row["sector"] != "Unknown":
            _sector_cache[ticker] = cached_row["sector"]
            if cached_row.get("industry"):
                _industry_cache[ticker] = cached_row["industry"]
            return cached_row["sector"]
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            sector, industry = await _fetch_sector_api(ticker, client)
    except Exception as e:
        logger.debug(f"get_sector failed for {ticker}: {e}")
        sector, industry = "Unknown", ""

    _sector_cache[ticker] = sector
    if industry:
        _industry_cache[ticker] = industry
    if sector != "Unknown":
        try:
            from database import save_sector_to_db
            await save_sector_to_db(ticker, sector, industry=industry)
        except Exception:
            pass

    return sector


async def get_sectors_batch(tickers: list) -> dict:
    """
    Fetch sectors (+ industry when cached) for multiple tickers concurrently.

    Returns:
      {symbol: {"sector": str, "industry": str}}

    Industry comes from DB enrichment (Massive nightly job) when available.
    Yahoo API is used as fallback for unknown sectors — industry from Yahoo too.
    """
    semaphore = asyncio.Semaphore(5)

    # result stores {"sector": ..., "industry": ...} per symbol
    result: dict[str, dict] = {}
    need_fetch: list[str] = []

    for t in tickers:
        t = t.upper()
        if t in _KNOWN_SECTORS:
            result[t] = {"sector": _KNOWN_SECTORS[t], "industry": _industry_cache.get(t, "")}
        elif t in _sector_cache:
            result[t] = {"sector": _sector_cache[t], "industry": _industry_cache.get(t, "")}
        else:
            need_fetch.append(t)

    if not need_fetch:
        return result

    # Check DB cache for remaining tickers (includes industry + massive_fetched)
    try:
        from database import get_sector_full_from_db
        still_need: list[str] = []
        for t in need_fetch:
            row = await get_sector_full_from_db(t)
            if row and row.get("sector") and row["sector"] != "Unknown":
                sector   = row["sector"]
                industry = row.get("industry") or ""
                result[t] = {"sector": sector, "industry": industry}
                _sector_cache[t] = sector
                if industry:
                    _industry_cache[t] = industry
            else:
                still_need.append(t)
        need_fetch = still_need
    except Exception:
        pass

    if not need_fetch:
        return result

    # Fetch remaining from Yahoo API (never Massive — rate limited, nightly only)
    async def fetch_one(ticker: str, client: httpx.AsyncClient):
        async with semaphore:
            sector, industry = await _fetch_sector_api(ticker, client)
            _sector_cache[ticker] = sector
            if industry:
                _industry_cache[ticker] = industry
            if sector != "Unknown":
                try:
                    from database import save_sector_to_db
                    await save_sector_to_db(ticker, sector, industry=industry)
                except Exception:
                    pass
            return ticker, sector, industry

    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            tasks = [fetch_one(t, client) for t in need_fetch]
            raw = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        logger.error(f"get_sectors_batch failed: {e}")
        raw = []

    for r in raw:
        if isinstance(r, tuple) and len(r) == 3:
            result[r[0]] = {"sector": r[1], "industry": r[2]}

    return result


def find_sector_leaders(results: list) -> dict:
    """
    Returns {sector: [leader_dicts]}.
    Leader = ticker with score > 60 OR (price_change_pct > 10% AND vol > 3x).
    """
    leaders: dict = {}
    for r in results:
        change = r.get("indicators", {}).get("price_change_pct", 0) or 0
        vol = r.get("indicators", {}).get("anomaly_ratio", 0)
        score_val = r.get("score", {}).get("total_score", 0)
        sector = r.get("sector", "Unknown")

        if sector == "Unknown":
            continue

        # Strong leader: high score OR big price move
        if score_val >= 60 or (change > 10.0 and vol > 3.0):
            leaders.setdefault(sector, []).append({
                "symbol": r["symbol"],
                "change": change,
                "vol": vol,
                "score": score_val,
            })

    # Sort each sector's leaders by score desc
    for sector in leaders:
        leaders[sector].sort(key=lambda x: x["score"], reverse=True)

    return leaders


def calc_sympathy_score(ticker_result: dict, sector_leaders: dict) -> dict:
    """
    Score sympathy play potential for a ticker given sector leaders.

    Logic (v3 — industry-aware):
    - Leader must have score >= 60
    - This ticker must lag leader by >= 3% price change
    - This ticker must have vol >= 1.5x
    - Industry-level match = stronger sympathy than sector-level only
    """
    from scanner.sector_map import TICKER_INDUSTRY, SYMPATHY_INDUSTRIES

    sector = ticker_result.get("sector", "Unknown")
    my_symbol = ticker_result.get("symbol", "")
    my_industry = TICKER_INDUSTRY.get(my_symbol, "")

    if sector == "Unknown" or sector not in sector_leaders:
        return {"is_sympathy": False, "sympathy_score": 0}

    leaders = sector_leaders[sector]
    if not leaders:
        return {"is_sympathy": False, "sympathy_score": 0}

    # Filter out this ticker from leaders
    sector_leaders_filtered = [l for l in leaders if l["symbol"] != my_symbol]
    if not sector_leaders_filtered:
        return {"is_sympathy": False, "sympathy_score": 0, "is_leader": True}

    best_leader = sector_leaders_filtered[0]
    leader_score = best_leader["score"]
    leader_change = best_leader["change"]
    leader_symbol = best_leader["symbol"]
    leader_industry = TICKER_INDUSTRY.get(leader_symbol, "")

    # Leader must be strong
    if leader_score < 60:
        return {"is_sympathy": False, "sympathy_score": 0}

    indicators = ticker_result.get("indicators", {})
    my_change = indicators.get("price_change_pct", 0) or 0
    my_cmf = indicators.get("cmf_pctl", 50)
    my_vol = indicators.get("anomaly_ratio", 0)

    lag = leader_change - my_change

    # Minimum lag and volume requirements
    if lag < 3.0:
        return {"is_sympathy": False, "sympathy_score": 0}
    if my_vol < 1.5:
        return {"is_sympathy": False, "sympathy_score": 0}

    score = 0

    # Leader strength bonus (max 40pts)
    score += min(40, leader_score * 0.4)

    # Lag bonus — more lag = more upside potential (max 30pts)
    score += min(30, lag * 3)

    # CMF bonus — already accumulating (max 20pts)
    if my_cmf > 70:
        score += 20
    elif my_cmf > 50:
        score += 10

    # Volume bonus (max 10pts)
    if my_vol > 3:
        score += 10
    elif my_vol > 2:
        score += 5

    # Industry-level sympathy bonus: same industry = much stronger signal
    industry_match = "sector"
    industry_bonus = 0
    if leader_industry and my_industry and leader_industry == my_industry:
        industry_match = "industry"
        strength = SYMPATHY_INDUSTRIES.get(my_industry, "WEAK")
        mult = {"STRONG": 0.4, "MEDIUM": 0.25, "WEAK": 0.1}.get(strength, 0.1)
        industry_bonus = min(20, leader_change * mult)
        score += industry_bonus
    elif my_industry:
        # Same sector but different industry — weaker sympathy
        industry_bonus = min(8, leader_change * 0.1)
        score += industry_bonus

    score = min(100, round(score))

    return {
        "is_sympathy": score >= 50,
        "sympathy_score": score,
        "sector": sector,
        "my_industry": my_industry,
        "leader_industry": leader_industry,
        "industry_match": industry_match,
        "leaders": [l["symbol"] for l in sector_leaders_filtered[:3]],
        "leader": leader_symbol,
        "leader_score": round(leader_score, 1),
        "leader_change_pct": round(leader_change, 2),
        "my_change_pct": round(my_change, 2),
        "lag_pct": round(lag, 2),
        # backwards-compat fields
        "leader_change": round(leader_change, 1),
        "candidate_change": round(my_change, 2),
        "window": "1-3 days",
    }
