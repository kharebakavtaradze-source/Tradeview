"""
Research Bundle Builder
=======================
Assembles a single structured research artifact from a completed replay run.

READ-ONLY. Never modifies:
  - scanner logic or scoring
  - live tiers or journal
  - portfolio logic
  - any live production table

All data is scoped to one replay run via run_id. No live market data is read.
No future-date data contamination: the bundle only summarises what the replay
computed — outcomes are forward returns that belong to the replay evaluation
window, not current live data.

Entry point:
    bundle = await build_research_bundle(run_id)
    markdown = render_research_bundle_markdown(bundle)
"""

import logging
from collections import defaultdict, Counter
from typing import Optional

logger = logging.getLogger(__name__)

# ── Outcome label helpers ─────────────────────────────────────────────────────

_NEGATIVE_LABELS = {"FALSE_POSITIVE", "FAILED_BREAKOUT"}
_POSITIVE_LABELS = {"SUCCESSFUL_BREAKOUT", "EARLY_WINNER"}

_WIN_THRESHOLD_3D = 0.0   # return_3d > 0 = win
_WIN_THRESHOLD_5D = 0.0   # return_5d > 0 = win


# ── Math helpers ──────────────────────────────────────────────────────────────

def _avg(values: list) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def _win_rate(values: list, threshold: float = 0.0) -> Optional[float]:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return round(sum(1 for v in vals if v > threshold) / len(vals) * 100, 1)


def _pct(n: int, total: int) -> float:
    return round(n / total * 100, 1) if total else 0.0


# ── Outcome map builder ───────────────────────────────────────────────────────

def _build_outcome_map(outcomes: list[dict]) -> dict:
    """
    Returns {candidate_id: {horizon: outcome_dict}}.
    Candidates with no outcomes will be absent from the map.
    """
    om: dict = defaultdict(dict)
    for o in outcomes:
        cid = o.get("replay_candidate_id")
        h   = o.get("horizon")
        if cid is not None and h:
            om[cid][h] = o
    return dict(om)


# ── Bucket stats helper ───────────────────────────────────────────────────────

def _bucket_stats(cand_ids: list[int], outcome_map: dict) -> dict:
    """Aggregate performance metrics for a set of candidate IDs."""
    r1, r3, r5, r10 = [], [], [], []
    gains, dds, a5, a10 = [], [], [], []

    for cid in cand_ids:
        horizons = outcome_map.get(cid, {})
        for hkey, lst in (("1d", r1), ("3d", r3), ("5d", r5), ("10d", r10)):
            v = horizons.get(hkey, {}).get("return_pct")
            if v is not None:
                lst.append(v)
        if "5d" in horizons:
            o5 = horizons["5d"]
            if o5.get("max_gain_pct")      is not None: gains.append(o5["max_gain_pct"])
            if o5.get("max_drawdown_pct")  is not None: dds.append(o5["max_drawdown_pct"])
            if o5.get("alpha_vs_spy")      is not None: a5.append(o5["alpha_vs_spy"])
        if "10d" in horizons:
            if horizons["10d"].get("alpha_vs_spy") is not None:
                a10.append(horizons["10d"]["alpha_vs_spy"])

    return {
        "count":                len(cand_ids),
        "avg_return_1d":        _avg(r1),
        "avg_return_3d":        _avg(r3),
        "avg_return_5d":        _avg(r5),
        "avg_return_10d":       _avg(r10),
        "avg_max_gain_pct":     _avg(gains),
        "avg_max_drawdown_pct": _avg(dds),
        "win_rate_3d":          _win_rate(r3),
        "win_rate_5d":          _win_rate(r5),
        "alpha_vs_spy_5d":      _avg(a5),
        "alpha_vs_spy_10d":     _avg(a10),
    }


def _build_perf_buckets(candidates: list[dict], outcome_map: dict,
                         bucket_fn, label: str) -> list[dict]:
    """
    Group candidates by bucket_fn(candidate) → bucket_key string.
    Return list of bucket dicts sorted by avg_return_5d desc.
    """
    groups: dict = defaultdict(list)
    for c in candidates:
        key = bucket_fn(c)
        groups[key].append(c["id"])

    rows = []
    for bucket_key, cids in groups.items():
        stats = _bucket_stats(cids, outcome_map)
        rows.append({"bucket": bucket_key, **stats})

    rows.sort(key=lambda x: x.get("avg_return_5d") or -999, reverse=True)
    return rows


# ── Section builders ──────────────────────────────────────────────────────────

def _build_summary(run: dict, candidates: list, outcomes: list,
                   missed: list) -> dict:
    """Section A — Replay Overview + Performance Summary."""
    all5 = [o for o in outcomes if o["horizon"] == "5d"]

    label_counts: dict = defaultdict(int)
    for o in all5:
        if o.get("outcome_label"):
            label_counts[o["outcome_label"]] += 1

    by_horizon = defaultdict(list)
    alpha_by_horizon = defaultdict(list)
    for o in outcomes:
        if o.get("return_pct") is not None:
            by_horizon[o["horizon"]].append(o["return_pct"])
        if o.get("alpha_vs_spy") is not None:
            alpha_by_horizon[o["horizon"]].append(o["alpha_vs_spy"])

    return {
        "run_id":           run["id"],
        "mode":             run.get("mode"),
        "as_of_date":       run.get("as_of_date"),
        "start_date":       run.get("start_date"),
        "end_date":         run.get("end_date"),
        "universe_mode":    run.get("universe_mode"),
        "status":           run.get("status"),
        "started_at":       run.get("started_at"),
        "finished_at":      run.get("finished_at"),
        "total_days":       run.get("total_days", 0),
        "total_symbols":    run.get("total_symbols", 0),
        "total_candidates": len(candidates),
        "total_outcomes":   len(outcomes),
        "total_outcomes_5d": len(all5),
        "total_missed_movers": len(missed),

        # Returns
        "avg_return_1d":        _avg(by_horizon.get("1d", [])),
        "avg_return_3d":        _avg(by_horizon.get("3d", [])),
        "avg_return_5d":        _avg(by_horizon.get("5d", [])),
        "avg_return_10d":       _avg(by_horizon.get("10d", [])),
        "avg_alpha_vs_spy_5d":  _avg(alpha_by_horizon.get("5d", [])),
        "avg_alpha_vs_spy_10d": _avg(alpha_by_horizon.get("10d", [])),
        "win_rate_3d":          _win_rate(by_horizon.get("3d", [])),
        "win_rate_5d":          _win_rate(by_horizon.get("5d", [])),

        # Outcome breakdown (5d only)
        "outcome_label_counts": {
            "SUCCESSFUL_BREAKOUT":  label_counts.get("SUCCESSFUL_BREAKOUT", 0),
            "EARLY_WINNER":         label_counts.get("EARLY_WINNER", 0),
            "NO_FOLLOW_THROUGH":    label_counts.get("NO_FOLLOW_THROUGH", 0),
            "LATE_SIGNAL":          label_counts.get("LATE_SIGNAL", 0),
            "FAILED_BREAKOUT":      label_counts.get("FAILED_BREAKOUT", 0),
            "FALSE_POSITIVE":       label_counts.get("FALSE_POSITIVE", 0),
            "NO_DATA":              label_counts.get("NO_DATA", 0),
        },
    }


