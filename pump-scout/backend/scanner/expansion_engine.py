"""
Post-Compression Expansion Engine.

A SEPARATE structure sub-engine that detects setups where compression +
accumulation precede sustainable expansion.  Independent of New Pump and
impulse paths — emits its own score/label/state/risk.  Never mixed into
new_pump_score or impulse_score.

Research evidence:
- Compression often appears as an early structural precursor
- Accumulation-like behaviour appears before many 4x pumps
- Spring/LPS often appears before expansion
- False positives can still show attractive price mechanics without
  sustained expansion — extreme one-day volume alone is not bullish
- Some 4x pumps are POST_COMPRESSION_BREAKOUT even when New Pump
  sequence is absent or insufficient (AFJK, TCGL)

States (priority order):
  OVERHEATED_EXPANSION — vertical move + extreme vol + weak base
  EXPANSION_START      — prior compression, range/volume starting to expand
  ACCUMULATION_READY   — compression + accumulation + spring/LPS or support test
  COMPRESSED_BASE      — compression + dryup, not yet extended
  NONE                 — none of the above

Labels: NONE / WEAK / MODERATE / STRONG / RISKY

Uses only pre-breakout / live-safe features. No future / outcome leakage.
"""
from typing import Optional


# ── Primitive detectors ──────────────────────────────────────────────────────

def _compression(bars, last) -> tuple:
    """
    Return (is_compressed, ratio).
    Tight path: 5-bar range / 20-bar range < 0.40.
    Long-base path: 20-bar range / 60-bar range < 0.45 (covers multi-week tight bases).
    """
    if last < 19:
        return False, None
    hi5  = max(b["high"] for b in bars[last - 4: last + 1])
    lo5  = min(b["low"]  for b in bars[last - 4: last + 1])
    hi20 = max(b["high"] for b in bars[last - 19: last + 1])
    lo20 = min(b["low"]  for b in bars[last - 19: last + 1])
    r20 = hi20 - lo20
    if r20 > 0:
        ratio = (hi5 - lo5) / r20
        if ratio < 0.40:
            return True, ratio

    # Long-base tightness: 20-bar range vs 60-bar range
    if last >= 59:
        hi60 = max(b["high"] for b in bars[last - 59: last + 1])
        lo60 = min(b["low"]  for b in bars[last - 59: last + 1])
        r60 = hi60 - lo60
        if r60 > 0 and r20 / r60 < 0.45:
            return True, r20 / r60

    return False, None


def _dryup(volumes, last) -> tuple:
    """Return (is_dry, ratio). min_5 / avg_20 < 0.75 (aligns with base_quality threshold)."""
    if last < 19 or len(volumes) <= last:
        return False, None
    avg_v20 = sum(volumes[last - 19: last + 1]) / 20
    if avg_v20 <= 0:
        return False, None
    min_v5 = min(volumes[last - 4: last + 1])
    ratio = min_v5 / avg_v20
    return ratio < 0.75, ratio


