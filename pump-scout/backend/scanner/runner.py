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


# Ribbon secondary pass is for analytical discovery only.
# It intentionally captures liquid compression setups that lack breakout
# volume confirmation and were excluded from the main scoring pipeline.
async def run_ribbon_pass(
    all_candles: dict,
    main_scan_symbols: set,
    spy_pct_5d: float = 0.0,
) -> int:
    """
    Ribbon secondary pass — analytical discovery only.

    Finds tickers with EMA compression that were excluded from the main scan
    (anomaly_ratio < 2.0). Uses already-fetched OHLCV candles — no new
    price data API calls.

    Returns count of ribbon candidates saved to DB.
    """
    from scanner.sector_map import NON_STOCK_SECURITIES

    candidates = []

    for symbol, candles in all_candles.items():
        # Skip ETFs / regime ETFs
        if symbol in REGIME_ETFS:
            continue
        # Skip non-stock securities (CEFs, ETNs)
        if symbol.upper() in NON_STOCK_SECURITIES:
            continue
        # Skip symbols already captured by main scan
        if symbol in main_scan_symbols:
            continue
        # Need enough history for EMA89
        if not candles or len(candles) < 100:
            continue

        try:
            ind = calc_all(candles)
            if not ind:
                continue

            price         = ind.get("price", 0)
            today_vol     = ind.get("today_vol", 0)
            anomaly_ratio = ind.get("anomaly_ratio", 0)
            spread        = ind.get("ema_spread_pct", 999.0)

            # Main scan already took anomaly_ratio >= 2.0
            if anomaly_ratio >= 2.0:
                continue
            # Require EMA compression (spread < 3%)
            if spread >= 3.0:
                continue
            # Minimum liquidity gate
            if today_vol < 300_000:
                continue

            # Relative strength vs SPY (5-day)
            rs_score = 0.0
            if spy_pct_5d != 0.0 and len(candles) >= 6:
                price_5d = candles[-6].get("c", price)
                if price_5d > 0:
                    rs_score = round((price - price_5d) / price_5d * 100 - spy_pct_5d, 2)

            obv_data = ind.get("obv") or {}
            rsi_data = ind.get("rsi") or {}

            candidates.append({
                "symbol":      symbol,
                "price":       price,
                "today_vol":   today_vol,
                "anomaly_ratio": anomaly_ratio,
                "ema8":        ind.get("ema8"),
                "ema13":       ind.get("ema13"),
                "ema20":       ind.get("ema20"),
                "ema21":       ind.get("ema21"),
                "ema34":       ind.get("ema34"),
                "ema50":       ind.get("ema50"),
                "ema55":       ind.get("ema55"),
                "ema89":       ind.get("ema89"),
                "ema200":      ind.get("ema200"),
                "ema_spread_pct":          spread,
                "ribbon_compression":      ind.get("ribbon_compression", "NONE"),
                "bullish_stack":           ind.get("bullish_stack", False),
                "bearish_stack":           ind.get("bearish_stack", False),
                "compression_and_bullish": ind.get("compression_and_bullish", False),
                "ribbon_position":         ind.get("ribbon_position"),
                "ema8_slope":              ind.get("ema8_slope", "FLAT"),
                "cmf_pctl":    ind.get("cmf_pctl"),
                "rsi":         rsi_data.get("value"),
                "bb_sqz_bars": ind.get("bb_sqz_bars", 0),
                "bb_squeeze":  ind.get("bb_squeeze", False),
                "obv_strength": obv_data.get("obv_strength"),
                "rs_score":    rs_score,
                "sector":      None,  # resolved below via batch lookup
            })

        except Exception as e:
            logger.warning(f"Ribbon pass: error processing {symbol}: {e}")
            continue

    if not candidates:
        return 0

    # Batch sector lookup for ribbon symbols (single API round-trip)
    try:
        ribbon_symbols = [c["symbol"] for c in candidates]
        sectors = await get_sectors_batch(ribbon_symbols)
        for c in candidates:
            c["sector"] = sectors.get(c["symbol"], "Unknown")
    except Exception as e:
        logger.warning(f"Ribbon pass: sector lookup failed (non-fatal): {e}")

    # Persist to DB
    try:
        from database import save_ribbon_candidates
        saved = await save_ribbon_candidates(candidates)
        logger.info(f"Ribbon secondary pass: {saved} candidates saved ({len(candidates)} qualified)")
        return saved
    except Exception as e:
        logger.error(f"Ribbon pass: save_ribbon_candidates failed: {e}")
        return 0


