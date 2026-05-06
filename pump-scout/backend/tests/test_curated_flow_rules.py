"""
Unit tests for replay/curated_flow_rules.py — Part 11.

Covers:
  - Rule matching for all 5 curated badges (single-bar flow, price, 5-bar window)
  - Score computation: HIGH / MEDIUM / LOW / IGNORE bucket assignment
  - Context bonuses and risk penalties
  - Anti-leakage assertion (_assert_no_leakage)
  - Export field existence via score_episode_curated_flow
"""
import pytest

from replay.curated_flow_rules import (
    BADGE_DIVERGENCE_ABSORB_PRESSURE,
    BADGE_DIVERGENCE_ACCUM,
    BADGE_BULLISH_ACCUM,
    BADGE_SUPPLY_ABSORB,
    BADGE_IGNITION_CONFIRM,
    BADGE_GAP_RESET_RECLAIM,
    ALL_CURATED_BADGES,
    evaluate_curated_flow_badges_from_snapshots,
    evaluate_curated_rules_on_snaps,
    compute_curated_flow_score,
    score_episode_curated_flow,
)


# ── Snapshot builders ─────────────────────────────────────────────────────────

def _snap(flow_tags=None, tags=None):
    """Minimal bar snapshot dict."""
    return {
        "flow_tags": list(flow_tags or []),
        "tags":      list(tags or []),
        "date":      "T-1",
    }


def _ep(**kwargs):
    """Minimal episode dict with safe pre-window defaults."""
    base = {
        "dryup_day_count_pre":          0,
        "d_confluence_day_count_pre":   0,
        "compression_days_pre":         0,
        "had_accumulation_like":        False,
        "had_spring_test_lps":          False,
        "split_context":                "NO_SPLIT",
        "median_dollar_volume_pre":     200_000,
        "high_expansion_risk_day_count_pre": 0,
        "split_artifact_risk":          False,
    }
    base.update(kwargs)
    return base


# ── Rule 0: DIVERGENCE_ABSORB_PRESSURE (run 142 strict variant) ──────────────

class TestRule0DivergenceAbsorbPressure:
    _tags = {
        "ADL_ACCUM_3D", "BUY_PRESSURE_HIGH", "CLOSE_HIGH",
        "CMF_NEGATIVE", "LOWER_WICK_ABSORPTION", "OBV_ACCUM_3D",
    }

    def test_full_match(self):
        snaps = [_snap(flow_tags=self._tags)]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_DIVERGENCE_ABSORB_PRESSURE in res["curated_flow_badges"]

    def test_partial_no_match_missing_lower_wick(self):
        partial = self._tags - {"LOWER_WICK_ABSORPTION"}
        snaps = [_snap(flow_tags=partial)]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_DIVERGENCE_ABSORB_PRESSURE not in res["curated_flow_badges"]

    def test_both_absorb_and_accum_fire_independently(self):
        # Remove LOWER_WICK_ABSORPTION → only ACCUM fires; add it → both fire
        accum_only = self._tags - {"LOWER_WICK_ABSORPTION"}
        snaps = [_snap(flow_tags=self._tags), _snap(flow_tags=accum_only)]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_DIVERGENCE_ABSORB_PRESSURE in res["curated_flow_badges"]
        assert BADGE_DIVERGENCE_ACCUM in res["curated_flow_badges"]

    def test_score_weight_is_higher_than_accum(self):
        # ABSORB_PRESSURE weight=5, ACCUM weight=4 → only max is used
        badges = [BADGE_DIVERGENCE_ABSORB_PRESSURE, BADGE_DIVERGENCE_ACCUM]
        ep = _ep(dryup_day_count_pre=10)
        res = compute_curated_flow_score(badges, ep)
        # Max of (5, 4) = 5; suppressed reason should appear
        assert any("double-count suppressed" in r for r in res["curated_flow_reasons"])

    def test_matched_bars_populated(self):
        snaps = [_snap(flow_tags=self._tags)]
        res = evaluate_curated_flow_badges_from_snapshots(snaps)
        assert res["exact_match_count"] >= 1
        assert any(mb["badge"] == BADGE_DIVERGENCE_ABSORB_PRESSURE
                   for mb in res["matched_bars"])


