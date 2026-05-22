"""
New Pump standalone scan runner — Massive/Polygon edition.

Universe → candles → new_pump_engine.analyze() → ranked results.

Data sources (Massive/Polygon only — no Finviz, no Yahoo):
  Universe : fetch_grouped_daily()      — single EOD call, all US stocks
  Filters  : neutral price/vol only     — no signal/tier/old-scanner bias
  Candles  : fetch_candles_massive()    — 200 daily bars per ticker
  Engine   : new_pump_engine.analyze()  — per-ticker, isolated failure handling

Scan modes
----------
full        (default) : full universe fetch + candle fetch + analyze all tickers
incremental           : fetch grouped_daily (1 API call) → only re-analyze tickers
                        with a new bar since last scan; keep prior scores for the rest
recalculate           : zero API calls — reload bars from DB cache, re-run all
                        signals on the previous scan universe (useful after formula changes)
"""
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Module-level state ─────────────────────────────────────────────────────────
_latest: dict  = {}
_running: bool = False

_np_progress: dict = {
    "running":        False,
    "phase":          "idle",   # idle|fetching_universe|filtering|fetching_candles|analyzing|enriching|enriching_context|done|error
    "started_at":     None,
    "finished_at":    None,
    "universe_size":  0,
    "fetched_count":  0,
    "analyzed_count": 0,
    "skipped_count":  0,
    "fire_count":     0,
    "strong_count":   0,
    "setup_count":    0,
    "elapsed_secs":   0,
    "last_error":     None,
    "excluded_non_common_stock_count": 0,
    "scan_mode":      "full",
}

# ── Neutral prefilters (no signal/tier bias) ───────────────────────────────────
MIN_PRICE    = 1.00
MAX_PRICE    = 500.0
MIN_VOLUME   = 50_000     # was 100K — replay: 6 strong movers blocked by vol gate
MIN_CANDLES  = 60         # bars required to run engine
CANDLES_DAYS = 200        # default lookback depth (EMA200 + all signals)
BATCH_SIZE   = 20         # concurrent Massive candle calls

# ── Two-tier bar depths for snapshot / live mode ──────────────────────────────
# FAST_SCAN_BARS: first-pass depth for all snapshot candidates
# DEEP_SCAN_BARS: re-fetch depth for shortlisted BUY / WATCH_HIGH / strong D
# MIN_LONG_CONTEXT: minimum bars required to keep a deep-pass result
FAST_SCAN_BARS  = 90
DEEP_SCAN_BARS  = 240
MIN_LONG_CONTEXT = 220


# ── Public API ─────────────────────────────────────────────────────────────────

def get_latest() -> dict:
    return _latest


def is_running() -> bool:
    return _running


def get_progress() -> dict:
    return dict(_np_progress)


async def load_latest_from_db() -> bool:
    """
    Restore the most recent demand scan from the database into _latest.
    Called at startup so results survive deploys.
    Returns True if a scan was loaded.
    """
    global _latest
    try:
        from database import get_latest_scan
        data = await get_latest_scan()
        if data and data.get("results"):
            _latest = data
            logger.info(
                f"[NpRunner] Restored scan from DB: "
                f"{len(data['results'])} results from {data.get('scanned_at', '?')}"
            )
            return True
    except Exception as exc:
        logger.warning(f"[NpRunner] DB restore failed (non-fatal): {exc}")
    return False


# ── Main runner ────────────────────────────────────────────────────────────────

