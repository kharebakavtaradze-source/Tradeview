"""
Pump Watch Scorer — speculative pump discovery score.

This score is SEPARATE from Scanner V2 BUY/WATCH/AVOID routing.
It does NOT modify or weaken Scanner V2 trade routing.
It does NOT convert discoveries to BUY signals.

Key design decision (critical):
  HIGH expansion_timing_risk:
    → For BUY routing (Scanner V2): hard AVOID
    → For Pump Watch:               volatility regime marker only — NOT an automatic reject

Labels:
  PUMP_WATCH_HIGH    score >= 65
  PUMP_WATCH_MEDIUM  score 45–64
  PUMP_SPECULATIVE   score 30–44
  PUMP_IGNORE        score < 30

Input: pre_features dict from raw_pattern_episode_features row
Output: {pump_watch_score, pump_watch_label, pump_watch_reasons, ...}
"""

import json
import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ── Label thresholds ──────────────────────────────────────────────────────────

LABEL_HIGH       = "PUMP_WATCH_HIGH"
LABEL_MEDIUM     = "PUMP_WATCH_MEDIUM"
LABEL_SPECULATIVE = "PUMP_SPECULATIVE"
LABEL_IGNORE     = "PUMP_IGNORE"

THRESHOLD_HIGH       = 65
THRESHOLD_MEDIUM     = 45
THRESHOLD_SPECULATIVE = 30

# ── Diagnostic label IDs ──────────────────────────────────────────────────────

DIAG_MISSING_STRUCTURE_RESCUE        = "PX_MISSING_STRUCTURE_RESCUE"
DIAG_NO_SCANNER_RAW_STRENGTH_RESCUE  = "PX_NO_SCANNER_RAW_STRENGTH_RESCUE"
DIAG_REVERSE_SPLIT_REGIME            = "PX_REVERSE_SPLIT_REGIME"
DIAG_SPLIT_ARTIFACT_EXCLUDED         = "SPLIT_ARTIFACT_EXCLUDED"

_ALL_DIAG_LABELS = [
    DIAG_MISSING_STRUCTURE_RESCUE,
    DIAG_NO_SCANNER_RAW_STRENGTH_RESCUE,
    DIAG_REVERSE_SPLIT_REGIME,
    DIAG_SPLIT_ARTIFACT_EXCLUDED,
]


