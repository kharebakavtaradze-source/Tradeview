"""
Pattern Discovery Engine — V1A Episode Aggregate + V1B Bar Sequence

V1A: Groups all episodes by group_type (4x_pump / normal_winner /
     false_positive / missed_mover) and computes per-signal rates and lift
     for every categorical, boolean, and combo field in
     raw_pattern_episode_features — including Demand tier, ATS, TZ signals,
     TZ 15bar, PREUP, and all NP/structural fields.

V1B: Mines N-bar structural sequences from raw_pattern_daily_features
     (last N PRE bars before breakout) using per-bar flags already stored
     as columns (expansion, dryup, engulfing, etc.).
"""

import json
import logging
from collections import defaultdict
from datetime import datetime

logger = logging.getLogger(__name__)

# ── In-memory progress tracker ───────────────────────────────────────────────

_discovery_progress: dict[int, dict] = {}


def get_discovery_status(run_id: int) -> dict:
    return _discovery_progress.get(run_id, {"phase": "IDLE", "running": False})


def _set_phase(run_id: int, phase: str, **extra):
    prev = _discovery_progress.get(run_id, {})
    _discovery_progress[run_id] = {
        "phase":      phase,
        "running":    phase not in ("COMPLETE", "ERROR", "IDLE"),
        "started_at": prev.get("started_at") or datetime.utcnow().isoformat(),
        **extra,
    }


# ── Field definitions ─────────────────────────────────────────────────────────

_CATEGORICAL_FIELDS = [
    # (field, family, description_prefix)
    ("demand_tier_at_breakout",           "DEMAND",    "Demand tier at breakout"),
    ("ats_at_breakout",                   "DEMAND",    "ATS signal at breakout"),
    ("readiness_tier_at_breakout",        "DEMAND",    "Readiness tier at breakout"),
    ("tz_t_signal_at_breakout",           "TZ",        "TZ T-signal at breakout"),
    ("tz_z_signal_at_breakout",           "TZ",        "TZ Z-signal at breakout"),
    ("preup_token_at_breakout",           "TZ",        "PREUP token at breakout"),
    ("line5_at_breakout",                 "TZ",        "Line5 at breakout"),
    ("best_tz_t_signal_15bar",            "TZ",        "Best TZ T-signal (15-bar)"),
    ("best_tz_z_signal_15bar",            "TZ",        "Best TZ Z-signal (15-bar)"),
    ("pump_type",                         "STRUCTURE", "Pump type"),
    ("strongest_wyckoff_state",           "STRUCTURE", "Strongest Wyckoff state"),
    ("strongest_sequence_type",           "STRUCTURE", "Strongest sequence type"),
    ("strongest_structural_bias",         "STRUCTURE", "Structural bias"),
    ("dominant_structure_phase_pre",      "STRUCTURE", "Dominant structure phase"),
    ("dominant_d_confluence_type_pre",    "STRUCTURE", "Dominant D-confluence type"),
    ("dominant_d_confluence_family_pre",  "STRUCTURE", "D-confluence family"),
    ("split_context",                     "SPLIT",     "Split context"),
    ("np_skip_reason",                    "NP",        "NP skip reason"),
]

