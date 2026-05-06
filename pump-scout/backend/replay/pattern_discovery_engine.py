"""
Pattern Discovery Engine — orchestrates the full discovery pipeline.

Pipeline modes
--------------
  episode_aggregate (V1A)
    1. Load missed pump dataset from DB (raw_pattern_episode_features)
    2. Run pattern miner on episode-level aggregate features

  bar_sequence (V1B)
    1. Load raw daily bars from DB (raw_pattern_daily_features, PRE phase)
    2. Build bar feature snapshots per episode
    3. Build rolling-window tag sequences
    4. Mine symbolic tag / sequence patterns

  both (default)
    Runs V1A then V1B; results are merged in the report.

Common to all modes
    3/5. Compute Pump Watch scores for all episodes
    4/6. Persist pump_watch scores + pattern candidates to DB
    5/7. Update discovered_signal_registry.json
    6/8. Generate structured discovery report

This engine does NOT change Scanner V2 BUY/WATCH/AVOID routing.
All outputs are EXPERIMENTAL or PUMP_WATCH only.
"""

import asyncio
import json
import logging
import math
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_REGISTRY_PATH = os.path.join(
    os.path.dirname(__file__), "..", "discovered_signal_registry.json"
)

# Curated FLOW evaluation cache: (run_id, episode_id) → curated_flow_result dict
# Populated during _run_bar_sequence_pipeline(); consumed by build_discovery_export().
_curated_flow_cache: dict[tuple[int, int], dict] = {}

# In-memory progress tracker
_discovery_progress: dict = {
    "running":    False,
    "run_id":     None,
    "mode":       None,
    "phase":      None,
    "episodes":   0,
    "group_counts": {},
    "pre_daily_rows_loaded": 0,
    "bar_snapshots_created": 0,
    "bar_sequences_created": 0,
    "flow_sequences_created": 0,
    "combined_sequences_created": 0,
    "patterns_evaluated": 0,
    "patterns_experimental": 0,
    "bar_patterns_evaluated": 0,
    "bar_patterns_experimental": 0,
    "flow_patterns_evaluated": 0,
    "combined_patterns_evaluated": 0,
    "custom_sequences_created": 0,
    "flow_custom_sequences_created": 0,
    "custom_patterns_evaluated": 0,
    "flow_custom_patterns_evaluated": 0,
    "patterns_rejected_low_count": 0,
    "patterns_rejected_low_lift": 0,
    "patterns_saved": 0,
    "episodes_scored": 0,
    "flow_tag_counts": {},
    "error":      None,
    "started_at": None,
    "finished_at": None,
}


def get_discovery_progress() -> dict:
    return dict(_discovery_progress)


# ── Registry helpers ──────────────────────────────────────────────────────────

def _load_registry() -> list[dict]:
    try:
        with open(_REGISTRY_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, list) else data.get("signals", [])
    except FileNotFoundError:
        return []
    except Exception as exc:
        logger.warning(f"Registry load error: {exc}")
        return []


def _save_registry(signals: list[dict]) -> None:
    try:
        with open(_REGISTRY_PATH, "w", encoding="utf-8") as f:
            json.dump(signals, f, indent=2, default=str)
    except Exception as exc:
        logger.error(f"Registry save error: {exc}")


def _merge_registry(existing: list[dict], new_candidates: list[dict], run_id: int) -> list[dict]:
    """
    Merge new_candidates into existing registry.
    Updates existing entries with new stats; appends genuinely new ones.
    Returns merged list.
    """
    by_id = {s["signal_id"]: s for s in existing}
    today = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")

    for cand in new_candidates:
        sid = cand.get("signal_id")
        if not sid:
            continue

        existing_entry = by_id.get(sid)
        if existing_entry:
            existing_entry["last_run_id"]                = run_id
            existing_entry["last_updated"]               = today
            existing_entry["sample_count_4x"]            = cand.get("count_all_4x", 0)
            existing_entry["sample_count_false_positive"] = cand.get("count_false_positive", 0)
            existing_entry["sample_count_normal_winner"] = cand.get("count_normal_winner", 0)
            existing_entry["lift_vs_false_positive"]     = cand.get("lift_vs_false_positive")
            existing_entry["false_positive_rate"]        = cand.get("false_positive_rate")
            existing_entry["split_artifact_exposure"]    = cand.get("split_artifact_exposure")
            existing_entry["reverse_split_exposure"]     = cand.get("reverse_split_exposure")
            existing_entry["precision_estimate"]         = cand.get("precision_estimate")
            existing_entry["recall_all_4x"]              = cand.get("recall_all_4x")
            # Upgrade status if newly qualified
            old_status = existing_entry.get("status", "DISCOVERED")
            new_status = cand.get("status", "RESEARCH_ONLY")
            _STATUS_RANK = {
                "VALIDATED_BUY_SUPPORT": 0, "VALIDATED_WATCH": 1,
                "EXPERIMENTAL": 2, "EXPERIMENTAL_RARE": 3,
                "RESEARCH_ONLY": 4, "DISCOVERED": 5, "REJECTED": 6,
            }
            if _STATUS_RANK.get(new_status, 9) < _STATUS_RANK.get(old_status, 9):
                existing_entry["status"] = new_status
            # Propagate bar-sequence fields if present
            for fld in ("source_type", "sequence_signature", "window_size",
                        "bar_signature", "median_days_to_breakout", "example_symbols"):
                if cand.get(fld) is not None:
                    existing_entry[fld] = cand[fld]
        else:
            source_type = cand.get("source_type", "EPISODE_AGGREGATE")
            new_entry = {
                "signal_id":               sid,
                "signal_name":             sid,
                "family":                  cand.get("family"),
                "source_type":             source_type,
                "status":                  cand.get("status", "DISCOVERED"),
                "intended_use":            cand.get("intended_use", "RESEARCH_ONLY"),
                "description":             cand.get("description", ""),
                "human_readable_definition": cand.get("description", ""),
                "machine_conditions":      cand.get("machine_conditions", []),
                "required_fields":         [],
                "forbidden_fields":        [],
                "source_run_ids":          [run_id],
                "discovery_date":          today,
                "last_run_id":             run_id,
                "last_updated":            today,
                "sample_count_4x":         cand.get("count_all_4x", 0),
                "sample_count_false_positive": cand.get("count_false_positive", 0),
                "sample_count_normal_winner":  cand.get("count_normal_winner", 0),
                "lift_vs_false_positive":  cand.get("lift_vs_false_positive"),
                "false_positive_rate":     cand.get("false_positive_rate"),
                "split_artifact_exposure": cand.get("split_artifact_exposure"),
                "reverse_split_exposure":  cand.get("reverse_split_exposure"),
                "precision_estimate":      cand.get("precision_estimate"),
                "recall_all_4x":           cand.get("recall_all_4x"),
                "notes":                   "",
                "replay_status":           "NOT_TESTED",
            }
            # Bar-sequence extra fields
            for fld in ("sequence_signature", "window_size", "bar_signature",
                        "median_days_to_breakout", "example_symbols"):
                if cand.get(fld) is not None:
                    new_entry[fld] = cand[fld]
            by_id[sid] = new_entry

    return list(by_id.values())


# ── DB persistence helpers ────────────────────────────────────────────────────

async def _persist_pump_watch_scores(run_id: int, scored_episodes: list[dict]) -> int:
    from database import update_raw_pattern_episode_features

    updated = 0
    for ep in scored_episodes:
        ep_id = ep.get("episode_id") or ep.get("id")
        if not ep_id:
            continue
        patch = {
            "pump_watch_score":             ep.get("pump_watch_score"),
            "pump_watch_label":             ep.get("pump_watch_label"),
            "pump_watch_reasons":           json.dumps(ep.get("pump_watch_reasons") or []),
            "pump_watch_risk_flags":        json.dumps(ep.get("pump_watch_risk_flags") or []),
            "pump_watch_pattern_ids":       json.dumps(ep.get("pump_watch_pattern_ids") or []),
            "pump_watch_split_context":     ep.get("pump_watch_split_context"),
            "pump_watch_confidence":        ep.get("pump_watch_confidence"),
            "pump_watch_diagnostic_labels": json.dumps(ep.get("pump_watch_diagnostic_labels") or []),
            "pump_watch_pattern_id":        ep.get("pump_watch_pattern_id"),
            "pump_watch_rescue_reason":     ep.get("pump_watch_rescue_reason"),
        }
        try:
            await update_raw_pattern_episode_features(run_id, ep_id, patch)
            updated += 1
        except Exception as exc:
            logger.debug(f"pump_watch persist ep={ep_id}: {exc}")

    return updated


async def _persist_pattern_candidates(run_id: int, candidates: list[dict]) -> int:
    from database import upsert_discovered_patterns

    rows: list[dict] = []
    for c in candidates:
        rows.append({
            "run_id":                  run_id,
            "signal_id":               c.get("signal_id"),
            "source_type":             c.get("source_type", "EPISODE_AGGREGATE"),
            "feature_family":          c.get("feature_family"),
            "family":                  c.get("family"),
            "status":                  c.get("status"),
            "intended_use":            c.get("intended_use"),
            "description":             c.get("description"),
            "count_missed_4x":         c.get("count_missed_4x"),
            "count_detected_4x":       c.get("count_detected_4x"),
            "count_all_4x":            c.get("count_all_4x"),
            "count_false_positive":    c.get("count_false_positive"),
            "count_normal_winner":     c.get("count_normal_winner"),
            "count_split_artifact":    c.get("count_split_artifact"),
            "lift_vs_false_positive":  c.get("lift_vs_false_positive"),
            "lift_vs_normal_winner":   c.get("lift_vs_normal_winner"),
            "precision_estimate":      c.get("precision_estimate"),
            "recall_all_4x":           c.get("recall_all_4x"),
            "false_positive_rate":     c.get("false_positive_rate"),
            "split_artifact_exposure": c.get("split_artifact_exposure"),
            "reverse_split_exposure":  c.get("reverse_split_exposure"),
            "recommendation":          c.get("recommendation"),
            "machine_conditions_json": json.dumps(c.get("machine_conditions") or []),
        })

    if not rows:
        return 0

    try:
        return await upsert_discovered_patterns(run_id, rows)
    except Exception as exc:
        logger.error(f"_persist_pattern_candidates: {exc}")
        return 0


