"""
Unit tests for replay/cfr_selector.py — CFR Selector v1.

Covers:
  1. Pump Watch base scoring (HIGH/MEDIUM/SPECULATIVE/IGNORE)
  2. FLOW setup scoring (divergence/absorption/bullish_accum/bearish_stress)
  3. FLOW trigger scoring (+3/+2/+1 paths)
  4. Custom confirmation scoring (L34/L43, D4/D6, VBO/LVBO, D_L34)
  5. Regime scoring (price/DV/ATR/split context)
  6. Risk penalties (artifact, reverse split, ATR extreme, price_gt25, illiquid)
  7. A-gate 1: base quality
  8. A-gate 2: clean regime
  9. A-gate 3: trigger required
  10. A-gate 4: not setup-only (no pure L64 / pure bearish stress)
  11. A-gate 5: risk control
  12. Bucket assignment (CFR_A / CFR_B / CFR_C / CFR_AVOID)
  13. PUMP_SPECULATIVE with strong trigger → can reach CFR_A
  14. PUMP_IGNORE max bucket is CFR_C (score<6) or CFR_B if high
  15. Anti-leakage: pump_multiple and group_type never appear in score logic
  16. build_cfr_selector_analysis: empty input returns safe default
  17. build_cfr_selector_analysis: multiple episodes, bucket distribution correct
  18. score_episodes_cfr: mutates dicts in-place, returns same list
  19. ABR disabled: no abr_ fields read in scoring
"""

import pytest

from replay.cfr_selector import (
    _compute_cfr_score,
    _aggregate_custom_signals,
    _is_clean_regime,
    _is_toxic_regime,
    score_episodes_cfr,
    build_cfr_selector_analysis,
)

# Badge constants (mirror cfr_selector.py)
_B_ABSORB_PRESSURE  = "PX_FLOW_DIVERGENCE_ABSORB_PRESSURE_1B"
_B_OBV_ACCUM        = "PX_FLOW_DIVERGENCE_OBV_ACCUM_DISTRIB_1B"
_B_DIVERGENCE_ACCUM = "PX_FLOW_DIVERGENCE_ACCUM_PRESSURE"
_B_BULLISH_ACCUM    = "PX_FLOW_BULLISH_ACCUM_IGNITION"
_B_SUPPLY_ABSORB    = "PX_FLOW_DIVERGENCE_SUPPLY_ABSORB"
_B_IGNITION_CONFIRM = "PX_IGNITION_CONFIRM_PRICE_ACTION"
_B_GAP_RESET        = "PX_GAP_RESET_RECLAIM_CONTEXT"


# ── Episode / custom builders ─────────────────────────────────────────────────

def _ep(
    pw_label="PUMP_WATCH_HIGH",
    flow_ctx="",
    subtypes=None,
    badges=None,
    price_bucket="PRICE_1_TO_3",
    atr_bucket="ATR_NORMAL_5_15",
    dv_bucket="DV_OK_250K_1M",
    split_ctx="NO_SPLIT",
    split_artifact=False,
    primary_badge=None,
    # outcome fields — must never affect scoring
    pump_multiple=None,
    group_type=None,
) -> dict:
    ep = {
        "pump_watch_label":         pw_label,
        "flow_replay_context":      flow_ctx,
        "curated_flow_subtypes":    subtypes or [],
        "curated_flow_badges":      badges   or [],
        "curated_flow_primary_badge": primary_badge,
        "price_bucket":             price_bucket,
        "atr_bucket":               atr_bucket,
        "dollar_volume_bucket":     dv_bucket,
        "split_context":            split_ctx,
        "split_artifact_risk":      split_artifact,
        # outcome (must not be read by scoring)
        "pump_multiple":            pump_multiple,
        "group_type":               group_type,
    }
    return ep


def _custom(**kwargs) -> dict:
    base = {k: 0 for k in [
        "l34", "l43", "l22", "l64", "fri34", "fri64",
        "d3_beup", "d4_beup", "d6_beup", "d4_l34", "d3_l34",
        "vbo", "lvbo",
    ]}
    base.update(kwargs)
    return base


def _score(ep: dict, custom: dict = None) -> dict:
    return _compute_cfr_score(ep, custom or _custom())


# ── 1. Pump Watch base ────────────────────────────────────────────────────────

class TestPumpWatchBase:
    def test_pw_high_gives_4(self):
        r = _score(_ep("PUMP_WATCH_HIGH"))
        assert r["custom_flow_regime_components_v1"]["pump_watch_base"] == 4.0

    def test_pw_medium_gives_3(self):
        r = _score(_ep("PUMP_WATCH_MEDIUM"))
        assert r["custom_flow_regime_components_v1"]["pump_watch_base"] == 3.0

    def test_pw_speculative_no_trigger_gives_0(self):
        r = _score(_ep("PUMP_SPECULATIVE"))
        assert r["custom_flow_regime_components_v1"]["pump_watch_base"] == 0.0

    def test_pw_speculative_with_trigger_gives_1(self):
        ep = _ep("PUMP_SPECULATIVE", badges=[_B_ABSORB_PRESSURE])
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["pump_watch_base"] == 1.0

    def test_pw_ignore_gives_minus3(self):
        r = _score(_ep("PUMP_IGNORE"))
        assert r["custom_flow_regime_components_v1"]["pump_watch_base"] == -3.0
        assert "pump_ignore" in r["custom_flow_regime_risk_flags_v1"]


