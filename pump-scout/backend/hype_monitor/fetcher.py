"""
Hype Monitor — Social Data Fetcher
Fetches StockTwits, Yahoo Finance News, and Reddit mentions concurrently.
Returns unified mention lists with timestamps and sentiment.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; PumpScout/9.0; research)",
    "Accept": "application/json",
}

TIMEOUT = 12.0


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(ts_str: str | None) -> datetime | None:
    if not ts_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S+0000", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(ts_str[:19], fmt[:len(fmt)])
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


async def _fetch_stocktwits(ticker: str, client: httpx.AsyncClient) -> list[dict]:
    """Fetch last ~30 messages from StockTwits stream."""
    url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
    try:
        resp = await client.get(url, headers=HEADERS)
        if resp.status_code != 200:
            return []
        data = resp.json()
        messages = data.get("messages", [])
        results = []
        for m in messages:
            ts = _parse_ts(m.get("created_at"))
            if not ts:
                continue
            sentiment_raw = (m.get("entities", {}) or {}).get("sentiment") or {}
            sentiment = sentiment_raw.get("basic", "").upper() if isinstance(sentiment_raw, dict) else ""
            results.append({
                "source": "stocktwits",
                "ts": ts,
                "text": (m.get("body") or "")[:280],
                "sentiment": sentiment,  # "BULLISH" / "BEARISH" / ""
            })
        return results
    except Exception as e:
        logger.debug(f"StockTwits fetch failed for {ticker}: {e}")
        return []


async def _fetch_yahoo_news(ticker: str, client: httpx.AsyncClient) -> list[dict]:
    """Fetch recent news headlines from Yahoo Finance search."""
    url = (
        f"https://query1.finance.yahoo.com/v1/finance/search"
        f"?q={ticker}&newsCount=15&quotesCount=0&enableFuzzyQuery=false"
    )
    try:
        resp = await client.get(url, headers=HEADERS)
        if resp.status_code != 200:
            return []
        data = resp.json()
        news = data.get("news", [])
        results = []
        for item in news:
            pub_epoch = item.get("providerPublishTime")
            if not pub_epoch:
                continue
            ts = datetime.fromtimestamp(pub_epoch, tz=timezone.utc)
            results.append({
                "source": "news",
                "ts": ts,
                "text": (item.get("title") or "")[:200],
                "sentiment": "",
            })
        return results
    except Exception as e:
        logger.debug(f"Yahoo News fetch failed for {ticker}: {e}")
        return []


async def _fetch_reddit(ticker: str, client: httpx.AsyncClient) -> list[dict]:
    """Search recent Reddit posts across WSB + penny stocks + small caps."""
    subreddits = "wallstreetbets+pennystocks+smallcapstocks+stocks"
    url = (
        f"https://www.reddit.com/r/{subreddits}/search.json"
        f"?q={ticker}&sort=new&t=day&restrict_sr=true&limit=25"
    )
    try:
        resp = await client.get(url, headers=HEADERS)
        if resp.status_code != 200:
            return []
        data = resp.json()
        posts = data.get("data", {}).get("children", [])
        results = []
        for p in posts:
            post = p.get("data", {})
            epoch = post.get("created_utc")
            if not epoch:
                continue
            ts = datetime.fromtimestamp(epoch, tz=timezone.utc)
            title = (post.get("title") or "")[:200]
            # Only count if ticker is in title/text (avoid subreddit noise)
            body = (post.get("selftext") or "")
            combined = (title + " " + body).upper()
            if ticker.upper() not in combined and f"${ticker.upper()}" not in combined:
                continue
            results.append({
                "source": "reddit",
                "ts": ts,
                "text": title,
                "sentiment": "",
            })
        return results
    except Exception as e:
        logger.debug(f"Reddit fetch failed for {ticker}: {e}")
        return []


async def fetch_all(ticker: str) -> dict[str, Any]:
    """
    Fetch all social sources for a ticker concurrently.
    Returns {ticker, mentions: [...], by_source: {stocktwits, news, reddit}, fetched_at}.
    Never raises — returns empty on any failure.
    """
    ticker = ticker.upper()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            twits, news, reddit = await asyncio.gather(
                _fetch_stocktwits(ticker, client),
                _fetch_yahoo_news(ticker, client),
                _fetch_reddit(ticker, client),
                return_exceptions=True,
            )
        # Coerce exceptions to empty lists
        twits = twits if isinstance(twits, list) else []
        news = news if isinstance(news, list) else []
        reddit = reddit if isinstance(reddit, list) else []
    except Exception as e:
        logger.warning(f"Hype fetch failed for {ticker}: {e}")
        twits, news, reddit = [], [], []

    all_mentions = twits + news + reddit
    # Sort newest first
    all_mentions.sort(key=lambda m: m["ts"], reverse=True)

    return {
        "ticker": ticker,
        "mentions": all_mentions,
        "by_source": {
            "stocktwits": twits,
            "news": news,
            "reddit": reddit,
        },
        "fetched_at": _now_utc().isoformat(),
    }
