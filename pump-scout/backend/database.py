"""
Database layer using SQLAlchemy async with PostgreSQL (asyncpg).
Railway provides DATABASE_URL automatically.
"""
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from typing import List, Optional

from sqlalchemy import BigInteger, Boolean, Column, Date, DateTime, Float, Integer, String, Text, UniqueConstraint, func, select, text
from sqlalchemy.exc import IntegrityError
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

if _IS_SQLITE:
    # Hard-fail in Railway/production environments — SQLite loses all data on restart
    if os.getenv("RAILWAY_ENVIRONMENT"):
        logger.critical(
            "FATAL: Running on Railway without DATABASE_URL set. "
            "Add a PostgreSQL plugin or set DATABASE_URL in Railway Variables. "
            "Refusing to start with SQLite on a deployed environment."
        )
        sys.exit(1)
    logger.warning(
        "⚠️  DATABASE_URL not set — using SQLite fallback (pump_scout.db). "
        "ALL DATA WILL BE LOST ON RESTART/DEPLOY. "
        "Set DATABASE_URL to a PostgreSQL connection string for persistence."
    )
else:
    logger.info("Database: PostgreSQL (persistent)")

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

    id            = Column(Integer, primary_key=True, index=True)
    scanned_at    = Column(DateTime, default=datetime.utcnow, index=True)
    total_tickers = Column(Integer, default=0)
    results_json  = Column(Text, nullable=False)
    scan_type     = Column(String(30), nullable=True, index=True)  # 'massive_eod' | 'yahoo_intraday'


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
    # ── New Pump source tracking (v14+) ──────────────────────────────────────
    source      = Column(String(20), nullable=True)  # "scanner" | "new_pump"
    signal_date = Column(String(10), nullable=True)  # YYYY-MM-DD of signal bar
    np_sequence = Column(String(40), nullable=True)  # e.g. "FULL_FRI34_G4_B2"


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
    vol_score = Column(Float, nullable=True)
    accum_score = Column(Float, nullable=True)
    quiet_factor = Column(Float, nullable=True)
    inst_bonus = Column(Float, nullable=True)
    original_score = Column(Float, nullable=True)
    original_tier = Column(String(10), nullable=True)
    downgrade_reason = Column(String(30), nullable=True)


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


class JournalSettings(Base):
    """Per-user journal configuration (single-row table)."""
    __tablename__ = "journal_settings"

    id              = Column(Integer, primary_key=True, index=True)
    starting_balance = Column(Float, default=2000.0, nullable=False)
    updated_at      = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


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
    current_price = Column(Float, nullable=True)     # latest fetched price
    price_updated_at = Column(DateTime, nullable=True)  # when current_price was last fetched
    pnl_usd = Column(Float, default=0)
    pnl_pct = Column(Float, default=0)
    max_gain_pct = Column(Float, default=0)          # peak P&L since entry
    max_loss_pct = Column(Float, default=0)          # worst P&L since entry
    stop_loss = Column(Float, nullable=True)         # ATR-based stop price
    target_price = Column(Float, nullable=True)      # TP1 — first target, partial exit here
    target_price_2 = Column(Float, nullable=True)    # TP2 — second target, exit remainder
    sell_pct_at_target_1 = Column(Integer, default=50)  # % to sell at TP1 (default 50%)
    tp1_hit = Column(Boolean, default=False)         # True after partial exit at TP1
    status = Column(String(10), default="OPEN")      # OPEN / CLOSED
    exit_reason = Column(String(20), nullable=True)  # ATR_STOP / TARGET_HIT / TARGET2_HIT / AI_SELL / CEF_FILTER
    reason = Column(Text, nullable=True)
    scan_data = Column(Text, nullable=True)          # JSON
    exit_date = Column(DateTime, nullable=True)
    days_held = Column(Integer, default=0)
    source = Column(String(20), nullable=True)       # "scanner" | "new_pump"


class AIPortfolioState(Base):
    __tablename__ = "ai_portfolio_state"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(String(10), unique=True, nullable=False, index=True)  # YYYY-MM-DD
    total_value = Column(Float, default=2000.0)
    cash = Column(Float, default=2000.0)
    invested = Column(Float, default=0)
    total_pnl_pct = Column(Float, default=0)
    baseline_value = Column(Float, default=2000.0)  # starting capital for P&L %
    decisions_json = Column(Text, nullable=True)   # JSON
    daily_report = Column(Text, nullable=True)     # JSON


class AIJournalPosition(Base):
    """Virtual position in the $500 AI Trading Journal account."""
    __tablename__ = "ai_journal_position"

    id             = Column(Integer, primary_key=True)
    symbol         = Column(String(10), nullable=False, index=True)
    entry_date     = Column(DateTime, default=datetime.utcnow)
    entry_price    = Column(Float, nullable=False)
    shares         = Column(Float, nullable=False)
    cost_basis     = Column(Float, nullable=False)
    target_price   = Column(Float, nullable=True)
    stop_price     = Column(Float, nullable=True)
    entry_rationale = Column(Text, nullable=True)
    status         = Column(String(10), default="OPEN")    # OPEN / CLOSED
    exit_date      = Column(DateTime, nullable=True)
    exit_price     = Column(Float, nullable=True)
    pnl_usd        = Column(Float, default=0.0)
    pnl_pct        = Column(Float, default=0.0)
    exit_reason    = Column(String(50), nullable=True)
    scan_tier      = Column(String(20), nullable=True)
    scan_score     = Column(Float, nullable=True)
    ats_signal     = Column(String(20), nullable=True)
    current_price      = Column(Float, nullable=True)
    current_value      = Column(Float, nullable=True)
    readiness_tier     = Column(String(10), nullable=True)
    confluence_signals = Column(Text, nullable=True)


class AIJournalEntry(Base):
    """A journal entry written by the AI after each review session."""
    __tablename__ = "ai_journal_entry"

    id               = Column(Integer, primary_key=True)
    created_at       = Column(DateTime, default=datetime.utcnow)
    journal_text     = Column(Text, nullable=False)
    strategy_notes   = Column(Text, nullable=True)
    capital_before   = Column(Float, nullable=False)
    capital_after    = Column(Float, nullable=False)
    positions_opened = Column(Integer, default=0)
    positions_closed = Column(Integer, default=0)
    decisions_json   = Column(Text, nullable=True)   # JSON array of decision objects


class AIJournalState(Base):
    """Single-row state for the AI Journal virtual account."""
    __tablename__ = "ai_journal_state"

    id               = Column(Integer, primary_key=True)
    capital          = Column(Float, default=500.0)
    starting_capital = Column(Float, default=500.0)
    updated_at       = Column(DateTime, default=datetime.utcnow)
    learned_strategy = Column(Text, nullable=True)   # JSON — evolves over sessions


class AISignalOutcome(Base):
    """Every PRIME_BUY / HIGH_CONF_BUY signal — tracked for 3/7/14-day forward returns."""
    __tablename__ = "ai_signal_outcome"
    __table_args__ = (UniqueConstraint("symbol", "signal_date", name="uq_signal_outcome"),)

    id              = Column(Integer, primary_key=True)
    symbol          = Column(String(10), nullable=False, index=True)
    signal_date     = Column(Date, nullable=False, index=True)
    tier            = Column(String(20), nullable=False)
    score           = Column(Float, nullable=True)
    ats_signal      = Column(String(20), nullable=True)
    readiness_tier  = Column(String(10), nullable=True)
    flow_signals    = Column(Text, nullable=True)    # JSON list
    flow_risks      = Column(Text, nullable=True)    # JSON list
    risk_flags      = Column(Text, nullable=True)    # JSON list
    price_at_signal = Column(Float, nullable=True)
    price_3d        = Column(Float, nullable=True)
    price_7d        = Column(Float, nullable=True)
    price_14d       = Column(Float, nullable=True)
    gain_3d         = Column(Float, nullable=True)   # % gain at day 3
    gain_7d         = Column(Float, nullable=True)
    gain_14d        = Column(Float, nullable=True)
    max_gain_14d    = Column(Float, nullable=True)   # best % gain within 14d window
    outcome_label   = Column(String(20), nullable=True)  # WIN_STRONG|WIN|FLAT|LOSS
    backfilled_at   = Column(DateTime, nullable=True)
    recorded_at     = Column(DateTime, default=datetime.utcnow)


class AIPatternMemory(Base):
    """Persisted pattern stats — what signal combos work or fail."""
    __tablename__ = "ai_pattern_memory"

    id            = Column(Integer, primary_key=True)
    pattern_key   = Column(String(120), nullable=False, unique=True, index=True)
    updated_at    = Column(DateTime, default=datetime.utcnow)
    n_trades      = Column(Integer, default=0)
    n_wins        = Column(Integer, default=0)
    win_rate      = Column(Float, default=0.0)
    avg_win_pct   = Column(Float, nullable=True)
    avg_loss_pct  = Column(Float, nullable=True)
    avg_hold_days = Column(Float, nullable=True)
    best_trade    = Column(Text, nullable=True)    # JSON
    notes         = Column(Text, nullable=True)    # AI's written insight


class TradeLesson(Base):
    """AI-generated structured lesson from each closed trade."""
    __tablename__ = "ai_trade_lesson"

    id            = Column(Integer, primary_key=True)
    created_at    = Column(DateTime, default=datetime.utcnow)
    position_id   = Column(Integer, nullable=True, index=True)
    symbol        = Column(String(10), nullable=False, index=True)
    pnl_pct       = Column(Float, nullable=True)
    exit_reason   = Column(String(50), nullable=True)
    scan_tier     = Column(String(20), nullable=True)
    ats_signal    = Column(String(20), nullable=True)
    readiness_tier = Column(String(10), nullable=True)
    flow_signals  = Column(Text, nullable=True)   # JSON list
    what_worked   = Column(Text, nullable=True)
    what_failed   = Column(Text, nullable=True)
    lesson        = Column(Text, nullable=True)   # 1-sentence key takeaway
    confidence    = Column(String(10), nullable=True)   # HIGH|MEDIUM|LOW
    tags          = Column(Text, nullable=True)   # JSON list


class SignalBlacklist(Base):
    """Patterns the AI has decided to avoid based on repeated failures."""
    __tablename__ = "ai_signal_blacklist"

    id              = Column(Integer, primary_key=True)
    pattern_key     = Column(String(120), nullable=False, unique=True, index=True)
    reason          = Column(Text, nullable=True)
    n_failures      = Column(Integer, default=1)
    suspended_until = Column(DateTime, nullable=True)   # None = permanent block
    created_at      = Column(DateTime, default=datetime.utcnow)
    updated_at      = Column(DateTime, default=datetime.utcnow)


class SectorCache(Base):
    """Persistent sector cache — avoids repeated Yahoo Finance / Massive API calls."""
    __tablename__ = "sector_cache"

    symbol           = Column(String(20), primary_key=True, index=True)
    sector           = Column(String(100), nullable=False)
    industry         = Column(String(100), nullable=True)
    market_cap       = Column(BigInteger, nullable=True)
    massive_fetched  = Column(Boolean, default=False, nullable=False)
    massive_fetched_at = Column(DateTime, nullable=True)
    fetched_at       = Column(DateTime, default=datetime.utcnow)


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


class PatternStreak(Base):
    """Multi-day pattern streaks — tracks consecutive scan appearances for ARM+ tickers."""
    __tablename__ = "pattern_streaks"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(10), nullable=False, unique=True, index=True)
    streak_start = Column(Date, nullable=False)
    streak_days = Column(Integer, default=1)
    avg_score = Column(Float, default=0)
    avg_cmf_pctl = Column(Float, default=0)
    avg_vol_ratio = Column(Float, default=0)
    avg_hype = Column(Integer, default=0)
    tier = Column(String(20), nullable=True)
    wyckoff = Column(String(30), nullable=True)
    last_seen = Column(Date, nullable=False)
    alerted = Column(Integer, default=0)   # bitmask: bit0=day3 sent, bit1=day5 sent


class RibbonCandidate(Base):
    """
    EMA ribbon secondary pass — analytical discovery only.
    Captures liquid compression setups that lack the volume anomaly (>= 2x)
    required by the main scan pipeline.  Three intraday upserts overwrite the
    same (scan_date, symbol) row so only the freshest snapshot is kept.
    """
    __tablename__ = "ribbon_candidates"
    __table_args__ = (UniqueConstraint("scan_date", "symbol", name="uq_ribbon_date_symbol"),)

    id          = Column(Integer, primary_key=True, index=True)
    scan_date   = Column(Date, nullable=False, index=True)
    symbol      = Column(String(10), nullable=False, index=True)
    price       = Column(Float, nullable=True)
    today_vol   = Column(Integer, nullable=True)
    anomaly_ratio          = Column(Float, nullable=True)
    ema8        = Column(Float, nullable=True)
    ema13       = Column(Float, nullable=True)
    ema20       = Column(Float, nullable=True)
    ema21       = Column(Float, nullable=True)
    ema34       = Column(Float, nullable=True)
    ema50       = Column(Float, nullable=True)
    ema55       = Column(Float, nullable=True)
    ema89       = Column(Float, nullable=True)
    ema200      = Column(Float, nullable=True)
    ema_spread_pct         = Column(Float, nullable=True)
    ribbon_compression     = Column(String(10), nullable=True)
    bullish_stack          = Column(Boolean, default=False)
    bearish_stack          = Column(Boolean, default=False)
    compression_and_bullish = Column(Boolean, default=False)
    ribbon_position        = Column(Float, nullable=True)
    ema8_slope             = Column(String(10), nullable=True)
    cmf_pctl    = Column(Float, nullable=True)
    rsi         = Column(Float, nullable=True)
    bb_sqz_bars = Column(Integer, default=0)
    bb_squeeze  = Column(Boolean, default=False)
    obv_strength = Column(String(10), nullable=True)
    rs_score    = Column(Float, default=0)
    sector      = Column(String(50), nullable=True)
    scanned_at  = Column(DateTime, default=datetime.utcnow)


class MacroEventBias(Base):
    """
    Trump News Event Bias Layer — Version Alpha.
    Read-only contextual intelligence. Never affects scores/tiers/rankings.
    One row per unique event_id (SHA1 of title+date). Idempotent upsert.
    """
    __tablename__ = "macro_event_bias"

    id               = Column(Integer, primary_key=True, index=True)
    event_id         = Column(String(12), unique=True, nullable=False, index=True)  # SHA1[:12]
    title            = Column(Text, nullable=False)
    source_url       = Column(Text, nullable=True)
    published_at     = Column(DateTime, nullable=False, index=True)
    fetched_at       = Column(DateTime, default=datetime.utcnow)
    relevance_score  = Column(Integer, nullable=False)       # 0–100
    event_classes    = Column(Text, nullable=True)           # JSON list
    primary_class    = Column(String(40), nullable=False, index=True)
    market_bias      = Column(String(20), nullable=False)    # BULLISH/BEARISH/RISK_OFF/MIXED/NEUTRAL
    time_horizon     = Column(String(10), nullable=True)     # SHORT/MEDIUM/LONG
    confidence       = Column(Integer, nullable=True)        # 0–100
    surprise_level   = Column(Integer, nullable=True)        # 0–100
    volatility_bias  = Column(String(10), nullable=True)     # LOW/MEDIUM/HIGH/VERY_HIGH
    oil_bias         = Column(String(10), nullable=True)     # BULLISH/BEARISH/NEUTRAL
    rates_bias       = Column(String(10), nullable=True)     # BULLISH/BEARISH/NEUTRAL
    dollar_bias      = Column(String(10), nullable=True)     # BULLISH/BEARISH/NEUTRAL
    bullish_sectors  = Column(Text, nullable=True)           # JSON list
    bearish_sectors  = Column(Text, nullable=True)           # JSON list
    bullish_industries = Column(Text, nullable=True)         # JSON list
    bearish_industries = Column(Text, nullable=True)         # JSON list
    is_active        = Column(Boolean, default=True)         # still within time_horizon


class UniverseCache(Base):
    """
    Nightly Massive reference snapshot — one row per active US common stock.
    Populated by scanner.massive_reference.sync_universe_cache().
    Provides SIC codes and company metadata for sector resolution fallback.
    """
    __tablename__ = "universe_cache"

    symbol                      = Column(String(10),  primary_key=True, index=True)
    name                        = Column(String(200), nullable=True)
    active                      = Column(Boolean,     default=True, nullable=False)
    market                      = Column(String(20),  nullable=True)
    type                        = Column(String(20),  nullable=True)   # CS / ADR / ADRC
    primary_exchange            = Column(String(20),  nullable=True)
    cik                         = Column(String(20),  nullable=True)
    sic_code                    = Column(Integer,     nullable=True, index=True)
    sic_description             = Column(String(200), nullable=True)
    market_cap                  = Column(BigInteger,  nullable=True)
    list_date                   = Column(String(10),  nullable=True)
    shares_outstanding          = Column(BigInteger,  nullable=True)
    weighted_shares_outstanding = Column(BigInteger,  nullable=True)
    last_synced_at              = Column(DateTime,    nullable=True, index=True)


class StockSplitCache(Base):
    """
    Corporate action split history — persisted from Massive /v3/reference/splits.
    Used by Raw Pattern Study split-impact analysis.
    """
    __tablename__ = "stock_split_cache"

    id                = Column(Integer,  primary_key=True)
    symbol            = Column(String(20), nullable=False, index=True)
    execution_date    = Column(String(10), nullable=False, index=True)
    split_from        = Column(Integer,  nullable=False)
    split_to          = Column(Integer,  nullable=False)
    ratio             = Column(Float,    nullable=True)   # split_to / split_from
    split_type        = Column(String(30), nullable=True) # FORWARD_SPLIT / REVERSE_SPLIT / STOCK_DIVIDEND / UNKNOWN
    adjustment_factor = Column(Float,    nullable=True)   # split_from / split_to
    source            = Column(String(20), nullable=True)
    synced_at         = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("symbol", "execution_date", name="uq_split_symbol_date"),
    )


class DemandTickerHistory(Base):
    """Per-ticker demand score snapshot saved after each scan run."""
    __tablename__ = "demand_ticker_history"

    id                    = Column(Integer, primary_key=True)
    scanned_at            = Column(DateTime, default=datetime.utcnow, index=True)
    symbol                = Column(String(10), nullable=False, index=True)
    demand_composite_score= Column(Float,   nullable=True)
    demand_composite_tier = Column(String(20), nullable=True)
    readiness_score       = Column(Float,   nullable=True)
    readiness_tier        = Column(String(10), nullable=True)
    combined_score        = Column(Float,   nullable=True)
    ats_signal            = Column(String(20), nullable=True)
    dryup_streak          = Column(Integer, nullable=True)
    vol_ratio             = Column(Float,   nullable=True)
    confluence_signals    = Column(String(120), nullable=True)   # comma-separated list


class CandleCache(Base):
    """Per-ticker daily OHLCV bar store for incremental scanning."""
    __tablename__ = "candle_cache"

    id     = Column(Integer,    primary_key=True)
    symbol = Column(String(10), nullable=False, index=True)
    date   = Column(String(10), nullable=False)          # YYYY-MM-DD
    o      = Column(Float,      nullable=True)
    h      = Column(Float,      nullable=True)
    l      = Column(Float,      nullable=True)
    c      = Column(Float,      nullable=True)
    v      = Column(BigInteger, nullable=True)
    t      = Column(BigInteger, nullable=True)            # epoch ms

    __table_args__ = (
        UniqueConstraint("symbol", "date", name="uq_candle_symbol_date"),
    )


_SCAN_CANDIDATE_MIGRATIONS = [
    ("vol_score",       "FLOAT"),
    ("accum_score",     "FLOAT"),
    ("quiet_factor",    "FLOAT"),
    ("inst_bonus",      "FLOAT"),
    ("original_score",  "FLOAT"),
    ("original_tier",   "VARCHAR(10)"),
    ("downgrade_reason","VARCHAR(30)"),
]

_SECTOR_CACHE_MIGRATIONS = [
    ("industry",           "VARCHAR(100)"),
    ("market_cap",         "BIGINT"),
    ("massive_fetched",    "BOOLEAN DEFAULT FALSE"),
    ("massive_fetched_at", "TIMESTAMP"),
]

_AI_PORTFOLIO_STATE_MIGRATIONS = [
    # DEFAULT 1000.0 so existing portfolios that started at $1000 get the right baseline
    ("baseline_value", "FLOAT DEFAULT 1000.0"),
]

_AI_PORTFOLIO_MIGRATIONS = [
    ("current_price",        "FLOAT"),
    ("max_gain_pct",         "FLOAT DEFAULT 0"),
    ("max_loss_pct",         "FLOAT DEFAULT 0"),
    ("stop_loss",            "FLOAT"),
    ("target_price",         "FLOAT"),
    ("exit_reason",          "VARCHAR(20)"),
    ("price_updated_at",     "TIMESTAMP"),
    ("target_price_2",       "FLOAT"),
    ("sell_pct_at_target_1", "INTEGER DEFAULT 50"),
    ("tp1_hit",              "BOOLEAN DEFAULT FALSE"),
    ("source",               "VARCHAR(20)"),
]

_PUMP_AI_SUMMARY_MIGRATIONS = [
    ("parse_failed", "BOOLEAN DEFAULT FALSE"),
    ("raw_response", "TEXT"),
    ("parse_error",  "TEXT"),
]

_RAW_PATTERN_EP_MIGRATIONS = [
    ("had_bull_stack_pre",                   "BOOLEAN"),
    ("bull_stack_days_pre",                  "INTEGER"),
    ("days_above_ema50_pre",                 "INTEGER"),
    ("days_above_ema200_pre",                "INTEGER"),
    ("ema50_reclaim_count_pre",              "INTEGER"),
    ("avg_close_vs_ema50_pct_pre",           "FLOAT"),
    ("avg_close_vs_ema200_pct_pre",          "FLOAT"),
    # New Pump engine episode aggregates (added in NP refactor)
    ("had_valid_recent_setup",               "BOOLEAN"),
    ("had_valid_recent_trigger",             "BOOLEAN"),
    ("had_valid_recent_confirm",             "BOOLEAN"),
    ("had_valid_full_sequence",              "BOOLEAN"),
    ("best_new_pump_label_rank",             "INTEGER"),
    ("best_new_pump_sequence_type",          "VARCHAR(40)"),
    ("days_from_last_setup_to_breakout",     "INTEGER"),
    ("days_from_last_trigger_to_breakout",   "INTEGER"),
    ("days_from_g4_to_b2",                   "INTEGER"),
    ("max_bull_stack_days_pre",              "INTEGER"),
    ("extreme_anomaly_day_count_pre",        "INTEGER"),
    ("median_dollar_volume_pre",             "FLOAT"),
    ("np_skip_reason",                       "VARCHAR(40)"),
    # NP count-based PRE-window aggregates
    ("l34_count_pre",                        "INTEGER"),
    ("fri34_count_pre",                      "INTEGER"),
    ("g4_count_pre",                         "INTEGER"),
    ("b2_count_pre",                         "INTEGER"),
    ("setup_only_l34_count_pre",             "INTEGER"),
    ("setup_only_fri34_count_pre",           "INTEGER"),
    ("trigger_after_l34_count_pre",          "INTEGER"),
    ("trigger_after_fri34_count_pre",        "INTEGER"),
    ("full_l34_g4_b2_count_pre",             "INTEGER"),
    ("full_fri34_g4_b2_count_pre",           "INTEGER"),
    ("isolated_g4_count_pre",                "INTEGER"),
    ("isolated_b2_count_pre",                "INTEGER"),
    ("confirm_after_g4_count_pre",           "INTEGER"),
    ("valid_setup_days_pre",                 "INTEGER"),
    ("valid_trigger_days_pre",               "INTEGER"),
    ("valid_confirm_days_pre",               "INTEGER"),
    ("valid_full_sequence_days_pre",         "INTEGER"),
    ("sector",                               "VARCHAR(50)"),
    ("industry",                             "VARCHAR(100)"),
    # Split / corporate action episode features
    ("has_split_near_episode",               "BOOLEAN"),
    ("has_reverse_split_near_episode",       "BOOLEAN"),
    ("has_forward_split_near_episode",       "BOOLEAN"),
    ("split_event_count",                    "INTEGER"),
    ("reverse_split_event_count",            "INTEGER"),
    ("forward_split_event_count",            "INTEGER"),
    ("nearest_split_date",                   "VARCHAR(10)"),
    ("nearest_split_type",                   "VARCHAR(30)"),
    ("nearest_split_ratio",                  "FLOAT"),
    ("nearest_split_days_from_breakout",     "INTEGER"),
    ("nearest_split_days_from_pump_start",   "INTEGER"),
    ("nearest_split_days_from_peak",         "INTEGER"),
    ("reverse_split_0_5d_before_breakout",   "BOOLEAN"),
    ("reverse_split_6_15d_before_breakout",  "BOOLEAN"),
    ("reverse_split_16_30d_before_breakout", "BOOLEAN"),
    ("reverse_split_31_60d_before_breakout", "BOOLEAN"),
    ("reverse_split_after_breakout",         "BOOLEAN"),
    ("split_during_pump_window",             "BOOLEAN"),
    ("split_after_peak_30d",                "BOOLEAN"),
    ("split_context",                        "VARCHAR(30)"),
    ("split_artifact_risk",                  "BOOLEAN"),
    ("split_artifact_reason",                "TEXT"),
    ("split_adjusted_move_estimate",         "FLOAT"),
    ("raw_move_pct",                         "FLOAT"),
    # Scanner v2 / NP structural fields (Phase 2B-7)
    # Structure phase
    ("dominant_structure_phase_pre",         "VARCHAR(30)"),
    ("best_structure_phase_pre",             "VARCHAR(30)"),
    ("max_structure_score_pre",              "INTEGER"),
    ("avg_structure_score_pre",              "FLOAT"),
    ("had_confirmed_structure_pre",          "BOOLEAN"),
    ("had_triggered_structure_pre",          "BOOLEAN"),
    ("had_early_structure_pre",              "BOOLEAN"),
    ("had_setup_phase_pre",                  "BOOLEAN"),
    ("had_impulse_only_pre",                 "BOOLEAN"),
    ("had_degraded_pre",                     "BOOLEAN"),
    # Compression / expansion
    ("had_accumulation_ready_pre",           "BOOLEAN"),
    ("had_expansion_start_pre",              "BOOLEAN"),
    ("had_overheated_expansion_pre",         "BOOLEAN"),
    ("max_expansion_timing_risk_pre",        "VARCHAR(10)"),
    ("high_expansion_risk_day_count_pre",    "INTEGER"),
    # D/WLNBB confluence
    ("had_d_confluence_pre",                 "BOOLEAN"),
    ("had_core_d_beup_pre",                  "BOOLEAN"),
    ("had_core_d_l34_pre",                   "BOOLEAN"),
    ("had_d6_beup_pre",                      "BOOLEAN"),
    ("had_d4_beup_pre",                      "BOOLEAN"),
    ("had_d3_beup_pre",                      "BOOLEAN"),
    ("had_l34_then_d4_3b_pre",               "BOOLEAN"),
    ("had_d4_then_beup_5b_pre",              "BOOLEAN"),
    ("had_d3_beup_toxic_pre",                "BOOLEAN"),
    ("dominant_d_confluence_type_pre",       "VARCHAR(30)"),
    ("dominant_d_confluence_family_pre",     "VARCHAR(30)"),
    ("d_confluence_day_count_pre",           "INTEGER"),
    ("d_confluence_best_type_pre",           "VARCHAR(30)"),
    # Decision / routing
    ("had_np_buy_candidate_pre",             "BOOLEAN"),
    ("had_np_watch_pre",                     "BOOLEAN"),
    ("had_np_avoid_pre",                     "BOOLEAN"),
    ("max_np_structure_score_pre",           "INTEGER"),
    ("buy_candidate_day_count_pre",          "INTEGER"),
    ("watch_day_count_pre",                  "INTEGER"),
    ("avoid_day_count_pre",                  "INTEGER"),
    # NP flags
    ("had_late_confirm_sequence_pre",        "BOOLEAN"),
    ("had_expansion_risk_flag_pre",          "BOOLEAN"),
    ("had_setup_only_l34_mid_avoid_pre",     "BOOLEAN"),
    # Pattern Discovery / Pump Watch (Phase 2B-PD)
    ("pump_watch_score",                     "INTEGER"),
    ("pump_watch_label",                     "VARCHAR(30)"),
    ("pump_watch_reasons",                   "TEXT"),
    ("pump_watch_risk_flags",                "TEXT"),
    ("pump_watch_pattern_ids",               "TEXT"),
    ("pump_watch_split_context",             "VARCHAR(30)"),
    ("pump_watch_confidence",                "VARCHAR(10)"),
    ("pump_watch_diagnostic_labels",         "TEXT"),       # JSON list of diagnostic label IDs
    ("pump_watch_pattern_id",                "VARCHAR(60)"), # primary diagnostic ID
    ("pump_watch_rescue_reason",             "VARCHAR(80)"), # human-readable rescue note
]

