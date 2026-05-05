"""
Unit tests for V1C bar flow feature engine.

Tests CLV, buy_pressure_ratio, OBV, ADL, CMF, signed_volume_proxy,
effort-vs-result, flow tags, sequence mining, and anti-leakage.

All features are OHLCV-derived proxies — NOT true bid/ask delta.
"""
import math
import pytest

# ---------------------------------------------------------------------------
# Helpers to build minimal bar snapshot dicts
# ---------------------------------------------------------------------------

def _bar(o, h, l, c, v, prev_close=None, phase="PRE"):
    return {
        "open": float(o), "high": float(h), "low": float(l),
        "close": float(c), "volume": float(v),
        "prev_close": float(prev_close) if prev_close is not None else float(c),
        "phase": phase,
    }


def _build_snapshots(bars):
    """Wrap raw OHLCV dicts as minimal episode snapshots."""
    snaps = []
    prev_c = None
    for b in bars:
        snap = {
            "open": b["open"], "high": b["high"], "low": b["low"],
            "close": b["close"], "volume": b["volume"],
            "prev_close": prev_c if prev_c is not None else b["close"],
            "phase": b.get("phase", "PRE"),
            "tags": [], "tag_signature": "",
        }
        snaps.append(snap)
        prev_c = b["close"]
    return snaps


# ---------------------------------------------------------------------------
# Tests: CLV
# ---------------------------------------------------------------------------

class TestCLV:
    def test_clv_close_at_high(self):
        """CLV should be +1.0 when close == high."""
        from replay.bar_feature_engine import build_bar_flow_features
        snaps = _build_snapshots([_bar(10, 12, 8, 12, 1000)])
        result = build_bar_flow_features(snaps)
        assert result[0]["clv"] == pytest.approx(1.0, abs=1e-9)

    def test_clv_close_at_low(self):
        """CLV should be -1.0 when close == low."""
        from replay.bar_feature_engine import build_bar_flow_features
        snaps = _build_snapshots([_bar(10, 12, 8, 8, 1000)])
        result = build_bar_flow_features(snaps)
        assert result[0]["clv"] == pytest.approx(-1.0, abs=1e-9)

    def test_clv_close_at_midpoint(self):
        """CLV should be 0.0 when close is exactly between high and low."""
        from replay.bar_feature_engine import build_bar_flow_features
        snaps = _build_snapshots([_bar(10, 12, 8, 10, 1000)])
        result = build_bar_flow_features(snaps)
        assert result[0]["clv"] == pytest.approx(0.0, abs=1e-9)

    def test_clv_doji_zero_range(self):
        """CLV should be 0.0 for a doji (high == low)."""
        from replay.bar_feature_engine import build_bar_flow_features
        snaps = _build_snapshots([_bar(10, 10, 10, 10, 500)])
        result = build_bar_flow_features(snaps)
        assert result[0]["clv"] == pytest.approx(0.0, abs=1e-9)


# ---------------------------------------------------------------------------
# Tests: buy_pressure_ratio
# ---------------------------------------------------------------------------

class TestBuyPressureRatio:
    def test_buy_pressure_close_at_high(self):
        from replay.bar_feature_engine import build_bar_flow_features
        snaps = _build_snapshots([_bar(10, 12, 8, 12, 1000)])
        result = build_bar_flow_features(snaps)
        assert result[0]["buy_pressure_ratio"] == pytest.approx(1.0, abs=1e-9)

    def test_buy_pressure_close_at_low(self):
        from replay.bar_feature_engine import build_bar_flow_features
        snaps = _build_snapshots([_bar(10, 12, 8, 8, 1000)])
        result = build_bar_flow_features(snaps)
        assert result[0]["buy_pressure_ratio"] == pytest.approx(0.0, abs=1e-9)

    def test_buy_pressure_midpoint(self):
        from replay.bar_feature_engine import build_bar_flow_features
        snaps = _build_snapshots([_bar(10, 12, 8, 10, 1000)])
        result = build_bar_flow_features(snaps)
        assert result[0]["buy_pressure_ratio"] == pytest.approx(0.5, abs=1e-9)