def _apply_diagnostic_labels(ep: dict, label: str, score: int,
                              risk_flags: list[str]) -> dict:
    """
    Compute diagnostic labels for an episode.

    Returns:
        {
          "pump_watch_diagnostic_labels": list[str],   # e.g. ["PX_MISSING_STRUCTURE_RESCUE"]
          "pump_watch_pattern_id":        str | None,  # primary diagnostic ID if any
          "pump_watch_rescue_reason":     str | None,  # human-readable rescue note
        }
    """
    diag_labels: list[str] = []
    pattern_id: Optional[str] = None
    rescue_reason: Optional[str] = None

    # ── PX_REVERSE_SPLIT_REGIME ───────────────────────────────────────────────
    split_ctx = ep.get("split_context") or ""
    has_reverse_split = split_ctx in ("RECENT_REVERSE_SPLIT", "OLD_REVERSE_SPLIT") or \
                        ep.get("has_reverse_split_near_episode")

    if has_reverse_split and not ep.get("split_artifact_risk"):
        diag_labels.append(DIAG_REVERSE_SPLIT_REGIME)
        pattern_id = DIAG_REVERSE_SPLIT_REGIME
        if split_ctx == "RECENT_REVERSE_SPLIT":
            rescue_reason = "reverse_split_regime_recent"
        else:
            rescue_reason = "reverse_split_regime_old"

    # ── PX_MISSING_STRUCTURE_RESCUE ───────────────────────────────────────────
    max_ss = ep.get("max_structure_score_pre") or 0
    bc_days = ep.get("buy_candidate_day_count_pre") or 0
    watch_days = ep.get("watch_day_count_pre") or 0

    missing_structure = (
        max_ss is None or max_ss <= 0
        or f"low_structure_score={max_ss}" in risk_flags
        or "low_structure_score=0" in " ".join(risk_flags)
    )
    no_scanner_pressure = (
        "no_scanner_pressure" in risk_flags
        or (bc_days <= 1 and watch_days <= 1
            and not ep.get("had_np_buy_candidate_pre")
            and not ep.get("had_np_watch_pre"))
    )

    dryup = ep.get("dryup_day_count_pre") or 0
    compression = ep.get("compression_days_pre") or 0
    atr_contraction = ep.get("atr_contraction_days_pre") or 0
    d_days = ep.get("d_confluence_day_count_pre") or 0
    d_best = ep.get("d_confluence_best_type") or ""
    bull_stack = ep.get("bull_stack_days_pre") or 0
    days_ema50 = ep.get("days_above_ema50_pre") or 0

    _STRONG_D_TYPES = {"D4_BEUP", "D6_BEUP", "D4_L34", "D3_L34", "D4_THEN_BEUP_5B"}

    has_raw_dryup = (8 <= dryup <= 30) or compression >= 6 or atr_contraction >= 10
    has_raw_dconf = d_days >= 4 or ep.get("had_d_confluence_pre") or d_best in _STRONG_D_TYPES
    has_raw_trend  = (
        bull_stack >= 10 or days_ema50 >= 15
        or ep.get("had_accumulation_like") or ep.get("had_spring_test_lps")
    )
    raw_strength = has_raw_dryup and has_raw_dconf and has_raw_trend

    if (missing_structure and no_scanner_pressure and raw_strength
            and not ep.get("split_artifact_risk")
            and label == LABEL_IGNORE and score >= 15):
        diag_labels.append(DIAG_MISSING_STRUCTURE_RESCUE)
        if not pattern_id:
            pattern_id = DIAG_MISSING_STRUCTURE_RESCUE
            rescue_reason = "missing_structure_rescue_raw_strength"

    # ── PX_NO_SCANNER_RAW_STRENGTH_RESCUE ─────────────────────────────────────
    # Fires when: no scanner pressure despite strong raw pre-pump evidence.
    # Structure may be present (unlike missing_structure rescue).
    # Separate from PX_MISSING_STRUCTURE_RESCUE — avoids double-tagging.
    _no_scanner = (
        "no_scanner_pressure" in risk_flags
        or (not ep.get("had_np_buy_candidate_pre")
            and not ep.get("had_np_watch_pre"))
    )
    _rs_score = 0
    if 8 <= (ep.get("dryup_day_count_pre") or 0) <= 30:
        _rs_score += 1
    if (ep.get("compression_days_pre") or 0) >= 6 or (ep.get("atr_contraction_days_pre") or 0) >= 10:
        _rs_score += 1
    if ep.get("had_spring_test_lps") or ep.get("had_accumulation_like"):
        _rs_score += 1
    _d_days2 = ep.get("d_confluence_day_count_pre") or 0
    _d_best2  = ep.get("d_confluence_best_type_pre") or ep.get("d_confluence_best_type") or ""
    if _d_days2 >= 4 or _d_best2 in _STRONG_D_TYPES:
        _rs_score += 1
    if (ep.get("accumulation_like_day_count") or 0) >= 10:
        _rs_score += 1
    if (ep.get("ema50_reclaim_count_pre") or 0) >= 2 or (ep.get("days_above_ema50_pre") or 0) >= 10:
        _rs_score += 1
    if (ep.get("valid_setup_days_pre") or 0) >= 10:
        _rs_score += 1

    if (DIAG_MISSING_STRUCTURE_RESCUE not in diag_labels
            and _no_scanner
            and _rs_score >= 4
            and not ep.get("split_artifact_risk")
            and ep.get("pump_type") not in (None, "UNKNOWN")):
        diag_labels.append(DIAG_NO_SCANNER_RAW_STRENGTH_RESCUE)
        if not pattern_id:
            pattern_id = DIAG_NO_SCANNER_RAW_STRENGTH_RESCUE
            rescue_reason = "no_scanner_pressure_but_raw_strength"

    return {
        "pump_watch_diagnostic_labels": diag_labels,
        "pump_watch_pattern_id":        pattern_id,
        "pump_watch_rescue_reason":     rescue_reason,
    }


# ── Scoring ───────────────────────────────────────────────────────────────────

