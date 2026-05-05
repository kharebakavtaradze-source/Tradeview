"""
Pattern Miner — finds recurring bar/sequence patterns before 4x pumps.

Operates on a missed_pump_dataset (from missed_pump_dataset.py).

For each seed pattern definition, computes per-group counts,
lift vs false_positive, precision/recall estimates, and forward return stats.

Output: list of PatternCandidate dicts, one per pattern.

Statuses:
  EXPERIMENTAL      — min thresholds met (count_all_4x >= 8, lift >= 1.5)
  EXPERIMENTAL_RARE — lower count (count >= 4) but high lift (>= 2.0)
  RESEARCH_ONLY     — below thresholds but non-zero and worth tracking
  REJECT            — lift < 1.0 or no signal

Anti-leakage: pattern conditions use only PRE-window features.
              forward_return fields are passed from external context,
              not computed from group_type.
"""

import logging
import math
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_TINY = 1e-9


# ── Thresholds ────────────────────────────────────────────────────────────────

STANDARD_MIN_COUNT_4X    = 8
STANDARD_MIN_LIFT        = 1.5

RARE_MIN_COUNT_4X        = 4
RARE_MIN_LIFT            = 2.0


# ── Pattern condition types ───────────────────────────────────────────────────

Condition = Callable[[dict], bool]


def _gt(key: str, threshold: float) -> Condition:
    def check(pf: dict) -> bool:
        v = pf.get(key)
        return v is not None and v > threshold
    return check


def _gte(key: str, threshold: float) -> Condition:
    def check(pf: dict) -> bool:
        v = pf.get(key)
        return v is not None and v >= threshold
    return check


def _lt(key: str, threshold: float) -> Condition:
    def check(pf: dict) -> bool:
        v = pf.get(key)
        return v is not None and v < threshold
    return check


def _bool_true(key: str) -> Condition:
    def check(pf: dict) -> bool:
        return bool(pf.get(key))
    return check


def _eq(key: str, value: Any) -> Condition:
    def check(pf: dict) -> bool:
        return pf.get(key) == value
    return check


def _in(key: str, values: list) -> Condition:
    def check(pf: dict) -> bool:
        return pf.get(key) in values
    return check


def _between(key: str, lo: float, hi: float) -> Condition:
    def check(pf: dict) -> bool:
        v = pf.get(key)
        return v is not None and lo <= v <= hi
    return check


def _all(*conditions: Condition) -> Condition:
    def check(pf: dict) -> bool:
        return all(c(pf) for c in conditions)
    return check


def _any(*conditions: Condition) -> Condition:
    def check(pf: dict) -> bool:
        return any(c(pf) for c in conditions)
    return check


# ── Seed pattern definitions ──────────────────────────────────────────────────

