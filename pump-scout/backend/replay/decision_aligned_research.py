"""
Decision-Aligned Research
==========================
Research/reporting layer that groups replay candidates by the current
production decision bucket (BUY_CANDIDATE / WATCH / IMPULSE_RISK / AVOID)
instead of by legacy outcome groups (4x_pump / false_positive / etc.).

Answers the new set of questions:
  • What separates BUY from WATCH?
  • What separates WATCH from AVOID?
  • Which event chronologies (via age_* fields) precede each decision?
  • How does IMPULSE_RISK chronology differ from structure BUY?

Data source:
  ReplaySignalCandidate columns + candidate_snapshot_json + ReplayOutcome
  All inputs are already live-safe (no outcome leakage into live engine).

Does NOT replace or modify:
  • Raw Pattern `group_type` legacy comparisons (4x_pump etc.)
  • Pattern Study chronology
  • Live engine / decision routing
"""

from __future__ import annotations

from collections import Counter
from typing import Optional


# ── Numeric helpers ──────────────────────────────────────────────────────────

def _clean(vals: list) -> list:
    return [v for v in vals if v is not None]

def _median(vals: list) -> Optional[float]:
    vals = _clean(vals)
    if not vals:
        return None
    vs = sorted(vals)
    n = len(vs)
    mid = n // 2
    return float(vs[mid]) if n % 2 == 1 else float((vs[mid - 1] + vs[mid]) / 2)

def _mean(vals: list) -> Optional[float]:
    vals = _clean(vals)
    return round(sum(vals) / len(vals), 3) if vals else None

def _share(counter: Counter, total: int, bucket: str) -> float:
    return round(100.0 * counter.get(bucket, 0) / total, 1) if total else 0.0


# ── Feature extraction per candidate ────────────────────────────────────────

def _candidate_features(c: dict) -> dict:
    """
    Pull the raw-pattern-style pre-window features from a replay candidate
    (columns + snapshot.new_pump).  No outcome leakage: everything here is
    known at scan time.
    """
    snap    = c.get("snapshot") or {}
    snap_np = snap.get("new_pump") or {}

    return {
        # Decision + state
        "decision":       c.get("np_decision"),
        "state":          c.get("np_state")              or snap_np.get("state"),
        "engine_path":    c.get("np_engine_path")        or snap_np.get("engine_path"),
        "seq_lbl":        c.get("new_pump_sequence_label") or snap_np.get("new_pump_sequence_label"),
        "setup_via":      c.get("np_setup_via"),
        "ftr":            c.get("np_fake_trigger_risk")  or snap_np.get("fake_trigger_risk"),
        "ce_state":       c.get("np_compression_expansion_state") or snap_np.get("compression_expansion_state"),
        "ce_risk":        c.get("np_expansion_timing_risk") or snap_np.get("expansion_timing_risk"),
        "sustain_prof":   c.get("np_sustain_profile"),
        # Numeric scores
        "bq_score":       c.get("np_base_quality_score"),
        "sustain_score":  c.get("np_sustain_proxy_score"),
        "ce_score":       c.get("np_compression_expansion_score"),
        "np_score":       c.get("new_pump_score"),
        "total_score":    c.get("total_score"),
        "impulse_score":  snap_np.get("impulse_score"),
        # Structural indicators from snapshot (raw-pattern-equivalent features)
        "avg_ema_spread": snap.get("avg_ema_spread") or snap.get("ema_spread"),
        "volume_z":       snap.get("volume_z") or snap_np.get("volume_z"),
        "ema_extended":   snap_np.get("ema_extended"),
        # Chronology proxies (already live-safe — stored at scan time)
        "age_l34":        c.get("np_age_l34"),
        "age_fri34":      c.get("np_age_fri34"),
        "age_g4":         snap_np.get("age_g4"),
        "age_b2":         snap_np.get("age_b2"),
    }


# ── Per-bucket summary ──────────────────────────────────────────────────────

_DECISION_ORDER = ("BUY_CANDIDATE", "WATCH", "IMPULSE_RISK", "AVOID")


