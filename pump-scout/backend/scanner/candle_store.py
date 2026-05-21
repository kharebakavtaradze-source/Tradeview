"""
Incremental candle cache for Pump Scout scanner.

fetch_incremental() replaces fetch_candles_massive() in the runner:
  - Reads cached bars from the candle_cache DB table
  - If cache is fresh (last bar == latest trading date): returns cached bars,
    merging in the grouped_daily bar if one day behind (zero extra API calls)
  - If cache is stale: fetches only the missing recent bars from Massive
  - If cache is empty (cold start / new ticker): full fetch, saves to cache
  - Detects split/adjustment via price discontinuity in the overlap window

Typical result after first full scan:
  - Cache hit:  DB read + merge of grouped_daily bar → 0 Massive API calls
  - Cache miss: 1 Massive API call → full 200-bar fetch → saved for next time
"""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_KEEP_DAYS       = 200    # bars to retain per symbol (EMA200)
_OVERLAP_DAYS    = 5      # days of overlap to fetch for split detection
_SPLIT_THRESHOLD = 0.08   # >8% price difference in overlap → adjustment happened
_FRESH_WINDOW    = 3      # days: if cache is within this window, skip full fetch


def _date_from_epoch(epoch_ms: int) -> str:
    """Convert Massive epoch ms → YYYY-MM-DD (UTC)."""
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def _normalize_grouped_bar(bar: dict) -> dict:
    """
    Convert a fetch_grouped_daily() bar (open/high/low/close/volume/date)
    to the standard candle format (o/h/l/c/v/t/date) used by the cache.
    """
    d = bar.get("date", "")
    t = bar.get("t") or (
        int(datetime.strptime(d, "%Y-%m-%d")
            .replace(tzinfo=timezone.utc).timestamp() * 1000)
        if d else 0
    )
    return {
        "o":    bar.get("open")   or bar.get("o"),
        "h":    bar.get("high")   or bar.get("h"),
        "l":    bar.get("low")    or bar.get("l"),
        "c":    bar.get("close")  or bar.get("c"),
        "v":    bar.get("volume") or bar.get("v") or 0,
        "t":    t,
        "date": d,
    }


def _annotate_dates(bars: list[dict]) -> list[dict]:
    """Add 'date' key to bars that only have epoch 't'."""
    for b in bars:
        if "date" not in b and b.get("t"):
            b["date"] = _date_from_epoch(b["t"])
    return bars


def _detect_adjustment(cached: list[dict], fresh: list[dict]) -> bool:
    """
    Return True if fresh bars show significantly different prices for dates
    already in the cache — indicating a split or corporate action adjustment.
    """
    if not cached or not fresh:
        return False
    cached_by_date = {b["date"]: b for b in cached if b.get("date")}
    for bar in fresh:
        d = bar.get("date", "")
        if d not in cached_by_date:
            continue
        c_close = (cached_by_date[d].get("c") or 0)
        f_close = (bar.get("c") or 0)
        if c_close > 0 and f_close > 0:
            if abs(f_close / c_close - 1) > _SPLIT_THRESHOLD:
                logger.debug(
                    f"Adjustment detected on {d}: cached_c={c_close:.2f} fresh_c={f_close:.2f}"
                )
                return True
    return False


async def fetch_incremental(
    symbol: str,
    target_days: int = 200,
    grouped_bar: Optional[dict] = None,
    force_refresh: bool = False,
) -> list[dict]:
    """
    Return up to `target_days` daily OHLCV bars for `symbol`.

    Parameters
    ----------
    symbol       : ticker symbol
    target_days  : how many bars to return (uses latest bars)
    grouped_bar  : if provided, the latest EOD bar from fetch_grouped_daily()
                   in {"open","high","low","close","volume","date",...} format.
                   Used to patch the cache without an extra API call.
    force_refresh: wipe cache and do a full re-fetch from Massive.
    """
    from database import get_candle_cache, save_candle_cache
    from scanner.massive_data import fetch_candles_massive

    # Determine the reference "latest trading date"
    ref_date = (
        grouped_bar.get("date", "") if grouped_bar
        else date.today().strftime("%Y-%m-%d")
    )

    # ── 1. Load cache ────────────────────────────────────────────────────────
    cached: list[dict] = []
    if not force_refresh:
        try:
            cached = await get_candle_cache(symbol)
        except Exception as e:
            logger.warning(f"[CandleStore] Cache read failed for {symbol}: {e}")

    # ── 2. Cache hit: fresh enough ───────────────────────────────────────────
    if cached:
        last_date = cached[-1]["date"]

        # Already have the latest date → fully fresh
        if last_date >= ref_date:
            return cached[-target_days:]

        # One day behind and grouped_bar available → free patch, no API call
        days_behind = (
            date.fromisoformat(ref_date) - date.fromisoformat(last_date)
        ).days
        if days_behind <= _FRESH_WINDOW and grouped_bar:
            nb = _normalize_grouped_bar(grouped_bar)
            if nb.get("date", "") > last_date:
                cached = cached + [nb]
                try:
                    await save_candle_cache(symbol, [nb])
                except Exception:
                    pass
            return cached[-target_days:]

        # Stale but has history — fetch overlap window to detect adjustments
        if days_behind <= 30:
            overlap_start = (
                date.fromisoformat(last_date) - timedelta(days=_OVERLAP_DAYS)
            ).strftime("%Y-%m-%d")
            try:
                fresh = await fetch_candles_massive(
                    symbol, days=_OVERLAP_DAYS + days_behind + 5
                )
                if fresh:
                    _annotate_dates(fresh)
                    overlap_fresh = [b for b in fresh if b.get("date", "") >= overlap_start]
                    if _detect_adjustment(cached, overlap_fresh):
                        logger.info(
                            f"[CandleStore] {symbol}: split/adjustment — forcing full re-fetch"
                        )
                        cached = []  # fall through to full fetch
                    else:
                        # Merge by date (fresh overwrites cached for same dates)
                        by_date: dict[str, dict] = {b["date"]: b for b in cached}
                        for b in fresh:
                            by_date[b["date"]] = b
                        merged = sorted(by_date.values(), key=lambda x: x["date"])
                        try:
                            await save_candle_cache(symbol, fresh)
                        except Exception:
                            pass
                        return merged[-target_days:]
            except Exception as e:
                logger.warning(f"[CandleStore] Incremental fetch failed for {symbol}: {e}")
                return cached[-target_days:]  # fall back to stale cache

    # ── 3. Cache miss / full refresh ─────────────────────────────────────────
    try:
        bars = await fetch_candles_massive(symbol, days=target_days + 60)
    except Exception as e:
        logger.warning(f"[CandleStore] Full fetch failed for {symbol}: {e}")
        return []

    if not bars:
        return []

    _annotate_dates(bars)

    try:
        await save_candle_cache(symbol, bars)
    except Exception as e:
        logger.warning(f"[CandleStore] Cache save failed for {symbol}: {e}")

    # Patch with grouped_bar if newer than what Massive returned
    if grouped_bar:
        nb = _normalize_grouped_bar(grouped_bar)
        if not bars or bars[-1].get("date", "") < nb.get("date", ""):
            bars = bars + [nb]
            try:
                await save_candle_cache(symbol, [nb])
            except Exception:
                pass

    return bars[-target_days:]