def _build_false_positives(candidates: list[dict], outcome_map: dict,
                            limit: int = 20) -> list[dict]:
    """Section C — Worst misleading candidates ranked by 5d return."""
    cand_by_id = {c["id"]: c for c in candidates}

    rows = []
    for cid, horizons in outcome_map.items():
        o5 = horizons.get("5d", {})
        ret5 = o5.get("return_pct")
        if ret5 is None or ret5 > -5.0:
            continue                         # only include genuinely bad outcomes
        o3 = horizons.get("3d", {})
        c  = cand_by_id.get(cid, {})

        tier    = c.get("tier", "?")
        np_lbl  = c.get("new_pump_label") or "UNKNOWN"
        np_seq  = c.get("new_pump_sequence_label") or "NONE"
        np_via  = c.get("np_setup_via") or "NONE"
        np_iso  = c.get("np_is_isolated_trigger", False)
        score   = c.get("total_score")

        why = f"{tier} tier | {np_lbl} | via {np_via}"
        if np_iso:
            why += " | ISOLATED_TRIGGER"
        if score is not None:
            why += f" | Score {round(score, 1)}"

        rows.append({
            "symbol":                  c.get("symbol", "?"),
            "scan_date":               c.get("scan_date"),
            "tier":                    tier,
            "total_score":             score,
            "new_pump_label":          np_lbl,
            "new_pump_sequence":       np_seq,
            "np_setup_via":            np_via,
            "np_is_isolated_trigger":  np_iso,
            "sector":                  c.get("sector"),
            "why_selected":            why,
            "return_3d":               o3.get("return_pct"),
            "return_5d":               ret5,
            "max_drawdown_pct":        o5.get("max_drawdown_pct"),
            "outcome_label":           o5.get("outcome_label"),
        })

    rows.sort(key=lambda x: x["return_5d"])
    return rows[:limit]


def _build_missed_section(missed: list[dict], limit: int = 20) -> list[dict]:
    """Section D — Top missed movers enriched with classification flags."""
    _STRICT_CODES  = {"filtered_by_volume_gate", "filtered_by_price_gate"}
    _SIGNAL_CODES  = {"no_structural_signal"}
    _UNIVERSE_CODES = {"not_in_universe", "filtered_as_non_equity"}

    result = []
    for m in missed[:limit]:
        why = m.get("why_missed", "other")
        result.append({
            "symbol":               m.get("symbol"),
            "scan_date":            m.get("scan_date"),
            "price_on_date":        m.get("price_on_date"),
            "future_return_3d":     m.get("future_return_3d"),
            "future_return_5d":     m.get("future_return_5d"),
            "future_return_10d":    m.get("future_return_10d"),
            "why_missed":           why,
            "was_in_universe":      why not in _UNIVERSE_CODES,
            "was_filtered_pre_score": why in _STRICT_CODES,
            "had_no_signal":        why in _SIGNAL_CODES,
            "details":              m.get("details", {}),
        })
    return result