def _bucket_summary(rows: list[dict], outcome_map: dict) -> dict:
    """
    Per-decision-bucket summary: counts, return avgs, feature medians,
    distribution of state/sequence/ce_state/ftr.
    """
    n = len(rows)
    if n == 0:
        return {"count": 0}

    # Outcome aggregates at 3d / 5d horizons
    r3 = [outcome_map.get((r["id"], "3d"), {}).get("return_pct") for r in rows]
    r5 = [outcome_map.get((r["id"], "5d"), {}).get("return_pct") for r in rows]
    mg = [outcome_map.get((r["id"], "5d"), {}).get("max_gain_pct") for r in rows]
    md = [outcome_map.get((r["id"], "5d"), {}).get("max_drawdown_pct") for r in rows]

    # Feature medians from snapshot + columns
    feats = [_candidate_features(r) for r in rows]

    # Categorical distributions
    state_counts  = Counter(f["state"] for f in feats if f["state"])
    seq_counts    = Counter(f["seq_lbl"] for f in feats if f["seq_lbl"])
    ce_counts     = Counter(f["ce_state"] for f in feats if f["ce_state"])
    ftr_counts    = Counter(f["ftr"] for f in feats if f["ftr"])
    path_counts   = Counter(f["engine_path"] for f in feats if f["engine_path"])
    setup_counts  = Counter(f["setup_via"] for f in feats if f["setup_via"])

    return {
        "count":            n,
        "avg_return_3d":    _mean(r3),
        "avg_return_5d":    _mean(r5),
        "avg_max_gain_5d":  _mean(mg),
        "avg_max_drawdown_5d": _mean(md),
        # Numeric feature medians
        "median_bq_score":      _median([f["bq_score"] for f in feats]),
        "median_sustain_score": _median([f["sustain_score"] for f in feats]),
        "median_ce_score":      _median([f["ce_score"] for f in feats]),
        "median_np_score":      _median([f["np_score"] for f in feats]),
        "median_total_score":   _median([f["total_score"] for f in feats]),
        "median_impulse_score": _median([f["impulse_score"] for f in feats]),
        "median_avg_ema_spread":_median([f["avg_ema_spread"] for f in feats]),
        "median_volume_z":      _median([f["volume_z"] for f in feats]),
        # Chronology medians (age_* = days since signal fired)
        "median_age_l34":   _median([f["age_l34"] for f in feats]),
        "median_age_fri34": _median([f["age_fri34"] for f in feats]),
        "median_age_g4":    _median([f["age_g4"] for f in feats]),
        "median_age_b2":    _median([f["age_b2"] for f in feats]),
        # Categorical distributions (top entries only to keep compact)
        "state_distribution":       dict(state_counts.most_common(6)),
        "sequence_distribution":    dict(seq_counts.most_common(8)),
        "ce_state_distribution":    dict(ce_counts.most_common(5)),
        "ftr_distribution":         dict(ftr_counts.most_common()),
        "engine_path_distribution": dict(path_counts.most_common()),
        "setup_via_distribution":   dict(setup_counts.most_common()),
    }


# ── Pairwise comparisons ─────────────────────────────────────────────────────

