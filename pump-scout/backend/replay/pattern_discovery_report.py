"""
Pattern Discovery Report Builder.

Generates a structured, human-readable discovery report from:
  - dataset_summary (from missed_pump_dataset)
  - pattern_candidates (from pattern_miner)
  - feature_separability (from pattern_miner)
  - pump_watch_distribution (from pump_watch_scorer)

Output is a dict of report sections suitable for serialization to JSON
and display in the frontend.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ── Label helpers ─────────────────────────────────────────────────────────────

_STATUS_EMOJI = {
    "EXPERIMENTAL":      "✅",
    "EXPERIMENTAL_RARE": "🔬",
    "RESEARCH_ONLY":     "📊",
    "REJECT":            "❌",
}

_VERDICT_EMOJI = {
    "BOOST":    "🚀",
    "INCREASE": "📈",
    "NEUTRAL":  "➡️",
    "PENALIZE": "⚠️",
}


def _fmt_rate(v: Optional[float], pct: bool = True) -> str:
    if v is None:
        return "—"
    return f"{v * 100:.1f}%" if pct else f"{v:.3f}"


def _fmt_lift(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v:.2f}×"


def _fmt_int(v) -> str:
    if v is None:
        return "—"
    return str(int(v))


# ── Report sections ───────────────────────────────────────────────────────────

def _section_dataset_summary(dataset_summary: dict) -> dict:
    s = dataset_summary
    miss_rate   = s.get("miss_rate")
    detect_rate = s.get("detection_rate")

    top_reasons = []
    for reason, count in (s.get("top_miss_reasons") or []):
        top_reasons.append({"reason": reason, "count": count})

    return {
        "title":       "Dataset Summary",
        "total":       s.get("total_episodes", 0),
        "missed_4x_pump_count":   s.get("missed_4x_pump_count", 0),
        "detected_4x_pump_count": s.get("detected_4x_pump_count", 0),
        "total_4x_pump_count":    s.get("total_4x_pump_count", 0),
        "false_positive_count":   s.get("false_positive_count", 0),
        "normal_winner_count":    s.get("normal_winner_count", 0),
        "split_artifact_count":   s.get("split_artifact_count", 0),
        "detection_rate":         f"{detect_rate * 100:.1f}%" if detect_rate is not None else "—",
        "miss_rate":              f"{miss_rate * 100:.1f}%" if miss_rate is not None else "—",
        "top_miss_reasons":       top_reasons,
        "narrative": (
            f"Out of {s.get('total_4x_pump_count', 0)} total 4× pumps, "
            f"the scanner detected {s.get('detected_4x_pump_count', 0)} "
            f"({detect_rate * 100:.1f}% detection rate) "
            f"and missed {s.get('missed_4x_pump_count', 0)} "
            f"({miss_rate * 100:.1f}% miss rate). "
            f"{s.get('split_artifact_count', 0)} episodes were flagged as split artifacts "
            "and excluded from clean training labels."
        ) if detect_rate is not None else "Insufficient data.",
    }


def _section_top_patterns(
    candidates: list[dict],
    status_filter: Optional[list[str]] = None,
    limit: int = 20,
) -> list[dict]:
    """Format top pattern candidates as report rows."""
    filtered = candidates
    if status_filter:
        filtered = [c for c in candidates if c.get("status") in status_filter]

    rows: list[dict] = []
    for c in filtered[:limit]:
        rows.append({
            "signal_id":              c.get("signal_id"),
            "family":                 c.get("family"),
            "status":                 c.get("status"),
            "status_emoji":           _STATUS_EMOJI.get(c.get("status", ""), ""),
            "description":            c.get("description"),
            "intended_use":           c.get("intended_use"),
            "recommendation":         c.get("recommendation"),
            "count_all_4x":           c.get("count_all_4x"),
            "count_missed_4x":        c.get("count_missed_4x"),
            "count_false_positive":   c.get("count_false_positive"),
            "lift_vs_fp":             _fmt_lift(c.get("lift_vs_false_positive")),
            "lift_vs_fp_raw":         c.get("lift_vs_false_positive"),
            "precision_estimate":     _fmt_rate(c.get("precision_estimate")),
            "recall_all_4x":          _fmt_rate(c.get("recall_all_4x")),
            "false_positive_rate":    _fmt_rate(c.get("false_positive_rate")),
            "split_artifact_exposure": _fmt_rate(c.get("split_artifact_exposure")),
            "reverse_split_exposure": _fmt_rate(c.get("reverse_split_exposure")),
            "machine_conditions":     c.get("machine_conditions") or [],
        })
    return rows


def _section_feature_separability(feature_sep: list[dict], limit: int = 20) -> list[dict]:
    """Format feature separability analysis as report rows."""
    rows: list[dict] = []
    for fs in feature_sep[:limit]:
        rows.append({
            "feature":     fs.get("feature"),
            "verdict":     fs.get("verdict"),
            "verdict_emoji": _VERDICT_EMOJI.get(fs.get("verdict", ""), ""),
            "median_4x":   _fmt_int(fs.get("median_4x")),
            "median_fp":   _fmt_int(fs.get("median_fp")),
            "median_nw":   _fmt_int(fs.get("median_nw")),
            "sep_vs_fp":   _fmt_lift(fs.get("sep_vs_fp")),
            "sep_vs_fp_raw": fs.get("sep_vs_fp"),
            "n_4x":        fs.get("n_4x"),
            "n_fp":        fs.get("n_fp"),
        })
    return rows


def _section_pump_watch(pw_dist: dict) -> dict:
    """Format pump watch score distribution summary."""
    by_label = pw_dist.get("by_label") or {}
    by_group  = pw_dist.get("by_group_type") or {}

    labels = ["PUMP_WATCH_HIGH", "PUMP_WATCH_MEDIUM", "PUMP_SPECULATIVE", "PUMP_IGNORE"]
    label_rows: list[dict] = []
    for lbl in labels:
        d = by_label.get(lbl) or {}
        label_rows.append({
            "label":               lbl,
            "total":               d.get("total", 0),
            "4x_pump_count":       d.get("4x_pump_count", 0),
            "false_positive_count": d.get("false_positive_count", 0),
            "normal_winner_count": d.get("normal_winner_count", 0),
            "4x_pump_rate":        _fmt_rate(d.get("4x_pump_rate"), pct=True) if "4x_pump_rate" in d else "—",
            "false_positive_rate_str": _fmt_rate(d.get("false_positive_rate"), pct=True) if "false_positive_rate" in d else "—",
        })

    group_rows: list[dict] = []
    for gt in ["4x_pump", "false_positive", "normal_winner"]:
        d = by_group.get(gt) or {}
        group_rows.append({
            "group_type":          gt,
            "total":               d.get("total", 0),
            "PUMP_WATCH_HIGH":     d.get("PUMP_WATCH_HIGH", 0),
            "PUMP_WATCH_MEDIUM":   d.get("PUMP_WATCH_MEDIUM", 0),
            "PUMP_SPECULATIVE":    d.get("PUMP_SPECULATIVE", 0),
            "PUMP_IGNORE":         d.get("PUMP_IGNORE", 0),
            "median_score":        d.get("median_score"),
        })

    return {
        "title":       "Pump Watch Score Distribution",
        "by_label":    label_rows,
        "by_group":    group_rows,
        "note": (
            "HIGH expansion_timing_risk is NOT an automatic reject for Pump Watch. "
            "It is a volatility regime marker only. "
            "For Scanner V2 BUY routing, HIGH expansion risk remains a hard AVOID."
        ),
    }


def _section_split_summary(dataset_summary: dict, candidates: list[dict]) -> dict:
    """Split context and artifact summary section."""
    art_count = dataset_summary.get("split_artifact_count", 0)

    # Find patterns with high split artifact exposure
    split_heavy = [
        c for c in candidates
        if (c.get("split_artifact_exposure") or 0) > 0.4
    ]

    split_regime_patterns = [
        c for c in candidates
        if c.get("family") == "S"
    ]

    return {
        "title":                "Split Context Summary",
        "split_artifact_count": art_count,
        "split_artifact_note": (
            f"{art_count} episodes excluded as split artifacts. "
            "These are kept in a separate group and NOT used as clean pump training data."
        ),
        "reverse_split_regime_note": (
            "RECENT_REVERSE_SPLIT episodes are NOT automatically deleted. "
            "They form a separate speculative regime. "
            "Do not mix with clean 4× pump model."
        ),
        "high_artifact_exposure_patterns": [
            {"signal_id": c["signal_id"], "artifact_exposure": _fmt_rate(c.get("split_artifact_exposure"))}
            for c in split_heavy
        ],
        "split_regime_patterns": [
            {"signal_id": c["signal_id"], "status": c["status"], "description": c["description"]}
            for c in split_regime_patterns
        ],
    }


def _section_registry_additions(candidates: list[dict]) -> list[dict]:
    """List new registry entries to add."""
    return [
        {
            "signal_id":     c["signal_id"],
            "family":        c["family"],
            "status":        c["status"],
            "intended_use":  c.get("intended_use"),
            "description":   c["description"],
            "recommendation": c["recommendation"],
            "lift_vs_fp":    _fmt_lift(c.get("lift_vs_false_positive")),
            "count_4x":      c.get("count_all_4x"),
        }
        for c in candidates
        if c["status"] in ("EXPERIMENTAL", "EXPERIMENTAL_RARE", "RESEARCH_ONLY")
    ]


def _section_replay_recommendations(candidates: list[dict]) -> list[dict]:
    """Generate replay validation recommendations."""
    recs: list[dict] = []
    for c in candidates:
        if c["status"] == "EXPERIMENTAL" and c.get("recommendation") == "add_to_pump_watch":
            recs.append({
                "signal_id":     c["signal_id"],
                "priority":      "HIGH",
                "action":        "Replay with pump_watch flag; validate lift >= 1.5 and FP rate < 60%",
                "condition":     "Add to Pump Watch after replay validation",
                "count_4x":      c.get("count_all_4x"),
                "lift_vs_fp":    _fmt_lift(c.get("lift_vs_false_positive")),
            })
        elif c["status"] == "EXPERIMENTAL_RARE":
            recs.append({
                "signal_id":     c["signal_id"],
                "priority":      "MEDIUM",
                "action":        "Collect more data in next run; replay only if count >= 8",
                "condition":     "Needs more samples before production consideration",
                "count_4x":      c.get("count_all_4x"),
                "lift_vs_fp":    _fmt_lift(c.get("lift_vs_false_positive")),
            })

    return recs


def _section_by_family(candidates: list[dict]) -> dict[str, list[dict]]:
    """Group pattern candidates by family code."""
    from replay.pattern_miner import group_patterns_by_family
    families = group_patterns_by_family(candidates)
    result: dict[str, list[dict]] = {}
    for fam, pats in sorted(families.items()):
        result[fam] = _section_top_patterns(pats, limit=10)
    return result


# ── Main report builder ───────────────────────────────────────────────────────

def _section_bar_patterns(
    bar_candidates: list[dict],
    window_filter: Optional[int] = None,
    limit: int = 20,
) -> list[dict]:
    """Format bar/sequence pattern candidates as report rows."""
    filtered = bar_candidates
    if window_filter is not None:
        filtered = [c for c in bar_candidates if c.get("window_size") == window_filter]

    rows: list[dict] = []
    for c in filtered[:limit]:
        rows.append({
            "signal_id":           c.get("signal_id"),
            "family":              c.get("family"),
            "source_type":         c.get("source_type"),
            "window_size":         c.get("window_size"),
            "sequence_signature":  c.get("sequence_signature"),
            "status":              c.get("status"),
            "status_emoji":        _STATUS_EMOJI.get(c.get("status", ""), ""),
            "description":         c.get("description"),
            "intended_use":        c.get("intended_use"),
            "recommendation":      c.get("recommendation"),
            "count_all_4x":        c.get("count_all_4x"),
            "count_missed_4x":     c.get("count_missed_4x"),
            "count_false_positive": c.get("count_false_positive"),
            "lift_vs_fp":          _fmt_lift(c.get("lift_vs_false_positive")),
            "lift_vs_fp_raw":      c.get("lift_vs_false_positive"),
            "precision_estimate":  _fmt_rate(c.get("precision_estimate")),
            "recall_all_4x":       _fmt_rate(c.get("recall_all_4x")),
            "false_positive_rate": _fmt_rate(c.get("false_positive_rate")),
        })
    return rows


def _section_bar_summary(
    bar_candidates: list[dict],
    windows: list[int],
) -> dict:
    """Summarize bar pattern discovery across window sizes."""
    by_window: dict[int, dict] = {}
    for w in windows:
        cands_w = [c for c in bar_candidates if c.get("window_size") == w]
        exp_w   = [c for c in cands_w if c["status"] in ("EXPERIMENTAL", "EXPERIMENTAL_RARE")]
        by_window[w] = {
            "window_size":       w,
            "total":             len(cands_w),
            "experimental":      len(exp_w),
            "top_lift":          max((c.get("lift_vs_false_positive") or 0) for c in cands_w) if cands_w else 0,
            "top_signature":     exp_w[0].get("sequence_signature") if exp_w else None,
        }

    all_exp = [c for c in bar_candidates if c["status"] in ("EXPERIMENTAL", "EXPERIMENTAL_RARE")]
    return {
        "title":              "Bar-Sequence Pattern Discovery Summary",
        "total_signatures":   len(bar_candidates),
        "experimental_count": len(all_exp),
        "by_window":          list(by_window.values()),
        "top_experimental":   _section_bar_patterns(all_exp, limit=10),
        "note": (
            "Bar-sequence patterns mine symbolic tag signatures from per-bar "
            "raw_pattern_daily_features rows. window_size=1 = single-bar tag; "
            "window_size<=3 = ordered bar sequence (→); "
            "window_size>3 = unordered tag-bag across window. "
            "Anti-leakage: group_type is NEVER used as a pattern condition."
        ),
    }


def build_discovery_report(
    run_id: int,
    dataset_summary: dict,
    pattern_candidates: list[dict],
    feature_separability: list[dict],
    pump_watch_distribution: dict,
    bar_candidates: Optional[list[dict]] = None,
    mode: str = "both",
    windows: Optional[list[int]] = None,
) -> dict:
    """
    Build the full pattern discovery report.

    Parameters
    ----------
    run_id               : run identifier
    dataset_summary      : from missed_pump_dataset
    pattern_candidates   : episode-aggregate pattern candidates (V1A)
    feature_separability : from compute_feature_separability
    pump_watch_distribution : from summarize_pump_watch_distribution
    bar_candidates       : bar/sequence pattern candidates (V1B); may be empty
    mode                 : "episode_aggregate" | "bar_sequence" | "both"
    windows              : bar window sizes used

    Returns a structured dict with sections suitable for JSON serialization
    and frontend display.
    """
    bar_candidates = bar_candidates or []
    windows        = windows or [1, 2, 3, 5, 10]

    experimental  = [c for c in pattern_candidates if c["status"] == "EXPERIMENTAL"]
    rare          = [c for c in pattern_candidates if c["status"] == "EXPERIMENTAL_RARE"]
    research_only = [c for c in pattern_candidates if c["status"] == "RESEARCH_ONLY"]
    rejected      = [c for c in pattern_candidates if c["status"] == "REJECT"]

    bar_exp       = [c for c in bar_candidates if c["status"] in ("EXPERIMENTAL", "EXPERIMENTAL_RARE")]

    report = {
        "run_id":          run_id,
        "mode":            mode,
        "section_dataset_summary":      _section_dataset_summary(dataset_summary),
        "section_top_experimental":     _section_top_patterns(experimental, limit=20),
        "section_top_rare":             _section_top_patterns(rare, limit=10),
        "section_top_research":         _section_top_patterns(research_only, limit=10),
        "section_rejected":             _section_top_patterns(rejected, limit=10),
        "section_feature_separability": _section_feature_separability(feature_separability, limit=25),
        "section_pump_watch":           _section_pump_watch(pump_watch_distribution),
        "section_split_summary":        _section_split_summary(dataset_summary, pattern_candidates),
        "section_registry_additions":   _section_registry_additions(pattern_candidates + bar_exp),
        "section_replay_recommendations": _section_replay_recommendations(pattern_candidates + bar_exp),
        "section_by_family":            _section_by_family(pattern_candidates),
        # Bar-sequence sections (V1B)
        "section_bar_summary":          _section_bar_summary(bar_candidates, windows) if bar_candidates else None,
        "section_bar_single_bar":       _section_bar_patterns(bar_candidates, window_filter=1,  limit=20),
        "section_bar_two_bar":          _section_bar_patterns(bar_candidates, window_filter=2,  limit=20),
        "section_bar_three_bar":        _section_bar_patterns(bar_candidates, window_filter=3,  limit=15),
        "section_bar_five_bar":         _section_bar_patterns(bar_candidates, window_filter=5,  limit=15),
        "section_bar_ten_bar":          _section_bar_patterns(bar_candidates, window_filter=10, limit=10),
        "counts": {
            "total_patterns_evaluated":     len(pattern_candidates),
            "experimental":                 len(experimental),
            "experimental_rare":            len(rare),
            "research_only":                len(research_only),
            "rejected":                     len(rejected),
            "bar_total_signatures":         len(bar_candidates),
            "bar_experimental":             len(bar_exp),
        },
        "notes_for_next_research": _notes_for_next_research(
            experimental, rare, research_only, rejected, dataset_summary,
            bar_exp=bar_exp,
        ),
    }

    return report


def _notes_for_next_research(
    experimental: list[dict],
    rare: list[dict],
    research_only: list[dict],
    rejected: list[dict],
    dataset_summary: dict,
    bar_exp: Optional[list[dict]] = None,
) -> list[str]:
    """Generate human-readable research notes for the next cycle."""
    notes: list[str] = []

    # Top separator patterns
    promising = [c for c in experimental if (c.get("lift_vs_false_positive") or 0) >= 2.0]
    if promising:
        ids = ", ".join(c["signal_id"] for c in promising[:3])
        notes.append(
            f"PROMISING: {ids} show 2×+ lift vs false_positive. "
            "Replay validate before adding to production scoring."
        )

    # High artifact exposure
    art_heavy = [c for c in experimental + rare if (c.get("split_artifact_exposure") or 0) > 0.5]
    if art_heavy:
        ids = ", ".join(c["signal_id"] for c in art_heavy[:3])
        notes.append(
            f"SPLIT CONTAMINATION: {ids} have >50% split artifact exposure. "
            "Clean up by splitting SPLIT_REGIME into its own model."
        )

    # Missed because avoid
    top_reasons = dict(dataset_summary.get("top_miss_reasons") or [])
    if top_reasons.get("missed_because_avoid", 0) > 0:
        notes.append(
            f"AVOID PATTERN: {top_reasons['missed_because_avoid']} missed 4× pumps had AVOID routing. "
            "Investigate: DISC_PUMP_AVOID_PUMP_001 — consider a secondary PUMP_WATCH overlay for high D-confluence AVOID cases."
        )

    # Needs more data
    if rare:
        ids = ", ".join(c["signal_id"] for c in rare[:4])
        notes.append(
            f"NEEDS MORE DATA: {ids} are rare candidates (count < 8). "
            "Run discovery on a longer date range to increase sample count."
        )

    # Rejected
    if rejected:
        ids = ", ".join(c["signal_id"] for c in rejected[:4])
        notes.append(
            f"REJECTED: {ids} showed no meaningful lift vs false_positive. "
            "These conditions do not differentiate pump episodes."
        )

    # Split regime
    notes.append(
        "SPLIT REGIME: RECENT_REVERSE_SPLIT episodes are a separate speculative regime. "
        "Do not retrain the main pump model on them. "
        "A dedicated RS_REGIME Pump Watch model should be evaluated separately."
    )

    # Bar-sequence discovery notes
    if bar_exp:
        bar_exp = bar_exp or []
        top_bar = bar_exp[:3]
        ids = ", ".join(c["signal_id"] for c in top_bar)
        notes.append(
            f"BAR PATTERNS: {len(bar_exp)} bar/sequence patterns qualified (EXPERIMENTAL/RARE). "
            f"Top signatures: {ids}. "
            "Validate by replaying on unseen date range before adding to Pump Watch."
        )
    else:
        notes.append(
            "BAR PATTERNS: No bar/sequence patterns qualified in this run. "
            "Try running in mode='bar_sequence' or 'both' with more episodes."
        )

    # Anti-leakage reminder
    notes.append(
        "ANTI-LEAKAGE: All pattern conditions use only PRE-window features. "
        "forward_return, group_type, pump_multiple, and days_from_breakout_to_peak "
        "must NEVER appear in live scanner feature generation."
    )

    return notes
