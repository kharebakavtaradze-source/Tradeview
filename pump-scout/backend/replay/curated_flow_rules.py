"""
Curated FLOW Rules — Frozen research-only badge registry.

Five hand-curated rules derived from run 139 top patterns (2025-11-05 → 2026-05-04).
These rules are FROZEN — they do not change with new discovery runs.

Anti-leakage contract:
  All evaluation uses only PRE-window bar snapshots (phase="PRE").
  No outcome fields (pump_multiple, group_type, days_to_peak, future returns)
  are read inside this module.

Production contract:
  RESEARCH_ONLY. Do NOT wire to Scanner V2 BUY/WATCH/AVOID routing.
  Do NOT promote to BUY. Do NOT add a score boost.
"""

from typing import Optional

# ── Curated badge names ───────────────────────────────────────────────────────

BADGE_DIVERGENCE_ACCUM  = "PX_FLOW_DIVERGENCE_ACCUM_PRESSURE"
BADGE_BULLISH_ACCUM     = "PX_FLOW_BULLISH_ACCUM_IGNITION"
BADGE_SUPPLY_ABSORB     = "PX_FLOW_DIVERGENCE_SUPPLY_ABSORB"
BADGE_IGNITION_CONFIRM  = "PX_IGNITION_CONFIRM_PRICE_ACTION"
BADGE_GAP_RESET_RECLAIM = "PX_GAP_RESET_RECLAIM_CONTEXT"

ALL_CURATED_BADGES = [
    BADGE_DIVERGENCE_ACCUM,
    BADGE_BULLISH_ACCUM,
    BADGE_SUPPLY_ABSORB,
    BADGE_IGNITION_CONFIRM,
    BADGE_GAP_RESET_RECLAIM,
]

# ── Frozen rule definitions ───────────────────────────────────────────────────
#
# tag_mode:
#   "flow"  → match against snap["flow_tags"]  (V1C: ADL_ACCUM_3D, CMF_*, …)
#   "price" → match against snap["tags"]        (V1B: EXPANSION, DRYUP, …)
#
# window:
#   1 → single bar must contain ALL required_tags
#   5 → union of any 5-bar consecutive window must contain ALL required_tags