def _build_pattern_review(summary: dict,
                           perf_tier: list,
                           perf_np_label: list,
                           false_positives: list, missed: list,
                           perf_np_setup_type: list = None,
                           perf_np_freshness: list = None) -> dict:
    """Section E — Deterministic pattern analysis (New Pump-centric)."""
    what_worked:    list = []
    what_failed:    list = []
    missed_patterns: list = []
    likely_strict:  list = []
    likely_noisy:   list = []
    suggested_focus: list = []

    total5 = summary.get("total_outcomes_5d", 0)
    lc     = summary.get("outcome_label_counts", {})
    avg5   = summary.get("avg_return_5d")
    wr5    = summary.get("win_rate_5d")

    # ── Overall performance ───────────────────────────────────────────────────
    if avg5 is not None:
        if avg5 >= 5.0 and (wr5 or 0) >= 55:
            what_worked.append(
                f"Overall avg 5d return {avg5:+.1f}% with {wr5:.0f}% win rate — solid signal quality"
            )
        elif avg5 < 0:
            what_failed.append(
                f"Negative avg 5d return ({avg5:+.1f}%) — net losing batch"
            )

    # ── Best / worst tier ────────────────────────────────────────────────────
    if perf_tier:
        best  = max(perf_tier, key=lambda x: x.get("avg_return_5d") or -999)
        worst = min(perf_tier, key=lambda x: x.get("avg_return_5d") or  999)
        if (best.get("avg_return_5d") or 0) >= 3.0:
            what_worked.append(
                f"{best['bucket']} tier: avg 5d {best['avg_return_5d']:+.1f}%, "
                f"win {best.get('win_rate_5d') or 0:.0f}% ({best['count']} candidates)"
            )
        if (worst.get("avg_return_5d") or 0) < -2.0:
            what_failed.append(
                f"{worst['bucket']} tier: avg 5d {worst['avg_return_5d']:+.1f}% "
                f"({worst['count']} candidates)"
            )

    # ── New Pump label signal quality ─────────────────────────────────────────
    _NP_ORDER = ["NEW_PUMP_FIRE", "NEW_PUMP_STRONG", "NEW_PUMP_SETUP",
                 "NEW_PUMP_TRIGGER_ONLY", "NEW_PUMP_WEAK", "NEW_PUMP_NONE"]
    np_fire  = next((x for x in perf_np_label if x["bucket"] == "NEW_PUMP_FIRE"),  None)
    np_none  = next((x for x in perf_np_label if x["bucket"] == "NEW_PUMP_NONE"),  None)
    np_weak  = next((x for x in perf_np_label if x["bucket"] == "NEW_PUMP_WEAK"),  None)
    np_setup = next((x for x in perf_np_label if x["bucket"] == "NEW_PUMP_SETUP"), None)

    if np_fire and np_none:
        f5 = np_fire.get("avg_return_5d") or 0
        n5 = np_none.get("avg_return_5d") or 0
        if f5 - n5 >= 3 and np_fire.get("count", 0) >= 2:
            what_worked.append(
                f"NEW_PUMP_FIRE avg 5d {f5:+.1f}% vs NONE {n5:+.1f}% "
                f"({np_fire['count']} FIRE candidates) — label discriminates well"
            )
        elif f5 - n5 < 1 and np_fire.get("count", 0) >= 3:
            what_failed.append(
                f"NEW_PUMP_FIRE shows no meaningful edge vs NONE ({f5:+.1f}% vs {n5:+.1f}%) — "
                "FIRE threshold may be too permissive"
            )

    if np_setup:
        s5 = np_setup.get("avg_return_5d") or 0
        if s5 >= 4.0 and np_setup.get("count", 0) >= 3:
            what_worked.append(
                f"NEW_PUMP_SETUP shows early edge {s5:+.1f}% avg 5d — "
                "early setup detection is working"
            )
        elif s5 < -1.0 and np_setup.get("count", 0) >= 3:
            what_failed.append(
                f"NEW_PUMP_SETUP avg 5d {s5:+.1f}% — setup signals may not be resolving"
            )

    if np_weak:
        w5 = np_weak.get("avg_return_5d") or 0
        if w5 < -2.0 and np_weak.get("count", 0) >= 3:
            likely_noisy.append(
                f"NEW_PUMP_WEAK avg 5d {w5:+.1f}% — weak signals are destructive; "
                "consider raising min score threshold"
            )

    # ── False positive rate ───────────────────────────────────────────────────
    if total5 > 0:
        fp_count = lc.get("FALSE_POSITIVE", 0) + lc.get("FAILED_BREAKOUT", 0)
        fp_rate  = _pct(fp_count, total5)
        if fp_rate >= 35:
            likely_noisy.append(
                f"False positive/failed rate {fp_rate:.0f}% — scoring may be too permissive"
            )
        elif fp_rate <= 15 and total5 >= 5:
            what_worked.append(f"Low false-positive/failed rate: {fp_rate:.0f}%")

    # ── Missed mover analysis ─────────────────────────────────────────────────
    if missed:
        reason_counts = Counter(m.get("why_missed") for m in missed if m.get("why_missed"))
        for reason, count in reason_counts.most_common(4):
            missed_patterns.append(f"{reason}: {count} strong movers")
            if reason == "filtered_by_volume_gate":
                likely_strict.append(
                    f"Volume gate filtered {count} strong mover(s) — consider lowering MIN_VOLUME"
                )
            elif reason == "filtered_by_price_gate":
                likely_strict.append(
                    f"Price gate filtered {count} strong mover(s) — review MIN/MAX price bounds"
                )
            elif reason == "no_structural_signal":
                likely_noisy.append(
                    f"{count} strong mover(s) had no New Pump structural signal — "
                    "check if L34/FRI34/G4/B2 thresholds are too strict"
                )

    # ── NP setup type analysis ────────────────────────────────────────────────
    np_setup_insights: list[str] = []
    if perf_np_setup_type:
        by_st = {b["bucket"]: b for b in perf_np_setup_type}
        l34  = by_st.get("L34");   fri34 = by_st.get("FRI34")
        none = by_st.get("NONE");  iso   = by_st.get("BOTH")
        if l34 and fri34 and l34.get("count", 0) >= 2 and fri34.get("count", 0) >= 2:
            l5 = l34.get("avg_return_5d") or 0
            f5 = fri34.get("avg_return_5d") or 0
            if l5 - f5 >= 2:
                np_setup_insights.append(
                    f"L34-based setups outperform FRI34 ({l5:+.1f}% vs {f5:+.1f}% avg 5d)"
                )
            elif f5 - l5 >= 2:
                np_setup_insights.append(
                    f"FRI34-based setups outperform L34 ({f5:+.1f}% vs {l5:+.1f}% avg 5d)"
                )
        if none and (none.get("avg_return_5d") or 0) < -2.0 and none.get("count", 0) >= 3:
            np_setup_insights.append(
                f"Candidates with no setup signal (np_setup_via=NONE) avg 5d "
                f"{none['avg_return_5d']:+.1f}% — no-setup candidates are destructive"
            )
            likely_noisy.append(
                f"np_setup_via=NONE group avg 5d {none['avg_return_5d']:+.1f}% — "
                "filter out candidates without L34/FRI34 setup"
            )

    # ── NP freshness analysis ─────────────────────────────────────────────────
    np_freshness_insights: list[str] = []
    if perf_np_freshness:
        by_fr = {b["bucket"]: b for b in perf_np_freshness}
        fresh = by_fr.get("FRESH");  stale = by_fr.get("STALE")
        if fresh and stale and fresh.get("count", 0) >= 2 and stale.get("count", 0) >= 2:
            fr5 = fresh.get("avg_return_5d") or 0
            st5 = stale.get("avg_return_5d") or 0
            if fr5 - st5 >= 3:
                np_freshness_insights.append(
                    f"Fresh setups (age ≤ 3) avg 5d {fr5:+.1f}% vs stale {st5:+.1f}% — freshness strongly discriminates"
                )
                what_worked.append(
                    f"np_freshness=FRESH avg 5d {fr5:+.1f}% — signal age is a strong filter"
                )
            elif st5 - fr5 >= 3:
                np_freshness_insights.append(
                    f"Stale setups outperforming fresh ({st5:+.1f}% vs {fr5:+.1f}%) — unexpected; inspect regime"
                )

    # ── Suggested focus ───────────────────────────────────────────────────────
    if what_worked:
        suggested_focus.append(f"Double down on: {what_worked[0]}")
    if likely_strict:
        suggested_focus.append(f"Loosen filter: {likely_strict[0]}")
    if likely_noisy:
        suggested_focus.append(f"Tighten filter or review: {likely_noisy[0]}")
    if what_failed:
        suggested_focus.append(f"Investigate: {what_failed[0]}")

    return {
        "what_worked":              what_worked,
        "what_failed":              what_failed,
        "missed_patterns":          missed_patterns,
        "likely_strict_filters":    likely_strict,
        "likely_noisy_filters":     likely_noisy,
        "suggested_focus":          suggested_focus,
        "np_setup_type_insights":   np_setup_insights,
        "np_freshness_insights":    np_freshness_insights,
    }


