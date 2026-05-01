"""
Massive Reference Data — universe cache and corporate actions.
==============================================================
Endpoints used:
  GET /v3/reference/tickers         → full US common-stock universe (nightly sync)
  GET /v3/reference/tickers/types   → allowed / excluded type code definitions
  GET /v3/reference/splits          → corporate action reverse-split detection

Nightly sync builds the local UniverseCache table:
  symbol, name, active, market, type, primary_exchange,
  cik, sic_code, sic_description, market_cap, list_date,
  shares_outstanding, weighted_shares_outstanding, last_synced_at

Usage pattern
-------------
  # Nightly job (run after market close):
  await sync_universe_cache()

  # Live lookup (sync, uses in-memory snapshot):
  meta = get_cached_ticker("AAPL")   # → dict or None

  # Corporate action risk (on-demand):
  splits = await fetch_ticker_splits("AAPL", since="2024-01-01")
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import date, datetime, timedelta
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

MASSIVE_API_KEY = os.getenv("MASSIVE_API_KEY", "")
MASSIVE_BASE    = "https://api.massive.com"
_TIMEOUT        = httpx.Timeout(30.0, connect=10.0)


def _params(**extra) -> dict:
    return {"apiKey": MASSIVE_API_KEY, **extra}


# ── In-memory snapshot (populated by sync_universe_cache) ────────────────────
# {SYMBOL: {name, active, market, type, primary_exchange, cik,
#           sic_code, sic_description, market_cap, list_date,
#           shares_outstanding, weighted_shares_outstanding}}
_universe_snapshot: dict[str, dict] = {}
_snapshot_ts: float = 0.0
_SNAPSHOT_TTL = 86_400  # 24 h — refresh only via nightly sync


def get_cached_ticker(symbol: str) -> Optional[dict]:
    """Sync lookup from in-memory universe snapshot.  Returns None if missing."""
    return _universe_snapshot.get((symbol or "").upper())


def snapshot_size() -> int:
    return len(_universe_snapshot)


def snapshot_age_hours() -> float:
    if not _snapshot_ts:
        return float("inf")
    return round((time.time() - _snapshot_ts) / 3600, 1)


async def load_from_db() -> int:
    """
    Bootstrap _universe_snapshot from the UniverseCache DB table at startup.
    Prevents SIC-based sector resolution from failing after server restart
    (nightly sync at 21:00 ET repopulates from API; this bridges the gap).
    Returns count of tickers loaded.  Non-fatal.
    """
    global _universe_snapshot, _snapshot_ts
    if _universe_snapshot:
        return len(_universe_snapshot)  # already loaded (in-memory sync ran)
    try:
        from database import get_session_factory, UniverseCache as _UC
        from sqlalchemy import select as _sa_select
        async with get_session_factory()() as session:
            result = await session.execute(_sa_select(_UC))
            rows = result.scalars().all()
        if rows:
            _universe_snapshot = {
                r.symbol: {
                    "name":             r.name,
                    "active":           r.active,
                    "market":           r.market,
                    "type":             r.type,
                    "primary_exchange": r.primary_exchange,
                    "cik":              r.cik,
                    "sic_code":         r.sic_code,
                    "sic_description":  r.sic_description,
                    "market_cap":       r.market_cap,
                    "list_date":        r.list_date,
                    "shares_outstanding":           r.shares_outstanding,
                    "weighted_shares_outstanding":  r.weighted_shares_outstanding,
                }
                for r in rows
            }
            _snapshot_ts = time.time()
            logger.info(f"[UniverseCache] Loaded {len(_universe_snapshot)} tickers from DB (startup bootstrap)")
            return len(_universe_snapshot)
        logger.info("[UniverseCache] DB empty — will be populated after nightly sync")
        return 0
    except Exception as exc:
        logger.warning(f"[UniverseCache] load_from_db failed (non-fatal): {exc}")
        return 0


# ── Type-code allowlist / blocklist ───────────────────────────────────────────

# Type codes that represent common equity (from /v3/reference/tickers/types)
_ALLOWED_TYPES: frozenset[str] = frozenset({"CS", "ADR", "ADRC", "ADRW", "ADRR"})

# Type codes that must never enter the universe
_EXCLUDED_TYPES: frozenset[str] = frozenset({
    "ETF", "ETN", "ETV", "FUND", "CEF", "MF",
    "SP", "WARRANT", "RIGHT", "UNIT", "BOND", "NOTE", "PFD",
    "OS", "LTD",
})


async def get_allowed_type_codes() -> dict[str, str]:
    """
    Fetch type code definitions from /v3/reference/tickers/types.
    Returns {type_code: description}.  Non-fatal on failure.
    """
    if not MASSIVE_API_KEY:
        return {}
    url = f"{MASSIVE_BASE}/v3/reference/tickers/types"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, params=_params(asset_class="stocks", locale="us"))
        if resp.status_code != 200:
            logger.warning(f"[UniverseSync] types HTTP {resp.status_code}")
            return {}
        results = resp.json().get("results") or []
        return {r["code"]: r.get("description", "") for r in results if r.get("code")}
    except Exception as exc:
        logger.warning(f"[UniverseSync] get_allowed_type_codes failed: {exc}")
        return {}


# ── Main nightly sync ─────────────────────────────────────────────────────────

async def sync_universe_cache(save_to_db: bool = True) -> int:
    """
    Fetch ALL active US common stocks from Massive reference API.
    Paginates through /v3/reference/tickers until exhausted.

    Returns total count of tickers upserted.
    Updates in-memory _universe_snapshot.

    Parameters
    ----------
    save_to_db : if True (default), upserts rows into UniverseCache via SQLAlchemy.
                 Set False for dry-run / test.
    """
    if not MASSIVE_API_KEY:
        logger.error("[UniverseSync] MASSIVE_API_KEY not set — aborting sync")
        return 0

    logger.info("[UniverseSync] Starting nightly universe sync…")
    rows: list[dict] = []
    url    = f"{MASSIVE_BASE}/v3/reference/tickers"
    params = _params(
        market="stocks",
        locale="us",
        active="true",
        type="CS",   # start with CS; extend to ADR below
        limit=1000,
    )

    # Fetch CS + ADR types in sequence (API only accepts one type per call)
    for ticker_type in ("CS", "ADR", "ADRC"):
        params["type"] = ticker_type
        page_url: Optional[str] = url
        page_params = dict(params)
        page = 0
        type_count = 0

        while page_url and page < 100:
            page += 1
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    if page == 1:
                        resp = await client.get(page_url, params=page_params)
                    else:
                        resp = await client.get(page_url, params={"apiKey": MASSIVE_API_KEY})

                if resp.status_code == 429:
                    logger.warning(f"[UniverseSync] rate limit hit (type={ticker_type} p={page})")
                    await asyncio.sleep(12)
                    continue
                if resp.status_code != 200:
                    logger.warning(
                        f"[UniverseSync] HTTP {resp.status_code} (type={ticker_type} p={page})"
                    )
                    break

                data = resp.json()
                for t in data.get("results") or []:
                    sym = (t.get("ticker") or "").upper()
                    if not sym or not sym.isalpha() or len(sym) > 5:
                        continue
                    rows.append({
                        "symbol":                   sym,
                        "name":                     t.get("name"),
                        "active":                   bool(t.get("active", True)),
                        "market":                   t.get("market"),
                        "type":                     t.get("type"),
                        "primary_exchange":         t.get("primary_exchange"),
                        "cik":                      t.get("cik"),
                        "sic_code":                 t.get("sic_code"),
                        "sic_description":          t.get("sic_description"),
                        "market_cap":               t.get("market_cap"),
                        "list_date":                t.get("list_date"),
                        "shares_outstanding":       t.get("share_class_shares_outstanding"),
                        "weighted_shares_outstanding": t.get("weighted_shares_outstanding"),
                    })
                    type_count += 1

                page_url = data.get("next_url")

            except Exception as exc:
                logger.warning(
                    f"[UniverseSync] fetch error (type={ticker_type} p={page}): {exc}"
                )
                break

        logger.info(f"[UniverseSync]   {ticker_type}: {type_count} tickers fetched")

    if not rows:
        logger.warning("[UniverseSync] 0 tickers returned — check API key / plan")
        return 0

    # Deduplicate by symbol (keep last entry per symbol)
    deduped: dict[str, dict] = {r["symbol"]: r for r in rows}
    logger.info(f"[UniverseSync] Total: {len(deduped)} unique tickers")

    # ── Update in-memory snapshot ─────────────────────────────────────────────
    global _universe_snapshot, _snapshot_ts
    _universe_snapshot = deduped
    _snapshot_ts       = time.time()

    if not save_to_db:
        return len(deduped)

    # ── Upsert to UniverseCache DB table ─────────────────────────────────────
    try:
        await _upsert_universe_cache(list(deduped.values()))
    except Exception as exc:
        logger.error(f"[UniverseSync] DB upsert failed: {exc}", exc_info=True)

    logger.info(f"[UniverseSync] Sync complete — {len(deduped)} tickers cached")
    return len(deduped)


async def _upsert_universe_cache(rows: list[dict]) -> None:
    """Bulk-upsert rows into the UniverseCache table."""
    from database import get_session_factory, UniverseCache
    from sqlalchemy import select

    now = datetime.utcnow()
    BATCH = 500

    async with get_session_factory()() as session:
        for i in range(0, len(rows), BATCH):
            chunk = rows[i: i + BATCH]
            syms  = [r["symbol"] for r in chunk]

            # Load existing rows for this batch
            result = await session.execute(
                select(UniverseCache).where(UniverseCache.symbol.in_(syms))
            )
            existing = {row.symbol: row for row in result.scalars()}

            for r in chunk:
                sym = r["symbol"]
                if sym in existing:
                    obj = existing[sym]
                    obj.name                     = r["name"]
                    obj.active                   = r["active"]
                    obj.market                   = r["market"]
                    obj.type                     = r["type"]
                    obj.primary_exchange         = r["primary_exchange"]
                    obj.cik                      = r["cik"]
                    obj.sic_code                 = r["sic_code"]
                    obj.sic_description          = r["sic_description"]
                    obj.market_cap               = r["market_cap"]
                    obj.list_date                = r["list_date"]
                    obj.shares_outstanding       = r["shares_outstanding"]
                    obj.weighted_shares_outstanding = r["weighted_shares_outstanding"]
                    obj.last_synced_at           = now
                else:
                    session.add(UniverseCache(
                        symbol                      = sym,
                        name                        = r["name"],
                        active                      = r["active"],
                        market                      = r["market"],
                        type                        = r["type"],
                        primary_exchange            = r["primary_exchange"],
                        cik                         = r["cik"],
                        sic_code                    = r["sic_code"],
                        sic_description             = r["sic_description"],
                        market_cap                  = r["market_cap"],
                        list_date                   = r["list_date"],
                        shares_outstanding          = r["shares_outstanding"],
                        weighted_shares_outstanding = r["weighted_shares_outstanding"],
                        last_synced_at              = now,
                    ))

            await session.commit()
            logger.debug(f"[UniverseSync] Upserted batch {i // BATCH + 1} ({len(chunk)} rows)")


# ── Corporate action splits ───────────────────────────────────────────────────

async def fetch_ticker_splits(
    symbol: str,
    since: Optional[str] = None,
) -> list[dict]:
    """
    Fetch corporate action splits for one symbol.

    Endpoint: GET /v3/reference/splits

    Parameters
    ----------
    symbol : ticker string
    since  : YYYY-MM-DD lower bound for execution_date (default: 90 days ago)

    Returns list of split dicts:
      {ticker, execution_date, split_from, split_to, reverse_split_risk}
    where reverse_split_risk = True when split_to < split_from (reverse split).

    Returns [] on failure (non-fatal).
    """
    if not MASSIVE_API_KEY:
        return []

    if since is None:
        since = (date.today() - timedelta(days=90)).isoformat()

    url = f"{MASSIVE_BASE}/v3/reference/splits"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0)) as client:
            resp = await client.get(url, params=_params(
                ticker                 = symbol.upper(),
                execution_date_gte     = since,
                limit                  = 100,
                sort                   = "execution_date",
                order                  = "desc",
            ))

        if resp.status_code == 404:
            return []
        if resp.status_code != 200:
            logger.debug(f"[Splits] HTTP {resp.status_code} for {symbol}")
            return []

        results = []
        for r in resp.json().get("results") or []:
            split_from = r.get("split_from", 1)
            split_to   = r.get("split_to",   1)
            results.append({
                "ticker":             r.get("ticker", symbol),
                "execution_date":     r.get("execution_date"),
                "split_from":         split_from,
                "split_to":           split_to,
                "reverse_split_risk": split_to < split_from,
            })
        return results

    except Exception as exc:
        logger.debug(f"[Splits] fetch_ticker_splits({symbol}): {exc}")
        return []


async def has_recent_reverse_split(symbol: str, days: int = 90) -> bool:
    """
    Return True if the ticker had a reverse split in the last `days` days.
    Used for scan-time risk annotation; non-fatal.
    """
    since = (date.today() - timedelta(days=days)).isoformat()
    splits = await fetch_ticker_splits(symbol, since=since)
    return any(s["reverse_split_risk"] for s in splits)
