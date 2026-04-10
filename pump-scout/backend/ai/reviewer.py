"""
AI Reviewer  —  backend/ai/reviewer.py
═══════════════════════════════════════
Analyzes past scan and journal outcomes to generate structured retrospective reviews.
READ-ONLY: does not modify any existing data.

Review types:
  DAILY              — what happened today (latest scan context)
  WEEKLY             — 7-day trade and setup review
  MISSED_OPPORTUNITY — movers not in journal or watchlist
  FALSE_POSITIVE     — journaled trades that hit stop / failed

Output shape:
{
  "review_type":      "DAILY | WEEKLY | MISSED_OPPORTUNITY | FALSE_POSITIVE_REVIEW",
  "summary":          "...",
  "what_worked":      [...],
  "what_failed":      [...],
  "missed_patterns":  [...],
  "suggested_focus":  [...],
  "confidence":       "LOW | MEDIUM | HIGH",
  "data_quality":     "SUFFICIENT | SPARSE | MINIMAL"
}
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

_MODEL    = "claude-haiku-4-5-20251001"
_FALLBACK = "claude-3-haiku-20240307"
_MAX_TOKENS = 600

_SYSTEM_PROMPT = """\
You are a trading systems analyst reviewing past scan and journal performance. \
Your job is to identify what worked, what failed, and what patterns were missed. \
Be specific and data-driven. Never fabricate data. \
If data is sparse, acknowledge it honestly. \
Respond ONLY with valid JSON — no markdown, no text outside the JSON."""


def _summarize_journal(entries: list[dict]) -> dict:
    """Compute basic stats from journal entries for the prompt."""
    if not entries:
        return {"count": 0}
    closed = [e for e in entries if e.get("status") in ("CLOSED", "STOPPED")]
    wins   = [e for e in closed if (e.get("final_pnl_pct") or 0) > 0]
    losses = [e for e in closed if (e.get("final_pnl_pct") or 0) <= 0]
    win_rate = round(len(wins) / len(closed) * 100, 1) if closed else 0
    avg_win  = round(sum(e.get("final_pnl_pct", 0) for e in wins) / max(len(wins), 1), 2)
    avg_loss = round(sum(e.get("final_pnl_pct", 0) for e in losses) / max(len(losses), 1), 2)
    tiers    = {}
    for e in closed:
        t = e.get("tier", "UNKNOWN")
        tiers[t] = tiers.get(t, 0) + 1

    winner_patterns = []
    for e in wins[:5]:
        winner_patterns.append({
            "symbol":      e.get("symbol"),
            "tier":        e.get("tier"),
            "gain_pct":    e.get("final_pnl_pct"),
            "wyckoff":     e.get("entry_wyckoff"),
            "exit_reason": e.get("exit_reason"),
        })
    loser_patterns = []
    for e in losses[:5]:
        loser_patterns.append({
            "symbol":      e.get("symbol"),
            "tier":        e.get("tier"),
            "loss_pct":    e.get("final_pnl_pct"),
            "wyckoff":     e.get("entry_wyckoff"),
            "exit_reason": e.get("exit_reason"),
        })

    return {
        "count":           len(entries),
        "closed":          len(closed),
        "open":            len(entries) - len(closed),
        "win_rate":        win_rate,
        "avg_win_pct":     avg_win,
        "avg_loss_pct":    avg_loss,
        "tier_distribution": tiers,
        "top_winners":     winner_patterns,
        "top_losers":      loser_patterns,
    }


def _summarize_candidates(candidates: list[dict]) -> dict:
    """Summarize scan candidates (control group) for review context."""
    if not candidates:
        return {"count": 0}
    tiers = {}
    has_outcome = [c for c in candidates if c.get("pct_5d") is not None]
    for c in candidates:
        t = c.get("tier", "UNKNOWN")
        tiers[t] = tiers.get(t, 0) + 1
    avg_5d = (
        round(sum(c.get("pct_5d", 0) for c in has_outcome) / len(has_outcome), 2)
        if has_outcome else None
    )
    strong = sorted(has_outcome, key=lambda c: c.get("pct_5d", 0), reverse=True)[:5]
    weak   = sorted(has_outcome, key=lambda c: c.get("pct_5d", 0))[:5]
    return {
        "count":          len(candidates),
        "with_outcomes":  len(has_outcome),
        "tier_distribution": tiers,
        "avg_5d_pct":     avg_5d,
        "strongest_5d":   [{"symbol": c["symbol"], "tier": c.get("tier"), "pct_5d": c.get("pct_5d")} for c in strong],
        "weakest_5d":     [{"symbol": c["symbol"], "tier": c.get("tier"), "pct_5d": c.get("pct_5d")} for c in weak],
    }


async def _call_claude(prompt: str, client) -> dict:
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
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                return json.loads(raw)
            except json.JSONDecodeError as e:
                logger.warning(f"Reviewer JSON parse error: {e}")
                return _fallback_review("DAILY", "JSON parse error")
            except Exception as e:
                name = type(e).__name__
                if "NotFound" in name:
                    break
                if "RateLimit" in name:
                    await asyncio.sleep(5)
                elif attempt == 0:
                    await asyncio.sleep(2)
                else:
                    logger.warning(f"Reviewer call failed [{model}]: {name}: {e}")
                    return _fallback_review("DAILY", str(name))
    return _fallback_review("DAILY", "all models failed")


def _fallback_review(review_type: str, reason: str) -> dict:
    return {
        "review_type":     review_type,
        "summary":         f"Review unavailable: {reason}",
        "what_worked":     [],
        "what_failed":     [],
        "missed_patterns": [],
        "suggested_focus": [],
        "confidence":      "LOW",
        "data_quality":    "MINIMAL",
        "generated_at":    datetime.utcnow().isoformat(),
    }


async def run_daily_review(
    journal_entries: list[dict],
    scan_candidates: list[dict],
    scan_summary: dict | None = None,
) -> dict:
    """Generate a daily review based on today's journal and scan data."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return _fallback_review("DAILY", "ANTHROPIC_API_KEY not set")

    j_sum = _summarize_journal(journal_entries)
    c_sum = _summarize_candidates(scan_candidates)
    data_quality = (
        "SUFFICIENT" if j_sum.get("closed", 0) >= 5
        else "SPARSE"   if j_sum.get("closed", 0) >= 2
        else "MINIMAL"
    )

    prompt = f"""Generate a DAILY review. Analyze the following data and respond with JSON only.

Journal summary (last 7 days):
{json.dumps(j_sum, indent=2)}

Scan candidate outcomes (recent):
{json.dumps(c_sum, indent=2)}

Scan context:
{json.dumps(scan_summary or {}, indent=2)}

Respond with this exact JSON structure:
{{
  "review_type": "DAILY",
  "summary": "<2-3 sentence overall assessment>",
  "what_worked": ["<specific setups or conditions that succeeded>"],
  "what_failed": ["<specific setups or conditions that failed>"],
  "missed_patterns": ["<patterns visible in hindsight that were not acted on>"],
  "suggested_focus": ["<1-3 actionable focus areas for next session>"],
  "confidence": "LOW | MEDIUM | HIGH",
  "data_quality": "{data_quality}"
}}

Be specific. Reference actual tiers, wyckoff states, or metrics when present in the data. If data is sparse, say so clearly."""

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key, timeout=30.0)
    except ImportError:
        return _fallback_review("DAILY", "anthropic not installed")

    result = await _call_claude(prompt, client)
    result["review_type"]  = "DAILY"
    result["generated_at"] = datetime.utcnow().isoformat()
    return result


