"""
Curated FLOW Replay Analyzer — Parts 4-9.

Consumes episodes that have been scored with curated_flow_rules.py
(fields: curated_flow_badges, curated_flow_score, curated_flow_bucket,
 curated_flow_reasons, curated_flow_risk_flags, curated_flow_subtypes,
 curated_flow_exact_match_count, curated_flow_is_proxy_only,
 curated_flow_primary_badge, curated_flow_matched_bars)
and builds the full research report including:

  - Exact-match diagnostics              (Part 4)
  - Bucket performance vs baseline       (Part 4 / 5)
  - Pump Watch × Curated FLOW matrix     (Part 6)
  - Pump Watch × Exact Badge matrix      (Part 7)
  - Badge-level performance              (Part 7)
  - Missed 4x rescue candidates          (Part 8)
  - False positive trap analysis         (Part 8)
  - Baseline vs baseline+FLOW comparison (Part 4)
  - Recommendations                      (Part 9)

RESEARCH ONLY — does not affect Scanner V2 routing.
"""

import logging
from typing import Optional

from replay.curated_flow_rules import (
    ALL_CURATED_BADGES,
    BADGE_DIVERGENCE_ABSORB_PRESSURE,
    BADGE_DIVERGENCE_ACCUM,
    BADGE_OBV_ACCUM_DISTRIB,
    BADGE_SUPPLY_ABSORB,
    score_episode_curated_flow,
    curated_rules_registry_snapshot,
    normalize_snapshot_flow_tags,
)

logger = logging.getLogger(__name__)

_BUCKETS = ["CURATED_FLOW_HIGH", "CURATED_FLOW_MEDIUM",
            "CURATED_FLOW_LOW",  "CURATED_FLOW_IGNORE"]

_PW_LABELS = ["PUMP_WATCH_HIGH", "PUMP_WATCH_MEDIUM",
              "PUMP_SPECULATIVE", "PUMP_IGNORE"]

_EXACT_PRESENCE_COLS = ["EXACT_BADGE_PRESENT", "PROXY_ONLY", "NO_CURATED_SIGNAL"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sym(ep: dict) -> str:
    return ep.get("symbol") or ep.get("ticker") or "?"

def _group(ep: dict) -> str:
    return ep.get("group_type") or ""

def _is_4x(ep: dict) -> bool:
    return _group(ep) == "4x_pump"

def _is_fp(ep: dict) -> bool:
    return _group(ep) == "false_positive"

def _is_win(ep: dict) -> bool:
    return _group(ep) == "normal_winner"

def _pw_label(ep: dict) -> str:
    return ep.get("pump_watch_label") or "UNKNOWN"

def _cf_bucket(ep: dict) -> str:
    return ep.get("curated_flow_bucket") or "CURATED_FLOW_IGNORE"

def _cf_score(ep: dict) -> float:
    return ep.get("curated_flow_score") or 0

def _cf_badges(ep: dict) -> list:
    return ep.get("curated_flow_badges") or []

def _cf_exact_count(ep: dict) -> int:
    return ep.get("curated_flow_exact_match_count") or 0

def _cf_is_proxy(ep: dict) -> bool:
    return bool(ep.get("curated_flow_is_proxy_only"))

def _median(lst: list) -> Optional[float]:
    if not lst:
        return None
    s = sorted(lst)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m-1] + s[m]) / 2

def _safe_rate(n: int, d: int) -> Optional[float]:
    return round(n / d, 3) if d > 0 else None

def _outcome_stats(eps: list[dict]) -> dict:
    n       = len(eps)
    n_4x    = sum(1 for e in eps if _is_4x(e))
    n_fp    = sum(1 for e in eps if _is_fp(e))
    n_win   = sum(1 for e in eps if _is_win(e))
    scores  = sorted(_cf_score(e) for e in eps)
    pm_list = sorted(e["pump_multiple"] for e in eps
                     if e.get("pump_multiple") is not None)
    pw_scores = sorted(e["pump_watch_score"] for e in eps
                       if e.get("pump_watch_score") is not None)
    r4x  = _safe_rate(n_4x, n)
    rfp  = _safe_rate(n_fp, n)
    prec = _safe_rate(n_4x, n_4x + n_fp) if (n_4x + n_fp) else None

    n_exact = sum(1 for e in eps if _cf_exact_count(e) > 0)
    n_proxy = sum(1 for e in eps if _cf_is_proxy(e) and _cf_score(e) >= 3)

    return {
        "total":                    n,
        "four_x_count":             n_4x,
        "false_positive_count":     n_fp,
        "normal_winner_count":      n_win,
        "four_x_rate":              r4x,
        "false_positive_rate":      rfp,
        "four_x_vs_fp_precision":   prec,
        "median_curated_flow_score": _median(scores),
        "median_pump_watch_score":  _median(pw_scores),
        "median_pump_multiple":     _median(pm_list),
        "exact_badge_count":        n_exact,
        "proxy_only_count":         n_proxy,
    }