_BOOLEAN_FIELDS = [
    ("had_compression",                        "STRUCTURE", "Had price compression in PRE"),
    ("had_bull_stack_pre",                     "STRUCTURE", "Had EMA bull stack in PRE"),
    ("had_accumulation_like",                  "STRUCTURE", "Had accumulation-like structure"),
    ("had_spring_test_lps",                    "STRUCTURE", "Had spring/test/LPS"),
    ("had_breakout_retest",                    "STRUCTURE", "Had breakout retest"),
    ("had_confirmed_structure_pre",            "STRUCTURE", "Had confirmed structure"),
    ("had_triggered_structure_pre",            "STRUCTURE", "Had triggered structure"),
    ("had_d_confluence_pre",                   "STRUCTURE", "Had D-confluence"),
    ("had_core_d_beup_pre",                    "STRUCTURE", "Had core D-BEUP"),
    ("had_core_d_l34_pre",                     "STRUCTURE", "Had core D-L34"),
    ("had_d4_beup_pre",                        "STRUCTURE", "Had D4-BEUP"),
    ("had_valid_full_sequence",                "NP",        "Had valid NP full sequence"),
    ("had_valid_recent_setup",                 "NP",        "Had valid NP setup"),
    ("had_valid_recent_trigger",               "NP",        "Had valid NP trigger"),
    ("had_valid_recent_confirm",               "NP",        "Had valid NP confirm"),
    ("had_np_buy_candidate_pre",               "NP",        "Had NP BUY_CANDIDATE day"),
    ("had_np_watch_pre",                       "NP",        "Had NP WATCH day"),
    ("had_prime_buy_pre",                      "DEMAND",    "Had PRIME_BUY in PRE window"),
    ("had_ats_prime_pre",                      "DEMAND",    "Had ATS_PRIME in PRE window"),
    ("demand_prime_at_breakout",               "DEMAND",    "PRIME_BUY at breakout"),
    ("demand_high_at_breakout",                "DEMAND",    "HIGH_CONF_BUY at breakout"),
    ("demand_watch_or_better_at_breakout",     "DEMAND",    "WATCH or better at breakout"),
    ("ats_prime_at_breakout",                  "DEMAND",    "ATS_PRIME at breakout"),
    ("ats_setup_or_better_at_breakout",        "DEMAND",    "ATS SETUP or better at breakout"),
    ("split_artifact_risk",                    "SPLIT",     "Split artifact risk"),
    ("has_split_near_episode",                 "SPLIT",     "Has split near episode"),
    ("has_reverse_split_near_episode",         "SPLIT",     "Has reverse split near episode"),
]

# 2-field combos (field_a, field_b, description)
_COMBO_FIELDS = [
    ("demand_tier_at_breakout",   "best_tz_t_signal_15bar",   "Demand tier + TZ 15bar T"),
    ("demand_tier_at_breakout",   "tz_t_signal_at_breakout",  "Demand tier + TZ T at breakout"),
    ("demand_tier_at_breakout",   "ats_at_breakout",          "Demand tier + ATS"),
    ("demand_tier_at_breakout",   "preup_token_at_breakout",  "Demand tier + PREUP"),
    ("ats_at_breakout",           "best_tz_t_signal_15bar",   "ATS + TZ 15bar T"),
    ("ats_at_breakout",           "tz_t_signal_at_breakout",  "ATS + TZ T at breakout"),
    ("tz_t_signal_at_breakout",   "preup_token_at_breakout",  "TZ T + PREUP at breakout"),
    ("best_tz_t_signal_15bar",    "preup_token_at_breakout",  "TZ 15bar T + PREUP"),
    ("best_tz_t_signal_15bar",    "tz_t_signal_at_breakout",  "TZ 15bar T + TZ T at breakout"),
    ("pump_type",                 "demand_tier_at_breakout",  "Pump type + Demand tier"),
    ("pump_type",                 "best_tz_t_signal_15bar",   "Pump type + TZ 15bar T"),
    ("pump_type",                 "ats_at_breakout",          "Pump type + ATS"),
    ("had_prime_buy_pre",         "best_tz_t_signal_15bar",   "Had PRIME_BUY pre + TZ 15bar T"),
    ("had_prime_buy_pre",         "tz_t_signal_at_breakout",  "Had PRIME_BUY pre + TZ T"),
    ("demand_tier_at_breakout",   "strongest_wyckoff_state",  "Demand tier + Wyckoff state"),
]

# ── Helpers ───────────────────────────────────────────────────────────────────

