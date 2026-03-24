"""
Scan Candidates — historical price fill job.
Runs at 16:10 ET weekdays to fill 5d / 10d / 20d prices for past candidates.
"""
import logging
from datetime import date, timedelta

import httpx

from database import ScanCandidate, get_session_factory
from sqlalchemy import select

logger = logging.getLogger(__name__)

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


async def _fetch_price(symbol: str) -> float | None:
    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    url,
                    params={"symbols": symbol.upper(), "fields": "regularMarketPrice"},
                    headers=YAHOO_HEADERS,
                )
                if resp.status_code == 200:
                    quotes = resp.json().get("quoteResponse", {}).get("result", [])
                    if quotes:
                        return quotes[0].get("regularMarketPrice")
        except Exception as e:
            logger.warning(f"Price fetch failed for {symbol} (attempt {attempt+1}): {e}")
    return None


async def fill_candidate_prices():
    """
    Runs at 16:10 ET weekdays.
    For each lookback window (5d/10d/20d), finds candidates whose scan_date
    was exactly N trading days ago and fills their forward price.
    Uses calendar days as approximation (5d≈7cal, 10d≈14cal, 20d≈28cal).
    """
    logger.info("fill_candidate_prices starting...")
    today = date.today()
    filled = 0

    windows = [
        ("price_5d",  "pct_5d",  7),   # ~5 trading days
        ("price_10d", "pct_10d", 14),  # ~10 trading days
        ("price_20d", "pct_20d", 28),  # ~20 trading days
    ]

    async with get_session_factory()() as session:
        for price_col, pct_col, cal_days in windows:
            target_date = today - timedelta(days=cal_days)
            result = await session.execute(
                select(ScanCandidate).where(
                    ScanCandidate.scan_date == target_date,
                    getattr(ScanCandidate, price_col).is_(None),
                )
            )
            candidates = result.scalars().all()
            logger.info(f"Filling {price_col} for {len(candidates)} candidates (scan_date={target_date})")

            for cand in candidates:
                price = await _fetch_price(cand.symbol)
                if price and cand.price and cand.price > 0:
                    pct = round((price - cand.price) / cand.price * 100, 2)
                    setattr(cand, price_col, round(price, 4))
                    setattr(cand, pct_col, pct)
                    filled += 1
                elif price:
                    setattr(cand, price_col, round(price, 4))
                    filled += 1

        await session.commit()

    logger.info(f"fill_candidate_prices done: {filled} prices filled")