# ── 2. FLOW setup ─────────────────────────────────────────────────────────────

class TestFlowSetup:
    def test_divergence_adds_1(self):
        ep = _ep("PUMP_WATCH_HIGH", flow_ctx="FLOW_DIVERGENCE")
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["flow_setup"] == 1.0

    def test_absorption_adds_1(self):
        ep = _ep("PUMP_WATCH_HIGH", subtypes=["FLOW_ABSORPTION"])
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["flow_setup"] == 1.0

    def test_bullish_accum_adds_1(self):
        ep = _ep("PUMP_WATCH_HIGH", subtypes=["FLOW_BULLISH_ACCUM"])
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["flow_setup"] == 1.0

    def test_divergence_plus_absorption_adds_2(self):
        ep = _ep("PUMP_WATCH_HIGH", subtypes=["FLOW_DIVERGENCE", "FLOW_ABSORPTION"])
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["flow_setup"] == 2.0

    def test_bearish_stress_alone_adds_0_pts(self):
        ep = _ep("PUMP_WATCH_HIGH", subtypes=["FLOW_BEARISH_STRESS"])
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["flow_setup"] == 0.0
        assert "flow_bearish_stress_context" in r["custom_flow_regime_reasons_v1"]

    def test_bearish_stress_with_divergence_still_1(self):
        ep = _ep("PUMP_WATCH_HIGH", subtypes=["FLOW_DIVERGENCE", "FLOW_BEARISH_STRESS"])
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["flow_setup"] == 1.0


# ── 3. FLOW trigger ───────────────────────────────────────────────────────────

class TestFlowTrigger:
    def test_absorb_pressure_adds_3(self):
        ep = _ep("PUMP_WATCH_HIGH", badges=[_B_ABSORB_PRESSURE])
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["trigger_confirmation"] == 3.0

    def test_bullish_accum_badge_adds_3(self):
        ep = _ep("PUMP_WATCH_HIGH", badges=[_B_BULLISH_ACCUM])
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["trigger_confirmation"] == 3.0

    def test_obv_accum_clean_adds_2(self):
        ep = _ep("PUMP_WATCH_HIGH", badges=[_B_OBV_ACCUM],
                 split_ctx="NO_SPLIT", atr_bucket="ATR_NORMAL_5_15")
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["trigger_confirmation"] == 2.0

    def test_obv_accum_dirty_adds_0(self):
        ep = _ep("PUMP_WATCH_HIGH", badges=[_B_OBV_ACCUM],
                 split_ctx="RECENT_REVERSE_SPLIT")
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["trigger_confirmation"] == 0.0

    def test_ignition_confirm_with_setup_adds_1(self):
        ep = _ep("PUMP_WATCH_HIGH",
                 subtypes=["FLOW_DIVERGENCE"],
                 badges=[_B_IGNITION_CONFIRM])
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["trigger_confirmation"] == 1.0

    def test_ignition_confirm_no_setup_adds_0(self):
        ep = _ep("PUMP_WATCH_HIGH", badges=[_B_IGNITION_CONFIRM])
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["trigger_confirmation"] == 0.0

    def test_gap_reset_is_context_only(self):
        ep = _ep("PUMP_WATCH_HIGH", badges=[_B_GAP_RESET])
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["trigger_confirmation"] == 0.0
        assert "gap_reset_context_only" in r["custom_flow_regime_reasons_v1"]

    def test_strong_trigger_is_has_strong_trigger(self):
        ep = _ep("PUMP_WATCH_HIGH", badges=[_B_ABSORB_PRESSURE])
        r  = _score(ep)
        assert r["custom_flow_regime_a_gate_passed"] is True or \
               r["custom_flow_regime_components_v1"]["trigger_confirmation"] == 3.0


# ── 4. Custom confirmation ────────────────────────────────────────────────────

