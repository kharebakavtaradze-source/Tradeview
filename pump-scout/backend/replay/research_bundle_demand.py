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

# TZ signal priority order (bullish T, then bearish Z, then no signal)
TZ_SIGNAL_ORDER = [
    "T4", "T6", "T1G", "T2G", "T1", "T2", "T9", "T10", "T3", "T11", "T5", "T12",
    "Z4", "Z6", "Z1G", "Z2G", "Z1", "Z2", "Z9", "Z10", "Z3", "Z11", "Z5", "Z12", "Z7",
    "NONE",
]

_PATTERN_TO_CAND = {
    "demand_tier_at_breakout":    "demand_composite_tier",
    "ats_at_breakout":            "ats_signal",
    "readiness_tier_at_breakout": "readiness_tier",
    "tz_t_signal_at_breakout":    "tz_t_signal",
    "tz_z_signal_at_breakout":    "tz_z_signal",
    "preup_token_at_breakout":    "preup_token",
    "line5_at_breakout":          "line5",
    "strongest_wyckoff_state":    "wyckoff_state",
}


async def build_research_bundle(run_id: int, raw_pattern_run_id: Optional[int] = None) -> dict:
    """Build demand-engine research bundle for a replay run."""
    import json as _json
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

    # ── TZ signal combinations ────────────────────────────────────────────────
    # Performance by TZ t_signal (bullish)
    by_tz_t = defaultdict(list)
    for c in candidates:
        sig = c.get("tz_t_signal") or "NONE"
        by_tz_t[sig].append(c)

    perf_by_tz_t = []
    for sig in TZ_SIGNAL_ORDER:
        if sig in by_tz_t:
            row = _perf_row(sig, by_tz_t[sig])
            if row:
                perf_by_tz_t.append(row)
    # Append any unlisted signals
    for sig, items in sorted(by_tz_t.items(), key=lambda x: -len(x[1])):
        if sig not in TZ_SIGNAL_ORDER and items:
            row = _perf_row(sig, items)
            if row:
                perf_by_tz_t.append(row)

    # Performance by PREUP token
    by_preup = defaultdict(list)
    for c in candidates:
        tok = c.get("preup_token") or "NONE"
        by_preup[tok].append(c)

    perf_by_preup = [
        _perf_row(tok, items)
        for tok, items in sorted(by_preup.items(), key=lambda x: -len(x[1]))
        if items
    ]
    perf_by_preup = [r for r in perf_by_preup if r]

    # Performance by Line5 (VIX-Fix / PSAR / RSI2 composite)
    by_line5 = defaultdict(list)
    for c in candidates:
        l5 = c.get("line5") or "NONE"
        by_line5[l5].append(c)

    perf_by_line5 = [
        _perf_row(l5, items)
        for l5, items in sorted(by_line5.items(), key=lambda x: -len(x[1]))
        if items
    ]
    perf_by_line5 = [r for r in perf_by_line5 if r]

    # TZ × Demand Tier cross-tab: top signal combos with outcome stats
    combo_map = defaultdict(list)
    for c in candidates:
        t_sig = c.get("tz_t_signal") or "NONE"
        tier  = c.get("demand_composite_tier") or "SKIP"
        combo_map[f"{t_sig}×{tier}"].append(c)

    tz_demand_combos = []
    for combo, items in sorted(combo_map.items(), key=lambda x: -len(x[1])):
        row = _perf_row(combo, items)
        if row and row["count"] >= 3:
            tz_demand_combos.append(row)

    # TZ × ATS cross-tab
    tz_ats_map = defaultdict(list)
    for c in candidates:
        t_sig = c.get("tz_t_signal") or "NONE"
        ats   = c.get("ats_signal") or "ATS_NONE"
        tz_ats_map[f"{t_sig}×{ats}"].append(c)

    tz_ats_combos = []
    for combo, items in sorted(tz_ats_map.items(), key=lambda x: -len(x[1])):
        row = _perf_row(combo, items)
        if row and row["count"] >= 3:
            tz_ats_combos.append(row)

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

    # ── Item 2: Missed mover why-code breakdown ───────────────────────────────
    # Groups missed movers by NSS why-code with actual return stats.
    # High avg-return for a code = the engine has a structural blind spot there.
    by_why: dict = defaultdict(list)
    for m in missed:
        by_why[m.get("why_missed") or "UNKNOWN"].append(m)

    missed_by_why = []
    for why, items in sorted(by_why.items(), key=lambda x: -len(x[1])):
        r5  = [m["future_return_5d"]  for m in items if m.get("future_return_5d")  is not None]
        r10 = [m["future_return_10d"] for m in items if m.get("future_return_10d") is not None]
        best = max(items, key=lambda m: m.get("future_return_5d") or 0, default=None)
        missed_by_why.append({
            "why_code":       why,
            "count":          len(items),
            "avg_5d":         round(sum(r5)  / len(r5),  2) if r5  else None,
            "avg_10d":        round(sum(r10) / len(r10), 2) if r10 else None,
            "best_symbol":    best.get("symbol")           if best else None,
            "best_return_5d": best.get("future_return_5d") if best else None,
        })

    # ── Items 1 + 4: Pattern discovery vs actual candidate performance ─────────
    # Loads BOOST/INCREASE patterns from raw_pattern_run_id, matches each
    # against replay candidates on categorical fields, compares predicted lift
    # against observed outcomes.  Shows which patterns actually delivered.
    pattern_vs_candidates: list[dict] = []
    if raw_pattern_run_id:
        try:
            from database import get_discovered_patterns as _gdp
            _patterns = await _gdp(raw_pattern_run_id)
            for _p in _patterns:
                if _p.get("recommendation") not in ("BOOST", "INCREASE"):
                    continue
                _cond_raw = _p.get("machine_conditions_json")
                if not _cond_raw:
                    continue
                try:
                    _cond = _json.loads(_cond_raw) if isinstance(_cond_raw, str) else _cond_raw
                except Exception:
                    continue
                if not isinstance(_cond, dict):
                    continue
                # Build candidate-side condition map — skip if any field not mappable
                _cand_conds: dict = {}
                _skip = False
                for _pf, _val in _cond.items():
                    _cf = _PATTERN_TO_CAND.get(_pf)
                    if _cf is None:
                        _skip = True
                        break
                    _cand_conds[_cf] = _val
                if _skip or not _cand_conds:
                    continue
                _matched = [
                    c for c in candidates
                    if all(c.get(_cf) == _v for _cf, _v in _cand_conds.items())
                ]
                if not _matched:
                    continue
                _perf = _perf_row(_p["signal_id"], _matched)
                if not _perf:
                    continue
                pattern_vs_candidates.append({
                    "signal_id":        _p["signal_id"],
                    "description":      _p.get("description"),
                    "feature_family":   _p.get("feature_family"),
                    "recommendation":   _p["recommendation"],
                    "predicted_lift":   _p.get("lift_vs_false_positive"),
                    "count_matched":    _perf["count"],
                    "avg_return_5d":    _perf.get("avg_return_5d"),
                    "win_rate_5d":      _perf.get("win_rate_5d"),
                    "avg_return_10d":   _perf.get("avg_return_10d"),
                    "avg_max_drawdown": _perf.get("avg_max_drawdown_pct"),
                    "alpha_vs_spy":     _perf.get("alpha_vs_spy_5d"),
                })
            pattern_vs_candidates.sort(
                key=lambda x: x.get("avg_return_5d") or -999, reverse=True
            )
        except Exception as _pe:
            logger.warning(f"[Bundle] pattern discovery audit failed: {_pe}")

    return {
        "run_id":                 run_id,
        "run":                    run,
        "overall":                overall,
        "performance_by_demand_tier":  perf_by_tier,
        "performance_by_ats_signal":   perf_by_ats,
        "performance_by_readiness_tier": perf_by_readiness,
        "performance_by_new_pump_label": perf_by_np_label,
        # TZ combination analytics
        "performance_by_tz_t_signal":  perf_by_tz_t,
        "performance_by_preup_token":  perf_by_preup,
        "performance_by_line5":        perf_by_line5,
        "tz_demand_tier_combos":       tz_demand_combos[:30],
        "tz_ats_combos":               tz_ats_combos[:20],
        "best_candidates":        best5,
        "worst_candidates":       worst5,
        "missed_movers":          missed_summary,
        # Item 2: why-code breakdown
        "missed_mover_why_breakdown":     missed_by_why,
        # Items 1 + 4: pattern discovery vs actual performance
        "pattern_vs_candidates":          pattern_vs_candidates,
        "raw_pattern_run_id_used":        raw_pattern_run_id,
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
    _table(bundle.get("performance_by_tz_t_signal"), "Performance by TZ Signal (T/Z)")
    _table(bundle.get("performance_by_preup_token"), "Performance by PREUP Token")
    _table(bundle.get("performance_by_line5"), "Performance by Line5 (VIX/PSAR/RSI2)")
    _table(bundle.get("tz_demand_tier_combos"), "TZ × Demand Tier Combinations")
    _table(bundle.get("tz_ats_combos"), "TZ × ATS Signal Combinations")

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

    # Why-code breakdown (item 2)
    why_rows = bundle.get("missed_mover_why_breakdown") or []
    if why_rows:
        lines.append("## Missed Movers by Why-Code")
        lines.append("| Why Code | Count | Avg 5d | Avg 10d | Best |")
        lines.append("|----------|-------|--------|---------|------|")
        for w in why_rows:
            best_ex = f"{w.get('best_symbol','')} {w.get('best_return_5d','')}"
            lines.append(
                f"| {w['why_code']} | {w['count']} | "
                f"{w.get('avg_5d') or '—'} | {w.get('avg_10d') or '—'} | {best_ex} |"
            )
        lines.append("")

    # Pattern discovery vs outcomes (items 1 + 4)
    pat_rows = bundle.get("pattern_vs_candidates") or []
    if pat_rows:
        lines.append("## Pattern Discovery vs Actual Performance")
        lines.append(
            "Predicted lift (from pump-study pattern mining) vs observed "
            f"returns on this replay run's candidates."
        )
        lines.append("")
        lines.append("| Signal | Rec | Pred Lift | N | Avg 5d | Win% | α/SPY |")
        lines.append("|--------|-----|-----------|---|--------|------|-------|")
        for p in pat_rows[:25]:
            lines.append(
                f"| {p['signal_id']} | {p['recommendation']} | "
                f"{p.get('predicted_lift') or '—'} | {p['count_matched']} | "
                f"{p.get('avg_return_5d') or '—'} | {p.get('win_rate_5d') or '—'} | "
                f"{p.get('alpha_vs_spy') or '—'} |"
            )
        lines.append("")

    return "\n".join(lines)