def _accumulation_count(bars, last, window: int = 15) -> int:
    """Count bars with close in upper 60% of daily range + above-median volume."""
    if last < window - 1:
        return 0
    start = max(0, last - window + 1)
    vols = [bars[j]["volume"] for j in range(start, last + 1)]
    if not vols:
        return 0
    sv = sorted(vols)
    med = sv[len(sv) // 2]
    count = 0
    for j in range(start, last + 1):
        b = bars[j]
        rng = b["high"] - b["low"]
        if rng <= 0:
            continue
        upper_pct = (b["close"] - b["low"]) / rng
        if upper_pct >= 0.60 and b["volume"] >= med:
            count += 1
    return count


def _spring_or_lps(bars, last) -> bool:
    """
    Spring / LPS within last 10 bars: a bar that wicked below the prior
    15-bar low but closed back above it.
    """
    if last < 15:
        return False
    for j in range(max(15, last - 9), last + 1):
        prior_low = min(b["low"] for b in bars[j - 15: j])
        if bars[j]["low"] < prior_low and bars[j]["close"] > prior_low:
            return True
    return False


def _expansion(bars, last) -> tuple:
    """
    Current bar shows range expansion (vs last 10 bars) AND up close.
    Returns (is_expanding, range_mult).
    """
    if last < 10:
        return False, None
    last_bar = bars[last]
    last_range = last_bar["high"] - last_bar["low"]
    prev_ranges = [bars[j]["high"] - bars[j]["low"]
                   for j in range(max(0, last - 10), last)]
    avg_prev = sum(prev_ranges) / len(prev_ranges) if prev_ranges else 0
    if avg_prev <= 0:
        return False, None
    mult = last_range / avg_prev
    is_up = last_bar["close"] > last_bar["open"]
    return (mult >= 1.5 and is_up), mult


def _atr_pct(bars, last) -> Optional[float]:
    if last < 10:
        return None
    trs = []
    for i in range(max(1, last - 9), last + 1):
        h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    c = bars[last]["close"]
    if not trs or c <= 0:
        return None
    return (sum(trs) / len(trs)) / c * 100


def _pct_3d(bars, last) -> Optional[float]:
    if last < 3:
        return None
    p0 = bars[last]["close"]
    p3 = bars[last - 3]["close"]
    if p3 <= 0:
        return None
    return (p0 - p3) / p3 * 100


# ── Public API ───────────────────────────────────────────────────────────────

def analyze_expansion(bars, *, base_quality_score: int,
                      avg_ema_spread: Optional[float],
                      volume_z: Optional[float],
                      ema_extended: Optional[float]) -> dict:
    """
    Run the post-compression expansion engine.

    Returns dict with:
      compression_expansion_state  — NONE | COMPRESSED_BASE | ACCUMULATION_READY
                                     | EXPANSION_START | OVERHEATED_EXPANSION
      compression_expansion_score  — 0..100
      compression_expansion_label  — NONE | WEAK | MODERATE | STRONG | RISKY
      expansion_timing_risk        — LOW | MEDIUM | HIGH
      expansion_quality_flags      — dict of explainable flags
    """
    if not bars or len(bars) < 20:
        return _empty()

    last = len(bars) - 1
    volumes = [b["volume"] for b in bars]

    is_comp,  comp_ratio  = _compression(bars, last)
    is_dry,   dry_ratio   = _dryup(volumes, last)
    accum_n               = _accumulation_count(bars, last)
    is_spring             = _spring_or_lps(bars, last)
    is_exp,   range_mult  = _expansion(bars, last)
    atr_pct               = _atr_pct(bars, last)
    pct3d                 = _pct_3d(bars, last)

    # Prior compression check — excludes the most recent 3 bars so an
    # expansion bar at the edge doesn't falsify its own compression base.
    is_comp_prior = False
    if last >= 22:
        prior_end = last - 3
        ok, _ = _compression(bars, prior_end)
        is_comp_prior = ok

    # Overheated: vertical move + extreme vol + weak base
    is_overheated = bool(
        pct3d is not None and pct3d >= 20
        and volume_z is not None and volume_z >= 4.0
        and base_quality_score < 40
    )

    # ── Flags ────────────────────────────────────────────────────────────────
    flags: dict = {}
    if is_comp:
        flags["compression"] = True
    else:
        flags["no_compression"] = True
    if is_dry:
        flags["dryup"] = True
    if accum_n >= 4:
        flags["accumulation_like"] = True
    if is_spring:
        flags["spring_or_lps"] = True
    if atr_pct is not None and atr_pct >= 7.0:
        flags["chaotic_atr"] = True
    if avg_ema_spread is not None and avg_ema_spread >= 55:
        flags["wide_ema_spread"] = True
    if ema_extended is not None and ema_extended >= 1.30:
        flags["overextended"] = True
    if is_overheated:
        flags["vertical_overheat"] = True
    if volume_z is not None and volume_z >= 4.0 and not (is_comp or is_comp_prior):
        flags["anomaly_without_base"] = True
    if is_exp and not (is_comp or is_comp_prior):
        flags["expansion_without_compression"] = True

    # ── State (priority top-down) ────────────────────────────────────────────
    controlled_atr = (atr_pct is None) or (atr_pct < 7.0)
    not_extended   = (ema_extended is None) or (ema_extended < 1.30)

    if is_overheated:
        state = "OVERHEATED_EXPANSION"
    elif (is_exp and (is_comp or is_comp_prior) and controlled_atr and not_extended
          and (volume_z is None or volume_z < 5.0)):
        state = "EXPANSION_START"
    elif (is_comp and accum_n >= 4 and (is_spring or accum_n >= 6)
          and controlled_atr):
        state = "ACCUMULATION_READY"
    elif is_comp and is_dry and not_extended:
        state = "COMPRESSED_BASE"
    else:
        state = "NONE"

    # ── Score (0..100) ───────────────────────────────────────────────────────
    score = 0
    # Rewards
    if is_comp or is_comp_prior:
        score += 18
    if is_dry:    score += 12
    if accum_n >= 6:   score += 15
    elif accum_n >= 4: score += 9
    elif accum_n >= 2: score += 4
    if is_spring: score += 12
    if is_exp and state in ("EXPANSION_START", "ACCUMULATION_READY"):
        score += 10 if (range_mult is not None and range_mult < 2.5) else 6

    # Base-quality anchor: controlled base lifts score
    if base_quality_score >= 60:   score += 10
    elif base_quality_score >= 40: score += 4

    # EMA tightness
    if avg_ema_spread is not None:
        if avg_ema_spread < 25:    score += 8
        elif avg_ema_spread < 40:  score += 4
        elif avg_ema_spread > 55:  score -= 6

    # Volatility control
    if atr_pct is not None:
        if atr_pct < 4.0:  score += 6
        elif atr_pct >= 7.0: score -= 8

    # Penalties
    if volume_z is not None and volume_z >= 4.0 and not (is_comp or is_comp_prior):
        score -= 10
    if ema_extended is not None and ema_extended >= 1.30:
        score -= 10
    if is_overheated:
        score -= 15

    score = max(0, min(100, score))

    # ── Timing risk ──────────────────────────────────────────────────────────
    if is_overheated:
        risk = "HIGH"
    elif flags.get("anomaly_without_base") or flags.get("chaotic_atr"):
        risk = "HIGH"
    elif flags.get("overextended") or flags.get("wide_ema_spread"):
        risk = "MEDIUM"
    elif state in ("ACCUMULATION_READY", "EXPANSION_START", "COMPRESSED_BASE") and score >= 40:
        risk = "LOW"
    elif state == "NONE":
        risk = "LOW" if score < 15 else "MEDIUM"
    else:
        risk = "MEDIUM"

    # ── Label ────────────────────────────────────────────────────────────────
    if state == "OVERHEATED_EXPANSION":
        label = "RISKY"
    elif state == "NONE":
        label = "NONE" if score < 15 else "WEAK"
    elif score >= 65 and state in ("ACCUMULATION_READY", "EXPANSION_START"):
        label = "STRONG"
    elif score >= 45:
        label = "MODERATE"
    elif score >= 25:
        label = "WEAK"
    else:
        label = "NONE"

    return dict(
        compression_expansion_state=state,
        compression_expansion_score=score,
        compression_expansion_label=label,
        expansion_timing_risk=risk,
        expansion_quality_flags=flags,
    )


def _empty() -> dict:
    return dict(
        compression_expansion_state="NONE",
        compression_expansion_score=0,
        compression_expansion_label="NONE",
        expansion_timing_risk="LOW",
        expansion_quality_flags={},
    )
