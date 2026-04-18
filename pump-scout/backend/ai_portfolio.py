"""
AI Paper Trading Portfolio — $2000 virtual account.
AI makes buy/sell decisions daily at 9:45 AM ET using scan + New Pump signals.
End-of-day report at 16:30 ET.
"""
import json
import logging
import os
from datetime import datetime, timezone

import anthropic
import httpx

from database import (
    close_ai_position,
    get_ai_portfolio_history,
    get_all_ai_positions,
    get_open_ai_positions,
    get_portfolio_state,
    get_recent_np_signals,
    insert_ai_position,
    partial_exit_ai_position,
    update_ai_position_price,
    update_portfolio_state,
    update_portfolio_value_from_positions,
)

logger = logging.getLogger(__name__)

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

_YAHOO_V8_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"


async def _fetch_price(symbol: str) -> float | None:
    """Fetch current price via Yahoo Finance v8 chart API (same as the scanner)."""
    url = f"{_YAHOO_V8_BASE}/{symbol.upper()}"
    try:
        async with httpx.AsyncClient(timeout=10.0, headers=YAHOO_HEADERS) as client:
            resp = await client.get(url, params={"interval": "1d", "range": "1d"})
            if resp.status_code == 200:
                meta = resp.json().get("chart", {}).get("result", [{}])[0].get("meta", {})
                price = meta.get("regularMarketPrice") or meta.get("previousClose")
                return float(price) if price else None
    except Exception as e:
        logger.warning(f"Portfolio price fetch failed for {symbol}: {e}")
    return None


async def _fetch_prices_batch(symbols: list[str]) -> dict[str, float]:
    """
    Fetch current prices for multiple symbols concurrently via v8 chart API.
    Returns {symbol: price} for all successful fetches.
    Uses the same v8 endpoint as the scanner (more reliable than v7 quote batch).
    """
    import asyncio
    semaphore = asyncio.Semaphore(5)  # max 5 concurrent requests

    async def _fetch_one(symbol: str, client: httpx.AsyncClient) -> tuple[str, float | None]:
        async with semaphore:
            url = f"{_YAHOO_V8_BASE}/{symbol.upper()}"
            for attempt in range(2):
                try:
                    resp = await client.get(url, params={"interval": "1d", "range": "1d"}, timeout=10.0)
                    if resp.status_code == 429:
                        await asyncio.sleep(1.5 ** attempt)
                        continue
                    if resp.status_code == 200:
                        meta = resp.json().get("chart", {}).get("result", [{}])[0].get("meta", {})
                        price = meta.get("regularMarketPrice") or meta.get("previousClose")
                        if price:
                            return symbol, float(price)
                except Exception as e:
                    logger.debug(f"Price fetch {symbol} attempt {attempt+1}: {e}")
            return symbol, None

    prices: dict[str, float] = {}
    async with httpx.AsyncClient(headers=YAHOO_HEADERS) as client:
        tasks = [_fetch_one(sym, client) for sym in symbols]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        for r in results:
            if isinstance(r, tuple) and r[1] is not None:
                prices[r[0]] = r[1]

    logger.info(f"Price batch fetch: {len(prices)}/{len(symbols)} symbols resolved")
    return prices


def _filter_ai_candidates(scan_results: list) -> list:
    """
    Hard pre-filter before AI sees candidates.
    AI only receives high-quality setups — code-level, cannot be overridden by prompt.
    """
    from scanner.sector_map import NON_STOCK_SECURITIES

    qualified = []
    for r in scan_results:
        # Skip CEFs, ETNs, and other non-stock securities
        if r.get("symbol", "") in NON_STOCK_SECURITIES:
            continue

        tier = r.get("score", {}).get("tier", "")
        indicators = r.get("indicators", {})
        cmf = indicators.get("cmf_pctl", 0)
        rsi = (indicators.get("rsi") or {}).get("value", 50) or 50
        wyckoff = r.get("regime", {}).get("state", "NONE")
        hype = (r.get("hype_score") or {}).get("hype_index", 0) or 0
        price_chg = abs(indicators.get("price_change_pct", 0))

        # Never chase: already moved >5% today
        if price_chg > 5:
            continue

        # Skip if earnings in ≤3 days — gap risk too high
        if r.get("earnings_risk") == "HIGH":
            continue

        if tier == "FIRE":
            qualified.append(r)
        elif tier == "ARM":
            # ARM needs additional confirmation
            if (cmf > 70
                    and rsi < 65
                    and hype < 40
                    and wyckoff not in ("NONE", "DISTRIBUTION")):
                qualified.append(r)

    return qualified


