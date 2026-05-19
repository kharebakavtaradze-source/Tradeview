"""
AI Trading Journal — $500 virtual account.

Claude reviews demand scan results, manages virtual positions, and writes
a journal entry explaining its reasoning and strategy evolution.

Strategy is grounded in R154–R157 research:
  Entry:  PRIME_BUY + ATS_PRIME/SETUP + readiness HOT/WARM + OBV_ACCUM
  Exit:   +25–35% target | –12% stop | tier drops to SKIP with risk flags
  Sizing: 15–20% of current capital, max 5 open positions
"""
import asyncio
import json
import logging
import os
from datetime import datetime, timezone, timedelta

import anthropic
import httpx

from database import (
    close_ai_journal_position,
    get_ai_journal_entries,
    get_ai_journal_positions,
    get_ai_journal_state,
    get_ai_performance_stats,
    get_pattern_memory,
    get_pending_backfill,
    get_recent_signal_outcomes,
    fill_signal_returns,
    open_ai_journal_position,
    save_ai_journal_entry,
    save_signal_outcomes,
    update_ai_journal_capital,
    upsert_pattern_memory,
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


# ── Signal outcome recording ──────────────────────────────────────────────────

async def record_scan_signals(scan_results: list[dict]) -> int:
    """
    Called after each scan run (non-blocking, swallows exceptions).
    Saves every PRIME_BUY and HIGH_CONF_BUY ticker as a signal outcome.
    Returns count inserted.
    """
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
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
        logger.debug(f"record_scan_signals error: {e}")
        return 0


# ── Forward return backfill ───────────────────────────────────────────────────

async def backfill_forward_returns() -> dict:
    """
    Gets pending outcomes via get_pending_backfill().
    For each, fetches Yahoo Finance historical bars and fills forward returns.
    Returns {"backfilled": n, "errors": m}.
    """
    pending = await get_pending_backfill(min_age_days=3, limit=60)
    backfilled = 0
    errors = 0

    for row in pending:
        try:
            symbol      = row["symbol"]
            sig_date_s  = row["signal_date"]  # YYYY-MM-DD
            price_entry = row.get("price_at_signal")
            if not price_entry:
                continue

            sig_date = datetime.strptime(sig_date_s, "%Y-%m-%d").date()

            url = f"{_YAHOO_V8}/{symbol.upper()}"
            async with httpx.AsyncClient(timeout=15.0, headers=_HEADERS) as c:
                r = await c.get(url, params={"interval": "1d", "range": "30d"})
            if r.status_code != 200:
                errors += 1
                continue

            chart = r.json().get("chart", {}).get("result", [])
            if not chart:
                errors += 1
                continue

            timestamps = chart[0].get("timestamp", [])
            closes     = chart[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])

            if not timestamps or not closes:
                errors += 1
                continue

            # Build list of (date, close) sorted ascending
            bars = []
            for ts, cl in zip(timestamps, closes):
                if cl is None:
                    continue
                d = datetime.utcfromtimestamp(ts).date()
                bars.append((d, cl))
            bars.sort(key=lambda x: x[0])

            # Filter to bars after signal_date
            future_bars = [(d, cl) for d, cl in bars if d > sig_date]

            def get_close_at_day(n: int) -> float | None:
                """Return close at approximately n trading days after signal."""
                if len(future_bars) >= n:
                    return future_bars[n - 1][1]
                if future_bars:
                    return future_bars[-1][1]
                return None

            price_3d  = get_close_at_day(3)
            price_7d  = get_close_at_day(7)
            price_14d = get_close_at_day(14)

            def gain(p: float | None) -> float | None:
                if p is None:
                    return None
                return round((p / price_entry - 1) * 100, 2)

            gain_3d  = gain(price_3d)
            gain_7d  = gain(price_7d)
            gain_14d = gain(price_14d)

            window_14 = future_bars[:14]
            max_gain_14d = (
                round((max(cl for _, cl in window_14) / price_entry - 1) * 100, 2)
                if window_14 else None
            )

            # Outcome label
            if max_gain_14d is not None and max_gain_14d >= 20:
                outcome_label = "WIN_STRONG"
            elif gain_7d is not None and gain_7d >= 8:
                outcome_label = "WIN"
            elif gain_14d is not None and gain_14d <= -8:
                outcome_label = "LOSS"
            else:
                outcome_label = "FLAT"

            await fill_signal_returns(row["id"], {
                "price_3d":      price_3d,
                "price_7d":      price_7d,
                "price_14d":     price_14d,
                "gain_3d":       gain_3d,
                "gain_7d":       gain_7d,
                "gain_14d":      gain_14d,
                "max_gain_14d":  max_gain_14d,
                "outcome_label": outcome_label,
            })
            backfilled += 1

        except Exception as e:
            logger.debug(f"backfill error ({row.get('symbol')}): {e}")
            errors += 1

    return {"backfilled": backfilled, "errors": errors}


# ── Market context ────────────────────────────────────────────────────────────