def _diff(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None:
        return None
    return round(a - b, 3)


def _pairwise(a_sum: dict, b_sum: dict, a_name: str, b_name: str) -> dict:
    """
    Compute {a_name} - {b_name} separation for key numeric features.
    Negative = bucket B is higher.  Positive = bucket A is higher.
    """
    if a_sum.get("count", 0) == 0 or b_sum.get("count", 0) == 0:
        return {"comparison": f"{a_name}_vs_{b_name}", "skipped_reason": "one or both buckets empty"}

    return {
        "comparison":        f"{a_name}_vs_{b_name}",
        "counts":            {a_name: a_sum["count"], b_name: b_sum["count"]},
        "return_5d_diff":    _diff(a_sum.get("avg_return_5d"),        b_sum.get("avg_return_5d")),
        "return_3d_diff":    _diff(a_sum.get("avg_return_3d"),        b_sum.get("avg_return_3d")),
        "max_gain_5d_diff":  _diff(a_sum.get("avg_max_gain_5d"),      b_sum.get("avg_max_gain_5d")),
        "max_drawdown_5d_diff": _diff(a_sum.get("avg_max_drawdown_5d"), b_sum.get("avg_max_drawdown_5d")),
        "bq_score_diff":     _diff(a_sum.get("median_bq_score"),      b_sum.get("median_bq_score")),
        "sustain_score_diff":_diff(a_sum.get("median_sustain_score"), b_sum.get("median_sustain_score")),
        "ce_score_diff":     _diff(a_sum.get("median_ce_score"),      b_sum.get("median_ce_score")),
        "np_score_diff":     _diff(a_sum.get("median_np_score"),      b_sum.get("median_np_score")),
        "ema_spread_diff":   _diff(a_sum.get("median_avg_ema_spread"),b_sum.get("median_avg_ema_spread")),
        "age_g4_diff":       _diff(a_sum.get("median_age_g4"),        b_sum.get("median_age_g4")),
        "age_l34_diff":      _diff(a_sum.get("median_age_l34"),       b_sum.get("median_age_l34")),
    }


# ── Chronology summaries ─────────────────────────────────────────────────────

def _chronology_bucket(rows: list[dict]) -> dict:
    """
    Event-chain chronology proxy using age_* fields and ce_state ordering.
    age_* = days between the signal and the scan date (smaller = more recent).
    A larger age_l34 with small age_g4 means setup came well before trigger —
    that ordering is itself an event chain.
    """
    if not rows:
        return {"count": 0}

    feats = [_candidate_features(r) for r in rows]

    def _has(f, key):
        return f.get(key) is not None

    # Fraction of candidates that show each "event" having fired pre-scan
    has_l34   = sum(1 for f in feats if _has(f, "age_l34"))
    has_fri34 = sum(1 for f in feats if _has(f, "age_fri34"))
    has_g4    = sum(1 for f in feats if _has(f, "age_g4"))
    has_b2    = sum(1 for f in feats if _has(f, "age_b2"))

    # Ordering check: setup_before_trigger = age_l34 > age_g4 (setup older than trigger)
    setup_before_trigger = sum(
        1 for f in feats
        if f.get("age_g4") is not None
        and (f.get("age_l34") is not None or f.get("age_fri34") is not None)
        and max(v for v in [f.get("age_l34"), f.get("age_fri34")] if v is not None) > f["age_g4"]
    )
    trigger_without_setup = sum(
        1 for f in feats
        if f.get("age_g4") is not None
        and f.get("age_l34") is None and f.get("age_fri34") is None
    )

    # CE phase distribution — where in the compression→expansion lifecycle
    ce_counts = Counter(f["ce_state"] for f in feats if f["ce_state"])

    n = len(feats)
    return {
        "count":                        n,
        "pct_with_l34_signal":          _share(Counter({"x": has_l34}),   n, "x"),
        "pct_with_fri34_signal":        _share(Counter({"x": has_fri34}), n, "x"),
        "pct_with_g4_trigger":          _share(Counter({"x": has_g4}),    n, "x"),
        "pct_with_b2_boundary":         _share(Counter({"x": has_b2}),    n, "x"),
        "pct_setup_before_trigger":     _share(Counter({"x": setup_before_trigger}), n, "x"),
        "pct_trigger_without_setup":    _share(Counter({"x": trigger_without_setup}), n, "x"),
        "median_days_setup_to_trigger": _median([
            max(v for v in [f.get("age_l34"), f.get("age_fri34")] if v is not None) - f["age_g4"]
            for f in feats
            if f.get("age_g4") is not None
            and (f.get("age_l34") is not None or f.get("age_fri34") is not None)
        ]),
        "median_age_g4":                _median([f["age_g4"] for f in feats]),
        "median_age_l34":               _median([f["age_l34"] for f in feats]),
        "ce_phase_distribution":        dict(ce_counts.most_common(5)),
    }


# ── Patch-plan style insights ────────────────────────────────────────────────

def _build_insights(summary: dict, pairwise: list[dict]) -> list[str]:
    """
    Concise decision-aware observations suitable for a research digest.
    Speaks in terms of BUY/WATCH/AVOID/IMPULSE_RISK, not 4x/false_positive.
    """
    out: list[str] = []
    buy   = summary.get("BUY_CANDIDATE") or {}
    watch = summary.get("WATCH") or {}
    avoid = summary.get("AVOID") or {}
    impul = summary.get("IMPULSE_RISK") or {}

    def _fmt(v, pct=True) -> str:
        if v is None:
            return "—"
        return f"{v:+.2f}%" if pct else f"{v:.1f}"

    if buy.get("count"):
        out.append(
            f"BUY_CANDIDATE (n={buy['count']}) avg 5d {_fmt(buy.get('avg_return_5d'))}; "
            f"median seq={next(iter(buy.get('sequence_distribution') or {}), 'NONE')}; "
            f"median bq={_fmt(buy.get('median_bq_score'), pct=False)}"
        )
    if watch.get("count"):
        out.append(
            f"WATCH (n={watch['count']}) avg 5d {_fmt(watch.get('avg_return_5d'))}; "
            f"dominated by state={next(iter(watch.get('state_distribution') or {}), 'NONE')}"
        )
    if avoid.get("count"):
        out.append(
            f"AVOID (n={avoid['count']}) avg 5d {_fmt(avoid.get('avg_return_5d'))}; "
            f"top state={next(iter(avoid.get('state_distribution') or {}), 'NONE')}"
        )
    if impul.get("count"):
        out.append(
            f"IMPULSE_RISK (n={impul['count']}) avg 5d {_fmt(impul.get('avg_return_5d'))}; "
            f"drawdown 5d {_fmt(impul.get('avg_max_drawdown_5d'))} vs BUY "
            f"{_fmt(buy.get('avg_max_drawdown_5d'))}"
        )

    # Cross-bucket observations
    for pw in pairwise:
        diff5 = pw.get("return_5d_diff")
        if diff5 is None:
            continue
        if pw["comparison"] == "BUY_CANDIDATE_vs_WATCH" and diff5 > 2:
            out.append(f"BUY beats WATCH by {diff5:+.2f}% 5d — routing is separating real setups")
        if pw["comparison"] == "WATCH_vs_AVOID" and diff5 > 3:
            out.append(f"WATCH beats AVOID by {diff5:+.2f}% 5d — watchlist is discriminating")
        if pw["comparison"] == "IMPULSE_RISK_vs_BUY_CANDIDATE":
            drawdown_gap = pw.get("max_drawdown_5d_diff")
            if drawdown_gap is not None and drawdown_gap < -3:
                out.append(
                    f"IMPULSE_RISK shows {abs(drawdown_gap):.1f}% deeper drawdown than BUY — "
                    f"use smaller size for impulse plays"
                )
    return out


# ── Public entrypoint ────────────────────────────────────────────────────────

async def build_decision_aligned_research(run_id: int) -> dict:
    """
    Build the full decision-aligned research payload for a replay run.
    Returns a dict with:
      summary_by_decision     — per-bucket counts + returns + feature medians
      pairwise_comparisons    — BUY vs WATCH, BUY vs AVOID, WATCH vs AVOID, ...
      chronology_by_decision  — age_* / setup-vs-trigger ordering per bucket
      insights                — short decision-aware observations
    """
    from database import (
        get_replay_run, get_replay_candidates, get_replay_outcomes,
    )
    from replay.research_bundle import _build_outcome_map

    run = await get_replay_run(run_id)
    if not run:
        raise ValueError(f"Replay run {run_id} not found")

    candidates = await get_replay_candidates(run_id, limit=10000)
    outcomes   = await get_replay_outcomes(run_id)
    outcome_map = _build_outcome_map(outcomes)

    # Group candidates by np_decision
    by_decision: dict[str, list[dict]] = {k: [] for k in _DECISION_ORDER}
    unknown: list[dict] = []
    for c in candidates:
        d = c.get("np_decision")
        if d in by_decision:
            by_decision[d].append(c)
        else:
            unknown.append(c)

    # Per-bucket summaries
    summary_by_decision = {
        d: _bucket_summary(rows, outcome_map) for d, rows in by_decision.items()
    }
    if unknown:
        summary_by_decision["UNDECIDED"] = _bucket_summary(unknown, outcome_map)

    # Pairwise comparisons covering the named pairs from the spec
    pairs = [
        ("BUY_CANDIDATE", "WATCH"),
        ("BUY_CANDIDATE", "AVOID"),
        ("WATCH",         "AVOID"),
        ("IMPULSE_RISK",  "BUY_CANDIDATE"),
        ("IMPULSE_RISK",  "AVOID"),
    ]
    pairwise_comparisons = [
        _pairwise(summary_by_decision.get(a, {}), summary_by_decision.get(b, {}), a, b)
        for a, b in pairs
    ]

    # Chronology by decision bucket
    chronology_by_decision = {
        d: _chronology_bucket(rows) for d, rows in by_decision.items()
    }

    insights = _build_insights(summary_by_decision, pairwise_comparisons)

    return {
        "run_id":                   run_id,
        "total_candidates":         len(candidates),
        "undecided_count":          len(unknown),
        "summary_by_decision":      summary_by_decision,
        "pairwise_comparisons":     pairwise_comparisons,
        "chronology_by_decision":   chronology_by_decision,
        "insights":                 insights,
        "notes": {
            "design":               "Additive to legacy Raw Pattern / Pump Study — does not replace them.",
            "data_source":          "ReplaySignalCandidate + ReplayOutcome (live-safe, no future leakage).",
            "chronology_proxy":     "age_l34 / age_fri34 / age_g4 / age_b2 stored at scan time.",
        },
    }


def render_decision_aligned_markdown(payload: dict) -> str:
    """Compact markdown render of the payload for report display."""
    out: list[str] = []
    out.append(f"# Decision-Aligned Research — Run {payload.get('run_id')}")
    out.append(f"\nTotal candidates: {payload.get('total_candidates')}  ·  "
               f"Undecided: {payload.get('undecided_count')}\n")

    out.append("## Summary by Decision")
    sbd = payload.get("summary_by_decision") or {}
    for d in ("BUY_CANDIDATE", "WATCH", "IMPULSE_RISK", "AVOID"):
        b = sbd.get(d) or {}
        if not b.get("count"):
            continue
        out.append(f"### {d}  (n={b['count']})")
        out.append(
            f"- avg 5d: {b.get('avg_return_5d')}%   avg 3d: {b.get('avg_return_3d')}%"
            f"   max_gain_5d: {b.get('avg_max_gain_5d')}%"
            f"   max_drawdown_5d: {b.get('avg_max_drawdown_5d')}%"
        )
        out.append(
            f"- medians: bq={b.get('median_bq_score')}  "
            f"sustain={b.get('median_sustain_score')}  "
            f"ce={b.get('median_ce_score')}  "
            f"np={b.get('median_np_score')}"
        )
        sd = b.get("state_distribution") or {}
        if sd:
            out.append(f"- state: {sd}")
        seqd = b.get("sequence_distribution") or {}
        if seqd:
            out.append(f"- sequence: {seqd}")

    out.append("\n## Pairwise Comparisons (A − B)")
    for pw in payload.get("pairwise_comparisons") or []:
        if pw.get("skipped_reason"):
            out.append(f"- {pw['comparison']}: skipped ({pw['skipped_reason']})")
            continue
        out.append(
            f"- **{pw['comparison']}**: Δreturn_5d={pw.get('return_5d_diff')}%  "
            f"Δbq={pw.get('bq_score_diff')}  Δsustain={pw.get('sustain_score_diff')}  "
            f"Δce={pw.get('ce_score_diff')}  Δdrawdown={pw.get('max_drawdown_5d_diff')}%"
        )

    out.append("\n## Chronology by Decision")
    cbd = payload.get("chronology_by_decision") or {}
    for d, c in cbd.items():
        if not c.get("count"):
            continue
        out.append(
            f"- **{d}** (n={c['count']}): "
            f"g4_seen={c.get('pct_with_g4_trigger')}%  "
            f"l34_seen={c.get('pct_with_l34_signal')}%  "
            f"setup_before_trigger={c.get('pct_setup_before_trigger')}%  "
            f"trigger_without_setup={c.get('pct_trigger_without_setup')}%  "
            f"median_setup→trigger_days={c.get('median_days_setup_to_trigger')}"
        )

    ins = payload.get("insights") or []
    if ins:
        out.append("\n## Insights")
        for line in ins:
            out.append(f"- {line}")

    return "\n".join(out)
