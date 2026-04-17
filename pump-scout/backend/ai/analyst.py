"""
AI Analyst  —  backend/ai/analyst.py
═══════════════════════════════════════
Analyzes current scan candidates and generates structured commentary.
READ-ONLY: does not modify any scan result, score, or tier.

Output shape per ticker:
{
  "verdict":         "STRONG_WATCH | WATCH | EARLY_INTEREST | LOW_QUALITY | EXTENDED",
  "quality_view":    "EARLY | CONFIRMED | MIXED | WEAK | LATE",
  "strengths":       [...],
  "weaknesses":      [...],
  "what_confirms":   [...],
  "what_invalidates":[...],
  "explanation":     "...",
  "confidence":      "LOW | MEDIUM | HIGH"
}
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

_MODEL   = "claude-haiku-4-5-20251001"
_FALLBACK = "claude-3-haiku-20240307"
_MAX_TOKENS  = 500
_BATCH_SIZE  = 25          # max candidates per run
_CONCURRENCY = 4           # simultaneous Claude calls


def _build_context(r: dict) -> dict:
    """Extract a compact, token-efficient context dict from a scan result."""
    ind = r.get("indicators") or {}
    sc  = r.get("score")      or {}
    obv = ind.get("obv")      or {}
    rsi = ind.get("rsi")      or {}
    return {
        "symbol":           r.get("symbol"),
        "price":            r.get("price"),
        "sector":           r.get("sector", "Unknown"),
        "tier":             sc.get("tier"),
        "total_score":      sc.get("total_score"),
        # volume
        "anomaly_ratio":    ind.get("anomaly_ratio"),
        "cmf_pctl":         ind.get("cmf_pctl"),
        "obv_strength":     obv.get("obv_strength"),
        "obv_divergence":   obv.get("obv_divergence"),
        # ribbon / momentum
        "ribbon_compression":     ind.get("ribbon_compression"),
        "bullish_stack":          ind.get("bullish_stack"),
        "bearish_stack":          ind.get("bearish_stack"),
        "compression_and_bullish":ind.get("compression_and_bullish"),
        "ema_spread_pct":         ind.get("ema_spread_pct"),
        "ema8_slope":             ind.get("ema8_slope"),
        "bb_sqz_bars":            ind.get("bb_sqz_bars"),
        "bb_squeeze":             ind.get("bb_squeeze"),
        # momentum
        "rs_score":         ind.get("rs_score"),
        "rsi":              rsi.get("value"),
        "rsi_divergence":   rsi.get("has_divergence"),
        "price_change_pct": ind.get("price_change_pct"),
        # regime
        "wyckoff_state":    (r.get("regime") or {}).get("state"),
        # ignition (may not be present for main scan results)
        "ignition_signal":  r.get("ignition_signal"),
        "ignition_quality": r.get("ignition_quality"),
    }


_SYSTEM_PROMPT = """\
You are a professional equity analyst specializing in Wyckoff methodology \
and small-cap momentum setups. Your role is to interpret technical scan data \
and produce structured, actionable commentary. \
Be concise and direct. Use the exact JSON format requested. \
Never invent data not present in the input."""


def _user_prompt(ctx: dict, research_context: str | None = None) -> str:
    context_block = ""
    if research_context:
        context_block = (
            "\nPRIOR QUANTITATIVE RESEARCH (Raw Pattern Study findings — apply when weighting signals):\n"
            f"{research_context}\n"
        )
    return f"""Analyze this scan candidate and respond ONLY with valid JSON — no markdown, no prose outside the JSON.
{context_block}
Input data:
{json.dumps(ctx, indent=2)}

Respond with this exact JSON structure:
{{
  "verdict": "STRONG_WATCH | WATCH | EARLY_INTEREST | LOW_QUALITY | EXTENDED",
  "quality_view": "EARLY | CONFIRMED | MIXED | WEAK | LATE",
  "strengths": ["<1-4 concise bullet points>"],
  "weaknesses": ["<1-4 concise bullet points>"],
  "what_confirms": ["<1-3 specific price/volume events that would confirm>"],
  "what_invalidates": ["<1-3 specific events that would kill the setup>"],
  "explanation": "<2-3 sentence natural-language summary>",
  "confidence": "LOW | MEDIUM | HIGH"
}}

