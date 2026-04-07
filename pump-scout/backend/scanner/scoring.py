"""
Pump Scout Scoring Engine v2.0 — Confluence-based pump detection.

Philosophy:
  Pumps happen when MULTIPLE signals align simultaneously.
  Instead of a simple weighted sum (one signal dominates), we use a
  confluence model: each additional strong signal multiplies the final score.

  Four dimensions (each 0–100):
    1. VOLUME PRESSURE  — is aggressive buying happening? (anomaly, Z-score, OBV)
    2. STRUCTURE        — is price compressed and coiling? (BB squeeze, EMA ribbon, Wyckoff)
    3. SMART MONEY FLOW — are institutions quietly loading? (CMF, OBV div, inst flow)
    4. MOMENTUM CONTEXT — are we early, not late? (RS, RSI div, gap, EMA trend)

  Confluence multiplier: each dimension scoring >= 60 earns +12% (max 4 dims = ×1.48)
  Silent Volume bonus: is_stealth + obv_divergence + cmf_pctl >= 60 → ×1.15 extra

  Penalties applied after:
    in_dist         → ×0.60 (smart money exiting)
    rsi > 70        → ×0.75 (overbought — too late)
    rsi > 65        → ×0.88
    cmf_pctl < 20   → ×0.80 (poor money flow)
    obv NEGATIVE    → ×0.85
    GAP_DOWN_STRONG → ×0.80
"""
import logging

logger = logging.getLogger(__name__)

# ── Cycle-phase sector bonus/penalty ─────────────────────────────────────────
# Additive, capped at ±20 — sector is context, not the dominant signal.
CYCLE_SECTOR_WEIGHTS: dict[str, dict[str, int]] = {
    "RISK_ON_GROWTH": {
        "Information Technology":  15,
        "Consumer Discretionary":  10,
        "Financials":               8,
        "Communication Services":   5,
        "Health Care":              3,
        "Energy":                  -5,
        "Utilities":              -10,
        "Consumer Staples":       -10,
    },
    "LATE_CYCLE": {
        "Energy":                  15,
        "Materials":               12,
        "Industrials":              8,
        "Financials":               5,
        "Information Technology":  -5,
        "Consumer Discretionary":  -8,
        "Real Estate":            -10,
    },
    "STAGFLATION": {
        "Energy":                  20,
        "Materials":               15,
        "Consumer Staples":        10,
        "Utilities":                8,
        "Information Technology": -15,
        "Consumer Discretionary": -20,
        "Real Estate":            -15,
    },
    "RISK_OFF": {
        "Utilities":               15,
        "Consumer Staples":        12,
        "Health Care":             10,
        "Communication Services":   5,
        "Energy":                  -5,
        "Information Technology": -10,
        "Consumer Discretionary": -15,
    },
    "FEAR": {
        "Materials":                5,
        "Consumer Staples":         5,
        # all others get -10 (applied as default in apply_cycle_bonus)
    },
    "NEUTRAL": {},
}


def apply_cycle_bonus(score: float, sector: str, cycle_phase: str) -> tuple[float, int]:
    """
    Apply additive sector bonus/penalty based on current cycle phase.
    Returns (new_score, bonus_applied).
    Bonus is capped at ±20. FEAR phase defaults to -10 for unlisted sectors.
    """
    weights = CYCLE_SECTOR_WEIGHTS.get(cycle_phase, {})
    if cycle_phase == "FEAR":
        bonus = weights.get(sector, -10)
    else:
        bonus = weights.get(sector, 0)
    bonus = max(-20, min(20, bonus))
    new_score = round(min(100, max(0, score + bonus)), 2)
    return new_score, bonus


