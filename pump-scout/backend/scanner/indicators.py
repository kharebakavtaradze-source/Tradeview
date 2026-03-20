"""
Pure technical indicator functions operating on OHLCV candle dicts.
Each candle: {"t": unix, "o": float, "h": float, "l": float, "c": float, "v": int}
"""
import math
from typing import List, Dict, Any


def sma(values: list, period: int) -> float:
    if len(values) < period:
        return 0.0
    return sum(values[-period:]) / period


def ema(values: list, period: int) -> float:
    if len(values) < period:
        return 0.0
    k = 2.0 / (period + 1)
    result = sum(values[:period]) / period
    for v in values[period:]:
        result = v * k + result * (1 - k)
    return result


def stdev(values: list, period: int) -> float:
    if len(values) < period:
        return 0.0
    window = values[-period:]
    mean = sum(window) / period
    variance = sum((x - mean) ** 2 for x in window) / period
    return math.sqrt(variance)


def percentrank(series: list, period: int) -> float:
    """Percent of last `period` values that are less than the current value."""
    if len(series) < period + 1:
        return 50.0
    current = series[-1]
    window = series[-period - 1 : -1]
    count_below = sum(1 for x in window if x < current)
    return (count_below / period) * 100.0


def calc_bb(candles: list, period: int = 20, mult: float = 2.0) -> dict:
    closes = [c["c"] for c in candles]
    if len(closes) < period:
        return {
            "upper": 0, "basis": 0, "lower": 0,
            "width": 0, "pctl": 50, "squeeze": False, "sqz_bars": 0
        }

    basis = sma(closes, period)
    sd = stdev(closes, period)
    upper = basis + mult * sd
    lower = basis - mult * sd
    width = (upper - lower) / basis if basis > 0 else 0

    # BB width percentile over last 125 bars
    widths = []
    for i in range(min(len(closes), 125)):
        end = len(closes) - i
        if end < period:
            break
        b = sma(closes[:end], period)
        s = stdev(closes[:end], period)
        if b > 0:
            widths.append((b + mult * s - (b - mult * s)) / b)
    widths.reverse()

    pctl = percentrank(widths + [width], len(widths)) if widths else 50.0
    squeeze = pctl < 25

    # Count consecutive squeeze bars
    sqz_bars = 0
    for i in range(len(candles) - 1, -1, -1):
        end = i + 1
        if end < period:
            break
        b_val = sma(closes[:end], period)
        s_val = stdev(closes[:end], period)
        if b_val <= 0:
            break
        w = (b_val + mult * s_val - (b_val - mult * s_val)) / b_val
        # approximate: squeeze if width < historical median
        if w < 0.1:  # tight threshold
            sqz_bars += 1
        else:
            break

    # Recalculate sqz_bars properly using pctl approach
    sqz_bars = 0
    all_widths = []
    for i in range(min(len(closes), 200)):
        end = len(closes) - (len(closes) - 1 - i)
        if end < period:
            continue
        b_v = sma(closes[:end], period)
        s_v = stdev(closes[:end], period)
        if b_v > 0:
            all_widths.append((b_v + mult * s_v - (b_v - mult * s_v)) / b_v)

    if len(all_widths) >= 2:
        for j in range(len(all_widths) - 1, -1, -1):
            pr = percentrank(all_widths[: j + 1], min(j, 124)) if j >= 1 else 50
            if pr < 25:
                sqz_bars += 1
            else:
                break

    return {
        "upper": round(upper, 4),
        "basis": round(basis, 4),
        "lower": round(lower, 4),
        "width": round(width, 6),
        "pctl": round(pctl, 2),
        "squeeze": squeeze,
        "sqz_bars": sqz_bars,
    }


def calc_cmf(candles: list, period: int = 20) -> dict:
    if len(candles) < period:
        return {"value": 0.0, "pctl": 50.0}

    mfvs = []
    vols = []
    for c in candles:
        hl = c["h"] - c["l"]
        if hl == 0:
            mfm = 0.0
        else:
            mfm = ((c["c"] - c["l"]) - (c["h"] - c["c"])) / hl
        mfvs.append(mfm * c["v"])
        vols.append(c["v"])

    sum_mfv = sum(mfvs[-period:])
    sum_vol = sum(vols[-period:])
    cmf_val = sum_mfv / sum_vol if sum_vol > 0 else 0.0

    # Historical CMF values for percentile
    hist_cmf = []
    for i in range(period, len(candles) + 1):
        sv = sum(vols[i - period : i])
        sm = sum(mfvs[i - period : i])
        hist_cmf.append(sm / sv if sv > 0 else 0.0)

    pctl = percentrank(hist_cmf + [cmf_val], len(hist_cmf)) if hist_cmf else 50.0

    return {"value": round(cmf_val, 4), "pctl": round(pctl, 2)}


