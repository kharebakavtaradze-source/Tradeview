"""
Database layer using SQLAlchemy async with PostgreSQL (asyncpg).
Railway provides DATABASE_URL automatically.
"""
import json
import logging
import os
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import Boolean, Column, Date, DateTime, Float, Integer, String, Text, select, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

logger = logging.getLogger(__name__)

# Build async database URL
def _get_db_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        # SQLite fallback for local development without PostgreSQL
        return "sqlite+aiosqlite:///./pump_scout.db"
    # Railway may provide postgresql:// — convert to asyncpg driver
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
    elif url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql+asyncpg://", 1)
    return url


DATABASE_URL = _get_db_url()
_IS_SQLITE = "sqlite" in DATABASE_URL

# Engine creation — defer to first use
_engine = None
_async_session = None


def get_engine():
    global _engine
    if _engine is None:
        connect_args = {}
        if _IS_SQLITE:
            connect_args = {"check_same_thread": False}
        _engine = create_async_engine(
            DATABASE_URL,
            echo=False,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
    return _engine


def get_session_factory():
    global _async_session
    if _async_session is None:
        _async_session = sessionmaker(
            get_engine(), class_=AsyncSession, expire_on_commit=False
        )
    return _async_session


class Base(DeclarativeBase):
    pass


class Scan(Base):
    __tablename__ = "scans"

    id = Column(Integer, primary_key=True, index=True)
    scanned_at = Column(DateTime, default=datetime.utcnow, index=True)
    total_tickers = Column(Integer, default=0)
    results_json = Column(Text, nullable=False)


class Watchlist(Base):
    __tablename__ = "watchlist"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(10), nullable=False, unique=True, index=True)
    added_at = Column(DateTime, default=datetime.utcnow)
    notes = Column(Text, nullable=True)


class Journal(Base):
    __tablename__ = "journal"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(10), nullable=False, index=True)
    added_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    entry_price = Column(Float, nullable=False)
    entry_date = Column(String(20), nullable=False)
    exit_price = Column(Float, nullable=True)
    exit_date = Column(String(20), nullable=True)
    direction = Column(String(10), default="LONG")
    tier = Column(String(20), nullable=True)
    score = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    outcome = Column(String(20), default="open")   # win / loss / open / skip
    gain_pct = Column(Float, nullable=True)        # auto-calculated on save
    indicators_snapshot = Column(Text, nullable=True)  # JSON
    ai_analysis = Column(Text, nullable=True)
    tags = Column(Text, nullable=True)             # JSON array
    # ── Extended fields (v10+) ─────────────────────────────────────────────
    entry_wyckoff = Column(String(30), nullable=True)
    entry_cmf_pctl = Column(Float, nullable=True)
    entry_vol_ratio = Column(Float, nullable=True)
    entry_hype = Column(Integer, default=0)
    catalyst = Column(String(50), nullable=True)
    stop_loss = Column(Float, nullable=True)
    target_price = Column(Float, nullable=True)
    current_price = Column(Float, nullable=True)
    current_pct = Column(Float, nullable=True)
    days_held = Column(Integer, default=0)
    max_gain_pct = Column(Float, default=0)
    max_loss_pct = Column(Float, default=0)
    status = Column(String(10), default="OPEN")    # OPEN / CLOSED / STOPPED
    exit_reason = Column(String(20), nullable=True)  # TARGET_HIT / STOP_HIT / MANUAL
    final_pnl_pct = Column(Float, nullable=True)
    # ── Alpha / SPY tracking (v13+) ───────────────────────────────────────────
    spy_return_pct = Column(Float, nullable=True)   # SPY cumulative % during hold
    alpha_pct = Column(Float, nullable=True)         # final_pnl_pct - spy_return_pct
    max_gain_day = Column(Integer, nullable=True)    # day number of max gain
    missed_exit_pct = Column(Float, nullable=True)   # max_gain_pct - final_pnl_pct
    last_updated = Column(DateTime, nullable=True)


class ScanCandidate(Base):
    """Control group — every FIRE/ARM ticker from each scan."""
    __tablename__ = "scan_candidates"

    id = Column(Integer, primary_key=True, index=True)
    scan_date = Column(Date, nullable=False, index=True)
    symbol = Column(String(10), nullable=False, index=True)
    price = Column(Float, nullable=True)
    tier = Column(String(10), nullable=True)
    score = Column(Float, nullable=True)
    wyckoff = Column(String(30), nullable=True)
    cmf_pctl = Column(Float, nullable=True)
    vol_ratio = Column(Float, nullable=True)
    hype = Column(Integer, default=0)
    divergences = Column(String(200), nullable=True)
    was_journaled = Column(Boolean, default=False)
    price_5d = Column(Float, nullable=True)
    pct_5d = Column(Float, nullable=True)
    price_10d = Column(Float, nullable=True)
    pct_10d = Column(Float, nullable=True)
    price_20d = Column(Float, nullable=True)
    pct_20d = Column(Float, nullable=True)


class PositionSnapshot(Base):
    """Daily end-of-day snapshot for each open journal entry."""
    __tablename__ = "position_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    journal_id = Column(Integer, nullable=False, index=True)
    snapshot_date = Column(Date, nullable=False)
    day_number = Column(Integer, nullable=False)
    price = Column(Float, nullable=True)
    pct_from_entry = Column(Float, nullable=True)
    cmf_pctl = Column(Float, nullable=True)
    vol_ratio = Column(Float, nullable=True)
    hype = Column(Integer, nullable=True)
    wyckoff = Column(String(30), nullable=True)
    spy_daily_pct = Column(Float, nullable=True)


class AIPortfolio(Base):
    __tablename__ = "ai_portfolio"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(10), nullable=False, index=True)
    action = Column(String(10), nullable=False)      # BUY / SELL / HOLD
    decision_date = Column(DateTime, default=datetime.utcnow)
    entry_price = Column(Float, nullable=True)
    exit_price = Column(Float, nullable=True)
    shares = Column(Float, nullable=True)
    invested_usd = Column(Float, default=0)
    current_value = Column(Float, nullable=True)
    pnl_usd = Column(Float, default=0)
    pnl_pct = Column(Float, default=0)
    status = Column(String(10), default="OPEN")      # OPEN / CLOSED
    reason = Column(Text, nullable=True)
    scan_data = Column(Text, nullable=True)          # JSON
    exit_date = Column(DateTime, nullable=True)
    days_held = Column(Integer, default=0)


