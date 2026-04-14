"""
Massive EOD Universe Scanner — Pipeline 1.

Runs once daily at 17:00 ET via scheduler.
Fetches ALL US stocks EOD data in a single Polygon API call,
then scores the top volume candidates using the full indicator stack.

Architecture:
  1. fetch_grouped_daily()  → 1 API call → ~5000 US stocks
  2. Price/volume filter    → ~2000–3000 pass
  3. Volume rank            → top 600 for full scoring
  4. fetch_candles_massive  → 600 individual history calls (batched)
  5. calc_all()             → full indicators
  6. detect_regime()        → Wyckoff state
  7. score_ticker()         → tier + total_score
  8. Sector enrichment      → get_sectors_batch()
  9. save_scan()            → persisted as scan_type='massive_eod'
  10. save_scan_candidates  → FIRE/ARM saved for tomorrow's intraday validation
  11. Ribbon pass           → EMA compression from full universe
  12. Unknown sector enrich → fetch_ticker_details for sector_cache
"""
import asyncio
import logging
from datetime import datetime, date

from scanner.massive_data import (
    fetch_grouped_daily,
    fetch_candles_massive,
    fetch_ticker_details,
    fetch_ticker_type,
    get_last_trading_day,
    get_us_etf_symbols,
)
from scanner.stock_universe_filter import is_common_stock, get_universe_filter_reason
from scanner.indicators import calc_all
from scanner.wyckoff import detect_regime
from scanner.scoring import score_ticker

logger = logging.getLogger(__name__)

# Filters for initial universe pass (applied to grouped daily data)
MIN_VOLUME   = 200_000   # at least 200K shares traded today
MIN_PRICE    = 1.50      # avoid true pennies
MAX_PRICE    = 500.0     # avoid Berkshire / massive stocks

# How many candidates get full history + indicator scoring
MAX_CANDIDATES = 3000

# Concurrent Polygon calls per batch (stay polite to API)
BATCH_SIZE = 40

# ETFs excluded from trading results (used for regime detection only)
_REGIME_ETFS = {"SPY", "QQQ", "XLE", "XLV", "XLU", "GLD", "IWM"}

# ── Live progress tracker ─────────────────────────────────────────────────────
# Module-level dict updated throughout the scan. Polled by /api/admin/universe-scan/status.
_progress: dict = {
    "running":           False,
    "phase":             "idle",          # idle | fetching_universe | filtering | scoring | enriching | saving | done | error
    "started_at":        None,
    "finished_at":       None,
    "target_date":       None,
    "universe_raw":      0,               # total tickers returned by grouped daily
    "universe_filtered": 0,               # after price/volume filter
    "candidates_total":  0,               # top N selected for full scoring
    "candidates_done":   0,               # scored so far
    "results_count":     0,               # passed scoring (not SKIP)
    "fire_count":        0,
    "arm_count":         0,
    "errors":            0,
    "elapsed_secs":      0,
    "eta_secs":          None,            # estimated seconds remaining
    "last_error":        None,
    "last_scan":         None,            # summary of last completed scan
}


def get_progress() -> dict:
    """Return a copy of the current scan progress dict."""
    p = dict(_progress)
    if p["running"] and p["started_at"]:
        p["elapsed_secs"] = round((datetime.utcnow() - p["started_at"]).total_seconds())
        # ETA: extrapolate from scoring rate
        done  = p["candidates_done"]
        total = p["candidates_total"]
        if done > 0 and total > done:
            rate = p["elapsed_secs"] / done          # seconds per candidate
            p["eta_secs"] = round(rate * (total - done))
        else:
            p["eta_secs"] = None
    return p


def _update(**kwargs):
    _progress.update(kwargs)
    if _progress.get("running") and _progress.get("started_at"):
        _progress["elapsed_secs"] = round(
            (datetime.utcnow() - _progress["started_at"]).total_seconds()
        )


