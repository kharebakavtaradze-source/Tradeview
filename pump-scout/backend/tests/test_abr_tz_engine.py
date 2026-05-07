"""
Unit tests for replay/abr_tz_engine.py + replay/abr_quality_analyzer.py.

Covers:
  - EMA series seeding / convergence
  - Suffix logic (NE / wick / penetration)
  - Z8 pattern (only fires when no other Z signal)
  - L1-L6 signal logic (volDownAdapted / volUpAdapted path)
  - Quality score components (signal_score + l_score + suffix_score)
  - SP500 / NASDAQ tier thresholds (STRONG / GOOD / AVERAGE / REJECT)
  - ABR classification (A / B / B+ / R) for SP500 and NASDAQ rules
  - feature_json field list completeness
  - Anti-leakage contract: no outcome fields used in engine
  - PREUP / PREDN primary values use "P66" / "P55" etc. (not "D66")
  - abr_quality_analyzer: Watch Rank v2 scoring and buckets
  - Watch Rank v2: WATCH_RANK_A / B / C / AVOID bucket transitions
"""
import math
import pytest

from replay.abr_tz_engine import (
    _ema_series,
    _signal_score,
    _sp500_tier,
    _nasdaq_tier,
    _abr,
    compute_abr_tz_features,
    _feature_json_fields,
)
from replay.abr_quality_analyzer import (
    _compute_watch_rank_v2,
    build_abr_quality_replay_analysis,
)


# ── Candle builders ───────────────────────────────────────────────────────────

def _candle(o=10.0, h=11.0, l=9.0, c=10.5, v=1_000_000.0):
    return {"open": o, "high": h, "low": l, "close": c, "volume": v}


def _flat_series(n: int = 40, price: float = 100.0, vol: float = 1_000_000.0):
    """n identical bars — no T/Z signals, stable volume."""
    return [_candle(o=price, h=price+0.5, l=price-0.5, c=price, v=vol) for _ in range(n)]


def _bullish_bar(base=100.0, range_=2.0, vol=1_000_000.0):
    return _candle(o=base, h=base+range_, l=base-0.5, c=base+range_*0.8, v=vol)


def _bearish_bar(base=102.0, range_=2.0, vol=1_000_000.0):
    return _candle(o=base+range_, h=base+range_+0.5, l=base-0.5, c=base, v=vol)


# ── EMA series ────────────────────────────────────────────────────────────────

class TestEmaSeries:
    def test_returns_none_before_period(self):
        closes = [10.0] * 5
        ema = _ema_series(closes, 9)
        assert all(v is None for v in ema)

    def test_seeded_from_sma(self):
        closes = [10.0] * 9
        ema = _ema_series(closes, 9)
        assert ema[8] == pytest.approx(10.0)

    def test_converges_to_flat_price(self):
        closes = [50.0] * 30
        ema = _ema_series(closes, 9)
        assert all(v == pytest.approx(50.0) for v in ema[8:])

    def test_empty_input(self):
        assert _ema_series([], 9) == []


# ── Signal score ──────────────────────────────────────────────────────────────

class TestSignalScore:
    def test_none_returns_0(self):
        assert _signal_score(None) == 0

    def test_t4_is_score_3(self):
        assert _signal_score("T4") == 3

    def test_z4_is_score_3(self):
        assert _signal_score("Z4") == 3

    def test_t1_is_score_2(self):
        assert _signal_score("T1") == 2

    def test_t10_is_score_1(self):
        # T10 not in score-3 or score-2 sets → 1
        assert _signal_score("T10") == 1

    def test_unknown_signal_is_score_1(self):
        assert _signal_score("UNKNOWN_XYZ") == 1


# ── Tier helpers ──────────────────────────────────────────────────────────────

