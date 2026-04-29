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

    # ── Q07: Sector LEADING/IMPROVING improves WATCH_HIGH ────────────────────
    v2_sector = validation.get("performance_by_scanner_v2_decision_sector_strength") or []

    def _aggregate_by_label_set(
        section: list, v2_label: str, label_set: frozenset,
    ) -> tuple[Optional[float], int]:
        """
        Sum count-weighted avg_return_5d across rows whose bucket is
        "<v2_label>|<x>" where x ∈ label_set.  Returns (weighted_avg, total_n).
        """
        total_weighted = 0.0
        total_n        = 0
        for row in section:
            b = row.get("bucket") or ""
            if "|" not in b:
                continue
            v2, suffix = b.split("|", 1)
            if v2 != v2_label or suffix not in label_set:
                continue
            r5 = row.get("avg_return_5d")
            n  = row.get("count") or 0
            if r5 is None or n <= 0:
                continue
            total_weighted += r5 * n
            total_n        += n
        if total_n == 0:
            return None, 0
        return round(total_weighted / total_n, 2), total_n

    wh_sec_pos_5, wh_sec_pos_n = _aggregate_by_label_set(v2_sector, "WATCH_HIGH", _SECTOR_POSITIVE)
    wh_sec_neg_5, wh_sec_neg_n = _aggregate_by_label_set(v2_sector, "WATCH_HIGH", _SECTOR_NEGATIVE)
    q7_v = _verdict_cmp(wh_sec_pos_5, wh_sec_neg_5, wh_sec_pos_n, wh_sec_neg_n)
    q7_d = _delta(wh_sec_pos_5, wh_sec_neg_5)
    if q7_v == "INSUFFICIENT_DATA":
        q7_int = (
            f"INSUFFICIENT_DATA: WATCH_HIGH × sector "
            f"positive n={wh_sec_pos_n}, negative n={wh_sec_neg_n} "
            f"(need ≥{MIN_COMPARISON_N} each)"
        )
    else:
        q7_int = (
            f"WATCH_HIGH × LEADING/IMPROVING avg5d {_fmt5(wh_sec_pos_5)} "
            f"(n={wh_sec_pos_n}) vs LAGGING/WEAKENING/UNKNOWN "
            f"{_fmt5(wh_sec_neg_5)} (n={wh_sec_neg_n})"
        )
    questions.append(_new_question(
        "Q07",
        "Does sector LEADING/IMPROVING improve WATCH_HIGH vs LAGGING/WEAKENING/UNKNOWN?",
        q7_d, q7_v, q7_int,
    ))

    # ── Q08: Macro RISK_OFF reduces quality vs RISK_ON ───────────────────────
    v2_macro = validation.get("performance_by_scanner_v2_decision_macro_regime") or []

    # Aggregate across actionable buckets (BUY_HIGH + BUY_NORMAL + WATCH_HIGH).
    macro_on_w  = 0.0; macro_on_n  = 0
    macro_off_w = 0.0; macro_off_n = 0
    for v2_label in ("BUY_CANDIDATE_HIGH", "BUY_CANDIDATE_NORMAL", "WATCH_HIGH"):
        on_avg,  on_n  = _aggregate_by_label_set(v2_macro, v2_label, _MACRO_POSITIVE)
        off_avg, off_n = _aggregate_by_label_set(v2_macro, v2_label, _MACRO_NEGATIVE)
        if on_avg  is not None and on_n  > 0:
            macro_on_w  += on_avg  * on_n;  macro_on_n  += on_n
        if off_avg is not None and off_n > 0:
            macro_off_w += off_avg * off_n; macro_off_n += off_n
    macro_on_avg  = round(macro_on_w  / macro_on_n,  2) if macro_on_n  else None
    macro_off_avg = round(macro_off_w / macro_off_n, 2) if macro_off_n else None

    if macro_on_n == 0 and macro_off_n == 0:
        q8_v   = "INSUFFICIENT_DATA"
        q8_int = ("INSUFFICIENT_DATA: no macro regime labels found for "
                  "actionable buckets — check macro_context coverage.")
    else:
        q8_v = _verdict_cmp(
            macro_on_avg, macro_off_avg,
            macro_on_n, macro_off_n,
            direction="higher_is_better",
        )
        q8_int = (
            f"Actionable × RISK_ON-family avg5d {_fmt5(macro_on_avg)} "
            f"(n={macro_on_n}) vs RISK_OFF-family {_fmt5(macro_off_avg)} "
            f"(n={macro_off_n})"
        )
    questions.append(_new_question(
        "Q08",
        "Does macro RISK_OFF reduce performance vs RISK_ON across actionable buckets?",
        _delta(macro_on_avg, macro_off_avg),
        q8_v, q8_int,
    ))

    # ── Q09: Scanner v2 reduces FP rate vs legacy FIRE/ARM ───────────────────
    fp_v2      = validation.get("false_positive_by_scanner_v2_decision") or []
    old_vs_new = validation.get("old_vs_new_scanner_comparison") or {}
    by_legacy  = old_vs_new.get("by_legacy_tier") or []

    def _weighted_fp(rows: list, label_n_field: str = "count") -> tuple[Optional[float], int]:
        """
        Compute count-weighted FP rate across the given rows.
        Each row must have false_positive_rate and a count field
        (label_n_field — "count" for legacy, "with_5d_data" for fp_v2).
        """
        total_w = 0.0
        total_n = 0
        for row in rows:
            fpr = row.get("false_positive_rate")
            n   = row.get(label_n_field) or 0
            if fpr is None or n <= 0:
                continue
            total_w += fpr * n
            total_n += n
        if total_n == 0:
            return None, 0
        return round(total_w / total_n, 2), total_n

    legacy_rows = [_safe_row(by_legacy, "FIRE"), _safe_row(by_legacy, "ARM")]
    legacy_fp,  legacy_n = _weighted_fp(legacy_rows, label_n_field="count")

    v2_rows = [_safe_row(fp_v2, "BUY_CANDIDATE_HIGH"), _safe_row(fp_v2, "BUY_CANDIDATE_NORMAL")]
    v2_fp,  v2_n  = _weighted_fp(v2_rows,  label_n_field="with_5d_data")

    q9_v = _verdict_cmp(
        v2_fp, legacy_fp,
        v2_n,  legacy_n,
        direction="lower_is_better",
    )
    q9_d = _delta(v2_fp, legacy_fp)
    if q9_v == "INSUFFICIENT_DATA":
        q9_int = (
            f"INSUFFICIENT_DATA: v2 BUY n={v2_n}, legacy FIRE+ARM n={legacy_n} "
            f"(need ≥{MIN_COMPARISON_N} each)"
        )
    else:
        q9_int = (
            f"Legacy FIRE+ARM FP rate {_fmt5(legacy_fp)} (n={legacy_n}) vs "
            f"v2 BUY (HIGH+NORMAL) FP rate {_fmt5(v2_fp)} (n={v2_n})"
        )
    questions.append(_new_question(
        "Q09",
        "Does Scanner v2 BUY reduce false-positive rate vs legacy FIRE/ARM?",
        q9_d, q9_v, q9_int,
    ))

    # ── Q10: UNKNOWN bucket < 5% (results trustworthy) ───────────────────────
    debug   = validation.get("_debug") or {}
    unk_pct = debug.get("scanner_v2_unknown_pct", 100.0)
    q10_v   = _verdict_threshold(unk_pct, 5.0, direction="below")
    q10_int = (
        f"scanner_v2_unknown_pct = {unk_pct}% — "
        + ("results are trustworthy."
           if q10_v == "PASS"
           else "high UNKNOWN% undermines cross-tab conclusions.")
    )
    questions.append(_new_question(
        "Q10",
        "Is the Scanner v2 UNKNOWN bucket < 5% (results trustworthy)?",
        unk_pct, q10_v, q10_int,
    ))

    return questions