class AIPortfolioState(Base):
    __tablename__ = "ai_portfolio_state"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(String(10), unique=True, nullable=False, index=True)  # YYYY-MM-DD
    total_value = Column(Float, default=1000.0)
    cash = Column(Float, default=1000.0)
    invested = Column(Float, default=0)
    total_pnl_pct = Column(Float, default=0)
    decisions_json = Column(Text, nullable=True)   # JSON
    daily_report = Column(Text, nullable=True)     # JSON


class SectorCache(Base):
    """Persistent sector cache — avoids repeated Yahoo Finance API calls."""
    __tablename__ = "sector_cache"

    symbol = Column(String(20), primary_key=True, index=True)
    sector = Column(String(100), nullable=False)
    fetched_at = Column(DateTime, default=datetime.utcnow)


class EodLog(Base):
    """End-of-day markdown log — one per trading day."""
    __tablename__ = "eod_logs"

    id = Column(Integer, primary_key=True, index=True)
    log_date = Column(String(10), unique=True, nullable=False, index=True)  # YYYY-MM-DD
    content = Column(Text, nullable=False)
    generated_at = Column(DateTime, default=datetime.utcnow)


class MarketRegime(Base):
    """Daily market regime snapshot (RISK_ON / RISK_OFF / FEAR / ROTATION / NEUTRAL)."""
    __tablename__ = "market_regime"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, unique=True, nullable=False, index=True)
    regime = Column(String(30), nullable=False)
    spy_pct = Column(Float, nullable=True)
    qqq_pct = Column(Float, nullable=True)
    xle_pct = Column(Float, nullable=True)
    xlv_pct = Column(Float, nullable=True)
    xlu_pct = Column(Float, nullable=True)
    gld_pct = Column(Float, nullable=True)
    spy_vs_ema20 = Column(Float, nullable=True)
    qqq_vs_ema20 = Column(Float, nullable=True)
    strong_sectors = Column(String(200), nullable=True)   # comma-separated
    weak_sectors = Column(String(200), nullable=True)     # comma-separated
    recommendation = Column(Text, nullable=True)
    etf_details_json = Column(Text, nullable=True)        # JSON
    created_at = Column(DateTime, default=datetime.utcnow)


class SectorStrength(Base):
    """Per-sector aggregate strength for a given scan date."""
    __tablename__ = "sector_strength"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(Date, nullable=False, index=True)
    sector = Column(String(50), nullable=False)
    avg_score = Column(Float, nullable=True)
    avg_cmf_pctl = Column(Float, nullable=True)
    avg_vol_ratio = Column(Float, nullable=True)
    ticker_count = Column(Integer, nullable=True)
    leader_symbol = Column(String(10), nullable=True)
    leader_score = Column(Float, nullable=True)
    momentum_pct = Column(Float, nullable=True)
    tickers_json = Column(Text, nullable=True)           # JSON list


_JOURNAL_MIGRATIONS = [
    ("direction",       "VARCHAR(10) DEFAULT 'LONG'"),
    ("updated_at",      "TIMESTAMP"),
    ("entry_wyckoff",   "VARCHAR(30)"),
    ("entry_cmf_pctl",  "FLOAT"),
    ("entry_vol_ratio", "FLOAT"),
    ("entry_hype",      "INTEGER DEFAULT 0"),
    ("catalyst",        "VARCHAR(50)"),
    ("stop_loss",       "FLOAT"),
    ("target_price",    "FLOAT"),
    ("current_price",   "FLOAT"),
    ("current_pct",     "FLOAT"),
    ("days_held",       "INTEGER DEFAULT 0"),
    ("max_gain_pct",    "FLOAT DEFAULT 0"),
    ("max_loss_pct",    "FLOAT DEFAULT 0"),
    ("status",          "VARCHAR(10) DEFAULT 'OPEN'"),
    ("exit_reason",     "VARCHAR(20)"),
    ("final_pnl_pct",   "FLOAT"),
    # v13+ alpha tracking
    ("spy_return_pct",  "FLOAT"),
    ("alpha_pct",       "FLOAT"),
    ("max_gain_day",    "INTEGER"),
    ("missed_exit_pct", "FLOAT"),
    ("last_updated",    "TIMESTAMP"),
]


async def _run_migrations(conn):
    """
    Safe ALTER TABLE statements for columns added after initial deployment.
    Uses IF NOT EXISTS / IGNORE patterns so they're idempotent.
    PostgreSQL and SQLite handled separately.
    """
    if _IS_SQLITE:
        for col, coltype in _JOURNAL_MIGRATIONS:
            try:
                await conn.execute(text(f"ALTER TABLE journal ADD COLUMN {col} {coltype}"))
            except Exception:
                pass  # column already exists
    else:
        for col, coltype in _JOURNAL_MIGRATIONS:
            try:
                await conn.execute(text(
                    f"ALTER TABLE journal ADD COLUMN IF NOT EXISTS {col} {coltype}"
                ))
            except Exception as e:
                logger.warning(f"Migration {col} failed (non-fatal): {e}")


async def init_db():
    """Create tables if they don't exist, then run safe migrations."""
    try:
        async with get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await _run_migrations(conn)
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise


async def save_scan(data: dict) -> int:
    """
    Persist a scan result. Returns the new scan ID.
    Keeps only the last 7 scans — prunes older ones automatically.
    """
    results = data.get("results", [])
    slim_results = [{k: v for k, v in r.items() if k != "candles"} for r in results]
    scan_data = {**data, "results": slim_results}

    async with get_session_factory()() as session:
        scan = Scan(
            scanned_at=datetime.utcnow(),
            total_tickers=data.get("total", len(results)),
            results_json=json.dumps(scan_data),
        )
        session.add(scan)
        await session.commit()
        await session.refresh(scan)
        scan_id = scan.id
        logger.info(f"Saved scan #{scan_id} with {scan.total_tickers} tickers")

    # Prune old scans — keep only the latest 7
    try:
        async with get_session_factory()() as session:
            result = await session.execute(
                select(Scan.id).order_by(Scan.scanned_at.desc()).offset(7)
            )
            old_ids = [row[0] for row in result.fetchall()]
            if old_ids:
                for old_id in old_ids:
                    old = await session.get(Scan, old_id)
                    if old:
                        await session.delete(old)
                await session.commit()
                logger.info(f"Pruned {len(old_ids)} old scans (kept last 7)")
    except Exception as e:
        logger.warning(f"Scan pruning failed (non-fatal): {e}")

    return scan_id