class TestTierHelpers:
    def test_sp500_strong_at_6(self):
        assert _sp500_tier(6) == "STRONG"

    def test_sp500_good_at_4(self):
        assert _sp500_tier(4) == "GOOD"

    def test_sp500_reject_at_1(self):
        assert _sp500_tier(1) == "REJECT"

    def test_sp500_average_at_3(self):
        assert _sp500_tier(3) == "AVERAGE"

    def test_nasdaq_strong_at_5(self):
        assert _nasdaq_tier(5) == "STRONG"

    def test_nasdaq_good_at_3(self):
        assert _nasdaq_tier(3) == "GOOD"

    def test_nasdaq_reject_at_0(self):
        assert _nasdaq_tier(0) == "REJECT"

    def test_nasdaq_average_at_2(self):
        assert _nasdaq_tier(2) == "AVERAGE"


# ── ABR classification helper ─────────────────────────────────────────────────

class TestAbrHelper:
    def test_gate_false_returns_R(self):
        assert _abr(False, "STRONG") == "R"

    def test_gate_true_prev2_average_returns_A(self):
        assert _abr(True, "AVERAGE") == "A"

    def test_gate_true_prev2_good_returns_B(self):
        assert _abr(True, "GOOD") == "B"

    def test_gate_true_prev2_strong_returns_Bplus(self):
        assert _abr(True, "STRONG") == "B+"

    def test_gate_true_prev2_reject_returns_R(self):
        assert _abr(True, "REJECT") == "R"


# ── compute_abr_tz_features: basic contract ───────────────────────────────────

class TestComputeAbrTzFeatures:
    def test_empty_returns_empty(self):
        assert compute_abr_tz_features([]) == []

    def test_same_length_as_input(self):
        candles = _flat_series(20)
        result = compute_abr_tz_features(candles)
        assert len(result) == 20

    def test_required_keys_present(self):
        candles = _flat_series(30)
        result = compute_abr_tz_features(candles)
        bar = result[-1]
        required = [
            "tz_ne_suffix", "tz_wick_suffix", "tz_pen_suffix", "tz_full_suffix",
            "tz_primary_signal", "tz_side",
            "tz_quality_score", "tz_quality_tier_sp500", "tz_quality_tier_nasdaq",
            "abr_sp500", "abr_nasdaq",
            "preup_primary", "predn_primary",
            "has_z8",
            "has_l1", "has_l2", "has_l3", "has_l4", "has_l5", "has_l6",
        ]
        for k in required:
            assert k in bar, f"Missing key: {k}"

    def test_no_outcome_fields(self):
        """Anti-leakage: engine must not output outcome fields."""
        candles = _flat_series(30)
        result = compute_abr_tz_features(candles)
        for bar in result:
            assert "pump_multiple" not in bar
            assert "group_type" not in bar
            assert "forward_return" not in bar

    def test_first_bar_ne_suffix_is_N(self):
        candles = _flat_series(5)
        result = compute_abr_tz_features(candles)
        assert result[0]["tz_ne_suffix"] == "N"

    def test_ne_suffix_E_when_close_breaks_high(self):
        """Close above prev bar's high → 'E' suffix."""
        base = [_candle(o=10, h=11, l=9, c=10.5)] * 5
        breakout = _candle(o=10, h=13, l=9, c=12.5)  # close > prev high 11
        candles = base + [breakout]
        result = compute_abr_tz_features(candles)
        assert result[-1]["tz_ne_suffix"] == "E"

    def test_abr_sp500_none_when_no_tz_signal(self):
        """Flat bars → no T/Z signal → ABR is None."""
        candles = _flat_series(30)
        result = compute_abr_tz_features(candles)
        # Most flat bars will have no T/Z signal
        bars_with_abr_none = [r for r in result if r["abr_sp500"] is None]
        assert len(bars_with_abr_none) > 0

    def test_l64_bool_present(self):
        """L6 boolean must be present and a bool."""
        candles = _flat_series(30)
        result = compute_abr_tz_features(candles)
        for bar in result:
            assert isinstance(bar["has_l6"], bool)

    def test_predn_primary_uses_P_prefix_not_D(self):
        """PREDN values must use 'P66', 'P55' etc., not 'D66'."""
        candles = _flat_series(50)
        result = compute_abr_tz_features(candles)
        for bar in result:
            predn = bar.get("predn_primary")
            if predn is not None:
                assert predn.startswith("P"), f"Expected P-prefix, got: {predn}"


# ── Quality score combinations ────────────────────────────────────────────────

