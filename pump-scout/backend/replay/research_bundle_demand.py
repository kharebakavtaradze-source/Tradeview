"""
Slim demand-engine research bundle for replay runs.
Replaces the old 2706-line research_bundle.py.
"""
import logging
from collections import defaultdict
from typing import Optional

logger = logging.getLogger(__name__)

TIER_ORDER = ["PRIME_BUY", "HIGH_CONF_BUY", "BUY_WATCH", "SETUP_MONITOR", "SKIP"]
ATS_ORDER  = ["ATS_PRIME", "ATS_SETUP", "ATS_WATCH", "ATS_NONE"]

async def build_research_bundle(run_id: int, raw_pattern_run_id: Optional[int] = None) -> dict:
    """Build demand-engine research bundle for a replay run."""
    # imports
    from database import get_replay_run, get_replay_candidates, get_replay_outcomes, get_replay_missed_movers

    run = await get_replay_run(run_id)
    if not run:
        raise ValueError(f"Replay run {run_id} not found")

    candidates = await get_replay_candidates(run_id, limit=5000)
    outcomes   = await get_replay_outcomes(run_id)
    missed     = await get_replay_missed_movers(run_id)

    # Build lookup: candidate_id -> outcome rows
    outcomes_by_cid = defaultdict(list)
    for o in outcomes:
        outcomes_by_cid[o["replay_candidate_id"]].append(o)

    # Build lookup: symbol -> candidate(s)
    cands_by_id = {c["id"]: c for c in candidates}

    def _perf_row(bucket, items):
        """Aggregate outcomes for a group of candidates."""
        if not items:
            return None
        returns_5d = []
        returns_10d = []
        drawdowns = []
        alphas = []
        for c in items:
            outs = outcomes_by_cid.get(c["id"], [])
            for o in outs:
                if o["horizon"] == "5d" and o.get("return_pct") is not None:
                    returns_5d.append(o["return_pct"])
                    if o.get("alpha_vs_spy") is not None:
                        alphas.append(o["alpha_vs_spy"])
                if o["horizon"] == "10d" and o.get("return_pct") is not None:
                    returns_10d.append(o["return_pct"])
                if o["horizon"] == "5d" and o.get("max_drawdown_pct") is not None:
                    drawdowns.append(o["max_drawdown_pct"])
        n = len(items)
        return {
            "bucket":            bucket,
            "count":             n,
            "with_outcomes":     len(returns_5d),
            "avg_return_5d":     round(sum(returns_5d) / len(returns_5d), 2) if returns_5d else None,
            "win_rate_5d":       round(100 * sum(1 for r in returns_5d if r > 0) / len(returns_5d), 1) if returns_5d else None,
            "avg_return_10d":    round(sum(returns_10d) / len(returns_10d), 2) if returns_10d else None,
            "avg_max_drawdown_pct": round(sum(drawdowns) / len(drawdowns), 2) if drawdowns else None,
            "alpha_vs_spy_5d":   round(sum(alphas) / len(alphas), 2) if alphas else None,
        }

    # Performance by demand tier
    by_tier = defaultdict(list)
    for c in candidates:
        tier = c.get("demand_composite_tier") or "SKIP"
        by_tier[tier].append(c)

    perf_by_tier = []
    for tier in TIER_ORDER:
        if tier in by_tier:
            row = _perf_row(tier, by_tier[tier])
            if row:
                perf_by_tier.append(row)

    # Performance by ATS signal
    by_ats = defaultdict(list)
    for c in candidates:
        ats = c.get("ats_signal") or "ATS_NONE"
        by_ats[ats].append(c)

    perf_by_ats = []
    for sig in ATS_ORDER:
        if sig in by_ats:
            row = _perf_row(sig, by_ats[sig])
            if row:
                perf_by_ats.append(row)

    # Performance by readiness tier
    by_readiness = defaultdict(list)
    for c in candidates:
        rt = c.get("readiness_tier") or "UNKNOWN"
        by_readiness[rt].append(c)

    perf_by_readiness = [
        _perf_row(rt, items)
        for rt, items in sorted(by_readiness.items(), key=lambda x: -len(x[1]))
        if items
    ]
    perf_by_readiness = [r for r in perf_by_readiness if r]

    # Performance by NP label
    by_np_label = defaultdict(list)
    for c in candidates:
        lbl = c.get("new_pump_label") or "NEW_PUMP_NONE"
        by_np_label[lbl].append(c)

    perf_by_np_label = [
        _perf_row(lbl, items)
        for lbl, items in sorted(by_np_label.items(), key=lambda x: -len(x[1]))
        if items
    ]
    perf_by_np_label = [r for r in perf_by_np_label if r]

    # Outcome distribution
    label_dist = defaultdict(int)
    for o in outcomes:
        if o.get("horizon") == "5d" and o.get("outcome_label"):
            label_dist[o["outcome_label"]] += 1

    # Overall stats
    all_5d = [o["return_pct"] for o in outcomes if o.get("horizon") == "5d" and o.get("return_pct") is not None]
    overall = {
        "total_candidates":  len(candidates),
        "total_outcomes":    len(outcomes),
        "missed_movers":     len(missed),
        "avg_return_5d":     round(sum(all_5d) / len(all_5d), 2) if all_5d else None,
        "win_rate_5d":       round(100 * sum(1 for r in all_5d if r > 0) / len(all_5d), 1) if all_5d else None,
        "outcome_label_dist": dict(label_dist),
    }

    # Best/worst candidates
    five_d_outs = [o for o in outcomes if o.get("horizon") == "5d" and o.get("return_pct") is not None]
    five_d_outs.sort(key=lambda x: x["return_pct"], reverse=True)

    def _cand_summary(o):
        c = cands_by_id.get(o.get("replay_candidate_id"), {})
        return {
            "symbol": o["symbol"],
            "scan_date": o.get("scan_date"),
            "return_5d": o["return_pct"],
            "demand_tier": c.get("demand_composite_tier"),
            "ats_signal": c.get("ats_signal"),
            "demand_score": c.get("demand_composite_score"),
            "np_label": c.get("new_pump_label"),
        }

    best5  = [_cand_summary(o) for o in five_d_outs[:5]]
    worst5 = [_cand_summary(o) for o in five_d_outs[-5:] if o["return_pct"] < 0]

    # Missed movers summary
    missed_summary = [
        {
            "symbol":   m.get("symbol"),
            "scan_date": m.get("scan_date"),
            "return_5d": m.get("future_return_5d"),
            "return_10d": m.get("future_return_10d"),
            "why_missed": m.get("why_missed"),
        }
        for m in missed[:20]
    ]

    return {
        "run_id":                 run_id,
        "run":                    run,
        "overall":                overall,
        "performance_by_demand_tier":  perf_by_tier,
        "performance_by_ats_signal":   perf_by_ats,
        "performance_by_readiness_tier": perf_by_readiness,
        "performance_by_new_pump_label": perf_by_np_label,
        "best_candidates":        best5,
        "worst_candidates":       worst5,
        "missed_movers":          missed_summary,
    }