def _atr_position_size(portfolio_value: float, entry: float, atr: float,
                       stop_mult: float = 1.5) -> float:
    """Risk 2% of portfolio per trade, ATR-based. Returns position size in USD."""
    risk_per_trade = portfolio_value * 0.02
    risk_per_share = atr * stop_mult
    if risk_per_share <= 0:
        return 50.0
    shares = risk_per_trade / risk_per_share
    size = shares * entry
    return round(max(50.0, min(600.0, size)), 2)


async def _get_np_candidates() -> list[dict]:
    """
    Fetch recent New Pump FIRE/STRONG signals from replay history (last 5 days).
    Skips isolated triggers (G4 with no setup) and non-stock securities.
    Returns list of candidate dicts compatible with the scan_ctx format.
    """
    from scanner.sector_map import NON_STOCK_SECURITIES
    try:
        np_signals = await get_recent_np_signals(days=5)
    except Exception as e:
        logger.warning(f"NP candidate fetch failed: {e}")
        return []

    seen: set[str] = set()
    candidates: list[dict] = []
    for s in np_signals:
        sym = s["symbol"]
        if sym in NON_STOCK_SECURITIES or sym in seen:
            continue
        if s.get("np_is_isolated_trigger"):
            continue
        seen.add(sym)
        price = await _fetch_price(sym) or s.get("price") or 0
        if price <= 0:
            continue
        candidates.append({
            "symbol": sym,
            "price": price,
            "tier": s["new_pump_label"],
            "score": round(s.get("new_pump_score") or 0, 1),
            "source": "new_pump",
            "np_setup_via": s.get("np_setup_via"),
            "np_sequence": s.get("new_pump_sequence_label"),
            "scan_date": s.get("scan_date"),
            "sector": s.get("sector", ""),
            "atr": 0,
            "wyckoff": "NONE",
            "cmf_pctl": 0,
            "rsi": None,
            "vol_ratio": 0,
            "hype": 0,
            "rs_score": 0,
        })
    return candidates


async def _build_portfolio_memory() -> dict[str, dict]:
    """
    Derive per-ticker win/loss memory from the last 100 closed positions.
    Returns {symbol: {wins, losses, avg_pnl, last_result}}.
    """
    positions = await get_all_ai_positions(100)
    memory: dict[str, dict] = {}
    for p in positions:
        if p.get("status") != "CLOSED":
            continue
        pnl = p.get("pnl_pct")
        if pnl is None:
            continue
        sym = p["symbol"]
        if sym not in memory:
            memory[sym] = {"wins": 0, "losses": 0, "_pnls": []}
        memory[sym]["_pnls"].append(pnl)
        if pnl >= 0:
            memory[sym]["wins"] += 1
        else:
            memory[sym]["losses"] += 1
    result = {}
    for sym, m in memory.items():
        pnls = m["_pnls"]
        result[sym] = {
            "wins": m["wins"],
            "losses": m["losses"],
            "avg_pnl": round(sum(pnls) / len(pnls), 2),
            "last_result": "WIN" if pnls[-1] >= 0 else "LOSS",
        }
    return result