def _seed_patterns() -> list[dict]:
    """
    Return the full list of seed pattern definitions.

    Each entry:
      signal_id   : unique ID for the pattern
      family      : pattern family (L, G, E, D, V, C, S, P)
      description : human-readable definition
      condition   : callable(pre_features: dict) -> bool
      intended_use: PUMP_WATCH | WATCH_SUPPORT | RESEARCH_ONLY
      machine_conditions: list of string descriptions
    """

    patterns: list[dict] = []

    # ── L-family: Liquidity / wick / absorption / reclaim ────────────────────

    patterns.append({
        "signal_id":   "DISC_LIQ_RECLAIM_001",
        "family":      "L",
        "description": "Dry-up reclaim bar: low-volume bars then reclaim of prior close with lower wick",
        "intended_use": "PUMP_WATCH",
        "machine_conditions": [
            "dryup_day_count_pre >= 2",
            "reclaim_bar_count_pre >= 1",
            "avg_lower_wick_pct >= 0.25 (inferred)",
        ],
        "condition": _all(
            _gte("dryup_day_count_pre", 2),
            _gte("reclaim_bar_count_pre", 1),
        ),
    })

    patterns.append({
        "signal_id":   "DISC_LIQ_SPRING_EMA50_001",
        "family":      "L",
        "description": "EMA50 spring reclaim: low dips below EMA50 then close recovers above, with prior dry-up",
        "intended_use": "PUMP_WATCH",
        "machine_conditions": [
            "ema50_reclaim_count_pre >= 1",
            "dryup_day_count_pre >= 2",
        ],
        "condition": _all(
            _gte("ema50_reclaim_count_pre", 1),
            _gte("dryup_day_count_pre", 2),
        ),
    })

    patterns.append({
        "signal_id":   "DISC_LIQ_ABSORPTION_001",
        "family":      "L",
        "description": "Repeated accumulation-like days: high lower wick + close mid-high on below-avg volume",
        "intended_use": "PUMP_WATCH",
        "machine_conditions": [
            "had_accumulation_like == True",
            "accumulation_like_day_count >= 3",
            "dryup_day_count_pre >= 3",
        ],
        "condition": _all(
            _bool_true("had_accumulation_like"),
            _gte("accumulation_like_day_count", 3),
            _gte("dryup_day_count_pre", 3),
        ),
    })

    # ── G-family: Gap behavior ─────────────────────────────────────────────────

    patterns.append({
        "signal_id":   "DISC_GAP_SHAKEOUT_001",
        "family":      "G",
        "description": "Gap-down shakeout reclaim: gap down then same-day recovery above prior close with lower wick",
        "intended_use": "PUMP_WATCH",
        "machine_conditions": [
            "reclaim_bar_count_pre >= 1",
            "dryup_day_count_pre >= 1",
            "had_spring_test_lps == True (or high reclaim count)",
        ],
        "condition": _all(
            _bool_true("had_spring_test_lps"),
            _gte("reclaim_bar_count_pre", 1),
        ),
    })

    patterns.append({
        "signal_id":   "DISC_GAP_HOLD_DRYUP_001",
        "family":      "G",
        "description": "Gap-up hold after dry-up: gap up on volume after period of quiet accumulation",
        "intended_use": "PUMP_WATCH",
        "machine_conditions": [
            "dryup_day_count_pre >= 3",
            "abnormal_volume_day_count_pre >= 1",
            "had_accumulation_like == True",
        ],
        "condition": _all(
            _gte("dryup_day_count_pre", 3),
            _gte("abnormal_volume_day_count_pre", 1),
        ),
    })

    # ── E-family: EMA crossing / reclaim ──────────────────────────────────────

    patterns.append({
        "signal_id":   "DISC_EMA_CLUSTER_RECLAIM_001",
        "family":      "E",
        "description": "EMA cluster reclaim: close crosses up through 2+ EMAs in one bar on above-avg volume",
        "intended_use": "PUMP_WATCH",
        "machine_conditions": [
            "ema50_reclaim_count_pre >= 2",
            "bull_stack_days_pre >= 3",
        ],
        "condition": _all(
            _gte("ema50_reclaim_count_pre", 2),
            _gte("bull_stack_days_pre", 3),
        ),
    })

    patterns.append({
        "signal_id":   "DISC_EMA_BULL_STACK_001",
        "family":      "E",
        "description": "Extended EMA bull stack: price held above EMA50 for 10+ days pre-breakout",
        "intended_use": "WATCH_SUPPORT",
        "machine_conditions": [
            "days_above_ema50_pre >= 10",
            "bull_stack_days_pre >= 8",
        ],
        "condition": _all(
            _gte("days_above_ema50_pre", 10),
            _gte("bull_stack_days_pre", 8),
        ),
    })

    # ── D-family: Delta / volume imbalance ────────────────────────────────────

    patterns.append({
        "signal_id":   "DISC_D_CONF_CLUSTER_001",
        "family":      "D",
        "description": "D-confluence cluster: 4+ D-confluence days in pre-window with good structure score",
        "intended_use": "WATCH_SUPPORT",
        "machine_conditions": [
            "d_confluence_day_count_pre >= 4",
            "had_d_confluence_pre == True",
            "max_structure_score_pre >= 55",
        ],
        "condition": _all(
            _gte("d_confluence_day_count_pre", 4),
            _bool_true("had_d_confluence_pre"),
            _gte("max_structure_score_pre", 55),
        ),
    })

    # ── V-family: Volume / dollar volume / dry-up / anomaly ──────────────────

    patterns.append({
        "signal_id":   "DISC_VOLUME_DRYUP_EXPAND_001",
        "family":      "V",
        "description": "Dry-up then volume expansion: 5+ dry-up days followed by abnormal volume",
        "intended_use": "PUMP_WATCH",
        "machine_conditions": [
            "dryup_day_count_pre >= 5",
            "abnormal_volume_day_count_pre >= 1",
        ],
        "condition": _all(
            _gte("dryup_day_count_pre", 5),
            _gte("abnormal_volume_day_count_pre", 1),
        ),
    })

    patterns.append({
        "signal_id":   "DISC_VOLUME_DRYUP_DEEP_001",
        "family":      "V",
        "description": "Deep dry-up period: 10+ days of below-avg volume in pre-window (quiet accumulation)",
        "intended_use": "PUMP_WATCH",
        "machine_conditions": [
            "dryup_day_count_pre >= 10",
        ],
        "condition": _gte("dryup_day_count_pre", 10),
    })

    patterns.append({
        "signal_id":   "DISC_VOLUME_EXTREME_ANOMALY_001",
        "family":      "V",
        "description": "Extreme volume spike (vol_z > 4) in pre-window with later compression",
        "intended_use": "RESEARCH_ONLY",
        "machine_conditions": [
            "extreme_anomaly_day_count_pre >= 1",
            "dryup_day_count_pre >= 3",
        ],
        "condition": _all(
            _gte("extreme_anomaly_day_count_pre", 1),
            _gte("dryup_day_count_pre", 3),
        ),
    })

    # ── C-family: Compression / volatility regime ─────────────────────────────

    patterns.append({
        "signal_id":   "DISC_COMPRESSION_LONG_001",
        "family":      "C",
        "description": "Extended compression: 8+ compression days in pre-window (BB squeeze or ATR contraction)",
        "intended_use": "PUMP_WATCH",
        "machine_conditions": [
            "compression_days_pre >= 8",
            "had_compression == True",
        ],
        "condition": _all(
            _gte("compression_days_pre", 8),
            _bool_true("had_compression"),
        ),
    })

    patterns.append({
        "signal_id":   "DISC_COMPRESSION_ATR_001",
        "family":      "C",
        "description": "ATR contraction with dry-up: price range contracting while volume dries up",
        "intended_use": "PUMP_WATCH",
        "machine_conditions": [
            "atr_contraction_days_pre >= 5",
            "dryup_day_count_pre >= 3",
        ],
        "condition": _all(
            _gte("atr_contraction_days_pre", 5),
            _gte("dryup_day_count_pre", 3),
        ),
    })

    # ── S-family: Split / reverse-split regime ────────────────────────────────

    patterns.append({
        "signal_id":   "DISC_SPLIT_REGIME_RS_RECENT_001",
        "family":      "S",
        "description": "Recent reverse split speculative regime: RS within 15d + accumulation evidence",
        "intended_use": "RESEARCH_ONLY",  # keep separate from clean pump model
        "machine_conditions": [
            "reverse_split_0_5d_before_breakout OR reverse_split_6_15d_before_breakout",
            "split_artifact_risk == False",
            "dryup_day_count_pre >= 3",
        ],
        "condition": _all(
            _any(
                _bool_true("reverse_split_0_5d_before_breakout"),
                _bool_true("reverse_split_6_15d_before_breakout"),
            ),
            _gte("dryup_day_count_pre", 3),
        ),
    })

    # ── P-family: Composite discovered pump patterns ──────────────────────────

    patterns.append({
        "signal_id":   "DISC_PUMP_COMPOSITE_BUY_PRESSURE_001",
        "family":      "P",
        "description": "Repeated buy pressure: 6+ BUY_CANDIDATE days in pre-window (key separator per run 98)",
        "intended_use": "PUMP_WATCH",
        "machine_conditions": [
            "buy_candidate_day_count_pre >= 6",
        ],
        "condition": _gte("buy_candidate_day_count_pre", 6),
    })

    patterns.append({
        "signal_id":   "DISC_PUMP_COMPOSITE_BUY_MOD_001",
        "family":      "P",
        "description": "Moderate buy pressure: 4+ BUY_CANDIDATE days in pre-window",
        "intended_use": "PUMP_WATCH",
        "machine_conditions": [
            "buy_candidate_day_count_pre >= 4",
        ],
        "condition": _gte("buy_candidate_day_count_pre", 4),
    })

    patterns.append({
        "signal_id":   "DISC_PUMP_COMPOSITE_STRUCTURE_HIGH_001",
        "family":      "P",
        "description": "Max structure spike: max_structure_score >= 70 with confirmed or triggered phase",
        "intended_use": "PUMP_WATCH",
        "machine_conditions": [
            "max_structure_score_pre >= 70",
            "had_confirmed_structure_pre OR had_triggered_structure_pre",
        ],
        "condition": _all(
            _gte("max_structure_score_pre", 70),
            _any(
                _bool_true("had_confirmed_structure_pre"),
                _bool_true("had_triggered_structure_pre"),
            ),
        ),
    })

    patterns.append({
        "signal_id":   "DISC_PUMP_COMPOSITE_WATCHLIST_001",
        "family":      "P",
        "description": "Extended watch pressure: watch_day_count >= 5 without BUY_CANDIDATE",
        "intended_use": "PUMP_WATCH",
        "machine_conditions": [
            "watch_day_count_pre >= 5",
            "buy_candidate_day_count_pre <= 1",
        ],
        "condition": _all(
            _gte("watch_day_count_pre", 5),
            _lt("buy_candidate_day_count_pre", 2),
        ),
    })

    patterns.append({
        "signal_id":   "DISC_PUMP_COMPOSITE_SETUP_PRESSURE_001",
        "family":      "P",
        "description": "Setup pressure: valid_setup_days >= 20 (many setup signals but no trigger)",
        "intended_use": "PUMP_WATCH",
        "machine_conditions": [
            "valid_setup_days_pre >= 20",
        ],
        "condition": _gte("valid_setup_days_pre", 20),
    })

    patterns.append({
        "signal_id":   "DISC_PUMP_COMPOSITE_ACC_SPRING_001",
        "family":      "P",
        "description": "Accumulation + spring: had_accumulation_like + had_spring_test_lps + compression",
        "intended_use": "PUMP_WATCH",
        "machine_conditions": [
            "had_accumulation_like == True",
            "had_spring_test_lps == True",
            "compression_days_pre >= 5",
        ],
        "condition": _all(
            _bool_true("had_accumulation_like"),
            _bool_true("had_spring_test_lps"),
            _gte("compression_days_pre", 5),
        ),
    })

    patterns.append({
        "signal_id":   "DISC_PUMP_COMPOSITE_FULL_001",
        "family":      "P",
        "description": "Full convergence: buy pressure + structure + dry-up + compression",
        "intended_use": "PUMP_WATCH",
        "machine_conditions": [
            "buy_candidate_day_count_pre >= 4",
            "max_structure_score_pre >= 58",
            "dryup_day_count_pre >= 5",
            "had_compression == True",
        ],
        "condition": _all(
            _gte("buy_candidate_day_count_pre", 4),
            _gte("max_structure_score_pre", 58),
            _gte("dryup_day_count_pre", 5),
            _bool_true("had_compression"),
        ),
    })

    # Expand: avoid → pump (missed because avoid but still pumped)
    patterns.append({
        "signal_id":   "DISC_PUMP_AVOID_PUMP_001",
        "family":      "P",
        "description": "Avoid-then-pump: scanner routed AVOID but stock still pumped 4x",
        "intended_use": "RESEARCH_ONLY",
        "machine_conditions": [
            "had_np_avoid_pre == True",
            "had_d_confluence_pre == True OR had_accumulation_like == True",
        ],
        "condition": _all(
            _bool_true("had_np_avoid_pre"),
            _any(
                _bool_true("had_d_confluence_pre"),
                _bool_true("had_accumulation_like"),
            ),
        ),
    })

    return patterns


