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
from .sector_sympathy import get_sectors_batch, find_sector_leaders, calc_sympathy_score
from .market_regime import calculate_sector_strength, get_latest_regime

logger = logging.getLogger(__name__)

# ETFs used purely for regime detection — excluded from trading results
REGIME_ETFS = {"SPY", "QQQ", "XLE", "XLV", "XLU", "GLD", "IWM"}


async def get_scan_symbols() -> tuple[list[str], dict]:
    """
    Build scan symbol list from 4 dynamic sources. No hardcoded tickers.
    Returns (symbols, source_counts) where source_counts logs the breakdown.
    """
    symbols: set[str] = set()

    # SOURCE 1: Screener (primary — Finviz → Yahoo → static fallback)
    screener_symbols = await get_tickers()
    symbols.update(screener_symbols)
    source_screener = len(screener_symbols)

    # SOURCE 2: Open journal positions — always track what we're holding
    source_journal = 0
    try:
        from database import get_open_journal_entries
        open_positions = await get_open_journal_entries()
        journal_syms = [p["symbol"] for p in open_positions if p.get("symbol")]
        symbols.update(journal_syms)
        source_journal = len(journal_syms)
    except Exception as e:
        logger.warning(f"get_scan_symbols: journal lookup failed: {e}")

    # SOURCE 3: Recent FIRE/ARM candidates (last 7 days, outcome not yet known)
    source_candidates = 0
    try:
        from database import get_recent_fire_arm_symbols
        recent_syms = await get_recent_fire_arm_symbols(days=7)
        symbols.update(recent_syms)
        source_candidates = len(recent_syms)
    except Exception as e:
        logger.warning(f"get_scan_symbols: recent candidates lookup failed: {e}")

    # SOURCE 4: Regime ETFs (needed for market regime calculation)
    symbols.update(REGIME_ETFS)

    total = len(symbols)
    source_counts = {
        "screener": source_screener,
        "journal": source_journal,
        "recent_candidates": source_candidates,
        "regime_etfs": len(REGIME_ETFS),
        "total": total,
    }

    print(f"Scan symbols breakdown:")
    print(f"  Screener:          {source_screener}")
    print(f"  Journal positions: {source_journal}")
    print(f"  Recent FIRE/ARM:   {source_candidates}")
    print(f"  Regime ETFs:       {len(REGIME_ETFS)}")
    print(f"  Total unique:      {total}")

    return list(symbols), source_counts


async def run_scan() -> dict:
    """
    Run a full market scan:
    1. Fetch tickers from Finviz
    2. Download OHLCV data from Yahoo Finance
    3. Calculate indicators + Wyckoff regime + institutional flow
    4. Score each ticker
    4.5. Sector sympathy detection
    5. Pre-market data
    6. AI analysis on top 20
    Returns scan result dict.
    """
    print("Starting scan...")
    scan_start = datetime.utcnow()

    # Step 1: Get symbols from all dynamic sources
    tickers, symbol_sources = await get_scan_symbols()
    print(f"Got {len(tickers)} symbols total")

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

            # Skip tickers where last-day volume < 200K (illiquid)
            if indicators.get("today_vol", 0) < 200_000:
                skipped += 1
                continue

            # VOL ANOMALY must be at least 2x the 20-day average
            if indicators.get("anomaly_ratio", 0) < 2.0:
                skipped += 1
                continue

            regime = detect_regime(candles, precomputed=indicators)
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

    # Filter regime ETFs out of trading results — they are scanned for regime
    # detection only and should not appear as trading candidates
    trading_results = [r for r in results if r["symbol"] not in REGIME_ETFS]
    etf_results = [r for r in results if r["symbol"] in REGIME_ETFS]
    print(f"Trading candidates: {len(trading_results)} (filtered {len(etf_results)} regime ETFs)")
    results = trading_results

    # Initialise for the return value (populated inside the if-block below)
    sector_strength: dict = {}
    regime = await get_latest_regime()

    # Step 4.5: Sector sympathy
    if results:
        print(f"Fetching sectors for {len(results)} tickers...")
        symbols = [r["symbol"] for r in results]
        sectors = await get_sectors_batch(symbols)
        for r in results:
            r["sector"] = sectors.get(r["symbol"], "Unknown")

        sector_leaders = find_sector_leaders(results)
        _TIER_RANK = {"SKIP": 0, "WATCH": 1, "STEALTH": 2, "SYMPATHY": 3, "BASE": 3, "ARM": 4, "FIRE": 5}
        for r in results:
            sympathy = calc_sympathy_score(r, sector_leaders)
            r["sympathy"] = sympathy
            if sympathy["is_sympathy"]:
                current_tier = r["score"]["tier"]
                if sympathy["sympathy_score"] >= 60:
                    if _TIER_RANK.get("SYMPATHY", 0) > _TIER_RANK.get(current_tier, 0):
                        r["score"]["tier"] = "SYMPATHY"
                elif sympathy["sympathy_score"] >= 40 and current_tier == "SKIP":
                    r["score"]["tier"] = "WATCH"

        # Calculate sector strength (saves to DB internally)
        print("Calculating sector strength...")
        sector_strength = await calculate_sector_strength(results)

        # Add regime_warning flag to each result
        weak_sectors = set(regime.get("weak_sectors", [])) if regime else set()
        for r in results:
            r["regime_warning"] = r.get("sector", "Unknown") in weak_sectors

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

    # Save FIRE/ARM tickers as scan candidates (control group)
    try:
        from database import save_scan_candidates
        saved = await save_scan_candidates(final)
        if saved:
            logger.info(f"Saved {saved} scan candidates (FIRE/ARM)")
    except Exception as e:
        logger.warning(f"save_scan_candidates failed (non-fatal): {e}")

    # Update pattern streaks (ARM+ multi-day accumulation tracking)
    try:
        from scanner.pattern_streaks import update_pattern_streaks
        await update_pattern_streaks(final)
    except Exception as e:
        logger.warning(f"update_pattern_streaks failed (non-fatal): {e}")

    # Enrich results with earnings data (one Finnhub API call for full calendar)
    try:
        from data.finnhub_provider import get_earnings_calendar
        earnings_cal = await get_earnings_calendar(days_ahead=14)
        if earnings_cal:
            for r in final:
                info = earnings_cal.get(r["symbol"], {"has_earnings": False})
                r["earnings"] = info
                r["earnings_risk"] = info.get("risk", "NONE") if info.get("has_earnings") else "NONE"
            logger.info(f"Earnings enrichment complete — {len(earnings_cal)} symbols in calendar")
    except Exception as e:
        logger.warning(f"Earnings enrichment failed (non-fatal): {e}")

    return {
        "results": final,
        "scanned_at": scan_start.isoformat(),
        "total": len(final),
        "duration_secs": round(duration_secs, 1),
        "tier_counts": tier_counts,
        "sector_strength": sector_strength if results else {},
        "market_regime": regime,
        "symbol_sources": symbol_sources,
    }