# ── Rule 1: DIVERGENCE_ACCUM ─────────────────────────────────────────────────

class TestRule1DivergenceAccum:
    _tags = {"ADL_ACCUM_3D", "BUY_PRESSURE_HIGH", "CLOSE_HIGH", "CMF_NEGATIVE", "OBV_ACCUM_3D"}

    def test_full_match(self):
        snaps = [_snap(flow_tags=self._tags)]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_DIVERGENCE_ACCUM in res["curated_flow_badges"]

    def test_partial_no_match(self):
        partial = self._tags - {"CMF_NEGATIVE"}
        snaps = [_snap(flow_tags=partial)]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_DIVERGENCE_ACCUM not in res["curated_flow_badges"]

    def test_match_on_any_bar(self):
        snaps = [
            _snap(flow_tags=set()),
            _snap(flow_tags=self._tags),
        ]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_DIVERGENCE_ACCUM in res["curated_flow_badges"]

    def test_not_matched_from_price_tags(self):
        # Rule 1 is flow-mode; these tags in snap["tags"] should not trigger it
        snaps = [_snap(flow_tags=set(), tags=self._tags)]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_DIVERGENCE_ACCUM not in res["curated_flow_badges"]


# ── Rule 2: BULLISH_ACCUM ────────────────────────────────────────────────────

class TestRule2BullishAccum:
    _tags = {
        "ADL_ACCUM_3D", "BUY_PRESSURE_HIGH", "CLOSE_HIGH",
        "CMF_POSITIVE", "DELTA_PROXY_BULL", "EFFORT_RESULT_BULL", "OBV_ACCUM_3D",
    }

    def test_full_match(self):
        snaps = [_snap(flow_tags=self._tags)]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_BULLISH_ACCUM in res["curated_flow_badges"]

    def test_missing_one_tag_no_match(self):
        partial = self._tags - {"DELTA_PROXY_BULL"}
        snaps = [_snap(flow_tags=partial)]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_BULLISH_ACCUM not in res["curated_flow_badges"]

    def test_subtype_flow_bullish_accum(self):
        snaps = [_snap(flow_tags=self._tags)]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert "FLOW_BULLISH_ACCUM" in res["curated_flow_subtypes"]


# ── Rule 3: SUPPLY_ABSORB ────────────────────────────────────────────────────

class TestRule3SupplyAbsorb:
    _tags = {"ADL_DISTRIB_3D", "BUY_PRESSURE_LOW", "CMF_NEGATIVE", "OBV_ACCUM_3D", "UPPER_WICK_SUPPLY"}

    def test_full_match(self):
        snaps = [_snap(flow_tags=self._tags)]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_SUPPLY_ABSORB in res["curated_flow_badges"]

    def test_partial_no_match(self):
        partial = self._tags - {"UPPER_WICK_SUPPLY"}
        snaps = [_snap(flow_tags=partial)]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_SUPPLY_ABSORB not in res["curated_flow_badges"]


# ── Rule 4: IGNITION_CONFIRM ─────────────────────────────────────────────────

class TestRule4IgnitionConfirm:
    _tags = {"EXPANSION", "STRONG_CLOSE", "VOL_SPIKE", "WIDE_RANGE"}

    def test_full_match_price_tags(self):
        snaps = [_snap(tags=self._tags)]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_IGNITION_CONFIRM in res["curated_flow_badges"]

    def test_not_matched_from_flow_tags(self):
        # Rule 4 is price-mode; must be in snap["tags"]
        snaps = [_snap(flow_tags=self._tags)]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_IGNITION_CONFIRM not in res["curated_flow_badges"]

    def test_partial_no_match(self):
        partial = self._tags - {"STRONG_CLOSE"}
        snaps = [_snap(tags=partial)]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_IGNITION_CONFIRM not in res["curated_flow_badges"]


