"""Sector engine — multi-timeframe performance, EMA trend, RS, RRG, and risk mode."""
import asyncio
import math
import time
from datetime import date
from typing import Optional

# ── ETF / sector maps ─────────────────────────────────────────────────────────
SECTOR_ETFS: dict[str, str] = {
    "XLC":  "Communication Services",
    "XLY":  "Consumer Discretionary",
    "XLP":  "Consumer Staples",
    "XLE":  "Energy",
    "XLF":  "Financials",
    "XLV":  "Health Care",
    "XLI":  "Industrials",
    "XLB":  "Materials",
    "XLRE": "Real Estate",
    "XLK":  "Technology",
    "XLU":  "Utilities",
}

BENCHMARK_ETFS  = ["SPY", "QQQ", "IWM", "DIA"]
BENCHMARK_NAMES = {"SPY": "S&P 500", "QQQ": "Nasdaq 100", "IWM": "Russell 2000", "DIA": "Dow Jones"}

_GROWTH_SECTORS    = {"XLK", "XLY", "XLF", "XLI", "XLC"}
_DEFENSIVE_SECTORS = {"XLP", "XLV", "XLU", "XLRE"}

_TOP_HOLDINGS: dict[str, list[str]] = {
    "XLC":  ["META", "GOOGL", "GOOG", "NFLX", "VZ", "T", "DIS", "TMUS", "EA", "OMC"],
    "XLY":  ["AMZN", "TSLA", "HD", "MCD", "BKNG", "NKE", "LOW", "TJX", "CMG", "SBUX"],
    "XLP":  ["PG", "KO", "PEP", "COST", "WMT", "PM", "MO", "MDLZ", "CL", "STZ"],
    "XLE":  ["XOM", "CVX", "COP", "EOG", "SLB", "MPC", "PSX", "VLO", "OXY", "HES"],
    "XLF":  ["BRK-B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "C", "SCHW"],
    "XLV":  ["UNH", "LLY", "JNJ", "ABBV", "MRK", "TMO", "ABT", "DHR", "AMGN", "PFE"],
    "XLI":  ["GE", "RTX", "CAT", "UPS", "HON", "DE", "BA", "LMT", "MMM", "ETN"],
    "XLB":  ["LIN", "APD", "ECL", "SHW", "FCX", "NEM", "DOW", "PPG", "NUE", "ALB"],
    "XLRE": ["PLD", "AMT", "EQIX", "WELL", "PSA", "SPG", "DLR", "O", "AVB", "EXR"],
    "XLK":  ["AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "ADBE", "CRM", "AMD", "QCOM", "ACN"],
    "XLU":  ["NEE", "DUK", "SO", "D", "AEP", "SRE", "PCG", "EXC", "XEL", "ED"],
}

# ── 30-minute in-memory cache ─────────────────────────────────────────────────
_TTL = 1800
_cache:    dict[str, object] = {}
_cache_ts: dict[str, float]  = {}


def _cached(key: str):
    if key in _cache and time.time() - _cache_ts.get(key, 0) < _TTL:
        return _cache[key]
    return None


def _set_cache(key: str, value):
    _cache[key]    = value
    _cache_ts[key] = time.time()
    return value


# ── Math helpers ──────────────────────────────────────────────────────────────
def _closes(candles: list) -> list:
    return [c["c"] for c in candles]


def _ema(values: list, period: int) -> float:
    if not values:
        return 0.0
    if len(values) <= period:
        return values[-1]
    k   = 2.0 / (period + 1)
    ema = sum(values[:period]) / period
    for v in values[period:]:
        ema = v * k + ema * (1 - k)
    return ema


def _safe_pct(closes: list, bars_back: int) -> Optional[float]:
    if len(closes) < bars_back + 1 or closes[-bars_back - 1] == 0:
        return None
    return round((closes[-1] / closes[-bars_back - 1] - 1) * 100, 2)


def _norm_to_100(vals: list) -> list:
    """Z-score normalization centered at 100 with 10-unit std-dev."""
    if len(vals) < 2:
        return [100.0] * len(vals)
    mean = sum(vals) / len(vals)
    std  = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))
    if std == 0:
        return [100.0] * len(vals)
    return [round(100 + (v - mean) / std * 10, 2) for v in vals]


