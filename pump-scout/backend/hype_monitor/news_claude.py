"""
Hype Monitor — Claude Web Search News Fetcher
Uses Claude's web_search tool to find recent news when scraping fails.
api.anthropic.com is whitelisted on Railway, making this far more reliable
than direct Yahoo/Finviz scraping in restricted network environments.

Cache: 1 hour per ticker to control API costs.
Only called for FIRE/ARM tickers or on explicit user click.
"""
import json
import logging
import os
import time

import anthropic

logger = logging.getLogger(__name__)

# In-memory cache: {ticker: {"data": dict, "timestamp": float}}
_news_cache: dict[str, dict] = {}
CACHE_TTL = 3600  # 1 hour


async def fetch_news_claude(ticker: str) -> dict:
    """
    Use Claude with web_search tool to find recent news about a ticker.
    Returns a news_detail dict compatible with the rest of the hype monitor pipeline.

    Only called when:
    - Yahoo + Finviz return 0 results (scraping blocked)
    - User explicitly clicks the hype button on a card
    - Cache is empty or older than 1 hour
    - Ticker score >= 50 (FIRE/ARM tiers)
    """
    ticker = ticker.upper()

    # Check cache first
    now = time.time()
    cached = _news_cache.get(ticker)
    if cached and (now - cached["timestamp"]) < CACHE_TTL:
        logger.debug(f"Claude news cache hit for {ticker}")
        return cached["data"]

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set — skipping Claude news fetch")
        return _empty_result()

    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=30.0)

    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            tools=[{
                "type": "web_search_20250305",
                "name": "web_search",
            }],
            messages=[{
                "role": "user",
                "content": (
                    f"Search for recent news about {ticker} stock from the last 7 days. "
                    "Include earnings, analyst upgrades/downgrades, SEC filings, partnerships, product news.\n"
                    "Return ONLY this JSON, no other text:\n"
                    "{\n"
                    '  "headlines": [\n'
                    '    {\n'
                    '      "title": "headline text",\n'
                    '      "publisher": "publisher name",\n'
                    '      "hours_ago": 24,\n'
                    '      "type": "real",\n'
                    '      "sentiment": "bullish"\n'
                    "    }\n"
                    "  ],\n"
                    '  "has_sec_filing": false,\n'
                    '  "has_real_news": true,\n'
                    '  "catalyst_summary": "one sentence what is driving this stock"\n'
                    "}\n\n"
                    "Rules for type field:\n"
                    '- "sec" if it mentions 8-K, 10-Q, Form 4, SEC filing\n'
                    '- "real" if from Reuters, Bloomberg, CNBC, WSJ, Barrons, '
                    "MarketWatch, Seeking Alpha, Investopedia, Yahoo Finance\n"
                    '- "pr" if from PR Newswire, Globe Newswire, Business Wire\n'
                    '- "unknown" for everything else\n\n'
                    "Rules for sentiment:\n"
                    '- "bullish" if positive for stock price\n'
                    '- "bearish" if negative for stock price\n'
                    '- "neutral" if informational only\n\n'
                    "Return maximum 8 headlines, newest first.\n"
                    "Return empty headlines array if no news found.\n"
                    "NEVER return anything except the JSON object."
                ),
            }],
        )

        # Extract text blocks from response (web_search may return tool_use + text blocks)
        full_text = ""
        for block in response.content:
            if hasattr(block, "text"):
                full_text += block.text

        # Strip markdown fences if present
        clean = full_text.strip()
        if "```json" in clean:
            clean = clean.split("```json")[1].split("```")[0]
        elif "```" in clean:
            clean = clean.split("```")[1].split("```")[0]

        data = json.loads(clean.strip())

        headlines = data.get("headlines", [])

        # Calculate weighted_count using same weights as _build_news_detail
        weighted = 0.0
        for h in headlines:
            t = h.get("type", "unknown")
            h_ago = h.get("hours_ago", 0)
            weight = 1.5 if t == "sec" else 1.0 if t == "real" else 0.7 if t == "unknown" else 0.5
            if h_ago <= 24:
                weighted += weight * 1.0
            else:
                weighted += weight * 0.4

        headlines_24h = [h for h in headlines if h.get("hours_ago", 999) <= 24]
        headlines_2_7d = [h for h in headlines if 24 < h.get("hours_ago", 0) <= 168]

        result = {
            "headlines": headlines_24h,
            "headlines_7d": headlines,
            "has_sec_filing": data.get("has_sec_filing", False),
            "has_real_news": data.get("has_real_news", False),
            "catalyst_summary": data.get("catalyst_summary", ""),
            "yahoo_count_24h": len(headlines_24h),
            "finviz_count_24h": 0,
            "count_24h": len(headlines_24h),
            "total_count_24h": len(headlines_24h),
            "count_2_7d": len(headlines_2_7d),
            "count_7d": len(headlines),
            "weighted_count": round(weighted, 2),
            "error": False,
            "source": "claude_web_search",
        }

        logger.info(f"Claude news fetched for {ticker}: {len(headlines)} headlines, "
                    f"catalyst: {result['catalyst_summary'][:60]}")

        # Store in cache
        _news_cache[ticker] = {"data": result, "timestamp": now}
        return result

    except json.JSONDecodeError as e:
        logger.warning(f"Claude news JSON parse error for {ticker}: {e}")
        return _empty_result()
    except anthropic.AuthenticationError as e:
        logger.error(f"Claude news auth error for {ticker}: {e}")
        return _empty_result()
    except Exception as e:
        logger.warning(f"Claude news fetch error for {ticker}: {e}")
        return _empty_result()


def _empty_result() -> dict:
    return {
        "headlines": [],
        "headlines_7d": [],
        "has_sec_filing": False,
        "has_real_news": False,
        "catalyst_summary": "",
        "yahoo_count_24h": 0,
        "finviz_count_24h": 0,
        "count_24h": 0,
        "total_count_24h": 0,
        "count_2_7d": 0,
        "count_7d": 0,
        "weighted_count": 0.0,
        "error": True,
        "source": "claude_web_search",
    }


def clear_cache(ticker: str | None = None):
    """Clear news cache for a ticker or all tickers."""
    if ticker:
        _news_cache.pop(ticker.upper(), None)
    else:
        _news_cache.clear()