# ── Statistics computation ────────────────────────────────────────────────────

def _safe_pct(num: int, denom: int) -> Optional[float]:
    if denom == 0:
        return None
    return round(num / denom, 4)


def _lift(rate_signal: Optional[float], rate_baseline: Optional[float]) -> Optional[float]:
    if rate_signal is None or rate_baseline is None or rate_baseline < _TINY:
        return None
    return round(rate_signal / rate_baseline, 3)


def _median(vals: list) -> Optional[float]:
    clean = sorted(v for v in vals if v is not None)
    if not clean:
        return None
    m = len(clean) // 2
    return float(clean[m]) if len(clean) % 2 == 1 else (clean[m-1] + clean[m]) / 2


def _mean(vals: list) -> Optional[float]:
    clean = [v for v in vals if v is not None]
    if not clean:
        return None
    return round(sum(clean) / len(clean), 4)


def _evaluate_pattern(
    pattern_def: dict,
    dataset: dict,
) -> dict:
    """
    Evaluate one pattern definition against all groups in the dataset.
    Returns a PatternCandidate dict.
    """
    cond     = pattern_def["condition"]
    groups   = ["missed_4x_pump", "detected_4x_pump", "false_positive", "normal_winner"]
    counts   = {}
    matching = {}

    for grp in groups:
        rows = dataset.get(grp) or []
        hits = [r for r in rows if cond(r.get("pre_features") or {})]
        counts[grp]   = len(rows)
        matching[grp] = len(hits)

    count_missed   = matching["missed_4x_pump"]
    count_detected = matching["detected_4x_pump"]
    count_fp       = matching["false_positive"]
    count_nw       = matching["normal_winner"]
    count_all_4x   = count_missed + count_detected

    total_missed   = counts["missed_4x_pump"]
    total_detected = counts["detected_4x_pump"]
    total_fp       = counts["false_positive"]
    total_nw       = counts["normal_winner"]
    total_all_4x   = total_missed + total_detected

    rate_all_4x = _safe_pct(count_all_4x, total_all_4x)
    rate_fp     = _safe_pct(count_fp,     total_fp)
    rate_nw     = _safe_pct(count_nw,     total_nw)

    lift_vs_fp  = _lift(rate_all_4x, rate_fp)
    lift_vs_nw  = _lift(rate_all_4x, rate_nw)

    # Precision: of everything matching, what fraction is 4x_pump?
    all_matching = count_all_4x + count_fp + count_nw
    precision    = _safe_pct(count_all_4x, all_matching)

    # Recall: of all 4x_pumps, what fraction does pattern catch?
    recall_missed   = _safe_pct(count_missed,   total_missed)   # of missed pumps
    recall_all_4x   = _safe_pct(count_all_4x,   total_all_4x)  # of all pumps

    false_positive_rate = _safe_pct(count_fp, total_fp) if total_fp > 0 else None

    # Split artifact exposure
    art_rows = dataset.get("split_artifact") or []
    count_art = sum(1 for r in art_rows if cond(r.get("pre_features") or {}))
    split_artifact_exposure = _safe_pct(count_art, len(art_rows)) if art_rows else None

    # Reverse split exposure (within the 4x pump group)
    rs_rows = [
        r for grp in ["missed_4x_pump", "detected_4x_pump"]
        for r in dataset.get(grp) or []
        if r.get("split_context") in ("RECENT_REVERSE_SPLIT", "OLD_REVERSE_SPLIT")
    ]
    count_rs_hit = sum(1 for r in rs_rows if cond(r.get("pre_features") or {}))
    reverse_split_exposure = _safe_pct(count_rs_hit, count_all_4x) if count_all_4x > 0 else None

    # Determine status
    status: str
    if count_all_4x >= STANDARD_MIN_COUNT_4X and (lift_vs_fp or 0) >= STANDARD_MIN_LIFT:
        status = "EXPERIMENTAL"
    elif count_all_4x >= RARE_MIN_COUNT_4X and (lift_vs_fp or 0) >= RARE_MIN_LIFT:
        status = "EXPERIMENTAL_RARE"
    elif count_all_4x >= 2 and (lift_vs_fp or 0) >= 1.0:
        status = "RESEARCH_ONLY"
    else:
        status = "REJECT"

    recommendation: str
    if status == "EXPERIMENTAL" and false_positive_rate is not None and false_positive_rate < 0.60:
        recommendation = "add_to_pump_watch"
    elif status == "EXPERIMENTAL_RARE":
        recommendation = "needs_more_data"
    elif status == "RESEARCH_ONLY":
        recommendation = "keep_research"
    elif count_art > count_all_4x:
        recommendation = "split_artifact_only"
    else:
        recommendation = "reject"

    return {
        "signal_id":              pattern_def["signal_id"],
        "family":                 pattern_def["family"],
        "description":            pattern_def["description"],
        "intended_use":           pattern_def.get("intended_use", "RESEARCH_ONLY"),
        "machine_conditions":     pattern_def.get("machine_conditions", []),
        "status":                 status,
        "recommendation":         recommendation,
        # Counts
        "count_missed_4x":        count_missed,
        "count_detected_4x":      count_detected,
        "count_all_4x":           count_all_4x,
        "count_false_positive":   count_fp,
        "count_normal_winner":    count_nw,
        "count_split_artifact":   count_art,
        # Rates
        "rate_all_4x":            rate_all_4x,
        "rate_false_positive":    rate_fp,
        "rate_normal_winner":     rate_nw,
        # Lift
        "lift_vs_false_positive": lift_vs_fp,
        "lift_vs_normal_winner":  lift_vs_nw,
        # Precision / recall
        "precision_estimate":     precision,
        "recall_missed_4x":       recall_missed,
        "recall_all_4x":          recall_all_4x,
        "false_positive_rate":    false_positive_rate,
        # Exposure
        "split_artifact_exposure":   split_artifact_exposure,
        "reverse_split_exposure":    reverse_split_exposure,
    }