_REPLAY_OUTCOME_MIGRATIONS = [
    ("max_high",        "FLOAT"),
    ("max_gain_day",    "INTEGER"),
    ("max_gain_date",   "VARCHAR(10)"),
    ("giveback_pct",    "FLOAT"),
    ("hit_5pct",        "BOOLEAN"),
    ("hit_10pct",       "BOOLEAN"),
    ("hit_20pct",       "BOOLEAN"),
    ("hit_50pct",       "BOOLEAN"),
    ("hit_100pct",      "BOOLEAN"),
    ("hit_5pct_day",    "INTEGER"),
    ("hit_10pct_day",   "INTEGER"),
    ("hit_20pct_day",   "INTEGER"),
    ("hit_50pct_day",   "INTEGER"),
    ("hit_100pct_day",  "INTEGER"),
]

# replay_signal_candidates: columns added post-initial-deployment.
# Used by both SQLite and Postgres migration branches.
_REPLAY_SIGNAL_CANDIDATE_MIGRATIONS = [
    # New Pump columns
    ("new_pump_score",                 "FLOAT"),
    ("new_pump_label",                 "VARCHAR(30)"),
    ("new_pump_sequence_label",        "VARCHAR(40)"),
    ("np_has_l34",                     "BOOLEAN"),
    ("np_has_fri34",                   "BOOLEAN"),
    ("np_has_g4",                      "BOOLEAN"),
    ("np_has_b2",                      "BOOLEAN"),
    ("np_age_l34",                     "INTEGER"),
    ("np_age_fri34",                   "INTEGER"),
    ("np_setup_via",                   "VARCHAR(10)"),
    ("np_is_isolated_trigger",         "BOOLEAN"),
    ("np_state",                       "VARCHAR(20)"),
    ("np_engine_path",                 "VARCHAR(20)"),
    ("np_base_quality_score",          "INTEGER"),
    ("np_sustain_proxy_score",         "INTEGER"),
    ("np_sustain_profile",             "VARCHAR(10)"),
    ("np_fake_trigger_risk",           "VARCHAR(10)"),
    ("np_compression_expansion_state", "VARCHAR(30)"),
    ("np_compression_expansion_score", "INTEGER"),
    ("np_compression_expansion_label", "VARCHAR(15)"),
    ("np_expansion_timing_risk",       "VARCHAR(10)"),
    ("np_decision",                    "VARCHAR(20)"),
    ("np_decision_reason",             "VARCHAR(200)"),
    # Scanner v2 / priority enrichment (Task 9)
    ("priority_score",                 "FLOAT"),
    ("priority_label",                 "VARCHAR(20)"),
    ("scanner_v2_decision",            "VARCHAR(25)"),
    ("scanner_v2_score",               "FLOAT"),
    # Scanner v2 enrichment gap-fill: structure + d_confluence + rank
    ("np_structure_phase",             "VARCHAR(30)"),
    ("np_structure_score",             "FLOAT"),
    ("d_confluence_family",            "VARCHAR(20)"),
    ("d_confluence_timing",            "VARCHAR(20)"),
    ("scanner_v2_rank",                "INTEGER"),
]

_UNIVERSE_CACHE_MIGRATIONS: list[tuple[str, str]] = []
# universe_cache is created fresh by create_all — no ALTER needed on new columns.
# Add tuples here if columns are added post-initial-deployment.

_DISCOVERED_PATTERN_MIGRATIONS: list[tuple[str, str]] = [
    ("source_type",    "VARCHAR(30)"),
    ("feature_family", "VARCHAR(30)"),
]

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
    # v14+ new pump tracking
    ("source",      "VARCHAR(20)"),
    ("signal_date", "VARCHAR(10)"),
    ("np_sequence", "VARCHAR(40)"),
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
                pass
        for col, coltype in _SCAN_CANDIDATE_MIGRATIONS:
            try:
                await conn.execute(text(f"ALTER TABLE scan_candidates ADD COLUMN {col} {coltype}"))
            except Exception:
                pass
        for col, coltype in _AI_PORTFOLIO_STATE_MIGRATIONS:
            try:
                await conn.execute(text(f"ALTER TABLE ai_portfolio_state ADD COLUMN {col} {coltype}"))
            except Exception:
                pass
        for col, coltype in _AI_PORTFOLIO_MIGRATIONS:
            try:
                await conn.execute(text(f"ALTER TABLE ai_portfolio ADD COLUMN {col} {coltype}"))
            except Exception:
                pass
        for col, coltype in _SECTOR_CACHE_MIGRATIONS:
            try:
                await conn.execute(text(f"ALTER TABLE sector_cache ADD COLUMN {col} {coltype}"))
            except Exception:
                pass
        try:
            await conn.execute(text("ALTER TABLE scans ADD COLUMN scan_type VARCHAR(30)"))
        except Exception:
            pass
        for col, coltype in _PUMP_AI_SUMMARY_MIGRATIONS:
            try:
                await conn.execute(text(f"ALTER TABLE pump_study_ai_summaries ADD COLUMN {col} {coltype}"))
            except Exception:
                pass
        for col, coltype in _RAW_PATTERN_EP_MIGRATIONS:
            try:
                await conn.execute(text(f"ALTER TABLE raw_pattern_episode_features ADD COLUMN {col} {coltype}"))
            except Exception:
                pass
        for col, coltype in _REPLAY_OUTCOME_MIGRATIONS:
            try:
                await conn.execute(text(f"ALTER TABLE replay_outcomes ADD COLUMN {col} {coltype}"))
            except Exception:
                pass
        for col, coltype in _REPLAY_SIGNAL_CANDIDATE_MIGRATIONS:
            try:
                await conn.execute(text(f"ALTER TABLE replay_signal_candidates ADD COLUMN {col} {coltype}"))
            except Exception:
                pass
        for col, coltype in _UNIVERSE_CACHE_MIGRATIONS:
            try:
                await conn.execute(text(f"ALTER TABLE universe_cache ADD COLUMN {col} {coltype}"))
            except Exception:
                pass
        for col, coltype in _DISCOVERED_PATTERN_MIGRATIONS:
            try:
                await conn.execute(text(f"ALTER TABLE discovered_patterns ADD COLUMN {col} {coltype}"))
            except Exception:
                pass
    else:
        for col, coltype in _JOURNAL_MIGRATIONS:
            try:
                await conn.execute(text(
                    f"ALTER TABLE journal ADD COLUMN IF NOT EXISTS {col} {coltype}"
                ))
            except Exception as e:
                logger.warning(f"Migration journal.{col} failed (non-fatal): {e}")
        for col, coltype in _SCAN_CANDIDATE_MIGRATIONS:
            try:
                await conn.execute(text(
                    f"ALTER TABLE scan_candidates ADD COLUMN IF NOT EXISTS {col} {coltype}"
                ))
            except Exception as e:
                logger.warning(f"Migration scan_candidates.{col} failed (non-fatal): {e}")
        for col, coltype in _AI_PORTFOLIO_STATE_MIGRATIONS:
            try:
                await conn.execute(text(
                    f"ALTER TABLE ai_portfolio_state ADD COLUMN IF NOT EXISTS {col} {coltype}"
                ))
            except Exception as e:
                logger.warning(f"Migration ai_portfolio_state.{col} failed (non-fatal): {e}")
        for col, coltype in _AI_PORTFOLIO_MIGRATIONS:
            try:
                await conn.execute(text(
                    f"ALTER TABLE ai_portfolio ADD COLUMN IF NOT EXISTS {col} {coltype}"
                ))
            except Exception as e:
                logger.warning(f"Migration ai_portfolio.{col} failed (non-fatal): {e}")
        for col, coltype in _SECTOR_CACHE_MIGRATIONS:
            try:
                await conn.execute(text(
                    f"ALTER TABLE sector_cache ADD COLUMN IF NOT EXISTS {col} {coltype}"
                ))
            except Exception as e:
                logger.warning(f"Migration sector_cache.{col} failed (non-fatal): {e}")
        try:
            await conn.execute(text(
                "ALTER TABLE scans ADD COLUMN IF NOT EXISTS scan_type VARCHAR(30)"
            ))
        except Exception as e:
            logger.warning(f"Migration scans.scan_type failed (non-fatal): {e}")
        for col, coltype in _PUMP_AI_SUMMARY_MIGRATIONS:
            try:
                await conn.execute(text(
                    f"ALTER TABLE pump_study_ai_summaries ADD COLUMN IF NOT EXISTS {col} {coltype}"
                ))
            except Exception as e:
                logger.warning(f"Migration pump_study_ai_summaries.{col} failed (non-fatal): {e}")
        for col, coltype in _RAW_PATTERN_EP_MIGRATIONS:
            try:
                await conn.execute(text(
                    f"ALTER TABLE raw_pattern_episode_features ADD COLUMN IF NOT EXISTS {col} {coltype}"
                ))
            except Exception as e:
                logger.warning(f"Migration raw_pattern_episode_features.{col} failed (non-fatal): {e}")

        # replay_signal_candidates columns added post-initial-deployment
        for col, coltype in _REPLAY_SIGNAL_CANDIDATE_MIGRATIONS:
            try:
                await conn.execute(text(
                    f"ALTER TABLE replay_signal_candidates ADD COLUMN IF NOT EXISTS {col} {coltype}"
                ))
            except Exception as e:
                logger.warning(f"Migration replay_signal_candidates.{col} failed (non-fatal): {e}")

        for col, coltype in _UNIVERSE_CACHE_MIGRATIONS:
            try:
                await conn.execute(text(
                    f"ALTER TABLE universe_cache ADD COLUMN IF NOT EXISTS {col} {coltype}"
                ))
            except Exception as e:
                logger.warning(f"Migration universe_cache.{col} failed (non-fatal): {e}")

        for col, coltype in _DISCOVERED_PATTERN_MIGRATIONS:
            try:
                await conn.execute(text(
                    f"ALTER TABLE discovered_patterns ADD COLUMN IF NOT EXISTS {col} {coltype}"
                ))
            except Exception as e:
                logger.warning(f"Migration discovered_patterns.{col} failed (non-fatal): {e}")

        # MFE columns on replay_outcomes
        for col, coltype in _REPLAY_OUTCOME_MIGRATIONS:
            try:
                await conn.execute(text(
                    f"ALTER TABLE replay_outcomes ADD COLUMN IF NOT EXISTS {col} {coltype}"
                ))
            except Exception as e:
                logger.warning(f"Migration replay_outcomes.{col} failed (non-fatal): {e}")

        # Drop removed AI advisory tables (idempotent)
        for tbl in ("ai_signal_analysis", "ai_review_reports", "ai_insights"):
            try:
                await conn.execute(text(f"DROP TABLE IF EXISTS {tbl}"))
            except Exception as e:
                logger.warning(f"Drop {tbl} failed (non-fatal): {e}")


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
            scan_type=data.get("scan_type"),
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


async def get_latest_scan_by_type(scan_type: str) -> Optional[dict]:
    """Return the most recent scan of a specific type ('massive_eod' or 'yahoo_intraday')."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(Scan)
            .where(Scan.scan_type == scan_type)
            .order_by(Scan.scanned_at.desc())
            .limit(1)
        )
        scan = result.scalar_one_or_none()
        if not scan:
            # Fallback: search JSON for scan_type field (for old rows without column value)
            result2 = await session.execute(
                select(Scan).order_by(Scan.scanned_at.desc()).limit(10)
            )
            for row in result2.scalars():
                try:
                    data = json.loads(row.results_json)
                    if data.get("scan_type") == scan_type:
                        data["scan_id"] = row.id
                        return data
                except Exception:
                    continue
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


async def save_demand_ticker_history(results: list[dict], scanned_at=None) -> int:
    """Save per-ticker demand scores from a scan. Keeps 30 days of history per symbol."""
    from datetime import datetime as _dt
    ts = scanned_at or _dt.utcnow()
    if not results:
        return 0
    saved = 0
    async with get_session_factory()() as session:
        for r in results:
            sym  = r.get("symbol")
            tier = r.get("demand_composite_tier", "SKIP")
            if not sym or tier == "SKIP":
                continue
            row = DemandTickerHistory(
                scanned_at             = ts,
                symbol                 = sym,
                demand_composite_score = r.get("demand_composite_score"),
                demand_composite_tier  = tier,
                readiness_score        = r.get("readiness_score"),
                readiness_tier         = r.get("readiness_tier"),
                combined_score         = r.get("combined_score"),
                ats_signal             = r.get("ats_signal"),
                dryup_streak           = r.get("dc_dryup_streak"),
                vol_ratio              = r.get("dc_vol_ratio"),
                confluence_signals     = ",".join(r.get("confluence_signals") or []),
            )
            session.add(row)
            saved += 1
        await session.commit()
    # Prune rows older than 30 days
    try:
        from datetime import timedelta
        cutoff = ts - timedelta(days=30)
        async with get_session_factory()() as session:
            old = await session.execute(
                select(DemandTickerHistory).where(DemandTickerHistory.scanned_at < cutoff)
            )
            for row in old.scalars():
                await session.delete(row)
            await session.commit()
    except Exception:
        pass
    return saved


async def get_demand_ticker_history(symbol: str, limit: int = 30) -> list[dict]:
    """Return per-scan score history for one symbol, newest first."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(DemandTickerHistory)
            .where(DemandTickerHistory.symbol == symbol.upper())
            .order_by(DemandTickerHistory.scanned_at.desc())
            .limit(limit)
        )
        rows = result.scalars().all()
    return [
        {
            "scanned_at":             r.scanned_at.isoformat(),
            "demand_composite_score": r.demand_composite_score,
            "demand_composite_tier":  r.demand_composite_tier,
            "readiness_score":        r.readiness_score,
            "readiness_tier":         r.readiness_tier,
            "combined_score":         r.combined_score,
            "ats_signal":             r.ats_signal,
            "dryup_streak":           r.dryup_streak,
            "vol_ratio":              r.vol_ratio,
            "confluence_signals":     [s for s in (r.confluence_signals or "").split(",") if s],
        }
        for r in rows
    ]