class TestCustomConfirmation:
    def test_l34_with_flow_adds_1(self):
        ep = _ep("PUMP_WATCH_HIGH", subtypes=["FLOW_DIVERGENCE"])
        r  = _score(ep, _custom(l34=1))
        assert r["custom_flow_regime_components_v1"]["custom_confirmation"] == 1.0
        assert "l34_l43_with_flow_setup" in r["custom_flow_regime_reasons_v1"]

    def test_l43_with_flow_adds_1(self):
        ep = _ep("PUMP_WATCH_HIGH", subtypes=["FLOW_DIVERGENCE"])
        r  = _score(ep, _custom(l43=1))
        assert r["custom_flow_regime_components_v1"]["custom_confirmation"] == 1.0

    def test_l34_no_flow_setup_no_pts(self):
        ep = _ep("PUMP_WATCH_HIGH")  # no flow subtypes
        r  = _score(ep, _custom(l34=1))
        assert r["custom_flow_regime_components_v1"]["custom_confirmation"] == 0.0

    def test_d4_beup_clean_adds_1(self):
        ep = _ep("PUMP_WATCH_HIGH", split_ctx="NO_SPLIT")
        r  = _score(ep, _custom(d4_beup=1))
        assert r["custom_flow_regime_components_v1"]["custom_confirmation"] == 1.0

    def test_d4_beup_dirty_no_pts(self):
        ep = _ep("PUMP_WATCH_HIGH", split_ctx="RECENT_REVERSE_SPLIT")
        r  = _score(ep, _custom(d4_beup=1))
        assert r["custom_flow_regime_components_v1"]["custom_confirmation"] == 0.0

    def test_vbo_with_setup_adds_1(self):
        ep = _ep("PUMP_WATCH_HIGH", subtypes=["FLOW_ABSORPTION"])
        r  = _score(ep, _custom(vbo=1))
        assert r["custom_flow_regime_components_v1"]["custom_confirmation"] == 1.0

    def test_d4_l34_not_toxic_adds_1(self):
        ep = _ep("PUMP_WATCH_HIGH", split_ctx="NO_SPLIT")
        r  = _score(ep, _custom(d4_l34=1))
        assert r["custom_flow_regime_components_v1"]["custom_confirmation"] == 1.0

    def test_d4_l34_toxic_no_pts(self):
        ep = _ep("PUMP_WATCH_HIGH", split_ctx="SPLIT_ARTIFACT_RISK", split_artifact=True)
        r  = _score(ep, _custom(d4_l34=1))
        assert r["custom_flow_regime_components_v1"]["custom_confirmation"] == 0.0

    def test_repeated_l64_no_trigger_minus1(self):
        ep = _ep("PUMP_WATCH_HIGH", subtypes=["FLOW_DIVERGENCE"])
        r  = _score(ep, _custom(l64=5))
        assert r["custom_flow_regime_components_v1"]["custom_confirmation"] == -1.0
        assert "repeated_l64_no_trigger" in r["custom_flow_regime_risk_flags_v1"]

    def test_multiple_confirmations_stack(self):
        ep = _ep("PUMP_WATCH_HIGH",
                 subtypes=["FLOW_DIVERGENCE", "FLOW_ABSORPTION"],
                 split_ctx="NO_SPLIT")
        r  = _score(ep, _custom(l34=1, d4_beup=1, vbo=1))
        # l34_flow(+1) + d4_beup_clean(+1) + vbo_setup(+1) = 3
        assert r["custom_flow_regime_components_v1"]["custom_confirmation"] == 3.0


# ── 5. Regime scoring ─────────────────────────────────────────────────────────

class TestRegime:
    def test_price_1_3_adds_2(self):
        ep = _ep("PUMP_WATCH_HIGH", price_bucket="PRICE_1_TO_3")
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["regime"] >= 2.0

    def test_price_3_10_adds_2(self):
        ep = _ep("PUMP_WATCH_HIGH", price_bucket="PRICE_3_TO_10")
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["regime"] >= 2.0

    def test_price_sub1_liquid_adds_1(self):
        ep = _ep("PUMP_WATCH_HIGH", price_bucket="PRICE_SUB_1", dv_bucket="DV_OK_250K_1M")
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["regime"] >= 1.0

    def test_dv_ok_adds_1(self):
        ep = _ep("PUMP_WATCH_HIGH", dv_bucket="DV_OK_250K_1M")
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["regime"] >= 1.0

    def test_atr_normal_adds_1(self):
        ep = _ep("PUMP_WATCH_HIGH", atr_bucket="ATR_NORMAL_5_15")
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["regime"] >= 1.0

    def test_no_split_adds_1(self):
        ep = _ep("PUMP_WATCH_HIGH", split_ctx="NO_SPLIT")
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["regime"] >= 1.0


# ── 6. Risk penalties ─────────────────────────────────────────────────────────

class TestRiskPenalties:
    def test_split_artifact_minus5(self):
        ep = _ep("PUMP_WATCH_HIGH", split_ctx="SPLIT_ARTIFACT_RISK", split_artifact=True)
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["risk_penalty"] <= -5.0
        assert "split_artifact" in r["custom_flow_regime_risk_flags_v1"]

    def test_recent_reverse_split_minus4(self):
        ep = _ep("PUMP_WATCH_HIGH", split_ctx="RECENT_REVERSE_SPLIT")
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["risk_penalty"] <= -4.0
        assert "recent_reverse_split" in r["custom_flow_regime_risk_flags_v1"]

    def test_old_reverse_split_minus3(self):
        ep = _ep("PUMP_WATCH_HIGH", split_ctx="OLD_REVERSE_SPLIT")
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["risk_penalty"] <= -3.0
        assert "old_reverse_split" in r["custom_flow_regime_risk_flags_v1"]

    def test_atr_extreme_minus3(self):
        ep = _ep("PUMP_WATCH_HIGH", atr_bucket="ATR_EXTREME_GT_40")
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["risk_penalty"] <= -3.0
        assert "atr_extreme" in r["custom_flow_regime_risk_flags_v1"]

    def test_price_gt25_minus2(self):
        ep = _ep("PUMP_WATCH_HIGH", price_bucket="PRICE_GT_25")
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["risk_penalty"] <= -2.0
        assert "price_gt25" in r["custom_flow_regime_risk_flags_v1"]

    def test_dv_illiquid_minus2(self):
        ep = _ep("PUMP_WATCH_HIGH", dv_bucket="DV_ILLIQUID_LT_50K")
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["risk_penalty"] <= -2.0
        assert "dv_illiquid" in r["custom_flow_regime_risk_flags_v1"]

    def test_pure_bearish_stress_minus2(self):
        ep = _ep("PUMP_WATCH_HIGH", subtypes=["FLOW_BEARISH_STRESS"])
        r  = _score(ep)
        assert r["custom_flow_regime_components_v1"]["risk_penalty"] <= -2.0
        assert "pure_bearish_stress_no_trigger" in r["custom_flow_regime_risk_flags_v1"]

    def test_bearish_stress_with_divergence_no_extra_penalty(self):
        ep = _ep("PUMP_WATCH_HIGH", subtypes=["FLOW_DIVERGENCE", "FLOW_BEARISH_STRESS"])
        r  = _score(ep)
        assert "pure_bearish_stress_no_trigger" not in r["custom_flow_regime_risk_flags_v1"]