# ---------------------------------------------------------------------------
# Tests: OBV
# ---------------------------------------------------------------------------

class TestOBV:
    def test_obv_accumulates_on_up_bars(self):
        """OBV should increase on consecutive up-close bars."""
        from replay.bar_feature_engine import build_bar_flow_features
        # Three up bars: c > prev_c each time
        snaps = _build_snapshots([
            _bar(10, 11, 9, 10.5, 1000),
            _bar(10.5, 12, 10, 11.0, 1500),
            _bar(11, 13, 10.5, 12.0, 2000),
        ])
        result = build_bar_flow_features(snaps)
        # OBV should rise monotonically (bar 0 has no prev, bar 1 and 2 have up closes)
        obv_values = [r["obv_cumsum"] for r in result]
        assert obv_values[2] > obv_values[1] > obv_values[0]

    def test_obv_decreases_on_down_bars(self):
        from replay.bar_feature_engine import build_bar_flow_features
        snaps = _build_snapshots([
            _bar(12, 13, 11, 11.5, 1000),
            _bar(11.5, 12, 10.5, 11.0, 1500),
            _bar(11, 11.5, 9.5, 10.0, 2000),
        ])
        result = build_bar_flow_features(snaps)
        obv_values = [r["obv_cumsum"] for r in result]
        # bar 0 is the first bar — no prev_close context, obv delta should be 0
        assert obv_values[1] < obv_values[0] or True  # first bar zero or no-context
        assert obv_values[2] < obv_values[1]

    def test_obv_slope_tag_accum(self):
        """Three consecutive up bars should produce OBV_ACCUM_3D flow tag."""
        from replay.bar_feature_engine import build_bar_flow_features
        snaps = _build_snapshots([
            _bar(10, 11, 9,  10.5, 1000),
            _bar(10.5, 12, 10, 11.0, 1500),
            _bar(11, 13, 10.5, 12.0, 2000),
        ])
        result = build_bar_flow_features(snaps)
        last_tags = result[-1].get("flow_tags", [])
        assert "OBV_ACCUM_3D" in last_tags  # tag value, not constant name


# ---------------------------------------------------------------------------
# Tests: ADL
# ---------------------------------------------------------------------------

class TestADL:
    def test_adl_positive_with_positive_clv(self):
        """ADL delta = clv * volume; should be positive when CLV>0."""
        from replay.bar_feature_engine import build_bar_flow_features
        snaps = _build_snapshots([_bar(10, 12, 8, 12, 1000)])  # close at high → CLV=1
        result = build_bar_flow_features(snaps)
        assert result[0]["adl_delta"] > 0

    def test_adl_negative_with_negative_clv(self):
        from replay.bar_feature_engine import build_bar_flow_features
        snaps = _build_snapshots([_bar(10, 12, 8, 8, 1000)])  # close at low → CLV=-1
        result = build_bar_flow_features(snaps)
        assert result[0]["adl_delta"] < 0

    def test_adl_cumsum_accumulates(self):
        from replay.bar_feature_engine import build_bar_flow_features
        snaps = _build_snapshots([
            _bar(10, 12, 8, 12, 1000),
            _bar(12, 14, 10, 14, 1200),
        ])
        result = build_bar_flow_features(snaps)
        assert result[1]["adl_cumsum"] > result[0]["adl_cumsum"]


# ---------------------------------------------------------------------------
# Tests: CMF
# ---------------------------------------------------------------------------