def _build_experiments(summary: dict,
                        perf_tier: list,
                        perf_np_label: list,
                        missed: list, pattern: dict) -> list[dict]:
    """Section F — Proposal-only experiments (New Pump-centric). NEVER auto-applied."""
    experiments: list[dict] = []

    lc     = summary.get("outcome_label_counts", {})
    total5 = summary.get("total_outcomes_5d", 0)

    # ── Volume gate ───────────────────────────────────────────────────────────
    vol_missed = sum(1 for m in missed if m.get("why_missed") == "filtered_by_volume_gate")
    if vol_missed >= 2:
        experiments.append({
            "title":           "Lower MIN_VOLUME threshold",
            "description":     f"{vol_missed} strong mover(s) were eliminated by the volume gate. "
                               "Test with MIN_VOLUME=50_000 to capture lower-liquidity breakouts.",
            "evidence":        f"{vol_missed} missed movers had why_missed='filtered_by_volume_gate'",
            "confidence":      "MEDIUM" if vol_missed >= 3 else "LOW",
            "experiment_type": "threshold",
        })

    # ── Price gate ────────────────────────────────────────────────────────────
    price_missed = sum(1 for m in missed if m.get("why_missed") == "filtered_by_price_gate")
    if price_missed >= 2:
        experiments.append({
            "title":           "Expand price range",
            "description":     f"{price_missed} strong mover(s) were outside the MIN/MAX price gate. "
                               "Consider raising MAX_PRICE or testing a high-price bucket separately.",
            "evidence":        f"{price_missed} missed movers had why_missed='filtered_by_price_gate'",
            "confidence":      "MEDIUM" if price_missed >= 3 else "LOW",
            "experiment_type": "threshold",
        })

    # ── No-structural-signal misses ───────────────────────────────────────────
    signal_missed = sum(1 for m in missed if m.get("why_missed") == "no_structural_signal")
    if signal_missed >= 3:
        experiments.append({
            "title":           "Investigate no-New-Pump-signal missed movers",
            "description":     f"{signal_missed} strong movers were in the universe but had no "
                               "L34/FRI34/G4/B2 signal. Review their bar-level anatomy to see "
                               "if a new signal pattern is being missed.",
            "evidence":        f"{signal_missed} missed movers had why_missed='no_structural_signal'",
            "confidence":      "MEDIUM",
            "experiment_type": "scoring_review",
        })

    # ── New Pump label FIRE vs NONE spread ───────────────────────────────────
    np_fire = next((x for x in perf_np_label if x["bucket"] == "NEW_PUMP_FIRE"),  None)
    np_none = next((x for x in perf_np_label if x["bucket"] == "NEW_PUMP_NONE"),  None)
    if np_fire and np_none:
        f5 = np_fire.get("avg_return_5d") or 0
        n5 = np_none.get("avg_return_5d") or 0
        if f5 - n5 >= 4 and np_fire.get("count", 0) >= 3:
            experiments.append({
                "title":           "Elevate NEW_PUMP_FIRE to priority bucket",
                "description":     "FIRE label shows a meaningful avg return edge. "
                                   "Consider restricting alerts to FIRE+STRONG labels only.",
                "evidence":        f"FIRE avg 5d {f5:+.1f}% vs NONE {n5:+.1f}% (delta {f5-n5:+.1f}%)",
                "confidence":      "HIGH" if f5 - n5 >= 7 else "MEDIUM",
                "experiment_type": "bucket_split",
            })
        elif n5 - f5 >= 3 and np_fire.get("count", 0) >= 3:
            experiments.append({
                "title":           "Review NEW_PUMP_FIRE signal quality",
                "description":     "FIRE label underperforms NONE. Score thresholds or "
                                   "sequence validity gates may be mis-calibrated for this regime.",
                "evidence":        f"FIRE avg 5d {f5:+.1f}% vs NONE {n5:+.1f}%",
                "confidence":      "MEDIUM",
                "experiment_type": "threshold",
            })

    # ── Setup-only quality ────────────────────────────────────────────────────
    np_setup = next((x for x in perf_np_label if x["bucket"] == "NEW_PUMP_SETUP"), None)
    np_trig  = next((x for x in perf_np_label if x["bucket"] == "NEW_PUMP_TRIGGER_ONLY"), None)
    if np_setup and np_trig:
        s5 = np_setup.get("avg_return_5d") or 0
        t5 = np_trig.get("avg_return_5d")  or 0
        if s5 >= 3.0 and s5 > t5 and np_setup.get("count", 0) >= 3:
            experiments.append({
                "title":           "Reward early setup sequences more aggressively",
                "description":     "SETUP label is outperforming TRIGGER_ONLY. "
                                   "Increase L34/FRI34 setup_score weights; early entry is showing edge.",
                "evidence":        f"SETUP avg 5d {s5:+.1f}% vs TRIGGER_ONLY {t5:+.1f}%",
                "confidence":      "MEDIUM",
                "experiment_type": "ranking_adjustment",
            })

    # ── Full sequence quality (FIRE vs STRONG) ───────────────────────────────
    np_strong = next((x for x in perf_np_label if x["bucket"] == "NEW_PUMP_STRONG"), None)
    if np_fire and np_strong and np_fire.get("count", 0) >= 3 and np_strong.get("count", 0) >= 3:
        fire5   = np_fire.get("avg_return_5d")   or 0
        strong5 = np_strong.get("avg_return_5d") or 0
        if strong5 - fire5 >= 3:
            experiments.append({
                "title":           "STRONG label outperforming FIRE — review score boundary",
                "description":     "Candidates labelled STRONG (46–61) are performing better than FIRE (62+). "
                                   "The FIRE threshold may be attracting over-extended sequences.",
                "evidence":        f"STRONG avg 5d {strong5:+.1f}% vs FIRE {fire5:+.1f}%",
                "confidence":      "MEDIUM",
                "experiment_type": "threshold",
            })

    # ── High false-positive rate ──────────────────────────────────────────────
    if total5 > 0:
        fp_count = lc.get("FALSE_POSITIVE", 0) + lc.get("FAILED_BREAKOUT", 0)
        fp_rate  = _pct(fp_count, total5)
        if fp_rate >= 35:
            experiments.append({
                "title":           "Tighten New Pump sequence validity gates",
                "description":     f"False-positive/failed rate is {fp_rate:.0f}%. "
                                   "Test tightening _MAX_SETUP_AGE or _MAX_TRIG_CONF_GAP to filter "
                                   "stale sequences that are generating noise.",
                "evidence":        f"{fp_count}/{total5} 5d outcomes were FAILED/FALSE_POSITIVE ({fp_rate:.0f}%)",
                "confidence":      "MEDIUM",
                "experiment_type": "threshold",
            })

    # ── BASE tier underperformance ────────────────────────────────────────────
    base = next((x for x in perf_tier if x["bucket"] == "BASE"), None)
    fire = next((x for x in perf_tier if x["bucket"] == "FIRE"), None)
    if base and fire:
        b5 = base.get("avg_return_5d") or 0
        f5 = fire.get("avg_return_5d") or 0
        if b5 < -1.0 and base.get("count", 0) >= 3:
            experiments.append({
                "title":           "Raise BASE tier minimum score",
                "description":     f"BASE tier avg 5d is {b5:+.1f}%, vs FIRE {f5:+.1f}%. "
                                   "Consider raising the BASE entry threshold or removing it from alerts.",
                "evidence":        f"BASE avg 5d {b5:+.1f}%, count={base.get('count')}; "
                                   f"FIRE avg 5d {f5:+.1f}%",
                "confidence":      "MEDIUM",
                "experiment_type": "threshold",
            })

    # Sort by confidence
    _conf_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    experiments.sort(key=lambda x: _conf_order.get(x["confidence"], 3))

    return experiments


# ── Main entry point ──────────────────────────────────────────────────────────