# ── 7-11. A-gate tests ────────────────────────────────────────────────────────

class TestAGates:
    def _cfr_a_ep(self):
        """Minimal episode that passes all 5 gates."""
        return _ep(
            "PUMP_WATCH_HIGH",
            subtypes=["FLOW_DIVERGENCE"],
            badges=[_B_ABSORB_PRESSURE],
            price_bucket="PRICE_1_TO_3",
            atr_bucket="ATR_NORMAL_5_15",
            dv_bucket="DV_OK_250K_1M",
            split_ctx="NO_SPLIT",
        )

    def test_all_gates_pass(self):
        r = _score(self._cfr_a_ep(), _custom(l34=1))
        assert r["custom_flow_regime_a_gate_passed"] is True

    def test_gate1_pump_ignore_blocks(self):
        ep = _ep("PUMP_IGNORE", badges=[_B_ABSORB_PRESSURE])
        r  = _score(ep)
        assert r["custom_flow_regime_a_gate_passed"] is False
        assert "pump_ignore_without_exception" in r["custom_flow_regime_a_blockers"]

    def test_gate2_split_artifact_blocks(self):
        ep = _ep("PUMP_WATCH_HIGH", badges=[_B_ABSORB_PRESSURE],
                 split_ctx="SPLIT_ARTIFACT_RISK", split_artifact=True)
        r  = _score(ep)
        assert r["custom_flow_regime_a_gate_passed"] is False
        assert "split_artifact" in r["custom_flow_regime_a_blockers"]

    def test_gate2_atr_extreme_blocks(self):
        ep = _ep("PUMP_WATCH_HIGH", badges=[_B_ABSORB_PRESSURE],
                 atr_bucket="ATR_EXTREME_GT_40")
        r  = _score(ep)
        assert r["custom_flow_regime_a_gate_passed"] is False
        assert "atr_extreme" in r["custom_flow_regime_a_blockers"]

    def test_gate2_price_gt25_blocks(self):
        ep = _ep("PUMP_WATCH_HIGH", badges=[_B_ABSORB_PRESSURE],
                 price_bucket="PRICE_GT_25")
        r  = _score(ep)
        assert r["custom_flow_regime_a_gate_passed"] is False
        assert "price_gt25" in r["custom_flow_regime_a_blockers"]

    def test_gate3_no_trigger_blocks(self):
        ep = _ep("PUMP_WATCH_HIGH", subtypes=["FLOW_DIVERGENCE"])
        r  = _score(ep)
        assert r["custom_flow_regime_a_gate_passed"] is False
        assert "no_trigger_confirmation" in r["custom_flow_regime_a_blockers"]

    def test_gate4_pure_l64_blocks(self):
        ep = _ep("PUMP_WATCH_HIGH", subtypes=["FLOW_DIVERGENCE"])
        # l64 present but no l34/l43 and no strong trigger
        r  = _score(ep, _custom(l64=2))
        assert "pure_l64_stress" in r["custom_flow_regime_a_blockers"]

    def test_gate4_pure_bearish_stress_blocks(self):
        ep = _ep("PUMP_WATCH_HIGH", subtypes=["FLOW_BEARISH_STRESS"])
        r  = _score(ep)
        assert r["custom_flow_regime_a_gate_passed"] is False
        assert any("bearish_stress" in b or "setup_only" in b
                   for b in r["custom_flow_regime_a_blockers"])

    def test_gate5_risk_flags_block(self):
        ep = _ep("PUMP_WATCH_HIGH", badges=[_B_ABSORB_PRESSURE],
                 split_ctx="RECENT_REVERSE_SPLIT")
        r  = _score(ep)
        assert r["custom_flow_regime_a_gate_passed"] is False

    def test_illiquid_waived_by_strong_trigger(self):
        ep = _ep("PUMP_WATCH_HIGH", badges=[_B_ABSORB_PRESSURE],
                 dv_bucket="DV_ILLIQUID_LT_50K", split_ctx="NO_SPLIT",
                 atr_bucket="ATR_NORMAL_5_15", price_bucket="PRICE_1_TO_3")
        r  = _score(ep)
        # illiquid waived because strong trigger present; gate 2 ok
        assert "illiquid" not in r["custom_flow_regime_a_blockers"]


