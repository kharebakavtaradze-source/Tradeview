"""
Hype Monitor — AI Analyst (Claude Sonnet)
Generates JSON-structured analysis of hype vs price/volume divergence.
Results are cached per ticker for 45 minutes to limit API calls.
"""
import json
import logging
import os
from datetime import datetime, timezone, timedelta
from typing import Any

import anthropic

logger = logging.getLogger(__name__)

# 45-minute in-memory cache: {ticker: {"result": dict, "cached_at": datetime}}
_cache: dict[str, dict] = {}
_CACHE_TTL = timedelta(minutes=45)

_SYSTEM = (
    "You are a quantitative trading analyst specializing in social sentiment vs volume divergence. "
    "Analyze the data and respond ONLY with valid JSON — no explanation, no markdown fences."
)

_SCHEMA = {
    "summary": "1-2 sentence plain English summary",
    "signals": ["list of 1-3 key signals as short strings"],
    "divergence_interpretation": "what the divergence pattern means for the trade",
    "risk_level": "LOW | MEDIUM | HIGH",
    "recommendation": "WATCH | ENTER | AVOID | EXIT",
}


async def analyze(
    ticker: str,
    hype_score: dict[str, Any],
    velocity: dict[str, Any],
    divergences: list[dict[str, Any]],
    scan_result: dict[str, Any],
    news_detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Get AI analysis of hype/volume divergence for a ticker.
    Returns cached result if fresh (< 45 min).
    Falls back to a minimal dict on API failure.
    """
    # Check cache
    cached = _cache.get(ticker)
    if cached:
        age = datetime.now(timezone.utc) - cached["cached_at"]
        if age < _CACHE_TTL:
            return {**cached["result"], "from_cache": True}

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set — skipping hype AI analysis")
        return _fallback(ticker, hype_score, divergences)

    indicators = scan_result.get("indicators", {})
    score = scan_result.get("score", {})

    nd = news_detail or {}
    headlines = nd.get("headlines", [])
    news_lines = "\n".join(
        f"  [{h['hours_ago']}h ago] [{h['publisher']}] {h['title']} [{h['type'].upper()}]"
        for h in headlines[:5]
    ) or "  (none)"

    prompt = (
        f"Ticker: {ticker}\n"
        f"Scan tier: {score.get('tier', 'WATCH')} | Score: {score.get('total_score', 0):.0f}/100\n"
        f"Price change: {indicators.get('price_change_pct', 0):+.1f}% | "
        f"Volume anomaly: {indicators.get('anomaly_ratio', 0):.1f}x\n"
        f"Wyckoff state: {scan_result.get('regime', {}).get('state', 'NONE')}\n\n"
        f"HYPE DATA (24h):\n"
        f"  Hype index: {hype_score.get('hype_index', 0):.0f}/100 ({hype_score.get('hype_tier', 'COLD')})\n"
        f"  Mentions: {hype_score.get('mention_counts', {})}\n"
        f"  Velocity 2h: {velocity.get('combined_velocity_2h', 0):.2f}x\n"
        f"  Velocity 6h: {velocity.get('velocity_6h', 0):.2f}x\n\n"
        f"RECENT NEWS (last 7d):\n{news_lines}\n"
        f"  SEC filings detected: {'YES' if nd.get('has_sec_filing') else 'no'}\n"
        f"  Real news articles (24h): {nd.get('yahoo_count_24h', 0) + nd.get('finviz_count_24h', 0)}\n"
        f"  Press releases (0.5x weight): counted in weighted score\n\n"
        f"DIVERGENCES DETECTED: {[d['type'] for d in divergences] or 'none'}\n"
        f"{json.dumps([{'type': d['type'], 'desc': d['description']} for d in divergences], indent=2)}\n\n"
        f"Respond with JSON matching this schema:\n{json.dumps(_SCHEMA, indent=2)}"
    )

    try:
        client = anthropic.AsyncAnthropic(api_key=api_key, timeout=20.0)
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=350,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.strip()
        # Strip markdown fences if model added them
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text)
    except json.JSONDecodeError as e:
        logger.warning(f"Hype AI JSON parse error for {ticker}: {e}")
        result = _fallback(ticker, hype_score, divergences)
    except Exception as e:
        logger.warning(f"Hype AI analysis failed for {ticker}: {e}")
        result = _fallback(ticker, hype_score, divergences)

    # Cache result
    _cache[ticker] = {"result": result, "cached_at": datetime.now(timezone.utc)}
    return {**result, "from_cache": False}


def _fallback(ticker: str, hype_score: dict, divergences: list) -> dict:
    """Minimal result when AI is unavailable."""
    div_types = [d["type"] for d in divergences]
    return {
        "summary": f"Hype index {hype_score.get('hype_index', 0):.0f}/100. Divergences: {', '.join(div_types) or 'none'}.",
        "signals": div_types[:3] or ["no divergence"],
        "divergence_interpretation": "AI analysis unavailable.",
        "risk_level": "MEDIUM",
        "recommendation": "WATCH",
        "from_cache": False,
    }


def clear_cache(ticker: str | None = None):
    """Clear cache for a ticker or all tickers."""
    if ticker:
        _cache.pop(ticker, None)
    else:
        _cache.clear()