async def _build_research_priors(scan_ctx: list[dict], np_ctx: list[dict]) -> dict:
    """
    Compact structured research priors from Replay + Raw Pattern evidence.
    Deliberately broad and stable — avoids fragile sequence-label micro-claims.
    Returns {"global": {...}, "candidate_adjustments": {sym: [notes]}}.
    """
    global_priors = {
        "early_setup_bias":        "positive",   # L34/FRI34 setups tend to precede 4x moves
        "late_confirm_caution":    "negative",   # confirm-heavy late structures run noisier
        "isolated_signal_penalty": "negative",   # G4/B2 without setup → false-positive-prone
        "extreme_anomaly_penalty": "negative",   # extreme vol_ratio adds volatility tax
        "bull_stack_context":      "positive",   # quality Wyckoff/regime context compounds edge
        "strong_label_bias":       "positive",   # NP FIRE > STRONG > TRIGGER_ONLY / WEAK
        "none_label_neutrality":   "neutral",
        "volume_gate_note":        "do_not_overfilter",
    }

    # Attach evidence trail — proves priors are backed by actual research runs,
    # not fabricated. AI can reference run ids in reasoning.
    try:
        from database import get_raw_pattern_runs, get_replay_history, get_pump_study_runs
        rp_runs  = await get_raw_pattern_runs(limit=1)
        rep_runs = await get_replay_history(limit=1)
        ps_runs  = await get_pump_study_runs(limit=1)
        global_priors["evidence_refs"] = {
            "raw_pattern_run_id": (rp_runs[0].get("id") if rp_runs else None),
            "replay_run_id":      (rep_runs[0].get("id") if rep_runs else None),
            "pump_study_run_id":  (ps_runs[0].get("id") if ps_runs else None),
        }
    except Exception as e:
        logger.debug(f"Research prior evidence refs skipped: {e}")

    # Candidate-level adjustments (derived per-row from visible attributes)
    adjustments: dict[str, list[str]] = {}

    for r in scan_ctx:
        notes: list[str] = []
        vol_ratio = r.get("vol_ratio") or 0
        if vol_ratio >= 5:
            notes.append("extreme_anomaly_caution")
        wyckoff = r.get("wyckoff") or "NONE"
        if wyckoff in ("ACCUMULATION", "BREAKOUT"):
            notes.append("bull_stack_context_positive")
        cmf = r.get("cmf_pctl") or 0
        if cmf >= 80:
            notes.append("healthy_accumulation_context")
        if notes:
            adjustments[r["symbol"]] = notes

    for r in np_ctx:
        notes: list[str] = []
        setup_via = r.get("np_setup_via") or "NONE"
        if setup_via == "NONE":
            notes.append("isolated_signal_penalty")
        elif setup_via in ("L34", "FRI34", "BOTH"):
            notes.append("early_setup_context_positive")
        if r.get("tier") == "FIRE":
            notes.append("strong_label_bias_positive")
        existing = adjustments.get(r["symbol"], [])
        merged = list(dict.fromkeys(existing + notes))
        if merged:
            adjustments[r["symbol"]] = merged

    return {"global": global_priors, "candidate_adjustments": adjustments}