def calc_setup_quality_layers(
    indicators: dict,
    regime: dict,
    market_regime: dict | None = None,
    sector_data: dict | None = None,
    industry_data: dict | None = None,
) -> dict:
    """
    5-layer trade quality assessment. DISPLAY ONLY — never modifies total_score.

    Layers (each 0–10):
      1. Market    — overall market regime health
      2. Sector    — sector momentum + class grade
      3. Industry  — industry ETF trend (sub-sector)
      4. Structure — Wyckoff structure + OBV/CMF alignment
      5. Execution — gap, premarket, squeeze trigger readiness

    Returns dict with layer scores and overall quality label.
    """
    layers: dict[str, int] = {}

    # ── Layer 1: Market ───────────────────────────────────────────────────────
    mkt = 5  # baseline neutral
    if market_regime:
        regime_str = market_regime.get("regime", "NEUTRAL")
        cycle = market_regime.get("cycle_phase", "NEUTRAL")
        spy_pct = market_regime.get("spy_pct", 0) or 0
        if regime_str in ("RISK_ON",):
            mkt = 9
        elif regime_str == "NEUTRAL":
            mkt = 6
        elif regime_str in ("RISK_OFF",):
            mkt = 3
        elif regime_str == "FEAR":
            mkt = 1
        # Cycle phase fine-tuning
        if cycle == "RISK_ON_GROWTH":
            mkt = min(10, mkt + 1)
        elif cycle in ("STAGFLATION", "FEAR"):
            mkt = max(0, mkt - 1)
        # SPY daily drift
        if spy_pct > 0.5:
            mkt = min(10, mkt + 1)
        elif spy_pct < -0.5:
            mkt = max(0, mkt - 1)
    layers["market"] = mkt

    # ── Layer 2: Sector ───────────────────────────────────────────────────────
    sec = 5
    if sector_data:
        sc_class = sector_data.get("sector_class", "C")
        sec_pct = sector_data.get("change_pct", 0) or 0
        class_map = {"A": 9, "B": 7, "C": 5, "D": 3, "F": 1}
        sec = class_map.get(sc_class, 5)
        # Reinforce with vs_spy
        vs_spy = sector_data.get("vs_spy_1d", 0) or 0
        if vs_spy > 0.3:
            sec = min(10, sec + 1)
        elif vs_spy < -0.3:
            sec = max(0, sec - 1)
    layers["sector"] = sec

    # ── Layer 3: Industry ─────────────────────────────────────────────────────
    ind = 5
    if industry_data:
        ind_pct = industry_data.get("pct_1d", 0) or 0
        if ind_pct > 1.0:
            ind = 9
        elif ind_pct > 0.3:
            ind = 7
        elif abs(ind_pct) < 0.3:
            ind = 5
        elif ind_pct < -1.0:
            ind = 2
        else:
            ind = 3
    layers["industry"] = ind

    # ── Layer 4: Structure ────────────────────────────────────────────────────
    struct = 0
    state = regime.get("state", "NONE")
    in_acc = regime.get("in_acc", False)
    obv = indicators.get("obv", {})
    obv_strength = obv.get("obv_strength", "WEAK")
    obv_div = obv.get("obv_divergence", False)
    cmf_pctl = indicators.get("cmf_pctl", 0)

    if state in ("FIRE", "ARM"):
        struct += 4
    elif state in ("BASE", "STEALTH_BASE", "STEALTH_ARM"):
        struct += 3
    elif state == "STEALTH":
        struct += 2

    if in_acc:
        struct += 2

    if obv_strength == "STRONG":
        struct += 2
    elif obv_strength == "MEDIUM":
        struct += 1

    if obv_div:
        struct += 1

    if cmf_pctl >= 70:
        struct += 1

    layers["structure"] = min(10, struct)

    # ── Layer 5: Execution ────────────────────────────────────────────────────
    exe = 0
    sqz_bars = indicators.get("bb_sqz_bars", 0)
    gap = indicators.get("gap", {})
    gap_type = gap.get("gap_type", "NONE")
    anomaly_ratio = indicators.get("anomaly_ratio", 0)
    stealth = indicators.get("stealth", {})

    # Squeeze buildup
    if sqz_bars >= 10:
        exe += 3
    elif sqz_bars >= 5:
        exe += 2
    elif sqz_bars >= 3:
        exe += 1

    # Gap confirmation
    if gap_type == "GAP_UP_STRONG":
        exe += 3
    elif gap_type == "GAP_UP":
        exe += 2
    elif gap_type == "GAP_DOWN_STRONG":
        exe -= 2
    elif gap_type == "GAP_DOWN":
        exe -= 1

    # Volume spike as entry confirmation
    if anomaly_ratio >= 5:
        exe += 3
    elif anomaly_ratio >= 3:
        exe += 2
    elif anomaly_ratio >= 2:
        exe += 1

    # Stealth accumulation bonus
    if stealth.get("is_stealth"):
        exe += 1

    layers["execution"] = max(0, min(10, exe))

    # ── Overall quality label ─────────────────────────────────────────────────
    avg = sum(layers.values()) / len(layers)
    if avg >= 8:
        quality = "PRIME"
    elif avg >= 6.5:
        quality = "STRONG"
    elif avg >= 5:
        quality = "MODERATE"
    elif avg >= 3.5:
        quality = "WEAK"
    else:
        quality = "AVOID"

    return {
        "layers": layers,
        "quality": quality,
        "avg": round(avg, 1),
    }