async def get_candle_cache(symbol: str) -> list[dict]:
    """Return all cached bars for symbol, sorted oldest→newest."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(CandleCache)
            .where(CandleCache.symbol == symbol.upper())
            .order_by(CandleCache.date.asc())
        )
        rows = result.scalars().all()
    return [
        {"o": r.o, "h": r.h, "l": r.l, "c": r.c,
         "v": r.v, "t": r.t, "date": r.date}
        for r in rows
    ]


async def save_candle_cache(symbol: str, bars: list[dict]) -> None:
    """
    Upsert bars into candle_cache for symbol. Bars older than 260 days are pruned.
    Each bar dict must have keys: date (YYYY-MM-DD), o, h, l, c, v, t.
    """
    if not bars:
        return
    from datetime import date as _date, timedelta
    sym     = symbol.upper()
    cutoff  = (_date.today() - timedelta(days=260)).strftime("%Y-%m-%d")

    async with get_session_factory()() as session:
        # Upsert each bar
        for b in bars:
            d = b.get("date", "")
            if not d or d < cutoff:
                continue
            existing = await session.execute(
                select(CandleCache).where(
                    CandleCache.symbol == sym,
                    CandleCache.date   == d,
                )
            )
            row = existing.scalar_one_or_none()
            if row:
                row.o = b.get("o"); row.h = b.get("h")
                row.l = b.get("l"); row.c = b.get("c")
                row.v = b.get("v"); row.t = b.get("t")
            else:
                session.add(CandleCache(
                    symbol=sym, date=d,
                    o=b.get("o"), h=b.get("h"), l=b.get("l"),
                    c=b.get("c"), v=b.get("v"), t=b.get("t"),
                ))
        # Prune rows older than cutoff
        old_result = await session.execute(
            select(CandleCache).where(
                CandleCache.symbol == sym,
                CandleCache.date   <  cutoff,
            )
        )
        for old_row in old_result.scalars():
            await session.delete(old_row)
        await session.commit()


async def get_demand_all_histories(limit_per_sym: int = 10) -> list[dict]:
    """Return recent history rows for all symbols that appeared in last scan (for timeline view)."""
    async with get_session_factory()() as session:
        # Get distinct symbols that have appeared recently
        result = await session.execute(
            select(DemandTickerHistory.symbol)
            .group_by(DemandTickerHistory.symbol)
            .order_by(func.max(DemandTickerHistory.scanned_at).desc())
            .limit(200)
        )
        syms = [r[0] for r in result.fetchall()]

    all_rows = []
    for sym in syms:
        rows = await get_demand_ticker_history(sym, limit=limit_per_sym)
        all_rows.extend(rows)
    return all_rows


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


async def get_sector_full_from_db(symbol: str) -> Optional[dict]:
    """
    Return the full cached sector row as a dict, regardless of age.
    Used by the nightly enrichment job.
    Returns None if not cached at all.
    """
    try:
        async with get_session_factory()() as session:
            result = await session.execute(
                select(SectorCache).where(SectorCache.symbol == symbol.upper())
            )
            row = result.scalar_one_or_none()
            if row:
                return {
                    "sector":          row.sector,
                    "industry":        row.industry,
                    "market_cap":      row.market_cap,
                    "massive_fetched": row.massive_fetched or False,
                }
    except Exception as e:
        logger.debug(f"sector_cache full read failed for {symbol}: {e}")
    return None


async def get_symbols_needing_enrichment(limit: int = 200) -> list[str]:
    """
    Return symbols that have no industry or unconfirmed sector
    and have NOT been fetched from Massive yet.
    """
    try:
        async with get_session_factory()() as session:
            result = await session.execute(
                select(SectorCache.symbol).where(
                    (SectorCache.massive_fetched == False) &  # noqa: E712
                    (
                        (SectorCache.industry == None) |  # noqa: E711
                        (SectorCache.sector == "Unknown") |
                        (SectorCache.sector == None)  # noqa: E711
                    )
                ).order_by(SectorCache.symbol).limit(limit)
            )
            return [row[0] for row in result.fetchall()]
    except Exception as e:
        logger.debug(f"get_symbols_needing_enrichment failed: {e}")
        return []


async def save_sector_to_db(
    symbol: str,
    sector: str,
    industry: str = "",
    market_cap: Optional[int] = None,
    massive_fetched: bool = False,
) -> None:
    """Upsert sector and industry into the DB cache."""
    try:
        async with get_session_factory()() as session:
            result = await session.execute(
                select(SectorCache).where(SectorCache.symbol == symbol.upper())
            )
            row = result.scalar_one_or_none()
            now = datetime.utcnow()
            if row:
                row.sector = sector
                if industry:
                    row.industry = industry
                if market_cap:
                    row.market_cap = market_cap
                if massive_fetched:
                    row.massive_fetched = True
                    row.massive_fetched_at = now
                row.fetched_at = now
            else:
                session.add(SectorCache(
                    symbol=symbol.upper(),
                    sector=sector,
                    industry=industry or None,
                    market_cap=market_cap or None,
                    massive_fetched=massive_fetched,
                    massive_fetched_at=now if massive_fetched else None,
                    fetched_at=now,
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
        # v14+ new pump tracking
        "source":      j.source,
        "signal_date": j.signal_date,
        "np_sequence": j.np_sequence,
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
            source=data.get("source"),
            signal_date=data.get("signal_date"),
            np_sequence=data.get("np_sequence"),
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


async def get_journal_settings() -> dict:
    """Return the single journal settings row, creating it with defaults if absent."""
    async with get_session_factory()() as session:
        result = await session.execute(select(JournalSettings).limit(1))
        row = result.scalar_one_or_none()
        if row is None:
            row = JournalSettings(starting_balance=2000.0)
            session.add(row)
            await session.commit()
            await session.refresh(row)
        return {"id": row.id, "starting_balance": row.starting_balance}


async def update_journal_settings(starting_balance: float) -> dict:
    """Update starting_balance in journal settings."""
    async with get_session_factory()() as session:
        result = await session.execute(select(JournalSettings).limit(1))
        row = result.scalar_one_or_none()
        if row is None:
            row = JournalSettings(starting_balance=starting_balance)
            session.add(row)
        else:
            row.starting_balance = starting_balance
            row.updated_at = datetime.utcnow()
        await session.commit()
        await session.refresh(row)
        return {"id": row.id, "starting_balance": row.starting_balance}


async def reset_journal() -> dict:
    """Delete all journal entries and position snapshots. Returns count of deleted records."""
    async with get_session_factory()() as session:
        snap_result = await session.execute(select(PositionSnapshot))
        snapshots = snap_result.scalars().all()
        snap_count = len(snapshots)
        for s in snapshots:
            await session.delete(s)

        entry_result = await session.execute(select(Journal))
        journal_entries = entry_result.scalars().all()
        entry_count = len(journal_entries)
        for e in journal_entries:
            await session.delete(e)

        await session.commit()
    return {"deleted_entries": entry_count, "deleted_snapshots": snap_count}


async def get_journal_stats() -> dict:
    entries = await get_journal()
    closed = [e for e in entries if e["outcome"] in ("win", "loss")]
    wins = [e for e in entries if e["outcome"] == "win"]
    losses = [e for e in entries if e["outcome"] == "loss"]
    open_trades = [e for e in entries if e["outcome"] == "open"]

    settings = await get_journal_settings()
    starting_balance = settings.get("starting_balance", 2000.0)

    def _trade_pnl(e):
        return e.get("final_pnl_pct") or e.get("gain_pct") or 0

    win_rate = round(len(wins) / len(closed) * 100, 1) if closed else 0
    avg_win = round(sum(_trade_pnl(e) for e in wins) / len(wins), 2) if wins else 0
    avg_loss = round(sum(_trade_pnl(e) for e in losses) / len(losses), 2) if losses else 0
    total_pnl = round(sum(_trade_pnl(e) for e in closed), 2)
    pnl_usd = round(starting_balance * total_pnl / 100, 2)
    portfolio_value_usd = round(starting_balance + pnl_usd, 2)

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

    # Best and worst individual trades
    best_trade = None
    worst_trade = None
    if closed:
        best_e = max(closed, key=_trade_pnl)
        worst_e = min(closed, key=_trade_pnl)
        best_trade = {
            "symbol": best_e.get("symbol"),
            "pnl_pct": round(_trade_pnl(best_e), 2),
            "outcome": best_e.get("outcome"),
            "days_held": best_e.get("days_held"),
        }
        worst_trade = {
            "symbol": worst_e.get("symbol"),
            "pnl_pct": round(_trade_pnl(worst_e), 2),
            "outcome": worst_e.get("outcome"),
            "days_held": worst_e.get("days_held"),
        }

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
        "best_trade": best_trade,
        "worst_trade": worst_trade,
        "starting_balance": starting_balance,
        "pnl_usd": pnl_usd,
        "portfolio_value_usd": portfolio_value_usd,
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
        "current_price": p.current_price,
        "pnl_usd": p.pnl_usd or 0,
        "pnl_pct": p.pnl_pct or 0,
        "max_gain_pct": p.max_gain_pct or 0,
        "max_loss_pct": p.max_loss_pct or 0,
        "stop_loss": p.stop_loss,
        "target_price": p.target_price,
        "target_price_2": p.target_price_2,
        "sell_pct_at_target_1": p.sell_pct_at_target_1 if p.sell_pct_at_target_1 is not None else 50,
        "tp1_hit": p.tp1_hit or False,
        "status": p.status,
        "exit_reason": p.exit_reason,
        "reason": p.reason,
        "days_held": p.days_held or 0,
        "source": p.source,
        "scan_data": json.loads(p.scan_data) if p.scan_data else None,
        "price_updated_at": p.price_updated_at.isoformat() if p.price_updated_at else None,
    }


async def get_portfolio_state() -> dict:
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    async with get_session_factory()() as session:
        result = await session.execute(
            select(AIPortfolioState).order_by(AIPortfolioState.id.desc()).limit(1)
        )
        state = result.scalar_one_or_none()
        if not state:
            state = AIPortfolioState(date=today_str, cash=2000.0, total_value=2000.0,
                                     baseline_value=2000.0)
            session.add(state)
            await session.commit()
            await session.refresh(state)
    return {
        "date": state.date,
        "total_value": state.total_value,
        "cash": state.cash,
        "invested": state.invested or 0,
        "total_pnl_pct": state.total_pnl_pct or 0,
        "baseline_value": state.baseline_value or 2000.0,
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
            # Carry forward baseline_value from the most recent row so it doesn't
            # silently reset to the column default when a new day's row is created.
            latest_result = await session.execute(
                select(AIPortfolioState).order_by(AIPortfolioState.id.desc()).limit(1)
            )
            latest = latest_result.scalar_one_or_none()
            baseline_fwd = (latest.baseline_value if latest and latest.baseline_value else 2000.0)
            state = AIPortfolioState(date=today_str, baseline_value=baseline_fwd)
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
                              scan_data: dict | None = None,
                              stop_loss: float | None = None,
                              target_price: float | None = None,
                              target_price_2: float | None = None,
                              sell_pct_at_target_1: int = 50,
                              source: str | None = None) -> dict:
    async with get_session_factory()() as session:
        pos = AIPortfolio(
            symbol=symbol.upper(),
            action="BUY",
            decision_date=datetime.utcnow(),
            entry_price=entry_price,
            shares=shares,
            invested_usd=invested_usd,
            current_value=invested_usd,
            current_price=entry_price,
            stop_loss=stop_loss,
            target_price=target_price,
            target_price_2=target_price_2,
            sell_pct_at_target_1=sell_pct_at_target_1,
            tp1_hit=False,
            status="OPEN",
            reason=reason,
            source=source,
            scan_data=json.dumps(scan_data) if scan_data else None,
        )
        session.add(pos)
        await session.commit()
        await session.refresh(pos)
    return _portfolio_to_dict(pos)


async def close_ai_position(symbol: str, exit_price: float, reason: str,
                             exit_reason: str | None = None) -> Optional[dict]:
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
        pos.exit_reason = exit_reason or reason[:20] if reason else None
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
        pos.current_price = current_price
        pos.current_value = current_price * (pos.shares or 0)
        pos.price_updated_at = datetime.utcnow()
        if pos.entry_price and pos.entry_price > 0:
            pnl = round((current_price - pos.entry_price) / pos.entry_price * 100, 2)
            pos.pnl_pct = pnl
            pos.pnl_usd = round((current_price - pos.entry_price) * (pos.shares or 0), 2)
            pos.max_gain_pct = round(max(pos.max_gain_pct or 0, pnl), 2)
            pos.max_loss_pct = round(min(pos.max_loss_pct or 0, pnl), 2)
        days = (datetime.utcnow() - pos.decision_date).days if pos.decision_date else 0
        pos.days_held = days
        await session.commit()


async def update_portfolio_value_from_positions() -> None:
    """Recalculate total_value and invested from live position prices. Called intraday."""
    positions = await get_open_ai_positions()
    state = await get_portfolio_state()
    invested = sum(p.get("current_value") or p.get("invested_usd") or 0 for p in positions)
    total_value = state["cash"] + invested
    baseline = state.get("baseline_value") or 2000.0
    total_pnl_pct = round((total_value - baseline) / baseline * 100, 2) if baseline else 0.0
    await update_portfolio_state(
        cash=state["cash"],
        total_value=total_value,
        invested=invested,
        total_pnl_pct=total_pnl_pct,
    )


async def reset_ai_portfolio(new_capital: float = 2000.0) -> dict:
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    async with get_session_factory()() as session:
        # Force-close all open positions at current_price or entry_price
        result = await session.execute(
            select(AIPortfolio).where(AIPortfolio.status == "OPEN")
        )
        open_pos = result.scalars().all()
        for pos in open_pos:
            close_price = pos.current_price or pos.entry_price or 0
            pos.status = "CLOSED"
            pos.exit_price = close_price
            pos.exit_date = datetime.utcnow()
            pos.exit_reason = "RESET"
            if pos.entry_price and pos.entry_price > 0 and close_price:
                pos.pnl_pct = round((close_price - pos.entry_price) / pos.entry_price * 100, 2)
                pos.pnl_usd = round((close_price - pos.entry_price) * (pos.shares or 0), 2)

        # Upsert today's state row
        state_result = await session.execute(
            select(AIPortfolioState).where(AIPortfolioState.date == today_str)
        )
        state = state_result.scalar_one_or_none()
        if not state:
            state = AIPortfolioState(date=today_str)
            session.add(state)
        state.cash = new_capital
        state.total_value = new_capital
        state.invested = 0.0
        state.total_pnl_pct = 0.0
        state.baseline_value = new_capital
        await session.commit()
    return {"status": "reset", "new_capital": new_capital}


async def update_ai_portfolio_baseline(new_baseline: float) -> dict:
    """Update baseline_value in the latest state row without touching positions."""
    today_str = datetime.utcnow().strftime("%Y-%m-%d")
    async with get_session_factory()() as session:
        result = await session.execute(
            select(AIPortfolioState).order_by(AIPortfolioState.id.desc()).limit(1)
        )
        state = result.scalar_one_or_none()
        if not state:
            state = AIPortfolioState(date=today_str, cash=new_baseline,
                                     total_value=new_baseline, baseline_value=new_baseline)
            session.add(state)
        else:
            state.baseline_value = new_baseline
        await session.commit()
        return {"baseline_value": new_baseline}


async def partial_exit_ai_position(position_id: int, current_price: float, sell_pct: int = 50) -> float:
    """
    Sell sell_pct% of shares at current_price, mark tp1_hit=True.
    Returns cash proceeds. Idempotent — no-op if tp1_hit already True.
    """
    async with get_session_factory()() as session:
        result = await session.execute(select(AIPortfolio).where(AIPortfolio.id == position_id))
        pos = result.scalar_one_or_none()
        if not pos or pos.tp1_hit:
            return 0.0
        sell_ratio = sell_pct / 100.0
        shares_sold = (pos.shares or 0) * sell_ratio
        proceeds = round(shares_sold * current_price, 2)
        pos.shares = round((pos.shares or 0) * (1 - sell_ratio), 6)
        pos.invested_usd = round((pos.invested_usd or 0) * (1 - sell_ratio), 2)
        pos.current_value = round(pos.shares * current_price, 2)
        pos.tp1_hit = True
        await session.commit()
    return proceeds


async def get_recent_np_signals(days: int = 5) -> list[dict]:
    """Return recent NP FIRE/STRONG signals from replay candidates (for AI portfolio)."""
    from datetime import date, timedelta
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    async with get_session_factory()() as session:
        result = await session.execute(
            select(ReplaySignalCandidate).where(
                ReplaySignalCandidate.new_pump_label.in_(["FIRE", "STRONG"]),
                ReplaySignalCandidate.scan_date >= cutoff,
            ).order_by(ReplaySignalCandidate.scan_date.desc()).limit(30)
        )
        rows = result.scalars().all()
    result_list = []
    for r in rows:
        # Extract d_confluence_type_v2 from snapshot JSON for D/WLNBB combo lookup
        dct_v2 = None
        try:
            snap = json.loads(r.candidate_snapshot_json or "{}")
            np_d = snap.get("new_pump") or {}
            dct_v2 = np_d.get("d_confluence_type_v2") or snap.get("d_confluence_type_v2")
        except Exception:
            pass
        result_list.append({
            "symbol": r.symbol,
            "scan_date": r.scan_date,
            "new_pump_label": r.new_pump_label,
            "new_pump_score": r.new_pump_score,
            "new_pump_sequence_label": r.new_pump_sequence_label,
            "np_setup_via": r.np_setup_via,
            "np_has_l34": r.np_has_l34,
            "np_has_fri34": r.np_has_fri34,
            "np_has_g4": r.np_has_g4,
            "np_has_b2": r.np_has_b2,
            "np_age_l34": r.np_age_l34,
            "np_age_fri34": r.np_age_fri34,
            "np_is_isolated_trigger": r.np_is_isolated_trigger,
            "sector": r.sector,
            "price": r.price,
            "tier": r.tier,
            # NP quality signals — used by AI portfolio for per-candidate assessment
            "np_state":                       r.np_state,
            "np_base_quality_score":          r.np_base_quality_score,
            "np_fake_trigger_risk":           r.np_fake_trigger_risk,
            "np_expansion_timing_risk":       r.np_expansion_timing_risk,
            "np_compression_expansion_state": r.np_compression_expansion_state,
            "np_decision":                    r.np_decision,
            # D/WLNBB combo classifier (extracted from snapshot JSON)
            "np_d_confluence_type_v2":        dct_v2,
        })
    return result_list


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
                score_data = r.get("score", {})
                cand = ScanCandidate(
                    scan_date=today,
                    symbol=r["symbol"],
                    price=r.get("price"),
                    tier=score_data["tier"],
                    score=score_data.get("total_score"),
                    wyckoff=r.get("regime", {}).get("state"),
                    cmf_pctl=r.get("indicators", {}).get("cmf_pctl"),
                    vol_ratio=r.get("indicators", {}).get("anomaly_ratio"),
                    hype=r.get("hype_score", {}).get("hype_index", 0),
                    divergences=divs or None,
                    was_journaled=False,
                    vol_score=score_data.get("vol_score"),
                    accum_score=score_data.get("accum_score"),
                    quiet_factor=score_data.get("quiet_factor"),
                    inst_bonus=score_data.get("inst_bonus"),
                    original_score=score_data.get("original_score"),
                    original_tier=score_data.get("original_tier"),
                    downgrade_reason=score_data.get("primary_downgrade"),
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
        # Store full result dict so cycle_phase, industry_leaders, etc. survive restarts
        etf_json = json.dumps({
            "etf_details":      data.get("etf_details", {}),
            "cycle_phase":      data.get("cycle_phase", "NEUTRAL"),
            "industry_leaders": data.get("industry_leaders", []),
            "industry_laggards":data.get("industry_laggards", []),
            "iwm_pct":          data.get("iwm_pct", 0),
            "iwm_vs_spy":       data.get("iwm_vs_spy", 0),
            "small_cap_regime": data.get("small_cap_regime", "NEUTRAL"),
        })

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

    # Load stored JSON — supports both old format (plain ETF dict) and
    # new format (nested dict with "etf_details" key and extra computed fields)
    raw = {}
    try:
        raw = json.loads(row.etf_details_json or "{}")
    except Exception:
        pass

    if "etf_details" in raw:
        # New format: full result dict
        etf              = raw.get("etf_details", {})
        cycle_phase      = raw.get("cycle_phase", "NEUTRAL")
        industry_leaders = raw.get("industry_leaders", [])
        industry_laggards= raw.get("industry_laggards", [])
        iwm_pct          = raw.get("iwm_pct", 0)
        iwm_vs_spy       = raw.get("iwm_vs_spy", 0)
        small_cap_regime = raw.get("small_cap_regime", "NEUTRAL")
    else:
        # Old format: just the ETF data dict — reconstruct derived fields
        etf = raw
        spy_1d = row.spy_pct or 0
        iwm_1d = (etf.get("IWM") or {}).get("pct_1d", 0) or 0
        iwm_vs_spy = round(iwm_1d - spy_1d, 2)
        iwm_pct = iwm_1d
        if iwm_vs_spy > 0.5:
            small_cap_regime = "LEADING"
        elif iwm_vs_spy < -0.5:
            small_cap_regime = "LAGGING"
        else:
            small_cap_regime = "NEUTRAL"
        # Reconstruct industry leaders/laggards from stored ETF data
        _IND_ETFS = {"SMH": "Semiconductors", "XBI": "Biotechnology",
                     "ITA": "Aerospace & Defense", "TAN": "Solar",
                     "KRE": "Regional Banks", "XME": "Metals & Mining",
                     "IYT": "Transportation"}
        industry_leaders = []
        industry_laggards = []
        for sym, name in _IND_ETFS.items():
            d = etf.get(sym) or {}
            p = d.get("pct_1d", 0) or 0
            entry = {"symbol": sym, "name": name, "pct_1d": p}
            if p > 1.0:
                industry_leaders.append(entry)
            elif p < -1.0:
                industry_laggards.append(entry)
        # Detect cycle phase from stored ETF pct_1d values
        def _p(sym): return (etf.get(sym) or {}).get("pct_1d", 0) or 0
        gld_p = _p("GLD"); spy_p = spy_1d
        if gld_p > 1.5 and spy_p < -1.0:
            cycle_phase = "FEAR"
        elif _p("XLE") > 1.0 and _p("XLK") < -0.5 and spy_p < 0:
            cycle_phase = "STAGFLATION"
        elif _p("XLE") > 0.5 and _p("XLB") > 0.3 and spy_p > -0.5:
            cycle_phase = "LATE_CYCLE"
        elif (_p("XLU") > 0.3 or _p("XLP") > 0.3 or _p("XLV") > 0.3) and _p("XLK") < 0:
            cycle_phase = "RISK_OFF"
        elif _p("XLK") > 0.5 and spy_p > 0:
            cycle_phase = "RISK_ON_GROWTH"
        else:
            cycle_phase = "NEUTRAL"

    return {
        "date":              row.date.isoformat() if row.date else None,
        "regime":            row.regime,
        "spy_pct":           row.spy_pct,
        "qqq_pct":           row.qqq_pct,
        "xle_pct":           row.xle_pct,
        "xlv_pct":           row.xlv_pct,
        "xlu_pct":           row.xlu_pct,
        "gld_pct":           row.gld_pct,
        "spy_vs_ema20":      row.spy_vs_ema20,
        "qqq_vs_ema20":      row.qqq_vs_ema20,
        "strong_sectors":    strong,
        "weak_sectors":      weak,
        "recommendation":    row.recommendation,
        "etf_details":       etf,
        "cycle_phase":       cycle_phase,
        "industry_leaders":  industry_leaders,
        "industry_laggards": industry_laggards,
        "iwm_pct":           iwm_pct,
        "iwm_vs_spy":        iwm_vs_spy,
        "small_cap_regime":  small_cap_regime,
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


# ─── Pattern Streaks ──────────────────────────────────────────────────────────

async def get_active_streaks(min_days: int = 2) -> List[dict]:
    """
    Return active pattern streaks seen today or yesterday with at least min_days length.
    Ordered by streak_days desc, then avg_score desc.
    """
    from datetime import date as _date, timedelta
    today = _date.today()
    yesterday = today - timedelta(days=1)
    async with get_session_factory()() as session:
        result = await session.execute(
            select(PatternStreak)
            .where(
                PatternStreak.last_seen >= yesterday,
                PatternStreak.streak_days >= min_days,
            )
            .order_by(PatternStreak.streak_days.desc(), PatternStreak.avg_score.desc())
        )
        streaks = result.scalars().all()
    return [
        {
            "symbol": s.symbol,
            "streak_days": s.streak_days,
            "streak_start": s.streak_start.isoformat() if s.streak_start else None,
            "avg_score": round(s.avg_score or 0, 1),
            "avg_cmf_pctl": round(s.avg_cmf_pctl or 0, 1),
            "avg_vol_ratio": round(s.avg_vol_ratio or 0, 2),
            "avg_hype": s.avg_hype or 0,
            "tier": s.tier,
            "wyckoff": s.wyckoff,
            "last_seen": s.last_seen.isoformat() if s.last_seen else None,
        }
        for s in streaks
    ]


# ─── Data Rotation ─────────────────────────────────────────────────────────────

async def save_ribbon_candidates(candidates: list[dict]) -> int:
    """
    Upsert ribbon pass candidates.
    ON CONFLICT (scan_date, symbol) updates key fields so the latest intraday
    snapshot always wins.
    """
    if not candidates:
        return 0
    from datetime import date as date_type
    today = date_type.today()
    saved = 0
    async with get_engine().begin() as conn:
        for c in candidates:
            try:
                params = {
                    "scan_date":   today,
                    "symbol":      c["symbol"],
                    "price":       c.get("price"),
                    "today_vol":   c.get("today_vol"),
                    "anomaly_ratio": c.get("anomaly_ratio"),
                    "ema8":        c.get("ema8"),
                    "ema13":       c.get("ema13"),
                    "ema20":       c.get("ema20"),
                    "ema21":       c.get("ema21"),
                    "ema34":       c.get("ema34"),
                    "ema50":       c.get("ema50"),
                    "ema55":       c.get("ema55"),
                    "ema89":       c.get("ema89"),
                    "ema200":      c.get("ema200"),
                    "ema_spread_pct":         c.get("ema_spread_pct"),
                    "ribbon_compression":     c.get("ribbon_compression", "NONE"),
                    "bullish_stack":          bool(c.get("bullish_stack", False)),
                    "bearish_stack":          bool(c.get("bearish_stack", False)),
                    "compression_and_bullish": bool(c.get("compression_and_bullish", False)),
                    "ribbon_position":        c.get("ribbon_position"),
                    "ema8_slope":             c.get("ema8_slope", "FLAT"),
                    "cmf_pctl":    c.get("cmf_pctl"),
                    "rsi":         c.get("rsi"),
                    "bb_sqz_bars": c.get("bb_sqz_bars", 0),
                    "bb_squeeze":  bool(c.get("bb_squeeze", False)),
                    "obv_strength": c.get("obv_strength"),
                    "rs_score":    c.get("rs_score", 0.0),
                    "sector":      c.get("sector"),
                }
                if _IS_SQLITE:
                    await conn.execute(text("""
                        INSERT OR REPLACE INTO ribbon_candidates (
                            scan_date, symbol, price, today_vol, anomaly_ratio,
                            ema8, ema13, ema20, ema21, ema34, ema50, ema55, ema89, ema200,
                            ema_spread_pct, ribbon_compression,
                            bullish_stack, bearish_stack, compression_and_bullish,
                            ribbon_position, ema8_slope,
                            cmf_pctl, rsi, bb_sqz_bars, bb_squeeze,
                            obv_strength, rs_score, sector, scanned_at
                        ) VALUES (
                            :scan_date, :symbol, :price, :today_vol, :anomaly_ratio,
                            :ema8, :ema13, :ema20, :ema21, :ema34, :ema50, :ema55, :ema89, :ema200,
                            :ema_spread_pct, :ribbon_compression,
                            :bullish_stack, :bearish_stack, :compression_and_bullish,
                            :ribbon_position, :ema8_slope,
                            :cmf_pctl, :rsi, :bb_sqz_bars, :bb_squeeze,
                            :obv_strength, :rs_score, :sector, CURRENT_TIMESTAMP
                        )
                    """), params)
                else:
                    await conn.execute(text("""
                        INSERT INTO ribbon_candidates (
                            scan_date, symbol, price, today_vol, anomaly_ratio,
                            ema8, ema13, ema20, ema21, ema34, ema50, ema55, ema89, ema200,
                            ema_spread_pct, ribbon_compression,
                            bullish_stack, bearish_stack, compression_and_bullish,
                            ribbon_position, ema8_slope,
                            cmf_pctl, rsi, bb_sqz_bars, bb_squeeze,
                            obv_strength, rs_score, sector, scanned_at
                        ) VALUES (
                            :scan_date, :symbol, :price, :today_vol, :anomaly_ratio,
                            :ema8, :ema13, :ema20, :ema21, :ema34, :ema50, :ema55, :ema89, :ema200,
                            :ema_spread_pct, :ribbon_compression,
                            :bullish_stack, :bearish_stack, :compression_and_bullish,
                            :ribbon_position, :ema8_slope,
                            :cmf_pctl, :rsi, :bb_sqz_bars, :bb_squeeze,
                            :obv_strength, :rs_score, :sector, NOW()
                        )
                        ON CONFLICT (scan_date, symbol) DO UPDATE SET
                            price                   = EXCLUDED.price,
                            today_vol               = EXCLUDED.today_vol,
                            anomaly_ratio           = EXCLUDED.anomaly_ratio,
                            ema_spread_pct          = EXCLUDED.ema_spread_pct,
                            ribbon_compression      = EXCLUDED.ribbon_compression,
                            bullish_stack           = EXCLUDED.bullish_stack,
                            bearish_stack           = EXCLUDED.bearish_stack,
                            compression_and_bullish = EXCLUDED.compression_and_bullish,
                            ribbon_position         = EXCLUDED.ribbon_position,
                            ema8_slope              = EXCLUDED.ema8_slope,
                            cmf_pctl                = EXCLUDED.cmf_pctl,
                            obv_strength            = EXCLUDED.obv_strength,
                            rs_score                = EXCLUDED.rs_score,
                            scanned_at              = NOW()
                    """), params)
                saved += 1
            except Exception as e:
                logger.warning(f"save_ribbon_candidates upsert failed for {c.get('symbol')}: {e}")
    return saved


async def get_ribbon_candidates(days_back: int = 1) -> list[dict]:
    """Return ribbon candidates from the last N days as plain dicts."""
    from datetime import date, timedelta
    cutoff = date.today() - timedelta(days=days_back)
    async with get_engine().begin() as conn:
        result = await conn.execute(
            text("SELECT * FROM ribbon_candidates WHERE scan_date >= :cutoff ORDER BY ema_spread_pct ASC"),
            {"cutoff": cutoff},
        )
        rows = result.mappings().all()
    return [dict(row) for row in rows]


async def rotate_old_data() -> dict:
    """
    Delete old rows to prevent DB bloat.
    Called weekly by the scheduler and available via admin endpoint.

    Retention policy:
      scans              — 30 days  (candles are large; 7-scan cap in save_scan is primary)
      scan_candidates    — 60 days  (covers 20d outcome tracking window with room to spare)
      position_snapshots — 60 days
      eod_logs           — 90 days

    Never deleted: journal, ai_portfolio, market_regime,
                   sector_strength, pattern_streaks, watchlist
    """
    from datetime import date, timedelta, datetime as dt

    today = date.today()
    cutoff_scans      = dt.combine(today - timedelta(days=30), dt.min.time())
    cutoff_candidates = today - timedelta(days=60)
    cutoff_snapshots  = today - timedelta(days=60)
    cutoff_eod        = (today - timedelta(days=90)).isoformat()  # stored as string

    deleted = {}

    async with get_engine().begin() as conn:
        r = await conn.execute(
            text("DELETE FROM scans WHERE scanned_at < :cutoff"),
            {"cutoff": cutoff_scans},
        )
        deleted["scans"] = r.rowcount

        r = await conn.execute(
            text("DELETE FROM scan_candidates WHERE scan_date < :cutoff"),
            {"cutoff": cutoff_candidates},
        )
        deleted["scan_candidates"] = r.rowcount

        r = await conn.execute(
            text("DELETE FROM position_snapshots WHERE snapshot_date < :cutoff"),
            {"cutoff": cutoff_snapshots},
        )
        deleted["position_snapshots"] = r.rowcount

        r = await conn.execute(
            text("DELETE FROM eod_logs WHERE log_date < :cutoff"),
            {"cutoff": cutoff_eod},
        )
        deleted["eod_logs"] = r.rowcount

        cutoff_ribbon = today - timedelta(days=14)
        r = await conn.execute(
            text("DELETE FROM ribbon_candidates WHERE scan_date < :cutoff"),
            {"cutoff": cutoff_ribbon},
        )
        deleted["ribbon_candidates"] = r.rowcount

    total = sum(deleted.values())
    logger.info(
        f"Data rotation complete — {total} rows removed: "
        + ", ".join(f"{tbl}={n}" for tbl, n in deleted.items())
    )
    return deleted


# ─── Macro Event Bias (Trump News Layer — Version Alpha) ──────────────────────

def _macro_event_to_dict(ev: MacroEventBias) -> dict:
    import json as _json
    def _parse(val):
        if isinstance(val, list):
            return val
        try:
            return _json.loads(val) if val else []
        except Exception:
            return []

    return {
        "id":                 ev.id,
        "event_id":           ev.event_id,
        "title":              ev.title,
        "source_url":         ev.source_url,
        "published_at":       ev.published_at.isoformat() if ev.published_at else None,
        "fetched_at":         ev.fetched_at.isoformat() if ev.fetched_at else None,
        "relevance_score":    ev.relevance_score,
        "event_classes":      _parse(ev.event_classes),
        "primary_class":      ev.primary_class,
        "market_bias":        ev.market_bias,
        "time_horizon":       ev.time_horizon,
        "confidence":         ev.confidence,
        "surprise_level":     ev.surprise_level,
        "volatility_bias":    ev.volatility_bias,
        "oil_bias":           ev.oil_bias,
        "rates_bias":         ev.rates_bias,
        "dollar_bias":        ev.dollar_bias,
        "bullish_sectors":    _parse(ev.bullish_sectors),
        "bearish_sectors":    _parse(ev.bearish_sectors),
        "bullish_industries": _parse(ev.bullish_industries),
        "bearish_industries": _parse(ev.bearish_industries),
        "is_active":          ev.is_active,
    }


async def upsert_macro_events(events: list[dict]) -> int:
    """
    Idempotent upsert of classified macro events.
    Uses event_id (SHA1 of title+date) to detect duplicates.
    Returns count of newly inserted rows.
    """
    import json as _json
    if not events:
        return 0

    inserted = 0
    async with get_session_factory()() as session:
        for ev in events:
            try:
                result = await session.execute(
                    select(MacroEventBias).where(MacroEventBias.event_id == ev["event_id"])
                )
                existing = result.scalar_one_or_none()
                if existing:
                    # Update is_active status (might change as events age)
                    existing.is_active = ev.get("is_active", True)
                    continue

                # Parse published_at
                try:
                    pub = datetime.fromisoformat(ev["published_at"].replace("Z", "+00:00"))
                    pub = pub.replace(tzinfo=None)  # store as UTC naive
                except Exception:
                    pub = datetime.utcnow()

                row = MacroEventBias(
                    event_id        = ev["event_id"],
                    title           = ev["title"],
                    source_url      = ev.get("source_url", ""),
                    published_at    = pub,
                    fetched_at      = datetime.utcnow(),
                    relevance_score = ev.get("relevance_score", 50),
                    event_classes   = _json.dumps(ev.get("event_classes", [])),
                    primary_class   = ev.get("primary_class", "GENERAL_POLITICAL_NOISE"),
                    market_bias     = ev.get("market_bias", "NEUTRAL"),
                    time_horizon    = ev.get("time_horizon", "SHORT"),
                    confidence      = ev.get("confidence", 50),
                    surprise_level  = ev.get("surprise_level", 20),
                    volatility_bias = ev.get("volatility_bias", "LOW"),
                    oil_bias        = ev.get("oil_bias", "NEUTRAL"),
                    rates_bias      = ev.get("rates_bias", "NEUTRAL"),
                    dollar_bias     = ev.get("dollar_bias", "NEUTRAL"),
                    bullish_sectors   = _json.dumps(ev.get("bullish_sectors", [])),
                    bearish_sectors   = _json.dumps(ev.get("bearish_sectors", [])),
                    bullish_industries= _json.dumps(ev.get("bullish_industries", [])),
                    bearish_industries= _json.dumps(ev.get("bearish_industries", [])),
                    is_active       = ev.get("is_active", True),
                )
                session.add(row)
                inserted += 1
            except Exception as e:
                logger.warning(f"upsert_macro_events failed for event_id={ev.get('event_id')}: {e}")

        await session.commit()

    logger.info(f"upsert_macro_events: {inserted} new events inserted (of {len(events)} total)")
    return inserted


async def get_macro_events_latest(limit: int = 20) -> list[dict]:
    """Return the most recent macro events ordered by published_at desc."""
    try:
        async with get_session_factory()() as session:
            result = await session.execute(
                select(MacroEventBias)
                .order_by(MacroEventBias.published_at.desc())
                .limit(limit)
            )
            rows = result.scalars().all()
            return [_macro_event_to_dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_macro_events_latest failed: {e}")
        return []


async def get_macro_events_history(days: int = 7, limit: int = 100) -> list[dict]:
    """Return events from the last N days."""
    try:
        cutoff = datetime.utcnow() - timedelta(days=days)
        async with get_session_factory()() as session:
            result = await session.execute(
                select(MacroEventBias)
                .where(MacroEventBias.published_at >= cutoff)
                .order_by(MacroEventBias.published_at.desc())
                .limit(limit)
            )
            rows = result.scalars().all()
            return [_macro_event_to_dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_macro_events_history failed: {e}")
        return []


async def get_macro_events_active(max_age_days: int = 3) -> list[dict]:
    """Return events that are still within their active window."""
    try:
        cutoff = datetime.utcnow() - timedelta(days=max_age_days)
        async with get_session_factory()() as session:
            result = await session.execute(
                select(MacroEventBias)
                .where(
                    (MacroEventBias.published_at >= cutoff) &
                    (MacroEventBias.is_active == True)  # noqa: E712
                )
                .order_by(MacroEventBias.relevance_score.desc(), MacroEventBias.published_at.desc())
            )
            rows = result.scalars().all()
            return [_macro_event_to_dict(r) for r in rows]
    except Exception as e:
        logger.error(f"get_macro_events_active failed: {e}")
        return []




# ╔══════════════════════════════════════════════════════════════════════════════╗
# ║  HISTORICAL REPLAY — DB MODELS + CRUD                                      ║
# ║  Strictly isolated from live production tables.                             ║
# ║  Live scan/journal/portfolio data is never touched.                         ║
# ╚══════════════════════════════════════════════════════════════════════════════╝

class ReplayRun(Base):
    """
    One historical replay run (single date OR date range).
    Tracks status, progress counters, and completion metadata.
    """
    __tablename__ = "replay_runs"

    id                  = Column(Integer, primary_key=True)
    mode                = Column(String(20),  default="single_day")   # single_day | date_range
    status              = Column(String(20),  default="running")       # running | completed | failed | cancelled
    universe_mode       = Column(String(10),  default="approx")        # strict | approx
    as_of_date          = Column(String(10),  nullable=True)           # YYYY-MM-DD  (single_day)
    start_date          = Column(String(10),  nullable=True)           # range start
    end_date            = Column(String(10),  nullable=True)           # range end
    total_days          = Column(Integer,     default=0)
    days_completed      = Column(Integer,     default=0)
    total_symbols       = Column(Integer,     default=0)
    total_candidates    = Column(Integer,     default=0)
    outcomes_computed   = Column(Integer,     default=0)
    missed_movers_found = Column(Integer,     default=0)
    error_message       = Column(Text,        nullable=True)
    notes               = Column(Text,        nullable=True)
    started_at          = Column(DateTime(timezone=True), nullable=True)
    finished_at         = Column(DateTime(timezone=True), nullable=True)
    created_at          = Column(DateTime(timezone=True), default=datetime.utcnow)


class ReplaySignalCandidate(Base):
    """
    One ticker signal generated during a historical replay scan.
    Stores the full indicator snapshot as-of the replay date.
    Never mixed with live ScanCandidate rows.
    """
    __tablename__ = "replay_signal_candidates"

    id                    = Column(Integer, primary_key=True)
    replay_run_id         = Column(Integer, nullable=False, index=True)
    scan_date             = Column(String(10), nullable=False, index=True)
    symbol                = Column(String(10), nullable=False)
    price                 = Column(Float,      nullable=True)
    tier                  = Column(String(10), nullable=True)
    total_score           = Column(Float,      nullable=True)
    wyckoff_state         = Column(String(20), nullable=True)
    ignition_signal       = Column(Boolean,    default=False)   # legacy — no longer written
    ribbon_signal         = Column(Boolean,    default=False)   # legacy — no longer written
    sector                = Column(String(60), nullable=True)
    new_pump_score        = Column(Float,      nullable=True)
    new_pump_label        = Column(String(30), nullable=True)
    new_pump_sequence_label = Column(String(40), nullable=True)
    # NP signal detail fields
    np_has_l34            = Column(Boolean,    nullable=True)
    np_has_fri34          = Column(Boolean,    nullable=True)
    np_has_g4             = Column(Boolean,    nullable=True)
    np_has_b2             = Column(Boolean,    nullable=True)
    np_age_l34            = Column(Integer,    nullable=True)
    np_age_fri34          = Column(Integer,    nullable=True)
    np_setup_via          = Column(String(10), nullable=True)   # L34 | FRI34 | BOTH | NONE
    np_is_isolated_trigger = Column(Boolean,   nullable=True)   # G4 fired without any setup
    np_state               = Column(String(20), nullable=True)  # classify_state() output
    np_engine_path         = Column(String(20), nullable=True)  # structure | impulse
    np_base_quality_score  = Column(Integer,    nullable=True)  # 0–100
    np_sustain_proxy_score = Column(Integer,    nullable=True)  # 0–100
    np_sustain_profile     = Column(String(10), nullable=True)  # LOW|MEDIUM|HIGH
    np_fake_trigger_risk   = Column(String(10), nullable=True)  # LOW|MEDIUM|HIGH
    np_compression_expansion_state = Column(String(30), nullable=True)  # NONE/COMPRESSED_BASE/...
    np_compression_expansion_score = Column(Integer,    nullable=True)  # 0–100
    np_compression_expansion_label = Column(String(15), nullable=True)  # NONE/WEAK/MODERATE/STRONG/RISKY
    np_expansion_timing_risk       = Column(String(10), nullable=True)  # LOW|MEDIUM|HIGH
    np_decision                    = Column(String(20), nullable=True)  # BUY_CANDIDATE/WATCH/IMPULSE_RISK/AVOID
    np_decision_reason             = Column(String(200), nullable=True) # human-readable
    # ── Scanner v2 / priority enrichment (added Task 9) ──────────────────────
    # Computed by enrich_np_candidates + build_v2_row in replay_engine.
    # Columns are queryable; full JSON of flags/reason/contexts lives in snapshot.
    priority_score        = Column(Float,      nullable=True)            # 0–100
    priority_label        = Column(String(20), nullable=True)            # PRIORITY_HIGH/MEDIUM/LOW/RISKY
    scanner_v2_decision   = Column(String(25), nullable=True)            # BUY_CANDIDATE_HIGH/NORMAL/WATCH_HIGH/MED/LOW/AVOID_*
    scanner_v2_score      = Column(Float,      nullable=True)            # 0–100
    np_structure_phase    = Column(String(30), nullable=True)            # CONFIRMED_STRUCTURE/EARLY_STRUCTURE/TRUE_NONE
    np_structure_score    = Column(Float,      nullable=True)            # 0–100 from new_pump_engine
    d_confluence_family   = Column(String(20), nullable=True)            # D6/D4/D3/SECONDARY/NONE — from scanner_v2
    d_confluence_timing   = Column(String(20), nullable=True)            # SAME_BAR/LAGGED/NONE — from scanner_v2
    scanner_v2_rank       = Column(Integer,    nullable=True)            # rank within scan batch
    candidate_snapshot_json = Column(Text,     nullable=True)   # full indicators + scoring
    created_at            = Column(DateTime(timezone=True), default=datetime.utcnow)


class ReplayOutcome(Base):
    """
    Forward return outcome for one replay candidate at one time horizon.
    One candidate produces up to 4 rows (1d / 3d / 5d / 10d).
    """
    __tablename__ = "replay_outcomes"

    id                  = Column(Integer,     primary_key=True)
    replay_candidate_id = Column(Integer,     nullable=False, index=True)
    replay_run_id       = Column(Integer,     nullable=False, index=True)
    scan_date           = Column(String(10),  nullable=False)
    symbol              = Column(String(10),  nullable=False)
    horizon             = Column(String(5),   nullable=False)  # 1d | 3d | 5d | 10d
    entry_price         = Column(Float,       nullable=True)
    exit_price          = Column(Float,       nullable=True)
    return_pct          = Column(Float,       nullable=True)
    max_gain_pct        = Column(Float,       nullable=True)
    max_drawdown_pct    = Column(Float,       nullable=True)
    alpha_vs_spy        = Column(Float,       nullable=True)
    outcome_label       = Column(String(30),  nullable=True)   # SUCCESSFUL_BREAKOUT | FAILED_BREAKOUT | etc.
    # MFE (Maximum Favorable Excursion) fields
    max_high            = Column(Float,       nullable=True)   # actual high price at peak
    max_gain_day        = Column(Integer,     nullable=True)   # 0-based day offset of peak
    max_gain_date       = Column(String(10),  nullable=True)   # YYYY-MM-DD of peak
    giveback_pct        = Column(Float,       nullable=True)   # max_gain_pct - return_pct
    # Threshold hit flags (populated for horizon=10d rows; NULL for 1d/3d/5d)
    hit_5pct            = Column(Boolean,     nullable=True)
    hit_10pct           = Column(Boolean,     nullable=True)
    hit_20pct           = Column(Boolean,     nullable=True)
    hit_50pct           = Column(Boolean,     nullable=True)
    hit_100pct          = Column(Boolean,     nullable=True)
    # First day when threshold was reached (NULL if never reached)
    hit_5pct_day        = Column(Integer,     nullable=True)
    hit_10pct_day       = Column(Integer,     nullable=True)
    hit_20pct_day       = Column(Integer,     nullable=True)
    hit_50pct_day       = Column(Integer,     nullable=True)
    hit_100pct_day      = Column(Integer,     nullable=True)
    created_at          = Column(DateTime(timezone=True), default=datetime.utcnow)


class ReplayMissedMover(Base):
    """
    Strong movers that the scanner failed to flag on a given replay date.
    Populated by the missed-opportunity analysis pass.
    """
    __tablename__ = "replay_missed_movers"

    id                  = Column(Integer,     primary_key=True)
    replay_run_id       = Column(Integer,     nullable=False, index=True)
    scan_date           = Column(String(10),  nullable=False)
    symbol              = Column(String(10),  nullable=False)
    price_on_date       = Column(Float,       nullable=True)
    future_return_3d    = Column(Float,       nullable=True)
    future_return_5d    = Column(Float,       nullable=True)
    future_return_10d   = Column(Float,       nullable=True)
    why_missed          = Column(String(40),  nullable=True)
    details_json        = Column(Text,        nullable=True)
    created_at          = Column(DateTime(timezone=True), default=datetime.utcnow)


# ── Replay CRUD ───────────────────────────────────────────────────────────────

async def create_replay_run(data: dict) -> int:
    """Insert a new replay run row. Returns the new run id."""
    async with get_session_factory()() as session:
        row = ReplayRun(
            mode                = data.get("mode", "single_day"),
            status              = data.get("status", "running"),
            universe_mode       = data.get("universe_mode", "approx"),
            as_of_date          = data.get("as_of_date"),
            start_date          = data.get("start_date"),
            end_date            = data.get("end_date"),
            total_days          = data.get("total_days", 0),
            notes               = data.get("notes"),
            started_at          = datetime.utcnow(),
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


async def update_replay_run(run_id: int, data: dict) -> None:
    """Patch an existing replay run row with any fields from data."""
    async with get_session_factory()() as session:
        result = await session.execute(select(ReplayRun).where(ReplayRun.id == run_id))
        row = result.scalar_one_or_none()
        if not row:
            return
        for k, v in data.items():
            if k == "finished_at" and isinstance(v, str):
                v = datetime.fromisoformat(v)
            if hasattr(row, k):
                setattr(row, k, v)
        await session.commit()


async def get_replay_run(run_id: int) -> Optional[dict]:
    """Return a single replay run as dict, or None."""
    async with get_session_factory()() as session:
        result = await session.execute(select(ReplayRun).where(ReplayRun.id == run_id))
        row = result.scalar_one_or_none()
        return _replay_run_to_dict(row) if row else None


async def get_replay_history(limit: int = 20) -> list[dict]:
    """Return the most recent replay runs, newest first."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(ReplayRun).order_by(ReplayRun.created_at.desc()).limit(limit)
        )
        return [_replay_run_to_dict(r) for r in result.scalars().all()]