async def get_latest_scan() -> Optional[dict]:
    """Retrieve the most recent scan result."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(Scan).order_by(Scan.scanned_at.desc()).limit(1)
        )
        scan = result.scalar_one_or_none()
        if not scan:
            return None
        data = json.loads(scan.results_json)
        data["scan_id"] = scan.id
        return data


async def get_scan_history(days: int = 30) -> List[dict]:
    """Return a summary of scans from the last N days."""
    since = datetime.utcnow() - timedelta(days=days)
    async with get_session_factory()() as session:
        result = await session.execute(
            select(Scan)
            .where(Scan.scanned_at >= since)
            .order_by(Scan.scanned_at.desc())
        )
        scans = result.scalars().all()

    history = []
    for scan in scans:
        try:
            data = json.loads(scan.results_json)
            history.append({
                "scan_id": scan.id,
                "scanned_at": scan.scanned_at.isoformat(),
                "total_tickers": scan.total_tickers,
                "tier_counts": data.get("tier_counts", {}),
                "top_tickers": [
                    {"symbol": r["symbol"], "tier": r["score"]["tier"], "score": r["score"]["total_score"]}
                    for r in data.get("results", [])[:10]
                ],
            })
        except Exception as e:
            logger.warning(f"Error parsing scan #{scan.id}: {e}")

    return history


async def get_watchlist() -> List[dict]:
    """Return all watchlist entries."""
    async with get_session_factory()() as session:
        result = await session.execute(select(Watchlist).order_by(Watchlist.added_at.desc()))
        items = result.scalars().all()
    return [
        {"id": w.id, "symbol": w.symbol, "added_at": w.added_at.isoformat(), "notes": w.notes}
        for w in items
    ]


async def add_to_watchlist(symbol: str, notes: Optional[str] = None) -> dict:
    """Add a ticker to the watchlist."""
    async with get_session_factory()() as session:
        item = Watchlist(symbol=symbol.upper(), notes=notes)
        session.add(item)
        await session.commit()
        await session.refresh(item)
    return {"id": item.id, "symbol": item.symbol, "added_at": item.added_at.isoformat()}


async def remove_from_watchlist(symbol: str) -> bool:
    """Remove a ticker from the watchlist. Returns True if removed."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(Watchlist).where(Watchlist.symbol == symbol.upper())
        )
        item = result.scalar_one_or_none()
        if not item:
            return False
        await session.delete(item)
        await session.commit()
    return True


# ─── Sector Cache ─────────────────────────────────────────────────────────────

async def get_sector_from_db(symbol: str) -> Optional[str]:
    """
    Return cached sector if fresh (< 24h). Returns None if stale or missing.
    """
    cutoff = datetime.utcnow() - timedelta(hours=24)
    try:
        async with get_session_factory()() as session:
            result = await session.execute(
                select(SectorCache).where(SectorCache.symbol == symbol.upper())
            )
            row = result.scalar_one_or_none()
            if row and row.fetched_at and row.fetched_at >= cutoff:
                return row.sector
    except Exception as e:
        logger.debug(f"sector_cache read failed for {symbol}: {e}")
    return None


async def save_sector_to_db(symbol: str, sector: str) -> None:
    """Upsert sector value into the DB cache."""
    try:
        async with get_session_factory()() as session:
            result = await session.execute(
                select(SectorCache).where(SectorCache.symbol == symbol.upper())
            )
            row = result.scalar_one_or_none()
            if row:
                row.sector = sector
                row.fetched_at = datetime.utcnow()
            else:
                session.add(SectorCache(
                    symbol=symbol.upper(),
                    sector=sector,
                    fetched_at=datetime.utcnow(),
                ))
            await session.commit()
    except Exception as e:
        logger.debug(f"sector_cache write failed for {symbol}: {e}")


# ─── Journal ─────────────────────────────────────────────────────────────────

def _journal_to_dict(j: Journal) -> dict:
    return {
        "id": j.id,
        "symbol": j.symbol,
        "added_at": j.added_at.isoformat() if j.added_at else None,
        "updated_at": j.updated_at.isoformat() if j.updated_at else None,
        "entry_price": j.entry_price,
        "entry_date": j.entry_date,
        "exit_price": j.exit_price,
        "exit_date": j.exit_date,
        "direction": j.direction or "LONG",
        "tier": j.tier,
        "score": j.score,
        "notes": j.notes,
        "outcome": j.outcome,
        "gain_pct": j.gain_pct,
        "indicators_snapshot": json.loads(j.indicators_snapshot) if j.indicators_snapshot else None,
        "ai_analysis": j.ai_analysis,
        "tags": json.loads(j.tags) if j.tags else [],
        # Extended v10+ fields
        "entry_wyckoff": j.entry_wyckoff,
        "entry_cmf_pctl": j.entry_cmf_pctl,
        "entry_vol_ratio": j.entry_vol_ratio,
        "entry_hype": j.entry_hype or 0,
        "catalyst": j.catalyst,
        "stop_loss": j.stop_loss,
        "target_price": j.target_price,
        "current_price": j.current_price,
        "current_pct": j.current_pct,
        "days_held": j.days_held or 0,
        "max_gain_pct": j.max_gain_pct or 0,
        "max_loss_pct": j.max_loss_pct or 0,
        "status": j.status or "OPEN",
        "exit_reason": j.exit_reason,
        "final_pnl_pct": j.final_pnl_pct,
        # v13+ alpha tracking
        "spy_return_pct": j.spy_return_pct,
        "alpha_pct": j.alpha_pct,
        "max_gain_day": j.max_gain_day,
        "missed_exit_pct": j.missed_exit_pct,
        "last_updated": j.last_updated.isoformat() if j.last_updated else None,
    }


def _calc_gain_pct(entry_price, exit_price, direction="LONG") -> Optional[float]:
    if entry_price and exit_price and entry_price > 0:
        pct = (exit_price - entry_price) / entry_price * 100
        if direction == "SHORT":
            pct = -pct
        return round(pct, 2)
    return None


async def get_journal() -> List[dict]:
    async with get_session_factory()() as session:
        result = await session.execute(select(Journal).order_by(Journal.added_at.desc()))
        items = result.scalars().all()
    return [_journal_to_dict(j) for j in items]


