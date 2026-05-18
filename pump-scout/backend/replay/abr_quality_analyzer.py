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

_T_HIGH = frozenset({"T4", "T6", "T3", "T11", "T12"})        # score=3
_T_MED  = frozenset({"T1G", "T2G", "T1", "T9", "T5"})       # score=2
_Z_HIGH = frozenset({"Z4", "Z6", "Z3", "Z5"})                # score=3
_Z_MED  = frozenset({"Z1G", "Z2G", "Z1", "Z9", "Z11"})      # score=2
_ALL_T  = _T_HIGH | _T_MED | frozenset({"T2", "T10"})
_ALL_Z  = _Z_HIGH | _Z_MED | frozenset({"Z2", "Z10", "Z8", "Z7", "Z12"})

_PREUP_TYPES = ("P66", "P55", "P89", "P3", "P2", "P50")
_PREDN_TYPES = ("P66", "P55", "P89", "P3", "P2", "P50")


def _abr_features_from_daily_rows(daily_rows: list[dict]) -> dict:
    """
    Aggregate ABR/TZ features across a pre-window daily row sequence.
    Returns a summary dict for one episode.

    Covers individual T/Z signal counts, PREUP type breakdown,
    L1-L6, ABR grades, quality tier, D-confluence flags from feature_json,
    and dominant-signal identifiers for episode-level grouping.
    """
    total = len(daily_rows)
    if total == 0:
        return {"total_bars": 0, "abr_coverage": 0.0}

    tz_signal_count = 0
    abr_a_count = abr_b_count = abr_bplus_count = abr_r_count = 0
    strong_count = good_count = average_count = reject_count = 0
    preup_count = predn_count = 0
    l1_count = l2_count = l3_count = 0
    l4_count = l5_count = l6_count = 0
    t_high_count = t_med_count = 0        # T tier-3 / tier-2
    z_high_count = z_med_count = 0        # Z tier-3 / tier-2
    tz_high_count = 0                     # any tier-3 (T or Z)
    quality_scores: list[float] = []
    tz_signals: list[str] = []
    preup_types: list[str] = []

    # Individual T/Z signal bar counters
    t_counts: Counter = Counter()
    z_counts: Counter = Counter()
    preup_type_counts: Counter = Counter()

    # D-confluence flags (may be present from upstream feature_json)
    d6_beup_count = d4_beup_count = d4_l34_count = d3_beup_count = 0
    any_d_core_count = 0

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
            if sig in _ALL_T:
                t_counts[sig] += 1
                if sig in _T_HIGH:
                    t_high_count += 1
                    tz_high_count += 1
                elif sig in _T_MED:
                    t_med_count += 1
            elif sig in _ALL_Z:
                z_counts[sig] += 1
                if sig in _Z_HIGH:
                    z_high_count += 1
                    tz_high_count += 1
                elif sig in _Z_MED:
                    z_med_count += 1

        qs = fj.get("tz_quality_score")
        if qs is not None:
            quality_scores.append(_num(qs))

        sp500_grade = fj.get("tz_quality_tier_sp500")
        if sp500_grade == "STRONG":    strong_count  += 1
        elif sp500_grade == "GOOD":    good_count    += 1
        elif sp500_grade == "AVERAGE": average_count += 1
        elif sp500_grade == "REJECT":  reject_count  += 1

        abr_sp = fj.get("abr_sp500")
        if abr_sp == "A":    abr_a_count     += 1
        elif abr_sp == "B":  abr_b_count     += 1
        elif abr_sp == "B+": abr_bplus_count += 1
        elif abr_sp == "R":  abr_r_count     += 1

        pu = fj.get("preup_primary")
        if pu:
            preup_count += 1
            preup_types.append(pu)
            preup_type_counts[pu] += 1
        if fj.get("predn_primary"):  predn_count  += 1

        if fj.get("has_l1"): l1_count += 1
        if fj.get("has_l2"): l2_count += 1
        if fj.get("has_l3"): l3_count += 1
        if fj.get("has_l4"): l4_count += 1
        if fj.get("has_l5"): l5_count += 1
        if fj.get("has_l6"): l6_count += 1

        # D-confluence flags (written by upstream pipeline into feature_json)
        d6 = fj.get("has_d6_beup") or fj.get("has_d6_beup_pre") or False
        d4 = fj.get("has_d4_beup") or fj.get("has_d4_beup_pre") or False
        d4l = fj.get("has_d4_l34") or fj.get("had_d4_l34_pre")  or False
        d3 = fj.get("has_d3_beup") or fj.get("has_d3_beup_pre") or False
        if d6:  d6_beup_count  += 1
        if d4:  d4_beup_count  += 1
        if d4l: d4_l34_count   += 1
        if d3:  d3_beup_count  += 1
        if d6 or d4 or d4l:  any_d_core_count += 1

    signal_freq = Counter(tz_signals).most_common(5)
    top_signals = [{"signal": s, "count": c} for s, c in signal_freq]

    # Dominant TZ signal = most frequent tz_primary_signal this episode
    dominant_tz = signal_freq[0][0] if signal_freq else None
    # Side: T vs Z
    dominant_tz_side = None
    if dominant_tz:
        dominant_tz_side = "T" if dominant_tz in _ALL_T else "Z"

    # Dominant PREUP type = most frequent preup_primary this episode
    preup_freq = preup_type_counts.most_common(1)
    dominant_preup = preup_freq[0][0] if preup_freq else None

    return {
        "total_bars":         total,
        "tz_signal_bars":     tz_signal_count,
        "abr_coverage":       _pct(tz_signal_count, total),
        # ABR grades
        "abr_a_bars":         abr_a_count,
        "abr_b_bars":         abr_b_count,
        "abr_bplus_bars":     abr_bplus_count,
        "abr_r_bars":         abr_r_count,
        # Quality tier
        "strong_bars":        strong_count,
        "good_bars":          good_count,
        "average_bars":       average_count,
        "reject_bars":        reject_count,
        # T/Z tier buckets
        "t_high_bars":        t_high_count,
        "t_med_bars":         t_med_count,
        "z_high_bars":        z_high_count,
        "z_med_bars":         z_med_count,
        "tz_high_bars":       tz_high_count,
        # Individual T signal counts (12 signals)
        "t4_bars":   t_counts.get("T4",  0), "t6_bars":  t_counts.get("T6",  0),
        "t3_bars":   t_counts.get("T3",  0), "t11_bars": t_counts.get("T11", 0),
        "t12_bars":  t_counts.get("T12", 0),
        "t1g_bars":  t_counts.get("T1G", 0), "t2g_bars": t_counts.get("T2G", 0),
        "t1_bars":   t_counts.get("T1",  0), "t9_bars":  t_counts.get("T9",  0),
        "t5_bars":   t_counts.get("T5",  0),
        "t2_bars":   t_counts.get("T2",  0), "t10_bars": t_counts.get("T10", 0),
        # Individual Z signal counts (14 signals)
        "z4_bars":   z_counts.get("Z4",  0), "z6_bars":  z_counts.get("Z6",  0),
        "z3_bars":   z_counts.get("Z3",  0), "z5_bars":  z_counts.get("Z5",  0),
        "z1g_bars":  z_counts.get("Z1G", 0), "z2g_bars": z_counts.get("Z2G", 0),
        "z1_bars":   z_counts.get("Z1",  0), "z9_bars":  z_counts.get("Z9",  0),
        "z11_bars":  z_counts.get("Z11", 0),
        "z2_bars":   z_counts.get("Z2",  0), "z10_bars": z_counts.get("Z10", 0),
        "z7_bars":   z_counts.get("Z7",  0), "z8_bars":  z_counts.get("Z8",  0),
        "z12_bars":  z_counts.get("Z12", 0),
        # PREUP / PREDN
        "preup_bars":   preup_count,
        "predn_bars":   predn_count,
        "preup66_bars": preup_type_counts.get("P66", 0),
        "preup55_bars": preup_type_counts.get("P55", 0),
        "preup89_bars": preup_type_counts.get("P89", 0),
        "preup3_bars":  preup_type_counts.get("P3",  0),
        "preup2_bars":  preup_type_counts.get("P2",  0),
        "preup50_bars": preup_type_counts.get("P50", 0),
        # L signals (L1-L6)
        "l1_bars":  l1_count, "l2_bars": l2_count,
        "l3_bars":  l3_count, "l4_bars": l4_count,
        "l5_bars":  l5_count, "l6_bars": l6_count,
        # D-confluence (from upstream feature_json)
        "d6_beup_bars":    d6_beup_count,
        "d4_beup_bars":    d4_beup_count,
        "d4_l34_bars":     d4_l34_count,
        "d3_beup_bars":    d3_beup_count,
        "any_d_core_bars": any_d_core_count,
        # Derived / dominant
        "mean_quality_score": round(sum(quality_scores) / len(quality_scores), 2) if quality_scores else None,
        "top_tz_signals":     top_signals,
        "dominant_tz_signal": dominant_tz,
        "dominant_tz_side":   dominant_tz_side,
        "dominant_preup_type": dominant_preup,
    }