CURATED_RULES: list[dict] = [
    # ── Rule 1: Divergence accumulation with hidden demand ────────────────────
    {
        "badge":            BADGE_DIVERGENCE_ACCUM,
        "required_tags":    frozenset({
            "ADL_ACCUM_3D", "BUY_PRESSURE_HIGH", "CLOSE_HIGH",
            "CMF_NEGATIVE", "OBV_ACCUM_3D",
        }),
        "optional_tags":    frozenset(),
        "tag_mode":         "flow",
        "window":           1,
        "feature_family":   "FLOW",
        "flow_subtype":     "FLOW_DIVERGENCE",
        "intended_use":     "WATCHLIST_RANKING",
        "production_status":"RESEARCH_ONLY",
        "score_weight":     4,
        "run139_stats": {
            "count_all_4x": 10, "count_false_positive": 1,
            "false_positive_rate": 0.015, "reliability_score": 0.842,
            "split_artifact_exposure": 0.0,
        },
        "interpretation":   (
            "Accumulation/buy pressure visible but CMF remains negative. "
            "May indicate hidden accumulation or pressure reversal before obvious breakout."
        ),
        "safety_note":      "Do not route to BUY",
    },

    # ── Rule 2: Clean bullish accumulation / ignition confirmation ────────────
    {
        "badge":            BADGE_BULLISH_ACCUM,
        "required_tags":    frozenset({
            "ADL_ACCUM_3D", "BUY_PRESSURE_HIGH", "CLOSE_HIGH",
            "CMF_POSITIVE", "DELTA_PROXY_BULL", "EFFORT_RESULT_BULL",
            "OBV_ACCUM_3D",
        }),
        "optional_tags":    frozenset(),
        "tag_mode":         "flow",
        "window":           1,
        "feature_family":   "FLOW",
        "flow_subtype":     "FLOW_BULLISH_ACCUM",
        "intended_use":     "PUMP_WATCH_CONFIRMATION",
        "production_status":"RESEARCH_ONLY",
        "score_weight":     3,
        "run139_stats": {
            "count_all_4x": 10, "count_false_positive": 3,
            "false_positive_rate": 0.045, "reliability_score": 0.7569,
            "split_artifact_exposure": 0.0588,
        },
        "interpretation":   "Clean bullish accumulation / ignition confirmation.",
        "safety_note":      "Do not route to BUY",
    },

    # ── Rule 3: Supply absorption / hidden demand divergence ──────────────────
    {
        "badge":            BADGE_SUPPLY_ABSORB,
        "required_tags":    frozenset({
            "ADL_DISTRIB_3D", "BUY_PRESSURE_LOW", "CMF_NEGATIVE",
            "OBV_ACCUM_3D", "UPPER_WICK_SUPPLY",
        }),
        "optional_tags":    frozenset(),
        "tag_mode":         "flow",
        "window":           1,
        "feature_family":   "FLOW",
        "flow_subtype":     "FLOW_DIVERGENCE",
        "intended_use":     "PUMP_WATCH_CONTEXT",
        "production_status":"RESEARCH_ONLY",
        "score_weight":     3,
        "run139_stats": {
            "count_all_4x": 10, "count_false_positive": 3,
            "false_positive_rate": 0.045, "reliability_score": 0.7569,
            "split_artifact_exposure": 0.0588,
        },
        "interpretation": (
            "Bearish-looking supply pressure but OBV accumulation present. "
            "Possible supply absorption / hidden demand."
        ),
        "safety_note": "Bearish-looking context. Do not use as bullish confirmation alone.",
    },

    # ── Rule 4: Price-action ignition confirmation ────────────────────────────
    {
        "badge":            BADGE_IGNITION_CONFIRM,
        "required_tags":    frozenset({
            "EXPANSION", "STRONG_CLOSE", "VOL_SPIKE", "WIDE_RANGE",
        }),
        "optional_tags":    frozenset(),
        "tag_mode":         "price",
        "window":           1,
        "feature_family":   "PRICE_ACTION",
        "flow_subtype":     None,
        "intended_use":     "CONFIRMATION",
        "production_status":"RESEARCH_ONLY",
        "score_weight":     2,
        "run139_stats": {
            "count_all_4x": 10, "count_false_positive": 3,
            "false_positive_rate": 0.045, "reliability_score": 0.7569,
        },
        "interpretation":   "Breakout / ignition confirmation. Not an early pre-pump setup.",
        "safety_note":      "Confirmation only, not early setup.",
    },

    # ── Rule 5: Gap reset / reclaim context (5-bar bag) ───────────────────────
    {
        "badge":            BADGE_GAP_RESET_RECLAIM,
        "required_tags":    frozenset({
            "DRYUP", "GAP_DOWN", "GAP_UP", "GAP_UP_HOLD",
            "INSIDE_BAR", "LOWER_WICK_RECLAIM", "STRONG_CLOSE",
        }),
        "optional_tags":    frozenset({"WEAK_CLOSE", "WIDE_RANGE"}),
        "tag_mode":         "price",
        "window":           5,
        "feature_family":   "PRICE_ACTION",
        "source_type":      "FIVE_BAR_SEQUENCE",
        "flow_subtype":     None,
        "intended_use":     "SETUP_CONTEXT",
        "production_status":"RESEARCH_ONLY",
        "score_weight":     2,
        "run139_stats": {
            "count_all_4x": 13, "count_false_positive": 7,
            "false_positive_rate": 0.106, "reliability_score": 0.7212,
        },
        "interpretation":   "Gap reset / reclaim context. Useful as setup context, not entry.",
        "safety_note":      None,
    },
]

# Fast lookup
_RULE_BY_BADGE: dict[str, dict] = {r["badge"]: r for r in CURATED_RULES}

# Score weight map
BADGE_SCORE_WEIGHTS: dict[str, int] = {r["badge"]: r["score_weight"] for r in CURATED_RULES}


# ── Rule evaluation ───────────────────────────────────────────────────────────

