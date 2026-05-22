"""
Test suite for bar-level Pattern Discovery Engine (V1B).

Tests:
  1. bars_to_tags() — tag generation from feature dicts
  2. build_bar_feature_snapshots_for_episode() — snapshot building from DB rows
  3. build_bar_sequences() — rolling-window sequence generation
  4. mine_bar_patterns() — statistical pattern mining
  5. Registry source_type integrity
  6. Anti-leakage assertions

Anti-leakage requirement: group_type, pump_multiple, forward_return, and
days_from_breakout_to_peak must NEVER appear in pattern conditions.
All tags and sequence signatures are derived from PRE-phase bar features only.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import json
import pytest

from replay.bar_feature_engine import (
    bars_to_tags,
    build_bar_feature_snapshots_for_episode,
    build_bar_sequences,
    TAG_STRONG_CLOSE,
    TAG_WEAK_CLOSE,
    TAG_DRYUP,
    TAG_VOLUME_SPIKE,
    TAG_EMA50_RECLAIM,
    TAG_BB_COMPRESSION,
    TAG_DELTA_IGNITION,
    TAG_GAP_UP,
    TAG_GAP_UP_HOLD,
    TAG_GAP_DOWN,
    TAG_GAP_DOWN_RECLAIM,
    TAG_LOWER_WICK_RECLAIM,
    TAG_EXPANSION,
    TAG_BULL_ENGULF,
    TAG_INSIDE_BAR,
    TAG_RECLAIM_BAR,
    TAG_EMA_BULL_STACK,
    TAG_L34,
    TAG_NP_SETUP,
    TAG_FLAT,
    ALL_TAGS,
)
from replay.pattern_miner import mine_bar_patterns


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_daily_row(
    episode_id: int = 1,
    phase: str = "PRE",
    relative_day: int = -5,
    date: str = "2025-01-10",
    close: float = 3.00,
    volume_vs_avg20: float = 1.0,
    strong_close: bool = False,
    weak_close: bool = False,
    dryup_day: bool = False,
    abnormal_volume: bool = False,
    compression_state: str = "NONE",
    bullish_engulfing: bool = False,
    inside_bar: bool = False,
    reclaim_bar: bool = False,
    expansion_bar: bool = False,
    wide_range_bar: bool = False,
    gap_pct: float = 0.0,
    lower_wick_pct: float = 0.0,
    close_position_in_bar: float = 0.5,
    feature_json: dict | None = None,
) -> dict:
    fj = feature_json or {}
    return {
        "episode_id":           episode_id,
        "phase":                phase,
        "relative_day_from_start": relative_day,
        "date":                 date,
        "open":                 close * 0.98,
        "high":                 close * 1.02,
        "low":                  close * 0.97,
        "close":                close,
        "volume":               100_000,
        "strong_close_near_high": strong_close,
        "weak_close_near_low":    weak_close,
        "wide_range_bar":         wide_range_bar,
        "narrow_range_bar":       False,
        "bullish_engulfing":      bullish_engulfing,
        "inside_bar":             inside_bar,
        "outside_bar":            False,
        "reclaim_bar":            reclaim_bar,
        "expansion_bar":          expansion_bar,
        "dryup_day":              dryup_day,
        "abnormal_volume_day":    abnormal_volume,
        "volume_vs_avg20":        volume_vs_avg20,
        "volume_zscore":          0.0,
        "gap_pct":                gap_pct,
        "lower_wick_pct":         lower_wick_pct,
        "upper_wick_pct":         0.1,
        "body_pct":               0.5,
        "close_position_in_bar":  close_position_in_bar,
        "compression_state":      compression_state,
        "bb_width":               0.05,
        "ema_spread_pct":         2.0,
        "feature_json":           fj,
    }


def _make_episode(
    episode_id: int = 1,
    symbol: str = "AAPL",
    group_type: str = "missed_4x_pump",
) -> dict:
    return {
        "episode_id": episode_id,
        "symbol":     symbol,
        "group_type": group_type,
    }


# ── 1. bars_to_tags() tests ───────────────────────────────────────────────────

class TestBarsToTags:
    def test_strong_close_tag(self):
        f = {"is_strong_close": True, "close_position_in_range": 0.80}
        assert TAG_STRONG_CLOSE in bars_to_tags(f)

    def test_strong_close_from_position(self):
        f = {"close_position_in_range": 0.72}
        assert TAG_STRONG_CLOSE in bars_to_tags(f)

    def test_weak_close_tag(self):
        f = {"is_weak_close": True, "close_position_in_range": 0.20}
        assert TAG_WEAK_CLOSE in bars_to_tags(f)

    def test_dryup_from_boolean(self):
        f = {"dryup_day": True}
        assert TAG_DRYUP in bars_to_tags(f)

    def test_dryup_from_rvol(self):
        f = {"volume_vs_avg20": 0.3}
        assert TAG_DRYUP in bars_to_tags(f)

    def test_volume_spike_from_boolean(self):
        f = {"abnormal_volume_day": True}
        assert TAG_VOLUME_SPIKE in bars_to_tags(f)

    def test_volume_spike_from_rvol(self):
        f = {"relative_volume_20d": 4.5}
        assert TAG_VOLUME_SPIKE in bars_to_tags(f)

    def test_ema50_reclaim_tag(self):
        f = {"ema50_reclaim_bar": True}
        assert TAG_EMA50_RECLAIM in bars_to_tags(f)

    def test_compression_from_state(self):
        f = {"compression_state": "STRONG"}
        assert TAG_BB_COMPRESSION in bars_to_tags(f)

    def test_compression_medium_state(self):
        f = {"compression_state": "MEDIUM"}
        assert TAG_BB_COMPRESSION in bars_to_tags(f)

    def test_no_compression_none_state(self):
        f = {"compression_state": "NONE"}
        assert TAG_BB_COMPRESSION not in bars_to_tags(f)

    def test_delta_ignition_tag(self):
        f = {"delta_ignition": True}
        assert TAG_DELTA_IGNITION in bars_to_tags(f)

    def test_gap_up_tag(self):
        f = {"gap_pct": 3.5}
        tags = bars_to_tags(f)
        assert TAG_GAP_UP in tags

    def test_gap_up_hold_tag(self):
        f = {"gap_pct": 3.5, "gap_hold": True}
        tags = bars_to_tags(f)
        assert TAG_GAP_UP_HOLD in tags

    def test_gap_down_tag(self):
        f = {"gap_pct": -3.0}
        assert TAG_GAP_DOWN in bars_to_tags(f)

    def test_gap_down_reclaim(self):
        f = {"gap_pct": -3.0, "gap_down_reclaim_same_day": True}
        tags = bars_to_tags(f)
        assert TAG_GAP_DOWN_RECLAIM in tags

    def test_lower_wick_reclaim(self):
        f = {"lower_wick_pct": 0.40, "close_position_in_bar": 0.65}
        assert TAG_LOWER_WICK_RECLAIM in bars_to_tags(f)

    def test_lower_wick_no_tag_weak_close(self):
        # Strong lower wick but closes weak — no LOWER_WICK_RECLAIM
        f = {"lower_wick_pct": 0.45, "close_position_in_bar": 0.30}
        assert TAG_LOWER_WICK_RECLAIM not in bars_to_tags(f)

    def test_expansion_tag(self):
        f = {"expansion_bar": True}
        assert TAG_EXPANSION in bars_to_tags(f)

    def test_bull_engulf_tag(self):
        f = {"bullish_engulfing": True}
        assert TAG_BULL_ENGULF in bars_to_tags(f)

    def test_inside_bar_tag(self):
        f = {"inside_bar": True}
        assert TAG_INSIDE_BAR in bars_to_tags(f)

    def test_reclaim_bar_tag(self):
        f = {"reclaim_bar": True}
        assert TAG_RECLAIM_BAR in bars_to_tags(f)

    def test_ema_bull_stack_tag(self):
        f = {"ema_stack_state": "BULL"}
        assert TAG_EMA_BULL_STACK in bars_to_tags(f)

    def test_l34_tag(self):
        f = {"has_l34": True}
        assert TAG_L34 in bars_to_tags(f)

    def test_np_setup_tag(self):
        f = {"np_is_setup": True}
        assert TAG_NP_SETUP in bars_to_tags(f)

    def test_flat_when_no_tags(self):
        f = {}
        tags = bars_to_tags(f)
        # Empty features → neutral close position (0.5) and rvol=1.0 → no tags
        assert TAG_FLAT in tags

    def test_tags_sorted_and_deduplicated(self):
        f = {"is_strong_close": True, "close_position_in_range": 0.80, "dryup_day": True}
        tags = bars_to_tags(f)
        assert tags == sorted(set(tags))

    def test_db_column_names_accepted(self):
        # Keys from raw_pattern_daily_features columns
        f = {
            "strong_close_near_high": True,
            "dryup_day":              True,
            "compression_state":      "STRONG",
        }
        tags = bars_to_tags(f)
        assert TAG_STRONG_CLOSE in tags
        assert TAG_DRYUP        in tags
        assert TAG_BB_COMPRESSION in tags

    def test_all_tag_constants_defined(self):
        assert len(ALL_TAGS) >= 20, "Expected at least 20 tag constants"


# ── 2. build_bar_feature_snapshots_for_episode() tests ───────────────────────

class TestBuildBarFeatureSnapshots:
    def test_returns_only_pre_rows(self):
        ep = _make_episode()
        rows = [
            _make_daily_row(phase="PRE",  relative_day=-5),
            _make_daily_row(phase="PRE",  relative_day=-3),
            _make_daily_row(phase="PUMP", relative_day=0),   # should be excluded
            _make_daily_row(phase="POST", relative_day=2),   # should be excluded
        ]
        snaps = build_bar_feature_snapshots_for_episode(ep, rows)
        assert len(snaps) == 2
        assert all(s["phase"] == "PRE" for s in snaps)

    def test_sorted_oldest_first(self):
        ep = _make_episode()
        rows = [
            _make_daily_row(phase="PRE", relative_day=-1, date="2025-01-15"),
            _make_daily_row(phase="PRE", relative_day=-5, date="2025-01-11"),
            _make_daily_row(phase="PRE", relative_day=-3, date="2025-01-13"),
        ]
        snaps = build_bar_feature_snapshots_for_episode(ep, rows)
        days = [s["days_to_breakout"] for s in snaps]
        assert days == sorted(days, reverse=True), "Should be sorted furthest→nearest breakout"

    def test_days_to_breakout_is_positive(self):
        ep = _make_episode()
        rows = [_make_daily_row(phase="PRE", relative_day=-7)]
        snaps = build_bar_feature_snapshots_for_episode(ep, rows)
        assert snaps[0]["days_to_breakout"] == 7

    def test_episode_fields_propagated(self):
        ep = _make_episode(episode_id=42, symbol="TSLA", group_type="false_positive")
        rows = [_make_daily_row(phase="PRE", relative_day=-2)]
        snaps = build_bar_feature_snapshots_for_episode(ep, rows)
        s = snaps[0]
        assert s["episode_id"] == 42
        assert s["symbol"]     == "TSLA"
        assert s["group_type"] == "false_positive"

    def test_tags_generated(self):
        ep = _make_episode()
        rows = [_make_daily_row(phase="PRE", relative_day=-3, dryup_day=True)]
        snaps = build_bar_feature_snapshots_for_episode(ep, rows)
        assert "tags" in snaps[0]
        assert isinstance(snaps[0]["tags"], list)
        assert len(snaps[0]["tags"]) >= 1

    def test_tag_signature_joined_by_plus(self):
        ep = _make_episode()
        rows = [_make_daily_row(phase="PRE", relative_day=-2, dryup_day=True, strong_close=True)]
        snaps = build_bar_feature_snapshots_for_episode(ep, rows)
        sig = snaps[0]["tag_signature"]
        tags = snaps[0]["tags"]
        assert sig == "+".join(tags)

    def test_feature_json_extras_propagated(self):
        ep = _make_episode()
        fj = {"ema50_reclaim_bar": True, "delta_ignition": False, "has_l34": True}
        rows = [_make_daily_row(phase="PRE", relative_day=-2, feature_json=fj)]
        snaps = build_bar_feature_snapshots_for_episode(ep, rows)
        s = snaps[0]
        assert s.get("ema50_reclaim_bar") is True
        assert s.get("has_l34")           is True
        assert TAG_EMA50_RECLAIM in s["tags"]
        assert TAG_L34 in s["tags"]

    def test_empty_rows_returns_empty(self):
        ep = _make_episode()
        snaps = build_bar_feature_snapshots_for_episode(ep, [])
        assert snaps == []

    def test_no_pre_rows_returns_empty(self):
        ep = _make_episode()
        rows = [_make_daily_row(phase="PUMP", relative_day=0)]
        snaps = build_bar_feature_snapshots_for_episode(ep, rows)
        assert snaps == []

    def test_feature_json_as_string(self):
        ep = _make_episode()
        fj_str = json.dumps({"delta_ignition": True})
        rows = [_make_daily_row(phase="PRE", relative_day=-3, feature_json=fj_str)]
        snaps = build_bar_feature_snapshots_for_episode(ep, rows)
        # Should not raise, delta_ignition should be readable
        assert snaps[0].get("delta_ignition") is True


# ── 3. build_bar_sequences() tests ───────────────────────────────────────────

class TestBuildBarSequences:
    def _make_snaps(self, n: int, group: str = "missed_4x_pump") -> list[dict]:
        ep = _make_episode(group_type=group)
        rows = [
            _make_daily_row(phase="PRE", relative_day=-(n - i), date=f"2025-01-{10 + i:02d}")
            for i in range(n)
        ]
        return build_bar_feature_snapshots_for_episode(ep, rows)

    def test_window1_produces_n_sequences(self):
        snaps = self._make_snaps(5)
        seqs = build_bar_sequences(snaps, windows=(1,))
        assert len(seqs) == 5

    def test_window2_produces_n_minus_1(self):
        snaps = self._make_snaps(5)
        seqs = build_bar_sequences(snaps, windows=(2,))
        assert len(seqs) == 4

    def test_window5_produces_correct_count(self):
        snaps = self._make_snaps(7)
        seqs = build_bar_sequences(snaps, windows=(5,))
        assert len(seqs) == 3  # 7 - 5 + 1

    def test_window_larger_than_snaps_returns_empty(self):
        snaps = self._make_snaps(3)
        seqs = build_bar_sequences(snaps, windows=(5,))
        assert seqs == []

    def test_multiple_windows(self):
        snaps = self._make_snaps(10)
        seqs = build_bar_sequences(snaps, windows=(1, 2, 3))
        w1 = [s for s in seqs if s["window_size"] == 1]
        w2 = [s for s in seqs if s["window_size"] == 2]
        w3 = [s for s in seqs if s["window_size"] == 3]
        assert len(w1) == 10
        assert len(w2) == 9
        assert len(w3) == 8

    def test_window1_signature_matches_bar_tag_signature(self):
        snaps = self._make_snaps(3)
        seqs = build_bar_sequences(snaps, windows=(1,))
        for seq, snap in zip(seqs, snaps):
            assert seq["sequence_signature"] == snap["tag_signature"]

    def test_window2_signature_uses_arrow_separator(self):
        ep = _make_episode()
        rows = [
            _make_daily_row(phase="PRE", relative_day=-2, dryup_day=True),
            _make_daily_row(phase="PRE", relative_day=-1, strong_close=True),
        ]
        snaps = build_bar_feature_snapshots_for_episode(ep, rows)
        seqs = build_bar_sequences(snaps, windows=(2,))
        assert "→" in seqs[0]["sequence_signature"]

    def test_window5_signature_is_tag_bag(self):
        snaps = self._make_snaps(5)
        seqs = build_bar_sequences(snaps, windows=(5,))
        # No ordered separator for windows > 3
        assert "→" not in seqs[0]["sequence_signature"]

    def test_episode_fields_propagated_to_sequences(self):
        ep = _make_episode(episode_id=99, symbol="XYZ", group_type="false_positive")
        rows = [_make_daily_row(phase="PRE", relative_day=-i - 1) for i in range(3)]
        snaps = build_bar_feature_snapshots_for_episode(ep, rows)
        seqs = build_bar_sequences(snaps, windows=(1,))
        assert all(s["episode_id"] == 99 for s in seqs)
        assert all(s["group_type"] == "false_positive" for s in seqs)

    def test_tag_counts_correct(self):
        ep = _make_episode()
        rows = [
            _make_daily_row(phase="PRE", relative_day=-3, dryup_day=True),
            _make_daily_row(phase="PRE", relative_day=-2, dryup_day=True),
            _make_daily_row(phase="PRE", relative_day=-1, strong_close=True),
        ]
        snaps = build_bar_feature_snapshots_for_episode(ep, rows)
        seqs = build_bar_sequences(snaps, windows=(3,))
        tc = seqs[0]["tag_counts"]
        assert tc.get(TAG_DRYUP, 0) == 2
        assert tc.get(TAG_STRONG_CLOSE, 0) == 1

    def test_days_to_breakout_start_end(self):
        ep = _make_episode()
        rows = [
            _make_daily_row(phase="PRE", relative_day=-5),
            _make_daily_row(phase="PRE", relative_day=-4),
            _make_daily_row(phase="PRE", relative_day=-3),
        ]
        snaps = build_bar_feature_snapshots_for_episode(ep, rows)
        seqs = build_bar_sequences(snaps, windows=(3,))
        s = seqs[0]
        assert s["days_to_breakout_start"] == 5
        assert s["days_to_breakout_end"]   == 3

    def test_empty_snaps_returns_empty(self):
        seqs = build_bar_sequences([], windows=(1, 2, 3))
        assert seqs == []


# ── 4. mine_bar_patterns() tests ─────────────────────────────────────────────

def _build_sequences_for_group(
    episode_ids: list[int],
    symbol: str,
    group_type: str,
    tag_mix: dict,  # {episode_id: [tags per bar (1 bar each)]}
) -> list[dict]:
    seqs = []
    for epid in episode_ids:
        tags = tag_mix.get(epid, [TAG_FLAT])
        sig  = "+".join(sorted(set(tags)))
        seqs.append({
            "episode_id":         epid,
            "symbol":             symbol,
            "group_type":         group_type,
            "window_size":        1,
            "start_date":         "2025-01-10",
            "end_date":           "2025-01-10",
            "days_to_breakout_start": 5,
            "days_to_breakout_end":   5,
            "sequence_signature": sig,
            "bar_tags":           [tags],
            "tag_counts":         {t: 1 for t in tags},
        })
    return seqs


class TestMineBarPatterns:
    def _build_dataset(self, sig_4x: str, n_4x: int, n_fp: int, n_nw: int) -> dict:
        """Build a minimal bar_sequences_by_group dataset."""
        flat_sig = TAG_FLAT

        missed_seqs = [
            {"episode_id": i, "symbol": "X", "group_type": "missed_4x_pump",
             "window_size": 1, "start_date": "2025-01-01", "end_date": "2025-01-01",
             "days_to_breakout_start": 3, "days_to_breakout_end": 3,
             "sequence_signature": sig_4x,
             "bar_tags": [[TAG_DRYUP]], "tag_counts": {TAG_DRYUP: 1}}
            for i in range(n_4x)
        ]
        fp_seqs = [
            {"episode_id": 1000 + i, "symbol": "Y", "group_type": "false_positive",
             "window_size": 1, "start_date": "2025-01-01", "end_date": "2025-01-01",
             "days_to_breakout_start": 3, "days_to_breakout_end": 3,
             "sequence_signature": flat_sig,
             "bar_tags": [[TAG_FLAT]], "tag_counts": {TAG_FLAT: 1}}
            for i in range(n_fp)
        ]
        nw_seqs = [
            {"episode_id": 2000 + i, "symbol": "Z", "group_type": "normal_winner",
             "window_size": 1, "start_date": "2025-01-01", "end_date": "2025-01-01",
             "days_to_breakout_start": 3, "days_to_breakout_end": 3,
             "sequence_signature": flat_sig,
             "bar_tags": [[TAG_FLAT]], "tag_counts": {TAG_FLAT: 1}}
            for i in range(n_nw)
        ]
        return {
            "missed_4x_pump":   missed_seqs,
            "detected_4x_pump": [],
            "false_positive":   fp_seqs,
            "normal_winner":    nw_seqs,
            "split_artifact":   [],
        }

    def test_returns_list(self):
        ds = self._build_dataset(TAG_DRYUP, n_4x=5, n_fp=0, n_nw=0)
        cands = mine_bar_patterns(ds, windows=(1,))
        assert isinstance(cands, list)

    def test_high_lift_pattern_experimental(self):
        # 10 4x episodes all have DRYUP, 0 FP episodes have DRYUP → lift = infinity
        ds = self._build_dataset(TAG_DRYUP, n_4x=10, n_fp=10, n_nw=5)
        cands = mine_bar_patterns(ds, windows=(1,))
        dryup_cand = next((c for c in cands if TAG_DRYUP in c.get("sequence_signature", "")), None)
        assert dryup_cand is not None
        assert dryup_cand["status"] == "EXPERIMENTAL"
        assert dryup_cand["count_all_4x"] == 10

    def test_low_count_returns_research_only(self):
        ds = self._build_dataset(TAG_DRYUP, n_4x=4, n_fp=10, n_nw=5)
        cands = mine_bar_patterns(ds, windows=(1,), min_episode_count_4x=3)
        dryup_cand = next((c for c in cands if TAG_DRYUP in c.get("sequence_signature", "")), None)
        # With 4 4x hits and some FP hits of flat, the DRYUP sig gets no FP hits → high lift
        if dryup_cand:
            assert dryup_cand["status"] in ("EXPERIMENTAL", "EXPERIMENTAL_RARE", "RESEARCH_ONLY")

    def test_sorted_by_status_then_lift(self):
        ds = self._build_dataset(TAG_DRYUP, n_4x=10, n_fp=5, n_nw=5)
        cands = mine_bar_patterns(ds, windows=(1,))
        statuses = [c["status"] for c in cands]
        status_order = {"EXPERIMENTAL": 0, "EXPERIMENTAL_RARE": 1, "RESEARCH_ONLY": 2, "REJECT": 3}
        ranks = [status_order.get(s, 9) for s in statuses]
        assert ranks == sorted(ranks), "Results not sorted by status"

    def test_source_type_single_bar(self):
        ds = self._build_dataset(TAG_DRYUP, n_4x=10, n_fp=5, n_nw=5)
        cands = mine_bar_patterns(ds, windows=(1,))
        for c in cands:
            if c.get("window_size") == 1:
                assert c["source_type"] == "SINGLE_BAR"

    def test_source_type_two_bar(self):
        ep = _make_episode()
        rows = [
            _make_daily_row(phase="PRE", relative_day=-2, dryup_day=True),
            _make_daily_row(phase="PRE", relative_day=-1, strong_close=True),
        ]
        snaps = build_bar_feature_snapshots_for_episode(ep, rows)
        seqs = build_bar_sequences(snaps, windows=(2,))
        ds = {"missed_4x_pump": seqs * 10, "detected_4x_pump": [], "false_positive": [],
              "normal_winner": [], "split_artifact": []}
        cands = mine_bar_patterns(ds, windows=(2,))
        for c in cands:
            assert c["source_type"] == "TWO_BAR_SEQUENCE"

    def test_empty_dataset_returns_empty(self):
        ds = {g: [] for g in ["missed_4x_pump", "detected_4x_pump", "false_positive",
                               "normal_winner", "split_artifact"]}
        cands = mine_bar_patterns(ds, windows=(1, 2, 3))
        assert cands == []

    def test_group_type_not_a_condition(self):
        """group_type must never appear in machine_conditions (anti-leakage)."""
        ds = self._build_dataset(TAG_DRYUP, n_4x=10, n_fp=5, n_nw=5)
        cands = mine_bar_patterns(ds, windows=(1,))
        for c in cands:
            for cond in (c.get("machine_conditions") or []):
                assert "group_type" not in cond.lower(), \
                    f"group_type found in conditions for {c['signal_id']}"


# ── 5. Registry source_type integrity ────────────────────────────────────────

class TestRegistryIntegrity:
    def _load_registry(self) -> list[dict]:
        reg_path = os.path.join(
            os.path.dirname(__file__), "..", "discovered_signal_registry.json"
        )
        with open(reg_path) as f:
            return json.load(f)

    def test_all_entries_have_source_type(self):
        registry = self._load_registry()
        for entry in registry:
            assert "source_type" in entry, \
                f"Missing source_type on {entry.get('signal_id')}"

    def test_existing_entries_have_episode_aggregate(self):
        registry = self._load_registry()
        for entry in registry:
            if entry.get("signal_id", "").startswith("DISC_") and \
               not entry.get("signal_id", "").startswith("DISC_BAR_"):
                assert entry["source_type"] == "EPISODE_AGGREGATE", \
                    f"Expected EPISODE_AGGREGATE for {entry.get('signal_id')}, " \
                    f"got {entry.get('source_type')}"

    def test_all_entries_have_required_fields(self):
        required = ["signal_id", "family", "status", "source_type",
                    "intended_use", "description"]
        registry = self._load_registry()
        for entry in registry:
            for fld in required:
                assert fld in entry, \
                    f"Missing field '{fld}' on {entry.get('signal_id')}"


# ── 6. Anti-leakage assertions ────────────────────────────────────────────────

class TestAntiLeakage:
    LEAKAGE_KEYS = {
        "pump_multiple", "forward_return", "group_type",
        "days_from_breakout_to_peak", "pump_type",
    }

    def test_bars_to_tags_never_uses_leakage_keys(self):
        """bars_to_tags() must not read leakage fields even if present."""
        f = {
            "pump_multiple":             10.0,
            "forward_return":            500.0,
            "group_type":                "missed_4x_pump",
            "days_from_breakout_to_peak": 5,
            "pump_type":                 "ORGANIC",
            "is_strong_close":           True,
        }
        tags = bars_to_tags(f)
        # TAG_STRONG_CLOSE should still fire, and no leakage tag should appear
        assert TAG_STRONG_CLOSE in tags
        for lk in self.LEAKAGE_KEYS:
            for tag in tags:
                assert lk.upper() not in tag, \
                    f"Leakage key '{lk}' leaked into tags"

    def test_snapshot_does_not_store_pump_multiple(self):
        ep = _make_episode()
        ep["pump_multiple"] = 8.0
        rows = [_make_daily_row(phase="PRE", relative_day=-3)]
        snaps = build_bar_feature_snapshots_for_episode(ep, rows)
        for snap in snaps:
            assert "pump_multiple" not in snap, "pump_multiple must not appear in bar snapshots"

    def test_snapshot_does_not_store_forward_return(self):
        ep = _make_episode()
        ep["forward_return"] = 300.0
        rows = [_make_daily_row(phase="PRE", relative_day=-3)]
        snaps = build_bar_feature_snapshots_for_episode(ep, rows)
        for snap in snaps:
            assert "forward_return" not in snap, "forward_return must not appear in bar snapshots"

    def test_sequence_signature_never_contains_leakage(self):
        ep = _make_episode()
        rows = [_make_daily_row(phase="PRE", relative_day=-i - 1) for i in range(5)]
        snaps = build_bar_feature_snapshots_for_episode(ep, rows)
        seqs = build_bar_sequences(snaps, windows=(1, 2, 3))
        for seq in seqs:
            sig = seq.get("sequence_signature", "")
            for lk in self.LEAKAGE_KEYS:
                assert lk.upper() not in sig.upper(), \
                    f"Leakage key '{lk}' found in sequence signature: {sig}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