# ── Main miner ────────────────────────────────────────────────────────────────

def mine_patterns(
    dataset: dict,
    custom_patterns: Optional[list[dict]] = None,
) -> list[dict]:
    """
    Run all seed patterns (+ any custom_patterns) against the dataset.
    Returns list of PatternCandidate dicts, sorted by status then lift.

    The returned list excludes patterns where count_all_4x == 0.
    """
    all_patterns = _seed_patterns()
    if custom_patterns:
        all_patterns.extend(custom_patterns)

    results: list[dict] = []
    for pdef in all_patterns:
        try:
            result = _evaluate_pattern(pdef, dataset)
            if result["count_all_4x"] > 0 or result["count_false_positive"] > 0:
                results.append(result)
        except Exception as exc:
            logger.warning(f"Pattern eval error [{pdef.get('signal_id')}]: {exc}")

    # Sort: status priority, then lift descending
    _STATUS_ORDER = {
        "EXPERIMENTAL": 0, "EXPERIMENTAL_RARE": 1,
        "RESEARCH_ONLY": 2, "REJECT": 3,
    }
    results.sort(key=lambda r: (
        _STATUS_ORDER.get(r["status"], 9),
        -(r["lift_vs_false_positive"] or 0),
    ))

    logger.info(
        f"mine_patterns: {len(results)} patterns evaluated | "
        f"experimental={sum(1 for r in results if r['status']=='EXPERIMENTAL')} | "
        f"rare={sum(1 for r in results if r['status']=='EXPERIMENTAL_RARE')} | "
        f"reject={sum(1 for r in results if r['status']=='REJECT')}"
    )
    return results


