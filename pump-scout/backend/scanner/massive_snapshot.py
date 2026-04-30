"""
Massive Market Snapshot — fast live scan first pass.
=====================================================
Endpoint: GET /v2/snapshot/locale/us/markets/stocks/tickers

Returns real-time intraday data for all US stocks in a single API call.
Used as the universe first-pass for live scans.

Advantages over grouped_daily for live use:
  - Real-time price / volume (not yesterday's EOD)
  - todaysChangePerc for momentum filtering
  - Minute-bar data for intraday context
  - No "0 rows = holiday" ambiguity during market hours

Replay continues to use grouped_daily (historical data, not available here).

Outputs
-------
fetch_market_snapshot()          → raw dict keyed by symbol
shortlist_from_snapshot(...)     → filtered + sorted list of candidate dicts
get_snapshot_candidate(sym, ...) → single ticker snapshot for live enrichment
"""
from __future__ import annotations

import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

MASSIVE_API_KEY = os.getenv("MASSIVE_API_KEY", "")
MASSIVE_BASE    = "https://api.massive.com"
_TIMEOUT        = httpx.Timeout(45.0, connect=15.0)   # full-market snapshot is large


def _params(**extra) -> dict:
    return {"apiKey": MASSIVE_API_KEY, **extra}


# ── Snapshot prefilter constants ──────────────────────────────────────────────

# Price band — same as replay / live scan
SNAP_MIN_PRICE    = 1.50
SNAP_MAX_PRICE    = 500.0

# Volume floor — day volume must exceed this for a meaningful signal
SNAP_MIN_DAY_VOL  = 50_000

# Dollar-volume proxy floor — close × day_volume (rough liquidity gate)
SNAP_MIN_DOLLAR_VOL = 150_000    # $150K — avoids sub-penny shell activity

# Momentum minimum — todaysChangePerc must be above this for first-pass
# Set to 0.0 to include all; raise to e.g. 2.0 for momentum-only passes.
SNAP_MIN_CHANGE_PCT = 0.0

# Maximum candidates returned from shortlist_from_snapshot
SNAP_MAX_CANDIDATES = 2000


async def fetch_market_snapshot() -> dict[str, dict]:
    """
    Fetch real-time snapshot for all US stocks.

    Returns
    -------
    {SYMBOL: {
        price         : float  (day.c or lastTrade.p)
        day_open      : float
        day_high      : float
        day_low       : float
        day_close     : float  (latest trade price)
        day_volume    : int
        day_vwap      : float
        prev_close    : float
        prev_volume   : int
        change_pct    : float  (todaysChangePerc)
        change_abs    : float  (todaysChange)
        dollar_volume : float  (day_vwap × day_volume proxy)
        updated_ms    : int    (epoch ms)
    }}
    Returns {} on any failure.
    """
    if not MASSIVE_API_KEY:
        logger.error("[Snapshot] MASSIVE_API_KEY not set")
        return {}

    url = f"{MASSIVE_BASE}/v2/snapshot/locale/us/markets/stocks/tickers"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, params=_params(include_otc="false"))

        if resp.status_code != 200:
            logger.warning(f"[Snapshot] HTTP {resp.status_code}: {resp.text[:200]}")
            return {}

        data    = resp.json()
        status  = data.get("status", "")
        if status not in ("OK", "DELAYED"):
            logger.warning(f"[Snapshot] status={status!r}")

        out: dict[str, dict] = {}
        for t in data.get("tickers") or []:
            sym = (t.get("ticker") or "").upper()
            if not sym or not sym.isalpha() or len(sym) > 5:
                continue

            day      = t.get("day")      or {}
            prev_day = t.get("prevDay")  or {}
            last_t   = t.get("lastTrade") or {}

            # Prefer day.c for the latest price; fall back to lastTrade
            day_c = day.get("c") or last_t.get("p") or 0.0
            day_v = int(day.get("v") or 0)
            vwap  = day.get("vw") or day_c

            out[sym] = {
                "price":         float(day_c),
                "day_open":      day.get("o"),
                "day_high":      day.get("h"),
                "day_low":       day.get("l"),
                "day_close":     float(day_c),
                "day_volume":    day_v,
                "day_vwap":      float(vwap),
                "prev_close":    prev_day.get("c"),
                "prev_volume":   int(prev_day.get("v") or 0),
                "change_pct":    float(t.get("todaysChangePerc") or 0.0),
                "change_abs":    float(t.get("todaysChange")     or 0.0),
                "dollar_volume": float(vwap) * day_v,
                "updated_ms":    t.get("updated"),
            }

        logger.info(f"[Snapshot] {len(out)} tickers fetched")
        return out

    except Exception as exc:
        logger.warning(f"[Snapshot] fetch_market_snapshot failed: {exc}")
        return {}


