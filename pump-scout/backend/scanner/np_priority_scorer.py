"""
NP Priority Scorer
==================
Ranks New Pump candidates by priority_score (0–100).

Rules:
  - priority_score is RANKING / enrichment ONLY.
    It NEVER changes decision, routing, or BUY/WATCH/AVOID counts.
  - HIGH expansion risk cannot produce PRIORITY_HIGH.
  - AVOID / IMPULSE_RISK candidates are capped at PRIORITY_LOW (max 54).
  - Missing context is neutral — never fatal.

Output fields per row:
  priority_score   float 0–100
  priority_label   PRIORITY_HIGH | PRIORITY_MEDIUM | PRIORITY_LOW | PRIORITY_RISKY
  priority_flags   list[str]  — active positive / negative modifiers
  priority_reason  str        — one-line human-readable summary
"""
import logging

logger = logging.getLogger(__name__)

# ── D/WLNBB confluence groups ────────────────────────────────────────────────
_D_HIGH   = frozenset({"D6_BEUP", "D6_BEUP_SAME"})
_D_MED_BP = frozenset({"D4_BEUP", "D4_BEUP_SAME"})
_D_MED_L  = frozenset({
    "D4_L34", "D4_L34_SAME",
    "D3_L34", "D3_L34_SAME",
    "L34_THEN_D4_3B", "L34_THEN_D3_3B",
})
_D_WEAK   = frozenset({"D3_BEUP", "D3_BEUP_SAME"})
_D_POOR   = frozenset({"D6_L34", "D6_L34_SAME"})
_D_SOLO   = frozenset({
    "D9", "D11",
    "SECONDARY_D_CONFLUENCE",
    "SECONDARY_D_BEUP_SAME", "SECONDARY_D_L34_SAME", "SECONDARY_D_L43_SAME",
})

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
    """Best available D/WLNBB label: v1 (clean labels) → simplified v2 → NONE."""
    v1 = row.get("d_confluence_type") or "NONE"
    if v1 and v1 != "NONE":
        return v1
    v2 = row.get("d_confluence_type_v2") or "NONE"
    if v2 and v2 != "NONE":
        return _DCONF_V2_SIMPLE.get(v2, v2)
    return "NONE"


def compute_priority(row: dict) -> dict:
    """
    Compute priority ranking for one enriched NP candidate row.

    Returns dict with priority_score, priority_label, priority_flags, priority_reason.
    Never raises — returns PRIORITY_RISKY with scorer_error flag on any exception.
    """
    try:
        return _inner(row)
    except Exception as exc:
        logger.debug(f"[PriorityScorer] {row.get('symbol')}: {exc}")
        return {
            "priority_score":  0.0,
            "priority_label":  "PRIORITY_RISKY",
            "priority_flags":  ["scorer_error"],
            "priority_reason": f"scorer_error: {exc}",
        }


