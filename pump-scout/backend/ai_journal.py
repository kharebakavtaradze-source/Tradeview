"""
AI Trading Journal — $500 virtual account.

Two-agent architecture:
  1. generate_trade_lesson()  — Sonnet 4.6, runs after each trade closes.
     Produces structured lessons: what worked, what failed, key takeaway.

  2. run_journal_session()    — Opus 4.7 with adaptive thinking, main decisions.
     Reads scan, lessons, pattern memory, blacklist → BUY/SELL decisions.

Strategy grounded in R154–R157 research:
  Entry:  PRIME_BUY + ATS_PRIME/SETUP + readiness HOT/WARM + OBV_ACCUM
  Exit:   +30% target | –12% stop | tier→SKIP with risk flags | 15-day time-stop
  Sizing: 18% of capital per position, max 5 open, min $50 / max $100
"""
import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone

import anthropic
import httpx

from database import (
    close_ai_journal_position,
    get_ai_journal_entries,
    get_ai_journal_positions,
    get_ai_journal_state,
    get_ai_performance_stats,
    get_blacklisted_patterns,
    get_pattern_memory,
    get_pending_backfill,
    get_recent_signal_outcomes,
    get_trade_lessons,
    fill_signal_returns,
    open_ai_journal_position,
    remove_signal_blacklist,
    save_ai_journal_entry,
    save_signal_outcomes,
    save_trade_lesson,
    update_ai_journal_capital,
    upsert_pattern_memory,
    upsert_signal_blacklist,
)

logger = logging.getLogger(__name__)

_YAHOO_V8    = "https://query1.finance.yahoo.com/v8/finance/chart"
_HEADERS     = {"User-Agent": "Mozilla/5.0"}

MAX_POSITIONS = 5
STOP_PCT      = 0.12   # –12% stop
TARGET_PCT    = 0.30   # +30% primary target
POSITION_SIZE = 0.18   # 18% of capital per position

_MODEL_MAIN   = "claude-opus-4-7"      # main decisions — thinking enabled
_MODEL_LESSON = "claude-sonnet-4-6"    # trade lessons  — fast, focused


# ── Price fetching ─────────────────────────────────────────────────────────────

async def _fetch_price(symbol: str) -> float | None:
    url = f"{_YAHOO_V8}/{symbol.upper()}"
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=_HEADERS) as c:
            r = await c.get(url, params={"interval": "1d", "range": "1d"})
            if r.status_code == 200:
                meta = r.json().get("chart", {}).get("result", [{}])[0].get("meta", {})
                p = meta.get("regularMarketPrice") or meta.get("previousClose")
                return float(p) if p else None
    except Exception as e:
        logger.debug(f"price fetch {symbol}: {e}")
    return None


# ── Market context ─────────────────────────────────────────────────────────────

async def _fetch_market_context() -> dict:
    _empty = {"spy_1d_pct": None, "spy_5d_pct": None, "vix": None, "market_mood": "UNKNOWN"}
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=_HEADERS) as c:
            spy_r, vix_r = await asyncio.gather(
                c.get(f"{_YAHOO_V8}/SPY",  params={"interval": "1d", "range": "5d"}),
                c.get(f"{_YAHOO_V8}/^VIX", params={"interval": "1d", "range": "5d"}),
                return_exceptions=True,
            )
        spy_1d = spy_5d = vix_val = None
        if not isinstance(spy_r, Exception) and spy_r.status_code == 200:
            spy_chart = spy_r.json().get("chart", {}).get("result", [])
            if spy_chart:
                closes = [c for c in spy_chart[0].get("indicators", {})
                          .get("quote", [{}])[0].get("close", []) if c is not None]
                if len(closes) >= 2:
                    spy_1d = round((closes[-1] / closes[-2] - 1) * 100, 2)
                if len(closes) >= 5:
                    spy_5d = round((closes[-1] / closes[0] - 1) * 100, 2)
        if not isinstance(vix_r, Exception) and vix_r.status_code == 200:
            vix_chart = vix_r.json().get("chart", {}).get("result", [])
            if vix_chart:
                meta = vix_chart[0].get("meta", {})
                vix_val = meta.get("regularMarketPrice") or meta.get("previousClose")
                if vix_val:
                    vix_val = round(float(vix_val), 2)
        if spy_1d is not None and vix_val is not None:
            if spy_1d > 0.5 and vix_val < 20:
                mood = "BULL"
            elif spy_1d < -0.5 or vix_val > 25:
                mood = "BEAR"
            else:
                mood = "NEUTRAL"
        else:
            mood = "UNKNOWN"
        return {"spy_1d_pct": spy_1d, "spy_5d_pct": spy_5d, "vix": vix_val, "market_mood": mood}
    except Exception as e:
        logger.debug(f"_fetch_market_context: {e}")
        return _empty