_FIELD_PREFIX = {
    "demand_tier_at_breakout":          "DEM",
    "ats_at_breakout":                  "ATS",
    "readiness_tier_at_breakout":       "RDY",
    "tz_t_signal_at_breakout":          "TZT",
    "tz_z_signal_at_breakout":          "TZZ",
    "preup_token_at_breakout":          "PUP",
    "line5_at_breakout":                "L5",
    "best_tz_t_signal_15bar":           "T15",
    "best_tz_z_signal_15bar":           "Z15",
    "pump_type":                        "PT",
    "strongest_wyckoff_state":          "WYC",
    "strongest_sequence_type":          "SEQ",
    "strongest_structural_bias":        "BIAS",
    "dominant_structure_phase_pre":     "STR",
    "dominant_d_confluence_type_pre":   "DCONF",
    "dominant_d_confluence_family_pre": "DCFAM",
    "split_context":                    "SPL",
    "np_skip_reason":                   "NPSKIP",
    "had_compression":                  "COMP",
    "had_bull_stack_pre":               "BSTK",
    "had_accumulation_like":            "ACC",
    "had_spring_test_lps":              "SPR",
    "had_breakout_retest":              "BRT",
    "had_confirmed_structure_pre":      "CSTR",
    "had_triggered_structure_pre":      "TSTR",
    "had_d_confluence_pre":             "DCONF",
    "had_core_d_beup_pre":              "DBEUP",
    "had_core_d_l34_pre":               "DL34",
    "had_d4_beup_pre":                  "D4BP",
    "had_valid_full_sequence":          "NVFS",
    "had_valid_recent_setup":           "NVSU",
    "had_valid_recent_trigger":         "NVTR",
    "had_valid_recent_confirm":         "NVCF",
    "had_np_buy_candidate_pre":         "NPBC",
    "had_np_watch_pre":                 "NPWT",
    "had_prime_buy_pre":                "PBPRE",
    "had_ats_prime_pre":                "ATSPRE",
    "demand_prime_at_breakout":         "DPRIME",
    "demand_high_at_breakout":          "DHIGH",
    "demand_watch_or_better_at_breakout": "DWOB",
    "ats_prime_at_breakout":            "ATSP",
    "ats_setup_or_better_at_breakout":  "ATSSOB",
    "split_artifact_risk":              "SPART",
    "has_split_near_episode":           "SPNR",
    "has_reverse_split_near_episode":   "RSPNR",
}


def _pfx(field: str) -> str:
    return _FIELD_PREFIX.get(field, field[:6].upper())


def _clean(val: str) -> str:
    return str(val).upper().replace(" ", "_").replace("-", "_").replace("/", "_")


def _sig(prefix: str, val: str) -> str:
    return f"DISC_EP_{prefix}_{_clean(val)}"[:60]


def _combo_sig(pa: str, va: str, pb: str, vb: str) -> str:
    return f"DISC_CMB_{pa}_{_clean(va)[:12]}__{pb}_{_clean(vb)[:12]}"[:60]


def _metrics(c4: int, cf: int, cn: int, total_4x: int, total_fp: int, total_nw: int) -> dict:
    r4  = c4 / total_4x if total_4x > 0 else 0
    rfp = cf / total_fp if total_fp > 0 else 0
    rnw = cn / total_nw if total_nw > 0 else 0
    lift_fp = r4 / rfp if rfp > 0 else (r4 * 10 if r4 > 0 else 0)
    lift_nw = r4 / rnw if rnw > 0 else (r4 * 10 if r4 > 0 else 0)
    denom = c4 + cf
    return {
        "lift_vs_false_positive": round(lift_fp, 3),
        "lift_vs_normal_winner":  round(lift_nw, 3),
        "precision_estimate":     round(c4 / denom, 3) if denom else 0,
        "recall_all_4x":          round(r4, 3),
        "false_positive_rate":    round(rfp, 3),
    }


def _rec(lift: float, prec: float, c4: int) -> str:
    if c4 < 3:
        return "IGNORE"
    if lift >= 3.0 and prec >= 0.5 and c4 >= 5:
        return "BOOST"
    if lift >= 2.0 and prec >= 0.4:
        return "INCREASE"
    if lift <= 0.4:
        return "PENALIZE"
    if lift <= 0.7:
        return "REDUCE"
    return "IGNORE"


# ── V1A: Episode Aggregate ────────────────────────────────────────────────────