async def get_journal_entry(entry_id: int) -> Optional[dict]:
    async with get_session_factory()() as session:
        result = await session.execute(select(Journal).where(Journal.id == entry_id))
        entry = result.scalar_one_or_none()
    return _journal_to_dict(entry) if entry else None


async def add_journal_entry(data: dict) -> dict:
    direction = data.get("direction", "LONG").upper()
    gain = _calc_gain_pct(data.get("entry_price"), data.get("exit_price"), direction)
    async with get_session_factory()() as session:
        entry = Journal(
            symbol=data["symbol"].upper(),
            entry_price=data["entry_price"],
            entry_date=data.get("entry_date", datetime.utcnow().strftime("%Y-%m-%d")),
            exit_price=data.get("exit_price"),
            exit_date=data.get("exit_date"),
            direction=direction,
            tier=data.get("tier"),
            score=data.get("score"),
            notes=data.get("notes"),
            outcome=data.get("outcome", "open"),
            gain_pct=gain,
            indicators_snapshot=json.dumps(data["indicators_snapshot"]) if data.get("indicators_snapshot") else None,
            ai_analysis=data.get("ai_analysis"),
            tags=json.dumps(data.get("tags", [])),
            updated_at=datetime.utcnow(),
            # Extended v10+ fields
            entry_wyckoff=data.get("entry_wyckoff"),
            entry_cmf_pctl=data.get("entry_cmf_pctl"),
            entry_vol_ratio=data.get("entry_vol_ratio"),
            entry_hype=data.get("entry_hype", 0),
            catalyst=data.get("catalyst"),
            stop_loss=data.get("stop_loss"),
            target_price=data.get("target_price"),
            status="OPEN",
        )
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
    return _journal_to_dict(entry)


async def update_journal_entry(entry_id: int, data: dict) -> Optional[dict]:
    async with get_session_factory()() as session:
        result = await session.execute(select(Journal).where(Journal.id == entry_id))
        entry = result.scalar_one_or_none()
        if not entry:
            return None
        updatable = (
            "exit_price", "exit_date", "notes", "outcome", "tier", "score",
            "ai_analysis", "direction", "stop_loss", "target_price", "catalyst",
            "current_price", "current_pct", "days_held", "max_gain_pct", "max_loss_pct",
            "status", "exit_reason", "final_pnl_pct",
            "spy_return_pct", "alpha_pct", "max_gain_day", "missed_exit_pct", "last_updated",
        )
        for field in updatable:
            if field in data:
                setattr(entry, field, data[field])
        if "tags" in data:
            entry.tags = json.dumps(data["tags"])
        direction = getattr(entry, "direction", "LONG") or "LONG"
        entry.gain_pct = _calc_gain_pct(entry.entry_price, entry.exit_price, direction)
        entry.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(entry)
    return _journal_to_dict(entry)