def _sample_syms(eps: list[dict], group_fn, k: int = 6) -> list[str]:
    return [_sym(e) for e in eps if group_fn(e)][:k]


# ── Score episodes using cached or freshly-computed curated flow ──────────────

def score_episodes_curated_flow(
    episodes: list[dict],
    daily_by_episode: Optional[dict] = None,
) -> list[dict]:
    """
    Augment episodes with curated_flow_* fields.

    If curated_flow_badges is already present (set during discovery run via the
    module-level cache), it is preserved.  Otherwise the function falls back to
    computing scores using only episode-level features (no bar snapshots).
    Pass daily_by_episode (episode_id → list[bar_row]) to enable full bar-level
    evaluation for episodes that lack cached results.

    Returns new list of episode dicts (originals not mutated).
    """
    from replay.bar_feature_engine import build_bar_feature_snapshots_for_episode

    result = []
    for ep in episodes:
        ep_copy = dict(ep)
        ep_id   = ep_copy.get("episode_id") or ep_copy.get("id")

        # Already scored (from pipeline cache) — recompute score in case fields updated
        if ep_copy.get("curated_flow_badges") is not None:
            if ep_copy.get("curated_flow_bucket") is None:
                from replay.curated_flow_rules import compute_curated_flow_score
                sc = compute_curated_flow_score(ep_copy["curated_flow_badges"], ep_copy)
                ep_copy.update(sc)
            # Ensure new v2 fields exist even on cached episodes
            if "curated_flow_exact_match_count" not in ep_copy:
                ep_copy["curated_flow_exact_match_count"] = len(ep_copy.get("curated_flow_badges") or [])
            if "curated_flow_is_proxy_only" not in ep_copy:
                ep_copy["curated_flow_is_proxy_only"] = ep_copy["curated_flow_exact_match_count"] == 0
            # Build curated_flow_debug for cached episodes using daily rows if available
            if "curated_flow_debug" not in ep_copy:
                snaps: list[dict] = []
                if daily_by_episode and ep_id is not None:
                    daily_rows = daily_by_episode.get(ep_id, [])
                    if daily_rows:
                        try:
                            snaps = build_bar_feature_snapshots_for_episode(ep_copy, daily_rows)
                        except Exception as _e:
                            logger.debug("snapshot build failed ep %s: %s", ep_id, _e)
                snaps_with_tags = sum(
                    1 for s in snaps
                    if (s.get("flow_tags") or []) not in ([], ["FLAT"])
                )
                seen_sigs: list[str] = [
                    s.get("flow_tag_signature") or "FLAT"
                    for s in snaps
                    if (s.get("flow_tag_signature") or "FLAT") != "FLAT"
                ]
                ep_copy["curated_flow_debug"] = {
                    "snapshot_count":           len(snaps),
                    "snapshots_with_flow_tags": snaps_with_tags,
                    "seen_flow_signatures":     sorted(set(seen_sigs)),
                    "badges_matched":           list(ep_copy.get("curated_flow_badges") or []),
                    "exact_match_count":        ep_copy.get("curated_flow_exact_match_count", 0),
                    "source":                   "cached",
                }
            result.append(ep_copy)
            continue

        # Full bar-level evaluation if daily rows available
        snaps: list[dict] = []
        if daily_by_episode and ep_id is not None:
            daily_rows = daily_by_episode.get(ep_id, [])
            if daily_rows:
                try:
                    snaps = build_bar_feature_snapshots_for_episode(ep_copy, daily_rows)
                except Exception as e:
                    logger.debug("snapshot build failed ep %s: %s", ep_id, e)

        cf = score_episode_curated_flow(ep_copy, snaps)
        ep_copy.update(cf)

        # Per-episode curated_flow_debug diagnostics
        snaps_with_tags = sum(
            1 for s in snaps
            if (s.get("flow_tags") or []) not in ([], ["FLAT"])
        )
        seen_sigs: list[str] = [
            s.get("flow_tag_signature") or "FLAT"
            for s in snaps
            if (s.get("flow_tag_signature") or "FLAT") != "FLAT"
        ]
        ep_copy["curated_flow_debug"] = {
            "snapshot_count":              len(snaps),
            "snapshots_with_flow_tags":    snaps_with_tags,
            "seen_flow_signatures":        sorted(set(seen_sigs)),
            "badges_matched":              list(ep_copy.get("curated_flow_badges") or []),
            "exact_match_count":           ep_copy.get("curated_flow_exact_match_count", 0),
        }

        result.append(ep_copy)

    return result