# ── Bar-sequence pipeline helpers ─────────────────────────────────────────────

async def _run_bar_sequence_pipeline(
    run_id: int,
    dataset: dict,
    windows: tuple,
    include_flow: bool = False,
    include_combined: bool = False,
    include_custom: bool = False,
) -> tuple[list[dict], dict]:
    """
    Load daily bar rows, build snapshots + sequences, mine bar patterns.

    Returns (all_bar_candidates, bar_sequences_by_group).
    bar_sequences_by_group uses price-action sequences (backward compat).
    """
    from database import get_raw_pattern_daily_features
    from replay.bar_feature_engine import (
        build_bar_feature_snapshots_for_episode,
        build_bar_sequences,
    )
    from replay.pattern_miner import mine_bar_patterns

    _discovery_progress["phase"] = "LOADING_BAR_FEATURES"
    logger.info(f"[DISCOVERY/V1B] run={run_id}: loading raw daily bars (PRE phase only)")

    all_daily = await get_raw_pattern_daily_features(
        run_id=run_id, phase="PRE", limit=200_000
    )
    _discovery_progress["pre_daily_rows_loaded"] = len(all_daily)

    # Group by episode_id for fast lookup
    daily_by_episode: dict[int, list[dict]] = {}
    for row in all_daily:
        eid = row.get("episode_id")
        if eid is not None:
            daily_by_episode.setdefault(eid, []).append(row)

    logger.info(
        f"[DISCOVERY/V1B] run={run_id}: {len(all_daily)} daily rows "
        f"across {len(daily_by_episode)} episodes"
    )

    _discovery_progress["phase"] = "BUILDING_BAR_SEQUENCES"

    _GROUPS = ["missed_4x_pump", "detected_4x_pump", "false_positive",
               "normal_winner", "split_artifact"]

    # Build price-action sequences (V1B) — always
    bar_sequences_by_group:              dict[str, list[dict]] = {g: [] for g in _GROUPS}
    flow_sequences_by_group:             dict[str, list[dict]] = {g: [] for g in _GROUPS}
    combined_sequences_by_group:         dict[str, list[dict]] = {g: [] for g in _GROUPS}
    custom_sequences_by_group:           dict[str, list[dict]] = {g: [] for g in _GROUPS}
    flow_custom_sequences_by_group:      dict[str, list[dict]] = {g: [] for g in _GROUPS}

    total_snapshots = 0
    # Accumulate flow tag counts for debug
    flow_tag_counts: dict[str, int] = {}

    for grp in _GROUPS:
        episodes = dataset.get(grp) or []
        for ep in episodes:
            ep_id      = ep.get("episode_id") or ep.get("id")
            daily_rows = daily_by_episode.get(ep_id, [])
            if not daily_rows:
                continue
            # build_bar_feature_snapshots_for_episode now also calls build_bar_flow_features
            snaps = build_bar_feature_snapshots_for_episode(ep, daily_rows)
            if not snaps:
                continue
            total_snapshots += len(snaps)

            # Price-action sequences (V1B)
            seqs_price = build_bar_sequences(snaps, windows=windows, tag_mode="price")
            bar_sequences_by_group[grp].extend(seqs_price)

            # Flow sequences (V1C)
            if include_flow or include_combined:
                seqs_flow = build_bar_sequences(snaps, windows=windows, tag_mode="flow")
                flow_sequences_by_group[grp].extend(seqs_flow)

            # Combined sequences (V1B + V1C)
            if include_combined:
                seqs_combined = build_bar_sequences(snaps, windows=windows, tag_mode="combined")
                combined_sequences_by_group[grp].extend(seqs_combined)

            # Custom signal sequences (CUSTOM_SIGNAL family)
            if include_custom:
                seqs_custom = build_bar_sequences(snaps, windows=windows, tag_mode="custom")
                custom_sequences_by_group[grp].extend(seqs_custom)
                seqs_fcc = build_bar_sequences(snaps, windows=windows, tag_mode="flow_custom_combined")
                flow_custom_sequences_by_group[grp].extend(seqs_fcc)

            # Evaluate curated FLOW rules on bar snapshots and cache result
            if include_flow or include_combined:
                try:
                    from replay.curated_flow_rules import score_episode_curated_flow
                    ep_id_for_cache = ep.get("episode_id") or ep.get("id")
                    if ep_id_for_cache is not None:
                        cf_result = score_episode_curated_flow(ep, snaps)
                        _curated_flow_cache[(run_id, ep_id_for_cache)] = cf_result
                        # Also attach directly so the in-memory episode has the fields
                        ep.update(cf_result)
                except Exception as _cfe:
                    logger.debug("curated_flow_rules failed for episode %s: %s",
                                 ep.get("episode_id"), _cfe)

            # Collect flow tag counts for debug
            for snap in snaps:
                for t in (snap.get("flow_tags") or []):
                    flow_tag_counts[t] = flow_tag_counts.get(t, 0) + 1

    total_seq     = sum(len(v) for v in bar_sequences_by_group.values())
    total_flow    = sum(len(v) for v in flow_sequences_by_group.values())
    total_comb    = sum(len(v) for v in combined_sequences_by_group.values())
    total_custom  = sum(len(v) for v in custom_sequences_by_group.values())
    total_fcc     = sum(len(v) for v in flow_custom_sequences_by_group.values())
    _discovery_progress["bar_snapshots_created"]       = total_snapshots
    _discovery_progress["bar_sequences_created"]       = total_seq
    _discovery_progress["flow_sequences_created"]      = total_flow
    _discovery_progress["combined_sequences_created"]  = total_comb
    _discovery_progress["custom_sequences_created"]    = total_custom
    _discovery_progress["flow_custom_sequences_created"] = total_fcc
    _discovery_progress["flow_tag_counts"]             = flow_tag_counts

    logger.info(
        f"[DISCOVERY/V1B+C] run={run_id}: {total_snapshots} snapshots | "
        f"price_seqs={total_seq} flow_seqs={total_flow} combined_seqs={total_comb} "
        f"custom_seqs={total_custom} flow_custom_seqs={total_fcc}"
    )

    # ── Mine price-action patterns (V1B) ──────────────────────────────────────
    _discovery_progress["phase"] = "MINING_BAR_PATTERNS"
    bar_candidates = mine_bar_patterns(
        bar_sequences_by_group=bar_sequences_by_group,
        windows=windows,
        feature_family="PRICE_ACTION",
    )
    _discovery_progress["bar_patterns_evaluated"]    = len(bar_candidates)
    _discovery_progress["bar_patterns_experimental"] = sum(
        1 for c in bar_candidates if c["status"] in ("EXPERIMENTAL", "EXPERIMENTAL_RARE")
    )

    all_candidates = list(bar_candidates)

    # ── Mine flow patterns (V1C) ──────────────────────────────────────────────
    flow_candidates: list[dict] = []
    if include_flow and any(flow_sequences_by_group.values()):
        _discovery_progress["phase"] = "MINING_FLOW_PATTERNS"
        flow_candidates = mine_bar_patterns(
            bar_sequences_by_group=flow_sequences_by_group,
            windows=windows,
            feature_family="FLOW",
        )
        _discovery_progress["flow_patterns_evaluated"] = len(flow_candidates)
        all_candidates.extend(flow_candidates)

    # ── Mine combined patterns (V1C) ──────────────────────────────────────────
    combined_candidates: list[dict] = []
    if include_combined and any(combined_sequences_by_group.values()):
        _discovery_progress["phase"] = "MINING_COMBINED_PATTERNS"
        combined_candidates = mine_bar_patterns(
            bar_sequences_by_group=combined_sequences_by_group,
            windows=windows,
            feature_family="COMBINED",
        )
        _discovery_progress["combined_patterns_evaluated"] = len(combined_candidates)
        all_candidates.extend(combined_candidates)

    # ── Mine custom signal patterns ───────────────────────────────────────────
    custom_candidates: list[dict] = []
    if include_custom and any(custom_sequences_by_group.values()):
        _discovery_progress["phase"] = "MINING_CUSTOM_PATTERNS"
        custom_candidates = mine_bar_patterns(
            bar_sequences_by_group=custom_sequences_by_group,
            windows=windows,
            feature_family="CUSTOM_SIGNAL",
        )
        _discovery_progress["custom_patterns_evaluated"] = len(custom_candidates)
        all_candidates.extend(custom_candidates)

    # ── Mine FLOW + Custom combined patterns ──────────────────────────────────
    flow_custom_candidates: list[dict] = []
    if include_custom and any(flow_custom_sequences_by_group.values()):
        _discovery_progress["phase"] = "MINING_FLOW_CUSTOM_PATTERNS"
        flow_custom_candidates = mine_bar_patterns(
            bar_sequences_by_group=flow_custom_sequences_by_group,
            windows=windows,
            feature_family="FLOW_CUSTOM_COMBINED",
        )
        _discovery_progress["flow_custom_patterns_evaluated"] = len(flow_custom_candidates)
        all_candidates.extend(flow_custom_candidates)

    logger.info(
        f"[DISCOVERY/V1B+C] run={run_id}: price={len(bar_candidates)} "
        f"flow={len(flow_candidates)} combined={len(combined_candidates)} "
        f"custom={len(custom_candidates)} flow_custom={len(flow_custom_candidates)} "
        f"total={len(all_candidates)}"
    )

    return all_candidates, bar_sequences_by_group


# ── Main pipeline ─────────────────────────────────────────────────────────────

