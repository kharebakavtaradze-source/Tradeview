"""
Scanner v2 Validation Sections
==============================
Adds Scanner v2 / Priority validation sections to the research bundle so we can
compare:
  - old scanner FIRE/ARM/BASE/WATCH (legacy_tier)
  - New Pump np_decision
  - Priority label (priority_score buckets)
  - Scanner v2 final decision

READ-ONLY. Never modifies scanner logic, scoring, or routing.

Reconstructs scanner_v2_decision and priority_label from stored candidate
fields when direct fields are absent.  When safe reconstruction is impossible
the bucket is "UNKNOWN" — never silently AVOID.
"""
import logging
from collections import defaultdict
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────────────
V2_LABELS = frozenset({
    "BUY_CANDIDATE_HIGH", "BUY_CANDIDATE_NORMAL",
    "WATCH_HIGH", "WATCH_MEDIUM", "WATCH_LOW",
    "AVOID_RISK", "AVOID_LOTTERY", "AVOID_DEAD",
})
V2_LABEL_ORDER = [
    "BUY_CANDIDATE_HIGH", "BUY_CANDIDATE_NORMAL",
    "WATCH_HIGH", "WATCH_MEDIUM", "WATCH_LOW",
    "AVOID_RISK", "AVOID_LOTTERY", "AVOID_DEAD",
    "UNKNOWN",
]
PRIORITY_ORDER = [
    "PRIORITY_HIGH", "PRIORITY_MEDIUM", "PRIORITY_LOW", "PRIORITY_RISKY", "UNKNOWN",
]
_RISK_FLAGS = frozenset({
    "expansion_risk_high", "overheated", "hype_late", "macro_headwind",
    "risk_off_regime", "sector_lagging", "d3_beup_weak", "d6_l34_poor",
})

_DCONF_V2_TO_SIMPLE: dict[str, str] = {
    "D6_BEUP_SAME": "D6_BEUP", "D4_BEUP_SAME": "D4_BEUP", "D3_BEUP_SAME": "D3_BEUP",
    "D4_L34_SAME":  "D4_L34",  "D3_L34_SAME":  "D3_L34",  "D6_L34_SAME":  "D6_L34",
    "D4_L43_SAME":  "D4_L43",  "D3_L43_SAME":  "D3_L43",  "D6_L43_SAME":  "D6_L43",
    "SECONDARY_D_BEUP_SAME": "SECONDARY_D_CONFLUENCE",
    "SECONDARY_D_L34_SAME":  "SECONDARY_D_CONFLUENCE",
    "SECONDARY_D_L43_SAME":  "SECONDARY_D_CONFLUENCE",
}


# ── Resolvers ────────────────────────────────────────────────────────────────

def resolve_priority_label(c: dict, cget: Callable) -> tuple[Optional[str], str]:
    """Returns (priority_label, source) where source in {direct, derived, missing}."""
    direct = cget(c, "priority_label")
    if isinstance(direct, str) and direct.startswith("PRIORITY_"):
        return direct, "direct"
    score = cget(c, "priority_score")
    if score is not None:
        try:
            ps = float(score)
            if ps >= 75: return "PRIORITY_HIGH",   "derived"
            if ps >= 55: return "PRIORITY_MEDIUM", "derived"
            if ps >= 35: return "PRIORITY_LOW",    "derived"
            return "PRIORITY_RISKY", "derived"
        except (TypeError, ValueError):
            pass
    return None, "missing"