# ── Rule 5: GAP_RESET_RECLAIM (5-bar window) ─────────────────────────────────

class TestRule5GapResetReclaim:
    _req_tags = {"DRYUP", "GAP_DOWN", "GAP_UP", "GAP_UP_HOLD", "INSIDE_BAR", "LOWER_WICK_RECLAIM", "STRONG_CLOSE"}

    def _distribute(self, tags):
        """Spread required tags across exactly 5 bars, one per bar."""
        tags = list(tags)
        snaps = []
        per = max(1, len(tags) // 5)
        idx = 0
        for i in range(5):
            chunk = tags[idx: idx + per]
            if i == 4:
                chunk = tags[idx:]
            snaps.append(_snap(tags=chunk))
            idx += per
        return snaps

    def test_match_when_tags_spread_across_5bars(self):
        snaps = self._distribute(self._req_tags)
        assert len(snaps) == 5
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_GAP_RESET_RECLAIM in res["curated_flow_badges"]

    def test_match_all_tags_on_one_bar(self):
        snaps = [_snap(tags=self._req_tags)] + [_snap() for _ in range(4)]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_GAP_RESET_RECLAIM in res["curated_flow_badges"]

    def test_no_match_with_only_4_bars(self):
        # Window requires >= 5 bars
        snaps = [_snap(tags=self._req_tags)] + [_snap() for _ in range(3)]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_GAP_RESET_RECLAIM not in res["curated_flow_badges"]

    def test_no_match_missing_one_required_tag(self):
        partial = self._req_tags - {"GAP_DOWN"}
        snaps = [_snap(tags=partial)] + [_snap() for _ in range(4)]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_GAP_RESET_RECLAIM not in res["curated_flow_badges"]


# ── evaluate_curated_rules_on_snaps edge cases ────────────────────────────────

class TestEvaluateEdgeCases:
    def test_empty_snaps_returns_empty(self):
        res = evaluate_curated_rules_on_snaps([])
        assert res["curated_flow_badges"] == []
        assert res["curated_flow_badge_reasons"] == []
        assert res["curated_flow_subtypes"] == []

    def test_badge_matched_at_most_once(self):
        tags = {"ADL_ACCUM_3D", "BUY_PRESSURE_HIGH", "CLOSE_HIGH", "CMF_NEGATIVE", "OBV_ACCUM_3D"}
        snaps = [_snap(flow_tags=tags), _snap(flow_tags=tags), _snap(flow_tags=tags)]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert res["curated_flow_badges"].count(BADGE_DIVERGENCE_ACCUM) == 1

    def test_badges_ordered_like_all_curated_badges(self):
        # Rule 1 + Rule 4 matched
        flow_tags = {"ADL_ACCUM_3D", "BUY_PRESSURE_HIGH", "CLOSE_HIGH", "CMF_NEGATIVE", "OBV_ACCUM_3D"}
        price_tags = {"EXPANSION", "STRONG_CLOSE", "VOL_SPIKE", "WIDE_RANGE"}
        snaps = [_snap(flow_tags=flow_tags, tags=price_tags)]
        res = evaluate_curated_rules_on_snaps(snaps)
        badges = res["curated_flow_badges"]
        assert badges.index(BADGE_DIVERGENCE_ACCUM) < badges.index(BADGE_IGNITION_CONFIRM)

    def test_reasons_non_empty_when_matched(self):
        tags = {"ADL_ACCUM_3D", "BUY_PRESSURE_HIGH", "CLOSE_HIGH", "CMF_NEGATIVE", "OBV_ACCUM_3D"}
        res = evaluate_curated_rules_on_snaps([_snap(flow_tags=tags)])
        assert len(res["curated_flow_badge_reasons"]) > 0


# ── compute_curated_flow_score: bucket assignment ─────────────────────────────

class TestScoreBuckets:
    def test_high_bucket(self):
        # DIVERGENCE_ACCUM (+4) + BULLISH_ACCUM (+3) + dryup 8-25d (+2) = 9 → HIGH
        badges = [BADGE_DIVERGENCE_ACCUM, BADGE_BULLISH_ACCUM]
        ep = _ep(dryup_day_count_pre=10)
        res = compute_curated_flow_score(badges, ep)
        assert res["curated_flow_bucket"] == "CURATED_FLOW_HIGH"
        assert res["curated_flow_score"] >= 8

    def test_medium_bucket(self):
        # IGNITION_CONFIRM (+2) + GAP_RESET (+2) + compression>=6d (+1) + no_split (+1) + median_dv>=100k (+1) = 7
        # compression>=4 satisfies has_context → no badge_no_context penalty
        badges = [BADGE_IGNITION_CONFIRM, BADGE_GAP_RESET_RECLAIM]
        ep = _ep(compression_days_pre=6)
        res = compute_curated_flow_score(badges, ep)
        assert res["curated_flow_bucket"] == "CURATED_FLOW_MEDIUM"

    def test_low_bucket(self):
        # IGNITION_CONFIRM (+2) + no_split (+1) + median_dv>=100k (+1) − badge_no_context (−2) = 2 → IGNORE
        # Need score 3-4 for LOW; use SUPPLY_ABSORB(+3) with badge_no_context(-2) = 1 → IGNORE...
        # DIVERGENCE_ACCUM (+4) + no context penalty (−2) + no_split (+1) + dv (+1) = 4 → LOW
        badges = [BADGE_DIVERGENCE_ACCUM]
        ep = _ep(dryup_day_count_pre=0, compression_days_pre=0, d_confluence_day_count_pre=0)
        res = compute_curated_flow_score(badges, ep)
        assert res["curated_flow_bucket"] == "CURATED_FLOW_LOW"

    def test_ignore_bucket_no_badges(self):
        res = compute_curated_flow_score([], _ep())
        assert res["curated_flow_bucket"] == "CURATED_FLOW_IGNORE"
        assert res["curated_flow_score"] < 3

    def test_split_artifact_penalty(self):
        badges = [BADGE_DIVERGENCE_ACCUM, BADGE_BULLISH_ACCUM]
        ep = _ep(split_artifact_risk=True, dryup_day_count_pre=10)
        res = compute_curated_flow_score(badges, ep)
        assert "split_artifact" in res["curated_flow_risk_flags"]
        # With -4 penalty the HIGH score should drop
        assert res["curated_flow_score"] < 9

    def test_reverse_split_penalty(self):
        badges = [BADGE_DIVERGENCE_ACCUM]
        ep = _ep(split_context="RECENT_REVERSE_SPLIT", dryup_day_count_pre=10)
        res = compute_curated_flow_score(badges, ep)
        assert "reverse_split" in res["curated_flow_risk_flags"]

    def test_low_dollar_volume_penalty(self):
        badges = [BADGE_DIVERGENCE_ACCUM]
        ep = _ep(median_dollar_volume_pre=30_000)
        res = compute_curated_flow_score(badges, ep)
        assert "low_dollar_volume" in res["curated_flow_risk_flags"]

    def test_bearish_supply_only_penalty(self):
        badges = [BADGE_SUPPLY_ABSORB]
        ep = _ep(dryup_day_count_pre=10)
        res = compute_curated_flow_score(badges, ep)
        assert "bearish_supply_only" in res["curated_flow_risk_flags"]

    def test_badge_no_context_penalty(self):
        badges = [BADGE_DIVERGENCE_ACCUM]
        ep = _ep(dryup_day_count_pre=0, compression_days_pre=0, d_confluence_day_count_pre=0)
        res = compute_curated_flow_score(badges, ep)
        assert "badge_no_context" in res["curated_flow_risk_flags"]

    def test_context_bonuses_require_exact_badge(self):
        # v2: context bonuses are skipped when no exact badge present
        badges = []
        ep = _ep(
            dryup_day_count_pre=12,
            d_confluence_day_count_pre=5,
            compression_days_pre=8,
            had_accumulation_like=True,
            had_spring_test_lps=True,
            split_context="NO_SPLIT",
            median_dollar_volume_pre=150_000,
        )
        res = compute_curated_flow_score(badges, ep)
        assert res["curated_flow_score"] == 0
        assert res["curated_flow_bucket"] == "CURATED_FLOW_IGNORE"
        assert any("context bonuses skipped" in r for r in res["curated_flow_reasons"])

    def test_context_bonuses_with_allow_proxy_score(self):
        # allow_proxy_score=True lets context bonuses fire without exact badge
        badges = []
        ep = _ep(
            dryup_day_count_pre=12,         # +2
            d_confluence_day_count_pre=5,   # +2
            compression_days_pre=8,         # +1
            had_accumulation_like=True,     # +1
            had_spring_test_lps=True,       # +1
            split_context="NO_SPLIT",       # +1
            median_dollar_volume_pre=150_000, # +1
        )
        res = compute_curated_flow_score(badges, ep, allow_proxy_score=True)
        assert res["curated_flow_score"] == 9
        assert res["curated_flow_bucket"] == "CURATED_FLOW_HIGH"

    def test_proxy_only_cap_at_4(self):
        # No exact badge: score capped at 4 → at most LOW bucket
        badges = []
        ep = _ep(
            dryup_day_count_pre=12,
            d_confluence_day_count_pre=5,
            compression_days_pre=8,
            had_accumulation_like=True,
            had_spring_test_lps=True,
            split_context="NO_SPLIT",
            median_dollar_volume_pre=150_000,
        )
        # Force context bonuses by using allow_proxy_score=True but check cap is present
        # without allow_proxy_score: cap is applied, score = 0 capped at 4 → still 0
        res_default = compute_curated_flow_score(badges, ep)
        assert res_default["curated_flow_is_proxy_only"] is True
        assert res_default["curated_flow_score"] <= 4
        assert res_default["curated_flow_bucket"] in ("CURATED_FLOW_LOW", "CURATED_FLOW_IGNORE")

    def test_is_proxy_only_false_when_badge_present(self):
        badges = [BADGE_DIVERGENCE_ACCUM]
        res = compute_curated_flow_score(badges, _ep(dryup_day_count_pre=10))
        assert res["curated_flow_is_proxy_only"] is False
        assert res["curated_flow_exact_match_count"] == 1

    def test_divergence_pressure_double_count_prevention(self):
        # Both ABSORB_PRESSURE(5) and ACCUM(4) fire → only max=5 counts
        badges = [BADGE_DIVERGENCE_ABSORB_PRESSURE, BADGE_DIVERGENCE_ACCUM]
        ep = _ep(dryup_day_count_pre=10)
        res = compute_curated_flow_score(badges, ep)
        # Score should include weight=5 (not 5+4=9 from badge alone)
        # Badge scores = 5; plus context bonuses (+2 dryup, +1 no_split, +1 dv) = 9
        assert res["curated_flow_score"] == 9
        assert res["curated_flow_primary_badge"] == BADGE_DIVERGENCE_ABSORB_PRESSURE

    def test_primary_badge_is_highest_weight_div_pressure(self):
        badges = [BADGE_DIVERGENCE_ACCUM, BADGE_DIVERGENCE_ABSORB_PRESSURE]
        res = compute_curated_flow_score(badges, _ep(dryup_day_count_pre=10))
        assert res["curated_flow_primary_badge"] == BADGE_DIVERGENCE_ABSORB_PRESSURE

    def test_reasons_list_non_empty_when_scored(self):
        badges = [BADGE_DIVERGENCE_ACCUM]
        res = compute_curated_flow_score(badges, _ep(dryup_day_count_pre=10))
        assert len(res["curated_flow_reasons"]) > 0


# ── Anti-leakage ──────────────────────────────────────────────────────────────

class TestAntiLeakage:
    def test_raises_on_outcome_field_pump_multiple(self):
        badges = [BADGE_DIVERGENCE_ACCUM]
        ep = _ep(pump_multiple=5.2)
        with pytest.raises(AssertionError, match="pump_multiple"):
            compute_curated_flow_score(badges, ep, _assert_no_leakage=True)

    def test_raises_on_outcome_field_group_type(self):
        badges = []
        ep = _ep(group_type="4x_pump")
        with pytest.raises(AssertionError, match="group_type"):
            compute_curated_flow_score(badges, ep, _assert_no_leakage=True)

    def test_raises_on_forward_return(self):
        badges = []
        ep = _ep(forward_return_5d=0.45)
        with pytest.raises(AssertionError):
            compute_curated_flow_score(badges, ep, _assert_no_leakage=True)

    def test_no_raise_on_clean_ep(self):
        badges = [BADGE_DIVERGENCE_ACCUM]
        ep = _ep(dryup_day_count_pre=10)
        # Should not raise
        compute_curated_flow_score(badges, ep, _assert_no_leakage=True)


# ── score_episode_curated_flow: export field existence ────────────────────────

class TestScoreEpisodeCuratedFlow:
    def test_returns_all_required_fields(self):
        snaps = [_snap(flow_tags={"ADL_ACCUM_3D", "BUY_PRESSURE_HIGH", "CLOSE_HIGH",
                                   "CMF_NEGATIVE", "OBV_ACCUM_3D"})]
        ep = _ep(dryup_day_count_pre=10)
        res = score_episode_curated_flow(ep, snaps)
        for field in (
            "curated_flow_badges", "curated_flow_score", "curated_flow_bucket",
            "curated_flow_risk_flags", "curated_flow_reasons",
            "curated_flow_badge_reasons", "curated_flow_subtypes",
            "curated_flow_exact_match_count", "curated_flow_is_proxy_only",
            "curated_flow_primary_badge", "curated_flow_matched_bars",
        ):
            assert field in res, f"Missing field: {field}"

    def test_exact_match_count_correct(self):
        snaps = [_snap(flow_tags={"ADL_ACCUM_3D", "BUY_PRESSURE_HIGH", "CLOSE_HIGH",
                                   "CMF_NEGATIVE", "OBV_ACCUM_3D"})]
        res = score_episode_curated_flow(_ep(dryup_day_count_pre=10), snaps)
        assert res["curated_flow_exact_match_count"] == 1

    def test_matched_bars_non_empty_when_badge_fires(self):
        snaps = [_snap(flow_tags={"ADL_ACCUM_3D", "BUY_PRESSURE_HIGH", "CLOSE_HIGH",
                                   "CMF_NEGATIVE", "OBV_ACCUM_3D"})]
        res = score_episode_curated_flow(_ep(dryup_day_count_pre=10), snaps)
        assert len(res["curated_flow_matched_bars"]) >= 1

    def test_bucket_is_valid_string(self):
        snaps = []
        ep = _ep()
        res = score_episode_curated_flow(ep, snaps)
        valid = {"CURATED_FLOW_HIGH", "CURATED_FLOW_MEDIUM", "CURATED_FLOW_LOW", "CURATED_FLOW_IGNORE"}
        assert res["curated_flow_bucket"] in valid

    def test_score_is_int(self):
        snaps = []
        ep = _ep()
        res = score_episode_curated_flow(ep, snaps)
        assert isinstance(res["curated_flow_score"], int)

    def test_badges_subset_of_all_curated(self):
        snaps = [_snap(flow_tags={"ADL_ACCUM_3D", "BUY_PRESSURE_HIGH", "CLOSE_HIGH",
                                   "CMF_NEGATIVE", "OBV_ACCUM_3D"})]
        ep = _ep(dryup_day_count_pre=10)
        res = score_episode_curated_flow(ep, snaps)
        for badge in res["curated_flow_badges"]:
            assert badge in ALL_CURATED_BADGES

    def test_empty_snaps_gives_ignore(self):
        res = score_episode_curated_flow(_ep(), [])
        assert res["curated_flow_bucket"] == "CURATED_FLOW_IGNORE"
        assert res["curated_flow_badges"] == []
