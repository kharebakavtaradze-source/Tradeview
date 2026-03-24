"""
Journal Auto-Close + AI Trade Analysis
Runs at 16:05 EST weekdays to update open positions and auto-close on stop/target hit.
Tracks SPY daily returns, saves position snapshots, computes alpha / max_gain_day / missed_exit_pct.
Provides cumulative insights endpoint with 6-hour cache.
"""
import json
import logging
import os
import time
from datetime import datetime, timezone

import anthropic
import httpx

from database import (
    get_open_journal_entries,
    get_max_gain_day,
    get_spy_cumulative_for_entry,
    save_position_snapshot,
    update_journal_entry,
)

logger = logging.getLogger(__name__)

# Insights cache: {result, timestamp}
_insights_cache: dict = {}
_INSIGHTS_CACHE_TTL = 3600 * 6  # 6 hours

YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


async def fetch_closing_price(symbol: str) -> float | None:
    """Fetch the latest closing price from Yahoo Finance v7."""
    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    url,
                    params={"symbols": symbol.upper(), "fields": "regularMarketPrice"},
                    headers=YAHOO_HEADERS,
                )
                if resp.status_code != 200:
                    return None
                quotes = resp.json().get("quoteResponse", {}).get("result", [])
                if quotes:
                    return quotes[0].get("regularMarketPrice")
        except Exception as e:
            logger.warning(f"Price fetch failed for {symbol} (attempt {attempt+1}): {e}")
    return None


async def analyze_closed_trade(entry: dict) -> str:
    """Generate AI post-trade analysis in Russian. Returns JSON string."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return ""

    outcome = "WIN" if (entry.get("final_pnl_pct") or 0) > 0 else "LOSS"
    max_gain_day = entry.get("max_gain_day", "?")
    missed = entry.get("missed_exit_pct", 0) or 0
    alpha = entry.get("alpha_pct", 0) or 0

    prompt = f"""Analyze this closed trade and provide insights to improve scanner logic. Respond in Russian. Return JSON only, no other text.

TRADE:
Symbol: {entry['symbol']}
Result: {outcome} {entry.get('final_pnl_pct', 0):+.1f}%
Days held: {entry.get('days_held', 0)}
Exit reason: {entry.get('exit_reason', 'MANUAL')}
Max gain reached: {entry.get('max_gain_pct', 0):+.1f}% on day {max_gain_day}
Max loss reached: {entry.get('max_loss_pct', 0):+.1f}%
Left on table: {missed:.1f}%
Alpha vs SPY: {alpha:+.1f}%

ENTRY SIGNALS:
Score: {entry.get('score', 0)} ({entry.get('tier', '?')})
Wyckoff: {entry.get('entry_wyckoff', '?')}
CMF percentile: {entry.get('entry_cmf_pctl', '?')}
Volume ratio: {entry.get('entry_vol_ratio', '?')}x
Hype index: {entry.get('entry_hype', 0)}/100
Catalyst: {entry.get('catalyst', 'MANUAL')}
Stop: ${entry.get('stop_loss', '?')}
Target: ${entry.get('target_price', '?')}
Notes: {entry.get('notes', 'none')}