# ── Part 4: Exact match diagnostics ──────────────────────────────────────────

def _build_curated_match_diagnostics(episodes: list[dict]) -> dict:
    """
    Aggregate exact-match vs proxy-only statistics.

    Returns
    -------
    {
      "exact_badge_match_count":                   int,
      "proxy_score_only_count":                    int,
      "episodes_with_exact_badges":                int,
      "episodes_with_proxy_only_score":            int,
      "badge_match_counts":                        {badge: n},
      "episodes_with_no_snapshots":                int,
      "episodes_with_snapshots_but_no_flow_tags":  int,
      "episodes_with_flow_tags_but_no_badge":      int,
      "top_seen_flow_signatures":                  [{signature, count}],
    }
    """
    eps_with_exact  = [e for e in episodes if _cf_exact_count(e) > 0]
    eps_proxy_only  = [e for e in episodes if _cf_is_proxy(e) and _cf_score(e) >= 3]

    badge_counts: dict[str, int] = {}
    for badge in ALL_CURATED_BADGES:
        badge_counts[badge] = sum(1 for e in episodes if badge in _cf_badges(e))

    # Per-episode debug breakdowns (available when score_episodes_curated_flow ran)
    no_snaps           = 0
    snaps_no_flow_tags = 0
    flow_tags_no_badge = 0
    sig_counter: dict[str, int] = {}
    for ep in episodes:
        dbg = ep.get("curated_flow_debug") or {}
        snap_n     = dbg.get("snapshot_count", 0)
        snaps_wtag = dbg.get("snapshots_with_flow_tags", 0)
        if snap_n == 0:
            no_snaps += 1
        elif snaps_wtag == 0:
            snaps_no_flow_tags += 1
        elif _cf_exact_count(ep) == 0:
            flow_tags_no_badge += 1
        for sig in (dbg.get("seen_flow_signatures") or []):
            sig_counter[sig] = sig_counter.get(sig, 0) + 1

    top_sigs = sorted(sig_counter.items(), key=lambda x: -x[1])[:20]

    return {
        "exact_badge_match_count":                  sum(_cf_exact_count(e) for e in episodes),
        "proxy_score_only_count":                   len(eps_proxy_only),
        "episodes_with_exact_badges":               len(eps_with_exact),
        "episodes_with_proxy_only_score":           len(eps_proxy_only),
        "badge_match_counts":                       badge_counts,
        "episodes_with_no_snapshots":               no_snaps,
        "episodes_with_snapshots_but_no_flow_tags": snaps_no_flow_tags,
        "episodes_with_flow_tags_but_no_badge":     flow_tags_no_badge,
        "top_seen_flow_signatures":                 [
            {"signature": sig, "count": cnt} for sig, cnt in top_sigs
        ],
    }


# ── Part 5: Bucket performance ────────────────────────────────────────────────

def _build_bucket_performance(episodes: list[dict]) -> dict:
    by_bucket: dict[str, list] = {b: [] for b in _BUCKETS}
    for ep in episodes:
        by_bucket.setdefault(_cf_bucket(ep), []).append(ep)

    result: dict[str, dict] = {}
    for bucket in _BUCKETS:
        eps   = by_bucket[bucket]
        stats = _outcome_stats(eps)
        stats["examples_4x"]            = _sample_syms(eps, _is_4x)
        stats["examples_false_positive"] = _sample_syms(eps, _is_fp)
        stats["split_artifact_count"]   = sum(1 for e in eps if e.get("split_artifact_risk"))
        stats["reverse_split_count"]    = sum(
            1 for e in eps
            if e.get("split_context") in ("RECENT_REVERSE_SPLIT", "OLD_REVERSE_SPLIT")
        )
        stats["low_dollar_volume_count"] = sum(
            1 for e in eps if 0 < (e.get("median_dollar_volume_pre") or 0) < 50_000
        )
        result[bucket] = stats

    return result


# ── Part 6: Pump Watch × Curated FLOW matrix ─────────────────────────────────