# ── Shared performance summary helper ────────────────────────────────────────

def _perf_summary(eps: list[dict]) -> dict:
    """
    Shared performance stats for a bucket of episodes.
    pump_multiple / group_type are outcome fields — used for REPORTING only,
    never for scoring. Anti-leakage contract satisfied.
    """
    pms = [e["pump_multiple"] for e in eps if e.get("pump_multiple") is not None]
    gt_dist: Counter = Counter(e.get("group_type") or "?" for e in eps)
    n4x = gt_dist.get("4x_pump", 0)
    n = len(eps)
    return {
        "episode_count":          n,
        "pump_multiple_median":   _median(pms),
        "pump_multiple_mean":     round(sum(pms) / len(pms), 2) if pms else None,
        "4x_pump_rate":           _pct(n4x, n),
        "group_type_distribution": dict(gt_dist.most_common()),
    }


# ── Signal frequency table ────────────────────────────────────────────────────

def _build_tz_signal_frequency(episodes: list[dict]) -> dict:
    """
    Aggregate per-signal firing counts across all episodes.
    Produces a frequency table: how many bars / how many episodes have each signal.
    Standalone stats — no outcome fields used.
    """
    bar_counts:     Counter = Counter()
    episode_counts: Counter = Counter()

    # Map signal name → abr_features key
    _sig_key = {
        "T4":"t4_bars","T6":"t6_bars","T3":"t3_bars","T11":"t11_bars","T12":"t12_bars",
        "T1G":"t1g_bars","T2G":"t2g_bars","T1":"t1_bars","T9":"t9_bars",
        "T5":"t5_bars","T2":"t2_bars","T10":"t10_bars",
        "Z4":"z4_bars","Z6":"z6_bars","Z3":"z3_bars","Z5":"z5_bars",
        "Z1G":"z1g_bars","Z2G":"z2g_bars","Z1":"z1_bars","Z9":"z9_bars","Z11":"z11_bars",
        "Z2":"z2_bars","Z10":"z10_bars","Z7":"z7_bars","Z8":"z8_bars","Z12":"z12_bars",
    }

    for ep in episodes:
        af   = ep.get("abr_features") or {}
        seen: set = set()
        for sig, key in _sig_key.items():
            n = af.get(key, 0)
            if n:
                bar_counts[sig] += n
                seen.add(sig)
        for s in seen:
            episode_counts[s] += 1

    total_eps = len(episodes)
    rows = []
    for sig in sorted(bar_counts, key=lambda s: -bar_counts[s]):
        rows.append({
            "signal":        sig,
            "tier":          3 if sig in (_T_HIGH | _Z_HIGH) else 2 if sig in (_T_MED | _Z_MED) else 1,
            "side":          "T" if sig in _ALL_T else "Z",
            "total_bars":    bar_counts[sig],
            "episode_count": episode_counts[sig],
            "episode_pct":   _pct(episode_counts[sig], total_eps),
        })
    return {"signals": rows, "total_episodes": total_eps}


