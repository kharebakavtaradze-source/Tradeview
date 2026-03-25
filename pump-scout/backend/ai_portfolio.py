"""
AI Paper Trading Portfolio — $1000 virtual account.
AI makes buy/sell decisions daily at 9:00 AM ET using scan results.
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
    insert_ai_position,
    update_ai_position_price,
    update_portfolio_state,
)

logger = logging.getLogger(__name__)

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


async def _fetch_price(symbol: str) -> float | None:
    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                url,
                params={"symbols": symbol.upper(), "fields": "regularMarketPrice"},
                headers=YAHOO_HEADERS,
            )
            if resp.status_code == 200:
                quotes = resp.json().get("quoteResponse", {}).get("result", [])
                if quotes:
                    return quotes[0].get("regularMarketPrice")
    except Exception as e:
        logger.warning(f"Portfolio price fetch failed for {symbol}: {e}")
    return None


async def ai_portfolio_decisions():
    """
    Runs at 9:00 AM ET weekdays.
    AI reviews scan results and open positions, makes BUY/SELL/HOLD/SKIP decisions.
    """
    logger.info("AI portfolio decisions starting...")

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.warning("ANTHROPIC_API_KEY not set — skipping portfolio decisions")
        return

    state = await get_portfolio_state()
    cash = state["cash"]
    open_positions = await get_open_ai_positions()

    # Get latest scan results
    from database import get_latest_scan
    scan = await get_latest_scan()
    if not scan:
        logger.warning("No scan data available for portfolio decisions")
        return

    candidates = [
        r for r in (scan.get("results") or [])
        if r.get("score", {}).get("tier") in ("FIRE", "ARM")
    ][:10]

    # Get user watchlist symbols for context
    from database import get_open_journal_entries
    watchlist_entries = await get_open_journal_entries()
    watchlist_symbols = [e["symbol"] for e in watchlist_entries]

    # Build portfolio context with live prices
    portfolio_ctx = []
    for pos in open_positions:
        price = await _fetch_price(pos["symbol"])
        if price:
            pnl = (price - pos["entry_price"]) / pos["entry_price"] * 100 if pos["entry_price"] else 0
            portfolio_ctx.append({
                "symbol": pos["symbol"],
                "entry_price": pos["entry_price"],
                "current_price": price,
                "pnl_pct": round(pnl, 2),
                "days_held": pos["days_held"],
                "invested_usd": pos["invested_usd"],
            })

    scan_ctx = [
        {
            "symbol": r["symbol"],
            "price": r.get("price", 0),
            "tier": r["score"]["tier"],
            "score": round(r["score"]["total_score"], 1),
            "wyckoff": r.get("regime", {}).get("state", "NONE"),
            "cmf_pctl": r.get("indicators", {}).get("cmf_pctl", 0),
            "vol_ratio": r.get("indicators", {}).get("anomaly_ratio", 0),
            "bb_squeeze": r.get("indicators", {}).get("bb_squeeze", False),
            "rsi": r.get("indicators", {}).get("rsi", {}).get("value"),
        }
        for r in candidates
    ]

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

    # Build concise sector summary
    sector_summary = {
        s: {"avg_score": v.get("avg_score"), "leader": v.get("leader_symbol"), "momentum_pct": v.get("momentum_pct")}
        for s, v in sector_strength_ctx.items()
    }

    prompt = f"""You are an AI trader managing a $1000 paper trading portfolio.
Your goal is to maximize returns using Wyckoff accumulation signals.

CURRENT DATE: {datetime.now(timezone.utc).strftime('%Y-%m-%d')}
CASH AVAILABLE: ${cash:.2f}
TOTAL PORTFOLIO VALUE: ${state['total_value']:.2f}

MARKET REGIME: {regime_name}
Recommendation: {regime_rec}

SECTOR STRENGTH TODAY:
{json.dumps(sector_summary, indent=2)}

RULES FOR TODAY:
Strong sectors: {', '.join(strong_sectors) if strong_sectors else 'All sectors active'}
Weak sectors: {', '.join(weak_sectors) if weak_sectors else 'None'}
- Prefer buying tickers from strong sectors.
- Avoid buying tickers from weak sectors unless signal is extremely strong (FIRE + CMF > 90).