Return this JSON:
{{
  "verdict": "{outcome}",
  "what_worked": "одно предложение что сработало",
  "what_failed": "одно предложение что не сработало",
  "key_lesson": "один actionable урок",
  "exit_timing": "вышли рано/поздно/вовремя + почему",
  "alpha_comment": "обогнали/отстали от рынка и почему",
  "signal_quality": {{
    "wyckoff_accurate": true,
    "cmf_accurate": true,
    "volume_accurate": true,
    "hype_accurate": true
  }},
  "suggestion": "конкретное изменение в логике скана"
}}"""

    try:
        client = anthropic.AsyncAnthropic(api_key=api_key, timeout=20.0)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text
        return text.replace("```json", "").replace("```", "").strip()
    except Exception as e:
        logger.warning(f"Trade analysis failed for {entry['symbol']}: {e}")
        return ""


async def auto_close_journal():
    """
    Runs at 16:05 EST weekdays.
    - Fetches SPY daily return for alpha calculation
    - Updates open journal entries with current price, days held, max gain/loss
    - Saves daily position snapshots
    - Auto-closes entries that hit their stop_loss or target_price
    - Computes alpha, max_gain_day, missed_exit_pct on close
    """
    logger.info("Auto-close journal starting...")
    entries = await get_open_journal_entries()
    if not entries:
        logger.info("No open journal entries to update")
        return

    # Fetch SPY price for alpha calculation
    spy_price = await fetch_closing_price("SPY")
    spy_daily_pct = 0.0
    if spy_price:
        # Compare to yesterday's SPY close via a simple ratio proxy
        # We use 0 as fallback if we can't get yesterday's price
        try:
            spy_yesterday = await _fetch_prev_close("SPY")
            if spy_yesterday and spy_yesterday > 0:
                spy_daily_pct = round((spy_price - spy_yesterday) / spy_yesterday * 100, 2)
        except Exception:
            pass

    updated = 0
    closed = 0
    for entry in entries:
        try:
            price = await fetch_closing_price(entry["symbol"])
            if not price:
                continue

            entry_price = entry.get("entry_price", 0)
            pct = (price - entry_price) / entry_price * 100 if entry_price > 0 else 0

            days = entry.get("days_held", 0) + 1
            max_gain = max(entry.get("max_gain_pct") or 0, pct)
            max_loss = min(entry.get("max_loss_pct") or 0, pct)

            # Save daily snapshot
            try:
                await save_position_snapshot(
                    journal_id=entry["id"],
                    day_number=days,
                    price=round(price, 4),
                    pct_from_entry=round(pct, 2),
                    spy_daily_pct=spy_daily_pct,
                )
            except Exception as e:
                logger.warning(f"Snapshot save failed for {entry['symbol']}: {e}")

            update_data = {
                "current_price": round(price, 4),
                "current_pct": round(pct, 2),
                "days_held": days,
                "max_gain_pct": round(max_gain, 2),
                "max_loss_pct": round(max_loss, 2),
                "last_updated": datetime.now(timezone.utc),
            }

            stop = entry.get("stop_loss")
            target = entry.get("target_price")

            if stop and price <= stop:
                spy_total = await get_spy_cumulative_for_entry(entry["id"])
                alpha = round(pct - spy_total, 2)
                mgd = await get_max_gain_day(entry["id"])
                missed_exit = round(max_gain - pct, 2)

                entry_for_analysis = {
                    **entry,
                    "final_pnl_pct": round(pct, 2),
                    "exit_reason": "STOP_HIT",
                    "days_held": days,
                    "max_gain_day": mgd,
                    "missed_exit_pct": missed_exit,
                    "alpha_pct": alpha,
                    "spy_return_pct": round(spy_total, 2),
                }
                ai = await analyze_closed_trade(entry_for_analysis)
                update_data.update({
                    "outcome": "loss",
                    "status": "STOPPED",
                    "exit_reason": "STOP_HIT",
                    "exit_price": round(price, 4),
                    "exit_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "final_pnl_pct": round(pct, 2),
                    "spy_return_pct": round(spy_total, 2),
                    "alpha_pct": alpha,
                    "max_gain_day": mgd,
                    "missed_exit_pct": missed_exit,
                    "ai_analysis": ai,
                })
                closed += 1
                logger.info(f"Auto-stopped {entry['symbol']} at ${price:.2f} ({pct:+.1f}%) alpha={alpha:+.1f}%")

            elif target and price >= target:
                spy_total = await get_spy_cumulative_for_entry(entry["id"])
                alpha = round(pct - spy_total, 2)
                mgd = await get_max_gain_day(entry["id"])
                missed_exit = round(max_gain - pct, 2)

                entry_for_analysis = {
                    **entry,
                    "final_pnl_pct": round(pct, 2),
                    "exit_reason": "TARGET_HIT",
                    "days_held": days,
                    "max_gain_day": mgd,
                    "missed_exit_pct": missed_exit,
                    "alpha_pct": alpha,
                    "spy_return_pct": round(spy_total, 2),
                }
                ai = await analyze_closed_trade(entry_for_analysis)
                update_data.update({
                    "outcome": "win",
                    "status": "CLOSED",
                    "exit_reason": "TARGET_HIT",
                    "exit_price": round(price, 4),
                    "exit_date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                    "final_pnl_pct": round(pct, 2),
                    "spy_return_pct": round(spy_total, 2),
                    "alpha_pct": alpha,
                    "max_gain_day": mgd,
                    "missed_exit_pct": missed_exit,
                    "ai_analysis": ai,
                })
                closed += 1
                logger.info(f"Auto-target hit {entry['symbol']} at ${price:.2f} ({pct:+.1f}%) alpha={alpha:+.1f}%")

            await update_journal_entry(entry["id"], update_data)
            updated += 1

        except Exception as e:
            logger.error(f"Auto-close failed for {entry.get('symbol')}: {e}")

    logger.info(f"Auto-close done: {updated} updated, {closed} closed | SPY day: {spy_daily_pct:+.2f}%")


async def _fetch_prev_close(symbol: str) -> float | None:
    """Fetch previous closing price via Yahoo Finance chart endpoint."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol.upper()}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                url,
                params={"interval": "1d", "range": "5d"},
                headers=YAHOO_HEADERS,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
            closes = data.get("chart", {}).get("result", [{}])[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
            closes = [c for c in closes if c is not None]
            if len(closes) >= 2:
                return closes[-2]
    except Exception as e:
        logger.warning(f"Prev close fetch failed for {symbol}: {e}")
    return None


async def get_cumulative_insights() -> dict:
    """
    Analyze all closed trades with AI analysis. Cache 6h.
    Returns patterns, win rate, signal quality insights.
    """
    now = time.time()
    if _insights_cache.get("result") and now - _insights_cache.get("ts", 0) < _INSIGHTS_CACHE_TTL:
        return {**_insights_cache["result"], "from_cache": True}

    from database import get_journal, get_journal_stats
    entries = await get_journal()
    closed = [e for e in entries if e.get("outcome") in ("win", "loss") and e.get("ai_analysis")]

    if len(closed) < 3:
        return {"message": "Нужно минимум 3 закрытых сделки с AI-анализом"}

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return {"message": "ANTHROPIC_API_KEY not configured"}

    stats = await get_journal_stats()
    wins = [e for e in closed if e["outcome"] == "win"]
    losses = [e for e in closed if e["outcome"] == "loss"]
    avg_return = sum(e.get("gain_pct") or 0 for e in closed) / len(closed)
    avg_alpha = sum(e.get("alpha_pct") or 0 for e in closed) / len(closed)
    avg_hold = sum(e.get("days_held") or 0 for e in closed) / len(closed)
    avg_max_gain_day = sum(e.get("max_gain_day") or 0 for e in closed) / len(closed)
    avg_missed = sum(e.get("missed_exit_pct") or 0 for e in closed) / len(closed)

    analyses = []
    for e in closed:
        analyses.append({
            "symbol": e["symbol"],
            "outcome": e["outcome"],
            "pnl": e.get("gain_pct", 0),
            "days_held": e.get("days_held", 0),
            "tier": e.get("tier"),
            "wyckoff": e.get("entry_wyckoff"),
            "hype": e.get("entry_hype", 0),
            "alpha": e.get("alpha_pct"),
            "missed_exit": e.get("missed_exit_pct"),
            "exit_reason": e.get("exit_reason"),
            "ai": e.get("ai_analysis", ""),
        })

    prompt = f"""Analyze {len(closed)} closed trades from a stock scanner. Find patterns. Respond in Russian. JSON only.

Trades summary:
{json.dumps(analyses, ensure_ascii=False)}

Stats:
- Total: {len(closed)}, Wins: {len(wins)}, Losses: {len(losses)}
- Avg return: {avg_return:.1f}%
- Avg alpha vs SPY: {avg_alpha:.1f}%
- Avg hold: {avg_hold:.1f} days
- Avg max gain day: {avg_max_gain_day:.1f}
- Avg missed exit: {avg_missed:.1f}%

Return:
{{
  "win_rate": {round(len(wins)/len(closed)*100, 1)},
  "best_signal": "какой сигнал лучше всего предсказывал победу",
  "worst_signal": "какой сигнал был самым ненадёжным",
  "best_wyckoff": "какой Wyckoff state работал лучше всего",
  "optimal_hold_days": "X-Y дней на основе данных",
  "hype_sweet_spot": "оптимальный hype при входе",
  "exit_insight": "выходим рано или поздно и на сколько",
  "alpha_insight": "реальный edge vs рынок",
  "top_3_improvements": [
    "конкретное изменение 1",
    "конкретное изменение 2",
    "конкретное изменение 3"
  ],
  "avoid_pattern": "какой паттерн исключить из скана",
  "best_cmf_threshold": "минимальный CMF%ile для входа"
}}"""

    try:
        client = anthropic.AsyncAnthropic(api_key=api_key, timeout=30.0)
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        text = response.content[0].text.replace("```json", "").replace("```", "").strip()
        result = json.loads(text)
        _insights_cache["result"] = result
        _insights_cache["ts"] = now
        return result
    except Exception as e:
        logger.error(f"Insights generation failed: {e}")
        return {"message": f"Analysis failed: {e}"}
