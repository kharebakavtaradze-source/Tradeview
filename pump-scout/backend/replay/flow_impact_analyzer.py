"""
Flow Impact Analyzer — RESEARCH ONLY.

Computes flow_replay_score per episode and builds the full FLOW / Diagnostic
Replay Impact report section for Pattern Discovery exports.

Does NOT modify Scanner V2 routing. Does NOT produce BUY signals.
All outputs are labeled RESEARCH_ONLY or PUMP_WATCH_CONTEXT.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Research-only score thresholds ────────────────────────────────────────────

FLOW_BUCKET_HIGH   = "FLOW_RESEARCH_HIGH"
FLOW_BUCKET_MEDIUM = "FLOW_RESEARCH_MEDIUM"
FLOW_BUCKET_LOW    = "FLOW_RESEARCH_LOW"
FLOW_BUCKET_IGNORE = "FLOW_RESEARCH_IGNORE"

FLOW_THRESHOLD_HIGH   = 8
FLOW_THRESHOLD_MEDIUM = 5
FLOW_THRESHOLD_LOW    = 3

# ── Diagnostic label constants (mirror pump_watch_scorer) ─────────────────────

_DIAG_STRONG_RESCUE  = "PX_NO_SCANNER_RAW_STRENGTH_RESCUE_STRONG"
_DIAG_WEAK_RESCUE    = "PX_NO_SCANNER_RAW_STRENGTH_RESCUE_WEAK"
_DIAG_MISSING_STRUCT = "PX_MISSING_STRUCTURE_RESCUE"
_DIAG_REVERSE_SPLIT  = "PX_REVERSE_SPLIT_REGIME"
_DIAG_SPLIT_ART      = "SPLIT_ARTIFACT_EXCLUDED"

_ALL_DIAG_LABELS = [
    _DIAG_STRONG_RESCUE,
    _DIAG_WEAK_RESCUE,
    _DIAG_MISSING_STRUCT,
    _DIAG_REVERSE_SPLIT,
    _DIAG_SPLIT_ART,
]

# ── Flow subtype constants ────────────────────────────────────────────────────

_ALL_FLOW_SUBTYPES = [
    "FLOW_DIVERGENCE",
    "FLOW_BEARISH_STRESS",
    "FLOW_ABSORPTION",
    "FLOW_BULLISH_ACCUM",
    "FLOW_GAP_FADE_OR_FAIL",
    "FLOW_MIXED_CONTEXT",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_diag(val) -> list:
    """Normalize pump_watch_diagnostic_labels from DB JSON string or in-memory list."""
    if val is None:
        return []
    if isinstance(val, list):
        return val
    try:
        import json
        result = json.loads(val)
        return result if isinstance(result, list) else []
    except Exception:
        return []


def _median(lst: list) -> Optional[float]:
    if not lst:
        return None
    s = sorted(lst)
    return s[len(s) // 2]


def _safe_rate(num: int, denom: int) -> Optional[float]:
    return round(num / denom, 3) if denom > 0 else None


def _ep_sym(ep: dict) -> str:
    return ep.get("symbol") or ep.get("ticker") or "?"


def _ep_label(ep: dict) -> str:
    sym = _ep_sym(ep)
    pm  = ep.get("pump_multiple")
    return f"{sym}({pm:.1f}x)" if pm else sym


# ── Episode flow context inference ────────────────────────────────────────────

def _infer_episode_flow_context(ep: dict) -> str:
    """
    Assign a primary flow context to an episode based on PRE-window features only.
    No forward-return leakage — uses only features available before breakout.
    """
    diag        = _parse_diag(ep.get("pump_watch_diagnostic_labels"))
    bc_days     = ep.get("buy_candidate_day_count_pre") or 0
    no_scanner  = (bc_days <= 1
                   and not ep.get("had_np_buy_candidate_pre")
                   and not ep.get("had_np_watch_pre"))
    has_accum   = (bool(ep.get("had_accumulation_like"))
                   or (ep.get("accumulation_like_day_count") or 0) >= 3)
    has_spring  = bool(ep.get("had_spring_test_lps"))
    max_ss      = ep.get("max_structure_score_pre") or 0
    dryup       = ep.get("dryup_day_count_pre") or 0
    compression = ep.get("compression_days_pre") or 0
    exp_risk    = ep.get("max_expansion_timing_risk_pre") or ""

    # Divergence: hidden accumulation / raw strength not seen by scanner
    if _DIAG_STRONG_RESCUE in diag and has_accum:
        return "FLOW_DIVERGENCE"
    if no_scanner and has_accum and max_ss >= 35 and dryup >= 8:
        return "FLOW_DIVERGENCE"
    if no_scanner and has_spring and dryup >= 8:
        return "FLOW_DIVERGENCE"

    # Absorption: Wyckoff spring / reclaim with base building
    if has_spring and (has_accum or dryup >= 8):
        return "FLOW_ABSORPTION"
    if has_accum and dryup >= 10:
        return "FLOW_ABSORPTION"
    if has_accum and compression >= 6:
        return "FLOW_ABSORPTION"

    # Bearish stress: expansion risk with structure overhead, no accumulation evidence
    if exp_risk == "HIGH" and max_ss >= 50 and not has_accum:
        return "FLOW_BEARISH_STRESS"

    # Bullish accum: scanner pressure + base building
    if not no_scanner and (has_accum or dryup >= 8 or compression >= 5):
        return "FLOW_BULLISH_ACCUM"

    return "FLOW_MIXED_CONTEXT"


# ── Flow replay score ─────────────────────────────────────────────────────────

def compute_flow_replay_score(ep: dict) -> dict:
    """
    Research-only FLOW replay score for one episode.
    NOT wired to Scanner V2. Does NOT produce BUY signals.
    """
    score      = 0
    reasons    = []
    risk_flags = []

    diag        = _parse_diag(ep.get("pump_watch_diagnostic_labels"))
    dryup       = ep.get("dryup_day_count_pre") or 0
    d_days      = ep.get("d_confluence_day_count_pre") or 0
    compression = ep.get("compression_days_pre") or 0
    acc_days    = ep.get("accumulation_like_day_count") or 0
    has_accum   = bool(ep.get("had_accumulation_like")) or acc_days >= 3
    has_spring  = bool(ep.get("had_spring_test_lps"))
    bc_days     = ep.get("buy_candidate_day_count_pre") or 0
    ema50_rec   = ep.get("ema50_reclaim_count_pre") or 0
    split_ctx   = ep.get("split_context") or ""

    flow_context = _infer_episode_flow_context(ep)

    # ── Flow context base score ───────────────────────────────────────────────
    if flow_context == "FLOW_DIVERGENCE":
        score += 3
        reasons.append("FLOW_DIVERGENCE: hidden accum / raw strength vs no scanner")
    elif flow_context == "FLOW_ABSORPTION":
        score += 2
        reasons.append("FLOW_ABSORPTION: spring test / reclaim with base building")
    elif flow_context == "FLOW_GAP_FADE_OR_FAIL":
        if has_accum or has_spring:
            score += 2
            reasons.append("FLOW_GAP_FADE_OR_FAIL with reclaim evidence")
    elif flow_context == "FLOW_BEARISH_STRESS":
        score += 1
        reasons.append("FLOW_BEARISH_STRESS: supply overhead detected")

    # ── Specific signal proxies ───────────────────────────────────────────────
    # ADL_ACCUM + OBV_DISTRIB proxy: accumulation with dryup (classic divergence)
    if has_accum and dryup >= 8:
        score += 2
        reasons.append(f"accum_with_dryup={dryup} (ADL_ACCUM proxy)")

    # LOWER_WICK_ABSORPTION proxy: spring test (wick through support, close above)
    if has_spring:
        score += 2
        reasons.append("spring_test_lps (LOWER_WICK_ABSORPTION proxy)")

    # GAP_DOWN_RECLAIM / CMF_TURN_UP proxy: ema50 reclaim after dry-up
    if ema50_rec >= 2 and dryup >= 5:
        score += 2
        reasons.append(f"ema50_reclaim={ema50_rec}_after_dryup (GAP_DOWN_RECLAIM proxy)")
    elif ema50_rec >= 1 and dryup >= 5:
        score += 1
        reasons.append(f"ema50_reclaim={ema50_rec} (CMF_TURN_UP proxy)")

    # DELTA_PROXY_BULL: repeated buy pressure with accumulation
    if bc_days >= 4 and has_accum:
        score += 1
        reasons.append(f"buy_pressure={bc_days}d_with_accum (DELTA_PROXY_BULL proxy)")

    # ── Context bonuses ───────────────────────────────────────────────────────
    if 8 <= dryup <= 25:
        score += 2
        reasons.append(f"dryup_sweet_spot={dryup}")
    elif dryup >= 5:
        score += 1

    if d_days >= 4:
        score += 2
        reasons.append(f"d_confluence_days={d_days}")
    elif d_days >= 2:
        score += 1

    if compression >= 6:
        score += 1
        reasons.append(f"compression_days={compression}")

    # Avoid double-adding accum/spring already counted above
    if has_accum and not any("accum" in r for r in reasons):
        score += 1
        reasons.append("had_accumulation_like")
    if has_spring and not any("spring" in r for r in reasons):
        score += 1
        reasons.append("had_spring_test_lps")

    # ── Penalties ─────────────────────────────────────────────────────────────
    if ep.get("split_artifact_risk"):
        score -= 3
        risk_flags.append("split_artifact_risk")

    if split_ctx == "RECENT_REVERSE_SPLIT":
        score -= 2
        risk_flags.append("recent_reverse_split_regime")

    med_dv = ep.get("median_dollar_volume_pre") or 0
    if 0 < med_dv < 50_000:
        score -= 2
        risk_flags.append(f"low_dollar_volume={med_dv:.0f}")

    # Bearish stress without any reclaim evidence = trap risk
    if (flow_context == "FLOW_BEARISH_STRESS"
            and not has_accum and not has_spring and ema50_rec < 1):
        score -= 2
        risk_flags.append("bearish_stress_without_reclaim")

    # High-FP pattern in context: weak rescue fires but episode is likely FP
    if _DIAG_WEAK_RESCUE in diag and _DIAG_STRONG_RESCUE not in diag:
        score -= 1
        risk_flags.append("weak_rescue_only_no_strong_confirmation")

    # ── Bucket assignment ─────────────────────────────────────────────────────
    score = max(-10, min(20, score))
    if score >= FLOW_THRESHOLD_HIGH:
        bucket = FLOW_BUCKET_HIGH
    elif score >= FLOW_THRESHOLD_MEDIUM:
        bucket = FLOW_BUCKET_MEDIUM
    elif score >= FLOW_THRESHOLD_LOW:
        bucket = FLOW_BUCKET_LOW
    else:
        bucket = FLOW_BUCKET_IGNORE

    return {
        "flow_replay_score":      score,
        "flow_replay_bucket":     bucket,
        "flow_replay_reasons":    reasons,
        "flow_replay_risk_flags": risk_flags,
        "flow_replay_context":    flow_context,
    }


def score_episodes_flow(episodes: list[dict]) -> list[dict]:
    """Add flow_replay_* fields to episode dicts. Returns augmented copies."""
    return [{**ep, **compute_flow_replay_score(ep)} for ep in episodes]


# ── Part 2A: By flow subtype ──────────────────────────────────────────────────

def _build_by_flow_subtype(
    episodes: list[dict],
    flow_patterns: list[dict],
) -> list[dict]:
    """
    Per-flow-subtype stats: episode-level outcomes + pattern-level reliability.
    Episode flow_subtype is derived from inferred context (approximation).
    Pattern reliability aggregated from discovered FLOW/COMBINED patterns.
    """
    # Pattern-level aggregation by flow_subtype
    pat_by_st: dict[str, dict] = {}
    for p in flow_patterns:
        st = p.get("flow_subtype") or "FLOW_MIXED_CONTEXT"
        if st == "N/A":
            st = "FLOW_MIXED_CONTEXT"
        g = pat_by_st.setdefault(st, {"count": 0, "rs": [], "fpr": []})
        g["count"] += 1
        rs = p.get("reliability_score")
        if rs is not None:
            g["rs"].append(rs)
        fpr = p.get("false_positive_rate")
        if fpr is not None:
            g["fpr"].append(fpr)

    # Episode-level grouping by inferred flow context
    ep_by_st: dict[str, list] = {st: [] for st in _ALL_FLOW_SUBTYPES}
    for ep in episodes:
        ctx = ep.get("flow_replay_context") or _infer_episode_flow_context(ep)
        ep_by_st.setdefault(ctx, []).append(ep)

    rows: list[dict] = []
    for st in _ALL_FLOW_SUBTYPES:
        eps   = ep_by_st.get(st, [])
        total = len(eps)
        n_4x  = sum(1 for e in eps if e.get("group_type") == "4x_pump")
        n_fp  = sum(1 for e in eps if e.get("group_type") == "false_positive")
        n_nw  = sum(1 for e in eps if e.get("group_type") == "normal_winner")
        pw_scores = [e.get("pump_watch_score") or 0 for e in eps]
        art_rates = [1 if e.get("split_artifact_risk") else 0 for e in eps]

        pat_data = pat_by_st.get(st, {})
        rs_list  = pat_data.get("rs", [])

        best_eps = sorted(
            [e for e in eps if e.get("group_type") == "4x_pump"],
            key=lambda x: -(x.get("pump_multiple") or 0),
        )
        worst_eps = sorted(
            [e for e in eps if e.get("group_type") == "false_positive"],
            key=lambda x: -(x.get("pump_watch_score") or 0),
        )

        rows.append({
            "flow_subtype":              st,
            "candidate_count":           total,
            "4x_count":                  n_4x,
            "false_positive_count":      n_fp,
            "normal_winner_count":       n_nw,
            "4x_rate":                   _safe_rate(n_4x, total),
            "false_positive_rate":       _safe_rate(n_fp, total),
            "median_reliability_score":  _median(rs_list),
            "median_pump_watch_score":   _median(pw_scores) if pw_scores else None,
            "split_artifact_exposure_avg": round(sum(art_rates) / total, 3) if total else None,
            "pattern_count":             pat_data.get("count", 0),
            "best_example_symbols":      [_ep_label(e) for e in best_eps[:5]],
            "worst_example_symbols":     [_ep_label(e) for e in worst_eps[:5]],
        })

    return rows


# ── Part 2B: By diagnostic label ─────────────────────────────────────────────

def _build_by_diagnostic_label(episodes: list[dict]) -> list[dict]:
    """Per-diagnostic-label stats: 4x rate, FP rate, median score, examples."""
    rows: list[dict] = []
    for lbl in _ALL_DIAG_LABELS:
        matching = [
            e for e in episodes
            if lbl in _parse_diag(e.get("pump_watch_diagnostic_labels"))
        ]
        total = len(matching)
        n_4x  = sum(1 for e in matching if e.get("group_type") == "4x_pump")
        n_fp  = sum(1 for e in matching if e.get("group_type") == "false_positive")
        n_nw  = sum(1 for e in matching if e.get("group_type") == "normal_winner")
        pw_scores = [e.get("pump_watch_score") or 0 for e in matching]

        rows.append({
            "diagnostic_label":        lbl,
            "candidate_count":         total,
            "4x_count":                n_4x,
            "false_positive_count":    n_fp,
            "normal_winner_count":     n_nw,
            "4x_rate":                 _safe_rate(n_4x, total),
            "false_positive_rate":     _safe_rate(n_fp, total),
            "median_pump_watch_score": _median(pw_scores) if pw_scores else None,
            "examples_4x": [
                _ep_label(e) for e in sorted(
                    [e for e in matching if e.get("group_type") == "4x_pump"],
                    key=lambda x: -(x.get("pump_multiple") or 0),
                )[:5]
            ],
            "examples_false_positive": [
                _ep_label(e) for e in sorted(
                    [e for e in matching if e.get("group_type") == "false_positive"],
                    key=lambda x: -(x.get("pump_watch_score") or 0),
                )[:5]
            ],
        })
    return rows


# ── Part 2C: Combination analysis ────────────────────────────────────────────

def _combo_stats(episodes: list[dict], filter_fn, name: str) -> dict:
    matching = [e for e in episodes if filter_fn(e)]
    total    = len(matching)
    n_4x     = sum(1 for e in matching if e.get("group_type") == "4x_pump")
    n_fp     = sum(1 for e in matching if e.get("group_type") == "false_positive")
    n_nw     = sum(1 for e in matching if e.get("group_type") == "normal_winner")
    pm_vals  = [e.get("pump_multiple") for e in matching if e.get("pump_multiple") is not None]
    precision = _safe_rate(n_4x, n_4x + n_fp) if (n_4x + n_fp) > 0 else None

    return {
        "combination":          name,
        "matched_count":        total,
        "4x_count":             n_4x,
        "false_positive_count": n_fp,
        "normal_winner_count":  n_nw,
        "4x_rate":              _safe_rate(n_4x, total),
        "false_positive_rate":  _safe_rate(n_fp, total),
        "precision_4x_vs_fp":   precision,
        "median_pump_multiple": _median(pm_vals),
        "symbols_4x": [
            _ep_label(e) for e in sorted(
                [e for e in matching if e.get("group_type") == "4x_pump"],
                key=lambda x: -(x.get("pump_multiple") or 0),
            )[:8]
        ],
        "symbols_false_positive": [
            _ep_label(e) for e in sorted(
                [e for e in matching if e.get("group_type") == "false_positive"],
                key=lambda x: -(x.get("pump_watch_score") or 0),
            )[:8]
        ],
    }


def _build_combo_analysis(episodes: list[dict]) -> list[dict]:
    def _ctx(e):  return e.get("flow_replay_context") or _infer_episode_flow_context(e)
    def _diag(e): return _parse_diag(e.get("pump_watch_diagnostic_labels"))
    def _dryup(e):   return (e.get("dryup_day_count_pre") or 0) >= 8
    def _dconf(e):   return (e.get("d_confluence_day_count_pre") or 0) >= 4
    def _comp(e):    return (e.get("compression_days_pre") or 0) >= 6
    def _no_art(e):  return not e.get("split_artifact_risk")
    def _no_rs(e):   return (e.get("split_context") or "") not in (
        "RECENT_REVERSE_SPLIT", "OLD_REVERSE_SPLIT")
    def _clean(e):   return (e.get("split_context") or "NO_SPLIT") == "NO_SPLIT"
    def _rescue(e):  return _DIAG_STRONG_RESCUE in _diag(e)
    def _lower(e):   return e.get("had_spring_test_lps") or e.get("had_accumulation_like")
    def _div(e):     return _ctx(e) == "FLOW_DIVERGENCE"
    def _stress(e):  return _ctx(e) == "FLOW_BEARISH_STRESS"
    def _absorp(e):  return _ctx(e) == "FLOW_ABSORPTION"

    combos = [
        ("FLOW_DIVERGENCE only",                   lambda e: _div(e)),
        ("FLOW_DIVERGENCE + dryup>=8",             lambda e: _div(e) and _dryup(e)),
        ("FLOW_DIVERGENCE + D-confluence>=4",      lambda e: _div(e) and _dconf(e)),
        ("FLOW_DIVERGENCE + dryup>=8 + D-conf>=4", lambda e: _div(e) and _dryup(e) and _dconf(e)),
        ("FLOW_BEARISH_STRESS only",               lambda e: _stress(e)),
        ("FLOW_BEARISH_STRESS + dryup>=8",         lambda e: _stress(e) and _dryup(e)),
        ("FLOW_BEARISH_STRESS + compression>=6",   lambda e: _stress(e) and _comp(e)),
        ("FLOW_ABSORPTION + lower_wick/reclaim",   lambda e: _absorp(e) and _lower(e)),
        ("STRONG_RESCUE only",                     lambda e: _rescue(e)),
        ("STRONG_RESCUE + D-confluence>=4",        lambda e: _rescue(e) and _dconf(e)),
        ("STRONG_RESCUE + no_split_artifact",      lambda e: _rescue(e) and _no_art(e)),
        ("FLOW_DIVERGENCE + STRONG_RESCUE",        lambda e: _div(e) and _rescue(e)),
        ("FLOW_DIVERGENCE + no_reverse_split",     lambda e: _div(e) and _no_rs(e)),
        ("FLOW_DIVERGENCE + split_context=NO_SPLIT", lambda e: _div(e) and _clean(e)),
    ]

    return [_combo_stats(episodes, fn, name) for name, fn in combos]


# ── Part 3: Missed 4x rescue candidates ──────────────────────────────────────

def _rescue_narrative(ep: dict, diag: list, pw_label: str, flow_ctx: str) -> str:
    parts = []
    if _DIAG_STRONG_RESCUE in diag:
        parts.append("STRONG_RESCUE: no scanner pressure + strong raw evidence → PUMP_IGNORE→PUMP_SPECULATIVE")
    if _DIAG_WEAK_RESCUE in diag:
        parts.append("WEAK_RESCUE: no scanner pressure + moderate raw evidence (diagnostic only)")
    if _DIAG_MISSING_STRUCT in diag:
        parts.append("MISSING_STRUCTURE: zero structure rescued by dryup+D-conf+trend")
    if flow_ctx == "FLOW_DIVERGENCE":
        parts.append("FLOW_DIVERGENCE: accumulation hidden from scanner")
    if flow_ctx == "FLOW_ABSORPTION":
        parts.append("FLOW_ABSORPTION: spring test / base building detected")
    if pw_label == "PUMP_IGNORE":
        parts.append("still PUMP_IGNORE — rescue threshold not met")
    elif pw_label == "PUMP_SPECULATIVE":
        parts.append("rescued → PUMP_SPECULATIVE")
    return "; ".join(parts) if parts else "Notable 4x miss — review manually"


def _build_missed_4x_rescue(episodes: list[dict]) -> list[dict]:
    """
    4x pump episodes caught by FLOW or diagnostic rescue labels.
    Includes episodes that were PUMP_IGNORE/PUMP_SPECULATIVE or carry a rescue diag.
    """
    rescue_set = {_DIAG_STRONG_RESCUE, _DIAG_WEAK_RESCUE, _DIAG_MISSING_STRUCT}

    rows = []
    for ep in episodes:
        if ep.get("group_type") != "4x_pump":
            continue
        diag        = _parse_diag(ep.get("pump_watch_diagnostic_labels"))
        has_rescue  = bool(rescue_set & set(diag))
        pw_label    = ep.get("pump_watch_label") or ""
        flow_ctx    = ep.get("flow_replay_context") or _infer_episode_flow_context(ep)
        flow_bucket = ep.get("flow_replay_bucket") or FLOW_BUCKET_IGNORE

        interesting = (
            has_rescue
            or pw_label in ("PUMP_IGNORE", "PUMP_SPECULATIVE")
            or flow_bucket in (FLOW_BUCKET_HIGH, FLOW_BUCKET_MEDIUM)
        )
        if not interesting:
            continue

        rows.append({
            "symbol":                  _ep_sym(ep),
            "pump_multiple":           ep.get("pump_multiple"),
            "pump_watch_label":        pw_label,
            "pump_watch_score":        ep.get("pump_watch_score"),
            "pump_watch_confidence":   ep.get("pump_watch_confidence"),
            "diagnostic_labels":       diag,
            "pump_watch_rescue_reason": ep.get("pump_watch_rescue_reason"),
            "flow_context":            flow_ctx,
            "flow_replay_bucket":      flow_bucket,
            "flow_replay_score":       ep.get("flow_replay_score"),
            "flow_replay_reasons":     ep.get("flow_replay_reasons") or [],
            "split_context":           ep.get("split_context"),
            "dryup_day_count_pre":     ep.get("dryup_day_count_pre"),
            "compression_days_pre":    ep.get("compression_days_pre"),
            "d_confluence_day_count_pre": ep.get("d_confluence_day_count_pre"),
            "max_structure_score_pre": ep.get("max_structure_score_pre"),
            "had_accumulation_like":   ep.get("had_accumulation_like"),
            "had_spring_test_lps":     ep.get("had_spring_test_lps"),
            "why_it_matters":          _rescue_narrative(ep, diag, pw_label, flow_ctx),
        })

    return sorted(rows, key=lambda x: -(x.get("pump_multiple") or 0))


# ── Part 4: False positive traps ─────────────────────────────────────────────

def _trap_narrative(ep: dict, diag: list, flow_ctx: str, risk_flags: list) -> list[str]:
    reasons = []
    split_ctx = ep.get("split_context") or ""
    rf_str    = " ".join(risk_flags)
    if _DIAG_REVERSE_SPLIT in diag:
        reasons.append(f"reverse_split_regime ({split_ctx}) — RS triggers false strength signals")
    if _DIAG_STRONG_RESCUE in diag:
        reasons.append("STRONG_RESCUE fired but still FP — raw strength ≠ pump outcome")
    if flow_ctx == "FLOW_BEARISH_STRESS":
        reasons.append("FLOW_BEARISH_STRESS without reclaim — supply trap, not absorption")
    if "low_dollar_volume" in rf_str:
        reasons.append("low dollar volume — pattern unreliable below $50K ADTV")
    if "high_expansion_risk" in rf_str:
        reasons.append("high expansion timing risk — volatility regime marker, not pump")
    if "no_scanner_pressure" in rf_str:
        reasons.append("no scanner pressure — low institutional interest")
    if "bearish_stress_without_reclaim" in " ".join(ep.get("flow_replay_risk_flags") or []):
        reasons.append("bearish stress without reclaim — potential supply overhang")
    if not reasons:
        reasons.append("high FLOW/PW score in false positive — manual review needed")
    return reasons


def _build_false_positive_traps(episodes: list[dict]) -> list[dict]:
    """
    False positive episodes with high FLOW/diagnostic activity — trap patterns.
    Top 20 by pump_watch_score descending.
    """
    trap_diags = {_DIAG_STRONG_RESCUE, _DIAG_WEAK_RESCUE, _DIAG_REVERSE_SPLIT}

    rows = []
    for ep in episodes:
        if ep.get("group_type") != "false_positive":
            continue
        diag        = _parse_diag(ep.get("pump_watch_diagnostic_labels"))
        has_diag    = bool(trap_diags & set(diag))
        flow_ctx    = ep.get("flow_replay_context") or _infer_episode_flow_context(ep)
        flow_bucket = ep.get("flow_replay_bucket") or FLOW_BUCKET_IGNORE
        pw_score    = ep.get("pump_watch_score") or 0
        risk_flags  = list(ep.get("pump_watch_risk_flags") or [])

        interesting = (
            has_diag
            or pw_score >= 30
            or flow_bucket in (FLOW_BUCKET_HIGH, FLOW_BUCKET_MEDIUM)
        )
        if not interesting:
            continue

        rows.append({
            "symbol":                  _ep_sym(ep),
            "pump_multiple":           ep.get("pump_multiple"),
            "pump_watch_label":        ep.get("pump_watch_label"),
            "pump_watch_score":        pw_score,
            "flow_context":            flow_ctx,
            "flow_replay_bucket":      flow_bucket,
            "flow_replay_score":       ep.get("flow_replay_score"),
            "diagnostic_labels":       diag,
            "split_context":           ep.get("split_context"),
            "split_artifact_risk":     ep.get("split_artifact_risk"),
            "pump_watch_risk_flags":   risk_flags,
            "trap_reasons":            _trap_narrative(ep, diag, flow_ctx, risk_flags),
            "dryup_day_count_pre":     ep.get("dryup_day_count_pre"),
            "compression_days_pre":    ep.get("compression_days_pre"),
            "d_confluence_day_count_pre": ep.get("d_confluence_day_count_pre"),
            "max_structure_score_pre": ep.get("max_structure_score_pre"),
            "median_dollar_volume_pre": ep.get("median_dollar_volume_pre"),
        })

    return sorted(rows, key=lambda x: -(x.get("pump_watch_score") or 0))[:20]


# ── Part 5: Flow replay score distribution ───────────────────────────────────

def _build_flow_replay_distribution(episodes: list[dict]) -> dict:
    result = {}
    for bucket in [FLOW_BUCKET_HIGH, FLOW_BUCKET_MEDIUM, FLOW_BUCKET_LOW, FLOW_BUCKET_IGNORE]:
        matching = [e for e in episodes if e.get("flow_replay_bucket") == bucket]
        total    = len(matching)
        n_4x     = sum(1 for e in matching if e.get("group_type") == "4x_pump")
        n_fp     = sum(1 for e in matching if e.get("group_type") == "false_positive")
        n_nw     = sum(1 for e in matching if e.get("group_type") == "normal_winner")
        pm_vals  = [e.get("pump_multiple") for e in matching if e.get("pump_multiple") is not None]
        result[bucket] = {
            "total":                total,
            "4x_count":             n_4x,
            "false_positive_count": n_fp,
            "normal_winner_count":  n_nw,
            "4x_rate":              _safe_rate(n_4x, total),
            "false_positive_rate":  _safe_rate(n_fp, total),
            "median_pump_multiple": _median(pm_vals),
        }
    return result


# ── Part 6: Pump Watch vs FLOW matrix ────────────────────────────────────────

def _build_pump_watch_vs_flow_matrix(episodes: list[dict]) -> dict:
    pw_labels    = ["PUMP_WATCH_HIGH", "PUMP_WATCH_MEDIUM", "PUMP_SPECULATIVE", "PUMP_IGNORE"]
    flow_buckets = [FLOW_BUCKET_HIGH, FLOW_BUCKET_MEDIUM, FLOW_BUCKET_LOW, FLOW_BUCKET_IGNORE]

    def _stats(eps):
        total   = len(eps)
        n_4x    = sum(1 for e in eps if e.get("group_type") == "4x_pump")
        n_fp    = sum(1 for e in eps if e.get("group_type") == "false_positive")
        pm_vals = [e.get("pump_multiple") for e in eps if e.get("pump_multiple") is not None]
        return {
            "total":                total,
            "4x_count":             n_4x,
            "false_positive_count": n_fp,
            "normal_winner_count":  sum(1 for e in eps if e.get("group_type") == "normal_winner"),
            "4x_rate":              _safe_rate(n_4x, total),
            "false_positive_rate":  _safe_rate(n_fp, total),
            "median_pump_multiple": _median(pm_vals),
        }

    by_pw  = {lbl:    _stats([e for e in episodes if e.get("pump_watch_label") == lbl])
              for lbl in pw_labels}
    by_flow = {bkt:   _stats([e for e in episodes if e.get("flow_replay_bucket") == bkt])
               for bkt in flow_buckets}

    # Cross-table rows=pw_label, cols=flow_bucket
    cross = []
    for lbl in pw_labels:
        cells = {}
        for bkt in flow_buckets:
            sub = [e for e in episodes
                   if e.get("pump_watch_label") == lbl
                   and e.get("flow_replay_bucket") == bkt]
            tot = len(sub)
            n4  = sum(1 for e in sub if e.get("group_type") == "4x_pump")
            nfp = sum(1 for e in sub if e.get("group_type") == "false_positive")
            cells[bkt] = {"total": tot, "4x_count": n4,
                          "false_positive_count": nfp,
                          "4x_rate": _safe_rate(n4, tot)}
        cross.append({"pump_watch_label": lbl, "cells": cells})

    fh = by_flow.get(FLOW_BUCKET_HIGH, {})
    ph = by_pw.get("PUMP_WATCH_HIGH", {})

    analysis = {
        "flow_research_high_beats_pw_high": (
            (fh.get("4x_rate") or 0) > (ph.get("4x_rate") or 0)
        ),
        "flow_research_high_catches_ignored_4x": any(
            e.get("flow_replay_bucket") == FLOW_BUCKET_HIGH
            and e.get("pump_watch_label") == "PUMP_IGNORE"
            and e.get("group_type") == "4x_pump"
            for e in episodes
        ),
        "flow_reduces_fp_in_high": (
            (fh.get("false_positive_rate") or 1.0) < (ph.get("false_positive_rate") or 1.0)
        ),
        "flow_divergence_improves_medium_speculative": any(
            e.get("flow_replay_context") == "FLOW_DIVERGENCE"
            and e.get("pump_watch_label") in ("PUMP_WATCH_MEDIUM", "PUMP_SPECULATIVE")
            and e.get("group_type") == "4x_pump"
            for e in episodes
        ),
    }

    return {
        "by_pump_watch_label": by_pw,
        "by_flow_bucket":      by_flow,
        "cross_table":         cross,
        "analysis_questions":  analysis,
        "note": (
            "RESEARCH ONLY. flow_replay_score is experimental. "
            "Do NOT use to change Scanner V2 BUY/WATCH/AVOID routing."
        ),
    }


# ── Recommendations ───────────────────────────────────────────────────────────

def _build_recommendations(episodes: list[dict], flow_patterns: list[dict]) -> list[str]:
    recs = []

    fh_eps  = [e for e in episodes if e.get("flow_replay_bucket") == FLOW_BUCKET_HIGH]
    if fh_eps:
        fh_4x = sum(1 for e in fh_eps if e.get("group_type") == "4x_pump")
        fh_fp = sum(1 for e in fh_eps if e.get("group_type") == "false_positive")
        fh_4x_rate = fh_4x / len(fh_eps)
        fh_fp_rate = fh_fp / len(fh_eps)
        if fh_4x_rate > 0.25 and fh_fp_rate < 0.30:
            recs.append(
                f"FLOW_RESEARCH_HIGH (n={len(fh_eps)}): 4x_rate={fh_4x_rate:.1%}, "
                f"fp_rate={fh_fp_rate:.1%}. Promising — validate on next run before "
                "adding to Pump Watch context."
            )
        elif fh_fp_rate > fh_4x_rate:
            recs.append(
                f"FLOW_RESEARCH_HIGH fp_rate ({fh_fp_rate:.1%}) > 4x_rate ({fh_4x_rate:.1%}). "
                "Threshold too loose — add dryup>=8 + D-confluence>=4 gates."
            )

    sr_eps = [e for e in episodes
              if _DIAG_STRONG_RESCUE in _parse_diag(e.get("pump_watch_diagnostic_labels"))]
    if sr_eps:
        sr_4x = sum(1 for e in sr_eps if e.get("group_type") == "4x_pump")
        sr_fp = sum(1 for e in sr_eps if e.get("group_type") == "false_positive")
        sr_rate = sr_4x / len(sr_eps)
        recs.append(
            f"STRONG_RESCUE (n={len(sr_eps)}): 4x_rate={sr_rate:.1%}, "
            f"4x={sr_4x}, fp={sr_fp}. "
            + ("Useful — worth PUMP_WATCH_CONTEXT consideration." if sr_rate > 0.25
               else "Needs more validation runs.")
        )

    wr_eps = [e for e in episodes
              if _DIAG_WEAK_RESCUE in _parse_diag(e.get("pump_watch_diagnostic_labels"))]
    if wr_eps:
        wr_fp_rate = (
            sum(1 for e in wr_eps if e.get("group_type") == "false_positive") / len(wr_eps)
        )
        if wr_fp_rate > 0.35:
            recs.append(
                f"WEAK_RESCUE fp_rate={wr_fp_rate:.1%} — keep diagnostic/debug only. "
                "Do NOT promote to routing rescue."
            )

    div_pats = [p for p in flow_patterns if p.get("flow_subtype") == "FLOW_DIVERGENCE"]
    if div_pats:
        top3 = sorted(div_pats, key=lambda x: -(x.get("reliability_score") or 0))[:3]
        recs.append(
            f"Top FLOW_DIVERGENCE patterns: {', '.join(p['signal_id'] for p in top3)}. "
            "Replay validate before adding to Pump Watch signal library."
        )

    recs.append(
        "CONSTRAINT: Do NOT use flow_replay_score or flow_replay_bucket to modify "
        "Scanner V2 BUY/WATCH/AVOID routing. All outputs are RESEARCH_ONLY."
    )
    return recs


# ── Main builder ──────────────────────────────────────────────────────────────

def build_flow_impact_report(
    episodes: list[dict],
    flow_patterns: list[dict],
) -> dict:
    """
    Build the full FLOW / Diagnostic Replay Impact report.

    Parameters
    ----------
    episodes      : DB-loaded or in-memory episodes; flow_replay_* fields are
                    added automatically if not already present.
    flow_patterns : discovered FLOW + COMBINED patterns with flow_subtype set.

    Returns a dict suitable for ``flow_replay_analysis`` in discovery exports.
    """
    if not episodes:
        return {
            "report_type": "flow_diagnostic_replay_impact",
            "safety_note": "RESEARCH ONLY.",
            "empty": True,
        }

    # Score episodes with flow_replay fields if not already done
    if "flow_replay_score" not in (episodes[0] if episodes else {}):
        episodes = score_episodes_flow(episodes)

    return {
        "report_type":    "flow_diagnostic_replay_impact",
        "safety_note":    (
            "RESEARCH ONLY. Do NOT use to modify Scanner V2 routing or BUY decisions."
        ),
        "episode_count":  len(episodes),
        "by_flow_subtype":    _build_by_flow_subtype(episodes, flow_patterns),
        "by_diagnostic_label": _build_by_diagnostic_label(episodes),
        "combo_analysis":     _build_combo_analysis(episodes),
        "missed_4x_rescue_candidates": _build_missed_4x_rescue(episodes),
        "false_positive_traps": _build_false_positive_traps(episodes),
        "flow_replay_score_distribution": _build_flow_replay_distribution(episodes),
        "pump_watch_vs_flow_matrix": _build_pump_watch_vs_flow_matrix(episodes),
        "recommendations":    _build_recommendations(episodes, flow_patterns),
    }
