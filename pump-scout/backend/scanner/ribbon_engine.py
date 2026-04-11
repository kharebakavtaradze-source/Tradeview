"""
Ribbon Engine — Quality Classification Layer
=============================================
Promotes the ribbon signal from a boolean into a multi-level quality class.

Replay evidence: Ribbon=True candidates showed meaningful avg 5d return lift
(+1.15%) vs Ribbon=False (-1.42%). This module makes that quality dimension
explicit and usable in downstream engines (pump, ignition, research bundles).

Quality classes (best → worst):
  RIBBON_CONFIRMED     — compression + full bullish alignment + supportive flow
  RIBBON_CONSTRUCTIVE  — compression + bullish structure, some flow support
  RIBBON_EARLY         — ribbon forming, improving structure, not yet aligned
  RIBBON_WEAK          — ribbon signals present but deteriorating / mixed
  RIBBON_NONE          — no meaningful ribbon setup

CRITICAL: This module never modifies total_score, tier, or any live scanner
output. It is a read-only classification layer used by new analytical engines.
"""

import logging

logger = logging.getLogger(__name__)


def classify_ribbon(indicators: dict) -> str:
    """
    Classify the ribbon quality level for a single ticker.

    Parameters
    ----------
    indicators : output of calc_all() from indicators.py

    Returns
    -------
    str: one of RIBBON_CONFIRMED / RIBBON_CONSTRUCTIVE / RIBBON_EARLY /
         RIBBON_WEAK / RIBBON_NONE
    """
    ribbon_compression     = indicators.get("ribbon_compression", "NONE")
    bullish_stack          = indicators.get("bullish_stack", False)
    bearish_stack          = indicators.get("bearish_stack", False)
    compression_and_bullish = indicators.get("compression_and_bullish", False)
    ema8_slope             = indicators.get("ema8_slope", "FLAT")
    ema_spread_pct         = indicators.get("ema_spread_pct", 999.0) or 999.0
    cmf_val                = indicators.get("cmf", 0.0) or 0.0
    cmf_pctl               = indicators.get("cmf_pctl", 0.0) or 0.0
    obv                    = indicators.get("obv", {}) or {}
    obv_strength           = obv.get("obv_strength", "WEAK")
    obv_slope_5d           = obv.get("obv_slope_5d", 0.0) or 0.0
    bb_squeeze             = indicators.get("bb_squeeze", False)
    above_ema20            = indicators.get("above_ema20", False)
    above_ema50            = indicators.get("above_ema50", False)

    # ── Hard NONE / WEAK cases ────────────────────────────────────────────────
    if ribbon_compression == "NONE" and not bullish_stack and not compression_and_bullish:
        return "RIBBON_NONE"

    # Bearish stack → degraded even if some compression exists
    if bearish_stack:
        return "RIBBON_WEAK"

    # ── Flow support check ────────────────────────────────────────────────────
    # At least moderate CMF + positive OBV slope = meaningful flow support
    cmf_positive    = cmf_val > 0.04 or cmf_pctl > 50
    obv_positive    = obv_strength in ("STRONG", "MEDIUM") or obv_slope_5d > 0
    flow_supportive = cmf_positive and obv_positive

    # ── Strong CMF alone counts as partial support ────────────────────────────
    strong_flow = cmf_val > 0.10 and cmf_pctl > 60

    # ── RIBBON_CONFIRMED ──────────────────────────────────────────────────────
    # Full ribbon alignment + flow confirmation
    if (
        compression_and_bullish
        and ribbon_compression in ("STRONG", "MEDIUM")
        and (flow_supportive or strong_flow)
        and ema8_slope == "RISING"
    ):
        return "RIBBON_CONFIRMED"

    # ── RIBBON_CONSTRUCTIVE ───────────────────────────────────────────────────
    # Compression + bullish orientation, partial flow or slope improvement
    if compression_and_bullish and ribbon_compression in ("STRONG", "MEDIUM"):
        return "RIBBON_CONSTRUCTIVE"

    if (
        ribbon_compression in ("STRONG", "MEDIUM")
        and bullish_stack
        and (flow_supportive or ema8_slope == "RISING")
    ):
        return "RIBBON_CONSTRUCTIVE"

    # BB squeeze with bullish stack is constructive even without full compression
    if bb_squeeze and bullish_stack and above_ema50:
        return "RIBBON_CONSTRUCTIVE"

    # ── RIBBON_EARLY ─────────────────────────────────────────────────────────
    # Ribbon forming but not yet fully aligned
    if ribbon_compression != "NONE" and ema8_slope == "RISING" and above_ema20:
        return "RIBBON_EARLY"

    if bullish_stack and ribbon_compression in ("MEDIUM", "WEAK") and cmf_positive:
        return "RIBBON_EARLY"

    if compression_and_bullish:
        # compression_and_bullish is set but not qualifying for CONFIRMED/CONSTRUCTIVE
        return "RIBBON_EARLY"

    # ── RIBBON_WEAK ──────────────────────────────────────────────────────────
    # Something ribbon-like exists but it's deteriorating or mixed
    return "RIBBON_WEAK"


def ribbon_class_rank(ribbon_class: str) -> int:
    """Return an integer rank for sorting (higher = stronger ribbon). 0 = none."""
    return {
        "RIBBON_CONFIRMED":    4,
        "RIBBON_CONSTRUCTIVE": 3,
        "RIBBON_EARLY":        2,
        "RIBBON_WEAK":         1,
        "RIBBON_NONE":         0,
    }.get(ribbon_class, 0)


def ribbon_class_color(ribbon_class: str) -> str:
    """Return a display color token for frontend use."""
    return {
        "RIBBON_CONFIRMED":    "lime",
        "RIBBON_CONSTRUCTIVE": "cyan",
        "RIBBON_EARLY":        "amber",
        "RIBBON_WEAK":         "text-muted",
        "RIBBON_NONE":         "text-dim",
    }.get(ribbon_class, "text-dim")