def calc_volume_anomaly(candles: list) -> dict:
    if len(candles) < 21:
        return {
            "avg_vol_20": 0, "today_vol": 0, "anomaly_ratio": 0,
            "vol_z": 0, "price_change_pct": 0, "is_quiet": False
        }

    volumes = [c["v"] for c in candles]
    closes = [c["c"] for c in candles]

    avg_vol_20 = sma(volumes[:-1], 20)
    avg_vol_5 = sma(volumes[:-1], min(5, len(volumes) - 1))
    today_vol = candles[-1]["v"]

    anomaly_ratio = today_vol / avg_vol_20 if avg_vol_20 > 0 else 0.0
    sd = stdev(volumes[:-1], min(20, len(volumes) - 1))
    vol_z = (today_vol - avg_vol_20) / sd if sd > 0 else 0.0

    close_today = closes[-1]
    close_prev = closes[-2] if len(closes) >= 2 else closes[-1]
    price_change_pct = (close_today - close_prev) / close_prev * 100 if close_prev > 0 else 0.0

    is_quiet = anomaly_ratio > 2.0 and abs(price_change_pct) < 3.0

    return {
        "avg_vol_20": round(avg_vol_20, 0),
        "avg_vol_5": round(avg_vol_5, 0),
        "today_vol": int(today_vol),
        "anomaly_ratio": round(anomaly_ratio, 2),
        "vol_z": round(vol_z, 2),
        "price_change_pct": round(price_change_pct, 2),
        "is_quiet": is_quiet,
    }


def calc_atr(candles: list, period: int = 14) -> dict:
    if len(candles) < period + 1:
        return {"value": 0.0, "ratio": 1.0}

    trs = []
    for i in range(1, len(candles)):
        h = candles[i]["h"]
        l = candles[i]["l"]
        pc = candles[i - 1]["c"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))

    atr_val = sma(trs, period)

    # ATR ratio: current ATR vs SMA of ATR over last 50 bars
    atr_history = [sma(trs[max(0, i - period) : i], min(period, i)) for i in range(period, len(trs) + 1)]
    atr_sma50 = sma(atr_history, min(50, len(atr_history)))
    ratio = atr_val / atr_sma50 if atr_sma50 > 0 else 1.0

    closes = [c["c"] for c in candles]
    price = closes[-1]
    atr_pct = (atr_val / price * 100) if price > 0 else 0

    return {
        "value": round(atr_val, 4),
        "ratio": round(ratio, 2),
        "pct": round(atr_pct, 2),
    }


def calc_all(candles: list) -> dict:
    if len(candles) < 20:
        return {}

    closes = [c["c"] for c in candles]
    volumes = [c["v"] for c in candles]

    bb = calc_bb(candles)
    cmf = calc_cmf(candles)
    vol_anomaly = calc_volume_anomaly(candles)
    atr = calc_atr(candles)

    ema20_val = ema(closes, 20)
    ema50_val = ema(closes, 50)
    ema200_val = ema(closes, min(200, len(closes)))

    price = closes[-1]
    vol_today = volumes[-1]

    return {
        "price": round(price, 4),
        "ema20": round(ema20_val, 4),
        "ema50": round(ema50_val, 4),
        "ema200": round(ema200_val, 4),
        "above_ema20": price > ema20_val,
        "above_ema50": price > ema50_val,
        # Bollinger Bands
        "bb_upper": bb["upper"],
        "bb_basis": bb["basis"],
        "bb_lower": bb["lower"],
        "bb_width": bb["width"],
        "bb_pctl": bb["pctl"],
        "bb_squeeze": bb["squeeze"],
        "bb_sqz_bars": bb["sqz_bars"],
        # CMF
        "cmf": cmf["value"],
        "cmf_pctl": cmf["pctl"],
        # Volume
        "avg_vol_20": vol_anomaly["avg_vol_20"],
        "avg_vol_5": vol_anomaly["avg_vol_5"],
        "today_vol": vol_anomaly["today_vol"],
        "anomaly_ratio": vol_anomaly["anomaly_ratio"],
        "vol_z": vol_anomaly["vol_z"],
        "price_change_pct": vol_anomaly["price_change_pct"],
        "is_quiet": vol_anomaly["is_quiet"],
        # ATR
        "atr": atr["value"],
        "atr_ratio": atr["ratio"],
        "atr_pct": atr["pct"],
    }
