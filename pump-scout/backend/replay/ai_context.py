"""
Research memory builder for AI Journal.

Reads the latest replay, raw pattern, and pump study data and formats
a compact evidence digest (~600 tokens) for injection into AI journal prompts.
Claude can then correlate individual journal entries with statistical ground truth.

Cache: each source refreshes every 2 hours so repeated journal insight calls
don't re-query the DB. Call invalidate_cache() after new runs complete.
"""
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

_CACHE_TTL = 7200   # 2 hours
_cache: dict = {}


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _set_cache(key: str, data: dict) -> None:
    _cache[key] = {"data": data, "ts": time.time()}


def _get_cache(key: str) -> Optional[dict]:
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < _CACHE_TTL:
        return entry["data"]
    return None


def invalidate_cache() -> None:
    """Call after any new replay / pattern / pump study run completes."""
    _cache.clear()


# ── Formatting helpers ────────────────────────────────────────────────────────

def _f(v, digits=1) -> str:
    if v is None:
        return "?"
    try:
        return f"{float(v):+.{digits}f}"
    except (TypeError, ValueError):
        return str(v)


def _pct(v) -> str:
    if v is None:
        return " ?%"
    try:
        return f"{float(v):3.0f}%"
    except (TypeError, ValueError):
        return " ?%"


# ── Perf stats ────────────────────────────────────────────────────────────────

def _compute_perf_rows(
    candidates: list[dict],
    out_map: dict[int, float],   # candidate_id → 5d return_pct
    bucket_fn,
    min_n: int = 3,
) -> list[dict]:
    """
    Compute per-bucket win-rate and average 5d return.
    Returns list sorted by avg_ret descending.
    """
    buckets: dict[str, list[float]] = {}
    for c in candidates:
        cid = c.get("id")
        if cid is None or cid not in out_map:
            continue
        ret = out_map[cid]
        if ret is None:
            continue
        bk = bucket_fn(c) or "UNKNOWN"
        buckets.setdefault(bk, []).append(ret)

    rows = []
    for bk, returns in buckets.items():
        n = len(returns)
        if n < min_n:
            continue
        win_rate = sum(1 for r in returns if r > 0) / n * 100
        avg_ret  = sum(returns) / n
        rows.append({"bucket": bk, "n": n, "win_rate": win_rate, "avg_ret": avg_ret})
    rows.sort(key=lambda x: x["avg_ret"], reverse=True)
    return rows


def _fmt_perf(rows: list[dict], width: int = 26, top: int = 8) -> str:
    if not rows:
        return "  (no data)\n"
    lines = []
    for r in rows[:top]:
        bk  = r["bucket"]
        wr  = _pct(r["win_rate"])
        avg = _f(r["avg_ret"])
        n   = r["n"]
        lines.append(f"  {bk:<{width}} {wr}WR {avg:>6}% avg  n={n}")
    return "\n".join(lines)


# ── Replay digest ─────────────────────────────────────────────────────────────