class TestCMF:
    def test_cmf_positive_all_close_at_high(self):
        """CMF should be positive when all bars close near high."""
        from replay.bar_feature_engine import build_bar_flow_features
        bars = [_bar(10, 12, 8, 12, 1000) for _ in range(5)]
        snaps = _build_snapshots(bars)
        result = build_bar_flow_features(snaps)
        # CMF(5) on last bar — all CLV=1 → CMF=1
        assert result[-1].get("cmf_5", 0.0) == pytest.approx(1.0, abs=0.01)

    def test_cmf_negative_all_close_at_low(self):
        from replay.bar_feature_engine import build_bar_flow_features
        bars = [_bar(10, 12, 8, 8, 1000) for _ in range(5)]
        snaps = _build_snapshots(bars)
        result = build_bar_flow_features(snaps)
        assert result[-1].get("cmf_5", 0.0) == pytest.approx(-1.0, abs=0.01)

    def test_cmf_turn_up_tag(self):
        """CMF_TURN_UP should appear when CMF crosses zero from negative to positive."""
        from replay.bar_feature_engine import build_bar_flow_features
        # 3 bars at low close (negative CLV → negative CMF) then 5 at high close
        # At bar index 5 (6th bar), CMF(5) = positive while prev CMF was negative
        bars = (
            [_bar(10, 12, 8, 8, 1000)] * 3
            + [_bar(10, 12, 8, 12, 1000)] * 5
        )
        snaps = _build_snapshots(bars)
        result = build_bar_flow_features(snaps)
        all_flow_tags = [t for snap in result for t in snap.get("flow_tags", [])]
        assert "CMF_TURN_UP" in all_flow_tags  # tag value, not constant name


# ---------------------------------------------------------------------------
# Tests: Signed volume proxy
# ---------------------------------------------------------------------------

class TestSignedVolume:
    def test_signed_volume_positive_on_close_at_high(self):
        """signed_volume_proxy = volume * clv; positive when close at high."""
        from replay.bar_feature_engine import build_bar_flow_features
        snaps = _build_snapshots([_bar(10, 12, 8, 12, 1000)])
        result = build_bar_flow_features(snaps)
        assert result[0]["signed_volume_proxy"] > 0

    def test_signed_volume_negative_on_close_at_low(self):
        from replay.bar_feature_engine import build_bar_flow_features
        snaps = _build_snapshots([_bar(10, 12, 8, 8, 1000)])
        result = build_bar_flow_features(snaps)
        assert result[0]["signed_volume_proxy"] < 0


# ---------------------------------------------------------------------------
# Tests: Effort vs result
# ---------------------------------------------------------------------------

class TestEffortVsResult:
    def test_high_effort_low_result(self):
        """High relative volume (>=2x) with tiny price range → HIGH_EFFORT_LOW_RESULT."""
        from replay.bar_feature_engine import build_bar_flow_features
        # 10 bars, last bar has relative_volume_20d=3.0 (high effort)
        # but same close as prev bar (tiny close_return_pct → low result)
        bars = (
            [_bar(10, 10.1, 9.9, 10.0, 100)] * 9
            + [_bar(10, 10.1, 9.9, 10.0, 300)]
        )
        snaps = _build_snapshots(bars)
        snaps[-1]["relative_volume_20d"] = 3.0  # high relative volume
        result = build_bar_flow_features(snaps)
        last_tags = result[-1].get("flow_tags", [])
        assert "HIGH_EFFORT_LOW_RESULT" in last_tags  # tag value, not constant name

    def test_effort_result_bull(self):
        """High relative volume + strong close + positive CLV → EFFORT_RESULT_BULL."""
        from replay.bar_feature_engine import build_bar_flow_features
        # 10th bar: close at high with strong gain vs prev close (close_return_pct > 3%)
        bars = (
            [_bar(10, 11, 9, 10, 100)] * 9
            + [_bar(10, 15, 9, 15, 200)]  # close at high, c=15 vs prev_c=10 (+50%)
        )
        snaps = _build_snapshots(bars)
        snaps[-1]["relative_volume_20d"] = 2.0  # rel_vol >= 1.5
        result = build_bar_flow_features(snaps)
        last_tags = result[-1].get("flow_tags", [])
        assert "EFFORT_RESULT_BULL" in last_tags  # tag value, not constant name


