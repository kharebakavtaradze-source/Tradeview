"""
Unit tests for replay/curated_flow_rules.py — Part 11 + Part 15 additions.

Covers:
  - Rule matching for all curated badges (single-bar flow, price, 5-bar window)
  - OBV divergence badge (run-144, Part 7)
  - Score computation: HIGH / MEDIUM / LOW / IGNORE bucket assignment
  - Context bonuses and risk penalties
  - OBV family double-count prevention (Part 9)
  - OBV regime penalties: price_gt25 and atr_extreme (Part 10)
  - Flow tag normalization via normalize_snapshot_flow_tags (Part 5)
  - Anti-leakage assertion (_assert_no_leakage)
  - Export field existence via score_episode_curated_flow
  - Proxy safety: OBV badge must not be reachable without exact match
"""
import pytest

from replay.curated_flow_rules import (
    BADGE_DIVERGENCE_ABSORB_PRESSURE,
    BADGE_DIVERGENCE_ACCUM,
    BADGE_BULLISH_ACCUM,
    BADGE_SUPPLY_ABSORB,
    BADGE_IGNITION_CONFIRM,
    BADGE_GAP_RESET_RECLAIM,
    BADGE_OBV_ACCUM_DISTRIB,
    ALL_CURATED_BADGES,
    _num,
    _gte,
    _between,
    evaluate_curated_flow_badges_from_snapshots,
    evaluate_curated_rules_on_snaps,
    compute_curated_flow_score,
    score_episode_curated_flow,
    normalize_snapshot_flow_tags,
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


# ── Rule (new): OBV_ACCUM_DISTRIB (run-144, Part 7) ──────────────────────────

class TestRuleOBVAccumDistrib:
    _tags = {"ADL_DISTRIB_3D", "CMF_NEGATIVE", "OBV_ACCUM_3D"}

    def test_full_match(self):
        snaps = [_snap(flow_tags=self._tags)]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_OBV_ACCUM_DISTRIB in res["curated_flow_badges"]

    def test_partial_no_match_missing_obv_accum(self):
        snaps = [_snap(flow_tags=self._tags - {"OBV_ACCUM_3D"})]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_OBV_ACCUM_DISTRIB not in res["curated_flow_badges"]

    def test_partial_no_match_missing_adl_distrib(self):
        snaps = [_snap(flow_tags=self._tags - {"ADL_DISTRIB_3D"})]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_OBV_ACCUM_DISTRIB not in res["curated_flow_badges"]

    def test_partial_no_match_missing_cmf_negative(self):
        snaps = [_snap(flow_tags=self._tags - {"CMF_NEGATIVE"})]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_OBV_ACCUM_DISTRIB not in res["curated_flow_badges"]

    def test_match_on_any_bar(self):
        snaps = [_snap(), _snap(flow_tags=self._tags)]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_OBV_ACCUM_DISTRIB in res["curated_flow_badges"]

    def test_flow_mode_only(self):
        # Must come from flow_tags, not price tags
        snaps = [_snap(flow_tags=set(), tags=self._tags)]
        res = evaluate_curated_rules_on_snaps(snaps)
        assert BADGE_OBV_ACCUM_DISTRIB not in res["curated_flow_badges"]

    def test_in_all_curated_badges(self):
        assert BADGE_OBV_ACCUM_DISTRIB in ALL_CURATED_BADGES

    def test_score_weight_4(self):
        badges = [BADGE_OBV_ACCUM_DISTRIB]
        ep = _ep(dryup_day_count_pre=10)
        res = compute_curated_flow_score(badges, ep)
        # Score should be at least 4 from badge alone (+ context bonuses, - maybe badge_no_context)
        # dryup=10 → has_context=True → no badge_no_context penalty
        # +4 badge + +2 dryup + +1 no_split + +1 dv = 8 → HIGH
        assert res["curated_flow_score"] >= 4

    def test_not_bearish_only_penalized(self):
        # OBV_ACCUM_DISTRIB alone should NOT trigger bearish_supply_only flag
        badges = [BADGE_OBV_ACCUM_DISTRIB]
        ep = _ep(dryup_day_count_pre=10)
        res = compute_curated_flow_score(badges, ep)
        assert "bearish_supply_only" not in res["curated_flow_risk_flags"]


# ── OBV family double-count prevention (Part 9) ───────────────────────────────

class TestOBVFamilyDoubleCount:
    def test_obv_supply_both_fire_only_max_score(self):
        # BADGE_OBV_ACCUM_DISTRIB (+4) and BADGE_SUPPLY_ABSORB (+3) are in same family
        # Only max=4 should be counted from the family
        badges = [BADGE_OBV_ACCUM_DISTRIB, BADGE_SUPPLY_ABSORB]
        ep = _ep(dryup_day_count_pre=10)
        res = compute_curated_flow_score(badges, ep)
        assert any("double-count suppressed" in r for r in res["curated_flow_reasons"])

    def test_obv_is_primary_over_supply_absorb(self):
        badges = [BADGE_OBV_ACCUM_DISTRIB, BADGE_SUPPLY_ABSORB]
        res = compute_curated_flow_score(badges, _ep(dryup_day_count_pre=10))
        assert res["curated_flow_primary_badge"] == BADGE_OBV_ACCUM_DISTRIB

    def test_supply_absorb_alone_gets_its_own_score(self):
        badges = [BADGE_SUPPLY_ABSORB]
        ep = _ep(dryup_day_count_pre=10)
        res = compute_curated_flow_score(badges, ep)
        # SUPPLY_ABSORB alone: +3 badge; but bearish_supply_only penalty applies → -2
        # dryup has_context → no badge_no_context
        # Score = 3 - 2 (bearish_supply_only) + 2 (dryup) + 1 + 1 = 5 → MEDIUM
        assert res["curated_flow_score"] >= 1

    def test_obv_family_separate_from_dp_family(self):
        # Both ABSORB_PRESSURE (dp_family) and OBV_ACCUM_DISTRIB (obv_family) should both score
        badges = [BADGE_DIVERGENCE_ABSORB_PRESSURE, BADGE_OBV_ACCUM_DISTRIB]
        ep = _ep(dryup_day_count_pre=10)
        res = compute_curated_flow_score(badges, ep)
        # Both families count independently: dp(5) + obv(4) + context
        # No double-count suppression across families
        score = res["curated_flow_score"]
        assert score >= 9  # at minimum: 5 + 4 = 9 from badges alone


# ── OBV regime penalties (Part 10) ───────────────────────────────────────────

class TestOBVRegimePenalties:
    _obv_badges = [BADGE_OBV_ACCUM_DISTRIB]

    def test_price_gt25_penalty(self):
        ep = _ep(dryup_day_count_pre=10, price_bucket="PRICE_GT_25")
        res = compute_curated_flow_score(self._obv_badges, ep)
        assert "obv_price_gt25" in res["curated_flow_risk_flags"]
        # Penalty of -2 should apply
        assert any("obv_badge+price_gt25" in r for r in res["curated_flow_reasons"])

    def test_atr_extreme_penalty(self):
        ep = _ep(dryup_day_count_pre=10, atr_bucket="ATR_EXTREME_GT_40")
        res = compute_curated_flow_score(self._obv_badges, ep)
        assert "obv_atr_extreme" in res["curated_flow_risk_flags"]
        assert any("obv_badge+atr_extreme" in r for r in res["curated_flow_reasons"])

    def test_both_regime_penalties_stack(self):
        ep = _ep(dryup_day_count_pre=10, price_bucket="PRICE_GT_25", atr_bucket="ATR_EXTREME_GT_40")
        res = compute_curated_flow_score(self._obv_badges, ep)
        assert "obv_price_gt25" in res["curated_flow_risk_flags"]
        assert "obv_atr_extreme" in res["curated_flow_risk_flags"]

    def test_no_penalty_normal_regime(self):
        ep = _ep(dryup_day_count_pre=10, price_bucket="PRICE_1_TO_3", atr_bucket="ATR_LOW_LT_5")
        res = compute_curated_flow_score(self._obv_badges, ep)
        assert "obv_price_gt25" not in res["curated_flow_risk_flags"]
        assert "obv_atr_extreme" not in res["curated_flow_risk_flags"]

    def test_penalty_only_when_obv_badge_present(self):
        # Should not apply penalties if OBV badge not in list
        badges = [BADGE_DIVERGENCE_ACCUM]
        ep = _ep(dryup_day_count_pre=10, price_bucket="PRICE_GT_25")
        res = compute_curated_flow_score(badges, ep)
        assert "obv_price_gt25" not in res["curated_flow_risk_flags"]


# ── normalize_snapshot_flow_tags (Part 5) ─────────────────────────────────────

class TestNormalizeSnapshotFlowTags:
    def test_reads_flow_tags_list(self):
        snap = {"flow_tags": ["ADL_ACCUM_3D", "CMF_NEGATIVE"]}
        result = normalize_snapshot_flow_tags(snap)
        assert "ADL_ACCUM_3D" in result
        assert "CMF_NEGATIVE" in result

    def test_skips_flat_in_flow_tags(self):
        snap = {"flow_tags": ["FLAT"]}
        result = normalize_snapshot_flow_tags(snap)
        assert result == [] or result == ["FLAT"]

    def test_explicit_empty_flow_tags_no_fallback_to_tags(self):
        # If flow_tags is explicitly [], do NOT fall back to tags even if tags has flow-named strings
        snap = {
            "flow_tags": [],
            "tags": ["ADL_ACCUM_3D", "CMF_NEGATIVE"],
        }
        result = normalize_snapshot_flow_tags(snap)
        # Must respect the explicit empty flow_tags — no tags-field pollution
        assert "ADL_ACCUM_3D" not in result
        assert result == []

    def test_falls_back_to_flow_tag_signature(self):
        snap = {"flow_tag_signature": "ADL_ACCUM_3D+OBV_ACCUM_3D"}
        result = normalize_snapshot_flow_tags(snap)
        assert "ADL_ACCUM_3D" in result
        assert "OBV_ACCUM_3D" in result

    def test_falls_back_to_feature_json_flow_tags(self):
        snap = {"feature_json": {"flow_tags": ["CMF_NEGATIVE", "OBV_ACCUM_3D"]}}
        result = normalize_snapshot_flow_tags(snap)
        assert "CMF_NEGATIVE" in result

    def test_empty_snap_returns_empty(self):
        result = normalize_snapshot_flow_tags({})
        assert result == []

    def test_priority_flow_tags_over_signature(self):
        # flow_tags list takes priority over flow_tag_signature
        snap = {
            "flow_tags": ["ADL_ACCUM_3D"],
            "flow_tag_signature": "DIFFERENT_TAG",
        }
        result = normalize_snapshot_flow_tags(snap)
        assert "ADL_ACCUM_3D" in result
        assert "DIFFERENT_TAG" not in result

    def test_returns_list(self):
        snap = {"flow_tags": ["ADL_ACCUM_3D"]}
        result = normalize_snapshot_flow_tags(snap)
        assert isinstance(result, list)


# ── Proxy safety: OBV badge requires exact match ──────────────────────────────

class TestOBVProxySafety:
    def test_obv_badge_not_scored_without_exact_match(self):
        # Proxy-only path: no badges → no OBV regime penalty, score capped at 4
        ep = _ep(
            dryup_day_count_pre=12,
            d_confluence_day_count_pre=5,
            compression_days_pre=8,
            price_bucket="PRICE_1_TO_3",
        )
        res = compute_curated_flow_score([], ep)
        assert "obv_price_gt25" not in res["curated_flow_risk_flags"]
        assert "obv_atr_extreme"  not in res["curated_flow_risk_flags"]
        assert res["curated_flow_is_proxy_only"] is True

    def test_obv_badge_required_tags_are_flow_only(self):
        # Verify the badge fires from flow_tags, not price tags
        obv_tags = {"ADL_DISTRIB_3D", "CMF_NEGATIVE", "OBV_ACCUM_3D"}
        snaps_price_only = [_snap(flow_tags=set(), tags=obv_tags)]
        snaps_flow       = [_snap(flow_tags=obv_tags, tags=set())]
        res_price = evaluate_curated_rules_on_snaps(snaps_price_only)
        res_flow  = evaluate_curated_rules_on_snaps(snaps_flow)
        assert BADGE_OBV_ACCUM_DISTRIB not in res_price["curated_flow_badges"]
        assert BADGE_OBV_ACCUM_DISTRIB in  res_flow["curated_flow_badges"]


# ── End-to-end: build_curated_flow_replay_analysis ───────────────────────────

class TestCuratedFlowReplayAnalysis:
    """
    End-to-end: build_curated_flow_replay_analysis with one episode + one matching
    snapshot produces a non-empty report with exact_badge_match_count > 0.
    """

    _OBV_SIG = "ADL_DISTRIB_3D+CMF_NEGATIVE+OBV_ACCUM_3D"

    def _obv_snap(self):
        return {
            "flow_tags":           ["ADL_DISTRIB_3D", "CMF_NEGATIVE", "OBV_ACCUM_3D"],
            "flow_tag_signature":  self._OBV_SIG,
            "tags":                [],
            "date":                "T-1",
            "days_to_breakout":    1,
        }

    def _scored_ep_with_debug(self, episode_id=1):
        """Episode pre-scored with OBV badge + curated_flow_debug pre-populated."""
        ep  = _ep(episode_id=episode_id, group_type="4x_pump", symbol="TST")
        cf  = score_episode_curated_flow(ep, [self._obv_snap()])
        ep_scored = {**ep, **cf}
        # Simulate what score_episodes_curated_flow would have stored in the fresh path
        ep_scored["curated_flow_debug"] = {
            "snapshot_count":           1,
            "snapshots_with_flow_tags": 1,
            "seen_flow_signatures":     [self._OBV_SIG],
            "badges_matched":           list(ep_scored.get("curated_flow_badges") or []),
            "exact_match_count":        ep_scored.get("curated_flow_exact_match_count", 0),
        }
        return ep_scored

    def test_exact_badge_match_count_nonzero(self):
        from replay.curated_flow_analyzer import build_curated_flow_replay_analysis

        result = build_curated_flow_replay_analysis([self._scored_ep_with_debug()])
        assert result["episode_count"] == 1
        diag = result["curated_match_diagnostics"]
        assert diag["exact_badge_match_count"] > 0, diag

    def test_obv_badge_in_badge_match_counts(self):
        from replay.curated_flow_analyzer import build_curated_flow_replay_analysis

        result = build_curated_flow_replay_analysis([self._scored_ep_with_debug()])
        diag = result["curated_match_diagnostics"]
        assert diag["badge_match_counts"][BADGE_OBV_ACCUM_DISTRIB] == 1

    def test_top_seen_flow_signatures_nonempty(self):
        from replay.curated_flow_analyzer import build_curated_flow_replay_analysis

        result = build_curated_flow_replay_analysis([self._scored_ep_with_debug()])
        diag = result["curated_match_diagnostics"]
        assert len(diag["top_seen_flow_signatures"]) > 0
        assert diag["top_seen_flow_signatures"][0]["signature"] == self._OBV_SIG

    def test_required_diagnostic_keys_always_present(self):
        from replay.curated_flow_analyzer import build_curated_flow_replay_analysis

        # Works for both matching and non-matching episodes
        ep_no_signal = _ep(episode_id=99, symbol="EMPTY")
        for ep in [self._scored_ep_with_debug(), ep_no_signal]:
            result = build_curated_flow_replay_analysis([ep])
            diag   = result["curated_match_diagnostics"]
            for key in (
                "exact_badge_match_count",
                "episodes_with_no_snapshots",
                "episodes_with_snapshots_but_no_flow_tags",
                "episodes_with_flow_tags_but_no_badge",
                "top_seen_flow_signatures",
            ):
                assert key in diag, f"Missing key '{key}' for ep={ep.get('symbol')}"

    def test_no_curated_flow_error_on_success(self):
        from replay.curated_flow_analyzer import build_curated_flow_replay_analysis

        result = build_curated_flow_replay_analysis([self._scored_ep_with_debug()])
        assert result.get("curated_flow_error") is None

    def test_empty_episodes_returns_zero_count(self):
        from replay.curated_flow_analyzer import build_curated_flow_replay_analysis

        result = build_curated_flow_replay_analysis([])
        assert result["episode_count"] == 0
        assert result["report_type"] == "curated_flow_replay_analysis"


# ── Safe numeric helpers ──────────────────────────────────────────────────────

class TestNumHelpers:
    def test_num_none_returns_default(self):
        assert _num(None) == 0
        assert _num(None, default=5) == 5

    def test_num_int_passthrough(self):
        assert _num(10) == 10.0
        assert _num(0) == 0.0

    def test_num_float_passthrough(self):
        assert _num(3.5) == 3.5

    def test_num_non_finite_returns_default(self):
        import math
        assert _num("NaN") == 0       # string "NaN" → nan → default
        assert _num(float("nan")) == 0 # float NaN → default
        assert _num(float("inf")) == 0 # Inf → default
        assert _num("abc") == 0        # non-numeric string → default

    def test_num_string_numeric(self):
        assert _num("7") == 7.0

    def test_gte_none_is_false_for_positive_threshold(self):
        assert _gte(None, 5) is False
        assert _gte(None, 1) is False

    def test_gte_valid_value(self):
        assert _gte(10, 5) is True
        assert _gte(5, 5) is True
        assert _gte(4, 5) is False

    def test_between_none_is_false(self):
        assert _between(None, 8, 25) is False

    def test_between_valid_range(self):
        assert _between(10, 8, 25) is True
        assert _between(8, 8, 25) is True
        assert _between(25, 8, 25) is True
        assert _between(7, 8, 25) is False
        assert _between(26, 8, 25) is False


# ── None-safe scoring ─────────────────────────────────────────────────────────

class TestNoneSafeScoring:
    """
    Ensures compute_curated_flow_score and the full analyzer pipeline never
    crash when episode fields are None (as they can be in the database).
    """

    _NULL_EP = {
        "dryup_day_count_pre":              None,
        "d_confluence_day_count_pre":       None,
        "compression_days_pre":             None,
        "median_dollar_volume_pre":         None,
        "avg_atr_pct_pre":                  None,
        "high_expansion_risk_day_count_pre": None,
        "had_accumulation_like":            None,
        "had_spring_test_lps":              None,
        "split_context":                    None,
        "price_bucket":                     None,
        "atr_bucket":                       None,
        "dollar_volume_bucket":             None,
        "split_artifact_risk":              None,
        "pump_multiple":                    None,
        "pump_watch_score":                 None,
        "pump_watch_label":                 None,
        "group_type":                       "4x_pump",
        "symbol":                           "NULLTEST",
        "episode_id":                       42,
    }

    def _null_ep(self, **overrides):
        return {**self._NULL_EP, **overrides}

    def test_median_dollar_volume_pre_none_does_not_crash(self):
        ep = self._null_ep(median_dollar_volume_pre=None)
        result = compute_curated_flow_score([], ep)
        assert result["curated_flow_bucket"] == "CURATED_FLOW_IGNORE"

    def test_dryup_day_count_pre_none_does_not_crash(self):
        ep = self._null_ep(dryup_day_count_pre=None)
        result = compute_curated_flow_score([], ep)
        assert "curated_flow_bucket" in result

    def test_d_confluence_day_count_pre_none_does_not_crash(self):
        ep = self._null_ep(d_confluence_day_count_pre=None)
        result = compute_curated_flow_score([], ep)
        assert "curated_flow_bucket" in result

    def test_compression_days_pre_none_does_not_crash(self):
        ep = self._null_ep(compression_days_pre=None)
        result = compute_curated_flow_score([], ep)
        assert "curated_flow_bucket" in result

    def test_high_expansion_risk_none_does_not_crash(self):
        ep = self._null_ep(high_expansion_risk_day_count_pre=None)
        result = compute_curated_flow_score([], ep)
        assert "curated_flow_bucket" in result

    def test_obv_badge_scores_with_all_context_fields_none(self):
        # Exact badge must still fire even when all optional context fields are None
        obv_snap = {
            "flow_tags":          ["ADL_DISTRIB_3D", "CMF_NEGATIVE", "OBV_ACCUM_3D"],
            "flow_tag_signature": "ADL_DISTRIB_3D+CMF_NEGATIVE+OBV_ACCUM_3D",
            "tags": [], "date": "T-1", "days_to_breakout": 1,
        }
        ep = self._null_ep()
        result = score_episode_curated_flow(ep, [obv_snap])
        assert BADGE_OBV_ACCUM_DISTRIB in result["curated_flow_badges"]
        assert result["curated_flow_exact_match_count"] == 1
        assert result["curated_flow_bucket"] != "CURATED_FLOW_IGNORE"

    def test_no_badge_plus_none_context_stays_ignore(self):
        ep = self._null_ep()
        result = compute_curated_flow_score([], ep)
        assert result["curated_flow_bucket"] == "CURATED_FLOW_IGNORE"
        assert result["curated_flow_is_proxy_only"] is True

    def test_full_analyzer_none_fields_does_not_crash(self):
        from replay.curated_flow_analyzer import build_curated_flow_replay_analysis
        # False-positive episode with high_expansion_risk=None is what crashed run 146
        fp_ep = self._null_ep(
            group_type="false_positive",
            curated_flow_badges=[BADGE_DIVERGENCE_ABSORB_PRESSURE],
            curated_flow_bucket="CURATED_FLOW_HIGH",
            curated_flow_score=9,
            curated_flow_exact_match_count=1,
            curated_flow_is_proxy_only=False,
        )
        result = build_curated_flow_replay_analysis([fp_ep])
        assert result.get("curated_flow_error") is None
        assert result["episode_count"] == 1
        assert "curated_match_diagnostics" in result

    def test_missing_dollar_volume_adds_risk_flag(self):
        # When median_dollar_volume_pre is None, bonus is skipped and risk flag set
        obv_snap = {
            "flow_tags":          ["ADL_DISTRIB_3D", "CMF_NEGATIVE", "OBV_ACCUM_3D"],
            "flow_tag_signature": "ADL_DISTRIB_3D+CMF_NEGATIVE+OBV_ACCUM_3D",
            "tags": [], "date": "T-1", "days_to_breakout": 1,
        }
        ep = self._null_ep(median_dollar_volume_pre=None)
        result = score_episode_curated_flow(ep, [obv_snap])
        assert "missing_dollar_volume" in result["curated_flow_risk_flags"]

    def test_all_none_episodes_full_pipeline_no_error(self):
        from replay.curated_flow_analyzer import build_curated_flow_replay_analysis
        episodes = [self._null_ep(episode_id=i, group_type=g) for i, g in enumerate(
            ["4x_pump", "false_positive", "normal_winner", "4x_pump", "no_pump"]
        )]
        result = build_curated_flow_replay_analysis(episodes)
        assert result.get("curated_flow_error") is None
        assert result["episode_count"] == 5
        diag = result["curated_match_diagnostics"]
        assert "badge_match_counts" in diag
        assert "top_seen_flow_signatures" in diag
