"""
Replay Recalculation Service
=============================
Safe, partial refresh of an existing replay run WITHOUT a full rescan.

What this module can do:
  • Rebuild the research bundle from existing candidates + outcomes
    (no candidate edits). Useful when bundle/bucketing logic changes.
  • Recompute the *decision layer* output for existing candidates using
    current `_decide()` logic. All inputs to _decide are already stored
    on the replay candidate (columns + snapshot.new_pump), so this is
    safe and honest.

What this module cannot do (requires full replay):
  • Re-run state / base_quality / sustain / fake_trigger / compression-
    expansion / impulse engines — these need raw daily candles which are
    not persisted on replay candidate rows.
  • Re-run candidate generation, universe selection, or the volume-gate
    pre-candidate filter.
  • Regenerate raw L34 / FRI34 / G4 / B2 detections.
  • Recompute missed-movers detection.

Design rules:
  • Idempotent. Running twice in a row produces the same result.
  • Never creates a new replay run.
  • Never inserts, deletes, or duplicates candidates / outcomes.
  • Never touches live scan tables.
  • Gracefully skips candidates whose stored inputs are insufficient.
"""

from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)


# Fields the decision-layer recalc actually updates on each candidate row
RECALCULATED_FIELDS = [
    "np_decision",
    "np_decision_reason",
]

# Fields the user might expect to be recomputed but which require full replay
# because their inputs (raw candles) are not stored on replay candidate rows.
SKIPPED_FIELDS_NEED_FULL_REPLAY = [
    "np_state",
    "np_engine_path",
    "np_base_quality_score",
    "np_sustain_proxy_score",
    "np_sustain_profile",
    "np_fake_trigger_risk",
    "quality_flags",
    "np_compression_expansion_state",
    "np_compression_expansion_score",
    "np_compression_expansion_label",
    "np_expansion_timing_risk",
    "expansion_quality_flags",
]

REQUIRES_FULL_REPLAY_FOR = [
    "candidate generation / universe selection",
    "volume-gate pre-candidate filtering",
    "raw L34 / FRI34 / G4 / B2 detection",
    "state / engine-path classification",
    "base-quality / sustain / fake-trigger computation",
    "post-compression expansion engine outputs",
    "impulse engine score / label",
    "missed-movers detection",
]


def _gather_decision_inputs(candidate: dict) -> Optional[dict]:
    """
    Pull the inputs `_decide()` needs from a stored candidate row + snapshot.
    Returns None if the candidate is too old/incomplete to safely recompute.
    """
    snap_np = (candidate.get("snapshot") or {}).get("new_pump") or {}

    state        = candidate.get("np_state")        or snap_np.get("state")
    engine_path  = candidate.get("np_engine_path")  or snap_np.get("engine_path") or "structure"
    seq_lbl      = candidate.get("new_pump_sequence_label") or snap_np.get("new_pump_sequence_label")
    bq_score     = candidate.get("np_base_quality_score")
    if bq_score is None:
        bq_score = snap_np.get("base_quality_score")
    sustain_profile = candidate.get("np_sustain_profile") or snap_np.get("sustain_profile") or "LOW"
    ftr          = candidate.get("np_fake_trigger_risk") or snap_np.get("fake_trigger_risk") or "LOW"
    missing_piece = snap_np.get("missing_piece")
    ce_state     = candidate.get("np_compression_expansion_state") or snap_np.get("compression_expansion_state") or "NONE"
    ce_score     = candidate.get("np_compression_expansion_score")
    if ce_score is None:
        ce_score = snap_np.get("compression_expansion_score") or 0
    ce_risk      = candidate.get("np_expansion_timing_risk") or snap_np.get("expansion_timing_risk") or "LOW"
    impulse_label = snap_np.get("impulse_label")
    impulse_score = snap_np.get("impulse_score") or 0
    np_label      = candidate.get("new_pump_label") or snap_np.get("new_pump_label")
    age_l34       = candidate.get("np_age_l34")   or snap_np.get("age_l34")
    age_fri34     = candidate.get("np_age_fri34") or snap_np.get("age_fri34")

    # State is the single hard prerequisite — without it the decision layer
    # cannot classify.  Older runs that predate the state classifier are
    # skipped safely.
    if not state:
        return None

    return {
        "state":           state,
        "engine_path":     engine_path,
        "seq_lbl":         seq_lbl,
        "bq_score":        int(bq_score) if bq_score is not None else 0,
        "sustain_profile": sustain_profile,
        "ftr":             ftr,
        "missing_piece":   missing_piece,
        "ce_state":        ce_state,
        "ce_score":        int(ce_score) if ce_score is not None else 0,
        "ce_risk":         ce_risk,
        "impulse_label":   impulse_label,
        "impulse_score":   impulse_score,
        "np_label":        np_label,
        "age_l34":         age_l34,
        "age_fri34":       age_fri34,
    }


async def recalculate_decision_layer(run_id: int) -> dict:
    """
    Re-run `_decide()` for every candidate in a replay run using the current
    engine logic, and write np_decision / np_decision_reason back to the DB.
    Does NOT touch upstream engine fields or create any new rows.
    """
    from database import get_replay_candidates, update_replay_candidate_decision
    from scanner.new_pump_engine import _decide

    candidates = await get_replay_candidates(run_id, limit=10000)

    updated = 0
    skipped_insufficient = 0
    for c in candidates:
        inputs = _gather_decision_inputs(c)
        if inputs is None:
            skipped_insufficient += 1
            continue
        try:
            decision, reason, _flags = _decide(**inputs)
        except Exception as exc:
            logger.debug(f"[RECALC] candidate {c.get('id')} decide failed: {exc}")
            skipped_insufficient += 1
            continue

        ok = await update_replay_candidate_decision(c["id"], decision, reason)
        if ok:
            updated += 1

    return {
        "candidate_count_total":  len(candidates),
        "updated_candidate_count": updated,
        "skipped_insufficient":   skipped_insufficient,
    }