def _build_pw_cf_matrix(episodes: list[dict]) -> dict:
    matrix: dict[str, dict] = {}
    for pw in _PW_LABELS:
        matrix[pw] = {}
        for bucket in _BUCKETS:
            cell = [e for e in episodes
                    if _pw_label(e) == pw and _cf_bucket(e) == bucket]
            stats = _outcome_stats(cell)
            stats["sample_symbols"] = [_sym(e) for e in cell[:5]]
            matrix[pw][bucket] = stats
    return matrix


# ── Part 7: Pump Watch × Exact Badge Presence matrix ─────────────────────────

def _build_pw_exact_badge_matrix(episodes: list[dict]) -> dict:
    """
    Second matrix: Pump Watch label × Exact Badge Presence.

    Columns: EXACT_BADGE_PRESENT, PROXY_ONLY, NO_CURATED_SIGNAL,
             plus one column per badge in ALL_CURATED_BADGES.
    """
    def _col(ep: dict) -> str:
        if _cf_exact_count(ep) > 0:
            return "EXACT_BADGE_PRESENT"
        if _cf_score(ep) >= 3:
            return "PROXY_ONLY"
        return "NO_CURATED_SIGNAL"

    all_cols = _EXACT_PRESENCE_COLS + ALL_CURATED_BADGES

    matrix: dict[str, dict] = {}
    for pw in _PW_LABELS:
        matrix[pw] = {}
        for col in _EXACT_PRESENCE_COLS:
            cell = [e for e in episodes if _pw_label(e) == pw and _col(e) == col]
            stats = _outcome_stats(cell)
            stats["sample_symbols"] = [_sym(e) for e in cell[:5]]
            matrix[pw][col] = stats
        # Per-badge breakdown for this PW label
        for badge in ALL_CURATED_BADGES:
            cell = [e for e in episodes if _pw_label(e) == pw and badge in _cf_badges(e)]
            stats = _outcome_stats(cell)
            stats["sample_symbols"] = [_sym(e) for e in cell[:5]]
            matrix[pw][badge] = stats
    return matrix


# ── Part 7: Badge-level performance ──────────────────────────────────────────

def _build_badge_performance(episodes: list[dict], regime_available: bool = False) -> list[dict]:
    rows = []
    for badge in ALL_CURATED_BADGES:
        matched = [e for e in episodes if badge in _cf_badges(e)]
        stats   = _outcome_stats(matched)
        stats["badge"]                   = badge
        stats["examples_4x"]             = _sample_syms(matched, _is_4x)
        stats["examples_false_positive"] = _sample_syms(matched, _is_fp)

        # Split context breakdown
        sc_counts: dict[str, int] = {}
        for e in matched:
            sc = e.get("split_context") or "NO_SPLIT"
            sc_counts[sc] = sc_counts.get(sc, 0) + 1
        stats["split_context_breakdown"] = sc_counts

        # Low dollar volume
        stats["low_dollar_volume_count"] = sum(
            1 for e in matched if 0 < (e.get("median_dollar_volume_pre") or 0) < 50_000
        )
        # Reverse split
        stats["reverse_split_count"] = sum(
            1 for e in matched
            if e.get("split_context") in ("RECENT_REVERSE_SPLIT", "OLD_REVERSE_SPLIT")
        )
        stats["split_artifact_count"] = sum(
            1 for e in matched if e.get("split_artifact_risk")
        )

        # Regime breakdown — always compute if any episode has bucket fields
        def _regime_breakdown(eps: list[dict], field: str) -> dict:
            by_bucket: dict[str, dict] = {}
            for e in eps:
                bkt = e.get(field) or "UNKNOWN"
                if bkt not in by_bucket:
                    by_bucket[bkt] = {"n": 0, "n_4x": 0, "n_fp": 0}
                by_bucket[bkt]["n"]    += 1
                if _is_4x(e): by_bucket[bkt]["n_4x"] += 1
                if _is_fp(e): by_bucket[bkt]["n_fp"]  += 1
            # Add 4x_rate per bucket
            for bkt, d in by_bucket.items():
                d["4x_rate"] = _safe_rate(d["n_4x"], d["n"])
                d["fp_rate"] = _safe_rate(d["n_fp"], d["n"])
            return by_bucket

        stats["by_price_bucket"]        = _regime_breakdown(matched, "price_bucket")
        stats["by_atr_bucket"]          = _regime_breakdown(matched, "atr_bucket")
        stats["by_dollar_volume_bucket"] = _regime_breakdown(matched, "dollar_volume_bucket")

        rows.append(stats)
    return rows