async def update_ai_positions_intraday():
    """
    Runs every 5 minutes during market hours (9:30–16:00 ET).
    - Batch-fetches live prices for all open AI positions
    - Updates current_price, pnl_pct, max_gain_pct, max_loss_pct, days_held
    - Auto-closes positions that hit ATR stop or target price
    - Force-sells CEF/ETN positions (should not be in portfolio)
    - Recalculates total portfolio value
    """
    from scanner.sector_map import NON_STOCK_SECURITIES

    positions = await get_open_ai_positions()
    if not positions:
        return

    symbols = [p["symbol"] for p in positions]
    symbol_to_pos = {p["symbol"]: p for p in positions}

    # Batch fetch all prices via v8 chart API (concurrent, same as scanner)
    prices = await _fetch_prices_batch(symbols)
    if not prices:
        logger.warning("Intraday AI price batch fetch returned no prices — skipping update")
        return

    state = await get_portfolio_state()
    cash = state["cash"]

    for pos in positions:
        sym = pos["symbol"]
        price = prices.get(sym)
        if not price:
            continue

        # Force-sell CEFs/ETNs that slipped through
        if sym in NON_STOCK_SECURITIES:
            closed = await close_ai_position(sym, price, "CEF/ETN filter — not a stock",
                                             exit_reason="CEF_FILTER")
            if closed:
                cash += closed.get("current_value", 0)
                logger.info(f"AI portfolio: force-sold CEF/ETN {sym} at ${price:.2f}")
            continue

        entry = pos.get("entry_price") or 0
        shares = pos.get("shares") or 0
        atr_stop = pos.get("stop_loss")
        target = pos.get("target_price")

        # Auto-close on ATR stop hit
        if atr_stop and price <= atr_stop:
            closed = await close_ai_position(sym, price, f"ATR stop hit ${atr_stop:.2f}",
                                             exit_reason="ATR_STOP")
            if closed:
                cash += price * shares
                logger.info(f"AI portfolio: {sym} ATR-stopped at ${price:.2f} "
                            f"(stop=${atr_stop:.2f})")
            continue

        target2 = pos.get("target_price_2")
        sell_pct = pos.get("sell_pct_at_target_1", 50)
        tp1_hit = pos.get("tp1_hit", False)

        # TP1: partial exit
        if target and price >= target and not tp1_hit:
            proceeds = await partial_exit_ai_position(pos["id"], price, sell_pct)
            cash += proceeds
            logger.info(f"AI portfolio: {sym} TP1 hit at ${price:.2f} — sold {sell_pct}% "
                        f"(${proceeds:.2f})")
            if not target2:
                # No TP2 — close the remaining shares fully
                closed = await close_ai_position(sym, price, f"Target hit ${target:.2f}",
                                                 exit_reason="TARGET_HIT")
                if closed:
                    cash += closed.get("current_value", 0)
            continue

        # TP2: close remainder
        if tp1_hit and target2 and price >= target2:
            closed = await close_ai_position(sym, price, f"Target 2 hit ${target2:.2f}",
                                             exit_reason="TARGET2_HIT")
            if closed:
                cash += closed.get("current_value", 0)
                logger.info(f"AI portfolio: {sym} TP2 hit at ${price:.2f}")
            continue

        # Update price, P&L, days_held
        await update_ai_position_price(pos["id"], price)

    # Recalculate portfolio value with updated prices
    await update_portfolio_value_from_positions()
    logger.debug(f"AI intraday update done: {len(prices)} prices fetched")


