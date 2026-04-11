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

        tier = c.get("tier", "?")
        ign  = c.get("ignition_signal", False)
        rib  = c.get("ribbon_signal", False)
        score = c.get("total_score")

        why = f"{tier} tier"
        if ign and rib:
            why += " | Ignition ✓ | Ribbon ✓"
        elif ign:
            why += " | Ignition ✓"
        elif rib:
            why += " | Ribbon ✓"
        if score is not None:
            why += f" | Score {round(score, 1)}"

        rows.append({
            "symbol":           c.get("symbol", "?"),
            "scan_date":        c.get("scan_date"),
            "tier":             tier,
            "total_score":      score,
            "ignition_signal":  ign,
            "ribbon_signal":    rib,
            "sector":           c.get("sector"),
            "why_selected":     why,
            "return_3d":        o3.get("return_pct"),
            "return_5d":        ret5,
            "max_drawdown_pct": o5.get("max_drawdown_pct"),
            "outcome_label":    o5.get("outcome_label"),
        })

    rows.sort(key=lambda x: x["return_5d"])
    return rows[:limit]


def _build_missed_section(missed: list[dict], limit: int = 20) -> list[dict]:
    """Section D — Top missed movers enriched with classification flags."""
    _STRICT_CODES  = {"filtered_by_volume_gate", "filtered_by_price_gate"}
    _SIGNAL_CODES  = {"no_structural_signal", "no_ignition"}
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
                           perf_tier: list, perf_ribbon: list,
                           perf_ignition: list, perf_source: list,
                           false_positives: list, missed: list) -> dict:
    """Section E — Deterministic pattern analysis."""
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

    # ── Ignition signal lift ─────────────────────────────────────────────────
    ign_true  = next((x for x in perf_ignition if x["bucket"] == "True"),  None)
    ign_false = next((x for x in perf_ignition if x["bucket"] == "False"), None)
    if ign_true and ign_false:
        t5  = ign_true.get("avg_return_5d")  or 0
        f5  = ign_false.get("avg_return_5d") or 0
        lift = round(t5 - f5, 1)
        if lift >= 2:
            what_worked.append(
                f"Ignition signal provides +{lift}% avg 5d lift vs non-ignition"
            )
        elif lift <= -2:
            what_failed.append(
                f"Ignition signal does not improve 5d returns (delta {lift:+.1f}%)"
            )

    # ── Ribbon signal lift ───────────────────────────────────────────────────
    rib_true  = next((x for x in perf_ribbon if x["bucket"] == "True"),  None)
    rib_false = next((x for x in perf_ribbon if x["bucket"] == "False"), None)
    if rib_true and rib_false:
        t5  = rib_true.get("avg_return_5d")  or 0
        f5  = rib_false.get("avg_return_5d") or 0
        lift = round(t5 - f5, 1)
        if lift >= 2:
            what_worked.append(
                f"Ribbon signal provides +{lift}% avg 5d lift vs no-ribbon"
            )
        elif lift <= -2:
            what_failed.append(
                f"Ribbon signal does not improve 5d returns (delta {lift:+.1f}%)"
            )

    # ── False positive rate ───────────────────────────────────────────────────
    if total5 > 0:
        fp_count = lc.get("FALSE_POSITIVE", 0) + lc.get("FAILED_BREAKOUT", 0)
        fp_rate  = _pct(fp_count, total5)
        if fp_rate >= 35:
            likely_noisy.append(
                f"False positive/failed rate {fp_rate:.0f}% — scoring may be too permissive for this date"
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
                    f"{count} strong mover(s) had no structural signal — "
                    "they moved without ribbon/ignition confirmation"
                )

    # ── Source bucket insight ─────────────────────────────────────────────────
    both = next((x for x in perf_source if x["bucket"] == "Ignition+Ribbon"), None)
    none_src = next((x for x in perf_source if x["bucket"] == "Neither"), None)
    if both and none_src:
        b5 = both.get("avg_return_5d") or 0
        n5 = none_src.get("avg_return_5d") or 0
        if b5 - n5 >= 3:
            what_worked.append(
                f"Ignition+Ribbon combo {b5:+.1f}% vs Neither {n5:+.1f}% 5d — "
                "signal stacking shows edge"
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
        "what_worked":          what_worked,
        "what_failed":          what_failed,
        "missed_patterns":      missed_patterns,
        "likely_strict_filters": likely_strict,
        "likely_noisy_filters": likely_noisy,
        "suggested_focus":      suggested_focus,
    }