async def recalculate_priority_and_v2(run_id: int) -> dict:
    """
    Backfill priority_* and scanner_v2_* fields on every candidate of a run
    by re-running the live enrichment pipeline (sector/macro/hype/sympathy +
    priority + Scanner v2) using the data already stored on each candidate
    row + snapshot.

    Safe and idempotent.  Inputs (np_decision, structure_phase, structure_score,
    expansion_timing_risk, d_confluence_*) are already persisted by the replay
    engine, so this needs no raw-candle access.

    Useful for backfilling existing pre-Task-9 replay runs without rescanning.
    """
    from database import get_replay_candidates, update_replay_candidate_v2
    from scanner.np_context_enricher import enrich_np_candidates
    from scanner.scanner_v2 import build_v2_row

    candidates = await get_replay_candidates(run_id, limit=10000)
    if not candidates:
        return {
            "candidate_count_total":   0,
            "updated_candidate_count": 0,
            "skipped_insufficient":    0,
        }

    # Build np_rows from stored candidate rows. Fields come from columns +
    # snapshot.new_pump (mirrors replay_engine._enrich_replay_candidates).
    np_rows: list[dict] = []
    for c in candidates:
        snap = c.get("snapshot") or {}
        snap_np = snap.get("new_pump") or {}
        np_rows.append({
            "symbol":                      c.get("symbol"),
            "sector":                      c.get("sector"),
            "industry":                    snap.get("industry"),
            "price":                       c.get("price"),
            "volume_today":                snap.get("volume"),
            "decision":                    c.get("np_decision") or snap_np.get("decision"),
            "decision_reason":             c.get("np_decision_reason") or snap_np.get("decision_reason"),
            "decision_flags":              snap_np.get("decision_flags") or [],
            "structure_phase":             snap_np.get("structure_phase"),
            "structure_score":             snap_np.get("structure_score"),
            "expansion_timing_risk":       c.get("np_expansion_timing_risk") or snap_np.get("expansion_timing_risk"),
            "compression_expansion_state": c.get("np_compression_expansion_state") or snap_np.get("compression_expansion_state"),
            "new_pump_sequence_label":     c.get("new_pump_sequence_label") or snap_np.get("new_pump_sequence_label"),
            "accumulation_ready":          snap_np.get("accumulation_ready"),
            "d_confluence_type":           snap.get("d_confluence_type"),
            "d_confluence_type_v2":        snap.get("d_confluence_type_v2"),
            "active_d_signals":            snap.get("active_d_signals") or [],
            "active_wlnbb_signals":        snap.get("active_wlnbb_signals") or [],
        })

    try:
        await enrich_np_candidates(np_rows)
    except Exception as exc:
        logger.warning(f"[RECALC/v2] enrich_np_candidates failed: {exc}")

    by_symbol = {r.get("symbol"): r for r in np_rows}

    updated = 0
    skipped = 0
    for idx, c in enumerate(candidates):
        sym = c.get("symbol")
        np_row = by_symbol.get(sym)
        if not np_row or not np_row.get("decision"):
            skipped += 1
            continue
        try:
            v2 = build_v2_row(np_row, rank=idx + 1)
        except Exception as exc:
            logger.debug(f"[RECALC/v2] build_v2_row failed {sym}: {exc}")
            skipped += 1
            continue

        fields = {
            "priority_score":       np_row.get("priority_score"),
            "priority_label":       np_row.get("priority_label"),
            "priority_flags":       np_row.get("priority_flags") or [],
            "priority_reason":      np_row.get("priority_reason"),
            "scanner_v2_decision":  v2.get("scanner_v2_decision"),
            "scanner_v2_score":     v2.get("scanner_v2_score"),
            "scanner_v2_reason":    v2.get("scanner_v2_reason"),
            "scanner_v2_flags":     v2.get("scanner_v2_flags") or [],
            "subsector":            v2.get("subsector"),
            "sector_context":       np_row.get("sector_context"),
            "macro_context":        np_row.get("macro_context"),
            "news_hype_context":    np_row.get("news_hype_context"),
            "sympathy_context":     np_row.get("sympathy_context"),
            "decision_flags":       np_row.get("decision_flags") or [],
        }
        ok = await update_replay_candidate_v2(c["id"], fields)
        if ok:
            updated += 1

    return {
        "candidate_count_total":   len(candidates),
        "updated_candidate_count": updated,
        "skipped_insufficient":    skipped,
    }


async def rebuild_research_bundle(run_id: int) -> dict:
    """
    Rebuild the research bundle for a run from existing candidates + outcomes.
    Research bundles are computed on demand (build_research_bundle loads from
    DB each call), so this is effectively a validation + cache-warming pass.
    We call it explicitly so the endpoint can verify it succeeds and return
    summary counts.
    """
    from replay.research_bundle import build_research_bundle
    bundle = await build_research_bundle(run_id)
    summary = bundle.get("summary") or {}
    return {
        "run_id":             run_id,
        "candidate_count":    summary.get("candidate_count"),
        "outcome_count":      summary.get("outcome_count"),
        "buckets_generated":  sum(1 for k in bundle.keys() if k.startswith("performance_by_")),
    }