# ── JSON extraction helper ─────────────────────────────────────────────────────

def _extract_json(text: str) -> dict:
    """Extract JSON from Claude response, handling markdown fences and thinking blocks."""
    text = text.strip()
    # Strip markdown code fences
    if "```" in text:
        m = re.search(r"```(?:json)?\s*([\s\S]+?)```", text)
        if m:
            text = m.group(1).strip()
    # Find outermost { ... }
    start = text.find("{")
    end   = text.rfind("}")
    if start != -1 and end != -1:
        text = text[start:end + 1]
    return json.loads(text)


# ── Signal outcome recording ───────────────────────────────────────────────────

async def record_scan_signals(scan_results: list[dict]) -> int:
    """Save every PRIME_BUY / HIGH_CONF_BUY signal for forward-return tracking."""
    try:
        today   = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        signals = []
        for r in scan_results:
            tier = r.get("demand_composite_tier")
            if tier not in ("PRIME_BUY", "HIGH_CONF_BUY"):
                continue
            signals.append({
                "symbol":          r.get("symbol", ""),
                "signal_date":     today,
                "tier":            tier,
                "score":           r.get("demand_composite_score"),
                "ats_signal":      r.get("ats_signal"),
                "readiness_tier":  r.get("readiness_tier"),
                "flow_signals":    r.get("flow_signals", []),
                "flow_risks":      r.get("flow_risks", []),
                "risk_flags":      r.get("demand_risk_flags", []),
                "price_at_signal": r.get("price"),
            })
        if signals:
            return await save_signal_outcomes(signals)
        return 0
    except Exception as e:
        logger.debug(f"record_scan_signals: {e}")
        return 0


# ── Forward return backfill ────────────────────────────────────────────────────