def score_ticker(indicators: dict, regime: dict, symbol: str = "") -> dict:
    """
    Confluence-based pump detection scoring engine.

    Scores four independent dimensions (0-100 each), then multiplies by a
    confluence bonus for setups where multiple dimensions align simultaneously.

    A stock with 3-4 strong signals gets a multiplicative boost — this makes
    FIRE tier genuinely hard to reach without multi-signal confirmation.
    """
    # ── Extract signals ───────────────────────────────────────────────────────
    anomaly_ratio   = indicators.get("anomaly_ratio", 0) or 0
    vol_z           = indicators.get("vol_z", 0) or 0
    cmf_pctl        = indicators.get("cmf_pctl", 0) or 0
    cmf_val         = indicators.get("cmf", 0) or 0
    sqz_bars        = indicators.get("bb_sqz_bars", 0) or 0
    atr_ratio       = indicators.get("atr_ratio", 1.0) or 1.0
    ribbon_compr    = indicators.get("ribbon_compression", "NONE")
    compr_bullish   = indicators.get("compression_and_bullish", False)
    ema8_slope      = indicators.get("ema8_slope", "FLAT")
    above_ema20     = indicators.get("above_ema20", False)
    above_ema50     = indicators.get("above_ema50", False)
    rs_score        = indicators.get("rs_score", 0) or 0
    price_chg_pct   = abs(indicators.get("price_change_pct", 0) or 0)

    stealth         = indicators.get("stealth", {}) or {}
    is_stealth      = stealth.get("is_stealth", False)
    stealth_score_v = stealth.get("stealth_score", 0) or 0

    obv             = indicators.get("obv", {}) or {}
    obv_strength    = obv.get("obv_strength", "WEAK")
    obv_divergence  = obv.get("obv_divergence", False)

    rsi_data        = indicators.get("rsi", {}) or {}
    rsi_value       = rsi_data.get("value", 50) or 50
    rsi_divergence  = rsi_data.get("has_divergence", False)
    div_strength    = rsi_data.get("div_strength", 0) or 0
    rsi_oversold    = rsi_data.get("oversold", False)

    gap             = indicators.get("gap", {}) or {}
    gap_type        = gap.get("gap_type", "NONE")

    inst            = indicators.get("institutional_flow", {}) or {}
    is_inst         = inst.get("is_institutional", False)
    inst_flow_score = inst.get("flow_score", 0) or 0

    state           = regime.get("state", "NONE")
    in_acc          = regime.get("in_acc", False)
    in_dist         = regime.get("in_dist", False)
    breakout        = regime.get("breakout", False)
    wyckoff_conf    = regime.get("confidence", 0) or 0

    # ── DIMENSION 1: VOLUME PRESSURE (0–100) ─────────────────────────────────
    # Is aggressive/unusual buying happening? Core pump-detection signal.

    # Anomaly ratio — continuous, not step function (0–50)
    if anomaly_ratio >= 10:
        vol_anomaly_pts = 50
    elif anomaly_ratio >= 5:
        vol_anomaly_pts = 35 + (anomaly_ratio - 5) / 5 * 15
    elif anomaly_ratio >= 2:
        vol_anomaly_pts = 15 + (anomaly_ratio - 2) / 3 * 20
    elif anomaly_ratio >= 1.5:
        vol_anomaly_pts = (anomaly_ratio - 1.5) / 0.5 * 15
    else:
        vol_anomaly_pts = 0

    # Volume Z-score — statistical significance (0–20)
    if vol_z >= 3.0:
        vol_z_pts = 20
    elif vol_z >= 2.0:
        vol_z_pts = 12 + (vol_z - 2.0) * 8
    elif vol_z >= 1.0:
        vol_z_pts = 4 + (vol_z - 1.0) * 8
    else:
        vol_z_pts = max(0.0, vol_z * 4)

    # OBV slope — are buyers accumulating over multiple days? (0–20)
    obv_vol_pts = {"STRONG": 20, "MEDIUM": 12, "WEAK": 5, "NEGATIVE": 0}.get(obv_strength, 0)

    # Stealth volume pattern — high vol + quiet price = smart money (0–15)
    if is_stealth and stealth_score_v >= 70:
        stealth_vol_pts = 15
    elif is_stealth and stealth_score_v >= 50:
        stealth_vol_pts = 10
    elif is_stealth:
        stealth_vol_pts = 5
    else:
        stealth_vol_pts = 0

    vol_dim = min(100.0, vol_anomaly_pts + vol_z_pts + obv_vol_pts + stealth_vol_pts)

    # ── DIMENSION 2: STRUCTURE (0–100) ───────────────────────────────────────
    # Is price technically compressed and ready to break out?

    # BB Squeeze duration — the coiled spring (0–35)
    if sqz_bars >= 10:
        bb_pts = 35
    elif sqz_bars >= 7:
        bb_pts = 28
    elif sqz_bars >= 5:
        bb_pts = 22
    elif sqz_bars >= 3:
        bb_pts = 15
    elif sqz_bars >= 1:
        bb_pts = 8
    else:
        bb_pts = 0

    # EMA ribbon compression — price-action compression (0–25)
    if ribbon_compr == "STRONG" and compr_bullish:
        ema_pts = 25   # compressed + price above all EMAs = textbook pre-breakout
    elif ribbon_compr == "STRONG":
        ema_pts = 18
    elif ribbon_compr == "MEDIUM" and compr_bullish:
        ema_pts = 16
    elif ribbon_compr == "MEDIUM":
        ema_pts = 11
    elif ribbon_compr == "WEAK":
        ema_pts = 5
    else:
        ema_pts = 0

    # Wyckoff state — structural context (0–25)
    _WYCKOFF_PTS = {
        "FIRE": 25, "ARM": 20, "STEALTH_ARM": 20,
        "BASE": 15, "STEALTH_BASE": 15, "STEALTH": 12,
    }
    wyckoff_pts = _WYCKOFF_PTS.get(state, 8 if in_acc else 0)

    # ATR expansion — volatility expanding after contraction = move starting (0–15)
    if atr_ratio >= 1.5:
        atr_pts = 15
    elif atr_ratio >= 1.2:
        atr_pts = 10
    elif atr_ratio >= 1.0:
        atr_pts = 4
    else:
        atr_pts = 0

    struct_dim = min(100.0, bb_pts + ema_pts + wyckoff_pts + atr_pts)

    # ── DIMENSION 3: SMART MONEY FLOW (0–100) ────────────────────────────────
    # Evidence of institutions quietly accumulating

    # CMF percentile — sustained buying pressure over N bars (0–35)
    if cmf_pctl >= 80:
        cmf_pts = 35
    elif cmf_pctl >= 65:
        cmf_pts = 25
    elif cmf_pctl >= 50:
        cmf_pts = 16
    elif cmf_pctl >= 35:
        cmf_pts = 9
    elif cmf_val > 0:
        cmf_pts = 4
    else:
        cmf_pts = 0

    # OBV divergence — OBV rising while price is flat (0–30)
    # This is the most reliable institutional accumulation fingerprint
    if obv_divergence and obv_strength == "STRONG":
        obv_div_pts = 30
    elif obv_divergence and obv_strength == "MEDIUM":
        obv_div_pts = 22
    elif obv_divergence:
        obv_div_pts = 15
    elif obv_strength == "STRONG":
        obv_div_pts = 10
    elif obv_strength == "MEDIUM":
        obv_div_pts = 5
    else:
        obv_div_pts = 0

    # Institutional flow — detected multi-day institutional buying (0–20)
    if is_inst and inst_flow_score >= 70:
        inst_pts = 20
    elif is_inst and inst_flow_score >= 50:
        inst_pts = 14
    elif is_inst:
        inst_pts = 8
    else:
        inst_pts = 0

    # Stealth pattern quality — confirms smart money loading (0–15)
    if stealth_score_v >= 70:
        stealth_smart_pts = 15
    elif stealth_score_v >= 50:
        stealth_smart_pts = 10
    elif stealth_score_v >= 30:
        stealth_smart_pts = 5
    else:
        stealth_smart_pts = 0

    smart_dim = min(100.0, cmf_pts + obv_div_pts + inst_pts + stealth_smart_pts)

    # ── DIMENSION 4: MOMENTUM CONTEXT (0–100) ────────────────────────────────
    # Are we early in the move? Is the stock outperforming?

    # RSI divergence — price lower low but RSI higher low = hidden strength (0–35)
    if rsi_divergence and div_strength >= 10:
        rsi_pts = 35
    elif rsi_divergence and div_strength >= 5:
        rsi_pts = 25
    elif rsi_divergence:
        rsi_pts = 18
    elif rsi_oversold:
        rsi_pts = 10
    elif rsi_value <= 50:
        rsi_pts = 5
    elif rsi_value <= 65:
        rsi_pts = 2
    else:
        rsi_pts = 0

    # Relative strength vs SPY 5-day — outperforming market = targeted buying (0–30)
    if rs_score > 10:
        rs_pts = 30
    elif rs_score > 5:
        rs_pts = 20
    elif rs_score > 2:
        rs_pts = 12
    elif rs_score > 0:
        rs_pts = 6
    else:
        rs_pts = 0

    # Gap direction (-15 to +15)
    gap_pts = {
        "GAP_UP_STRONG": 15, "GAP_UP": 10,
        "NONE": 0, "GAP_DOWN": -8, "GAP_DOWN_STRONG": -15,
    }.get(gap_type, 0)

    # Price position + EMA trend (0–25)
    if breakout and in_acc:
        pos_pts = 20   # breakout from accumulation = ideal entry point
    elif breakout:
        pos_pts = 12
    elif above_ema50:
        pos_pts = 10
    elif above_ema20:
        pos_pts = 6
    else:
        pos_pts = 0
    if ema8_slope == "RISING":
        pos_pts = min(pos_pts + 5, 25)

    mom_dim = min(100.0, max(0.0, rsi_pts + rs_pts + gap_pts + pos_pts))

    # ── CONFLUENCE MULTIPLIER ─────────────────────────────────────────────────
    # Each dimension scoring >= 60 earns +12% — rewarding multi-signal setups
    dims = [vol_dim, struct_dim, smart_dim, mom_dim]
    strong_count = sum(1 for d in dims if d >= 60)
    confluence_mult = 1.0 + strong_count * 0.12   # max ×1.48 with 4 strong dims

    # ── SILENT VOLUME BONUS ───────────────────────────────────────────────────
    # The "institutional accumulation fingerprint":
    # High volume + flat price + OBV rising + CMF elevated = pre-pump loading
    silent_volume = is_stealth and obv_divergence and cmf_pctl >= 60
    silent_mult = 1.15 if silent_volume else 1.0

    # ── BASE SCORE ────────────────────────────────────────────────────────────
    weighted_base = (
        vol_dim    * 0.35 +
        struct_dim * 0.30 +
        smart_dim  * 0.20 +
        mom_dim    * 0.15
    )
    total_score = weighted_base * confluence_mult * silent_mult

    # ── PENALTIES ─────────────────────────────────────────────────────────────
    if in_dist:
        total_score *= 0.60          # smart money is selling, not buying
    if rsi_value > 70:
        total_score *= 0.75          # overbought — too late to enter cleanly
    elif rsi_value > 65:
        total_score *= 0.88          # approaching overbought
    if cmf_pctl < 20:
        total_score *= 0.80          # sustained selling pressure
    if obv_strength == "NEGATIVE":
        total_score *= 0.85          # more volume on down-days than up-days
    if gap_type == "GAP_DOWN_STRONG":
        total_score *= 0.80          # strong overnight distribution event

    # Stealth floor — meaningful stealth always at least WATCH
    if is_stealth and stealth_score_v >= 50 and total_score < 25:
        total_score = 25.0

    total_score = round(min(total_score, 100), 2)

    # ── TIER ASSIGNMENT ───────────────────────────────────────────────────────
    if total_score > 78:
        tier = "FIRE"
    elif total_score > 58:
        tier = "ARM"
    elif total_score > 38:
        tier = "BASE"
    elif is_stealth and stealth_score_v >= 50:
        tier = "STEALTH"
    elif total_score > 22:
        tier = "WATCH"
    else:
        tier = "SKIP"

    # Wyckoff state can upgrade tier (never downgrade)
    _TIER_RANK = {"SKIP": 0, "WATCH": 1, "STEALTH": 2, "SYMPATHY": 3, "BASE": 3, "ARM": 4, "FIRE": 5}
    _STATE_MIN = {
        "FIRE": "FIRE", "ARM": "ARM", "BASE": "BASE",
        "STEALTH": "STEALTH", "STEALTH_BASE": "STEALTH", "STEALTH_ARM": "STEALTH",
    }
    if state in _STATE_MIN:
        candidate = _STATE_MIN[state]
        if _TIER_RANK.get(candidate, 0) > _TIER_RANK.get(tier, 0):
            tier = candidate

    # Strong institutional flow upgrades BASE/WATCH → ARM
    if (
        is_inst
        and inst.get("days", 0) >= 5
        and inst_flow_score >= 70
        and tier in ("BASE", "WATCH")
    ):
        tier = "ARM"

    # Hard caps
    if in_dist and tier == "FIRE":
        tier = "ARM"
    if rsi_value > 70 and tier == "FIRE":
        tier = "ARM"

    original_tier = tier
    original_score = total_score

    # ── QUALITY DOWNGRADES ────────────────────────────────────────────────────
    cef_warning = False
    cef_note = None
    score_conflict = False
    score_conflict_note = None
    primary_downgrade = None

    _run_conflict_check = True
    if symbol:
        from scanner.sector_map import NON_STOCK_SECURITIES
        if symbol.upper() in NON_STOCK_SECURITIES:
            cef_warning = True
            cef_note = (
                "Closed-end fund or ETN — volume signals may reflect "
                "NAV/distribution mechanics, not institutional accumulation."
            )
            if tier in ("FIRE", "ARM"):
                tier = "WATCH"
                total_score = round(total_score * 0.6, 2)
            primary_downgrade = "NON_STOCK_SECURITY"
            logger.info(f"CEF downgrade: {symbol} {original_tier}→{tier} score {total_score:.1f}")
            _run_conflict_check = False

    if _run_conflict_check and total_score >= 75 and wyckoff_conf < 50:
        score_conflict = True
        score_conflict_note = (
            f"Score {total_score:.0f} driven by volume/stealth but Wyckoff "
            f"confidence only {wyckoff_conf}% — structure not fully "
            f"confirmed, treat as ARM."
        )
        if tier == "FIRE":
            tier = "ARM"
            total_score = round(total_score * 0.88, 2)
        primary_downgrade = "LOW_CONFIDENCE"
        if symbol:
            logger.info(
                f"Conflict downgrade: {symbol} {original_tier}→{tier} "
                f"score {total_score:.1f} confidence {wyckoff_conf}%"
            )

    # ── BACKWARD-COMPATIBLE RETURN VALUES ────────────────────────────────────
    # Legacy fields kept for DB schema / frontend compatibility.
    # vol_score and accum_score now reflect the new pillar scores.
    vol_score    = round(vol_dim)
    accum_score  = round((struct_dim + smart_dim) / 2)
    stealth_bonus = round(stealth_score_v * 0.3, 2)
    inst_bonus   = round(inst_pts * 0.2, 2) if is_inst else 0.0
    rs_bonus     = rs_pts

    # quiet_factor repurposed as confluence display value
    quiet_factor = round(confluence_mult, 3)

    return {
        "total_score":    total_score,
        # Legacy compatibility fields
        "vol_score":      vol_score,
        "accum_score":    accum_score,
        "stealth_bonus":  stealth_bonus,
        "inst_bonus":     inst_bonus,
        "rs_score":       round(rs_score, 2),
        "rs_bonus":       rs_bonus,
        "sector_rs_bonus": 0,            # applied post-scoring in runner.py
        "quiet_factor":   quiet_factor,  # now = confluence_mult for display
        # Tier
        "tier":           tier,
        "original_tier":  original_tier,
        "original_score": original_score,
        # Diagnostics
        "primary_downgrade":   primary_downgrade,
        "cef_warning":         cef_warning,
        "cef_note":            cef_note,
        "score_conflict":      score_conflict,
        "score_conflict_note": score_conflict_note,
        # New pillar breakdown (analytics / frontend)
        "vol_dim":         round(vol_dim, 1),
        "struct_dim":      round(struct_dim, 1),
        "smart_dim":       round(smart_dim, 1),
        "mom_dim":         round(mom_dim, 1),
        "confluence_mult": quiet_factor,
        "silent_volume":   silent_volume,
        "strong_dims":     strong_count,
    }
