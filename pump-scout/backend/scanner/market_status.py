"""
Market Status — fetch real-time US market state and upcoming schedule.
======================================================================
Endpoints:
  GET /v1/marketstatus/now       → current session (open / closed / extended-hours)
  GET /v1/marketstatus/upcoming  → holidays and early-close dates

Public API
----------
is_market_open()              → bool          (regular session only, 5-min cache)
is_extended_hours()           → bool          (pre/post-market)
get_market_status()           → dict          (full status dict, 5-min cache)
get_upcoming_closures()       → list[dict]    (holiday/early-close list, 1h cache)
is_trading_day(date_str)      → bool          (True = normal trading day)
next_open_time()              → Optional[datetime UTC]
"""
from __future__ import annotations

import logging
import os
import time
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

MASSIVE_API_KEY = os.getenv("MASSIVE_API_KEY", "")
MASSIVE_BASE    = "https://api.massive.com"
_TIMEOUT        = httpx.Timeout(10.0, connect=5.0)

# Cache TTLs
_STATUS_TTL   = 300    # 5 min — fine-grained enough for open/close detection
_UPCOMING_TTL = 3600   # 1 h  — holiday list only changes overnight

_status_cache:   dict | None       = None
_status_ts:      float             = 0.0

_upcoming_cache: list[dict] | None = None
_upcoming_ts:    float             = 0.0


def _params(**extra) -> dict:
    return {"apiKey": MASSIVE_API_KEY, **extra}


# ── Core status fetch ─────────────────────────────────────────────────────────

async def get_market_status(force: bool = False) -> dict:
    """
    Fetch current market status from Massive /v1/marketstatus/now.
    Returns full response dict (keys: market, serverTime, exchanges, currencies).
    5-min TTL. Returns stale cache or {} on failure — never raises.
    """
    global _status_cache, _status_ts
    now = time.time()
    if not force and _status_cache is not None and now - _status_ts < _STATUS_TTL:
        return _status_cache

    if not MASSIVE_API_KEY:
        logger.debug("[MarketStatus] MASSIVE_API_KEY not set")
        return _status_cache or {}

    url = f"{MASSIVE_BASE}/v1/marketstatus/now"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, params=_params())
        if resp.status_code != 200:
            logger.debug(f"[MarketStatus] HTTP {resp.status_code}")
            return _status_cache or {}
        data = resp.json()
        _status_cache = data
        _status_ts    = now
        return data
    except Exception as exc:
        logger.debug(f"[MarketStatus] get_market_status: {exc}")
        return _status_cache or {}


async def is_market_open() -> bool:
    """
    True when the US regular session is open (09:30–16:00 ET, Mon–Fri, non-holiday).
    Uses 5-min cached status. Returns False on any failure.
    """
    try:
        status = await get_market_status()
        # Massive returns market = "open" | "closed" | "extended-hours"
        return (status.get("market") or "").lower() == "open"
    except Exception:
        return False


async def is_extended_hours() -> bool:
    """True during pre-market or post-market extended hours."""
    try:
        status = await get_market_status()
        return "extended" in (status.get("market") or "").lower()
    except Exception:
        return False


# ── Upcoming schedule ─────────────────────────────────────────────────────────

async def get_upcoming_closures(days: int = 30) -> list[dict]:
    """
    Fetch upcoming market closures and early-close dates from /v1/marketstatus/upcoming.
    Returns list of {date, status, exchange, name}.
    1-hour TTL. Returns stale cache or [] on failure — never raises.
    """
    global _upcoming_cache, _upcoming_ts
    now = time.time()
    if _upcoming_cache is not None and now - _upcoming_ts < _UPCOMING_TTL:
        return _upcoming_cache

    if not MASSIVE_API_KEY:
        return _upcoming_cache or []

    url = f"{MASSIVE_BASE}/v1/marketstatus/upcoming"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, params=_params())
        if resp.status_code != 200:
            logger.debug(f"[MarketStatus] upcoming HTTP {resp.status_code}")
            return _upcoming_cache or []
        body = resp.json()
        # Some API versions return a bare list; others wrap in {"results": [...]}
        results: list[dict] = body if isinstance(body, list) else (body.get("results") or [])
        _upcoming_cache = results
        _upcoming_ts    = now
        return results
    except Exception as exc:
        logger.debug(f"[MarketStatus] get_upcoming_closures: {exc}")
        return _upcoming_cache or []


async def is_trading_day(date_str: str) -> bool:
    """
    Return True if date_str (YYYY-MM-DD) is a normal trading day.
    Returns True when closure list cannot be determined (non-fatal).
    """
    try:
        closures = await get_upcoming_closures()
        for c in closures:
            if c.get("date") == date_str and (c.get("status") or "").lower() == "closed":
                return False
        return True
    except Exception:
        return True


async def next_open_time() -> Optional[datetime]:
    """
    Return the UTC datetime of the next regular-session open.
    Skips weekends and known holidays. Non-fatal: returns None on failure.

    Assumes NYSE regular open = 09:30 ET.  Converts to UTC using 13:30 (EDT)
    as a best-effort approximation (correct Apr–Oct; 14:30 UTC in EST Nov–Mar).
    Callers that need exact DST-correct times should use zoneinfo/pytz directly.
    """
    try:
        closures = await get_upcoming_closures()
        closed_dates = {c["date"] for c in closures if (c.get("status") or "").lower() == "closed"}
        today = date.today()
        for delta in range(1, 14):          # look up to 2 weeks ahead
            candidate = today + timedelta(days=delta)
            if candidate.weekday() >= 5:    # Sat=5, Sun=6
                continue
            ds = candidate.isoformat()
            if ds in closed_dates:
                continue
            # 09:30 ET ≈ 13:30 UTC (EDT).  Good enough for scheduling.
            return datetime(
                candidate.year, candidate.month, candidate.day,
                13, 30, 0, tzinfo=timezone.utc,
            )
        return None
    except Exception as exc:
        logger.debug(f"[MarketStatus] next_open_time: {exc}")
        return None