async def run_pattern_discovery(
    run_id: int,
    mode: str = "both",
    windows: tuple = (1, 2, 3, 5, 10),
    exclude_split_artifacts: bool = False,
) -> dict:
    """
    Full discovery pipeline for one raw_pattern_study run_id.

    Parameters
    ----------
    run_id                : raw_pattern_runs.id to analyse
    mode                  : "episode_aggregate" | "bar_sequence" | "both"
                            | "flow" | "combined" | "all"
                            "all" = episode_aggregate + bar_sequence + flow + combined
    windows               : bar-sequence window sizes (only used when mode
                            includes bar_sequence or flow)
    exclude_split_artifacts : if True, split_artifact episodes are excluded
                              from episode-level mining counts (still kept
                              in a separate group for exposure stats)

    Returns
    -------
    Summary dict with status, episodes_loaded, patterns_evaluated, etc.
    """
    # Normalise mode flags
    _run_episode  = mode in ("episode_aggregate", "both", "all")
    _run_price    = mode in ("bar_sequence", "both", "all")
    _run_flow     = mode in ("flow", "combined", "all")
    _run_combined = mode in ("combined", "all")
    _run_custom   = mode in ("custom", "all")
    global _discovery_progress

    if _discovery_progress["running"]:
        return {"status": "ALREADY_RUNNING", "run_id": _discovery_progress["run_id"]}

    _discovery_progress.update({
        "running":    True,
        "run_id":     run_id,
        "mode":       mode,
        "phase":      "LOADING",
        "error":      None,
        "group_counts": {},
        "pre_daily_rows_loaded": 0,
        "bar_snapshots_created": 0,
        "bar_sequences_created": 0,
        "flow_sequences_created": 0,
        "combined_sequences_created": 0,
        "custom_sequences_created": 0,
        "flow_custom_sequences_created": 0,
        "bar_patterns_evaluated":       0,
        "bar_patterns_experimental":    0,
        "flow_patterns_evaluated":      0,
        "combined_patterns_evaluated":  0,
        "custom_patterns_evaluated":    0,
        "flow_custom_patterns_evaluated": 0,
        "patterns_rejected_low_count": 0,
        "patterns_rejected_low_lift":  0,
        "patterns_saved": 0,
        "flow_tag_counts": {},
        "started_at": datetime.now(tz=timezone.utc).isoformat(),
        "finished_at": None,
    })

    try:
        # ── Phase 1: Load episode-level dataset ───────────────────────────────
        from replay.missed_pump_dataset import load_dataset_for_run
        _discovery_progress["phase"] = "LOADING_DATASET"

        dataset = await load_dataset_for_run(run_id)
        if not dataset:
            raise ValueError(f"No episodes found for run_id={run_id}")

        summary      = dataset.get("summary") or {}
        total_ep     = summary.get("total_episodes", 0)
        group_counts = {
            "missed_4x_pump":   summary.get("missed_4x_pump_count", 0),
            "detected_4x_pump": summary.get("detected_4x_pump_count", 0),
            "false_positive":   summary.get("false_positive_count", 0),
            "normal_winner":    summary.get("normal_winner_count", 0),
            "split_artifact":   summary.get("split_artifact_count", 0),
            "unknown":          len(dataset.get("unknown") or []),
        }
        _discovery_progress["episodes"]    = total_ep
        _discovery_progress["group_counts"] = group_counts

        logger.info(
            f"[DISCOVERY] run={run_id} mode={mode}: loaded {total_ep} episodes | "
            f"missed={group_counts['missed_4x_pump']} "
            f"detected={group_counts['detected_4x_pump']} "
            f"fp={group_counts['false_positive']} "
            f"nw={group_counts['normal_winner']} "
            f"art={group_counts['split_artifact']} "
            f"unknown={group_counts['unknown']}"
        )

        # ── Phase 2: Episode-aggregate pattern mining (V1A) ───────────────────
        candidates: list[dict] = []
        feature_sep: list[dict] = []
        bar_candidates: list[dict] = []
        bar_sequences_by_group: dict = {}

        if _run_episode:
            from replay.pattern_miner import mine_patterns, compute_feature_separability
            _discovery_progress["phase"] = "PATTERN_MINING_V1A"

            candidates  = mine_patterns(dataset)
            feature_sep = compute_feature_separability(dataset)

            _discovery_progress["patterns_evaluated"]         = len(candidates)
            _discovery_progress["patterns_experimental"]      = sum(
                1 for c in candidates
                if c["status"] in ("EXPERIMENTAL", "EXPERIMENTAL_RARE")
            )
            _discovery_progress["patterns_rejected_low_count"] = sum(
                1 for c in candidates
                if c["status"] == "REJECT" and (c.get("count_all_4x") or 0) < 2
            )
            _discovery_progress["patterns_rejected_low_lift"]  = sum(
                1 for c in candidates
                if c["status"] == "REJECT" and (c.get("count_all_4x") or 0) >= 2
            )
            logger.info(
                f"[DISCOVERY/V1A] run={run_id}: {len(candidates)} patterns | "
                f"experimental={_discovery_progress['patterns_experimental']} | "
                f"rejected_low_count={_discovery_progress['patterns_rejected_low_count']} | "
                f"rejected_low_lift={_discovery_progress['patterns_rejected_low_lift']}"
            )

        # ── Phase 3: Bar/flow/custom pattern mining (V1B + V1C + custom) ────
        if _run_price or _run_flow or _run_combined or _run_custom:
            bar_candidates, bar_sequences_by_group = await _run_bar_sequence_pipeline(
                run_id=run_id,
                dataset=dataset,
                windows=windows,
                include_flow=_run_flow,
                include_combined=_run_combined,
                include_custom=_run_custom,
            )

        # ── Phase 4: Pump Watch scoring ───────────────────────────────────────
        from replay.pump_watch_scorer import score_episodes, summarize_pump_watch_distribution
        _discovery_progress["phase"] = "PUMP_WATCH_SCORING"

        from database import get_raw_pattern_episode_features
        all_episodes_raw = await get_raw_pattern_episode_features(run_id=run_id, limit=10000)

        scored       = score_episodes(all_episodes_raw)
        pw_dist      = summarize_pump_watch_distribution(scored)
        _discovery_progress["episodes_scored"] = len(scored)

        # ── Phase 5: Persist pump watch scores ────────────────────────────────
        _discovery_progress["phase"] = "PERSISTING_SCORES"
        updated = await _persist_pump_watch_scores(run_id, scored)
        logger.info(f"[DISCOVERY] run={run_id}: persisted pump_watch scores for {updated} episodes")

        # ── Phase 6: Persist pattern candidates ───────────────────────────────
        _discovery_progress["phase"] = "PERSISTING_PATTERNS"
        all_candidates = candidates + bar_candidates
        saved_patterns = await _persist_pattern_candidates(run_id, all_candidates)
        _discovery_progress["patterns_saved"] = saved_patterns
        logger.info(f"[DISCOVERY] run={run_id}: persisted {saved_patterns} pattern rows")

        # ── Phase 7: Update registry ──────────────────────────────────────────
        _discovery_progress["phase"] = "UPDATING_REGISTRY"
        existing_registry = _load_registry()
        registry_candidates = [
            c for c in all_candidates
            if c["status"] in ("EXPERIMENTAL", "EXPERIMENTAL_RARE", "RESEARCH_ONLY")
        ]
        merged_registry = _merge_registry(existing_registry, registry_candidates, run_id)
        _save_registry(merged_registry)
        logger.info(
            f"[DISCOVERY] run={run_id}: registry updated — "
            f"{len(merged_registry)} total signals"
        )

        # ── Phase 8: Build report ─────────────────────────────────────────────
        _discovery_progress["phase"] = "BUILDING_REPORT"
        from replay.pattern_discovery_report import build_discovery_report
        report = build_discovery_report(
            run_id=run_id,
            dataset_summary=summary,
            pattern_candidates=candidates,
            bar_candidates=bar_candidates,
            feature_separability=feature_sep,
            pump_watch_distribution=pw_dist,
            mode=mode,
            windows=list(windows),
        )

        _discovery_progress.update({
            "running":    False,
            "phase":      "COMPLETE",
            "finished_at": datetime.now(tz=timezone.utc).isoformat(),
        })

        return {
            "status":                    "COMPLETE",
            "run_id":                    run_id,
            "mode":                      mode,
            "episodes_loaded":           total_ep,
            "group_counts":              group_counts,
            "pre_daily_rows_loaded":     _discovery_progress["pre_daily_rows_loaded"],
            "bar_snapshots_created":     _discovery_progress["bar_snapshots_created"],
            "bar_sequences_created":     _discovery_progress["bar_sequences_created"],
            "patterns_evaluated":        len(candidates),
            "patterns_experimental":     _discovery_progress["patterns_experimental"],
            "patterns_rejected_low_count": _discovery_progress["patterns_rejected_low_count"],
            "patterns_rejected_low_lift":  _discovery_progress["patterns_rejected_low_lift"],
            "bar_patterns_evaluated":    len(bar_candidates),
            "bar_patterns_experimental": _discovery_progress["bar_patterns_experimental"],
            "patterns_saved":            saved_patterns,
            "episodes_scored":           len(scored),
            "pump_watch_distribution":   pw_dist,
            "top_patterns":              [
                c for c in candidates
                if c["status"] in ("EXPERIMENTAL", "EXPERIMENTAL_RARE")
            ][:10],
            "top_bar_patterns":          [
                c for c in bar_candidates
                if c["status"] in ("EXPERIMENTAL", "EXPERIMENTAL_RARE")
            ][:10],
            "feature_separability":      feature_sep[:20],
            "dataset_summary":           summary,
            "report":                    report,
            "registry_total_signals":    len(merged_registry),
        }

    except Exception as exc:
        logger.exception(f"[DISCOVERY] run={run_id}: FATAL: {exc}")
        _discovery_progress.update({
            "running": False,
            "phase":   "ERROR",
            "error":   str(exc),
            "finished_at": datetime.now(tz=timezone.utc).isoformat(),
        })
        return {"status": "ERROR", "run_id": run_id, "error": str(exc)}


async def get_discovery_results(run_id: int) -> dict:
    """Return the latest discovery results for a run_id from the DB."""
    from database import get_discovered_patterns, get_raw_pattern_episode_features
    from replay.pump_watch_scorer import summarize_pump_watch_distribution

    try:
        patterns = await get_discovered_patterns(run_id)
        episodes = await get_raw_pattern_episode_features(run_id=run_id, limit=10000)
        pw_dist  = summarize_pump_watch_distribution(episodes)

        return {
            "run_id":                  run_id,
            "patterns":                patterns,
            "pump_watch_distribution": pw_dist,
            "registry":                _load_registry(),
        }
    except Exception as exc:
        logger.error(f"get_discovery_results({run_id}): {exc}")
        return {"run_id": run_id, "error": str(exc)}


