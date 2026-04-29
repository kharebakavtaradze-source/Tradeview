"""
Scanner v2 Auto-Evaluation Findings
====================================
Runs 10 acceptance checks, answers 10 validation questions, detects
regressions, builds a statistical verdict, and emits conditional
recommendations — all from the already-computed scanner_v2_validation dict.

READ-ONLY. Never modifies scanner logic, scoring, or routing.

Entry point:
    findings = build_scanner_v2_findings(
        validation=scanner_v2_validation,
        summary=summary,
        d_wlnbb_coverage_pct=d_wlnbb_coverage_pct,
    )
    # findings["acceptance_checks"]
    # findings["validation_questions"]
    # findings["regressions"]
    # findings["statistical_verdict"]
    # findings["recommendations"]
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# ── Sample-size thresholds ────────────────────────────────────────────────────
# Any PASS/FAIL below these thresholds collapses to INSUFFICIENT_DATA.
MIN_RUN_N        = 50   # minimum total actionable candidates for a run-level verdict
MIN_BUCKET_N     = 5    # minimum bucket count to evaluate that bucket on its own
MIN_COMPARISON_N = 5    # minimum count on each side of a delta comparison
MIN_DW_BUCKET_N  = 10   # higher bar for D/WLNBB cross-tab buckets (data is sparser)


# ── Sector / macro label groupings ────────────────────────────────────────────
# Real label values used by np_context_enricher — do not assume STRONG/WEAK.
_SECTOR_POSITIVE = frozenset({"SECTOR_LEADING",  "SECTOR_IMPROVING"})
_SECTOR_NEGATIVE = frozenset({"SECTOR_LAGGING",  "SECTOR_WEAKENING", "UNKNOWN"})

_MACRO_POSITIVE = frozenset({"RISK_ON",  "SMALL_CAP_RISK_ON",  "GROWTH_ROTATION"})
_MACRO_NEGATIVE = frozenset({"RISK_OFF", "SMALL_CAP_RISK_OFF", "FEAR", "DEFENSIVE_ROTATION"})


# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def _safe_get(section: list, bucket: str, field: str) -> Optional[float]:
    """Return `field` from a perf/mfe section list for a named bucket, or None."""
    if not section:
        return None
    for row in section:
        if row.get("bucket") == bucket:
            return row.get(field)
    return None


def _safe_row(section: list, bucket: str) -> dict:
    """Return the full bucket row from a perf/mfe section, or {} if missing."""
    if not section:
        return {}
    for row in section:
        if row.get("bucket") == bucket:
            return row
    return {}


def _delta(a: Optional[float], b: Optional[float]) -> Optional[float]:
    """Return round(a - b, 2) or None if either side is missing."""
    if a is None or b is None:
        return None
    return round(a - b, 2)


def _verdict_cmp(
    a: Optional[float],
    b: Optional[float],
    n_a: Optional[int],
    n_b: Optional[int],
    direction: str = "higher_is_better",
) -> str:
    """
    Return PASS / FAIL / INSUFFICIENT_DATA for an a-vs-b comparison.

    Both sides must meet MIN_COMPARISON_N; otherwise verdict is
    INSUFFICIENT_DATA — never a confident PASS/FAIL from n=1–2 buckets.
    """
    if (n_a is None or n_a < MIN_COMPARISON_N or
            n_b is None or n_b < MIN_COMPARISON_N):
        return "INSUFFICIENT_DATA"
    if a is None or b is None:
        return "INSUFFICIENT_DATA"
    if direction == "higher_is_better":
        return "PASS" if a > b else "FAIL"
    return "PASS" if a < b else "FAIL"


def _verdict_threshold(
    value:     Optional[float],
    threshold: float,
    n:         Optional[int] = None,
    direction: str = "above",
) -> str:
    """
    Threshold-based verdict (no comparison side).
    direction: "above" → PASS if value >= threshold
               "below" → PASS if value <= threshold
    """
    if n is not None and n < MIN_BUCKET_N:
        return "INSUFFICIENT_DATA"
    if value is None:
        return "INSUFFICIENT_DATA"
    if direction == "above":
        return "PASS" if value >= threshold else "FAIL"
    return "PASS" if value <= threshold else "FAIL"


def _fmt5(v: Optional[float]) -> str:
    """Compact percent formatter for interpretation strings."""
    if v is None:
        return "—"
    return f"{v:+.1f}%"


# ══════════════════════════════════════════════════════════════════════════════
# TASK 1: ACCEPTANCE CHECKS
# ══════════════════════════════════════════════════════════════════════════════

def _new_check(check_id: str, description: str, passed: bool,
               value, threshold, note: str = "") -> dict:
    """Stable shape for every acceptance-check row."""
    return {
        "id":          check_id,
        "description": description,
        "passed":      bool(passed),
        "value":       value,
        "threshold":   threshold,
        "note":        note,
    }


def _build_acceptance_checks(
    validation:           dict,
    summary:              dict,
    d_wlnbb_coverage_pct: float,
) -> list[dict]:
    """
    Run 10 acceptance checks against the already-computed validation dict.
    Returns a list of check dicts; never raises.

    Task 1b implements C01–C04b (data coverage). Task 1c, 1d add the rest.
    """
    debug   = validation.get("_debug") or {}
    n_total = summary.get("total_candidates", 0)
    checks: list[dict] = []

    # ── C01: Total candidates > 0 ────────────────────────────────────────────
    checks.append(_new_check(
        "C01", "Total candidates > 0",
        passed    = n_total > 0,
        value     = n_total,
        threshold = "> 0",
        note      = "" if n_total > 0 else "Replay produced no candidates — nothing to evaluate.",
    ))

    # ── C02: scanner_v2_unknown_pct ≤ 5% ─────────────────────────────────────
    unknown_pct = debug.get("scanner_v2_unknown_pct", 100.0)
    checks.append(_new_check(
        "C02", "Scanner v2 UNKNOWN bucket ≤ 5%",
        passed    = unknown_pct <= 5.0,
        value     = unknown_pct,
        threshold = "≤ 5%",
        note      = "High UNKNOWN% means enrichment or priority_score is missing.",
    ))

    # ── C03: priority coverage (direct + derived) ≥ 90% ──────────────────────
    p_direct  = debug.get("priority_direct",  0)
    p_derived = debug.get("priority_derived", 0)
    p_cov_pct = round((p_direct + p_derived) / n_total * 100, 1) if n_total else 0.0
    checks.append(_new_check(
        "C03", "Priority label coverage (direct + derived) ≥ 90%",
        passed    = p_cov_pct >= 90.0,
        value     = p_cov_pct,
        threshold = "≥ 90%",
        note      = "Low coverage means priority_score was not computed for many candidates.",
    ))

    # ── C04: Sector context coverage > 0% ────────────────────────────────────
    sec_cov = debug.get("sector_context_coverage_pct", 0.0)
    checks.append(_new_check(
        "C04", "Sector context coverage > 0%",
        passed    = sec_cov > 0.0,
        value     = sec_cov,
        threshold = "> 0%",
        note      = "0% means enrich_np_candidates did not attach sector_context.",
    ))

    # ── C04b: Macro context coverage > 0% ────────────────────────────────────
    mac_cov = debug.get("macro_context_coverage_pct", 0.0)
    checks.append(_new_check(
        "C04b", "Macro context coverage > 0%",
        passed    = mac_cov > 0.0,
        value     = mac_cov,
        threshold = "> 0%",
        note      = "0% means enrich_np_candidates did not attach macro_context.",
    ))

    # ── Bucket-existence checks (C05–C07) ────────────────────────────────────
    perf_v2 = validation.get("performance_by_scanner_v2_decision") or []

    # ── C05: BUY_CANDIDATE_HIGH bucket exists (count ≥ 1) ────────────────────
    bch_count = _safe_get(perf_v2, "BUY_CANDIDATE_HIGH", "count") or 0
    checks.append(_new_check(
        "C05", "BUY_CANDIDATE_HIGH bucket exists (count ≥ 1)",
        passed    = bch_count >= 1,
        value     = bch_count,
        threshold = "≥ 1",
        note      = "Existence check only — performance evaluation requires "
                    f"≥{MIN_BUCKET_N} (handled in Q01).",
    ))

    # ── C06: All 3 WATCH tiers present ───────────────────────────────────────
    _WATCH = ("WATCH_HIGH", "WATCH_MEDIUM", "WATCH_LOW")
    watch_present = {
        lbl: (_safe_get(perf_v2, lbl, "count") or 0) >= 1 for lbl in _WATCH
    }
    missing_watch = [k for k, v in watch_present.items() if not v]
    checks.append(_new_check(
        "C06", "All WATCH tiers present (HIGH / MEDIUM / LOW)",
        passed    = not missing_watch,
        value     = watch_present,
        threshold = "all 3 present",
        note      = "" if not missing_watch else f"Missing: {missing_watch}",
    ))

    # ── C07: All AVOID buckets present ───────────────────────────────────────
    _AVOID = ("AVOID_RISK", "AVOID_LOTTERY", "AVOID_DEAD")
    avoid_present = {
        lbl: (_safe_get(perf_v2, lbl, "count") or 0) >= 1 for lbl in _AVOID
    }
    missing_avoid = [k for k, v in avoid_present.items() if not v]
    checks.append(_new_check(
        "C07", "All AVOID buckets present (RISK / LOTTERY / DEAD)",
        passed    = not missing_avoid,
        value     = avoid_present,
        threshold = "all 3 present",
        note      = "" if not missing_avoid else f"Missing: {missing_avoid}",
    ))

    # ── MFE / signal coverage / collapse checks (C08–C10) ────────────────────
    mfe_v2 = validation.get("mfe_by_scanner_v2_decision") or []

    # ── C08: MFE data populated (at least 1 candidate with 10d MFE) ──────────
    mfe_n_total = sum((row.get("mfe_n") or 0) for row in mfe_v2)
    checks.append(_new_check(
        "C08", "MFE data populated (≥ 1 candidate with 10d MFE)",
        passed    = mfe_n_total >= 1,
        value     = mfe_n_total,
        threshold = "≥ 1",
        note      = "0 means no candidate has a 10d outcome — re-run outcome "
                    "computation or expand the replay window.",
    ))

    # ── C09: D/WLNBB coverage > 0% ───────────────────────────────────────────
    checks.append(_new_check(
        "C09", "D/WLNBB coverage > 0%",
        passed    = (d_wlnbb_coverage_pct or 0.0) > 0.0,
        value     = d_wlnbb_coverage_pct,
        threshold = "> 0%",
        note      = "0% means run pre-dates D/WLNBB feature — re-run replay "
                    "to populate D/WLNBB analytics.",
    ))

    # ── C10: No single v2 bucket holds > 80% of all candidates ───────────────
    max_pct          = 0.0
    dominant_bucket  = None
    if n_total > 0 and perf_v2:
        for row in perf_v2:
            pct = round((row.get("count") or 0) / n_total * 100, 1)
            if pct > max_pct:
                max_pct         = pct
                dominant_bucket = row.get("bucket")
    checks.append(_new_check(
        "C10", "No single Scanner v2 bucket holds > 80% of all candidates",
        passed    = max_pct <= 80.0,
        value     = (
            f"{dominant_bucket}: {max_pct}%" if dominant_bucket else "—"
        ),
        threshold = "≤ 80% per bucket",
        note      = "Single-bucket dominance signals enrichment failure or "
                    "a routing collapse (e.g. everything → WATCH_LOW).",
    ))

    return checks


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT (Task 2–4 will fill these in)
# ══════════════════════════════════════════════════════════════════════════════

def build_scanner_v2_findings(
    validation:           dict,
    summary:              dict,
    d_wlnbb_coverage_pct: float = 0.0,
) -> dict:
    """
    Build all scanner v2 auto-evaluation findings from the already-computed
    validation dict.  Returns a stable dict shape; never raises.
    """
    try:
        acceptance_checks = _build_acceptance_checks(
            validation, summary, d_wlnbb_coverage_pct,
        )
    except Exception as exc:
        logger.warning(f"[FINDINGS] acceptance_checks failed: {exc}")
        acceptance_checks = []

    return {
        "acceptance_checks":    acceptance_checks,
        "validation_questions": [],
        "regressions":          [],
        "statistical_verdict":  {"verdict": "PENDING", "summary": "not yet implemented"},
        "recommendations":      [],
    }
