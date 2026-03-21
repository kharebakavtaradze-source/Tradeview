"""
Sector Sympathy Scanner.
When one ticker in a sector pumps, others in the same sector that
haven't moved yet often follow within 1-3 days.
"""
import asyncio
import logging
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# In-memory cache — sectors change rarely, per-process cache is fine
_sector_cache: dict = {}


async def get_sector(ticker: str, session: Optional[aiohttp.ClientSession] = None) -> str:
    """Fetch sector for a ticker from Yahoo Finance assetProfile. Cached in-process."""
    if ticker in _sector_cache:
        return _sector_cache[ticker]

    url = (
        f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}"
        f"?modules=assetProfile"
    )
    headers = {"User-Agent": "Mozilla/5.0"}
    close_session = session is None
    if close_session:
        session = aiohttp.ClientSession()

    try:
        async with session.get(
            url, headers=headers, timeout=aiohttp.ClientTimeout(total=5)
        ) as resp:
            if resp.status != 200:
                return "Unknown"
            data = await resp.json(content_type=None)
            result = data.get("quoteSummary", {}).get("result") or [{}]
            profile = result[0].get("assetProfile", {})
            sector = profile.get("sector") or "Unknown"
            _sector_cache[ticker] = sector
            return sector
    except Exception as e:
        logger.debug(f"get_sector failed for {ticker}: {e}")
        return "Unknown"
    finally:
        if close_session:
            await session.close()


async def get_sectors_batch(tickers: list) -> dict:
    """Fetch sectors for multiple tickers concurrently (max 10 at a time)."""
    semaphore = asyncio.Semaphore(10)

    async def fetch_one(ticker: str, session: aiohttp.ClientSession):
        async with semaphore:
            sector = await get_sector(ticker, session=session)
            return ticker, sector

    async with aiohttp.ClientSession() as session:
        tasks = [fetch_one(t, session) for t in tickers]
        raw = await asyncio.gather(*tasks, return_exceptions=True)

    out = {}
    for r in raw:
        if isinstance(r, tuple):
            out[r[0]] = r[1]
    return out


def find_sector_leaders(results: list) -> dict:
    """
    Returns {sector: [leader_dicts]}.
    Leader = ticker with price_change_pct > 10% AND vol_anomaly > 3x today.
    """
    leaders: dict = {}
    for r in results:
        change = (
            r.get("price_change_pct")
            or r.get("indicators", {}).get("price_change_pct", 0)
            or 0
        )
        vol = r.get("indicators", {}).get("anomaly_ratio", 0)
        sector = r.get("sector", "Unknown")

        if change > 10.0 and vol > 3.0 and sector != "Unknown":
            leaders.setdefault(sector, []).append(
                {"symbol": r["symbol"], "change": change, "vol": vol}
            )
    return leaders


def calc_sympathy_score(ticker_result: dict, sector_leaders: dict) -> dict:
    """
    Score sympathy play potential for a ticker given the current sector leaders.
    Sympathy candidate: same sector as a leader but hasn't moved yet (< 5%).
    """
    sector = ticker_result.get("sector", "Unknown")

    if sector == "Unknown" or sector not in sector_leaders:
        return {"is_sympathy": False, "sympathy_score": 0}

    leaders = sector_leaders[sector]
    ticker_change = (
        ticker_result.get("price_change_pct")
        or ticker_result.get("indicators", {}).get("price_change_pct", 0)
        or 0
    )

    # Must be in same sector as a leader but not moved yet
    if ticker_change >= 5.0 or not leaders:
        return {"is_sympathy": False, "sympathy_score": 0}

    max_leader_change = max(l["change"] for l in leaders)
    max_leader_vol = max(l["vol"] for l in leaders)

    sympathy_score = 0

    # Leader strength bonus (max 40)
    if max_leader_change > 50:
        sympathy_score += 40
    elif max_leader_change > 30:
        sympathy_score += 30
    elif max_leader_change > 15:
        sympathy_score += 20
    else:
        sympathy_score += 10

    # Volume bonus (max 30)
    if max_leader_vol > 10:
        sympathy_score += 30
    elif max_leader_vol > 5:
        sympathy_score += 20
    else:
        sympathy_score += 10

    # Candidate's own setup bonus (max 30)
    own_score = ticker_result.get("score", {}).get("total_score", 0)
    sympathy_score += min(own_score * 0.3, 30)

    return {
        "is_sympathy": True,
        "sympathy_score": min(int(sympathy_score), 100),
        "sector": sector,
        "leaders": [l["symbol"] for l in leaders],
        "leader_change": round(max_leader_change, 1),
        "candidate_change": round(ticker_change, 2),
        "window": "1-3 days",
    }
