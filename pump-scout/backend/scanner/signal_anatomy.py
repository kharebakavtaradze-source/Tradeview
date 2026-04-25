"""
Signal Anatomy — diagnostic layer for understanding why New Pump signals fire or don't.

Supplements new_pump_engine.analyze() with per-condition near-miss tracking,
G4 arm/consume history, and human-readable diagnosis.  Read-only: no engine changes.

Usage:
    from scanner.signal_anatomy import compute_anatomy
    report = compute_anatomy(bars)   # bars = list of {open,high,low,close,volume}
"""
from collections import Counter

from scanner.new_pump_engine import (
    _bar_primitives,
    _sig_L34, _sig_BLUE, _sig_FRI34,
    _update_g4, _sig_B2,
    _t_signals, _z_signals,
    _compute_rsi,
    _MAX_SETUP_AGE, _MAX_TRIGGER_AGE, _MAX_CONFIRM_AGE,
    analyze as _np_analyze,
)


# ── L34 near-miss helpers ─────────────────────────────────────────────────────

def _l34_conditions(p):
    return {
        "v_gt_v1":  p["v"] > p["v1"],   # volume increased
        "c_gt_c1":  p["c"] > p["c1"],   # close improved
        "c_le_h1":  p["c"] <= p["h1"],  # didn't breach prior high (quiet)
        "c_ge_o":   p["c"] >= p["o"],   # bull candle
    }


def _l34_near_miss(p):
    """Return near-miss dict if exactly 3/4 L34 conditions pass, else None."""
    conds = _l34_conditions(p)
    passing = [k for k, v in conds.items() if v]
    failing = [k for k, v in conds.items() if not v]
    if len(passing) == 3:
        return {"failed": failing[0], "passed": passing}
    return None


# ── Volume z-score (same formula as engine) ───────────────────────────────────

def _volume_z(volumes, i):
    win = volumes[max(0, i - 19): i + 1]
    if len(win) < 2:
        return None
    mid = sum(win) / len(win)
    var = sum((x - mid) ** 2 for x in win) / len(win)
    std = var ** 0.5
    return (volumes[i] - mid) / std if std > 0 else None


# ── Core anatomy pass ─────────────────────────────────────────────────────────

