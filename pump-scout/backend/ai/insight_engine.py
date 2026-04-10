"""
AI Insight Engine  —  backend/ai/insight_engine.py
════════════════════════════════════════════════════
Generates higher-level pattern observations and improvement suggestions
by studying historical scan candidates and journal outcomes.

READ-ONLY: does not modify any production logic.
All outputs are labeled as SUGGESTIONS / OBSERVATIONS only.

Output shape per insight:
{
  "insight_type":       "PATTERN | FILTER_WARNING | MISSED_EDGE | BEHAVIORAL | MODEL_NOTE",
  "title":              "...",
  "description":        "...",
  "evidence":           [...],
  "suggested_experiment":"...",
  "confidence":         "LOW | MEDIUM | HIGH"
}
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

_MODEL    = "claude-haiku-4-5-20251001"
_FALLBACK = "claude-3-haiku-20240307"
_MAX_TOKENS = 700

_SYSTEM_PROMPT = """\
You are a quantitative research analyst studying a technical scan system's \
historical performance. Your role is to surface non-obvious patterns, \
identify potential filter improvements, and highlight missed edges. \
You do NOT have access to live markets. \
Never make investment recommendations. \
All outputs are advisory suggestions, not production changes. \
Respond ONLY with valid JSON — no markdown, no prose outside the JSON."""


def _compute_pattern_stats(candidates: list[dict], journal: list[dict]) -> dict:
    """
    Build a compact, token-efficient stats block from candidates + journal.
    This is what gets sent to Claude.
    """
    # Candidate outcome breakdown by tier
    tier_stats: dict[str, dict] = {}
    for c in candidates:
        tier = c.get("tier", "UNKNOWN")
        if tier not in tier_stats:
            tier_stats[tier] = {"count": 0, "pct_5d_sum": 0, "with_5d": 0}
        tier_stats[tier]["count"] += 1
        p5 = c.get("pct_5d")
        if p5 is not None:
            tier_stats[tier]["pct_5d_sum"] += p5
            tier_stats[tier]["with_5d"]    += 1

    tier_summary = {}
    for t, s in tier_stats.items():
        avg = round(s["pct_5d_sum"] / s["with_5d"], 2) if s["with_5d"] else None
        tier_summary[t] = {"count": s["count"], "avg_5d_pct": avg, "with_outcomes": s["with_5d"]}

    # Wyckoff state breakdown
    wyckoff_stats: dict[str, dict] = {}
    for c in candidates:
        w = c.get("wyckoff", "UNKNOWN") or "UNKNOWN"
        if w not in wyckoff_stats:
            wyckoff_stats[w] = {"count": 0, "pct_5d_sum": 0, "with_5d": 0}
        wyckoff_stats[w]["count"] += 1
        p5 = c.get("pct_5d")
        if p5 is not None:
            wyckoff_stats[w]["pct_5d_sum"] += p5
            wyckoff_stats[w]["with_5d"]    += 1

    wyckoff_summary = {}
    for w, s in wyckoff_stats.items():
        avg = round(s["pct_5d_sum"] / s["with_5d"], 2) if s["with_5d"] else None
        wyckoff_summary[w] = {"count": s["count"], "avg_5d_pct": avg}

    # Journal closed trade patterns
    closed = [e for e in journal if e.get("status") in ("CLOSED", "STOPPED")]
    wins   = [e for e in closed if (e.get("final_pnl_pct") or 0) > 0]
    losses = [e for e in closed if (e.get("final_pnl_pct") or 0) <= 0]

    tier_journal: dict[str, dict] = {}
    for e in closed:
        t = e.get("tier", "UNKNOWN")
        if t not in tier_journal:
            tier_journal[t] = {"trades": 0, "wins": 0, "total_pnl": 0}
        tier_journal[t]["trades"]    += 1
        tier_journal[t]["total_pnl"] += (e.get("final_pnl_pct") or 0)
        if (e.get("final_pnl_pct") or 0) > 0:
            tier_journal[t]["wins"] += 1

    tier_journal_summary = {
        t: {
            "trades":   s["trades"],
            "win_rate": round(s["wins"] / s["trades"] * 100, 1) if s["trades"] else 0,
            "avg_pnl":  round(s["total_pnl"] / s["trades"], 2) if s["trades"] else 0,
        }
        for t, s in tier_journal.items()
    }

    # High-vol candidates that moved big (potential filter gaps)
    big_movers_not_journaled = [
        {"symbol": c["symbol"], "tier": c.get("tier"), "pct_5d": c.get("pct_5d"), "vol_ratio": c.get("vol_ratio")}
        for c in sorted(candidates, key=lambda x: x.get("pct_5d") or 0, reverse=True)
        if (c.get("pct_5d") or 0) > 10
        and c["symbol"] not in {e["symbol"] for e in journal}
    ][:10]

    return {
        "total_candidates":     len(candidates),
        "total_journal":        len(journal),
        "journal_closed":       len(closed),
        "journal_win_rate":     round(len(wins) / max(len(closed), 1) * 100, 1),
        "tier_scan_outcomes":   tier_summary,
        "wyckoff_outcomes":     wyckoff_summary,
        "tier_journal_outcomes":tier_journal_summary,
        "big_movers_not_journaled": big_movers_not_journaled,
    }