OPEN POSITIONS:
{json.dumps(portfolio_ctx, indent=2)}

TODAY'S SCAN CANDIDATES (FIRE + ARM only):
{json.dumps(scan_ctx, indent=2)}

USER WATCHLIST SYMBOLS (high-priority):
{watchlist_symbols}

RULES:
- Maximum 5 open positions at once (currently {len(open_positions)})
- Minimum position size: $50, Maximum: $300
- FIRE tier = allocate more, ARM = allocate less
- Never buy if CMF < 20th percentile
- Never buy if hype index > 60
- Sell if position held > 14 days without 10% gain
- Consider user watchlist as high-priority candidates

Respond in Russian. Return JSON only:
{{
  "decisions": [
    {{
      "symbol": "TICK",
      "action": "BUY",
      "price": 13.47,
      "amount_usd": 200,
      "reason": "краткое объяснение на русском"
    }},
    {{
      "symbol": "TICK2",
      "action": "SELL",
      "price": 15.20,
      "reason": "краткое объяснение"
    }},
    {{
      "symbol": "TICK3",
      "action": "SKIP",
      "reason": "краткое объяснение"
    }}
  ],
  "portfolio_note": "общий комментарий о состоянии портфеля"
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
            amount = d.get("amount_usd", 100)
            price = d.get("price", 0)
            if not price:
                price = await _fetch_price(symbol) or 0
            if price <= 0 or cash < amount or len(open_positions) >= 5:
                continue
            shares = amount / price
            await insert_ai_position(
                symbol=symbol,
                entry_price=price,
                shares=shares,
                invested_usd=amount,
                reason=reason,
                scan_data=next((r for r in scan_ctx if r["symbol"] == symbol), None),
            )
            cash -= amount
            executed_buys += 1
            open_positions = await get_open_ai_positions()  # refresh count

        elif action == "SELL":
            price = d.get("price", 0)
            if not price:
                price = await _fetch_price(symbol) or 0
            if price <= 0:
                continue
            closed = await close_ai_position(symbol, price, reason)
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
    pnl_pct = (total_value - 1000) / 1000 * 100

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

    # Update all position values with closing prices
    total_value = state["cash"]
    pos_ctx = []
    for pos in positions:
        price = await _fetch_price(pos["symbol"])
        if price:
            await update_ai_position_price(pos["id"], price)
            value = price * (pos.get("shares") or 0)
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

    total_pnl_pct = (total_value - 1000) / 1000 * 100

    # Get today's closed positions
    all_pos = await get_all_ai_positions(50)
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    closed_today = [
        p for p in all_pos
        if p.get("status") == "CLOSED" and (p.get("exit_date") or "").startswith(today_str)
    ]

    prompt = f"""Generate a daily trading report in Russian. Be concise and analytical. Return JSON only.

DATE: {today_str}
PORTFOLIO VALUE: ${total_value:.2f} (started $1000)
TOTAL P&L: {total_pnl_pct:+.1f}%
CASH: ${state['cash']:.2f}

OPEN POSITIONS:
{json.dumps(pos_ctx, indent=2)}

CLOSED TODAY:
{json.dumps([{{'symbol': p['symbol'], 'pnl_pct': p['pnl_pct'], 'reason': p.get('reason', '')}} for p in closed_today], indent=2)}

Return JSON:
{{
  "summary": "2-3 предложения о состоянии портфеля",
  "best_position": "символ и почему держать",
  "concern": "что беспокоит или null",
  "tomorrow_plan": "что планирую делать завтра",
  "portfolio_health": "STRONG"
}}"""

    try:
        client = anthropic.AsyncAnthropic(api_key=api_key, timeout=20.0)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.replace("```json", "").replace("```", "").strip()
        report = json.loads(text)
    except Exception as e:
        logger.error(f"Daily report AI call failed: {e}")
        report = {"summary": "Report generation failed.", "portfolio_health": "NEUTRAL"}

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