async def run_new_pump_scan(
    max_tickers:  int | None = None,
    use_snapshot: bool       = False,
    scan_mode:    str        = "full",   # "full" | "incremental" | "recalculate"
) -> dict:
    """
    Standalone New Pump scan using Massive/Polygon exclusively.

    Modes
    -----
    scan_mode="full" (default):
        1. Universe via fetch_grouped_daily() — yesterday's EOD bars for all US stocks
        2. Neutral prefilters (price, volume, ticker shape)
        3. Candles via fetch_candles_massive() — CANDLES_DAYS=200 bars
        4. new_pump_engine.analyze() per ticker
        5. Sort by new_pump_score DESC

    scan_mode="incremental":
        1. Fetch grouped_daily (1 API call) to get latest bar dates
        2. Re-use previous scan universe — skip re-filtering
        3. Fetch candles ONLY for tickers with a new bar since last scan (mostly cache hits)
        4. Re-analyze only changed tickers; merge unchanged results from previous scan
        → Typical speedup: 5-10x on second scan of same day / next morning

    scan_mode="recalculate":
        1. Zero API calls — load bars for previous universe from DB cache
        2. Re-run full analysis + enrichment pipeline on all previous tickers
        → Useful after signal formula changes or scoring tuning

    use_snapshot=True (live / intraday):
        1. Universe via fetch_market_snapshot() — real-time prices for all US stocks
        2. Prefilter via shortlist_from_snapshot() — price, vol, dollar-vol, change_pct
        3. Two-tier candle fetch:
             First pass  — FAST_SCAN_BARS=90   for all snapshot candidates
             Second pass — DEEP_SCAN_BARS=240   for BUY / WATCH_HIGH / strong-D tickers
        4. new_pump_engine.analyze() — shallow pass then re-run deep pass on shortlist
        5. Sort by new_pump_score DESC

    max_tickers: operational safety cap (None = unlimited).
    Updates _latest and _np_progress; returns _latest.
    """
    global _latest, _running, _np_progress
    if _running:
        return _latest

    _running = True
    started_at = datetime.now(timezone.utc)
    _np_progress.update({
        "running": True, "phase": "fetching_universe",
        "started_at": started_at.isoformat(), "finished_at": None,
        "universe_size": 0, "fetched_count": 0, "analyzed_count": 0,
        "skipped_count": 0, "fire_count": 0, "strong_count": 0,
        "setup_count": 0, "elapsed_secs": 0, "last_error": None,
        "excluded_non_common_stock_count": 0,
        "scan_mode": scan_mode,
    })

    try:
        from scanner.massive_data import fetch_grouped_daily, fetch_candles_massive

        # ── Shared defaults (overridden below for non-full modes) ─────────────
        excluded_non_common_stock_count    = 0
        excluded_non_common_stock_examples: list[str] = []
        all_bars:             dict             = {}
        all_candles:          dict[str, list]  = {}
        candidates:           list[str]        = []
        _prev_results_by_sym: dict             = {}
        _unchanged_syms:      list[str]        = []
        _skip_fetch = False   # True → skip universe fetch + candle fetch below

        # ── RECALCULATE: zero API calls — load bars from DB cache ─────────────
        if scan_mode == "recalculate":
            prev = _latest.get("results", [])
            if prev:
                _skip_fetch = True
                _np_progress["phase"] = "loading_cache"
                candidates = [r["symbol"] for r in prev]
                if max_tickers is not None:
                    candidates = candidates[:max_tickers]
                _np_progress["universe_size"] = len(candidates)
                from database import get_candle_cache as _gcc
                async def _load_cached(sym: str) -> None:
                    try:
                        bars = await _gcc(sym)
                        if bars and len(bars) >= MIN_CANDLES:
                            all_candles[sym] = bars[-CANDLES_DAYS:]
                    except Exception:
                        pass
                for _bi in range(0, len(candidates), BATCH_SIZE * 4):
                    await asyncio.gather(*[_load_cached(s) for s in candidates[_bi:_bi + BATCH_SIZE * 4]])
                _np_progress["fetched_count"] = len(all_candles)
                logger.info(f"[NpRunner] Recalculate: loaded {len(all_candles)}/{len(candidates)} from cache")
            else:
                logger.warning("[NpRunner] recalculate: no prior results — falling back to full scan")
                scan_mode = "full"

        # ── INCREMENTAL: 1 API call — re-analyze only tickers with new bars ───
        elif scan_mode == "incremental":
            prev = _latest.get("results", [])
            if prev:
                _skip_fetch = True
                _np_progress["phase"] = "fetching_universe"
                all_bars = await fetch_grouped_daily()
                prev_scan_date = (_latest.get("scanned_at") or "")[:10]
                _prev_results_by_sym = {r["symbol"]: r for r in prev}
                candidates = list(_prev_results_by_sym.keys())
                if max_tickers is not None:
                    candidates = candidates[:max_tickers]
                # Split candidates into changed (new grouped_daily bar) vs unchanged
                _changed_syms = [
                    s for s in candidates
                    if all_bars.get(s, {}).get("date", "") > prev_scan_date
                ]
                _unchanged_syms = [s for s in candidates if s not in set(_changed_syms)]
                logger.info(
                    f"[NpRunner] Incremental: {len(_changed_syms)} changed, "
                    f"{len(_unchanged_syms)} unchanged of {len(candidates)}"
                )
                _np_progress.update({"phase": "fetching_candles", "universe_size": len(candidates)})
                from scanner.candle_store import fetch_incremental as _fi2
                async def _fetch_inc(sym: str) -> None:
                    try:
                        bars = await _fi2(sym, target_days=CANDLES_DAYS, grouped_bar=all_bars.get(sym))
                        if bars and len(bars) >= MIN_CANDLES:
                            all_candles[sym] = bars
                    except Exception as exc:
                        logger.debug(f"[NpRunner] incr candle failed {sym}: {exc}")
                for _bi in range(0, len(_changed_syms), BATCH_SIZE):
                    await asyncio.gather(*[_fetch_inc(s) for s in _changed_syms[_bi:_bi + BATCH_SIZE]])
                    await asyncio.sleep(0.5)
                _np_progress["fetched_count"] = len(all_candles)
                logger.info(f"[NpRunner] Incremental candles ready: {len(all_candles)} changed tickers")
            else:
                logger.warning("[NpRunner] incremental: no prior results — falling back to full scan")
                scan_mode = "full"

        # ── FULL SCAN: normal universe fetch + candle fetch ───────────────────
        if not _skip_fetch:
            # ── Step 1: Universe ─────────────────────────────────────────────
            if use_snapshot:
                # Live mode: real-time snapshot as universe (no grouped_daily call)
                logger.info("[NpRunner] Fetching live market snapshot universe…")
                from scanner.massive_snapshot import (
                    fetch_market_snapshot, shortlist_from_snapshot,
                )
                _snap = await fetch_market_snapshot()
                # Pre-fetch ETF exclusion set for snapshot filtering
                etf_symbols: set[str] = set()
                try:
                    from scanner.massive_data import get_us_etf_symbols
                    etf_symbols = await get_us_etf_symbols()
                except Exception as _exc:
                    logger.warning(f"[NpRunner] ETF exclusion fetch failed (non-fatal): {_exc}")

                _shortlist = shortlist_from_snapshot(_snap, etf_exclusions=etf_symbols)
                # Apply UniverseCache positive filter to snapshot candidates (in-memory, no API call)
                from scanner.massive_reference import get_cached_ticker as _get_cached_ticker
                from scanner.stock_universe_filter import is_common_stock as _is_common_stock
                _filtered: list = []
                for _c in _shortlist:
                    _sym = _c["symbol"]
                    _meta = _get_cached_ticker(_sym)
                    if _meta is not None and not _is_common_stock(_meta):
                        excluded_non_common_stock_count += 1
                        if len(excluded_non_common_stock_examples) < 20:
                            excluded_non_common_stock_examples.append(_sym)
                    else:
                        _filtered.append(_c)
                candidates = [c["symbol"] for c in _filtered]
                logger.info(f"[NpRunner] Snapshot universe: {len(_snap)} → {len(candidates)} after prefilter")
            else:
                # EOD mode: yesterday's grouped daily bars as universe
                logger.info("[NpRunner] Fetching grouped daily universe from Massive…")
                all_bars = await fetch_grouped_daily()

                # ── Step 2: Neutral prefilters (incl. ETF/fund exclusion) ─────
                _np_progress["phase"] = "filtering"

                etf_symbols = set()
                try:
                    from scanner.massive_data import get_us_etf_symbols
                    etf_symbols = await get_us_etf_symbols()
                    logger.info(f"[NpRunner] ETF exclusion set loaded: {len(etf_symbols)} symbols")
                except Exception as _exc:
                    logger.warning(f"[NpRunner] ETF exclusion fetch failed (non-fatal): {_exc}")

                from scanner.massive_reference import get_cached_ticker as _get_cached_ticker
                from scanner.stock_universe_filter import is_common_stock as _is_common_stock

                candidates = []
                total_symbols_before_filter = 0
                for sym, bar in all_bars.items():
                    total_symbols_before_filter += 1
                    if not sym.isalpha() or len(sym) > 5:
                        continue
                    # Tier 1: UniverseCache positive filter — authoritative, no API call
                    _meta = _get_cached_ticker(sym)
                    if _meta is not None:
                        if not _is_common_stock(_meta):
                            excluded_non_common_stock_count += 1
                            if len(excluded_non_common_stock_examples) < 20:
                                excluded_non_common_stock_examples.append(sym)
                            continue
                    elif sym.upper() in etf_symbols:
                        # Tier 2: cache miss — fall back to bulk ETF exclusion set
                        excluded_non_common_stock_count += 1
                        if len(excluded_non_common_stock_examples) < 20:
                            excluded_non_common_stock_examples.append(sym)
                        continue
                    price  = bar.get("close") or bar.get("c") or 0
                    volume = bar.get("volume") or bar.get("v") or 0
                    if not (MIN_PRICE <= price <= MAX_PRICE):
                        continue
                    if volume < MIN_VOLUME:
                        continue
                    candidates.append(sym)

                logger.info(
                    f"[NpRunner] Filter summary: total={total_symbols_before_filter} "
                    f"excluded_non_cs={excluded_non_common_stock_count} "
                    f"examples={excluded_non_common_stock_examples[:5]} "
                    f"candidates={len(candidates)}"
                )

            _np_progress["phase"] = "filtering"

            # Optional hard cap — only for operational override, not normal use
            if max_tickers is not None:
                candidates = candidates[:max_tickers]
            _np_progress["universe_size"] = len(candidates)
            _np_progress["excluded_non_common_stock_count"] = excluded_non_common_stock_count
            logger.info(f"[NpRunner] Universe after neutral prefilters: {len(candidates)} tickers")

            # ── Step 3: Fetch candles (batched) ───────────────────────────────
            _np_progress["phase"] = "fetching_candles"

            # Snapshot mode uses FAST_SCAN_BARS for first pass; EOD uses full depth.
            first_pass_days = FAST_SCAN_BARS if use_snapshot else CANDLES_DAYS

            from scanner.candle_store import fetch_incremental as _fetch_incremental

            # In EOD mode, all_bars has the latest grouped_daily bar for each ticker —
            # pass it to fetch_incremental so cached tickers need zero extra API calls.
            _grouped = all_bars if not use_snapshot else {}

            async def _fetch_one(sym: str, days: int = first_pass_days) -> None:
                try:
                    bars = await _fetch_incremental(
                        sym,
                        target_days=days,
                        grouped_bar=_grouped.get(sym),
                    )
                    if bars and len(bars) >= MIN_CANDLES:
                        all_candles[sym] = bars
                except Exception as exc:
                    logger.debug(f"[NpRunner] candle fetch failed {sym}: {exc}")

            for i in range(0, len(candidates), BATCH_SIZE):
                await asyncio.gather(*[_fetch_one(s) for s in candidates[i:i + BATCH_SIZE]])
                await asyncio.sleep(0.5)

            _np_progress["fetched_count"] = len(all_candles)
            logger.info(f"[NpRunner] Candles fetched: {len(all_candles)}/{len(candidates)}")

        # ── Step 4: Analyze ───────────────────────────────────────────────────
        _np_progress["phase"] = "analyzing"
        from scanner.new_pump_engine import analyze as np_analyze

        results = []
        skipped = 0
        for sym, candles in all_candles.items():
            try:
                bars = [
                    {"open": c["o"], "high": c["h"], "low": c["l"],
                     "close": c["c"], "volume": c["v"]}
                    for c in candles
                ]

                # Compute D + WLNBB confluence first — feeds combo boost into analyze()
                _dw: dict = {}
                try:
                    from scanner.manual_d_wlnbb_features import compute_d_wlnbb_confluence
                    _dw = compute_d_wlnbb_confluence(bars)
                except Exception as _exc:
                    logger.debug(f"[NpRunner] d_wlnbb skipped {sym}: {_exc}")

                np = np_analyze(
                    bars,
                    d_combo_type=_dw.get("d_confluence_type_v2") or "NONE",
                    has_triple_d_l34_beup=bool(_dw.get("has_triple_d_l34_beup")),
                )
            except Exception as exc:
                logger.debug(f"[NpRunner] analyze failed {sym}: {exc}")
                skipped += 1
                continue

            last     = candles[-1]
            last_idx = len(candles) - 1
            vol_slice = [c["v"] for c in candles[-20:] if c.get("v")]
            avg_vol   = sum(vol_slice) / len(vol_slice) if vol_slice else 0

            # ── Signal bar index (for signal_date + next_day) ─────────────
            _ag4  = np.get("age_g4")
            _al34 = np.get("age_l34")
            _afr  = np.get("age_fri34")
            _ab2  = np.get("age_b2")
            if _ag4 is not None:
                sig_idx = last_idx - _ag4
            elif _afr is not None or _al34 is not None:
                _ages = [a for a in [_afr, _al34] if a is not None]
                sig_idx = last_idx - min(_ages)
            elif _ab2 is not None:
                sig_idx = last_idx - _ab2
            else:
                sig_idx = last_idx
            sig_idx = max(0, min(sig_idx, last_idx))

            # signal_date — UTC date of the signal bar
            signal_date = None
            _t = candles[sig_idx].get("t")
            if _t:
                signal_date = datetime.fromtimestamp(_t / 1000, tz=timezone.utc).strftime("%Y-%m-%d")

            # next_day — OHLC + return for the bar immediately after signal
            next_day = None
            if sig_idx + 1 <= last_idx:
                _nd  = candles[sig_idx + 1]
                _sc  = candles[sig_idx].get("c") or 0
                _ndo = _nd.get("o")
                _ndc = _nd.get("c")
                _ndh = _nd.get("h")
                _ndl = _nd.get("l")
                _ndt = _nd.get("t")
                _ret = round((_ndc - _sc) / _sc * 100, 2) if _ndc and _sc else None
                _gap = round((_ndo - _sc) / _sc * 100, 2) if _ndo and _sc else None
                next_day = {
                    "date":       datetime.fromtimestamp(_ndt / 1000, tz=timezone.utc).strftime("%Y-%m-%d") if _ndt else None,
                    "open":       _ndo,
                    "high":       _ndh,
                    "low":        _ndl,
                    "close":      _ndc,
                    "return_pct": _ret,
                    "gap_pct":    _gap,
                    "is_winner":  _ret is not None and _ret > 0,
                }

            lbl = np.get("new_pump_label") or "NEW_PUMP_NONE"
            if lbl == "NEW_PUMP_FIRE":     _np_progress["fire_count"]   += 1
            elif lbl == "NEW_PUMP_STRONG": _np_progress["strong_count"] += 1
            elif lbl == "NEW_PUMP_SETUP":  _np_progress["setup_count"]  += 1

            results.append({
                "symbol":                  sym,
                "price":                   last.get("c"),
                "volume_today":            last.get("v"),
                "avg_volume_20d":          round(avg_vol),
                "new_pump_score":          np.get("new_pump_score"),
                "new_pump_label":          lbl,
                "new_pump_sequence_label": np.get("new_pump_sequence_label"),
                "new_pump_setup_score":    np.get("new_pump_setup_score"),
                "new_pump_trigger_score":  np.get("new_pump_trigger_score"),
                "new_pump_confirm_score":  np.get("new_pump_confirm_score"),
                "new_pump_modifier_score": np.get("new_pump_modifier_score"),
                "has_l34":   np.get("has_l34"),
                "has_fri34": np.get("has_fri34"),
                "has_g4":    np.get("has_g4"),
                "has_b2":    np.get("has_b2"),
                "age_l34":    np.get("age_l34"),
                "age_fri34":  np.get("age_fri34"),
                "age_g4":     np.get("age_g4"),
                "age_b2":     np.get("age_b2"),
                "state":          np.get("state"),
                "engine_path":    np.get("engine_path"),
                "missing_piece":  np.get("missing_piece"),
                "main_risk":      np.get("main_risk"),
                "impulse_score":  np.get("impulse_score"),
                "impulse_label":  np.get("impulse_label"),
                "base_quality_score":  np.get("base_quality_score"),
                "sustain_proxy_score": np.get("sustain_proxy_score"),
                "sustain_profile":     np.get("sustain_profile"),
                "fake_trigger_risk":   np.get("fake_trigger_risk"),
                "compression_expansion_state": np.get("compression_expansion_state"),
                "compression_expansion_score": np.get("compression_expansion_score"),
                "compression_expansion_label": np.get("compression_expansion_label"),
                "expansion_timing_risk":       np.get("expansion_timing_risk"),
                "decision":                    np.get("decision"),
                "decision_reason":             np.get("decision_reason"),
                "decision_flags":              np.get("decision_flags"),
                "decision_authority":          np.get("decision_authority"),
                "legacy_label_role":           np.get("legacy_label_role"),
                "structure_phase":             np.get("structure_phase"),
                "structure_score":             np.get("structure_score"),
                "structure_advisory":          np.get("structure_advisory"),
                "signal_date": signal_date,
                "next_day":    next_day,
                # ── Research: Manual D + WLNBB confluence (all fields via _dw) ─
                **_dw,
            })
            _np_progress["analyzed_count"] = len(results)

        _np_progress["skipped_count"] = skipped

        # ── Incremental: merge unchanged results from previous scan ───────────
        if scan_mode == "incremental" and _prev_results_by_sym and _unchanged_syms:
            unchanged_results = [_prev_results_by_sym[s] for s in _unchanged_syms if s in _prev_results_by_sym]
            results = results + unchanged_results
            logger.info(f"[NpRunner] Incremental merge: {len(results) - len(unchanged_results)} re-analyzed + {len(unchanged_results)} carried over")

        # ── Step 4b: Deep-bar pass (snapshot mode only) ───────────────────────
        # Re-fetch DEEP_SCAN_BARS=240 for BUY / strong-D candidates and re-analyze.
        # Replaces the shallow result in-place when deep bars are long enough.
        if use_snapshot and results:
            _DEEP_LABELS = {"NEW_PUMP_FIRE", "NEW_PUMP_STRONG"}
            deep_syms = [
                r["symbol"] for r in results
                if (r.get("new_pump_label") in _DEEP_LABELS)
                or (r.get("has_g4") and (r.get("has_l34") or r.get("has_fri34")))
            ]
            if deep_syms:
                logger.info(f"[NpRunner] Deep-bar pass: {len(deep_syms)} candidates @ {DEEP_SCAN_BARS} bars")
                deep_candles: dict[str, list] = {}

                async def _fetch_deep(sym: str) -> None:
                    try:
                        bars = await _fetch_incremental(
                            sym,
                            target_days=DEEP_SCAN_BARS,
                            grouped_bar=_grouped.get(sym),
                        )
                        if bars and len(bars) >= MIN_LONG_CONTEXT:
                            deep_candles[sym] = bars
                    except Exception as _exc:
                        logger.debug(f"[NpRunner] deep fetch failed {sym}: {_exc}")

                for i in range(0, len(deep_syms), BATCH_SIZE):
                    await asyncio.gather(*[_fetch_deep(s) for s in deep_syms[i:i + BATCH_SIZE]])
                    await asyncio.sleep(0.5)

                # Re-analyze and replace shallow results
                _result_idx = {r["symbol"]: idx for idx, r in enumerate(results)}
                for sym, deep_bars_raw in deep_candles.items():
                    try:
                        deep_bars = [
                            {"open": c["o"], "high": c["h"], "low": c["l"],
                             "close": c["c"], "volume": c["v"]}
                            for c in deep_bars_raw
                        ]
                        _dw2: dict = {}
                        try:
                            from scanner.manual_d_wlnbb_features import compute_d_wlnbb_confluence
                            _dw2 = compute_d_wlnbb_confluence(deep_bars)
                        except Exception:
                            pass
                        np2 = np_analyze(
                            deep_bars,
                            d_combo_type=_dw2.get("d_confluence_type_v2") or "NONE",
                            has_triple_d_l34_beup=bool(_dw2.get("has_triple_d_l34_beup")),
                        )
                        idx = _result_idx.get(sym)
                        if idx is not None:
                            r = results[idx]
                            # Overwrite NP engine fields with deep-bar values
                            for _k in (
                                "new_pump_score", "new_pump_label", "new_pump_sequence_label",
                                "new_pump_setup_score", "new_pump_trigger_score",
                                "new_pump_confirm_score", "new_pump_modifier_score",
                                "has_l34", "has_fri34", "has_g4", "has_b2",
                                "age_l34", "age_fri34", "age_g4", "age_b2",
                                "state", "engine_path", "missing_piece", "main_risk",
                                "impulse_score", "impulse_label",
                                "base_quality_score", "sustain_proxy_score", "sustain_profile",
                                "fake_trigger_risk",
                                "compression_expansion_state", "compression_expansion_score",
                                "compression_expansion_label", "expansion_timing_risk",
                                "decision", "decision_reason", "decision_flags",
                                "decision_authority", "legacy_label_role",
                                "structure_phase", "structure_score", "structure_advisory",
                            ):
                                r[_k] = np2.get(_k, r.get(_k))
                            r.update(_dw2)
                            lbl2 = r["new_pump_label"] or "NEW_PUMP_NONE"
                            r["new_pump_label"] = lbl2
                    except Exception as _exc:
                        logger.debug(f"[NpRunner] deep re-analyze failed {sym}: {_exc}")

                logger.info(f"[NpRunner] Deep pass complete: {len(deep_candles)}/{len(deep_syms)} upgraded")

        # ── Step 5: Sort ─────────────────────────────────────────────────────
        _LABEL_ORDER = {
            "NEW_PUMP_FIRE": 0, "NEW_PUMP_STRONG": 1, "NEW_PUMP_SETUP": 2,
            "NEW_PUMP_TRIGGER_ONLY": 3, "NEW_PUMP_WEAK": 4, "NEW_PUMP_NONE": 5,
        }
        results.sort(key=lambda r: (
            _LABEL_ORDER.get(r["new_pump_label"] or "", 9),
            -(r["new_pump_score"] or 0),
        ))

        elapsed = round((datetime.now(timezone.utc) - started_at).total_seconds(), 1)
        logger.info(
            f"[NpRunner] Done: analyzed={len(results)}, skipped={skipped}, "
            f"FIRE={_np_progress['fire_count']}, STRONG={_np_progress['strong_count']}, "
            f"SETUP={_np_progress['setup_count']}, {elapsed}s"
        )

        # ── Step 6: Sector enrichment (single batch DB query) ─────────────────
        _np_progress["phase"] = "enriching"
        try:
            from database import get_session_factory
            from database import SectorCache
            from sqlalchemy import select as _sa_select
            syms = [r["symbol"] for r in results]
            async with get_session_factory()() as _sess:
                _rows = await _sess.execute(
                    _sa_select(SectorCache).where(SectorCache.symbol.in_(syms))
                )
                _sec_map = {row.symbol: {"sector": row.sector, "industry": row.industry}
                            for row in _rows.scalars()}
            for r in results:
                sc = _sec_map.get(r["symbol"])
                r["sector"]   = sc["sector"]   if sc else None
                r["industry"] = sc["industry"] if sc else None
            logger.info(f"[NpRunner] Sector enriched: {len(_sec_map)}/{len(results)}")
        except Exception as exc:
            logger.warning(f"[NpRunner] sector enrichment skipped: {exc}")
            for r in results:
                r.setdefault("sector", None)
                r.setdefault("industry", None)

        # ── Step 7: Context enrichment (sector/macro/news/sympathy) ──────────────
        _np_progress["phase"] = "enriching_context"
        try:
            from scanner.np_context_enricher import enrich_np_candidates
            results = await enrich_np_candidates(results)
            logger.info("[NpRunner] Context enrichment complete")
        except Exception as _ctx_exc:
            logger.warning(f"[NpRunner] Context enrichment failed (non-fatal): {_ctx_exc}")

        # ── Step 8: Demand Composite scoring (ATS + signal fusion) ───────────
        _np_progress["phase"] = "demand_composite"
        try:
            from scanner.demand_composite_scanner import apply_demand_composite
            # Merge shallow + deep candles so ATS has best available bars
            merged_candles = {**all_candles}
            if use_snapshot:
                merged_candles.update(deep_candles if "deep_candles" in dir() else {})
            results = apply_demand_composite(results, merged_candles)
            prime   = sum(1 for r in results if r.get("demand_composite_tier") == "PRIME_BUY")
            high    = sum(1 for r in results if r.get("demand_composite_tier") == "HIGH_CONF_BUY")
            logger.info(f"[NpRunner] Demand composite: PRIME={prime}, HIGH_CONF={high}")
        except Exception as _dc_exc:
            logger.warning(f"[NpRunner] Demand composite failed (non-fatal): {_dc_exc}")

        _prime_count = sum(1 for r in results if r.get("demand_composite_tier") == "PRIME_BUY")
        _high_count  = sum(1 for r in results if r.get("demand_composite_tier") == "HIGH_CONF_BUY")
        _watch_count = sum(1 for r in results if r.get("demand_composite_tier") == "BUY_WATCH")
        _ats_prime   = sum(1 for r in results if r.get("ats_signal") == "ATS_PRIME")

        _latest = {
            "results":        results,
            "total":          len(results),
            "universe":       len(candidates),
            "fetched":        len(all_candles),
            "analyzed_count": len(results),
            "skipped_count":  skipped,
            "fire_count":     _np_progress["fire_count"],
            "strong_count":   _np_progress["strong_count"],
            "setup_count":    _np_progress["setup_count"],
            "demand_prime_count":    _prime_count,
            "demand_high_count":     _high_count,
            "demand_watch_count":    _watch_count,
            "ats_prime_count":       _ats_prime,
            "excluded_non_common_stock_count": excluded_non_common_stock_count,
            "excluded_non_common_stock_examples": excluded_non_common_stock_examples[:20],
            "scanned_at":     started_at.isoformat(),
            "elapsed_secs":   elapsed,
            "scan_mode":      scan_mode,
        }
        _np_progress.update({
            "phase":        "done",
            "elapsed_secs": elapsed,
            "finished_at":  datetime.now(timezone.utc).isoformat(),
        })

        # ── Step 9: Persist to DB so results survive deploys ─────────────────
        try:
            from database import save_scan as _save_scan
            await _save_scan(_latest)
        except Exception as _sv_exc:
            logger.warning(f"[NpRunner] scan DB save failed (non-fatal): {_sv_exc}")

        # ── Step 10: Record signal outcomes for AI pattern learning ───────────
        try:
            from ai_journal import record_scan_signals
            asyncio.create_task(record_scan_signals(results))
        except Exception as _so_exc:
            logger.debug(f"[NpRunner] signal outcome recording skipped: {_so_exc}")

        return _latest

    except Exception as exc:
        logger.error(f"[NpRunner] scan failed: {exc}", exc_info=True)
        _np_progress.update({"phase": "error", "last_error": str(exc)})
        return _latest
    finally:
        _running = False
        _np_progress["running"] = False