async def backfill_forward_returns() -> dict:
    """Fill 3/7/14-day forward returns for signals older than 3 days."""
    pending    = await get_pending_backfill(min_age_days=3, limit=60)
    backfilled = 0
    errors     = 0
    for row in pending:
        try:
            symbol      = row["symbol"]
            sig_date    = datetime.strptime(row["signal_date"], "%Y-%m-%d").date()
            price_entry = row.get("price_at_signal")
            if not price_entry:
                continue
            async with httpx.AsyncClient(timeout=15.0, headers=_HEADERS) as c:
                r = await c.get(f"{_YAHOO_V8}/{symbol.upper()}",
                                params={"interval": "1d", "range": "30d"})
            if r.status_code != 200:
                errors += 1
                continue
            chart = r.json().get("chart", {}).get("result", [])
            if not chart:
                errors += 1
                continue
            timestamps = chart[0].get("timestamp", [])
            closes     = chart[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
            bars = sorted(
                [(datetime.utcfromtimestamp(ts).date(), cl)
                 for ts, cl in zip(timestamps, closes) if cl is not None],
                key=lambda x: x[0],
            )
            future = [(d, cl) for d, cl in bars if d > sig_date]

            def nth(n):
                return future[n - 1][1] if len(future) >= n else (future[-1][1] if future else None)

            p3, p7, p14 = nth(3), nth(7), nth(14)
            gain = lambda p: round((p / price_entry - 1) * 100, 2) if p else None
            g3, g7, g14 = gain(p3), gain(p7), gain(p14)
            w14  = future[:14]
            mx   = round((max(cl for _, cl in w14) / price_entry - 1) * 100, 2) if w14 else None
            if   mx is not None and mx >= 20:  lbl = "WIN_STRONG"
            elif g7 is not None and g7 >= 8:   lbl = "WIN"
            elif g14 is not None and g14 <= -8: lbl = "LOSS"
            else:                               lbl = "FLAT"
            await fill_signal_returns(row["id"], {
                "price_3d": p3, "price_7d": p7, "price_14d": p14,
                "gain_3d": g3,  "gain_7d": g7,  "gain_14d": g14,
                "max_gain_14d": mx, "outcome_label": lbl,
            })
            backfilled += 1
        except Exception as e:
            logger.debug(f"backfill ({row.get('symbol')}): {e}")
            errors += 1
    return {"backfilled": backfilled, "errors": errors}


# ── Agent 1: Trade Lesson (Sonnet 4.6) ────────────────────────────────────────

_LESSON_SYSTEM = """\
You are a trading coach analyzing a completed virtual trade.
Given entry signals and exit result, write a concise structured lesson.
Focus on which specific signals were predictive vs noise.
Respond with JSON ONLY — no prose outside the JSON object.
"""

async def generate_trade_lesson(position: dict) -> dict | None:
    """
    Sonnet 4.6 mini-session. Called after each trade closes.
    Returns a structured lesson dict or None on failure.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    prompt = json.dumps({
        "symbol":        position.get("symbol"),
        "entry_price":   position.get("entry_price"),
        "exit_price":    position.get("exit_price"),
        "pnl_pct":       position.get("pnl_pct"),
        "exit_reason":   position.get("exit_reason"),
        "days_held":     position.get("days_held", 0),
        "scan_tier":     position.get("scan_tier"),
        "ats_signal":    position.get("ats_signal"),
        "readiness_tier": position.get("readiness_tier"),
        "flow_signals":  position.get("flow_signals_entry") or [],
        "entry_rationale": position.get("entry_rationale"),
    }, indent=2)
    try:
        client = anthropic.AsyncAnthropic(api_key=api_key, timeout=30.0)
        resp   = await client.messages.create(
            model      = _MODEL_LESSON,
            max_tokens = 600,
            system     = _LESSON_SYSTEM,
            messages   = [{"role": "user", "content": (
                f"Analyze this closed trade and produce a lesson.\n\n{prompt}\n\n"
                "Respond with JSON:\n"
                '{"what_worked":"...","what_failed":"...","lesson":"1-sentence takeaway",'
                '"confidence":"HIGH|MEDIUM|LOW","tags":["tag1"]}'
            )}],
        )
        parsed = _extract_json(resp.content[0].text)
        return parsed
    except Exception as e:
        logger.debug(f"generate_trade_lesson ({position.get('symbol')}): {e}")
        return None


# ── Agent 2: Main Journal Session (Opus 4.7 + adaptive thinking) ──────────────

_SYSTEM = """\
You are the AI Trading Journal for a $500 virtual paper-trading account.
You operate on the Demand Scanner's research-backed signal stack (R154–R157).
You have access to persistent memory: trade lessons, pattern memory, and a signal blacklist.

=== STRATEGY RULES (NON-NEGOTIABLE) ===

ENTRY: All of the following must be true:
  1. demand_composite_tier == "PRIME_BUY" (score ≥ 13)
  2. ats_signal in ["ATS_PRIME", "ATS_SETUP"]
  3. readiness_tier in ["HOT", "WARM"]
  4. No hard risk flags: dv_illiquid, atr_extreme, overheated_expansion, price_gt25
  5. Price $0.50–$15
  6. Open positions < 5
  7. Cash available ≥ $50
  8. Pattern NOT in active blacklist

SIZING: 18% of capital (min $50, max $100) per position
STOP:   –12% from entry
TARGET: +30% from entry
BOOST (higher conviction, same rules still apply): OBV_ACCUM + LOWER_WICK_ABSORB + ATS_PRIME

EXIT:
  - current_pnl_pct ≤ –12%              → SELL, reason: STOP_HIT
  - current_pnl_pct ≥ +30%              → SELL, reason: TARGET_HIT
  - days_held ≥ 15 with pnl_pct < +5%   → SELL, reason: TIME_STOP
  - tier dropped to SKIP + risk flags    → SELL, reason: SIGNAL_LOST
  - current_pnl_pct ≥ +20%, days_held ≥ 10 → consider early exit

RISK:
  - Never add to a losing position
  - No duplicate symbols (skip BUY if already OPEN)
  - HIGH_CONF_BUY = watchlist only, never enter directly
  - Bear market (market_mood == "BEAR"): raise entry bar to ATS_PRIME only

=== MEMORY LAYERS ===

trade_lessons: Structured lessons from each closed trade. Read them carefully.
  Each lesson has: what_worked, what_failed, lesson (1-sentence takeaway), confidence.
  Let high-confidence lessons reinforce or modify your entry criteria.

pattern_memory: Historical win rates per signal combo (tier|ats|readiness).
  Use this to rank candidates by pattern win rate, not just score.

signal_blacklist: Patterns you previously decided to avoid.
  DO NOT enter a trade if its pattern_key matches an active blacklist entry.

recent_signal_outcomes: What actually happened (3/7/14d) after past signals.
  Look for patterns: do OBV_ACCUM signals actually deliver? Do FLAT outcomes cluster?

=== RESPONSE FORMAT — JSON ONLY ===
{
  "decisions": [
    {
      "action": "BUY"|"SELL"|"HOLD"|"WATCH",
      "symbol": "TICKER",
      "price": 2.50,
      "shares": 40,
      "cost": 100.00,
      "target": 3.25,
      "stop": 2.20,
      "rationale": "Specific signals + lesson references",
      "position_id": null
    }
  ],
  "journal_entry": "4-5 paragraphs: (1) scan overview, (2) decisions + reasoning, (3) portfolio state, (4) what lessons/patterns shaped decisions today, (5) what to watch next session.",
  "strategy_update": "1-2 sentences of refinement, or null.",
  "pattern_insights": [
    {
      "pattern_key": "PRIME_BUY|ATS_PRIME|HOT",
      "n_observations": 4,
      "win_rate": 0.75,
      "avg_gain_7d": 14.2,
      "notes": "What this pattern means and when it fires best."
    }
  ],
  "blacklist_updates": [
    {
      "action": "BLOCK"|"UNBLOCK",
      "pattern_key": "HIGH_CONF_BUY|ATS_WATCH|COOL",
      "reason": "Why block/unblock",
      "suspend_days": 30
    }
  ]
}
"""


async def run_journal_session(scan_results: list[dict]) -> dict:
    """
    Main AI Journal session using Opus 4.7 with adaptive thinking.
    Called after each demand scan run.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not configured"}

    state     = await get_ai_journal_state()
    capital   = state["capital"]
    positions = await get_ai_journal_positions("OPEN")
    history   = await get_ai_journal_positions("CLOSED")
    entries   = await get_ai_journal_entries(5)

    # ── Auto-close stops / targets, generate lesson for each ─────────────────
    auto_closed = []
    now_utc     = datetime.now(timezone.utc)

    for pos in positions:
        price = await _fetch_price(pos["symbol"])
        if price is None:
            continue
        pnl_pct = (price / pos["entry_price"] - 1) * 100 if pos["entry_price"] else 0
        reason  = None
        if pnl_pct <= -STOP_PCT * 100:
            reason = "STOP_HIT"
        elif pnl_pct >= TARGET_PCT * 100:
            reason = "TARGET_HIT"
        if reason:
            result = await close_ai_journal_position(pos["id"], price, reason)
            if result:
                closed_pos = {**pos, "exit_price": price, "exit_reason": reason, **result}
                auto_closed.append(closed_pos)
                # Generate a structured lesson for this closed trade
                lesson_data = await generate_trade_lesson(closed_pos)
                if lesson_data:
                    await save_trade_lesson({
                        "position_id":   pos["id"],
                        "symbol":        pos["symbol"],
                        "pnl_pct":       result.get("pnl_pct"),
                        "exit_reason":   reason,
                        "scan_tier":     pos.get("scan_tier"),
                        "ats_signal":    pos.get("ats_signal"),
                        "readiness_tier": pos.get("readiness_tier"),
                        **lesson_data,
                    })
                capital += price * pos["shares"]

    # Refresh after auto-closes
    positions = await get_ai_journal_positions("OPEN")

    # ── Enrich open positions with live price, P&L, days held ────────────────
    enriched = []
    for pos in positions:
        cp = await _fetch_price(pos["symbol"])
        pnl = round((cp / pos["entry_price"] - 1) * 100, 2) if cp and pos["entry_price"] else None
        days = 0
        raw  = pos.get("entry_date")
        if raw:
            try:
                dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                days = (now_utc - dt).days
            except Exception:
                pass
        enriched.append({**pos, "current_price": cp, "current_pnl_pct": pnl, "days_held": days})

    # ── Load all memory layers ────────────────────────────────────────────────
    market_ctx      = await _fetch_market_context()
    pattern_mem     = await get_pattern_memory(10)
    perf_stats      = await get_ai_performance_stats()
    recent_outcomes = await get_recent_signal_outcomes(20)
    trade_lessons   = await get_trade_lessons(12)
    blacklist       = await get_blacklisted_patterns()

    # ── Build prompt ──────────────────────────────────────────────────────────
    invested = sum(p["cost_basis"] for p in positions)
    cash     = capital - invested

    candidates = [
        r for r in scan_results
        if r.get("demand_composite_tier") in ("PRIME_BUY", "HIGH_CONF_BUY")
    ][:12]

    closed_summary = [
        {
            "symbol":      p["symbol"],
            "pnl_pct":     round(p["pnl_pct"], 1),
            "pnl_usd":     round(p["pnl_usd"], 2),
            "exit_reason": p["exit_reason"],
            "tier":        p["scan_tier"],
        }
        for p in (history or [])[:5]
    ]

    user_prompt = json.dumps({
        "account": {
            "capital_total":    round(capital, 2),
            "cash_available":   round(cash, 2),
            "invested":         round(invested, 2),
            "open_positions":   len(enriched),
            "max_positions":    MAX_POSITIONS,
            "starting_capital": state["starting_capital"],
            "total_pnl_pct":    round((capital / state["starting_capital"] - 1) * 100, 1),
            "win_rate":         perf_stats.get("win_rate"),
            "avg_win_pct":      perf_stats.get("avg_win_pct"),
            "avg_loss_pct":     perf_stats.get("avg_loss_pct"),
        },
        "open_positions": [
            {
                "id":              p["id"],
                "symbol":          p["symbol"],
                "entry_price":     p["entry_price"],
                "current_price":   p["current_price"],
                "current_pnl_pct": p["current_pnl_pct"],
                "days_held":       p["days_held"],
                "cost_basis":      p["cost_basis"],
                "target_price":    p["target_price"],
                "stop_price":      p["stop_price"],
                "scan_tier":       p["scan_tier"],
                "ats_signal":      p.get("ats_signal"),
            }
            for p in enriched
        ],
        "auto_closed_this_session": auto_closed,
        "recent_closed_trades":     closed_summary,
        "market_context":           market_ctx,
        "trade_lessons": [
            {
                "symbol":      l["symbol"],
                "pnl_pct":     l["pnl_pct"],
                "exit_reason": l["exit_reason"],
                "scan_tier":   l["scan_tier"],
                "ats_signal":  l["ats_signal"],
                "what_worked": l["what_worked"],
                "what_failed": l["what_failed"],
                "lesson":      l["lesson"],
                "confidence":  l["confidence"],
                "tags":        l["tags"],
            }
            for l in (trade_lessons or [])
        ],
        "pattern_memory": [
            {
                "pattern_key": pm["pattern_key"],
                "win_rate":    pm["win_rate"],
                "n_trades":    pm["n_trades"],
                "notes":       pm["notes"],
            }
            for pm in (pattern_mem or [])
        ],
        "signal_blacklist": [
            {
                "pattern_key": b["pattern_key"],
                "reason":      b["reason"],
                "n_failures":  b["n_failures"],
            }
            for b in blacklist if b.get("active")
        ],
        "recent_signal_outcomes": [
            {
                "symbol":        o["symbol"],
                "tier":          o["tier"],
                "ats":           o["ats_signal"],
                "gain_7d":       o["gain_7d"],
                "outcome_label": o["outcome_label"],
            }
            for o in (recent_outcomes or [])
        ],
        "previous_journal_entries": [
            {"date": e["created_at"][:10], "text": e["journal_text"][:800]}
            for e in entries
        ],
        "scan_candidates": [
            {
                "symbol":          r.get("symbol"),
                "tier":            r.get("demand_composite_tier"),
                "score":           r.get("demand_composite_score"),
                "price":           r.get("price"),
                "ats":             r.get("ats_signal"),
                "readiness":       r.get("readiness_tier"),
                "readiness_score": r.get("readiness_score"),
                "flow_signals":    r.get("flow_signals", []),
                "flow_risks":      r.get("flow_risks", []),
                "confluence":      r.get("confluence_signals", []),
                "dryup":           r.get("dc_dryup_streak"),
                "vol_ratio":       r.get("dc_vol_ratio"),
                "risk_flags":      r.get("demand_risk_flags", []),
                "breakdown":       r.get("demand_score_breakdown", {}),
            }
            for r in candidates
        ],
    }, indent=2)

    # ── Call Opus 4.7 with adaptive thinking ─────────────────────────────────
    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=180.0)
    try:
        async with client.messages.stream(
            model    = _MODEL_MAIN,
            max_tokens = 6000,
            thinking   = {"type": "adaptive"},
            system   = [{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages = [{"role": "user", "content": user_prompt}],
        ) as stream:
            response = await stream.get_final_message()

        # Extract text content blocks (skip thinking blocks)
        raw = ""
        for block in response.content:
            if block.type == "text":
                raw = block.text.strip()
                break

        parsed = _extract_json(raw)
    except Exception as e:
        logger.error(f"AI Journal Opus call failed: {e}")
        return {"error": str(e)}

    decisions        = parsed.get("decisions", [])
    journal_text     = parsed.get("journal_entry", "No journal entry generated.")
    strategy_notes   = parsed.get("strategy_update") or ""
    pattern_insights = parsed.get("pattern_insights", [])
    blacklist_updates = parsed.get("blacklist_updates", [])

    # ── Execute BUY / SELL decisions ─────────────────────────────────────────
    opened_count  = 0
    closed_count  = len(auto_closed)
    capital_delta = 0.0
    open_symbols  = {p["symbol"] for p in positions}

    # Build active blacklist set for quick lookup
    active_blacklist_keys = {b["pattern_key"] for b in blacklist if b.get("active")}

    for dec in decisions:
        action = dec.get("action", "").upper()
        symbol = (dec.get("symbol") or "").upper()
        price  = float(dec.get("price") or 0)
        if not symbol or not price:
            continue

        if action == "BUY" and symbol not in open_symbols:
            # Blacklist check
            scan_r = next((r for r in scan_results if r.get("symbol") == symbol), {})
            tier   = scan_r.get("demand_composite_tier", "")
            ats    = scan_r.get("ats_signal", "")
            ready  = scan_r.get("readiness_tier", "")
            pkey   = f"{tier}|{ats}|{ready}"
            if pkey in active_blacklist_keys:
                logger.info(f"[Journal] BUY blocked by blacklist: {symbol} ({pkey})")
                continue

            cost   = round(capital * POSITION_SIZE, 2)
            cost   = max(50.0, min(100.0, cost))
            if cost > cash:
                continue
            shares = round(cost / price, 4)
            target = round(price * (1 + TARGET_PCT), 2)
            stop   = round(price * (1 - STOP_PCT), 2)
            await open_ai_journal_position({
                "symbol":          symbol,
                "entry_price":     price,
                "shares":          shares,
                "cost_basis":      cost,
                "target_price":    target,
                "stop_price":      stop,
                "entry_rationale": dec.get("rationale", ""),
                "scan_tier":       tier,
                "scan_score":      scan_r.get("demand_composite_score"),
                "ats_signal":      ats,
                "readiness_tier":  ready,
            })
            capital_delta -= cost
            cash -= cost
            open_symbols.add(symbol)
            opened_count += 1

        elif action == "SELL":
            pos_id     = dec.get("position_id")
            target_pos = next(
                (p for p in enriched if p["id"] == pos_id or p["symbol"] == symbol), None
            )
            if target_pos:
                result = await close_ai_journal_position(
                    target_pos["id"], price, (dec.get("rationale") or "AI_SELL")[:40]
                )
                if result:
                    proceeds = price * target_pos["shares"]
                    capital_delta += proceeds
                    cash += proceeds
                    closed_count += 1
                    open_symbols.discard(symbol)
                    # Generate lesson for AI-triggered sell too
                    lesson_data = await generate_trade_lesson({
                        **target_pos,
                        "exit_price":  price,
                        "exit_reason": (dec.get("rationale") or "AI_SELL")[:40],
                        "pnl_pct":     result.get("pnl_pct"),
                    })
                    if lesson_data:
                        await save_trade_lesson({
                            "position_id":   target_pos["id"],
                            "symbol":        symbol,
                            "pnl_pct":       result.get("pnl_pct"),
                            "exit_reason":   (dec.get("rationale") or "AI_SELL")[:40],
                            "scan_tier":     target_pos.get("scan_tier"),
                            "ats_signal":    target_pos.get("ats_signal"),
                            "readiness_tier": target_pos.get("readiness_tier"),
                            **lesson_data,
                        })

    # ── Persist pattern insights ──────────────────────────────────────────────
    for pi in pattern_insights:
        try:
            pk = pi.get("pattern_key")
            if not pk:
                continue
            n_obs = int(pi.get("n_observations") or 0)
            wr    = float(pi.get("win_rate") or 0)
            await upsert_pattern_memory(
                pattern_key  = pk,
                n_trades     = n_obs,
                n_wins       = int(round(wr * n_obs)),
                win_rate     = wr,
                avg_win_pct  = pi.get("avg_gain_7d"),
                avg_loss_pct = None,
                notes        = pi.get("notes"),
            )
        except Exception as e:
            logger.debug(f"upsert_pattern_memory: {e}")

    # ── Apply blacklist updates ───────────────────────────────────────────────
    for bu in blacklist_updates:
        try:
            pk     = bu.get("pattern_key")
            action = (bu.get("action") or "").upper()
            if not pk or action not in ("BLOCK", "UNBLOCK"):
                continue
            if action == "BLOCK":
                days = int(bu.get("suspend_days") or 0)
                until = datetime.utcnow() + timedelta(days=days) if days > 0 else None
                await upsert_signal_blacklist(
                    pattern_key     = pk,
                    reason          = bu.get("reason") or "",
                    n_failures      = 1,
                    suspended_until = until,
                )
            elif action == "UNBLOCK":
                await remove_signal_blacklist(pk)
        except Exception as e:
            logger.debug(f"blacklist_update: {e}")

    # ── Save journal entry and update capital ─────────────────────────────────
    new_capital = round(capital + capital_delta, 2)
    await update_ai_journal_capital(
        new_capital,
        json.dumps({"notes": strategy_notes, "updated": datetime.utcnow().isoformat()})
        if strategy_notes else None,
    )
    entry_id = await save_ai_journal_entry({
        "journal_text":     journal_text,
        "strategy_notes":   strategy_notes,
        "capital_before":   capital,
        "capital_after":    new_capital,
        "positions_opened": opened_count,
        "positions_closed": closed_count,
        "decisions":        decisions,
    })

    return {
        "entry_id":          entry_id,
        "capital_before":    capital,
        "capital_after":     new_capital,
        "positions_opened":  opened_count,
        "positions_closed":  closed_count,
        "auto_closed":       len(auto_closed),
        "decisions_count":   len(decisions),
        "blacklist_changes": len(blacklist_updates),
        "lessons_generated": sum(1 for _ in auto_closed),
        "journal_preview":   journal_text[:200],
    }
