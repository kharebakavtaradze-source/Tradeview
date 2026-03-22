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

# ─── Known sector map — zero API calls for these tickers ─────────────────────
_KNOWN_SECTORS: dict[str, str] = {
    # Crypto miners
    "MARA": "Financial Services", "RIOT": "Financial Services", "CLSK": "Financial Services",
    "HUT": "Financial Services", "BITF": "Financial Services", "WULF": "Financial Services",
    "BTBT": "Financial Services", "CIFR": "Financial Services", "IREN": "Financial Services",
    "GREE": "Financial Services",
    # EV / Automotive
    "NKLA": "Consumer Cyclical", "FFIE": "Consumer Cyclical", "GOEV": "Consumer Cyclical",
    "MULN": "Consumer Cyclical", "WKHS": "Industrials", "RIVN": "Consumer Cyclical",
    "LCID": "Consumer Cyclical", "PTRA": "Industrials", "SOLO": "Consumer Cyclical",
    "BLNK": "Consumer Cyclical", "EVGO": "Consumer Cyclical", "CHPT": "Consumer Cyclical",
    "AYRO": "Consumer Cyclical", "IDEX": "Consumer Cyclical",
    # AI / Tech
    "BBAI": "Technology", "SOUN": "Technology", "AIXI": "Technology", "AITX": "Technology",
    "SMCI": "Technology", "IONQ": "Technology", "RGTI": "Technology", "QUBT": "Technology",
    "QBTS": "Technology", "CXAI": "Technology", "GFAI": "Technology", "TUYA": "Technology",
    "AIOT": "Technology",
    # Space / Satellite
    "ASTS": "Communication Services", "SATL": "Communication Services",
    "RKLB": "Industrials", "LUNR": "Industrials", "MNTS": "Industrials",
    "VORB": "Industrials", "ASTRA": "Industrials", "SPIR": "Communication Services",
    "GSAT": "Communication Services", "VSAT": "Communication Services",
    "NXST": "Communication Services",
    # Biotech / Healthcare
    "BNGO": "Healthcare", "NVAX": "Healthcare", "OCGN": "Healthcare",
    "SAVA": "Healthcare", "SENS": "Healthcare",
    "CODX": "Healthcare", "INMB": "Healthcare", "IRWD": "Healthcare",
    "TPST": "Healthcare", "HALO": "Healthcare", "CAPR": "Healthcare",
    "DNLI": "Healthcare", "FOLD": "Healthcare", "MIST": "Healthcare",
    "RCKT": "Healthcare", "RYTM": "Healthcare", "CRVS": "Healthcare",
    "DERM": "Healthcare", "HUMA": "Healthcare", "INAB": "Healthcare",
    "ZLAB": "Healthcare", "NRIX": "Healthcare", "VSTM": "Healthcare",
    "CORT": "Healthcare", "ATAI": "Healthcare", "CLDX": "Healthcare",
    "VNDA": "Healthcare", "AKBA": "Healthcare", "ADMA": "Healthcare",
    "BCYC": "Healthcare", "XNCR": "Healthcare", "SANA": "Healthcare",
    "TGTX": "Healthcare", "TNXP": "Healthcare", "PCVX": "Healthcare",
    "IMVT": "Healthcare", "BHVN": "Healthcare", "KPTI": "Healthcare",
    "VRCA": "Healthcare", "IDYA": "Healthcare", "CPRX": "Healthcare",
    "NRXS": "Healthcare", "STRO": "Healthcare", "PDSB": "Healthcare",
    "ALLO": "Healthcare", "AMRX": "Healthcare", "ERAS": "Healthcare",
    "FATE": "Healthcare", "KLTR": "Healthcare", "ITRM": "Healthcare",
    "CRBU": "Healthcare", "REPL": "Healthcare", "ARRY": "Healthcare",
    "KYMR": "Healthcare",
    # Financial Services
    "EFSC": "Financial Services", "SOFI": "Financial Services",
    "HOOD": "Financial Services",
    # Real Estate
    "NXRT": "Real Estate",
    # Consumer
    "CURV": "Consumer Cyclical", "SCHL": "Consumer Defensive",
    # Industrials
    "NNBR": "Industrials", "TITN": "Industrials",
    # Gaming / Media
    "AMC": "Communication Services", "GME": "Consumer Cyclical",
    "DKNG": "Consumer Cyclical", "PENN": "Consumer Cyclical",
    # Cannabis
    "SNDL": "Consumer Defensive", "TLRY": "Consumer Defensive",
    "CGC": "Consumer Defensive", "ACB": "Consumer Defensive",
    "CRON": "Consumer Defensive", "HEXO": "Consumer Defensive",
}


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