async def build_research_bundle(run_id: int) -> dict:
    """
    Build and return the full research bundle for a replay run.
    All data is loaded from replay-scoped DB tables only.
    Returns a stable dict shape regardless of data completeness.
    """
    from database import (
        get_replay_run, get_replay_candidates,
        get_replay_outcomes, get_replay_missed_movers,
    )

    # ── Load all data ─────────────────────────────────────────────────────────
    run = await get_replay_run(run_id)
    if not run:
        raise ValueError(f"Replay run {run_id} not found")

    candidates = await get_replay_candidates(run_id, limit=5000)
    outcomes   = await get_replay_outcomes(run_id)
    missed     = await get_replay_missed_movers(run_id)

    outcome_map = _build_outcome_map(outcomes)

    # ── Section A: Summary ────────────────────────────────────────────────────
    summary = _build_summary(run, candidates, outcomes, missed)

    # ── Section B: Performance by bucket ─────────────────────────────────────
    perf_tier = _build_perf_buckets(
        candidates, outcome_map,
        lambda c: c.get("tier") or "UNKNOWN",
        "tier",
    )

    # ── New Pump Engine buckets ───────────────────────────────────────────────
    _NP_LABEL_ORDER = [
        "NEW_PUMP_FIRE", "NEW_PUMP_STRONG", "NEW_PUMP_SETUP",
        "NEW_PUMP_TRIGGER_ONLY", "NEW_PUMP_WEAK", "NEW_PUMP_NONE",
    ]
    perf_new_pump_label = _build_perf_buckets(
        candidates, outcome_map,
        lambda c: c.get("new_pump_label") or "NEW_PUMP_NONE",
        "new_pump_label",
    )
    perf_new_pump_label.sort(
        key=lambda x: _NP_LABEL_ORDER.index(x["bucket"])
        if x["bucket"] in _NP_LABEL_ORDER else 99
    )

    perf_new_pump_seq = _build_perf_buckets(
        candidates, outcome_map,
        lambda c: c.get("new_pump_sequence_label") or "NONE",
        "new_pump_sequence",
    )

    _NP_SETUP_ORDER = ["L34", "FRI34", "BOTH", "NONE"]
    perf_np_setup_type = _build_perf_buckets(
        candidates, outcome_map,
        lambda c: c.get("np_setup_via") or "NONE",
        "np_setup_via",
    )
    perf_np_setup_type.sort(
        key=lambda x: _NP_SETUP_ORDER.index(x["bucket"])
        if x["bucket"] in _NP_SETUP_ORDER else 99
    )

    def _np_freshness_tier(c: dict) -> str:
        age_l34   = c.get("np_age_l34")
        age_fri34 = c.get("np_age_fri34")
        ages = [a for a in [age_l34, age_fri34] if a is not None]
        if not ages:
            return "NO_SETUP"
        age = min(ages)
        if age <= 3:   return "FRESH"
        if age <= 7:   return "MODERATE"
        return "STALE"

    _NP_FRESH_ORDER = ["FRESH", "MODERATE", "STALE", "NO_SETUP"]
    perf_np_freshness = _build_perf_buckets(
        candidates, outcome_map,
        _np_freshness_tier,
        "np_freshness",
    )
    perf_np_freshness.sort(
        key=lambda x: _NP_FRESH_ORDER.index(x["bucket"])
        if x["bucket"] in _NP_FRESH_ORDER else 99
    )

    # ── Sections C, D: False positives + Missed movers ────────────────────────
    false_positives = _build_false_positives(candidates, outcome_map)
    missed_section  = _build_missed_section(missed)

    # ── Section E: Pattern review ─────────────────────────────────────────────
    pattern_review = _build_pattern_review(
        summary, perf_tier, perf_new_pump_label,
        false_positives, missed_section,
        perf_np_setup_type=perf_np_setup_type,
        perf_np_freshness=perf_np_freshness,
    )

    # ── Section F: Suggested experiments ─────────────────────────────────────
    suggested_experiments = _build_experiments(
        summary, perf_tier, perf_new_pump_label,
        missed_section, pattern_review,
    )

    bundle = {
        "run":                              run,
        "summary":                          summary,
        "performance_by_tier":              perf_tier,
        "performance_by_new_pump_label":    perf_new_pump_label,
        "performance_by_new_pump_sequence": perf_new_pump_seq,
        "performance_by_np_setup_type":     perf_np_setup_type,
        "performance_by_np_freshness":      perf_np_freshness,
        "false_positives":                  false_positives,
        "missed_movers":                    missed_section,
        "pattern_review":                   pattern_review,
        "suggested_experiments":            suggested_experiments,
    }

    logger.info(
        f"[BUNDLE] run_id={run_id} built: "
        f"{len(candidates)} cands, {len(false_positives)} FPs, "
        f"{len(missed_section)} missed, {len(suggested_experiments)} experiments"
    )
    return bundle


# ── Markdown renderer ─────────────────────────────────────────────────────────

def _mdtable(headers: list[str], rows: list[list]) -> str:
    """Render a compact Markdown pipe table."""
    header = "| " + " | ".join(headers) + " |"
    sep    = "| " + " | ".join("---" for _ in headers) + " |"
    body   = "\n".join("| " + " | ".join(str(v) for v in row) + " |" for row in rows)
    return "\n".join([header, sep, body]) if rows else f"*No data*"


def _fmt(v, sign: bool = False, suffix: str = "") -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        s = f"{v:+.1f}" if sign else f"{v:.1f}"
        return s + suffix
    return str(v) + suffix