async def run_weekly_review(
    journal_entries: list[dict],
    scan_candidates: list[dict],
) -> dict:
    """Generate a weekly review of performance patterns."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return _fallback_review("WEEKLY", "ANTHROPIC_API_KEY not set")

    j_sum = _summarize_journal(journal_entries)
    c_sum = _summarize_candidates(scan_candidates)
    data_quality = (
        "SUFFICIENT" if j_sum.get("closed", 0) >= 8
        else "SPARSE"   if j_sum.get("closed", 0) >= 3
        else "MINIMAL"
    )

    prompt = f"""Generate a WEEKLY performance review. Respond with JSON only.

Journal summary (last 30 days):
{json.dumps(j_sum, indent=2)}

Scan candidate pool (last 30 days):
{json.dumps(c_sum, indent=2)}

Respond with:
{{
  "review_type": "WEEKLY",
  "summary": "<3-4 sentence weekly assessment>",
  "what_worked": ["<what tier/setup types consistently produced positive outcomes>"],
  "what_failed": ["<what setup types or conditions consistently failed>"],
  "missed_patterns": ["<tickers or setups in scan that moved big but were not journaled>"],
  "suggested_focus": ["<2-4 strategic adjustments or focus areas for next week>"],
  "confidence": "LOW | MEDIUM | HIGH",
  "data_quality": "{data_quality}"
}}"""

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key, timeout=30.0)
    except ImportError:
        return _fallback_review("WEEKLY", "anthropic not installed")

    result = await _call_claude(prompt, client)
    result["review_type"]  = "WEEKLY"
    result["generated_at"] = datetime.utcnow().isoformat()
    return result


async def run_missed_opportunities(
    scan_candidates: list[dict],
    journal_entries: list[dict],
) -> dict:
    """Identify strong movers from the scan control group that were never journaled."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return _fallback_review("MISSED_OPPORTUNITY", "ANTHROPIC_API_KEY not set")

    journaled_syms = {e.get("symbol", "").upper() for e in journal_entries}
    # candidates with 5d outcome data, not journaled, sorted by pct_5d
    missed = [
        c for c in scan_candidates
        if c.get("pct_5d") is not None
        and c.get("symbol", "").upper() not in journaled_syms
    ]
    missed.sort(key=lambda c: c.get("pct_5d", 0), reverse=True)
    top_missed = missed[:15]

    if not top_missed:
        result = _fallback_review("MISSED_OPPORTUNITY", "no outcome data available yet")
        result["summary"] = "No outcome data available yet for missed opportunity analysis."
        return result

    missed_compact = [
        {
            "symbol":  c["symbol"],
            "tier":    c.get("tier"),
            "pct_5d":  c.get("pct_5d"),
            "vol_ratio": c.get("vol_ratio"),
            "wyckoff": c.get("wyckoff"),
        }
        for c in top_missed
    ]

    prompt = f"""Analyze these scan candidates that were NOT journaled but had strong 5-day outcomes.

Missed opportunities (sorted by 5d return):
{json.dumps(missed_compact, indent=2)}

Respond with JSON only:
{{
  "review_type": "MISSED_OPPORTUNITY",
  "summary": "<2-3 sentences on why these were likely missed>",
  "what_worked": ["<what was common in the best missed setups>"],
  "what_failed": ["<what in the scan process filtered them out prematurely>"],
  "missed_patterns": ["<recurring characteristics of missed movers>"],
  "suggested_focus": ["<1-3 suggestions to catch similar setups earlier>"],
  "confidence": "LOW | MEDIUM | HIGH",
  "data_quality": "SUFFICIENT"
}}"""

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key, timeout=30.0)
    except ImportError:
        return _fallback_review("MISSED_OPPORTUNITY", "anthropic not installed")

    result = await _call_claude(prompt, client)
    result["review_type"]  = "MISSED_OPPORTUNITY"
    result["generated_at"] = datetime.utcnow().isoformat()
    return result


