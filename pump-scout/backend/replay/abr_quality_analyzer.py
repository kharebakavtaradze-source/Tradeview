"""
ABR Quality Analyzer — Research Only.

Reads ABR/TZ features pre-computed by abr_tz_engine into feature_json,
aggregates per-episode ABR quality statistics, and builds:

  abr_debug             — coverage / signal distribution stats
  abr_quality_analysis  — per-tier performance summary
  watch_rank_v2         — per-episode Watch Rank Score v2 (research-only)
  watch_rank_v2_analysis — dataset-level Watch Rank v2 summary

RESEARCH ONLY — do NOT route to Scanner V2 BUY/WATCH/AVOID.
Anti-leakage: only pre-window feature_json fields are read for scoring.
Outcome fields (pump_multiple, group_type) are only read for analysis/reporting,
never for scoring or ranking.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from typing import Optional

logger = logging.getLogger(__name__)


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


# ── Episode-level ABR feature extraction ─────────────────────────────────────

def _abr_features_from_daily_rows(daily_rows: list[dict]) -> dict:
    """
    Aggregate ABR/TZ features across a pre-window daily row sequence.
    Returns a summary dict for one episode.
    """
    total = len(daily_rows)
    if total == 0:
        return {"total_bars": 0, "abr_coverage": 0.0}

    tz_signal_count   = 0
    abr_a_count       = 0
    abr_b_count       = 0
    abr_bplus_count   = 0
    abr_r_count       = 0
    strong_count      = 0
    good_count        = 0
    average_count     = 0
    reject_count      = 0
    preup_count       = 0
    predn_count       = 0
    z8_count          = 0
    l1_count = l2_count = l3_count = 0
    l4_count = l5_count = l6_count = 0
    quality_scores: list[float] = []
    tz_signals: list[str]       = []

    for row in daily_rows:
        fj = row.get("feature_json") or {}
        if isinstance(fj, str):
            try:
                import json
                fj = json.loads(fj)
            except Exception:
                fj = {}

        sig = fj.get("tz_primary_signal")
        if sig:
            tz_signal_count += 1
            tz_signals.append(sig)

        qs = fj.get("tz_quality_score")
        if qs is not None:
            quality_scores.append(_num(qs))

        sp500_grade = fj.get("tz_quality_tier_sp500")
        if sp500_grade == "STRONG":   strong_count  += 1
        elif sp500_grade == "GOOD":   good_count    += 1
        elif sp500_grade == "AVERAGE": average_count += 1
        elif sp500_grade == "REJECT": reject_count  += 1

        abr_sp = fj.get("abr_sp500")
        if abr_sp == "A":   abr_a_count     += 1
        elif abr_sp == "B": abr_b_count     += 1
        elif abr_sp == "B+": abr_bplus_count += 1
        elif abr_sp == "R": abr_r_count     += 1

        if fj.get("preup_primary"):  preup_count += 1
        if fj.get("predn_primary"):  predn_count += 1
        if fj.get("has_z8"):         z8_count    += 1
        if fj.get("has_l1"):         l1_count    += 1
        if fj.get("has_l2"):         l2_count    += 1
        if fj.get("has_l3"):         l3_count    += 1
        if fj.get("has_l4"):         l4_count    += 1
        if fj.get("has_l5"):         l5_count    += 1
        if fj.get("has_l6"):         l6_count    += 1

    signal_freq = Counter(tz_signals).most_common(5)
    top_signals = [{"signal": s, "count": c} for s, c in signal_freq]

    return {
        "total_bars":         total,
        "tz_signal_bars":     tz_signal_count,
        "abr_coverage":       _pct(tz_signal_count, total),
        "abr_a_bars":         abr_a_count,
        "abr_b_bars":         abr_b_count,
        "abr_bplus_bars":     abr_bplus_count,
        "abr_r_bars":         abr_r_count,
        "strong_bars":        strong_count,
        "good_bars":          good_count,
        "average_bars":       average_count,
        "reject_bars":        reject_count,
        "preup_bars":         preup_count,
        "predn_bars":         predn_count,
        "z8_bars":            z8_count,
        "l1_bars":            l1_count,
        "l2_bars":            l2_count,
        "l3_bars":            l3_count,
        "l4_bars":            l4_count,
        "l5_bars":            l5_count,
        "l6_bars":            l6_count,
        "mean_quality_score": round(sum(quality_scores) / len(quality_scores), 2) if quality_scores else None,
        "top_tz_signals":     top_signals,
    }


# ── Watch Rank Score v2 ───────────────────────────────────────────────────────

def _compute_watch_rank_v2(ep: dict, abr_feats: dict) -> dict:
    """
    Compute Watch Rank Score v2 for one episode.

    Components (research-only, NEVER routed to Scanner V2):
      pump_watch     : pump_watch_score clamped 0-10, scaled to 0-3 pts
      curated_flow   : curated_flow_score 0-5 pts
      abr_quality    : ABR A/B+/B/R counts converted 0-4 pts
      regime         : placeholder (market_regime not yet populated) 0-1 pts
      custom         : PREUP density 0-1 pt
      penalty        : high reject_bars rate → -1 pt

    Total max ≈ 14 pts.
    Buckets: WATCH_RANK_A ≥ 10 / B 7-9 / C 4-6 / AVOID < 4
    """
    components: dict[str, float] = {}
    reasons: list[str] = []
    risk_flags: list[str] = []

    # ── Pump Watch component (0-3 pts) ────────────────────────────────────────
    pw = _num(ep.get("pump_watch_score"))
    pw_pts = min(3.0, pw / 10.0 * 3.0)
    components["pump_watch"] = round(pw_pts, 2)
    if pw_pts >= 2.0:
        reasons.append(f"pump_watch_score={pw:.1f}")

    # ── Curated FLOW component (0-5 pts) ──────────────────────────────────────
    cf = _num(ep.get("curated_flow_score"))
    cf_pts = min(5.0, cf)
    components["curated_flow"] = round(cf_pts, 2)
    if cf_pts >= 2.0:
        reasons.append(f"curated_flow_score={cf:.1f}")

    # ── ABR quality component (0-4 pts) ───────────────────────────────────────
    a_bars    = abr_feats.get("abr_a_bars",    0)
    bplus_bars = abr_feats.get("abr_bplus_bars", 0)
    b_bars    = abr_feats.get("abr_b_bars",    0)
    r_bars    = abr_feats.get("abr_r_bars",    0)
    total_bars = max(1, abr_feats.get("total_bars", 1))

    abr_positive = a_bars * 2 + bplus_bars * 1.5 + b_bars * 1.0
    abr_pts = min(4.0, abr_positive / total_bars * 20.0)
    components["abr_quality"] = round(abr_pts, 2)
    if a_bars > 0:
        reasons.append(f"abr_a_bars={a_bars}")
    elif bplus_bars > 0:
        reasons.append(f"abr_bplus_bars={bplus_bars}")

    reject_rate = r_bars / total_bars
    if reject_rate > 0.4:
        risk_flags.append(f"high_abr_reject_rate={reject_rate:.0%}")

    # ── Regime component (placeholder, 0-1 pts) ───────────────────────────────
    regime_pts = 0.0
    components["regime"] = regime_pts  # populated once market_regime is live

    # ── Custom/PREUP density (0-1 pt) ─────────────────────────────────────────
    preup_bars = abr_feats.get("preup_bars", 0)
    custom_pts = 1.0 if (preup_bars / total_bars >= 0.10) else 0.0
    components["custom"] = custom_pts
    if custom_pts:
        reasons.append(f"preup_density={preup_bars}/{total_bars}")

    # ── Penalty ──────────────────────────────────────────────────────────────
    penalty = 0.0
    if reject_rate > 0.5:
        penalty -= 1.0
        risk_flags.append("majority_reject_bars")
    if _num(ep.get("curated_flow_score")) == 0 and pw < 3:
        penalty -= 0.5
        risk_flags.append("no_flow_low_pw")
    components["penalty"] = penalty

    # ── Total ─────────────────────────────────────────────────────────────────
    total = pw_pts + cf_pts + abr_pts + regime_pts + custom_pts + penalty
    total = round(max(0.0, total), 2)

    if total >= 10:
        bucket = "WATCH_RANK_A"
    elif total >= 7:
        bucket = "WATCH_RANK_B"
    elif total >= 4:
        bucket = "WATCH_RANK_C"
    else:
        bucket = "AVOID"

    return {
        "watch_rank_score_v2":      total,
        "watch_rank_bucket_v2":     bucket,
        "watch_rank_reasons_v2":    reasons,
        "watch_rank_risk_flags_v2": risk_flags,
        "watch_rank_components_v2": components,
    }


# ── Per-episode scoring pass ──────────────────────────────────────────────────

def score_episodes_abr(
    episodes: list[dict],
    daily_by_episode: Optional[dict] = None,
) -> list[dict]:
    """
    Score all episodes with ABR features and Watch Rank v2.

    Mutates episode dicts in-place (adds abr_features, watch_rank_*_v2 keys).
    Returns the same list.
    """
    if not episodes:
        return episodes

    daily_by_episode = daily_by_episode or {}

    for ep in episodes:
        ep_id = ep.get("episode_id") or ep.get("id")
        daily_rows = daily_by_episode.get(ep_id, []) if ep_id is not None else []

        abr_feats = _abr_features_from_daily_rows(daily_rows)
        ep["abr_features"] = abr_feats

        wrank = _compute_watch_rank_v2(ep, abr_feats)
        ep.update(wrank)

    return episodes


# ── ABR debug section ─────────────────────────────────────────────────────────

def _build_abr_debug(episodes: list[dict], daily_by_episode: dict) -> dict:
    total_eps  = len(episodes)
    total_bars = 0
    tz_bars    = 0
    coverage_list: list[float] = []
    strong_eps = good_eps = average_eps = reject_eps = 0
    a_eps = bplus_eps = b_eps = r_eps = 0
    abr_missing = 0

    for ep in episodes:
        ep_id = ep.get("episode_id") or ep.get("id")
        daily_rows = daily_by_episode.get(ep_id, []) if ep_id is not None else []
        af = ep.get("abr_features") or _abr_features_from_daily_rows(daily_rows)

        tb  = af.get("total_bars",     0)
        tzb = af.get("tz_signal_bars", 0)
        total_bars += tb
        tz_bars    += tzb
        if tb == 0:
            abr_missing += 1
        else:
            cov = af.get("abr_coverage") or 0.0
            coverage_list.append(cov)

        # Determine dominant grade (most common non-None grade over bars)
        if af.get("strong_bars", 0):   strong_eps  += 1
        if af.get("good_bars", 0):     good_eps    += 1
        if af.get("average_bars", 0):  average_eps += 1
        if af.get("reject_bars", 0):   reject_eps  += 1

        if af.get("abr_a_bars", 0):    a_eps    += 1
        if af.get("abr_bplus_bars", 0): bplus_eps += 1
        if af.get("abr_b_bars", 0):    b_eps    += 1
        if af.get("abr_r_bars", 0):    r_eps    += 1

    return {
        "total_episodes":          total_eps,
        "total_bars":              total_bars,
        "tz_signal_bars":          tz_bars,
        "abr_coverage_rate":       _pct(tz_bars, total_bars),
        "abr_missing_episodes":    abr_missing,
        "mean_coverage":           round(sum(coverage_list) / len(coverage_list), 4) if coverage_list else None,
        "episodes_with_strong":    strong_eps,
        "episodes_with_good":      good_eps,
        "episodes_with_average":   average_eps,
        "episodes_with_reject":    reject_eps,
        "episodes_with_abr_a":     a_eps,
        "episodes_with_abr_bplus": bplus_eps,
        "episodes_with_abr_b":     b_eps,
        "episodes_with_abr_r":     r_eps,
    }


# ── ABR quality analysis section ──────────────────────────────────────────────

def _build_abr_quality_analysis(episodes: list[dict]) -> dict:
    """
    Group episodes by ABR quality bucket and summarize outcomes.
    Outcome fields (pump_multiple, group_type) are read for reporting ONLY.
    """
    buckets: dict[str, list[dict]] = defaultdict(list)

    for ep in episodes:
        af  = ep.get("abr_features") or {}
        a_b = af.get("abr_a_bars", 0)
        bp  = af.get("abr_bplus_bars", 0)
        b_b = af.get("abr_b_bars", 0)

        if a_b > 0:      key = "has_ABR_A"
        elif bp > 0:     key = "has_ABR_B+"
        elif b_b > 0:    key = "has_ABR_B"
        else:            key = "no_ABR"
        buckets[key].append(ep)

    result: dict[str, dict] = {}
    for key, eps in buckets.items():
        pms = [e["pump_multiple"] for e in eps if e.get("pump_multiple") is not None]
        pws = [_num(e.get("pump_watch_score")) for e in eps if e.get("pump_watch_score") is not None]
        cfs = [_num(e.get("curated_flow_score")) for e in eps if e.get("curated_flow_score") is not None]
        wrs = [_num(e.get("watch_rank_score_v2")) for e in eps]

        group_dist: Counter = Counter(e.get("group_type") or "?" for e in eps)

        result[key] = {
            "episode_count":          len(eps),
            "pump_multiple_median":   _median(pms),
            "pump_watch_score_median": _median(pws),
            "curated_flow_score_median": _median(cfs),
            "watch_rank_v2_median":   _median(wrs),
            "group_type_distribution": dict(group_dist.most_common()),
        }

    return result


# ── Watch Rank v2 analysis section ───────────────────────────────────────────

def _build_watch_rank_v2_analysis(episodes: list[dict]) -> dict:
    """
    Summarize Watch Rank v2 distribution across all episodes.
    """
    bucket_counts: Counter = Counter()
    score_list: list[float] = []
    top_list: list[dict]   = []

    for ep in episodes:
        score = _num(ep.get("watch_rank_score_v2"))
        bucket = ep.get("watch_rank_bucket_v2") or "AVOID"
        bucket_counts[bucket] += 1
        score_list.append(score)

        if bucket in ("WATCH_RANK_A", "WATCH_RANK_B"):
            top_list.append({
                "symbol":               ep.get("symbol") or ep.get("ticker"),
                "episode_id":           ep.get("episode_id") or ep.get("id"),
                "watch_rank_score_v2":  score,
                "watch_rank_bucket_v2": bucket,
                "pump_watch_score":     ep.get("pump_watch_score"),
                "curated_flow_score":   ep.get("curated_flow_score"),
                "watch_rank_reasons_v2": ep.get("watch_rank_reasons_v2"),
                "pump_multiple":        ep.get("pump_multiple"),
                "group_type":           ep.get("group_type"),
            })

    top_list.sort(key=lambda x: -(x["watch_rank_score_v2"] or 0))

    return {
        "bucket_distribution":    dict(bucket_counts.most_common()),
        "total_episodes":         len(episodes),
        "median_watch_rank_score_v2": _median(score_list),
        "mean_watch_rank_score_v2": round(sum(score_list) / len(score_list), 2) if score_list else None,
        "top_episodes":           top_list[:50],
        "notes": (
            "Watch Rank v2 is RESEARCH ONLY. "
            "Do NOT route to Scanner V2 BUY/WATCH/AVOID. "
            "Regime component is placeholder (0 pts) until market_regime is live."
        ),
    }


# ── Main entry point ──────────────────────────────────────────────────────────

def build_abr_quality_replay_analysis(
    episodes: list[dict],
    daily_by_episode: Optional[dict] = None,
) -> dict:
    """
    Top-level function: score all episodes and build all ABR export sections.

    Returns dict with keys:
      abr_debug, abr_quality_analysis, watch_rank_v2_analysis
    """
    if not episodes:
        return {
            "abr_debug": {"total_episodes": 0},
            "abr_quality_analysis": {},
            "watch_rank_v2_analysis": {"total_episodes": 0, "bucket_distribution": {}},
        }

    daily_by_episode = daily_by_episode or {}

    scored = score_episodes_abr(episodes, daily_by_episode=daily_by_episode)

    abr_debug = _build_abr_debug(scored, daily_by_episode)
    abr_quality = _build_abr_quality_analysis(scored)
    wrv2_analysis = _build_watch_rank_v2_analysis(scored)

    return {
        "abr_debug":            abr_debug,
        "abr_quality_analysis": abr_quality,
        "watch_rank_v2_analysis": wrv2_analysis,
        "anti_leakage": (
            "ABR quality score uses only feature_json OHLCV/indicator fields. "
            "No pump_multiple, group_type, or forward returns used in scoring. "
            "pump_multiple/group_type appear only in analysis/reporting sections."
        ),
    }
