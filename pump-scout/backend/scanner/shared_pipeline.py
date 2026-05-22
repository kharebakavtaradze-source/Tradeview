"""
Shared analytics pipeline — single canonical call used by all three studios.
Given raw OHLCV candles, returns bar labels, readiness score, signals, and metrics.
"""
from __future__ import annotations
from typing import Optional


def run_episode_pipeline(
    candles: list[dict],
    bar_labels: Optional[list[dict]] = None,
) -> dict:
    """
    Process a candle list through the full bar-label + scoring pipeline.

    Args:
        candles:    Raw OHLCV candles (dicts with open/high/low/close/volume or o/h/l/c/v).
        bar_labels: Pre-computed bar labels (skips recomputation if provided).

    Returns dict with keys:
        bar_labels        list[dict]   One label dict per bar.
        score             float        Readiness score (0-10).
        readiness_tier    str          HOT / WARM / COOL / COLD.
        signals           list[str]    Confluence signal names that fired.
        metrics           dict         max_gap_pct_5d, max_vol_ratio_5d, etc.
    """
    from scanner.manual_d_wlnbb_features import compute_combined_bar_labels
    from scanner.demand_composite_scanner import _compute_candle_metrics, _compute_readiness

    if bar_labels is None:
        bar_labels = compute_combined_bar_labels(candles, last_n=len(candles))

    metrics = _compute_candle_metrics(candles)
    result  = _compute_readiness(bar_labels, metrics)

    return {
        "bar_labels":      bar_labels,
        "score":           result.get("readiness_score", 0.0),
        "readiness_tier":  result.get("readiness_tier",  "COLD"),
        "signals":         result.get("confluence_signals", []),
        "metrics":         metrics,
    }