def _build_experiments(summary: dict,
                        perf_tier: list, perf_ribbon: list,
                        perf_ignition: list, perf_source: list,
                        missed: list, pattern: dict) -> list[dict]:
    """Section F — Proposal-only experiments. NEVER auto-applied."""
    experiments: list[dict] = []

    lc    = summary.get("outcome_label_counts", {})
    total5 = summary.get("total_outcomes_5d", 0)

    # ── Volume gate ───────────────────────────────────────────────────────────
    vol_missed = sum(1 for m in missed if m.get("why_missed") == "filtered_by_volume_gate")
    if vol_missed >= 2:
        experiments.append({
            "title":           "Lower MIN_VOLUME threshold",
            "description":     f"{vol_missed} strong mover(s) were eliminated by the volume gate. "
                               "Test with MIN_VOLUME=100_000 to capture lower-liquidity breakouts.",
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
            "title":           "Investigate no-structural-signal missed movers",
            "description":     f"{signal_missed} strong movers were in the universe but scored SKIP. "
                               "Review their indicator profiles to see if a new signal pattern is being missed.",
            "evidence":        f"{signal_missed} missed movers had why_missed='no_structural_signal'",
            "confidence":      "MEDIUM",
            "experiment_type": "scoring_review",
        })

    # ── Ignition signal tier split ────────────────────────────────────────────
    ign_true  = next((x for x in perf_ignition if x["bucket"] == "True"),  None)
    ign_false = next((x for x in perf_ignition if x["bucket"] == "False"), None)
    if ign_true and ign_false:
        t5 = ign_true.get("avg_return_5d")  or 0
        f5 = ign_false.get("avg_return_5d") or 0
        if t5 - f5 >= 3 and ign_true.get("count", 0) >= 3:
            experiments.append({
                "title":           "Promote ignition-confirmed candidates",
                "description":     "Ignition signal shows a meaningful return edge. "
                                   "Test a dedicated higher-priority bucket or score boost for ignition-confirmed names.",
                "evidence":        f"Ignition=True avg 5d {t5:+.1f}% vs False {f5:+.1f}% (delta {t5-f5:+.1f}%)",
                "confidence":      "HIGH" if t5 - f5 >= 5 else "MEDIUM",
                "experiment_type": "bucket_split",
            })
        elif f5 - t5 >= 3:
            experiments.append({
                "title":           "Review ignition signal reliability",
                "description":     "Non-ignition candidates outperformed ignition ones. "
                                   "Check whether the ignition threshold is too aggressive for this date.",
                "evidence":        f"Ignition=True avg 5d {t5:+.1f}% vs False {f5:+.1f}%",
                "confidence":      "MEDIUM",
                "experiment_type": "threshold",
            })

    # ── Ribbon signal split ───────────────────────────────────────────────────
    rib_true  = next((x for x in perf_ribbon if x["bucket"] == "True"),  None)
    rib_false = next((x for x in perf_ribbon if x["bucket"] == "False"), None)
    if rib_true and rib_false:
        t5 = rib_true.get("avg_return_5d")  or 0
        f5 = rib_false.get("avg_return_5d") or 0
        if t5 - f5 >= 3 and rib_true.get("count", 0) >= 3:
            experiments.append({
                "title":           "Weight ribbon-aligned candidates higher",
                "description":     "Ribbon signal shows a meaningful avg return edge. "
                                   "Test awarding a +5pt score bonus or separate bucket for ribbon-confirmed names.",
                "evidence":        f"Ribbon=True avg 5d {t5:+.1f}% vs False {f5:+.1f}%",
                "confidence":      "HIGH" if t5 - f5 >= 5 else "MEDIUM",
                "experiment_type": "ranking_adjustment",
            })

    # ── Ignition + Ribbon combo ───────────────────────────────────────────────
    both = next((x for x in perf_source if x["bucket"] == "Ignition+Ribbon"), None)
    only_ign = next((x for x in perf_source if x["bucket"] == "Ignition Only"), None)
    if both and only_ign and (both.get("avg_return_5d") or 0) >= 5.0 and both.get("count", 0) >= 3:
        experiments.append({
            "title":           "Create dedicated Ignition+Ribbon super-tier",
            "description":     "Candidates with both ignition and ribbon signals show the strongest returns. "
                               "Promote them to a dedicated tier or watchlist bucket.",
            "evidence":        f"Ignition+Ribbon avg 5d {both.get('avg_return_5d'):+.1f}%, "
                               f"n={both.get('count')}",
            "confidence":      "HIGH",
            "experiment_type": "bucket_split",
        })

    # ── High false-positive rate ──────────────────────────────────────────────
    if total5 > 0:
        fp_count = lc.get("FALSE_POSITIVE", 0) + lc.get("FAILED_BREAKOUT", 0)
        fp_rate  = _pct(fp_count, total5)
        if fp_rate >= 35:
            experiments.append({
                "title":           "Tighten entry-quality threshold",
                "description":     f"False-positive/failed rate is {fp_rate:.0f}%. "
                                   "Test raising MIN_SCORE or adding a pre-ignition OBV requirement.",
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
    perf_ribbon = _build_perf_buckets(
        candidates, outcome_map,
        lambda c: str(bool(c.get("ribbon_signal"))),
        "ribbon_signal",
    )
    perf_ignition = _build_perf_buckets(
        candidates, outcome_map,
        lambda c: str(bool(c.get("ignition_signal"))),
        "ignition_signal",
    )
    perf_source = _build_perf_buckets(
        candidates, outcome_map,
        lambda c: (
            "Ignition+Ribbon" if c.get("ignition_signal") and c.get("ribbon_signal") else
            "Ignition Only"   if c.get("ignition_signal") else
            "Ribbon Only"     if c.get("ribbon_signal")   else
            "Neither"
        ),
        "signal_combo",
    )

    # ── Sections C, D: False positives + Missed movers ────────────────────────
    false_positives = _build_false_positives(candidates, outcome_map)
    missed_section  = _build_missed_section(missed)

    # ── Section E: Pattern review ─────────────────────────────────────────────
    pattern_review = _build_pattern_review(
        summary, perf_tier, perf_ribbon, perf_ignition, perf_source,
        false_positives, missed_section,
    )

    # ── Section F: Suggested experiments ─────────────────────────────────────
    suggested_experiments = _build_experiments(
        summary, perf_tier, perf_ribbon, perf_ignition, perf_source,
        missed_section, pattern_review,
    )

    bundle = {
        "run":                          run,
        "summary":                      summary,
        "performance_by_tier":          perf_tier,
        "performance_by_ribbon_signal": perf_ribbon,
        "performance_by_ignition_signal": perf_ignition,
        "performance_by_source":        perf_source,
        "false_positives":              false_positives,
        "missed_movers":                missed_section,
        "pattern_review":               pattern_review,
        "suggested_experiments":        suggested_experiments,
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

    _bucket_section("Performance by Tier",           bundle.get("performance_by_tier", []))
    _bucket_section("Performance by Signal Combo",   bundle.get("performance_by_source", []))
    _bucket_section("Performance by Ignition Signal",bundle.get("performance_by_ignition_signal", []))
    _bucket_section("Performance by Ribbon Signal",  bundle.get("performance_by_ribbon_signal", []))

    # ── Section C: Top False Positives ────────────────────────────────────────
    add("## Top False Positives")
    add("")
    fps = bundle.get("false_positives", [])
    if fps:
        rows = []
        for fp in fps[:10]:
            rows.append([
                fp.get("symbol", "?"),
                fp.get("tier", "?"),
                _fmt(fp.get("return_3d"), sign=True, suffix="%"),
                _fmt(fp.get("return_5d"), sign=True, suffix="%"),
                _fmt(fp.get("max_drawdown_pct"), sign=True, suffix="%"),
                fp.get("outcome_label") or "—",
                "✓" if fp.get("ignition_signal") else "—",
                "✓" if fp.get("ribbon_signal") else "—",
            ])
        add(_mdtable(
            ["Symbol", "Tier", "3d", "5d", "MaxDD", "Label", "Ign", "Rib"],
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
