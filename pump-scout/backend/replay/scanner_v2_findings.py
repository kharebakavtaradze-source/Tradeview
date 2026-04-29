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
# MAIN ENTRY POINT (Task 1b–4b will fill these in)
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
    return {
        "acceptance_checks":    [],
        "validation_questions": [],
        "regressions":          [],
        "statistical_verdict":  {"verdict": "PENDING", "summary": "not yet implemented"},
        "recommendations":      [],
    }