async def _load_replay_digest() -> tuple[str, Optional[dict]]:
    cached = _get_cache("replay")
    if cached:
        return cached["text"], cached["meta"]
    try:
        from database import get_replay_history, get_replay_candidates, get_replay_outcomes
        runs = await get_replay_history(limit=5)
        run  = next((r for r in runs if r.get("status") == "completed"), None)
        if not run:
            return "", None

        run_id   = run["id"]
        run_date = (run.get("created_at") or "")[:10]
        total    = run.get("total_candidates", 0)

        candidates = await get_replay_candidates(run_id, limit=5000)
        outcomes   = await get_replay_outcomes(run_id)
        if not candidates or not outcomes:
            return "", None

        # Build 5d outcome map: candidate_id → return_pct
        out_map: dict[int, float] = {
            o["replay_candidate_id"]: o["return_pct"]
            for o in outcomes
            if o.get("horizon") == "5d" and o.get("return_pct") is not None
        }

        # ── sequence performance ──────────────────────────────────────────────
        seq_rows = _compute_perf_rows(
            candidates, out_map,
            lambda c: c.get("new_pump_sequence_label") or "NONE",
        )

        # ── base quality ──────────────────────────────────────────────────────
        def _bq_bucket(c):
            s = c.get("np_base_quality_score")
            if s is None:  return None
            if s >= 60:    return "HIGH(≥60)"
            if s >= 35:    return "MEDIUM(35-59)"
            return "LOW(<35)"

        bq_rows = [r for r in _compute_perf_rows(candidates, out_map, _bq_bucket)
                   if r["bucket"] != "UNKNOWN"]
        bq_order = {"HIGH(≥60)": 0, "MEDIUM(35-59)": 1, "LOW(<35)": 2}
        bq_rows.sort(key=lambda x: bq_order.get(x["bucket"], 9))

        # ── fake trigger risk ─────────────────────────────────────────────────
        ftr_rows = _compute_perf_rows(
            candidates, out_map,
            lambda c: c.get("np_fake_trigger_risk") or "LOW",
        )
        ftr_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        ftr_rows.sort(key=lambda x: ftr_order.get(x["bucket"], 9))

        # ── NP state ─────────────────────────────────────────────────────────
        state_order = ["TRIGGERED", "PRE_TRIGGER", "CONFIRMED", "FAILED_SETUP",
                       "BROKEN_SETUP", "OVEREXTENDED", "IMPULSE", "NEUTRAL"]
        state_rows = [r for r in _compute_perf_rows(
            candidates, out_map, lambda c: c.get("np_state") or "NEUTRAL"
        ) if r["n"] >= 5]
        state_rows.sort(key=lambda x: state_order.index(x["bucket"])
                        if x["bucket"] in state_order else 99)

        # ── CE state (compression/expansion) ─────────────────────────────────
        ce_rows = _compute_perf_rows(
            candidates, out_map,
            lambda c: c.get("np_compression_expansion_state") or "NONE",
        )
        ce_order = ["ACCUMULATION_READY", "EXPANSION_START", "COMPRESSED_BASE",
                    "OVERHEATED_EXPANSION", "NONE"]
        ce_rows = [r for r in ce_rows if r["n"] >= 5]
        ce_rows.sort(key=lambda x: ce_order.index(x["bucket"])
                     if x["bucket"] in ce_order else 99)

        # ── D/WLNBB combo performance (from snapshot JSON) ────────────────────
        def _dw_combo_bucket(c: dict) -> str | None:
            snap = c.get("snapshot") or {}
            new_pump = snap.get("new_pump") or {}
            # d_confluence_type_v2 is the primary combo classifier
            combo = (new_pump.get("d_confluence_type_v2")
                     or snap.get("d_confluence_type_v2"))
            if combo and combo != "NONE":
                return combo
            return None

        dw_rows = _compute_perf_rows(candidates, out_map, _dw_combo_bucket, min_n=3)
        # Sort best WR first for AI readability
        dw_rows.sort(key=lambda x: x["win_rate"], reverse=True)

        # ── expansion timing risk ─────────────────────────────────────────────
        etr_rows = _compute_perf_rows(
            candidates, out_map,
            lambda c: c.get("np_expansion_timing_risk") or "LOW",
        )
        etr_order = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}
        etr_rows.sort(key=lambda x: etr_order.get(x["bucket"], 9))

        # ── standout tickers ──────────────────────────────────────────────────
        scored = [(c, out_map.get(c["id"])) for c in candidates if c.get("id") in out_map]

        worst = sorted([(c, r) for c, r in scored if r is not None and r < -3],
                       key=lambda x: x[1])[:3]
        best  = sorted([(c, r) for c, r in scored if r is not None and r > 8],
                       key=lambda x: x[1], reverse=True)[:3]

        # ── build text ────────────────────────────────────────────────────────
        lines = [
            f"── REPLAY RUN #{run_id}  ({run_date})  {total} candidates  horizon=5d ──",
        ]

        if seq_rows:
            lines += ["", "SEQUENCE PERFORMANCE:", _fmt_perf(seq_rows, width=26)]

        if bq_rows:
            lines += ["", "BASE QUALITY:", _fmt_perf(bq_rows, width=14)]

        if ftr_rows:
            lines += ["", "FAKE TRIGGER RISK:", _fmt_perf(ftr_rows, width=10)]

        if state_rows:
            lines += ["", "NP STATE:", _fmt_perf(state_rows, width=14)]

        if ce_rows:
            lines += ["", "CE STATE (compression/expansion):", _fmt_perf(ce_rows, width=22)]

        if etr_rows:
            lines += ["", "EXPANSION TIMING RISK:", _fmt_perf(etr_rows, width=10)]

        if dw_rows:
            lines += ["", "D/WLNBB COMBO PERFORMANCE (top by WR, research only):"]
            lines.append(_fmt_perf(dw_rows, width=28, top=10))

        if worst:
            lines += ["", "FALSE POSITIVE EXAMPLES (worst 5d):"]
            for c, ret in worst:
                sym = c.get("symbol", "?")
                seq = (c.get("new_pump_sequence_label") or "?")[:22]
                bq  = c.get("np_base_quality_score")
                ftr = c.get("np_fake_trigger_risk") or "?"
                bq_s = f" bq={bq}" if bq is not None else ""
                lines.append(f"  {sym}: {seq}{bq_s} ftr={ftr}  → {ret:+.1f}%")

        if best:
            lines += ["", "TOP WINNERS (strongest 5d):"]
            for c, ret in best:
                sym  = c.get("symbol", "?")
                seq  = (c.get("new_pump_sequence_label") or "?")[:22]
                bq   = c.get("np_base_quality_score")
                bq_s = f" bq={bq}" if bq is not None else ""
                lines.append(f"  {sym}: {seq}{bq_s}  → {ret:+.1f}%")

        text = "\n".join(lines)
        meta = {"run_id": run_id, "date": run_date, "candidates": total}
        _set_cache("replay", {"text": text, "meta": meta})
        return text, meta

    except Exception as exc:
        logger.warning(f"[ai_context] replay digest failed: {exc}")
        return "", None


