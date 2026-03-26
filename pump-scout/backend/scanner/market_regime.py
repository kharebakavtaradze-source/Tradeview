"""
Market Regime Detector + Sector Strength Calculator.
Runs once per day at 16:15 ET (after close) to capture previous-day closing prices.
If today's data is unavailable, callers fall back to the most recent date in the DB.
"""
import json
import logging
from datetime import date, datetime

import httpx

logger = logging.getLogger(__name__)

REGIME_ETFS = ["SPY", "QQQ", "XLE", "XLV", "XLU", "GLD"]

_YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.5",
}

# ── In-memory cache ──────────────────────────────────────────────────────────
_regime_cache: dict | None = None
_regime_cache_date: str | None = None
_sector_strength_cache: dict | None = None
_sector_strength_cache_date: str | None = None


async def fetch_etf_data(symbol: str) -> dict | None:
    """Fetch 1-day change, 5-day change and EMA20 for an ETF via Yahoo Finance API."""
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol.upper()}"
    try:
        async with httpx.AsyncClient(timeout=15.0, headers=_YAHOO_HEADERS) as client:
            resp = await client.get(url, params={"interval": "1d", "range": "60d"})
            if resp.status_code != 200:
                logger.warning(f"fetch_etf_data {symbol}: HTTP {resp.status_code}")
                return None

            chart = resp.json().get("chart", {})
            result = chart.get("result") or []
            if not result:
                return None

            closes = result[0].get("indicators", {}).get("quote", [{}])[0].get("close", [])
            closes = [float(c) for c in closes if c is not None]
            if len(closes) < 6:
                return None

            current = closes[-1]
            prev    = closes[-2]
            prev_5  = closes[-6]

            pct_1d = (current - prev) / prev * 100
            pct_5d = (current - prev_5) / prev_5 * 100

            # EMA20 (exponential moving average, alpha = 2/21)
            alpha = 2.0 / 21.0
            ema = closes[0]
            for p in closes[1:]:
                ema = alpha * p + (1.0 - alpha) * ema
            ema20 = ema
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
    Falls back to most recent non-zero DB row if all ETF values are 0 or None.
    """
    global _regime_cache, _regime_cache_date

    logger.info("Detecting market regime...")

    etf_data: dict = {}
    for sym in REGIME_ETFS:
        data = await fetch_etf_data(sym)
        if data:
            etf_data[sym] = data

    # If all key ETF pct values are zero/missing, fall back to last good DB row
    spy_pct = etf_data.get("SPY", {}).get("pct_1d", 0)
    qqq_pct = etf_data.get("QQQ", {}).get("pct_1d", 0)
    if not etf_data or (spy_pct == 0 and qqq_pct == 0):
        logger.warning("ETF data appears empty/zero — checking DB for most recent non-zero regime")
        try:
            from database import get_market_regime_latest
            fallback = await get_market_regime_latest()
            if fallback and (fallback.get("spy_pct") or fallback.get("qqq_pct")):
                logger.warning(f"Using cached regime from {fallback.get('date')} (ETF fetch returned no data)")
                _regime_cache = fallback
                _regime_cache_date = fallback.get("date", date.today().isoformat())
                return fallback
        except Exception as e:
            logger.warning(f"DB fallback for regime failed: {e}")

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
    """Return today's regime from cache → DB.
    If today's data is not yet available (regime runs at 16:15),
    returns the most recent available date from the DB as a fallback.
    """
    global _regime_cache, _regime_cache_date

    today = date.today().isoformat()
    if _regime_cache and _regime_cache_date == today:
        return _regime_cache

    try:
        from database import get_market_regime_latest
        # get_market_regime_latest() returns the most recent row regardless of date,
        # so scans run before 16:15 will use the previous trading day's regime.
        regime = await get_market_regime_latest()
        if regime:
            _regime_cache = regime
            _regime_cache_date = regime.get("date", today)
            if regime.get("date") != today:
                logger.info(f"Market regime: using most recent available ({regime.get('date')}) — today's not yet saved")
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