Rules:
- STRONG_WATCH: ribbon+volume+sector all aligned, ignition confirmed
- WATCH: 2 of 3 layers aligned, setup building
- EARLY_INTEREST: only 1 signal present, needs confirmation
- LOW_QUALITY: conflicting signals or weak structure
- EXTENDED: setup may be too late (RSI extended, volume climax)
- quality_view EARLY: pre-ignition compression
- quality_view CONFIRMED: ignition underway
- quality_view MIXED: partial confirmation
- quality_view WEAK: structure not yet developed
- quality_view LATE: already moved significantly"""


async def _analyze_one(r: dict, client, research_context: str | None = None) -> dict:
    """Call Claude for one ticker, return the structured analysis dict."""
    symbol = r.get("symbol", "?")
    ctx    = _build_context(r)
    prompt = _user_prompt(ctx, research_context)
    prompt = prompt.replace('\u2028', '\n').replace('\u2029', '\n')

    for model in (_MODEL, _FALLBACK):
        for attempt in range(2):
            try:
                resp = await client.messages.create(
                    model=model,
                    max_tokens=_MAX_TOKENS,
                    system=_SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": prompt}],
                )
                raw = resp.content[0].text.strip()
                # Strip accidental markdown fences
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                analysis = json.loads(raw)
                analysis["symbol"]     = symbol
                analysis["analyzed_at"] = datetime.utcnow().isoformat()
                logger.info(f"AI analyst OK: {symbol} → {analysis.get('verdict')}")
                return analysis
            except json.JSONDecodeError as e:
                logger.warning(f"AI analyst JSON parse failed for {symbol}: {e}")
                return _fallback(symbol, "JSON parse error")
            except Exception as e:
                name = type(e).__name__
                if "NotFound" in name:
                    break  # try next model
                if "RateLimit" in name:
                    await asyncio.sleep(5)
                elif attempt == 0:
                    await asyncio.sleep(2)
                else:
                    logger.warning(f"AI analyst failed for {symbol} [{model}]: {name}: {e}")
                    return _fallback(symbol, str(name))

    return _fallback(symbol, "all models failed")


def _fallback(symbol: str, reason: str) -> dict:
    return {
        "symbol":          symbol,
        "verdict":         "WATCH",
        "quality_view":    "MIXED",
        "strengths":       [],
        "weaknesses":      [f"AI analysis unavailable: {reason}"],
        "what_confirms":   [],
        "what_invalidates":[],
        "explanation":     "AI analysis could not be completed for this ticker.",
        "confidence":      "LOW",
        "analyzed_at":     datetime.utcnow().isoformat(),
    }


async def run_analyst(
    scan_results: list[dict],
    *,
    max_tickers: int = _BATCH_SIZE,
    research_context: str | None = None,
) -> list[dict]:
    """
    Analyze top N candidates from the current scan.
    Returns a list of structured analysis dicts.
    Does NOT modify the input scan_results.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("AI Analyst: ANTHROPIC_API_KEY not set — returning empty analysis")
        return []

    # Sort by total_score descending, take top N
    ranked = sorted(
        scan_results,
        key=lambda r: (r.get("score") or {}).get("total_score") or 0,
        reverse=True,
    )[:max_tickers]

    if not ranked:
        return []

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key, timeout=30.0)
    except ImportError:
        logger.error("anthropic package not installed")
        return []

    semaphore = asyncio.Semaphore(_CONCURRENCY)

    async def bounded(r):
        async with semaphore:
            return await _analyze_one(r, client, research_context)

    results = await asyncio.gather(*[bounded(r) for r in ranked], return_exceptions=True)

    output = []
    for r, res in zip(ranked, results):
        if isinstance(res, Exception):
            output.append(_fallback(r.get("symbol", "?"), str(res)))
        else:
            output.append(res)

    return output