def shortlist_from_snapshot(
    snapshot:         dict[str, dict],
    min_price:        float = SNAP_MIN_PRICE,
    max_price:        float = SNAP_MAX_PRICE,
    min_day_vol:      int   = SNAP_MIN_DAY_VOL,
    min_dollar_vol:   float = SNAP_MIN_DOLLAR_VOL,
    min_change_pct:   float = SNAP_MIN_CHANGE_PCT,
    etf_exclusions:   Optional[set[str]] = None,
    max_candidates:   int   = SNAP_MAX_CANDIDATES,
) -> list[dict]:
    """
    Apply prefilters to a raw snapshot dict and return sorted candidate list.

    Sorting: dollar_volume × (1 + abs(change_pct)/10) DESC — combines
    liquidity and momentum into a single priority proxy.

    Returns list of {symbol, price, day_volume, day_vwap, change_pct,
                     prev_close, dollar_volume, updated_ms}.
    """
    excluded = etf_exclusions or set()
    candidates: list[dict] = []

    for sym, s in snapshot.items():
        if sym in excluded:
            continue
        price   = s["price"]
        day_vol = s["day_volume"]
        dv      = s["dollar_volume"]
        chg     = s["change_pct"]

        if not (min_price <= price <= max_price):
            continue
        if day_vol < min_day_vol:
            continue
        if dv < min_dollar_vol:
            continue
        if chg < min_change_pct:
            continue

        candidates.append({
            "symbol":       sym,
            "price":        price,
            "day_volume":   day_vol,
            "day_vwap":     s["day_vwap"],
            "day_open":     s["day_open"],
            "day_high":     s["day_high"],
            "day_low":      s["day_low"],
            "prev_close":   s["prev_close"],
            "change_pct":   chg,
            "dollar_volume": dv,
            "updated_ms":   s["updated_ms"],
        })

    # Rank: dollar-volume × momentum bonus
    candidates.sort(
        key=lambda c: c["dollar_volume"] * (1 + abs(c["change_pct"]) / 10),
        reverse=True,
    )
    return candidates[:max_candidates]


async def get_snapshot_candidate(symbol: str) -> Optional[dict]:
    """
    Fetch single-ticker snapshot for real-time enrichment of a live candidate.
    Returns snapshot dict or None on failure.
    """
    if not MASSIVE_API_KEY:
        return None
    url = f"{MASSIVE_BASE}/v2/snapshot/locale/us/markets/stocks/tickers/{symbol.upper()}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=4.0)) as client:
            resp = await client.get(url, params=_params())
        if resp.status_code != 200:
            return None
        t = (resp.json().get("ticker")) or {}
        if not t:
            return None
        day      = t.get("day")     or {}
        prev_day = t.get("prevDay") or {}
        day_c = day.get("c") or 0.0
        day_v = int(day.get("v") or 0)
        vwap  = day.get("vw") or day_c
        return {
            "symbol":       symbol.upper(),
            "price":        float(day_c),
            "day_volume":   day_v,
            "day_vwap":     float(vwap),
            "prev_close":   prev_day.get("c"),
            "change_pct":   float(t.get("todaysChangePerc") or 0.0),
            "dollar_volume": float(vwap) * day_v,
        }
    except Exception as exc:
        logger.debug(f"[Snapshot] get_snapshot_candidate({symbol}): {exc}")
        return None