async def _fetch_market_context() -> dict:
    """Fetch SPY and VIX from Yahoo, return market mood."""
    _empty = {"spy_1d_pct": None, "spy_5d_pct": None, "vix": None, "market_mood": "UNKNOWN"}
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=_HEADERS) as c:
            spy_r, vix_r = await asyncio.gather(
                c.get(f"{_YAHOO_V8}/SPY", params={"interval": "1d", "range": "5d"}),
                c.get(f"{_YAHOO_V8}/^VIX", params={"interval": "1d", "range": "5d"}),
                return_exceptions=True,
            )

        spy_1d = spy_5d = vix_val = None

        if not isinstance(spy_r, Exception) and spy_r.status_code == 200:
            spy_chart = spy_r.json().get("chart", {}).get("result", [])
            if spy_chart:
                closes = [
                    c for c in spy_chart[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
                    if c is not None
                ]
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

        # Market mood
        if spy_1d is not None and vix_val is not None:
            if spy_1d > 0.5 and vix_val < 20:
                mood = "BULL"
            elif spy_1d < -0.5 or vix_val > 25:
                mood = "BEAR"
            else:
                mood = "NEUTRAL"
        else:
            mood = "UNKNOWN"

        return {
            "spy_1d_pct":  spy_1d,
            "spy_5d_pct":  spy_5d,
            "vix":         vix_val,
            "market_mood": mood,
        }
    except Exception as e:
        logger.debug(f"_fetch_market_context error: {e}")
        return _empty


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

=== PATTERN LEARNING ===
You have access to pattern_memory (historical win rates per signal combo) and
recent_signal_outcomes (what happened after signals fired). Use this data to:
1. Identify which signal combos have the highest win rate and why
2. Refine entry criteria based on real outcomes (not just theory)
3. Note patterns you've seen work: e.g. "PRIME_BUY+ATS_PRIME+OBV_ACCUM: 3/4 wins, avg +24%"
4. Note patterns that failed: e.g. "HIGH_CONF_BUY alone: 1/5 wins, stop-outs common"

Add to your JSON response:
"pattern_insights": [
  {
    "pattern_key": "PRIME_BUY|ATS_PRIME|HOT",
    "n_observations": 4,
    "win_rate": 0.75,
    "avg_gain_7d": 14.2,
    "notes": "2-3 sentence insight about this pattern based on what you've learned"
  }
]

=== CURRENT POSITION MANAGEMENT ===
Each open position now shows current_price and current_pnl_pct and days_held.
- At +20% or more: consider partial sell logic, journal it as potential early exit
- At days_held >= 12: review time-stop urgency
- At current_pnl_pct >= TARGET% (30): Claude should SELL, overriding auto-close

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
  "strategy_update": "1-2 sentences: any strategy refinement based on recent performance. null if no change.",
  "pattern_insights": []
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

    # ── Enrich open positions with current price, P&L%, days_held ────────────
    now_utc = datetime.now(timezone.utc)
    enriched_positions = []
    for pos in positions:
        current_price = await _fetch_price(pos["symbol"])
        current_pnl_pct = None
        if current_price and pos["entry_price"]:
            current_pnl_pct = round((current_price / pos["entry_price"] - 1) * 100, 2)
        # days_held from entry_date
        entry_date_raw = pos.get("entry_date")
        days_held = 0
        if entry_date_raw:
            try:
                if isinstance(entry_date_raw, str):
                    entry_dt = datetime.fromisoformat(entry_date_raw.replace("Z", "+00:00"))
                else:
                    entry_dt = entry_date_raw
                if entry_dt.tzinfo is None:
                    entry_dt = entry_dt.replace(tzinfo=timezone.utc)
                days_held = (now_utc - entry_dt).days
            except Exception:
                days_held = 0
        enriched_positions.append({
            **pos,
            "current_price":   current_price,
            "current_pnl_pct": current_pnl_pct,
            "days_held":       days_held,
        })

    # ── Fetch supporting context ──────────────────────────────────────────────
    market_ctx    = await _fetch_market_context()
    pattern_mem   = await get_pattern_memory(10)
    perf_stats    = await get_ai_performance_stats()
    recent_outcomes = await get_recent_signal_outcomes(20)

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
            "win_rate":           perf_stats.get("win_rate"),
            "avg_win_pct":        perf_stats.get("avg_win_pct"),
            "avg_loss_pct":       perf_stats.get("avg_loss_pct"),
        },
        "open_positions": [
            {
                "id":              p["id"],
                "symbol":          p["symbol"],
                "entry_price":     p["entry_price"],
                "shares":          p["shares"],
                "cost_basis":      p["cost_basis"],
                "target_price":    p["target_price"],
                "stop_price":      p["stop_price"],
                "scan_tier":       p["scan_tier"],
                "current_price":   p["current_price"],
                "current_pnl_pct": p["current_pnl_pct"],
                "days_held":       p["days_held"],
            }
            for p in enriched_positions
        ],
        "auto_closed_this_session": auto_closed,
        "recent_closed_trades":     closed_summary,
        "market_context":           market_ctx,
        "pattern_memory": [
            {
                "pattern_key": pm["pattern_key"],
                "win_rate":    pm["win_rate"],
                "n_trades":    pm["n_trades"],
                "notes":       pm["notes"],
            }
            for pm in (pattern_mem or [])
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
            {"date": e["created_at"][:10], "summary": e["journal_text"][:800]}
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
            max_tokens=2400,
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

    decisions        = parsed.get("decisions", [])
    journal_text     = parsed.get("journal_entry", "No journal entry generated.")
    strategy_notes   = parsed.get("strategy_update") or ""
    pattern_insights = parsed.get("pattern_insights", [])

    # ── Execute decisions ─────────────────────────────────────────────────────
    opened_count  = 0
    closed_count  = len(auto_closed)
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

    # ── Persist pattern insights from Claude ──────────────────────────────────
    for pi in pattern_insights:
        try:
            pk = pi.get("pattern_key")
            if not pk:
                continue
            await upsert_pattern_memory(
                pattern_key  = pk,
                n_trades     = int(pi.get("n_observations") or 0),
                n_wins       = int(round((pi.get("win_rate") or 0) * int(pi.get("n_observations") or 0))),
                win_rate     = float(pi.get("win_rate") or 0),
                avg_win_pct  = pi.get("avg_gain_7d"),
                avg_loss_pct = None,
                notes        = pi.get("notes"),
            )
        except Exception as e:
            logger.debug(f"upsert_pattern_memory error ({pi.get('pattern_key')}): {e}")

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