# ── Per-TZ-signal performance ─────────────────────────────────────────────────

def _build_perf_by_tz_signal(episodes: list[dict]) -> list[dict]:
    """
    Group episodes by dominant TZ signal (most frequent signal in pre-window).
    Reports pump outcome per signal type.
    """
    buckets: dict = defaultdict(list)
    for ep in episodes:
        af  = ep.get("abr_features") or {}
        sig = af.get("dominant_tz_signal") or "NO_SIGNAL"
        buckets[sig].append(ep)

    rows = []
    for sig, eps in sorted(buckets.items(), key=lambda x: -len(x[1])):
        af0 = eps[0].get("abr_features") or {}
        rows.append({
            "signal": sig,
            "tier":   3 if sig in (_T_HIGH | _Z_HIGH) else 2 if sig in (_T_MED | _Z_MED) else 1 if sig not in ("NO_SIGNAL",) else 0,
            "side":   "T" if sig in _ALL_T else "Z" if sig in _ALL_Z else None,
            **_perf_summary(eps),
        })
    return rows


# ── Per-PREUP-type performance ────────────────────────────────────────────────

_PREUP_ORDER = ["P66", "P55", "P89", "P3", "P2", "P50", "NO_PREUP"]

def _build_perf_by_preup_type(episodes: list[dict]) -> list[dict]:
    """Group episodes by dominant PREUP type (highest-priority PREUP in pre-window)."""
    buckets: dict = defaultdict(list)
    for ep in episodes:
        af  = ep.get("abr_features") or {}
        pu  = af.get("dominant_preup_type") or "NO_PREUP"
        buckets[pu].append(ep)

    rows = []
    for pu in _PREUP_ORDER:
        if pu not in buckets:
            continue
        rows.append({"preup_type": pu, **_perf_summary(buckets[pu])})
    for pu, eps in buckets.items():
        if pu not in _PREUP_ORDER:
            rows.append({"preup_type": pu, **_perf_summary(eps)})
    return rows