# ── Part 8: Missed 4x rescue ──────────────────────────────────────────────────

def _build_missed_4x_rescue(episodes: list[dict]) -> list[dict]:
    """
    4x pumps that were missed by baseline (PUMP_IGNORE / PUMP_SPECULATIVE)
    but CURATED_FLOW bucket is HIGH or MEDIUM and no split artifact risk.
    """
    rescue: list[dict] = []
    for ep in episodes:
        if not _is_4x(ep):
            continue
        if ep.get("split_artifact_risk"):
            continue
        pw = _pw_label(ep)
        if pw not in ("PUMP_IGNORE", "PUMP_SPECULATIVE"):
            continue
        bucket = _cf_bucket(ep)
        if bucket not in ("CURATED_FLOW_HIGH", "CURATED_FLOW_MEDIUM"):
            continue
        rescue.append({
            "symbol":                     _sym(ep),
            "original_pw_label":          pw,
            "pump_watch_score":           ep.get("pump_watch_score"),
            "curated_flow_bucket":        bucket,
            "curated_flow_score":         _cf_score(ep),
            "curated_flow_badges":        _cf_badges(ep),
            "curated_flow_subtypes":      ep.get("curated_flow_subtypes") or [],
            "curated_flow_exact_match_count": _cf_exact_count(ep),
            "curated_flow_primary_badge": ep.get("curated_flow_primary_badge"),
            "curated_flow_matched_bars":  ep.get("curated_flow_matched_bars") or [],
            "pump_multiple":              ep.get("pump_multiple"),
            "dryup_day_count_pre":        ep.get("dryup_day_count_pre"),
            "compression_days_pre":       ep.get("compression_days_pre"),
            "d_confluence_day_count_pre": ep.get("d_confluence_day_count_pre"),
            "split_context":              ep.get("split_context") or "NO_SPLIT",
            "had_accumulation_like":      ep.get("had_accumulation_like"),
            "had_spring_test_lps":        ep.get("had_spring_test_lps"),
            "why_missed":                 ep.get("why_missed") or {},
            "curated_flow_reasons":       ep.get("curated_flow_reasons") or [],
        })
    rescue.sort(key=lambda r: (
        0 if r["curated_flow_bucket"] == "CURATED_FLOW_HIGH" else 1,
        -(r["curated_flow_score"] or 0),
    ))
    return rescue


# ── Part 8: False positive traps ──────────────────────────────────────────────

def _build_fp_traps(episodes: list[dict]) -> list[dict]:
    """
    False positives where CURATED_FLOW_HIGH/MEDIUM — i.e. FLOW badges fired
    on what turned out to be losers. Also flag the specific risk factors.
    """
    traps: list[dict] = []
    for ep in episodes:
        if not _is_fp(ep):
            continue
        bucket = _cf_bucket(ep)
        if bucket not in ("CURATED_FLOW_HIGH", "CURATED_FLOW_MEDIUM"):
            continue

        badges = _cf_badges(ep)
        risk_flags: list[str] = list(ep.get("curated_flow_risk_flags") or [])

        trap_notes: list[str] = []
        sc = ep.get("split_context") or "NO_SPLIT"
        if sc in ("RECENT_REVERSE_SPLIT", "OLD_REVERSE_SPLIT"):
            trap_notes.append("reverse_split_regime")
        dv = ep.get("median_dollar_volume_pre") or 0
        if 0 < dv < 50_000:
            trap_notes.append("low_dollar_volume")
        if ep.get("high_expansion_risk_day_count_pre", 0) >= 20:
            trap_notes.append("high_expansion_risk")
        if BADGE_SUPPLY_ABSORB in badges and BADGE_DIVERGENCE_ACCUM not in badges:
            trap_notes.append("bearish_supply_only_badge")
        if _cf_is_proxy(ep):
            trap_notes.append("proxy_only_score")

        traps.append({
            "symbol":               _sym(ep),
            "pump_watch_label":     _pw_label(ep),
            "pump_watch_score":     ep.get("pump_watch_score"),
            "curated_flow_bucket":  bucket,
            "curated_flow_score":   _cf_score(ep),
            "curated_flow_badges":  badges,
            "curated_flow_exact_match_count": _cf_exact_count(ep),
            "curated_flow_is_proxy_only":     _cf_is_proxy(ep),
            "split_context":        sc,
            "median_dollar_volume_pre": dv,
            "high_expansion_risk_day_count_pre": ep.get("high_expansion_risk_day_count_pre"),
            "risk_flags":           risk_flags,
            "trap_notes":           trap_notes,
        })

    traps.sort(key=lambda t: -(t["curated_flow_score"] or 0))
    return traps