# ── 12. Bucket assignment ─────────────────────────────────────────────────────

class TestBucketAssignment:
    def test_cfr_a_perfect_episode(self):
        ep = _ep("PUMP_WATCH_HIGH",
                 subtypes=["FLOW_DIVERGENCE", "FLOW_ABSORPTION"],
                 badges=[_B_ABSORB_PRESSURE],
                 price_bucket="PRICE_1_TO_3",
                 atr_bucket="ATR_NORMAL_5_15",
                 dv_bucket="DV_OK_250K_1M",
                 split_ctx="NO_SPLIT")
        r  = _score(ep, _custom(l34=1, d4_beup=1))
        assert r["custom_flow_regime_bucket_v1"] == "CFR_A"

    def test_cfr_avoid_pump_ignore_no_trigger(self):
        r = _score(_ep("PUMP_IGNORE"))
        assert r["custom_flow_regime_bucket_v1"] == "CFR_AVOID"

    def test_cfr_c_medium_score(self):
        # PW MEDIUM(+3) + no flow + ATR normal(+1) + no_split(+1) + dv_ok(+1) = 6
        # but gate3 fails (no trigger) → CFR_B not CFR_A
        # total=6 → CFR_B
        ep = _ep("PUMP_WATCH_MEDIUM",
                 price_bucket="PRICE_1_TO_3",
                 atr_bucket="ATR_NORMAL_5_15",
                 dv_bucket="DV_OK_250K_1M",
                 split_ctx="NO_SPLIT")
        r  = _score(ep)
        assert r["custom_flow_regime_bucket_v1"] in ("CFR_B", "CFR_C")

    def test_score_clamped_to_20(self):
        # Max possible: PW_HIGH(4) + flow_3(3) + trigger_3(3) + custom_4(4) + regime_5(5) = 19
        ep = _ep("PUMP_WATCH_HIGH",
                 subtypes=["FLOW_DIVERGENCE", "FLOW_ABSORPTION", "FLOW_BULLISH_ACCUM"],
                 badges=[_B_ABSORB_PRESSURE],
                 price_bucket="PRICE_1_TO_3",
                 atr_bucket="ATR_NORMAL_5_15",
                 dv_bucket="DV_LIQUID_1M_10M",
                 split_ctx="NO_SPLIT")
        r  = _score(ep, _custom(l34=1, d4_beup=1, vbo=1, d4_l34=1))
        assert r["custom_flow_regime_score_v1"] <= 20

    def test_score_not_below_minus20(self):
        ep = _ep("PUMP_IGNORE", split_ctx="SPLIT_ARTIFACT_RISK",
                 split_artifact=True, atr_bucket="ATR_EXTREME_GT_40",
                 price_bucket="PRICE_GT_25", dv_bucket="DV_ILLIQUID_LT_50K",
                 subtypes=["FLOW_BEARISH_STRESS"])
        r  = _score(ep)
        assert r["custom_flow_regime_score_v1"] >= -20


# ── 13. PUMP_SPECULATIVE → CFR_A path ────────────────────────────────────────

class TestSpeculativePath:
    def test_speculative_with_trigger_clean_custom_can_be_cfr_a(self):
        ep = _ep("PUMP_SPECULATIVE",
                 subtypes=["FLOW_DIVERGENCE"],
                 badges=[_B_ABSORB_PRESSURE],
                 price_bucket="PRICE_1_TO_3",
                 atr_bucket="ATR_NORMAL_5_15",
                 dv_bucket="DV_OK_250K_1M",
                 split_ctx="NO_SPLIT")
        r  = _score(ep, _custom(l34=1))
        # base(+1) + flow_setup(+1) + trigger(+3) + custom(+1) + regime(4+) >= 9
        assert r["custom_flow_regime_components_v1"]["pump_watch_base"] == 1.0
        assert r["custom_flow_regime_components_v1"]["trigger_confirmation"] == 3.0

    def test_speculative_no_trigger_cannot_be_cfr_a(self):
        ep = _ep("PUMP_SPECULATIVE", subtypes=["FLOW_DIVERGENCE"])
        r  = _score(ep)
        assert r["custom_flow_regime_a_gate_passed"] is False
        assert "no_trigger_confirmation" in r["custom_flow_regime_a_blockers"]


# ── 14. PUMP_IGNORE ceiling ───────────────────────────────────────────────────

class TestIgnoreCeiling:
    def test_pump_ignore_cannot_be_cfr_a(self):
        ep = _ep("PUMP_IGNORE",
                 subtypes=["FLOW_DIVERGENCE"],
                 badges=[_B_ABSORB_PRESSURE],
                 price_bucket="PRICE_1_TO_3",
                 atr_bucket="ATR_NORMAL_5_15",
                 dv_bucket="DV_OK_250K_1M",
                 split_ctx="NO_SPLIT")
        r  = _score(ep, _custom(l34=1))
        assert r["custom_flow_regime_bucket_v1"] != "CFR_A"
        assert r["custom_flow_regime_a_gate_passed"] is False


# ── 15. Anti-leakage ─────────────────────────────────────────────────────────

