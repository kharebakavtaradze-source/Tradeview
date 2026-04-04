"""
Massive.com Reference Data client.
Free plan: 5 calls/minute.
Used ONLY for nightly sector/industry enrichment — never during live scans.
"""
import logging
import os

import httpx

logger = logging.getLogger(__name__)

MASSIVE_API_KEY = os.getenv("MASSIVE_API_KEY", "")
MASSIVE_BASE = "https://api.massive.com/v1"


async def get_ticker_reference(symbol: str) -> dict | None:
    """
    Fetch sector + industry + company info from Massive Reference Data.

    Free plan: 5 calls/min — only call for nightly enrichment cache misses.
    Returns dict with sector/industry/market_cap/exchange or None on failure.
    """
    if not MASSIVE_API_KEY:
        logger.warning("MASSIVE_API_KEY not set — skipping Massive lookup")
        return None

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{MASSIVE_BASE}/stocks/{symbol.upper()}/details",
                headers={"Authorization": f"Bearer {MASSIVE_API_KEY}"},
            )

            if resp.status_code == 429:
                logger.warning(f"Massive rate limit hit for {symbol}")
                return None

            if resp.status_code == 404:
                logger.debug(f"Massive: {symbol} not found (404)")
                return None

            if resp.status_code != 200:
                logger.debug(f"Massive: {symbol} returned HTTP {resp.status_code}")
                return None

            data = resp.json()

            # Normalise sector name via GICS mapping if possible
            raw_sector = data.get("sector") or ""
            try:
                from scanner.sector_map import FINVIZ_TO_GICS
                sector = FINVIZ_TO_GICS.get(raw_sector, raw_sector) or raw_sector
            except Exception:
                sector = raw_sector

            return {
                "sector":      sector or None,
                "industry":    data.get("industry") or None,
                "market_cap":  data.get("market_cap") or data.get("marketCap") or None,
                "description": (data.get("description") or "")[:200],
                "exchange":    data.get("exchange") or None,
                "country":     data.get("country") or "US",
            }

    except Exception as e:
        logger.warning(f"Massive reference fetch failed for {symbol}: {e}")
        return None