def resolve_scanner_v2_decision(c: dict, cget: Callable) -> tuple[Optional[str], str]:
    """
    Returns (v2_decision, source) where source in {direct, reconstructed, unknown}.

    Conservative: when np_decision is missing or unrecognized, returns UNKNOWN.
    Never defaults to AVOID for missing fields.

    Mirrors scanner_v2._map_v2_decision logic including R35 hard-block rules:
      - OVERHEATED_EXPANSION: BUY→AVOID_RISK, WATCH→AVOID_LOTTERY
      - exp_risk=HIGH in WATCH: AVOID_LOTTERY at any priority label
    """
    direct = cget(c, "scanner_v2_decision")
    if direct in V2_LABELS:
        return direct, "direct"

    np_decision = cget(c, "np_decision") or cget(c, "decision")
    if np_decision not in ("BUY_CANDIDATE", "WATCH", "AVOID", "IMPULSE_RISK"):
        return None, "unknown"

    p_label, _ = resolve_priority_label(c, cget)
    # Replay rows expose this as `np_expansion_timing_risk`; live/in-memory rows
    # use `expansion_timing_risk`. Check both before defaulting to LOW.
    exp_risk = (cget(c, "expansion_timing_risk")
                or cget(c, "np_expansion_timing_risk")
                or "LOW")

    decision_flags = cget(c, "decision_flags") or []
    priority_flags = cget(c, "priority_flags") or []
    all_flags = set(list(decision_flags) + list(priority_flags))
    is_overheated = "overheated" in all_flags

    if np_decision == "BUY_CANDIDATE":
        # R35: OVERHEATED hard-blocks all BUY outcomes
        if is_overheated:
            return "AVOID_RISK", "reconstructed"
        if p_label == "PRIORITY_HIGH" and exp_risk != "HIGH":
            return "BUY_CANDIDATE_HIGH", "reconstructed"
        return "BUY_CANDIDATE_NORMAL", "reconstructed"

    if np_decision == "WATCH":
        # R35: OVERHEATED and exp_risk=HIGH both route to AVOID_LOTTERY at any priority
        if is_overheated or exp_risk == "HIGH":
            return "AVOID_LOTTERY", "reconstructed"
        if p_label == "PRIORITY_HIGH":   return "WATCH_HIGH",   "reconstructed"
        if p_label == "PRIORITY_MEDIUM": return "WATCH_MEDIUM", "reconstructed"
        return "WATCH_LOW", "reconstructed"

    if np_decision == "IMPULSE_RISK":
        return "AVOID_LOTTERY", "reconstructed"

    # AVOID
    if exp_risk == "HIGH" or (all_flags & _RISK_FLAGS):
        return "AVOID_RISK", "reconstructed"
    return "AVOID_DEAD", "reconstructed"


# ── Helpers (replicate from research_bundle to avoid circular imports) ───────

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


def _bucket_stats(cand_ids: list, outcome_map: dict) -> dict:
    r1, r3, r5, r10 = [], [], [], []
    gains, dds, a5, a10 = [], [], [], []
    for cid in cand_ids:
        h = outcome_map.get(cid, {})
        for hk, lst in (("1d", r1), ("3d", r3), ("5d", r5), ("10d", r10)):
            v = h.get(hk, {}).get("return_pct")
            if v is not None:
                lst.append(v)
        if "5d" in h:
            o5 = h["5d"]
            if o5.get("max_gain_pct")     is not None: gains.append(o5["max_gain_pct"])
            if o5.get("max_drawdown_pct") is not None: dds.append(o5["max_drawdown_pct"])
            if o5.get("alpha_vs_spy")     is not None: a5.append(o5["alpha_vs_spy"])
        if "10d" in h and h["10d"].get("alpha_vs_spy") is not None:
            a10.append(h["10d"]["alpha_vs_spy"])
    return {
        "count":                len(cand_ids),
        "avg_return_1d":        _avg(r1),
        "avg_return_3d":        _avg(r3),
        "avg_return_5d":        _avg(r5),
        "avg_return_10d":       _avg(r10),
        "win_rate_3d":          _win_rate(r3),
        "win_rate_5d":          _win_rate(r5),
        "avg_max_gain_pct":     _avg(gains),
        "avg_max_drawdown_pct": _avg(dds),
        "alpha_vs_spy_5d":      _avg(a5),
        "alpha_vs_spy_10d":     _avg(a10),
    }