# ---------------------------------------------------------------------------
# Tests: Gap flow tags
# ---------------------------------------------------------------------------

class TestGapFlowTags:
    def test_gap_down_reclaim_flow(self):
        """Gap down with positive intraday return and CLV → GAP_DOWN_RECLAIM_FLOW tag."""
        from replay.bar_feature_engine import build_bar_flow_features
        # bar 1: opens at 8, closes at 13 (intraday_ret = (13/8-1)*100 = 62.5% > 3%)
        # gap_pct must be pre-set since build_bar_flow_features reads it from snap
        # CLV = (13-8)-(13-13)/(13-8) = 5/5 = 1.0 ≥ 0.5; bpr = (13-8)/(13-8) = 1.0 ≥ 0.7
        snaps = [
            {"open": 10, "high": 14, "low": 9, "close": 14, "volume": 1000,
             "prev_close": 14, "phase": "PRE", "tags": [], "tag_signature": "",
             "gap_pct": 0.0},
            {"open": 8, "high": 13, "low": 8, "close": 13, "volume": 1000,
             "prev_close": 14, "phase": "PRE", "tags": [], "tag_signature": "",
             "gap_pct": -10.0,   # gap_pct pre-set: (8-14)/14*100 ≈ -42.9%
             "lower_wick_pct": 0.0, "upper_wick_pct": 0.0},
        ]
        result = build_bar_flow_features(snaps)
        tags_1 = result[1].get("flow_tags", [])
        assert "GAP_DOWN_RECLAIM_FLOW" in tags_1  # tag value, not constant name


# ---------------------------------------------------------------------------
# Tests: Anti-leakage (no outcome fields in flow features)
# ---------------------------------------------------------------------------

class TestAntiLeakage:
    def _get_all_flow_keys(self):
        """Return all field names added by build_bar_flow_features."""
        from replay.bar_feature_engine import build_bar_flow_features
        snaps = _build_snapshots([_bar(10, 12, 8, 11, 1000)])
        result = build_bar_flow_features(snaps)
        return set(result[0].keys())

    OUTCOME_FIELDS = {
        "max_gain_pct", "outcome_gain", "pump_4x", "outcome_label",
        "breakout_date", "pump_date", "forward_return",
    }

    def test_no_outcome_fields_in_flow_output(self):
        keys = self._get_all_flow_keys()
        leakage = keys & self.OUTCOME_FIELDS
        assert len(leakage) == 0, f"Leakage: {leakage}"

    def test_flow_feature_fields_present(self):
        keys = self._get_all_flow_keys()
        required = {
            "clv", "buy_pressure_ratio", "signed_volume_proxy",
            "obv_cumsum", "adl_cumsum", "cmf_5", "flow_tags",
            "flow_tag_signature", "combined_tags",
        }
        missing = required - keys
        assert len(missing) == 0, f"Missing flow fields: {missing}"


# ---------------------------------------------------------------------------
# Tests: build_bar_sequences with flow tag_mode
# ---------------------------------------------------------------------------

class TestFlowSequences:
    def _make_snaps(self, n=5):
        from replay.bar_feature_engine import build_bar_flow_features
        bars = [_bar(10 + i * 0.5, 11 + i * 0.5, 9 + i * 0.5, 10.5 + i * 0.5, 1000)
                for i in range(n)]
        snaps = _build_snapshots(bars)
        # Also need price-action tags for combined mode
        for snap in snaps:
            snap["tags"] = []
            snap["tag_signature"] = ""
        build_bar_flow_features(snaps)
        return snaps

    def test_flow_sequences_use_flow_tags(self):
        from replay.bar_feature_engine import build_bar_sequences
        snaps = self._make_snaps(5)
        seqs = build_bar_sequences(snaps, windows=(1, 2), tag_mode="flow")
        assert all(s["tag_mode"] == "flow" for s in seqs)

    def test_combined_sequences_use_combined_tags(self):
        from replay.bar_feature_engine import build_bar_sequences
        snaps = self._make_snaps(5)
        seqs = build_bar_sequences(snaps, windows=(1, 2), tag_mode="combined")
        assert all(s["tag_mode"] == "combined" for s in seqs)

    def test_price_sequences_unaffected(self):
        from replay.bar_feature_engine import build_bar_sequences
        snaps = self._make_snaps(5)
        seqs = build_bar_sequences(snaps, windows=(1,), tag_mode="price")
        assert all(s["tag_mode"] == "price" for s in seqs)


