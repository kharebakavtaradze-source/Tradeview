"""
End-of-day log generator.
Runs at 4:35 PM ET (after journal auto-close + candidate price fill + AI report).
Produces a Markdown file you can upload directly to Claude chat for analysis.
"""
import logging
from datetime import datetime, timezone, timedelta

import httpx

from database import (
    get_journal,
    get_journal_stats,
    get_latest_scan,
    get_watchlist,
    get_portfolio_state,
    get_open_ai_positions,
    get_candidates_missed,
    save_eod_log,
    update_journal_entry,
)

logger = logging.getLogger(__name__)

EASTERN = timezone(timedelta(hours=-4))  # EDT; scheduler handles DST via timezone name

_YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
}


async def _fetch_price(symbol: str) -> float | None:
    """Fetch current market price from Yahoo Finance."""
    url = "https://query1.finance.yahoo.com/v7/finance/quote"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                url,
                params={"symbols": symbol.upper(), "fields": "regularMarketPrice"},
                headers=_YAHOO_HEADERS,
            )
            if resp.status_code == 200:
                quotes = resp.json().get("quoteResponse", {}).get("result", [])
                if quotes:
                    return quotes[0].get("regularMarketPrice")
    except Exception as e:
        logger.warning(f"EOD price fetch failed for {symbol}: {e}")
    return None


def _pct(val) -> str:
    if val is None:
        return "n/a"
    sign = "+" if val >= 0 else ""
    return f"{sign}{val:.2f}%"


def _price(val) -> str:
    if val is None:
        return "n/a"
    return f"${val:.2f}"