async def delete_replay_run(run_id: int) -> dict:
    """
    Hard-delete a replay run and all its linked child records.
    Returns deleted row counts per table.
    Raises ValueError if run does not exist.
    """
    async with get_session_factory()() as session:
        run = (await session.execute(
            select(ReplayRun).where(ReplayRun.id == run_id)
        )).scalar_one_or_none()
        if not run:
            raise ValueError(f"Replay run {run_id} not found")

        counts = {}

        # Children — delete in dependency order (no FK constraints enforced by SQLite,
        # but order matters for Postgres if constraints are ever added)
        for Model, label, fk in [
            (ReplaySignalCandidate, "candidates",   ReplaySignalCandidate.replay_run_id),
            (ReplayOutcome,         "outcomes",     ReplayOutcome.replay_run_id),
            (ReplayMissedMover,     "missed_movers", ReplayMissedMover.replay_run_id),
        ]:
            result = await session.execute(select(Model).where(fk == run_id))
            rows   = result.scalars().all()
            for r in rows:
                await session.delete(r)
            counts[label] = len(rows)

        await session.delete(run)
        counts["run"] = 1
        await session.commit()
        return counts


async def delete_pump_study_run(run_id: int) -> dict:
    """
    Hard-delete a pump-study run and all its linked child records.
    Returns deleted row counts per table.
    Raises ValueError if run does not exist.
    """
    async with get_session_factory()() as session:
        run = (await session.execute(
            select(PumpStudyRun).where(PumpStudyRun.id == run_id)
        )).scalar_one_or_none()
        if not run:
            raise ValueError(f"Pump study run {run_id} not found")

        counts = {}

        # Leaf tables first — snapshot and event rows hang off episodes
        for Model, label, fk in [
            (PumpEpisodeSnapshot,   "snapshots",     PumpEpisodeSnapshot.run_id),
            (PumpEpisodeEvent,      "events",        PumpEpisodeEvent.run_id),
            (PumpEpisodeDetection,  "detections",    PumpEpisodeDetection.run_id),
            (PumpComparisonMember,  "cmp_members",   PumpComparisonMember.run_id),
            (PumpComparisonGroup,   "cmp_groups",    PumpComparisonGroup.run_id),
            (PumpCluster,           "clusters",      PumpCluster.run_id),
            (PumpEpisode,           "episodes",      PumpEpisode.run_id),
            (PumpStudyAISummary,    "ai_summaries",  PumpStudyAISummary.run_id),
        ]:
            result = await session.execute(select(Model).where(fk == run_id))
            rows   = result.scalars().all()
            for r in rows:
                await session.delete(r)
            counts[label] = len(rows)

        await session.delete(run)
        counts["run"] = 1
        await session.commit()
        return counts


async def save_replay_candidates(run_id: int, scan_date: str, candidates: list[dict]) -> int:
    """Bulk-insert replay signal candidates. Returns count inserted."""
    if not candidates:
        return 0
    async with get_session_factory()() as session:
        for c in candidates:
            row = ReplaySignalCandidate(
                replay_run_id           = run_id,
                scan_date               = scan_date,
                symbol                  = c.get("symbol", ""),
                price                   = c.get("price"),
                tier                    = c.get("tier"),
                total_score             = c.get("total_score"),
                wyckoff_state           = c.get("wyckoff_state"),
                sector                  = c.get("sector"),
                new_pump_score          = c.get("new_pump_score"),
                new_pump_label          = c.get("new_pump_label"),
                new_pump_sequence_label = c.get("new_pump_sequence_label"),
                np_has_l34              = c.get("np_has_l34"),
                np_has_fri34            = c.get("np_has_fri34"),
                np_has_g4               = c.get("np_has_g4"),
                np_has_b2               = c.get("np_has_b2"),
                np_age_l34              = c.get("np_age_l34"),
                np_age_fri34            = c.get("np_age_fri34"),
                np_setup_via            = c.get("np_setup_via"),
                np_is_isolated_trigger  = c.get("np_is_isolated_trigger"),
                np_state               = c.get("np_state"),
                np_engine_path         = c.get("np_engine_path"),
                np_base_quality_score  = c.get("np_base_quality_score"),
                np_sustain_proxy_score = c.get("np_sustain_proxy_score"),
                np_sustain_profile     = c.get("np_sustain_profile"),
                np_fake_trigger_risk   = c.get("np_fake_trigger_risk"),
                np_compression_expansion_state = c.get("np_compression_expansion_state"),
                np_compression_expansion_score = c.get("np_compression_expansion_score"),
                np_compression_expansion_label = c.get("np_compression_expansion_label"),
                np_expansion_timing_risk       = c.get("np_expansion_timing_risk"),
                np_decision                    = c.get("np_decision"),
                np_decision_reason             = (c.get("np_decision_reason") or "")[:200] if c.get("np_decision_reason") else None,
                priority_score                 = c.get("priority_score"),
                priority_label                 = c.get("priority_label"),
                scanner_v2_decision            = c.get("scanner_v2_decision"),
                scanner_v2_score               = c.get("scanner_v2_score"),
                np_structure_phase             = c.get("np_structure_phase"),
                np_structure_score             = c.get("np_structure_score"),
                d_confluence_family            = c.get("d_confluence_family"),
                d_confluence_timing            = c.get("d_confluence_timing"),
                scanner_v2_rank                = c.get("scanner_v2_rank"),
                candidate_snapshot_json = json.dumps(c.get("snapshot") or {}),
            )
            session.add(row)
        await session.commit()
    return len(candidates)