# ══════════════════════════════════════════════════════════════════════════════
# TASK 3: REGRESSION DETECTION
# ══════════════════════════════════════════════════════════════════════════════

def _new_regression(rid: str, description: str, severity: str,
                    value, triggered: bool, note: str = "") -> dict:
    """Stable shape for every regression row."""
    return {
        "regression_id": rid,
        "description":   description,
        "severity":      severity,
        "value":         value,
        "triggered":     bool(triggered),
        "note":          note,
    }


def _detect_regressions(validation: dict, summary: dict) -> list[dict]:
    """
    Auto-detect suspicious patterns that indicate broken evaluation.
    Returns a list of regression rows; never raises.

    Severity: HIGH (fatal — needs investigation),
              MEDIUM (notable — may be acceptable),
              INFO (worth flagging but not a problem).

    Comparisons require MIN_BUCKET_N on each side or the regression is
    skipped (not falsely cleared, not falsely triggered).
    """
    perf_v2  = validation.get("performance_by_scanner_v2_decision") or []
    mfe_v2   = validation.get("mfe_by_scanner_v2_decision")         or []
    perf_pri = validation.get("performance_by_priority_label")      or []
    debug    = validation.get("_debug") or {}
    n_total  = summary.get("total_candidates", 0)

    regressions: list[dict] = []

    bch  = _safe_row(perf_v2, "BUY_CANDIDATE_HIGH")
    wh   = _safe_row(perf_v2, "WATCH_HIGH")
    wl   = _safe_row(perf_v2, "WATCH_LOW")
    bch5, bch_n = bch.get("avg_return_5d"), bch.get("count") or 0
    wh5,  wh_n  = wh.get("avg_return_5d"),  wh.get("count")  or 0
    wl5,  wl_n  = wl.get("avg_return_5d"),  wl.get("count")  or 0

    ph = _safe_row(perf_pri, "PRIORITY_HIGH")
    pl = _safe_row(perf_pri, "PRIORITY_LOW")
    ph5, ph_n = ph.get("avg_return_5d"), ph.get("count") or 0
    pl5, pl_n = pl.get("avg_return_5d"), pl.get("count") or 0

    # ── R01: BUY_CANDIDATE_HIGH underperforms WATCH_HIGH ─────────────────────
    # MEDIUM by default — WATCH_HIGH can legitimately be opportunity-rich.
    # HIGH only if BUY_HIGH also underperforms WATCH_LOW or PRIORITY_LOW
    # (a true priority inversion).
    if (bch5 is not None and bch_n >= MIN_BUCKET_N
            and wh5 is not None and wh_n >= MIN_BUCKET_N):
        triggered = bch5 < wh5
        if triggered:
            fatal_below_low = (
                (wl5 is not None and wl_n >= MIN_BUCKET_N and bch5 < wl5)
                or
                (pl5 is not None and pl_n >= MIN_BUCKET_N and bch5 < pl5)
            )
            severity = "HIGH" if fatal_below_low else "MEDIUM"
            note     = (
                "Also underperforms WATCH_LOW or PRIORITY_LOW — "
                "priority inversion is fatal."
                if fatal_below_low
                else "WATCH_HIGH may be more opportunity-rich; "
                     "compare MFE (Q02b) before treating as fatal."
            )
        else:
            severity, note = "INFO", ""
        regressions.append(_new_regression(
            "R01",
            "BUY_CANDIDATE_HIGH underperforms WATCH_HIGH by avg_return_5d",
            severity,
            f"BUY_HIGH {_fmt5(bch5)} vs WATCH_HIGH {_fmt5(wh5)} "
            f"(WATCH_LOW {_fmt5(wl5)}, PRIORITY_LOW {_fmt5(pl5)})",
            triggered, note,
        ))

    # ── R02: Any AVOID bucket avg_return_5d > BUY_CANDIDATE_HIGH ─────────────
    if bch5 is not None and bch_n >= MIN_BUCKET_N:
        for avoid_lbl in ("AVOID_RISK", "AVOID_LOTTERY", "AVOID_DEAD"):
            row  = _safe_row(perf_v2, avoid_lbl)
            av5  = row.get("avg_return_5d")
            av_n = row.get("count") or 0
            if av5 is None or av_n < MIN_BUCKET_N:
                continue
            triggered = av5 > bch5
            if triggered:
                regressions.append(_new_regression(
                    "R02",
                    f"{avoid_lbl} outperforms BUY_CANDIDATE_HIGH (AVOID beating BUY)",
                    "HIGH",
                    f"{avoid_lbl} {_fmt5(av5)} (n={av_n}) > "
                    f"BUY_HIGH {_fmt5(bch5)} (n={bch_n})",
                    True,
                    note="Scoring inversion — inspect priority_score formula "
                         "and AVOID routing.",
                ))

    # ── R03: PRIORITY_HIGH underperforms PRIORITY_LOW ────────────────────────
    if (ph5 is not None and ph_n >= MIN_BUCKET_N
            and pl5 is not None and pl_n >= MIN_BUCKET_N):
        triggered = ph5 < pl5
        regressions.append(_new_regression(
            "R03",
            "PRIORITY_HIGH underperforms PRIORITY_LOW (priority score not discriminating)",
            "HIGH" if triggered else "INFO",
            f"PRIORITY_HIGH {_fmt5(ph5)} (n={ph_n}) vs "
            f"PRIORITY_LOW {_fmt5(pl5)} (n={pl_n})",
            triggered,
            note="Indicates the priority_score formula is inverted." if triggered else "",
        ))

    # ── R04: scanner_v2_unknown_pct > 20% ────────────────────────────────────
    unk_pct   = debug.get("scanner_v2_unknown_pct", 0.0)
    triggered = unk_pct > 20.0
    regressions.append(_new_regression(
        "R04",
        "scanner_v2_unknown_pct > 20% (enrichment likely failed)",
        "HIGH",
        f"{unk_pct}%",
        triggered,
        note="Run /api/replay/{run_id}/recalculate-scanner-v2 to backfill, "
             "or re-run replay with current code." if triggered else "",
    ))

    # ── R05: Single Scanner v2 bucket holds > 90% of all candidates ──────────
    if n_total > 0 and perf_v2:
        for row in perf_v2:
            count = row.get("count") or 0
            pct   = round(count / n_total * 100, 1)
            if pct > 90.0:
                regressions.append(_new_regression(
                    "R05",
                    "Single Scanner v2 bucket holds > 90% of all candidates",
                    "HIGH",
                    f"{row.get('bucket')}: {pct}% ({count}/{n_total})",
                    True,
                    note="All candidates collapsed into one label — likely "
                         "enrichment or routing failure.",
                ))
                break  # one collapse is enough; don't double-flag

    # ── R06: AVOID_LOTTERY MFE < AVOID_DEAD MFE (lottery profile inverted) ───
    al_mfe = _safe_row(mfe_v2, "AVOID_LOTTERY")
    ad_mfe = _safe_row(mfe_v2, "AVOID_DEAD")
    al_mg, al_mn = al_mfe.get("avg_max_gain_10d_pct"), al_mfe.get("mfe_n") or 0
    ad_mg, ad_mn = ad_mfe.get("avg_max_gain_10d_pct"), ad_mfe.get("mfe_n") or 0
    if (al_mg is not None and ad_mg is not None
            and al_mn >= MIN_BUCKET_N and ad_mn >= MIN_BUCKET_N):
        triggered = al_mg < ad_mg
        regressions.append(_new_regression(
            "R06",
            "AVOID_LOTTERY MFE < AVOID_DEAD MFE (lottery profile inverted)",
            "MEDIUM",
            f"LOTTERY max_gain10d {_fmt5(al_mg)} (mfe_n={al_mn}) vs "
            f"DEAD {_fmt5(ad_mg)} (mfe_n={ad_mn})",
            triggered,
            note="By design AVOID_LOTTERY should have higher MFE than "
                 "AVOID_DEAD." if triggered else "",
        ))

    # ── R07: BUY_CANDIDATE_HIGH count = 0 with total candidates > 20 ─────────
    if n_total > 20:
        triggered = bch_n == 0
        regressions.append(_new_regression(
            "R07",
            "BUY_CANDIDATE_HIGH count = 0 with total candidates > 20",
            "MEDIUM",
            f"BUY_HIGH n={bch_n}, total n={n_total}",
            triggered,
            note="Expand date range / universe, or lower the priority_score "
                 "HIGH threshold from 75." if triggered else "",
        ))

    return regressions


# ══════════════════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT (Task 4 will fill these in)
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

    try:
        regressions = _detect_regressions(validation, summary)
    except Exception as exc:
        logger.warning(f"[FINDINGS] regressions failed: {exc}")
        regressions = []

    return {
        "acceptance_checks":    acceptance_checks,
        "validation_questions": validation_questions,
        "regressions":          regressions,
        "statistical_verdict":  {"verdict": "PENDING", "summary": "not yet implemented"},
        "recommendations":      [],
    }