async def generate_eod_log() -> str:
    """Pull all data and render a Markdown report. Returns the markdown string."""
    today = datetime.now(EASTERN).strftime("%Y-%m-%d")
    weekday = datetime.now(EASTERN).strftime("%A")
    now_str = datetime.now(EASTERN).strftime("%H:%M ET")

    lines = []

    # ── Header ────────────────────────────────────────────────────────────────
    lines += [
        f"# Pump Scout — End of Day Report",
        f"**Date:** {today} ({weekday})  |  **Generated:** {now_str}",
        "",
        "---",
        "",
    ]

    # ── Today's Scan Summary ─────────────────────────────────────────────────
    lines.append("## Today's Scan")
    try:
        scan = await get_latest_scan()
        if scan:
            results = scan.get("results", [])
            scanned_at = scan.get("scanned_at", "")
            lines.append(f"_Last scan: {scanned_at}_")
            lines.append("")
            tier_order = ["FIRE", "ARM", "BASE", "STEALTH", "SYMPATHY", "FLOW", "SILENT", "HYPE", "WATCH"]
            by_tier: dict = {}
            for r in results:
                t = r.get("tier", "OTHER")
                by_tier.setdefault(t, []).append(r)
            for tier in tier_order:
                tickers = by_tier.get(tier, [])
                if tickers:
                    top = sorted(tickers, key=lambda x: x.get("score", 0), reverse=True)[:5]
                    row = ", ".join(
                        f"**{t['symbol']}** (score {t.get('score', 0):.0f}, {_price(t.get('price'))})"
                        for t in top
                    )
                    lines.append(f"- **{tier}** [{len(tickers)}]: {row}")
            lines.append(f"\n_Total flagged: {len(results)}_")
        else:
            lines.append("_No scan data available._")
    except Exception as e:
        lines.append(f"_Scan data unavailable: {e}_")
    lines.append("")

    # ── Open Positions ────────────────────────────────────────────────────────
    lines.append("## Open Journal Positions")
    try:
        journal = await get_journal()
        open_pos = [e for e in journal if e.get("outcome") == "open"]
        if open_pos:
            # Positions added after 16:05 (auto-close window) have no current_price yet.
            # Fetch and persist prices for them so the report shows live data.
            for e in open_pos:
                if e.get("current_price") is None and e.get("entry_price"):
                    price = await _fetch_price(e["symbol"])
                    if price:
                        entry_price = e["entry_price"]
                        pct = round((price - entry_price) / entry_price * 100, 2)
                        e["current_price"] = price
                        e["current_pct"] = pct
                        try:
                            await update_journal_entry(e["id"], {
                                "current_price": price,
                                "current_pct": pct,
                            })
                        except Exception as upd_err:
                            logger.warning(f"EOD price persist failed for {e['symbol']}: {upd_err}")

            lines.append("| Symbol | Tier | Entry | Current | P&L % | Days | Stop | Target |")
            lines.append("|--------|------|-------|---------|-------|------|------|--------|")
            for e in sorted(open_pos, key=lambda x: x.get("current_pct") or 0, reverse=True):
                lines.append(
                    f"| {e['symbol']} "
                    f"| {e.get('tier') or '-'} "
                    f"| {_price(e.get('entry_price'))} "
                    f"| {_price(e.get('current_price'))} "
                    f"| {_pct(e.get('current_pct'))} "
                    f"| {e.get('days_held') or 0}d "
                    f"| {_price(e.get('stop_loss'))} "
                    f"| {_price(e.get('target_price'))} |"
                )
        else:
            lines.append("_No open positions._")
    except Exception as e:
        lines.append(f"_Journal unavailable: {e}_")
    lines.append("")

    # ── Closed Today ──────────────────────────────────────────────────────────
    lines.append("## Closed Today")
    try:
        closed_today = [
            e for e in journal
            if e.get("outcome") in ("win", "loss")
            and (e.get("exit_date") or "")[:10] == today
        ]
        if closed_today:
            lines.append("| Symbol | Outcome | Entry | Exit | P&L % | Alpha vs SPY | Days | Exit Reason |")
            lines.append("|--------|---------|-------|------|-------|-------------|------|-------------|")
            for e in closed_today:
                outcome_emoji = "WIN" if e["outcome"] == "win" else "LOSS"
                lines.append(
                    f"| {e['symbol']} "
                    f"| {outcome_emoji} "
                    f"| {_price(e.get('entry_price'))} "
                    f"| {_price(e.get('exit_price'))} "
                    f"| {_pct(e.get('final_pnl_pct') or e.get('gain_pct'))} "
                    f"| {_pct(e.get('alpha_pct'))} "
                    f"| {e.get('days_held') or 0}d "
                    f"| {e.get('exit_reason') or 'manual'} |"
                )
        else:
            lines.append("_No positions closed today._")
    except Exception as e:
        lines.append(f"_Closed trades unavailable: {e}_")
    lines.append("")

    # ── Journal Stats ─────────────────────────────────────────────────────────
    lines.append("## Overall Journal Stats")
    try:
        stats = await get_journal_stats()
        lines += [
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total Trades | {stats['total_trades']} |",
            f"| Win Rate | {stats['win_rate_pct']}% ({stats['wins']}W / {stats['losses']}L) |",
            f"| Avg Win | {_pct(stats['avg_gain_winners'])} |",
            f"| Avg Loss | {_pct(stats['avg_loss_losers'])} |",
            f"| Total P&L | {_pct(stats['total_pnl_pct'])} |",
            f"| Best Tier | {stats.get('best_tier') or 'n/a'} |",
            f"| Best Score Range | {stats.get('best_score_range') or 'n/a'} |",
        ]
    except Exception as e:
        lines.append(f"_Stats unavailable: {e}_")
    lines.append("")

    # ── Missed Opportunities ──────────────────────────────────────────────────
    lines.append("## Missed Opportunities (Scan Candidates Not Journaled)")
    try:
        missed = await get_candidates_missed()
        movers = missed.get("top_movers", [])
        if movers:
            lines.append("| Symbol | Tier | Score | Entry Price | Best Move |")
            lines.append("|--------|------|-------|-------------|-----------|")
            for m in movers[:10]:
                best = max(
                    filter(None, [m.get("pct_5d"), m.get("pct_10d"), m.get("pct_20d")]),
                    default=None
                )
                lines.append(
                    f"| {m.get('symbol')} "
                    f"| {m.get('tier') or '-'} "
                    f"| {m.get('score', 0):.0f} "
                    f"| {_price(m.get('price'))} "
                    f"| {_pct(best)} |"
                )
        else:
            lines.append("_No missed opportunities data yet._")
    except Exception as e:
        lines.append(f"_Missed opportunities unavailable: {e}_")
    lines.append("")

    # ── Watchlist ─────────────────────────────────────────────────────────────
    lines.append("## Watchlist")
    try:
        watchlist = await get_watchlist()
        if watchlist:
            symbols = ", ".join(f"**{w['symbol']}**" for w in watchlist)
            lines.append(symbols)
        else:
            lines.append("_Watchlist is empty._")
    except Exception as e:
        lines.append(f"_Watchlist unavailable: {e}_")
    lines.append("")

    # ── AI Portfolio ──────────────────────────────────────────────────────────
    lines.append("## AI Paper Portfolio")
    try:
        state = await get_portfolio_state()
        ai_open = await get_open_ai_positions()
        lines += [
            f"**Total Value:** {_price(state.get('total_value'))}  |  "
            f"**Cash:** {_price(state.get('cash'))}  |  "
            f"**P&L:** {_pct(state.get('total_pnl_pct'))}",
            "",
        ]
        if ai_open:
            lines.append("| Symbol | Entry | P&L % | Days |")
            lines.append("|--------|-------|-------|------|")
            for p in ai_open:
                lines.append(
                    f"| {p['symbol']} "
                    f"| {_price(p.get('entry_price'))} "
                    f"| {_pct(p.get('pnl_pct'))} "
                    f"| {p.get('days_held', 0)}d |"
                )
        else:
            lines.append("_No open AI positions._")
    except Exception as e:
        lines.append(f"_AI portfolio unavailable: {e}_")
    lines.append("")

    # ── Footer ────────────────────────────────────────────────────────────────
    lines += [
        "---",
        "_Generated by Pump Scout. Upload this file to Claude chat for analysis._",
    ]

    return "\n".join(lines)


async def run_eod_log():
    """Entry point called by the scheduler."""
    try:
        logger.info("Generating EOD log...")
        today = datetime.now(EASTERN).strftime("%Y-%m-%d")
        content = await generate_eod_log()
        await save_eod_log(today, content)
        logger.info(f"EOD log saved for {today} ({len(content)} chars)")
    except Exception as e:
        logger.error(f"EOD log generation failed: {e}", exc_info=True)