def _mfe_stats(cand_ids: list, mfe_map: dict) -> dict:
    gains, gbacks, ret10s, ttm = [], [], [], []
    h10 = h20 = h50 = 0
    for cid in cand_ids:
        m = mfe_map.get(cid)
        if not m:
            continue
        mg = m.get("max_gain_10d_pct")
        if mg is not None:
            gains.append(mg)
            if mg >= 10: h10 += 1
            if mg >= 20: h20 += 1
            if mg >= 50: h50 += 1
        gb = m.get("giveback_10d_pct")
        if gb is not None: gbacks.append(gb)
        r10 = m.get("return_10d")
        if r10 is not None: ret10s.append(r10)
        d = m.get("max_gain_10d_day")
        if d is not None: ttm.append(d)
    n = len(gains)
    if n == 0:
        return {"count": len(cand_ids), "mfe_n": 0,
                "avg_return_10d": None, "avg_max_gain_10d_pct": None,
                "median_max_gain_10d_pct": None,
                "hit_10pct_rate": None, "hit_20pct_rate": None, "hit_50pct_rate": None,
                "avg_time_to_max_gain_10d": None, "avg_giveback_10d_pct": None}
    gs = sorted(gains)
    return {
        "count":                    len(cand_ids),
        "mfe_n":                    n,
        "avg_return_10d":           _avg(ret10s),
        "avg_max_gain_10d_pct":     round(sum(gains) / n, 2),
        "median_max_gain_10d_pct":  round(gs[n // 2], 2),
        "hit_10pct_rate":           round(h10 / n * 100, 1),
        "hit_20pct_rate":           round(h20 / n * 100, 1),
        "hit_50pct_rate":           round(h50 / n * 100, 1),
        "avg_time_to_max_gain_10d": round(sum(ttm) / len(ttm), 1) if ttm else None,
        "avg_giveback_10d_pct":     round(sum(gbacks) / len(gbacks), 2) if gbacks else None,
    }


def _fp_stats(cand_ids: list, outcome_map: dict, total_fp: int) -> dict:
    """False-positive counts/rate. FP = 5d return < -5.0. pct_of_all_false_positives = bucket_fps / global_fps."""
    n = len(cand_ids)
    fp = 0
    with_5d = 0
    for cid in cand_ids:
        r5 = (outcome_map.get(cid, {}).get("5d") or {}).get("return_pct")
        if r5 is None:
            continue
        with_5d += 1
        if r5 < -5.0:
            fp += 1
    return {
        "count":                       n,
        "with_5d_data":                with_5d,
        "false_positive_count":        fp,
        "false_positive_rate":         round(fp / with_5d * 100, 1) if with_5d else None,
        "pct_of_all_false_positives":  round(fp / total_fp * 100, 1) if total_fp else 0.0,
    }


def _group_by(items: list, key_fn: Callable) -> dict[str, list]:
    g: dict[str, list] = defaultdict(list)
    for c in items:
        cid = c.get("id")
        if cid is None:
            continue
        g[key_fn(c) or "UNKNOWN"].append(cid)
    return dict(g)


def _section(groups: dict, stats_fn: Callable, order: list = None,
             extra_fn: Callable = None) -> list[dict]:
    rows = []
    for k, cids in groups.items():
        row = {"bucket": k, **stats_fn(cids)}
        if extra_fn:
            row.update(extra_fn(k, cids))
        rows.append(row)
    if order:
        rows.sort(key=lambda r: order.index(r["bucket"]) if r["bucket"] in order else 99)
    else:
        rows.sort(key=lambda r: r.get("avg_return_5d") or r.get("avg_max_gain_10d_pct") or -999, reverse=True)
    return rows


# ── D-confluence resolver (mirrors research_bundle's _dc_label) ──────────────

def _resolve_dconf(c: dict, cget: Callable) -> str:
    v1 = cget(c, "d_confluence_type")
    if v1 and v1 != "NONE":
        return v1
    v2 = cget(c, "d_confluence_type_v2")
    if v2 and v2 != "NONE":
        return _DCONF_V2_TO_SIMPLE.get(v2, "NONE")
    return "NONE"


# ── Main entry point ─────────────────────────────────────────────────────────

def build_scanner_v2_validation(
    candidates: list[dict],
    outcomes:   list[dict],
    outcome_map: dict,
    mfe_map:    dict,
    cget:       Callable,
) -> dict:
    """
    Build all 11 scanner v2 validation sections.

    Returns a dict keyed by section name.  Adds debug counters tracking
    field coverage and reconstruction outcomes.  Never raises.
    """
    n_total = len(candidates)
    if n_total == 0:
        return {"_warning": "no candidates", "_debug": {}}

    # ── Resolve fields once per candidate ────────────────────────────────────
    resolved: list[dict] = []
    cov = {
        "scanner_v2_direct":        0,
        "scanner_v2_reconstructed": 0,
        "scanner_v2_unknown":       0,
        "priority_direct":          0,
        "priority_derived":         0,
        "priority_missing":         0,
        "sector_context_present":   0,
        "macro_context_present":    0,
    }
    for c in candidates:
        v2_dec, v2_src = resolve_scanner_v2_decision(c, cget)
        p_lab,  p_src  = resolve_priority_label(c, cget)
        cov[f"scanner_v2_{v2_src}"] += 1
        cov[f"priority_{p_src}"]    += 1
        if cget(c, "sector_context"):
            cov["sector_context_present"] += 1
        if cget(c, "macro_context"):
            cov["macro_context_present"] += 1
        resolved.append({
            "id":                  c.get("id"),
            "candidate":           c,
            "scanner_v2_decision": v2_dec or "UNKNOWN",
            "priority_label":      p_lab  or "UNKNOWN",
            "np_decision":         (cget(c, "np_decision") or cget(c, "decision")) or "UNKNOWN",
            "legacy_tier":         c.get("tier") or "UNKNOWN",
            "structure_phase":     cget(c, "structure_phase") or "UNKNOWN",
        })

    debug = {
        **cov,
        "scanner_v2_field_coverage_pct":   _pct(cov["scanner_v2_direct"], n_total),
        "scanner_v2_reconstructed_pct":    _pct(cov["scanner_v2_reconstructed"], n_total),
        "scanner_v2_unknown_pct":          _pct(cov["scanner_v2_unknown"], n_total),
        "priority_field_coverage_pct":     _pct(cov["priority_direct"], n_total),
        "priority_derived_pct":            _pct(cov["priority_derived"], n_total),
        "sector_context_coverage_pct":     _pct(cov["sector_context_present"], n_total),
        "macro_context_coverage_pct":      _pct(cov["macro_context_present"], n_total),
        "total_candidates":                n_total,
    }

    # ── Helper: build a virtual candidate list for grouping ──────────────────
    def cand_ids_for(key_fn):
        groups: dict[str, list] = defaultdict(list)
        for r in resolved:
            if r["id"] is None:
                continue
            groups[key_fn(r) or "UNKNOWN"].append(r["id"])
        return dict(groups)

    # Total false positives across all candidates
    total_fp = sum(
        1 for r in resolved
        if (outcome_map.get(r["id"], {}).get("5d") or {}).get("return_pct") is not None
        and outcome_map[r["id"]]["5d"]["return_pct"] < -5.0
    )

    bs = lambda cids: _bucket_stats(cids, outcome_map)
    ms = lambda cids: _mfe_stats(cids, mfe_map)

    # ── 1. performance_by_scanner_v2_decision ────────────────────────────────
    perf_v2 = _section(cand_ids_for(lambda r: r["scanner_v2_decision"]),
                       bs, order=V2_LABEL_ORDER)

    # ── 2. mfe_by_scanner_v2_decision ────────────────────────────────────────
    mfe_v2 = _section(cand_ids_for(lambda r: r["scanner_v2_decision"]),
                      ms, order=V2_LABEL_ORDER)

    # ── 3. false_positive_by_scanner_v2_decision ─────────────────────────────
    fp_v2_groups = cand_ids_for(lambda r: r["scanner_v2_decision"])
    fp_v2 = []
    for k in V2_LABEL_ORDER:
        if k not in fp_v2_groups:
            continue
        fp_v2.append({"bucket": k, **_fp_stats(fp_v2_groups[k], outcome_map, total_fp)})

    # ── 4. old_vs_new_scanner_comparison ─────────────────────────────────────
    def cmp_section(key_fn, order):
        groups = cand_ids_for(key_fn)
        out = []
        for k in (order if order else groups.keys()):
            if k not in groups:
                continue
            cids = groups[k]
            row = {"bucket": k}
            row.update({
                "count":                  len(cids),
                "avg_return_5d":          _avg([(outcome_map.get(cid, {}).get("5d") or {}).get("return_pct") for cid in cids]),
                "avg_return_10d":         _avg([(outcome_map.get(cid, {}).get("10d") or {}).get("return_pct") for cid in cids]),
            })
            mfe_row = _mfe_stats(cids, mfe_map)
            for k2 in ("avg_max_gain_10d_pct", "hit_10pct_rate", "hit_20pct_rate",
                       "hit_50pct_rate", "avg_giveback_10d_pct", "avg_time_to_max_gain_10d"):
                row[k2] = mfe_row.get(k2)
            row["false_positive_rate"] = _fp_stats(cids, outcome_map, total_fp)["false_positive_rate"]
            out.append(row)
        return out

    legacy_tier_order = ["FIRE", "ARM", "BASE", "WATCH", "STEALTH", "SYMPATHY", "SKIP", "UNKNOWN"]
    np_dec_order = ["BUY_CANDIDATE", "WATCH", "IMPULSE_RISK", "AVOID", "UNKNOWN"]

    old_vs_new = {
        "by_legacy_tier":         cmp_section(lambda r: r["legacy_tier"],         legacy_tier_order),
        "by_np_decision":         cmp_section(lambda r: r["np_decision"],         np_dec_order),
        "by_priority_label":      cmp_section(lambda r: r["priority_label"],      PRIORITY_ORDER),
        "by_scanner_v2_decision": cmp_section(lambda r: r["scanner_v2_decision"], V2_LABEL_ORDER),
    }

    # ── 5. performance_by_priority_label ─────────────────────────────────────
    perf_priority = _section(cand_ids_for(lambda r: r["priority_label"]),
                             bs, order=PRIORITY_ORDER)

    # ── 6. mfe_by_priority_label ─────────────────────────────────────────────
    mfe_priority = _section(cand_ids_for(lambda r: r["priority_label"]),
                            ms, order=PRIORITY_ORDER)

    # ── 7. performance_by_np_decision_priority_label (composite) ─────────────
    perf_np_priority = _section(
        cand_ids_for(lambda r: f"{r['np_decision']}|{r['priority_label']}"),
        bs,
    )

    # ── 8. performance_by_scanner_v2_decision_d_confluence ───────────────────
    def v2_x_dconf(r):
        return f"{r['scanner_v2_decision']}|{_resolve_dconf(r['candidate'], cget)}"
    perf_v2_dconf = _section(cand_ids_for(v2_x_dconf), bs)

    # ── 9. performance_by_scanner_v2_decision_sector_strength ────────────────
    def sector_strength(c: dict) -> str:
        sc = cget(c, "sector_context") or {}
        if not isinstance(sc, dict):
            return "UNKNOWN"
        return sc.get("sector_strength") or "UNKNOWN"

    def v2_x_sector(r):
        return f"{r['scanner_v2_decision']}|{sector_strength(r['candidate'])}"
    perf_v2_sector = _section(cand_ids_for(v2_x_sector), bs)

    # ── 10. performance_by_scanner_v2_decision_macro_regime ──────────────────
    def macro_regime(c: dict) -> str:
        mc = cget(c, "macro_context") or {}
        if not isinstance(mc, dict):
            return "UNKNOWN"
        return mc.get("market_regime") or mc.get("risk_mode") or "UNKNOWN"

    def v2_x_macro(r):
        return f"{r['scanner_v2_decision']}|{macro_regime(r['candidate'])}"
    perf_v2_macro = _section(cand_ids_for(v2_x_macro), bs)


    # ── 11. missed_movers_by_scanner_v2_decision ─────────────────────────────
    # "Routing miss" = candidate we scanned, routed to an AVOID/WATCH bucket,
    # but it moved >= STRONG_MOVER_THRESHOLD anyway.
    # Computable entirely from candidates + outcome_map — no missed_movers table needed.
    STRONG_MOVER_THRESHOLD = 10.0  # mirrors outcome_engine._MISSED_THRESHOLD_5D
    AVOID_BUCKETS = frozenset({"AVOID_DEAD", "AVOID_RISK", "AVOID_LOTTERY"})
    WATCH_BUCKETS = frozenset({"WATCH_LOW", "WATCH_MEDIUM", "WATCH_HIGH"})

    missed_by_v2: dict[str, dict] = {}
    for r in resolved:
        dec = r["scanner_v2_decision"]
        ret5 = (outcome_map.get(r["id"], {}).get("5d") or {}).get("return_pct")
        bucket = missed_by_v2.setdefault(dec, {
            "bucket": dec,
            "count": 0,
            "with_5d_data": 0,
            "strong_mover_count": 0,   # moved >= threshold
            "strong_mover_returns": [],
        })
        bucket["count"] += 1
        if ret5 is not None:
            bucket["with_5d_data"] += 1
            if ret5 >= STRONG_MOVER_THRESHOLD:
                bucket["strong_mover_count"] += 1
                bucket["strong_mover_returns"].append(ret5)

    missed_v2_rows = []
    for dec in V2_LABEL_ORDER:
        if dec not in missed_by_v2:
            continue
        b = missed_by_v2[dec]
        n_with = b["with_5d_data"]
        n_strong = b["strong_mover_count"]
        rets = b["strong_mover_returns"]
        is_routing_miss = dec in AVOID_BUCKETS
        missed_v2_rows.append({
            "bucket":               dec,
            "count":                b["count"],
            "with_5d_data":         n_with,
            "strong_mover_count":   n_strong,
            "strong_mover_rate":    round(n_strong / n_with * 100, 1) if n_with else None,
            "avg_return_5d_strong": _avg(rets),
            "is_routing_miss":      is_routing_miss,  # True for AVOID buckets
        })

    missed_v2 = {
        "available":          True,
        "threshold_5d_pct":   STRONG_MOVER_THRESHOLD,
        "by_decision":        missed_v2_rows,
        "routing_miss_total": sum(
            r["strong_mover_count"] for r in missed_v2_rows
            if r["bucket"] in AVOID_BUCKETS
        ),
        "routing_miss_in_watch": sum(
            r["strong_mover_count"] for r in missed_v2_rows
            if r["bucket"] in WATCH_BUCKETS
        ),
        "note": (
            "routing_miss = AVOID candidate that moved >= threshold; "
            "routing_miss_in_watch = WATCH candidate that moved >= threshold"
        ),
    }

    return {
        "performance_by_scanner_v2_decision":           perf_v2,
        "mfe_by_scanner_v2_decision":                   mfe_v2,
        "false_positive_by_scanner_v2_decision":        fp_v2,
        "old_vs_new_scanner_comparison":                old_vs_new,
        "performance_by_priority_label":                perf_priority,
        "mfe_by_priority_label":                        mfe_priority,
        "performance_by_np_decision_priority_label":    perf_np_priority,
        "performance_by_scanner_v2_decision_d_confluence":     perf_v2_dconf,
        "performance_by_scanner_v2_decision_sector_strength":  perf_v2_sector,
        "performance_by_scanner_v2_decision_macro_regime":     perf_v2_macro,
        "missed_movers_by_scanner_v2_decision":         missed_v2,
        "_debug":                                       debug,
    }