async def get_open_journal_entries() -> List[dict]:
    """Return journal entries with status=OPEN / outcome=open."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(Journal).where(Journal.outcome == "open").order_by(Journal.added_at.desc())
        )
        items = result.scalars().all()
    return [_journal_to_dict(j) for j in items]


async def delete_journal_entry(entry_id: int) -> bool:
    async with get_session_factory()() as session:
        result = await session.execute(select(Journal).where(Journal.id == entry_id))
        entry = result.scalar_one_or_none()
        if not entry:
            return False
        await session.delete(entry)
        await session.commit()
    return True


async def get_journal_stats() -> dict:
    entries = await get_journal()
    closed = [e for e in entries if e["outcome"] in ("win", "loss")]
    wins = [e for e in entries if e["outcome"] == "win"]
    losses = [e for e in entries if e["outcome"] == "loss"]
    open_trades = [e for e in entries if e["outcome"] == "open"]

    win_rate = round(len(wins) / len(closed) * 100, 1) if closed else 0
    avg_win = round(sum(e["gain_pct"] or 0 for e in wins) / len(wins), 2) if wins else 0
    avg_loss = round(sum(e["gain_pct"] or 0 for e in losses) / len(losses), 2) if losses else 0
    total_pnl = round(sum(e["gain_pct"] or 0 for e in closed), 2)

    # Best tier by win rate
    tier_stats: dict = {}
    for e in closed:
        t = e.get("tier") or "UNKNOWN"
        tier_stats.setdefault(t, {"wins": 0, "total": 0})
        tier_stats[t]["total"] += 1
        if e["outcome"] == "win":
            tier_stats[t]["wins"] += 1
    best_tier = max(
        tier_stats, key=lambda t: tier_stats[t]["wins"] / tier_stats[t]["total"]
    ) if tier_stats else None

    # Best score range
    buckets: dict = {}
    for e in closed:
        sc = e.get("score") or 0
        b = f"{int(sc // 10) * 10}-{int(sc // 10) * 10 + 10}"
        buckets.setdefault(b, {"wins": 0, "total": 0})
        buckets[b]["total"] += 1
        if e["outcome"] == "win":
            buckets[b]["wins"] += 1
    best_range = max(
        buckets, key=lambda b: buckets[b]["wins"] / buckets[b]["total"]
    ) if buckets else None

    return {
        "total_trades": len(entries),
        "open_trades": len(open_trades),
        "closed_trades": len(closed),
        "win_rate_pct": win_rate,
        "avg_gain_winners": avg_win,
        "avg_loss_losers": avg_loss,
        "total_pnl_pct": total_pnl,
        "best_tier": best_tier,
        "best_score_range": best_range,
        "wins": len(wins),
        "losses": len(losses),
    }


# ─── AI Portfolio ─────────────────────────────────────────────────────────────

def _portfolio_to_dict(p: AIPortfolio) -> dict:
    return {
        "id": p.id,
        "symbol": p.symbol,
        "action": p.action,
        "decision_date": p.decision_date.isoformat() if p.decision_date else None,
        "entry_price": p.entry_price,
        "exit_price": p.exit_price,
        "exit_date": p.exit_date.isoformat() if p.exit_date else None,
        "shares": p.shares,
        "invested_usd": p.invested_usd,
        "current_value": p.current_value,
        "pnl_usd": p.pnl_usd or 0,
        "pnl_pct": p.pnl_pct or 0,
        "status": p.status,
        "reason": p.reason,
        "days_held": p.days_held or 0,
        "scan_data": json.loads(p.scan_data) if p.scan_data else None,
    }


async def get_portfolio_state() -> dict:
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    async with get_session_factory()() as session:
        result = await session.execute(
            select(AIPortfolioState).order_by(AIPortfolioState.id.desc()).limit(1)
        )
        state = result.scalar_one_or_none()
        if not state:
            # Bootstrap with $1000
            state = AIPortfolioState(date=today_str, cash=1000.0, total_value=1000.0)
            session.add(state)
            await session.commit()
            await session.refresh(state)
    return {
        "date": state.date,
        "total_value": state.total_value,
        "cash": state.cash,
        "invested": state.invested or 0,
        "total_pnl_pct": state.total_pnl_pct or 0,
        "decisions_json": json.loads(state.decisions_json) if state.decisions_json else None,
        "daily_report": json.loads(state.daily_report) if state.daily_report else None,
    }


async def update_portfolio_state(cash: float, total_value: float, invested: float,
                                  total_pnl_pct: float, decisions: dict | None = None,
                                  report: dict | None = None) -> None:
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    async with get_session_factory()() as session:
        result = await session.execute(
            select(AIPortfolioState).where(AIPortfolioState.date == today_str)
        )
        state = result.scalar_one_or_none()
        if not state:
            state = AIPortfolioState(date=today_str)
            session.add(state)
        state.cash = cash
        state.total_value = total_value
        state.invested = invested
        state.total_pnl_pct = total_pnl_pct
        if decisions:
            state.decisions_json = json.dumps(decisions)
        if report:
            state.daily_report = json.dumps(report)
        await session.commit()


async def get_open_ai_positions() -> List[dict]:
    async with get_session_factory()() as session:
        result = await session.execute(
            select(AIPortfolio).where(AIPortfolio.status == "OPEN").order_by(AIPortfolio.decision_date.desc())
        )
        items = result.scalars().all()
    return [_portfolio_to_dict(p) for p in items]


async def get_all_ai_positions(limit: int = 50) -> List[dict]:
    async with get_session_factory()() as session:
        result = await session.execute(
            select(AIPortfolio).order_by(AIPortfolio.decision_date.desc()).limit(limit)
        )
        items = result.scalars().all()
    return [_portfolio_to_dict(p) for p in items]


async def insert_ai_position(symbol: str, entry_price: float, shares: float,
                              invested_usd: float, reason: str,
                              scan_data: dict | None = None) -> dict:
    async with get_session_factory()() as session:
        pos = AIPortfolio(
            symbol=symbol.upper(),
            action="BUY",
            decision_date=datetime.utcnow(),
            entry_price=entry_price,
            shares=shares,
            invested_usd=invested_usd,
            current_value=invested_usd,
            status="OPEN",
            reason=reason,
            scan_data=json.dumps(scan_data) if scan_data else None,
        )
        session.add(pos)
        await session.commit()
        await session.refresh(pos)
    return _portfolio_to_dict(pos)


async def close_ai_position(symbol: str, exit_price: float, reason: str) -> Optional[dict]:
    async with get_session_factory()() as session:
        result = await session.execute(
            select(AIPortfolio).where(
                AIPortfolio.symbol == symbol.upper(),
                AIPortfolio.status == "OPEN",
            ).order_by(AIPortfolio.decision_date.desc()).limit(1)
        )
        pos = result.scalar_one_or_none()
        if not pos:
            return None
        pos.status = "CLOSED"
        pos.exit_price = exit_price
        pos.exit_date = datetime.utcnow()
        if pos.entry_price and pos.entry_price > 0:
            pos.pnl_pct = round((exit_price - pos.entry_price) / pos.entry_price * 100, 2)
            pos.pnl_usd = round((exit_price - pos.entry_price) * (pos.shares or 0), 2)
        pos.current_value = exit_price * (pos.shares or 0)
        await session.commit()
        await session.refresh(pos)
    return _portfolio_to_dict(pos)


async def update_ai_position_price(position_id: int, current_price: float) -> None:
    async with get_session_factory()() as session:
        result = await session.execute(select(AIPortfolio).where(AIPortfolio.id == position_id))
        pos = result.scalar_one_or_none()
        if not pos:
            return
        pos.current_value = current_price * (pos.shares or 0)
        if pos.entry_price and pos.entry_price > 0:
            pos.pnl_pct = round((current_price - pos.entry_price) / pos.entry_price * 100, 2)
            pos.pnl_usd = round((current_price - pos.entry_price) * (pos.shares or 0), 2)
        days = (datetime.utcnow() - pos.decision_date).days if pos.decision_date else 0
        pos.days_held = days
        await session.commit()


async def get_ai_portfolio_history(limit: int = 10) -> List[dict]:
    async with get_session_factory()() as session:
        result = await session.execute(
            select(AIPortfolioState).order_by(AIPortfolioState.id.desc()).limit(limit)
        )
        rows = result.scalars().all()
    return [
        {
            "date": r.date,
            "total_value": r.total_value,
            "cash": r.cash,
            "total_pnl_pct": r.total_pnl_pct or 0,
        }
        for r in reversed(rows)
    ]


# ─── Scan Candidates ──────────────────────────────────────────────────────────

def _candidate_to_dict(c: ScanCandidate) -> dict:
    return {
        "id": c.id,
        "scan_date": c.scan_date.isoformat() if c.scan_date else None,
        "symbol": c.symbol,
        "price": c.price,
        "tier": c.tier,
        "score": c.score,
        "wyckoff": c.wyckoff,
        "cmf_pctl": c.cmf_pctl,
        "vol_ratio": c.vol_ratio,
        "hype": c.hype or 0,
        "divergences": c.divergences,
        "was_journaled": c.was_journaled or False,
        "price_5d": c.price_5d,
        "pct_5d": c.pct_5d,
        "price_10d": c.price_10d,
        "pct_10d": c.pct_10d,
        "price_20d": c.price_20d,
        "pct_20d": c.pct_20d,
    }


async def save_scan_candidates(scan_results: list) -> int:
    """Save FIRE/ARM tickers from a scan as control-group candidates."""
    from datetime import date as date_type
    today = date_type.today()
    candidates = [r for r in scan_results if r.get("score", {}).get("tier") in ("FIRE", "ARM")]
    if not candidates:
        return 0
    saved = 0
    async with get_session_factory()() as session:
        for r in candidates:
            try:
                # Check if already saved today
                existing = await session.execute(
                    select(ScanCandidate).where(
                        ScanCandidate.symbol == r["symbol"],
                        ScanCandidate.scan_date == today,
                    )
                )
                if existing.scalar_one_or_none():
                    continue
                divs = ",".join(d["type"] for d in r.get("divergences", []))
                cand = ScanCandidate(
                    scan_date=today,
                    symbol=r["symbol"],
                    price=r.get("price"),
                    tier=r["score"]["tier"],
                    score=r["score"].get("total_score"),
                    wyckoff=r.get("regime", {}).get("state"),
                    cmf_pctl=r.get("indicators", {}).get("cmf_pctl"),
                    vol_ratio=r.get("indicators", {}).get("anomaly_ratio"),
                    hype=r.get("hype_score", {}).get("hype_index", 0),
                    divergences=divs or None,
                    was_journaled=False,
                )
                session.add(cand)
                saved += 1
            except Exception as e:
                logger.warning(f"save_scan_candidate failed for {r.get('symbol')}: {e}")
        await session.commit()
    return saved


async def mark_candidate_journaled(symbol: str) -> None:
    """Mark today's scan candidate as journaled when user adds it to journal."""
    from datetime import date as date_type
    today = date_type.today()
    async with get_session_factory()() as session:
        result = await session.execute(
            select(ScanCandidate).where(
                ScanCandidate.symbol == symbol.upper(),
                ScanCandidate.scan_date == today,
            )
        )
        cand = result.scalar_one_or_none()
        if cand:
            cand.was_journaled = True
            await session.commit()


