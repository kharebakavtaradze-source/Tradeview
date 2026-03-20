"""
Database layer using SQLAlchemy async with PostgreSQL (asyncpg).
Railway provides DATABASE_URL automatically.
"""
import json
import logging
import os
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import Column, DateTime, Integer, String, Text, select
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
