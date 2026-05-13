"""
Scanner v2 — New Pump as structural core.
==========================================
Status: ACTIVE DECISION LAYER (on top of new_pump_engine.py)

Architecture:
  new_pump_engine.py  → np_decision (eligibility gate — NEVER overridden)
  np_priority_scorer  → priority_score / priority_label (ranking layer)
  scanner_v2.py       → scanner_v2_decision (final classification label)

CRITICAL RULES — read before modifying:
  1. np_decision is the eligibility gate.  No BUY without BUY_CANDIDATE.
  2. No WATCH_HIGH without np_decision == WATCH.
  3. HYPE / SYMPATHY / sector / macro CANNOT create BUY alone.
  4. HIGH expansion_timing_risk CANNOT produce BUY_CANDIDATE_HIGH.
  5. AVOID cannot be upgraded to BUY/WATCH_HIGH/WATCH_MEDIUM.
  8. OVERHEATED_EXPANSION hard-blocks ALL BUY (→ AVOID_RISK) and ALL WATCH (→ AVOID_LOTTERY).
     R35 data: -4.28% 5d 36.4% WR across all phases/sequences.
  9. expansion_timing_risk=HIGH hard-blocks WATCH_HIGH and WATCH_MEDIUM (→ AVOID_LOTTERY).
     R35 data: -3.61% 5d 39.0% WR.
     Exception 1: AVOID_DEAD + strong D confluence (D4/D6 BEUP or D4/D3 L34) + non-impulse
     phase → WATCH_LOW (data-driven: these combos avg +2–4% 5d with 60-73% win rate).
     Exception 2: AVOID_RISK (soft risk only — no expansion_risk_high/overheated) + strong
     D confluence + non-impulse phase → WATCH_LOW (rescues 16.4% routing-miss leakage;
     run_id=30: 128/781 AVOID_RISK stocks moved ≥10% 5d with avg +44.18%).
  6. Missing context is neutral — never fatal.
  7. D/WLNBB confluence can improve classification only within allowed np_decision boundaries.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── v2 decision labels ────────────────────────────────────────────────────────
V2_LABELS = frozenset({
    "BUY_CANDIDATE_HIGH",
    "BUY_CANDIDATE_NORMAL",
    "WATCH_HIGH",
    "WATCH_MEDIUM",
    "WATCH_LOW",
    "AVOID_RISK",
    "AVOID_LOTTERY",
    "AVOID_DEAD",
})

# ── D confluence labels that allow AVOID_DEAD → WATCH_LOW upgrade ────────────
# Data from run_id=30 (2343 candidates, 85 days):
#   D4_BEUP avg +4.31% 5d 60% win; D6_BEUP avg +3.8% 63% win
#   D4_L34  avg +2.1% 65% win;     D3_L34  avg +2.9% 73% win
#   L34_THEN_D4_3B: run_id=32 avg +5.13% 5d, alpha +4.97%, FP 8.5%
#   D4_THEN_BEUP_5B: run_id=30 avg +4.31% 5d — R35 promoted to upgrade set
_AVOID_UPGRADE_DCONF = frozenset({
    "D4_BEUP", "D6_BEUP", "D4_L34", "D3_L34",
    "L34_THEN_D4_3B", "D4_THEN_BEUP_5B",
})

# ── Negative priority flags that signal meaningful risk ───────────────────────
_HIGH_RISK_FLAGS = frozenset({
    "expansion_risk_high",
    "overheated",
    "hype_late",
    "macro_headwind",
    "risk_off_regime",
    "sector_lagging",
    "d3_beup_weak",
    "d6_l34_poor",
})

# Flags that block D-confluence rescue from AVOID_RISK → WATCH_LOW.
# expansion_risk_high / overheated = price already extended; D-conf can't fix that.
# Soft flags (macro_headwind, sector_lagging, hype_late, …) can be overridden by
# strong structural alignment (D4/D6 BEUP or D4/D3 L34).
_HARD_RISK_FLAGS = frozenset({"expansion_risk_high", "overheated"})

# ── Suggested actions per v2 label ───────────────────────────────────────────
_ACTIONS: dict[str, str] = {
    "BUY_CANDIDATE_HIGH":   "Actionable candidate; verify live liquidity/news risk.",
    "BUY_CANDIDATE_NORMAL": "Valid structure; monitor entry conditions.",
    "WATCH_HIGH":           "High-priority watch; wait for trigger/confirmation.",
    "WATCH_MEDIUM":         "Watch only; needs stronger confirmation.",
    "WATCH_LOW":            "Low-priority watch.",
    "AVOID_RISK":           "Avoid due to risk/structure.",
    "AVOID_LOTTERY":        "Volatile/lottery profile; not swing-safe.",
    "AVOID_DEAD":           "Ignore unless new structure appears.",
}

# ── v2 decision sort order ────────────────────────────────────────────────────
_ORDER: dict[str, int] = {
    "BUY_CANDIDATE_HIGH":   0,
    "BUY_CANDIDATE_NORMAL": 1,
    "WATCH_HIGH":           2,
    "WATCH_MEDIUM":         3,
    "WATCH_LOW":            4,
    "AVOID_RISK":           5,
    "AVOID_LOTTERY":        6,
    "AVOID_DEAD":           7,
}

# ── D/WLNBB v2 → simplified label (mirrors np_priority_scorer) ───────────────
_DCONF_V2_SIMPLE: dict[str, str] = {
    "D6_BEUP_SAME":          "D6_BEUP",
    "D4_BEUP_SAME":          "D4_BEUP",
    "D3_BEUP_SAME":          "D3_BEUP",
    "D4_L34_SAME":           "D4_L34",
    "D3_L34_SAME":           "D3_L34",
    "D6_L34_SAME":           "D6_L34",
    "D4_L43_SAME":           "D4_L43",
    "D3_L43_SAME":           "D3_L43",
    "D6_L43_SAME":           "D6_L43",
    "SECONDARY_D_BEUP_SAME": "SECONDARY_D_CONFLUENCE",
    "SECONDARY_D_L34_SAME":  "SECONDARY_D_CONFLUENCE",
    "SECONDARY_D_L43_SAME":  "SECONDARY_D_CONFLUENCE",
}


def _resolve_dconf(row: dict) -> str:
    """Best available D/WLNBB label: v1 (clean) → simplified v2 → NONE."""
    v1 = row.get("d_confluence_type") or "NONE"
    if v1 and v1 != "NONE":
        return v1
    v2 = row.get("d_confluence_type_v2") or "NONE"
    if v2 and v2 != "NONE":
        return _DCONF_V2_SIMPLE.get(v2, v2)
    return "NONE"


def _dconf_family(d_conf: str) -> Optional[str]:
    if d_conf == "NONE":
        return None
    if "BEUP" in d_conf:
        return "BEUP"
    if "L34" in d_conf:
        return "L34"
    if "L43" in d_conf:
        return "L43"
    if "SECONDARY" in d_conf:
        return "SECONDARY"
    return "OTHER"


def _dconf_timing(row: dict) -> Optional[str]:
    v2 = row.get("d_confluence_type_v2") or "NONE"
    if v2 == "NONE":
        return None
    return "SAME_BAR" if v2.endswith("_SAME") else "LAGGED"


def _ss_bucket(ss: Optional[float]) -> str:
    if ss is None:
        return "UNKNOWN"
    if ss >= 66:
        return "66_100"
    if ss >= 46:
        return "46_65"
    if ss >= 26:
        return "26_45"
    return "0_25"


# ── Core decision mapper ──────────────────────────────────────────────────────

def _map_v2_decision(
    np_decision: str,
    priority_label: str,
    priority_score: float,
    priority_flags: list[str],
    exp_risk: str,
    d_conf: str = "NONE",
    structure_phase: str = "NONE",
    ce_state: str = "NONE",
) -> tuple[str, str, list[str]]:
    """
    Map np_decision + priority context → (v2_decision, reason, v2_flags).

    np_decision is the strict gate:
      BUY_CANDIDATE → BUY tier
      WATCH         → WATCH tier
      AVOID / IMPULSE_RISK → AVOID tier (no upgrade possible)

    BUY_CANDIDATE_HIGH requires priority_score >= 85 (not just PRIORITY_HIGH >= 80).
    This ensures BUY_NORMAL is populated and avoids all-HIGH inflation.
    """
    pf_set   = set(priority_flags or [])
    has_risk = bool(pf_set & _HIGH_RISK_FLAGS)

    # ── BUY tier ──────────────────────────────────────────────────────────────
    if np_decision == "BUY_CANDIDATE":
        # R35: OVERHEATED_EXPANSION -4.28% 5d 36.4% WR — hard block, no BUY of any kind
        if "overheated" in pf_set:
            return (
                "AVOID_RISK",
                f"BUY_CANDIDATE blocked: overheated_expansion — R35 -4.28% 5d",
                ["np_buy", "overheated", "hard_block"],
            )
        if (priority_label == "PRIORITY_HIGH"
                and priority_score >= 85
                and exp_risk != "HIGH"):
            return (
                "BUY_CANDIDATE_HIGH",
                f"BUY_CANDIDATE + PRIORITY_HIGH score={priority_score:.0f} (exp_risk={exp_risk})",
                ["np_buy", "priority_high"],
            )
        flags = ["np_buy"]
        parts = [f"BUY_CANDIDATE priority={priority_label} score={priority_score:.0f}"]
        if exp_risk == "HIGH":
            flags.append("expansion_risk_high")
            parts.append("HIGH expansion risk demoted to NORMAL")
        return ("BUY_CANDIDATE_NORMAL", " ".join(parts), flags)

    # ── WATCH tier ────────────────────────────────────────────────────────────
    if np_decision == "WATCH":
        # R35: OVERHEATED -4.28% 5d / exp_risk=HIGH -3.61% 5d — lottery profile at any priority
        if "overheated" in pf_set:
            return (
                "AVOID_LOTTERY",
                f"WATCH blocked: overheated_expansion — R35 -4.28% 5d",
                ["np_watch", "overheated", "lottery_profile"],
            )
        if exp_risk == "HIGH":
            return (
                "AVOID_LOTTERY",
                f"WATCH priority={priority_label} + exp_risk=HIGH — lottery profile",
                ["np_watch", "expansion_risk_high", "lottery_profile"],
            )
        if priority_label == "PRIORITY_HIGH":
            return ("WATCH_HIGH", "WATCH + PRIORITY_HIGH", ["np_watch", "priority_high"])
        if priority_label == "PRIORITY_MEDIUM":
            return ("WATCH_MEDIUM", "WATCH + PRIORITY_MEDIUM", ["np_watch", "priority_medium"])
        return ("WATCH_LOW", f"WATCH priority={priority_label}", ["np_watch"])

    # ── AVOID tier (AVOID + IMPULSE_RISK) ────────────────────────────────────
    # IMPULSE_RISK = volatile move, not a swing setup — lottery profile
    if np_decision == "IMPULSE_RISK":
        return (
            "AVOID_LOTTERY",
            "IMPULSE_RISK — volatile/lottery profile, not swing-safe",
            ["np_impulse", "lottery_profile"],
        )

    # AVOID: bucket by risk level
    if has_risk:
        top = [f for f in (priority_flags or []) if f in _HIGH_RISK_FLAGS][:3]
        # D-confluence rescue: strong structural alignment overrides soft risk flags.
        # Hard risks (expansion_risk_high, overheated) block this — price already extended.
        hard_risk = bool(pf_set & _HARD_RISK_FLAGS)
        if (not hard_risk
                and d_conf in _AVOID_UPGRADE_DCONF
                and structure_phase not in {"IMPULSE_ONLY", "BROKEN_STRUCTURE"}
                and exp_risk != "HIGH"):
            return (
                "WATCH_LOW",
                f"AVOID+risk({'+'.join(top) or 'soft'}) rescued by {d_conf} → WATCH_LOW",
                ["np_avoid", "has_risk", "d_conf_upgrade"] + top,
            )
        return (
            "AVOID_RISK",
            f"AVOID with risk signals: {'+'.join(top) if top else 'risk_flags'}",
            ["np_avoid", "has_risk"] + top,
        )

    # AVOID_DEAD upgrade: strong D confluence + non-impulse phase → WATCH_LOW
    # Excluded: IMPULSE_ONLY, BROKEN_STRUCTURE (data shows catastrophic returns)
    _bad_phases = {"IMPULSE_ONLY", "BROKEN_STRUCTURE", "DEGRADED", "TRUE_NONE"}
    if (d_conf in _AVOID_UPGRADE_DCONF
            and structure_phase not in _bad_phases
            and exp_risk != "HIGH"):
        return (
            "WATCH_LOW",
            f"AVOID (no risk) + {d_conf} + {structure_phase} → WATCH_LOW",
            ["np_avoid", "d_conf_upgrade"],
        )

    # R35: ACCUMULATION_READY +1.15% 5d 58.6% WR — rescue even without D confluence
    if (ce_state == "ACCUMULATION_READY"
            and structure_phase not in _bad_phases
            and exp_risk != "HIGH"
            and not (pf_set & _HARD_RISK_FLAGS)):
        return (
            "WATCH_LOW",
            f"AVOID (no risk) + ACCUMULATION_READY + {structure_phase} → WATCH_LOW",
            ["np_avoid", "accumulation_ready_rescue"],
        )

    return (
        "AVOID_DEAD",
        "AVOID — no meaningful structure or opportunity signal",
        ["np_avoid"],
    )


def _v2_score(priority_score: float, v2_decision: str) -> float:
    """scanner_v2_score: priority_score with small final adjustment. Clamped 0–100."""
    adj = 0.0
    if v2_decision == "BUY_CANDIDATE_HIGH":
        adj = +5.0
    elif v2_decision == "WATCH_HIGH":
        adj = +3.0
    elif v2_decision in ("AVOID_RISK", "AVOID_DEAD"):
        adj = -10.0
    return round(max(0.0, min(100.0, priority_score + adj)), 1)


# ── Row builder ───────────────────────────────────────────────────────────────

def build_v2_row(row: dict, rank: int = 0) -> dict:
    """
    Build one Scanner v2 output row from an enriched NP row.
    Never raises — returns a minimal AVOID_DEAD row on any error.
    """
    try:
        return _build_inner(row, rank)
    except Exception as exc:
        sym = row.get("symbol") or "?"
        logger.warning(f"[ScannerV2] build_v2_row failed {sym}: {exc}")
        return {
            "symbol":              sym,
            "company_name":        None,
            "price":               row.get("price"),
            "volume":              row.get("volume_today"),
            "sector":              row.get("sector"),
            "subsector":           None,
            "new_pump":            {},
            "priority":            {},
            "confirmation":        {},
            "context":             {},
            "scanner_v2_decision": "AVOID_DEAD",
            "scanner_v2_score":    0.0,
            "scanner_v2_rank":     rank,
            "scanner_v2_reason":   f"build_error: {exc}",
            "scanner_v2_flags":    ["build_error"],
            "suggested_action":    _ACTIONS["AVOID_DEAD"],
        }


def _build_inner(row: dict, rank: int) -> dict:
    sym            = (row.get("symbol") or "").upper()
    np_decision    = row.get("decision") or "AVOID"
    p_label        = row.get("priority_label") or "PRIORITY_LOW"
    p_flags        = row.get("priority_flags") or []
    p_score        = float(row.get("priority_score") or 0.0)
    p_reason       = row.get("priority_reason")
    exp_risk       = row.get("expansion_timing_risk") or "LOW"
    ss             = row.get("structure_score")
    sc             = row.get("sector_context") or {}

    d_conf         = _resolve_dconf(row)
    d_family       = _dconf_family(d_conf)
    d_timing       = _dconf_timing(row)
    structure_phase = row.get("structure_phase") or "NONE"
    ce_state       = row.get("compression_expansion_state") or "NONE"

    v2_decision, v2_reason, v2_flags = _map_v2_decision(
        np_decision, p_label, p_score, p_flags, exp_risk, d_conf, structure_phase, ce_state
    )
    v2_score = _v2_score(p_score, v2_decision)

    window_expl = None
    if d_conf != "NONE":
        timing_str = {"SAME_BAR": "same-bar", "LAGGED": "lagged"}.get(d_timing, "")
        window_expl = (
            f"{d_conf} confluence"
            + (f" ({timing_str})" if timing_str else "")
            + (f" — family: {d_family}" if d_family else "")
        )

    return {
        # ── Identity ──────────────────────────────────────────────────────────
        "symbol":       sym,
        "company_name": row.get("company_name"),
        "price":        row.get("price"),
        "volume":       row.get("volume_today"),
        # Prefer normalized GICS name from sector_context over raw SectorCache value.
        # row["sector"] is already promoted to GICS by enrich_np_candidates after
        # sector_context is built; sc.get("sector") is the same but is the safe fallback.
        "sector":       sc.get("sector") or row.get("sector"),
        "subsector":    sc.get("subsector"),

        # ── New Pump structural block ─────────────────────────────────────────
        "new_pump": {
            "np_decision":               np_decision,
            "decision_reason":           row.get("decision_reason"),
            "decision_flags":            row.get("decision_flags") or [],
            "structure_phase":           row.get("structure_phase"),
            "structure_score":           ss,
            "structure_score_bucket":    _ss_bucket(ss),
            "sequence":                  row.get("new_pump_sequence_label"),
            "expansion_timing_risk":     exp_risk,
            "compression_expansion_state": row.get("compression_expansion_state"),
        },

        # ── Priority ranking block ────────────────────────────────────────────
        "priority": {
            "priority_score":  p_score,
            "priority_label":  p_label,
            "priority_flags":  p_flags,
            "priority_reason": p_reason,
        },

        # ── D/WLNBB confirmation block ────────────────────────────────────────
        "confirmation": {
            "d_confluence_type":    row.get("d_confluence_type"),
            "d_confluence_type_v2": row.get("d_confluence_type_v2"),
            "active_d_signals":     row.get("active_d_signals") or [],
            "active_wlnbb_signals": row.get("active_wlnbb_signals") or [],
            "d_confluence_family":  d_family,
            "d_confluence_timing":  d_timing,
            "window_explanation":   window_expl,
        },

        # ── Context blocks (pass-through) ─────────────────────────────────────
        "context": {
            "sector_context":    row.get("sector_context"),
            "macro_context":     row.get("macro_context"),
            "news_hype_context": row.get("news_hype_context"),
            "sympathy_context":  row.get("sympathy_context"),
            "legacy_context":    row.get("legacy_context"),
        },

        # ── Final Scanner v2 fields ───────────────────────────────────────────
        "scanner_v2_decision": v2_decision,
        "scanner_v2_score":    v2_score,
        "scanner_v2_rank":     rank,
        "scanner_v2_reason":   v2_reason,
        "scanner_v2_flags":    v2_flags,
        "suggested_action":    _ACTIONS.get(v2_decision, ""),
    }


# ── Batch builder ─────────────────────────────────────────────────────────────

def build_v2_results(np_results: list[dict]) -> list[dict]:
    """
    Transform enriched NP rows into Scanner v2 rows.
    Sorts: scanner_v2_score desc → structure_score desc → symbol asc.
    Assigns scanner_v2_rank after sorting.
    """
    rows: list[tuple[dict, float]] = []
    for row in (np_results or []):
        try:
            v2 = build_v2_row(row, rank=0)
            rows.append((v2, float(row.get("structure_score") or 0)))
        except Exception as exc:
            logger.debug(f"[ScannerV2] skipped {row.get('symbol')}: {exc}")

    rows.sort(key=lambda x: (
        -x[0]["scanner_v2_score"],
        -x[1],
        x[0]["symbol"],
    ))

    result: list[dict] = []
    for rank, (v2_row, _) in enumerate(rows, start=1):
        v2_row["scanner_v2_rank"] = rank
        result.append(v2_row)

    return result


def decision_counts(v2_rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in v2_rows:
        d = r.get("scanner_v2_decision") or "UNKNOWN"
        counts[d] = counts.get(d, 0) + 1
    return counts


# Known normalized GICS sector names (used for coverage check)
_GICS_SECTORS: frozenset[str] = frozenset({
    "Information Technology", "Health Care", "Financials",
    "Consumer Discretionary", "Consumer Staples", "Energy",
    "Industrials", "Materials", "Real Estate",
    "Communication Services", "Utilities",
})


def sector_coverage_stats(v2_rows: list[dict]) -> dict:
    """
    Compute sector/subsector coverage over a batch of v2 rows.

    Returns
    -------
    {
      sector_known_pct          : float  — rows with a normalized GICS sector (%)
      subsector_known_pct       : float  — rows with a non-None subsector (%)
      raw_industry_as_sector_count : int — rows where raw_sector_input was resolved
      total                     : int
    }
    """
    n = len(v2_rows)
    if n == 0:
        return {
            "sector_known_pct":              0.0,
            "subsector_known_pct":           0.0,
            "raw_industry_as_sector_count":  0,
            "total":                         0,
        }

    sector_known   = 0
    subsector_known = 0
    raw_resolved   = 0

    for r in v2_rows:
        sector = r.get("sector") or ""
        if sector in _GICS_SECTORS:
            sector_known += 1

        if r.get("subsector"):
            subsector_known += 1

        sc = (r.get("context") or {}).get("sector_context") or {}
        if sc.get("raw_sector_input"):
            raw_resolved += 1

    return {
        "sector_known_pct":              round(sector_known   / n * 100, 1),
        "subsector_known_pct":           round(subsector_known / n * 100, 1),
        "raw_industry_as_sector_count":  raw_resolved,
        "total":                         n,
    }


def np_decision_counts(v2_rows: list[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in v2_rows:
        d = (r.get("new_pump") or {}).get("np_decision") or "UNKNOWN"
        counts[d] = counts.get(d, 0) + 1
    return counts
