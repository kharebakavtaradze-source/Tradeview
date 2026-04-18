"""
New Pump standalone scan runner — Massive/Polygon edition.

Universe → candles → new_pump_engine.analyze() → ranked results.

Data sources (Massive/Polygon only — no Finviz, no Yahoo):
  Universe : fetch_grouped_daily()      — single EOD call, all US stocks
  Filters  : neutral price/vol only     — no signal/tier/old-scanner bias
  Candles  : fetch_candles_massive()    — 200 daily bars per ticker
  Engine   : new_pump_engine.analyze()  — per-ticker, isolated failure handling
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
    "phase":          "idle",   # idle|fetching_universe|filtering|fetching_candles|analyzing|done|error
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
}

# ── Neutral prefilters (no signal/tier bias) ───────────────────────────────────
MIN_PRICE    = 1.00
MAX_PRICE    = 500.0
MIN_VOLUME   = 100_000    # shares on universe date
MIN_CANDLES  = 60         # bars required to run engine
CANDLES_DAYS = 200        # lookback depth (EMA200 + RSI + z-score + all signals)
BATCH_SIZE   = 20         # concurrent Massive candle calls


# ── Public API ─────────────────────────────────────────────────────────────────

def get_latest() -> dict:
    return _latest


def is_running() -> bool:
    return _running


def get_progress() -> dict:
    return dict(_np_progress)


# ── Main runner ────────────────────────────────────────────────────────────────

async def run_new_pump_scan(max_tickers: int = 2000) -> dict:
    """
    Standalone New Pump scan using Massive/Polygon exclusively.
    1. Universe via fetch_grouped_daily()
    2. Neutral prefilters (price, volume, ticker shape)
    3. Candles via fetch_candles_massive() (200 bars, 20 concurrent)
    4. new_pump_engine.analyze() per ticker — per-symbol failures are skipped
    5. Sort by label tier -> score descending
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
    })

    try:
        from scanner.massive_data import fetch_grouped_daily, fetch_candles_massive

        # ── Step 1: Universe ─────────────────────────────────────────────────
        logger.info("[NpRunner] Fetching grouped daily universe from Massive…")
        all_bars = await fetch_grouped_daily()

        # ── Step 2: Neutral prefilters ────────────────────────────────────────
        _np_progress["phase"] = "filtering"
        candidates = []
        for sym, bar in all_bars.items():
            if not sym.isalpha() or len(sym) > 5:
                continue
            price  = bar.get("close") or bar.get("c") or 0
            volume = bar.get("volume") or bar.get("v") or 0
            if not (MIN_PRICE <= price <= MAX_PRICE):
                continue
            if volume < MIN_VOLUME:
                continue
            candidates.append(sym)

        # Rank by dollar-volume descending, cap universe
        candidates.sort(
            key=lambda s: (
                (all_bars[s].get("close") or all_bars[s].get("c") or 0) *
                (all_bars[s].get("volume") or all_bars[s].get("v") or 0)
            ),
            reverse=True,
        )
        candidates = candidates[:max_tickers]
        _np_progress["universe_size"] = len(candidates)
        logger.info(f"[NpRunner] Universe after neutral prefilters: {len(candidates)} tickers")

        # ── Step 3: Fetch candles (batched) ───────────────────────────────────
        _np_progress["phase"] = "fetching_candles"
        all_candles: dict[str, list] = {}

        async def _fetch_one(sym: str) -> None:
            try:
                bars = await fetch_candles_massive(sym, days=CANDLES_DAYS)
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
                np = np_analyze(bars)
            except Exception as exc:
                logger.debug(f"[NpRunner] analyze failed {sym}: {exc}")
                skipped += 1
                continue

            last = candles[-1]
            vol_slice = [c["v"] for c in candles[-20:] if c.get("v")]
            avg_vol   = sum(vol_slice) / len(vol_slice) if vol_slice else 0

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
                "age_l34":   np.get("age_l34"),
                "age_fri34": np.get("age_fri34"),
                "age_g4":    np.get("age_g4"),
                "age_b2":    np.get("age_b2"),
            })
            _np_progress["analyzed_count"] = len(results)

        _np_progress["skipped_count"] = skipped

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
            "scanned_at":     started_at.isoformat(),
            "elapsed_secs":   elapsed,
        }
        _np_progress.update({
            "phase":        "done",
            "elapsed_secs": elapsed,
            "finished_at":  datetime.now(timezone.utc).isoformat(),
        })
        return _latest

    except Exception as exc:
        logger.error(f"[NpRunner] scan failed: {exc}", exc_info=True)
        _np_progress.update({"phase": "error", "last_error": str(exc)})
        return _latest
    finally:
        _running = False
        _np_progress["running"] = False
