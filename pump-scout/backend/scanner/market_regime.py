"""
Market Regime Detector + Sector Strength Calculator.
Runs once per day at 8:00 AM ET (scheduled) or on-demand.
"""
import json
import logging
from datetime import date, datetime

logger = logging.getLogger(__name__)

REGIME_ETFS = ["SPY", "QQQ", "XLE", "XLV", "XLU", "GLD"]

# ── In-memory cache ──────────────────────────────────────────────────────────
_regime_cache: dict | None = None
_regime_cache_date: str | None = None
_sector_strength_cache: dict | None = None
_sector_strength_cache_date: str | None = None


async def fetch_etf_data(symbol: str) -> dict | None:
    """Fetch 1-day change, 5-day change and EMA20 for an ETF via yfinance."""
    try:
        import yfinance as yf
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="30d")
        if hist.empty or len(hist) < 6:
            return None

        current = float(hist["Close"].iloc[-1])
        prev = float(hist["Close"].iloc[-2])
        pct_1d = (current - prev) / prev * 100

        prev_5 = float(hist["Close"].iloc[-6])
        pct_5d = (current - prev_5) / prev_5 * 100

        ema20 = float(hist["Close"].ewm(span=20).mean().iloc[-1])
        vs_ema20 = (current - ema20) / ema20 * 100

        return {
            "symbol": symbol,
            "price": round(current, 2),
            "pct_1d": round(pct_1d, 2),
            "pct_5d": round(pct_5d, 2),
            "vs_ema20": round(vs_ema20, 2),
            "above_ema20": current > ema20,
        }
    except Exception as e:
        logger.warning(f"fetch_etf_data failed for {symbol}: {e}")
        return None


async def detect_market_regime() -> dict:
    """
    Detect the current market regime using ETF data.
    Saves to DB and updates in-memory cache.
    """
    global _regime_cache, _regime_cache_date

    logger.info("Detecting market regime...")

    etf_data: dict = {}
    for sym in REGIME_ETFS:
        data = await fetch_etf_data(sym)
        if data:
            etf_data[sym] = data

    spy = etf_data.get("SPY", {})
    qqq = etf_data.get("QQQ", {})
    xle = etf_data.get("XLE", {})
    xlv = etf_data.get("XLV", {})
    xlu = etf_data.get("XLU", {})
    gld = etf_data.get("GLD", {})

    regime = "NEUTRAL"
    strong_sectors: list[str] = []
    weak_sectors: list[str] = []
    recommendation = ""

    # FEAR: Gold rising + SPY falling
    if gld.get("pct_5d", 0) > 2 and spy.get("pct_5d", 0) < -2:
        regime = "FEAR"
        strong_sectors = ["Materials", "Utilities", "Healthcare"]
        weak_sectors = ["Technology", "Consumer Cyclical", "Financial"]
        recommendation = "Рынок в страхе. Фокус на defensive секторах. Только FIRE сигналы."

    # RISK_OFF: SPY below EMA20 + Utilities outperform
    elif not spy.get("above_ema20", True) and xlu.get("pct_5d", 0) > qqq.get("pct_5d", 0):
        regime = "RISK_OFF"
        strong_sectors = ["Utilities", "Healthcare", "Consumer Defensive"]
        weak_sectors = ["Technology", "Communication", "Consumer Cyclical"]
        recommendation = "Защитный режим. Предпочитать Healthcare и Utilities."

    # ROTATION_ENERGY: Energy strongly outperforms
    elif xle.get("pct_5d", 0) > spy.get("pct_5d", 0) + 3:
        regime = "ROTATION_ENERGY"
        strong_sectors = ["Energy", "Materials"]
        weak_sectors = ["Technology", "Consumer Cyclical"]
        recommendation = "Ротация в Energy. Искать нефтяные sympathy сделки."

    # ROTATION_DEFENSIVE: Defensive beats growth
    elif (xlv.get("pct_5d", 0) > qqq.get("pct_5d", 0) + 2 or
          xlu.get("pct_5d", 0) > qqq.get("pct_5d", 0) + 2):
        regime = "ROTATION_DEFENSIVE"
        strong_sectors = ["Healthcare", "Consumer Defensive", "Utilities"]
        weak_sectors = ["Technology", "Communication"]
        recommendation = "Деньги перетекают в defensive. Biotech и Healthcare в приоритете."

    # RISK_ON: SPY + QQQ above EMA20
    elif (spy.get("above_ema20", False) and
          qqq.get("above_ema20", False) and
          qqq.get("pct_5d", 0) > 0):
        regime = "RISK_ON"
        strong_sectors = ["Technology", "Communication", "Consumer Cyclical"]
        weak_sectors = ["Utilities", "Consumer Defensive"]
        recommendation = "Бычий рынок. Фокус на Growth секторах. Все сигналы активны."

    else:
        regime = "NEUTRAL"
        strong_sectors = []
        weak_sectors = []
        recommendation = "Нейтральный рынок. Работать по обычным сигналам."

    result = {
        "regime": regime,
        "date": date.today().isoformat(),
        "spy_pct": spy.get("pct_1d", 0),
        "qqq_pct": qqq.get("pct_1d", 0),
        "xle_pct": xle.get("pct_1d", 0),
        "xlv_pct": xlv.get("pct_1d", 0),
        "xlu_pct": xlu.get("pct_1d", 0),
        "gld_pct": gld.get("pct_1d", 0),
        "spy_vs_ema20": spy.get("vs_ema20", 0),
        "qqq_vs_ema20": qqq.get("vs_ema20", 0),
        "strong_sectors": strong_sectors,
        "weak_sectors": weak_sectors,
        "recommendation": recommendation,
        "etf_details": etf_data,
    }

    # Persist to DB
    try:
        from database import save_market_regime
        await save_market_regime(result)
    except Exception as e:
        logger.warning(f"save_market_regime failed (non-fatal): {e}")

    _regime_cache = result
    _regime_cache_date = date.today().isoformat()
    logger.info(f"Market regime detected: {regime}")
    return result