# ── Feature separator analysis ────────────────────────────────────────────────

def compute_feature_separability(
    dataset: dict,
    feature_keys: Optional[list[str]] = None,
) -> list[dict]:
    """
    For each numeric episode feature, compute group medians and lift vs false_positive.
    Useful for identifying which raw features most separate 4x_pump from false_positive.
    """
    if feature_keys is None:
        feature_keys = [
            "buy_candidate_day_count_pre", "watch_day_count_pre", "avoid_day_count_pre",
            "dryup_day_count_pre", "compression_days_pre", "atr_contraction_days_pre",
            "max_structure_score_pre", "avg_structure_score_pre",
            "d_confluence_day_count_pre", "bull_stack_days_pre",
            "days_above_ema50_pre", "ema50_reclaim_count_pre",
            "accumulation_like_day_count", "reclaim_bar_count_pre",
            "max_volume_anomaly_pre", "abnormal_volume_day_count_pre",
            "extreme_anomaly_day_count_pre", "high_expansion_risk_day_count_pre",
            "valid_setup_days_pre", "valid_trigger_days_pre",
        ]

    def _group_vals(group_name: str, key: str) -> list:
        rows = dataset.get(group_name) or []
        return [r["pre_features"].get(key) for r in rows if r["pre_features"].get(key) is not None]

    results: list[dict] = []
    for key in feature_keys:
        vals_4x = _group_vals("missed_4x_pump",   key) + _group_vals("detected_4x_pump", key)
        vals_fp = _group_vals("false_positive",    key)
        vals_nw = _group_vals("normal_winner",     key)

        m4x = _median(vals_4x)
        mfp = _median(vals_fp)
        mnw = _median(vals_nw)

        sep_fp = _lift(m4x, mfp) if m4x and mfp else None
        sep_nw = _lift(m4x, mnw) if m4x and mnw else None

        if sep_fp is not None and sep_fp >= 1.4:
            verdict = "BOOST"
        elif sep_fp is not None and sep_fp >= 1.15:
            verdict = "INCREASE"
        elif sep_fp is not None and sep_fp <= 0.7:
            verdict = "PENALIZE"
        else:
            verdict = "NEUTRAL"

        results.append({
            "feature":       key,
            "median_4x":     m4x,
            "median_fp":     mfp,
            "median_nw":     mnw,
            "sep_vs_fp":     sep_fp,
            "sep_vs_nw":     sep_nw,
            "n_4x":          len(vals_4x),
            "n_fp":          len(vals_fp),
            "verdict":       verdict,
        })

    results.sort(key=lambda r: -(r["sep_vs_fp"] or 0))
    return results


# ── Pattern family report ─────────────────────────────────────────────────────

def group_patterns_by_family(candidates: list[dict]) -> dict[str, list[dict]]:
    """Group pattern candidates by family code."""
    groups: dict[str, list[dict]] = {}
    for c in candidates:
        fam = c.get("family") or "UNKNOWN"
        groups.setdefault(fam, []).append(c)
    return groups