# ── Part 4: Baseline vs curated FLOW comparison ───────────────────────────────

def _build_baseline_comparison(episodes: list[dict]) -> dict:
    baseline_stats = _outcome_stats(episodes)
    bucket_stats   = _build_bucket_performance(episodes)

    high_only = [e for e in episodes if _cf_bucket(e) == "CURATED_FLOW_HIGH"]
    high_stats = _outcome_stats(high_only)

    # Separate exact vs proxy within HIGH
    high_exact = [e for e in high_only if _cf_exact_count(e) > 0]
    high_proxy = [e for e in high_only if _cf_is_proxy(e)]

    pw_high    = [e for e in episodes if _pw_label(e) == "PUMP_WATCH_HIGH"]
    pw_high_stats = _outcome_stats(pw_high)

    return {
        "baseline": {
            "description": "All episodes, no FLOW filter",
            **baseline_stats,
        },
        "baseline_plus_curated_flow_badges": {
            "description": "Same candidate set, annotated with Curated FLOW bucket",
            "by_bucket": bucket_stats,
        },
        "curated_flow_rerank_research": {
            "description": (
                "Research-only simulated reranking by CURATED_FLOW_HIGH. "
                "Candidate inclusion unchanged."
            ),
            "curated_flow_high_only":          high_stats,
            "curated_flow_high_exact_only":    _outcome_stats(high_exact),
            "curated_flow_high_proxy_only":    _outcome_stats(high_proxy),
            "pump_watch_high_comparison":      pw_high_stats,
            "cf_high_beats_pw_high_four_x_rate": (
                (high_stats.get("four_x_rate") or 0) >
                (pw_high_stats.get("four_x_rate") or 0)
            ),
            "cf_high_lower_fp_rate": (
                (high_stats.get("false_positive_rate") or 1.0) <
                (pw_high_stats.get("false_positive_rate") or 0.0)
            ),
        },
    }


# ── Warnings ──────────────────────────────────────────────────────────────────

def _build_warnings(
    bucket_perf: dict,
    episodes: list[dict],
    diagnostics: dict,
) -> list[str]:
    warnings: list[str] = []

    high = bucket_perf.get("CURATED_FLOW_HIGH", {})
    h_4x = high.get("four_x_rate") or 0
    h_fp = high.get("false_positive_rate") or 0
    if h_fp >= h_4x and high.get("total", 0) > 0:
        warnings.append(
            f"CURATED_FLOW_HIGH FP rate ({h_fp:.1%}) >= 4x rate ({h_4x:.1%}) — "
            "use with caution; FLOW badge alone is not sufficient."
        )

    # Exact badge count is zero (scoring is all proxy-based)
    eps_with_exact = diagnostics.get("episodes_with_exact_badges", 0)
    total_eps      = len(episodes) or 1
    if eps_with_exact == 0:
        warnings.append(
            "Curated FLOW exact badges are not matching. "
            "Score is proxy-only (dryup/compression/D-confluence context). "
            "This means bar-level flow tags (ADL_ACCUM_3D, BUY_PRESSURE_HIGH, etc.) "
            "are absent from the episode snapshots."
        )
    elif diagnostics.get("proxy_score_only_count", 0) > eps_with_exact:
        proxy_n = diagnostics["proxy_score_only_count"]
        warnings.append(
            f"Curated FLOW score is dominated by proxy/context bonuses: "
            f"{proxy_n} proxy-only vs {eps_with_exact} exact badge episodes. "
            "CURATED_FLOW_HIGH requires exact badge evidence (proxy-only capped at LOW)."
        )

    # Reverse-split dominance in HIGH
    high_eps = [e for e in episodes if _cf_bucket(e) == "CURATED_FLOW_HIGH"]
    if high_eps:
        rs_pct = sum(
            1 for e in high_eps
            if e.get("split_context") in ("RECENT_REVERSE_SPLIT", "OLD_REVERSE_SPLIT")
        ) / len(high_eps)
        if rs_pct > 0.35:
            warnings.append(
                f"CURATED_FLOW_HIGH is {rs_pct:.0%} reverse-split episodes — "
                "consider excluding split_context != NO_SPLIT for cleaner signal."
            )
        ldv_pct = sum(
            1 for e in high_eps
            if 0 < (e.get("median_dollar_volume_pre") or 0) < 50_000
        ) / len(high_eps)
        if ldv_pct > 0.40:
            warnings.append(
                f"CURATED_FLOW_HIGH has {ldv_pct:.0%} low-dollar-volume episodes (<$50k/day)."
            )

    # 4x episodes hiding in IGNORE
    ignore_eps = [e for e in episodes if _cf_bucket(e) == "CURATED_FLOW_IGNORE"]
    if ignore_eps:
        ignore_4x_rate = sum(1 for e in ignore_eps if _is_4x(e)) / len(ignore_eps)
        if ignore_4x_rate > 0.20:
            warnings.append(
                f"CURATED_FLOW_IGNORE still contains {ignore_4x_rate:.0%} 4x episodes — "
                "scoring rules may be missing some true patterns."
            )

    return warnings