async def run_failure_review(
    journal_entries: list[dict],
) -> dict:
    """Analyze journaled trades that hit stop loss or produced losses."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return _fallback_review("FALSE_POSITIVE_REVIEW", "ANTHROPIC_API_KEY not set")

    failures = [
        e for e in journal_entries
        if e.get("status") in ("CLOSED", "STOPPED")
        and (e.get("final_pnl_pct") or 0) < 0
    ]
    failures.sort(key=lambda e: e.get("final_pnl_pct", 0))

    if not failures:
        result = _fallback_review("FALSE_POSITIVE_REVIEW", "no failed trades found")
        result["summary"] = "No failed trades found in the journal yet."
        return result

    compact = [
        {
            "symbol":      e["symbol"],
            "tier":        e.get("tier"),
            "loss_pct":    e.get("final_pnl_pct"),
            "wyckoff":     e.get("entry_wyckoff"),
            "exit_reason": e.get("exit_reason"),
            "days_held":   e.get("days_held"),
        }
        for e in failures[:15]
    ]

    prompt = f"""Analyze these failed/stopped trades from the journal to identify failure patterns.

Failed trades:
{json.dumps(compact, indent=2)}

Respond with JSON only:
{{
  "review_type": "FALSE_POSITIVE_REVIEW",
  "summary": "<2-3 sentences on recurring failure themes>",
  "what_worked": ["<any partial successes or lessons from these failures>"],
  "what_failed": ["<specific technical or contextual reasons for failures>"],
  "missed_patterns": ["<warning signals that were present but ignored>"],
  "suggested_focus": ["<1-3 filter improvements to reduce false positives>"],
  "confidence": "LOW | MEDIUM | HIGH",
  "data_quality": "SUFFICIENT"
}}"""

    try:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=api_key, timeout=30.0)
    except ImportError:
        return _fallback_review("FALSE_POSITIVE_REVIEW", "anthropic not installed")

    result = await _call_claude(prompt, client)
    result["review_type"]  = "FALSE_POSITIVE_REVIEW"
    result["generated_at"] = datetime.utcnow().isoformat()
    return result
