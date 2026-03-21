"""
Database layer using SQLAlchemy async with PostgreSQL (asyncpg).
Railway provides DATABASE_URL automatically.
"""
import json
import logging
import os
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import Column, DateTime, Float, Integer, String, Text, select
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

# Engine creation — defer to first use
_engine = None
_async_session = None


def get_engine():
    global _engine
    if _engine is None:
        connect_args = {}
        if "sqlite" in DATABASE_URL:
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
    entry_price = Column(Float, nullable=False)
    entry_date = Column(String(20), nullable=False)
    exit_price = Column(Float, nullable=True)
    exit_date = Column(String(20), nullable=True)
    tier = Column(String(20), nullable=True)
    score = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    outcome = Column(String(20), default="open")   # win / loss / open / skip
    gain_pct = Column(Float, nullable=True)        # auto-calculated on save
    indicators_snapshot = Column(Text, nullable=True)  # JSON
    ai_analysis = Column(Text, nullable=True)
    tags = Column(Text, nullable=True)             # JSON array


async def init_db():
    """Create tables if they don't exist."""
    try:
        async with get_engine().begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise


async def save_scan(data: dict) -> int:
    """Persist a scan result to the database. Returns the scan ID."""
    results = data.get("results", [])
    # Strip candles from storage to reduce size
    slim_results = []
    for r in results:
        slim = {k: v for k, v in r.items() if k != "candles"}
        slim_results.append(slim)

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
        logger.info(f"Saved scan #{scan.id} with {scan.total_tickers} tickers")
        return scan.id


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


# ─── Journal ─────────────────────────────────────────────────────────────────

def _journal_to_dict(j: Journal) -> dict:
    return {
        "id": j.id,
        "symbol": j.symbol,
        "added_at": j.added_at.isoformat() if j.added_at else None,
        "entry_price": j.entry_price,
        "entry_date": j.entry_date,
        "exit_price": j.exit_price,
        "exit_date": j.exit_date,
        "tier": j.tier,
        "score": j.score,
        "notes": j.notes,
        "outcome": j.outcome,
        "gain_pct": j.gain_pct,
        "indicators_snapshot": json.loads(j.indicators_snapshot) if j.indicators_snapshot else None,
        "ai_analysis": j.ai_analysis,
        "tags": json.loads(j.tags) if j.tags else [],
    }


def _calc_gain_pct(entry_price, exit_price) -> Optional[float]:
    if entry_price and exit_price and entry_price > 0:
        return round((exit_price - entry_price) / entry_price * 100, 2)
    return None


async def get_journal() -> List[dict]:
    async with get_session_factory()() as session:
        result = await session.execute(select(Journal).order_by(Journal.added_at.desc()))
        items = result.scalars().all()
    return [_journal_to_dict(j) for j in items]


async def add_journal_entry(data: dict) -> dict:
    gain = _calc_gain_pct(data.get("entry_price"), data.get("exit_price"))
    async with get_session_factory()() as session:
        entry = Journal(
            symbol=data["symbol"].upper(),
            entry_price=data["entry_price"],
            entry_date=data.get("entry_date", datetime.utcnow().strftime("%Y-%m-%d")),
            exit_price=data.get("exit_price"),
            exit_date=data.get("exit_date"),
            tier=data.get("tier"),
            score=data.get("score"),
            notes=data.get("notes"),
            outcome=data.get("outcome", "open"),
            gain_pct=gain,
            indicators_snapshot=json.dumps(data["indicators_snapshot"]) if data.get("indicators_snapshot") else None,
            ai_analysis=data.get("ai_analysis"),
            tags=json.dumps(data.get("tags", [])),
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
        for field in ("exit_price", "exit_date", "notes", "outcome", "tier", "score", "ai_analysis"):
            if field in data:
                setattr(entry, field, data[field])
        if "tags" in data:
            entry.tags = json.dumps(data["tags"])
        entry.gain_pct = _calc_gain_pct(entry.entry_price, entry.exit_price)
        await session.commit()
        await session.refresh(entry)
    return _journal_to_dict(entry)


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