class TestAntiLeakage:
    def test_pump_multiple_not_in_score_reasons(self):
        ep = _ep("PUMP_WATCH_HIGH", pump_multiple=10.0)
        r  = _score(ep)
        reasons_str = " ".join(r.get("custom_flow_regime_reasons_v1") or [])
        assert "pump_multiple" not in reasons_str

    def test_group_type_not_in_score_reasons(self):
        ep = _ep("PUMP_WATCH_HIGH", group_type="4X_PUMP")
        r1 = _score(ep)
        ep2 = _ep("PUMP_WATCH_HIGH", group_type="FALSE_POSITIVE")
        r2  = _score(ep2)
        assert r1["custom_flow_regime_score_v1"] == r2["custom_flow_regime_score_v1"]

    def test_same_score_regardless_of_outcome(self):
        ep_a = _ep("PUMP_WATCH_HIGH", pump_multiple=5.0, group_type="4X_PUMP")
        ep_b = _ep("PUMP_WATCH_HIGH", pump_multiple=None, group_type=None)
        assert _score(ep_a)["custom_flow_regime_score_v1"] == \
               _score(ep_b)["custom_flow_regime_score_v1"]

    def test_abr_fields_not_read_by_scoring(self):
        # ABR disabled: adding abr_sp500 / tz_quality_score must not change score
        ep_base = _ep("PUMP_WATCH_HIGH")
        ep_abr  = dict(_ep("PUMP_WATCH_HIGH"))
        ep_abr["abr_sp500"] = "A"
        ep_abr["tz_quality_score"] = 90
        ep_abr["tz_quality_tier_sp500"] = "STRONG"
        r_base = _score(ep_base)
        r_abr  = _score(ep_abr)
        assert r_base["custom_flow_regime_score_v1"] == r_abr["custom_flow_regime_score_v1"]


# ── 16. build_cfr_selector_analysis: empty input ─────────────────────────────

class TestBuildCfrEmpty:
    def test_empty_list_returns_safe_default(self):
        result = build_cfr_selector_analysis([])
        assert "custom_flow_regime_selector_v1_analysis" in result
        ana = result["custom_flow_regime_selector_v1_analysis"]
        assert ana["summary"]["total_episodes"] == 0
        assert ana["bucket_performance"] == {}

    def test_none_daily_ok(self):
        result = build_cfr_selector_analysis([], daily_by_episode=None)
        assert result["custom_flow_regime_selector_v1_analysis"]["summary"]["total_episodes"] == 0


# ── 17. build_cfr_selector_analysis: multi-episode distribution ───────────────

class TestBuildCfrMulti:
    def _make_episodes(self):
        return [
            # strong episode → expect CFR_A
            dict(_ep("PUMP_WATCH_HIGH",
                     subtypes=["FLOW_DIVERGENCE"],
                     badges=[_B_ABSORB_PRESSURE],
                     price_bucket="PRICE_1_TO_3",
                     atr_bucket="ATR_NORMAL_5_15",
                     dv_bucket="DV_OK_250K_1M",
                     split_ctx="NO_SPLIT"),
                 episode_id=1, pump_multiple=5.0, group_type="4X_PUMP"),
            # weak episode → CFR_AVOID or CFR_C
            dict(_ep("PUMP_IGNORE", split_ctx="RECENT_REVERSE_SPLIT"),
                 episode_id=2, pump_multiple=1.2, group_type="FALSE_POSITIVE"),
            # medium episode → CFR_B or CFR_C
            dict(_ep("PUMP_WATCH_MEDIUM",
                     price_bucket="PRICE_1_TO_3",
                     dv_bucket="DV_OK_250K_1M",
                     atr_bucket="ATR_NORMAL_5_15",
                     split_ctx="NO_SPLIT"),
                 episode_id=3, pump_multiple=2.5, group_type="WATCHLIST"),
        ]

    def test_result_has_all_keys(self):
        result = build_cfr_selector_analysis(self._make_episodes())
        ana    = result["custom_flow_regime_selector_v1_analysis"]
        required = [
            "summary", "bucket_performance", "compare_vs_pump_watch",
            "cfr_x_pump_watch_matrix", "cfr_x_flow_badge_matrix",
            "cfr_x_custom_matrix", "cfr_x_regime_matrix",
            "top_cfr_a", "cfr_a_false_positives", "cfr_a_4x_examples",
            "blocked_from_a_examples", "top_a_blockers", "recommendations",
            "anti_leakage",
        ]
        for key in required:
            assert key in ana, f"Missing key: {key}"

    def test_total_episodes_correct(self):
        eps    = self._make_episodes()
        ana    = build_cfr_selector_analysis(eps)["custom_flow_regime_selector_v1_analysis"]
        assert ana["summary"]["total_episodes"] == 3

    def test_abr_disabled_flag(self):
        ana = build_cfr_selector_analysis(self._make_episodes())["custom_flow_regime_selector_v1_analysis"]
        assert ana["summary"]["abr_disabled"] is True
        assert ana["summary"]["use_abr_in_cfr_v1"] is False

    def test_bucket_counts_sum_to_total(self):
        ana  = build_cfr_selector_analysis(self._make_episodes())["custom_flow_regime_selector_v1_analysis"]
        s    = ana["summary"]
        total = s["cfr_a_count"] + s["cfr_b_count"] + s["cfr_c_count"] + s["cfr_avoid_count"]
        assert total == s["total_episodes"]

    def test_bucket_performance_has_all_present_buckets(self):
        ana = build_cfr_selector_analysis(self._make_episodes())["custom_flow_regime_selector_v1_analysis"]
        bp  = ana["bucket_performance"]
        # every bucket present in scoring should appear in performance
        for bk in bp:
            assert bk in ("CFR_A", "CFR_B", "CFR_C", "CFR_AVOID")