# ── Recommendations ───────────────────────────────────────────────────────────

def _build_recommendations(
    episodes: list[dict],
    bucket_perf: dict,
    missed_4x: list[dict],
    fp_traps: list[dict],
    flow_patterns: list[dict],
    diagnostics: dict,
) -> list[str]:
    recs: list[str] = []

    high = bucket_perf.get("CURATED_FLOW_HIGH", {})
    h_4x = high.get("four_x_rate") or 0
    h_fp = high.get("false_positive_rate") or 0
    h_n  = high.get("total") or 0

    pw_high   = [e for e in episodes if _pw_label(e) == "PUMP_WATCH_HIGH"]
    pw_4x_raw = sum(1 for e in pw_high if _is_4x(e))
    pw_4x     = _safe_rate(pw_4x_raw, len(pw_high)) or 0

    if h_n >= 8 and h_4x > pw_4x and h_fp <= 0.30:
        recs.append(
            f"CURATED_FLOW_HIGH 4x rate ({h_4x:.1%}) exceeds PUMP_WATCH_HIGH "
            f"({pw_4x:.1%}) at n={h_n}. Candidate for stable watchlist feature."
        )

    rescue_count = len(missed_4x)
    if rescue_count >= 3:
        recs.append(
            f"{rescue_count} missed 4x episodes rescued by CURATED_FLOW_HIGH/MEDIUM "
            "from PUMP_IGNORE/SPECULATIVE. Warrants analysis for baseline coverage gap."
        )

    trap_count = len(fp_traps)
    if trap_count > rescue_count:
        recs.append(
            f"FP traps ({trap_count}) exceed rescued 4x ({rescue_count}). "
            "Consider adding split_context and dollar-volume gates before widening signal."
        )

    if h_n < 8:
        recs.append(
            f"CURATED_FLOW_HIGH has only {h_n} episodes — insufficient for stable "
            "signal estimation. Extend replay period or universe."
        )

    # ABSORB_PRESSURE badge specific
    from replay.curated_flow_rules import BADGE_DIVERGENCE_ABSORB_PRESSURE
    absorb_n = diagnostics.get("badge_match_counts", {}).get(
        BADGE_DIVERGENCE_ABSORB_PRESSURE, 0
    )
    if absorb_n > 0:
        absorb_eps = [e for e in episodes
                      if BADGE_DIVERGENCE_ABSORB_PRESSURE in _cf_badges(e)]
        a_4x = _safe_rate(sum(1 for e in absorb_eps if _is_4x(e)), len(absorb_eps)) or 0
        recs.append(
            f"PX_FLOW_DIVERGENCE_ABSORB_PRESSURE_1B matched {absorb_n} episodes "
            f"(4x rate {a_4x:.1%}). Derived from run 142: cnt_4x=9, fpr=0.0."
        )

    # Broad divergence badge
    div_eps = [e for e in episodes if BADGE_DIVERGENCE_ACCUM in _cf_badges(e)]
    if div_eps:
        d_4x = _safe_rate(sum(1 for e in div_eps if _is_4x(e)), len(div_eps)) or 0
        recs.append(
            f"PX_FLOW_DIVERGENCE_ACCUM_PRESSURE matched {len(div_eps)} episodes "
            f"(4x rate {d_4x:.1%} vs run-139 14.9%). Monitor for period stability."
        )

    recs.append("RESEARCH ONLY — do not route any of these to Scanner V2 BUY/WATCH.")
    return recs


# ── Summary card ──────────────────────────────────────────────────────────────