def render_research_bundle_markdown(bundle: dict) -> str:
    """Render the demand research bundle as markdown."""
    lines = []
    run = bundle.get("run") or {}
    ov  = bundle.get("overall") or {}

    lines.append(f"# Demand Engine Research Bundle — Run {bundle['run_id']}")
    lines.append(f"Date: {run.get('as_of_date') or run.get('start_date', '?')} | Mode: {run.get('mode', '?')} | Status: {run.get('status', '?')}")
    lines.append("")
    lines.append("## Overall")
    lines.append(f"- Candidates: {ov.get('total_candidates', 0)}")
    lines.append(f"- With outcomes: {ov.get('total_outcomes', 0)}")
    lines.append(f"- Avg 5d return: {ov.get('avg_return_5d', '—')}")
    lines.append(f"- Win rate 5d: {ov.get('win_rate_5d', '—')}%")
    lines.append(f"- Missed movers: {ov.get('missed_movers', 0)}")
    lines.append("")

    def _table(rows, title):
        if not rows:
            return
        lines.append(f"## {title}")
        lines.append("| Bucket | N | Avg 5d | Win% | Avg 10d | Avg DD | α/SPY |")
        lines.append("|--------|---|--------|------|---------|--------|-------|")
        for r in rows:
            lines.append(
                f"| {r['bucket']} | {r['count']} | "
                f"{r['avg_return_5d'] or '—'} | {r['win_rate_5d'] or '—'} | "
                f"{r['avg_return_10d'] or '—'} | {r['avg_max_drawdown_pct'] or '—'} | "
                f"{r['alpha_vs_spy_5d'] or '—'} |"
            )
        lines.append("")

    _table(bundle.get("performance_by_demand_tier"), "Performance by Demand Tier")
    _table(bundle.get("performance_by_ats_signal"), "Performance by ATS Signal")
    _table(bundle.get("performance_by_readiness_tier"), "Performance by Readiness Tier")
    _table(bundle.get("performance_by_new_pump_label"), "Performance by NP Label")

    best = bundle.get("best_candidates") or []
    if best:
        lines.append("## Best Candidates (5d)")
        for c in best:
            lines.append(f"- {c['symbol']} {c.get('scan_date','')} | +{c['return_5d']:.1f}% | {c.get('demand_tier','')} | {c.get('ats_signal','')}")
        lines.append("")

    missed = bundle.get("missed_movers") or []
    if missed:
        lines.append("## Missed Movers")
        for m in missed[:10]:
            lines.append(f"- {m['symbol']} {m.get('scan_date','')} | 5d:{m.get('return_5d','—')} | {m.get('why_missed','')}")
        lines.append("")

    return "\n".join(lines)