# ── Per-L-signal performance ──────────────────────────────────────────────────

def _build_perf_by_l_signal(episodes: list[dict]) -> list[dict]:
    """
    Group episodes by which L signals fired in their pre-window.
    L5 (bullish absorption) and L1 are the most meaningful.
    """
    l_keys = {
        "L1": "l1_bars", "L2": "l2_bars", "L3": "l3_bars",
        "L4": "l4_bars", "L5": "l5_bars", "L6": "l6_bars",
    }
    buckets: dict = {k: [] for k in list(l_keys) + ["NO_L"]}

    for ep in episodes:
        af = ep.get("abr_features") or {}
        fired = [lbl for lbl, key in l_keys.items() if af.get(key, 0) > 0]
        if not fired:
            buckets["NO_L"].append(ep)
        else:
            # Episode can appear in multiple L buckets (one per fired signal)
            for lbl in fired:
                buckets[lbl].append(ep)

    rows = []
    for lbl in list(l_keys) + ["NO_L"]:
        eps = buckets[lbl]
        if eps:
            rows.append({"l_signal": lbl, **_perf_summary(eps)})
    return rows


# ── TZ × PREUP combination performance ───────────────────────────────────────

def _build_tz_x_preup(episodes: list[dict]) -> list[dict]:
    """
    4-way cross: has_any_TZ × has_any_PREUP.
    Identifies whether TZ+PREUP confluence outperforms either alone.
    """
    buckets: dict = defaultdict(list)
    for ep in episodes:
        af     = ep.get("abr_features") or {}
        has_tz = af.get("tz_signal_bars", 0) > 0
        has_pu = af.get("preup_bars",     0) > 0
        key = ("TZ+PREUP" if has_tz and has_pu else
               "TZ_only"  if has_tz            else
               "PREUP_only" if has_pu          else "NEITHER")
        buckets[key].append(ep)

    order = ["TZ+PREUP", "TZ_only", "PREUP_only", "NEITHER"]
    rows = []
    for k in order:
        if k in buckets:
            rows.append({"bucket": k, **_perf_summary(buckets[k])})
    return rows