# ── Source-type inference (mirrors database._infer_source_type) ───────────────

def _st_from_signal_id(signal_id: str, stored: Optional[str] = None) -> str:
    if stored:
        return stored
    if not signal_id:
        return "EPISODE_AGGREGATE"
    for prefix, st in (
        ("DISC_BAR_TEN_BAR_CONTEXT_",             "TEN_BAR_CONTEXT"),
        ("DISC_BAR_THREE_BAR_SEQUENCE_",          "THREE_BAR_SEQUENCE"),
        ("DISC_BAR_TWO_BAR_SEQUENCE_",            "TWO_BAR_SEQUENCE"),
        ("DISC_BAR_FIVE_BAR_SEQUENCE_",           "FIVE_BAR_SEQUENCE"),
        ("DISC_BAR_SINGLE_BAR_",                  "SINGLE_BAR"),
        ("DISC_FLOW_TEN_BAR_CONTEXT_",            "TEN_BAR_CONTEXT"),
        ("DISC_FLOW_THREE_BAR_SEQUENCE_",         "THREE_BAR_SEQUENCE"),
        ("DISC_FLOW_TWO_BAR_SEQUENCE_",           "TWO_BAR_SEQUENCE"),
        ("DISC_FLOW_FIVE_BAR_SEQUENCE_",          "FIVE_BAR_SEQUENCE"),
        ("DISC_FLOW_SINGLE_BAR_",                 "SINGLE_BAR"),
        ("DISC_COMBINED_TEN_BAR_CONTEXT_",        "TEN_BAR_CONTEXT"),
        ("DISC_COMBINED_THREE_BAR_SEQUENCE_",     "THREE_BAR_SEQUENCE"),
        ("DISC_COMBINED_TWO_BAR_SEQUENCE_",       "TWO_BAR_SEQUENCE"),
        ("DISC_COMBINED_FIVE_BAR_SEQUENCE_",      "FIVE_BAR_SEQUENCE"),
        ("DISC_COMBINED_SINGLE_BAR_",             "SINGLE_BAR"),
        ("DISC_CUSTOM_TEN_BAR_CONTEXT_",          "TEN_BAR_CONTEXT"),
        ("DISC_CUSTOM_THREE_BAR_SEQUENCE_",       "THREE_BAR_SEQUENCE"),
        ("DISC_CUSTOM_TWO_BAR_SEQUENCE_",         "TWO_BAR_SEQUENCE"),
        ("DISC_CUSTOM_FIVE_BAR_SEQUENCE_",        "FIVE_BAR_SEQUENCE"),
        ("DISC_CUSTOM_SINGLE_BAR_",               "SINGLE_BAR"),
        ("DISC_FLOW_CUSTOM_TEN_BAR_CONTEXT_",     "TEN_BAR_CONTEXT"),
        ("DISC_FLOW_CUSTOM_THREE_BAR_SEQUENCE_",  "THREE_BAR_SEQUENCE"),
        ("DISC_FLOW_CUSTOM_TWO_BAR_SEQUENCE_",    "TWO_BAR_SEQUENCE"),
        ("DISC_FLOW_CUSTOM_FIVE_BAR_SEQUENCE_",   "FIVE_BAR_SEQUENCE"),
        ("DISC_FLOW_CUSTOM_SINGLE_BAR_",          "SINGLE_BAR"),
    ):
        if signal_id.startswith(prefix):
            return st
    return "EPISODE_AGGREGATE"


def _ff_from_signal_id(signal_id: str, stored: Optional[str] = None) -> str:
    """Infer feature_family from signal_id prefix."""
    if stored:
        return stored
    if not signal_id:
        return "EPISODE_AGGREGATE"
    if signal_id.startswith("DISC_FLOW_CUSTOM_"):
        return "FLOW_CUSTOM_COMBINED"
    if signal_id.startswith("DISC_FLOW_"):
        return "FLOW"
    if signal_id.startswith("DISC_COMBINED_"):
        return "COMBINED"
    if signal_id.startswith("DISC_CUSTOM_"):
        return "CUSTOM_SIGNAL"
    if signal_id.startswith("DISC_BAR_"):
        return "PRICE_ACTION"
    return "EPISODE_AGGREGATE"


# ── Flow subtype inference ────────────────────────────────────────────────────

_FLOW_DIVERGENCE_PAIRS: list[set] = [
    {"ADL_ACCUM_3D",  "OBV_DISTRIB_3D"},
    {"ADL_DISTRIB_3D", "OBV_ACCUM_3D"},
    {"CMF_NEGATIVE",  "BUY_PRESSURE_HIGH"},
    {"CMF_POSITIVE",  "CLOSE_LOW"},
]

_FLOW_GAP_TAGS        = {"GAP_UP", "GAP_DOWN", "GAP_UP_WEAK", "GAP_DOWN_WEAK"}
_FLOW_GAP_FADE_TAGS   = {"CLOSE_LOW", "GAP_FADE", "OBV_DISTRIB_3D", "CMF_NEGATIVE"}
_FLOW_GAP_RECLAIM_TAGS = {"CLOSE_HIGH", "BUY_PRESSURE_HIGH", "OBV_ACCUM_3D", "ADL_ACCUM_3D"}
_FLOW_ABSORPTION_TAGS  = {"CLV_POSITIVE", "SIGNED_VOL_POSITIVE", "ADL_ACCUM_3D"}
_FLOW_BEARISH_TAGS     = {"ADL_DISTRIB_3D", "OBV_DISTRIB_3D", "CMF_NEGATIVE", "UPPER_WICK_SUPPLY", "CLOSE_LOW"}
_FLOW_BULLISH_TAGS     = {"ADL_ACCUM_3D", "OBV_ACCUM_3D", "CMF_POSITIVE", "BUY_PRESSURE_HIGH", "CLOSE_HIGH"}


def _extract_pattern_tags(p: dict) -> list[str]:
    """Extract symbolic tags from machine_conditions signature= entry or description."""
    mc = p.get("machine_conditions") or []
    if isinstance(mc, str):
        try:
            mc = json.loads(mc)
        except Exception:
            mc = []
    for entry in mc:
        if isinstance(entry, str) and entry.startswith("signature="):
            sig = entry[len("signature="):]
            return [t.strip() for t in sig.split("+") if t.strip()]
    # Fallback: "Bar <SOURCE_TYPE>: TAG1+TAG2+..."
    desc = p.get("description") or ""
    if ":" in desc:
        sig_part = desc.split(":", 1)[1].strip()
        return [t.strip() for t in sig_part.split("+") if t.strip()]
    return []


def _infer_flow_subtype(p: dict) -> str:
    """
    Infer FLOW subtype from pattern tags.
    Priority: divergence > gap_fade > gap_reclaim > absorption > bearish > bullish > mixed.
    Returns 'N/A' for non-FLOW/COMBINED families.
    """
    if p.get("feature_family") not in ("FLOW", "COMBINED"):
        return "N/A"

    tags = _extract_pattern_tags(p)
    if not tags:
        return "FLOW_MIXED_CONTEXT"

    tag_set = set(tags)

    # 1. Divergence — conflicting accumulation/distribution signals
    for pair in _FLOW_DIVERGENCE_PAIRS:
        if pair.issubset(tag_set):
            return "FLOW_DIVERGENCE"

    # 2. Gap fade/fail
    has_gap = bool(tag_set & _FLOW_GAP_TAGS)
    if has_gap and (tag_set & _FLOW_GAP_FADE_TAGS):
        return "FLOW_GAP_FADE_OR_FAIL"

    # 3. Gap reclaim/hold
    if has_gap and (tag_set & _FLOW_GAP_RECLAIM_TAGS):
        return "FLOW_GAP_RECLAIM_OR_HOLD"

    # 4. Absorption — accumulation co-occurring with selling pressure
    if (tag_set & _FLOW_ABSORPTION_TAGS) and (tag_set & _FLOW_BEARISH_TAGS):
        return "FLOW_ABSORPTION"

    # 5. Bearish stress — multiple distribution/supply tags
    if len(tag_set & _FLOW_BEARISH_TAGS) >= 2:
        return "FLOW_BEARISH_STRESS"

    # 6. Bullish accumulation — multiple accumulation/demand tags
    if len(tag_set & _FLOW_BULLISH_TAGS) >= 2:
        return "FLOW_BULLISH_ACCUM"

    return "FLOW_MIXED_CONTEXT"


