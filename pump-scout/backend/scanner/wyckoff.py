"""
Wyckoff regime detection for accumulation/distribution analysis.
"""
from .indicators import sma, stdev


def detect_regime(candles: list) -> dict:
    if len(candles) < 60:
        return {
            "state": "NONE",
            "tr_high": None, "tr_low": None, "tr_mid": None,
            "in_acc": False, "in_dist": False, "confidence": 0,
            "sc": False, "bc": False,
        }

    closes = [c["c"] for c in candles]
    highs = [c["h"] for c in candles]
    lows = [c["l"] for c in candles]
    volumes = [c["v"] for c in candles]

    avg_vol = sma(volumes, 20)

    # --- Selling Climax (SC): high volume bearish bar at 60-bar low ---
    sc = False
    sc_idx = None
    for i in range(len(candles) - 1, max(len(candles) - 60, 0), -1):
        bar = candles[i]
        is_bearish = bar["c"] < bar["o"]
        is_high_vol = bar["v"] > avg_vol * 2
        lookback_lows = lows[max(0, i - 59) : i + 1]
        is_at_low = bar["l"] == min(lookback_lows)
        if is_bearish and is_high_vol and is_at_low:
            sc = True
            sc_idx = i
            break

    # --- Buying Climax (BC): high volume bullish bar at 60-bar high ---
    bc = False
    bc_idx = None
    for i in range(len(candles) - 1, max(len(candles) - 60, 0), -1):
        bar = candles[i]
        is_bullish = bar["c"] > bar["o"]
        is_high_vol = bar["v"] > avg_vol * 2
        lookback_highs = highs[max(0, i - 59) : i + 1]
        is_at_high = bar["h"] == max(lookback_highs)
        if is_bullish and is_high_vol and is_at_high:
            bc = True
            bc_idx = i
            break

    # --- Determine Trading Range ---
    # Use recent 40-bar range as proxy
    lookback = 40
    recent_highs = highs[-lookback:]
    recent_lows = lows[-lookback:]
    tr_high = max(recent_highs)
    tr_low = min(recent_lows)
    tr_mid = (tr_high + tr_low) / 2

    price_range = tr_high - tr_low

    # --- Accumulation: SC detected, price consolidating in range ---
    in_acc = False
    if sc and sc_idx is not None:
        bars_since_sc = len(candles) - 1 - sc_idx
        current_price = closes[-1]
        if (
            bars_since_sc >= 5
            and current_price >= tr_low
            and current_price <= tr_high
            and price_range > 0
        ):
            in_acc = True

    # Heuristic: if no explicit SC but price is near multi-week lows with contraction
    if not in_acc:
        min_low_60 = min(lows[-60:])
        max_high_60 = max(highs[-60:])
        range_60 = max_high_60 - min_low_60
        current_price = closes[-1]
        near_bottom = (current_price - min_low_60) / range_60 < 0.4 if range_60 > 0 else False
        vol_contracting = sma(volumes[-10:], 10) < sma(volumes[-30:], 30) if len(volumes) >= 30 else False
        if near_bottom and vol_contracting:
            in_acc = True

    # --- Distribution: BC detected, price consolidating near highs ---
    in_dist = False
    if bc and bc_idx is not None:
        bars_since_bc = len(candles) - 1 - bc_idx
        current_price = closes[-1]
        if (
            bars_since_bc >= 5
            and current_price >= tr_low
            and current_price <= tr_high
        ):
            in_dist = True

    # --- Get BB and CMF data (use precomputed from indicators if available) ---
    # These are computed inline for independence
    from .indicators import calc_bb, calc_cmf
    bb = calc_bb(candles)
    cmf = calc_cmf(candles)

    sqz_bars = bb["sqz_bars"]
    cmf_val = cmf["value"]
    vol_anomaly_ratio = candles[-1]["v"] / avg_vol if avg_vol > 0 else 0

    # Simple vol_z
    vol_sd = stdev(volumes[-21:-1], 20) if len(volumes) >= 21 else 0
    vol_z = (candles[-1]["v"] - avg_vol) / vol_sd if vol_sd > 0 else 0

    # Breakout detection: close > 20-bar high (excluding current)
    recent_high_20 = max(highs[-21:-1]) if len(highs) >= 21 else highs[-1]
    breakout = closes[-1] > recent_high_20

    # --- State Machine ---
    state = "NONE"
    confidence = 0

    if in_acc:
        current_price = closes[-1]
        position_in_range = (current_price - tr_low) / price_range if price_range > 0 else 0

        # FIRE: breakout from accumulation with volume
        if breakout and vol_z > 1.0 and sqz_bars >= 3:
            state = "FIRE"
            confidence = min(100, 60 + int(vol_z * 10) + sqz_bars)

        # ARM: near top of range, squeeze, positive CMF
        elif (
            position_in_range >= 0.65
            and sqz_bars >= 3
            and cmf_val > 0
        ):
            state = "ARM"
            confidence = min(100, 40 + sqz_bars * 3 + int(cmf_val * 100))

        # BASE: in accumulation with squeeze and CMF
        elif sqz_bars >= 2 and cmf_val > 0:
            state = "BASE"
            confidence = min(100, 20 + sqz_bars * 4 + int(cmf_val * 80))

        else:
            state = "NONE"
            confidence = 10

    return {
        "state": state,
        "tr_high": round(tr_high, 4) if tr_high else None,
        "tr_low": round(tr_low, 4) if tr_low else None,
        "tr_mid": round(tr_mid, 4) if tr_mid else None,
        "in_acc": in_acc,
        "in_dist": in_dist,
        "sc": sc,
        "bc": bc,
        "confidence": confidence,
        "sqz_bars": sqz_bars,
        "cmf": round(cmf_val, 4),
        "breakout": breakout,
        "vol_z": round(vol_z, 2),
    }
