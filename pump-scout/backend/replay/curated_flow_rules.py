"""
Curated FLOW Rules — Frozen research-only badge registry.

Six hand-curated rules derived from run 139/142 top patterns.
These rules are FROZEN — they do not change with new discovery runs.

Anti-leakage contract:
  All evaluation uses only PRE-window bar snapshots (phase="PRE").
  No outcome fields (pump_multiple, group_type, days_to_peak, future returns)
  are read inside this module.

Production contract:
  RESEARCH_ONLY. Do NOT wire to Scanner V2 BUY/WATCH/AVOID routing.
  Do NOT promote to BUY. Do NOT add a score boost.

Scoring model (v2)
------------------
  Exact badge evidence is required for CURATED_FLOW_HIGH or MEDIUM.
  Proxy-only context (dryup / compression / D-confluence / no_split) is capped
  at score=4 / CURATED_FLOW_LOW unless allow_proxy_score=True.

  Divergence-pressure family (ABSORB_PRESSURE + ACCUM_PRESSURE) uses a
  max-score rather than sum to prevent double-counting when both fire.
"""

from typing import Optional


# ── None-safe numeric helpers ─────────────────────────────────────────────────

def _num(value, default: float = 0) -> float:
    """Coerce a possibly-None episode field to a finite number.
    Handles None, empty-string, NaN, Inf, and non-numeric values without crashing.
    dict.get(key, default) only substitutes when the key is absent; it does NOT
    substitute when the key is present with value None, so always use _num().
    """
    if value is None:
        return default
    try:
        v = float(value)
        return v if (v == v and v != float("inf") and v != float("-inf")) else default
    except (TypeError, ValueError):
        return default


def _gte(value, threshold: float, default: float = 0) -> bool:
    """None-safe `value >= threshold`. Returns False when value is None/invalid."""
    return _num(value, default) >= threshold


def _between(value, low: float, high: float, default: float = 0) -> bool:
    """None-safe `low <= value <= high`. Returns False when value is None/invalid."""
    v = _num(value, default)
    return low <= v <= high


# ── Curated badge names ───────────────────────────────────────────────────────

# Strict divergence variant — requires LOWER_WICK_ABSORPTION (run-142 pattern)
BADGE_DIVERGENCE_ABSORB_PRESSURE = "PX_FLOW_DIVERGENCE_ABSORB_PRESSURE_1B"

# OBV accumulation + ADL distribution divergence (run-144 pattern)
BADGE_OBV_ACCUM_DISTRIB          = "PX_FLOW_DIVERGENCE_OBV_ACCUM_DISTRIB_1B"

# Broad divergence variant — original run-139 pattern
BADGE_DIVERGENCE_ACCUM           = "PX_FLOW_DIVERGENCE_ACCUM_PRESSURE"

BADGE_BULLISH_ACCUM              = "PX_FLOW_BULLISH_ACCUM_IGNITION"
BADGE_SUPPLY_ABSORB              = "PX_FLOW_DIVERGENCE_SUPPLY_ABSORB"
BADGE_IGNITION_CONFIRM           = "PX_IGNITION_CONFIRM_PRICE_ACTION"
BADGE_GAP_RESET_RECLAIM          = "PX_GAP_RESET_RECLAIM_CONTEXT"

# Canonical order: strict-first within each family
ALL_CURATED_BADGES: list[str] = [
    BADGE_DIVERGENCE_ABSORB_PRESSURE,
    BADGE_OBV_ACCUM_DISTRIB,
    BADGE_DIVERGENCE_ACCUM,
    BADGE_BULLISH_ACCUM,
    BADGE_SUPPLY_ABSORB,
    BADGE_IGNITION_CONFIRM,
    BADGE_GAP_RESET_RECLAIM,
]

# Divergence-pressure family — only max score applied to avoid double-counting
_DIV_PRESSURE_FAMILY: frozenset[str] = frozenset({
    BADGE_DIVERGENCE_ABSORB_PRESSURE,
    BADGE_DIVERGENCE_ACCUM,
})

# OBV-divergence family — only max score applied to avoid double-counting
_DIV_OBV_FAMILY: frozenset[str] = frozenset({
    BADGE_OBV_ACCUM_DISTRIB,
    BADGE_SUPPLY_ABSORB,
})

