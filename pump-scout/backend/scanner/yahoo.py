"""
Fetch OHLCV data from Yahoo Finance v8 API.
"""
import asyncio
import logging
from typing import Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

YAHOO_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.5",
}

SEMAPHORE_LIMIT = 5
REQUEST_DELAY = 0.2  # seconds between requests


async def fetch_ohlcv(
    ticker: str,
    interval: str = "1d",
    period: str = "6mo",
    client: Optional[httpx.AsyncClient] = None,
) -> Optional[List[dict]]:
    """
    Fetch OHLCV candles for a single ticker from Yahoo Finance.
    Returns list of candle dicts or None on failure.
    """
    url = f"{YAHOO_BASE}/{ticker}"
    params = {"interval": interval, "range": period}

    async def _fetch(c: httpx.AsyncClient) -> Optional[List[dict]]:
        for attempt in range(3):
            try:
                resp = await c.get(url, params=params, timeout=10.0)
                if resp.status_code == 429:
                    await asyncio.sleep(2 ** attempt)
                    continue
                if resp.status_code != 200:
                    return None

                data = resp.json()
                result = data.get("chart", {}).get("result")
                if not result:
                    return None

                chart = result[0]
                timestamps = chart.get("timestamp", [])
                indicators = chart.get("indicators", {})
                quote = indicators.get("quote", [{}])[0]

                opens = quote.get("open", [])
                highs = quote.get("high", [])
                lows = quote.get("low", [])
                closes = quote.get("close", [])
                volumes = quote.get("volume", [])

                if not timestamps or not closes:
                    return None

                candles = []
                for i, ts in enumerate(timestamps):
                    try:
                        o = opens[i]
                        h = highs[i]
                        lo = lows[i]
                        c_val = closes[i]
                        v = volumes[i]
                        # Skip bars with None values
                        if any(x is None for x in [o, h, lo, c_val, v]):
                            continue
                        candles.append({
                            "t": int(ts),
                            "o": float(o),
                            "h": float(h),
                            "l": float(lo),
                            "c": float(c_val),
                            "v": int(v),
                        })
                    except (IndexError, TypeError, ValueError):
                        continue

                return candles if candles else None

            except httpx.TimeoutException:
                logger.debug(f"Timeout fetching {ticker}")
                return None
            except Exception as e:
                logger.debug(f"Error fetching {ticker}: {e}")
                return None
        return None

    if client is not None:
        return await _fetch(client)

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as c:
        return await _fetch(c)


async def fetch_premarket_batch(tickers: List[str]) -> Dict[str, dict]:
    """
    Fetch pre-market / after-hours quote data for a list of tickers.
    Uses Yahoo Finance v7 quote API (single request for all symbols).
    Returns {symbol: {premarket_pct, premarket_price, has_premarket}} per ticker.
    """
    if not tickers:
        return {}

    results: Dict[str, dict] = {}
    chunk_size = 50  # Yahoo accepts up to ~100 symbols per request

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True, timeout=15.0) as client:
        for i in range(0, len(tickers), chunk_size):
            chunk = tickers[i : i + chunk_size]
            symbols_str = ",".join(chunk)
            url = "https://query1.finance.yahoo.com/v7/finance/quote"
            params = {
                "symbols": symbols_str,
                "fields": "preMarketPrice,preMarketChangePercent,postMarketPrice,postMarketChangePercent,regularMarketPrice",
            }
            try:
                resp = await client.get(url, params=params)
                if resp.status_code != 200:
                    continue
                data = resp.json()
                quotes = data.get("quoteResponse", {}).get("result", [])
                for q in quotes:
                    sym = q.get("symbol", "")
                    pre_pct   = q.get("preMarketChangePercent")
                    pre_price = q.get("preMarketPrice")
                    post_pct  = q.get("postMarketChangePercent")
                    post_price= q.get("postMarketPrice")
                    # Prefer pre-market if available, else after-hours
                    if pre_pct is not None:
                        results[sym] = {
                            "premarket_pct":   round(pre_pct, 2),
                            "premarket_price": round(pre_price, 4) if pre_price else None,
                            "session":         "pre",
                            "has_premarket":   True,
                        }
                    elif post_pct is not None:
                        results[sym] = {
                            "premarket_pct":   round(post_pct, 2),
                            "premarket_price": round(post_price, 4) if post_price else None,
                            "session":         "post",
                            "has_premarket":   True,
                        }
                await asyncio.sleep(0.3)
            except Exception as e:
                logger.warning(f"Pre-market fetch error for chunk: {e}")

    return results


async def fetch_batch(
    tickers: List[str],
    interval: str = "1d",
) -> Dict[str, List[dict]]:
    """
    Fetch OHLCV data for all tickers concurrently (max 5 at a time).
    Returns {ticker: candles[]} for successful fetches.
    """
    semaphore = asyncio.Semaphore(SEMAPHORE_LIMIT)
    results: Dict[str, List[dict]] = {}

    async def fetch_one(ticker: str, client: httpx.AsyncClient):
        async with semaphore:
            candles = await fetch_ohlcv(ticker, interval=interval, client=client)
            if candles:
                results[ticker] = candles
            await asyncio.sleep(REQUEST_DELAY)

    async with httpx.AsyncClient(headers=HEADERS, follow_redirects=True) as client:
        tasks = [fetch_one(ticker, client) for ticker in tickers]
        await asyncio.gather(*tasks, return_exceptions=True)

    logger.info(f"Fetched {len(results)}/{len(tickers)} tickers successfully")
    return results
