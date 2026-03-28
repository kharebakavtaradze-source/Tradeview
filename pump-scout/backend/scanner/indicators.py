"""
Pure technical indicator functions operating on OHLCV candle dicts.
Each candle: {"t": unix, "o": float, "h": float, "l": float, "c": float, "v": int}
"""
import math
from typing import List, Dict, Any
from .institutional_flow import calc_institutional_flow


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

    # Count consecutive squeeze bars using percentile approach
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


def _calc_rsi_series(closes: list, period: int = 14) -> list:
    """Compute RSI for every close. Returns list same length as closes."""
    if len(closes) < period + 1:
        return [50.0] * len(closes)

    gains, losses = [], []
    for i in range(1, len(closes)):
        delta = closes[i] - closes[i - 1]
        gains.append(max(delta, 0.0))
        losses.append(max(-delta, 0.0))

    avg_g = sum(gains[:period]) / period
    avg_l = sum(losses[:period]) / period

    rsi = [50.0] * (period + 1)  # pad initial bars
    rsi.append(100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l))

    for i in range(period, len(gains)):
        avg_g = (avg_g * (period - 1) + gains[i]) / period
        avg_l = (avg_l * (period - 1) + losses[i]) / period
        rsi.append(100.0 if avg_l == 0 else 100 - 100 / (1 + avg_g / avg_l))

    return rsi


def calc_rsi(candles: list, period: int = 14) -> dict:
    """
    RSI value + bullish divergence detection.
    Bullish divergence: price makes lower low but RSI makes higher low
    in the last 30 bars — classic sign of hidden strength.
    """
    closes = [c["c"] for c in candles]
    lows   = [c["l"] for c in candles]

    rsi_series = _calc_rsi_series(closes, period)
    current_rsi = round(rsi_series[-1], 1) if rsi_series else 50.0

    has_divergence = False
    div_strength   = 0  # RSI diff between two lows (higher = stronger)

    if len(candles) >= 30:
        lookback = min(35, len(candles) - 5)
        seg_start = len(candles) - lookback

        # Build (price_low, rsi_at_bar) pairs, skip last 3 (too fresh)
        seg = [(lows[i], rsi_series[i]) for i in range(seg_start, len(candles) - 3)]

        half = len(seg) // 2
        if half >= 3:
            # Lowest price point in first half vs second half
            low1_price, low1_rsi = min(seg[:half], key=lambda x: x[0])
            low2_price, low2_rsi = min(seg[half:], key=lambda x: x[0])

            price_lower_low = low2_price < low1_price          # lower low ✓
            rsi_higher_low  = low2_rsi  > low1_rsi + 3.0       # higher RSI ✓
            both_oversold   = low1_rsi < 50 and low2_rsi < 55  # not from overbought

            if price_lower_low and rsi_higher_low and both_oversold:
                has_divergence = True
                div_strength   = round(low2_rsi - low1_rsi, 1)

    return {
        "value":         current_rsi,
        "has_divergence": has_divergence,
        "div_strength":   div_strength,
        "oversold":       current_rsi < 35,
        "overbought":     current_rsi > 70,
    }


def calc_gap(candles: list) -> dict:
    """
    Gap detector: today's open vs yesterday's close.
    Gap up = bullish momentum / overnight demand.
    Gap down = distribution / selling pressure.
    """
    if len(candles) < 2:
        return {"gap_pct": 0.0, "gap_type": "NONE", "is_gap_up": False}

    today     = candles[-1]
    yesterday = candles[-2]

    gap_pct = (today["o"] - yesterday["c"]) / yesterday["c"] * 100 if yesterday["c"] > 0 else 0.0

    if gap_pct >= 5.0:
        gap_type = "GAP_UP_STRONG"
    elif gap_pct >= 2.0:
        gap_type = "GAP_UP"
    elif gap_pct <= -5.0:
        gap_type = "GAP_DOWN_STRONG"
    elif gap_pct <= -2.0:
        gap_type = "GAP_DOWN"
    else:
        gap_type = "NONE"

    return {
        "gap_pct":   round(gap_pct, 2),
        "gap_type":  gap_type,
        "is_gap_up": gap_pct >= 2.0,
    }