async def run_universe_scan(target_date: str = None) -> dict:
    """
    Full EOD universe scan via Massive/Polygon.
    Called by scheduler at 22:00 ET Mon–Fri.

    Returns scan result dict compatible with save_scan().
    """
    scan_start = datetime.utcnow()

    if not target_date:
        target_date = get_last_trading_day(offset=0)

    _update(
        running=True, phase="fetching_universe",
        started_at=scan_start, finished_at=None, target_date=target_date,
        universe_raw=0, universe_filtered=0, candidates_total=0,
        candidates_done=0, results_count=0, fire_count=0, arm_count=0,
        errors=0, last_error=None,
    )
    logger.info(f"=== Universe Scan starting: {target_date} ===")

    # ── STEP 1: One API call → all US stocks ────────────────────────────────
    all_bars = await fetch_grouped_daily(target_date)
    if not all_bars:
        _update(running=False, phase="error", finished_at=datetime.utcnow(),
                last_error="No trading data found (tried 5 days back — check API key / Polygon plan)")
        logger.error("Universe scan aborted: fetch_grouped_daily returned empty after 5 attempts")
        return {
            "results": [], "scan_type": "massive_eod",
            "scanned_at": scan_start.isoformat(),
            "total": 0, "error": "No data from Massive API",
        }

    _update(phase="filtering", universe_raw=len(all_bars))
    logger.info(f"Universe: {len(all_bars)} tickers in grouped daily")

    # ── STEP 2: Load ETF exclusion list + apply filters ─────────────────────
    try:
        from scanner.sector_map import NON_STOCK_SECURITIES
    except Exception:
        NON_STOCK_SECURITIES = set()

    # Fetch US ETF symbol list (cached 7 days, one call per week)
    _update(phase="filtering_etf")
    etf_symbols: set[str] = set()
    try:
        etf_symbols = await get_us_etf_symbols()
        logger.info(f"Exclusion list: {len(etf_symbols)} non-stock symbols (ETF/ETN/ETV/FUND/CEF + hardcoded)")
    except Exception as e:
        logger.warning(f"ETF list fetch failed (non-fatal, ETFs may slip through): {e}")
    _update(phase="filtering")

    filtered = {}
    skip_regime = skip_etf = skip_cef = skip_vol = skip_price = 0
    for sym, bar in all_bars.items():
        if sym in _REGIME_ETFS:
            skip_regime += 1; continue
        if sym.upper() in etf_symbols:
            skip_etf += 1; continue
        if sym.upper() in NON_STOCK_SECURITIES:
            skip_cef += 1; continue
        vol   = bar["volume"]
        close = bar["close"]
        if vol < MIN_VOLUME:
            skip_vol += 1; continue
        if not (MIN_PRICE <= close <= MAX_PRICE):
            skip_price += 1; continue
        filtered[sym] = bar

    logger.info(
        f"After filters: {len(filtered)} stocks "
        f"(skipped: {skip_regime} regime ETFs, {skip_etf} ETFs, "
        f"{skip_cef} CEF/ETN, {skip_vol} low-vol, {skip_price} price)"
    )

    # ── STEP 3: Pre-score → select top candidates for full scoring ───────────
    # Rank by dollar volume × price-move bonus rather than raw share volume.
    # Dollar volume = close × volume (de-emphasises penny-stock noise).
    # Move bonus = 1 + |day_change_pct| / 10 (rewards stocks that actually moved).
    # Stocks with $1M+ daily dollar vol AND a 5% move rank 1.5× higher than flat ones.
    def _pre_score(bar: dict) -> float:
        close  = bar["close"]
        vol    = bar["volume"]
        open_  = bar.get("open") or close
        dollar_vol = close * vol
        move_pct = abs(close - open_) / open_ * 100 if open_ > 0 else 0
        return dollar_vol * (1 + move_pct / 10)

    ranked = sorted(filtered.items(), key=lambda kv: _pre_score(kv[1]), reverse=True)
    candidates = [sym for sym, _ in ranked[:MAX_CANDIDATES]]
    _update(phase="scoring", universe_filtered=len(filtered), candidates_total=len(candidates))
    logger.info(
        f"Top {len(candidates)} candidates selected by dollar-vol×move pre-score "
        f"(from {len(filtered)} filtered stocks)"
    )

    # ── STEP 4–7: Fetch candle history, calc indicators, score ──────────────
    results   = []
    errors    = 0
    all_scored_candles: dict = {}  # kept for ribbon pass

    # Fetch market regime once (used in scoring)
    try:
        from scanner.market_regime import get_latest_regime
        market_regime = await get_latest_regime() or {}
    except Exception:
        market_regime = {}

    # Pre-compute SPY 5-day return for relative strength
    spy_pct_5d = 0.0
    spy_bar = all_bars.get("SPY") or all_bars.get("spy")
    if spy_bar:
        # Will compute properly after candle fetch; use EOD approximation
        spy_pct_5d = 0.0  # updated below after SPY candles fetched

    skip_type = 0  # count of symbols removed by per-symbol type verification

    for i in range(0, len(candidates), BATCH_SIZE):
        batch = candidates[i : i + BATCH_SIZE]

        # Fetch candle history AND Polygon security type concurrently.
        # Type check runs in parallel — no added wall-clock time.
        # This catches ETFs/funds that Polygon mis-classifies as CS in its
        # reference data, which the bulk exclusion list cannot catch.
        candle_tasks = [fetch_candles_massive(sym, days=200) for sym in batch]
        type_tasks   = [fetch_ticker_type(sym)               for sym in batch]
        all_gathered = await asyncio.gather(*candle_tasks, *type_tasks, return_exceptions=True)
        candle_results = all_gathered[:len(batch)]
        type_results   = all_gathered[len(batch):]

        for sym, candles, ticker_type in zip(batch, candle_results, type_results):
            # Per-symbol type guard: hard allowlist — only common stocks.
            # None / Exception means type lookup failed → allow through (conservative).
            if not isinstance(ticker_type, Exception) and ticker_type is not None:
                meta = {"type": ticker_type}
                if not is_common_stock(meta):
                    reason = get_universe_filter_reason(meta)
                    logger.info(
                        f"Skipping {sym}: type={ticker_type!r} "
                        f"universe_filter_reason={reason}"
                    )
                    skip_type += 1
                    continue

            if isinstance(candles, Exception):
                logger.warning(f"Candles exception for {sym}: {candles}")
                errors += 1
                continue

            if not candles or len(candles) < 60:
                continue  # not enough history

            # Append today's EOD bar so indicators include today's close
            today_bar = all_bars.get(sym)
            if today_bar:
                candles = candles + [{
                    "o": today_bar["open"],
                    "h": today_bar["high"],
                    "l": today_bar["low"],
                    "c": today_bar["close"],
                    "v": today_bar["volume"],
                    "t": int(datetime.utcnow().timestamp() * 1000),
                }]

            try:
                indicators = calc_all(candles)
                if not indicators:
                    continue

                # Relative strength vs SPY (5-day)
                ticker_pct_5d = indicators.get("price_change_pct_5d", 0.0)
                indicators["rs_score"] = round(ticker_pct_5d - spy_pct_5d, 2)

                regime = detect_regime(candles, precomputed=indicators)
                score  = score_ticker(indicators, regime, symbol=sym)

                if score["tier"] == "SKIP":
                    continue

                price = today_bar["close"] if today_bar else (candles[-1]["c"] if candles else 0)

                result = {
                    "symbol":      sym,
                    "price":       price,
                    "volume_today": today_bar["volume"] if today_bar else indicators.get("today_vol", 0),
                    "indicators":  indicators,
                    "regime":      regime,
                    "score":       score,
                    "scanned_at":  scan_start.isoformat(),
                    "ai_analysis": None,
                    "scan_type":   "massive_eod",
                    "scan_date":   target_date,
                }
                results.append(result)
                all_scored_candles[sym] = candles  # keep for ribbon pass

            except Exception as e:
                logger.warning(f"Scoring failed for {sym}: {e}")
                errors += 1

        done_so_far = min(i + BATCH_SIZE, len(candidates))
        fire_so_far = sum(1 for r in results if r["score"]["tier"] == "FIRE")
        arm_so_far  = sum(1 for r in results if r["score"]["tier"] == "ARM")
        _update(
            candidates_done=done_so_far,
            results_count=len(results),
            fire_count=fire_so_far,
            arm_count=arm_so_far,
            errors=errors,
        )
        logger.info(
            f"Universe scan: {done_so_far}/{len(candidates)} scored | "
            f"{len(results)} results ({fire_so_far} FIRE, {arm_so_far} ARM)"
        )

        # Brief pause between batches to be polite to Polygon API
        await asyncio.sleep(0.3)

    logger.info(f"Scoring complete: {len(results)} scored, {errors} errors, {skip_type} skipped by type check")
    _update(phase="enriching")

    # ── STEP 8: Sector enrichment via get_sectors_batch ─────────────────────
    if results:
        try:
            from scanner.sector_sympathy import get_sectors_batch, find_sector_leaders, calc_sympathy_score
            from scanner.sector_map import SYMPATHY_INDUSTRIES
            syms = [r["symbol"] for r in results]
            sectors_data = await get_sectors_batch(syms)
            for r in results:
                sec_info = sectors_data.get(r["symbol"], {})
                if isinstance(sec_info, dict):
                    r["sector"]   = sec_info.get("sector", "Unknown") or "Unknown"
                    r["industry"] = sec_info.get("industry", "") or ""
                else:
                    r["sector"]   = sec_info or "Unknown"
                    r["industry"] = ""
                r["sympathy_strength"] = (
                    SYMPATHY_INDUSTRIES.get(r["industry"], "WEAK")
                    if r["industry"] else "UNKNOWN"
                )
        except Exception as e:
            logger.warning(f"Sector enrichment failed (non-fatal): {e}")
            for r in results:
                r.setdefault("sector", "Unknown")
                r.setdefault("industry", "")
                r.setdefault("sympathy_strength", "UNKNOWN")

    # Sector strength calculation (saves to DB)
    sector_strength: dict = {}
    if results:
        try:
            from scanner.market_regime import calculate_sector_strength
            sector_strength = await calculate_sector_strength(results)
        except Exception as e:
            logger.warning(f"calculate_sector_strength failed (non-fatal): {e}")

    # Finviz sector performance bonus (same as intraday runner)
    sector_perf: dict = {}
    try:
        from scanner.sector_performance import fetch_sector_performance
        from scanner.scoring import apply_cycle_bonus
        from scanner.sector_map import FINVIZ_TO_GICS
        sector_perf = await fetch_sector_performance()
        cycle_phase = market_regime.get("cycle_phase", "NEUTRAL")
        _TIER_RANK  = {"SKIP": 0, "WATCH": 1, "STEALTH": 2, "SYMPATHY": 3, "BASE": 3, "ARM": 4, "FIRE": 5}
        weak_sectors = set(market_regime.get("weak_sectors", []))

        for r in results:
            sector = r.get("sector", "Unknown")
            r["regime_warning"] = sector in weak_sectors
            sc = r["score"]

            sp = sector_perf.get(sector)
            if not sp and sector_perf:
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
                    if sc["total_score"] <= 60 and _TIER_RANK.get(sc["tier"], 0) >= _TIER_RANK["FIRE"]:
                        sc["tier"] = "ARM"

                sector_class = sp.get("sector_class", "C")
                sc["sector_class"] = sector_class
                class_bonus = {"A": 5, "B": 0, "C": 0, "D": -5, "F": -10}.get(sector_class, 0)
                if class_bonus != 0:
                    sc["total_score"] = round(min(100, max(0, sc["total_score"] + class_bonus)), 2)
                    sc["sector_class_bonus"] = class_bonus
                    if sector_class == "F":
                        r["regime_warning"] = True
                else:
                    sc["sector_class_bonus"] = 0

            if sector != "Unknown":
                new_score, cycle_bonus = apply_cycle_bonus(sc["total_score"], sector, cycle_phase)
                sc["total_score"] = new_score
                sc["cycle_phase_bonus"] = cycle_bonus
                sc["cycle_phase"] = cycle_phase
                if sc["total_score"] > 80 and _TIER_RANK.get(sc["tier"], 0) < _TIER_RANK["FIRE"]:
                    if sc["tier"] not in ("SYMPATHY",):
                        sc["tier"] = "FIRE"
                elif sc["total_score"] > 60 and sc["tier"] in ("BASE", "WATCH", "STEALTH"):
                    sc["tier"] = "ARM"
            else:
                sc["cycle_phase_bonus"] = 0
                sc["cycle_phase"] = cycle_phase

    except Exception as e:
        logger.warning(f"Sector bonus application failed (non-fatal): {e}")

    # Sort by score descending
    results.sort(key=lambda x: x["score"].get("total_score", 0), reverse=True)

    # ── STEP 8.5: AI analysis for top FIRE/ARM/STEALTH ──────────────────────
    # Mutates result dicts in-place; must run before save_scan so analysis
    # is persisted. Mirrors what the intraday runner does in Step 6.
    if results:
        try:
            from scanner.ai_analyst import analyze_batch
            logger.info("Running AI analysis on top FIRE/ARM/STEALTH tickers...")
            await analyze_batch(results)
        except Exception as e:
            logger.warning(f"AI analysis failed (non-fatal): {e}")

    # Tier counts
    tier_counts: dict = {}
    for r in results:
        t = r["score"]["tier"]
        tier_counts[t] = tier_counts.get(t, 0) + 1

    _update(
        phase="saving",
        results_count=len(results),
        fire_count=tier_counts.get("FIRE", 0),
        arm_count=tier_counts.get("ARM", 0),
    )

    scan_end = datetime.utcnow()
    duration_secs = (scan_end - scan_start).total_seconds()

    scan_result = {
        "results":          results,
        "scanned_at":       scan_start.isoformat(),
        "total":            len(results),
        "duration_secs":    round(duration_secs, 1),
        "tier_counts":      tier_counts,
        "sector_strength":  sector_strength,
        "sector_performance": sector_perf,
        "market_regime":    market_regime,
        "scan_type":        "massive_eod",
        "scan_date":        target_date,
        "universe_size":    len(all_bars),
        "candidates_scored": len(candidates),
        "symbol_sources":   {
            "universe":   len(all_bars),
            "filtered":   len(filtered),
            "candidates": len(candidates),
            "scored":     len(results),
        },
    }

    # ── STEP 9: Save to DB ───────────────────────────────────────────────────
    try:
        from database import save_scan
        scan_id = await save_scan(scan_result)
        logger.info(f"Universe scan saved as scan #{scan_id}")
    except Exception as e:
        logger.error(f"save_scan failed: {e}")

    # ── STEP 10: Save FIRE/ARM as scan_candidates ────────────────────────────
    try:
        from database import save_scan_candidates
        saved = await save_scan_candidates(results)
        logger.info(f"Saved {saved} FIRE/ARM candidates from universe scan")
    except Exception as e:
        logger.warning(f"save_scan_candidates failed (non-fatal): {e}")

    # ── STEP 11: Ribbon pass (EMA compression from full universe) ────────────
    try:
        from scanner.runner import run_ribbon_pass
        main_symbols = {r["symbol"] for r in results}
        ribbon_count = await run_ribbon_pass(
            all_candles=all_scored_candles,
            main_scan_symbols=main_symbols,
            spy_pct_5d=spy_pct_5d,
        )
        scan_result["ribbon_extra_count"] = ribbon_count
        logger.info(f"Ribbon pass: {ribbon_count} EMA compression candidates")
    except Exception as e:
        logger.warning(f"Ribbon pass failed (non-fatal): {e}")

    # ── STEP 12: Enrich unknown sectors via ticker details ───────────────────
    unknown_symbols = [r["symbol"] for r in results if r.get("sector") == "Unknown"]
    if unknown_symbols:
        logger.info(f"Enriching {min(len(unknown_symbols), 50)} unknown sectors via Massive")
        try:
            from database import save_sector_to_db
            for sym in unknown_symbols[:50]:
                details = await fetch_ticker_details(sym)
                if details and details.get("sector"):
                    await save_sector_to_db(
                        sym,
                        sector=details["sector"],
                        industry=details.get("industry") or "",
                        market_cap=details.get("market_cap"),
                        massive_fetched=True,
                    )
                await asyncio.sleep(0.2)
        except Exception as e:
            logger.warning(f"Unknown sector enrichment failed (non-fatal): {e}")

    finished_at = datetime.utcnow()
    _update(
        running=False, phase="done", finished_at=finished_at,
        last_scan={
            "target_date":    target_date,
            "total":          len(results),
            "fire":           tier_counts.get("FIRE", 0),
            "arm":            tier_counts.get("ARM", 0),
            "universe_size":  len(all_bars),
            "duration_secs":  round(duration_secs, 1),
            "finished_at":    finished_at.isoformat(),
        },
    )
    logger.info(
        f"=== Universe scan complete: {len(results)} results, "
        f"{tier_counts.get('FIRE', 0)} FIRE, {tier_counts.get('ARM', 0)} ARM "
        f"| {round(duration_secs, 0)}s ==="
    )

    return scan_result