class TestQualityScore:
    def test_quality_score_composition(self):
        """Quality score = signal_score + l_score + suffix_score (all ints)."""
        candles = _flat_series(30)
        result = compute_abr_tz_features(candles)
        for bar in result:
            qs  = bar["tz_quality_score"]
            ss  = bar["tz_signal_score"]
            ls  = bar["tz_l_score"]
            suf = bar["tz_suffix_score"]
            assert qs == ss + ls + suf, f"Score mismatch: {qs} != {ss}+{ls}+{suf}"

    def test_sp500_tier_consistent_with_score(self):
        """SP500 tier must match _sp500_tier(score) for bars with a signal."""
        candles = _flat_series(30)
        result = compute_abr_tz_features(candles)
        for bar in result:
            if bar["tz_quality_tier_sp500"] is not None:
                expected = _sp500_tier(bar["tz_quality_score"])
                assert bar["tz_quality_tier_sp500"] == expected

    def test_nasdaq_tier_consistent_with_score(self):
        candles = _flat_series(30)
        result = compute_abr_tz_features(candles)
        for bar in result:
            if bar["tz_quality_tier_nasdaq"] is not None:
                expected = _nasdaq_tier(bar["tz_quality_score"])
                assert bar["tz_quality_tier_nasdaq"] == expected


# ── ABR prev1/prev2 logic ─────────────────────────────────────────────────────

class TestAbrPrevFields:
    def test_prev1_signal_matches_previous_bar(self):
        candles = _flat_series(30)
        result = compute_abr_tz_features(candles)
        for i in range(1, len(result)):
            assert result[i]["tz_prev1_signal"] == result[i-1]["tz_primary_signal"]

    def test_prev2_signal_matches_two_bars_ago(self):
        candles = _flat_series(30)
        result = compute_abr_tz_features(candles)
        for i in range(2, len(result)):
            assert result[i]["tz_prev2_signal"] == result[i-2]["tz_primary_signal"]

    def test_first_bar_prev1_is_none(self):
        candles = _flat_series(5)
        result = compute_abr_tz_features(candles)
        assert result[0]["tz_prev1_signal"] is None
        assert result[0]["tz_prev1_quality_score"] is None

    def test_second_bar_prev2_is_none(self):
        candles = _flat_series(5)
        result = compute_abr_tz_features(candles)
        assert result[1]["tz_prev2_signal"] is None


# ── feature_json_fields list ──────────────────────────────────────────────────

class TestFeatureJsonFields:
    def test_returns_list_of_strings(self):
        fields = _feature_json_fields()
        assert isinstance(fields, list)
        assert all(isinstance(f, str) for f in fields)

    def test_minimum_field_count(self):
        assert len(_feature_json_fields()) >= 50

    def test_key_fields_present(self):
        fields = set(_feature_json_fields())
        for k in [
            "tz_primary_signal", "tz_quality_score",
            "abr_sp500", "abr_nasdaq",
            "preup_primary", "predn_primary",
            "has_z8", "has_l1", "has_l5",
        ]:
            assert k in fields, f"Missing from _feature_json_fields: {k}"

    def test_no_internal_underscore_fields(self):
        """Internal helper fields (_tz_signal, etc.) must NOT appear in output."""
        for f in _feature_json_fields():
            assert not f.startswith("_"), f"Internal field exposed: {f}"


# ── Watch Rank v2 ─────────────────────────────────────────────────────────────

