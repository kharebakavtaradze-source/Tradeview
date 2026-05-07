"""
Custom / FLOW / Regime Selector v1 — Research Only.

Scores every episode on a badge-level + regime-gated ranking.
ABR is DISABLED in v1 (use_abr = False) — ABR remains diagnostic only.

Scoring contract
----------------
  score = pump_watch_base + flow_setup + flow_trigger
          + custom_confirmation + regime + risk_penalty

Buckets:
  CFR_A     — score >= 9 AND all 5 A-gates passed
  CFR_B     — score >= 6
  CFR_C     — score >= 3
  CFR_AVOID — score < 3

A-Gate requirements (ALL must pass for CFR_A):
  Gate 1 — Base quality: PUMP_WATCH_HIGH or MEDIUM
            (or SPECULATIVE with strong trigger + clean regime + custom confirm)
  Gate 2 — Clean regime: no split artifact, not recent reverse split,
            not ATR extreme, not PRICE_GT_25, not illiquid unless exception
  Gate 3 — Trigger: at least one strong trigger confirmed
  Gate 4 — Not setup-only: not pure L64/bearish_stress/GAP_RESET
  Gate 5 — Risk control: no major risk flags

Anti-leakage contract
---------------------
  pump_multiple, group_type, future returns, post-window fields
  MUST NOT be used in score computation.
  They are only read in _build_*_performance() for outcome reporting.

RESEARCH ONLY — never route to Scanner V2 BUY/WATCH/AVOID.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from typing import Optional

logger = logging.getLogger(__name__)

# ── Badge constants (mirror curated_flow_rules.py) ────────────────────────────

_B_ABSORB_PRESSURE = "PX_FLOW_DIVERGENCE_ABSORB_PRESSURE_1B"
_B_OBV_ACCUM       = "PX_FLOW_DIVERGENCE_OBV_ACCUM_DISTRIB_1B"
_B_DIVERGENCE_ACCUM = "PX_FLOW_DIVERGENCE_ACCUM_PRESSURE"
_B_BULLISH_ACCUM   = "PX_FLOW_BULLISH_ACCUM_IGNITION"
_B_SUPPLY_ABSORB   = "PX_FLOW_DIVERGENCE_SUPPLY_ABSORB"
_B_IGNITION_CONFIRM = "PX_IGNITION_CONFIRM_PRICE_ACTION"
_B_GAP_RESET       = "PX_GAP_RESET_RECLAIM_CONTEXT"

# Strong triggers (score +3 each)
_STRONG_TRIGGERS_3 = {_B_ABSORB_PRESSURE, _B_BULLISH_ACCUM}
# Strong triggers (score +2 with clean regime)
_STRONG_TRIGGERS_2 = {_B_OBV_ACCUM, _B_DIVERGENCE_ACCUM, _B_SUPPLY_ABSORB}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _num(v, default: float = 0.0) -> float:
    if v is None:
        return default
    try:
        f = float(v)
        return f if (f == f and f != float("inf") and f != float("-inf")) else default
    except (TypeError, ValueError):
        return default


def _median(vals: list) -> Optional[float]:
    cleaned = sorted(x for x in vals if x is not None)
    n = len(cleaned)
    if n == 0:
        return None
    mid = n // 2
    return cleaned[mid] if n % 2 else (cleaned[mid - 1] + cleaned[mid]) / 2.0


def _pct(num: int, denom: int) -> Optional[float]:
    return round(num / denom, 4) if denom > 0 else None


def _sym(ep: dict) -> str:
    return ep.get("symbol") or ep.get("ticker") or "?"


# ── Regime helpers ────────────────────────────────────────────────────────────

def _is_clean_regime(ep: dict) -> bool:
    """Returns True when the episode passes basic cleanliness gates for CFR_A."""
    if ep.get("split_artifact_risk"):
        return False
    sc = ep.get("split_context") or ""
    if sc in ("RECENT_REVERSE_SPLIT", "SPLIT_ARTIFACT_RISK"):
        return False
    if ep.get("atr_bucket") == "ATR_EXTREME_GT_40":
        return False
    if ep.get("price_bucket") == "PRICE_GT_25":
        return False
    return True


def _is_toxic_regime(ep: dict) -> bool:
    """Returns True for the worst regime conditions (reverse split / artifact)."""
    if ep.get("split_artifact_risk"):
        return True
    sc = ep.get("split_context") or ""
    return sc in ("RECENT_REVERSE_SPLIT", "SPLIT_ARTIFACT_RISK", "OLD_REVERSE_SPLIT")


# ── Custom signal aggregation from daily rows ─────────────────────────────────

def _aggregate_custom_signals(daily_rows: list[dict]) -> dict:
    """Count custom signal flag occurrences across pre-window daily rows."""
    counters = {
        "l34": 0, "l43": 0, "l22": 0, "l64": 0,
        "fri34": 0, "fri64": 0,
        "d3_beup": 0, "d4_beup": 0, "d6_beup": 0,
        "d4_l34": 0, "d3_l34": 0,
        "vbo": 0, "lvbo": 0,
    }
    for row in daily_rows:
        fj = row.get("feature_json") or {}
        if isinstance(fj, str):
            try:
                import json as _json
                fj = _json.loads(fj)
            except Exception:
                fj = {}
        for k in counters:
            if fj.get(f"has_{k}"):
                counters[k] += 1
    return counters


# ── FLOW context extraction ───────────────────────────────────────────────────

def _flow_contexts(ep: dict) -> dict:
    """Extract all FLOW context flags from episode-level fields."""
    ctx = ep.get("flow_replay_context") or ""
    subtypes = set(ep.get("curated_flow_subtypes") or [])
    badges   = set(ep.get("curated_flow_badges")   or [])

    return {
        "divergence":    ctx == "FLOW_DIVERGENCE"   or "FLOW_DIVERGENCE"   in subtypes,
        "absorption":    ctx == "FLOW_ABSORPTION"   or "FLOW_ABSORPTION"   in subtypes,
        "bearish_stress": ctx == "FLOW_BEARISH_STRESS" or "FLOW_BEARISH_STRESS" in subtypes,
        "bullish_accum": ctx == "FLOW_BULLISH_ACCUM" or "FLOW_BULLISH_ACCUM" in subtypes,
        "badges":        badges,
        "primary_badge": ep.get("curated_flow_primary_badge"),
    }


# ── Core scoring function ─────────────────────────────────────────────────────

def _compute_cfr_score(ep: dict, custom: dict) -> dict:
    """
    Compute CFR v1 score for one episode.

    Parameters
    ----------
    ep     : episode dict (pre-scored by all upstream analyzers)
    custom : custom signal counter dict from _aggregate_custom_signals()

    Returns
    -------
    dict with all cfr_* fields. Outcome fields never used.
    """
    score = 0
    reasons: list[str]    = []
    risk_flags: list[str] = []
    a_blockers: list[str] = []
    components: dict[str, float] = {
        "pump_watch_base":     0.0,
        "flow_setup":          0.0,
        "trigger_confirmation": 0.0,
        "custom_confirmation": 0.0,
        "regime":              0.0,
        "risk_penalty":        0.0,
    }

    pw_label = ep.get("pump_watch_label") or "PUMP_IGNORE"
    flow     = _flow_contexts(ep)
    badges   = flow["badges"]
    clean    = _is_clean_regime(ep)
    toxic    = _is_toxic_regime(ep)

    price_bucket = ep.get("price_bucket") or "PRICE_UNKNOWN"
    atr_bucket   = ep.get("atr_bucket")   or "ATR_UNKNOWN"
    dv_bucket    = ep.get("dollar_volume_bucket") or "DV_UNKNOWN"
    split_ctx    = ep.get("split_context") or "UNKNOWN"
    split_art    = bool(ep.get("split_artifact_risk"))

    # ── 1. Pump Watch base ──────────────────────────────────────────────────
    pw_pts = 0
    speculative_base = False
    if pw_label == "PUMP_WATCH_HIGH":
        pw_pts = 4
        reasons.append("pump_watch_high")
    elif pw_label == "PUMP_WATCH_MEDIUM":
        pw_pts = 3
        reasons.append("pump_watch_medium")
    elif pw_label == "PUMP_SPECULATIVE":
        speculative_base = True   # conditional +1 added after trigger check
    elif pw_label == "PUMP_IGNORE":
        pw_pts = -3
        risk_flags.append("pump_ignore")
    components["pump_watch_base"] = pw_pts
    score += pw_pts

    # ── 2. FLOW setup ───────────────────────────────────────────────────────
    flow_setup_pts = 0
    has_flow_setup = False
    if flow["divergence"]:
        flow_setup_pts += 1
        has_flow_setup = True
        reasons.append("flow_divergence_setup")
    if flow["absorption"]:
        flow_setup_pts += 1
        has_flow_setup = True
        reasons.append("flow_absorption_setup")
    if flow["bullish_accum"]:
        # bullish_accum upgrades setup and can also contribute to trigger
        flow_setup_pts += 1
        has_flow_setup = True
        reasons.append("flow_bullish_accum_context")
    if flow["bearish_stress"] and not flow["divergence"] and not flow["bullish_accum"]:
        # bearish_stress is setup context only (no extra setup pts)
        has_flow_setup = True
        reasons.append("flow_bearish_stress_context")
    components["flow_setup"] = float(flow_setup_pts)
    score += flow_setup_pts

    # ── 3. FLOW trigger ─────────────────────────────────────────────────────
    trigger_pts = 0
    has_strong_trigger = False
    primary_trigger: Optional[str] = None

    # +3 triggers
    for b in (_B_ABSORB_PRESSURE, _B_BULLISH_ACCUM):
        if b in badges:
            trigger_pts += 3
            has_strong_trigger = True
            primary_trigger = b
            reasons.append(f"strong_trigger_{b}")
            break  # don't double-count

    # +2 triggers with clean regime
    if not has_strong_trigger and clean:
        for b in (_B_OBV_ACCUM, _B_DIVERGENCE_ACCUM, _B_SUPPLY_ABSORB):
            if b in badges:
                trigger_pts += 2
                has_strong_trigger = True
                primary_trigger = b
                reasons.append(f"trigger_clean_regime_{b}")
                break

    # +1 ignition confirm (only when setup exists)
    if _B_IGNITION_CONFIRM in badges and has_flow_setup and not has_strong_trigger:
        trigger_pts += 1
        primary_trigger = _B_IGNITION_CONFIRM
        reasons.append("ignition_confirm_with_setup")

    # GAP_RESET: context only, 0 trigger pts
    if _B_GAP_RESET in badges and not has_strong_trigger:
        reasons.append("gap_reset_context_only")

    # PUMP_SPECULATIVE: +1 only if strong trigger
    if speculative_base:
        if has_strong_trigger:
            pw_pts_spec = 1
            components["pump_watch_base"] = float(pw_pts_spec)
            score += pw_pts_spec
            reasons.append("pump_speculative_with_trigger")
        # else: 0 pts for speculative without trigger

    components["trigger_confirmation"] = float(trigger_pts)
    score += trigger_pts

    # ── 4. Custom confirmation ──────────────────────────────────────────────
    custom_pts = 0
    has_custom_confirm = False

    has_l34  = custom.get("l34",   0) > 0
    has_l43  = custom.get("l43",   0) > 0
    has_l64_many = custom.get("l64", 0) >= 5   # repeated = stress
    has_l64_any  = custom.get("l64", 0) > 0
    has_vbo  = custom.get("vbo",   0) > 0
    has_lvbo = custom.get("lvbo",  0) > 0
    has_d4_beup = custom.get("d4_beup", 0) > 0
    has_d6_beup = custom.get("d6_beup", 0) > 0
    has_d4_l34  = custom.get("d4_l34",  0) > 0
    has_d3_l34  = custom.get("d3_l34",  0) > 0

    if (has_l34 or has_l43) and has_flow_setup:
        custom_pts += 1
        has_custom_confirm = True
        reasons.append("l34_l43_with_flow_setup")

    if (has_d4_beup or has_d6_beup) and clean:
        custom_pts += 1
        has_custom_confirm = True
        reasons.append("d4_d6_beup_clean_regime")

    if (has_vbo or has_lvbo) and has_flow_setup:
        custom_pts += 1
        has_custom_confirm = True
        reasons.append("vbo_lvbo_after_setup")

    if (has_d4_l34 or has_d3_l34) and not toxic:
        custom_pts += 1
        has_custom_confirm = True
        reasons.append("d_l34_combo")

    # Penalty: repeated L64 without trigger
    if has_l64_many and not has_strong_trigger:
        custom_pts -= 1
        risk_flags.append("repeated_l64_no_trigger")

    components["custom_confirmation"] = float(custom_pts)
    score += custom_pts

    # ── 5. Regime scoring ───────────────────────────────────────────────────
    regime_pts = 0

    if price_bucket in ("PRICE_1_TO_3", "PRICE_3_TO_10"):
        regime_pts += 2
        reasons.append(f"price_ok:{price_bucket}")
    elif price_bucket == "PRICE_SUB_1" and dv_bucket != "DV_ILLIQUID_LT_50K":
        regime_pts += 1
        reasons.append("price_sub1_liquid")

    if dv_bucket in ("DV_OK_250K_1M", "DV_LIQUID_1M_10M", "DV_HIGH_GT_10M"):
        regime_pts += 1
        reasons.append(f"dv_ok:{dv_bucket}")

    if atr_bucket == "ATR_NORMAL_5_15":
        regime_pts += 1
        reasons.append("atr_normal")

    if split_ctx == "NO_SPLIT":
        regime_pts += 1
        reasons.append("no_split")

    components["regime"] = float(regime_pts)
    score += regime_pts

    # ── 6. Risk penalties ───────────────────────────────────────────────────
    risk_pts = 0

    if split_art or split_ctx == "SPLIT_ARTIFACT_RISK":
        risk_pts -= 5
        risk_flags.append("split_artifact")
    elif split_ctx == "RECENT_REVERSE_SPLIT":
        risk_pts -= 4
        risk_flags.append("recent_reverse_split")
    elif split_ctx == "OLD_REVERSE_SPLIT":
        risk_pts -= 3
        risk_flags.append("old_reverse_split")

    if atr_bucket == "ATR_EXTREME_GT_40":
        risk_pts -= 3
        risk_flags.append("atr_extreme")

    if price_bucket == "PRICE_GT_25":
        risk_pts -= 2
        risk_flags.append("price_gt25")

    if dv_bucket == "DV_ILLIQUID_LT_50K":
        risk_pts -= 2
        risk_flags.append("dv_illiquid")

    if price_bucket == "PRICE_MICRO_LT_050" and dv_bucket in ("DV_ILLIQUID_LT_50K", "DV_THIN_50K_250K"):
        risk_pts -= 1
        risk_flags.append("micro_price_illiquid")

    # Pure bearish stress without trigger
    pure_bearish = (
        flow["bearish_stress"]
        and not has_strong_trigger
        and not flow["divergence"]
        and not flow["bullish_accum"]
        and not flow["absorption"]
    )
    if pure_bearish:
        risk_pts -= 2
        risk_flags.append("pure_bearish_stress_no_trigger")

    components["risk_penalty"] = float(risk_pts)
    score += risk_pts

    # ── 7. A-gate evaluation ────────────────────────────────────────────────
    a_gate_passed = True

    # Gate 1: Base quality
    gate1_ok = (
        pw_label in ("PUMP_WATCH_HIGH", "PUMP_WATCH_MEDIUM")
        or (pw_label == "PUMP_SPECULATIVE" and has_strong_trigger and clean and has_custom_confirm)
    )
    if not gate1_ok:
        a_gate_passed = False
        if pw_label == "PUMP_IGNORE":
            a_blockers.append("pump_ignore_without_exception")
        else:
            a_blockers.append("no_base_quality")

    # Gate 2: Clean regime
    dv_exception = has_strong_trigger   # strong trigger may waive illiquid block
    gate2_ok = (
        not split_art
        and split_ctx not in ("RECENT_REVERSE_SPLIT", "SPLIT_ARTIFACT_RISK")
        and atr_bucket != "ATR_EXTREME_GT_40"
        and price_bucket != "PRICE_GT_25"
        and (dv_bucket != "DV_ILLIQUID_LT_50K" or dv_exception)
    )
    if not gate2_ok:
        a_gate_passed = False
        if split_art or split_ctx == "SPLIT_ARTIFACT_RISK":
            a_blockers.append("split_artifact")
        if split_ctx == "RECENT_REVERSE_SPLIT":
            a_blockers.append("recent_reverse_split")
        if split_ctx == "OLD_REVERSE_SPLIT":
            a_blockers.append("old_reverse_split")
        if atr_bucket == "ATR_EXTREME_GT_40":
            a_blockers.append("atr_extreme")
        if price_bucket == "PRICE_GT_25":
            a_blockers.append("price_gt25")
        if dv_bucket == "DV_ILLIQUID_LT_50K" and not dv_exception:
            a_blockers.append("illiquid")

    # Gate 3: Trigger
    if not has_strong_trigger:
        a_gate_passed = False
        a_blockers.append("no_trigger_confirmation")

    # Gate 4: Not setup-only
    is_pure_l64 = has_l64_any and not has_l34 and not has_l43 and not has_strong_trigger
    is_setup_only = (
        not has_strong_trigger
        and (pure_bearish or is_pure_l64 or (not flow["divergence"] and not flow["bullish_accum"] and not flow["absorption"]))
    )
    if is_setup_only:
        a_gate_passed = False
        if is_pure_l64:
            a_blockers.append("pure_l64_stress")
        elif pure_bearish:
            a_blockers.append("pure_bearish_stress")
        elif not flow["divergence"] and not flow["bullish_accum"]:
            a_blockers.append("setup_only")

    # Gate 5: Risk control
    blocking_flags = {"split_artifact", "recent_reverse_split", "atr_extreme", "price_gt25"}
    if any(f in risk_flags for f in blocking_flags):
        a_gate_passed = False
        # blockers already added above

    # Pure bearish stress always blocks A
    if pure_bearish:
        a_gate_passed = False
        if "pure_bearish_stress" not in a_blockers:
            a_blockers.append("pure_bearish_stress")

    # CFR_IGNORE check for broad curated only
    exact_count = _num(ep.get("curated_flow_exact_match_count"))
    proxy_only  = bool(ep.get("curated_flow_is_proxy_only"))
    if exact_count == 0 and proxy_only and not has_strong_trigger and not has_flow_setup:
        a_gate_passed = False
        if "broad_curated_only" not in a_blockers:
            a_blockers.append("broad_curated_only")

    # Deduplicate blockers
    seen = set()
    a_blockers = [b for b in a_blockers if not (b in seen or seen.add(b))]

    # ── 8. Bucket assignment ────────────────────────────────────────────────
    final_score = max(-20, min(20, score))
    if a_gate_passed and final_score >= 9:
        bucket = "CFR_A"
    elif final_score >= 6:
        bucket = "CFR_B"
    elif final_score >= 3:
        bucket = "CFR_C"
    else:
        bucket = "CFR_AVOID"

    # Determine primary fields
    primary_setup = (
        "FLOW_DIVERGENCE" if flow["divergence"] else
        "FLOW_BULLISH_ACCUM" if flow["bullish_accum"] else
        "FLOW_ABSORPTION" if flow["absorption"] else
        "FLOW_BEARISH_STRESS" if flow["bearish_stress"] else
        "NONE"
    )
    primary_custom = (
        "L34_L43" if (has_l34 or has_l43) else
        "D4_D6_BEUP" if (has_d4_beup or has_d6_beup) else
        "VBO_LVBO" if (has_vbo or has_lvbo) else
        "D_L34" if (has_d4_l34 or has_d3_l34) else
        "NONE"
    )
    primary_regime = f"{price_bucket}|{atr_bucket}|{dv_bucket}"

    return {
        "custom_flow_regime_score_v1":             final_score,
        "custom_flow_regime_bucket_v1":            bucket,
        "custom_flow_regime_reasons_v1":           reasons,
        "custom_flow_regime_risk_flags_v1":        risk_flags,
        "custom_flow_regime_components_v1":        components,
        "custom_flow_regime_a_gate_passed":        a_gate_passed,
        "custom_flow_regime_a_blockers":           a_blockers,
        "custom_flow_regime_primary_setup":        primary_setup,
        "custom_flow_regime_primary_trigger":      primary_trigger,
        "custom_flow_regime_primary_custom_confirm": primary_custom,
        "custom_flow_regime_primary_regime":       primary_regime,
    }


# ── Per-episode scoring pass ──────────────────────────────────────────────────

def score_episodes_cfr(
    episodes: list[dict],
    daily_by_episode: Optional[dict] = None,
) -> list[dict]:
    """
    Score all episodes with CFR v1.  Mutates dicts in-place.
    Returns the same list.
    """
    if not episodes:
        return episodes

    daily_by_episode = daily_by_episode or {}

    for ep in episodes:
        ep_id = ep.get("episode_id") or ep.get("id")
        daily_rows = daily_by_episode.get(ep_id, []) if ep_id is not None else []
        custom = _aggregate_custom_signals(daily_rows)
        result = _compute_cfr_score(ep, custom)
        ep.update(result)

    return episodes


# ── Bucket performance analysis ───────────────────────────────────────────────

def _bucket_performance(episodes: list[dict]) -> dict:
    """
    Per-CFR-bucket outcome stats.
    Outcome fields (pump_multiple, group_type) used here for analysis ONLY.
    """
    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for ep in episodes:
        b = ep.get("custom_flow_regime_bucket_v1") or "CFR_AVOID"
        by_bucket[b].append(ep)

    result = {}
    for bucket, eps in by_bucket.items():
        pms  = [ep["pump_multiple"] for ep in eps if ep.get("pump_multiple") is not None]
        pws  = [_num(ep.get("pump_watch_score")) for ep in eps if ep.get("pump_watch_score") is not None]
        cfrs = [_num(ep.get("custom_flow_regime_score_v1")) for ep in eps]
        gts  = Counter(ep.get("group_type") or "?" for ep in eps)

        n = len(eps)
        splits = sum(1 for e in eps if e.get("split_artifact_risk"))
        n_4x = sum(1 for pm in pms if pm >= 4.0)
        n_fp  = sum(1 for e in eps if e.get("group_type") in ("FALSE_POSITIVE",))

        examples_4x = [
            {"symbol": _sym(e), "pump_multiple": e.get("pump_multiple"),
             "cfr_score": _num(e.get("custom_flow_regime_score_v1")),
             "trigger": e.get("custom_flow_regime_primary_trigger"),
             "reasons": (e.get("custom_flow_regime_reasons_v1") or [])[:5]}
            for e in sorted(eps, key=lambda x: -(x.get("pump_multiple") or 0))
            if (e.get("pump_multiple") or 0) >= 4.0
        ][:5]

        examples_fp = [
            {"symbol": _sym(e), "cfr_score": _num(e.get("custom_flow_regime_score_v1")),
             "risk_flags": e.get("custom_flow_regime_risk_flags_v1") or [],
             "a_blockers": e.get("custom_flow_regime_a_blockers") or [],
             "reasons": (e.get("custom_flow_regime_reasons_v1") or [])[:4]}
            for e in eps if e.get("group_type") in ("FALSE_POSITIVE",)
        ][:5]

        result[bucket] = {
            "total":                  n,
            "4x_count":               n_4x,
            "false_positive_count":   n_fp,
            "split_artifact_count":   splits,
            "4x_rate":                _pct(n_4x, n),
            "false_positive_rate":    _pct(n_fp, n),
            "median_pump_watch_score":  _median(pws),
            "median_cfr_score":         _median(cfrs),
            "group_type_distribution":  dict(gts.most_common()),
            "examples_4x":            examples_4x,
            "examples_false_positive": examples_fp,
        }
    return result


# ── Comparison vs Pump Watch ──────────────────────────────────────────────────

def _compare_vs_pump_watch(episodes: list[dict]) -> dict:
    """Cross-tab CFR bucket vs Pump Watch label."""
    matrix: dict[str, Counter] = defaultdict(Counter)
    for ep in episodes:
        cfr = ep.get("custom_flow_regime_bucket_v1") or "CFR_AVOID"
        pw  = ep.get("pump_watch_label") or "PUMP_IGNORE"
        matrix[cfr][pw] += 1
    return {k: dict(v.most_common()) for k, v in matrix.items()}


def _compare_vs_flow_badge(episodes: list[dict]) -> dict:
    """CFR bucket vs primary FLOW badge."""
    matrix: dict[str, Counter] = defaultdict(Counter)
    for ep in episodes:
        cfr = ep.get("custom_flow_regime_bucket_v1") or "CFR_AVOID"
        badge = ep.get("curated_flow_primary_badge") or "NONE"
        matrix[cfr][badge] += 1
    return {k: dict(v.most_common()) for k, v in matrix.items()}


def _compare_vs_custom(episodes: list[dict]) -> dict:
    """CFR bucket vs primary custom confirmation."""
    matrix: dict[str, Counter] = defaultdict(Counter)
    for ep in episodes:
        cfr    = ep.get("custom_flow_regime_bucket_v1") or "CFR_AVOID"
        custom = ep.get("custom_flow_regime_primary_custom_confirm") or "NONE"
        matrix[cfr][custom] += 1
    return {k: dict(v.most_common()) for k, v in matrix.items()}


def _compare_vs_regime(episodes: list[dict]) -> dict:
    """CFR bucket vs price bucket."""
    matrix: dict[str, Counter] = defaultdict(Counter)
    for ep in episodes:
        cfr   = ep.get("custom_flow_regime_bucket_v1") or "CFR_AVOID"
        price = ep.get("price_bucket") or "PRICE_UNKNOWN"
        matrix[cfr][price] += 1
    return {k: dict(v.most_common()) for k, v in matrix.items()}


# ── Main analysis builder ─────────────────────────────────────────────────────

def build_cfr_selector_analysis(
    episodes: list[dict],
    daily_by_episode: Optional[dict] = None,
) -> dict:
    """
    Top-level entry point.

    Scores all episodes with CFR v1 and returns:
      custom_flow_regime_selector_v1_analysis — full export dict
    """
    if not episodes:
        return {
            "custom_flow_regime_selector_v1_analysis": {
                "summary": {"total_episodes": 0},
                "bucket_performance": {},
            }
        }

    daily_by_episode = daily_by_episode or {}
    scored = score_episodes_cfr(episodes, daily_by_episode=daily_by_episode)

    # ── Aggregate counts ────────────────────────────────────────────────────
    bucket_counts: Counter = Counter()
    score_list: list[float] = []
    all_blockers: Counter   = Counter()

    for ep in scored:
        b = ep.get("custom_flow_regime_bucket_v1") or "CFR_AVOID"
        bucket_counts[b] += 1
        score_list.append(_num(ep.get("custom_flow_regime_score_v1")))
        for bl in (ep.get("custom_flow_regime_a_blockers") or []):
            all_blockers[bl] += 1

    cfr_a_eps = [e for e in scored if e.get("custom_flow_regime_bucket_v1") == "CFR_A"]
    cfr_a_pms = [e.get("pump_multiple") for e in cfr_a_eps if e.get("pump_multiple") is not None]
    cfr_a_4x  = sum(1 for pm in cfr_a_pms if pm >= 4.0)
    cfr_a_fp  = sum(1 for e in cfr_a_eps if e.get("group_type") in ("FALSE_POSITIVE",))
    cfr_a_n   = len(cfr_a_eps)

    # ── Pump Watch HIGH baseline ────────────────────────────────────────────
    pw_high = [e for e in scored if e.get("pump_watch_label") == "PUMP_WATCH_HIGH"]
    pw_high_pms = [e.get("pump_multiple") for e in pw_high if e.get("pump_multiple") is not None]
    pw_high_4x  = sum(1 for pm in pw_high_pms if pm >= 4.0)
    pw_high_fp  = sum(1 for e in pw_high if e.get("group_type") in ("FALSE_POSITIVE",))
    pw_high_n   = len(pw_high)

    baseline = {
        "total":               pw_high_n,
        "4x_count":            pw_high_4x,
        "false_positive_count": pw_high_fp,
        "4x_rate":             _pct(pw_high_4x, pw_high_n),
        "false_positive_rate": _pct(pw_high_fp, pw_high_n),
        "label":               "PUMP_WATCH_HIGH from run data",
    }

    cfr_a_verdict = "insufficient_data"
    if cfr_a_n > 0 and pw_high_n > 0:
        cfr_4x_r  = _pct(cfr_a_4x, cfr_a_n) or 0.0
        cfr_fp_r  = _pct(cfr_a_fp, cfr_a_n) or 0.0
        pw_4x_r   = _pct(pw_high_4x, pw_high_n) or 0.0
        pw_fp_r   = _pct(pw_high_fp, pw_high_n) or 0.0
        if cfr_4x_r >= pw_4x_r and cfr_fp_r <= pw_fp_r:
            cfr_a_verdict = "CFR_A_BEATS_BASELINE"
        elif cfr_4x_r >= pw_4x_r:
            cfr_a_verdict = "CFR_A_HIGHER_4X_BUT_MORE_FP"
        elif cfr_fp_r <= pw_fp_r:
            cfr_a_verdict = "CFR_A_LOWER_FP_BUT_LESS_4X"
        else:
            cfr_a_verdict = "CFR_A_BELOW_BASELINE"

    # ── Top CFR_A list ──────────────────────────────────────────────────────
    top_cfr_a = sorted(cfr_a_eps, key=lambda x: -(x.get("pump_multiple") or 0))[:20]
    top_cfr_a_out = [
        {
            "symbol":           _sym(e),
            "episode_id":       e.get("episode_id") or e.get("id"),
            "group_type":       e.get("group_type"),
            "pump_multiple":    e.get("pump_multiple"),
            "cfr_score":        _num(e.get("custom_flow_regime_score_v1")),
            "pump_watch_label": e.get("pump_watch_label"),
            "primary_setup":    e.get("custom_flow_regime_primary_setup"),
            "primary_trigger":  e.get("custom_flow_regime_primary_trigger"),
            "custom_confirm":   e.get("custom_flow_regime_primary_custom_confirm"),
            "regime":           e.get("custom_flow_regime_primary_regime"),
            "risk_flags":       e.get("custom_flow_regime_risk_flags_v1") or [],
        }
        for e in top_cfr_a
    ]

    # ── CFR_A false positives ───────────────────────────────────────────────
    cfr_a_fp_list = [
        {
            "symbol":       _sym(e),
            "cfr_score":    _num(e.get("custom_flow_regime_score_v1")),
            "reasons":      (e.get("custom_flow_regime_reasons_v1") or [])[:6],
            "risk_flags":   e.get("custom_flow_regime_risk_flags_v1") or [],
            "a_gate_passed": e.get("custom_flow_regime_a_gate_passed"),
            "components":   e.get("custom_flow_regime_components_v1"),
        }
        for e in cfr_a_eps if e.get("group_type") in ("FALSE_POSITIVE",)
    ]

    # ── CFR_A 4x examples ──────────────────────────────────────────────────
    cfr_a_4x_list = [
        {
            "symbol":        _sym(e),
            "pump_multiple": e.get("pump_multiple"),
            "cfr_score":     _num(e.get("custom_flow_regime_score_v1")),
            "primary_trigger": e.get("custom_flow_regime_primary_trigger"),
            "reasons":       (e.get("custom_flow_regime_reasons_v1") or [])[:5],
            "components":    e.get("custom_flow_regime_components_v1"),
        }
        for e in cfr_a_eps if (e.get("pump_multiple") or 0) >= 4.0
    ]

    # ── Blocked from A (not in CFR_A but have score >= 6) ──────────────────
    blocked_from_a = [
        {
            "symbol":       _sym(e),
            "cfr_score":    _num(e.get("custom_flow_regime_score_v1")),
            "cfr_bucket":   e.get("custom_flow_regime_bucket_v1"),
            "group_type":   e.get("group_type"),
            "pump_multiple": e.get("pump_multiple"),
            "a_blockers":   e.get("custom_flow_regime_a_blockers") or [],
        }
        for e in scored
        if not e.get("custom_flow_regime_a_gate_passed")
        and _num(e.get("custom_flow_regime_score_v1")) >= 6
    ][:20]

    # ── Recommendations ────────────────────────────────────────────────────
    recs = [
        "CFR_A requires: PUMP_WATCH_HIGH/MEDIUM + clean regime + strong trigger + custom confirmation.",
        "ABR is disabled in v1 — ABR fields are diagnostic only.",
        "L64/FLOW_BEARISH_STRESS/GAP_RESET cannot create CFR_A alone.",
        "PUMP_SPECULATIVE can reach CFR_A only with strong trigger + clean regime + custom confirm.",
        "PUMP_IGNORE max bucket is CFR_C unless exception path passes (future v2).",
    ]
    if cfr_a_n > 10:
        recs.append(f"CFR_A count={cfr_a_n} — consider tightening thresholds if FP rate is high.")
    if cfr_a_n == 0:
        recs.append("No CFR_A episodes found — check if trigger badges are present in curated_flow_badges.")

    analysis = {
        "summary": {
            "total_episodes":        len(scored),
            "cfr_a_count":           bucket_counts.get("CFR_A", 0),
            "cfr_b_count":           bucket_counts.get("CFR_B", 0),
            "cfr_c_count":           bucket_counts.get("CFR_C", 0),
            "cfr_avoid_count":       bucket_counts.get("CFR_AVOID", 0),
            "cfr_a_4x_rate":         _pct(cfr_a_4x, cfr_a_n),
            "cfr_a_fp_rate":         _pct(cfr_a_fp, cfr_a_n),
            "median_cfr_score":      _median(score_list),
            "bucket_counts":         dict(bucket_counts.most_common()),
            "abr_disabled":          True,
            "use_abr_in_cfr_v1":     False,
        },
        "bucket_performance":         _bucket_performance(scored),
        "compare_vs_pump_watch":      {"cfr_a_vs_pw_high_baseline": baseline, "verdict": cfr_a_verdict},
        "cfr_x_pump_watch_matrix":    _compare_vs_pump_watch(scored),
        "cfr_x_flow_badge_matrix":    _compare_vs_flow_badge(scored),
        "cfr_x_custom_matrix":        _compare_vs_custom(scored),
        "cfr_x_regime_matrix":        _compare_vs_regime(scored),
        "top_cfr_a":                  top_cfr_a_out,
        "cfr_a_false_positives":      cfr_a_fp_list,
        "cfr_a_4x_examples":          cfr_a_4x_list,
        "blocked_from_a_examples":    blocked_from_a,
        "top_a_blockers":             dict(all_blockers.most_common(15)),
        "recommendations":            recs,
        "anti_leakage": (
            "pump_multiple and group_type are used ONLY in analysis/reporting sections. "
            "CFR score uses only pre-window episode fields and custom signal counts from feature_json. "
            "ABR fields are not used in CFR v1 scoring."
        ),
    }

    return {"custom_flow_regime_selector_v1_analysis": analysis}