async def run_insight_engine(
    scan_candidates: list[dict],
    journal_entries: list[dict],
    *,
    max_insights: int = 5,
) -> list[dict]:
    """
    Generate pattern-level insights from historical data.
    Returns a list of insight dicts. Does NOT modify any production data.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("Insight Engine: ANTHROPIC_API_KEY not set — returning empty")
        return []

    if len(scan_candidates) < 10 and len(journal_entries) < 3:
        logger.info("Insight Engine: insufficient data, skipping")
        return [_minimal_insight()]

    stats = _compute_pattern_stats(scan_candidates, journal_entries)

    prompt = f"""You are studying a technical scan system's historical performance data.
Generate {max_insights} high-quality insights about patterns, filter gaps, and improvement opportunities.

Historical statistics:
{json.dumps(stats, indent=2)}

Respond with JSON only — a list of insight objects:
[
  {{
    "insight_type": "PATTERN | FILTER_WARNING | MISSED_EDGE | BEHAVIORAL | MODEL_NOTE",
    "title": "<short title (10 words max)>",
    "description": "<2-3 sentence description with specific references to the data>",
    "evidence": ["<data point or observation supporting this insight>"],
    "suggested_experiment": "<one specific, safe, testable suggestion — NOT a production change>",
    "confidence": "LOW | MEDIUM | HIGH"
  }}
]

insight_type guide:
- PATTERN: recurring statistical pattern in outcomes
- FILTER_WARNING: current filter may be too strict or too loose
- MISSED_EDGE: category of setups being consistently under-captured
- BEHAVIORAL: human behavioral pattern (timing, entry sizing, exits)
- MODEL_NOTE: observation about model/scan calibration

Rules:
- Reference specific tiers, wyckoff states, pct values from the data
- If data is sparse (few closed trades), confidence must be LOW
- Do NOT suggest changing production scoring or thresholds directly
- suggested_experiment must be safe, small-scale, and observable
- Produce exactly {max_insights} insights"""

    prompt = prompt.replace('\u2028', '\n').replace('\u2029', '\n')

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key, timeout=35.0)
    except ImportError:
        logger.error("anthropic not installed")
        return []

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
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                insights = json.loads(raw)
                if not isinstance(insights, list):
                    insights = [insights]
                ts = datetime.utcnow().isoformat()
                for ins in insights:
                    ins["generated_at"] = ts
                logger.info(f"Insight Engine: generated {len(insights)} insights")
                return insights
            except json.JSONDecodeError as e:
                logger.warning(f"Insight Engine JSON parse error: {e}")
                return []
            except Exception as e:
                name = type(e).__name__
                if "NotFound" in name:
                    break
                import asyncio
                if "RateLimit" in name:
                    await asyncio.sleep(5)
                elif attempt == 0:
                    await asyncio.sleep(2)
                else:
                    logger.warning(f"Insight Engine failed [{model}]: {name}: {e}")
                    return []
    return []


def _minimal_insight() -> dict:
    return {
        "insight_type":        "MODEL_NOTE",
        "title":               "Insufficient data for pattern analysis",
        "description":         "The system needs more closed trades and scan outcomes before meaningful patterns can be identified. Continue journaling entries and allow the scan to accumulate more historical data.",
        "evidence":            ["Fewer than 10 scan candidates with outcomes or fewer than 3 closed journal trades"],
        "suggested_experiment":"Journal at least 10 trades to completion, then re-run insight analysis.",
        "confidence":          "LOW",
        "generated_at":        datetime.utcnow().isoformat(),
    }