async def get_latest_regime() -> dict | None:
    """Return today's regime from cache → DB."""
    global _regime_cache, _regime_cache_date

    today = date.today().isoformat()
    if _regime_cache and _regime_cache_date == today:
        return _regime_cache

    try:
        from database import get_market_regime_latest
        regime = await get_market_regime_latest()
        if regime:
            _regime_cache = regime
            _regime_cache_date = regime.get("date", today)
            return regime
    except Exception as e:
        logger.warning(f"get_latest_regime DB lookup failed: {e}")

    return None


async def calculate_sector_strength(scan_results: list) -> dict:
    """
    Group scan results by sector and compute aggregate strength metrics.
    Called after every scan. Saves to DB and returns result dict.
    """
    global _sector_strength_cache, _sector_strength_cache_date

    from scanner.sector_sympathy import _KNOWN_SECTORS

    sectors: dict = {}

    for r in scan_results:
        sector = r.get("sector", "Unknown")
        if sector == "Unknown":
            continue

        if sector not in sectors:
            sectors[sector] = {
                "tickers": [],
                "scores": [],
                "cmf_pctls": [],
                "vol_ratios": [],
                "price_changes": [],
            }

        indicators = r.get("indicators", {})
        score_val = r.get("score", {}).get("total_score", 0)

        sectors[sector]["tickers"].append(r["symbol"])
        sectors[sector]["scores"].append(score_val)
        sectors[sector]["cmf_pctls"].append(indicators.get("cmf_pctl", 50))
        sectors[sector]["vol_ratios"].append(indicators.get("anomaly_ratio", 1))
        sectors[sector]["price_changes"].append(indicators.get("price_change_pct", 0))

    result: dict = {}
    for sector, data in sectors.items():
        if not data["scores"]:
            continue

        scores = data["scores"]
        avg_score = sum(scores) / len(scores)
        avg_cmf = sum(data["cmf_pctls"]) / len(data["cmf_pctls"])
        avg_vol = sum(data["vol_ratios"]) / len(data["vol_ratios"])
        momentum = sum(data["price_changes"]) / len(data["price_changes"])

        best_idx = scores.index(max(scores))
        leader = data["tickers"][best_idx]

        result[sector] = {
            "sector": sector,
            "ticker_count": len(data["tickers"]),
            "avg_score": round(avg_score, 1),
            "avg_cmf_pctl": round(avg_cmf, 1),
            "avg_vol_ratio": round(avg_vol, 2),
            "momentum_pct": round(momentum, 2),
            "leader_symbol": leader,
            "leader_score": round(max(scores), 1),
            "tickers": data["tickers"],
        }

    # Persist to DB
    try:
        from database import save_sector_strength
        await save_sector_strength(result)
    except Exception as e:
        logger.warning(f"save_sector_strength failed (non-fatal): {e}")

    _sector_strength_cache = result
    _sector_strength_cache_date = date.today().isoformat()
    logger.info(f"Sector strength calculated for {len(result)} sectors")
    return result


async def get_latest_sector_strength() -> dict:
    """Return today's sector strength from cache → DB."""
    global _sector_strength_cache, _sector_strength_cache_date

    today = date.today().isoformat()
    if _sector_strength_cache and _sector_strength_cache_date == today:
        return _sector_strength_cache

    try:
        from database import get_sector_strength_latest
        data = await get_sector_strength_latest()
        if data:
            _sector_strength_cache = data
            _sector_strength_cache_date = today
            return data
    except Exception as e:
        logger.warning(f"get_latest_sector_strength DB lookup failed: {e}")

    return {}