def _mine_v1a(
    g4x: list, gfp: list, gnw: list, gmis: list,
    save_mode: str,
) -> list[dict]:
    total_4x = len(g4x)
    total_fp = len(gfp)
    total_nw = len(gnw)
    rows: list[dict] = []

    def _add(signal_id, source_type, family, description, c4, cf, cn, conditions):
        m = _metrics(c4, cf, cn, total_4x, total_fp, total_nw)
        r = _rec(m["lift_vs_false_positive"], m["precision_estimate"], c4)
        if save_mode == "compact" and r == "IGNORE" and c4 < 3:
            return
        rows.append({
            "signal_id":               signal_id,
            "source_type":             source_type,
            "feature_family":          family,
            "family":                  family[:2],
            "status":                  "ACCEPTED" if r in ("BOOST", "INCREASE") else "DISCOVERED",
            "intended_use":            "DEMAND_FILTER",
            "description":             description,
            "count_detected_4x":       c4,
            "count_missed_4x":         total_4x - c4,
            "count_all_4x":            total_4x,
            "count_false_positive":    cf,
            "count_normal_winner":     cn,
            "recommendation":          r,
            "machine_conditions_json": json.dumps(conditions),
            **m,
        })

    # Categorical fields
    for field, family, desc_prefix in _CATEGORICAL_FIELDS:
        all_vals: set[str] = set()
        for ep in g4x + gfp + gnw:
            v = ep.get(field)
            if v and str(v).strip() not in ("", "None", "none"):
                all_vals.add(str(v))
        for val in sorted(all_vals):
            c4 = sum(1 for e in g4x  if str(e.get(field) or "") == val)
            cf = sum(1 for e in gfp  if str(e.get(field) or "") == val)
            cn = sum(1 for e in gnw  if str(e.get(field) or "") == val)
            if c4 == 0 and cf == 0:
                continue
            _add(
                _sig(_pfx(field), val),
                "EPISODE_AGGREGATE", family,
                f"{desc_prefix} = {val}",
                c4, cf, cn,
                [{"field": field, "op": "eq", "value": val}],
            )

    # Boolean fields
    for field, family, desc in _BOOLEAN_FIELDS:
        c4 = sum(1 for e in g4x if e.get(field) is True)
        cf = sum(1 for e in gfp if e.get(field) is True)
        cn = sum(1 for e in gnw if e.get(field) is True)
        if c4 == 0 and cf == 0:
            continue
        _add(
            f"DISC_EP_{_pfx(field)}_TRUE"[:60],
            "EPISODE_AGGREGATE", family, desc,
            c4, cf, cn,
            [{"field": field, "op": "eq", "value": True}],
        )

    # 2-field combos
    for field_a, field_b, combo_desc in _COMBO_FIELDS:
        # Determine if either field is boolean
        bool_a = any(f == field_a for f, _, _ in _BOOLEAN_FIELDS)
        bool_b = any(f == field_b for f, _, _ in _BOOLEAN_FIELDS)

        if bool_a and not bool_b:
            # boolean × categorical
            all_vals_b: set[str] = set()
            for ep in g4x + gfp + gnw:
                v = ep.get(field_b)
                if v and str(v).strip() not in ("", "None"):
                    all_vals_b.add(str(v))
            for vb in sorted(all_vals_b):
                c4 = sum(1 for e in g4x if e.get(field_a) is True and str(e.get(field_b) or "") == vb)
                cf = sum(1 for e in gfp if e.get(field_a) is True and str(e.get(field_b) or "") == vb)
                cn = sum(1 for e in gnw if e.get(field_a) is True and str(e.get(field_b) or "") == vb)
                if c4 == 0 and cf == 0:
                    continue
                _add(
                    _combo_sig(_pfx(field_a), "TRUE", _pfx(field_b), vb),
                    "EPISODE_AGGREGATE", "COMBINED",
                    f"{combo_desc}: TRUE + {vb}",
                    c4, cf, cn,
                    [{"field": field_a, "op": "eq", "value": True},
                     {"field": field_b, "op": "eq", "value": vb}],
                )
        else:
            # categorical × categorical
            pairs: set[tuple] = set()
            for ep in g4x + gfp + gnw:
                va = ep.get(field_a)
                vb = ep.get(field_b)
                if va and vb and str(va).strip() not in ("", "None") and str(vb).strip() not in ("", "None"):
                    pairs.add((str(va), str(vb)))
            for va, vb in sorted(pairs):
                c4 = sum(1 for e in g4x if str(e.get(field_a) or "") == va and str(e.get(field_b) or "") == vb)
                cf = sum(1 for e in gfp if str(e.get(field_a) or "") == va and str(e.get(field_b) or "") == vb)
                cn = sum(1 for e in gnw if str(e.get(field_a) or "") == va and str(e.get(field_b) or "") == vb)
                if c4 == 0 and cf == 0:
                    continue
                _add(
                    _combo_sig(_pfx(field_a), va, _pfx(field_b), vb),
                    "EPISODE_AGGREGATE", "COMBINED",
                    f"{combo_desc}: {va} + {vb}",
                    c4, cf, cn,
                    [{"field": field_a, "op": "eq", "value": va},
                     {"field": field_b, "op": "eq", "value": vb}],
                )

    return rows


# ── V1B: Bar Sequence ─────────────────────────────────────────────────────────