def evaluate_curated_rules_on_snaps(snaps: list[dict]) -> dict:
    """
    Evaluate all 5 curated rules against a single episode's bar snapshots.

    Parameters
    ----------
    snaps : list of bar snapshot dicts (oldest→newest) from
            build_bar_feature_snapshots_for_episode().
            Each snap must have ``flow_tags`` and ``tags`` lists.

    Returns
    -------
    {
      "curated_flow_badges":       list[str],
      "curated_flow_badge_reasons":list[str],
      "curated_flow_subtypes":     list[str],
    }

    Anti-leakage: reads only snap["flow_tags"] and snap["tags"]. Never
    reads group_type, pump_multiple, or any future-return field.
    """
    if not snaps:
        return {
            "curated_flow_badges": [],
            "curated_flow_badge_reasons": [],
            "curated_flow_subtypes": [],
        }

    matched: set[str] = set()
    reasons: list[str] = []

    # ── Single-bar rules (window=1) ───────────────────────────────────────────
    for snap in snaps:
        snap_date  = snap.get("date") or snap.get("days_to_breakout") or "?"
        flow_tags  = set(snap.get("flow_tags") or [])
        price_tags = set(snap.get("tags") or [])

        for rule in CURATED_RULES:
            if rule["window"] != 1:
                continue
            badge = rule["badge"]
            if badge in matched:
                continue
            tag_pool = flow_tags if rule["tag_mode"] == "flow" else price_tags
            if rule["required_tags"].issubset(tag_pool):
                matched.add(badge)
                reasons.append(f"{badge} bar={snap_date}")

    # ── 5-bar window rule ─────────────────────────────────────────────────────
    gap_rule = _RULE_BY_BADGE[BADGE_GAP_RESET_RECLAIM]
    if BADGE_GAP_RESET_RECLAIM not in matched and len(snaps) >= 5:
        for start in range(len(snaps) - 4):
            window = snaps[start: start + 5]
            union_tags: set[str] = set()
            for s in window:
                union_tags.update(s.get("tags") or [])
            if gap_rule["required_tags"].issubset(union_tags):
                end_date = window[-1].get("date") or "?"
                matched.add(BADGE_GAP_RESET_RECLAIM)
                reasons.append(f"{BADGE_GAP_RESET_RECLAIM} 5bar_end={end_date}")
                break

    # ── Derive flow subtypes ──────────────────────────────────────────────────
    subtypes: list[str] = []
    for badge in ALL_CURATED_BADGES:
        if badge in matched:
            st = _RULE_BY_BADGE[badge].get("flow_subtype")
            if st and st not in subtypes:
                subtypes.append(st)

    badges_ordered = [b for b in ALL_CURATED_BADGES if b in matched]
    return {
        "curated_flow_badges":        badges_ordered,
        "curated_flow_badge_reasons": reasons,
        "curated_flow_subtypes":      subtypes,
    }


# ── Score computation ─────────────────────────────────────────────────────────

# Forbidden outcome fields — used in anti-leakage assertion
_OUTCOME_FIELDS = frozenset({
    "pump_multiple", "group_type", "days_from_breakout_to_peak",
    "days_to_peak", "forward_return_1d", "forward_return_3d",
    "forward_return_5d", "forward_return_10d", "pump_return_pct",
    "outcome_label", "detected_at_peak",
})