def _compute_flow_subtype_calibration(patterns: list[dict]) -> dict:
    """
    Aggregate pattern-level stats by flow_subtype.
    Uses count_all_4x / count_false_positive / reliability_score from each pattern.
    Excludes 'N/A' (non-FLOW families).
    """
    by_st: dict[str, list] = {}
    for p in patterns:
        st = p.get("flow_subtype") or "N/A"
        if st == "N/A":
            continue
        by_st.setdefault(st, []).append(p)

    result: dict = {}
    for st, pats in by_st.items():
        total_4x = sum(p.get("count_all_4x") or 0 for p in pats)
        total_fp = sum(p.get("count_false_positive") or 0 for p in pats)
        denom = total_4x + total_fp
        rs_list  = sorted(p["reliability_score"] for p in pats
                          if p.get("reliability_score") is not None)
        fpr_list = sorted(p["false_positive_rate"] for p in pats
                          if p.get("false_positive_rate") is not None)
        result[st] = {
            "pattern_count":       len(pats),
            "total_4x":            total_4x,
            "total_fp":            total_fp,
            "4x_rate":             round(total_4x / denom, 3) if denom > 0 else None,
            "false_positive_rate": round(total_fp / denom, 3) if denom > 0 else None,
            "median_reliability":  rs_list[len(rs_list) // 2]  if rs_list  else None,
            "median_fpr":          fpr_list[len(fpr_list) // 2] if fpr_list else None,
        }
    return result


def _reject_reason(p: dict) -> Optional[str]:
    if p.get("status") != "REJECT":
        return None
    cnt  = p.get("count_all_4x") or 0
    lift = p.get("lift_vs_false_positive") or 0
    fpr  = p.get("false_positive_rate") or 0
    art  = p.get("split_artifact_exposure") or 0
    if cnt == 0:
        return "no_4x_hits"
    if cnt < 2:
        return "low_count"
    if art > 0.8:
        return "split_contaminated"
    if fpr > 0.9:
        return "false_positive_contaminated"
    if lift < 1.0:
        return "low_lift"
    return "unknown"


_RANKING_FORMULA_VERSION = "balanced_reliability_v2"

_RELIABILITY_SCORE_LEGEND = {
    "formula": (
        "0.40*support_score + 0.25*fp_quality + 0.20*lift_score + 0.15*recall_score - split_penalty"
    ),
    "components": {
        "support_score": "min(count_all_4x / 10, 1.0)",
        "fp_quality":    "1.0 - min(false_positive_rate, 1.0)",
        "lift_score":    "log1p(min(lift_vs_false_positive, 20)) / log1p(20)",
        "recall_score":  "min(recall_all_4x, 1.0)",
        "split_penalty": "min(split_artifact_exposure, 1.0) * 0.25",
    },
    "caps": [
        "count_all_4x < 4  => cap 0.35",
        "count_all_4x 4–7  => cap 0.55",
        "false_positive_rate > 0.25 => cap 0.60",
        "split_artifact_exposure > 0.50 => cap 0.45",
    ],
    "range": "0.0 – 1.0",
    "version": _RANKING_FORMULA_VERSION,
}


def _reliability_score(p: dict) -> float:
    cnt  = p.get("count_all_4x") or 0
    lift = p.get("lift_vs_false_positive") or 0
    fpr  = p.get("false_positive_rate") or 0
    rec  = p.get("recall_all_4x") or 0
    art  = p.get("split_artifact_exposure") or 0

    support_score = min(cnt / 10.0, 1.0)
    fp_quality    = 1.0 - min(fpr, 1.0)
    lift_capped   = min(lift, 20.0)
    lift_score    = math.log1p(lift_capped) / math.log1p(20.0)
    recall_score  = min(rec, 1.0)
    split_penalty = min(art, 1.0) * 0.25

    score = (
        0.40 * support_score
        + 0.25 * fp_quality
        + 0.20 * lift_score
        + 0.15 * recall_score
        - split_penalty
    )
    score = max(0.0, min(1.0, score))

    # Sample-size caps — prevent rare zero-FP patterns from dominating
    if cnt < 4:
        score = min(score, 0.35)
    elif cnt <= 7:
        score = min(score, 0.55)
    if fpr > 0.25:
        score = min(score, 0.60)
    if art > 0.50:
        score = min(score, 0.45)

    return round(score, 4)


# ── Section defaults ──────────────────────────────────────────────────────────

_SECTION_DEFAULTS: dict[str, dict] = {
    "full":     dict(include_rejected=True,  top_n=None, hide_split_contaminated=False),
    "compact":  dict(include_rejected=False, top_n=250,  hide_split_contaminated=True),
    "summary":  dict(include_rejected=False, top_n=None, hide_split_contaminated=False),
    "accepted": dict(include_rejected=False, top_n=1000, hide_split_contaminated=True),
    "rankings": dict(include_rejected=False, top_n=250,  hide_split_contaminated=True),
    "episodes": dict(include_rejected=False, top_n=None, hide_split_contaminated=False),
    "patterns": dict(include_rejected=True,  top_n=None, hide_split_contaminated=False),
    "rejected": dict(include_rejected=True,  top_n=None, hide_split_contaminated=False),
}

_VALID_SECTIONS = set(_SECTION_DEFAULTS)
_ACCEPTED_STATUSES = {"EXPERIMENTAL", "EXPERIMENTAL_RARE", "RESEARCH_ONLY",
                      "VALIDATED_WATCH", "WATCH_CANDIDATE", "VALIDATED_BUY_SUPPORT"}


# ── Shared notes ──────────────────────────────────────────────────────────────

_NOTES_BASE = {
    "reject_reason_legend": {
        "no_4x_hits":                 "Pattern matched 0 episodes in the 4x pump group",
        "low_count":                  "Pattern matched < 2 episodes in the 4x pump group",
        "split_contaminated":         "split_artifact_exposure > 0.8",
        "false_positive_contaminated": "false_positive_rate > 0.9",
        "low_lift":                   "lift_vs_false_positive < 1.0",
        "unknown":                    "Rejected for undetermined reason",
    },
    "source_type_legend": {
        "EPISODE_AGGREGATE": "V1A: pre-window aggregate features per episode",
        "SINGLE_BAR":        "V1B: single-bar symbolic tag signature",
        "TWO_BAR_SEQUENCE":  "V1B: rolling 2-bar tag sequence",
        "THREE_BAR_SEQUENCE": "V1B: rolling 3-bar tag sequence",
        "FIVE_BAR_SEQUENCE": "V1B: rolling 5-bar tag sequence",
        "TEN_BAR_CONTEXT":   "V1B: 10-bar rolling context window",
    },
    "status_legend": {
        "EXPERIMENTAL":      "count_all_4x >= 8, lift >= 1.5",
        "EXPERIMENTAL_RARE": "count_all_4x >= 4, lift >= 2.0",
        "RESEARCH_ONLY":     "count_all_4x >= 2, lift >= 1.0",
        "REJECT":            "Below thresholds — see reject_reason",
    },
    "diagnostic_label_legend": {
        "PX_MISSING_STRUCTURE_RESCUE": (
            "Episode has missing/zero structure score and no scanner pressure, "
            "but shows raw dryup/compression + D-confluence + trend evidence. "
            "PUMP_IGNORE→PUMP_SPECULATIVE rescue only."
        ),
        "PX_REVERSE_SPLIT_REGIME": (
            "Episode occurred near a recent or old reverse split. "
            "Treated as a separate speculative regime — not mixed with clean pump models."
        ),
        "SPLIT_ARTIFACT_EXCLUDED": (
            "Episode identified as split artifact — excluded from all pump watch routing."
        ),
    },
    "safety": (
        "IMPORTANT: Do NOT use any pattern to modify Scanner V2 BUY/WATCH/AVOID routing. "
        "All patterns are EXPERIMENTAL or RESEARCH_ONLY."
    ),
    "ranking_note": (
        "top_by_lift is research-only and unstable for small-sample zero-FP patterns. "
        "Use top_by_clean_reliability or top_by_supported_edge for signal selection."
    ),
}


def _notes(extra: str = "") -> dict:
    return {**_NOTES_BASE, "analysis_guidance": extra} if extra else dict(_NOTES_BASE)


# ── Pattern filtering ─────────────────────────────────────────────────────────

def _apply_pattern_filters(
    patterns: list[dict],
    source_type_filter: Optional[str],
    status_filter: Optional[str],
    min_4x_ep: Optional[int],
    max_fp_rate: Optional[float],
    hide_split_contaminated: bool,
) -> list[dict]:
    result = patterns
    if source_type_filter:
        result = [p for p in result if p.get("source_type") == source_type_filter]
    if status_filter:
        result = [p for p in result if p.get("status") == status_filter]
    if min_4x_ep is not None:
        result = [p for p in result if (p.get("count_all_4x") or 0) >= min_4x_ep]
    if max_fp_rate is not None:
        result = [p for p in result
                  if p.get("false_positive_rate") is None
                  or (p.get("false_positive_rate") or 1.0) <= max_fp_rate]
    if hide_split_contaminated:
        result = [p for p in result if (p.get("split_artifact_exposure") or 0) <= 0.50]
    return result


# ── Full discovery export builder ─────────────────────────────────────────────

async def build_discovery_export(
    run_id: int,
    section: str = "full",
    include_rejected: Optional[bool] = None,
    top_n: Optional[int] = None,
    source_type_filter: Optional[str] = None,
    status_filter: Optional[str] = None,
    min_4x_ep: Optional[int] = None,
    max_fp_rate: Optional[float] = None,
    hide_split_contaminated: Optional[bool] = None,
) -> dict:
    """
    Build a section-specific ChatGPT-ready export for one raw-pattern + discovery run.

    section values:
      full      — everything (large, ~15–20 MB)
      compact   — optimised for ChatGPT: accepted patterns, rankings, sample episodes
      summary   — metadata + counters only, no patterns or episodes
      accepted  — accepted patterns + ranking tables only
      rankings  — ranking tables only
      episodes  — episodes with all pump_watch/split fields
      patterns  — all patterns (accepted + rejected)
      rejected  — rejected patterns only

    Does NOT modify Scanner V2 routing or Pump Watch scoring.
    All output is EXPERIMENTAL / RESEARCH_ONLY.
    """
    from database import (
        get_raw_pattern_run,
        get_raw_pattern_episode_features,
        get_raw_pattern_comparisons,
        get_discovered_patterns,
    )
    from replay.pump_watch_scorer import (
        summarize_pump_watch_distribution,
        compute_pump_watch_calibration,
    )

    if section not in _VALID_SECTIONS:
        section = "full"

    # Apply section defaults for params that were left as None
    defs = _SECTION_DEFAULTS[section]
    if include_rejected    is None: include_rejected    = defs["include_rejected"]
    if top_n               is None: top_n               = defs["top_n"]
    if hide_split_contaminated is None: hide_split_contaminated = defs["hide_split_contaminated"]

    # ── Load data ─────────────────────────────────────────────────────────────
    run      = await get_raw_pattern_run(run_id)
    patterns = await get_discovered_patterns(run_id)
    prog     = get_discovery_progress()

    # Load episodes for any section that outputs pump_watch_summary/calibration
    need_episodes = section in ("full", "compact", "episodes", "summary")
    episodes = (
        await get_raw_pattern_episode_features(run_id, limit=10000)
        if need_episodes else []
    )
    comps = (
        await get_raw_pattern_comparisons(run_id)
        if section == "full" else []
    )
    registry = _load_registry() if section in ("full", "compact") else []

    # ── Normalise patterns ────────────────────────────────────────────────────
    for p in patterns:
        p["source_type"]       = _st_from_signal_id(p.get("signal_id"), p.get("source_type"))
        p["feature_family"]    = _ff_from_signal_id(p.get("signal_id"), p.get("feature_family"))
        p["reject_reason"]     = _reject_reason(p)
        p["reliability_score"] = _reliability_score(p)
        p["flow_subtype"]      = _infer_flow_subtype(p)

    # ── Shared derived objects ────────────────────────────────────────────────
    accepted_all = [p for p in patterns if p.get("status") in _ACCEPTED_STATUSES]
    rejected_all = [p for p in patterns if p.get("status") == "REJECT"]

    by_st_all: dict[str, list] = {}
    for p in patterns:
        by_st_all.setdefault(p["source_type"], []).append(p)
    st_counts = {st: len(lst) for st, lst in by_st_all.items()}

    CONTAM_THRESHOLD = 0.50
    contaminated_all = sorted(
        (p for p in patterns if (p.get("split_artifact_exposure") or 0) > CONTAM_THRESHOLD),
        key=lambda x: -(x.get("split_artifact_exposure") or 0),
    )

    # feature_family counts
    by_ff_all: dict[str, list] = {}
    for p in patterns:
        by_ff_all.setdefault(p["feature_family"], []).append(p)
    feature_family_counts = {ff: len(lst) for ff, lst in by_ff_all.items()}

    # Pump Watch summary (only when episodes were loaded)
    pw_dist        = summarize_pump_watch_distribution(episodes) if episodes else {}
    pw_calibration = compute_pump_watch_calibration(episodes)    if episodes else {}
    diagnostic_label_counts = pw_dist.get("diagnostic_label_counts", {}) if pw_dist else {}

    # Flow debug from in-memory progress
    flow_debug = {
        "flow_features_created":          prog.get("bar_snapshots_created", 0),
        "flow_sequences_created":         prog.get("flow_sequences_created", 0),
        "combined_sequences_created":     prog.get("combined_sequences_created", 0),
        "flow_patterns_created":          prog.get("flow_patterns_evaluated", 0),
        "combined_patterns_created":      prog.get("combined_patterns_evaluated", 0),
        "custom_sequences_created":       prog.get("custom_sequences_created", 0),
        "flow_custom_sequences_created":  prog.get("flow_custom_sequences_created", 0),
        "custom_patterns_created":        prog.get("custom_patterns_evaluated", 0),
        "flow_custom_patterns_created":   prog.get("flow_custom_patterns_evaluated", 0),
        "flow_tag_counts":                prog.get("flow_tag_counts", {}),
        "delta_note": (
            "All flow features are OHLCV-derived proxies, NOT true bid/ask delta. "
            "CLV, signed_volume_proxy, OBV, ADL, CMF computed from open/high/low/close/volume."
        ),
        "custom_signal_note": (
            "CUSTOM_SIGNAL family is RESEARCH_ONLY. "
            "Tags read from feature_json boolean flags pre-computed by upstream process. "
            "Run discovery with mode='custom' or mode='all' to populate."
        ),
    }

    group_counts = prog.get("group_counts") or {}
    discovery_status = {
        "episodes":         prog.get("episodes")              or len(episodes),
        "episodes_scored":  prog.get("episodes_scored")       or 0,
        "episode_patterns": prog.get("patterns_evaluated")    or st_counts.get("EPISODE_AGGREGATE", 0),
        "bar_patterns":     prog.get("bar_patterns_evaluated") or (len(patterns) - st_counts.get("EPISODE_AGGREGATE", 0)),
        "patterns_saved":   prog.get("patterns_saved")        or len(patterns),
        **group_counts,
    }

    debug = {
        "daily_rows":   prog.get("pre_daily_rows_loaded", 0),
        "snapshots":    prog.get("bar_snapshots_created", 0),
        "sequences":    prog.get("bar_sequences_created", 0),
        "rejected_low_count":                    prog.get("patterns_rejected_low_count", 0),
        "rejected_low_lift":                     prog.get("patterns_rejected_low_lift",  0),
        "rejected_split_artifact":               sum(1 for p in rejected_all if p.get("reject_reason") == "split_contaminated"),
        "rejected_false_positive_contamination": sum(1 for p in rejected_all if p.get("reject_reason") == "false_positive_contaminated"),
        "rejected_no_4x_hits":                   sum(1 for p in rejected_all if p.get("reject_reason") == "no_4x_hits"),
        "source_type_counts": st_counts,
    }

    summary_obj = {
        "total_patterns":    len(patterns),
        "accepted_patterns": len(accepted_all),
        "rejected_patterns": len(rejected_all),
        "source_type_counts": st_counts,
        "contaminated_count": len(contaminated_all),
    }

    split_contamination_summary = {
        "contaminated_pattern_count": len(contaminated_all),
        "threshold": CONTAM_THRESHOLD,
        "top_contaminated": [
            {"signal_id": p["signal_id"], "source_type": p["source_type"],
             "split_artifact_exposure": p.get("split_artifact_exposure"),
             "count_all_4x": p.get("count_all_4x"),
             "recommendation": "do_not_add_without_cleaning_split_episodes"}
            for p in contaminated_all[:20]
        ],
    }

    split_contamination_full = {
        "contaminated_pattern_count": len(contaminated_all),
        "threshold": CONTAM_THRESHOLD,
        "patterns": [
            {"signal_id": p["signal_id"], "source_type": p["source_type"],
             "split_artifact_exposure": p.get("split_artifact_exposure"),
             "count_all_4x": p.get("count_all_4x"),
             "count_false_positive": p.get("count_false_positive"),
             "recommendation": "do_not_add_without_cleaning_split_episodes"}
            for p in contaminated_all
        ],
    }

    bar_sequence_summary = {
        "daily_rows_loaded":     prog.get("pre_daily_rows_loaded", 0),
        "bar_snapshots_created": prog.get("bar_snapshots_created", 0),
        "bar_sequences_created": prog.get("bar_sequences_created", 0),
        "single_bar_patterns":   st_counts.get("SINGLE_BAR",        0),
        "two_bar_patterns":      st_counts.get("TWO_BAR_SEQUENCE",   0),
        "three_bar_patterns":    st_counts.get("THREE_BAR_SEQUENCE", 0),
        "five_bar_patterns":     st_counts.get("FIVE_BAR_SEQUENCE",  0),
        "ten_bar_patterns":      st_counts.get("TEN_BAR_CONTEXT",    0),
    }

    # ── Apply user filters to the working pattern set ─────────────────────────
    # Filters apply to accepted; rejected section gets all rejected regardless
    working = accepted_all if not include_rejected else patterns
    working = _apply_pattern_filters(
        working, source_type_filter, status_filter,
        min_4x_ep, max_fp_rate, hide_split_contaminated,
    )
    n = top_n or len(working)

    # ── Ranking tables (built from filtered working set) ──────────────────────
    def _top(lst, key, limit):
        return sorted(lst, key=key)[:limit]

    top_by_reliability = _top(
        working, lambda x: -(x["reliability_score"] or 0), min(100, n))
    top_by_lift = _top(
        (p for p in working if p.get("lift_vs_false_positive") is not None),
        lambda x: -(x["lift_vs_false_positive"] or 0), min(100, n))
    top_by_missed = _top(
        (p for p in working if (p.get("count_missed_4x") or 0) > 0),
        lambda x: -(x["count_missed_4x"] or 0), min(100, n))

    # Clean reliability: hide high-contamination + require minimum 4x sample
    top_by_clean_reliability = _top(
        [p for p in working
         if (p.get("split_artifact_exposure") or 0) <= 0.50
         and (p.get("count_all_4x") or 0) >= 4],
        lambda x: -(x["reliability_score"] or 0), min(100, n))

    # Supported edge: all quality gates met simultaneously
    top_by_supported_edge = _top(
        [p for p in working
         if (p.get("count_all_4x") or 0) >= 8
         and (p.get("lift_vs_false_positive") or 0) >= 1.5
         and (p.get("false_positive_rate") or 1.0) <= 0.25
         and (p.get("split_artifact_exposure") or 0) <= 0.50],
        lambda x: -(x["reliability_score"] or 0), min(100, n))

    # Clean missed-4x: exclude high FP rate and contaminated patterns
    top_by_missed_4x_clean = _top(
        [p for p in working
         if (p.get("count_missed_4x") or 0) > 0
         and (p.get("false_positive_rate") or 1.0) <= 0.35
         and (p.get("split_artifact_exposure") or 0) <= 0.50],
        lambda x: -(x["count_missed_4x"] or 0), min(100, n))

    by_st_working: dict[str, list] = {}
    for p in working:
        by_st_working.setdefault(p["source_type"], []).append(p)
    top_by_source_type = {
        st: _top(lst, lambda x: -(x.get("lift_vs_false_positive") or 0), 100)
        for st, lst in by_st_working.items()
    }

    # Flow-family rankings
    flow_working         = [p for p in working if p.get("feature_family") == "FLOW"]
    combined_working     = [p for p in working if p.get("feature_family") == "COMBINED"]
    custom_working       = [p for p in working if p.get("feature_family") == "CUSTOM_SIGNAL"]
    flow_custom_working  = [p for p in working if p.get("feature_family") == "FLOW_CUSTOM_COMBINED"]

    # Enrich calibration with pattern-level flow_subtype aggregation
    if pw_calibration:
        pw_calibration["by_flow_subtype"] = _compute_flow_subtype_calibration(
            flow_working + combined_working
        )

    # FLOW / Diagnostic replay impact analysis (research-only, Part 7)
    flow_scored_episodes: list = []
    flow_replay_analysis: dict = {}
    if episodes:
        try:
            from replay.flow_impact_analyzer import score_episodes_flow, build_flow_impact_report
            flow_scored_episodes = score_episodes_flow(episodes)
            flow_replay_analysis = build_flow_impact_report(
                flow_scored_episodes, flow_working + combined_working
            )
        except Exception as _fia_err:
            logger.warning("flow_impact_analyzer failed: %s", _fia_err)
            flow_scored_episodes = episodes

    # Curated FLOW replay analysis (research-only, Part 9)
    curated_scored_episodes: list = []
    curated_flow_analysis: dict = {}
    if episodes:
        try:
            from replay.curated_flow_analyzer import (
                score_episodes_curated_flow,
                build_curated_flow_replay_analysis,
            )
            curated_scored_episodes = score_episodes_curated_flow(
                flow_scored_episodes if flow_scored_episodes else episodes
            )
            curated_flow_analysis = build_curated_flow_replay_analysis(
                curated_scored_episodes, flow_working + combined_working
            )
        except Exception as _cfa_err:
            logger.warning("curated_flow_analyzer failed: %s", _cfa_err)
            curated_scored_episodes = flow_scored_episodes if flow_scored_episodes else episodes

    top_flow_by_clean_reliability = _top(
        [p for p in flow_working
         if (p.get("split_artifact_exposure") or 0) <= 0.50
         and (p.get("count_all_4x") or 0) >= 4],
        lambda x: -(x["reliability_score"] or 0), min(100, n))

    top_combined_by_clean_reliability = _top(
        [p for p in combined_working
         if (p.get("split_artifact_exposure") or 0) <= 0.50
         and (p.get("count_all_4x") or 0) >= 4],
        lambda x: -(x["reliability_score"] or 0), min(100, n))

    top_flow_by_missed_4x = _top(
        [p for p in flow_working
         if (p.get("count_missed_4x") or 0) > 0
         and (p.get("false_positive_rate") or 1.0) <= 0.35],
        lambda x: -(x["count_missed_4x"] or 0), min(100, n))

    top_combined_by_missed_4x = _top(
        [p for p in combined_working
         if (p.get("count_missed_4x") or 0) > 0
         and (p.get("false_positive_rate") or 1.0) <= 0.35],
        lambda x: -(x["count_missed_4x"] or 0), min(100, n))

    # Strict FLOW clean reliability: cnt>=8, fpr<=30%, exposure<=35%
    top_flow_clean_reliability = _top(
        [p for p in flow_working
         if (p.get("count_all_4x") or 0) >= 8
         and (p.get("false_positive_rate") or 1.0) <= 0.30
         and (p.get("split_artifact_exposure") or 0) <= 0.35],
        lambda x: -(x["reliability_score"] or 0), min(100, n))

    # Strict COMBINED clean reliability: same gates
    top_combined_clean_reliability = _top(
        [p for p in combined_working
         if (p.get("count_all_4x") or 0) >= 8
         and (p.get("false_positive_rate") or 1.0) <= 0.30
         and (p.get("split_artifact_exposure") or 0) <= 0.35],
        lambda x: -(x["reliability_score"] or 0), min(100, n))

    # Custom signal rankings
    top_custom_signal_clean_reliability = _top(
        [p for p in custom_working
         if (p.get("split_artifact_exposure") or 0) <= 0.50
         and (p.get("count_all_4x") or 0) >= 4],
        lambda x: -(x["reliability_score"] or 0), min(100, n))

    top_flow_custom_combined = _top(
        [p for p in flow_custom_working
         if (p.get("split_artifact_exposure") or 0) <= 0.50
         and (p.get("count_all_4x") or 0) >= 4],
        lambda x: -(x["reliability_score"] or 0), min(100, n))

    def _sig_has_tag(p: dict, tag: str) -> bool:
        """True if pattern signal_id or machine_conditions mention this tag."""
        if tag in (p.get("signal_id") or ""):
            return True
        mc = p.get("machine_conditions") or []
        if isinstance(mc, str):
            return tag in mc
        return any(tag in str(c) for c in mc)

    top_custom_l43_patterns = _top(
        [p for p in custom_working + flow_custom_working if _sig_has_tag(p, "L43")],
        lambda x: -(x["reliability_score"] or 0), min(50, n))

    top_custom_d_confluence_patterns = _top(
        [p for p in custom_working + flow_custom_working
         if any(_sig_has_tag(p, t) for t in ("D3_BEUP", "D4_BEUP", "D6_BEUP", "D3_L34", "D4_L34"))],
        lambda x: -(x["reliability_score"] or 0), min(50, n))

    top_custom_l_series_patterns = _top(
        [p for p in custom_working + flow_custom_working
         if any(_sig_has_tag(p, t) for t in ("L34", "L64", "L22"))
         and not _sig_has_tag(p, "L43")],
        lambda x: -(x["reliability_score"] or 0), min(50, n))

    # Subtype-specific FLOW rankings (sorted by reliability_score)
    top_flow_divergence = _top(
        [p for p in flow_working if p.get("flow_subtype") == "FLOW_DIVERGENCE"],
        lambda x: -(x["reliability_score"] or 0), min(50, n))

    top_flow_stress = _top(
        [p for p in flow_working if p.get("flow_subtype") == "FLOW_BEARISH_STRESS"],
        lambda x: -(x["reliability_score"] or 0), min(50, n))

    top_flow_absorption = _top(
        [p for p in flow_working if p.get("flow_subtype") == "FLOW_ABSORPTION"],
        lambda x: -(x["reliability_score"] or 0), min(50, n))

    # flow_subtype distribution across FLOW + COMBINED patterns
    flow_subtype_counts: dict[str, int] = {}
    for p in flow_working + combined_working:
        st = p.get("flow_subtype") or "N/A"
        flow_subtype_counts[st] = flow_subtype_counts.get(st, 0) + 1

    # ── Accepted sorted for section output ────────────────────────────────────
    accepted_sorted = sorted(
        working,
        key=lambda x: (-(x["reliability_score"] or 0),
                       -(x.get("count_all_4x") or 0),
                       (x.get("false_positive_rate") or 1.0)),
    )[:n]

    # ── Sample episodes for compact section ───────────────────────────────────
    # Prefer curated_scored_episodes (has all flow + curated_flow_* fields)
    _ep_src = curated_scored_episodes if curated_scored_episodes else (flow_scored_episodes if flow_scored_episodes else episodes)
    sample_episodes: dict = {}
    split_summary: dict = {}
    if _ep_src:
        sample_episodes = {
            "pump_watch_high": sorted(
                (ep for ep in _ep_src if ep.get("pump_watch_label") == "PUMP_WATCH_HIGH"),
                key=lambda x: -(x.get("pump_watch_score") or 0),
            )[:25],
            "missed_4x": [
                ep for ep in _ep_src
                if ep.get("group_type") == "4x_pump" and not ep.get("had_np_buy_candidate_pre")
            ][:25],
            "false_positive_high_score": sorted(
                (ep for ep in _ep_src if ep.get("group_type") == "false_positive"),
                key=lambda x: -(x.get("pump_watch_score") or 0),
            )[:25],
            "split_artifacts": [
                ep for ep in _ep_src if ep.get("split_artifact_risk")
            ][:25],
        }
        split_summary = {
            "split_artifact_count":      sum(1 for ep in _ep_src if ep.get("split_artifact_risk")),
            "recent_reverse_split_count": sum(1 for ep in _ep_src if ep.get("split_context") == "RECENT_REVERSE_SPLIT"),
            "old_reverse_split_count":   sum(1 for ep in _ep_src if ep.get("split_context") == "OLD_REVERSE_SPLIT"),
            "no_split_count":            sum(1 for ep in _ep_src if not ep.get("split_context") or ep.get("split_context") == "NO_SPLIT"),
        }

    exported_at = datetime.now(tz=timezone.utc).isoformat()

    # ── Section-specific assembly ─────────────────────────────────────────────

    if section == "summary":
        return {
            "export_type": "raw_pattern_discovery_summary",
            "section": "summary",
            "exported_at": exported_at,
            "run_id": run_id,
            "run": run,
            "discovery_status": discovery_status,
            "debug": debug,
            "flow_debug": flow_debug,
            "summary": summary_obj,
            "pump_watch_summary": pw_dist,
            "pump_watch_calibration": pw_calibration,
            "diagnostic_label_counts": diagnostic_label_counts,
            "patterns_by_source_type_counts": st_counts,
            "feature_family_counts": feature_family_counts,
            "flow_subtype_counts": flow_subtype_counts,
            "split_contamination_summary": split_contamination_summary,
            "bar_sequence_summary": bar_sequence_summary,
            "flow_replay_analysis": flow_replay_analysis,
            "curated_flow_replay_analysis": curated_flow_analysis,
            "custom_signal_patterns_created":   prog.get("custom_patterns_evaluated", 0),
            "flow_custom_patterns_created":     prog.get("flow_custom_patterns_evaluated", 0),
            "custom_signal_sequences_created":  prog.get("custom_sequences_created", 0),
            "ranking_formula_version": _RANKING_FORMULA_VERSION,
            "reliability_score_legend": _RELIABILITY_SCORE_LEGEND,
            "notes": _notes(),
        }

    if section == "accepted":
        return {
            "export_type": "raw_pattern_discovery_accepted",
            "section": "accepted",
            "exported_at": exported_at,
            "run_id": run_id,
            "run": run,
            "filters_applied": {
                "source_type": source_type_filter,
                "status": status_filter,
                "min_4x_ep": min_4x_ep,
                "max_fp_rate": max_fp_rate,
                "hide_split_contaminated": hide_split_contaminated,
                "top_n": n,
            },
            "accepted_patterns":                 accepted_sorted,
            "top_by_reliability":                top_by_reliability,
            "top_by_clean_reliability":          top_by_clean_reliability,
            "top_by_supported_edge":             top_by_supported_edge,
            "top_by_missed_4x":                 top_by_missed,
            "top_by_missed_4x_clean":           top_by_missed_4x_clean,
            "top_by_source_type":               top_by_source_type,
            "top_flow_by_clean_reliability":     top_flow_by_clean_reliability,
            "top_combined_by_clean_reliability": top_combined_by_clean_reliability,
            "top_flow_clean_reliability":        top_flow_clean_reliability,
            "top_combined_clean_reliability":    top_combined_clean_reliability,
            "top_flow_divergence":               top_flow_divergence,
            "top_flow_stress":                   top_flow_stress,
            "top_flow_absorption":               top_flow_absorption,
            "top_flow_by_missed_4x":             top_flow_by_missed_4x,
            "top_combined_by_missed_4x":         top_combined_by_missed_4x,
            "feature_family_counts":             feature_family_counts,
            "flow_subtype_counts":               flow_subtype_counts,
            "ranking_formula_version":           _RANKING_FORMULA_VERSION,
            "reliability_score_legend":          _RELIABILITY_SCORE_LEGEND,
            "notes": _notes(
                "accepted_patterns sorted by reliability_score desc. "
                "Use top_flow_clean_reliability (cnt>=8, fpr<=30%, exposure<=35%) for FLOW signal selection. "
                "top_by_lift is research-only and unstable for zero-FP patterns. "
                "Flow patterns (top_flow_*) are OHLCV proxies, NOT true bid/ask delta. "
                "All patterns are EXPERIMENTAL or RESEARCH_ONLY."
            ),
        }

    if section == "rankings":
        return {
            "export_type": "raw_pattern_discovery_rankings",
            "section": "rankings",
            "exported_at": exported_at,
            "run_id": run_id,
            "run": run,
            "top_by_reliability":                 top_by_reliability,
            "top_by_clean_reliability":           top_by_clean_reliability,
            "top_by_supported_edge":              top_by_supported_edge,
            "top_by_lift":                        top_by_lift,
            "top_by_missed_4x":                  top_by_missed,
            "top_by_missed_4x_clean":            top_by_missed_4x_clean,
            "top_by_source_type":                top_by_source_type,
            "top_flow_by_clean_reliability":     top_flow_by_clean_reliability,
            "top_combined_by_clean_reliability": top_combined_by_clean_reliability,
            "top_flow_clean_reliability":        top_flow_clean_reliability,
            "top_combined_clean_reliability":    top_combined_clean_reliability,
            "top_flow_divergence":               top_flow_divergence,
            "top_flow_stress":                   top_flow_stress,
            "top_flow_absorption":               top_flow_absorption,
            "top_flow_by_missed_4x":             top_flow_by_missed_4x,
            "top_combined_by_missed_4x":         top_combined_by_missed_4x,
            "feature_family_counts":             feature_family_counts,
            "flow_subtype_counts":               flow_subtype_counts,
            "split_contamination":               split_contamination_summary,
            "ranking_formula_version":           _RANKING_FORMULA_VERSION,
            "reliability_score_legend":          _RELIABILITY_SCORE_LEGEND,
            "notes": _notes(
                "IMPORTANT: top_by_lift is dominated by rare zero-FP patterns with low sample count. "
                "Use top_flow_clean_reliability (cnt>=8, fpr<=30%, exposure<=35%) for FLOW signal selection. "
                "top_flow_divergence/stress/absorption filter by flow_subtype. "
                "Flow patterns (top_flow_*) are OHLCV proxies, NOT true bid/ask delta. "
                "top_by_supported_edge requires count_all_4x>=8, lift>=1.5, fpr<=25%, exposure<=50%."
            ),
        }

    if section == "episodes":
        return {
            "export_type": "raw_pattern_discovery_episodes",
            "section": "episodes",
            "exported_at": exported_at,
            "run_id": run_id,
            "run": run,
            "episodes": _ep_src or episodes,
            "pump_watch_summary": pw_dist,
            "split_summary": split_summary,
            "curated_flow_replay_analysis": curated_flow_analysis,
            "notes": _notes(),
        }

    if section == "patterns":
        return {
            "export_type": "raw_pattern_discovery_patterns",
            "section": "patterns",
            "exported_at": exported_at,
            "run_id": run_id,
            "run": run,
            "summary": summary_obj,
            "discovered_patterns": patterns,
            "patterns_by_source_type": by_st_all,
            "notes": _notes(),
        }

    if section == "rejected":
        return {
            "export_type": "raw_pattern_discovery_rejected",
            "section": "rejected",
            "exported_at": exported_at,
            "run_id": run_id,
            "run": run,
            "rejected_patterns": rejected_all,
            "notes": _notes(),
        }

    if section == "compact":
        return {
            "export_type": "raw_pattern_discovery_compact",
            "section": "compact",
            "exported_at": exported_at,
            "run_id": run_id,
            "run": run,
            "discovery_status": discovery_status,
            "debug": debug,
            "flow_debug": flow_debug,
            "pump_watch_summary": pw_dist,
            "pump_watch_calibration": pw_calibration,
            "diagnostic_label_counts": diagnostic_label_counts,
            "patterns_by_source_type_counts": st_counts,
            "feature_family_counts":             feature_family_counts,
            "flow_subtype_counts":               flow_subtype_counts,
            "accepted_patterns":                 accepted_sorted[:1000],
            "top_by_reliability":                top_by_reliability,
            "top_by_clean_reliability":          top_by_clean_reliability,
            "top_by_supported_edge":             top_by_supported_edge,
            "top_by_missed_4x":                 top_by_missed,
            "top_by_missed_4x_clean":           top_by_missed_4x_clean,
            "top_by_source_type":               top_by_source_type,
            "top_flow_by_clean_reliability":     top_flow_by_clean_reliability,
            "top_combined_by_clean_reliability": top_combined_by_clean_reliability,
            "top_flow_clean_reliability":        top_flow_clean_reliability,
            "top_combined_clean_reliability":    top_combined_clean_reliability,
            "top_flow_divergence":               top_flow_divergence,
            "top_flow_stress":                   top_flow_stress,
            "top_flow_absorption":               top_flow_absorption,
            "top_flow_by_missed_4x":             top_flow_by_missed_4x,
            "top_combined_by_missed_4x":         top_combined_by_missed_4x,
            "split_contamination_summary":       split_contamination_summary,
            "sample_episodes":                   sample_episodes,
            "flow_replay_analysis":              flow_replay_analysis,
            "curated_flow_replay_analysis":      curated_flow_analysis,
            "top_custom_signal_clean_reliability": top_custom_signal_clean_reliability,
            "top_flow_custom_combined":          top_flow_custom_combined,
            "top_custom_l43_patterns":           top_custom_l43_patterns,
            "top_custom_d_confluence_patterns":  top_custom_d_confluence_patterns,
            "top_custom_l_series_patterns":      top_custom_l_series_patterns,
            "registry_snapshot":                 registry,
            "ranking_formula_version":           _RANKING_FORMULA_VERSION,
            "reliability_score_legend":          _RELIABILITY_SCORE_LEGEND,
            "notes": _notes(
                "Compact export: accepted patterns only (max 1000), sample episodes (top 25 per group). "
                "For all episodes use section=episodes. For rejected patterns use section=rejected. "
                "Use top_flow_clean_reliability (cnt>=8, fpr<=30%, exposure<=35%) for FLOW signal selection. "
                "top_by_lift is research-only — unstable for zero-FP patterns. "
                "Flow patterns (top_flow_*) are OHLCV proxies, NOT true bid/ask delta. "
                "All patterns are EXPERIMENTAL or RESEARCH_ONLY."
            ),
        }

    # section == "full" (default)
    return {
        "export_type": "raw_pattern_study_with_discovery",
        "section": "full",
        "exported_at": exported_at,
        "run_id": run_id,
        "run": run,
        "discovery_status": discovery_status,
        "debug": debug,
        "flow_debug": flow_debug,
        "summary": summary_obj,
        "episodes": _ep_src or episodes,
        "comparisons": comps,
        "pump_watch_summary": pw_dist,
        "pump_watch_calibration": pw_calibration,
        "diagnostic_label_counts": diagnostic_label_counts,
        "feature_family_counts":                 feature_family_counts,
        "flow_subtype_counts":                   flow_subtype_counts,
        "discovered_patterns":                   patterns if include_rejected else accepted_all,
        "accepted_patterns":                     accepted_all,
        "rejected_patterns":                     rejected_all if include_rejected else [],
        "patterns_by_source_type":               by_st_all,
        "top_by_lift":                           top_by_lift,
        "top_by_missed_4x":                     top_by_missed,
        "top_by_reliability":                    top_by_reliability,
        "top_by_clean_reliability":              top_by_clean_reliability,
        "top_by_supported_edge":                 top_by_supported_edge,
        "top_by_missed_4x_clean":               top_by_missed_4x_clean,
        "top_by_source_type":                    top_by_source_type,
        "top_flow_by_clean_reliability":         top_flow_by_clean_reliability,
        "top_combined_by_clean_reliability":     top_combined_by_clean_reliability,
        "top_flow_clean_reliability":            top_flow_clean_reliability,
        "top_combined_clean_reliability":        top_combined_clean_reliability,
        "top_flow_divergence":                   top_flow_divergence,
        "top_flow_stress":                       top_flow_stress,
        "top_flow_absorption":                   top_flow_absorption,
        "top_flow_by_missed_4x":                 top_flow_by_missed_4x,
        "top_combined_by_missed_4x":             top_combined_by_missed_4x,
        "split_contamination":                   split_contamination_full,
        "bar_sequence_summary":                  bar_sequence_summary,
        "flow_replay_analysis":                  flow_replay_analysis,
        "curated_flow_replay_analysis":          curated_flow_analysis,
        "top_custom_signal_clean_reliability":   top_custom_signal_clean_reliability,
        "top_flow_custom_combined":              top_flow_custom_combined,
        "top_custom_l43_patterns":               top_custom_l43_patterns,
        "top_custom_d_confluence_patterns":      top_custom_d_confluence_patterns,
        "top_custom_l_series_patterns":          top_custom_l_series_patterns,
        "registry_snapshot":                     registry,
        "ranking_formula_version":               _RANKING_FORMULA_VERSION,
        "reliability_score_legend":              _RELIABILITY_SCORE_LEGEND,
        "notes": _notes(
            "Full export includes all patterns (accepted + rejected), all episodes, comparisons. "
            "Use top_flow_clean_reliability (cnt>=8, fpr<=30%, exposure<=35%) for FLOW signal selection. "
            "top_by_lift is research-only and unstable for small-sample zero-FP patterns. "
            "Flow patterns (top_flow_*) are OHLCV proxies, NOT true bid/ask delta. "
            "All patterns are EXPERIMENTAL or RESEARCH_ONLY."
        ),
    }