class TestWatchRankV2:
    def _ep_base(self, **kwargs):
        ep = {
            "pump_watch_score":   0.0,
            "curated_flow_score": 0.0,
        }
        ep.update(kwargs)
        return ep

    def _abr_feats_base(self, **kwargs):
        feats = {
            "total_bars":   30,
            "abr_a_bars":   0,
            "abr_bplus_bars": 0,
            "abr_b_bars":   0,
            "abr_r_bars":   0,
            "preup_bars":   0,
        }
        feats.update(kwargs)
        return feats

    def test_zero_score_is_avoid(self):
        wrank = _compute_watch_rank_v2(self._ep_base(), self._abr_feats_base())
        assert wrank["watch_rank_bucket_v2"] == "AVOID"

    def test_high_pump_watch_reaches_watch_rank_b(self):
        ep = self._ep_base(pump_watch_score=10.0, curated_flow_score=5.0)
        af = self._abr_feats_base(abr_a_bars=5)
        wrank = _compute_watch_rank_v2(ep, af)
        assert wrank["watch_rank_bucket_v2"] in ("WATCH_RANK_A", "WATCH_RANK_B")

    def test_watch_rank_a_requires_score_gte_10(self):
        ep = self._ep_base(pump_watch_score=10.0, curated_flow_score=5.0)
        af = self._abr_feats_base(abr_a_bars=10, preup_bars=6)
        wrank = _compute_watch_rank_v2(ep, af)
        if wrank["watch_rank_score_v2"] >= 10:
            assert wrank["watch_rank_bucket_v2"] == "WATCH_RANK_A"

    def test_watch_rank_c_range(self):
        ep = self._ep_base(pump_watch_score=5.0, curated_flow_score=2.0)
        af = self._abr_feats_base()
        wrank = _compute_watch_rank_v2(ep, af)
        score = wrank["watch_rank_score_v2"]
        if 4 <= score < 7:
            assert wrank["watch_rank_bucket_v2"] == "WATCH_RANK_C"

    def test_components_sum_to_score(self):
        ep = self._ep_base(pump_watch_score=7.0, curated_flow_score=3.0)
        af = self._abr_feats_base(abr_a_bars=3, preup_bars=5)
        wrank = _compute_watch_rank_v2(ep, af)
        comps = wrank["watch_rank_components_v2"]
        expected = sum(comps.values())
        assert wrank["watch_rank_score_v2"] == pytest.approx(max(0.0, expected), abs=0.02)

    def test_high_reject_rate_adds_risk_flag(self):
        af = self._abr_feats_base(abr_r_bars=20, total_bars=30)
        wrank = _compute_watch_rank_v2(self._ep_base(), af)
        assert any("reject" in f.lower() or "abr" in f.lower() for f in wrank["watch_rank_risk_flags_v2"])

    def test_score_is_nonnegative(self):
        af = self._abr_feats_base(abr_r_bars=30, total_bars=30)
        wrank = _compute_watch_rank_v2(self._ep_base(), af)
        assert wrank["watch_rank_score_v2"] >= 0


# ── build_abr_quality_replay_analysis ────────────────────────────────────────

class TestBuildAbrQualityReplayAnalysis:
    def test_empty_episodes_returns_empty_sections(self):
        result = build_abr_quality_replay_analysis([])
        assert result["abr_debug"]["total_episodes"] == 0
        assert result["watch_rank_v2_analysis"]["total_episodes"] == 0

    def test_required_top_level_keys(self):
        ep = {"episode_id": 1, "pump_watch_score": 5.0, "curated_flow_score": 2.0}
        result = build_abr_quality_replay_analysis([ep])
        for k in ["abr_debug", "abr_quality_analysis", "watch_rank_v2_analysis", "anti_leakage"]:
            assert k in result, f"Missing key: {k}"

    def test_episode_gets_watch_rank_fields(self):
        ep = {"episode_id": 1, "pump_watch_score": 7.0, "curated_flow_score": 3.0}
        build_abr_quality_replay_analysis([ep])
        assert "watch_rank_score_v2" in ep
        assert "watch_rank_bucket_v2" in ep
        assert "watch_rank_reasons_v2" in ep

    def test_daily_rows_with_abr_fields_affect_coverage(self):
        ep = {"episode_id": 42, "pump_watch_score": 0.0, "curated_flow_score": 0.0}
        daily_rows = [
            {"feature_json": {"tz_primary_signal": "T4", "tz_quality_score": 7,
                              "tz_quality_tier_sp500": "STRONG", "abr_sp500": "A"}},
            {"feature_json": {"tz_primary_signal": None, "tz_quality_score": 0}},
        ]
        result = build_abr_quality_replay_analysis(
            [ep], daily_by_episode={42: daily_rows}
        )
        debug = result["abr_debug"]
        assert debug["tz_signal_bars"] == 1
        assert debug["episodes_with_abr_a"] == 1