def _bar_tag(bar: dict) -> str:
    """Convert a daily feature row into a compact single-bar tag string."""
    tags = []
    if bar.get("expansion_bar"):
        tags.append("EXP")
    elif bar.get("wide_range_bar") and bar.get("strong_close_near_high"):
        tags.append("WRB")
    elif bar.get("wide_range_bar"):
        tags.append("WR")
    elif bar.get("narrow_range_bar"):
        tags.append("NR")
    else:
        tags.append("NORM")

    if bar.get("abnormal_volume_day"):
        tags.append("AV")
    elif bar.get("dryup_day"):
        tags.append("DRY")

    if bar.get("bullish_engulfing"):
        tags.append("BEG")
    elif bar.get("bearish_engulfing"):
        tags.append("BENG")
    elif bar.get("reclaim_bar"):
        tags.append("RCL")
    elif bar.get("inside_bar"):
        tags.append("INS")

    if bar.get("strong_close_near_high") and "EXP" not in tags and "WRB" not in tags:
        tags.append("SC")
    elif bar.get("weak_close_near_low"):
        tags.append("WC")

    return "+".join(tags) if tags else "NORM"


def _mine_v1b(
    g4x_ids: set, gfp_ids: set, gnw_ids: set,
    daily_by_ep: dict[int, list],
    windows: list[int],
    total_4x: int, total_fp: int, total_nw: int,
    save_mode: str,
) -> list[dict]:
    rows: list[dict] = []

    for window in windows:
        # Build sequence → {4x: count, fp: count, nw: count}
        seq_counts: dict[str, dict] = defaultdict(lambda: {"4x": 0, "fp": 0, "nw": 0})

        for ep_id, bars in daily_by_ep.items():
            # Only PRE bars, sorted by date desc (last N = closest to breakout)
            pre = sorted(
                [b for b in bars if b.get("phase") == "PRE"],
                key=lambda b: b.get("date", ""),
            )
            if len(pre) < 1:
                continue
            last_n = pre[-window:]  # last N bars before breakout
            seq = " → ".join(_bar_tag(b) for b in last_n)

            group = (
                "4x" if ep_id in g4x_ids else
                "fp" if ep_id in gfp_ids else
                "nw" if ep_id in gnw_ids else None
            )
            if group:
                seq_counts[seq][group] += 1

        for seq, cnts in seq_counts.items():
            c4 = cnts["4x"]
            cf = cnts["fp"]
            cn = cnts["nw"]
            if c4 == 0 and cf == 0:
                continue
            m   = _metrics(c4, cf, cn, total_4x, total_fp, total_nw)
            rec = _rec(m["lift_vs_false_positive"], m["precision_estimate"], c4)
            if save_mode == "compact" and rec == "IGNORE" and c4 < 3:
                continue

            src_map = {1: "SINGLE_BAR", 2: "TWO_BAR_SEQUENCE", 3: "THREE_BAR_SEQUENCE",
                       5: "FIVE_BAR_SEQUENCE", 10: "TEN_BAR_CONTEXT"}
            src_type = src_map.get(window, f"{window}_BAR_SEQUENCE")

            # Build signal_id from sequence string (truncated)
            seq_key = seq.replace(" → ", "_").replace("+", "").replace(" ", "")[:35]
            signal_id = f"DISC_BAR_{src_type[:8]}_{seq_key}"[:60]

            rows.append({
                "signal_id":               signal_id,
                "source_type":             src_type,
                "feature_family":          "PRICE_ACTION",
                "family":                  "BA",
                "status":                  "ACCEPTED" if rec in ("BOOST", "INCREASE") else "DISCOVERED",
                "intended_use":            "DEMAND_FILTER",
                "description":             f"{window}-bar seq: {seq}",
                "count_detected_4x":       c4,
                "count_missed_4x":         total_4x - c4,
                "count_all_4x":            total_4x,
                "count_false_positive":    cf,
                "count_normal_winner":     cn,
                "recommendation":          rec,
                "machine_conditions_json": json.dumps([
                    {"type": "bar_sequence", "window": window, "sequence": seq}
                ]),
                **m,
            })

    return rows


# ── Main entry point ──────────────────────────────────────────────────────────

