"""
Early Pump Ignition Layer — detects pre-breakout accumulation setups.

This module is a RESEARCH / DISCOVERY layer that sits BETWEEN raw scan data
and confirmed breakout scoring. It identifies stocks that are building toward
a pump BEFORE they show up as obvious volume-anomaly candidates.

Design principles:
  - Additive and safe: never modifies total_score or tier
  - Explainable: every signal produces a human-readable reason
  - Two classes of opportunity:
      CONFIRMED — strong structure + volume rising toward breakout
      EARLY     — price/structure improving, volume not yet explosive
      WATCH     — something interesting, needs more evidence
      NONE      — no clear ignition signal

Five ignition archetypes (ignition_bucket):
  RIBBON_LED   — EMA compression + alignment driving the signal
  PRICE_LED    — price recovering above EMA cluster before volume
  RS_LED       — outperforming market quietly (rotation starting)
  VOLUME_LED   — volume waking up but not yet at breakout threshold
  THEME_LED    — sector/industry momentum helping (if context available)
  MIXED        — multiple archetypes equally strong
  NONE         — no dominant archetype
"""
import logging

logger = logging.getLogger(__name__)


def calc_ignition(
    indicators: dict,
    regime: dict,
    rs_score: float = 0.0,
    earnings_risk: str = "NONE",
    sector_context: dict | None = None,
) -> dict:
    """
    Compute the early ignition analysis for a single ticker.

    Parameters
    ----------
    indicators   : output of calc_all() from indicators.py
    regime       : output of detect_regime() from wyckoff.py
    rs_score     : relative strength vs SPY 5-day (set by runner/universe_scan)
    earnings_risk: "NONE" | "MEDIUM" | "HIGH"
    sector_context: optional dict with sector_class, change_pct, vs_spy_1d

    Returns
    -------
    dict with: ignition_signal, ignition_bucket, ignition_quality,
               ignition_reason, ignition_confirmations, ignition_warnings
    """
    # ── Extract signals ───────────────────────────────────────────────────────
    ribbon_compr    = indicators.get("ribbon_compression", "NONE")
    bullish_stack   = indicators.get("bullish_stack", False)
    bearish_stack   = indicators.get("bearish_stack", False)
    compr_bullish   = indicators.get("compression_and_bullish", False)
    ema8_slope      = indicators.get("ema8_slope", "FLAT")
    ema_spread      = indicators.get("ema_spread_pct", 999.0) or 999.0
    above_ema20     = indicators.get("above_ema20", False)
    above_ema50     = indicators.get("above_ema50", False)
    sqz_bars        = indicators.get("bb_sqz_bars", 0) or 0
    anomaly_ratio   = indicators.get("anomaly_ratio", 0.0) or 0.0
    vol_z           = indicators.get("vol_z", 0.0) or 0.0
    price_chg_pct   = indicators.get("price_change_pct", 0.0) or 0.0
    today_vol       = indicators.get("today_vol", 0) or 0
    cmf_pctl        = indicators.get("cmf_pctl", 0.0) or 0.0
    cmf_val         = indicators.get("cmf", 0.0) or 0.0
    obv             = indicators.get("obv", {}) or {}
    obv_strength    = obv.get("obv_strength", "WEAK")
    obv_divergence  = obv.get("obv_divergence", False)
    rsi_data        = indicators.get("rsi", {}) or {}
    rsi_value       = rsi_data.get("value", 50.0) or 50.0
    rsi_divergence  = rsi_data.get("has_divergence", False)
    stealth         = indicators.get("stealth", {}) or {}
    is_stealth      = stealth.get("is_stealth", False)

    in_acc          = regime.get("in_acc", False)
    in_dist         = regime.get("in_dist", False)
    state           = regime.get("state", "NONE")
    breakout        = regime.get("breakout", False)

    rs_score        = float(rs_score or 0.0)

    # ── Step 1: Quality score + confirmations/warnings ────────────────────────
    quality = 0
    confirmations: list[str] = []
    warnings: list[str] = []

    # ── Structure signals ─────────────────────────────────────────────────────
    if ribbon_compr == "STRONG":
        quality += 20
        confirmations.append("Strong EMA ribbon compression")
    elif ribbon_compr == "MEDIUM":
        quality += 12
        confirmations.append("Medium EMA ribbon compression")

    if compr_bullish:
        quality += 15
        confirmations.append("Price above compressed EMA ribbon (bullish alignment)")
    elif bullish_stack:
        quality += 10
        confirmations.append("Bullish EMA stack")

    if bearish_stack:
        quality -= 20
        warnings.append("Bearish EMA stack — price below all EMAs")

    # ── Price action ──────────────────────────────────────────────────────────
    if above_ema20 and above_ema50:
        quality += 8
        confirmations.append("Price above both EMA20 and EMA50")
    elif above_ema20:
        quality += 4
        confirmations.append("Price above EMA20")

    if ema8_slope == "RISING":
        quality += 8
        confirmations.append("Fast EMA (8) sloping upward")
    elif ema8_slope == "FALLING":
        quality -= 5
        warnings.append("Fast EMA falling — short-term momentum weakening")

    if sqz_bars >= 10:
        quality += 12
        confirmations.append(f"Deep BB squeeze: {sqz_bars} consecutive bars")
    elif sqz_bars >= 5:
        quality += 8
        confirmations.append(f"BB squeeze building: {sqz_bars} bars")
    elif sqz_bars >= 3:
        quality += 4
        confirmations.append(f"Early BB squeeze: {sqz_bars} bars")

    if in_acc and state not in ("FIRE",):
        quality += 8
        confirmations.append("Wyckoff accumulation phase detected")

    if rsi_divergence:
        quality += 8
        confirmations.append("RSI divergence — hidden bullish strength")
    elif 35 <= rsi_value <= 55:
        quality += 4
        confirmations.append(f"RSI in constructive zone ({rsi_value:.0f})")
    elif rsi_value > 72:
        warnings.append(f"RSI overbought ({rsi_value:.0f}) — extended")

    # ── Money flow ────────────────────────────────────────────────────────────
    if cmf_pctl >= 70:
        quality += 10
        confirmations.append(f"CMF strong ({cmf_pctl:.0f}th percentile)")
    elif cmf_pctl >= 50:
        quality += 5
        confirmations.append(f"CMF positive ({cmf_pctl:.0f}th percentile)")
    elif cmf_pctl < 25:
        warnings.append("Weak money flow (CMF below 25th percentile)")

    if obv_strength == "STRONG":
        quality += 10
        confirmations.append("OBV strong — sustained accumulation")
    elif obv_strength == "MEDIUM":
        quality += 5
        confirmations.append("OBV medium — moderate buying pressure")
    elif obv_strength == "NEGATIVE":
        quality -= 8
        warnings.append("OBV negative — more volume on down-days")

    if obv_divergence:
        quality += 8
        confirmations.append("OBV divergence — OBV rising while price flat (stealth buying)")

    if is_stealth:
        quality += 6
        confirmations.append("Stealth volume pattern — high volume, quiet price")

    # ── Volume emergence ──────────────────────────────────────────────────────
    # The KEY differentiation: volume is rising but not yet at breakout threshold (2.0)
    if anomaly_ratio >= 1.8:
        quality += 15
        confirmations.append(f"Volume near breakout level ({anomaly_ratio:.1f}x avg)")
    elif anomaly_ratio >= 1.2:
        quality += 10
        confirmations.append(f"Volume rising ({anomaly_ratio:.1f}x avg) — pre-breakout emergence")
    elif anomaly_ratio >= 0.8:
        quality += 5
        confirmations.append(f"Volume picking up ({anomaly_ratio:.1f}x avg)")
    # anomaly < 0.5 = no volume signal, no points added

    # ── Relative strength ─────────────────────────────────────────────────────
    if rs_score > 10:
        quality += 10
        confirmations.append(f"Strong relative strength vs market (+{rs_score:.1f}%)")
    elif rs_score > 3:
        quality += 5
        confirmations.append(f"Positive relative strength vs market (+{rs_score:.1f}%)")
    elif rs_score < -5:
        warnings.append(f"Underperforming market ({rs_score:.1f}%) — sector rotation risk")

    # ── Sector context (if available) ─────────────────────────────────────────
    if sector_context:
        sc_class = sector_context.get("sector_class", "C")
        vs_spy = sector_context.get("vs_spy_1d", 0.0) or 0.0
        if sc_class in ("A", "B"):
            quality += 5
            confirmations.append(f"Strong sector ({sc_class} class)")
        elif sc_class in ("D", "F"):
            quality -= 5
            warnings.append(f"Weak sector ({sc_class} class)")
        if vs_spy > 0.5:
            quality += 3
            confirmations.append("Sector outperforming SPY today")

    # ── Warnings ──────────────────────────────────────────────────────────────
    if ema_spread > 8.0:
        quality -= 10
        warnings.append(f"Price too extended above ribbon ({ema_spread:.1f}% spread)")

    if today_vol < 300_000:
        quality -= 15
        warnings.append(f"Low liquidity ({today_vol:,} shares today)")

    if earnings_risk == "HIGH":
        quality -= 10
        warnings.append("High earnings risk — imminent report")
    elif earnings_risk == "MEDIUM":
        warnings.append("Upcoming earnings — moderate risk")

    if in_dist:
        quality -= 20
        warnings.append("Wyckoff distribution — smart money may be exiting")

    # ── Clamp quality ─────────────────────────────────────────────────────────
    quality = max(0, min(100, quality))

    # ── Step 2: Determine dominant ignition bucket ────────────────────────────
    bucket_scores: dict[str, int] = {
        "RIBBON_LED": 0,
        "PRICE_LED":  0,
        "VOLUME_LED": 0,
        "RS_LED":     0,
        "THEME_LED":  0,
    }

    if ribbon_compr in ("STRONG", "MEDIUM"):
        bucket_scores["RIBBON_LED"] += 30
    if compr_bullish:
        bucket_scores["RIBBON_LED"] += 20
    if sqz_bars >= 5:
        bucket_scores["RIBBON_LED"] += 10

    if above_ema20 and above_ema50 and ema8_slope == "RISING":
        bucket_scores["PRICE_LED"] += 30
    if above_ema20 and price_chg_pct > 1.0:
        bucket_scores["PRICE_LED"] += 15
    if rsi_divergence:
        bucket_scores["PRICE_LED"] += 10
    if in_acc:
        bucket_scores["PRICE_LED"] += 8

    if 0.8 <= anomaly_ratio < 2.0:
        bucket_scores["VOLUME_LED"] += 25
    if obv_strength == "STRONG":
        bucket_scores["VOLUME_LED"] += 15
    if obv_divergence or is_stealth:
        bucket_scores["VOLUME_LED"] += 10

    if rs_score > 5:
        bucket_scores["RS_LED"] += 30
    if rs_score > 10:
        bucket_scores["RS_LED"] += 20
    if rs_score > 0 and above_ema50:
        bucket_scores["RS_LED"] += 10

    if sector_context:
        sc_class = sector_context.get("sector_class", "C")
        vs_spy = sector_context.get("vs_spy_1d", 0.0) or 0.0
        if sc_class in ("A", "B") and vs_spy > 0.3:
            bucket_scores["THEME_LED"] += 25
        if vs_spy > 1.0:
            bucket_scores["THEME_LED"] += 15

    max_bucket_score = max(bucket_scores.values())
    if max_bucket_score < 10:
        bucket = "NONE"
    else:
        threshold = max_bucket_score * 0.7
        top_buckets = [k for k, v in bucket_scores.items() if v >= threshold and v > 0]
        if len(top_buckets) >= 3:
            bucket = "MIXED"
        elif len(top_buckets) == 2:
            # Two buckets roughly equal — call it MIXED
            bucket = "MIXED"
        elif top_buckets:
            bucket = top_buckets[0]
        else:
            bucket = "NONE"

    # ── Step 3: Signal classification ─────────────────────────────────────────
    n_conf = len(confirmations)

    if bearish_stack and in_dist:
        # Hard override — no ignition in full distribution + bearish trend
        signal = "NO_IGNITION"
        quality = min(quality, 10)
        bucket = "NONE"
    elif quality >= 60 and n_conf >= 4:
        # Strong quality + multiple confirmations
        if anomaly_ratio >= 1.5 or breakout or state in ("FIRE", "ARM"):
            signal = "IGNITION_CONFIRMED"
        else:
            signal = "EARLY_IGNITION"
    elif quality >= 40 and n_conf >= 3:
        signal = "EARLY_IGNITION"
    elif quality >= 22 and n_conf >= 2:
        signal = "IGNITION_WATCH"
    else:
        signal = "NO_IGNITION"

    # ── Step 4: Human-readable reason ─────────────────────────────────────────
    if signal == "IGNITION_CONFIRMED":
        if anomaly_ratio >= 1.5:
            reason = (
                f"Strong structure + volume rising ({anomaly_ratio:.1f}x avg) "
                f"approaching breakout threshold — {n_conf} signals aligned"
            )
        elif breakout:
            reason = (
                f"Breakout from accumulation base with {n_conf} confirming signals "
                f"({'bullish ribbon' if compr_bullish else 'EMA aligned'})"
            )
        else:
            reason = (
                f"High-confidence ignition: {n_conf} signals aligned "
                f"({'compression + bullish' if compr_bullish else ribbon_compr.lower() + ' ribbon'})"
            )
    elif signal == "EARLY_IGNITION":
        if bucket == "RIBBON_LED":
            ribbon_desc = "Strong" if ribbon_compr == "STRONG" else "Medium"
            bullish_note = " + bullish alignment" if compr_bullish else ""
            reason = (
                f"{ribbon_desc} EMA compression{bullish_note} — "
                f"coiled spring before full volume confirmation"
            )
        elif bucket == "PRICE_LED":
            reason = (
                f"Price recovering above EMA cluster (slope {'rising' if ema8_slope == 'RISING' else 'improving'}) "
                f"— strength accumulating quietly"
            )
        elif bucket == "RS_LED":
            reason = (
                f"Relative strength +{rs_score:.1f}% vs market — "
                f"quiet rotation into this name before breakout"
            )
        elif bucket == "VOLUME_LED":
            reason = (
                f"Volume waking up ({anomaly_ratio:.1f}x avg) before hitting official breakout threshold — "
                f"early accumulation signal"
            )
        elif bucket == "MIXED":
            reason = (
                f"Multiple early signals aligning ({n_conf} confirmations) — "
                f"setup building across structure + flow + price action"
            )
        else:
            reason = f"Early accumulation pattern: {n_conf} signals present"
    elif signal == "IGNITION_WATCH":
        reason = (
            "Constructive structure forming — watchlist candidate, "
            "needs volume or price confirmation to escalate"
        )
    else:
        if n_conf == 0:
            reason = "No ignition signals detected"
        else:
            reason = f"Insufficient signal confluence ({n_conf} weak confirmations) — noise level"

    return {
        "ignition_signal":        signal,
        "ignition_bucket":        bucket,
        "ignition_quality":       quality,
        "ignition_reason":        reason,
        "ignition_confirmations": confirmations,
        "ignition_warnings":      warnings,
    }


