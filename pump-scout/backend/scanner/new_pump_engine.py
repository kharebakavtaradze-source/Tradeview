"""
New Pump Engine
Thinks in order: Setup -> Trigger -> Confirmation
Components: L34, FRI34, G4, B2
"""

MIN_BODY_RATIO = 1.0
SETUP_STALENESS = 5

# Sequence validity windows
_MAX_SETUP_AGE      = 10   # setup must be within 10 bars to participate in any sequence
_MAX_TRIGGER_AGE    = 5    # G4 must be within 5 bars
_MAX_CONFIRM_AGE    = 5    # B2 must be within 5 bars
_MAX_SETUP_TRIG_GAP = 8    # setup → trigger gap (bars between them)
_MAX_TRIG_CONF_GAP  = 4    # trigger → confirm gap


# Shared predicates — single source of truth for ordering/gap checks
def _valid_setup_before_trigger(setup_age, g4_age):
    """Setup must exist, be within setup-age window, fire BEFORE G4, and gap within window."""
    return (setup_age is not None and g4_age is not None
            and setup_age <= _MAX_SETUP_AGE
            and setup_age > g4_age
            and (setup_age - g4_age) <= _MAX_SETUP_TRIG_GAP)


def _valid_confirm_after_trigger(b2_age, g4_age):
    """B2 must exist, be within confirm window, fire strictly AFTER G4, and gap within window."""
    return (b2_age is not None and g4_age is not None
            and b2_age <= _MAX_CONFIRM_AGE
            and b2_age < g4_age
            and (g4_age - b2_age) <= _MAX_TRIG_CONF_GAP)


# ---------------------------------------------------------------------------
# Rolling helpers
# ---------------------------------------------------------------------------

def _sma(values, period):
    if len(values) < period:
        return None
    return sum(values[-period:]) / period


def _std(values, period):
    if len(values) < period:
        return None
    window = values[-period:]
    mean = sum(window) / period
    variance = sum((x - mean) ** 2 for x in window) / period
    return variance ** 0.5


