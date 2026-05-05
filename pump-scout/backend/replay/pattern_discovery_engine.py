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
import os
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_REGISTRY_PATH = os.path.join(
    os.path.dirname(__file__), "..", "discovered_signal_registry.json"
)

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
    "patterns_evaluated": 0,
    "patterns_experimental": 0,
    "bar_patterns_evaluated": 0,
    "bar_patterns_experimental": 0,
    "patterns_rejected_low_count": 0,
    "patterns_rejected_low_lift": 0,
    "patterns_saved": 0,
    "episodes_scored": 0,
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
            "pump_watch_score":        ep.get("pump_watch_score"),
            "pump_watch_label":        ep.get("pump_watch_label"),
            "pump_watch_reasons":      json.dumps(ep.get("pump_watch_reasons") or []),
            "pump_watch_risk_flags":   json.dumps(ep.get("pump_watch_risk_flags") or []),
            "pump_watch_pattern_ids":  json.dumps(ep.get("pump_watch_pattern_ids") or []),
            "pump_watch_split_context": ep.get("pump_watch_split_context"),
            "pump_watch_confidence":   ep.get("pump_watch_confidence"),
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
) -> tuple[list[dict], dict]:
    """
    Load daily bar rows, build snapshots + sequences, mine bar patterns.

    Returns (bar_candidates, bar_sequences_by_group).
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

    # Build sequences per group
    _GROUPS = ["missed_4x_pump", "detected_4x_pump", "false_positive",
               "normal_winner", "split_artifact"]

    bar_sequences_by_group: dict[str, list[dict]] = {g: [] for g in _GROUPS}

    total_snapshots = 0
    for grp in _GROUPS:
        episodes = dataset.get(grp) or []
        for ep in episodes:
            ep_id      = ep.get("episode_id") or ep.get("id")
            daily_rows = daily_by_episode.get(ep_id, [])
            if not daily_rows:
                continue
            snaps = build_bar_feature_snapshots_for_episode(ep, daily_rows)
            if not snaps:
                continue
            total_snapshots += len(snaps)
            seqs = build_bar_sequences(snaps, windows=windows)
            bar_sequences_by_group[grp].extend(seqs)

    total_sequences = sum(len(v) for v in bar_sequences_by_group.values())
    _discovery_progress["bar_snapshots_created"] = total_snapshots
    _discovery_progress["bar_sequences_created"] = total_sequences
    logger.info(
        f"[DISCOVERY/V1B] run={run_id}: {total_snapshots} bar snapshots, "
        f"{total_sequences} sequences built"
    )

    _discovery_progress["phase"] = "MINING_BAR_PATTERNS"
    bar_candidates = mine_bar_patterns(
        bar_sequences_by_group=bar_sequences_by_group,
        windows=windows,
    )

    _discovery_progress["bar_patterns_evaluated"]   = len(bar_candidates)
    _discovery_progress["bar_patterns_experimental"] = sum(
        1 for c in bar_candidates if c["status"] in ("EXPERIMENTAL", "EXPERIMENTAL_RARE")
    )
    logger.info(
        f"[DISCOVERY/V1B] run={run_id}: {len(bar_candidates)} bar patterns | "
        f"experimental={_discovery_progress['bar_patterns_experimental']}"
    )

    return bar_candidates, bar_sequences_by_group


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
    windows               : bar-sequence window sizes (only used when mode
                            includes bar_sequence)
    exclude_split_artifacts : if True, split_artifact episodes are excluded
                              from episode-level mining counts (still kept
                              in a separate group for exposure stats)

    Returns
    -------
    Summary dict with status, episodes_loaded, patterns_evaluated, etc.
    """
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
        "bar_patterns_evaluated":    0,
        "bar_patterns_experimental": 0,
        "patterns_rejected_low_count": 0,
        "patterns_rejected_low_lift": 0,
        "patterns_saved": 0,
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

        if mode in ("episode_aggregate", "both"):
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

        # ── Phase 3: Bar-sequence pattern mining (V1B) ────────────────────────
        if mode in ("bar_sequence", "both"):
            bar_candidates, bar_sequences_by_group = await _run_bar_sequence_pipeline(
                run_id=run_id,
                dataset=dataset,
                windows=windows,
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