def _build_tz_high_x_preup(episodes: list[dict]) -> list[dict]:
    """
    Same cross-tab but restricted to HIGH-SCORE TZ signals (tier-3: T4/T6/T3/T11/T12/Z4/Z6/Z3/Z5).
    """
    buckets: dict = defaultdict(list)
    for ep in episodes:
        af      = ep.get("abr_features") or {}
        has_htz = af.get("tz_high_bars", 0) > 0
        has_pu  = af.get("preup_bars",   0) > 0
        key = ("HIGH_TZ+PREUP" if has_htz and has_pu else
               "HIGH_TZ_only"  if has_htz            else
               "PREUP_only"    if has_pu             else "NEITHER")
        buckets[key].append(ep)

    order = ["HIGH_TZ+PREUP", "HIGH_TZ_only", "PREUP_only", "NEITHER"]
    rows = []
    for k in order:
        if k in buckets:
            rows.append({"bucket": k, **_perf_summary(buckets[k])})
    return rows


# ── ABR grade × PREUP combo ───────────────────────────────────────────────────

def _build_abr_x_preup(episodes: list[dict]) -> list[dict]:
    """
    Cross ABR grade (A / B+ / B / no_ABR) with PREUP presence.
    Shows whether PREUP adds value on top of each ABR grade.
    """
    buckets: dict = defaultdict(list)
    for ep in episodes:
        af  = ep.get("abr_features") or {}
        a   = af.get("abr_a_bars",    0)
        bp  = af.get("abr_bplus_bars",0)
        b   = af.get("abr_b_bars",    0)
        pu  = af.get("preup_bars",    0) > 0
        abr = ("A" if a > 0 else "B+" if bp > 0 else "B" if b > 0 else "no_ABR")
        key = f"{abr}+PREUP" if pu else abr
        buckets[key].append(ep)

    order = [
        "A+PREUP", "A", "B++PREUP", "B+",
        "B+PREUP", "B", "no_ABR+PREUP", "no_ABR",
    ]
    rows = []
    for k in order:
        if k in buckets:
            rows.append({"bucket": k, **_perf_summary(buckets[k])})
    for k, eps in buckets.items():
        if k not in order:
            rows.append({"bucket": k, **_perf_summary(eps)})
    return rows


# ── ABR grade × L-signal combo ────────────────────────────────────────────────

def _build_abr_x_l(episodes: list[dict]) -> list[dict]:
    """
    Cross ABR grade with L-signal presence (especially L5 = bullish absorption).
    """
    buckets: dict = defaultdict(list)
    for ep in episodes:
        af  = ep.get("abr_features") or {}
        a   = af.get("abr_a_bars",    0)
        bp  = af.get("abr_bplus_bars",0)
        b   = af.get("abr_b_bars",    0)
        l5  = af.get("l5_bars", 0) > 0
        l1  = af.get("l1_bars", 0) > 0
        abr = ("A" if a > 0 else "B+" if bp > 0 else "B" if b > 0 else "no_ABR")
        l_tag = "+L5" if l5 else "+L1" if l1 else ""
        key = f"{abr}{l_tag}" if l_tag else abr
        buckets[key].append(ep)

    rows = []
    for k, eps in sorted(buckets.items(), key=lambda x: -len(x[1])):
        rows.append({"bucket": k, **_perf_summary(eps)})
    return rows