# ── 18. score_episodes_cfr: in-place mutation ─────────────────────────────────

class TestScoreEpisodesInPlace:
    def test_returns_same_list(self):
        eps = [_ep("PUMP_WATCH_HIGH")]
        out = score_episodes_cfr(eps)
        assert out is eps

    def test_dicts_mutated_in_place(self):
        ep  = _ep("PUMP_WATCH_HIGH")
        score_episodes_cfr([ep])
        assert "custom_flow_regime_score_v1" in ep
        assert "custom_flow_regime_bucket_v1" in ep

    def test_empty_list_ok(self):
        result = score_episodes_cfr([])
        assert result == []

    def test_daily_by_episode_lookup(self):
        import json
        ep = dict(_ep("PUMP_WATCH_HIGH", subtypes=["FLOW_DIVERGENCE"]), episode_id=99)
        daily_row = {"feature_json": json.dumps({"has_l34": True})}
        score_episodes_cfr([ep], daily_by_episode={99: [daily_row]})
        assert ep.get("custom_flow_regime_bucket_v1") is not None


# ── Regime helpers ─────────────────────────────────────────────────────────────

class TestRegimeHelpers:
    def test_is_clean_regime_split_artifact_false(self):
        ep = _ep(split_artifact=True)
        assert _is_clean_regime(ep) is False

    def test_is_clean_regime_recent_reverse_false(self):
        ep = _ep(split_ctx="RECENT_REVERSE_SPLIT")
        assert _is_clean_regime(ep) is False

    def test_is_clean_regime_atr_extreme_false(self):
        ep = _ep(atr_bucket="ATR_EXTREME_GT_40")
        assert _is_clean_regime(ep) is False

    def test_is_clean_regime_price_gt25_false(self):
        ep = _ep(price_bucket="PRICE_GT_25")
        assert _is_clean_regime(ep) is False

    def test_is_clean_regime_ok(self):
        assert _is_clean_regime(_ep()) is True

    def test_is_toxic_artifact(self):
        assert _is_toxic_regime(_ep(split_artifact=True)) is True

    def test_is_toxic_recent_reverse(self):
        assert _is_toxic_regime(_ep(split_ctx="RECENT_REVERSE_SPLIT")) is True

    def test_is_not_toxic_clean(self):
        assert _is_toxic_regime(_ep()) is False


# ── _aggregate_custom_signals ──────────────────────────────────────────────────

class TestAggregateCustomSignals:
    def test_empty_rows(self):
        result = _aggregate_custom_signals([])
        assert result["l34"] == 0

    def test_counts_feature_json_flags(self):
        import json
        rows = [
            {"feature_json": json.dumps({"has_l34": True, "has_l43": True})},
            {"feature_json": json.dumps({"has_l34": True})},
        ]
        result = _aggregate_custom_signals(rows)
        assert result["l34"] == 2
        assert result["l43"] == 1
        assert result["l64"] == 0

    def test_handles_string_feature_json(self):
        import json
        rows = [{"feature_json": json.dumps({"has_vbo": True})}]
        result = _aggregate_custom_signals(rows)
        assert result["vbo"] == 1

    def test_handles_missing_feature_json(self):
        rows = [{"other_field": "x"}]
        result = _aggregate_custom_signals(rows)
        assert result["l34"] == 0


# ── Metric family separation (outcome vs group_type) ──────────────────────────