def compute_curated_flow_score(
    badges: list[str],
    ep: dict,
    *,
    _assert_no_leakage: bool = False,
) -> dict:
    """
    Compute research-only curated FLOW score + bucket for one episode.

    Parameters
    ----------
    badges  : matched badge names from evaluate_curated_rules_on_snaps()
    ep      : episode feature dict (PRE-window fields only)
    _assert_no_leakage : if True, raise AssertionError if ep contains any
                         known outcome field (used in tests).

    Returns
    -------
    {
      "curated_flow_score":      int,
      "curated_flow_bucket":     str,   # CURATED_FLOW_HIGH/MEDIUM/LOW/IGNORE
      "curated_flow_risk_flags": list[str],
      "curated_flow_reasons":    list[str],
    }
    """
    if _assert_no_leakage:
        found = _OUTCOME_FIELDS & set(ep.keys())
        if found:
            raise AssertionError(
                f"Anti-leakage violation: episode contains outcome fields: {found}"
            )

    score       = 0
    risk_flags: list[str] = []
    reasons:    list[str] = []

    # ── Badge scores ──────────────────────────────────────────────────────────
    for badge in badges:
        w = BADGE_SCORE_WEIGHTS.get(badge, 0)
        if w:
            score += w
            reasons.append(f"+{w} {badge}")

    # ── Context bonuses ───────────────────────────────────────────────────────
    dryup        = ep.get("dryup_day_count_pre") or 0
    d_conf       = ep.get("d_confluence_day_count_pre") or 0
    compression  = ep.get("compression_days_pre") or 0
    had_accum    = bool(ep.get("had_accumulation_like"))
    had_spring   = bool(ep.get("had_spring_test_lps"))
    split_ctx    = ep.get("split_context") or "NO_SPLIT"
    median_dv    = ep.get("median_dollar_volume_pre") or 0
    high_exp_ct  = ep.get("high_expansion_risk_day_count_pre") or 0

    if 8 <= dryup <= 25:
        score += 2; reasons.append("+2 dryup 8-25d")
    if d_conf >= 4:
        score += 2; reasons.append("+2 d_confluence>=4d")
    if compression >= 6:
        score += 1; reasons.append("+1 compression>=6d")
    if had_accum:
        score += 1; reasons.append("+1 had_accumulation_like")
    if had_spring:
        score += 1; reasons.append("+1 had_spring_test_lps")
    if split_ctx == "NO_SPLIT":
        score += 1; reasons.append("+1 no_split")
    if median_dv >= 100_000:
        score += 1; reasons.append("+1 median_dv>=100k")

    # ── Penalties ─────────────────────────────────────────────────────────────
    if ep.get("split_artifact_risk"):
        score -= 4; risk_flags.append("split_artifact"); reasons.append("-4 split_artifact")

    if split_ctx in ("RECENT_REVERSE_SPLIT", "OLD_REVERSE_SPLIT"):
        score -= 3; risk_flags.append("reverse_split"); reasons.append("-3 reverse_split")

    if 0 < median_dv < 50_000:
        score -= 2; risk_flags.append("low_dollar_volume"); reasons.append("-2 low_dv<50k")

    # Bearish/supply-only badge without any bullish/reclaim confirmation
    bearish_only = (
        BADGE_SUPPLY_ABSORB in badges
        and BADGE_DIVERGENCE_ACCUM not in badges
        and BADGE_BULLISH_ACCUM    not in badges
        and BADGE_IGNITION_CONFIRM not in badges
        and BADGE_GAP_RESET_RECLAIM not in badges
    )
    if bearish_only:
        score -= 2; risk_flags.append("bearish_supply_only"); reasons.append("-2 bearish_supply_only")

    # High expansion risk without any bullish flow badge
    has_bullish = (
        BADGE_DIVERGENCE_ACCUM in badges
        or BADGE_BULLISH_ACCUM in badges
    )
    if high_exp_ct >= 30 and not has_bullish:
        score -= 2; risk_flags.append("high_expansion_risk"); reasons.append("-2 high_exp>=30_no_bullish")

    # Badge matched but no dryup/compression/D-confluence context
    has_any_badge = len(badges) > 0
    has_context   = dryup >= 5 or compression >= 4 or d_conf >= 2
    if has_any_badge and not has_context:
        score -= 2; risk_flags.append("badge_no_context"); reasons.append("-2 badge_no_context")

    # ── Bucket ────────────────────────────────────────────────────────────────
    if score >= 8:
        bucket = "CURATED_FLOW_HIGH"
    elif score >= 5:
        bucket = "CURATED_FLOW_MEDIUM"
    elif score >= 3:
        bucket = "CURATED_FLOW_LOW"
    else:
        bucket = "CURATED_FLOW_IGNORE"

    return {
        "curated_flow_score":      score,
        "curated_flow_bucket":     bucket,
        "curated_flow_risk_flags": risk_flags,
        "curated_flow_reasons":    reasons,
    }


def score_episode_curated_flow(ep: dict, snaps: list[dict]) -> dict:
    """
    Convenience: evaluate rules on snaps, compute score, return merged result.
    Returned dict can be merged into the episode dict.
    """
    rule_result  = evaluate_curated_rules_on_snaps(snaps)
    score_result = compute_curated_flow_score(
        rule_result["curated_flow_badges"], ep
    )
    return {**rule_result, **score_result}


# ── Registry snapshot (for export metadata) ───────────────────────────────────

def curated_rules_registry_snapshot() -> list[dict]:
    """Return a serialisable snapshot of the frozen curated rule registry."""
    return [
        {
            "badge":            r["badge"],
            "required_tags":    sorted(r["required_tags"]),
            "tag_mode":         r["tag_mode"],
            "window":           r["window"],
            "feature_family":   r["feature_family"],
            "flow_subtype":     r.get("flow_subtype"),
            "intended_use":     r["intended_use"],
            "production_status":r["production_status"],
            "score_weight":     r["score_weight"],
            "run139_stats":     r.get("run139_stats", {}),
            "interpretation":   r.get("interpretation"),
            "safety_note":      r.get("safety_note"),
        }
        for r in CURATED_RULES
    ]
