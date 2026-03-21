"""
Hype Monitor — Divergence Detector
Detects mismatches between social hype and price/volume action.

Divergence types:
  SILENT_VOLUME   — high volume anomaly, low social hype (smart money accumulating quietly)
  VELOCITY_SPIKE  — sudden acceleration in mentions (catalyst or retail FOMO starting)
  PEAK_FADING     — hype was high but now falling, price hasn't moved (sentiment exhaustion)
  HYPE_NO_VOLUME  — lots of social buzz, but volume not confirming (pump attempt without follow-through)
"""
from typing import Any


def detect_divergences(
    hype_score: dict[str, Any],
    velocity: dict[str, Any],
    scan_result: dict[str, Any],
    previous_hype: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """
    Detect all active divergence signals.

    Args:
        hype_score:    Output of calc_hype_score()
        velocity:      Output of calc_velocity()
        scan_result:   Ticker entry from the main scan (indicators, regime, score, etc.)
        previous_hype: Previous hype state dict (from last monitor cycle)

    Returns:
        List of {type, label, description, severity} dicts (may be empty)
    """
    divergences = []

    indicators = scan_result.get("indicators", {})
    anomaly_ratio = indicators.get("anomaly_ratio") or 0
    price_change_pct = indicators.get("price_change_pct") or 0

    hype_index = hype_score.get("hype_index", 0)
    vel_2h = velocity.get("combined_velocity_2h", 0)
    prev_hype_index = (previous_hype or {}).get("hype_index", None)

    # ── SILENT_VOLUME ─────────────────────────────────────────────────────────
    # High vol anomaly + low hype = smart money moving without retail noticing
    if anomaly_ratio >= 2.5 and hype_index <= 30:
        severity = "HIGH" if anomaly_ratio >= 4.0 else "MEDIUM"
        divergences.append({
            "type": "SILENT_VOLUME",
            "label": "🔇 SILENT VOLUME",
            "description": (
                f"Volume {anomaly_ratio:.1f}x above average with only {hype_index:.0f}/100 social hype. "
                "Smart money moving without retail attention."
            ),
            "severity": severity,
        })

    # ── VELOCITY_SPIKE ────────────────────────────────────────────────────────
    # Sudden acceleration in mentions (2h rate ≥ 3x baseline)
    if vel_2h >= 3.0:
        severity = "HIGH" if vel_2h >= 6.0 else "MEDIUM"
        divergences.append({
            "type": "VELOCITY_SPIKE",
            "label": "🚀 VELOCITY SPIKE",
            "description": (
                f"Mention velocity {vel_2h:.1f}x above normal pace in last 2 hours. "
                "Retail attention accelerating rapidly."
            ),
            "severity": severity,
        })

    # ── PEAK_FADING ───────────────────────────────────────────────────────────
    # Hype was high but now dropping while price hasn't responded (distribution)
    if prev_hype_index is not None:
        hype_drop = prev_hype_index - hype_index
        if hype_drop >= 15 and prev_hype_index >= 50 and abs(price_change_pct) < 3.0:
            divergences.append({
                "type": "PEAK_FADING",
                "label": "📉 PEAK FADING",
                "description": (
                    f"Hype dropped from {prev_hype_index:.0f} to {hype_index:.0f} "
                    f"while price only moved {price_change_pct:+.1f}%. Sentiment exhaustion."
                ),
                "severity": "MEDIUM",
            })

    # ── HYPE_NO_VOLUME ────────────────────────────────────────────────────────
    # Social buzz without volume confirmation = possible pump attempt
    if hype_index >= 50 and anomaly_ratio < 1.5:
        severity = "HIGH" if hype_index >= 70 and anomaly_ratio < 1.2 else "MEDIUM"
        divergences.append({
            "type": "HYPE_NO_VOLUME",
            "label": "⚠ HYPE, NO VOLUME",
            "description": (
                f"High hype ({hype_index:.0f}/100) but volume only {anomaly_ratio:.1f}x normal. "
                "Social buzz not confirmed by institutional participation."
            ),
            "severity": severity,
        })

    return divergences