def enrich_results_with_ignition(results: list[dict]) -> list[dict]:
    """
    Apply ignition analysis to a list of scan result dicts in-place.
    Safe to call on both main-scan results and ribbon-pass candidates.
    Does NOT modify total_score or tier.
    """
    for r in results:
        try:
            indicators = r.get("indicators") or {}
            regime     = r.get("regime") or {}
            rs         = indicators.get("rs_score") or r.get("rs_score") or 0.0
            earnings   = r.get("earnings_risk") or "NONE"
            sector_ctx = None  # could be enriched from sector_perf if passed

            r["ignition"] = calc_ignition(
                indicators=indicators,
                regime=regime,
                rs_score=float(rs),
                earnings_risk=str(earnings),
                sector_context=sector_ctx,
            )
        except Exception as e:
            logger.warning(f"ignition calc failed for {r.get('symbol', '?')}: {e}")
            r["ignition"] = {
                "ignition_signal":        "NO_IGNITION",
                "ignition_bucket":        "NONE",
                "ignition_quality":       0,
                "ignition_reason":        "Calculation error",
                "ignition_confirmations": [],
                "ignition_warnings":      [],
            }
    return results


def build_ignition_response(
    main_results: list[dict],
    ribbon_results: list[dict],
    mode: str = "all",
    min_volume: int = 200_000,
    min_quality: int = 0,
    bullish_only: bool = False,
    max_results: int = 100,
) -> dict:
    """
    Merge main scan + ribbon candidates, apply ignition analysis,
    filter and sort. Returns the full ignition endpoint response.
    """
    # Tag source on copies (never mutate originals)
    main_tagged = []
    for r in main_results:
        rc = {
            # Flatten key fields for the response (don't return full indicator dicts)
            "symbol":           r.get("symbol"),
            "price":            r.get("price"),
            "sector":           r.get("sector"),
            "tier":             r.get("score", {}).get("tier") if r.get("score") else None,
            "total_score":      r.get("score", {}).get("total_score") if r.get("score") else None,
            "source":           "main_scan",
            "anomaly_ratio":    r.get("indicators", {}).get("anomaly_ratio"),
            "cmf_pctl":         r.get("indicators", {}).get("cmf_pctl"),
            "obv_strength":     (r.get("indicators", {}).get("obv") or {}).get("obv_strength"),
            "obv_divergence":   (r.get("indicators", {}).get("obv") or {}).get("obv_divergence"),
            "ribbon_compression": r.get("indicators", {}).get("ribbon_compression"),
            "bullish_stack":    r.get("indicators", {}).get("bullish_stack"),
            "bearish_stack":    r.get("indicators", {}).get("bearish_stack"),
            "compression_and_bullish": r.get("indicators", {}).get("compression_and_bullish"),
            "ema_spread_pct":   r.get("indicators", {}).get("ema_spread_pct"),
            "ema8_slope":       r.get("indicators", {}).get("ema8_slope"),
            "rs_score":         r.get("indicators", {}).get("rs_score") or 0.0,
            "today_vol":        r.get("indicators", {}).get("today_vol") or r.get("volume_today"),
            "bb_sqz_bars":      r.get("indicators", {}).get("bb_sqz_bars", 0),
            "rsi":              (r.get("indicators", {}).get("rsi") or {}).get("value"),
            "earnings_risk":    r.get("earnings_risk", "NONE"),
            "ai_analysis":      r.get("ai_analysis"),
            # Keep full indicators + regime for ignition calc
            "_indicators":      r.get("indicators", {}),
            "_regime":          r.get("regime", {}),
        }
        main_tagged.append(rc)

    ribbon_tagged = []
    for r in ribbon_results:
        rc = {
            "symbol":           r.get("symbol"),
            "price":            r.get("price"),
            "sector":           r.get("sector"),
            "tier":             None,   # ribbon candidates have no tier
            "total_score":      None,
            "source":           "ribbon_pass",
            "anomaly_ratio":    r.get("anomaly_ratio"),
            "cmf_pctl":         r.get("cmf_pctl"),
            "obv_strength":     r.get("obv_strength"),
            "obv_divergence":   None,   # not stored in ribbon table
            "ribbon_compression": r.get("ribbon_compression"),
            "bullish_stack":    r.get("bullish_stack", False),
            "bearish_stack":    r.get("bearish_stack", False),
            "compression_and_bullish": r.get("compression_and_bullish", False),
            "ema_spread_pct":   r.get("ema_spread_pct"),
            "ema8_slope":       r.get("ema8_slope"),
            "rs_score":         r.get("rs_score") or 0.0,
            "today_vol":        r.get("today_vol"),
            "bb_sqz_bars":      r.get("bb_sqz_bars", 0),
            "rsi":              r.get("rsi"),
            "earnings_risk":    "NONE",
            "ai_analysis":      None,
            "_indicators":      {
                # Reconstruct a minimal indicators dict from stored fields
                "ribbon_compression": r.get("ribbon_compression", "NONE"),
                "bullish_stack":      r.get("bullish_stack", False),
                "bearish_stack":      r.get("bearish_stack", False),
                "compression_and_bullish": r.get("compression_and_bullish", False),
                "ema8_slope":         r.get("ema8_slope", "FLAT"),
                "ema_spread_pct":     r.get("ema_spread_pct", 999.0),
                "above_ema20":        True,  # conservative default
                "above_ema50":        r.get("bullish_stack", False),
                "bb_sqz_bars":        r.get("bb_sqz_bars", 0),
                "anomaly_ratio":      r.get("anomaly_ratio", 0.0),
                "vol_z":              0.0,
                "cmf_pctl":           r.get("cmf_pctl", 0.0),
                "cmf":                0.0,
                "obv": {
                    "obv_strength":  r.get("obv_strength", "WEAK"),
                    "obv_divergence": False,
                },
                "rsi": {"value": r.get("rsi", 50.0)},
                "stealth": {},
                "today_vol":          r.get("today_vol", 0),
                "rs_score":           r.get("rs_score", 0.0),
                "price_change_pct":   0.0,
            },
            "_regime": {},
        }
        ribbon_tagged.append(rc)

    # Deduplicate — main scan takes priority over ribbon
    main_symbols = {r["symbol"] for r in main_tagged}
    ribbon_unique = [r for r in ribbon_tagged if r["symbol"] not in main_symbols]
    all_candidates = main_tagged + ribbon_unique

    # Apply ignition scoring
    for r in all_candidates:
        try:
            r["ignition"] = calc_ignition(
                indicators=r.pop("_indicators"),
                regime=r.pop("_regime"),
                rs_score=float(r.get("rs_score") or 0.0),
                earnings_risk=r.get("earnings_risk", "NONE"),
            )
        except Exception as e:
            logger.warning(f"ignition failed for {r.get('symbol')}: {e}")
            r.pop("_indicators", None)
            r.pop("_regime", None)
            r["ignition"] = {
                "ignition_signal": "NO_IGNITION",
                "ignition_bucket": "NONE",
                "ignition_quality": 0,
                "ignition_reason": "Error",
                "ignition_confirmations": [],
                "ignition_warnings": [],
            }

    # Flatten ignition fields onto the top-level dict for easier frontend consumption
    for r in all_candidates:
        ig = r.get("ignition", {})
        r["ignition_signal"]        = ig.get("ignition_signal", "NO_IGNITION")
        r["ignition_bucket"]        = ig.get("ignition_bucket", "NONE")
        r["ignition_quality"]       = ig.get("ignition_quality", 0)
        r["ignition_reason"]        = ig.get("ignition_reason", "")
        r["ignition_confirmations"] = ig.get("ignition_confirmations", [])
        r["ignition_warnings"]      = ig.get("ignition_warnings", [])

    # Apply filters
    filtered = []
    for r in all_candidates:
        if r.get("today_vol") and r["today_vol"] < min_volume:
            continue
        if r["ignition_quality"] < min_quality:
            continue
        if bullish_only and r.get("bearish_stack"):
            continue
        sig = r["ignition_signal"]
        if mode == "confirmed" and sig != "IGNITION_CONFIRMED":
            continue
        if mode == "early" and sig not in ("IGNITION_CONFIRMED", "EARLY_IGNITION"):
            continue
        if mode == "watch" and sig == "NO_IGNITION":
            continue
        filtered.append(r)

    # Sort by ignition_quality descending, then total_score (main scan priority)
    filtered.sort(
        key=lambda x: (x["ignition_quality"], x.get("total_score") or 0),
        reverse=True,
    )
    filtered = filtered[:max_results]

    # Build summary
    all_sigs = [r["ignition_signal"] for r in filtered]
    by_bucket: dict[str, int] = {}
    for r in filtered:
        b = r["ignition_bucket"]
        by_bucket[b] = by_bucket.get(b, 0) + 1

    summary = {
        "total":     len(filtered),
        "confirmed": all_sigs.count("IGNITION_CONFIRMED"),
        "early":     all_sigs.count("EARLY_IGNITION"),
        "watch":     all_sigs.count("IGNITION_WATCH"),
        "no_signal": all_sigs.count("NO_IGNITION"),
        "from_main":   sum(1 for r in filtered if r["source"] == "main_scan"),
        "from_ribbon": sum(1 for r in filtered if r["source"] == "ribbon_pass"),
        "by_bucket": by_bucket,
    }

    return {"results": filtered, "summary": summary}