# ── Candle fetching ───────────────────────────────────────────────────────────
async def _fetch_candles(symbol: str, days: int = 220) -> list:
    from scanner.massive_data import fetch_candles_massive
    return await fetch_candles_massive(symbol, days=days)


# ── Compute functions ─────────────────────────────────────────────────────────
def compute_sector_performance(candles: list, spy_closes: list) -> dict:
    closes = _closes(candles)
    if not closes:
        return {}

    def _vs(etf_ret: Optional[float], bars_back: int) -> Optional[float]:
        if etf_ret is None:
            return None
        spy_ret = _safe_pct(spy_closes, bars_back)
        if spy_ret is None:
            return None
        return round(etf_ret - spy_ret, 2)

    r1d   = _safe_pct(closes, 1)
    r5d   = _safe_pct(closes, 5)
    r20d  = _safe_pct(closes, 20)
    r50d  = _safe_pct(closes, 50)
    r200d = _safe_pct(closes, 200)

    return {
        "close":      round(closes[-1], 2),
        "ret_1d":     r1d,
        "ret_5d":     r5d,
        "ret_20d":    r20d,
        "ret_50d":    r50d,
        "ret_200d":   r200d,
        "vs_spy_1d":  _vs(r1d,  1),
        "vs_spy_5d":  _vs(r5d,  5),
        "vs_spy_20d": _vs(r20d, 20),
    }


def compute_sector_trend(candles: list) -> dict:
    closes = _closes(candles)
    if len(closes) < 20:
        return {"trend_label": "NEUTRAL", "ema_20": None, "ema_50": None, "ema_200": None}

    e20  = _ema(closes, 20)
    e50  = _ema(closes, 50)  if len(closes) >= 50  else None
    e200 = _ema(closes, 200) if len(closes) >= 200 else None
    px   = closes[-1]

    if   e200 and e50 and px > e20 > e50 > e200:
        label = "LEADING"
    elif e50 and px > e20 and e20 > e50:
        label = "IMPROVING"
    elif e50 and px < e20 and e20 < e50:
        label = "WEAKENING"
    elif e200 and e50 and px < e20 < e50 < e200:
        label = "LAGGING"
    else:
        label = "NEUTRAL"

    return {
        "trend_label": label,
        "ema_20":  round(e20, 2),
        "ema_50":  round(e50,  2) if e50  else None,
        "ema_200": round(e200, 2) if e200 else None,
    }


def compute_relative_strength(etf_candles: list, spy_candles: list) -> dict:
    n = min(len(etf_candles), len(spy_candles))
    if n < 21:
        return {"rs_ratio": 1.0, "rs_momentum": 1.0, "rs_trend": "NEUTRAL"}

    etf_c = _closes(etf_candles[-n:])
    spy_c = _closes(spy_candles[-n:])

    rs_vals = [e / s for e, s in zip(etf_c, spy_c) if s != 0]
    if len(rs_vals) < 21:
        return {"rs_ratio": 1.0, "rs_momentum": 1.0, "rs_trend": "NEUTRAL"}

    rs_now = rs_vals[-1]
    rs_20b = rs_vals[-21]
    rs_mom = round(rs_now / rs_20b, 4) if rs_20b != 0 else 1.0

    lookback = rs_vals[-52:] if len(rs_vals) >= 52 else rs_vals
    mean_rs  = sum(lookback) / len(lookback)
    rs_norm  = round(rs_now / mean_rs, 4) if mean_rs != 0 else 1.0

    trend = (
        "OUTPERFORMING"   if rs_now > rs_20b * 1.02 else
        "UNDERPERFORMING" if rs_now < rs_20b * 0.98 else
        "NEUTRAL"
    )

    return {"rs_ratio": rs_norm, "rs_momentum": rs_mom, "rs_trend": trend}