async def get_candidates_missed() -> dict:
    """Return candidates that were not journaled and their outcome over 5d/10d/20d."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(ScanCandidate).order_by(ScanCandidate.scan_date.desc())
        )
        candidates = result.scalars().all()
    rows = [_candidate_to_dict(c) for c in candidates]
    total = len(rows)
    journaled = sum(1 for c in rows if c["was_journaled"])
    not_journaled = [c for c in rows if not c["was_journaled"] and c["pct_5d"] is not None]
    went_up_10 = sum(1 for c in not_journaled if (c["pct_5d"] or 0) >= 10)
    went_down_5 = sum(1 for c in not_journaled if (c["pct_5d"] or 0) <= -5)
    filter_accuracy = round(went_down_5 / len(not_journaled), 2) if not_journaled else 0
    return {
        "total_fire_arm_scanned": total,
        "journaled": journaled,
        "not_journaled_went_up_10pct": went_up_10,
        "not_journaled_went_down_5pct": went_down_5,
        "filter_accuracy": filter_accuracy,
        "recent": rows[:50],
    }


async def get_candidates_summary() -> list:
    """Return aggregate stats by tier for scan candidates."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(ScanCandidate).where(ScanCandidate.pct_5d.isnot(None))
        )
        candidates = result.scalars().all()
    by_tier: dict = {}
    for c in candidates:
        t = c.tier or "UNKNOWN"
        by_tier.setdefault(t, {"count": 0, "up_5d": 0, "avg_5d": 0.0, "sum_5d": 0.0})
        by_tier[t]["count"] += 1
        by_tier[t]["sum_5d"] += c.pct_5d or 0
        if (c.pct_5d or 0) > 0:
            by_tier[t]["up_5d"] += 1
    return [
        {
            "tier": t,
            "count": v["count"],
            "up_rate_5d": round(v["up_5d"] / v["count"], 2) if v["count"] else 0,
            "avg_pct_5d": round(v["sum_5d"] / v["count"], 2) if v["count"] else 0,
        }
        for t, v in by_tier.items()
    ]


async def get_recent_fire_arm_symbols(days: int = 7) -> list[str]:
    """Return distinct symbols from FIRE/ARM scan candidates in the last N days
    where pct_5d is still NULL (outcome not yet known — still worth watching)."""
    from datetime import date as _date, timedelta
    since = _date.today() - timedelta(days=days)
    async with get_session_factory()() as session:
        result = await session.execute(
            select(ScanCandidate.symbol)
            .where(ScanCandidate.scan_date >= since)
            .where(ScanCandidate.tier.in_(["FIRE", "ARM"]))
            .where(ScanCandidate.pct_5d.is_(None))
            .distinct()
        )
        return [row[0] for row in result.all()]


# ─── Position Snapshots ───────────────────────────────────────────────────────

async def save_position_snapshot(journal_id: int, day_number: int, price: float,
                                  pct_from_entry: float, spy_daily_pct: float) -> None:
    from datetime import date as date_type
    today = date_type.today()
    async with get_session_factory()() as session:
        snap = PositionSnapshot(
            journal_id=journal_id,
            snapshot_date=today,
            day_number=day_number,
            price=price,
            pct_from_entry=pct_from_entry,
            spy_daily_pct=spy_daily_pct,
        )
        session.add(snap)
        await session.commit()


async def get_position_snapshots(journal_id: int) -> List[dict]:
    async with get_session_factory()() as session:
        result = await session.execute(
            select(PositionSnapshot)
            .where(PositionSnapshot.journal_id == journal_id)
            .order_by(PositionSnapshot.day_number.asc())
        )
        snaps = result.scalars().all()
    return [
        {
            "day_number": s.day_number,
            "snapshot_date": s.snapshot_date.isoformat() if s.snapshot_date else None,
            "price": s.price,
            "pct_from_entry": s.pct_from_entry,
            "spy_daily_pct": s.spy_daily_pct,
        }
        for s in snaps
    ]


async def get_spy_cumulative_for_entry(journal_id: int) -> float:
    """Sum all spy_daily_pct snapshots for a journal entry."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(PositionSnapshot.spy_daily_pct).where(PositionSnapshot.journal_id == journal_id)
        )
        rows = result.scalars().all()
    return sum(r or 0 for r in rows)


async def get_max_gain_day(journal_id: int) -> Optional[int]:
    """Return day_number of the highest pct_from_entry snapshot."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(PositionSnapshot)
            .where(PositionSnapshot.journal_id == journal_id)
            .order_by(PositionSnapshot.pct_from_entry.desc())
            .limit(1)
        )
        snap = result.scalar_one_or_none()
    return snap.day_number if snap else None


# ─── Deep Analytics ───────────────────────────────────────────────────────────