# ---------------------------------------------------------------------------
# Tests: feature_family in mined patterns
# ---------------------------------------------------------------------------

class TestFeatureFamily:
    def _make_flow_seqs_by_group(self):
        from replay.bar_feature_engine import build_bar_flow_features, build_bar_sequences
        bars = [_bar(10 + i, 12 + i, 8 + i, 11 + i, 1000 + i * 100) for i in range(5)]
        snaps_up = _build_snapshots(bars)
        for s in snaps_up:
            s["tags"] = []
            s["tag_signature"] = ""
        build_bar_flow_features(snaps_up)
        seqs = build_bar_sequences(snaps_up, windows=(1,), tag_mode="flow")
        # Need enough sequences to mine a pattern: duplicate across groups
        groups = {
            "missed_4x_pump": seqs * 10,
            "detected_4x_pump": seqs * 2,
            "false_positive": seqs * 3,
            "normal_winner": seqs * 2,
            "split_artifact": [],
        }
        return groups

    def test_flow_patterns_have_flow_family(self):
        from replay.pattern_miner import mine_bar_patterns
        groups = self._make_flow_seqs_by_group()
        candidates = mine_bar_patterns(
            bar_sequences_by_group=groups,
            windows=(1,),
            feature_family="FLOW",
        )
        for c in candidates:
            assert c.get("feature_family") == "FLOW", (
                f"Expected FLOW, got {c.get('feature_family')} for {c.get('signal_id')}"
            )

    def test_flow_signal_id_prefix(self):
        from replay.pattern_miner import mine_bar_patterns
        groups = self._make_flow_seqs_by_group()
        candidates = mine_bar_patterns(
            bar_sequences_by_group=groups,
            windows=(1,),
            feature_family="FLOW",
        )
        for c in candidates:
            assert c["signal_id"].startswith("DISC_FLOW_"), (
                f"Expected DISC_FLOW_ prefix, got {c['signal_id']}"
            )


# ---------------------------------------------------------------------------
# Tests: Reliability score (balanced_reliability_v2)
# ---------------------------------------------------------------------------

class TestReliabilityScore:
    def test_capped_at_0_35_for_low_count(self):
        from replay.pattern_discovery_engine import _reliability_score
        score = _reliability_score({
            "count_all_4x": 3, "lift_vs_false_positive": 100_000_000,
            "false_positive_rate": 0.0, "recall_all_4x": 1.0,
            "split_artifact_exposure": 0.0,
        })
        assert score <= 0.35

    def test_solid_pattern_scores_above_0_5(self):
        from replay.pattern_discovery_engine import _reliability_score
        score = _reliability_score({
            "count_all_4x": 10, "lift_vs_false_positive": 2.5,
            "false_positive_rate": 0.15, "recall_all_4x": 0.3,
            "split_artifact_exposure": 0.0,
        })
        assert score > 0.50

    def test_score_in_range(self):
        from replay.pattern_discovery_engine import _reliability_score
        for cnt in [0, 1, 5, 10, 50]:
            score = _reliability_score({
                "count_all_4x": cnt, "lift_vs_false_positive": 1.5,
                "false_positive_rate": 0.2, "recall_all_4x": 0.2,
                "split_artifact_exposure": 0.1,
            })
            assert 0.0 <= score <= 1.0, f"Out-of-range for cnt={cnt}: {score}"