def render_research_bundle_markdown(bundle: dict) -> str:
    """
    Render the research bundle as a concise, human-readable Markdown report.
    Designed to be pasted into AI chat for further analysis.
    """
    s    = bundle.get("summary", {})
    run  = bundle.get("run", {})
    lc   = s.get("outcome_label_counts", {})

    lines: list[str] = []
    add = lines.append

    # ── Header ────────────────────────────────────────────────────────────────
    run_date = (
        run.get("as_of_date") or
        f"{run.get('start_date')} → {run.get('end_date')}"
    )
    add(f"# Replay Research Bundle — Run #{s.get('run_id')}")
    add(f"**Date:** {run_date} | "
        f"**Mode:** {run.get('mode', '?')} | "
        f"**Universe:** {run.get('universe_mode', '?')}")
    add(f"**Candidates:** {s.get('total_candidates', 0)} | "
        f"**Outcomes (5d):** {s.get('total_outcomes_5d', 0)} | "
        f"**Missed Movers:** {s.get('total_missed_movers', 0)}")
    add("")

    # ── Section A: Performance Summary ───────────────────────────────────────
    add("---")
    add("")
    add("## Performance Summary")
    add("")
    add(_mdtable(
        ["Horizon", "Avg Return", "Win Rate", "α vs SPY"],
        [
            ["1d",  _fmt(s.get("avg_return_1d"),  sign=True, suffix="%"),
                    _fmt(s.get("win_rate_3d"), suffix="%"),  "—"],
            ["3d",  _fmt(s.get("avg_return_3d"),  sign=True, suffix="%"),
                    _fmt(s.get("win_rate_3d"), suffix="%"),  "—"],
            ["5d",  _fmt(s.get("avg_return_5d"),  sign=True, suffix="%"),
                    _fmt(s.get("win_rate_5d"), suffix="%"),
                    _fmt(s.get("avg_alpha_vs_spy_5d"),  sign=True, suffix="%")],
            ["10d", _fmt(s.get("avg_return_10d"), sign=True, suffix="%"),
                    "—",
                    _fmt(s.get("avg_alpha_vs_spy_10d"), sign=True, suffix="%")],
        ]
    ))
    add("")
    add("**Outcome Distribution (5d):**")
    label_parts = [
        f"✅ Breakout: {lc.get('SUCCESSFUL_BREAKOUT', 0)}",
        f"⚡ Early Win: {lc.get('EARLY_WINNER', 0)}",
        f"😐 No Follow: {lc.get('NO_FOLLOW_THROUGH', 0)}",
        f"🕐 Late: {lc.get('LATE_SIGNAL', 0)}",
        f"❌ Failed: {lc.get('FAILED_BREAKOUT', 0)}",
        f"🚫 False Pos: {lc.get('FALSE_POSITIVE', 0)}",
    ]
    add("  ".join(label_parts))
    add("")

    # ── Section B: Performance by Bucket ─────────────────────────────────────
    def _bucket_section(title: str, perf_list: list):
        add(f"## {title}")
        add("")
        if not perf_list:
            add("*No data*")
            add("")
            return
        rows = []
        for b in perf_list:
            rows.append([
                b["bucket"],
                b.get("count", 0),
                _fmt(b.get("avg_return_5d"),  sign=True, suffix="%"),
                _fmt(b.get("win_rate_5d"),                suffix="%"),
                _fmt(b.get("avg_return_10d"), sign=True, suffix="%"),
                _fmt(b.get("avg_max_drawdown_pct"), sign=True, suffix="%"),
                _fmt(b.get("alpha_vs_spy_5d"),     sign=True, suffix="%"),
            ])
        add(_mdtable(
            ["Bucket", "Count", "Avg 5d", "Win%", "Avg 10d", "Avg DD", "α/SPY"],
            rows,
        ))
        add("")

    _bucket_section("Performance by New Pump Label",    bundle.get("performance_by_new_pump_label", []))
    _bucket_section("Performance by New Pump Sequence", bundle.get("performance_by_new_pump_sequence", []))
    _bucket_section("Performance by NP Setup Type (L34 / FRI34 / BOTH / NONE)", bundle.get("performance_by_np_setup_type", []))
    _bucket_section("Performance by NP Setup Freshness", bundle.get("performance_by_np_freshness", []))
    _bucket_section("Performance by Tier",              bundle.get("performance_by_tier", []))

    # ── Section C: Top False Positives ────────────────────────────────────────
    add("## Top False Positives")
    add("")
    fps = bundle.get("false_positives", [])
    if fps:
        rows = []
        for fp in fps[:10]:
            iso_flag = "⚠️ ISO" if fp.get("np_is_isolated_trigger") else ""
            rows.append([
                fp.get("symbol", "?"),
                fp.get("tier", "?"),
                fp.get("new_pump_label") or "—",
                fp.get("np_setup_via") or "—",
                iso_flag,
                _fmt(fp.get("return_3d"), sign=True, suffix="%"),
                _fmt(fp.get("return_5d"), sign=True, suffix="%"),
                _fmt(fp.get("max_drawdown_pct"), sign=True, suffix="%"),
            ])
        add(_mdtable(
            ["Symbol", "Tier", "NP Label", "Setup Via", "Isolated?", "3d", "5d", "MaxDD"],
            rows,
        ))
    else:
        add("*No significant false positives in this run.*")
    add("")

    # ── Section D: Top Missed Movers ─────────────────────────────────────────
    add("## Top Missed Movers")
    add("")
    mm = bundle.get("missed_movers", [])
    if mm:
        rows = []
        for m in mm[:10]:
            rows.append([
                m.get("symbol", "?"),
                _fmt(m.get("future_return_3d"), sign=True, suffix="%"),
                _fmt(m.get("future_return_5d"), sign=True, suffix="%"),
                _fmt(m.get("future_return_10d"), sign=True, suffix="%"),
                m.get("why_missed") or "—",
            ])
        add(_mdtable(
            ["Symbol", "3d Ret", "5d Ret", "10d Ret", "Why Missed"],
            rows,
        ))
    else:
        add("*No significant missed movers for this run.*")
    add("")

    # ── Section E: Pattern Review ─────────────────────────────────────────────
    add("## Pattern Review")
    add("")
    pr = bundle.get("pattern_review", {})

    def _bullet_list(header: str, items: list):
        if not items:
            return
        add(f"**{header}**")
        for item in items:
            add(f"- {item}")
        add("")

    _bullet_list("What Worked",            pr.get("what_worked", []))
    _bullet_list("What Failed",            pr.get("what_failed", []))
    _bullet_list("NP Setup Type Insights", pr.get("np_setup_type_insights", []))
    _bullet_list("NP Freshness Insights",  pr.get("np_freshness_insights", []))
    _bullet_list("Missed Patterns",        pr.get("missed_patterns", []))
    _bullet_list("Likely Too Strict",      pr.get("likely_strict_filters", []))
    _bullet_list("Likely Too Noisy",       pr.get("likely_noisy_filters", []))
    _bullet_list("Suggested Focus",        pr.get("suggested_focus", []))

    if not any(pr.get(k) for k in ["what_worked", "what_failed", "missed_patterns"]):
        add("*Insufficient data to generate pattern review.*")
        add("")

    # ── Section F: Suggested Experiments ─────────────────────────────────────
    add("## Suggested Experiments")
    add("")
    add("> ⚠️ These are research proposals only. No experiment is auto-applied.")
    add("")
    exps = bundle.get("suggested_experiments", [])
    if exps:
        for i, e in enumerate(exps, 1):
            conf_icon = {"HIGH": "🟢", "MEDIUM": "🟡", "LOW": "⚪"}.get(e.get("confidence"), "⚪")
            add(f"### {i}. {e.get('title', 'Untitled')}")
            add(f"**Type:** `{e.get('experiment_type', '?')}` {conf_icon} {e.get('confidence', '?')} confidence")
            add("")
            add(e.get("description", ""))
            add("")
            add(f"*Evidence: {e.get('evidence', '—')}*")
            add("")
    else:
        add("*No experiments suggested for this run — data may be insufficient.*")
        add("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════════════════════
# Raw Pattern Study — NP Count-Based Research Bundle
# ═══════════════════════════════════════════════════════════════════════════════

def _median(vals: list) -> Optional[float]:
    cleaned = sorted(v for v in vals if v is not None)
    n = len(cleaned)
    if n == 0:
        return None
    mid = n // 2
    return round((cleaned[mid - 1] + cleaned[mid]) / 2 if n % 2 == 0 else cleaned[mid], 2)


_NP_COUNT_FIELDS = [
    "l34_count_pre", "fri34_count_pre", "g4_count_pre", "b2_count_pre",
    "setup_only_l34_count_pre", "setup_only_fri34_count_pre",
    "trigger_after_l34_count_pre", "trigger_after_fri34_count_pre",
    "full_l34_g4_b2_count_pre", "full_fri34_g4_b2_count_pre",
    "isolated_g4_count_pre", "isolated_b2_count_pre",
    "confirm_after_g4_count_pre",
    "valid_setup_days_pre", "valid_trigger_days_pre",
    "valid_confirm_days_pre", "valid_full_sequence_days_pre",
]

# Decision-useful subset for separation summary
_NP_COUNT_PRIORITY = [
    "l34_count_pre", "fri34_count_pre",
    "setup_only_l34_count_pre", "trigger_after_fri34_count_pre",
    "full_fri34_g4_b2_count_pre", "isolated_g4_count_pre",
    "isolated_b2_count_pre", "valid_setup_days_pre",
    "valid_full_sequence_days_pre",
]

_GROUPS = ["4x_pump", "false_positive", "normal_winner", "missed_mover"]


def _group_count_stats(ep_rows_by_group: dict) -> dict:
    """
    Returns {field: {group: {median, mean, n, nonzero_pct}}} for all NP count fields.
    """
    out: dict = {}
    for field in _NP_COUNT_FIELDS:
        out[field] = {}
        for grp, rows in ep_rows_by_group.items():
            vals = [r[field] for r in rows if r.get(field) is not None]
            n    = len(rows)
            nv   = len(vals)
            out[field][grp] = {
                "median":      _median(vals),
                "mean":        round(sum(vals) / nv, 2) if nv else None,
                "n":           n,
                "nonzero_pct": round(sum(1 for v in vals if v and v > 0) / n * 100, 1) if n else 0.0,
            }
    return out


def _build_np_count_analysis(ep_rows_by_group: dict) -> dict:
    """Builds NP count analysis sections A–E."""
    gcs = _group_count_stats(ep_rows_by_group)

    def _grp(field, group, stat="median"):
        return (gcs.get(field) or {}).get(group, {}).get(stat)

    # ── Section A: separation summary ─────────────────────────────────────────
    sep_rows = []
    for field in _NP_COUNT_PRIORITY:
        p4  = _grp(field, "4x_pump")
        pfp = _grp(field, "false_positive")
        pnw = _grp(field, "normal_winner")
        if p4 is None and pfp is None:
            continue
        lift = round(p4 - pfp, 2) if p4 is not None and pfp is not None else None
        sep_rows.append({
            "field":         field,
            "pump_median":   p4,
            "fp_median":     pfp,
            "nw_median":     pnw,
            "lift_4x_vs_fp": lift,
            "pump_n":        _grp(field, "4x_pump", "n"),
            "fp_n":          _grp(field, "false_positive", "n"),
        })
    sep_rows.sort(key=lambda r: abs(r.get("lift_4x_vs_fp") or 0), reverse=True)

    # ── Section B: repeated setup insights ───────────────────────────────────
    setup_insights: list[str] = []
    p4_l34  = _grp("l34_count_pre",        "4x_pump")
    fp_l34  = _grp("l34_count_pre",        "false_positive")
    p4_vsd  = _grp("valid_setup_days_pre", "4x_pump")
    fp_vsd  = _grp("valid_setup_days_pre", "false_positive")
    p4_so   = _grp("setup_only_l34_count_pre", "4x_pump")

    if p4_l34 is not None and fp_l34 is not None:
        delta = round(p4_l34 - fp_l34, 2)
        if delta > 0.5:
            setup_insights.append(
                f"Repeated L34 setup correlates with 4x: 4x_pump med={p4_l34} vs FP med={fp_l34} (Δ{delta:+.2f})"
            )
        elif delta < -0.5:
            setup_insights.append(
                f"L34 setup count higher in FP (med {fp_l34}) than 4x (med {p4_l34}) — repeated setup alone is not discriminating"
            )
        else:
            setup_insights.append(f"L34 setup count similar across groups: 4x={p4_l34}, FP={fp_l34}")
    if p4_vsd is not None and fp_vsd is not None:
        delta = round(p4_vsd - fp_vsd, 2)
        if delta > 1:
            setup_insights.append(
                f"Persistent valid setup (valid_setup_days): 4x med={p4_vsd} > FP med={fp_vsd} — sustained structure matters"
            )
        elif delta < -1:
            setup_insights.append(
                f"FP has more valid_setup_days (med {fp_vsd}) than 4x (med {p4_vsd}) — freshness density not a clean separator here"
            )
    if p4_so is not None:
        fp_so = _grp("setup_only_l34_count_pre", "false_positive")
        setup_insights.append(
            f"setup_only_l34 (setup fires without trigger): 4x med={p4_so}, FP med={fp_so}"
        )

    # ── Section C: isolated signal insights ──────────────────────────────────
    iso_insights: list[str] = []
    for sig, label in [("isolated_g4_count_pre", "G4"), ("isolated_b2_count_pre", "B2")]:
        p4v  = _grp(sig, "4x_pump")
        fpv  = _grp(sig, "false_positive")
        if p4v is None and fpv is None:
            continue
        if fpv is not None and p4v is not None:
            if fpv > p4v + 0.3:
                iso_insights.append(
                    f"Isolated {label} is a red flag: FP med={fpv} > 4x med={p4v} — trigger/confirm without setup accumulates in false positives"
                )
            elif p4v > fpv + 0.3:
                iso_insights.append(f"Isolated {label}: 4x med={p4v} > FP med={fpv} — unexpected; inspect outliers")
            else:
                iso_insights.append(f"Isolated {label} similar: 4x={p4v}, FP={fpv}")

    # ── Section D: full-sequence density insights ─────────────────────────────
    seq_insights: list[str] = []
    for f, label in [
        ("full_fri34_g4_b2_count_pre", "full_FRI34→G4→B2"),
        ("full_l34_g4_b2_count_pre",   "full_L34→G4→B2"),
        ("valid_full_sequence_days_pre", "valid_full_seq_days"),
    ]:
        p4v = _grp(f, "4x_pump")
        fpv = _grp(f, "false_positive")
        if p4v is None and fpv is None:
            continue
        delta = round(p4v - fpv, 2) if p4v is not None and fpv is not None else None
        note = ""
        if delta is not None:
            if abs(delta) < 0.3:
                note = "— similar; repeated full-sequence may be noisy, not separating"
            elif delta > 0:
                note = f"— 4x higher by {delta:+.2f}"
            else:
                note = f"— FP higher by {abs(delta):.2f}; repeated full-sequence could indicate over-extended chasing"
        seq_insights.append(f"{label}: 4x med={p4v}, FP med={fpv} {note}".strip())

    # ── Section E: validity density insights ─────────────────────────────────
    valid_insights: list[str] = []
    for f in ["valid_setup_days_pre", "valid_trigger_days_pre",
              "valid_confirm_days_pre", "valid_full_sequence_days_pre"]:
        p4v = _grp(f, "4x_pump")
        fpv = _grp(f, "false_positive")
        if p4v is None and fpv is None:
            continue
        delta = round(p4v - fpv, 2) if p4v is not None and fpv is not None else None
        direction = f"Δ{delta:+.2f}" if delta is not None else "—"
        valid_insights.append(f"{f}: 4x med={p4v}, FP med={fpv} ({direction})")

    # ── Pattern review (count-based) ─────────────────────────────────────────
    count_review: list[str] = []
    # L34 setup density vs full-sequence density
    p4_l34   = _grp("l34_count_pre",        "4x_pump")
    p4_full  = _grp("full_fri34_g4_b2_count_pre", "4x_pump")
    fp_full  = _grp("full_fri34_g4_b2_count_pre", "false_positive")
    if p4_l34 and p4_full:
        if p4_l34 > (p4_full or 0):
            count_review.append(
                "Repeated early L34 setup appears stronger signal than repeated full-sequence count "
                f"(4x med: l34_count={p4_l34} > full_fri34_g4_b2={p4_full})"
            )
    iso_g4_fp = _grp("isolated_g4_count_pre", "false_positive")
    iso_g4_4x = _grp("isolated_g4_count_pre", "4x_pump")
    if iso_g4_fp is not None and iso_g4_4x is not None and iso_g4_fp > iso_g4_4x:
        count_review.append(
            "Isolated G4 clusters appear noisy/false-positive-prone: "
            f"FP med {iso_g4_fp} > 4x med {iso_g4_4x}"
        )
    if fp_full is not None and p4_full is not None and abs(fp_full - p4_full) < 0.3:
        count_review.append(
            "Repeated full-sequence density does not cleanly separate groups — "
            "avoid over-rewarding it vs setup density"
        )
    vsd_4x = _grp("valid_setup_days_pre", "4x_pump")
    vcd_4x = _grp("valid_confirm_days_pre", "4x_pump")
    if vsd_4x and vcd_4x and vsd_4x > vcd_4x:
        count_review.append(
            f"Setup freshness density (valid_setup_days med={vsd_4x}) > "
            f"confirm density (valid_confirm_days med={vcd_4x}) in 4x_pump — "
            "setup density deserves more weight than late confirm density"
        )

    return {
        "field_stats":               gcs,
        "separation_summary":        sep_rows,
        "setup_analysis":            {"insights": setup_insights},
        "isolated_signal_analysis":  {"insights": iso_insights},
        "full_sequence_analysis":    {"insights": seq_insights},
        "validity_density_analysis": {"insights": valid_insights},
        "count_pattern_review":      count_review,
    }


async def build_raw_pattern_research_bundle(raw_run_id: int) -> dict:
    """
    Build NP count-based research bundle for a Raw Pattern Study run.
    Groups episodes by group_type and computes NP count statistics across groups.
    """
    from collections import defaultdict as _dd
    from database import get_raw_pattern_run, get_raw_pattern_episode_features

    run = await get_raw_pattern_run(raw_run_id)
    if not run:
        raise ValueError(f"Raw pattern run {raw_run_id} not found")

    episodes = await get_raw_pattern_episode_features(raw_run_id, limit=2000)

    ep_by_group: dict = _dd(list)
    for ep in episodes:
        g = ep.get("group_type")
        if g:
            ep_by_group[g].append(ep)

    group_counts = {g: len(rows) for g, rows in ep_by_group.items()}
    np_count_analysis = _build_np_count_analysis(dict(ep_by_group)) if ep_by_group else {}

    logger.info(
        f"[RAW_BUNDLE] run_id={raw_run_id} groups: {group_counts} "
        f"count_fields_populated={bool(ep_by_group)}"
    )

    return {
        "run":               run,
        "group_counts":      group_counts,
        "np_count_analysis": np_count_analysis,
        "total_episodes":    len(episodes),
    }


def render_raw_pattern_bundle_markdown(bundle: dict) -> str:
    """Markdown report for a Raw Pattern Study NP count-based research bundle."""
    run  = bundle.get("run", {})
    gcs  = bundle.get("group_counts", {})
    npa  = bundle.get("np_count_analysis", {})

    lines: list[str] = []
    add = lines.append

    add(f"# Raw Pattern Study — NP Count Analysis (Run #{run.get('id', '?')})")
    add(f"**Range:** {run.get('start_date')} → {run.get('end_date')} | "
        f"**Episodes:** {bundle.get('total_episodes', 0)}")
    gc_parts = [f"{g}={n}" for g, n in sorted(gcs.items())]
    add(f"**Groups:** {', '.join(gc_parts) if gc_parts else '—'}")
    add("")

    if not npa:
        add("*No NP count data — run `build_raw_pattern_episode_features_new_pump()` first.*")
        return "\n".join(lines)

    # ── Count-based pattern review ────────────────────────────────────────────
    cpr = npa.get("count_pattern_review", [])
    if cpr:
        add("## Key Findings")
        add("")
        for item in cpr:
            add(f"- {item}")
        add("")

    # ── Section A: separation summary ─────────────────────────────────────────
    add("---")
    add("")
    add("## A. NP Count-Field Separation  *(4x_pump vs false_positive)*")
    add("")
    sep = npa.get("separation_summary", [])
    if sep:
        rows = []
        for r in sep[:9]:
            short = (r["field"]
                     .replace("_count_pre", "")
                     .replace("_days_pre", " days")
                     .replace("_pre", ""))
            rows.append([
                short,
                _fmt(r.get("pump_median")),
                _fmt(r.get("fp_median")),
                _fmt(r.get("nw_median")),
                (_fmt(r["lift_4x_vs_fp"], sign=True) if r.get("lift_4x_vs_fp") is not None else "—"),
                str(r.get("pump_n") or "—"),
            ])
        add(_mdtable(
            ["Field", "4x median", "FP median", "NW median", "Lift(4x-FP)", "4x n"],
            rows,
        ))
    else:
        add("*No data — count fields may all be null.*")
    add("")

    # ── Section B: repeated setup ─────────────────────────────────────────────
    add("## B. Repeated Setup Analysis")
    add("")
    sa = npa.get("setup_analysis", {}).get("insights", [])
    if sa:
        for i in sa:
            add(f"- {i}")
    else:
        add("*No setup count data.*")
    add("")

    # ── Section C: isolated signals ───────────────────────────────────────────
    add("## C. Isolated-Signal Penalty")
    add("")
    ia = npa.get("isolated_signal_analysis", {}).get("insights", [])
    if ia:
        for i in ia:
            add(f"- {i}")
    else:
        add("*No isolated signal count data.*")
    add("")

    # ── Section D: full-sequence density ──────────────────────────────────────
    add("## D. Full-Sequence Density")
    add("")
    add("> Higher count ≠ better — check direction vs false_positive group.")
    add("")
    fa = npa.get("full_sequence_analysis", {}).get("insights", [])
    if fa:
        for i in fa:
            add(f"- {i}")
    else:
        add("*No full-sequence count data.*")
    add("")

    # ── Section E: validity / freshness density ────────────────────────────────
    add("## E. Validity / Freshness Density")
    add("")
    gcs_full = npa.get("field_stats", {})
    valid_fields = ["valid_setup_days_pre", "valid_trigger_days_pre",
                    "valid_confirm_days_pre", "valid_full_sequence_days_pre"]
    vrows = []
    for f in valid_fields:
        fg = gcs_full.get(f, {})
        if not fg:
            continue
        short = f.replace("_days_pre", "d").replace("_pre", "")
        vrows.append([
            short,
            _fmt((fg.get("4x_pump") or {}).get("median")),
            _fmt((fg.get("false_positive") or {}).get("median")),
            _fmt((fg.get("normal_winner") or {}).get("median")),
            _fmt((fg.get("missed_mover") or {}).get("median")),
        ])
    if vrows:
        add(_mdtable(["Field", "4x_pump", "false_pos", "normal_win", "missed_mv"], vrows))
    va = npa.get("validity_density_analysis", {}).get("insights", [])
    if va:
        add("")
        for i in va:
            add(f"- {i}")
    add("")

    return "\n".join(lines)