def compute_rrg_data(etf_series: dict, spy_candles: list) -> dict:
    """Normalized RRG coordinates (x, y) centered at 100."""
    spy_c = _closes(spy_candles)

    raw: dict[str, dict] = {}
    for etf, candles in etf_series.items():
        n = min(len(candles), len(spy_c))
        if n < 30:
            continue
        ec     = _closes(candles[-n:])
        sc     = spy_c[-n:]
        rs_ser = [e / s for e, s in zip(ec, sc) if s != 0]
        if len(rs_ser) < 11:
            continue

        rs_now = rs_ser[-1]
        rs_10b = rs_ser[-11]
        rs_mom = rs_now / rs_10b if rs_10b != 0 else 1.0

        # Weekly trail: last 5 samples every 5 bars
        trail_rs  = [rs_ser[-1 - i * 5] for i in range(4, -1, -1) if len(rs_ser) > i * 5]
        trail_mom = [
            round(trail_rs[j] / trail_rs[j - 1], 6) if j > 0 and trail_rs[j - 1] != 0 else 1.0
            for j in range(len(trail_rs))
        ]

        raw[etf] = {"rs": rs_now, "mom": rs_mom, "trail_rs": trail_rs, "trail_mom": trail_mom}

    if not raw:
        return {}

    etf_list = list(raw.keys())
    rs_norm  = _norm_to_100([raw[e]["rs"]  for e in etf_list])
    mom_norm = _norm_to_100([raw[e]["mom"] for e in etf_list])

    out = {}
    for i, etf in enumerate(etf_list):
        x = rs_norm[i]
        y = mom_norm[i]
        quadrant = (
            "LEADING"   if x >= 100 and y >= 100 else
            "WEAKENING" if x >= 100 and y <  100 else
            "LAGGING"   if x <  100 and y <  100 else
            "IMPROVING"
        )
        out[etf] = {
            "x": x, "y": y,
            "quadrant":  quadrant,
            "name":      SECTOR_ETFS.get(etf, etf),
            "trail_rs":  [round(v, 6) for v in raw[etf]["trail_rs"]],
            "trail_mom": raw[etf]["trail_mom"],
        }

    return out


def compute_risk_mode(sector_data: dict) -> dict:
    grow_rets = [v["ret_5d"] for k, v in sector_data.items()
                 if k in _GROWTH_SECTORS    and v.get("ret_5d") is not None]
    def_rets  = [v["ret_5d"] for k, v in sector_data.items()
                 if k in _DEFENSIVE_SECTORS and v.get("ret_5d") is not None]

    if not grow_rets or not def_rets:
        return {"risk_mode": "NEUTRAL", "risk_score": 0.0, "growth_avg": 0.0, "defensive_avg": 0.0}

    g_avg = round(sum(grow_rets) / len(grow_rets), 2)
    d_avg = round(sum(def_rets)  / len(def_rets),  2)
    diff  = round(g_avg - d_avg, 2)

    mode = "RISK_ON" if diff > 0.5 else ("RISK_OFF" if diff < -0.5 else "NEUTRAL")
    return {"risk_mode": mode, "risk_score": diff, "growth_avg": g_avg, "defensive_avg": d_avg}


# ── Top movers helper ─────────────────────────────────────────────────────────
def _score_val(r: dict) -> float:
    s = r.get("score")
    if isinstance(s, dict):
        return s.get("total_score", 0) or 0
    return s or 0


def _top_movers_for_etf(etf: str, scan_results: list, n: int = 5) -> list:
    holdings = set(_TOP_HOLDINGS.get(etf, []))
    matches  = [r for r in scan_results if r.get("symbol") in holdings]
    matches.sort(key=_score_val, reverse=True)
    return [
        {
            "symbol":          m["symbol"],
            "score":           round(_score_val(m), 1),
            "price":           m.get("price"),
            "price_change_pct": m.get("indicators", {}).get("price_change_pct"),
            "tier":            m.get("score", {}).get("tier") if isinstance(m.get("score"), dict) else None,
        }
        for m in matches[:n]
    ]


def _load_scan_results() -> list:
    try:
        from scanner.new_pump_runner import get_latest
        scan = get_latest()
        return scan.get("results", []) if scan else []
    except Exception:
        return []