def compute_pump_watch_score(ep: dict) -> dict:
    """
    Compute the Pump Watch score for one episode.

    Parameters
    ----------
    ep : dict from raw_pattern_episode_features (all columns as dict keys)

    Returns
    -------
    {
      pump_watch_score:       int,
      pump_watch_label:       str,
      pump_watch_reasons:     list[str],   # positive contributors
      pump_watch_risk_flags:  list[str],   # negative flags / warnings
      pump_watch_pattern_ids: list[str],   # matched seed patterns
      pump_watch_split_context: str,
      pump_watch_confidence:  str,         # HIGH / MEDIUM / LOW
    }
    """
    score    = 0
    reasons  = []
    risk_flags = []

    # ── Base eligibility checks ───────────────────────────────────────────────
    if ep.get("split_artifact_risk"):
        return {
            "pump_watch_score":             -40,
            "pump_watch_label":             LABEL_IGNORE,
            "pump_watch_reasons":           [],
            "pump_watch_risk_flags":        ["SPLIT_ARTIFACT_EXCLUDED"],
            "pump_watch_pattern_ids":       [],
            "pump_watch_split_context":     ep.get("split_context") or "SPLIT_ARTIFACT_RISK",
            "pump_watch_confidence":        "LOW",
            "pump_watch_diagnostic_labels": [DIAG_SPLIT_ARTIFACT_EXCLUDED],
            "pump_watch_pattern_id":        DIAG_SPLIT_ARTIFACT_EXCLUDED,
            "pump_watch_rescue_reason":     None,
        }

    skip_reason = ep.get("np_skip_reason") or ""
    if skip_reason in ("INSUFFICIENT_CANDLES", "NO_DATA"):
        risk_flags.append("INSUFFICIENT_CANDLES")
        score -= 15

    # ── Score components (additive) ───────────────────────────────────────────

    # Repeated buy pressure (strongest separator per raw-pattern run 98)
    bc_days = ep.get("buy_candidate_day_count_pre") or 0
    if bc_days >= 6:
        score += 25
        reasons.append(f"buy_candidate_days={bc_days} (strong repeated pressure)")
    elif bc_days >= 4:
        score += 18
        reasons.append(f"buy_candidate_days={bc_days} (moderate repeated pressure)")
    elif bc_days >= 2:
        score += 8
        reasons.append(f"buy_candidate_days={bc_days}")

    # Structure score
    max_ss = ep.get("max_structure_score_pre") or 0
    avg_ss = ep.get("avg_structure_score_pre") or 0
    if max_ss >= 70:
        score += 15
        reasons.append(f"max_structure_score={max_ss} (high quality)")
    elif max_ss >= 55:
        score += 8
        reasons.append(f"max_structure_score={max_ss}")
    if avg_ss >= 40:
        score += 10
        reasons.append(f"avg_structure_score={avg_ss:.0f}")

    # EMA ribbon quality
    bull_stack = ep.get("bull_stack_days_pre") or 0
    if bull_stack >= 8:
        score += 10
        reasons.append(f"bull_stack_days={bull_stack}")
    elif bull_stack >= 4:
        score += 5

    days_above_ema50 = ep.get("days_above_ema50_pre") or 0
    if days_above_ema50 >= 12:
        score += 8
        reasons.append(f"days_above_ema50={days_above_ema50}")
    elif days_above_ema50 >= 7:
        score += 4

    # Dry-up (quiet before storm)
    dryup = ep.get("dryup_day_count_pre") or 0
    if 10 <= dryup <= 25:
        score += 8
        reasons.append(f"dryup_days={dryup} (sweet spot)")
    elif dryup >= 5:
        score += 4
        reasons.append(f"dryup_days={dryup}")
    elif dryup >= 2:
        score += 2

    # Compression
    compression_days = ep.get("compression_days_pre") or 0
    if compression_days >= 6:
        score += 6
        reasons.append(f"compression_days={compression_days}")
    elif compression_days >= 3:
        score += 3

    # D-confluence
    d_days = ep.get("d_confluence_day_count_pre") or 0
    if d_days >= 5:
        score += 6
        reasons.append(f"d_confluence_days={d_days}")
    elif d_days >= 2:
        score += 3

    # Structure phases
    if ep.get("had_triggered_structure_pre"):
        score += 6
        reasons.append("had_triggered_structure")
    if ep.get("had_early_structure_pre"):
        score += 5
        reasons.append("had_early_structure")
    if ep.get("had_confirmed_structure_pre"):
        score += 8
        reasons.append("had_confirmed_structure")

    # Accumulation / Wyckoff
    if ep.get("had_spring_test_lps"):
        score += 5
        reasons.append("had_spring_test_lps")
    if ep.get("had_accumulation_like"):
        score += 5
        reasons.append("had_accumulation_like")

    # Volume expansion after dry-up
    acc_days = ep.get("accumulation_like_day_count") or 0
    if acc_days >= 3:
        score += 5
        reasons.append(f"accumulation_like_days={acc_days}")

    # EMA50 reclaim events
    ema50_reclaims = ep.get("ema50_reclaim_count_pre") or 0
    if ema50_reclaims >= 2:
        score += 5
        reasons.append(f"ema50_reclaim_count={ema50_reclaims}")

    # ── Penalties ─────────────────────────────────────────────────────────────

    # Split artifact (hard penalty — already caught above, this is belt-and-suspenders)
    if ep.get("split_artifact_risk"):
        score -= 40
        risk_flags.append("SPLIT_ARTIFACT_RISK")

    # Poor structure
    if max_ss < 48:
        score -= 10
        risk_flags.append(f"low_structure_score={max_ss}")

    # No scanner pressure
    if bc_days <= 1 and (ep.get("watch_day_count_pre") or 0) <= 1:
        score -= 10
        risk_flags.append("no_scanner_pressure")

    # Bad structure phase (broken/impulse_only with low score)
    best_phase = ep.get("best_structure_phase_pre") or ""
    if best_phase in ("BROKEN_STRUCTURE", "IMPULSE_ONLY") and max_ss < 58:
        score -= 8
        risk_flags.append(f"broken_or_impulse_structure({best_phase})")

    # D-confluence quality: only poor/toxic group detected
    d_family = ep.get("dominant_d_confluence_family_pre") or ""
    if d_family in ("TOXIC", "POOR") and d_days > 0:
        score -= 8
        risk_flags.append(f"toxic_d_confluence_only({d_family})")

    # No dry-up AND no compression = no base building
    if dryup < 2 and compression_days < 3:
        score -= 6
        risk_flags.append("no_dryup_or_compression")

    # Dollar volume too low (not tradable)
    med_dv = ep.get("median_dollar_volume_pre") or 0
    if med_dv > 0 and med_dv < 200_000:
        score -= 6
        risk_flags.append(f"low_dollar_volume={med_dv:.0f}")

    # IMPORTANT: High expansion risk is NOT an automatic reject for Pump Watch
    # It is only a regime marker. For BUY routing it IS a hard avoid.
    exp_risk = ep.get("max_expansion_timing_risk_pre") or ""
    if exp_risk == "HIGH":
        risk_flags.append("high_expansion_risk_marker (not a reject for pump_watch)")
        # No score penalty — just flag it

    # ── Matched seed patterns ─────────────────────────────────────────────────
    from replay.pattern_miner import _seed_patterns
    matched_patterns: list[str] = []
    try:
        for pdef in _seed_patterns():
            cond = pdef.get("condition")
            if cond and cond(ep):
                matched_patterns.append(pdef["signal_id"])
    except Exception:
        pass

    # ── Label ─────────────────────────────────────────────────────────────────
    score = max(-100, min(score, 100))

    if score >= THRESHOLD_HIGH:
        label = LABEL_HIGH
    elif score >= THRESHOLD_MEDIUM:
        label = LABEL_MEDIUM
    elif score >= THRESHOLD_SPECULATIVE:
        label = LABEL_SPECULATIVE
    else:
        label = LABEL_IGNORE

    # ── Confidence ────────────────────────────────────────────────────────────
    n_reasons  = len(reasons)
    n_riskflags = len([f for f in risk_flags if "marker" not in f])
    if n_reasons >= 5 and n_riskflags == 0:
        confidence = "HIGH"
    elif n_reasons >= 3 and n_riskflags <= 1:
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    diag = _apply_diagnostic_labels(ep, label, score, risk_flags)

    # Rescue routing: PUMP_IGNORE with raw strength → PUMP_SPECULATIVE
    if DIAG_MISSING_STRUCTURE_RESCUE in diag["pump_watch_diagnostic_labels"] and label == LABEL_IGNORE:
        label = LABEL_SPECULATIVE
        risk_flags.append("structure_fields_missing")

    # No-scanner raw strength rescue: PUMP_IGNORE → PUMP_SPECULATIVE (score >= 15)
    if (DIAG_NO_SCANNER_RAW_STRENGTH_RESCUE in diag["pump_watch_diagnostic_labels"]
            and label == LABEL_IGNORE and score >= 15):
        label = LABEL_SPECULATIVE
        risk_flags.append("no_scanner_pressure_but_raw_strength")

    # Reverse split regime: cap confidence at MEDIUM for recent splits
    split_ctx = ep.get("split_context") or ""
    if DIAG_REVERSE_SPLIT_REGIME in diag["pump_watch_diagnostic_labels"]:
        risk_flags.append("reverse_split_regime_requires_separate_model")
        if split_ctx == "RECENT_REVERSE_SPLIT" and confidence == "HIGH":
            confidence = "MEDIUM"

    return {
        "pump_watch_score":           score,
        "pump_watch_label":           label,
        "pump_watch_reasons":         reasons,
        "pump_watch_risk_flags":      risk_flags,
        "pump_watch_pattern_ids":     matched_patterns,
        "pump_watch_split_context":   ep.get("split_context") or "NO_SPLIT",
        "pump_watch_confidence":      confidence,
        "pump_watch_diagnostic_labels": diag["pump_watch_diagnostic_labels"],
        "pump_watch_pattern_id":      diag["pump_watch_pattern_id"],
        "pump_watch_rescue_reason":   diag["pump_watch_rescue_reason"],
    }