async def ai_portfolio_decisions():
    """
    Runs at 9:45 AM ET weekdays.
    AI reviews scan results and open positions, makes BUY/SELL/HOLD decisions.
    Hard candidate filter runs before AI call to prevent bad trades.
    CEF/ETN positions are force-sold before AI runs.
    """
    logger.info("AI portfolio decisions starting...")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set — skipping portfolio decisions")
        return

    state = await get_portfolio_state()
    cash = state["cash"]
    open_positions = await get_open_ai_positions()

    # ── Force-sell any CEF/ETN positions immediately ──────────────────────────
    from scanner.sector_map import NON_STOCK_SECURITIES
    for pos in list(open_positions):
        if pos["symbol"] in NON_STOCK_SECURITIES:
            price = await _fetch_price(pos["symbol"]) or pos.get("entry_price", 0)
            closed = await close_ai_position(pos["symbol"], price,
                                             "CEF/ETN — not a stock", exit_reason="CEF_FILTER")
            if closed:
                cash += price * (pos.get("shares") or 0)
                logger.warning(f"Force-sold CEF/ETN {pos['symbol']} at ${price:.2f}")
    open_positions = await get_open_ai_positions()

    # Get latest EOD universe scan (preferred) — fall back to any scan
    from database import get_latest_scan, get_latest_scan_by_type
    scan = await get_latest_scan_by_type("massive_eod") or await get_latest_scan()
    if not scan:
        logger.warning("No scan data available for portfolio decisions")
        return

    all_fire_arm = [
        r for r in (scan.get("results") or [])
        if r.get("score", {}).get("tier") in ("FIRE", "ARM")
    ]

    # Hard code-level filter — AI only sees pre-qualified candidates
    qualified = _filter_ai_candidates(all_fire_arm)

    # New Pump candidates from replay history (last 5 days)
    np_candidates = await _get_np_candidates()

    # No qualified candidates → hold cash, skip API call
    if not qualified and not np_candidates:
        no_trade = {
            "decisions": [],
            "portfolio_note": (
                "Нет качественных сигналов сегодня. "
                "Держу cash. Лучшая сделка = никакой сделки при плохом рынке."
            ),
            "no_trade_reason": "no_qualified_candidates",
        }
        await update_portfolio_state(
            cash=cash,
            total_value=state["total_value"],
            invested=state["total_value"] - cash,
            total_pnl_pct=state.get("total_pnl_pct", 0),
            decisions=no_trade,
        )
        logger.info("No qualified candidates — holding cash, skipped AI call")
        return

    # Get user watchlist symbols for context
    from database import get_open_journal_entries
    watchlist_entries = await get_open_journal_entries()
    watchlist_symbols = [e["symbol"] for e in watchlist_entries]

    # Build portfolio context with live prices + risk metrics
    portfolio_ctx = []
    for pos in open_positions:
        price = await _fetch_price(pos["symbol"])
        if not price:
            price = pos.get("current_price") or pos.get("entry_price") or 0
        if price and pos.get("entry_price"):
            await update_ai_position_price(pos["id"], price)
        entry = pos.get("entry_price") or 0
        pnl = round((price - entry) / entry * 100, 2) if entry else 0
        stop = pos.get("stop_loss")
        target = pos.get("target_price")
        dist_to_stop = round((price - stop) / stop * 100, 1) if stop and price else None
        dist_to_target = round((target - price) / price * 100, 1) if target and price else None
        risk_flag = "NEAR_STOP" if dist_to_stop is not None and dist_to_stop < 3 else (
                    "OVER_TARGET" if dist_to_target is not None and dist_to_target <= 0 else "OK")
        portfolio_ctx.append({
            "symbol": pos["symbol"],
            "source": pos.get("source", "scanner"),
            "entry_price": entry,
            "current_price": price,
            "pnl_pct": pnl,
            "max_gain_pct": pos.get("max_gain_pct", 0),
            "max_loss_pct": pos.get("max_loss_pct", 0),
            "days_held": pos.get("days_held", 0),
            "invested_usd": pos.get("invested_usd", 0),
            "stop_loss": stop,
            "target_price": target,
            "target_price_2": pos.get("target_price_2"),
            "tp1_hit": pos.get("tp1_hit", False),
            "dist_to_stop_pct": dist_to_stop,
            "dist_to_target_pct": dist_to_target,
            "risk_flag": risk_flag,
        })

    scan_ctx = [
        {
            "symbol": r["symbol"],
            "source": "scanner",
            "price": r.get("price", 0),
            "tier": r["score"]["tier"],
            "score": round(r["score"]["total_score"], 1),
            "wyckoff": r.get("regime", {}).get("state", "NONE"),
            "cmf_pctl": r.get("indicators", {}).get("cmf_pctl", 0),
            "rsi": (r.get("indicators", {}).get("rsi") or {}).get("value"),
            "vol_ratio": r.get("indicators", {}).get("anomaly_ratio", 0),
            "atr": r.get("indicators", {}).get("atr", 0),
            "hype": (r.get("hype_score") or {}).get("hype_index", 0),
            "rs_score": r.get("indicators", {}).get("rs_score", 0),
            "sector": r.get("sector", ""),
        }
        for r in qualified[:10]
    ]

    np_ctx = np_candidates[:8]

    # Load market regime and sector strength for context
    regime_ctx = {}
    sector_strength_ctx = {}
    try:
        from scanner.market_regime import get_latest_regime, get_latest_sector_strength
        regime_ctx = await get_latest_regime() or {}
        sector_strength_ctx = await get_latest_sector_strength()
    except Exception:
        pass

    strong_sectors = regime_ctx.get("strong_sectors", [])
    weak_sectors = regime_ctx.get("weak_sectors", [])
    regime_name = regime_ctx.get("regime", "NEUTRAL")
    regime_rec = regime_ctx.get("recommendation", "")

    # Portfolio risk summary
    losing_positions = [p for p in portfolio_ctx if p["pnl_pct"] < -3]
    near_stop_positions = [p for p in portfolio_ctx if p.get("risk_flag") == "NEAR_STOP"]
    total_invested = sum(p["invested_usd"] for p in portfolio_ctx)
    portfolio_drawdown = round((state["total_value"] - 2000) / 2000 * 100, 2)

    # Ticker-level win/loss memory from closed position history
    portfolio_memory = await _build_portfolio_memory()
    all_candidate_syms = {r["symbol"] for r in scan_ctx} | {r["symbol"] for r in np_ctx}
    memory_ctx = {sym: m for sym, m in portfolio_memory.items() if sym in all_candidate_syms}

    # Research priors — broad evidence-based biases from Replay + Raw Pattern
    research_priors = await _build_research_priors(scan_ctx, np_ctx)

    prompt = f"""You are an AI trader managing a $2000 paper trading portfolio.
Your goal is to maximize risk-adjusted returns using Wyckoff accumulation and New Pump signals.

CURRENT DATE: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}
CASH: ${cash:.2f} | INVESTED: ${total_invested:.2f} | TOTAL VALUE: ${state['total_value']:.2f}
PORTFOLIO P&L: {portfolio_drawdown:+.1f}%

MARKET REGIME: {regime_name}
Recommendation: {regime_rec}
Strong sectors: {', '.join(strong_sectors) if strong_sectors else 'none'}
Weak sectors: {', '.join(weak_sectors) if weak_sectors else 'none'}

OPEN POSITIONS ({len(portfolio_ctx)} total, {len(near_stop_positions)} near stop, {len(losing_positions)} losing >3%):
{json.dumps(portfolio_ctx, indent=2)}

SCANNER CANDIDATES (Wyckoff/CMF pre-filtered):
{json.dumps(scan_ctx, indent=2)}

NEW PUMP CANDIDATES (NP engine FIRE/STRONG, last 5 days):
{json.dumps(np_ctx, indent=2)}

USER WATCHLIST (manual trades for context):
{watchlist_symbols}

TICKER MEMORY (prior trades in current candidates):
{json.dumps(memory_ctx, indent=2) if memory_ctx else 'none'}

RESEARCH PRIORS (broad biases from Replay + Raw Pattern + Pump Study evidence):
{json.dumps(research_priors, indent=2)}

RISK FLAGS:
- Near stop (within 3%): {[p['symbol'] for p in near_stop_positions] or 'none'}
- Losing >3%: {[p['symbol'] for p in losing_positions] or 'none'}
- Slots used: {len(open_positions)}/5

STRICT RULES (not negotiable):
1. Scanner candidates: FIRE tier or ARM with CMF > 70%ile (pre-filtered)
2. New Pump candidates: FIRE or STRONG label, prefer non-NONE np_setup_via
3. Never buy RSI > 65, hype > 40, Wyckoff = DISTRIBUTION
4. Two-target exits: TP1 = entry + ATR×3.75 (sell 50%), TP2 = entry + ATR×7.5 (sell rest)
   Stop: entry - ATR×1.5. For NP candidates without ATR use price-based estimate.
5. Risk 2% of portfolio per trade via ATR sizing (min $50, max $600)
6. Max 5 positions — prefer cash in RISK_OFF/FEAR regime
7. SELL if: held > 14d without 10% gain, hype > 70, dist_to_stop < 3%, Wyckoff→DISTRIBUTION
8. Never chase: skip if moved >5% today, sector in weak_sectors list
9. Use TICKER MEMORY: avoid repeat losers; prefer proven winners
10. Use RESEARCH PRIORS: downsize/caution candidates with isolated_signal_penalty or
    extreme_anomaly_caution; boost confidence when early_setup / bull_stack / strong_label
    notes stack. Priors do NOT override New Pump source, but shape sizing and tone.

For each BUY include stop_loss, target_price (TP1), target_price_2 (TP2), sell_pct_at_target_1 (default 50).

Respond in Russian. Return JSON only:
{{
  "decisions": [
    {{
      "symbol": "TICK",
      "action": "BUY",
      "price": 13.47,
      "stop_loss": 12.20,
      "target_price": 18.50,
      "target_price_2": 23.50,
      "sell_pct_at_target_1": 50,
      "reason": "подробное объяснение: источник сигнала (scanner/new_pump), ключевые метрики, память по тикеру"
    }},
    {{
      "symbol": "TICK2",
      "action": "SELL",
      "reason": "почему продаём: стоп пробит / цель достигнута / сигнал ослаб / держали слишком долго"
    }}
  ],
  "risk_assessment": "оценка рисков портфеля одним предложением",
  "portfolio_note": "общий комментарий: рыночный контекст и логика решений"
}}"""

    try:
        client = anthropic.AsyncAnthropic(api_key=api_key, timeout=30.0)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.replace("```json", "").replace("```", "").strip()
        result = json.loads(text)
    except Exception as e:
        logger.error(f"Portfolio decisions AI call failed: {e}")
        return

    decisions = result.get("decisions", [])
    executed_buys = 0
    executed_sells = 0

    for d in decisions:
        action = d.get("action", "").upper()
        symbol = d.get("symbol", "").upper()
        reason = d.get("reason", "")

        if action == "BUY":
            price = d.get("price", 0)
            if not price:
                price = await _fetch_price(symbol) or 0
            if price <= 0 or len(open_positions) >= 5:
                continue

            # Find source — check scan_ctx first, then np_ctx
            r_data = next((r for r in scan_ctx if r["symbol"] == symbol), None)
            np_data = next((r for r in np_ctx if r["symbol"] == symbol), None)
            if r_data is None and np_data is not None:
                r_data = np_data
            elif r_data is None:
                r_data = {}
            atr = r_data.get("atr") or 0
            source = r_data.get("source", "scanner")

            if atr and atr > 0:
                amount = _atr_position_size(state["total_value"], price, atr)
            else:
                amount = d.get("amount_usd", 150)

            if cash < amount:
                amount = min(amount, cash)
            if amount < 50:
                continue

            # Compute stop/targets from AI decision (preferred) or ATR fallback
            stop_loss = d.get("stop_loss")
            target_price = d.get("target_price")
            target_price_2 = d.get("target_price_2")
            sell_pct_at_target_1 = d.get("sell_pct_at_target_1", 50)
            if not stop_loss and atr:
                stop_loss = round(price - atr * 1.5, 4)
            if not target_price and atr:
                target_price = round(price + atr * 3.75, 4)
            if not target_price_2 and atr:
                target_price_2 = round(price + atr * 7.5, 4)

            shares = amount / price
            await insert_ai_position(
                symbol=symbol,
                entry_price=price,
                shares=shares,
                invested_usd=amount,
                reason=reason,
                scan_data={**r_data, "atr": atr},
                stop_loss=stop_loss,
                target_price=target_price,
                target_price_2=target_price_2,
                sell_pct_at_target_1=sell_pct_at_target_1,
                source=source,
            )
            cash -= amount
            executed_buys += 1
            open_positions = await get_open_ai_positions()

        elif action == "SELL":
            price = d.get("price", 0)
            if not price:
                price = await _fetch_price(symbol) or 0
            if price <= 0:
                continue
            closed = await close_ai_position(symbol, price, reason, exit_reason="AI_SELL")
            if closed:
                cash += closed.get("current_value", 0)
                executed_sells += 1

    # Recalculate total value
    open_pos = await get_open_ai_positions()
    total_value = cash
    for pos in open_pos:
        price = await _fetch_price(pos["symbol"])
        if price:
            await update_ai_position_price(pos["id"], price)
            total_value += price * (pos.get("shares") or 0)
        else:
            total_value += pos.get("invested_usd") or 0

    invested = total_value - cash
    pnl_pct = (total_value - 2000) / 2000 * 100

    await update_portfolio_state(
        cash=cash,
        total_value=total_value,
        invested=invested,
        total_pnl_pct=round(pnl_pct, 2),
        decisions=result,
    )

    logger.info(f"Portfolio decisions done: {executed_buys} buys, {executed_sells} sells. "
                f"Value: ${total_value:.2f} ({pnl_pct:+.1f}%)")