def _inner(row: dict) -> dict:
    decision = row.get("decision") or "AVOID"
    ss       = float(row.get("structure_score") or 0)
    phase    = row.get("structure_phase") or "TRUE_NONE"
    seq      = row.get("new_pump_sequence_label") or "NONE"
    ce_state = row.get("compression_expansion_state") or "NONE"
    exp_risk = row.get("expansion_timing_risk") or "LOW"
    d_conf   = _resolve_dconf(row)

    sc  = row.get("sector_context")    or {}
    mc  = row.get("macro_context")     or {}
    nhc = row.get("news_hype_context") or {}
    syc = row.get("sympathy_context")  or {}
    lc  = row.get("legacy_context")    or {}

    score: float = ss
    flags: list[str] = []

    # ── Structure phase ───────────────────────────────────────────────────────
    if phase in ("CONFIRMED_STRUCTURE", "TRIGGERED_STRUCTURE"):
        score += 10
        flags.append("strong_phase")
    elif phase == "EARLY_STRUCTURE":
        score += 3

    # ── Compression / expansion state ─────────────────────────────────────────
    if ce_state == "ACCUMULATION_READY":
        score += 8
        flags.append("accumulation_ready")
    elif ce_state == "OVERHEATED_EXPANSION":
        score -= 10
        flags.append("overheated")

    # ── D/WLNBB confluence ────────────────────────────────────────────────────
    if d_conf in _D_HIGH:
        score += 8
        flags.append("d6_beup")
    elif d_conf in _D_MED_BP:
        score += 5
        flags.append("d4_beup")
    elif d_conf in _D_MED_L:
        score += 5
        flags.append("d_l34")
    elif d_conf in _D_WEAK:
        score -= 8
        flags.append("d3_beup_weak")
    elif d_conf in _D_POOR:
        score -= 8
        flags.append("d6_l34_poor")
    elif d_conf in _D_SOLO:
        score -= 5
        flags.append("d_standalone")

    # ── Sequence penalty ──────────────────────────────────────────────────────
    if seq == "SETUP_ONLY_L34":
        score -= 8
        flags.append("setup_only_l34")

    # ── Sector / subsector ────────────────────────────────────────────────────
    ss_str  = sc.get("sector_strength")    or "SECTOR_UNKNOWN"
    sub_str = sc.get("subsector_strength") or "SUBSECTOR_UNKNOWN"

    if ss_str in ("SECTOR_LEADING", "SECTOR_IMPROVING"):
        score += 3
        flags.append("sector_tailwind")
    elif ss_str == "SECTOR_LAGGING":
        score -= 5
        flags.append("sector_lagging")

    if sub_str in ("SUBSECTOR_LEADING", "SUBSECTOR_IMPROVING"):
        score += 3
        flags.append("subsector_tailwind")

    # ── Macro / regime ────────────────────────────────────────────────────────
    if mc.get("macro_tailwind"):
        score += 3
        flags.append("macro_tailwind")
    elif mc.get("macro_headwind"):
        score -= 5
        flags.append("macro_headwind")

    if (mc.get("risk_mode") or "") in ("RISK_OFF", "FEAR"):
        score -= 5
        flags.append("risk_off_regime")

    # ── Sympathy ──────────────────────────────────────────────────────────────
    sym_score = syc.get("sympathy_score") or 0
    sym_align = syc.get("candidate_alignment") or ""
    if sym_score > 0 and sym_align == "LAG":
        score += 3
        flags.append("sympathy_aligned")
    elif sym_score > 10:
        score += 2
        flags.append("sympathy_signal")

    # ── News / hype ───────────────────────────────────────────────────────────
    hype_tier  = nhc.get("hype_tier")  or "COLD"
    hype_state = nhc.get("hype_state") or "COLD"
    risk_fls   = nhc.get("catalyst_risk_flags") or []

    if hype_state == "SILENT_ACCUMULATION":
        score += 3
        flags.append("silent_accumulation")
    elif hype_tier in ("HOT", "VIRAL") and hype_state == "ACTIVE_HYPE":
        score += 3
        flags.append("hype_active")

    if "PEAK_FADING" in risk_fls or hype_state == "PEAK_FADING":
        score -= 5
        flags.append("hype_late")

    # ── Legacy stealth / silent (present only when legacy_context is attached) ─
    lc_tags = lc.get("legacy_tags") or []
    if "SILENT" in lc_tags or "STEALTH" in lc_tags:
        score += 3
        flags.append("stealth_silent")

    # ── Hard penalty: HIGH expansion risk ─────────────────────────────────────
    if exp_risk == "HIGH":
        score -= 20
        flags.append("expansion_risk_high")

    # ── AVOID / IMPULSE_RISK hard cap: max PRIORITY_LOW = 54 ─────────────────
    if decision in ("AVOID", "IMPULSE_RISK"):
        score = min(score, 54.0)

    score = round(max(0.0, min(100.0, score)), 1)

    # ── Priority label ────────────────────────────────────────────────────────
    if score >= 75:
        label = "PRIORITY_HIGH"
    elif score >= 55:
        label = "PRIORITY_MEDIUM"
    elif score >= 35:
        label = "PRIORITY_LOW"
    else:
        label = "PRIORITY_RISKY"

    # Belt-and-suspenders: enforce hard rules on label
    if exp_risk == "HIGH" and label == "PRIORITY_HIGH":
        label = "PRIORITY_MEDIUM"
    if decision in ("AVOID", "IMPULSE_RISK") and label in ("PRIORITY_HIGH", "PRIORITY_MEDIUM"):
        label = "PRIORITY_LOW"

    reason = (
        f"base={int(ss)} decision={decision} phase={phase} dconf={d_conf} "
        f"flags=[{'+'.join(flags) if flags else 'none'}] final={score}"
    )

    return {
        "priority_score":  score,
        "priority_label":  label,
        "priority_flags":  flags,
        "priority_reason": reason,
    }