# ── Frozen rule definitions ───────────────────────────────────────────────────
#
# tag_mode:
#   "flow"  → match against snap["flow_tags"]  (V1C: ADL_ACCUM_3D, CMF_*, …)
#   "price" → match against snap["tags"]        (V1B: EXPANSION, DRYUP, …)
#
# window:
#   1 → single bar must contain ALL required_tags
#   5 → union of any 5-bar consecutive window must contain ALL required_tags
#
# Rule priority: first rule in list has precedence only for primary_badge.
# All matching rules fire independently.

CURATED_RULES: list[dict] = [
    # ── Rule 0: STRICT divergence — absorption pressure + lower-wick (run 142) ─
    {
        "badge":            BADGE_DIVERGENCE_ABSORB_PRESSURE,
        "required_tags":    frozenset({
            "ADL_ACCUM_3D", "BUY_PRESSURE_HIGH", "CLOSE_HIGH",
            "CMF_NEGATIVE", "LOWER_WICK_ABSORPTION", "OBV_ACCUM_3D",
        }),
        "optional_tags":    frozenset(),
        "tag_mode":         "flow",
        "window":           1,
        "feature_family":   "FLOW",
        "source_type":      "SINGLE_BAR",
        "flow_subtype":     "FLOW_DIVERGENCE",
        "intended_use":     "WATCHLIST_RANKING",
        "production_status":"RESEARCH_ONLY",
        "score_weight":     5,
        "run142_stats": {
            "count_all_4x": 9, "count_false_positive": 0,
            "false_positive_rate": 0.0, "reliability_score": 0.7997,
            "split_artifact_exposure": 0.1538,
        },
        "interpretation": (
            "Hidden accumulation / pressure reversal with lower-wick absorption. "
            "Accumulation pressure despite negative CMF; lower wick suggests "
            "absorption/reclaim before breakout."
        ),
        "safety_note": "Do not route to BUY. Research-only FLOW context.",
    },

    # ── Rule 1: OBV accumulation / ADL distribution divergence (run 144) ────────
    {
        "badge":            BADGE_OBV_ACCUM_DISTRIB,
        "required_tags":    frozenset({
            "ADL_DISTRIB_3D", "CMF_NEGATIVE", "OBV_ACCUM_3D",
        }),
        "optional_tags":    frozenset(),
        "tag_mode":         "flow",
        "window":           1,
        "feature_family":   "FLOW",
        "source_type":      "SINGLE_BAR",
        "flow_subtype":     "FLOW_DIVERGENCE",
        "intended_use":     "WATCHLIST_RANKING",
        "production_status":"RESEARCH_ONLY",
        "score_weight":     4,
        "run144_stats": {
            "count_all_4x": 25, "count_false_positive": 8,
            "false_positive_rate": 0.131, "reliability_score": 0.7647,
            "split_artifact_exposure": None,
            "regime_notes": "Best in PRICE_1_TO_3 (84.6% 4x) / PRICE_3_TO_10 (75.0% 4x). Avoid PRICE_GT_25.",
        },
        "interpretation": (
            "OBV accumulating while ADL distributing and CMF negative. "
            "Hidden-demand divergence — buyers absorbing supply without visible price progress."
        ),
        "safety_note": "Do not route to BUY. Research-only FLOW divergence context.",
    },

    # ── Rule 2: BROAD divergence accumulation with hidden demand (run 139) ─────
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
        "source_type":      "SINGLE_BAR",
        "flow_subtype":     "FLOW_DIVERGENCE",
        "intended_use":     "WATCHLIST_RANKING",
        "production_status":"RESEARCH_ONLY",
        "score_weight":     4,
        "run139_stats": {
            "count_all_4x": 10, "count_false_positive": 1,
            "false_positive_rate": 0.015, "reliability_score": 0.842,
            "split_artifact_exposure": 0.0,
        },
        "interpretation": (
            "Accumulation/buy pressure visible but CMF remains negative. "
            "May indicate hidden accumulation or pressure reversal before obvious breakout."
        ),
        "safety_note": "Do not route to BUY",
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
        "source_type":      "SINGLE_BAR",
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
        "source_type":      "SINGLE_BAR",
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
        "source_type":      "SINGLE_BAR",
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

# Forbidden outcome fields — used in anti-leakage assertion
_OUTCOME_FIELDS = frozenset({
    "pump_multiple", "group_type", "days_from_breakout_to_peak",
    "days_to_peak", "forward_return_1d", "forward_return_3d",
    "forward_return_5d", "forward_return_10d", "pump_return_pct",
    "outcome_label", "detected_at_peak",
})


# ── Known flow tag vocabulary (for normalization fallback) ────────────────────

_KNOWN_FLOW_TAGS: frozenset[str] = frozenset({
    "ADL_ACCUM_3D", "ADL_DISTRIB_3D",
    "OBV_ACCUM_3D", "OBV_DISTRIB_3D",
    "CMF_NEGATIVE", "CMF_POSITIVE",
    "BUY_PRESSURE_HIGH", "BUY_PRESSURE_LOW",
    "CLOSE_HIGH", "CLOSE_LOW",
    "LOWER_WICK_ABSORPTION", "UPPER_WICK_SUPPLY",
    "DELTA_PROXY_BULL", "DELTA_PROXY_BEAR",
    "EFFORT_RESULT_BULL", "EFFORT_RESULT_BEAR",
    "LOW_EFFORT_HIGH_RESULT", "HIGH_EFFORT_LOW_RESULT",
    "GAP_DOWN_RECLAIM_FLOW", "GAP_UP_HOLD_FLOW",
    "GAP_UP_FADE_FLOW", "GAP_DOWN_FAIL_FLOW",
})


def normalize_snapshot_flow_tags(snapshot: dict) -> list[str]:
    """
    Extract and normalize flow tags from a snapshot using a priority fallback chain.

    Priority:
      1. snapshot["flow_tags"] if list
      2. snapshot["flow_tag_signature"] split by "+"
      3. snapshot["feature_json"]["flow_tags"] if list
      4. snapshot["feature_json"]["flow_tag_signature"] split by "+"
      5. snapshot["tag_signature"] if it contains known flow tags
      6. snapshot["tags"] if it contains known flow tags

    Returns a deduplicated, uppercased, whitespace-stripped list.
    """
    def _parse(val) -> list[str]:
        if isinstance(val, list):
            return [str(t).strip().upper() for t in val if str(t).strip()]
        if isinstance(val, str):
            return [t.strip().upper() for t in val.replace("→", "+").split("+") if t.strip()]
        return []

    fj = snapshot.get("feature_json") or {}

    # If flow_tags is explicitly set (even as []), respect it — no fallback to tags field.
    # Only use the last-resort tag fallback when all explicit flow fields are absent.
    explicit_flow_tags = snapshot.get("flow_tags")
    if explicit_flow_tags is not None:
        candidate = _parse(explicit_flow_tags)
    else:
        for candidate in [
            _parse(snapshot.get("flow_tag_signature")),
            _parse(fj.get("flow_tags")),
            _parse(fj.get("flow_tag_signature")),
        ]:
            if candidate:
                break
        else:
            # Last-resort: check tag_signature / tags for known flow tags
            ts = _parse(snapshot.get("tag_signature"))
            if any(t in _KNOWN_FLOW_TAGS for t in ts):
                candidate = ts
            else:
                tg = _parse(snapshot.get("tags"))
                candidate = tg if any(t in _KNOWN_FLOW_TAGS for t in tg) else []

    seen: set[str] = set()
    result: list[str] = []
    for t in candidate:
        if t and t not in seen:
            seen.add(t)
            result.append(t)
    return result


# ── Exact bar-level badge evaluation ─────────────────────────────────────────

def evaluate_curated_flow_badges_from_snapshots(snaps: list[dict]) -> dict:
    """
    Evaluate all curated rules against bar snapshots and return rich diagnostics.

    Anti-leakage: reads only snap["flow_tags"] and snap["tags"].
    Never reads group_type, pump_multiple, or any future-return field.

    Returns
    -------
    {
      "badges":             list[str],
      "badge_reasons":      list[str],
      "subtypes":           list[str],
      "exact_match_count":  int,        # number of distinct badges that fired
      "matched_bars":       list[dict]  # per-bar diagnostics for each firing
    }
    """
    if not snaps:
        return {
            "badges":            [],
            "badge_reasons":     [],
            "subtypes":          [],
            "exact_match_count": 0,
            "matched_bars":      [],
        }

    matched: set[str]    = set()
    reasons: list[str]   = []
    matched_bars: list[dict] = []

    # ── Single-bar rules (window=1) ───────────────────────────────────────────
    for snap in snaps:
        snap_date  = snap.get("date") or snap.get("days_to_breakout") or "?"
        flow_tags  = set(normalize_snapshot_flow_tags(snap))
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
                matched_bars.append({
                    "date":          snap_date,
                    "badge":         badge,
                    "flow_tags":     sorted(flow_tags),
                    "price_tags":    sorted(price_tags),
                    "tag_signature": snap.get("tag_signature") or "+".join(sorted(flow_tags)),
                })

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
                matched_bars.append({
                    "date":          end_date,
                    "badge":         BADGE_GAP_RESET_RECLAIM,
                    "flow_tags":     [],
                    "price_tags":    sorted(union_tags),
                    "tag_signature": "+".join(sorted(union_tags)),
                })
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
        "badges":            badges_ordered,
        "badge_reasons":     reasons,
        "subtypes":          subtypes,
        "exact_match_count": len(badges_ordered),
        "matched_bars":      matched_bars,
    }