def _build_summary(
    episodes: list[dict],
    bucket_perf: dict,
    missed_4x: list[dict],
    fp_traps: list[dict],
    diagnostics: dict,
) -> dict:
    high        = bucket_perf.get("CURATED_FLOW_HIGH", {})
    pw_high_eps = [e for e in episodes if _pw_label(e) == "PUMP_WATCH_HIGH"]
    pw_4x_rate  = _safe_rate(
        sum(1 for e in pw_high_eps if _is_4x(e)), len(pw_high_eps)
    )
    badge_match_count = sum(1 for e in episodes if _cf_badges(e))

    return {
        "episode_count":               len(episodes),
        "badge_match_count":           badge_match_count,
        "exact_badge_match_count":     diagnostics.get("episodes_with_exact_badges", 0),
        "proxy_only_count":            diagnostics.get("episodes_with_proxy_only_score", 0),
        "curated_flow_high_count":     high.get("total"),
        "curated_flow_high_4x_rate":   high.get("four_x_rate"),
        "curated_flow_high_fp_rate":   high.get("false_positive_rate"),
        "pump_watch_high_4x_rate":     pw_4x_rate,
        "missed_4x_rescued_count":     len(missed_4x),
        "false_positive_trap_count":   len(fp_traps),
        "top_exact_badge":             (
            max(
                diagnostics.get("badge_match_counts", {}).items(),
                key=lambda kv: kv[1],
                default=("none", 0),
            )[0]
            if diagnostics.get("badge_match_counts") else None
        ),
        "curated_rules_snapshot":      curated_rules_registry_snapshot(),
    }


# ── Main report builder (Part 9) ──────────────────────────────────────────────

def build_curated_flow_replay_analysis(
    episodes: list[dict],
    flow_patterns: Optional[list[dict]] = None,
    daily_by_episode: Optional[dict] = None,
) -> dict:
    """
    Build the full curated FLOW replay analysis report.

    Parameters
    ----------
    episodes         : episode dicts, ideally already augmented with
                       curated_flow_* fields from the pipeline cache.
                       If not, pass daily_by_episode for bar-level evaluation.
    flow_patterns    : FLOW/COMBINED pattern candidates from build_discovery_export()
    daily_by_episode : {episode_id → [bar_row, ...]} for fresh evaluation

    Returns
    -------
    curated_flow_replay_analysis dict (Part 9 spec).
    """
    if not episodes:
        return {
            "report_type":    "curated_flow_replay_analysis",
            "safety_note":    "RESEARCH ONLY. No BUY promotion. No Scanner V2 change.",
            "episode_count":  0,
            "anti_leakage_note": (
                "Curated FLOW uses only as-of/pre-window fields. "
                "No pump_multiple, group_type, or future returns used in scoring."
            ),
        }

    # Score episodes (preserves existing curated_flow_* fields if cached)
    scored = score_episodes_curated_flow(episodes, daily_by_episode)

    # Detect if regime data is available on episodes
    regime_available = any(e.get("price_bucket") for e in scored)

    diagnostics  = _build_curated_match_diagnostics(scored)
    bucket_perf  = _build_bucket_performance(scored)
    pw_matrix    = _build_pw_cf_matrix(scored)
    badge_matrix = _build_pw_exact_badge_matrix(scored)
    badge_perf   = _build_badge_performance(scored, regime_available=regime_available)
    missed_4x    = _build_missed_4x_rescue(scored)
    fp_traps     = _build_fp_traps(scored)
    baseline_cmp = _build_baseline_comparison(scored)
    warnings     = _build_warnings(bucket_perf, scored, diagnostics)
    recs         = _build_recommendations(
        scored, bucket_perf, missed_4x, fp_traps,
        flow_patterns or [], diagnostics,
    )
    summary      = _build_summary(scored, bucket_perf, missed_4x, fp_traps, diagnostics)

    return {
        "report_type":   "curated_flow_replay_analysis",
        "safety_note":   "RESEARCH ONLY. No BUY promotion. No Scanner V2 change.",
        "anti_leakage_note": (
            "Curated FLOW uses only as-of/pre-window fields. "
            "No pump_multiple, group_type, or future returns used in scoring."
        ),
        "episode_count":                    len(scored),
        "summary":                          summary,
        "curated_match_diagnostics":        diagnostics,
        "bucket_performance":               bucket_perf,
        "pump_watch_x_curated_flow_matrix": pw_matrix,
        "pump_watch_x_exact_badge_matrix":  badge_matrix,
        "badge_performance":                badge_perf,
        "missed_4x_rescue":                 missed_4x,
        "false_positive_traps":             fp_traps,
        "baseline_vs_curated_flow":         baseline_cmp,
        "warnings":                         warnings,
        "recommendations":                  recs,
    }
