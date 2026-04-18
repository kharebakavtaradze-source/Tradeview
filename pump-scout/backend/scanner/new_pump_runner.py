"""
New Pump standalone scan runner.

Completely independent of the old scanner pipeline.
Universe → candles → new_pump_engine.analyze() → ranked results.

Universe filters (intentionally neutral — no old-scanner bias):
- US common equities on major exchanges
- Price $1.00 – $500
- Avg daily volume ≥ 100K shares (liquidity floor)
- At least 30 candles of history
"""
import asyncio
import logging
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Module-level in-memory cache (one result set, like _scan_running in main.py) ──
_latest: dict = {}
_running: bool = False

# Finviz filter strings — broad, exchange-agnostic, no signal/momentum bias
_FILTER_LARGE  = "v=111&f=geo_usa,sh_avgvol_o200,sh_price_o1,sh_price_u500&ft=4"
_FILTER_MID    = "v=111&f=geo_usa,sh_avgvol_o100,sh_price_o1,sh_price_u100&ft=4"

MIN_CANDLES = 30   # require at least this many bars of history
MIN_VOL     = 100_000  # minimum average daily volume (shares)


def get_latest() -> dict:
    return _latest


def is_running() -> bool:
    return _running


async def run_new_pump_scan(max_tickers: int = 1500) -> dict:
    """
    Full standalone New Pump scan.
    1. Build neutral universe via Finviz (broad, no old-scanner signals).
    2. Fetch candles for each ticker via Yahoo.
    3. Run new_pump_engine.analyze() on each.
    4. Sort by new_pump_score descending.
    Returns result dict and updates module-level _latest cache.
    """
    global _latest, _running
    if _running:
        return _latest

    _running = True
    started_at = datetime.now(timezone.utc)

    try:
        # ── Step 1: Universe ──────────────────────────────────────────────────
        tickers = await _build_universe(max_tickers)
        logger.info(f"[NewPumpRunner] Universe: {len(tickers)} tickers")

        # ── Step 2: Candles ───────────────────────────────────────────────────
        from scanner.yahoo import fetch_batch
        all_candles = await fetch_batch(tickers, interval="1d")
        logger.info(f"[NewPumpRunner] Candles fetched: {len(all_candles)}/{len(tickers)}")

        # ── Step 3: Analyze ───────────────────────────────────────────────────
        from scanner.new_pump_engine import analyze as np_analyze
        results = []
        for sym, candles in all_candles.items():
            if len(candles) < MIN_CANDLES:
                continue
            last = candles[-1]
            vol_recent = [c["v"] for c in candles[-20:] if c.get("v")]
            avg_vol = sum(vol_recent) / len(vol_recent) if vol_recent else 0
            if avg_vol < MIN_VOL:
                continue

            bars = [{"open": c["o"], "high": c["h"], "low": c["l"],
                     "close": c["c"], "volume": c["v"]} for c in candles]
            try:
                np = np_analyze(bars)
            except Exception:
                continue

            results.append({
                "symbol":                  sym,
                "price":                   last.get("c"),
                "volume_today":            last.get("v"),
                "avg_volume_20d":          round(avg_vol),
                "new_pump_score":          np.get("new_pump_score"),
                "new_pump_label":          np.get("new_pump_label"),
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

        # ── Step 4: Sort ──────────────────────────────────────────────────────
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
            f"[NewPumpRunner] Done: {len(results)} scored, "
            f"{len(all_candles)} fetched, {elapsed}s"
        )

        _latest = {
            "results":     results,
            "total":       len(results),
            "universe":    len(tickers),
            "fetched":     len(all_candles),
            "scanned_at":  started_at.isoformat(),
            "elapsed_secs": elapsed,
        }
        return _latest

    except Exception as e:
        logger.error(f"[NewPumpRunner] scan failed: {e}", exc_info=True)
        return _latest
    finally:
        _running = False


async def _build_universe(max_tickers: int) -> list[str]:
    """
    Build a neutral ticker universe using Finviz broad filters only.
    No momentum, no signal, no old-scanner bias.
    Falls back to get_tickers() if Finviz is blocked.
    """
    import httpx
    from scanner.finviz import HEADERS, FINVIZ_BASE, _fetch_finviz_filter

    seen: set[str] = set()
    tickers: list[str] = []

    filters = [
        ("large_mid", _FILTER_LARGE, min(max_tickers, 1000)),
        ("mid_small", _FILTER_MID,   min(max_tickers - len(tickers), 500)),
    ]

    try:
        async with httpx.AsyncClient(
            headers=HEADERS, timeout=25.0, follow_redirects=True
        ) as client:
            for label, fparams, limit in filters:
                if len(tickers) >= max_tickers:
                    break
                batch = await _fetch_finviz_filter(client, fparams, limit)
                added = 0
                for t in batch:
                    if t not in seen:
                        seen.add(t)
                        tickers.append(t)
                        added += 1
                logger.info(f"[NewPumpRunner] Finviz {label}: +{added} → {len(tickers)} total")
                if batch:
                    await asyncio.sleep(1.5)
    except Exception as e:
        logger.warning(f"[NewPumpRunner] Finviz universe failed: {e}")

    if len(tickers) < 50:
        # Fallback: use existing get_tickers (better than nothing)
        logger.warning("[NewPumpRunner] Finviz too small, falling back to get_tickers()")
        from scanner.finviz import get_tickers
        fallback = await get_tickers()
        for t in fallback:
            if t not in seen:
                seen.add(t)
                tickers.append(t)

    return tickers[:max_tickers]