# ── D-confluence × ABR/PREUP cross-analysis ──────────────────────────────────

def _d_strength(af: dict) -> str:
    """Classify D-confluence strength from pre-window bar counts."""
    if af.get("d6_beup_bars", 0) > 0:    return "D6_BEUP"
    if af.get("d4_l34_bars",  0) > 0:    return "D4_L34"
    if af.get("d4_beup_bars", 0) > 0:    return "D4_BEUP"
    if af.get("d3_beup_bars", 0) > 0:    return "D3_BEUP"
    if af.get("any_d_core_bars", 0) > 0: return "D_OTHER"
    return "NO_D"

_D_ORDER = ["D6_BEUP", "D4_L34", "D4_BEUP", "D3_BEUP", "D_OTHER", "NO_D"]

def _build_d_x_abr(episodes: list[dict]) -> list[dict]:
    """
    D-confluence strength × ABR grade.
    The 'combination with replay' cross-analysis:
    shows whether TZ/ABR quality adds alpha within each D-type.
    """
    buckets: dict = defaultdict(list)
    for ep in episodes:
        af  = ep.get("abr_features") or {}
        d   = _d_strength(af)
        a   = af.get("abr_a_bars",    0)
        bp  = af.get("abr_bplus_bars",0)
        b   = af.get("abr_b_bars",    0)
        abr = ("A" if a > 0 else "B+" if bp > 0 else "B" if b > 0 else "no_ABR")
        buckets[f"{d}|{abr}"].append(ep)

    rows = []
    for d in _D_ORDER:
        for abr in ("A", "B+", "B", "no_ABR"):
            key = f"{d}|{abr}"
            if key in buckets:
                rows.append({"bucket": key, "d_type": d, "abr_grade": abr, **_perf_summary(buckets[key])})
    return rows


def _build_d_x_preup(episodes: list[dict]) -> list[dict]:
    """
    D-confluence × PREUP presence.
    Did PREUP occur on the same bars as D-confluence?
    """
    buckets: dict = defaultdict(list)
    for ep in episodes:
        af = ep.get("abr_features") or {}
        d  = _d_strength(af)
        pu = "PREUP" if af.get("preup_bars", 0) > 0 else "NO_PREUP"
        buckets[f"{d}|{pu}"].append(ep)

    rows = []
    for d in _D_ORDER:
        for pu in ("PREUP", "NO_PREUP"):
            key = f"{d}|{pu}"
            if key in buckets:
                rows.append({"bucket": key, "d_type": d, "preup": pu, **_perf_summary(buckets[key])})
    return rows


