"""
Pattern similarity: match current demand scanner candidates against
historical pump episodes using normalized feature vectors.
"""
import math
from typing import Optional


# Feature names for logging/debugging
FEATURE_NAMES = [
    "vol_anomaly",      # vol_ratio normalized to 0-1 (clip at 5)
    "compression",      # dryup_streak normalized (clip at 15)
    "ats_strength",     # ats conditions met / 5
    "ribbon_ema",       # near_ema50 or had_ribbon
    "readiness",        # readiness_score / 10
    "confluence",       # confluence_signals count / 3
]


def _norm(val, lo, hi):
    """Clamp and normalize val to [0, 1]."""
    if val is None:
        return 0.0
    return max(0.0, min(1.0, (val - lo) / (hi - lo))) if hi > lo else 0.0


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na  = math.sqrt(sum(x * x for x in a))
    nb  = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def candidate_vector(r: dict) -> list[float]:
    """Build feature vector from a demand scanner result dict."""
    ats_map = {"ATS_PRIME": 5, "ATS_SETUP": 4, "ATS_WATCH": 3}
    ats_met  = len(r.get("ats_conditions_met") or [])
    ats_sig  = ats_map.get(r.get("ats_signal", ""), 0)
    ats_val  = max(ats_met, ats_sig) / 5.0

    conf_cnt = len(r.get("confluence_signals") or [])

    return [
        _norm(r.get("dc_vol_ratio")  or 1.0, 1.0, 5.0),
        _norm(r.get("dc_dryup_streak") or 0,   1.0, 15.0),
        ats_val,
        1.0 if r.get("dc_near_ema50") else 0.0,
        _norm(r.get("readiness_score") or 0,  0.0, 10.0),
        _norm(conf_cnt,                        0.0, 3.0),
    ]


def episode_vector(ep: dict) -> list[float]:
    """Build feature vector from a pump episode dict (from _pump_episode_to_dict)."""
    summary = ep.get("summary") or {}
    return [
        _norm(ep.get("max_volume_anomaly") or 1.0, 1.0, 5.0),
        # Use compression proxy: inverse of days_to_peak (short peak = fast pump = coiled)
        _norm(max(0, 20 - (ep.get("days_to_peak") or 20)), 0.0, 15.0),
        1.0 if ep.get("had_ignition") else 0.0,
        1.0 if ep.get("had_ribbon")   else 0.0,
        # was_flagged → scanner found it → likely had readiness
        0.7 if ep.get("was_flagged_by_scanner") else 0.3,
        # summary may store confluence count from when study was run
        _norm(summary.get("confluence_count") or 0, 0.0, 3.0),
    ]


def find_similar(
    candidate: dict,
    episodes: list[dict],
    top_n: int = 5,
    min_multiple: float = 1.5,
) -> list[dict]:
    """
    Return top_n most similar historical pump episodes to `candidate`.
    Only considers episodes with pump_multiple >= min_multiple.
    """
    vec = candidate_vector(candidate)
    scored = []
    for ep in episodes:
        if (ep.get("pump_multiple") or 0) < min_multiple:
            continue
        ev = episode_vector(ep)
        sim = _cosine(vec, ev)
        scored.append({
            "similarity":       round(sim, 3),
            "episode_id":       ep.get("id"),
            "run_id":           ep.get("run_id"),
            "symbol":           ep.get("symbol"),
            "pump_start_date":  ep.get("pump_start_date"),
            "pump_peak_date":   ep.get("pump_peak_date"),
            "pump_multiple":    ep.get("pump_multiple"),
            "pump_return_pct":  ep.get("pump_return_pct"),
            "days_to_peak":     ep.get("days_to_peak"),
            "pump_type":        ep.get("pump_type"),
            "sector":           ep.get("sector"),
            "had_ignition":     ep.get("had_ignition"),
            "had_ribbon":       ep.get("had_ribbon"),
            "max_volume_anomaly": ep.get("max_volume_anomaly"),
        })
    scored.sort(key=lambda x: -x["similarity"])
    return scored[:top_n]