# ── Raw pattern digest ────────────────────────────────────────────────────────

async def _load_raw_pattern_digest() -> tuple[str, Optional[dict]]:
    cached = _get_cache("raw_pattern")
    if cached:
        return cached["text"], cached["meta"]
    try:
        from database import get_raw_pattern_runs, get_raw_pattern_comparisons
        runs = await get_raw_pattern_runs(limit=5)
        run  = next((r for r in runs if r.get("status") == "completed"), None)
        if not run:
            return "", None

        run_id   = run["id"]
        run_date = (run.get("created_at") or "")[:10]

        # Key features that discriminate 4x pump from false positive
        KEY_FEATURES: list[tuple[str, str]] = [
            ("bull_stack_days_pre",          "bull stack days"),
            ("dryup_day_count_pre",          "dry-up days"),
            ("compression_days_pre",         "compression days"),
            ("days_above_ema50_pre",         "days above EMA50"),
            ("avg_close_vs_ema200_pct_pre",  "avg close vs EMA200 %"),
            ("avg_atr_pct_pre",              "avg ATR %"),
            ("abnormal_volume_day_count_pre","abnormal vol days"),
            ("inside_bar_count_pre",         "inside bar count"),
        ]

        comps_4x = await get_raw_pattern_comparisons(run_id, group_name="4x_pump")
        comps_fp = await get_raw_pattern_comparisons(run_id, group_name="false_positive")
        comps_nw = await get_raw_pattern_comparisons(run_id, group_name="normal_winner")

        def _lk(rows: list) -> dict:
            return {r["feature_name"]: r.get("median_value") for r in rows}

        lk4x = _lk(comps_4x)
        lkfp  = _lk(comps_fp)
        lknw  = _lk(comps_nw)

        if not lk4x:
            return "", None

        n4x = comps_4x[0]["member_count"] if comps_4x else 0
        nfp  = comps_fp[0]["member_count"]  if comps_fp  else 0
        nnw  = comps_nw[0]["member_count"]  if comps_nw  else 0

        lines = [
            f"── RAW PATTERN RUN #{run_id}  ({run_date})"
            f"  4x_pump(n={n4x})  false_pos(n={nfp})  normal_win(n={nnw}) ──",
            "",
            f"{'FEATURE':<38}  {'4x_pump':>8}  {'false_pos':>9}  {'normal':>7}  {'Δ4x-FP':>8}",
        ]
        for col, label in KEY_FEATURES:
            v4x = lk4x.get(col)
            vfp  = lkfp.get(col)
            vnw  = lknw.get(col)
            if v4x is None and vfp is None:
                continue

            def _fv(v):
                if v is None:
                    return "     ?"
                return f"{v:8.1f}"

            delta = ""
            if v4x is not None and vfp is not None:
                d = v4x - vfp
                if abs(d) >= 0.5:
                    delta = f"{d:+8.1f}"

            lines.append(f"  {label:<36}  {_fv(v4x)}  {_fv(vfp):>9}  {_fv(vnw):>7}  {delta:>8}")

        text = "\n".join(lines)
        meta = {"run_id": run_id, "date": run_date}
        _set_cache("raw_pattern", {"text": text, "meta": meta})
        return text, meta

    except Exception as exc:
        logger.warning(f"[ai_context] raw pattern digest failed: {exc}")
        return "", None