async def get_deep_analytics() -> dict:
    """Full analytics breakdown: by signal, timing, alpha, missed opportunities."""
    entries = await get_journal()
    closed = [e for e in entries if e.get("outcome") in ("win", "loss")]
    if not closed:
        return {"message": "No closed trades yet"}

    def win_rate(group):
        wins = sum(1 for e in group if e["outcome"] == "win")
        return round(wins / len(group), 2) if group else 0

    def avg_return(group):
        vals = [e.get("final_pnl_pct") or e.get("gain_pct") or 0 for e in group]
        return round(sum(vals) / len(vals), 2) if vals else 0

    def avg_alpha(group):
        vals = [e.get("alpha_pct") or 0 for e in group]
        return round(sum(vals) / len(vals), 2) if vals else 0

    # By Wyckoff
    wyckoff_groups: dict = {}
    for e in closed:
        k = e.get("entry_wyckoff") or "UNKNOWN"
        wyckoff_groups.setdefault(k, []).append(e)
    by_wyckoff = [
        {"state": k, "count": len(v), "win_rate": win_rate(v),
         "avg_return": avg_return(v), "avg_alpha": avg_alpha(v)}
        for k, v in sorted(wyckoff_groups.items(), key=lambda x: -len(x[1]))
    ]

    # By CMF bucket
    cmf_buckets = [
        (">90%ile", lambda e: (e.get("entry_cmf_pctl") or 0) > 90),
        ("70-90%ile", lambda e: 70 < (e.get("entry_cmf_pctl") or 0) <= 90),
        ("50-70%ile", lambda e: 50 < (e.get("entry_cmf_pctl") or 0) <= 70),
        ("<50%ile", lambda e: (e.get("entry_cmf_pctl") or 0) <= 50),
    ]
    by_cmf = []
    for label, fn in cmf_buckets:
        g = [e for e in closed if fn(e)]
        if g:
            by_cmf.append({"bucket": label, "count": len(g), "win_rate": win_rate(g), "avg_return": avg_return(g)})

    # By Hype bucket
    hype_buckets = [
        ("<20", lambda e: (e.get("entry_hype") or 0) < 20),
        ("20-40", lambda e: 20 <= (e.get("entry_hype") or 0) < 40),
        ("40-60", lambda e: 40 <= (e.get("entry_hype") or 0) < 60),
        (">60", lambda e: (e.get("entry_hype") or 0) >= 60),
    ]
    by_hype = []
    for label, fn in hype_buckets:
        g = [e for e in closed if fn(e)]
        if g:
            by_hype.append({"bucket": label, "count": len(g), "win_rate": win_rate(g), "avg_return": avg_return(g)})

    # By Tier
    tier_groups: dict = {}
    for e in closed:
        k = e.get("tier") or "UNKNOWN"
        tier_groups.setdefault(k, []).append(e)
    by_tier = [
        {"tier": k, "count": len(v), "win_rate": win_rate(v), "avg_return": avg_return(v)}
        for k, v in sorted(tier_groups.items(), key=lambda x: -len(x[1]))
    ]

    # Timing
    hold_days = [e.get("days_held") or 0 for e in closed]
    max_gain_days = [e.get("max_gain_day") for e in closed if e.get("max_gain_day")]
    missed = [e.get("missed_exit_pct") or 0 for e in closed]
    avg_hold = round(sum(hold_days) / len(hold_days), 1) if hold_days else 0
    avg_max_gain_day = round(sum(max_gain_days) / len(max_gain_days), 1) if max_gain_days else 0
    avg_missed = round(sum(missed) / len(missed), 2) if missed else 0
    suggested_hold = int(avg_max_gain_day) if avg_max_gain_day else None
    exit_too_late = sum(1 for e in closed if (e.get("missed_exit_pct") or 0) > 3)
    exit_too_early = sum(1 for e in closed if (e.get("days_held") or 0) < (avg_max_gain_day or 999))

    # Alpha
    alpha_vals = [e.get("alpha_pct") for e in closed if e.get("alpha_pct") is not None]
    avg_alpha_val = round(sum(alpha_vals) / len(alpha_vals), 2) if alpha_vals else 0
    positive_alpha = sum(1 for a in alpha_vals if a > 0)
    positive_alpha_rate = round(positive_alpha / len(alpha_vals), 2) if alpha_vals else 0

    # Missed opportunities (from scan_candidates)
    try:
        missed_opp = await get_candidates_missed()
    except Exception:
        missed_opp = {}

    return {
        "signal_performance": {
            "by_wyckoff": by_wyckoff,
            "by_cmf_bucket": by_cmf,
            "by_hype_bucket": by_hype,
            "by_tier": by_tier,
        },
        "timing": {
            "avg_max_gain_day": avg_max_gain_day,
            "avg_days_held": avg_hold,
            "avg_missed_exit_pct": avg_missed,
            "suggested_hold_days": suggested_hold,
            "exit_too_late_count": exit_too_late,
            "exit_too_early_count": exit_too_early,
        },
        "alpha": {
            "avg_alpha_vs_spy": avg_alpha_val,
            "positive_alpha_rate": positive_alpha_rate,
        },
        "missed_opportunities": missed_opp,
        "total_closed": len(closed),
    }


# ─── EOD Log ──────────────────────────────────────────────────────────────────

async def save_eod_log(log_date: str, content: str) -> None:
    """Upsert an end-of-day log for the given date (YYYY-MM-DD)."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(EodLog).where(EodLog.log_date == log_date)
        )
        existing = result.scalar_one_or_none()
        if existing:
            existing.content = content
            existing.generated_at = datetime.utcnow()
        else:
            session.add(EodLog(log_date=log_date, content=content))
        await session.commit()


async def get_eod_log(log_date: str) -> Optional[dict]:
    """Return EOD log for a given date, or None."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(EodLog).where(EodLog.log_date == log_date)
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        return {"log_date": row.log_date, "content": row.content, "generated_at": row.generated_at.isoformat()}


