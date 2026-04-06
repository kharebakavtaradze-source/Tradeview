"""
Journal Auto-Close + AI Trade Analysis
Runs at 16:05 EST weekdays to update open positions and auto-close on stop/target hit.
Tracks SPY daily returns, saves position snapshots, computes alpha / max_gain_day / missed_exit_pct.
Provides cumulative insights endpoint with 6-hour cache.
"""
import asyncio
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
    """Fetch the latest market price via Yahoo Finance v8/finance/chart (same as scanner)."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol.upper()}"
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    url,
                    params={"interval": "1d", "range": "5d"},
                    headers=YAHOO_HEADERS,
                )
                if resp.status_code != 200:
                    await asyncio.sleep(2 ** attempt)
                    continue
                result = resp.json().get("chart", {}).get("result") or []
                if result:
                    price = result[0].get("meta", {}).get("regularMarketPrice")
                    if price:
                        return price
        except Exception as e:
            logger.warning(f"Price fetch failed for {symbol} (attempt {attempt+1}): {e}")
            await asyncio.sleep(2 ** attempt)
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


async def update_journal_prices_intraday():
    """
    Runs every 5 minutes during market hours (9:30–16:00 ET).
    Fetches live prices for all open journal entries and persists
    current_price + current_pct to DB so the journal shows live P&L
    even between page loads and outside market hours.
    """
    entries = await get_open_journal_entries()
    if not entries:
        return

    symbols = list({e["symbol"] for e in entries})
    entry_map = {e["symbol"]: e for e in entries}

    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                url,
                params={"symbols": ",".join(symbols), "fields": "regularMarketPrice"},
                headers=YAHOO_HEADERS,
            )
            if resp.status_code != 200:
                return
            quotes = resp.json().get("quoteResponse", {}).get("result", [])
            for q in quotes:
                sym = q.get("symbol")
                price = q.get("regularMarketPrice")
                if not sym or not price:
                    continue
                entry = entry_map.get(sym)
                if not entry:
                    continue
                entry_price = entry.get("entry_price", 0)
                pct = round((price - entry_price) / entry_price * 100, 2) if entry_price else 0
                await update_journal_entry(entry["id"], {
                    "current_price": round(price, 4),
                    "current_pct": pct,
                })
    except Exception as e:
        logger.warning(f"Intraday price update failed: {e}")


async def _batch_fetch_prices(symbols: list[str]) -> dict[str, float]:
    """Batch-fetch latest prices for a list of symbols via Yahoo Finance v7.
    Returns {symbol: price} for all successful lookups."""
    if not symbols:
        return {}
    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    result: dict[str, float] = {}
    # Yahoo accepts up to ~200 symbols in one call; chunk just in case
    chunk_size = 50
    for i in range(0, len(symbols), chunk_size):
        chunk = symbols[i : i + chunk_size]
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=15.0) as client:
                    resp = await client.get(
                        url,
                        params={"symbols": ",".join(chunk), "fields": "regularMarketPrice"},
                        headers=YAHOO_HEADERS,
                    )
                    if resp.status_code != 200:
                        break
                    quotes = resp.json().get("quoteResponse", {}).get("result", [])
                    for q in quotes:
                        sym = q.get("symbol")
                        price = q.get("regularMarketPrice")
                        if sym and price:
                            result[sym] = price
                    break  # success
            except Exception as e:
                logger.warning(f"Batch price fetch attempt {attempt+1} failed: {e}")
                if attempt < 2:
                    await asyncio.sleep(2 ** attempt)
    return result


async def auto_close_journal(dry_run: bool = False):
    """
    Runs at 16:05 EST weekdays.
    - Batch-fetches all prices in a single Yahoo Finance call
    - Updates open journal entries with current price, days held, max gain/loss
    - Saves daily position snapshots
    - Auto-closes entries that hit their stop_loss or target_price
    - Computes alpha, max_gain_day, missed_exit_pct on close

    If dry_run=True, returns what WOULD be closed without writing to DB.
    """
    logger.info(f"Auto-close journal starting... (dry_run={dry_run})")
    entries = await get_open_journal_entries()
    if not entries:
        logger.info("No open journal entries to update")
        return {"updated": 0, "closed": 0, "skipped": 0, "dry_run": dry_run}

    # --- Batch-fetch all prices (including SPY) in one go ---
    all_symbols = list({e["symbol"] for e in entries} | {"SPY"})
    prices = await _batch_fetch_prices(all_symbols)

    spy_price = prices.get("SPY")
    spy_daily_pct = 0.0
    if spy_price:
        try:
            spy_yesterday = await _fetch_prev_close("SPY")
            if spy_yesterday and spy_yesterday > 0:
                spy_daily_pct = round((spy_price - spy_yesterday) / spy_yesterday * 100, 2)
        except Exception:
            pass

    updated = 0
    closed = 0
    skipped = 0
    dry_run_results = []

    for entry in entries:
        sym = entry["symbol"]
        price = prices.get(sym)
        if not price:
            logger.warning(f"No price for {sym} — skipping")
            skipped += 1
            continue

        try:
            entry_price = entry.get("entry_price", 0)
            pct = (price - entry_price) / entry_price * 100 if entry_price > 0 else 0

            days = entry.get("days_held", 0) + 1
            max_gain = max(entry.get("max_gain_pct") or 0, pct)
            max_loss = min(entry.get("max_loss_pct") or 0, pct)

            stop = entry.get("stop_loss")
            target = entry.get("target_price")

            should_stop = stop and price <= stop
            should_target = target and price >= target

            if dry_run:
                dry_run_results.append({
                    "symbol": sym,
                    "price": round(price, 4),
                    "pct": round(pct, 2),
                    "stop": stop,
                    "target": target,
                    "would_close": "STOP_HIT" if should_stop else ("TARGET_HIT" if should_target else None),
                })
                continue

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
                logger.warning(f"Snapshot save failed for {sym}: {e}")

            update_data = {
                "current_price": round(price, 4),
                "current_pct": round(pct, 2),
                "days_held": days,
                "max_gain_pct": round(max_gain, 2),
                "max_loss_pct": round(max_loss, 2),
                "last_updated": datetime.now(timezone.utc),
            }

            if should_stop or should_target:
                spy_total = await get_spy_cumulative_for_entry(entry["id"])
                alpha = round(pct - spy_total, 2)
                mgd = await get_max_gain_day(entry["id"])
                missed_exit = round(max_gain - pct, 2)
                exit_reason = "STOP_HIT" if should_stop else "TARGET_HIT"
                outcome = "loss" if should_stop else "win"
                status = "STOPPED" if should_stop else "CLOSED"

                entry_for_analysis = {
                    **entry,
                    "final_pnl_pct": round(pct, 2),
                    "exit_reason": exit_reason,
                    "days_held": days,
                    "max_gain_day": mgd,
                    "missed_exit_pct": missed_exit,
                    "alpha_pct": alpha,
                    "spy_return_pct": round(spy_total, 2),
                }
                ai = await analyze_closed_trade(entry_for_analysis)
                update_data.update({
                    "outcome": outcome,
                    "status": status,
                    "exit_reason": exit_reason,
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
                logger.info(f"Auto-{exit_reason} {sym} at ${price:.2f} ({pct:+.1f}%) alpha={alpha:+.1f}%")

            await update_journal_entry(entry["id"], update_data)
            updated += 1

        except Exception as e:
            logger.error(f"Auto-close failed for {sym}: {e}")
            skipped += 1

    if dry_run:
        logger.info(f"Dry-run complete: {len(dry_run_results)} entries checked")
        return {"dry_run": True, "entries": dry_run_results}

    logger.info(f"Auto-close done: {updated} updated, {closed} closed, {skipped} skipped | SPY day: {spy_daily_pct:+.2f}%")
    return {"updated": updated, "closed": closed, "skipped": skipped, "spy_daily_pct": spy_daily_pct}


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
    avg_return = sum(e.get("final_pnl_pct") or e.get("gain_pct") or 0 for e in closed) / len(closed)
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