# ── Pump study digest ─────────────────────────────────────────────────────────

async def _load_pump_study_digest() -> tuple[str, Optional[dict]]:
    cached = _get_cache("pump_study")
    if cached:
        return cached["text"], cached["meta"]
    try:
        from database import get_pump_study_runs, get_pump_ai_summary
        runs = await get_pump_study_runs(limit=5)
        run  = next((r for r in runs if r.get("status") == "completed"), None)
        if not run:
            return "", None

        run_id   = run["id"]
        run_date = (run.get("started_at") or run.get("created_at") or "")[:10]
        episodes = run.get("episode_count", 0)
        period   = f"{run.get('start_date','')} – {run.get('end_date','')}"

        ai = await get_pump_ai_summary(run_id)

        lines = [
            f"── PUMP STUDY #{run_id}  ({run_date})  {episodes} 4x+ episodes  period={period} ──",
        ]

        if ai and not ai.get("parse_failed"):
            analysis = ai.get("analysis") or {}
            rec      = ai.get("recommendation") or ""
            if rec:
                lines += ["", f"RECOMMENDATION: {rec[:300]}"]

            findings = analysis.get("key_findings") or analysis.get("findings") or []
            if isinstance(findings, list) and findings:
                lines += ["", "KEY FINDINGS:"]
                for f in findings[:5]:
                    if isinstance(f, str):
                        lines.append(f"  • {f[:180]}")
            elif isinstance(findings, str) and findings:
                lines.append(f"  • {findings[:300]}")

            # Pump type breakdown if available
            by_type = analysis.get("by_pump_type") or {}
            if by_type:
                lines += ["", "PUMP TYPE BREAKDOWN:"]
                for pt, stats in list(by_type.items())[:4]:
                    if isinstance(stats, dict):
                        n   = stats.get("count", "?")
                        med = stats.get("median_days", "?")
                        lines.append(f"  {pt}: n={n}  median_days={med}")
        else:
            lines += [
                "",
                f"  Episodes: {episodes}  Period: {period}",
                f"  (AI summary not yet generated for this run)",
            ]

        text = "\n".join(lines)
        meta = {"run_id": run_id, "date": run_date, "episodes": episodes}
        _set_cache("pump_study", {"text": text, "meta": meta})
        return text, meta

    except Exception as exc:
        logger.warning(f"[ai_context] pump study digest failed: {exc}")
        return "", None


# ── Public API ────────────────────────────────────────────────────────────────

async def build_research_digest() -> dict:
    """
    Build a structured research memory digest from the latest available data.

    Returns dict:
      text       — full digest string ready for system prompt injection
      sources    — list of {type, run_id, date} for each source
      has_data   — True if at least one source produced usable data
    """
    replay_text,  replay_meta  = await _load_replay_digest()
    pattern_text, pattern_meta = await _load_raw_pattern_digest()
    study_text,   study_meta   = await _load_pump_study_digest()

    sections: list[str] = []
    sources:  list[dict] = []

    for text, meta, src_type in (
        (replay_text,  replay_meta,  "replay"),
        (pattern_text, pattern_meta, "raw_pattern"),
        (study_text,   study_meta,   "pump_study"),
    ):
        if text:
            sections.append(text)
        if meta and text:
            sources.append({"type": src_type, **meta})

    if not sections:
        return {"text": "", "sources": [], "has_data": False}

    src_line = "Sources: " + "  ·  ".join(
        f"{s['type']} #{s.get('run_id','?')} ({s.get('date','')})"
        for s in sources
    )

    full_text = (
        "=== RESEARCH MEMORY ===\n"
        + src_line + "\n\n"
        + "\n\n".join(sections)
    )

    return {"text": full_text, "sources": sources, "has_data": True}