# ── Public API ────────────────────────────────────────────────────────────────
async def get_sector_snapshot() -> dict:
    cached = _cached("overview")
    if cached is not None:
        return cached

    all_syms = list(SECTOR_ETFS.keys()) + BENCHMARK_ETFS
    raw = await asyncio.gather(*[_fetch_candles(s) for s in all_syms], return_exceptions=True)
    candles_map = {s: (r if isinstance(r, list) else []) for s, r in zip(all_syms, raw)}

    spy_c = _closes(candles_map.get("SPY", []))

    # Benchmarks
    benchmarks: dict = {}
    for sym in BENCHMARK_ETFS:
        c = _closes(candles_map.get(sym, []))
        if c:
            benchmarks[sym] = {
                "name":   BENCHMARK_NAMES.get(sym, sym),
                "close":  round(c[-1], 2),
                "ret_1d": _safe_pct(c, 1),
                "ret_5d": _safe_pct(c, 5),
                "ret_20d": _safe_pct(c, 20),
            }

    # Sectors
    sectors_out: dict = {}
    for etf, name in SECTOR_ETFS.items():
        c = candles_map.get(etf, [])
        perf  = compute_sector_performance(c, spy_c)
        trend = compute_sector_trend(c)
        rs    = compute_relative_strength(c, candles_map.get("SPY", []))
        sectors_out[etf] = {"name": name, **perf, **trend, **rs}

    # RRG
    rrg = compute_rrg_data({e: candles_map.get(e, []) for e in SECTOR_ETFS},
                           candles_map.get("SPY", []))
    for etf, rd in rrg.items():
        if etf in sectors_out:
            sectors_out[etf]["rrg_x"]        = rd["x"]
            sectors_out[etf]["rrg_y"]        = rd["y"]
            sectors_out[etf]["rrg_quadrant"] = rd["quadrant"]

    risk = compute_risk_mode(sectors_out)

    data = {
        "as_of":      date.today().isoformat(),
        "risk_mode":  risk["risk_mode"],
        "risk_score": risk["risk_score"],
        "risk_detail": {
            "growth_avg":    risk["growth_avg"],
            "defensive_avg": risk["defensive_avg"],
        },
        "benchmarks": benchmarks,
        "sectors":    sectors_out,
    }
    return _set_cache("overview", data)


async def get_rrg_data() -> dict:
    cached = _cached("rrg")
    if cached is not None:
        return cached

    all_syms = list(SECTOR_ETFS.keys()) + ["SPY"]
    raw = await asyncio.gather(*[_fetch_candles(s) for s in all_syms], return_exceptions=True)
    candles_map = {s: (r if isinstance(r, list) else []) for s, r in zip(all_syms, raw)}

    rrg = compute_rrg_data({e: candles_map[e] for e in SECTOR_ETFS},
                           candles_map.get("SPY", []))
    return _set_cache("rrg", {"sectors": rrg, "as_of": date.today().isoformat()})


async def get_sector_detail(etf: str) -> dict:
    if etf not in SECTOR_ETFS:
        return {}

    ck = f"detail_{etf}"
    cached = _cached(ck)
    if cached is not None:
        return cached

    etf_c, spy_c_raw = await asyncio.gather(_fetch_candles(etf), _fetch_candles("SPY"),
                                             return_exceptions=True)
    etf_candles = etf_c if isinstance(etf_c, list) else []
    spy_candles = spy_c_raw if isinstance(spy_c_raw, list) else []

    perf  = compute_sector_performance(etf_candles, _closes(spy_candles))
    trend = compute_sector_trend(etf_candles)
    rs    = compute_relative_strength(etf_candles, spy_candles)

    scan_results = _load_scan_results()
    movers = _top_movers_for_etf(etf, scan_results)

    data = {
        "etf":          etf,
        "name":         SECTOR_ETFS[etf],
        "top_holdings": _TOP_HOLDINGS.get(etf, []),
        "top_movers":   movers,
        **perf,
        **trend,
        **rs,
    }
    return _set_cache(ck, data)


async def get_all_top_movers() -> dict:
    cached = _cached("top_movers")
    if cached is not None:
        return cached

    scan_results = _load_scan_results()
    out = {etf: _top_movers_for_etf(etf, scan_results) for etf in SECTOR_ETFS}
    return _set_cache("top_movers", {"sectors": out, "as_of": date.today().isoformat()})