def score_episodes(episodes: list[dict]) -> list[dict]:
    """
    Score a list of episode dicts. Returns augmented copies with pump_watch fields.
    """
    results: list[dict] = []
    for ep in episodes:
        pw = compute_pump_watch_score(ep)
        results.append({**ep, **pw})
    return results


def _parse_diag_labels(val) -> list:
    """Normalize pump_watch_diagnostic_labels from DB (JSON str) or in-memory (list)."""
    if val is None:
        return []
    if isinstance(val, list):
        return val
    try:
        result = json.loads(val)
        return result if isinstance(result, list) else []
    except Exception:
        return []


def summarize_pump_watch_distribution(scored_episodes: list[dict]) -> dict:
    """
    Build a summary of pump watch label distribution by group_type.
    Handles both in-memory scored episodes (lists) and DB-loaded rows (JSON strings).
    """
    labels = [LABEL_HIGH, LABEL_MEDIUM, LABEL_SPECULATIVE, LABEL_IGNORE]
    group_types = ["4x_pump", "false_positive", "normal_winner"]

    distribution: dict = {}
    for gt in group_types:
        rows = [ep for ep in scored_episodes if ep.get("group_type") == gt]
        distribution[gt] = {
            lbl: sum(1 for ep in rows if ep.get("pump_watch_label") == lbl)
            for lbl in labels
        }
        distribution[gt]["total"] = len(rows)
        if rows:
            scores = [ep.get("pump_watch_score") or 0 for ep in rows]
            distribution[gt]["median_score"] = sorted(scores)[len(scores)//2]

    by_label: dict = {}
    for lbl in labels:
        matching = [ep for ep in scored_episodes if ep.get("pump_watch_label") == lbl]
        by_label[lbl] = {
            "total":                len(matching),
            "4x_pump_count":        sum(1 for ep in matching if ep.get("group_type") == "4x_pump"),
            "false_positive_count": sum(1 for ep in matching if ep.get("group_type") == "false_positive"),
            "normal_winner_count":  sum(1 for ep in matching if ep.get("group_type") == "normal_winner"),
        }
        if by_label[lbl]["total"] > 0:
            by_label[lbl]["4x_pump_rate"] = round(
                by_label[lbl]["4x_pump_count"] / by_label[lbl]["total"], 3
            )
            by_label[lbl]["false_positive_rate"] = round(
                by_label[lbl]["false_positive_count"] / by_label[lbl]["total"], 3
            )

    # Parse diagnostic labels from DB (JSON string) or in-memory (list)
    diagnostic_label_counts = {
        diag_lbl: sum(
            1 for ep in scored_episodes
            if diag_lbl in _parse_diag_labels(ep.get("pump_watch_diagnostic_labels"))
        )
        for diag_lbl in _ALL_DIAG_LABELS
    }

    return {
        "by_group_type":           distribution,
        "by_label":                by_label,
        "diagnostic_label_counts": diagnostic_label_counts,
    }


def compute_pump_watch_calibration(scored_episodes: list[dict]) -> dict:
    """
    Compute calibration metrics for pump watch labels.

    Returns flags for known miscalibration patterns observed in run 137:
      - high_underperforms_medium: HIGH label has lower 4x rate than MEDIUM
      - high_fp_rate_gt_4x_rate:   HIGH false_positive_rate > HIGH 4x_rate
      - ignore_contains_many_4x:   PUMP_IGNORE 4x_rate > 0.20

    Does NOT change scoring. For diagnostic/reporting purposes only.
    """
    if not scored_episodes:
        return {}

    labels = [LABEL_HIGH, LABEL_MEDIUM, LABEL_SPECULATIVE, LABEL_IGNORE]
    by_label: dict = {}
    for lbl in labels:
        matching = [ep for ep in scored_episodes if ep.get("pump_watch_label") == lbl]
        total = len(matching)
        if total == 0:
            by_label[lbl] = {"total": 0}
            continue
        n_4x = sum(1 for ep in matching if ep.get("group_type") == "4x_pump")
        n_fp = sum(1 for ep in matching if ep.get("group_type") == "false_positive")
        n_nw = sum(1 for ep in matching if ep.get("group_type") == "normal_winner")
        scores = sorted([ep.get("pump_watch_score") or 0 for ep in matching])
        by_label[lbl] = {
            "total":             total,
            "4x_pump_count":     n_4x,
            "false_positive_count": n_fp,
            "normal_winner_count":  n_nw,
            "4x_rate":           round(n_4x / total, 3),
            "false_positive_rate": round(n_fp / total, 3),
            "normal_winner_rate": round(n_nw / total, 3),
            "median_score":      scores[len(scores) // 2],
        }

    high  = by_label.get(LABEL_HIGH,    {})
    med   = by_label.get(LABEL_MEDIUM,  {})
    spec  = by_label.get(LABEL_SPECULATIVE, {})
    ign   = by_label.get(LABEL_IGNORE,  {})

    high_4x = high.get("4x_rate", 0.0)
    med_4x  = med.get("4x_rate",  0.0)
    high_fp = high.get("false_positive_rate", 0.0)
    ign_4x  = ign.get("4x_rate",  0.0)

    high_underperforms_medium  = bool(high.get("total", 0) > 0 and med.get("total", 0) > 0 and high_4x < med_4x)
    high_fp_rate_gt_4x_rate    = bool(high.get("total", 0) > 0 and high_fp > high_4x)
    ignore_contains_many_4x    = bool(ign.get("total",  0) > 0 and ign_4x > 0.20)

    warnings: list[str] = []
    if high_underperforms_medium:
        warnings.append(
            f"PUMP_WATCH_HIGH 4x_rate ({high_4x:.1%}) < PUMP_WATCH_MEDIUM 4x_rate ({med_4x:.1%}). "
            "HIGH label is not the best predictor."
        )
    if high_fp_rate_gt_4x_rate:
        warnings.append(
            f"PUMP_WATCH_HIGH false_positive_rate ({high_fp:.1%}) > 4x_rate ({high_4x:.1%}). "
            "More false positives than true pump candidates in HIGH bucket."
        )
    if ignore_contains_many_4x:
        warnings.append(
            f"PUMP_IGNORE 4x_rate ({ign_4x:.1%}) > 20%. "
            "Significant 4x pump events are being ignored — scoring may need recalibration."
        )

    return {
        "by_label":                   by_label,
        "high_underperforms_medium":  high_underperforms_medium,
        "high_fp_rate_gt_4x_rate":    high_fp_rate_gt_4x_rate,
        "ignore_contains_many_4x":    ignore_contains_many_4x,
        "warnings":                   warnings,
        "recommended_next_action": (
            "Do not use PUMP_WATCH_HIGH as final selector until recalibrated."
            if high_underperforms_medium or high_fp_rate_gt_4x_rate else
            "Calibration looks reasonable — monitor with more runs."
        ),
    }