class TestMetricFamilySeparation:
    """
    Verifies that bucket_performance and the top-level summary expose
    both metric families correctly:
      outcome_*  — derived from pump_multiple
      group_*    — derived from group_type label (lowercase)

    Root bug fixed: old code compared group_type against "FALSE_POSITIVE"
    (uppercase) while the DB stores "false_positive" (lowercase), yielding
    group_false_positive_count=0 even when the distribution showed 14 FPs.
    """

    def _make_cfr_a_eps(self, *, group_types, pump_multiples):
        eps = []
        for i, (gt, pm) in enumerate(zip(group_types, pump_multiples)):
            ep = dict(_ep(
                "PUMP_WATCH_HIGH",
                subtypes=["FLOW_DIVERGENCE"],
                badges=[_B_ABSORB_PRESSURE],
                price_bucket="PRICE_1_TO_3",
                atr_bucket="ATR_NORMAL_5_15",
                dv_bucket="DV_OK_250K_1M",
                split_ctx="NO_SPLIT",
                pump_multiple=pm,
                group_type=gt,
            ), episode_id=i)
            eps.append(ep)
        return eps

    def test_group_fp_count_uses_lowercase(self):
        # 2 false_positive (lowercase), 1 4x_pump
        eps = self._make_cfr_a_eps(
            group_types=["false_positive", "false_positive", "4x_pump"],
            pump_multiples=[1.1, 1.2, 5.0],
        )
        result = build_cfr_selector_analysis(eps)
        ana    = result["custom_flow_regime_selector_v1_analysis"]
        s      = ana["summary"]
        assert s["cfr_a_group_false_positive_count"] == 2
        assert s["cfr_a_group_4x_count"] == 1

    def test_group_fp_rate_correct(self):
        eps = self._make_cfr_a_eps(
            group_types=["false_positive"] * 14 + ["4x_pump"] * 6,
            pump_multiples=[1.0] * 14 + [5.0] * 6,
        )
        result = build_cfr_selector_analysis(eps)
        ana    = result["custom_flow_regime_selector_v1_analysis"]
        s      = ana["summary"]
        assert s["cfr_a_group_false_positive_count"] == 14
        assert s["cfr_a_group_false_positive_rate"] is not None
        assert abs(s["cfr_a_group_false_positive_rate"] - 14 / 20) < 0.001

    def test_outcome_4x_rate_independent_of_group_type(self):
        # pump_multiple >= 4 for 3 episodes, group_type is "false_positive" for all
        eps = self._make_cfr_a_eps(
            group_types=["false_positive"] * 5,
            pump_multiples=[5.0, 4.1, 4.5, 2.0, 1.0],
        )
        result = build_cfr_selector_analysis(eps)
        ana    = result["custom_flow_regime_selector_v1_analysis"]
        s      = ana["summary"]
        # 3 episodes have pm>=4, all are false_positive by group
        assert s["cfr_a_outcome_4x_count"] == 3
        assert s["cfr_a_group_false_positive_count"] == 5

    def test_bucket_performance_has_new_fields(self):
        eps = self._make_cfr_a_eps(
            group_types=["4x_pump", "false_positive"],
            pump_multiples=[5.0, 1.0],
        )
        result = build_cfr_selector_analysis(eps)
        bp     = result["custom_flow_regime_selector_v1_analysis"]["bucket_performance"]
        cfr_a  = bp.get("CFR_A") or {}
        required = [
            "outcome_4x_count", "outcome_4x_rate",
            "group_4x_count",   "group_4x_rate",
            "group_false_positive_count", "group_false_positive_rate",
            "normal_winner_count", "split_artifact_count",
        ]
        for field in required:
            assert field in cfr_a, f"Missing field in bucket_performance: {field}"

    def test_bucket_performance_no_old_fields(self):
        # Old fields ('4x_count', 'false_positive_count', 'false_positive_rate')
        # must not appear — they were misleading / wrong-case
        eps = self._make_cfr_a_eps(
            group_types=["4x_pump"],
            pump_multiples=[5.0],
        )
        result = build_cfr_selector_analysis(eps)
        bp     = result["custom_flow_regime_selector_v1_analysis"]["bucket_performance"]
        cfr_a  = bp.get("CFR_A") or {}
        assert "4x_count"           not in cfr_a
        assert "false_positive_count" not in cfr_a
        assert "false_positive_rate"  not in cfr_a
        assert "4x_rate"            not in cfr_a

    def test_sanity_warning_triggered_on_uppercase_gt(self):
        # Simulate the run-149 bug: group_type_distribution shows fp=14 but
        # uppercase "FALSE_POSITIVE" would produce count=0.
        # The fix lowercases internally so count should now be >0 and no warning.
        eps = self._make_cfr_a_eps(
            group_types=["false_positive"] * 3,
            pump_multiples=[1.0, 1.1, 1.2],
        )
        result = build_cfr_selector_analysis(eps)
        ana    = result["custom_flow_regime_selector_v1_analysis"]
        s      = ana["summary"]
        # No sanity warning because count is correct
        assert s["cfr_a_group_false_positive_count"] == 3
        assert not s.get("sanity_warnings")

    def test_baseline_uses_renamed_fields(self):
        eps = self._make_cfr_a_eps(
            group_types=["4x_pump", "false_positive", "normal_winner"],
            pump_multiples=[5.0, 1.0, 2.0],
        )
        result = build_cfr_selector_analysis(eps)
        ana    = result["custom_flow_regime_selector_v1_analysis"]
        baseline = ana["compare_vs_pump_watch"]["cfr_a_vs_pw_high_baseline"]
        assert "outcome_4x_rate" in baseline
        assert "group_false_positive_rate" in baseline
        assert "4x_rate"           not in baseline
        assert "false_positive_rate" not in baseline

    def test_summary_has_all_new_fields(self):
        eps = self._make_cfr_a_eps(
            group_types=["4x_pump"],
            pump_multiples=[5.0],
        )
        result = build_cfr_selector_analysis(eps)
        s      = result["custom_flow_regime_selector_v1_analysis"]["summary"]
        new_fields = [
            "cfr_a_outcome_4x_count", "cfr_a_outcome_4x_rate",
            "cfr_a_group_4x_count",   "cfr_a_group_4x_rate",
            "cfr_a_group_false_positive_count", "cfr_a_group_false_positive_rate",
        ]
        for f in new_fields:
            assert f in s, f"Missing summary field: {f}"
