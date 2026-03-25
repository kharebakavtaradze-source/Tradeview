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
_sector_cache: dict = {}

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# Import canonical sector map; also expose as _KNOWN_SECTORS for backwards compat
from scanner.sector_map import SECTOR_MAP as _KNOWN_SECTORS


async def _fetch_sector_api(ticker: str, client: httpx.AsyncClient) -> str:
    """Fetch sector from Yahoo Finance assetProfile. Tries query2 then query1."""
    for host in ("query2.finance.yahoo.com", "query1.finance.yahoo.com"):
        url = f"https://{host}/v10/finance/quoteSummary/{ticker}?modules=assetProfile"
        try:
            resp = await client.get(url, headers=_HEADERS)
            if resp.status_code == 200:
                data = resp.json()
                result = data.get("quoteSummary", {}).get("result") or [{}]
                sector = result[0].get("assetProfile", {}).get("sector") or ""
                if sector:
                    return sector
        except Exception:
            continue
    return "Unknown"


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
        from database import get_sector_from_db, save_sector_to_db
        cached = await get_sector_from_db(ticker)
        if cached:
            _sector_cache[ticker] = cached
            return cached
    except Exception:
        pass

    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            sector = await _fetch_sector_api(ticker, client)
    except Exception as e:
        logger.debug(f"get_sector failed for {ticker}: {e}")
        sector = "Unknown"

    _sector_cache[ticker] = sector
    if sector != "Unknown":
        try:
            from database import save_sector_to_db
            await save_sector_to_db(ticker, sector)
        except Exception:
            pass

    return sector


async def get_sectors_batch(tickers: list) -> dict:
    """Fetch sectors for multiple tickers concurrently (max 5 at a time)."""
    semaphore = asyncio.Semaphore(5)

    # Pre-fill from known map and in-memory cache
    result: dict[str, str] = {}
    need_fetch: list[str] = []
    for t in tickers:
        t = t.upper()
        if t in _KNOWN_SECTORS:
            result[t] = _KNOWN_SECTORS[t]
        elif t in _sector_cache:
            result[t] = _sector_cache[t]
        else:
            need_fetch.append(t)

    if not need_fetch:
        return result

    # Check DB cache for remaining tickers
    try:
        from database import get_sector_from_db
        still_need: list[str] = []
        for t in need_fetch:
            cached = await get_sector_from_db(t)
            if cached:
                result[t] = cached
                _sector_cache[t] = cached
            else:
                still_need.append(t)
        need_fetch = still_need
    except Exception:
        pass

    if not need_fetch:
        return result

    # Fetch remaining from Yahoo API
    async def fetch_one(ticker: str, client: httpx.AsyncClient):
        async with semaphore:
            sector = await _fetch_sector_api(ticker, client)
            _sector_cache[ticker] = sector
            if sector != "Unknown":
                try:
                    from database import save_sector_to_db
                    await save_sector_to_db(ticker, sector)
                except Exception:
                    pass
            return ticker, sector

    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            tasks = [fetch_one(t, client) for t in need_fetch]
            raw = await asyncio.gather(*tasks, return_exceptions=True)
    except Exception as e:
        logger.error(f"get_sectors_batch failed: {e}")
        raw = []

    for r in raw:
        if isinstance(r, tuple) and len(r) == 2:
            result[r[0]] = r[1]

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

    New logic (v2):
    - Leader must have score >= 60
    - This ticker must lag leader by >= 3% price change
    - This ticker must have vol >= 1.5x
    - CMF bonus for accumulation signal
    """
    sector = ticker_result.get("sector", "Unknown")

    if sector == "Unknown" or sector not in sector_leaders:
        return {"is_sympathy": False, "sympathy_score": 0}

    leaders = sector_leaders[sector]
    if not leaders:
        return {"is_sympathy": False, "sympathy_score": 0}

    my_symbol = ticker_result.get("symbol", "")
    # Filter out this ticker from leaders
    sector_leaders_filtered = [l for l in leaders if l["symbol"] != my_symbol]
    if not sector_leaders_filtered:
        return {"is_sympathy": False, "sympathy_score": 0, "is_leader": True}

    best_leader = sector_leaders_filtered[0]
    leader_score = best_leader["score"]
    leader_change = best_leader["change"]

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

    score = min(100, round(score))

    return {
        "is_sympathy": score >= 50,
        "sympathy_score": score,
        "sector": sector,
        "leaders": [l["symbol"] for l in sector_leaders_filtered[:3]],
        "leader": best_leader["symbol"],
        "leader_score": round(leader_score, 1),
        "leader_change_pct": round(leader_change, 2),
        "my_change_pct": round(my_change, 2),
        "lag_pct": round(lag, 2),
        # backwards-compat fields
        "leader_change": round(leader_change, 1),
        "candidate_change": round(my_change, 2),
        "window": "1-3 days",
    }