async def get_latest_eod_log() -> Optional[dict]:
    """Return the most recent EOD log."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(EodLog).order_by(EodLog.log_date.desc()).limit(1)
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        return {"log_date": row.log_date, "content": row.content, "generated_at": row.generated_at.isoformat()}


# ─── Market Regime ─────────────────────────────────────────────────────────────

async def save_market_regime(data: dict) -> None:
    """Upsert today's market regime record."""
    from datetime import date as _date
    today = _date.today()
    async with get_session_factory()() as session:
        result = await session.execute(
            select(MarketRegime).where(MarketRegime.date == today)
        )
        row = result.scalar_one_or_none()
        strong = ",".join(data.get("strong_sectors", []))
        weak = ",".join(data.get("weak_sectors", []))
        etf_json = json.dumps(data.get("etf_details", {}))

        if row:
            row.regime = data["regime"]
            row.spy_pct = data.get("spy_pct")
            row.qqq_pct = data.get("qqq_pct")
            row.xle_pct = data.get("xle_pct")
            row.xlv_pct = data.get("xlv_pct")
            row.xlu_pct = data.get("xlu_pct")
            row.gld_pct = data.get("gld_pct")
            row.spy_vs_ema20 = data.get("spy_vs_ema20")
            row.qqq_vs_ema20 = data.get("qqq_vs_ema20")
            row.strong_sectors = strong
            row.weak_sectors = weak
            row.recommendation = data.get("recommendation")
            row.etf_details_json = etf_json
        else:
            session.add(MarketRegime(
                date=today,
                regime=data["regime"],
                spy_pct=data.get("spy_pct"),
                qqq_pct=data.get("qqq_pct"),
                xle_pct=data.get("xle_pct"),
                xlv_pct=data.get("xlv_pct"),
                xlu_pct=data.get("xlu_pct"),
                gld_pct=data.get("gld_pct"),
                spy_vs_ema20=data.get("spy_vs_ema20"),
                qqq_vs_ema20=data.get("qqq_vs_ema20"),
                strong_sectors=strong,
                weak_sectors=weak,
                recommendation=data.get("recommendation"),
                etf_details_json=etf_json,
            ))
        await session.commit()


def _regime_row_to_dict(row: MarketRegime) -> dict:
    strong = [s for s in (row.strong_sectors or "").split(",") if s]
    weak = [s for s in (row.weak_sectors or "").split(",") if s]
    etf = {}
    try:
        etf = json.loads(row.etf_details_json or "{}")
    except Exception:
        pass
    return {
        "date": row.date.isoformat() if row.date else None,
        "regime": row.regime,
        "spy_pct": row.spy_pct,
        "qqq_pct": row.qqq_pct,
        "xle_pct": row.xle_pct,
        "xlv_pct": row.xlv_pct,
        "xlu_pct": row.xlu_pct,
        "gld_pct": row.gld_pct,
        "spy_vs_ema20": row.spy_vs_ema20,
        "qqq_vs_ema20": row.qqq_vs_ema20,
        "strong_sectors": strong,
        "weak_sectors": weak,
        "recommendation": row.recommendation,
        "etf_details": etf,
    }


async def get_market_regime_latest() -> Optional[dict]:
    """Return the most recent market regime record."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(MarketRegime).order_by(MarketRegime.date.desc()).limit(1)
        )
        row = result.scalar_one_or_none()
        return _regime_row_to_dict(row) if row else None


async def get_market_regime_history(days: int = 30) -> List[dict]:
    """Return market regime records for the last N days."""
    from datetime import date as _date, timedelta
    since = _date.today() - timedelta(days=days)
    async with get_session_factory()() as session:
        result = await session.execute(
            select(MarketRegime)
            .where(MarketRegime.date >= since)
            .order_by(MarketRegime.date.desc())
        )
        rows = result.scalars().all()
        return [_regime_row_to_dict(r) for r in rows]


# ─── Sector Strength ───────────────────────────────────────────────────────────

async def save_sector_strength(data: dict) -> None:
    """Upsert today's sector strength records (one row per sector)."""
    from datetime import date as _date
    today = _date.today()
    async with get_session_factory()() as session:
        for sector, info in data.items():
            result = await session.execute(
                select(SectorStrength).where(
                    SectorStrength.date == today,
                    SectorStrength.sector == sector,
                )
            )
            row = result.scalar_one_or_none()
            tickers_json = json.dumps(info.get("tickers", []))
            if row:
                row.avg_score = info.get("avg_score")
                row.avg_cmf_pctl = info.get("avg_cmf_pctl")
                row.avg_vol_ratio = info.get("avg_vol_ratio")
                row.ticker_count = info.get("ticker_count")
                row.leader_symbol = info.get("leader_symbol")
                row.leader_score = info.get("leader_score")
                row.momentum_pct = info.get("momentum_pct")
                row.tickers_json = tickers_json
            else:
                session.add(SectorStrength(
                    date=today,
                    sector=sector,
                    avg_score=info.get("avg_score"),
                    avg_cmf_pctl=info.get("avg_cmf_pctl"),
                    avg_vol_ratio=info.get("avg_vol_ratio"),
                    ticker_count=info.get("ticker_count"),
                    leader_symbol=info.get("leader_symbol"),
                    leader_score=info.get("leader_score"),
                    momentum_pct=info.get("momentum_pct"),
                    tickers_json=tickers_json,
                ))
        await session.commit()


def _strength_row_to_dict(row: SectorStrength) -> dict:
    tickers = []
    try:
        tickers = json.loads(row.tickers_json or "[]")
    except Exception:
        pass
    return {
        "sector": row.sector,
        "date": row.date.isoformat() if row.date else None,
        "avg_score": row.avg_score,
        "avg_cmf_pctl": row.avg_cmf_pctl,
        "avg_vol_ratio": row.avg_vol_ratio,
        "ticker_count": row.ticker_count,
        "leader_symbol": row.leader_symbol,
        "leader_score": row.leader_score,
        "momentum_pct": row.momentum_pct,
        "tickers": tickers,
    }


async def get_sector_strength_latest() -> dict:
    """Return today's (or most recent) sector strength as {sector: dict}."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(SectorStrength.date).order_by(SectorStrength.date.desc()).limit(1)
        )
        latest_date = result.scalar_one_or_none()
        if not latest_date:
            return {}

        result2 = await session.execute(
            select(SectorStrength).where(SectorStrength.date == latest_date)
        )
        rows = result2.scalars().all()
        return {r.sector: _strength_row_to_dict(r) for r in rows}


async def get_sector_strength_for_sector(sector: str) -> Optional[dict]:
    """Return the most recent strength record for a specific sector."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(SectorStrength)
            .where(SectorStrength.sector == sector)
            .order_by(SectorStrength.date.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        return _strength_row_to_dict(row) if row else None