async def generate_daily_report():
    """
    Runs at 16:30 EST weekdays.
    Generates AI daily report and sends to Telegram.
    """
    logger.info("AI portfolio daily report starting...")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return

    state = await get_portfolio_state()
    positions = await get_open_ai_positions()

    # Update all position values with closing prices + ATR stop check
    total_value = state["cash"]
    pos_ctx = []
    for pos in positions:
        price = await _fetch_price(pos["symbol"])
        if price:
            await update_ai_position_price(pos["id"], price)
            value = price * (pos.get("shares") or 0)

            # ATR-based stop check (P4): close if price fell below ATR stop
            scan_data = pos.get("scan_data") or {}
            atr = scan_data.get("atr") or 0
            if atr and atr > 0 and pos.get("entry_price"):
                atr_stop = pos["entry_price"] - (atr * 1.5)
                if price <= atr_stop:
                    closed = await close_ai_position(pos["symbol"], price, "ATR_STOP_HIT")
                    if closed:
                        total_value += price * (pos.get("shares") or 0)
                        logger.info(f"AI portfolio: {pos['symbol']} ATR-stopped at ${price:.2f} "
                                    f"(stop=${atr_stop:.2f}, entry=${pos['entry_price']:.2f})")
                    continue  # don't add to pos_ctx — now closed

            total_value += value
            pnl = (price - pos["entry_price"]) / pos["entry_price"] * 100 if pos["entry_price"] else 0
            pos_ctx.append({
                "symbol": pos["symbol"],
                "entry": pos["entry_price"],
                "current": price,
                "pnl_pct": round(pnl, 2),
                "days_held": pos["days_held"],
                "invested": pos["invested_usd"],
            })
        else:
            total_value += pos.get("invested_usd") or 0

    total_pnl_pct = (total_value - 2000) / 2000 * 100

    # Get today's closed positions
    all_pos = await get_all_ai_positions(50)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    closed_today = [
        p for p in all_pos
        if p.get("status") == "CLOSED" and (p.get("exit_date") or "").startswith(today_str)
    ]

    prompt = f"""Generate a daily trading report in Russian. Be concise and analytical. Return JSON only.

DATE: {today_str}
PORTFOLIO VALUE: ${total_value:.2f} (started $2000)
TOTAL P&L: {total_pnl_pct:+.1f}%
CASH: ${state['cash']:.2f}

OPEN POSITIONS:
{json.dumps(pos_ctx, indent=2)}

CLOSED TODAY:
{json.dumps([{{'symbol': p['symbol'], 'pnl_pct': p['pnl_pct'], 'reason': p.get('reason', '')}} for p in closed_today], indent=2)}

Return JSON:
{{
  "summary": "2-3 предложения о состоянии портфеля",
  "best_position": "символ и почему держать или null",
  "concern": "что беспокоит или null",
  "tomorrow_plan": "что планирую делать завтра",
  "portfolio_health": "STRONG|NEUTRAL|WEAK"
}}"""

    try:
        client = anthropic.AsyncAnthropic(api_key=api_key, timeout=25.0)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.replace("```json", "").replace("```", "").strip()
        report = json.loads(text)
    except Exception as e:
        logger.error(f"Daily report AI call failed: {e}")
        report = {
            "summary": f"Не удалось сгенерировать отчёт: {e}",
            "portfolio_health": "NEUTRAL",
        }

    await update_portfolio_state(
        cash=state["cash"],
        total_value=total_value,
        invested=total_value - state["cash"],
        total_pnl_pct=round(total_pnl_pct, 2),
        report=report,
    )

    # Send Telegram
    try:
        from alerts.telegram import send_message
        health_emoji = "💚" if report.get("portfolio_health") == "STRONG" else "🔴" if report.get("portfolio_health") == "WEAK" else "🟡"
        msg = (
            f"📊 <b>AI Portfolio Daily Report</b>\n"
            f"{today_str}\n\n"
            f"💰 Value: <b>${total_value:.2f}</b> ({total_pnl_pct:+.1f}%)\n"
            f"💵 Cash: ${state['cash']:.2f}\n\n"
            f"{report.get('summary', '')}\n\n"
            f"🏆 Best: {report.get('best_position', '—')}\n"
            f"⚠️ Concern: {report.get('concern') or 'нет'}\n"
            f"📋 Tomorrow: {report.get('tomorrow_plan', '—')}\n"
            f"{health_emoji} Health: {report.get('portfolio_health', 'NEUTRAL')}"
        )
        await send_message(msg)
    except Exception as e:
        logger.warning(f"Telegram report send failed: {e}")

    logger.info(f"Daily report done. Value: ${total_value:.2f} ({total_pnl_pct:+.1f}%)")