def compute_anatomy(bars):
    """
    Full signal anatomy for a bar series.

    Returns a dict with:
      final          — result of np_analyze(bars)
      bar_anatomy    — per-bar detail for the last 30 bars
      signal_analysis — per-signal fire/near-miss counts
      l34_near_misses_30 — near-miss records in last 30 bars
      diagnosis      — human-readable list of why signals didn't fire
      is_no_signal   — True when final result is NEW_PUMP_NONE (no fresh signals)
    """
    n = len(bars)
    if n < 20:
        return {"error": "insufficient_bars", "n_bars": n}

    closes  = [b["close"]  for b in bars]
    volumes = [b["volume"] for b in bars]
    rsi_s   = _compute_rsi(closes)

    final = _np_analyze(bars)

    # ── Bar-level pass ────────────────────────────────────────────────────────
    g_armed = False
    history = {}

    l34_fires   = []
    fri34_fires = []
    g4_fires    = []
    b2_fires    = []
    l34_nms     = []       # near-miss records
    g4_arm_events      = []
    g4_consumed_events = []
    bar_anatomy = []

    for i in range(1, n):
        p = _bar_primitives(bars, i)

        vz  = _volume_z(volumes, i)
        rr3 = None
        if i >= 2:
            rv = [rsi_s[j] for j in (i - 2, i - 1, i) if rsi_s[j] is not None]
            if len(rv) == 3:
                rr3 = max(rv) - min(rv)

        l34   = _sig_L34(p)
        blue  = _sig_BLUE(p, vz, rr3)
        fri34 = _sig_FRI34(l34, blue)
        t = _t_signals(p)
        z = _z_signals(p)

        prev_armed = g_armed
        g4, g_armed = _update_g4(g_armed, t, z)
        b2 = _sig_B2(i, t, z, history)

        # Track arm/consume events for G4 diagnosis
        if not prev_armed and g_armed:
            g4_arm_events.append({
                "bar_idx":  i,
                "bars_ago": n - 1 - i,
                "z_signals": [k for k, v in z.items() if v],
            })
        if prev_armed and not g_armed and not g4:
            g4_consumed_events.append({
                "bar_idx":    i,
                "bars_ago":   n - 1 - i,
                "consumed_by": [k for k, v in t.items() if v],
            })

        # Record fires
        bar_codes = set()
        if l34:   bar_codes.add("L34");   l34_fires.append(i)
        if fri34: bar_codes.add("FRI34"); fri34_fires.append(i)
        if g4:    bar_codes.add("G4");    g4_fires.append(i)
        if b2:    bar_codes.add("B2");    b2_fires.append(i)
        # Mirror _build_signal_history: T/Z signal codes must be in history so
        # subsequent bars' _sig_B2 can find prior-bar T3/T11/Z2G/Z6/_B2_BRANCH*.
        # Without this, B2 never fires in the bar-level pass even when the engine
        # final result reports it — causing inconsistent badges vs per-bar table.
        for name, fired in t.items():
            if fired: bar_codes.add(name)
        for name, fired in z.items():
            if fired: bar_codes.add(name)
        history[i] = frozenset(bar_codes)

        # L34 near-miss
        if not l34:
            nm = _l34_near_miss(p)
            if nm:
                l34_nms.append({"bar_idx": i, "bars_ago": n - 1 - i, **nm})

        # Store detail for last 30 bars
        if i >= n - 30:
            bar_anatomy.append({
                "bar_idx":   i,
                "bars_ago":  n - 1 - i,
                "l34":       l34,
                "fri34":     fri34,
                "blue":      blue,
                "g4":        g4,
                "b2":        b2,
                "g4_armed":  g_armed,
                "volume_z":  round(vz, 2) if vz is not None else None,
                "rsi_range3":round(rr3, 2) if rr3 is not None else None,
                "l34_near_miss":     _l34_near_miss(p),
                "l34_conditions":    _l34_conditions(p),
                "t_signals_fired":   [k for k, v in t.items() if v],
                "z_signals_fired":   [k for k, v in z.items() if v],
                "close":     round(p["c"], 4),
                "v_ratio":   round(p["v"] / p["v1"], 2) if p["v1"] else None,
            })

    last = n - 1

    # ── Freshness windows ─────────────────────────────────────────────────────
    l34_recent   = [b for b in l34_fires   if last - b <= _MAX_SETUP_AGE]
    fri34_recent = [b for b in fri34_fires if last - b <= _MAX_SETUP_AGE]
    g4_recent    = [b for b in g4_fires    if last - b <= _MAX_TRIGGER_AGE]
    b2_recent    = [b for b in b2_fires    if last - b <= _MAX_CONFIRM_AGE]
    l34_nms_30   = [x for x in l34_nms    if x["bars_ago"] <= 30]

    # ── Human-readable diagnosis ──────────────────────────────────────────────
    diagnosis = []

    # L34
    if not l34_fires:
        diagnosis.append(
            "L34 never fired in all bars — price action produces no quiet bullish accumulation bars. "
            "Likely cause: stock either never improves close while staying below prior high (too strong/gap), "
            "or consistently fails the bull-candle condition."
        )
    elif not l34_recent:
        age = last - l34_fires[-1]
        diagnosis.append(
            f"L34 last fired {age} bars ago (freshness window = {_MAX_SETUP_AGE} bars). "
            f"Signal exists historically ({len(l34_fires)} total fires) but is stale."
        )

    # L34 near-misses
    if l34_nms_30:
        block_counts = Counter(x["failed"] for x in l34_nms_30)
        top = block_counts.most_common(3)
        top_str = ", ".join(f"'{k}' ({v}x)" for k, v in top)
        diagnosis.append(
            f"L34 had {len(l34_nms_30)} near-misses in last 30 bars (3/4 conditions passed). "
            f"Most common blocking condition: {top_str}. "
            "Interpretation: "
            "'c_le_h1' block = stock too strong/gapping; "
            "'v_gt_v1' block = volume not increasing; "
            "'c_ge_o' block = bear candle; "
            "'c_gt_c1' block = close didn't improve."
        )

    # G4
    if not g4_fires:
        if not g4_arm_events:
            diagnosis.append(
                "G4 never armed in 200 bars — no Z10/Z11/Z12 bearish consolidation pattern seen. "
                "This stock may never have had a bearish rest before a bullish move."
            )
        else:
            consumed = len(g4_consumed_events)
            consumed_by = Counter(
                s for e in g4_consumed_events for s in e["consumed_by"]
            ).most_common(3)
            consumed_str = ", ".join(f"{k}({v}x)" for k, v in consumed_by)
            diagnosis.append(
                f"G4 armed {len(g4_arm_events)}x but never fired. "
                f"Armed state consumed {consumed}x by {consumed_str} before T4 fired. "
                "T1/T1G/T6 consume the arm without triggering G4."
            )
    elif not g4_recent:
        age = last - g4_fires[-1]
        diagnosis.append(
            f"G4 last fired {age} bars ago (freshness window = {_MAX_TRIGGER_AGE} bars). "
            f"Trigger exists historically ({len(g4_fires)} total) but is too stale to score."
        )

    # B2
    if not b2_fires:
        diagnosis.append(
            f"B2 (confirmation) never fired in {n} bars. "
            "B2 requires T4 with specific prior bar patterns (T3/Z2G/Z6/T11)."
        )
    elif not b2_recent:
        age = last - b2_fires[-1]
        diagnosis.append(
            f"B2 last fired {age} bars ago (freshness window = {_MAX_CONFIRM_AGE} bars)."
        )

    # FRI34 specific
    if l34_fires and not fri34_fires:
        diagnosis.append(
            "FRI34 never fired despite L34 firing. "
            "FRI34 requires L34 AND BLUE (volume_z ≥ 1.1 AND rsi_range3 ≤ 5.0). "
            "BLUE was likely blocked by low volume_z or high RSI choppiness."
        )

    if not diagnosis:
        diagnosis.append("All signals appear structurally present — no obvious blocking condition found.")

    return {
        "n_bars":       n,
        "final":        final,
        "bar_anatomy":  bar_anatomy,
        "signal_analysis": {
            "l34": {
                "fires_all":          len(l34_fires),
                "fires_recent":       len(l34_recent),
                "near_misses_30":     len(l34_nms_30),
                "last_fire_bars_ago": (last - l34_fires[-1]) if l34_fires else None,
            },
            "fri34": {
                "fires_all":          len(fri34_fires),
                "fires_recent":       len(fri34_recent),
                "last_fire_bars_ago": (last - fri34_fires[-1]) if fri34_fires else None,
            },
            "g4": {
                "fires_all":          len(g4_fires),
                "fires_recent":       len(g4_recent),
                "arm_events_all":     len(g4_arm_events),
                "consumed_events":    len(g4_consumed_events),
                "arm_detail":         g4_arm_events[-5:],
                "consumed_detail":    g4_consumed_events[-5:],
                "last_fire_bars_ago": (last - g4_fires[-1]) if g4_fires else None,
            },
            "b2": {
                "fires_all":          len(b2_fires),
                "fires_recent":       len(b2_recent),
                "last_fire_bars_ago": (last - b2_fires[-1]) if b2_fires else None,
            },
        },
        "l34_near_misses_30": l34_nms_30,
        "diagnosis":          diagnosis,
        "is_no_signal": not (l34_recent or fri34_recent or g4_recent or b2_recent),
    }
