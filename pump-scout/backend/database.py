"""
Database layer using SQLAlchemy async with PostgreSQL (asyncpg).
Railway provides DATABASE_URL automatically.
"""
import json
import logging
import os
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, select, text
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
