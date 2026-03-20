"""
AI analysis of ticker setups using Claude via the Anthropic API.
"""
import asyncio
import json
import logging
import os
from typing import List

import anthropic

logger = logging.getLogger(__name__)

# Try newest model first, fall back to older if unavailable
MODELS = [
    "claude-haiku-4-5-20251001",
    "claude-3-5-haiku-20241022",
    "claude-3-haiku-20240307",
]


async def analyze_ticker(
    symbol: str,
    indicators: dict,
    regime: dict,
    score: dict,
) -> str:
    """
    Generate an AI analysis of a ticker's setup using Claude.
    Returns formatted analysis text.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("ANTHROPIC_API_KEY is not set — skipping AI analysis")
        return f"REGIME: {regime.get('state', 'NONE')} — AI key not configured\nVERDICT: WATCH — Set ANTHROPIC_API_KEY in Railway Variables."

    stealth = indicators.get("stealth", {})
    rsi_data = indicators.get("rsi", {})
    gap_data = indicators.get("gap", {})

    data_summary = {
        "symbol": symbol,
        "price": indicators.get("price"),
        "price_change_pct": indicators.get("price_change_pct"),
        "anomaly_ratio": indicators.get("anomaly_ratio"),
        "vol_z": indicators.get("vol_z"),
        "today_vol": indicators.get("today_vol"),
        "avg_vol_20": indicators.get("avg_vol_20"),
        "cmf": indicators.get("cmf"),
        "cmf_pctl": indicators.get("cmf_pctl"),
        "bb_squeeze": indicators.get("bb_squeeze"),
        "bb_sqz_bars": indicators.get("bb_sqz_bars"),
        "bb_pctl": indicators.get("bb_pctl"),
        "ema20": indicators.get("ema20"),
        "ema50": indicators.get("ema50"),
        "atr_pct": indicators.get("atr_pct"),
        "rsi": rsi_data.get("value"),
        "rsi_divergence": rsi_data.get("has_divergence"),
        "gap_type": gap_data.get("gap_type"),
        "gap_pct": gap_data.get("gap_pct"),
        "stealth_detected": stealth.get("is_stealth"),
        "stealth_score": stealth.get("stealth_score"),
        "stealth_vol_ratio": stealth.get("vol_ratio"),
        "wyckoff_state": regime.get("state"),
        "tr_high": regime.get("tr_high"),
        "tr_low": regime.get("tr_low"),
        "in_acc": regime.get("in_acc"),
        "in_dist": regime.get("in_dist"),
        "sc_detected": regime.get("sc"),
        "bc_detected": regime.get("bc"),
        "regime_confidence": regime.get("confidence"),
        "total_score": score.get("total_score"),
        "tier": score.get("tier"),
        "vol_score": score.get("vol_score"),
        "accum_score": score.get("accum_score"),
        "stealth_bonus": score.get("stealth_bonus"),
        "quiet_factor": score.get("quiet_factor"),
    }

    prompt = f"""You are an expert trading analyst specializing in Wyckoff methodology and small-cap momentum stocks.
Analyze this setup and respond in EXACTLY this format (be concise):

REGIME: [state] — [one sentence why]
PHASE: [Wyckoff A/B/C/D/E] — [what defines it now]
VOLUME: [what the volume anomaly means — absorption/climax/interest]
KEY LEVELS: TR High ${regime.get('tr_high', 'N/A')} | TR Low ${regime.get('tr_low', 'N/A')}
CATALYST NEEDED: [what price action would confirm the setup]
INVALIDATION: [what would kill the setup]
VERDICT: [STRONG BUY SETUP / WATCH / AVOID] — [2 sentence conclusion]

Data:
{json.dumps(data_summary, indent=2)}"""

    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=30.0)

    for model in MODELS:
        for attempt in range(2):
            try:
                response = await client.messages.create(
                    model=model,
                    max_tokens=400,
                    messages=[{"role": "user", "content": prompt}],
                )
                logger.info(f"AI analysis OK for {symbol} using {model}")
                return response.content[0].text
            except anthropic.RateLimitError:
                logger.warning(f"Rate limit hit for {symbol}, waiting 5s...")
                await asyncio.sleep(5)
            except anthropic.NotFoundError:
                logger.warning(f"Model {model} not found, trying next...")
                break  # try next model
            except anthropic.AuthenticationError as e:
                logger.error(f"Auth error — check ANTHROPIC_API_KEY: {e}")
                return f"REGIME: {regime.get('state', 'NONE')} — API key invalid\nVERDICT: WATCH — Check ANTHROPIC_API_KEY in Railway Variables."
            except Exception as e:
                logger.error(f"AI analysis failed for {symbol} [{model}] attempt {attempt+1}: {type(e).__name__}: {e}")
                if attempt == 0:
                    await asyncio.sleep(2)

    return f"REGIME: {regime.get('state', 'NONE')} — Analysis unavailable\nVERDICT: WATCH — Claude API call failed. Check Railway logs."


async def analyze_batch(results: List[dict]) -> List[dict]:
    """
    Analyze top 20 tickers by score concurrently (max 3 at a time).
    Adds ai_analysis field to each result dict.
    """
    top20 = results[:20]
    semaphore = asyncio.Semaphore(3)

    async def analyze_one(result: dict):
        async with semaphore:
            symbol = result["symbol"]
            try:
                analysis = await analyze_ticker(
                    symbol=symbol,
                    indicators=result.get("indicators", {}),
                    regime=result.get("regime", {}),
                    score=result.get("score", {}),
                )
                result["ai_analysis"] = analysis
                logger.info(f"AI analysis complete for {symbol}")
            except Exception as e:
                logger.error(f"Failed AI analysis for {symbol}: {e}")
                result["ai_analysis"] = None
            return result

    tasks = [analyze_one(r) for r in top20]
    await asyncio.gather(*tasks, return_exceptions=True)

    return top20
