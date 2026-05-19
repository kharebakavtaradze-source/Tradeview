"""
AI Trading Journal — $500 virtual account.

Claude reviews demand scan results, manages virtual positions, and writes
a journal entry explaining its reasoning and strategy evolution.

Strategy is grounded in R154–R157 research:
  Entry:  PRIME_BUY + ATS_PRIME/SETUP + readiness HOT/WARM + OBV_ACCUM
  Exit:   +25–35% target | –12% stop | tier drops to SKIP with risk flags
  Sizing: 15–20% of current capital, max 5 open positions
"""
import json
import logging
import os
from datetime import datetime, timezone

import anthropic
import httpx

from database import (
    close_ai_journal_position,
    get_ai_journal_entries,
    get_ai_journal_positions,
    get_ai_journal_state,
    open_ai_journal_position,
    save_ai_journal_entry,
    update_ai_journal_capital,
)

logger = logging.getLogger(__name__)

_YAHOO_V8 = "https://query1.finance.yahoo.com/v8/finance/chart"
_HEADERS   = {"User-Agent": "Mozilla/5.0"}

MAX_POSITIONS = 5
STOP_PCT      = 0.12   # –12% stop
TARGET_PCT    = 0.30   # +30% primary target
POSITION_SIZE = 0.18   # 18% of capital per position


# ── Price fetching ────────────────────────────────────────────────────────────

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


# ── System prompt (cached) ────────────────────────────────────────────────────

_SYSTEM = """\
You are the AI Trading Journal for a $500 virtual paper-trading account.
You operate on the Demand Scanner's research-backed signal stack (R154–R157).

=== YOUR STRATEGY (NON-NEGOTIABLE RULES) ===

ENTRY CRITERIA (must satisfy ALL):
  1. demand_composite_tier == "PRIME_BUY" (score ≥ 13)
  2. ats_signal in ["ATS_PRIME", "ATS_SETUP"]
  3. readiness_tier in ["HOT", "WARM"]
  4. No hard risk flags: dv_illiquid, atr_extreme, overheated_expansion, price_gt25
  5. Price $0.50–$15 (sweet spot for $500 account)
  6. Max 5 concurrent positions
  7. Available cash ≥ $50

POSITION SIZING: 18% of current capital per position (min $50, max $100)
STOP LOSS: –12% from entry price
TAKE PROFIT: +30% from entry price
BOOST signals (increase conviction): OBV_ACCUM, LOWER_WICK_ABSORB, ATS_PRIME

SELL / EXIT CRITERIA:
  - Exit if current price hits stop (–12%) → reason: STOP_HIT
  - Exit if current price hits target (+30%) → reason: TARGET_HIT
  - Exit if tier drops to "SKIP" + has risk flags → reason: SIGNAL_LOST
  - Exit if held > 15 trading days with no progress → reason: TIME_STOP

RISK MANAGEMENT:
  - Never add to a losing position
  - Skip BUY if a position in same symbol already OPEN
  - HIGH_CONF_BUY is watchlist only — never enter unless it upgrades to PRIME_BUY
  - PUMP_WATCH_HIGH is miscalibrated (R157 finding) — treat as neutral, not bullish

=== RESPONSE FORMAT ===
You MUST respond with valid JSON only, no prose outside JSON:

{
  "decisions": [
    {
      "action": "BUY" | "SELL" | "HOLD" | "WATCH",
      "symbol": "TICKER",
      "price": 2.50,
      "shares": 40,
      "cost": 100.00,
      "target": 3.25,
      "stop": 2.20,
      "rationale": "1-2 sentence reason grounded in specific signals",
      "position_id": null  // null for BUY, fill for SELL
    }
  ],
  "journal_entry": "3–5 paragraph journal. Paragraph 1: what scan showed today. Paragraph 2: decisions made and why. Paragraph 3: current portfolio status and risk exposure. Paragraph 4: what I'm learning / strategy refinement. Paragraph 5 (optional): what to watch next session.",
  "strategy_update": "1-2 sentences: any strategy refinement based on recent performance. null if no change."
}
"""


# ── Main session runner ───────────────────────────────────────────────────────

