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
# TASK 2: VALIDATION QUESTIONS
# ══════════════════════════════════════════════════════════════════════════════

def _new_question(qid: str, question: str, delta, verdict: str,
                  interpretation: str) -> dict:
    """Stable shape for every validation-question row."""
    return {
        "question_id":    qid,
        "question":       question,
        "delta":          delta,
        "verdict":        verdict,
        "interpretation": interpretation,
    }


def _build_validation_questions(validation: dict, summary: dict) -> list[dict]:
    """
    Auto-answer the 10 (+1 split) Scanner v2 validation questions from the
    already-computed validation dict.  Each row is
    {question_id, question, delta, verdict, interpretation}.

    Task 2a: Q01, Q02a, Q02b, Q03.  Tasks 2b / 2c add the rest.
    """
    perf_v2  = validation.get("performance_by_scanner_v2_decision") or []
    mfe_v2   = validation.get("mfe_by_scanner_v2_decision")         or []
    perf_pri = validation.get("performance_by_priority_label")      or []

    questions: list[dict] = []

    # ── Q01: BUY_CANDIDATE_HIGH vs BUY_CANDIDATE_NORMAL by avg_return_5d ─────
    bch_row = _safe_row(perf_v2, "BUY_CANDIDATE_HIGH")
    bcn_row = _safe_row(perf_v2, "BUY_CANDIDATE_NORMAL")
    bch5    = bch_row.get("avg_return_5d")
    bcn5    = bcn_row.get("avg_return_5d")
    bch_n   = bch_row.get("count") or 0
    bcn_n   = bcn_row.get("count") or 0
    q1_d    = _delta(bch5, bcn5)
    q1_v    = _verdict_cmp(bch5, bcn5, bch_n, bcn_n)
    if q1_v == "INSUFFICIENT_DATA":
        q1_int = (
            f"INSUFFICIENT_DATA: BUY_HIGH n={bch_n}, BUY_NORMAL n={bcn_n} "
            f"(need ≥{MIN_COMPARISON_N} each)"
        )
    else:
        q1_int = (
            f"BUY_CANDIDATE_HIGH avg5d {_fmt5(bch5)} (n={bch_n}) vs "
            f"NORMAL {_fmt5(bcn5)} (n={bcn_n}); delta {_fmt5(q1_d)}"
        )
    questions.append(_new_question(
        "Q01",
        "Does BUY_CANDIDATE_HIGH outperform BUY_CANDIDATE_NORMAL by avg_return_5d?",
        q1_d, q1_v, q1_int,
    ))

    # ── Q02a: WATCH close-return hierarchy (HIGH > MEDIUM > LOW by 5d) ───────
    wh_row = _safe_row(perf_v2, "WATCH_HIGH")
    wm_row = _safe_row(perf_v2, "WATCH_MEDIUM")
    wl_row = _safe_row(perf_v2, "WATCH_LOW")
    wh5, wm5, wl5 = wh_row.get("avg_return_5d"), wm_row.get("avg_return_5d"), wl_row.get("avg_return_5d")
    wh_n, wm_n, wl_n = wh_row.get("count") or 0, wm_row.get("count") or 0, wl_row.get("count") or 0
    q2a_hm = _verdict_cmp(wh5, wm5, wh_n, wm_n)
    q2a_ml = _verdict_cmp(wm5, wl5, wm_n, wl_n)
    if "INSUFFICIENT_DATA" in (q2a_hm, q2a_ml):
        q2a_v = "INSUFFICIENT_DATA"
    elif q2a_hm == "PASS" and q2a_ml == "PASS":
        q2a_v = "PASS"
    else:
        q2a_v = "FAIL"
    q2a_int = (
        f"WATCH_HIGH {_fmt5(wh5)} (n={wh_n}), MED {_fmt5(wm5)} (n={wm_n}), "
        f"LOW {_fmt5(wl5)} (n={wl_n}) | HIGH>MED: {q2a_hm}, MED>LOW: {q2a_ml}"
    )
    questions.append(_new_question(
        "Q02a",
        "WATCH close-return hierarchy: WATCH_HIGH > WATCH_MEDIUM > WATCH_LOW (avg_return_5d)?",
        _delta(wh5, wl5), q2a_v, q2a_int,
    ))

    # ── Q02b: WATCH opportunity hierarchy (MFE-based) ────────────────────────
    wh_mfe = _safe_row(mfe_v2, "WATCH_HIGH")
    wm_mfe = _safe_row(mfe_v2, "WATCH_MEDIUM")
    wl_mfe = _safe_row(mfe_v2, "WATCH_LOW")
    wh_mg = wh_mfe.get("avg_max_gain_10d_pct")
    wm_mg = wm_mfe.get("avg_max_gain_10d_pct")
    wl_mg = wl_mfe.get("avg_max_gain_10d_pct")
    wh_mn = wh_mfe.get("mfe_n") or 0
    wm_mn = wm_mfe.get("mfe_n") or 0
    wl_mn = wl_mfe.get("mfe_n") or 0
    # Compare HIGH vs LOW (the cleanest opportunity test); if both MED & LOW
    # are sparse, fall back to HIGH vs MED.
    if wh_mn >= MIN_COMPARISON_N and wl_mn >= MIN_COMPARISON_N:
        q2b_v = _verdict_cmp(wh_mg, wl_mg, wh_mn, wl_mn)
        q2b_d = _delta(wh_mg, wl_mg)
    elif wh_mn >= MIN_COMPARISON_N and wm_mn >= MIN_COMPARISON_N:
        q2b_v = _verdict_cmp(wh_mg, wm_mg, wh_mn, wm_mn)
        q2b_d = _delta(wh_mg, wm_mg)
    else:
        q2b_v = "INSUFFICIENT_DATA"
        q2b_d = None
    q2b_int = (
        f"WATCH_HIGH max_gain10d {_fmt5(wh_mg)} (mfe_n={wh_mn}), "
        f"MED {_fmt5(wm_mg)} (mfe_n={wm_mn}), "
        f"LOW {_fmt5(wl_mg)} (mfe_n={wl_mn})"
    )
    if q2a_v == "FAIL" and q2b_v == "PASS":
        q2b_int += (
            " — WATCH_HIGH may be more opportunity-rich but not better by close-return."
        )
    questions.append(_new_question(
        "Q02b",
        "WATCH opportunity hierarchy: WATCH_HIGH ≥ WATCH_MEDIUM/LOW by avg_max_gain_10d_pct?",
        q2b_d, q2b_v, q2b_int,
    ))

    # ── Q03: PRIORITY_HIGH > MEDIUM > LOW > RISKY by avg_return_5d ───────────
    ph_row = _safe_row(perf_pri, "PRIORITY_HIGH")
    pm_row = _safe_row(perf_pri, "PRIORITY_MEDIUM")
    pl_row = _safe_row(perf_pri, "PRIORITY_LOW")
    pr_row = _safe_row(perf_pri, "PRIORITY_RISKY")
    ph5, pm5, pl5, pr5 = (ph_row.get("avg_return_5d"), pm_row.get("avg_return_5d"),
                           pl_row.get("avg_return_5d"), pr_row.get("avg_return_5d"))
    ph_n = ph_row.get("count") or 0
    pm_n = pm_row.get("count") or 0
    pl_n = pl_row.get("count") or 0
    pr_n = pr_row.get("count") or 0

    q3_hm = _verdict_cmp(ph5, pm5, ph_n, pm_n)
    q3_ml = _verdict_cmp(pm5, pl5, pm_n, pl_n)
    # PRIORITY_RISKY is sparse — only include when both sides meet threshold.
    if pl_n >= MIN_COMPARISON_N and pr_n >= MIN_COMPARISON_N:
        q3_lr = _verdict_cmp(pl5, pr5, pl_n, pr_n)
    else:
        q3_lr = "SKIP"
    if "INSUFFICIENT_DATA" in (q3_hm, q3_ml):
        q3_v = "INSUFFICIENT_DATA"
    else:
        all_pass = (q3_hm == "PASS" and q3_ml == "PASS"
                    and q3_lr in ("PASS", "SKIP"))
        q3_v = "PASS" if all_pass else "FAIL"
    q3_d = _delta(ph5, pr5 if pr5 is not None else pl5)
    q3_int = (
        f"HIGH {_fmt5(ph5)} (n={ph_n}), MED {_fmt5(pm5)} (n={pm_n}), "
        f"LOW {_fmt5(pl5)} (n={pl_n}), RISKY {_fmt5(pr5)} (n={pr_n}) | "
        f"H>M: {q3_hm}, M>L: {q3_ml}, L>R: {q3_lr}"
    )
    questions.append(_new_question(
        "Q03",
        "PRIORITY_HIGH > PRIORITY_MEDIUM > PRIORITY_LOW > PRIORITY_RISKY by avg_return_5d?",
        q3_d, q3_v, q3_int,
    ))

    # ── Q04: AVOID_LOTTERY profile (high MFE + high giveback) ────────────────
    # Lottery profile is confirmed if EITHER:
    #   (a) avg_max_gain_10d_pct > 15 AND avg_giveback_10d_pct > 8
    #   (b) avg_max_gain_10d_pct − avg_return_10d > 10  (high spike, weak close)
    al_mfe   = _safe_row(mfe_v2, "AVOID_LOTTERY")
    al_perf  = _safe_row(perf_v2, "AVOID_LOTTERY")
    al_mg    = al_mfe.get("avg_max_gain_10d_pct")
    al_gb    = al_mfe.get("avg_giveback_10d_pct")
    al_r10   = al_mfe.get("avg_return_10d")
    al_mn    = al_mfe.get("mfe_n")  or 0
    al_n     = al_perf.get("count") or 0
    if al_mn < MIN_BUCKET_N:
        q4_v   = "INSUFFICIENT_DATA"
        q4_d   = None
        q4_int = (
            f"INSUFFICIENT_DATA: AVOID_LOTTERY mfe_n={al_mn} "
            f"(need ≥{MIN_BUCKET_N}); count={al_n}"
        )
    else:
        lottery_a = (al_mg is not None and al_mg > 15.0 and
                     al_gb is not None and al_gb > 8.0)
        lottery_b = (al_mg is not None and al_r10 is not None and
                     (al_mg - al_r10) > 10.0)
        q4_v = "PASS" if (lottery_a or lottery_b) else "FAIL"
        q4_d = _delta(al_mg, al_r10)
        q4_int = (
            f"AVOID_LOTTERY: max_gain10d {_fmt5(al_mg)}, "
            f"giveback10d {_fmt5(al_gb)}, return10d {_fmt5(al_r10)} "
            f"(mfe_n={al_mn})"
        )
        if q4_v == "PASS":
            reasons = []
            if lottery_a: reasons.append("high MFE + high giveback")
            if lottery_b: reasons.append("MFE-vs-return10d spread > 10")
            q4_int += f" — lottery profile confirmed ({', '.join(reasons)})."
        else:
            q4_int += " — lottery profile NOT confirmed."
    questions.append(_new_question(
        "Q04",
        "Does AVOID_LOTTERY show high MFE + high giveback (lottery profile)?",
        q4_d, q4_v, q4_int,
    ))

    # ── Q05: AVOID_DEAD low MFE (avg_max_gain_10d_pct < 5) ───────────────────
    ad_mfe = _safe_row(mfe_v2, "AVOID_DEAD")
    ad_mg  = ad_mfe.get("avg_max_gain_10d_pct")
    ad_mn  = ad_mfe.get("mfe_n") or 0
    q5_v = _verdict_threshold(ad_mg, 5.0, n=ad_mn, direction="below")
    if q5_v == "INSUFFICIENT_DATA":
        q5_int = (
            f"INSUFFICIENT_DATA: AVOID_DEAD mfe_n={ad_mn} "
            f"(need ≥{MIN_BUCKET_N})"
        )
    else:
        q5_int = (
            f"AVOID_DEAD avg_max_gain10d {_fmt5(ad_mg)} (mfe_n={ad_mn}) — "
            + ("low MFE confirmed (dead-money profile)."
               if q5_v == "PASS"
               else "MFE not low; check whether AVOID_DEAD routing is too lenient.")
        )
    questions.append(_new_question(
        "Q05",
        "Does AVOID_DEAD have low MFE (avg_max_gain_10d_pct < 5)?",
        ad_mg, q5_v, q5_int,
    ))

    # ── Q06: D6_BEUP improves WATCH_HIGH / BUY_CANDIDATE_HIGH ────────────────
    v2_dconf = validation.get("performance_by_scanner_v2_decision_d_confluence") or []

    def _dconf_perf(v2_label: str, dconf_label: str):
        bucket = f"{v2_label}|{dconf_label}"
        row = _safe_row(v2_dconf, bucket)
        return row.get("avg_return_5d"), row.get("count") or 0

    wh_d6_5, wh_d6_n = _dconf_perf("WATCH_HIGH",         "D6_BEUP")
    wh_no_5, wh_no_n = _dconf_perf("WATCH_HIGH",         "NONE")
    bh_d6_5, bh_d6_n = _dconf_perf("BUY_CANDIDATE_HIGH", "D6_BEUP")
    bh_no_5, bh_no_n = _dconf_perf("BUY_CANDIDATE_HIGH", "NONE")

    # MIN_DW_BUCKET_N is the higher bar for D/WLNBB cross-tabs.
    def _d6_check(v2_label: str, d6_5, d6_n, no_5, no_n) -> tuple[str, str]:
        if d6_n < MIN_DW_BUCKET_N or no_n < MIN_DW_BUCKET_N:
            return ("INSUFFICIENT_DATA",
                    f"{v2_label}: D6_BEUP n={d6_n}, NONE n={no_n} "
                    f"(need ≥{MIN_DW_BUCKET_N} each)")
        if d6_5 is None or no_5 is None:
            return ("INSUFFICIENT_DATA",
                    f"{v2_label}: D6_BEUP {_fmt5(d6_5)} vs NONE {_fmt5(no_5)} (missing values)")
        verdict = "PASS" if d6_5 > no_5 else "FAIL"
        return (verdict, f"{v2_label}: D6_BEUP {_fmt5(d6_5)} (n={d6_n}) vs "
                          f"NONE {_fmt5(no_5)} (n={no_n}) → {verdict}")

    wh_v, wh_evidence = _d6_check("WATCH_HIGH",         wh_d6_5, wh_d6_n, wh_no_5, wh_no_n)
    bh_v, bh_evidence = _d6_check("BUY_CANDIDATE_HIGH", bh_d6_5, bh_d6_n, bh_no_5, bh_no_n)

    if wh_v == "INSUFFICIENT_DATA" and bh_v == "INSUFFICIENT_DATA":
        q6_v = "INSUFFICIENT_DATA"
    elif "PASS" in (wh_v, bh_v):
        q6_v = "PASS"
    else:
        q6_v = "FAIL"

    # Pick the dominant delta as the headline (whichever has data)
    if wh_d6_5 is not None and wh_no_5 is not None:
        q6_d = _delta(wh_d6_5, wh_no_5)
    elif bh_d6_5 is not None and bh_no_5 is not None:
        q6_d = _delta(bh_d6_5, bh_no_5)
    else:
        q6_d = None

    q6_int = " | ".join([wh_evidence, bh_evidence])
    questions.append(_new_question(
        "Q06",
        "Does D6_BEUP confluence improve performance for WATCH_HIGH and BUY_CANDIDATE_HIGH?",
        q6_d, q6_v, q6_int,
    ))

    return questions


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT (Task 3–4 will fill these in)
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

    try:
        validation_questions = _build_validation_questions(validation, summary)
    except Exception as exc:
        logger.warning(f"[FINDINGS] validation_questions failed: {exc}")
        validation_questions = []

    return {
        "acceptance_checks":    acceptance_checks,
        "validation_questions": validation_questions,
        "regressions":          [],
        "statistical_verdict":  {"verdict": "PENDING", "summary": "not yet implemented"},
        "recommendations":      [],
    }