def _compute_rsi(closes, period=14):
    """Wilder RSI series, same length as closes. None where insufficient data."""
    rsi = [None] * len(closes)
    if len(closes) <= period:
        return rsi

    gains  = [max(closes[j] - closes[j - 1], 0) for j in range(1, len(closes))]
    losses = [max(closes[j - 1] - closes[j], 0) for j in range(1, len(closes))]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def _rsi(ag, al):
        return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)

    rsi[period] = _rsi(avg_gain, avg_loss)
    for j in range(period + 1, len(closes)):
        avg_gain = (avg_gain * (period - 1) + gains[j - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[j - 1]) / period
        rsi[j] = _rsi(avg_gain, avg_loss)

    return rsi


def _compute_ema(values, period):
    """EMA series, same length as values. None where insufficient data."""
    result = [None] * len(values)
    if len(values) < period:
        return result
    k = 2.0 / (period + 1)
    result[period - 1] = sum(values[:period]) / period
    for j in range(period, len(values)):
        result[j] = values[j] * k + result[j - 1] * (1 - k)
    return result


# ---------------------------------------------------------------------------
# Bar primitives
# ---------------------------------------------------------------------------

def _bar_primitives(bars, i):
    cb = bars[i];  pb = bars[i - 1]

    o  = cb["open"];  h  = cb["high"];  l  = cb["low"];  c  = cb["close"];  v  = cb["volume"]
    o1 = pb["open"];  h1 = pb["high"];  l1 = pb["low"];  c1 = pb["close"];  v1 = pb["volume"]

    body  = abs(c - o);   pbody = abs(c1 - o1)
    cTop  = max(o, c);    cBot  = min(o, c)
    pTop  = max(o1, c1);  pBot  = min(o1, c1)

    isBull = c > o;  isBear = c < o;  isDoji = c == o
    p1Bull = c1 > o1;  p1Bear = c1 <= o1

    engOk = (pbody > 0
             and body / pbody >= MIN_BODY_RATIO
             and cTop >= pTop
             and pBot >= cBot)
    insOk = cTop <= pTop and cBot >= pBot

    return dict(
        o=o, h=h, l=l, c=c, v=v,
        o1=o1, h1=h1, l1=l1, c1=c1, v1=v1,
        body=body, pbody=pbody,
        cTop=cTop, cBot=cBot, pTop=pTop, pBot=pBot,
        isBull=isBull, isBear=isBear, isDoji=isDoji,
        p1Bull=p1Bull, p1Bear=p1Bear,
        engOk=engOk, insOk=insOk,
    )


# ---------------------------------------------------------------------------
# Setup signals
# ---------------------------------------------------------------------------

def _sig_L34(p):
    """Quiet bullish setup: rising participation, price improves but not yet breaking prev high."""
    return (p["v"] > p["v1"]
            and p["c"] > p["c1"]
            and p["c"] <= p["h1"]
            and p["c"] >= p["o"])


def _sig_BLUE(p, volume_z, rsi_range3):
    """Volume spike without chaotic RSI expansion."""
    if volume_z is None or rsi_range3 is None:
        return False
    return volume_z >= 1.1 and rsi_range3 <= 5.0


def _sig_FRI34(l34, blue):
    """Stronger validated setup: BLUE + L34."""
    return blue and l34


# ---------------------------------------------------------------------------
# T-signals (bullish)
# ---------------------------------------------------------------------------

def _t_signals(p):
    o, c, o1, c1 = p["o"], p["c"], p["o1"], p["c1"]
    bull = p["isBull"];  p1bull = p["p1Bull"];  p1bear = p["p1Bear"]
    eng  = p["engOk"];   ins    = p["insOk"]

    return dict(
        T1G = p1bear and o > c1  and o > o1  and c > o1 and bull,
        T1  = p1bear and o >= c1 and o1 >= o and c > o1 and bull,
        T2G = p1bull and o >= o1 and o > c1  and c > c1 and bull,
        T2  = p1bull and o >= o1 and o <= c1 and c > c1 and bull,
        T3  = p1bear and bull and o < o1 and o < c1 and c < o1 and c > c1,
        T4  = p1bear and bull and eng,
        T6  = p1bull and bull and eng,
        T10 = p1bull and bull and ins,
        T11 = p1bull and bull and o < o1 and c >= o1 and c < c1,
    )


# ---------------------------------------------------------------------------
# Z-signals (bearish)
# ---------------------------------------------------------------------------

def _z_signals(p):
    o, c, o1, c1 = p["o"], p["c"], p["o1"], p["c1"]
    bear = p["isBear"];  p1bear = p["p1Bear"];  p1bull = p["p1Bull"]
    eng  = p["engOk"];   ins    = p["insOk"]

    return dict(
        Z2G = p1bear and o <= o1 and o < c1 and c < c1 and bear,
        Z6  = p1bear and bear and eng,
        Z10 = p1bear and bear and ins,
        Z11 = p1bear and bear and o > o1 and (c > c1 or c > o1),
        Z12 = p1bull and o <= o1 and bear,
    )


# ---------------------------------------------------------------------------
# G4 state machine
# ---------------------------------------------------------------------------

def _update_g4(g_armed, t, z):
    """
    Arm on Z10|Z11|Z12. Fire G4 on first T4 while armed.
    T1, T1G, T4, T6 all consume the armed state.
    Returns (g4_fired, new_g_armed).
    """
    if z["Z10"] or z["Z11"] or z["Z12"]:
        g_armed = True

    g4 = False
    if g_armed:
        if t["T4"]:
            g4 = True;  g_armed = False
        elif t["T1"] or t["T1G"] or t["T6"]:
            g_armed = False

    return g4, g_armed


# ---------------------------------------------------------------------------
# B2 confirmation
# ---------------------------------------------------------------------------

_B2_BRANCH1 = {"T1", "T1G", "T2", "T2G", "T3", "T4", "T6", "T10", "T11"}
_B2_BRANCH2 = {"T1", "T1G", "T2G", "T3", "T4", "T6", "T10", "T11"}


def _sig_B2(i, t, z, history):
    def h(idx):
        return history.get(idx, frozenset())

    b2 = False
    if t["T4"]:
        if h(i - 2) & _B2_BRANCH1:          b2 = True
        if "T3"  in h(i - 3):               b2 = True
        if "T3"  in h(i - 6):               b2 = True
        if "Z2G" in h(i - 1):               b2 = True
        if "Z6"  in h(i - 1) or "Z6" in h(i - 2): b2 = True
    if t["T6"]:
        if h(i - 1) & _B2_BRANCH2:          b2 = True
        if "T11" in h(i - 2):               b2 = True

    return b2


# ---------------------------------------------------------------------------
# Core inner loop (shared by run() and analyze())
# ---------------------------------------------------------------------------

def _build_signal_history(bars):
    """
    Run bar-by-bar signal detection.
    Returns dict with per-bar signals and raw component bar lists.
    """
    n = len(bars)
    closes  = [b["close"]  for b in bars]
    volumes = [b["volume"] for b in bars]
    rsi_series = _compute_rsi(closes)

    signals    = []
    history    = {}
    g_armed    = False
    setup_bar  = None;  setup_type  = None
    trigger_bar = None

    l34_bars   = []
    fri34_bars = []
    g4_bars    = []
    b2_bars    = []

    for i in range(1, n):
        p = _bar_primitives(bars, i)

        # Volume stats for BLUE
        vol_win  = volumes[max(0, i - 19): i + 1]
        vol_mid  = _sma(vol_win, 20)
        vol_std  = _std(vol_win, 20)
        volume_z = None
        if vol_mid is not None and vol_std is not None and vol_std > 0:
            volume_z = (p["v"] - vol_mid) / vol_std

        # RSI range over last 3 bars
        rsi_range3 = None
        if i >= 2:
            rv = [rsi_series[j] for j in (i - 2, i - 1, i) if rsi_series[j] is not None]
            if len(rv) == 3:
                rsi_range3 = max(rv) - min(rv)

        t = _t_signals(p)
        z = _z_signals(p)

        l34   = _sig_L34(p)
        blue  = _sig_BLUE(p, volume_z, rsi_range3)
        fri34 = _sig_FRI34(l34, blue)

        g4, g_armed = _update_g4(g_armed, t, z)
        b2 = _sig_B2(i, t, z, history)

        # Record bar codes
        bar_codes = set()
        if l34:   bar_codes.add("L34");   l34_bars.append(i)
        if fri34: bar_codes.add("FRI34"); fri34_bars.append(i)
        for name, fired in t.items():
            if fired: bar_codes.add(name)
        for name, fired in z.items():
            if fired: bar_codes.add(name)
        if g4: bar_codes.add("G4"); g4_bars.append(i)
        if b2: bar_codes.add("B2"); b2_bars.append(i)
        history[i] = frozenset(bar_codes)

        # Setup / trigger tracking
        if fri34:
            setup_bar = i;  setup_type = "FRI34";  trigger_bar = None
        elif l34:
            setup_bar = i;  setup_type = "L34";    trigger_bar = None

        setup_age   = (i - setup_bar)   if setup_bar   is not None else None
        setup_fresh = setup_age is not None and 1 <= setup_age <= SETUP_STALENESS

        if g4 and setup_fresh:
            trigger_bar = i

        trigger_age   = (i - trigger_bar) if trigger_bar is not None else None
        trigger_fresh = trigger_age is not None and 1 <= trigger_age <= 3

        # Emit per-bar signal
        active = []
        if fri34:  active.append("FRI34")
        elif l34:  active.append("L34")
        if g4:     active.append("G4")
        if b2:     active.append("B2")

        has_setup   = l34 or fri34
        has_trigger = g4
        has_confirm = b2

        if has_setup and has_trigger and has_confirm:
            seq = f"{setup_type}->G4->B2";  strength = "strong"
            reason = f"full sequence: {seq}"
        elif has_setup and has_trigger:
            seq = f"{setup_type}->G4";  strength = "moderate"
            reason = f"setup+trigger: {seq}"
        elif has_trigger and has_confirm:
            lbl = setup_type if setup_fresh else None
            seq = f"{lbl}->G4->B2" if lbl else "G4->B2"
            strength = "strong" if lbl else "moderate"
            reason = f"trigger+confirmation: {seq}"
        elif has_trigger:
            seq = f"{setup_type}->G4" if setup_fresh else "G4"
            strength = "moderate" if setup_fresh else "weak"
            reason = f"trigger: {seq}"
        elif has_confirm and trigger_fresh:
            seq = "->B2";  strength = "moderate"
            reason = "confirmation after recent trigger"
        elif has_setup:
            seq = setup_type;  strength = "weak"
            reason = f"setup only: {seq}"
        else:
            continue

        signals.append(dict(index=i, sequence=seq, strength=strength,
                            components=active, reason=reason))

    return dict(
        signals=signals,
        l34_bars=l34_bars, fri34_bars=fri34_bars,
        g4_bars=g4_bars,   b2_bars=b2_bars,
        history=history,
        n=n,
    )


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------

def _setup_score(age_l34, age_fri34, count_l34_w, count_fri34_w):
    score = 0
    # FRI34 (stronger) takes priority in overlapping cases
    if age_fri34 == 0:
        score += 16
    elif age_fri34 is not None and age_fri34 <= 3:
        score += 12
    elif age_fri34 is not None and age_fri34 <= _MAX_SETUP_AGE:
        score += 5           # still label-valid but stale — small contribution
    if count_fri34_w >= 2:
        score += 6

    # L34 boosted — replay shows SETUP_ONLY_L34 is the best-performing sequence
    if age_l34 == 0:
        score += 14
    elif age_l34 is not None and age_l34 <= 3:
        score += 11
    elif age_l34 is not None and age_l34 <= _MAX_SETUP_AGE:
        score += 4           # still label-valid but stale — small contribution
    if count_l34_w >= 2:
        score += 6

    return score


def _trigger_score(age_g4, age_l34, age_fri34):
    score = 0
    if age_g4 is None:
        return 0

    if age_g4 == 0:
        score += 16
    elif age_g4 <= 3:
        score += 12

    # Setup existed within 5 bars before G4
    best_setup_age = min(
        a for a in (age_l34, age_fri34) if a is not None
    ) if (age_l34 is not None or age_fri34 is not None) else None

    if best_setup_age is not None and best_setup_age <= 5:
        score += 6
        if age_fri34 is not None and age_fri34 <= 5:
            score += 5   # was 3 — replay shows TRIGGER_AFTER_FRI34 avg +2.3%

    return score


def _confirm_score(age_b2, age_g4, age_l34, age_fri34):
    score = 0
    if age_b2 is None:
        return 0

    # Confirm contribution reduced — replay shows CONFIRM_AFTER_G4 avg -3.7%, FULL_* avg -1.5 to -1.9%
    if age_b2 == 0:
        score += 6
    elif age_b2 <= 3:
        score += 5

    # B2 strictly after G4 within confirm gap — halved bonus
    if (age_g4 is not None
            and age_b2 < age_g4
            and (age_g4 - age_b2) <= _MAX_TRIG_CONF_GAP):
        score += 3

    # Note: isolated-B2 penalty lives in _modifier_score (#9) to keep single source of truth.
    return score


def _sequence_bonus(age_l34, age_fri34, age_g4, age_b2):
    """Bonus only for fresh, ordered sequences within gap windows."""
    if age_g4 is None or age_g4 > _MAX_TRIGGER_AGE:
        return 0

    good_fri34 = _valid_setup_before_trigger(age_fri34, age_g4)
    good_l34   = _valid_setup_before_trigger(age_l34,   age_g4)
    good_b2    = _valid_confirm_after_trigger(age_b2,   age_g4)

    # Full-sequence bonus stays low — replay FULL_* both negative
    # TRIGGER_AFTER_L34 strongly upweighted — Replay 14: strongest meaningful bucket
    # TRIGGER_AFTER_FRI34 mildly upweighted — positive but smaller sample
    if good_fri34 and good_b2:
        return 4
    if good_l34 and good_b2:
        return 3
    if good_fri34:
        return 10            # TRIGGER_AFTER_FRI34 — positive replay evidence
    if good_l34:
        return 13            # TRIGGER_AFTER_L34 — strongest replay bucket (was 7)
    return 0


def _progression_adjustment(seq_label: str, base_quality_score: int = 50) -> int:
    """
    Per-sequence score adjustment, now quality-conditional for setup-only sequences.
    SETUP_ONLY_L34 is no longer blindly penalized — MOBX-type 4x pumps have strong
    base quality with no G4 yet.
    """
    if seq_label == "ISOLATED_G4":
        return -8   # Replay 14: weak, no setup context
    if seq_label == "NONE":
        return -5   # no progression — most destructive
    if seq_label == "ISOLATED_B2":
        return -3   # orphaned confirmation without trigger context
    if seq_label == "SETUP_ONLY_FRI34":
        # Structure stalled despite FRI34 — severity depends on base quality
        if base_quality_score >= 60:
            return -1
        if base_quality_score >= 40:
            return -4
        return -6
    if seq_label == "SETUP_ONLY_L34":
        # MOBX-type: strong base can still be a real 4x setup in pre-trigger phase
        if base_quality_score >= 60:
            return +4   # reward: clean early setup, watchlist candidate
        if base_quality_score >= 40:
            return 0    # neutral: wait for trigger
        return -4       # weak base = likely failed setup
    return 0


# ---------------------------------------------------------------------------
# Phase 3 — Base Quality + Sustain Proxy + Fake Trigger Filter
# ---------------------------------------------------------------------------

def _compute_base_quality(bars, last, bull_stack_len, days_above_ema50,
                           ema50_reclaim_count, avg_ema_spread, volumes):
    """
    Base quality score 0–100.  Measures how clean/structured the pre-breakout base is.
    Uses only live-safe pre-breakout features — zero outcome leakage.

    Key research calibration (Run 52):
      4x_pump  median: bull_stack_days=14, avg_ema_spread=35.7%, days_above_ema50=19
      false_pos median: bull_stack_days=4,  avg_ema_spread=59.3%, days_above_ema50=11
    """
    score = 0

    # 1. Bull stack persistence (up to 28 pts)
    if bull_stack_len >= 15:   score += 28
    elif bull_stack_len >= 10: score += 22
    elif bull_stack_len >= 5:  score += 14
    elif bull_stack_len >= 2:  score += 7

    # 2. EMA50 proximity persistence: 4x med=19d, normal=14d (up to 18 pts)
    if days_above_ema50 >= 18:   score += 18
    elif days_above_ema50 >= 14: score += 14
    elif days_above_ema50 >= 10: score += 10
    elif days_above_ema50 >= 6:  score += 5

    # 3. EMA ribbon spread: tight=strong, wide=extended/choppy (up to 15 pts)
    if avg_ema_spread is not None:
        if avg_ema_spread < 15:    score += 15
        elif avg_ema_spread < 25:  score += 12
        elif avg_ema_spread < 40:  score += 8
        elif avg_ema_spread < 55:  score += 2
        elif avg_ema_spread >= 60: score -= 8   # false_positive median territory

    # 4. EMA50 reclaim quality: sweet spot=2, ≥4=choppy (up to 8 pts)
    if ema50_reclaim_count == 0:
        score += 5   # clean hold
    elif ema50_reclaim_count == 2:
        score += 8   # bounce-recovery pattern
    elif ema50_reclaim_count == 1:
        score += 6
    elif ema50_reclaim_count >= 4:
        score -= 4   # choppy: false-positive territory

    # 5. Volume dry-up proxy: min vol last 5 bars vs 20-bar avg (up to 15 pts)
    if last >= 19 and len(volumes) > last:
        avg_v20 = sum(volumes[max(0, last - 19): last + 1]) / 20
        min_v5 = min(volumes[max(0, last - 4): last + 1])
        dryup_ratio = min_v5 / avg_v20 if avg_v20 > 0 else 1.0
        if dryup_ratio < 0.35:   score += 15
        elif dryup_ratio < 0.55: score += 10
        elif dryup_ratio < 0.75: score += 5

    # 6. Price compression: 5-bar range / 20-bar range (up to 12 pts)
    if last >= 19:
        hi5  = max(b["high"] for b in bars[max(0, last - 4):  last + 1])
        lo5  = min(b["low"]  for b in bars[max(0, last - 4):  last + 1])
        hi20 = max(b["high"] for b in bars[max(0, last - 19): last + 1])
        lo20 = min(b["low"]  for b in bars[max(0, last - 19): last + 1])
        range20 = hi20 - lo20
        if range20 > 0:
            compression = (hi5 - lo5) / range20
            if compression < 0.25:   score += 12
            elif compression < 0.40: score += 8
            elif compression < 0.55: score += 4

    return max(0, min(100, score))


def _compute_sustain_proxy(base_quality_score, bull_stack_len, days_above_ema50,
                            avg_ema_spread, volumes, bars, last):
    """
    Sustain proxy score 0–100 + profile label (LOW/MEDIUM/HIGH).
    Estimates whether setup conditions historically lead to sustained moves.
    Does NOT use days_from_breakout_to_peak or any outcome features.
    """
    score = 0

    # Base quality anchor (40% weight — sustain adds incremental signal)
    score += int(base_quality_score * 0.40)

    # Extended low-volume duration: coiled energy proxy (up to 20 pts)
    if last >= 14 and len(volumes) > last:
        avg_v20 = sum(volumes[max(0, last - 19): last + 1]) / min(20, last + 1)
        low_vol_days = sum(
            1 for j in range(max(0, last - 9), last + 1)
            if avg_v20 > 0 and volumes[j] < 0.65 * avg_v20
        )
        if low_vol_days >= 7:   score += 20
        elif low_vol_days >= 5: score += 14
        elif low_vol_days >= 3: score += 8
        elif low_vol_days >= 1: score += 3

    # Long bull stack duration: strongest sustain predictor (up to 15 pts)
    if bull_stack_len >= 20:   score += 15
    elif bull_stack_len >= 12: score += 10
    elif bull_stack_len >= 6:  score += 5

    # Controlled intraday volatility = tight base, not chaotic (up to 10 pts)
    if last >= 9:
        ranges = [
            (b["high"] - b["low"]) / b["close"] * 100
            for b in bars[max(0, last - 9): last + 1]
            if b["close"] > 0
        ]
        if ranges:
            avg_range_pct = sum(ranges) / len(ranges)
            if avg_range_pct < 2.0:   score += 10
            elif avg_range_pct < 3.5: score += 6
            elif avg_range_pct < 5.0: score += 2
            elif avg_range_pct > 8.0: score -= 5   # chaotic base

    # Tight EMA spread = expansion room (up to 10 pts)
    if avg_ema_spread is not None:
        if avg_ema_spread < 20:    score += 10
        elif avg_ema_spread < 35:  score += 5
        elif avg_ema_spread > 60:  score -= 8

    score = max(0, min(100, score))
    profile = "HIGH" if score >= 65 else ("MEDIUM" if score >= 40 else "LOW")
    return score, profile


def _fake_trigger_risk(seq_lbl, base_quality_score, avg_ema_spread, volume_z):
    """
    Assess fake trigger risk for trigger / full / confirm sequences.
    Catches QNCX / WNW / ELPW / SPHL-type false positives where structure
    looks complete but base quality is poor.  Returns "LOW"/"MEDIUM"/"HIGH".
    """
    FT_SEQS = (
        "TRIGGER_AFTER_L34", "TRIGGER_AFTER_FRI34",
        "FULL_L34_G4_B2",    "FULL_FRI34_G4_B2",
        "CONFIRM_AFTER_G4",
    )
    if seq_lbl not in FT_SEQS:
        return "LOW"

    risk = 0
    if base_quality_score < 25:    risk += 3
    elif base_quality_score < 40:  risk += 2
    elif base_quality_score < 55:  risk += 1

    if avg_ema_spread is not None:
        if avg_ema_spread > 65:   risk += 2
        elif avg_ema_spread > 55: risk += 1

    if volume_z is not None and volume_z > 4.0:
        risk += 2   # chaotic spike = suspicious trigger

    # FULL sequences with weak base are the most dangerous false positives
    if seq_lbl in ("FULL_L34_G4_B2", "FULL_FRI34_G4_B2") and base_quality_score < 40:
        risk += 1

    if risk >= 4:   return "HIGH"
    elif risk >= 2: return "MEDIUM"
    return "LOW"


def _fake_trigger_penalty(ftr_val: str, seq_lbl: str = None) -> int:
    """Sequence-aware penalty. FULL_* + HIGH risk is extra penalized."""
    base = {"HIGH": -10, "MEDIUM": -5, "LOW": 0}.get(ftr_val, 0)
    if ftr_val == "HIGH" and seq_lbl in ("FULL_L34_G4_B2", "FULL_FRI34_G4_B2"):
        base -= 5
    return base


def _pre_trigger_gate(state: str, bq_score: int) -> tuple:
    """
    PRE_TRIGGER noise filter. Returns (weak_flag, score_penalty).
    PRE_TRIGGER alone isn't bullish — require base quality ≥ 45 or apply penalty.
    """
    if state == "PRE_TRIGGER":
        if bq_score < 30:
            return True, -12
        if bq_score < 45:
            return True, -8
    return False, 0


def _compute_base_flags(bq_score, avg_ema_spread, bars, last, volumes) -> dict:
    """
    Explainable base-quality diagnostic flags.  Does NOT affect score —
    scoring is done via _compute_base_quality + modifiers.  Used for UI and
    as inputs to label capping.
    """
    flags = {}

    if avg_ema_spread is not None and avg_ema_spread >= 55:
        flags["wide_ema_spread"] = True

    # Volume dry-up: if min_5 / avg_20 ratio is high, there was no dryup.
    if last >= 19 and len(volumes) > last:
        avg_v20 = sum(volumes[max(0, last - 19): last + 1]) / 20
        if avg_v20 > 0:
            dryup_ratio = min(volumes[max(0, last - 4): last + 1]) / avg_v20
            if dryup_ratio >= 0.75:
                flags["low_dryup"] = True

    # Compression: 5-bar range / 20-bar range. High value = no compression.
    if last >= 19:
        hi5  = max(b["high"] for b in bars[max(0, last - 4):  last + 1])
        lo5  = min(b["low"]  for b in bars[max(0, last - 4):  last + 1])
        hi20 = max(b["high"] for b in bars[max(0, last - 19): last + 1])
        lo20 = min(b["low"]  for b in bars[max(0, last - 19): last + 1])
        r20 = hi20 - lo20
        if r20 > 0 and (hi5 - lo5) / r20 >= 0.60:
            flags["low_compression"] = True

    # Chaotic base: avg true-range / close over last 10 bars.
    if last >= 10:
        trs = []
        for i in range(max(1, last - 9), last + 1):
            h, l, pc = bars[i]["high"], bars[i]["low"], bars[i - 1]["close"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        c = bars[last]["close"]
        if trs and c > 0:
            atr_pct = (sum(trs) / len(trs)) / c * 100
            if atr_pct >= 7.0:
                flags["chaotic_base"] = True

    return flags


def _cap_label(label: str, weak_pre_trigger_base: bool, ftr: str, bq_score: int) -> str:
    """
    Label cap gate.  Prevents high labels from emerging when the underlying
    quality evidence contradicts the sequence.
    """
    ORDER = ["NEW_PUMP_NONE", "NEW_PUMP_WEAK", "NEW_PUMP_TRIGGER_ONLY",
             "NEW_PUMP_SETUP", "NEW_PUMP_STRONG", "NEW_PUMP_FIRE"]
    rank = ORDER.index(label) if label in ORDER else 0

    # weak PRE_TRIGGER base: cap to SETUP
    if weak_pre_trigger_base and rank > 3:
        return "NEW_PUMP_SETUP"
    # HIGH fake trigger risk: cap to SETUP
    if ftr == "HIGH" and rank > 3:
        return "NEW_PUMP_SETUP"
    # very poor base: never allow FIRE regardless of sequence
    if bq_score < 35 and rank > 4:
        return "NEW_PUMP_STRONG"
    return label


def _quality_score_modifier(base_quality_score: int, state: str) -> int:
    """
    Translate base quality into a score delta, conditioned on state.
    Allows strong-base PRE_TRIGGER/TRIGGERED to rank higher,
    and low-base TRIGGERED to be downgraded.
    """
    mod = 0
    if state in ("PRE_TRIGGER", "TRIGGERED"):
        if base_quality_score >= 70:   mod += 5
        elif base_quality_score >= 55: mod += 2
        elif base_quality_score < 30:  mod -= 5
        elif base_quality_score < 45:  mod -= 2
    return mod


def _modifier_score(age_l34, age_fri34, age_g4, age_b2,
                    ema20, ema50, ema200, close, volume_z, body_ratio, dv_ratio,
                    bull_stack_len=0, days_above_ema50=0, ema50_reclaim_count=0,
                    avg_ema_spread=None):
    mod = 0
    ema20_ok  = ema20  is not None
    ema50_ok  = ema50  is not None
    ema200_ok = ema200 is not None

    # --- Positive modifiers ---

    # 1. Bull stack presence + duration (up to +12)
    # Research: bull_stack_days_pre median 14 for 4x_pump vs 8 for false_positive.
    # Duration bonus separates sustained stacks from brief crossovers.
    if ema20_ok and ema50_ok and ema200_ok and ema20 > ema50 > ema200:
        mod += 8
        if bull_stack_len >= 10:
            mod += 4   # 4x_pump territory (median=14 days)
        elif bull_stack_len >= 5:
            mod += 2
    elif ema20_ok and ema50_ok and ema20 > ema50:
        mod += 4
    elif ema20_ok and ema200_ok and ema20 > ema200:
        mod += 2

    # 2. Ribbon quality: EMA50 proximity + reclaim count (up to +4)
    # Research: days_above_ema50 median 19 for 4x_pump vs 14 for normal_winner.
    # ema50_reclaim_count sweet spot = 2 (4x_pump); ≥4 = choppy (false_positive territory).
    rq = 0
    if days_above_ema50 >= 15:
        rq += 3
    elif days_above_ema50 >= 10:
        rq += 2
    elif days_above_ema50 >= 5:
        rq += 1
    if ema50_reclaim_count == 2:
        rq += 1   # persistent but recovers — 4x_pump sweet spot
    elif ema50_reclaim_count >= 4:
        rq -= 1   # choppy pattern more common in false_positives
    mod += rq

    # 3. Quality dollar-volume context (up to +5)
    if dv_ratio is not None:
        if dv_ratio >= 2.0:
            mod += 5
        elif dv_ratio >= 1.3:
            mod += 3
        elif dv_ratio >= 0.8:
            mod += 1

    # 4. Moderate abnormal-volume context (up to +3)
    if volume_z is not None and 1.1 <= volume_z <= 2.5:
        mod += 3
    elif volume_z is not None and 2.5 < volume_z <= 3.5:
        mod += 1

    # 5. Body expansion — deweighted per research (avg_body_pct gap <0.03, low discriminant)
    if body_ratio is not None and 1.2 <= body_ratio <= 2.5:
        mod += 1   # token tie-breaker only; was +4

    # --- Negative modifiers ---

    # 6. Ultra-extreme anomaly spike (up to -8)
    if volume_z is not None:
        if volume_z > 4.0:
            mod -= 8
        elif volume_z > 3.5:
            mod -= 5
        elif volume_z > 3.0:
            mod -= 3

    # 7. EMA ribbon spread — recalibrated from Run #50 research
    # 4x_pump avg_ema_spread_pre median=35.7%, false_positive=59.3%
    # Tight ribbon (<20%) = reward; >60% = false_positive territory
    if avg_ema_spread is not None:
        if avg_ema_spread < 20:
            mod += 3   # tight ribbon: superior squeeze persistence
        elif avg_ema_spread < 40:
            pass       # neutral — normal 4x_pump range
        elif avg_ema_spread > 60:
            mod -= 6   # false_positive median territory
        elif avg_ema_spread > 50:
            mod -= 3
        elif avg_ema_spread > 45:
            mod -= 1
    elif ema20_ok and ema200_ok and ema200 > 0:
        spread_pct = (ema20 - ema200) / ema200 * 100
        if spread_pct < 20:
            mod += 3
        elif spread_pct > 60:
            mod -= 6
        elif spread_pct > 50:
            mod -= 3
        elif spread_pct > 45:
            mod -= 1

    # 8. Overly extended above EMA200 (up to -4)
    if ema200_ok and ema200 > 0:
        ext = close / ema200
        if ext > 1.5:
            mod -= 4
        elif ext > 1.3:
            mod -= 2

    # 9. Stale setup penalty (up to -4)
    best_setup_age = min(
        a for a in (age_l34, age_fri34) if a is not None
    ) if (age_l34 is not None or age_fri34 is not None) else None

    if best_setup_age is None:
        mod -= 4
    elif best_setup_age > 8:
        mod -= 4
    elif best_setup_age > 5:
        mod -= 2
    elif best_setup_age > 3:
        mod -= 1

    # 10. Isolated B2 penalty (up to -6) — single source of truth
    if age_b2 is not None:
        has_g4_context    = age_g4    is not None and age_g4    <= 5
        has_setup_context = best_setup_age is not None and best_setup_age <= 10
        if not has_g4_context and not has_setup_context:
            mod -= 6
        elif not has_g4_context:
            mod -= 3

    return mod


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------

def _sequence_label(age_l34, age_fri34, age_g4, age_b2):
    has_l34   = age_l34   is not None
    has_fri34 = age_fri34 is not None
    has_g4    = age_g4    is not None
    has_b2    = age_b2    is not None

    # Freshness gates — component must be recent enough to participate
    fresh_fri34 = has_fri34 and age_fri34 <= _MAX_SETUP_AGE
    fresh_l34   = has_l34   and age_l34   <= _MAX_SETUP_AGE
    fresh_g4    = has_g4    and age_g4    <= _MAX_TRIGGER_AGE
    fresh_b2    = has_b2    and age_b2    <= _MAX_CONFIRM_AGE

    good_fri34 = _valid_setup_before_trigger(age_fri34, age_g4)
    good_l34   = _valid_setup_before_trigger(age_l34,   age_g4)
    good_b2    = _valid_confirm_after_trigger(age_b2,   age_g4)

    # FULL sequences — all three freshness gates + ordering + gap required
    if fresh_fri34 and fresh_g4 and fresh_b2 and good_fri34 and good_b2:
        return "FULL_FRI34_G4_B2"

    if fresh_l34 and fresh_g4 and fresh_b2 and good_l34 and good_b2:
        return "FULL_L34_G4_B2"

    # Confirm after G4 — fresh G4 + fresh B2 + strict ordering + tight gap
    if fresh_g4 and fresh_b2 and good_b2:
        return "CONFIRM_AFTER_G4"

    # Trigger after setup — fresh setup + G4 present + gap ok
    if has_g4 and fresh_fri34 and good_fri34:
        return "TRIGGER_AFTER_FRI34"

    if has_g4 and fresh_l34 and good_l34:
        return "TRIGGER_AFTER_L34"

    # Isolated G4 — no fresh setup within window
    if has_g4 and not fresh_fri34 and not fresh_l34:
        return "ISOLATED_G4"

    # Setup only
    if fresh_fri34 and not fresh_g4:
        return "SETUP_ONLY_FRI34"

    if fresh_l34 and not fresh_g4:
        return "SETUP_ONLY_L34"

    # Isolated B2
    if has_b2 and not fresh_g4:
        return "ISOLATED_B2"

    return "NONE"


def _final_label(score):
    # Thresholds recalibrated after Replay Run #7:
    # — lowered across the board to rescue good cases from NONE (+2.6% avg leaked there)
    # — FIRE loosened slightly (single-case sample, old threshold was unreachable)
    # — STRONG kept meaningful (avg +2.4% in replay, best reliable label)
    if score >= 62:  return "NEW_PUMP_FIRE"       # was 70
    if score >= 46:  return "NEW_PUMP_STRONG"     # was 55
    if score >= 34:  return "NEW_PUMP_SETUP"      # was 40
    if score >= 22:  return "NEW_PUMP_TRIGGER_ONLY"  # was 25
    if score >=  8:  return "NEW_PUMP_WEAK"       # was 10
    return "NEW_PUMP_NONE"


def _empty_analysis():
    return dict(
        has_l34=False, has_fri34=False, has_g4=False, has_b2=False,
        age_l34=None, age_fri34=None, age_g4=None, age_b2=None,
        new_pump_setup_score=0,
        new_pump_trigger_score=0,
        new_pump_confirm_score=0,
        new_pump_modifier_score=0,
        new_pump_score=0,
        new_pump_sequence_label="NONE",
        new_pump_label="NEW_PUMP_NONE",
        state="NEUTRAL",
        engine_path="structure",
        missing_piece="structure_not_present",
        main_risk="no_progression",
        impulse_score=0,
        impulse_label=None,
        volume_z=None,
        ema_extended=None,
        base_quality_score=0,
        sustain_proxy_score=0,
        sustain_profile="LOW",
        fake_trigger_risk="LOW",
        quality_flags={},
        compression_expansion_state="NONE",
        compression_expansion_score=0,
        compression_expansion_label="NONE",
        expansion_timing_risk="LOW",
        expansion_quality_flags={},
        decision="AVOID",
        decision_reason="no data",
        decision_flags=[],
    )



# ---------------------------------------------------------------------------
# Phase 1: State classifier
# ---------------------------------------------------------------------------

_CONFIRMED_SEQS = {"FULL_FRI34_G4_B2", "FULL_L34_G4_B2", "CONFIRM_AFTER_G4"}
_TRIGGERED_SEQS = {"TRIGGER_AFTER_L34", "TRIGGER_AFTER_FRI34"}
_SETUP_SEQS     = {"SETUP_ONLY_L34", "SETUP_ONLY_FRI34"}


def classify_state(ctx: dict) -> str:
    """
    Derive market state from analyze() context.
    ctx must include: new_pump_sequence_label, has_*/age_* fields,
    volume_z, ema_extended.

    States (priority order):
      CONFIRMED     — full G4+B2 progression completed
      TRIGGERED     — valid setup→trigger sequence (WSHP-type: PRE_TRIGGER)
      PRE_TRIGGER   — fresh setup, trigger not yet fired
      OVEREXTENDED  — price extended above EMA200, trigger absent/stale (TORO-type)
      IMPULSE       — explosive volume/price without NP structure (FRMM-type)
      FAILED_SETUP  — L34 historically present, not progressing (AGPU-type)
      BROKEN_SETUP  — all signals stale, structure decayed
      NEUTRAL       — none of the above apply
    """
    seq      = ctx.get("new_pump_sequence_label", "NONE")
    age_l34  = ctx.get("age_l34")
    age_fri34= ctx.get("age_fri34")
    age_g4   = ctx.get("age_g4")
    has_l34  = ctx.get("has_l34", False)
    has_fri34= ctx.get("has_fri34", False)
    has_g4   = ctx.get("has_g4", False)
    volume_z = ctx.get("volume_z")
    ema_ext  = ctx.get("ema_extended") or 1.0

    fresh_g4    = has_g4 and age_g4 is not None and age_g4 <= _MAX_TRIGGER_AGE
    fresh_setup = (
        (has_l34   and age_l34   is not None and age_l34   <= _MAX_SETUP_AGE) or
        (has_fri34 and age_fri34 is not None and age_fri34 <= _MAX_SETUP_AGE)
    )

    if seq in _CONFIRMED_SEQS:
        return "CONFIRMED"

    if seq in _TRIGGERED_SEQS:
        return "TRIGGERED"

    if seq in _SETUP_SEQS:
        return "PRE_TRIGGER"

    # OVEREXTENDED: price well above EMA200, no valid trigger (TORO example)
    if ema_ext > 1.3 and not fresh_g4 and (has_l34 or has_fri34 or has_g4):
        return "OVEREXTENDED"

    # IMPULSE: explosive volume without NP structure (FRMM example)
    if volume_z is not None and volume_z >= 1.8 and not fresh_setup and not fresh_g4:
        return "IMPULSE"

    # FAILED_SETUP vs BROKEN_SETUP: L34 present but no G4 (AGPU example)
    if has_l34 and not fresh_g4:
        ages = [a for a in (age_l34, age_fri34) if a is not None]
        best_age = min(ages) if ages else None
        if best_age is not None and best_age > _MAX_SETUP_AGE:
            return "BROKEN_SETUP"
        return "FAILED_SETUP"

    # BROKEN_SETUP: had G4 historically, all signals now stale
    if has_g4 and not fresh_g4 and not fresh_setup and seq == "NONE":
        return "BROKEN_SETUP"

    return "NEUTRAL"


# ---------------------------------------------------------------------------
# Phase 5: Explanation fields
# ---------------------------------------------------------------------------

def _explain(seq_label: str, state: str,
             age_g4, age_l34, age_fri34, age_b2) -> tuple:
    """Return (missing_piece, main_risk) for explainable output."""
    if state == "CONFIRMED":
        missing = None
    elif seq_label in ("SETUP_ONLY_L34", "SETUP_ONLY_FRI34"):
        missing = "G4"
    elif seq_label in ("TRIGGER_AFTER_L34", "TRIGGER_AFTER_FRI34", "ISOLATED_G4"):
        missing = "B2"
    elif age_l34 is None and age_fri34 is None:
        missing = "structure_not_present"
    elif seq_label == "NONE":
        missing = "fresh_trigger"
    else:
        missing = None

    if state == "OVEREXTENDED":
        risk = "move_without_confirm"
    elif state == "IMPULSE":
        risk = "external_move_without_base"
    elif state in ("FAILED_SETUP", "BROKEN_SETUP", "PRE_TRIGGER", "NEUTRAL"):
        risk = "no_progression"
    elif state == "TRIGGERED":
        risk = "no_progression"
    elif state == "CONFIRMED" and seq_label == "CONFIRM_AFTER_G4":
        risk = "move_without_confirm"
    else:
        risk = None

    return missing, risk


# ---------------------------------------------------------------------------
# Phase 4: Impulse engine (separate path, does not contaminate structure score)
# ---------------------------------------------------------------------------

def compute_impulse_score(bars: list) -> dict:
    """
    Score explosive volume/price expansion regardless of NP structure.
    Returns impulse_score (int) and impulse_label (str or None).
    Lives on a separate path — never added to new_pump_score.
    """
    n = len(bars)
    if n < 20:
        return {"impulse_score": 0, "impulse_label": None}

    closes  = [b["close"]  for b in bars]
    volumes = [b["volume"] for b in bars]
    last = n - 1

    vol_win = volumes[max(0, last - 19): last + 1]
    vol_mid = sum(vol_win) / len(vol_win) if vol_win else 0
    vol_var = sum((v - vol_mid) ** 2 for v in vol_win) / len(vol_win) if vol_win else 0
    vol_std = vol_var ** 0.5
    vz = (volumes[last] - vol_mid) / vol_std if vol_std > 0 else 0

    low_10   = min(b["low"] for b in bars[max(0, last - 9): last + 1])
    price_exp = (closes[last] - low_10) / low_10 * 100 if low_10 > 0 else 0

    ref5 = closes[max(0, last - 4)]
    mom5 = (closes[last] - ref5) / ref5 * 100 if ref5 > 0 else 0

    score = 0
    if vz >= 3.0:          score += 30
    elif vz >= 2.0:        score += 20
    elif vz >= 1.5:        score += 10

    if price_exp >= 15:    score += 25
    elif price_exp >= 8:   score += 15
    elif price_exp >= 4:   score += 8

    if mom5 >= 10:         score += 20
    elif mom5 >= 5:        score += 12
    elif mom5 >= 2:        score += 6

    if score >= 50:        label = "IMPULSE_STRONG"
    elif score >= 25:      label = "IMPULSE_WATCH"
    else:                  label = None

    return {"impulse_score": score, "impulse_label": label}


# ---------------------------------------------------------------------------
# Decision Layer
# ---------------------------------------------------------------------------
# Sits on top of structure + base-quality + expansion + impulse engines and
# emits ONE final trading decision per candidate.
#
# Values:
#   BUY_CANDIDATE — confirmed/triggered structure + solid base + not overheated
#   WATCH         — good base + early setup / pre-trigger / accumulation
#   IMPULSE_RISK  — explosive move on the impulse path, not a structure buy
#   AVOID         — degraded structure, high fake-trigger risk, overheated, or
#                   very weak base
#
# Uses only live-safe fields already computed by the engines above — no
# outcome / future leakage.

def _decide(*, state, engine_path, seq_lbl, bq_score, sustain_profile, ftr,
            missing_piece, ce_state, ce_score, ce_risk,
            impulse_label, impulse_score) -> tuple:
    """
    Returns (decision, decision_reason, decision_flags).
    decision_flags is a list of short tokens describing what drove the call.
    """
    flags: list = []

    # ── AVOID gates (hard red flags, checked first) ─────────────────────────
    if ftr == "HIGH":
        flags.append("high_fake_trigger_risk")
        return "AVOID", "fake-trigger risk HIGH despite sequence", flags

    if state in ("FAILED_SETUP", "BROKEN_SETUP", "OVEREXTENDED"):
        flags.append("degraded_structure")
        return "AVOID", f"structure state={state}", flags

    if bq_score < 25:
        flags.append("very_low_base_quality")
        return "AVOID", f"base quality very low ({bq_score})", flags

    if ce_state == "OVERHEATED_EXPANSION":
        flags.append("overheated_expansion")
        return "AVOID", "post-compression engine flagged overheat", flags

    # ── IMPULSE_RISK (separate from structure path) ─────────────────────────
    if engine_path == "impulse":
        if impulse_label == "IMPULSE_STRONG" or (impulse_score or 0) >= 50:
            flags.append("impulse_path_strong")
            return "IMPULSE_RISK", "impulse-only path, no structure support", flags
        flags.append("impulse_path_weak")
        return "AVOID", "impulse path without enough impulse strength", flags

    # ── BUY_CANDIDATE gates ─────────────────────────────────────────────────
    structure_ready = state in ("TRIGGERED", "CONFIRMED")
    bq_ok           = bq_score >= 45
    ftr_ok          = ftr != "HIGH"             # already filtered above, keep explicit
    sustain_ok      = sustain_profile in ("MEDIUM", "HIGH")
    ce_safe         = ce_state != "OVERHEATED_EXPANSION"  # already filtered
    critical_miss   = missing_piece in ("no_trigger", "structure_not_present")

    if (structure_ready and bq_ok and ftr_ok and ce_safe
            and not critical_miss):
        # Demote TRIGGERED + MEDIUM ftr + borderline base to WATCH (ELA-like
        # trigger with weak quality must not become BUY).
        if state == "TRIGGERED" and ftr == "MEDIUM" and bq_score < 55:
            flags.append("triggered_but_medium_ftr")
            return "WATCH", "triggered with medium fake-trigger risk", flags
        # Demote TRIGGERED with LOW sustain when structure not yet confirmed.
        if state == "TRIGGERED" and sustain_profile == "LOW" and bq_score < 55:
            flags.append("triggered_weak_sustain")
            return "WATCH", "triggered but sustain LOW + base not strong", flags
        flags.append("structure_ready")
        if bq_score >= 60: flags.append("strong_base")
        if ce_state in ("ACCUMULATION_READY", "EXPANSION_START"):
            flags.append(f"ce_{ce_state.lower()}")
        return "BUY_CANDIDATE", f"{state} + base_quality={bq_score}", flags

    # ── WATCH gates (good early setups / pre-trigger / early expansion) ─────
    # TRIGGERED/CONFIRMED that didn't pass BUY gates → WATCH (not AVOID)
    if structure_ready:
        if not bq_ok:
            flags.append("triggered_weak_base")
            return "WATCH", f"{state} but base quality weak ({bq_score})", flags
        if not sustain_ok:
            flags.append("triggered_weak_sustain")
            return "WATCH", f"{state} but sustain {sustain_profile}", flags
        # critical_miss on structure
        flags.append("triggered_missing_piece")
        return "WATCH", f"{state} but missing={missing_piece}", flags

    if state == "PRE_TRIGGER" and bq_ok:
        flags.append("pre_trigger_good_base")
        if ce_state in ("COMPRESSED_BASE", "ACCUMULATION_READY", "EXPANSION_START"):
            flags.append(f"ce_{ce_state.lower()}")
        return "WATCH", f"PRE_TRIGGER with base_quality={bq_score}", flags

    # Setup-only sequences with strong base (MOBX / CAPR / UGRO-like)
    if seq_lbl in ("SETUP_ONLY_L34", "SETUP_ONLY_FRI34") and bq_score >= 55:
        flags.append("setup_only_strong_base")
        return "WATCH", f"{seq_lbl} with strong base", flags

    # Expansion engine sees something actionable before structure trigger
    if ce_state in ("ACCUMULATION_READY", "EXPANSION_START") and ce_score >= 45 and bq_score >= 40:
        flags.append("expansion_engine_ready")
        flags.append(f"ce_{ce_state.lower()}")
        return "WATCH", f"compression-expansion={ce_state}", flags

    if ce_state == "COMPRESSED_BASE" and ce_score >= 40 and bq_score >= 45:
        flags.append("compressed_base_good")
        return "WATCH", "compressed base forming with good quality", flags

    # ── Default AVOID ───────────────────────────────────────────────────────
    if bq_score < 40:
        flags.append("weak_base_no_structure")
    return "AVOID", "no compelling structural or expansion setup", flags


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run(bars):
    """
    Run engine over bars (oldest-first). Returns list of per-bar signal dicts.
    Each dict: index, sequence, strength, components, reason.
    """
    if len(bars) < 2:
        return []
    return _build_signal_history(bars)["signals"]


def analyze(bars):
    """
    Full analysis for the most recent bar.

    bars: list of dicts with keys open/high/low/close/volume, oldest-first.

    Returns dict with:
      has_l34, has_fri34, has_g4, has_b2
      age_l34, age_fri34, age_g4, age_b2
      new_pump_setup_score, new_pump_trigger_score,
      new_pump_confirm_score, new_pump_modifier_score,
      new_pump_score
      new_pump_sequence_label
      new_pump_label
    """
    n = len(bars)
    if n < 2:
        return _empty_analysis()

    tracking = _build_signal_history(bars)
    last = n - 1

    closes  = [b["close"]  for b in bars]
    volumes = [b["volume"] for b in bars]

    ema20_s  = _compute_ema(closes, 20)
    ema50_s  = _compute_ema(closes, 50)
    ema200_s = _compute_ema(closes, 200)
    ema20  = ema20_s[last]
    ema50  = ema50_s[last]
    ema200 = ema200_s[last]

    # Volume stats
    vol_win  = volumes[max(0, last - 19): last + 1]
    vol_mid  = _sma(vol_win, 20)
    vol_std  = _std(vol_win, 20)
    volume_z = None
    if vol_mid is not None and vol_std is not None and vol_std > 0:
        volume_z = (volumes[last] - vol_mid) / vol_std

    # Dollar-volume ratio vs 20-bar avg
    dv_win  = [closes[j] * volumes[j] for j in range(max(0, last - 19), last + 1)]
    cur_dv  = closes[last] * volumes[last]
    avg_dv  = sum(dv_win) / len(dv_win) if dv_win else None
    dv_ratio = cur_dv / avg_dv if avg_dv and avg_dv > 0 else None

    # Body expansion: avg of last 5 bars vs last 20 bars
    bodies_5  = [abs(bars[j]["close"] - bars[j]["open"])
                 for j in range(max(0, last - 4), last + 1)]
    bodies_20 = [abs(bars[j]["close"] - bars[j]["open"])
                 for j in range(max(0, last - 19), last + 1)]
    avg_b5  = sum(bodies_5)  / len(bodies_5)  if bodies_5  else None
    avg_b20 = sum(bodies_20) / len(bodies_20) if bodies_20 else None
    body_ratio = avg_b5 / avg_b20 if avg_b5 and avg_b20 and avg_b20 > 0 else None

    # Ribbon quality metrics (research-calibrated from Run #50)
    # bull_stack_len: consecutive bars with full ema20 > ema50 > ema200 (up to 30 bars)
    bull_stack_len = 0
    for i in range(last, max(-1, last - 30), -1):
        e20 = ema20_s[i]; e50 = ema50_s[i]; e200 = ema200_s[i]
        if e20 is not None and e50 is not None and e200 is not None and e20 > e50 > e200:
            bull_stack_len += 1
        else:
            break

    # days_above_ema50: close > EMA50 count over last 20 bars
    days_above_ema50 = sum(
        1 for i in range(max(0, last - 19), last + 1)
        if ema50_s[i] is not None and closes[i] > ema50_s[i]
    )

    # ema50_reclaim_count: close crossed from below to above EMA50 in last 20 bars
    ema50_reclaim_count = sum(
        1 for i in range(max(1, last - 19), last + 1)
        if (ema50_s[i] is not None and ema50_s[i - 1] is not None
            and closes[i] > ema50_s[i] and closes[i - 1] <= ema50_s[i - 1])
    )

    # avg_ema_spread_10: avg |EMA20 - EMA200| / EMA200 % over last 10 bars
    ema_spreads = [
        abs(ema20_s[i] - ema200_s[i]) / ema200_s[i] * 100
        for i in range(max(0, last - 9), last + 1)
        if ema20_s[i] is not None and ema200_s[i] is not None and ema200_s[i] > 0
    ]
    avg_ema_spread_10 = sum(ema_spreads) / len(ema_spreads) if ema_spreads else None

    # Ages (None = signal never fired)
    def _age(bar_list):
        return (last - max(bar_list)) if bar_list else None

    age_l34   = _age(tracking["l34_bars"])
    age_fri34 = _age(tracking["fri34_bars"])
    age_g4    = _age(tracking["g4_bars"])
    age_b2    = _age(tracking["b2_bars"])

    has_l34   = age_l34   is not None
    has_fri34 = age_fri34 is not None
    has_g4    = age_g4    is not None
    has_b2    = age_b2    is not None

    # Repeated counts over setup-age window (aligned with _MAX_SETUP_AGE)
    count_l34_w   = sum(1 for b in tracking["l34_bars"]   if last - b < _MAX_SETUP_AGE)
    count_fri34_w = sum(1 for b in tracking["fri34_bars"] if last - b < _MAX_SETUP_AGE)

    # Sequence label + state computed early so base_quality can condition scoring
    seq_lbl      = _sequence_label(age_l34, age_fri34, age_g4, age_b2)
    ema_extended = (closes[last] / ema200) if (ema200 and ema200 > 0) else None
    _ctx = dict(
        new_pump_sequence_label=seq_lbl,
        has_l34=has_l34, has_fri34=has_fri34, has_g4=has_g4, has_b2=has_b2,
        age_l34=age_l34, age_fri34=age_fri34, age_g4=age_g4, age_b2=age_b2,
        volume_z=volume_z,
        ema_extended=ema_extended,
    )
    state       = classify_state(_ctx)
    engine_path = "impulse" if state == "IMPULSE" else "structure"

    # Phase 3: base quality (needs pre-computed ribbon metrics)
    bq_score = _compute_base_quality(
        bars, last, bull_stack_len, days_above_ema50,
        ema50_reclaim_count, avg_ema_spread_10, volumes,
    )

    # Scores — progression_adjustment is now quality-conditional
    setup_score   = _setup_score(age_l34, age_fri34, count_l34_w, count_fri34_w)
    trigger_score = _trigger_score(age_g4, age_l34, age_fri34)
    confirm_score = _confirm_score(age_b2, age_g4, age_l34, age_fri34)
    seq_bonus     = _sequence_bonus(age_l34, age_fri34, age_g4, age_b2)
    mod_score     = _modifier_score(
        age_l34, age_fri34, age_g4, age_b2,
        ema20, ema50, ema200, closes[last],
        volume_z, body_ratio, dv_ratio,
        bull_stack_len=bull_stack_len,
        days_above_ema50=days_above_ema50,
        ema50_reclaim_count=ema50_reclaim_count,
        avg_ema_spread=avg_ema_spread_10,
    )
    prog_adj = _progression_adjustment(seq_lbl, bq_score)

    # Fake trigger risk + quality modifier + PRE_TRIGGER gate
    ftr       = _fake_trigger_risk(seq_lbl, bq_score, avg_ema_spread_10, volume_z)
    ftr_pen   = _fake_trigger_penalty(ftr, seq_lbl)
    qmod      = _quality_score_modifier(bq_score, state)
    weak_pre_trigger_base, pt_gate_pen = _pre_trigger_gate(state, bq_score)
    base_flags = _compute_base_flags(bq_score, avg_ema_spread_10, bars, last, volumes)

    total = max(0, setup_score + trigger_score + confirm_score
                   + seq_bonus + mod_score + prog_adj + ftr_pen + qmod + pt_gate_pen)

    # Sustain proxy + impulse (separate paths, do not contaminate new_pump_score)
    sp_score, sp_profile = _compute_sustain_proxy(
        bq_score, bull_stack_len, days_above_ema50,
        avg_ema_spread_10, volumes, bars, last,
    )
    missing_piece, main_risk = _explain(seq_lbl, state, age_g4, age_l34, age_fri34, age_b2)
    impulse = compute_impulse_score(bars)

    # Post-Compression Expansion sub-engine — independent output, never mixed
    # into new_pump_score or impulse_score.
    try:
        from scanner.expansion_engine import analyze_expansion
        exp = analyze_expansion(
            bars,
            base_quality_score=bq_score,
            avg_ema_spread=avg_ema_spread_10,
            volume_z=volume_z,
            ema_extended=ema_extended,
        )
    except Exception:
        exp = dict(
            compression_expansion_state="NONE",
            compression_expansion_score=0,
            compression_expansion_label="NONE",
            expansion_timing_risk="LOW",
            expansion_quality_flags={},
        )

    # Assemble quality_flags + apply label cap
    quality_flags = dict(base_flags)
    if weak_pre_trigger_base:
        quality_flags["weak_pre_trigger_base"] = True
    if ftr == "HIGH" and seq_lbl in (
        "TRIGGER_AFTER_L34", "TRIGGER_AFTER_FRI34",
        "FULL_L34_G4_B2", "FULL_FRI34_G4_B2", "CONFIRM_AFTER_G4",
    ):
        quality_flags["fake_trigger_low_quality"] = True

    raw_label    = _final_label(total)
    capped_label = _cap_label(raw_label, weak_pre_trigger_base, ftr, bq_score)

    # Final decision layer (after all other engines have produced output)
    decision, decision_reason, decision_flags = _decide(
        state=state,
        engine_path=engine_path,
        seq_lbl=seq_lbl,
        bq_score=bq_score,
        sustain_profile=sp_profile,
        ftr=ftr,
        missing_piece=missing_piece,
        ce_state=exp["compression_expansion_state"],
        ce_score=exp["compression_expansion_score"],
        ce_risk=exp["expansion_timing_risk"],
        impulse_label=impulse["impulse_label"],
        impulse_score=impulse["impulse_score"],
    )

    return dict(
        has_l34=has_l34, has_fri34=has_fri34, has_g4=has_g4, has_b2=has_b2,
        age_l34=age_l34, age_fri34=age_fri34, age_g4=age_g4, age_b2=age_b2,
        new_pump_setup_score=setup_score,
        new_pump_trigger_score=trigger_score,
        new_pump_confirm_score=confirm_score,
        new_pump_modifier_score=mod_score,
        new_pump_score=total,
        new_pump_sequence_label=seq_lbl,
        new_pump_label=capped_label,
        state=state,
        engine_path=engine_path,
        missing_piece=missing_piece,
        main_risk=main_risk,
        impulse_score=impulse["impulse_score"],
        impulse_label=impulse["impulse_label"],
        volume_z=round(volume_z, 3) if volume_z is not None else None,
        ema_extended=round(ema_extended, 3) if ema_extended is not None else None,
        base_quality_score=bq_score,
        sustain_proxy_score=sp_score,
        sustain_profile=sp_profile,
        fake_trigger_risk=ftr,
        quality_flags=quality_flags,
        compression_expansion_state=exp["compression_expansion_state"],
        compression_expansion_score=exp["compression_expansion_score"],
        compression_expansion_label=exp["compression_expansion_label"],
        expansion_timing_risk=exp["expansion_timing_risk"],
        expansion_quality_flags=exp["expansion_quality_flags"],
        decision=decision,
        decision_reason=decision_reason,
        decision_flags=decision_flags,
    )


def summarize_results(scan_results, top_n=20):
    """
    Produce a debug summary of New Pump output across a scan result set.

    scan_results: list of result dicts from runner.py (each has "symbol" and "new_pump").
    Returns a dict with label_counts, sequence_counts, and top_by_score.
    """
    _LABEL_ORDER = [
        "NEW_PUMP_FIRE", "NEW_PUMP_STRONG", "NEW_PUMP_SETUP",
        "NEW_PUMP_TRIGGER_ONLY", "NEW_PUMP_WEAK", "NEW_PUMP_NONE",
    ]

    label_counts    = {lbl: 0 for lbl in _LABEL_ORDER}
    sequence_counts = {}
    ranked          = []

    for r in scan_results:
        np = r.get("new_pump")
        if not np:
            continue

        lbl = np.get("new_pump_label", "NEW_PUMP_NONE")
        label_counts[lbl] = label_counts.get(lbl, 0) + 1

        seq = np.get("new_pump_sequence_label", "NONE")
        sequence_counts[seq] = sequence_counts.get(seq, 0) + 1

        ranked.append({
            "symbol":                 r.get("symbol", "?"),
            "new_pump_score":         np.get("new_pump_score", 0),
            "new_pump_label":         lbl,
            "new_pump_sequence_label": seq,
            "has_l34":                np.get("has_l34", False),
            "has_fri34":              np.get("has_fri34", False),
            "has_g4":                 np.get("has_g4", False),
            "has_b2":                 np.get("has_b2", False),
        })

    ranked.sort(key=lambda x: x["new_pump_score"], reverse=True)

    return dict(
        label_counts=label_counts,
        sequence_counts=dict(sorted(sequence_counts.items(),
                                    key=lambda kv: kv[1], reverse=True)),
        top_by_score=ranked[:top_n],
    )
