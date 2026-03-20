"""
Main scan orchestrator — ties together all scanner modules.
"""
import logging
from datetime import datetime

from .finviz import get_tickers
from .yahoo import fetch_batch, fetch_premarket_batch
from .indicators import calc_all
from .wyckoff import detect_regime
from .scoring import score_ticker
from .ai_analyst import analyze_batch

logger = logging.getLogger(__name__)


async def run_scan() -> dict:
    """
    Run a full market scan:
    1. Fetch tickers from Finviz
    2. Download OHLCV data from Yahoo Finance
    3. Calculate indicators + Wyckoff regime
    4. Score each ticker
    5. AI analysis on top 20
    Returns scan result dict.
    """
    print("Starting scan...")
    scan_start = datetime.utcnow()

    # Step 1: Get tickers
    tickers = await get_tickers()
    print(f"Got {len(tickers)} tickers")

    # Step 2: Fetch OHLCV data
    all_data = await fetch_batch(tickers)
    print(f"Loaded data for {len(all_data)} tickers")

    # Step 3: Calculate indicators for each
    results = []
    skipped = 0

    for symbol, candles in all_data.items():
        if len(candles) < 60:
            skipped += 1
            continue

        try:
            indicators = calc_all(candles)
            if not indicators:
                skipped += 1
                continue

            # Skip tickers with avg volume < 200K (illiquid)
            if indicators.get("avg_vol_20", 0) < 200_000:
                skipped += 1
                continue

            regime = detect_regime(candles)
            score = score_ticker(indicators, regime)

            if score["tier"] == "SKIP":
                skipped += 1
                continue

            results.append({
                "symbol": symbol,
                "price": candles[-1]["c"],
                "volume_today": candles[-1]["v"],
                "indicators": indicators,
                "regime": regime,
                "score": score,
                "candles": candles[-100:],  # last 100 bars only
                "scanned_at": scan_start.isoformat(),
                "ai_analysis": None,
            })
        except Exception as e:
            logger.warning(f"Error processing {symbol}: {e}")
            skipped += 1
            continue

    print(f"Scored {len(results)} tickers, skipped {skipped}")

    # Step 4: Sort by score descending
    results.sort(key=lambda x: x["score"]["total_score"], reverse=True)

    # Step 5: Pre-market data for all scored tickers
    scored_symbols = [r["symbol"] for r in results]
    if scored_symbols:
        print(f"Fetching pre-market data for {len(scored_symbols)} tickers...")
        premarket_data = await fetch_premarket_batch(scored_symbols)
        for r in results:
            pm = premarket_data.get(r["symbol"])
            r["premarket"] = pm if pm else {"has_premarket": False, "premarket_pct": 0, "session": None}

    # Step 6: AI analysis for top 20
    if results:
        print(f"Running AI analysis on top {min(20, len(results))} tickers...")
        top20 = await analyze_batch(results)

        # Merge AI analysis back into full results
        top_symbols = {r["symbol"] for r in top20}
        final = top20 + [r for r in results if r["symbol"] not in top_symbols]
    else:
        final = results

    top_symbols_list = [r["symbol"] for r in final[:5]]
    print(f"Scan complete. {len(final)} tickers. Top: {top_symbols_list}")

    scan_end = datetime.utcnow()
    duration_secs = (scan_end - scan_start).total_seconds()

    # Tier counts
    tier_counts = {}
    for r in final:
        tier = r["score"]["tier"]
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    return {
        "results": final,
        "scanned_at": scan_start.isoformat(),
        "total": len(final),
        "duration_secs": round(duration_secs, 1),
        "tier_counts": tier_counts,
    }