async def run_discovery(
    run_id: int,
    mode: str = "both",          # both | episode_aggregate | bar_sequence
    windows: list[int] | None = None,
    exclude_split_artifacts: bool = True,
    save_mode: str = "compact",  # compact | research | debug
) -> dict:
    """
    Run pattern discovery for a raw-pattern-study run.
    Writes results to discovered_patterns table.
    Updates _discovery_progress in-memory.
    Returns summary dict.
    """
    from database import (
        get_raw_pattern_episode_features,
        get_raw_pattern_daily_features,
        upsert_discovered_patterns,
    )

    if windows is None:
        windows = [1, 2, 3, 5, 10]

    do_v1a = mode in ("both", "episode_aggregate", "all")
    do_v1b = mode in ("both", "bar_sequence", "all")

    _set_phase(run_id, "LOADING_DATASET", patterns_found=0)

    # Load all episode features (no limit)
    episodes = await get_raw_pattern_episode_features(run_id, limit=20_000)
    if not episodes:
        _set_phase(run_id, "ERROR", error="No episode features found — run the raw pattern study first")
        return {"error": "No episode features"}

    if exclude_split_artifacts:
        episodes = [e for e in episodes if not e.get("split_artifact_risk")]

    groups: dict[str, list] = defaultdict(list)
    for ep in episodes:
        groups[ep.get("group_type") or "unknown"].append(ep)

    g4x  = groups["4x_pump"]
    gfp  = groups["false_positive"]
    gnw  = groups["normal_winner"]
    gmis = groups["missed_mover"]

    total_4x = len(g4x)
    total_fp = len(gfp)
    total_nw = len(gnw)

    if total_4x == 0:
        _set_phase(run_id, "ERROR", error="No 4x_pump episodes in this run")
        return {"error": "No 4x_pump episodes"}

    _set_phase(run_id, "PATTERN_MINING_V1A" if do_v1a else "LOADING_BAR_FEATURES",
               groups={"4x_pump": total_4x, "false_positive": total_fp,
                       "normal_winner": total_nw, "missed_mover": len(gmis)})

    all_rows: list[dict] = []

    # ── V1A ───────────────────────────────────────────────────────────────────
    if do_v1a:
        v1a_rows = _mine_v1a(g4x, gfp, gnw, gmis, save_mode)
        all_rows.extend(v1a_rows)
        logger.info(f"[Discovery] V1A run={run_id}: {len(v1a_rows)} patterns")

    # ── V1B ───────────────────────────────────────────────────────────────────
    if do_v1b:
        _set_phase(run_id, "LOADING_BAR_FEATURES", patterns_found=len(all_rows))
        daily = await get_raw_pattern_daily_features(run_id, limit=200_000)

        daily_by_ep: dict[int, list] = defaultdict(list)
        for bar in daily:
            daily_by_ep[bar["episode_id"]].append(bar)

        g4x_ids = {e["episode_id"] for e in g4x}
        gfp_ids = {e["episode_id"] for e in gfp}
        gnw_ids = {e["episode_id"] for e in gnw}

        _set_phase(run_id, "MINING_BAR_PATTERNS", patterns_found=len(all_rows))
        v1b_rows = _mine_v1b(
            g4x_ids, gfp_ids, gnw_ids,
            daily_by_ep, windows,
            total_4x, total_fp, total_nw,
            save_mode,
        )
        all_rows.extend(v1b_rows)
        logger.info(f"[Discovery] V1B run={run_id}: {len(v1b_rows)} patterns")

    # ── Persist ───────────────────────────────────────────────────────────────
    _set_phase(run_id, "PERSISTING_PATTERNS", patterns_found=len(all_rows))
    saved = await upsert_discovered_patterns(run_id, all_rows)

    summary = {
        "patterns_saved": saved,
        "groups": {
            "4x_pump":        total_4x,
            "false_positive": total_fp,
            "normal_winner":  total_nw,
            "missed_mover":   len(gmis),
        },
        "v1a_count": len([r for r in all_rows if r["source_type"] == "EPISODE_AGGREGATE"]),
        "v1b_count": len([r for r in all_rows if r["source_type"] != "EPISODE_AGGREGATE"]),
        "boost_count":    len([r for r in all_rows if r["recommendation"] == "BOOST"]),
        "increase_count": len([r for r in all_rows if r["recommendation"] == "INCREASE"]),
        "penalize_count": len([r for r in all_rows if r["recommendation"] == "PENALIZE"]),
    }

    _set_phase(run_id, "COMPLETE",
               patterns_found=saved,
               finished_at=datetime.utcnow().isoformat(),
               **summary)

    return summary