async def run_journal_session(scan_results: list[dict]) -> dict:
    """
    Core AI Journal logic. Called after each demand scan.
    Returns a summary of decisions made.
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "ANTHROPIC_API_KEY not configured"}

    state     = await get_ai_journal_state()
    capital   = state["capital"]
    positions = await get_ai_journal_positions("OPEN")
    history   = await get_ai_journal_positions("CLOSED")
    entries   = await get_ai_journal_entries(5)

    # ── Refresh open position prices & check stop/target hits ────────────────
    auto_closed = []
    for pos in positions:
        price = await _fetch_price(pos["symbol"])
        if price is None:
            continue
        pnl_pct = (price / pos["entry_price"] - 1) * 100 if pos["entry_price"] else 0
        if pnl_pct <= -STOP_PCT * 100:
            result = await close_ai_journal_position(pos["id"], price, "STOP_HIT")
            if result:
                capital += price * pos["shares"]
                auto_closed.append({**pos, "exit_price": price, "exit_reason": "STOP_HIT", **result})
        elif pnl_pct >= TARGET_PCT * 100:
            result = await close_ai_journal_position(pos["id"], price, "TARGET_HIT")
            if result:
                capital += price * pos["shares"]
                auto_closed.append({**pos, "exit_price": price, "exit_reason": "TARGET_HIT", **result})

    # Refresh position list after auto-closes
    positions = await get_ai_journal_positions("OPEN")

    # ── Build context for Claude ──────────────────────────────────────────────
    invested  = sum(p["cost_basis"] for p in positions)
    cash      = capital - invested
    n_open    = len(positions)

    # Top scan candidates (PRIME_BUY + HIGH_CONF_BUY only)
    candidates = [
        r for r in scan_results
        if r.get("demand_composite_tier") in ("PRIME_BUY", "HIGH_CONF_BUY")
    ][:12]

    # Recent closed trade performance (last 5)
    closed_summary = []
    for p in (history or [])[:5]:
        closed_summary.append({
            "symbol":      p["symbol"],
            "pnl_pct":     round(p["pnl_pct"], 1),
            "pnl_usd":     round(p["pnl_usd"], 2),
            "exit_reason": p["exit_reason"],
            "tier":        p["scan_tier"],
        })

    # Learned strategy from previous sessions
    learned = state.get("learned_strategy") or {}

    user_prompt = json.dumps({
        "account": {
            "capital_total":      round(capital, 2),
            "cash_available":     round(cash, 2),
            "invested":           round(invested, 2),
            "open_positions":     n_open,
            "max_positions":      MAX_POSITIONS,
            "starting_capital":   state["starting_capital"],
            "total_pnl_pct":      round((capital / state["starting_capital"] - 1) * 100, 1),
        },
        "open_positions": [
            {
                "id":           p["id"],
                "symbol":       p["symbol"],
                "entry_price":  p["entry_price"],
                "shares":       p["shares"],
                "cost_basis":   p["cost_basis"],
                "target_price": p["target_price"],
                "stop_price":   p["stop_price"],
                "scan_tier":    p["scan_tier"],
            }
            for p in positions
        ],
        "auto_closed_this_session": auto_closed,
        "recent_closed_trades":     closed_summary,
        "previous_journal_entries": [
            {"date": e["created_at"][:10], "summary": e["journal_text"][:300]}
            for e in entries
        ],
        "learned_strategy": learned,
        "scan_candidates": [
            {
                "symbol":       r.get("symbol"),
                "tier":         r.get("demand_composite_tier"),
                "score":        r.get("demand_composite_score"),
                "price":        r.get("price"),
                "ats":          r.get("ats_signal"),
                "readiness":    r.get("readiness_tier"),
                "readiness_score": r.get("readiness_score"),
                "flow_signals": r.get("flow_signals", []),
                "flow_risks":   r.get("flow_risks", []),
                "confluence":   r.get("confluence_signals", []),
                "dryup":        r.get("dc_dryup_streak"),
                "vol_ratio":    r.get("dc_vol_ratio"),
                "risk_flags":   r.get("demand_risk_flags", []),
                "breakdown":    r.get("demand_score_breakdown", {}),
            }
            for r in candidates
        ],
    }, indent=2)

    client = anthropic.AsyncAnthropic(api_key=api_key, timeout=45.0)
    try:
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1800,
            system=[{"type": "text", "text": _SYSTEM, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = response.content[0].text.strip()
        # Claude might wrap in ```json ... ```
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        parsed = json.loads(raw)
    except Exception as e:
        logger.error(f"AI Journal Claude call failed: {e}")
        return {"error": str(e)}

    decisions      = parsed.get("decisions", [])
    journal_text   = parsed.get("journal_entry", "No journal entry generated.")
    strategy_notes = parsed.get("strategy_update") or ""

    # ── Execute decisions ─────────────────────────────────────────────────────
    opened_count = 0
    closed_count = len(auto_closed)
    capital_delta = 0.0

    open_symbols = {p["symbol"] for p in positions}

    for dec in decisions:
        action = dec.get("action", "").upper()
        symbol = (dec.get("symbol") or "").upper()
        price  = float(dec.get("price") or 0)
        if not symbol or not price:
            continue

        if action == "BUY" and symbol not in open_symbols:
            cost = round(capital * POSITION_SIZE, 2)
            cost = max(50.0, min(100.0, cost))
            if cost > cash:
                continue
            shares = round(cost / price, 4)
            target = round(price * (1 + TARGET_PCT), 2)
            stop   = round(price * (1 - STOP_PCT), 2)
            # Find matching scan result for tier/score
            scan_r = next((r for r in scan_results if r.get("symbol") == symbol), {})
            await open_ai_journal_position({
                "symbol":          symbol,
                "entry_price":     price,
                "shares":          shares,
                "cost_basis":      cost,
                "target_price":    target,
                "stop_price":      stop,
                "entry_rationale": dec.get("rationale", ""),
                "scan_tier":       scan_r.get("demand_composite_tier"),
                "scan_score":      scan_r.get("demand_composite_score"),
                "ats_signal":      scan_r.get("ats_signal"),
            })
            capital_delta -= cost
            cash -= cost
            open_symbols.add(symbol)
            opened_count += 1

        elif action == "SELL":
            pos_id = dec.get("position_id")
            target_pos = next(
                (p for p in positions if p["id"] == pos_id or p["symbol"] == symbol),
                None,
            )
            if target_pos:
                result = await close_ai_journal_position(
                    target_pos["id"], price, dec.get("rationale", "AI_SELL")[:40]
                )
                if result:
                    proceeds = price * target_pos["shares"]
                    capital_delta += proceeds - target_pos["cost_basis"] + target_pos["cost_basis"]
                    cash += proceeds
                    closed_count += 1
                    open_symbols.discard(symbol)

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
        "entry_id":        entry_id,
        "capital_before":  capital,
        "capital_after":   new_capital,
        "positions_opened": opened_count,
        "positions_closed": closed_count,
        "auto_closed":     len(auto_closed),
        "decisions_count": len(decisions),
        "journal_preview": journal_text[:200],
    }