def _build_d_x_tz_high(episodes: list[dict]) -> list[dict]:
    """
    D-confluence × high-score TZ presence.
    Core combination: D-type from scanner + TZ tier-3 signal from Pine Script.
    """
    buckets: dict = defaultdict(list)
    for ep in episodes:
        af    = ep.get("abr_features") or {}
        d     = _d_strength(af)
        htz   = "HIGH_TZ" if af.get("tz_high_bars", 0) > 0 else "NO_HIGH_TZ"
        buckets[f"{d}|{htz}"].append(ep)

    rows = []
    for d in _D_ORDER:
        for htz in ("HIGH_TZ", "NO_HIGH_TZ"):
            key = f"{d}|{htz}"
            if key in buckets:
                rows.append({"bucket": key, "d_type": d, "tz_high": htz, **_perf_summary(buckets[key])})
    return rows


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
      abr_debug               — coverage / signal distribution stats
      abr_quality_analysis    — performance by ABR grade (A/B+/B/no_ABR)
      watch_rank_v2_analysis  — Watch Rank v2 bucket distribution

      # ── Standalone TZ/PREUP/L signal stats ───────────────────────────────────
      tz_signal_frequency          — per-signal bar + episode frequency table
      performance_by_tz_signal     — pump outcomes grouped by dominant TZ signal
      performance_by_preup_type    — pump outcomes grouped by dominant PREUP type
      performance_by_l_signal      — pump outcomes by L signal (L1-L6)

      # ── TZ combination stats ─────────────────────────────────────────────────
      performance_by_tz_x_preup       — TZ presence × PREUP presence (4-way)
      performance_by_tz_high_x_preup  — same but tier-3 TZ signals only
      performance_by_abr_x_preup      — ABR grade × PREUP (shows PREUP alpha per grade)
      performance_by_abr_x_l          — ABR grade × L5/L1 signal

      # ── Combination with D-confluence signals (cross-system) ─────────────────
      performance_by_d_x_abr          — D-type × ABR grade (D from scanner, ABR from TZ)
      performance_by_d_x_preup        — D-type × PREUP presence
      performance_by_d_x_tz_high      — D-type × high-score TZ (tier-3 only)
    """
    if not episodes:
        return {
            "abr_debug": {"total_episodes": 0},
            "abr_quality_analysis": {},
            "watch_rank_v2_analysis": {"total_episodes": 0, "bucket_distribution": {}},
        }

    daily_by_episode = daily_by_episode or {}

    scored = score_episodes_abr(episodes, daily_by_episode=daily_by_episode)

    abr_debug     = _build_abr_debug(scored, daily_by_episode)
    abr_quality   = _build_abr_quality_analysis(scored)
    wrv2_analysis = _build_watch_rank_v2_analysis(scored)

    # ── Standalone signal stats ───────────────────────────────────────────────
    tz_freq         = _build_tz_signal_frequency(scored)
    perf_tz_sig     = _build_perf_by_tz_signal(scored)
    perf_preup_type = _build_perf_by_preup_type(scored)
    perf_l_signal   = _build_perf_by_l_signal(scored)

    # ── Combination tables ────────────────────────────────────────────────────
    perf_tz_x_preup      = _build_tz_x_preup(scored)
    perf_tz_high_x_preup = _build_tz_high_x_preup(scored)
    perf_abr_x_preup     = _build_abr_x_preup(scored)
    perf_abr_x_l         = _build_abr_x_l(scored)

    # ── D-confluence cross (combination with replay D-signals) ────────────────
    perf_d_x_abr    = _build_d_x_abr(scored)
    perf_d_x_preup  = _build_d_x_preup(scored)
    perf_d_x_tz_h   = _build_d_x_tz_high(scored)

    return {
        "abr_debug":                         abr_debug,
        "abr_quality_analysis":              abr_quality,
        "watch_rank_v2_analysis":            wrv2_analysis,
        # standalone
        "tz_signal_frequency":               tz_freq,
        "performance_by_tz_signal":          perf_tz_sig,
        "performance_by_preup_type":         perf_preup_type,
        "performance_by_l_signal":           perf_l_signal,
        # combos
        "performance_by_tz_x_preup":         perf_tz_x_preup,
        "performance_by_tz_high_x_preup":    perf_tz_high_x_preup,
        "performance_by_abr_x_preup":        perf_abr_x_preup,
        "performance_by_abr_x_l":            perf_abr_x_l,
        # cross-system (D-confluence × TZ/PREUP)
        "performance_by_d_x_abr":            perf_d_x_abr,
        "performance_by_d_x_preup":          perf_d_x_preup,
        "performance_by_d_x_tz_high":        perf_d_x_tz_h,
        "anti_leakage": (
            "ABR quality score uses only feature_json OHLCV/indicator fields. "
            "No pump_multiple, group_type, or forward returns used in scoring. "
            "pump_multiple/group_type appear only in analysis/reporting sections."
        ),
    }