async def get_scan_symbols() -> tuple[list[str], dict]:
    """
    Build intraday validation symbol list.

    PIPELINE 2 (Yahoo Intraday) — NOT a universe screener.
    Sources are yesterday's Massive EOD candidates + journal positions.
    Much smaller universe (200–400) vs old Finviz screener (800).

    Falls back to Finviz screener on first run (when no EOD candidates exist yet).
    """
    symbols: set[str] = set()

    # SOURCE 1: Yesterday's FIRE/ARM/BASE candidates from Massive EOD scan
    # These are the signals we want to validate at market open.
    source_eod_candidates = 0
    try:
        from database import get_recent_fire_arm_symbols
        recent_syms = await get_recent_fire_arm_symbols(days=2)
        symbols.update(recent_syms)
        source_eod_candidates = len(recent_syms)
    except Exception as e:
        logger.warning(f"get_scan_symbols: recent candidates lookup failed: {e}")

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

    # SOURCE 3: Regime ETFs (needed for market regime calculation)
    symbols.update(REGIME_ETFS)

    # FALLBACK: If no EOD candidates yet (first run / cold start),
    # use Finviz screener so the system is never empty.
    source_screener = 0
    if source_eod_candidates == 0:
        logger.warning("No EOD candidates found — falling back to Finviz screener (cold start)")
        try:
            screener_syms = await get_tickers()
            symbols.update(screener_syms)
            source_screener = len(screener_syms)
        except Exception as e:
            logger.warning(f"get_scan_symbols: Finviz fallback failed: {e}")

    total = len(symbols)
    source_counts = {
        "eod_candidates": source_eod_candidates,
        "journal":         source_journal,
        "regime_etfs":     len(REGIME_ETFS),
        "screener_fallback": source_screener,
        "total":           total,
        "scan_mode":       "intraday_validation" if source_eod_candidates > 0 else "screener_fallback",
    }

    print("Intraday scan symbols:")
    print(f"  EOD candidates:    {source_eod_candidates}")
    print(f"  Journal positions: {source_journal}")
    print(f"  Regime ETFs:       {len(REGIME_ETFS)}")
    if source_screener:
        print(f"  Screener fallback: {source_screener}")
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

    # Fetch Finviz sector performance once (cached, non-blocking)
    sector_perf: dict = {}
    try:
        from scanner.sector_performance import fetch_sector_performance
        sector_perf = await fetch_sector_performance()
    except Exception as e:
        logger.warning(f"sector_performance fetch failed (non-fatal): {e}")

    # Step 3: Calculate indicators for each
    results = []
    skipped = 0

    # Pre-compute SPY 5-day return for relative strength comparison
    spy_pct_5d = 0.0
    spy_candles = all_data.get("SPY", [])
    if len(spy_candles) >= 6:
        spy_close_now = spy_candles[-1]["c"]
        spy_close_5d = spy_candles[-6]["c"]
        if spy_close_5d > 0:
            spy_pct_5d = (spy_close_now - spy_close_5d) / spy_close_5d * 100

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

            # Relative Strength vs SPY (5-day)
            ticker_pct_5d = indicators.get("price_change_pct_5d", 0.0)
            indicators["rs_score"] = round(ticker_pct_5d - spy_pct_5d, 2)

            regime = detect_regime(candles, precomputed=indicators)
            score = score_ticker(indicators, regime, symbol=symbol)

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
        sectors_data = await get_sectors_batch(symbols)
        from scanner.sector_map import SYMPATHY_INDUSTRIES
        for r in results:
            sec_info = sectors_data.get(r["symbol"], {})
            if isinstance(sec_info, dict):
                r["sector"]   = sec_info.get("sector", "Unknown") or "Unknown"
                r["industry"] = sec_info.get("industry", "") or ""
            else:
                r["sector"]   = sec_info or "Unknown"
                r["industry"] = ""
            # Sympathy strength from industry classification
            if r["industry"]:
                r["sympathy_strength"] = SYMPATHY_INDUSTRIES.get(r["industry"], "WEAK")
            else:
                r["sympathy_strength"] = "UNKNOWN"

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

        # Sector alignment: Finviz live + cycle phase bonus (applied post-sector-resolution)
        from scanner.scoring import apply_cycle_bonus
        from scanner.sector_map import FINVIZ_TO_GICS
        cycle_phase = regime.get("cycle_phase", "NEUTRAL") if regime else "NEUTRAL"
        _TIER_RANK = {"SKIP": 0, "WATCH": 1, "STEALTH": 2, "SYMPATHY": 3, "BASE": 3, "ARM": 4, "FIRE": 5}
        for r in results:
            sector = r.get("sector", "Unknown")
            sc = r["score"]

            # 1. Finviz live sector performance bonus (try GICS name then Finviz name)
            gics_sector = sector
            sp = sector_perf.get(sector) if sector_perf else None
            if not sp and sector_perf:
                # Try mapping via FINVIZ_TO_GICS reverse: find Finviz key whose GICS value matches
                for fv_name, gics_name in FINVIZ_TO_GICS.items():
                    if gics_name == sector:
                        sp = sector_perf.get(fv_name)
                        break
            if sp:
                if sp["change_pct"] > 0.5:
                    sc["total_score"] = min(round(sc["total_score"] + 5, 2), 100)
                    sc["sector_rs_bonus"] = 5
                elif sp["change_pct"] < -1.5:
                    sc["total_score"] = round(sc["total_score"] * 0.90, 2)
                    sc["sector_rs_bonus"] = -10
                    score_now = sc["total_score"]
                    current_tier = sc["tier"]
                    if score_now <= 60 and _TIER_RANK.get(current_tier, 0) >= _TIER_RANK["FIRE"]:
                        sc["tier"] = "ARM"

            # 2. Sector class bonus from A/B/C/D/F classification
            sector_class = sp.get("sector_class", "C") if sp else "C"
            sc["sector_class"] = sector_class
            class_bonus = {"A": 5, "B": 0, "C": 0, "D": -5, "F": -10}.get(sector_class, 0)
            if class_bonus != 0:
                sc["total_score"] = round(min(100, max(0, sc["total_score"] + class_bonus)), 2)
                sc["sector_class_bonus"] = class_bonus
                if sector_class == "F":
                    r["regime_warning"] = True
            else:
                sc["sector_class_bonus"] = 0

            # 3. Cycle phase sector bonus (additive, ±20 cap)
            if sector != "Unknown":
                new_score, cycle_bonus = apply_cycle_bonus(sc["total_score"], sector, cycle_phase)
                sc["total_score"] = new_score
                sc["cycle_phase_bonus"] = cycle_bonus
                sc["cycle_phase"] = cycle_phase
                # Re-check tier after bonus
                if sc["total_score"] > 80 and _TIER_RANK.get(sc["tier"], 0) < _TIER_RANK["FIRE"]:
                    if sc["tier"] not in ("SYMPATHY",):
                        sc["tier"] = "FIRE"
                elif sc["total_score"] > 60 and sc["tier"] in ("BASE", "WATCH", "STEALTH"):
                    sc["tier"] = "ARM"
            else:
                sc["cycle_phase_bonus"] = 0
                sc["cycle_phase"] = cycle_phase

            # 4. Setup quality layers (DISPLAY ONLY — never touches total_score)
            try:
                from scanner.scoring import calc_setup_quality_layers
                # Build sector_data for quality layer from sector_perf entry (sp)
                sector_data_for_layers = sp if sp else {}
                quality_layers = calc_setup_quality_layers(
                    indicators=r["indicators"],
                    regime=r["regime"],
                    market_regime=regime,
                    sector_data=sector_data_for_layers,
                    industry_data=None,  # industry ETF data not per-ticker yet
                )
                r["setup_quality"] = quality_layers
            except Exception as _qe:
                r["setup_quality"] = {"layers": {}, "quality": "MODERATE", "avg": 5.0}

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

    # ── Ribbon secondary pass (non-fatal) ────────────────────────────────────
    # Discovers liquid compression setups excluded from main scan (no vol anomaly).
    ribbon_extra = 0
    try:
        main_symbols = {r["symbol"] for r in final}
        ribbon_extra = await run_ribbon_pass(
            all_candles=all_data,
            main_scan_symbols=main_symbols,
            spy_pct_5d=spy_pct_5d,
        )
        logger.info(f"Ribbon pass added {ribbon_extra} tickers to ribbon_candidates")
    except Exception as e:
        logger.error(f"Ribbon pass failed (non-fatal): {e}")

    return {
        "results":            final,
        "scanned_at":         scan_start.isoformat(),
        "total":              len(final),
        "duration_secs":      round(duration_secs, 1),
        "tier_counts":        tier_counts,
        "sector_strength":    sector_strength if results else {},
        "sector_performance": sector_perf,
        "market_regime":      regime,
        "symbol_sources":     symbol_sources,
        "ribbon_extra_count": ribbon_extra,
        "scan_type":          "yahoo_intraday",
    }