def evaluate_curated_rules_on_snaps(snaps: list[dict]) -> dict:
    """
    Backward-compatible wrapper around evaluate_curated_flow_badges_from_snapshots.

    Returns the legacy keys used by score_episode_curated_flow:
      curated_flow_badges, curated_flow_badge_reasons, curated_flow_subtypes.
    Also passes through exact_match_count and matched_bars for richer callers.
    """
    r = evaluate_curated_flow_badges_from_snapshots(snaps)
    return {
        "curated_flow_badges":        r["badges"],
        "curated_flow_badge_reasons": r["badge_reasons"],
        "curated_flow_subtypes":      r["subtypes"],
        "curated_flow_exact_match_count": r["exact_match_count"],
        "curated_flow_matched_bars":  r["matched_bars"],
    }


# ── Score computation ─────────────────────────────────────────────────────────

def compute_curated_flow_score(
    badges: list[str],
    ep: dict,
    *,
    allow_proxy_score: bool = False,
    _assert_no_leakage: bool = False,
) -> dict:
    """
    Compute research-only curated FLOW score + bucket for one episode.

    Parameters
    ----------
    badges           : matched badge names from evaluate_curated_rules_on_snaps()
    ep               : episode feature dict (PRE-window fields only)
    allow_proxy_score: if False (default), context bonuses are only applied when
                       at least one exact badge fired, and the score is capped at 4
                       (CURATED_FLOW_LOW) when no exact badge is present.
                       Set True for diagnostic / research mode.
    _assert_no_leakage: if True, raise AssertionError if ep contains any
                        known outcome field (used in tests).

    Returns
    -------
    {
      "curated_flow_score":             int,
      "curated_flow_bucket":            str,
      "curated_flow_risk_flags":        list[str],
      "curated_flow_reasons":           list[str],
      "curated_flow_exact_match_count": int,
      "curated_flow_is_proxy_only":     bool,
      "curated_flow_primary_badge":     str | None,
    }

    Scoring model v2
    ----------------
    A. Badge scores (divergence-pressure family uses max, not sum)
    B. Context bonuses — only applied when exact badge present OR allow_proxy_score
    C. Penalties — always applied
    D. Proxy-only cap — if no exact badge and not allow_proxy_score:
         score = min(score, 4), bucket ≤ CURATED_FLOW_LOW
    E. Bucket thresholds:
         CURATED_FLOW_HIGH   ≥ 8 AND exact_badge_count > 0
         CURATED_FLOW_MEDIUM 5–7 AND exact_badge_count > 0
         CURATED_FLOW_LOW    3–4 (or proxy-only score ≥ 3)
         CURATED_FLOW_IGNORE < 3
    """
    if _assert_no_leakage:
        found = _OUTCOME_FIELDS & set(ep.keys())
        if found:
            raise AssertionError(
                f"Anti-leakage violation: episode contains outcome fields: {found}"
            )

    score                 = 0
    risk_flags: list[str] = []
    reasons:    list[str] = []

    exact_badge_count = len(badges)
    has_exact_badge   = exact_badge_count > 0

    # ── A. Badge scores with double-counting prevention ───────────────────────
    # Each family uses max-score (not sum) to avoid double-counting
    dp_badges   = [b for b in badges if b in _DIV_PRESSURE_FAMILY]
    obv_badges  = [b for b in badges if b in _DIV_OBV_FAMILY]
    other_badges = [
        b for b in badges
        if b not in _DIV_PRESSURE_FAMILY and b not in _DIV_OBV_FAMILY
    ]

    primary_badge: Optional[str] = None

    if dp_badges:
        primary_dp    = max(dp_badges, key=lambda b: BADGE_SCORE_WEIGHTS.get(b, 0))
        max_dp_score  = BADGE_SCORE_WEIGHTS[primary_dp]
        score        += max_dp_score
        reasons.append(f"+{max_dp_score} {primary_dp} (div_pressure_family_max)")
        primary_badge = primary_dp
        if len(dp_badges) > 1:
            suppressed = [b for b in dp_badges if b != primary_dp]
            reasons.append(
                f"[double-count suppressed: {', '.join(suppressed)} in div_pressure_family]"
            )

    if obv_badges:
        primary_obv   = max(obv_badges, key=lambda b: BADGE_SCORE_WEIGHTS.get(b, 0))
        max_obv_score = BADGE_SCORE_WEIGHTS[primary_obv]
        score        += max_obv_score
        reasons.append(f"+{max_obv_score} {primary_obv} (div_obv_family_max)")
        if primary_badge is None:
            primary_badge = primary_obv
        if len(obv_badges) > 1:
            suppressed = [b for b in obv_badges if b != primary_obv]
            reasons.append(
                f"[double-count suppressed: {', '.join(suppressed)} in div_obv_family]"
            )

    for badge in other_badges:
        w = BADGE_SCORE_WEIGHTS.get(badge, 0)
        if w:
            score += w
            reasons.append(f"+{w} {badge}")
        if primary_badge is None:
            primary_badge = badge

    # ── B. Context bonuses (only with exact badge OR allow_proxy_score) ───────
    dryup       = _num(ep.get("dryup_day_count_pre"))
    d_conf      = _num(ep.get("d_confluence_day_count_pre"))
    compression = _num(ep.get("compression_days_pre"))
    had_accum   = bool(ep.get("had_accumulation_like"))
    had_spring  = bool(ep.get("had_spring_test_lps"))
    split_ctx   = ep.get("split_context") or "NO_SPLIT"
    median_dv   = _num(ep.get("median_dollar_volume_pre"))
    high_exp_ct = _num(ep.get("high_expansion_risk_day_count_pre"))

    if has_exact_badge or allow_proxy_score:
        if _between(dryup, 8, 25):
            score += 2; reasons.append("+2 dryup 8-25d")
        if _gte(d_conf, 4):
            score += 2; reasons.append("+2 d_confluence>=4d")
        if _gte(compression, 6):
            score += 1; reasons.append("+1 compression>=6d")
        if had_accum:
            score += 1; reasons.append("+1 had_accumulation_like")
        if had_spring:
            score += 1; reasons.append("+1 had_spring_test_lps")
        if split_ctx == "NO_SPLIT":
            score += 1; reasons.append("+1 no_split")
        if median_dv == 0:
            risk_flags.append("missing_dollar_volume")
        elif _gte(median_dv, 100_000):
            score += 1; reasons.append("+1 median_dv>=100k")
    else:
        reasons.append("[context bonuses skipped: no exact badge]")

    # ── C. Penalties (always applied) ────────────────────────────────────────
    if ep.get("split_artifact_risk"):
        score -= 4; risk_flags.append("split_artifact"); reasons.append("-4 split_artifact")

    if split_ctx in ("RECENT_REVERSE_SPLIT", "OLD_REVERSE_SPLIT"):
        score -= 3; risk_flags.append("reverse_split"); reasons.append("-3 reverse_split")

    if 0 < median_dv < 50_000:
        score -= 2; risk_flags.append("low_dollar_volume"); reasons.append("-2 low_dv<50k")

    # Bearish/supply-only badge without any bullish/reclaim confirmation
    bearish_only = (
        BADGE_SUPPLY_ABSORB in badges
        and BADGE_OBV_ACCUM_DISTRIB          not in badges
        and BADGE_DIVERGENCE_ABSORB_PRESSURE not in badges
        and BADGE_DIVERGENCE_ACCUM           not in badges
        and BADGE_BULLISH_ACCUM              not in badges
        and BADGE_IGNITION_CONFIRM           not in badges
        and BADGE_GAP_RESET_RECLAIM          not in badges
    )
    if bearish_only:
        score -= 2; risk_flags.append("bearish_supply_only"); reasons.append("-2 bearish_supply_only")

    # High expansion risk without any bullish/accumulation flow badge
    has_bullish = (
        BADGE_DIVERGENCE_ABSORB_PRESSURE in badges
        or BADGE_OBV_ACCUM_DISTRIB       in badges
        or BADGE_DIVERGENCE_ACCUM        in badges
        or BADGE_BULLISH_ACCUM           in badges
    )
    if _gte(high_exp_ct, 30) and not has_bullish:
        score -= 2; risk_flags.append("high_expansion_risk"); reasons.append("-2 high_exp>=30_no_bullish")

    # Regime penalties for OBV divergence badge (run-144 regime analysis)
    if BADGE_OBV_ACCUM_DISTRIB in badges:
        price_bucket = ep.get("price_bucket") or ""
        atr_bucket   = ep.get("atr_bucket") or ""
        if price_bucket == "PRICE_GT_25":
            score -= 2; risk_flags.append("obv_price_gt25"); reasons.append("-2 obv_badge+price_gt25")
        if atr_bucket == "ATR_EXTREME_GT_40":
            score -= 2; risk_flags.append("obv_atr_extreme"); reasons.append("-2 obv_badge+atr_extreme")

    # Badge matched but no dryup/compression/D-confluence context
    has_context = _gte(dryup, 5) or _gte(compression, 4) or _gte(d_conf, 2)
    if has_exact_badge and not has_context:
        score -= 2; risk_flags.append("badge_no_context"); reasons.append("-2 badge_no_context")

    # ── D. Proxy-only cap ─────────────────────────────────────────────────────
    is_proxy_only = not has_exact_badge
    if is_proxy_only and not allow_proxy_score:
        if score > 4:
            score = 4
            reasons.append("[proxy_only: score capped at 4]")

    # ── E. Bucket (requires exact badge for HIGH/MEDIUM) ──────────────────────
    if is_proxy_only and not allow_proxy_score:
        # Proxy-only: at most LOW
        bucket = "CURATED_FLOW_LOW" if score >= 3 else "CURATED_FLOW_IGNORE"
    else:
        if score >= 8:
            bucket = "CURATED_FLOW_HIGH"
        elif score >= 5:
            bucket = "CURATED_FLOW_MEDIUM"
        elif score >= 3:
            bucket = "CURATED_FLOW_LOW"
        else:
            bucket = "CURATED_FLOW_IGNORE"

    return {
        "curated_flow_score":             score,
        "curated_flow_bucket":            bucket,
        "curated_flow_risk_flags":        risk_flags,
        "curated_flow_reasons":           reasons,
        "curated_flow_exact_match_count": exact_badge_count,
        "curated_flow_is_proxy_only":     is_proxy_only,
        "curated_flow_primary_badge":     primary_badge,
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
            "source_type":      r.get("source_type"),
            "flow_subtype":     r.get("flow_subtype"),
            "intended_use":     r["intended_use"],
            "production_status":r["production_status"],
            "score_weight":     r["score_weight"],
            "run_stats":        r.get("run144_stats") or r.get("run142_stats") or r.get("run139_stats", {}),
            "interpretation":   r.get("interpretation"),
            "safety_note":      r.get("safety_note"),
        }
        for r in CURATED_RULES
    ]
