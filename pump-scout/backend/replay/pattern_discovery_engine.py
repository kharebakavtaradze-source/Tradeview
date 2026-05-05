"""
Pattern Discovery Engine — orchestrates the full discovery pipeline.

Pipeline:
  1. Load missed pump dataset from DB (raw_pattern_episode_features)
  2. Run pattern miner on episode-level features
  3. Compute pump watch scores for all episodes
  4. Update discovered_signal_registry with new candidates
  5. Persist pump watch scores back to DB
  6. Generate structured discovery report

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

# In-memory progress tracker (parallel to pump_study_engine pattern)
_discovery_progress: dict = {
    "running":    False,
    "run_id":     None,
    "phase":      None,
    "episodes":   0,
    "patterns_evaluated": 0,
    "patterns_experimental": 0,
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
            # Update stats from this run
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
        else:
            # New entry
            new_entry = {
                "signal_id":               sid,
                "signal_name":             sid,
                "family":                  cand.get("family"),
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
            by_id[sid] = new_entry

    return list(by_id.values())


# ── DB persistence helpers ────────────────────────────────────────────────────

async def _persist_pump_watch_scores(run_id: int, scored_episodes: list[dict]) -> int:
    """
    Write pump watch scores back to raw_pattern_episode_features.
    Returns number of rows updated.
    """
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
    """
    Upsert pattern candidates into the pattern_discovery_results table.
    Returns number saved.
    """
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


# ── Main pipeline ─────────────────────────────────────────────────────────────

async def run_pattern_discovery(run_id: int) -> dict:
    """
    Full discovery pipeline for one raw_pattern_study run_id.

    Returns a summary dict with:
      status, episodes_loaded, patterns_evaluated, patterns_experimental,
      episodes_scored, pump_watch_distribution, top_patterns, feature_separability
    """
    global _discovery_progress

    if _discovery_progress["running"]:
        return {"status": "ALREADY_RUNNING", "run_id": _discovery_progress["run_id"]}

    _discovery_progress.update({
        "running":    True,
        "run_id":     run_id,
        "phase":      "LOADING",
        "error":      None,
        "started_at": datetime.now(tz=timezone.utc).isoformat(),
        "finished_at": None,
    })

    try:
        # ── Phase 1: Load dataset ─────────────────────────────────────────────
        from replay.missed_pump_dataset import load_dataset_for_run
        _discovery_progress["phase"] = "LOADING_DATASET"

        dataset = await load_dataset_for_run(run_id)
        if not dataset:
            raise ValueError(f"No episodes found for run_id={run_id}")

        summary = dataset.get("summary") or {}
        total_episodes = summary.get("total_episodes", 0)
        _discovery_progress["episodes"] = total_episodes

        logger.info(
            f"[DISCOVERY] run={run_id}: loaded {total_episodes} episodes | "
            f"missed={summary.get('missed_4x_pump_count')} "
            f"detected={summary.get('detected_4x_pump_count')} "
            f"fp={summary.get('false_positive_count')} "
            f"art={summary.get('split_artifact_count')}"
        )

        # ── Phase 2: Pattern mining ───────────────────────────────────────────
        from replay.pattern_miner import mine_patterns, compute_feature_separability
        _discovery_progress["phase"] = "PATTERN_MINING"

        candidates = mine_patterns(dataset)
        _discovery_progress["patterns_evaluated"] = len(candidates)
        _discovery_progress["patterns_experimental"] = sum(
            1 for c in candidates if c["status"] in ("EXPERIMENTAL", "EXPERIMENTAL_RARE")
        )

        feature_sep = compute_feature_separability(dataset)

        logger.info(
            f"[DISCOVERY] run={run_id}: {len(candidates)} patterns evaluated | "
            f"experimental={_discovery_progress['patterns_experimental']}"
        )

        # ── Phase 3: Pump Watch scoring ───────────────────────────────────────
        from replay.pump_watch_scorer import score_episodes, summarize_pump_watch_distribution
        _discovery_progress["phase"] = "PUMP_WATCH_SCORING"

        # Build flat episode list for scoring
        all_episodes_raw: list[dict] = []
        from database import get_raw_pattern_episode_features
        all_episodes_raw = await get_raw_pattern_episode_features(run_id=run_id, limit=10000)

        scored = score_episodes(all_episodes_raw)
        _discovery_progress["episodes_scored"] = len(scored)

        pw_distribution = summarize_pump_watch_distribution(scored)

        # ── Phase 4: Persist pump watch scores ────────────────────────────────
        _discovery_progress["phase"] = "PERSISTING_SCORES"
        updated = await _persist_pump_watch_scores(run_id, scored)
        logger.info(f"[DISCOVERY] run={run_id}: persisted pump_watch scores for {updated} episodes")

        # ── Phase 5: Persist pattern candidates ───────────────────────────────
        _discovery_progress["phase"] = "PERSISTING_PATTERNS"
        saved_patterns = await _persist_pattern_candidates(run_id, candidates)
        logger.info(f"[DISCOVERY] run={run_id}: persisted {saved_patterns} pattern rows")

        # ── Phase 6: Update registry ──────────────────────────────────────────
        _discovery_progress["phase"] = "UPDATING_REGISTRY"
        existing_registry = _load_registry()
        # Only merge EXPERIMENTAL or EXPERIMENTAL_RARE patterns into registry
        registry_candidates = [
            c for c in candidates
            if c["status"] in ("EXPERIMENTAL", "EXPERIMENTAL_RARE", "RESEARCH_ONLY")
        ]
        merged_registry = _merge_registry(existing_registry, registry_candidates, run_id)
        _save_registry(merged_registry)
        logger.info(
            f"[DISCOVERY] run={run_id}: registry updated — "
            f"{len(merged_registry)} total signals"
        )

        # ── Phase 7: Build report ─────────────────────────────────────────────
        _discovery_progress["phase"] = "BUILDING_REPORT"
        from replay.pattern_discovery_report import build_discovery_report
        report = build_discovery_report(
            run_id=run_id,
            dataset_summary=summary,
            pattern_candidates=candidates,
            feature_separability=feature_sep,
            pump_watch_distribution=pw_distribution,
        )

        _discovery_progress.update({
            "running":    False,
            "phase":      "COMPLETE",
            "finished_at": datetime.now(tz=timezone.utc).isoformat(),
        })

        return {
            "status":                  "COMPLETE",
            "run_id":                  run_id,
            "episodes_loaded":         total_episodes,
            "patterns_evaluated":      len(candidates),
            "patterns_experimental":   _discovery_progress["patterns_experimental"],
            "episodes_scored":         len(scored),
            "pump_watch_distribution": pw_distribution,
            "top_patterns":            [c for c in candidates if c["status"] in ("EXPERIMENTAL", "EXPERIMENTAL_RARE")][:10],
            "feature_separability":    feature_sep[:20],
            "dataset_summary":         summary,
            "report":                  report,
            "registry_total_signals":  len(merged_registry),
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
    """
    Return the latest discovery results for a run_id from the DB.
    """
    from database import get_discovered_patterns, get_raw_pattern_episode_features
    from replay.pump_watch_scorer import summarize_pump_watch_distribution

    try:
        patterns  = await get_discovered_patterns(run_id)
        episodes  = await get_raw_pattern_episode_features(run_id=run_id, limit=10000)
        pw_dist   = summarize_pump_watch_distribution(episodes)

        return {
            "run_id":                  run_id,
            "patterns":                patterns,
            "pump_watch_distribution": pw_dist,
            "registry":                _load_registry(),
        }
    except Exception as exc:
        logger.error(f"get_discovery_results({run_id}): {exc}")
        return {"run_id": run_id, "error": str(exc)}