async def update_replay_candidate_decision(candidate_id: int,
                                           decision: Optional[str],
                                           decision_reason: Optional[str]) -> bool:
    """
    Patch only the decision-layer fields on an existing replay candidate row.
    Used by the replay recalculation service so logic tweaks do not require
    a full universe rescan. Never touches upstream engine outputs.
    Returns True if the row was found and updated.
    """
    async with get_session_factory()() as session:
        result = await session.execute(
            select(ReplaySignalCandidate).where(ReplaySignalCandidate.id == candidate_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            return False
        row.np_decision        = decision
        row.np_decision_reason = (decision_reason or "")[:200] if decision_reason else None
        await session.commit()
        return True


async def update_replay_candidate_v2(candidate_id: int, fields: dict) -> bool:
    """
    Patch priority + Scanner v2 fields on an existing replay candidate row,
    and merge non-column extras (priority_flags/reason, scanner_v2_flags/reason,
    sector_context, macro_context, news_hype_context, sympathy_context,
    decision_flags, subsector) into the snapshot JSON blob so the research
    bundle's _cget snapshot path can read them.

    Used by the recalc_service to backfill Scanner v2 fields on existing
    replay rows without a full rescan.  Returns True if the row was found.
    """
    async with get_session_factory()() as session:
        result = await session.execute(
            select(ReplaySignalCandidate).where(ReplaySignalCandidate.id == candidate_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            return False

        # Direct columns
        if "priority_score" in fields:       row.priority_score      = fields["priority_score"]
        if "priority_label" in fields:       row.priority_label      = fields["priority_label"]
        if "scanner_v2_decision" in fields:  row.scanner_v2_decision = fields["scanner_v2_decision"]
        if "scanner_v2_score" in fields:     row.scanner_v2_score    = fields["scanner_v2_score"]
        if "np_structure_phase" in fields:   row.np_structure_phase  = fields["np_structure_phase"]
        if "np_structure_score" in fields:   row.np_structure_score  = fields["np_structure_score"]
        if "d_confluence_family" in fields:  row.d_confluence_family = fields["d_confluence_family"]
        if "d_confluence_timing" in fields:  row.d_confluence_timing = fields["d_confluence_timing"]
        if "scanner_v2_rank" in fields:      row.scanner_v2_rank     = fields["scanner_v2_rank"]

        # Snapshot-blob extras
        try:
            snap = json.loads(row.candidate_snapshot_json or "{}")
        except Exception:
            snap = {}
        for k in ("priority_flags", "priority_reason",
                  "scanner_v2_flags", "scanner_v2_reason",
                  "sector_context", "macro_context",
                  "news_hype_context", "sympathy_context",
                  "legacy_context", "decision_flags", "subsector",
                  "d_confluence_family", "d_confluence_timing", "window_explanation",
                  "structure_score_bucket", "suggested_action", "scanner_v2_rank",
                  "priority_score", "priority_label",
                  "scanner_v2_decision", "scanner_v2_score"):
            if k in fields and isinstance(
                fields[k], (int, float, str, bool, type(None), list, dict)
            ):
                snap[k] = fields[k]
        row.candidate_snapshot_json = json.dumps(snap)

        await session.commit()
        return True


async def get_replay_candidates(run_id: int, limit: int = 500) -> list[dict]:
    """Return all candidates for a replay run."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(ReplaySignalCandidate)
            .where(ReplaySignalCandidate.replay_run_id == run_id)
            .order_by(ReplaySignalCandidate.total_score.desc())
            .limit(limit)
        )
        return [_replay_candidate_to_dict(r) for r in result.scalars().all()]


async def save_replay_outcomes(outcomes: list[dict]) -> int:
    """Bulk-insert outcome rows. Returns count inserted."""
    if not outcomes:
        return 0
    async with get_session_factory()() as session:
        for o in outcomes:
            row = ReplayOutcome(
                replay_candidate_id = o["replay_candidate_id"],
                replay_run_id       = o["replay_run_id"],
                scan_date           = o["scan_date"],
                symbol              = o["symbol"],
                horizon             = o["horizon"],
                entry_price         = o.get("entry_price"),
                exit_price          = o.get("exit_price"),
                return_pct          = o.get("return_pct"),
                max_gain_pct        = o.get("max_gain_pct"),
                max_drawdown_pct    = o.get("max_drawdown_pct"),
                alpha_vs_spy        = o.get("alpha_vs_spy"),
                outcome_label       = o.get("outcome_label"),
                # MFE fields
                max_high            = o.get("max_high"),
                max_gain_day        = o.get("max_gain_day"),
                max_gain_date       = o.get("max_gain_date"),
                giveback_pct        = o.get("giveback_pct"),
                hit_5pct            = o.get("hit_5pct"),
                hit_10pct           = o.get("hit_10pct"),
                hit_20pct           = o.get("hit_20pct"),
                hit_50pct           = o.get("hit_50pct"),
                hit_100pct          = o.get("hit_100pct"),
                hit_5pct_day        = o.get("hit_5pct_day"),
                hit_10pct_day       = o.get("hit_10pct_day"),
                hit_20pct_day       = o.get("hit_20pct_day"),
                hit_50pct_day       = o.get("hit_50pct_day"),
                hit_100pct_day      = o.get("hit_100pct_day"),
            )
            session.add(row)
        await session.commit()
    return len(outcomes)


async def get_replay_outcomes(run_id: int) -> list[dict]:
    """Return all outcomes for a replay run."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(ReplayOutcome)
            .where(ReplayOutcome.replay_run_id == run_id)
            .order_by(ReplayOutcome.scan_date, ReplayOutcome.symbol, ReplayOutcome.horizon)
        )
        rows = result.scalars().all()
        return [
            {
                "id": r.id, "replay_candidate_id": r.replay_candidate_id,
                "scan_date": r.scan_date, "symbol": r.symbol,
                "horizon": r.horizon, "entry_price": r.entry_price,
                "exit_price": r.exit_price, "return_pct": r.return_pct,
                "max_gain_pct": r.max_gain_pct, "max_drawdown_pct": r.max_drawdown_pct,
                "alpha_vs_spy": r.alpha_vs_spy, "outcome_label": r.outcome_label,
                # MFE fields
                "max_high":       r.max_high,
                "max_gain_day":   r.max_gain_day,
                "max_gain_date":  r.max_gain_date,
                "giveback_pct":   r.giveback_pct,
                "hit_5pct":       r.hit_5pct,
                "hit_10pct":      r.hit_10pct,
                "hit_20pct":      r.hit_20pct,
                "hit_50pct":      r.hit_50pct,
                "hit_100pct":     r.hit_100pct,
                "hit_5pct_day":   r.hit_5pct_day,
                "hit_10pct_day":  r.hit_10pct_day,
                "hit_20pct_day":  r.hit_20pct_day,
                "hit_50pct_day":  r.hit_50pct_day,
                "hit_100pct_day": r.hit_100pct_day,
            }
            for r in rows
        ]


async def save_replay_missed_movers(run_id: int, movers: list[dict]) -> int:
    """Bulk-insert missed mover rows. Returns count inserted."""
    if not movers:
        return 0
    async with get_session_factory()() as session:
        for m in movers:
            row = ReplayMissedMover(
                replay_run_id    = run_id,
                scan_date        = m["scan_date"],
                symbol           = m["symbol"],
                price_on_date    = m.get("price_on_date"),
                future_return_3d = m.get("future_return_3d"),
                future_return_5d = m.get("future_return_5d"),
                future_return_10d= m.get("future_return_10d"),
                why_missed       = m.get("why_missed"),
                details_json     = json.dumps(m.get("details") or {}),
            )
            session.add(row)
        await session.commit()
    return len(movers)


async def get_replay_missed_movers(run_id: int) -> list[dict]:
    """Return missed movers for a replay run, sorted by forward return."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(ReplayMissedMover)
            .where(ReplayMissedMover.replay_run_id == run_id)
            .order_by(ReplayMissedMover.future_return_5d.desc().nullslast())
        )
        rows = result.scalars().all()
        return [
            {
                "id": r.id, "scan_date": r.scan_date, "symbol": r.symbol,
                "price_on_date": r.price_on_date,
                "future_return_3d": r.future_return_3d,
                "future_return_5d": r.future_return_5d,
                "future_return_10d": r.future_return_10d,
                "why_missed": r.why_missed,
                "details": json.loads(r.details_json or "{}"),
            }
            for r in rows
        ]


# ── Serialisers ───────────────────────────────────────────────────────────────

def _replay_run_to_dict(r: ReplayRun) -> dict:
    return {
        "id":                   r.id,
        "mode":                 r.mode,
        "status":               r.status,
        "universe_mode":        r.universe_mode,
        "as_of_date":           r.as_of_date,
        "start_date":           r.start_date,
        "end_date":             r.end_date,
        "total_days":           r.total_days,
        "days_completed":       r.days_completed,
        "total_symbols":        r.total_symbols,
        "total_candidates":     r.total_candidates,
        "outcomes_computed":    r.outcomes_computed,
        "missed_movers_found":  r.missed_movers_found,
        "error_message":        r.error_message,
        "notes":                r.notes,
        "started_at":           r.started_at.isoformat() if r.started_at else None,
        "finished_at":          r.finished_at.isoformat() if r.finished_at else None,
        "created_at":           r.created_at.isoformat() if r.created_at else None,
    }


def _replay_candidate_to_dict(r: ReplaySignalCandidate) -> dict:
    return {
        "id":               r.id,
        "replay_run_id":    r.replay_run_id,
        "scan_date":        r.scan_date,
        "symbol":           r.symbol,
        "price":            r.price,
        "tier":             r.tier,
        "total_score":      r.total_score,
        "wyckoff_state":           r.wyckoff_state,
        "sector":                  r.sector,
        "new_pump_score":          r.new_pump_score,
        "new_pump_label":          r.new_pump_label,
        "new_pump_sequence_label": r.new_pump_sequence_label,
        "np_has_l34":              r.np_has_l34,
        "np_has_fri34":            r.np_has_fri34,
        "np_has_g4":               r.np_has_g4,
        "np_has_b2":               r.np_has_b2,
        "np_age_l34":              r.np_age_l34,
        "np_age_fri34":            r.np_age_fri34,
        "np_setup_via":            r.np_setup_via,
        "np_is_isolated_trigger":  r.np_is_isolated_trigger,
        "np_state":                r.np_state,
        "np_engine_path":          r.np_engine_path,
        "np_base_quality_score":   r.np_base_quality_score,
        "np_sustain_proxy_score":  r.np_sustain_proxy_score,
        "np_sustain_profile":      r.np_sustain_profile,
        "np_fake_trigger_risk":    r.np_fake_trigger_risk,
        "np_compression_expansion_state": r.np_compression_expansion_state,
        "np_compression_expansion_score": r.np_compression_expansion_score,
        "np_compression_expansion_label": r.np_compression_expansion_label,
        "np_expansion_timing_risk":       r.np_expansion_timing_risk,
        "np_decision":                    r.np_decision,
        "np_decision_reason":             r.np_decision_reason,
        "priority_score":                 r.priority_score,
        "priority_label":                 r.priority_label,
        "scanner_v2_decision":            r.scanner_v2_decision,
        "scanner_v2_score":               r.scanner_v2_score,
        "np_structure_phase":             r.np_structure_phase,
        "np_structure_score":             r.np_structure_score,
        "d_confluence_family":            r.d_confluence_family,
        "d_confluence_timing":            r.d_confluence_timing,
        "scanner_v2_rank":                r.scanner_v2_rank,
        "snapshot":                json.loads(r.candidate_snapshot_json or "{}"),
        "created_at":              r.created_at.isoformat() if r.created_at else None,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# 4x PUMP STUDY — Replay-only research tables
# All tables are additive; no existing table is modified.
#
# Table hierarchy (creation order):
#   pump_study_runs
#   pump_episode_detections   ← raw hits before dedup
#   pump_clusters             ← groups of overlapping raw detections
#   pump_episodes             ← one canonical episode per cluster
#   pump_episode_snapshots    ← daily OHLCV+indicators per episode window
#   pump_episode_events       ← milestone events per episode
#   pump_comparison_groups    ← aggregate stats per comparison bucket
#   pump_comparison_members   ← one row per symbol per comparison group
# ═══════════════════════════════════════════════════════════════════════════════

class PumpStudyRun(Base):
    """
    One pump study run covering a date range.
    Tracks status, parameters, and granular completion counts.
    Replay-only — never touches live scan data.
    """
    __tablename__ = "pump_study_runs"

    id                  = Column(Integer,  primary_key=True)
    status              = Column(String(20), default="pending")  # pending|running|completed|failed
    start_date          = Column(String(10), nullable=False)
    end_date            = Column(String(10), nullable=False)
    window_days         = Column(Integer,  default=14)     # look-ahead trading-day window
    min_multiple        = Column(Float,    default=4.0)    # e.g. 4.0 = 4x
    universe_limit      = Column(Integer,  default=0)      # 0 = no limit
    # Granular counts updated as the run progresses
    symbols_scanned     = Column(Integer,  default=0)
    raw_detection_count = Column(Integer,  default=0)
    cluster_count       = Column(Integer,  default=0)
    episode_count       = Column(Integer,  default=0)
    snapshot_count      = Column(Integer,  default=0)
    event_count         = Column(Integer,  default=0)
    error_message       = Column(Text,     nullable=True)
    notes               = Column(Text,     nullable=True)
    started_at          = Column(DateTime(timezone=True), nullable=True)
    finished_at         = Column(DateTime(timezone=True), nullable=True)
    created_at          = Column(DateTime(timezone=True), default=datetime.utcnow)


class PumpEpisodeDetection(Base):
    """
    Raw detection before clustering / deduplication.
    One row per sliding-window hit (symbol + window_start + window_peak).
    Multiple rows for the same symbol may overlap in date range.
    cluster_id and is_canonical are back-filled after clustering.
    """
    __tablename__ = "pump_episode_detections"

    id                = Column(Integer,    primary_key=True)
    run_id            = Column(Integer,    nullable=False, index=True)
    symbol            = Column(String(10), nullable=False,  index=True)
    window_start_date = Column(String(10), nullable=False)
    window_peak_date  = Column(String(10), nullable=False)
    window_days       = Column(Integer,    nullable=True)
    start_price       = Column(Float,      nullable=False)
    peak_price        = Column(Float,      nullable=False)
    multiple          = Column(Float,      nullable=False)
    return_pct        = Column(Float,      nullable=False)
    days_to_peak             = Column(Integer, nullable=True)   # trading days from start to peak
    days_to_double           = Column(Integer, nullable=True)   # trading days to first 2x bar
    max_drawdown_before_peak = Column(Float,   nullable=True)   # worst low vs start_price (%)
    cluster_id               = Column(String(40), nullable=True, index=True)  # set post-cluster
    is_canonical             = Column(Boolean, default=False)
    created_at               = Column(DateTime(timezone=True), default=datetime.utcnow)


class PumpEpisode(Base):
    """
    One confirmed pump episode (deduplicated / canonical).
    One row per pump event per symbol — the best representative from each cluster.
    """
    __tablename__ = "pump_episodes"

    id                       = Column(Integer,    primary_key=True)
    run_id                   = Column(Integer,    nullable=False, index=True)
    cluster_id               = Column(String(40), nullable=True,  index=True)
    symbol                   = Column(String(10), nullable=False,  index=True)
    pump_start_date          = Column(String(10), nullable=False)
    pump_peak_date           = Column(String(10), nullable=False)
    pump_window_days         = Column(Integer,    nullable=True)
    start_price              = Column(Float,      nullable=False)
    peak_price               = Column(Float,      nullable=False)
    pump_multiple            = Column(Float,      nullable=False)
    pump_return_pct          = Column(Float,      nullable=False)
    days_to_peak             = Column(Integer,    nullable=True)
    days_to_double           = Column(Integer,    nullable=True)
    max_drawdown_before_peak = Column(Float,      nullable=True)
    pump_type                = Column(String(40), nullable=True)
    was_in_universe          = Column(Boolean,    default=False)
    was_flagged_by_scanner   = Column(Boolean,    default=False)
    filter_reason            = Column(String(80), nullable=True)
    had_ribbon               = Column(Boolean,    default=False)
    had_ignition             = Column(Boolean,    default=False)
    strongest_wyckoff_state  = Column(String(20), nullable=True)
    strongest_retest_before  = Column(String(20), nullable=True)
    max_volume_anomaly       = Column(Float,      nullable=True)
    largest_gap_pct          = Column(Float,      nullable=True)
    sector                   = Column(String(60), nullable=True)
    industry                 = Column(String(60), nullable=True)
    summary_json             = Column(Text,       nullable=True)
    created_at               = Column(DateTime(timezone=True), default=datetime.utcnow)


class PumpEpisodeSnapshot(Base):
    """
    Daily OHLCV + technical indicators for one calendar day inside an episode window.

    window_phase:            PRE | PUMP | POST
    relative_day_from_start: 0 = pump_start_date; negative = pre-pump days
    relative_day_from_peak:  0 = pump_peak_date;  negative = days before peak;
                             positive = post-peak days
    """
    __tablename__ = "pump_episode_snapshots"

    id                      = Column(Integer,    primary_key=True)
    episode_id              = Column(Integer,    nullable=False, index=True)
    run_id                  = Column(Integer,    nullable=False, index=True)
    symbol                  = Column(String(10), nullable=False)
    date                    = Column(String(10), nullable=False)
    window_phase            = Column(String(6),  nullable=True)   # PRE | PUMP | POST
    relative_day_from_start = Column(Integer,    nullable=True)   # trading days from start
    relative_day_from_peak  = Column(Integer,    nullable=True)   # trading days from peak
    # OHLCV
    open                    = Column(Float,      nullable=True)
    high                    = Column(Float,      nullable=True)
    low                     = Column(Float,      nullable=True)
    close                   = Column(Float,      nullable=True)
    volume                  = Column(BigInteger, nullable=True)
    # Derived OHLCV
    gap_pct                 = Column(Float,      nullable=True)
    intraday_range_pct      = Column(Float,      nullable=True)
    close_position          = Column(Float,      nullable=True)   # 0–1 position in bar
    daily_return_pct        = Column(Float,      nullable=True)
    cum_return_pct          = Column(Float,      nullable=True)   # from pump start price
    # Volume
    volume_vs_avg20         = Column(Float,      nullable=True)
    volume_zscore           = Column(Float,      nullable=True)
    # Technicals
    atr_pct                 = Column(Float,      nullable=True)
    bb_width                = Column(Float,      nullable=True)
    bb_squeeze              = Column(Boolean,    nullable=True)
    rsi                     = Column(Float,      nullable=True)
    cmf                     = Column(Float,      nullable=True)
    # Structure signals
    ribbon_class            = Column(String(30), nullable=True)
    wyckoff_state           = Column(String(20), nullable=True)
    # Full raw snapshot for auditing / future reprocessing
    snapshot_json           = Column(Text,       nullable=True)
    created_at              = Column(DateTime(timezone=True), default=datetime.utcnow)


class PumpEpisodeEvent(Base):
    """
    Key timeline milestones detected inside an episode window.

    event_value:       optional quantitative value for the event
                       (e.g. return_pct at that milestone, volume ratio, etc.)
    event_detail_json: optional structured dict with extra context
    days_before_pump:  offset from pump_start_date
                       (negative = before start, 0 = start, positive = after)
    """
    __tablename__ = "pump_episode_events"

    id                = Column(Integer,    primary_key=True)
    episode_id        = Column(Integer,    nullable=False, index=True)
    run_id            = Column(Integer,    nullable=False, index=True)
    symbol            = Column(String(10), nullable=False)
    event_date        = Column(String(10), nullable=False)
    event_type        = Column(String(50), nullable=False)
    event_value       = Column(Float,      nullable=True)   # quantitative value
    event_detail_json = Column(Text,       nullable=True)   # structured detail dict
    event_note        = Column(Text,       nullable=True)   # human-readable note
    days_before_pump  = Column(Integer,    nullable=True)   # offset from pump_start_date
    created_at        = Column(DateTime(timezone=True), default=datetime.utcnow)


class PumpCluster(Base):
    """
    Symbol-level clustering result.
    Multiple overlapping raw detections for the same symbol collapse into one cluster.
    The canonical detection has the earliest start date within the cluster.
    """
    __tablename__ = "pump_clusters"

    id                   = Column(Integer,    primary_key=True)
    run_id               = Column(Integer,    nullable=False, index=True)
    cluster_id           = Column(String(40), nullable=False, index=True)
    symbol               = Column(String(10), nullable=False)
    canonical_episode_id = Column(Integer,    nullable=True)
    cluster_start_date   = Column(String(10), nullable=True)
    cluster_end_date     = Column(String(10), nullable=True)
    canonical_start_date = Column(String(10), nullable=True)
    canonical_peak_date  = Column(String(10), nullable=True)
    raw_detection_count  = Column(Integer,    default=1)
    created_at           = Column(DateTime(timezone=True), default=datetime.utcnow)


class PumpComparisonGroup(Base):
    """
    Aggregate statistical summary for one comparison bucket.
    Buckets: 4x_pump | normal_winner | false_positive | missed

    member_count: number of symbols in this group (also len of PumpComparisonMember rows)
    stats_json:   feature distribution dict (mean / median / p25 / p75 per feature)
    """
    __tablename__ = "pump_comparison_groups"

    id           = Column(Integer,    primary_key=True)
    run_id       = Column(Integer,    nullable=False, index=True)
    group_name   = Column(String(30), nullable=False)
    member_count = Column(Integer,    default=0)
    stats_json   = Column(Text,       nullable=True)   # feature distribution dict
    created_at   = Column(DateTime(timezone=True), default=datetime.utcnow)


class PumpComparisonMember(Base):
    """
    One symbol's membership in a comparison group.
    Stores the per-member features used to compute group aggregate stats.
    """
    __tablename__ = "pump_comparison_members"

    id             = Column(Integer,    primary_key=True)
    group_id       = Column(Integer,    nullable=False, index=True)
    run_id         = Column(Integer,    nullable=False, index=True)
    group_name     = Column(String(30), nullable=False)
    symbol         = Column(String(10), nullable=False)
    episode_id     = Column(Integer,    nullable=True)
    pump_multiple  = Column(Float,      nullable=True)
    pump_return_pct= Column(Float,      nullable=True)
    days_to_peak   = Column(Integer,    nullable=True)
    pump_type      = Column(String(40), nullable=True)
    features_json  = Column(Text,       nullable=True)   # per-member feature dict
    created_at     = Column(DateTime(timezone=True), default=datetime.utcnow)


class PumpStudyAISummary(Base):
    """
    AI-generated pattern analysis for one pump-study run.
    Generated lazily on first request; immutable after creation.
    Run-scoped, replay-scoped only — never touches live scanner state.
    """
    __tablename__ = "pump_study_ai_summaries"

    id             = Column(Integer,     primary_key=True)
    run_id         = Column(Integer,     nullable=False, unique=True, index=True)
    # Parsed analysis object as JSON string
    analysis_json  = Column(Text,        nullable=True)
    # Top-level recommendation string (one of the allowed slugs)
    recommendation = Column(String(100), nullable=True)
    # Serialised evidence bundle fed to the model (for auditing)
    evidence_json  = Column(Text,        nullable=True)
    # Limitations paragraph (missing catalyst/news note)
    limitations    = Column(Text,        nullable=True)
    model_used     = Column(String(60),  nullable=True)
    # Parse-failure audit columns (added post-initial-deployment via migration)
    parse_failed   = Column(Boolean,     default=False, nullable=True)
    raw_response   = Column(Text,        nullable=True)   # raw model text on failure
    parse_error    = Column(Text,        nullable=True)   # exception string on failure
    created_at     = Column(DateTime(timezone=True), default=datetime.utcnow)


# ═══════════════════════════════════════════════════════════════════════════════
# RAW PATTERN STUDY — Feature Discovery Layer
# ───────────────────────────────────────────────────────────────────────────────
# Purpose: extract, store, and compare raw candle/volume/volatility/structure
# features across the four canonical groups (4x_pump, normal_winner,
# false_positive, missed_mover) so that repeating pre-conditions can be
# discovered empirically — before any template or matching logic is built.
#
# Data source: pump_episode_snapshots + pump_episodes from an existing
# pump_study_run.  No new candle fetching.
#
# Table hierarchy (creation order):
#   raw_pattern_runs
#   raw_pattern_daily_features     ← one row per episode × day (PRE/PUMP/POST)
#   raw_pattern_episode_features   ← aggregated feature vector per episode
#   raw_pattern_comparisons        ← per-feature stats per group (normalised)
#   raw_pattern_comparison_members ← one membership row per symbol per group
# ═══════════════════════════════════════════════════════════════════════════════

class RawPatternRun(Base):
    """
    One raw-pattern discovery run.
    Optionally linked to an existing pump_study_run as data source.
    status: pending | running | completed | failed
    """
    __tablename__ = "raw_pattern_runs"

    id                    = Column(Integer,    primary_key=True)
    pump_study_run_id     = Column(Integer,    nullable=True, index=True)  # FK → pump_study_runs.id (nullable for standalone)
    status                = Column(String(20), default="pending")
    start_date            = Column(String(10), nullable=True)
    end_date              = Column(String(10), nullable=True)
    # Progress counters
    raw_daily_count       = Column(Integer, default=0)
    episode_feature_count = Column(Integer, default=0)
    comparison_count      = Column(Integer, default=0)
    # Metadata
    notes                 = Column(Text, nullable=True)
    error_message         = Column(Text, nullable=True)
    started_at            = Column(DateTime(timezone=True), nullable=True)
    finished_at           = Column(DateTime(timezone=True), nullable=True)
    created_at            = Column(DateTime(timezone=True), default=datetime.utcnow)


class RawPatternDailyFeatures(Base):
    """
    One row per episode × calendar day (PRE / PUMP / POST phases).
    Derived from pump_episode_snapshots.snapshot_json — no re-fetch of candles.

    Adds fields not stored as snapshot columns plus full candle anatomy,
    multi-timeframe volume ratios, compression/volatility state, distance
    context, and candle-level pattern flags.  Overflow fields go to
    feature_json.
    """
    __tablename__ = "raw_pattern_daily_features"

    id         = Column(Integer,    primary_key=True)
    run_id     = Column(Integer,    nullable=False, index=True)   # FK → raw_pattern_runs.id
    episode_id = Column(Integer,    nullable=False, index=True)   # FK → pump_episodes.id
    symbol     = Column(String(10), index=True)
    date       = Column(String(10))

    # ── Window context ─────────────────────────────────────────────────────────
    phase                    = Column(String(6),  nullable=True)   # PRE | PUMP | POST
    relative_day_from_start  = Column(Integer,    nullable=True)   # neg=pre, 0=start, pos=post
    relative_day_from_peak   = Column(Integer,    nullable=True)

    # ── Instrument / context ───────────────────────────────────────────────────
    sector                   = Column(String(60), nullable=True)
    industry                 = Column(String(80), nullable=True)
    exchange                 = Column(String(20), nullable=True)
    market_cap               = Column(Float,      nullable=True)
    float_shares             = Column(Float,      nullable=True)   # shares float ("float" is a builtin)
    market_regime            = Column(String(20), nullable=True)   # e.g. BULL|BEAR|CHOPPY

    # ── Raw OHLCV ─────────────────────────────────────────────────────────────
    open                     = Column(Float,      nullable=True)
    high                     = Column(Float,      nullable=True)
    low                      = Column(Float,      nullable=True)
    close                    = Column(Float,      nullable=True)
    volume                   = Column(BigInteger, nullable=True)
    dollar_volume            = Column(Float,      nullable=True)   # close × volume

    # ── Candle anatomy ─────────────────────────────────────────────────────────
    gap_pct                  = Column(Float,   nullable=True)   # (open - prev_close) / prev_close
    intraday_range_pct       = Column(Float,   nullable=True)   # (high - low) / open
    body_pct                 = Column(Float,   nullable=True)   # |close-open| / (high-low)
    upper_wick_pct           = Column(Float,   nullable=True)   # (high - max(open,close)) / (high-low)
    lower_wick_pct           = Column(Float,   nullable=True)   # (min(open,close) - low) / (high-low)
    close_position_in_bar    = Column(Float,   nullable=True)   # 0–1 position of close in day's range
    wide_range_bar           = Column(Boolean, nullable=True)   # intraday_range > 1.5× 20d avg
    narrow_range_bar         = Column(Boolean, nullable=True)   # intraday_range < 0.5× 20d avg
    strong_close_near_high   = Column(Boolean, nullable=True)   # close_position >= 0.80
    weak_close_near_low      = Column(Boolean, nullable=True)   # close_position <= 0.20

    # ── Volume / liquidity ─────────────────────────────────────────────────────
    volume_vs_avg5           = Column(Float,   nullable=True)
    volume_vs_avg10          = Column(Float,   nullable=True)
    volume_vs_avg20          = Column(Float,   nullable=True)
    volume_zscore            = Column(Float,   nullable=True)
    dollar_volume_vs_avg20   = Column(Float,   nullable=True)
    abnormal_volume_day      = Column(Boolean, nullable=True)   # vol_vs_avg20>=2.0 OR vol_z>=2.5
    dryup_day                = Column(Boolean, nullable=True)   # vol_vs_avg20 < 0.5 (quiet)

    # ── Volatility / compression ───────────────────────────────────────────────
    atr                      = Column(Float,    nullable=True)   # absolute ATR value
    atr_pct                  = Column(Float,    nullable=True)   # ATR as % of price
    atr_expansion_state      = Column(String(12), nullable=True) # EXPANDING|CONTRACTING|NEUTRAL
    bb_width                 = Column(Float,    nullable=True)
    bb_squeeze_bars          = Column(Integer,  nullable=True)   # consecutive squeeze bar count
    ema_spread_pct           = Column(Float,    nullable=True)   # (max_ema - min_ema) / price * 100
    compression_state        = Column(String(10), nullable=True) # STRONG|MEDIUM|WEAK|NONE (ribbon_compression)

    # ── Distance / range context ───────────────────────────────────────────────
    distance_to_range_high   = Column(Float, nullable=True)     # (52w_high - close) / close pct
    distance_to_range_low    = Column(Float, nullable=True)     # (close - 52w_low) / close pct
    distance_to_mid_range    = Column(Float, nullable=True)     # (close - mid) / mid pct

    # ── Candle-level pattern flags ─────────────────────────────────────────────
    bullish_engulfing        = Column(Boolean, nullable=True)
    bearish_engulfing        = Column(Boolean, nullable=True)
    inside_bar               = Column(Boolean, nullable=True)
    outside_bar              = Column(Boolean, nullable=True)
    doji_like                = Column(Boolean, nullable=True)   # body_pct < 0.10
    reclaim_bar              = Column(Boolean, nullable=True)   # gap-down open, close above prev close
    expansion_bar            = Column(Boolean, nullable=True)   # wide_range_bar + strong_close + above-avg vol

    # ── Overflow ───────────────────────────────────────────────────────────────
    feature_json             = Column(Text, nullable=True)      # extra payload not yet promoted to columns

    created_at               = Column(DateTime(timezone=True), default=datetime.utcnow)


class RawPatternEpisodeFeatures(Base):
    """
    Aggregated feature vector for one episode.
    Computed from its RawPatternDailyFeatures rows (PRE / PUMP / POST sections).
    PRE-window aggregates are the primary discovery focus.

    group_type assigns each episode into one of the four canonical buckets
    (4x_pump | normal_winner | false_positive | missed_mover).
    """
    __tablename__ = "raw_pattern_episode_features"

    id           = Column(Integer,    primary_key=True)
    run_id       = Column(Integer,    nullable=False, index=True)
    episode_id   = Column(Integer,    nullable=False, index=True)   # FK → pump_episodes.id
    symbol       = Column(String(10))
    group_type   = Column(String(30), nullable=True, index=True)    # 4x_pump|normal_winner|false_positive|missed_mover
    pump_multiple= Column(Float,      nullable=True)
    pump_type    = Column(String(40), nullable=True)

    # ── Timing / phase lengths ─────────────────────────────────────────────────
    pre_days                                    = Column(Integer, nullable=True)
    pump_days                                   = Column(Integer, nullable=True)
    post_days                                   = Column(Integer, nullable=True)
    days_in_base                                = Column(Integer, nullable=True)  # consecutive compression days before breakout
    days_from_first_abnormal_volume_to_breakout = Column(Integer, nullable=True)
    days_from_breakout_to_peak                  = Column(Integer, nullable=True)
    days_from_first_compression_to_breakout     = Column(Integer, nullable=True)

    # ── PRE-window: candle aggregates ─────────────────────────────────────────
    avg_body_pct_pre           = Column(Float,   nullable=True)
    avg_upper_wick_pct_pre     = Column(Float,   nullable=True)
    avg_lower_wick_pct_pre     = Column(Float,   nullable=True)
    wide_range_bar_count_pre   = Column(Integer, nullable=True)
    narrow_range_bar_count_pre = Column(Integer, nullable=True)
    strong_close_count_pre     = Column(Integer, nullable=True)

    # ── PRE-window: pattern counts ────────────────────────────────────────────
    bullish_engulfing_count_pre = Column(Integer, nullable=True)
    bearish_engulfing_count_pre = Column(Integer, nullable=True)
    inside_bar_count_pre        = Column(Integer, nullable=True)
    outside_bar_count_pre       = Column(Integer, nullable=True)
    reclaim_bar_count_pre       = Column(Integer, nullable=True)
    expansion_bar_count_pre     = Column(Integer, nullable=True)

    # ── PRE-window: volume aggregates ─────────────────────────────────────────
    max_volume_anomaly_pre        = Column(Float,   nullable=True)
    median_volume_anomaly_pre     = Column(Float,   nullable=True)
    abnormal_volume_day_count_pre = Column(Integer, nullable=True)
    dryup_day_count_pre           = Column(Integer, nullable=True)
    max_dollar_volume_pre         = Column(Float,   nullable=True)

    # ── PRE-window: compression / volatility ──────────────────────────────────
    had_compression              = Column(Boolean, nullable=True)
    compression_days_pre         = Column(Integer, nullable=True)
    min_bb_width_pre             = Column(Float,   nullable=True)
    avg_atr_pct_pre              = Column(Float,   nullable=True)
    atr_contraction_days_pre     = Column(Integer, nullable=True)  # days with atr_expansion_state=CONTRACTING

    # ── PRE-window: EMA ribbon aggregates (from feature_json) ─────────────────
    had_bull_stack_pre           = Column(Boolean, nullable=True)  # any day had bullish_stack=True
    bull_stack_days_pre          = Column(Integer, nullable=True)  # count of bullish_stack days
    days_above_ema50_pre         = Column(Integer, nullable=True)
    days_above_ema200_pre        = Column(Integer, nullable=True)
    ema50_reclaim_count_pre      = Column(Integer, nullable=True)  # ema50_reclaim_day events in PRE
    avg_close_vs_ema50_pct_pre   = Column(Float,   nullable=True)  # mean (close-ema50)/ema50 %
    avg_close_vs_ema200_pct_pre  = Column(Float,   nullable=True)  # mean (close-ema200)/ema200 %

    # ── PRE-window: structure / sequence ──────────────────────────────────────
    had_accumulation_like         = Column(Boolean,    nullable=True)
    accumulation_like_day_count   = Column(Integer,    nullable=True)
    had_spring_test_lps           = Column(Boolean,    nullable=True)
    had_breakout_retest           = Column(Boolean,    nullable=True)
    retest_count                  = Column(Integer,    nullable=True)
    avg_retest_quality            = Column(Float,      nullable=True)
    strongest_wyckoff_state       = Column(String(20), nullable=True)
    strongest_sequence_type       = Column(String(40), nullable=True)  # e.g. ACCUMULATION_SPRING_ARM
    strongest_structural_bias     = Column(String(20), nullable=True)  # BULLISH|BEARISH|NEUTRAL

    # ── New Pump engine episode aggregates ─────────────────────────────────────
    had_valid_recent_setup        = Column(Boolean,    nullable=True)  # fresh L34 or FRI34 ≤ age_max
    had_valid_recent_trigger      = Column(Boolean,    nullable=True)  # fresh G4 ≤ age_max
    had_valid_recent_confirm      = Column(Boolean,    nullable=True)  # fresh B2 ≤ age_max
    had_valid_full_sequence       = Column(Boolean,    nullable=True)  # all three valid + gaps ok
    best_new_pump_label_rank      = Column(Integer,    nullable=True)  # FIRE=0…NONE=5
    best_new_pump_sequence_type   = Column(String(40), nullable=True)  # NP sequence label at scan date
    days_from_last_setup_to_breakout   = Column(Integer, nullable=True)
    days_from_last_trigger_to_breakout = Column(Integer, nullable=True)
    days_from_g4_to_b2            = Column(Integer,    nullable=True)  # G4→B2 confirmation gap
    max_bull_stack_days_pre       = Column(Integer,    nullable=True)  # longest consecutive bull-stack run
    extreme_anomaly_day_count_pre = Column(Integer,    nullable=True)  # vol_z>4 OR range>3×avg days
    median_dollar_volume_pre      = Column(Float,      nullable=True)
    np_skip_reason                = Column(String(40), nullable=True)  # why NP phase was skipped
    # NP count-based PRE-window aggregates
    l34_count_pre                 = Column(Integer,    nullable=True)
    fri34_count_pre               = Column(Integer,    nullable=True)
    g4_count_pre                  = Column(Integer,    nullable=True)
    b2_count_pre                  = Column(Integer,    nullable=True)
    setup_only_l34_count_pre      = Column(Integer,    nullable=True)
    setup_only_fri34_count_pre    = Column(Integer,    nullable=True)
    trigger_after_l34_count_pre   = Column(Integer,    nullable=True)
    trigger_after_fri34_count_pre = Column(Integer,    nullable=True)
    full_l34_g4_b2_count_pre      = Column(Integer,    nullable=True)
    full_fri34_g4_b2_count_pre    = Column(Integer,    nullable=True)
    isolated_g4_count_pre         = Column(Integer,    nullable=True)
    isolated_b2_count_pre         = Column(Integer,    nullable=True)
    confirm_after_g4_count_pre    = Column(Integer,    nullable=True)
    valid_setup_days_pre          = Column(Integer,    nullable=True)
    valid_trigger_days_pre        = Column(Integer,    nullable=True)
    valid_confirm_days_pre        = Column(Integer,    nullable=True)
    valid_full_sequence_days_pre  = Column(Integer,    nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    sector     = Column(String(50),  nullable=True)
    industry   = Column(String(100), nullable=True)

    # ── Split / corporate action episode features ──────────────────────────────
    has_split_near_episode           = Column(Boolean,    nullable=True)
    has_reverse_split_near_episode   = Column(Boolean,    nullable=True)
    has_forward_split_near_episode   = Column(Boolean,    nullable=True)
    split_event_count                = Column(Integer,    nullable=True)
    reverse_split_event_count        = Column(Integer,    nullable=True)
    forward_split_event_count        = Column(Integer,    nullable=True)
    nearest_split_date               = Column(String(10), nullable=True)
    nearest_split_type               = Column(String(30), nullable=True)
    nearest_split_ratio              = Column(Float,      nullable=True)
    nearest_split_days_from_breakout = Column(Integer,    nullable=True)
    nearest_split_days_from_pump_start = Column(Integer,  nullable=True)
    nearest_split_days_from_peak     = Column(Integer,    nullable=True)
    reverse_split_0_5d_before_breakout  = Column(Boolean, nullable=True)
    reverse_split_6_15d_before_breakout = Column(Boolean, nullable=True)
    reverse_split_16_30d_before_breakout = Column(Boolean, nullable=True)
    reverse_split_31_60d_before_breakout = Column(Boolean, nullable=True)
    reverse_split_after_breakout     = Column(Boolean,    nullable=True)
    split_during_pump_window         = Column(Boolean,    nullable=True)
    split_after_peak_30d             = Column(Boolean,    nullable=True)
    split_context                    = Column(String(30), nullable=True)
    split_artifact_risk              = Column(Boolean,    nullable=True)
    split_artifact_reason            = Column(Text,       nullable=True)
    split_adjusted_move_estimate     = Column(Float,      nullable=True)
    raw_move_pct                     = Column(Float,      nullable=True)

    # ── Scanner v2 / NP structural fields (Phase 2B-7) ────────────────────────
    # Structure phase aggregates
    dominant_structure_phase_pre      = Column(String(30), nullable=True)
    best_structure_phase_pre          = Column(String(30), nullable=True)
    max_structure_score_pre           = Column(Integer,    nullable=True)
    avg_structure_score_pre           = Column(Float,      nullable=True)
    had_confirmed_structure_pre       = Column(Boolean,    nullable=True)
    had_triggered_structure_pre       = Column(Boolean,    nullable=True)
    had_early_structure_pre           = Column(Boolean,    nullable=True)
    had_setup_phase_pre               = Column(Boolean,    nullable=True)
    had_impulse_only_pre              = Column(Boolean,    nullable=True)
    had_degraded_pre                  = Column(Boolean,    nullable=True)
    # Compression / expansion
    had_accumulation_ready_pre        = Column(Boolean,    nullable=True)
    had_expansion_start_pre           = Column(Boolean,    nullable=True)
    had_overheated_expansion_pre      = Column(Boolean,    nullable=True)
    max_expansion_timing_risk_pre     = Column(String(10), nullable=True)
    high_expansion_risk_day_count_pre = Column(Integer,    nullable=True)
    # D/WLNBB confluence
    had_d_confluence_pre              = Column(Boolean,    nullable=True)
    had_core_d_beup_pre               = Column(Boolean,    nullable=True)
    had_core_d_l34_pre                = Column(Boolean,    nullable=True)
    had_d6_beup_pre                   = Column(Boolean,    nullable=True)
    had_d4_beup_pre                   = Column(Boolean,    nullable=True)
    had_d3_beup_pre                   = Column(Boolean,    nullable=True)
    had_l34_then_d4_3b_pre            = Column(Boolean,    nullable=True)
    had_d4_then_beup_5b_pre           = Column(Boolean,    nullable=True)
    had_d3_beup_toxic_pre             = Column(Boolean,    nullable=True)
    dominant_d_confluence_type_pre    = Column(String(30), nullable=True)
    dominant_d_confluence_family_pre  = Column(String(30), nullable=True)
    d_confluence_day_count_pre        = Column(Integer,    nullable=True)
    d_confluence_best_type_pre        = Column(String(30), nullable=True)
    # Decision / routing
    had_np_buy_candidate_pre          = Column(Boolean,    nullable=True)
    had_np_watch_pre                  = Column(Boolean,    nullable=True)
    had_np_avoid_pre                  = Column(Boolean,    nullable=True)
    max_np_structure_score_pre        = Column(Integer,    nullable=True)
    buy_candidate_day_count_pre       = Column(Integer,    nullable=True)
    watch_day_count_pre               = Column(Integer,    nullable=True)
    avoid_day_count_pre               = Column(Integer,    nullable=True)
    # NP flags
    had_late_confirm_sequence_pre     = Column(Boolean,    nullable=True)
    had_expansion_risk_flag_pre       = Column(Boolean,    nullable=True)
    had_setup_only_l34_mid_avoid_pre  = Column(Boolean,    nullable=True)
    # Pattern Discovery / Pump Watch fields (Phase 2B-PD)
    pump_watch_score                  = Column(Integer,    nullable=True)
    pump_watch_label                  = Column(String(30), nullable=True)
    pump_watch_reasons                = Column(Text,       nullable=True)   # JSON list
    pump_watch_risk_flags             = Column(Text,       nullable=True)   # JSON list
    pump_watch_pattern_ids            = Column(Text,       nullable=True)   # JSON list
    pump_watch_split_context          = Column(String(30), nullable=True)
    pump_watch_confidence             = Column(String(10), nullable=True)
    pump_watch_diagnostic_labels      = Column(Text,       nullable=True)   # JSON list
    pump_watch_pattern_id             = Column(String(60), nullable=True)
    pump_watch_rescue_reason          = Column(String(80), nullable=True)


class RawPatternComparison(Base):
    """
    Per-feature distribution stats for one group within a raw-pattern run.
    Normalised: one row per (run_id, group_name, feature_name).

    stats_json holds any additional distribution fields (std, pct_nonzero,
    sample_count, etc.) that don't warrant dedicated columns.
    """
    __tablename__ = "raw_pattern_comparisons"

    id           = Column(Integer,    primary_key=True)
    run_id       = Column(Integer,    nullable=False, index=True)
    group_name   = Column(String(30), nullable=False, index=True)   # 4x_pump|normal_winner|false_positive|missed_mover
    feature_name = Column(String(80), nullable=False)
    member_count = Column(Integer,    default=0)
    mean_value   = Column(Float,      nullable=True)
    median_value = Column(Float,      nullable=True)
    p25_value    = Column(Float,      nullable=True)
    p75_value    = Column(Float,      nullable=True)
    p90_value    = Column(Float,      nullable=True)
    stats_json   = Column(Text,       nullable=True)                # std, pct_nonzero, etc.
    created_at   = Column(DateTime(timezone=True), default=datetime.utcnow)


class RawPatternComparisonMember(Base):
    """
    One symbol's membership in a raw-pattern comparison group.
    features_json carries the full episode-feature dict so that group
    statistics can be computed or recomputed without re-reading episode rows.
    """
    __tablename__ = "raw_pattern_comparison_members"

    id            = Column(Integer,    primary_key=True)
    run_id        = Column(Integer,    nullable=False, index=True)
    group_name    = Column(String(30), nullable=False, index=True)   # denormalized
    symbol        = Column(String(10), nullable=False)
    episode_id    = Column(Integer,    nullable=True)                 # FK → pump_episodes.id; null for missed_mover
    features_json = Column(Text,       nullable=True)                 # full episode feature dict for stats aggregation
    created_at    = Column(DateTime(timezone=True), default=datetime.utcnow)


class RawPatternAISummary(Base):
    """
    AI-generated analysis for one raw-pattern study run.
    Generated lazily on first request; immutable after creation.
    Replay-scoped only — never touches live scanner state.
    """
    __tablename__ = "raw_pattern_ai_summaries"

    id             = Column(Integer,     primary_key=True)
    run_id         = Column(Integer,     nullable=False, unique=True, index=True)
    analysis_json  = Column(Text,        nullable=True)   # parsed analysis object
    recommendation = Column(String(200), nullable=True)   # top-level recommendation string
    evidence_json  = Column(Text,        nullable=True)   # serialised evidence bundle (audit)
    limitations    = Column(Text,        nullable=True)
    model_used     = Column(String(60),  nullable=True)
    parse_failed   = Column(Boolean,     default=False, nullable=True)
    raw_response   = Column(Text,        nullable=True)   # raw model text on failure
    parse_error    = Column(Text,        nullable=True)   # exception string on failure
    created_at     = Column(DateTime(timezone=True), default=datetime.utcnow)


class DiscoveredPattern(Base):
    """
    Mined pattern candidates from the Pattern Discovery Engine.
    One row per (run_id, signal_id) — updated on each discovery run.
    """
    __tablename__ = "discovered_patterns"

    id                     = Column(Integer,  primary_key=True)
    run_id                 = Column(Integer,  nullable=False, index=True)
    signal_id              = Column(String(60), nullable=False, index=True)
    source_type            = Column(String(30), nullable=True)
    feature_family         = Column(String(30), nullable=True)
    family                 = Column(String(10), nullable=True)
    status                 = Column(String(30), nullable=True)
    intended_use           = Column(String(30), nullable=True)
    description            = Column(Text,       nullable=True)
    count_missed_4x        = Column(Integer,  nullable=True)
    count_detected_4x      = Column(Integer,  nullable=True)
    count_all_4x           = Column(Integer,  nullable=True)
    count_false_positive   = Column(Integer,  nullable=True)
    count_normal_winner    = Column(Integer,  nullable=True)
    count_split_artifact   = Column(Integer,  nullable=True)
    lift_vs_false_positive = Column(Float,    nullable=True)
    lift_vs_normal_winner  = Column(Float,    nullable=True)
    precision_estimate     = Column(Float,    nullable=True)
    recall_all_4x          = Column(Float,    nullable=True)
    false_positive_rate    = Column(Float,    nullable=True)
    split_artifact_exposure= Column(Float,    nullable=True)
    reverse_split_exposure = Column(Float,    nullable=True)
    recommendation         = Column(String(30), nullable=True)
    machine_conditions_json= Column(Text,       nullable=True)
    created_at             = Column(DateTime(timezone=True), default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("run_id", "signal_id", name="uq_discovered_pattern_run_signal"),
    )


# ── Pump Study CRUD ───────────────────────────────────────────────────────────

async def create_pump_study_run(data: dict) -> int:
    async with get_session_factory()() as session:
        row = PumpStudyRun(
            status         = "pending",
            start_date     = data["start_date"],
            end_date       = data["end_date"],
            window_days    = data.get("window_days",    14),
            min_multiple   = data.get("min_multiple",   4.0),
            universe_limit = data.get("universe_limit", 0),
            notes          = data.get("notes"),
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


async def update_pump_study_run(run_id: int, data: dict) -> None:
    async with get_session_factory()() as session:
        result = await session.execute(select(PumpStudyRun).where(PumpStudyRun.id == run_id))
        row = result.scalar_one_or_none()
        if not row:
            return
        for k, v in data.items():
            if hasattr(row, k):
                setattr(row, k, v)
        await session.commit()


async def get_pump_study_run(run_id: int) -> Optional[dict]:
    async with get_session_factory()() as session:
        result = await session.execute(select(PumpStudyRun).where(PumpStudyRun.id == run_id))
        row = result.scalar_one_or_none()
        return _pump_study_run_to_dict(row) if row else None


async def get_pump_study_runs(limit: int = 20) -> list[dict]:
    async with get_session_factory()() as session:
        result = await session.execute(
            select(PumpStudyRun).order_by(PumpStudyRun.created_at.desc()).limit(limit)
        )
        return [_pump_study_run_to_dict(r) for r in result.scalars().all()]


# ── Raw detections ────────────────────────────────────────────────────────────

async def save_pump_episode_detections(run_id: int, detections: list[dict]) -> int:
    """Bulk-insert raw detections. Returns count inserted."""
    if not detections:
        return 0
    async with get_session_factory()() as session:
        for d in detections:
            row = PumpEpisodeDetection(
                run_id                   = run_id,
                symbol                   = d["symbol"],
                window_start_date        = d["window_start_date"],
                window_peak_date         = d["window_peak_date"],
                window_days              = d.get("window_days"),
                start_price              = d["start_price"],
                peak_price               = d["peak_price"],
                multiple                 = d["multiple"],
                return_pct               = d["return_pct"],
                days_to_peak             = d.get("days_to_peak"),
                days_to_double           = d.get("days_to_double"),
                max_drawdown_before_peak = d.get("max_drawdown_before_peak"),
                cluster_id               = d.get("cluster_id"),
                is_canonical             = d.get("is_canonical", False),
            )
            session.add(row)
        await session.commit()
    return len(detections)


async def get_pump_episode_detections(run_id: int) -> list[dict]:
    async with get_session_factory()() as session:
        result = await session.execute(
            select(PumpEpisodeDetection)
            .where(PumpEpisodeDetection.run_id == run_id)
            .order_by(PumpEpisodeDetection.symbol, PumpEpisodeDetection.window_start_date)
        )
        rows = result.scalars().all()
        return [
            {
                "id":                       r.id,
                "symbol":                   r.symbol,
                "window_start_date":        r.window_start_date,
                "window_peak_date":         r.window_peak_date,
                "window_days":              r.window_days,
                "start_price":              r.start_price,
                "peak_price":               r.peak_price,
                "multiple":                 r.multiple,
                "return_pct":               r.return_pct,
                "days_to_peak":             r.days_to_peak,
                "days_to_double":           r.days_to_double,
                "max_drawdown_before_peak": r.max_drawdown_before_peak,
                "cluster_id":               r.cluster_id,
                "is_canonical":             r.is_canonical,
            }
            for r in rows
        ]


# ── Episodes ──────────────────────────────────────────────────────────────────

async def save_pump_episodes(run_id: int, episodes: list[dict]) -> list[int]:
    """Bulk-insert pump episodes. Returns list of inserted IDs."""
    ids = []
    async with get_session_factory()() as session:
        for ep in episodes:
            row = PumpEpisode(
                run_id                   = run_id,
                cluster_id               = ep.get("cluster_id"),
                symbol                   = ep["symbol"],
                pump_start_date          = ep["pump_start_date"],
                pump_peak_date           = ep["pump_peak_date"],
                pump_window_days         = ep.get("pump_window_days"),
                start_price              = ep["start_price"],
                peak_price               = ep["peak_price"],
                pump_multiple            = ep["pump_multiple"],
                pump_return_pct          = ep["pump_return_pct"],
                days_to_peak             = ep.get("days_to_peak"),
                days_to_double           = ep.get("days_to_double"),
                max_drawdown_before_peak = ep.get("max_drawdown_before_peak"),
                pump_type                = ep.get("pump_type"),
                was_in_universe          = ep.get("was_in_universe", False),
                was_flagged_by_scanner   = ep.get("was_flagged_by_scanner", False),
                filter_reason            = ep.get("filter_reason"),
                had_ribbon               = ep.get("had_ribbon", False),
                had_ignition             = ep.get("had_ignition", False),
                strongest_wyckoff_state  = ep.get("strongest_wyckoff_state"),
                strongest_retest_before  = ep.get("strongest_retest_before"),
                max_volume_anomaly       = ep.get("max_volume_anomaly"),
                largest_gap_pct          = ep.get("largest_gap_pct"),
                sector                   = ep.get("sector"),
                industry                 = ep.get("industry"),
                summary_json             = json.dumps(ep.get("summary") or {}),
            )
            session.add(row)
            await session.flush()
            ids.append(row.id)
        await session.commit()
    return ids


async def get_pump_episodes(
    run_id: int,
    limit: int = 200,
    symbol: Optional[str] = None,
    pump_type: Optional[str] = None,
    min_multiple: Optional[float] = None,
    caught_only: bool = False,
    missed_only: bool = False,
) -> list[dict]:
    async with get_session_factory()() as session:
        q = select(PumpEpisode).where(PumpEpisode.run_id == run_id)
        if symbol:
            q = q.where(PumpEpisode.symbol == symbol.upper())
        if pump_type:
            q = q.where(PumpEpisode.pump_type == pump_type)
        if min_multiple is not None:
            q = q.where(PumpEpisode.pump_multiple >= min_multiple)
        if caught_only:
            q = q.where(PumpEpisode.was_flagged_by_scanner == True)   # noqa: E712
        if missed_only:
            q = q.where(PumpEpisode.was_flagged_by_scanner == False)  # noqa: E712
        q = q.order_by(PumpEpisode.pump_multiple.desc()).limit(limit)
        result = await session.execute(q)
        return [_pump_episode_to_dict(r) for r in result.scalars().all()]


async def get_pump_episode(episode_id: int) -> Optional[dict]:
    async with get_session_factory()() as session:
        result = await session.execute(
            select(PumpEpisode).where(PumpEpisode.id == episode_id)
        )
        row = result.scalar_one_or_none()
        return _pump_episode_to_dict(row) if row else None


# ── Snapshots ─────────────────────────────────────────────────────────────────

async def save_pump_episode_snapshots(snapshots: list[dict]) -> int:
    if not snapshots:
        return 0
    async with get_session_factory()() as session:
        for s in snapshots:
            row = PumpEpisodeSnapshot(
                episode_id              = s["episode_id"],
                run_id                  = s["run_id"],
                symbol                  = s["symbol"],
                date                    = s["date"],
                window_phase            = s.get("window_phase"),
                relative_day_from_start = s.get("relative_day_from_start"),
                relative_day_from_peak  = s.get("relative_day_from_peak"),
                open                    = s.get("open"),
                high                    = s.get("high"),
                low                     = s.get("low"),
                close                   = s.get("close"),
                volume                  = s.get("volume"),
                gap_pct                 = s.get("gap_pct"),
                intraday_range_pct      = s.get("intraday_range_pct"),
                close_position          = s.get("close_position"),
                daily_return_pct        = s.get("daily_return_pct"),
                cum_return_pct          = s.get("cum_return_pct"),
                volume_vs_avg20         = s.get("volume_vs_avg20"),
                volume_zscore           = s.get("volume_zscore"),
                atr_pct                 = s.get("atr_pct"),
                bb_width                = s.get("bb_width"),
                bb_squeeze              = s.get("bb_squeeze"),
                rsi                     = s.get("rsi"),
                cmf                     = s.get("cmf"),
                ribbon_class            = s.get("ribbon_class"),
                wyckoff_state           = s.get("wyckoff_state"),
                snapshot_json           = json.dumps(s.get("snapshot") or {}),
            )
            session.add(row)
        await session.commit()
    return len(snapshots)


async def get_pump_episode_snapshots(
    episode_id: int,
    phase: Optional[str] = None,
) -> list[dict]:
    async with get_session_factory()() as session:
        q = select(PumpEpisodeSnapshot).where(PumpEpisodeSnapshot.episode_id == episode_id)
        if phase:
            q = q.where(PumpEpisodeSnapshot.window_phase == phase.upper())
        q = q.order_by(PumpEpisodeSnapshot.date)
        result = await session.execute(q)
        return [_snapshot_to_dict(r) for r in result.scalars().all()]


async def get_run_snapshots(
    run_id: int,
    episode_id: Optional[int] = None,
    phase: Optional[str] = None,
    limit: int = 5000,
) -> list[dict]:
    async with get_session_factory()() as session:
        q = select(PumpEpisodeSnapshot).where(PumpEpisodeSnapshot.run_id == run_id)
        if episode_id is not None:
            q = q.where(PumpEpisodeSnapshot.episode_id == episode_id)
        if phase:
            q = q.where(PumpEpisodeSnapshot.window_phase == phase.upper())
        q = q.order_by(PumpEpisodeSnapshot.episode_id, PumpEpisodeSnapshot.date).limit(limit)
        result = await session.execute(q)
        return [_snapshot_to_dict(r) for r in result.scalars().all()]


# ── Events / timeline ─────────────────────────────────────────────────────────

async def save_pump_episode_events(events: list[dict]) -> int:
    if not events:
        return 0
    async with get_session_factory()() as session:
        for ev in events:
            row = PumpEpisodeEvent(
                episode_id        = ev["episode_id"],
                run_id            = ev["run_id"],
                symbol            = ev["symbol"],
                event_date        = ev["event_date"],
                event_type        = ev["event_type"],
                event_value       = ev.get("event_value"),
                event_detail_json = json.dumps(ev["event_detail"]) if ev.get("event_detail") else None,
                event_note        = ev.get("event_note"),
                days_before_pump  = ev.get("days_before_pump"),
            )
            session.add(row)
        await session.commit()
    return len(events)


async def get_pump_episode_events(episode_id: int) -> list[dict]:
    async with get_session_factory()() as session:
        result = await session.execute(
            select(PumpEpisodeEvent)
            .where(PumpEpisodeEvent.episode_id == episode_id)
            .order_by(PumpEpisodeEvent.event_date)
        )
        return [_event_to_dict(r) for r in result.scalars().all()]


async def get_pump_study_timeline(
    run_id: int,
    episode_id: Optional[int] = None,
) -> list[dict]:
    """All timeline events for a run (or one episode), sorted chronologically."""
    async with get_session_factory()() as session:
        q = select(PumpEpisodeEvent).where(PumpEpisodeEvent.run_id == run_id)
        if episode_id is not None:
            q = q.where(PumpEpisodeEvent.episode_id == episode_id)
        q = q.order_by(PumpEpisodeEvent.symbol, PumpEpisodeEvent.event_date)
        result = await session.execute(q)
        return [_event_to_dict(r) for r in result.scalars().all()]


# ── Clusters ──────────────────────────────────────────────────────────────────

async def save_pump_clusters(clusters: list[dict]) -> int:
    if not clusters:
        return 0
    async with get_session_factory()() as session:
        for c in clusters:
            row = PumpCluster(
                run_id               = c["run_id"],
                cluster_id           = c["cluster_id"],
                symbol               = c["symbol"],
                canonical_episode_id = c.get("canonical_episode_id"),
                cluster_start_date   = c.get("cluster_start_date"),
                cluster_end_date     = c.get("cluster_end_date"),
                canonical_start_date = c.get("canonical_start_date"),
                canonical_peak_date  = c.get("canonical_peak_date"),
                raw_detection_count  = c.get("raw_detection_count", 1),
            )
            session.add(row)
        await session.commit()
    return len(clusters)


async def get_pump_clusters(run_id: int) -> list[dict]:
    async with get_session_factory()() as session:
        result = await session.execute(
            select(PumpCluster)
            .where(PumpCluster.run_id == run_id)
            .order_by(PumpCluster.symbol, PumpCluster.cluster_start_date)
        )
        rows = result.scalars().all()
        return [
            {
                "id":                   r.id,
                "cluster_id":           r.cluster_id,
                "symbol":               r.symbol,
                "canonical_episode_id": r.canonical_episode_id,
                "cluster_start_date":   r.cluster_start_date,
                "cluster_end_date":     r.cluster_end_date,
                "canonical_start_date": r.canonical_start_date,
                "canonical_peak_date":  r.canonical_peak_date,
                "raw_detection_count":  r.raw_detection_count,
            }
            for r in rows
        ]


async def get_pump_cluster_detections(run_id: int, cluster_id: str) -> list[dict]:
    """Return raw detections belonging to one specific cluster."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(PumpEpisodeDetection)
            .where(
                PumpEpisodeDetection.run_id     == run_id,
                PumpEpisodeDetection.cluster_id == cluster_id,
            )
            .order_by(PumpEpisodeDetection.window_start_date)
        )
        rows = result.scalars().all()
        return [
            {
                "id":                       r.id,
                "symbol":                   r.symbol,
                "window_start_date":        r.window_start_date,
                "window_peak_date":         r.window_peak_date,
                "window_days":              r.window_days,
                "start_price":              r.start_price,
                "peak_price":               r.peak_price,
                "multiple":                 r.multiple,
                "return_pct":               r.return_pct,
                "days_to_peak":             r.days_to_peak,
                "days_to_double":           r.days_to_double,
                "max_drawdown_before_peak": r.max_drawdown_before_peak,
                "cluster_id":               r.cluster_id,
                "is_canonical":             r.is_canonical,
            }
            for r in rows
        ]


async def update_pump_cluster_episode_id(
    run_id: int,
    cluster_id: str,
    episode_id: int,
) -> None:
    """Back-fill canonical_episode_id on a cluster row after the episode is saved."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(PumpCluster).where(
                PumpCluster.run_id     == run_id,
                PumpCluster.cluster_id == cluster_id,
            )
        )
        row = result.scalar_one_or_none()
        if row:
            row.canonical_episode_id = episode_id
            await session.commit()


async def update_pump_episode_enrichment(episode_id: int, data: dict) -> None:
    """
    Back-fill enriched fields on a PumpEpisode row after Phase 3C–3E analysis.

    Updatable via this function:
        pump_type, had_ribbon, had_ignition, strongest_wyckoff_state,
        max_volume_anomaly, largest_gap_pct, summary_json
    """
    async with get_session_factory()() as session:
        result = await session.execute(
            select(PumpEpisode).where(PumpEpisode.id == episode_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            return
        for k, v in data.items():
            if hasattr(row, k):
                setattr(row, k, v)
        await session.commit()


# ── Comparison groups + members ───────────────────────────────────────────────

async def save_pump_comparison_group(run_id: int, group: dict) -> int:
    """Insert one comparison group. Returns its DB id."""
    async with get_session_factory()() as session:
        row = PumpComparisonGroup(
            run_id       = run_id,
            group_name   = group["group_name"],
            member_count = group.get("member_count", 0),
            stats_json   = json.dumps(group.get("stats") or {}),
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


async def save_pump_comparison_members(members: list[dict]) -> int:
    if not members:
        return 0
    async with get_session_factory()() as session:
        for m in members:
            row = PumpComparisonMember(
                group_id        = m["group_id"],
                run_id          = m["run_id"],
                group_name      = m["group_name"],
                symbol          = m["symbol"],
                episode_id      = m.get("episode_id"),
                pump_multiple   = m.get("pump_multiple"),
                pump_return_pct = m.get("pump_return_pct"),
                days_to_peak    = m.get("days_to_peak"),
                pump_type       = m.get("pump_type"),
                features_json   = json.dumps(m.get("features") or {}),
            )
            session.add(row)
        await session.commit()
    return len(members)


async def get_pump_comparison_groups(run_id: int) -> list[dict]:
    async with get_session_factory()() as session:
        result = await session.execute(
            select(PumpComparisonGroup)
            .where(PumpComparisonGroup.run_id == run_id)
            .order_by(PumpComparisonGroup.group_name)
        )
        return [
            {
                "id":           r.id,
                "group_name":   r.group_name,
                "member_count": r.member_count,
                "stats":        json.loads(r.stats_json or "{}"),
            }
            for r in result.scalars().all()
        ]


async def get_pump_comparison_members(
    run_id: int,
    group_id: Optional[int] = None,
) -> list[dict]:
    async with get_session_factory()() as session:
        q = select(PumpComparisonMember).where(PumpComparisonMember.run_id == run_id)
        if group_id is not None:
            q = q.where(PumpComparisonMember.group_id == group_id)
        q = q.order_by(PumpComparisonMember.group_name, PumpComparisonMember.symbol)
        result = await session.execute(q)
        return [
            {
                "id":             r.id,
                "group_id":       r.group_id,
                "group_name":     r.group_name,
                "symbol":         r.symbol,
                "episode_id":     r.episode_id,
                "pump_multiple":  r.pump_multiple,
                "pump_return_pct":r.pump_return_pct,
                "days_to_peak":   r.days_to_peak,
                "pump_type":      r.pump_type,
                "features":       json.loads(r.features_json or "{}"),
            }
            for r in result.scalars().all()
        ]


# ── Pump Study serialisers ────────────────────────────────────────────────────

def _pump_study_run_to_dict(r: PumpStudyRun) -> dict:
    return {
        "id":                   r.id,
        "status":               r.status,
        "start_date":           r.start_date,
        "end_date":             r.end_date,
        "window_days":          r.window_days,
        "min_multiple":         r.min_multiple,
        "universe_limit":       r.universe_limit,
        "symbols_scanned":      r.symbols_scanned,
        "raw_detection_count":  r.raw_detection_count,
        "cluster_count":        r.cluster_count,
        "episode_count":        r.episode_count,
        "snapshot_count":       r.snapshot_count,
        "event_count":          r.event_count,
        "error_message":        r.error_message,
        "notes":                r.notes,
        "started_at":           r.started_at.isoformat()  if r.started_at  else None,
        "finished_at":          r.finished_at.isoformat() if r.finished_at else None,
        "created_at":           r.created_at.isoformat()  if r.created_at  else None,
    }


def _pump_episode_to_dict(r: PumpEpisode) -> dict:
    return {
        "id":                       r.id,
        "run_id":                   r.run_id,
        "cluster_id":               r.cluster_id,
        "symbol":                   r.symbol,
        "pump_start_date":          r.pump_start_date,
        "pump_peak_date":           r.pump_peak_date,
        "pump_window_days":         r.pump_window_days,
        "start_price":              r.start_price,
        "peak_price":               r.peak_price,
        "pump_multiple":            r.pump_multiple,
        "pump_return_pct":          r.pump_return_pct,
        "days_to_peak":             r.days_to_peak,
        "days_to_double":           r.days_to_double,
        "max_drawdown_before_peak": r.max_drawdown_before_peak,
        "pump_type":                r.pump_type,
        "was_in_universe":          r.was_in_universe,
        "was_flagged_by_scanner":   r.was_flagged_by_scanner,
        "filter_reason":            r.filter_reason,
        "had_ribbon":               r.had_ribbon,
        "had_ignition":             r.had_ignition,
        "strongest_wyckoff_state":  r.strongest_wyckoff_state,
        "strongest_retest_before":  r.strongest_retest_before,
        "max_volume_anomaly":       r.max_volume_anomaly,
        "largest_gap_pct":          r.largest_gap_pct,
        "sector":                   r.sector,
        "industry":                 r.industry,
        "summary":                  json.loads(r.summary_json or "{}"),
        "created_at":               r.created_at.isoformat() if r.created_at else None,
    }


def _snapshot_to_dict(r: PumpEpisodeSnapshot) -> dict:
    return {
        "id":                       r.id,
        "episode_id":               r.episode_id,
        "symbol":                   r.symbol,
        "date":                     r.date,
        "window_phase":             r.window_phase,
        "relative_day_from_start":  r.relative_day_from_start,
        "relative_day_from_peak":   r.relative_day_from_peak,
        "open":                     r.open,
        "high":                     r.high,
        "low":                      r.low,
        "close":                    r.close,
        "volume":                   r.volume,
        "gap_pct":                  r.gap_pct,
        "intraday_range_pct":       r.intraday_range_pct,
        "close_position":           r.close_position,
        "daily_return_pct":         r.daily_return_pct,
        "cum_return_pct":           r.cum_return_pct,
        "volume_vs_avg20":          r.volume_vs_avg20,
        "volume_zscore":            r.volume_zscore,
        "atr_pct":                  r.atr_pct,
        "bb_width":                 r.bb_width,
        "bb_squeeze":               r.bb_squeeze,
        "rsi":                      r.rsi,
        "cmf":                      r.cmf,
        "ribbon_class":             r.ribbon_class,
        "wyckoff_state":            r.wyckoff_state,
        "snapshot":                 json.loads(r.snapshot_json or "{}"),
    }


def _event_to_dict(r: PumpEpisodeEvent) -> dict:
    return {
        "id":               r.id,
        "episode_id":       r.episode_id,
        "symbol":           r.symbol,
        "event_date":       r.event_date,
        "event_type":       r.event_type,
        "event_value":      r.event_value,
        "event_detail":     json.loads(r.event_detail_json or "{}"),
        "event_note":       r.event_note,
        "days_before_pump": r.days_before_pump,
    }


# ── Pump Study AI Summary CRUD ────────────────────────────────────────────────

async def save_pump_ai_summary(run_id: int, data: dict) -> int:
    """Persist an AI-generated analysis for a pump-study run (insert or replace)."""
    async with get_session_factory()() as session:
        # Delete any stale row first so we can re-insert cleanly
        existing = await session.execute(
            select(PumpStudyAISummary).where(PumpStudyAISummary.run_id == run_id)
        )
        old = existing.scalar_one_or_none()
        if old:
            await session.delete(old)
            await session.flush()

        row = PumpStudyAISummary(
            run_id         = run_id,
            analysis_json  = json.dumps(data.get("analysis") or {}),
            recommendation = data.get("recommendation", ""),
            evidence_json  = json.dumps(data.get("evidence") or {}),
            limitations    = data.get("limitations", ""),
            model_used     = data.get("model_used", ""),
            parse_failed   = data.get("parse_failed", False),
            raw_response   = data.get("raw_response"),
            parse_error    = data.get("parse_error"),
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


async def get_pump_ai_summary(run_id: int) -> dict | None:
    """Return a stored AI summary or None if not yet generated."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(PumpStudyAISummary).where(PumpStudyAISummary.run_id == run_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        return {
            "run_id":         row.run_id,
            "analysis":       json.loads(row.analysis_json or "{}"),
            "recommendation": row.recommendation,
            "evidence":       json.loads(row.evidence_json or "{}"),
            "limitations":    row.limitations,
            "model_used":     row.model_used,
            "parse_failed":   bool(row.parse_failed) if row.parse_failed is not None else False,
            "raw_response":   row.raw_response,
            "parse_error":    row.parse_error,
            "created_at":     row.created_at.isoformat() if row.created_at else None,
        }


# ── Raw Pattern Study CRUD ────────────────────────────────────────────────────

def _raw_pattern_run_to_dict(row: RawPatternRun) -> dict:
    return {
        "id":                    row.id,
        "pump_study_run_id":     row.pump_study_run_id,
        "status":                row.status,
        "start_date":            row.start_date,
        "end_date":              row.end_date,
        "raw_daily_count":       row.raw_daily_count,
        "episode_feature_count": row.episode_feature_count,
        "comparison_count":      row.comparison_count,
        "notes":                 row.notes,
        "error_message":         row.error_message,
        "started_at":            row.started_at.isoformat() if row.started_at else None,
        "finished_at":           row.finished_at.isoformat() if row.finished_at else None,
        "created_at":            row.created_at.isoformat() if row.created_at else None,
    }


async def create_raw_pattern_run(
    pump_study_run_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
    notes: str | None = None,
) -> int:
    """Create a new raw-pattern discovery run. Returns run id."""
    async with get_session_factory()() as session:
        row = RawPatternRun(
            pump_study_run_id = pump_study_run_id,
            status            = "pending",
            start_date        = start_date,
            end_date          = end_date,
            notes             = notes,
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


async def update_raw_pattern_run(run_id: int, data: dict) -> None:
    """Patch any subset of fields on a raw-pattern run row."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(RawPatternRun).where(RawPatternRun.id == run_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            return
        for k, v in data.items():
            if hasattr(row, k):
                setattr(row, k, v)
        await session.commit()


async def get_raw_pattern_run(run_id: int) -> dict | None:
    async with get_session_factory()() as session:
        result = await session.execute(
            select(RawPatternRun).where(RawPatternRun.id == run_id)
        )
        row = result.scalar_one_or_none()
        return _raw_pattern_run_to_dict(row) if row else None


async def get_raw_pattern_runs(
    pump_study_run_id: int | None = None,
    limit: int = 20,
) -> list[dict]:
    async with get_session_factory()() as session:
        q = select(RawPatternRun).order_by(RawPatternRun.created_at.desc()).limit(limit)
        if pump_study_run_id is not None:
            q = q.where(RawPatternRun.pump_study_run_id == pump_study_run_id)
        result = await session.execute(q)
        return [_raw_pattern_run_to_dict(r) for r in result.scalars().all()]


async def get_np_coverage_stats(run_id: int) -> dict:
    """
    Count how many raw_pattern_episode_features rows for this run have NP
    analysis results vs explicit skip reasons.

    Returns:
        total, analyzed, skipped, skip_insufficient_candles, skip_failed,
        coverage_pct (0–100, None when total=0)
    """
    async with get_session_factory()() as session:
        result = await session.execute(
            text("""
                SELECT
                    COUNT(*) AS total,
                    COUNT(CASE WHEN np_skip_reason IS NULL THEN 1 END) AS analyzed,
                    COUNT(CASE WHEN np_skip_reason IS NOT NULL THEN 1 END) AS skipped,
                    COUNT(CASE WHEN np_skip_reason = 'insufficient_candles' THEN 1 END) AS skip_candles,
                    COUNT(CASE WHEN np_skip_reason = 'np_analysis_failed'   THEN 1 END) AS skip_failed
                FROM raw_pattern_episode_features
                WHERE run_id = :run_id
            """),
            {"run_id": run_id},
        )
        row = result.mappings().one_or_none()
        if not row:
            return {"total": 0, "analyzed": 0, "skipped": 0,
                    "skip_insufficient_candles": 0, "skip_failed": 0,
                    "coverage_pct": None}
        total    = int(row["total"] or 0)
        analyzed = int(row["analyzed"] or 0)
        return {
            "total":                     total,
            "analyzed":                  analyzed,
            "skipped":                   int(row["skipped"] or 0),
            "skip_insufficient_candles": int(row["skip_candles"] or 0),
            "skip_failed":               int(row["skip_failed"] or 0),
            "coverage_pct":              round(analyzed / total * 100, 1) if total else None,
        }


async def save_raw_pattern_daily_features(run_id: int, rows: list[dict]) -> int:
    """Bulk-insert daily feature rows. Returns count inserted."""
    if not rows:
        return 0
    async with get_session_factory()() as session:
        for d in rows:
            row = RawPatternDailyFeatures(
                run_id                   = run_id,
                episode_id               = d["episode_id"],
                symbol                   = d["symbol"],
                date                     = d["date"],
                phase                    = d.get("phase"),
                relative_day_from_start  = d.get("relative_day_from_start"),
                relative_day_from_peak   = d.get("relative_day_from_peak"),
                sector                   = d.get("sector"),
                industry                 = d.get("industry"),
                exchange                 = d.get("exchange"),
                market_cap               = d.get("market_cap"),
                float_shares             = d.get("float_shares"),
                market_regime            = d.get("market_regime"),
                open                     = d.get("open"),
                high                     = d.get("high"),
                low                      = d.get("low"),
                close                    = d.get("close"),
                volume                   = d.get("volume"),
                dollar_volume            = d.get("dollar_volume"),
                gap_pct                  = d.get("gap_pct"),
                intraday_range_pct       = d.get("intraday_range_pct"),
                body_pct                 = d.get("body_pct"),
                upper_wick_pct           = d.get("upper_wick_pct"),
                lower_wick_pct           = d.get("lower_wick_pct"),
                close_position_in_bar    = d.get("close_position_in_bar"),
                wide_range_bar           = d.get("wide_range_bar"),
                narrow_range_bar         = d.get("narrow_range_bar"),
                strong_close_near_high   = d.get("strong_close_near_high"),
                weak_close_near_low      = d.get("weak_close_near_low"),
                volume_vs_avg5           = d.get("volume_vs_avg5"),
                volume_vs_avg10          = d.get("volume_vs_avg10"),
                volume_vs_avg20          = d.get("volume_vs_avg20"),
                volume_zscore            = d.get("volume_zscore"),
                dollar_volume_vs_avg20   = d.get("dollar_volume_vs_avg20"),
                abnormal_volume_day      = d.get("abnormal_volume_day"),
                dryup_day                = d.get("dryup_day"),
                atr                      = d.get("atr"),
                atr_pct                  = d.get("atr_pct"),
                atr_expansion_state      = d.get("atr_expansion_state"),
                bb_width                 = d.get("bb_width"),
                bb_squeeze_bars          = d.get("bb_squeeze_bars"),
                ema_spread_pct           = d.get("ema_spread_pct"),
                compression_state        = d.get("compression_state"),
                distance_to_range_high   = d.get("distance_to_range_high"),
                distance_to_range_low    = d.get("distance_to_range_low"),
                distance_to_mid_range    = d.get("distance_to_mid_range"),
                bullish_engulfing        = d.get("bullish_engulfing"),
                bearish_engulfing        = d.get("bearish_engulfing"),
                inside_bar               = d.get("inside_bar"),
                outside_bar              = d.get("outside_bar"),
                doji_like                = d.get("doji_like"),
                reclaim_bar              = d.get("reclaim_bar"),
                expansion_bar            = d.get("expansion_bar"),
                feature_json             = json.dumps(d["feature_json"]) if d.get("feature_json") else None,
            )
            session.add(row)
        await session.commit()
    return len(rows)


async def get_raw_pattern_daily_features(
    run_id: int,
    episode_id: int | None = None,
    phase: str | None = None,
    limit: int = 5000,
) -> list[dict]:
    async with get_session_factory()() as session:
        q = (
            select(RawPatternDailyFeatures)
            .where(RawPatternDailyFeatures.run_id == run_id)
            .order_by(RawPatternDailyFeatures.episode_id,
                      RawPatternDailyFeatures.relative_day_from_start)
        )
        if episode_id is not None:
            q = q.where(RawPatternDailyFeatures.episode_id == episode_id)
        if phase is not None:
            q = q.where(RawPatternDailyFeatures.phase == phase)
        q = q.limit(limit)
        result = await session.execute(q)
        rows = result.scalars().all()
        out = []
        for r in rows:
            d = {c.key: getattr(r, c.key) for c in RawPatternDailyFeatures.__table__.columns}
            d["feature_json"] = json.loads(d["feature_json"]) if d.get("feature_json") else None
            out.append(d)
        return out


async def save_raw_pattern_episode_features(run_id: int, rows: list[dict]) -> list[int]:
    """Bulk-insert episode-level feature rows. Returns list of inserted ids."""
    if not rows:
        return []
    ids = []
    async with get_session_factory()() as session:
        for d in rows:
            row = RawPatternEpisodeFeatures(
                run_id                                      = run_id,
                episode_id                                  = d["episode_id"],
                symbol                                      = d["symbol"],
                group_type                                  = d.get("group_type"),
                pump_multiple                               = d.get("pump_multiple"),
                pump_type                                   = d.get("pump_type"),
                pre_days                                    = d.get("pre_days"),
                pump_days                                   = d.get("pump_days"),
                post_days                                   = d.get("post_days"),
                days_in_base                                = d.get("days_in_base"),
                days_from_first_abnormal_volume_to_breakout = d.get("days_from_first_abnormal_volume_to_breakout"),
                days_from_breakout_to_peak                  = d.get("days_from_breakout_to_peak"),
                days_from_first_compression_to_breakout     = d.get("days_from_first_compression_to_breakout"),
                avg_body_pct_pre                            = d.get("avg_body_pct_pre"),
                avg_upper_wick_pct_pre                      = d.get("avg_upper_wick_pct_pre"),
                avg_lower_wick_pct_pre                      = d.get("avg_lower_wick_pct_pre"),
                wide_range_bar_count_pre                    = d.get("wide_range_bar_count_pre"),
                narrow_range_bar_count_pre                  = d.get("narrow_range_bar_count_pre"),
                strong_close_count_pre                      = d.get("strong_close_count_pre"),
                bullish_engulfing_count_pre                 = d.get("bullish_engulfing_count_pre"),
                bearish_engulfing_count_pre                 = d.get("bearish_engulfing_count_pre"),
                inside_bar_count_pre                        = d.get("inside_bar_count_pre"),
                outside_bar_count_pre                       = d.get("outside_bar_count_pre"),
                reclaim_bar_count_pre                       = d.get("reclaim_bar_count_pre"),
                expansion_bar_count_pre                     = d.get("expansion_bar_count_pre"),
                max_volume_anomaly_pre                      = d.get("max_volume_anomaly_pre"),
                median_volume_anomaly_pre                   = d.get("median_volume_anomaly_pre"),
                abnormal_volume_day_count_pre               = d.get("abnormal_volume_day_count_pre"),
                dryup_day_count_pre                         = d.get("dryup_day_count_pre"),
                max_dollar_volume_pre                       = d.get("max_dollar_volume_pre"),
                had_compression                             = d.get("had_compression"),
                compression_days_pre                        = d.get("compression_days_pre"),
                min_bb_width_pre                            = d.get("min_bb_width_pre"),
                avg_atr_pct_pre                             = d.get("avg_atr_pct_pre"),
                atr_contraction_days_pre                    = d.get("atr_contraction_days_pre"),
                had_bull_stack_pre                          = d.get("had_bull_stack_pre"),
                bull_stack_days_pre                         = d.get("bull_stack_days_pre"),
                days_above_ema50_pre                        = d.get("days_above_ema50_pre"),
                days_above_ema200_pre                       = d.get("days_above_ema200_pre"),
                ema50_reclaim_count_pre                     = d.get("ema50_reclaim_count_pre"),
                avg_close_vs_ema50_pct_pre                  = d.get("avg_close_vs_ema50_pct_pre"),
                avg_close_vs_ema200_pct_pre                 = d.get("avg_close_vs_ema200_pct_pre"),
                had_accumulation_like                       = d.get("had_accumulation_like"),
                accumulation_like_day_count                 = d.get("accumulation_like_day_count"),
                had_spring_test_lps                         = d.get("had_spring_test_lps"),
                had_breakout_retest                         = d.get("had_breakout_retest"),
                retest_count                                = d.get("retest_count"),
                avg_retest_quality                          = d.get("avg_retest_quality"),
                strongest_wyckoff_state                     = d.get("strongest_wyckoff_state"),
                strongest_sequence_type                     = d.get("strongest_sequence_type"),
                strongest_structural_bias                   = d.get("strongest_structural_bias"),
            )
            session.add(row)
            await session.flush()
            ids.append(row.id)
        await session.commit()
    return ids


async def get_raw_pattern_episode_features(
    run_id: int,
    group_type: str | None = None,
    limit: int = 1000,
) -> list[dict]:
    async with get_session_factory()() as session:
        q = (
            select(RawPatternEpisodeFeatures)
            .where(RawPatternEpisodeFeatures.run_id == run_id)
            .order_by(RawPatternEpisodeFeatures.id)
        )
        if group_type is not None:
            q = q.where(RawPatternEpisodeFeatures.group_type == group_type)
        q = q.limit(limit)
        result = await session.execute(q)
        rows = result.scalars().all()
        return [
            {c.key: getattr(r, c.key) for c in RawPatternEpisodeFeatures.__table__.columns}
            for r in rows
        ]


async def update_raw_pattern_episode_features(
    run_id: int,
    episode_id: int,
    data: dict,
) -> None:
    """
    Patch an existing raw_pattern_episode_features row identified by
    (run_id, episode_id).  Only keys present in *data* are written;
    unrelated columns are left unchanged.
    """
    if not data:
        return
    async with get_session_factory()() as session:
        result = await session.execute(
            select(RawPatternEpisodeFeatures).where(
                RawPatternEpisodeFeatures.run_id     == run_id,
                RawPatternEpisodeFeatures.episode_id == episode_id,
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return
        for key, value in data.items():
            if hasattr(row, key):
                setattr(row, key, value)
        await session.commit()


async def save_raw_pattern_comparison_rows(run_id: int, rows: list[dict]) -> int:
    """
    Bulk-insert per-feature comparison stats (one row per group × feature).
    Each dict must contain: group_name, feature_name, member_count,
    mean_value, median_value, p25_value, p75_value, p90_value.
    Optional: stats_json (dict — will be serialised).
    Returns count inserted.
    """
    if not rows:
        return 0
    async with get_session_factory()() as session:
        for d in rows:
            row = RawPatternComparison(
                run_id       = run_id,
                group_name   = d["group_name"],
                feature_name = d["feature_name"],
                member_count = d.get("member_count", 0),
                mean_value   = d.get("mean_value"),
                median_value = d.get("median_value"),
                p25_value    = d.get("p25_value"),
                p75_value    = d.get("p75_value"),
                p90_value    = d.get("p90_value"),
                stats_json   = json.dumps(d["stats_json"]) if d.get("stats_json") else None,
            )
            session.add(row)
        await session.commit()
    return len(rows)


async def get_raw_pattern_comparisons(
    run_id: int,
    group_name: str | None = None,
    feature_name: str | None = None,
) -> list[dict]:
    """
    Return per-feature comparison rows for a run.
    Optionally filter by group_name and/or feature_name.
    """
    async with get_session_factory()() as session:
        q = (
            select(RawPatternComparison)
            .where(RawPatternComparison.run_id == run_id)
            .order_by(RawPatternComparison.group_name, RawPatternComparison.feature_name)
        )
        if group_name is not None:
            q = q.where(RawPatternComparison.group_name == group_name)
        if feature_name is not None:
            q = q.where(RawPatternComparison.feature_name == feature_name)
        result = await session.execute(q)
        rows = result.scalars().all()
        out = []
        for r in rows:
            out.append({
                "id":           r.id,
                "run_id":       r.run_id,
                "group_name":   r.group_name,
                "feature_name": r.feature_name,
                "member_count": r.member_count,
                "mean_value":   r.mean_value,
                "median_value": r.median_value,
                "p25_value":    r.p25_value,
                "p75_value":    r.p75_value,
                "p90_value":    r.p90_value,
                "stats":        json.loads(r.stats_json) if r.stats_json else {},
            })
        return out


async def save_raw_pattern_comparison_members(run_id: int, group_name: str,
                                              members: list[dict]) -> int:
    """
    Bulk-insert comparison member rows.
    Each dict must contain: symbol.  Optional: episode_id, features (dict).
    Returns count inserted.
    """
    if not members:
        return 0
    async with get_session_factory()() as session:
        for m in members:
            row = RawPatternComparisonMember(
                run_id        = run_id,
                group_name    = group_name,
                symbol        = m["symbol"],
                episode_id    = m.get("episode_id"),
                features_json = json.dumps(m.get("features") or {}),
            )
            session.add(row)
        await session.commit()
    return len(members)


async def get_raw_pattern_comparison_members(
    run_id: int,
    group_name: str | None = None,
    limit: int = 2000,
) -> list[dict]:
    async with get_session_factory()() as session:
        q = (
            select(RawPatternComparisonMember)
            .where(RawPatternComparisonMember.run_id == run_id)
            .order_by(RawPatternComparisonMember.group_name,
                      RawPatternComparisonMember.symbol)
        )
        if group_name is not None:
            q = q.where(RawPatternComparisonMember.group_name == group_name)
        q = q.limit(limit)
        result = await session.execute(q)
        rows = result.scalars().all()
        return [
            {
                "id":           r.id,
                "run_id":       r.run_id,
                "group_name":   r.group_name,
                "symbol":       r.symbol,
                "episode_id":   r.episode_id,
                "features":     json.loads(r.features_json) if r.features_json else {},
            }
            for r in rows
        ]


async def save_raw_pattern_ai_summary(run_id: int, data: dict) -> int:
    """Persist an AI-generated analysis for a raw-pattern run (insert or replace)."""
    async with get_session_factory()() as session:
        existing = await session.execute(
            select(RawPatternAISummary).where(RawPatternAISummary.run_id == run_id)
        )
        old = existing.scalar_one_or_none()
        if old:
            await session.delete(old)
            await session.flush()
        row = RawPatternAISummary(
            run_id         = run_id,
            analysis_json  = json.dumps(data.get("analysis") or {}),
            recommendation = data.get("recommendation", ""),
            evidence_json  = json.dumps(data.get("evidence") or {}),
            limitations    = data.get("limitations", ""),
            model_used     = data.get("model_used", ""),
            parse_failed   = data.get("parse_failed", False),
            raw_response   = data.get("raw_response"),
            parse_error    = data.get("parse_error"),
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


async def get_raw_pattern_ai_summary(run_id: int) -> dict | None:
    """Return a stored raw-pattern AI summary, or None if not yet generated."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(RawPatternAISummary).where(RawPatternAISummary.run_id == run_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            return None
        return {
            "run_id":         row.run_id,
            "analysis":       json.loads(row.analysis_json or "{}"),
            "recommendation": row.recommendation,
            "evidence":       json.loads(row.evidence_json or "{}"),
            "limitations":    row.limitations,
            "model_used":     row.model_used,
            "parse_failed":   bool(row.parse_failed) if row.parse_failed is not None else False,
            "raw_response":   row.raw_response,
            "parse_error":    row.parse_error,
            "created_at":     row.created_at.isoformat() if row.created_at else None,
        }


async def clear_raw_pattern_comparisons(run_id: int) -> int:
    """Delete all raw_pattern_comparisons + raw_pattern_comparison_members for a run.
    Used before rebuilding comparisons in a repair pass.  Returns rows deleted."""
    async with get_session_factory()() as session:
        total = 0
        for Model, fk in [
            (RawPatternComparisonMember, RawPatternComparisonMember.run_id),
            (RawPatternComparison,       RawPatternComparison.run_id),
        ]:
            result = await session.execute(select(Model).where(fk == run_id))
            rows   = result.scalars().all()
            for r in rows:
                await session.delete(r)
            total += len(rows)
        await session.commit()
    return total


async def delete_raw_pattern_run(run_id: int) -> dict:
    """Hard-delete a raw-pattern run and all its child records."""
    async with get_session_factory()() as session:
        run = (await session.execute(
            select(RawPatternRun).where(RawPatternRun.id == run_id)
        )).scalar_one_or_none()
        if not run:
            raise ValueError(f"Raw pattern run {run_id} not found")

        counts = {}
        for Model, label, fk in [
            (RawPatternComparisonMember, "cmp_members",     RawPatternComparisonMember.run_id),
            (RawPatternComparison,       "cmp_features",    RawPatternComparison.run_id),
            (RawPatternEpisodeFeatures,  "ep_features",     RawPatternEpisodeFeatures.run_id),
            (RawPatternDailyFeatures,    "daily_features",  RawPatternDailyFeatures.run_id),
            (RawPatternAISummary,        "ai_summaries",    RawPatternAISummary.run_id),
            (DiscoveredPattern,          "discovered_patterns", DiscoveredPattern.run_id),
        ]:
            result = await session.execute(select(Model).where(fk == run_id))
            rows   = result.scalars().all()
            for r in rows:
                await session.delete(r)
            counts[label] = len(rows)

        await session.delete(run)
        counts["run"] = 1
        await session.commit()
        return counts


async def cleanup_raw_pattern_runs(
    keep_last_n: int = 5,
    dry_run: bool = True,
    vacuum: bool = False,
) -> dict:
    """
    Bulk-delete old raw-pattern-study runs to reclaim DB storage.

    Keeps the `keep_last_n` most-recent complete runs ordered by created_at desc.
    Deletes all child records (episode_features, daily_features, ai_summaries,
    discovered_patterns, comparison records) then the run row itself.

    Returns a summary dict with `runs_to_delete` list, `deleted` counts,
    `dry_run` flag, and `vacuum_done` flag.
    """
    async with get_session_factory()() as session:
        # Load all complete runs ordered newest-first
        result = await session.execute(
            select(RawPatternRun)
            .where(RawPatternRun.status == "complete")
            .order_by(RawPatternRun.created_at.desc())
        )
        complete_runs = result.scalars().all()

        to_delete = complete_runs[keep_last_n:]
        to_delete_ids = [r.id for r in to_delete]

        preview = [
            {
                "run_id":     r.id,
                "ticker":     r.ticker,
                "created_at": r.created_at.isoformat() if r.created_at else None,
                "status":     r.status,
            }
            for r in to_delete
        ]

        if dry_run or not to_delete_ids:
            return {
                "dry_run":        dry_run,
                "keep_last_n":    keep_last_n,
                "runs_kept":      len(complete_runs) - len(to_delete),
                "runs_to_delete": preview,
                "deleted":        {},
                "vacuum_done":    False,
            }

        # Hard-delete each run (reuse per-row delete logic)
        total_counts: dict[str, int] = {}
        for run_id in to_delete_ids:
            run_row = (await session.execute(
                select(RawPatternRun).where(RawPatternRun.id == run_id)
            )).scalar_one_or_none()
            if not run_row:
                continue
            for Model, label, fk in [
                (RawPatternComparisonMember, "cmp_members",        RawPatternComparisonMember.run_id),
                (RawPatternComparison,       "cmp_features",       RawPatternComparison.run_id),
                (RawPatternEpisodeFeatures,  "ep_features",        RawPatternEpisodeFeatures.run_id),
                (RawPatternDailyFeatures,    "daily_features",     RawPatternDailyFeatures.run_id),
                (RawPatternAISummary,        "ai_summaries",       RawPatternAISummary.run_id),
                (DiscoveredPattern,          "discovered_patterns", DiscoveredPattern.run_id),
            ]:
                rows = (await session.execute(select(Model).where(fk == run_id))).scalars().all()
                for r in rows:
                    await session.delete(r)
                total_counts[label] = total_counts.get(label, 0) + len(rows)
            await session.delete(run_row)
            total_counts["runs"] = total_counts.get("runs", 0) + 1

        await session.commit()

    vacuum_done = False
    if vacuum and _IS_SQLITE:
        engine = get_engine()
        async with engine.connect() as conn:
            await conn.execute(text("VACUUM"))
        vacuum_done = True

    return {
        "dry_run":        False,
        "keep_last_n":    keep_last_n,
        "runs_kept":      len(complete_runs) - len(to_delete),
        "runs_to_delete": preview,
        "deleted":        total_counts,
        "vacuum_done":    vacuum_done,
    }


# ── StockSplitCache CRUD ──────────────────────────────────────────────────────

async def save_stock_splits(splits: list[dict]) -> int:
    """
    Upsert split records into StockSplitCache.
    Each dict must have: symbol, execution_date, split_from, split_to, split_type,
    ratio, adjustment_factor, source.
    Returns count of rows inserted/updated.
    """
    if not splits:
        return 0
    now = datetime.utcnow()
    async with get_session_factory()() as session:
        count = 0
        for s in splits:
            existing = (await session.execute(
                select(StockSplitCache).where(
                    StockSplitCache.symbol == s["symbol"].upper(),
                    StockSplitCache.execution_date == s["execution_date"],
                )
            )).scalar_one_or_none()
            if existing:
                existing.split_from        = s.get("split_from", existing.split_from)
                existing.split_to          = s.get("split_to",   existing.split_to)
                existing.ratio             = s.get("ratio")
                existing.split_type        = s.get("split_type")
                existing.adjustment_factor = s.get("adjustment_factor")
                existing.source            = s.get("source", "massive")
                existing.synced_at         = now
            else:
                session.add(StockSplitCache(
                    symbol           = s["symbol"].upper(),
                    execution_date   = s["execution_date"],
                    split_from       = s.get("split_from", 1),
                    split_to         = s.get("split_to",   1),
                    ratio            = s.get("ratio"),
                    split_type       = s.get("split_type"),
                    adjustment_factor= s.get("adjustment_factor"),
                    source           = s.get("source", "massive"),
                    synced_at        = now,
                ))
                count += 1
        await session.commit()
        return count


async def get_stock_splits_for_symbols(
    symbols: list[str],
    since:   str,
    until:   str,
) -> dict[str, list[dict]]:
    """
    Return cached splits for the given symbols within [since, until] (inclusive).
    Returns dict[symbol_upper → list[split_dict]].
    """
    if not symbols:
        return {}
    upper = [s.upper() for s in symbols]
    async with get_session_factory()() as session:
        q = select(StockSplitCache).where(
            StockSplitCache.symbol.in_(upper),
            StockSplitCache.execution_date >= since,
            StockSplitCache.execution_date <= until,
        ).order_by(StockSplitCache.symbol, StockSplitCache.execution_date)
        rows = (await session.execute(q)).scalars().all()
        result: dict[str, list[dict]] = {s: [] for s in upper}
        for r in rows:
            result[r.symbol].append({
                "symbol":           r.symbol,
                "execution_date":   r.execution_date,
                "split_from":       r.split_from,
                "split_to":         r.split_to,
                "ratio":            r.ratio,
                "split_type":       r.split_type,
                "adjustment_factor":r.adjustment_factor,
                "source":           r.source,
            })
        return result


# ── Pattern Discovery CRUD ────────────────────────────────────────────────────

async def upsert_discovered_patterns(run_id: int, rows: list[dict]) -> int:
    """
    Upsert discovered pattern rows for a run.
    Returns count of rows inserted/updated.
    """
    if not rows:
        return 0
    async with get_session_factory()() as session:
        count = 0
        for d in rows:
            signal_id = (d.get("signal_id") or "")[:60]
            existing = (await session.execute(
                select(DiscoveredPattern).where(
                    DiscoveredPattern.run_id    == run_id,
                    DiscoveredPattern.signal_id == signal_id,
                )
            )).scalar_one_or_none()

            if existing:
                for col in [
                    "source_type", "feature_family", "family", "status", "intended_use",
                    "description", "count_missed_4x", "count_detected_4x", "count_all_4x",
                    "count_false_positive", "count_normal_winner", "count_split_artifact",
                    "lift_vs_false_positive", "lift_vs_normal_winner",
                    "precision_estimate", "recall_all_4x", "false_positive_rate",
                    "split_artifact_exposure", "reverse_split_exposure",
                    "recommendation", "machine_conditions_json",
                ]:
                    if col in d:
                        setattr(existing, col, d[col])
                count += 1
            else:
                session.add(DiscoveredPattern(
                    run_id                  = run_id,
                    signal_id               = signal_id,
                    source_type             = d.get("source_type"),
                    feature_family          = d.get("feature_family"),
                    family                  = d.get("family"),
                    status                  = d.get("status"),
                    intended_use            = d.get("intended_use"),
                    description             = d.get("description"),
                    count_missed_4x         = d.get("count_missed_4x"),
                    count_detected_4x       = d.get("count_detected_4x"),
                    count_all_4x            = d.get("count_all_4x"),
                    count_false_positive    = d.get("count_false_positive"),
                    count_normal_winner     = d.get("count_normal_winner"),
                    count_split_artifact    = d.get("count_split_artifact"),
                    lift_vs_false_positive  = d.get("lift_vs_false_positive"),
                    lift_vs_normal_winner   = d.get("lift_vs_normal_winner"),
                    precision_estimate      = d.get("precision_estimate"),
                    recall_all_4x           = d.get("recall_all_4x"),
                    false_positive_rate     = d.get("false_positive_rate"),
                    split_artifact_exposure = d.get("split_artifact_exposure"),
                    reverse_split_exposure  = d.get("reverse_split_exposure"),
                    recommendation          = d.get("recommendation"),
                    machine_conditions_json = d.get("machine_conditions_json"),
                ))
                count += 1

        await session.commit()
        return count


def _infer_source_type(signal_id: str, stored: Optional[str] = None) -> str:
    """Infer source_type from signal_id when the stored column is null."""
    if stored:
        return stored
    if not signal_id:
        return "EPISODE_AGGREGATE"
    _PREFIXES = [
        ("DISC_BAR_TEN_BAR_CONTEXT_",        "TEN_BAR_CONTEXT"),
        ("DISC_BAR_THREE_BAR_SEQUENCE_",      "THREE_BAR_SEQUENCE"),
        ("DISC_BAR_TWO_BAR_SEQUENCE_",        "TWO_BAR_SEQUENCE"),
        ("DISC_BAR_FIVE_BAR_SEQUENCE_",       "FIVE_BAR_SEQUENCE"),
        ("DISC_BAR_SINGLE_BAR_",              "SINGLE_BAR"),
        ("DISC_FLOW_TEN_BAR_CONTEXT_",        "TEN_BAR_CONTEXT"),
        ("DISC_FLOW_THREE_BAR_SEQUENCE_",     "THREE_BAR_SEQUENCE"),
        ("DISC_FLOW_TWO_BAR_SEQUENCE_",       "TWO_BAR_SEQUENCE"),
        ("DISC_FLOW_FIVE_BAR_SEQUENCE_",      "FIVE_BAR_SEQUENCE"),
        ("DISC_FLOW_SINGLE_BAR_",             "SINGLE_BAR"),
        ("DISC_COMBINED_TEN_BAR_CONTEXT_",    "TEN_BAR_CONTEXT"),
        ("DISC_COMBINED_THREE_BAR_SEQUENCE_", "THREE_BAR_SEQUENCE"),
        ("DISC_COMBINED_TWO_BAR_SEQUENCE_",   "TWO_BAR_SEQUENCE"),
        ("DISC_COMBINED_FIVE_BAR_SEQUENCE_",  "FIVE_BAR_SEQUENCE"),
        ("DISC_COMBINED_SINGLE_BAR_",         "SINGLE_BAR"),
    ]
    for prefix, st in _PREFIXES:
        if signal_id.startswith(prefix):
            return st
    return "EPISODE_AGGREGATE"


def _infer_feature_family(signal_id: str, stored: Optional[str] = None) -> str:
    """Infer feature_family from signal_id prefix when the stored column is null."""
    if stored:
        return stored
    if not signal_id:
        return "EPISODE_AGGREGATE"
    if signal_id.startswith("DISC_FLOW_"):
        return "FLOW"
    if signal_id.startswith("DISC_COMBINED_"):
        return "COMBINED"
    if signal_id.startswith("DISC_BAR_"):
        return "PRICE_ACTION"
    return "EPISODE_AGGREGATE"


async def get_discovered_patterns(run_id: int) -> list[dict]:
    """Return all discovered patterns for a run, sorted by lift_vs_false_positive desc."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(DiscoveredPattern)
            .where(DiscoveredPattern.run_id == run_id)
            .order_by(DiscoveredPattern.lift_vs_false_positive.desc().nullslast())
        )
        rows = result.scalars().all()
        return [
            {
                "id":                    r.id,
                "run_id":                r.run_id,
                "signal_id":             r.signal_id,
                "source_type":           _infer_source_type(r.signal_id, getattr(r, "source_type", None)),
                "feature_family":        _infer_feature_family(r.signal_id, getattr(r, "feature_family", None)),
                "family":                r.family,
                "status":                r.status,
                "intended_use":          r.intended_use,
                "description":           r.description,
                "count_missed_4x":       r.count_missed_4x,
                "count_detected_4x":     r.count_detected_4x,
                "count_all_4x":          r.count_all_4x,
                "count_false_positive":  r.count_false_positive,
                "count_normal_winner":   r.count_normal_winner,
                "count_split_artifact":  r.count_split_artifact,
                "lift_vs_false_positive": r.lift_vs_false_positive,
                "lift_vs_normal_winner": r.lift_vs_normal_winner,
                "precision_estimate":    r.precision_estimate,
                "recall_all_4x":         r.recall_all_4x,
                "false_positive_rate":   r.false_positive_rate,
                "split_artifact_exposure": r.split_artifact_exposure,
                "reverse_split_exposure": r.reverse_split_exposure,
                "recommendation":        r.recommendation,
                "machine_conditions":    json.loads(r.machine_conditions_json or "[]"),
                "created_at":            r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]


# ── AI Journal CRUD ───────────────────────────────────────────────────────────

async def get_ai_journal_state() -> dict:
    """Return (or initialise) the single AI Journal state row."""
    async with get_session_factory()() as session:
        result = await session.execute(select(AIJournalState).limit(1))
        state = result.scalar_one_or_none()
        if not state:
            state = AIJournalState()
            session.add(state)
            await session.commit()
            await session.refresh(state)
        return {
            "capital":          state.capital,
            "starting_capital": state.starting_capital,
            "updated_at":       state.updated_at.isoformat() if state.updated_at else None,
            "learned_strategy": json.loads(state.learned_strategy or "null"),
        }


async def update_ai_journal_capital(new_capital: float, strategy_json: str | None = None):
    async with get_session_factory()() as session:
        result = await session.execute(select(AIJournalState).limit(1))
        state = result.scalar_one_or_none()
        if not state:
            state = AIJournalState()
            session.add(state)
        state.capital = new_capital
        state.updated_at = datetime.utcnow()
        if strategy_json is not None:
            state.learned_strategy = strategy_json
        await session.commit()


async def reset_ai_journal(new_capital: float = 500.0):
    async with get_session_factory()() as session:
        # Close all open positions at 0 P&L
        pos_result = await session.execute(
            select(AIJournalPosition).where(AIJournalPosition.status == "OPEN")
        )
        for pos in pos_result.scalars().all():
            pos.status = "CLOSED"
            pos.exit_date = datetime.utcnow()
            pos.exit_reason = "RESET"
            pos.pnl_usd = 0.0
            pos.pnl_pct = 0.0
        # Reset state
        state_result = await session.execute(select(AIJournalState).limit(1))
        state = state_result.scalar_one_or_none()
        if not state:
            state = AIJournalState()
            session.add(state)
        state.capital = new_capital
        state.starting_capital = new_capital
        state.updated_at = datetime.utcnow()
        state.learned_strategy = None
        await session.commit()
    return {"ok": True, "capital": new_capital}


async def get_ai_journal_positions(status: str = "OPEN") -> list[dict]:
    async with get_session_factory()() as session:
        q = select(AIJournalPosition).where(AIJournalPosition.status == status)\
              .order_by(AIJournalPosition.entry_date.desc())
        result = await session.execute(q)
        return [
            {
                "id":              p.id,
                "symbol":          p.symbol,
                "entry_date":      p.entry_date.isoformat() if p.entry_date else None,
                "entry_price":     p.entry_price,
                "shares":          p.shares,
                "cost_basis":      p.cost_basis,
                "target_price":    p.target_price,
                "stop_price":      p.stop_price,
                "entry_rationale": p.entry_rationale,
                "status":          p.status,
                "exit_date":       p.exit_date.isoformat() if p.exit_date else None,
                "exit_price":      p.exit_price,
                "pnl_usd":         p.pnl_usd,
                "pnl_pct":         p.pnl_pct,
                "exit_reason":     p.exit_reason,
                "scan_tier":       p.scan_tier,
                "scan_score":      p.scan_score,
                "ats_signal":      p.ats_signal,
                "current_price":   p.current_price,
                "current_value":   p.current_value,
            }
            for p in result.scalars().all()
        ]


async def open_ai_journal_position(pos: dict) -> int:
    async with get_session_factory()() as session:
        p = AIJournalPosition(
            symbol          = pos["symbol"],
            entry_price     = pos["entry_price"],
            shares          = pos["shares"],
            cost_basis      = pos["cost_basis"],
            target_price    = pos.get("target_price"),
            stop_price      = pos.get("stop_price"),
            entry_rationale = pos.get("entry_rationale"),
            scan_tier       = pos.get("scan_tier"),
            scan_score      = pos.get("scan_score"),
            ats_signal      = pos.get("ats_signal"),
            status          = "OPEN",
        )
        session.add(p)
        await session.commit()
        await session.refresh(p)
        return p.id


async def close_ai_journal_position(position_id: int, exit_price: float, reason: str):
    async with get_session_factory()() as session:
        result = await session.execute(
            select(AIJournalPosition).where(AIJournalPosition.id == position_id)
        )
        pos = result.scalar_one_or_none()
        if not pos:
            return None
        pnl_usd = (exit_price - pos.entry_price) * pos.shares
        pnl_pct = (exit_price / pos.entry_price - 1) * 100 if pos.entry_price else 0
        pos.status     = "CLOSED"
        pos.exit_date  = datetime.utcnow()
        pos.exit_price = exit_price
        pos.pnl_usd    = round(pnl_usd, 2)
        pos.pnl_pct    = round(pnl_pct, 2)
        pos.exit_reason = reason
        await session.commit()
        return {"pnl_usd": pos.pnl_usd, "pnl_pct": pos.pnl_pct}


async def save_ai_journal_entry(entry: dict) -> int:
    async with get_session_factory()() as session:
        e = AIJournalEntry(
            journal_text     = entry["journal_text"],
            strategy_notes   = entry.get("strategy_notes"),
            capital_before   = entry["capital_before"],
            capital_after    = entry["capital_after"],
            positions_opened = entry.get("positions_opened", 0),
            positions_closed = entry.get("positions_closed", 0),
            decisions_json   = json.dumps(entry.get("decisions", [])),
        )
        session.add(e)
        await session.commit()
        await session.refresh(e)
        return e.id


async def get_ai_journal_entries(limit: int = 10) -> list[dict]:
    async with get_session_factory()() as session:
        q = select(AIJournalEntry).order_by(AIJournalEntry.created_at.desc()).limit(limit)
        result = await session.execute(q)
        return [
            {
                "id":               e.id,
                "created_at":       e.created_at.isoformat() if e.created_at else None,
                "journal_text":     e.journal_text,
                "strategy_notes":   e.strategy_notes,
                "capital_before":   e.capital_before,
                "capital_after":    e.capital_after,
                "positions_opened": e.positions_opened,
                "positions_closed": e.positions_closed,
                "decisions":        json.loads(e.decisions_json or "[]"),
            }
            for e in result.scalars().all()
        ]


# ── AI Signal Outcome & Pattern Memory functions ──────────────────────────────

async def save_signal_outcomes(signals: list[dict]) -> int:
    """Bulk-insert signal outcomes, skip duplicates (uq_signal_outcome constraint).

    Each signal dict should have keys: symbol, signal_date (str YYYY-MM-DD), tier, score,
    ats_signal, readiness_tier, flow_signals (list), flow_risks (list), risk_flags (list),
    price_at_signal.
    Returns count of rows actually inserted.
    """
    from datetime import date as _date
    inserted = 0
    for sig in signals:
        try:
            async with get_session_factory()() as session:
                sig_date = sig.get("signal_date")
                if isinstance(sig_date, str):
                    sig_date = _date.fromisoformat(sig_date)
                row = AISignalOutcome(
                    symbol          = str(sig["symbol"]).upper(),
                    signal_date     = sig_date,
                    tier            = sig.get("tier", ""),
                    score           = sig.get("score"),
                    ats_signal      = sig.get("ats_signal"),
                    readiness_tier  = sig.get("readiness_tier"),
                    flow_signals    = json.dumps(sig.get("flow_signals") or []),
                    flow_risks      = json.dumps(sig.get("flow_risks") or []),
                    risk_flags      = json.dumps(sig.get("risk_flags") or []),
                    price_at_signal = sig.get("price_at_signal"),
                )
                session.add(row)
                await session.commit()
                inserted += 1
        except IntegrityError:
            # Duplicate — skip silently
            pass
        except Exception as e:
            logger.debug(f"save_signal_outcomes row error ({sig.get('symbol')}): {e}")
    return inserted


async def get_pending_backfill(min_age_days: int = 3, limit: int = 60) -> list[dict]:
    """Return outcomes older than min_age_days with no backfill yet."""
    cutoff = datetime.utcnow() - timedelta(days=min_age_days)
    async with get_session_factory()() as session:
        q = (
            select(AISignalOutcome)
            .where(
                AISignalOutcome.backfilled_at.is_(None),
                AISignalOutcome.recorded_at < cutoff,
            )
            .order_by(AISignalOutcome.recorded_at.asc())
            .limit(limit)
        )
        result = await session.execute(q)
        return [
            {
                "id":              r.id,
                "symbol":          r.symbol,
                "signal_date":     r.signal_date.isoformat() if r.signal_date else None,
                "price_at_signal": r.price_at_signal,
                "tier":            r.tier,
                "ats_signal":      r.ats_signal,
                "readiness_tier":  r.readiness_tier,
            }
            for r in result.scalars().all()
        ]


async def fill_signal_returns(outcome_id: int, data: dict):
    """Fill price_3d/7d/14d, gain_3d/7d/14d, max_gain_14d, outcome_label, backfilled_at."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(AISignalOutcome).where(AISignalOutcome.id == outcome_id)
        )
        row = result.scalar_one_or_none()
        if not row:
            return
        row.price_3d      = data.get("price_3d")
        row.price_7d      = data.get("price_7d")
        row.price_14d     = data.get("price_14d")
        row.gain_3d       = data.get("gain_3d")
        row.gain_7d       = data.get("gain_7d")
        row.gain_14d      = data.get("gain_14d")
        row.max_gain_14d  = data.get("max_gain_14d")
        row.outcome_label = data.get("outcome_label")
        row.backfilled_at = datetime.utcnow()
        await session.commit()


async def get_pattern_stats_from_outcomes() -> list[dict]:
    """Compute win rates per pattern_key from backfilled outcomes.

    pattern_key = f"{tier}|{ats_signal}|{readiness_tier}"
    A 'win' is outcome_label in ('WIN', 'WIN_STRONG').
    Returns list of dicts: pattern_key, n_total, n_wins, win_rate, avg_gain_7d, avg_max_gain.
    """
    async with get_session_factory()() as session:
        q = select(AISignalOutcome).where(AISignalOutcome.backfilled_at.isnot(None))
        result = await session.execute(q)
        rows = result.scalars().all()

    stats: dict[str, dict] = {}
    for r in rows:
        key = f"{r.tier}|{r.ats_signal or ''}|{r.readiness_tier or ''}"
        if key not in stats:
            stats[key] = {"n_total": 0, "n_wins": 0, "gain_7d_sum": 0.0, "max_gain_sum": 0.0}
        stats[key]["n_total"] += 1
        if r.outcome_label in ("WIN", "WIN_STRONG"):
            stats[key]["n_wins"] += 1
        if r.gain_7d is not None:
            stats[key]["gain_7d_sum"] += r.gain_7d
        if r.max_gain_14d is not None:
            stats[key]["max_gain_sum"] += r.max_gain_14d

    out = []
    for key, s in stats.items():
        n = s["n_total"]
        out.append({
            "pattern_key":  key,
            "n_total":      n,
            "n_wins":       s["n_wins"],
            "win_rate":     round(s["n_wins"] / n, 3) if n > 0 else 0.0,
            "avg_gain_7d":  round(s["gain_7d_sum"] / n, 2) if n > 0 else None,
            "avg_max_gain": round(s["max_gain_sum"] / n, 2) if n > 0 else None,
        })
    out.sort(key=lambda x: x["n_total"], reverse=True)
    return out


async def upsert_pattern_memory(
    pattern_key: str,
    n_trades: int,
    n_wins: int,
    win_rate: float,
    avg_win_pct: float | None,
    avg_loss_pct: float | None,
    notes: str | None = None,
):
    """Create or update a pattern memory row."""
    async with get_session_factory()() as session:
        result = await session.execute(
            select(AIPatternMemory).where(AIPatternMemory.pattern_key == pattern_key)
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = AIPatternMemory(pattern_key=pattern_key)
            session.add(row)
        row.n_trades     = n_trades
        row.n_wins       = n_wins
        row.win_rate     = win_rate
        row.avg_win_pct  = avg_win_pct
        row.avg_loss_pct = avg_loss_pct
        row.updated_at   = datetime.utcnow()
        if notes is not None:
            row.notes = notes
        await session.commit()


async def get_pattern_memory(limit: int = 15) -> list[dict]:
    """Return patterns ordered by n_trades DESC."""
    async with get_session_factory()() as session:
        q = (
            select(AIPatternMemory)
            .order_by(AIPatternMemory.n_trades.desc())
            .limit(limit)
        )
        result = await session.execute(q)
        return [
            {
                "id":            r.id,
                "pattern_key":   r.pattern_key,
                "updated_at":    r.updated_at.isoformat() if r.updated_at else None,
                "n_trades":      r.n_trades,
                "n_wins":        r.n_wins,
                "win_rate":      r.win_rate,
                "avg_win_pct":   r.avg_win_pct,
                "avg_loss_pct":  r.avg_loss_pct,
                "avg_hold_days": r.avg_hold_days,
                "best_trade":    r.best_trade,
                "notes":         r.notes,
            }
            for r in result.scalars().all()
        ]


async def get_ai_performance_stats() -> dict:
    """Aggregate stats from all CLOSED AIJournalPosition rows.

    Returns: total_trades, n_wins, win_rate, avg_win_pct, avg_loss_pct,
             total_pnl_usd, best_trade (symbol+pnl_pct), worst_trade (symbol+pnl_pct)
    """
    async with get_session_factory()() as session:
        q = select(AIJournalPosition).where(AIJournalPosition.status == "CLOSED")
        result = await session.execute(q)
        closed = result.scalars().all()

    if not closed:
        return {
            "total_trades": 0,
            "n_wins":       0,
            "win_rate":     0.0,
            "avg_win_pct":  None,
            "avg_loss_pct": None,
            "total_pnl_usd": 0.0,
            "best_trade":   None,
            "worst_trade":  None,
        }

    wins  = [p for p in closed if (p.pnl_usd or 0) > 0]
    loses = [p for p in closed if (p.pnl_usd or 0) <= 0]

    avg_win  = round(sum(p.pnl_pct for p in wins) / len(wins), 2) if wins else None
    avg_loss = round(sum(p.pnl_pct for p in loses) / len(loses), 2) if loses else None

    best  = max(closed, key=lambda p: p.pnl_pct or 0.0)
    worst = min(closed, key=lambda p: p.pnl_pct or 0.0)

    return {
        "total_trades": len(closed),
        "n_wins":       len(wins),
        "win_rate":     round(len(wins) / len(closed), 3),
        "avg_win_pct":  avg_win,
        "avg_loss_pct": avg_loss,
        "total_pnl_usd": round(sum(p.pnl_usd or 0 for p in closed), 2),
        "best_trade":   {"symbol": best.symbol,  "pnl_pct": round(best.pnl_pct or 0, 2)},
        "worst_trade":  {"symbol": worst.symbol, "pnl_pct": round(worst.pnl_pct or 0, 2)},
    }


async def get_recent_signal_outcomes(limit: int = 20) -> list[dict]:
    """Return the most recent backfilled signal outcomes."""
    async with get_session_factory()() as session:
        q = (
            select(AISignalOutcome)
            .where(AISignalOutcome.outcome_label.isnot(None))
            .order_by(AISignalOutcome.signal_date.desc())
            .limit(limit)
        )
        result = await session.execute(q)
        return [
            {
                "symbol":        r.symbol,
                "tier":          r.tier,
                "ats_signal":    r.ats_signal,
                "readiness_tier": r.readiness_tier,
                "gain_7d":       r.gain_7d,
                "max_gain_14d":  r.max_gain_14d,
                "outcome_label": r.outcome_label,
                "signal_date":   r.signal_date.isoformat() if r.signal_date else None,
            }
            for r in result.scalars().all()
        ]


# ── Trade Lessons ──────────────────────────────────────────────────────────────

async def save_trade_lesson(lesson: dict) -> int:
    async with get_session_factory()() as session:
        row = TradeLesson(
            position_id    = lesson.get("position_id"),
            symbol         = lesson.get("symbol", ""),
            pnl_pct        = lesson.get("pnl_pct"),
            exit_reason    = lesson.get("exit_reason"),
            scan_tier      = lesson.get("scan_tier"),
            ats_signal     = lesson.get("ats_signal"),
            readiness_tier = lesson.get("readiness_tier"),
            flow_signals   = json.dumps(lesson.get("flow_signals") or []),
            what_worked    = lesson.get("what_worked"),
            what_failed    = lesson.get("what_failed"),
            lesson         = lesson.get("lesson"),
            confidence     = lesson.get("confidence"),
            tags           = json.dumps(lesson.get("tags") or []),
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row.id


async def get_trade_lessons(limit: int = 20) -> list[dict]:
    async with get_session_factory()() as session:
        q = select(TradeLesson).order_by(TradeLesson.created_at.desc()).limit(limit)
        result = await session.execute(q)
        return [
            {
                "id":            r.id,
                "created_at":    r.created_at.isoformat() if r.created_at else None,
                "position_id":   r.position_id,
                "symbol":        r.symbol,
                "pnl_pct":       r.pnl_pct,
                "exit_reason":   r.exit_reason,
                "scan_tier":     r.scan_tier,
                "ats_signal":    r.ats_signal,
                "readiness_tier": r.readiness_tier,
                "flow_signals":  json.loads(r.flow_signals or "[]"),
                "what_worked":   r.what_worked,
                "what_failed":   r.what_failed,
                "lesson":        r.lesson,
                "confidence":    r.confidence,
                "tags":          json.loads(r.tags or "[]"),
            }
            for r in result.scalars().all()
        ]


# ── Signal Blacklist ───────────────────────────────────────────────────────────

async def upsert_signal_blacklist(
    pattern_key: str,
    reason: str,
    n_failures: int = 1,
    suspended_until: datetime | None = None,
) -> None:
    async with get_session_factory()() as session:
        result = await session.execute(
            select(SignalBlacklist).where(SignalBlacklist.pattern_key == pattern_key)
        )
        row = result.scalar_one_or_none()
        if row:
            row.reason          = reason
            row.n_failures      = n_failures
            row.suspended_until = suspended_until
            row.updated_at      = datetime.utcnow()
        else:
            row = SignalBlacklist(
                pattern_key     = pattern_key,
                reason          = reason,
                n_failures      = n_failures,
                suspended_until = suspended_until,
            )
            session.add(row)
        await session.commit()


async def remove_signal_blacklist(pattern_key: str) -> None:
    async with get_session_factory()() as session:
        result = await session.execute(
            select(SignalBlacklist).where(SignalBlacklist.pattern_key == pattern_key)
        )
        row = result.scalar_one_or_none()
        if row:
            await session.delete(row)
            await session.commit()


async def get_blacklisted_patterns() -> list[dict]:
    """Return all active blacklist entries (expired suspensions excluded)."""
    now = datetime.utcnow()
    async with get_session_factory()() as session:
        q = select(SignalBlacklist).order_by(SignalBlacklist.n_failures.desc())
        result = await session.execute(q)
        rows = result.scalars().all()
        return [
            {
                "pattern_key":     r.pattern_key,
                "reason":          r.reason,
                "n_failures":      r.n_failures,
                "suspended_until": r.suspended_until.isoformat() if r.suspended_until else None,
                "active":          r.suspended_until is None or r.suspended_until > now,
                "created_at":      r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
