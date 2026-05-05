"""
Missed Pump Dataset Builder.

Queries raw_pattern_episode_features for a given run_id and classifies
episodes into research groups:

  missed_4x_pump   — 4x pump that scanner did NOT flag as BUY_CANDIDATE
  detected_4x_pump — 4x pump that scanner DID flag as BUY_CANDIDATE
  false_positive    — false positive (scan flagged, no pump)
  normal_winner     — strong sub-4x winner
  split_artifact    — split artifact (excluded from clean training)

Output per episode includes why_missed analysis so the Pattern Miner
can find common failure modes.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ── Group classification ──────────────────────────────────────────────────────

def _classify_episode_group(ep: dict) -> str:
    """Return the research group label for one episode dict."""
    gt           = ep.get("group_type") or ""
    artifact     = ep.get("split_artifact_risk") or False
    had_buy      = ep.get("had_np_buy_candidate_pre") or False

    if artifact:
        return "split_artifact"

    if gt == "4x_pump":
        return "detected_4x_pump" if had_buy else "missed_4x_pump"

    if gt == "false_positive":
        return "false_positive"

    if gt == "normal_winner":
        return "normal_winner"

    if gt == "missed_mover":
        return "normal_winner"

    return "unknown"


def _why_missed(ep: dict) -> dict:
    """
    Analyse why a 4x_pump was missed by the scanner.
    Returns a dict of boolean flags + a human-readable list of reasons.
    """
    flags: dict[str, bool] = {
        "missed_because_avoid":                  bool(ep.get("had_np_avoid_pre")),
        "missed_because_high_expansion_risk":    (
            ep.get("max_expansion_timing_risk_pre") == "HIGH"
        ),
        "missed_because_broken_structure":       (
            ep.get("best_structure_phase_pre") in ("BROKEN_STRUCTURE", None)
            and not ep.get("had_confirmed_structure_pre")
            and not ep.get("had_triggered_structure_pre")
        ),
        "missed_because_no_trigger":             (
            not ep.get("had_valid_recent_trigger")
            and not ep.get("had_valid_recent_confirm")
        ),
        "missed_because_no_buy_candidate":       (
            not ep.get("had_np_buy_candidate_pre")
        ),
        "missed_because_split_filter":           (
            ep.get("split_context") in ("RECENT_REVERSE_SPLIT", "SPLIT_ARTIFACT_RISK")
        ),
        "missed_because_insufficient_candles":   bool(ep.get("np_skip_reason")),
        "missed_because_only_watch":             (
            bool(ep.get("had_np_watch_pre"))
            and not ep.get("had_np_buy_candidate_pre")
        ),
    }

    reasons: list[str] = [k for k, v in flags.items() if v]
    flags["missed_reasons"] = reasons  # type: ignore[assignment]
    return flags


def _existing_signals_summary(ep: dict) -> dict:
    """Summarise which existing scanner signals were present in the pre-window."""
    return {
        "had_buy_candidate":      bool(ep.get("had_np_buy_candidate_pre")),
        "had_watch":              bool(ep.get("had_np_watch_pre")),
        "had_avoid":              bool(ep.get("had_np_avoid_pre")),
        "had_d_confluence":       bool(ep.get("had_d_confluence_pre")),
        "had_confirmed_structure": bool(ep.get("had_confirmed_structure_pre")),
        "had_triggered_structure": bool(ep.get("had_triggered_structure_pre")),
        "had_early_structure":    bool(ep.get("had_early_structure_pre")),
        "had_accumulation_like":  bool(ep.get("had_accumulation_like")),
        "had_spring_test_lps":    bool(ep.get("had_spring_test_lps")),
        "had_valid_full_sequence": bool(ep.get("had_valid_full_sequence")),
        "buy_candidate_day_count": ep.get("buy_candidate_day_count_pre") or 0,
        "watch_day_count":        ep.get("watch_day_count_pre") or 0,
        "avoid_day_count":        ep.get("avoid_day_count_pre") or 0,
        "d_confluence_day_count": ep.get("d_confluence_day_count_pre") or 0,
        "max_structure_score":    ep.get("max_structure_score_pre") or 0,
        "split_context":          ep.get("split_context") or "NO_SPLIT",
    }


# ── Episode-level feature extraction ─────────────────────────────────────────

def _episode_to_dataset_row(ep: dict) -> dict:
    """Convert a raw_pattern_episode_features dict to a dataset row."""
    research_group = _classify_episode_group(ep)
    why            = _why_missed(ep) if research_group == "missed_4x_pump" else {}
    signals        = _existing_signals_summary(ep)

    return {
        # Identity
        "episode_id":      ep.get("episode_id") or ep.get("id"),
        "run_id":          ep.get("run_id"),
        "symbol":          ep.get("symbol"),
        "group_type":      ep.get("group_type"),
        "research_group":  research_group,
        # Episode performance
        "pump_multiple":   ep.get("pump_multiple"),
        "pump_type":       ep.get("pump_type"),
        "split_context":   ep.get("split_context") or "NO_SPLIT",
        "split_artifact_risk": bool(ep.get("split_artifact_risk")),
        # Pre-window signals
        "existing_signals": signals,
        # Why missed (only populated for missed_4x_pump)
        "why_missed":      why,
        # Key episode features for pattern mining
        "pre_features": {
            # EMA / ribbon
            "had_bull_stack_pre":          ep.get("had_bull_stack_pre"),
            "bull_stack_days_pre":         ep.get("bull_stack_days_pre") or 0,
            "days_above_ema50_pre":        ep.get("days_above_ema50_pre") or 0,
            "ema50_reclaim_count_pre":     ep.get("ema50_reclaim_count_pre") or 0,
            "avg_close_vs_ema50_pct_pre":  ep.get("avg_close_vs_ema50_pct_pre"),
            # Volume / compression
            "dryup_day_count_pre":         ep.get("dryup_day_count_pre") or 0,
            "compression_days_pre":        ep.get("compression_days_pre") or 0,
            "atr_contraction_days_pre":    ep.get("atr_contraction_days_pre") or 0,
            "had_compression":             ep.get("had_compression"),
            "max_volume_anomaly_pre":      ep.get("max_volume_anomaly_pre"),
            "median_volume_anomaly_pre":   ep.get("median_volume_anomaly_pre"),
            "abnormal_volume_day_count_pre": ep.get("abnormal_volume_day_count_pre") or 0,
            "extreme_anomaly_day_count_pre": ep.get("extreme_anomaly_day_count_pre") or 0,
            # Structure
            "max_structure_score_pre":     ep.get("max_structure_score_pre") or 0,
            "avg_structure_score_pre":     ep.get("avg_structure_score_pre") or 0,
            "dominant_structure_phase_pre": ep.get("dominant_structure_phase_pre"),
            "best_structure_phase_pre":    ep.get("best_structure_phase_pre"),
            "had_confirmed_structure_pre": ep.get("had_confirmed_structure_pre"),
            "had_triggered_structure_pre": ep.get("had_triggered_structure_pre"),
            "had_early_structure_pre":     ep.get("had_early_structure_pre"),
            "had_accumulation_ready_pre":  ep.get("had_accumulation_ready_pre"),
            "had_overheated_expansion_pre": ep.get("had_overheated_expansion_pre"),
            "max_expansion_timing_risk_pre": ep.get("max_expansion_timing_risk_pre"),
            "high_expansion_risk_day_count_pre": ep.get("high_expansion_risk_day_count_pre") or 0,
            # D / WLNBB
            "had_d_confluence_pre":        ep.get("had_d_confluence_pre"),
            "d_confluence_day_count_pre":  ep.get("d_confluence_day_count_pre") or 0,
            "d_confluence_best_type_pre":  ep.get("d_confluence_best_type_pre"),
            "dominant_d_confluence_family_pre": ep.get("dominant_d_confluence_family_pre"),
            # NP routing
            "had_np_buy_candidate_pre":    ep.get("had_np_buy_candidate_pre"),
            "had_np_watch_pre":            ep.get("had_np_watch_pre"),
            "had_np_avoid_pre":            ep.get("had_np_avoid_pre"),
            "buy_candidate_day_count_pre": ep.get("buy_candidate_day_count_pre") or 0,
            "watch_day_count_pre":         ep.get("watch_day_count_pre") or 0,
            "avoid_day_count_pre":         ep.get("avoid_day_count_pre") or 0,
            "valid_setup_days_pre":        ep.get("valid_setup_days_pre") or 0,
            "valid_trigger_days_pre":      ep.get("valid_trigger_days_pre") or 0,
            # Accumulation / Wyckoff
            "had_accumulation_like":       ep.get("had_accumulation_like"),
            "accumulation_like_day_count": ep.get("accumulation_like_day_count") or 0,
            "had_spring_test_lps":         ep.get("had_spring_test_lps"),
            "reclaim_bar_count_pre":       ep.get("reclaim_bar_count_pre") or 0,
            # Timing
            "days_in_base":                ep.get("days_in_base") or 0,
            "days_from_first_compression_to_breakout": ep.get("days_from_first_compression_to_breakout"),
            "days_from_first_abnormal_volume_to_breakout": ep.get("days_from_first_abnormal_volume_to_breakout"),
            # Split
            "has_reverse_split_near_episode": ep.get("has_reverse_split_near_episode"),
            "nearest_split_ratio":         ep.get("nearest_split_ratio"),
            "nearest_split_days_from_breakout": ep.get("nearest_split_days_from_breakout"),
            "reverse_split_0_5d_before_breakout":  ep.get("reverse_split_0_5d_before_breakout"),
            "reverse_split_6_15d_before_breakout": ep.get("reverse_split_6_15d_before_breakout"),
        },
    }


# ── Dataset builder ───────────────────────────────────────────────────────────

def build_missed_pump_dataset(
    episodes: list[dict],
    exclude_split_artifacts: bool = True,
    min_pump_multiple: float = 4.0,
) -> dict:
    """
    Build a structured research dataset from a list of raw_pattern_episode_features dicts.

    Parameters
    ----------
    episodes              : list of episode feature dicts (from get_raw_pattern_episode_features)
    exclude_split_artifacts: if True, split_artifact episodes go to their own group, not mixed in
    min_pump_multiple     : minimum pump multiple to count as a 4x pump candidate

    Returns
    -------
    {
      "missed_4x_pump":   [...],
      "detected_4x_pump": [...],
      "false_positive":   [...],
      "normal_winner":    [...],
      "split_artifact":   [...],
      "unknown":          [...],
      "summary": {...},
    }
    """
    groups: dict[str, list[dict]] = {
        "missed_4x_pump":   [],
        "detected_4x_pump": [],
        "false_positive":   [],
        "normal_winner":    [],
        "split_artifact":   [],
        "unknown":          [],
    }

    for ep in episodes:
        row = _episode_to_dataset_row(ep)
        grp = row["research_group"]
        groups[grp].append(row)

    # Summary statistics
    n_missed   = len(groups["missed_4x_pump"])
    n_detected = len(groups["detected_4x_pump"])
    n_fp       = len(groups["false_positive"])
    n_nw       = len(groups["normal_winner"])
    n_art      = len(groups["split_artifact"])
    n_total_4x = n_missed + n_detected

    # Most common why_missed reasons
    reason_counts: dict[str, int] = {}
    for row in groups["missed_4x_pump"]:
        for reason in row.get("why_missed", {}).get("missed_reasons", []):
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

    top_reasons = sorted(reason_counts.items(), key=lambda x: -x[1])

    # Pre-window feature medians for missed vs detected
    def _median(vals: list) -> Optional[float]:
        clean = [v for v in vals if v is not None]
        if not clean:
            return None
        s = sorted(clean)
        m = len(s) // 2
        return float(s[m]) if len(s) % 2 == 1 else (s[m-1] + s[m]) / 2

    def _feature_median(group: list[dict], key: str) -> Optional[float]:
        return _median([r["pre_features"].get(key) for r in group])

    comparison_features = [
        "buy_candidate_day_count_pre", "watch_day_count_pre", "avoid_day_count_pre",
        "dryup_day_count_pre", "compression_days_pre", "max_structure_score_pre",
        "d_confluence_day_count_pre", "bull_stack_days_pre", "days_above_ema50_pre",
        "accumulation_like_day_count", "max_volume_anomaly_pre", "high_expansion_risk_day_count_pre",
    ]

    missed_medians   = {k: _feature_median(groups["missed_4x_pump"],   k) for k in comparison_features}
    detected_medians = {k: _feature_median(groups["detected_4x_pump"], k) for k in comparison_features}
    fp_medians       = {k: _feature_median(groups["false_positive"],   k) for k in comparison_features}

    summary = {
        "total_episodes":       len(episodes),
        "missed_4x_pump_count": n_missed,
        "detected_4x_pump_count": n_detected,
        "total_4x_pump_count":  n_total_4x,
        "false_positive_count": n_fp,
        "normal_winner_count":  n_nw,
        "split_artifact_count": n_art,
        "detection_rate":       round(n_detected / n_total_4x, 3) if n_total_4x > 0 else None,
        "miss_rate":            round(n_missed   / n_total_4x, 3) if n_total_4x > 0 else None,
        "top_miss_reasons":     top_reasons[:8],
        "feature_medians": {
            "missed_4x_pump":   missed_medians,
            "detected_4x_pump": detected_medians,
            "false_positive":   fp_medians,
        },
    }

    return {**groups, "summary": summary}


# ── Async DB loader ───────────────────────────────────────────────────────────

async def load_dataset_for_run(run_id: int) -> dict:
    """
    Load all episodes for a raw pattern run and build the research dataset.
    Returns the same structure as build_missed_pump_dataset().
    """
    from database import get_raw_pattern_episode_features

    try:
        episodes = await get_raw_pattern_episode_features(run_id=run_id, limit=10000)
    except Exception as exc:
        logger.error(f"load_dataset_for_run({run_id}): DB error: {exc}")
        return {}

    if not episodes:
        logger.warning(f"load_dataset_for_run({run_id}): no episodes found")
        return {}

    logger.info(
        f"load_dataset_for_run({run_id}): loaded {len(episodes)} episodes"
    )
    return build_missed_pump_dataset(episodes)


def get_group_as_features(
    dataset: dict,
    group: str,
    feature_keys: Optional[list[str]] = None,
) -> list[dict]:
    """
    Extract a flat list of pre_features dicts from a dataset group.
    Optionally filter to specific feature keys.
    """
    rows = dataset.get(group) or []
    result: list[dict] = []
    for row in rows:
        pf = row.get("pre_features") or {}
        if feature_keys:
            pf = {k: pf.get(k) for k in feature_keys}
        result.append({"symbol": row.get("symbol"), "episode_id": row.get("episode_id"), **pf})
    return result
