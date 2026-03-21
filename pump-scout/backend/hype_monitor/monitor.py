"""
Hype Monitor — Orchestrator
Watches top 30 tickers from the latest scan every 30 minutes.
Compares hype vs volume/price for divergence signals.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from database import get_latest_scan
from hype_monitor.fetcher import fetch_all
from hype_monitor.velocity import calc_velocity
from hype_monitor.hype_score import calc_hype_score
from hype_monitor.divergence import detect_divergences
from hype_monitor.ai_analyst import analyze as ai_analyze
from hype_monitor.alerter import send_hype_alerts, send_hype_summary
from alerts.telegram import is_configured as telegram_configured

logger = logging.getLogger(__name__)

# State from previous cycle: {ticker: hype_score_dict}
_previous_hype_state: dict[str, dict] = {}

# Last completed cycle results: list of per-ticker result dicts
_latest_results: list[dict] = []
_last_run_at: datetime | None = None

# Per-ticker alert history: {ticker: [{type, ts, divergences}]}
_alert_history: list[dict] = []

_MAX_TICKERS = 30
_SEMAPHORE_LIMIT = 3  # concurrent ticker fetches


async def _process_ticker(
    ticker_data: dict[str, Any],
    semaphore: asyncio.Semaphore,
) -> dict[str, Any] | None:
    """Fetch and score one ticker's hype data. Returns result dict or None on failure."""
    ticker = ticker_data.get("symbol", "")
    if not ticker:
        return None

    async with semaphore:
        try:
            raw = await fetch_all(ticker)
            velocity = calc_velocity(raw)
            hype_score = calc_hype_score(raw, velocity)

            prev = _previous_hype_state.get(ticker)
            divergences = detect_divergences(hype_score, velocity, ticker_data, prev)

            news_detail = raw.get("news_detail", {})

            # Only call AI if there are divergences (saves API calls)
            ai_result = None
            if divergences:
                ai_result = await ai_analyze(
                    ticker, hype_score, velocity, divergences, ticker_data, news_detail
                )

            # Send Telegram alerts for this ticker's divergences
            alerted = []
            if divergences and telegram_configured():
                alerted = await send_hype_alerts(
                    ticker, hype_score, velocity, divergences, ticker_data, ai_result
                )

            return {
                "ticker": ticker,
                "hype_score": hype_score,
                "velocity": velocity,
                "divergences": divergences,
                "ai_analysis": ai_result,
                "news": news_detail,
                "alerted": alerted,
                "scan_tier": ticker_data.get("score", {}).get("tier", "WATCH"),
                "scan_score": ticker_data.get("score", {}).get("total_score", 0),
                "price": ticker_data.get("price", 0),
                "price_change_pct": ticker_data.get("indicators", {}).get("price_change_pct", 0),
                "anomaly_ratio": ticker_data.get("indicators", {}).get("anomaly_ratio", 0),
            }

        except Exception as e:
            logger.error(f"Hype monitor failed for {ticker}: {e}", exc_info=True)
            return None


async def run_hype_monitor() -> list[dict[str, Any]]:
    """
    Main entry point — run one full hype monitor cycle.
    Returns list of per-ticker result dicts.
    """
    global _previous_hype_state, _latest_results, _last_run_at, _alert_history

    logger.info("Hype monitor cycle starting...")

    # Load latest scan data
    scan_data = await get_latest_scan()
    if not scan_data:
        logger.info("No scan data available — skipping hype monitor")
        return []

    results_raw = scan_data.get("results", [])
    if not results_raw:
        return []

    # Top N tickers by score
    sorted_results = sorted(
        results_raw,
        key=lambda r: r.get("score", {}).get("total_score", 0),
        reverse=True,
    )
    top_tickers = sorted_results[:_MAX_TICKERS]

    logger.info(f"Hype monitor: processing {len(top_tickers)} tickers")

    semaphore = asyncio.Semaphore(_SEMAPHORE_LIMIT)
    tasks = [_process_ticker(td, semaphore) for td in top_tickers]
    raw_results = await asyncio.gather(*tasks)

    results = [r for r in raw_results if r is not None]

    # Update previous state for next cycle
    for r in results:
        _previous_hype_state[r["ticker"]] = r["hype_score"]

    # Track alert history
    for r in results:
        if r.get("alerted"):
            _alert_history.append({
                "ticker": r["ticker"],
                "ts": datetime.now(timezone.utc).isoformat(),
                "types": r["alerted"],
                "hype_index": r["hype_score"].get("hype_index", 0),
            })
    # Keep last 200 history entries
    _alert_history = _alert_history[-200:]

    # Send summary for HOT/VIRAL tickers
    if telegram_configured():
        await send_hype_summary(results)

    _latest_results = results
    _last_run_at = datetime.now(timezone.utc)

    hot_count = sum(1 for r in results if r["hype_score"].get("hype_tier") in ("HOT", "VIRAL"))
    logger.info(
        f"Hype monitor complete — {len(results)} tickers, "
        f"{hot_count} HOT/VIRAL, "
        f"{sum(len(r.get('divergences',[])) for r in results)} divergences"
    )

    return results


def get_latest_hype_results() -> list[dict]:
    return _latest_results


def get_hype_for_ticker(ticker: str) -> dict | None:
    for r in _latest_results:
        if r.get("ticker") == ticker.upper():
            return r
    return None


def get_alert_history() -> list[dict]:
    return list(reversed(_alert_history))


def get_status() -> dict:
    return {
        "last_run_at": _last_run_at.isoformat() if _last_run_at else None,
        "tickers_monitored": len(_latest_results),
        "hot_tickers": [
            r["ticker"] for r in _latest_results
            if r["hype_score"].get("hype_tier") in ("HOT", "VIRAL")
        ],
        "total_divergences": sum(len(r.get("divergences", [])) for r in _latest_results),
        "alert_count_24h": len(_alert_history),
    }