def calc_stealth(candles: list) -> dict:
    """
    Stealth Accumulation: volume jumped 2x+ vs yesterday
    but price barely moved. Smart money quietly buying.
    """
    if len(candles) < 3:
        return {"is_stealth": False, "vol_ratio": 0,
                "price_change_pct": 0, "stealth_score": 0,
                "vol_vs_avg": 0, "close_position": 0.5, "strength": "WEAK"}

    today     = candles[-1]
    yesterday = candles[-2]

    vol_today     = today["v"]
    vol_yesterday = yesterday["v"]
    vol_ratio = vol_today / vol_yesterday if vol_yesterday > 0 else 0

    avg_vol_20 = sum(c["v"] for c in candles[-21:-1]) / 20
    vol_vs_avg = vol_today / avg_vol_20 if avg_vol_20 > 0 else 0

    price_change_pct = abs((today["c"] - yesterday["c"]) / yesterday["c"] * 100) if yesterday["c"] > 0 else 0

    bar_range = today["h"] - today["l"]
    close_pos = (today["c"] - today["l"]) / bar_range if bar_range > 0 else 0.5

    vol_jumped    = vol_ratio >= 2.0
    vol_above_avg = vol_vs_avg >= 1.5
    price_quiet   = price_change_pct <= 7.0
    bullish_close = close_pos >= 0.4

    is_stealth = vol_jumped and vol_above_avg and price_quiet

    stealth_score = 0

    if vol_ratio >= 5.0:    stealth_score += 40
    elif vol_ratio >= 3.0:  stealth_score += 30
    elif vol_ratio >= 2.0:  stealth_score += 20

    if vol_vs_avg >= 4.0:   stealth_score += 30
    elif vol_vs_avg >= 2.5: stealth_score += 20
    elif vol_vs_avg >= 1.5: stealth_score += 10

    if price_change_pct <= 1.0:   stealth_score += 30
    elif price_change_pct <= 3.0: stealth_score += 20
    elif price_change_pct <= 5.0: stealth_score += 10
    elif price_change_pct <= 7.0: stealth_score += 5

    if bullish_close: stealth_score += 10

    if today["c"] < yesterday["c"]:
        stealth_score = int(stealth_score * 0.5)

    stealth_score = min(stealth_score, 100)

    return {
        "is_stealth":       is_stealth,
        "vol_ratio":        round(vol_ratio, 2),
        "vol_vs_avg":       round(vol_vs_avg, 2),
        "price_change_pct": round(price_change_pct, 2),
        "close_position":   round(close_pos, 2),
        "stealth_score":    stealth_score,
        "strength":         "STRONG" if stealth_score >= 70 else "MEDIUM" if stealth_score >= 40 else "WEAK",
    }


def calc_obv(candles: list) -> dict:
    """
    On-Balance Volume — cumulative volume direction indicator.

    OBV rises when price closes up, falls when price closes down.
    Key signal: OBV rising while price flat = stealth accumulation (smart money buying quietly).

    Returns:
      obv_current:     latest OBV value (cumulative)
      obv_slope_5d:    OBV change over last 5 days (positive = buying pressure)
      obv_slope_20d:   OBV change over last 20 days
      obv_divergence:  True when OBV rising but price flat/falling (bullish hidden strength)
      obv_strength:    STRONG / MEDIUM / WEAK / NEGATIVE
      normalized_slope: obv_slope_5d normalised by avg daily volume
    """
    if len(candles) < 20:
        return {
            "obv_current": 0,
            "obv_slope_5d": 0,
            "obv_slope_20d": 0,
            "obv_divergence": False,
            "obv_strength": "WEAK",
            "normalized_slope": 0.0,
        }

    # Build cumulative OBV series
    obv_series = [0]
    for i in range(1, len(candles)):
        prev = obv_series[-1]
        if candles[i]["c"] > candles[i - 1]["c"]:
            obv_series.append(prev + candles[i]["v"])
        elif candles[i]["c"] < candles[i - 1]["c"]:
            obv_series.append(prev - candles[i]["v"])
        else:
            obv_series.append(prev)

    current_obv  = obv_series[-1]
    obv_5d_ago   = obv_series[-6]  if len(obv_series) >= 6  else obv_series[0]
    obv_20d_ago  = obv_series[-21] if len(obv_series) >= 21 else obv_series[0]
    obv_slope_5d  = current_obv - obv_5d_ago
    obv_slope_20d = current_obv - obv_20d_ago

    # Price movement over last 5 days (for divergence detection)
    price_now    = candles[-1]["c"]
    price_5d_ago = candles[-6]["c"] if len(candles) >= 6 else candles[0]["c"]
    price_slope_5d = price_now - price_5d_ago

    # Bullish divergence: OBV rising while price is flat (within ±2%) or falling
    obv_divergence = (
        obv_slope_5d > 0
        and abs(price_slope_5d) <= price_now * 0.02
    )

    # Normalise slope by average daily volume over last 20 bars
    avg_vol = sum(c["v"] for c in candles[-20:]) / 20
    normalized_slope = round(obv_slope_5d / (avg_vol * 5), 3) if avg_vol > 0 else 0.0

    if normalized_slope > 0.3:
        obv_strength = "STRONG"
    elif normalized_slope > 0.1:
        obv_strength = "MEDIUM"
    elif normalized_slope > 0:
        obv_strength = "WEAK"
    else:
        obv_strength = "NEGATIVE"

    return {
        "obv_current":      round(current_obv),
        "obv_slope_5d":     round(obv_slope_5d),
        "obv_slope_20d":    round(obv_slope_20d),
        "obv_divergence":   obv_divergence,
        "obv_strength":     obv_strength,
        "normalized_slope": normalized_slope,
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
    stealth = calc_stealth(candles)
    rsi_data = calc_rsi(candles)
    gap = calc_gap(candles)
    inst_flow = calc_institutional_flow(candles)
    obv = calc_obv(candles)

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
        # Stealth
        "stealth": stealth,
        # RSI
        "rsi": rsi_data,
        # Gap
        "gap": gap,
        # Institutional Flow
        "institutional_flow": inst_flow,
        # OBV
        "obv": obv,
    }
