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

    v2 — recalibrated for small-cap universe (Replay 18: v1 produced 90% LOW scores).
    Thresholds lowered, EMA-spread penalty softened, weight shifted toward
    compression + dryup which are more universal signals across market caps.

    Component weights:
      Price compression      25 pts  (5-bar/20-bar ratio; most universal)
      Volume dry-up          25 pts  (min_5/avg_20; coiled energy)
      Bull stack persistence 20 pts  (lowered thresholds vs v1)
      EMA50 proximity        15 pts  (lowered thresholds vs v1)
      EMA ribbon spread      10 pts  (softer penalty for natural small-cap spread)
      Intraday volatility     5 pts  (tight daily candles)
    """
    score = 0

    # 1. Price compression: 5-bar range / 20-bar range (up to 25 pts)
    if last >= 19:
        hi5  = max(b["high"] for b in bars[max(0, last - 4):  last + 1])
        lo5  = min(b["low"]  for b in bars[max(0, last - 4):  last + 1])
        hi20 = max(b["high"] for b in bars[max(0, last - 19): last + 1])
        lo20 = min(b["low"]  for b in bars[max(0, last - 19): last + 1])
        r20  = hi20 - lo20
        if r20 > 0:
            comp = (hi5 - lo5) / r20
            if comp < 0.20:   score += 25
            elif comp < 0.35: score += 18
            elif comp < 0.50: score += 12
            elif comp < 0.65: score += 6

    # 2. Volume dry-up: min vol last 5 bars vs 20-bar avg (up to 25 pts)
    if last >= 19 and len(volumes) > last:
        avg_v20  = sum(volumes[max(0, last - 19): last + 1]) / 20
        min_v5   = min(volumes[max(0, last - 4): last + 1])
        dryup    = min_v5 / avg_v20 if avg_v20 > 0 else 1.0
        if dryup < 0.25:   score += 25
        elif dryup < 0.45: score += 18
        elif dryup < 0.65: score += 12
        elif dryup < 0.80: score += 6

    # 3. Bull stack persistence: lowered thresholds for small-cap (up to 20 pts)
    if bull_stack_len >= 10:   score += 20
    elif bull_stack_len >= 6:  score += 15
    elif bull_stack_len >= 3:  score += 10
    elif bull_stack_len >= 1:  score += 5

    # 4. EMA50 proximity: lowered thresholds (up to 15 pts)
    if days_above_ema50 >= 12:   score += 15
    elif days_above_ema50 >= 8:  score += 11
    elif days_above_ema50 >= 4:  score += 7
    elif days_above_ema50 >= 1:  score += 3

    # 5. EMA ribbon spread: softened penalty — small-caps naturally wider (up to 10 pts)
    if avg_ema_spread is not None:
        if avg_ema_spread < 20:    score += 10
        elif avg_ema_spread < 35:  score += 7
        elif avg_ema_spread < 50:  score += 4
        elif avg_ema_spread < 65:  score += 1
        else:                      score -= 3   # was -8; softened for small-cap universe

    # 6. Intraday volatility control: tight daily ranges (up to 5 pts)
    if last >= 9:
        ranges = [
            (b["high"] - b["low"]) / b["close"] * 100
            for b in bars[max(0, last - 9): last + 1]
            if b["close"] > 0
        ]
        if ranges:
            avg_r = sum(ranges) / len(ranges)
            if avg_r < 3.0:    score += 5
            elif avg_r < 5.0:  score += 3
            elif avg_r < 8.0:  score += 1

    return max(0, min(100, score))


def _compute_sustain_proxy(base_quality_score, bull_stack_len, days_above_ema50,
                            avg_ema_spread, volumes, bars, last):
    """
    Sustain proxy score 0–100 + profile label (LOW/MEDIUM/HIGH).
    Estimates whether setup conditions historically lead to sustained moves.
    Does NOT use days_from_breakout_to_peak or any outcome features.

    v2 — independent of base_quality_score.  Previous formula anchored 40%
    on bq which was under-calibrated → 99% of candidates collapsed to LOW.
    New formula scores continuation quality directly from raw signals.

    Components:
      Volume discipline       35 pts  (low-vol days = coiled controlled rotation)
      Compression stability   25 pts  (10-bar/30-bar ratio, multi-week tightness)
      Intraday control        20 pts  (tight candles, not chaotic one-day spikes)
      Bull persistence        15 pts  (continuation support structure)
      EMA spread              5 pts   (room for expansion)
    """
    score = 0

    # 1. Volume discipline: sustained low-vol = controlled rotation, not spike (up to 35 pts)
    if last >= 14 and len(volumes) > last:
        avg_v20 = sum(volumes[max(0, last - 19): last + 1]) / min(20, last + 1)
        low_vol_days = sum(
            1 for j in range(max(0, last - 9), last + 1)
            if avg_v20 > 0 and volumes[j] < 0.65 * avg_v20
        )
        if low_vol_days >= 7:   score += 35
        elif low_vol_days >= 5: score += 25
        elif low_vol_days >= 3: score += 15
        elif low_vol_days >= 1: score += 5

    # 2. Compression stability: 10-bar range / 30-bar range (up to 25 pts)
    if last >= 29:
        hi10 = max(b["high"] for b in bars[max(0, last - 9):  last + 1])
        lo10 = min(b["low"]  for b in bars[max(0, last - 9):  last + 1])
        hi30 = max(b["high"] for b in bars[max(0, last - 29): last + 1])
        lo30 = min(b["low"]  for b in bars[max(0, last - 29): last + 1])
        r30  = hi30 - lo30
        if r30 > 0:
            stab = (hi10 - lo10) / r30
            if stab < 0.25:   score += 25
            elif stab < 0.40: score += 18
            elif stab < 0.55: score += 10
            elif stab < 0.70: score += 5

    # 3. Intraday control: tight daily candles = controlled base (up to 20 pts)
    if last >= 9:
        ranges = [
            (b["high"] - b["low"]) / b["close"] * 100
            for b in bars[max(0, last - 9): last + 1]
            if b["close"] > 0
        ]
        if ranges:
            avg_r = sum(ranges) / len(ranges)
            if avg_r < 2.0:    score += 20
            elif avg_r < 3.5:  score += 14
            elif avg_r < 5.0:  score += 8
            elif avg_r < 8.0:  score += 3
            elif avg_r > 12.0: score -= 5   # chaotic parabolic — not controlled

    # 4. Bull stack persistence: sustained trend support (up to 15 pts)
    if bull_stack_len >= 8:    score += 15
    elif bull_stack_len >= 4:  score += 10
    elif bull_stack_len >= 2:  score += 5

    # 5. EMA spread: tight = room to expand (up to 5 pts)
    if avg_ema_spread is not None:
        if avg_ema_spread < 20:    score += 5
        elif avg_ema_spread < 35:  score += 3

    score = max(0, min(100, score))
    profile = "HIGH" if score >= 60 else ("MEDIUM" if score >= 35 else "LOW")
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
    Explainable base-quality diagnostic flags.  Advisory only — does not affect score.
    Thresholds aligned with v2 quality-scoring formula for consistency.
    """
    flags = {}

    # EMA spread: flag truly wide (>= 65%); threshold raised from 55% so natural
    # small-cap spread is not over-flagged. Also flag tight spread positively.
    if avg_ema_spread is not None:
        if avg_ema_spread >= 65:
            flags["wide_ema_spread"] = True
        elif avg_ema_spread < 20:
            flags["tight_ema_spread"] = True

    # Volume dry-up: threshold raised 0.75 → 0.80 to match new scoring formula
    if last >= 19 and len(volumes) > last:
        avg_v20 = sum(volumes[max(0, last - 19): last + 1]) / 20
        if avg_v20 > 0:
            dryup = min(volumes[max(0, last - 4): last + 1]) / avg_v20
            if dryup >= 0.80:
                flags["low_dryup"] = True
            elif dryup < 0.25:
                flags["strong_dryup"] = True

    # Compression: 5-bar/20-bar ratio — threshold aligned with new formula
    if last >= 19:
        hi5  = max(b["high"] for b in bars[max(0, last - 4):  last + 1])
        lo5  = min(b["low"]  for b in bars[max(0, last - 4):  last + 1])
        hi20 = max(b["high"] for b in bars[max(0, last - 19): last + 1])
        lo20 = min(b["low"]  for b in bars[max(0, last - 19): last + 1])
        r20  = hi20 - lo20
        if r20 > 0:
            comp = (hi5 - lo5) / r20
            if comp >= 0.65:
                flags["low_compression"] = True
            elif comp < 0.20:
                flags["strong_compression"] = True

    # Chaotic base: ATR pct >= 7% (unchanged threshold)
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
            elif atr_pct < 3.0:
                flags["controlled_expansion_context"] = True

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
                    avg_ema_spread=None,
                    bull_eng_count_20=0, extreme_anom_count_20=0, b2_count_20=0):
    mod = 0
    ema20_ok  = ema20  is not None
    ema50_ok  = ema50  is not None
    ema200_ok = ema200 is not None

    # --- Positive modifiers ---

    # 1. Bull stack presence + duration (up to +13)
    # R59: bull_stack_days_pre INCREASE — 4x_pump median=14 days vs FP median=8 days.
    # Added 14-day tier (+5) to match 4x_pump territory; previous top was >= 10 (+4).
    if ema20_ok and ema50_ok and ema200_ok and ema20 > ema50 > ema200:
        mod += 8
        if bull_stack_len >= 14:   # R59: 4x_pump median territory
            mod += 5
        elif bull_stack_len >= 10:
            mod += 4
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

    # 5a. Bullish engulfing count — R59: BOOST 2.0× (4x_pump has 2× more engulfing bars pre-pump)
    if bull_eng_count_20 >= 3:
        mod += 5
    elif bull_eng_count_20 >= 2:
        mod += 3
    elif bull_eng_count_20 >= 1:
        mod += 1

    # --- Negative modifiers ---

    # 6. Ultra-extreme anomaly spike (up to -8)
    if volume_z is not None:
        if volume_z > 4.0:
            mod -= 8
        elif volume_z > 3.5:
            mod -= 5
        elif volume_z > 3.0:
            mod -= 3

    # 6a. Repeated extreme-anomaly penalty — R59: extreme_anomaly_day_count_pre PENALIZE (FP higher).
    # Counts bars in last 20 (excluding today) where volume exceeded 3.5σ.
    # Today's spike already penalised in #6; this targets stale anomaly footprints.
    if extreme_anom_count_20 >= 3:
        mod -= 4
    elif extreme_anom_count_20 >= 2:
        mod -= 2
    elif extreme_anom_count_20 == 1:
        mod -= 1

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

    # 10a. B2 cycling penalty — R59: b2_count_pre PENALIZE (FP 2× more cycling B2 bars).
    # Multiple recent B2s without an active G4 trigger = choppy false-positive footprint.
    if b2_count_20 >= 3 and (age_g4 is None or age_g4 > 5):
        mod -= 3
    elif b2_count_20 >= 2 and age_g4 is None:
        mod -= 1

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
    # v3.5 (R21, n=906, Apr 2026):
    # — FIRE raised 62→68: R21 FIRE n=4 -0.38% vs NONE +0.51% — no edge, tighten gate
    # — STRONG raised 46→55: R21 STRONG -1.97%, structure_score 46_65 bucket -0.70% n=212
    if score >= 68:  return "NEW_PUMP_FIRE"       # was 62
    if score >= 55:  return "NEW_PUMP_STRONG"     # was 46
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
        decision_authority="structure_phase_score",
        legacy_label_role="diagnostic_only",
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

# v3.6: sequences permitted to generate BUY_CANDIDATE decisions.
# Excludes TRIGGER_AFTER_FRI34 (R21 n=5 -2.19%), ISOLATED_G4 (R21 n=267 -1.63%),
# ISOLATED_B2, SETUP_ONLY_L34 (weak vs FRI34), NONE (no signal).
_BUY_SEQUENCE_WHITELIST = frozenset({
    "TRIGGER_AFTER_L34",
    "CONFIRM_AFTER_G4",
    "FULL_L34_G4_B2",
    "FULL_FRI34_G4_B2",
    "SETUP_ONLY_FRI34",
})


def _decide(*, state, engine_path, seq_lbl, bq_score, sustain_profile, ftr,
            missing_piece, ce_state, ce_score, ce_risk,
            impulse_label, impulse_score,
            np_label=None, age_l34=None, age_fri34=None,
            structure_phase=None, structure_score=None) -> tuple:
    """
    Returns (decision, decision_reason, decision_flags).

    Routing v3 — calibrated on Replay 18+19+20 + Pattern Study R59 (Apr 2026).

    Key calibration facts:
      • bq LOW not worse than MEDIUM — bq removed as hard routing gate (advisory only).
      • PRE_TRIGGER avg 5d +3.85% (194 cands R19) — broad watchlist entry.
      • NEUTRAL avg 5d -4.58% R19 — correctly avoided.
      • ISOLATED_B2 avg 5d -3.60% R19 — explicit hard-avoid.
      • HIGH ftr n=5 +24.57% 5d R19 — annotate only, do NOT demote routing.
      • BROKEN_SETUP n=13 -4.49% 5d, 30.8% WR R20 — reverted to AVOID (R19 n=5 was outlier).
      • NEW_PUMP_WEAK n=144 +3.28% 5d, +8.9% 10d R20 — top-performing NP label.
      • SETUP_ONLY_FRI34 n=128 +4.15% 5d, 68.0% WR R20 — best PRE_TRIGGER, score raised.
      • COMPRESSED_BASE -1.82% 5d R20 — caution flag confirmed.
      • MODERATE freshness (age 4-7 bars) +3.17% 5d vs FRESH +1.09% R20 — flagged.
      v3.4 — R59 Pattern Study (n=209, run_id=59, 2025-12-02..2026-04-24):
      • bullish_engulfing_count_pre BOOST 2.0× — added +1/+3/+5 pts to modifier (#5a).
      • extreme_anomaly_day_count_pre PENALIZE — added -1/-2/-4 pts for stale spikes (#6a).
      • b2_count_pre PENALIZE (FP 2×) — added cycling penalty when no active G4 (#10a).
      • bull_stack_days_pre INCREASE (4x median=14d) — extended threshold to 14+ → +5 (#1).
      v3.5 — Replay R21 (n=906, run_id=21, 2026-03-01..2026-04-24):
      • FIRE threshold 62→68: R21 FIRE n=4 -0.38% vs NONE +0.51% — no edge, tighten gate.
      • STRONG threshold 46→55: R21 STRONG -1.97% 5d, structure_score 46_65 -0.70% n=212.
      • ISOLATED_G4 WATCH→AVOID: R21 n=267 -1.63% 5d — trigger without setup is negative.
      v3.6 — Decision authority cleanup (Apr 2026):
      • structure_phase + structure_score computed BEFORE _decide() — primary authority.
      • Legacy np_label demoted: FIRE/STRONG alone cannot create BUY_CANDIDATE.
      • BUY gate: structure_score >= 66 + CONFIRMED/TRIGGERED phase + whitelisted sequence.
      • Mid-score cap: structure_score 46-65 → max WATCH (R21: 46_65 bucket -0.70% 5d).
      • CONFIRMED/TRIGGERED + non-whitelisted sequence → WATCH (not BUY).
      • EARLY/SETUP phase + weak score (<46) → AVOID.
      v3.7 — Replay R22 (n=927, run_id=22, 2026-03-01..2026-04-24):
      • Validation: BUY n=36 +4.67% 5d 63.9% WR — clean edge, all in 66_100 bucket.
      • SETUP_ONLY_L34 + mid_ss → AVOID (was WATCH). R22: WATCH|46_65 -0.84% 5d
        37.8% WR (n=219, dominated by SETUP_ONLY_L34); SETUP_ONLY_L34 = 44% of all FPs.
      • SETUP_ONLY_FRI34 unaffected (base ss=62 → naturally lands in 66_100 → WATCH).
    """
    flags: list = []
    _ss = structure_score or 0
    _sp = structure_phase or "TRUE_NONE"

    # ── Hard AVOID: state-based structural failures (unchanged from v3.x) ─────
    if state == "NEUTRAL":
        flags.append("avoid_neutral")
        return "AVOID", "neutral — no structure present", flags

    if state == "FAILED_SETUP":
        flags.append("avoid_failed_setup")
        return "AVOID", "failed setup — structure never formed", flags

    if state == "OVEREXTENDED":
        flags.append("avoid_overextended")
        return "AVOID", "overextended — entry risk too high", flags

    # R20: BROKEN_SETUP n=13 -4.49% 5d, 30.8% WR — reverted to AVOID.
    if state == "BROKEN_SETUP":
        flags.append("avoid_broken_setup")
        return "AVOID", "broken setup — structure invalidated", flags

    # ISOLATED_B2: worst sequence R18 (-4.09% 5d, -14.94% alpha 10d).
    if seq_lbl == "ISOLATED_B2":
        flags.append("avoid_isolated_b2")
        return "AVOID", "isolated B2 — consistently negative sequence", flags

    # NONE sequence without triggered structure: R18 -2.49% 5d, -8.72% alpha 10d.
    if seq_lbl == "NONE" and state not in ("TRIGGERED", "CONFIRMED"):
        flags.append("avoid_none_sequence")
        return "AVOID", "no recognised sequence + no trigger", flags

    # R21: ISOLATED_G4 n=267 -1.63% 5d.
    if seq_lbl == "ISOLATED_G4":
        flags.append("avoid_isolated_g4")
        return "AVOID", "ISOLATED_G4 — trigger without setup, negative expectation", flags

    # ── Impulse path (separate playbook — unchanged) ──────────────────────────
    # R18: strong impulse +7.08%, 69.2% WR. Keep independent of structure routing.
    if engine_path == "impulse":
        if impulse_label == "IMPULSE_STRONG" or (impulse_score or 0) >= 50:
            flags.append("impulse_separate_playbook")
            return "IMPULSE_RISK", "impulse-only path, strong signal", flags
        flags.append("impulse_path_weak")
        return "AVOID", "impulse path without structural support", flags

    # ── Legacy label demotion annotations ─────────────────────────────────────
    # Labels remain in output for display/backward compat but do NOT drive routing.
    if np_label in ("NEW_PUMP_FIRE", "NEW_PUMP_STRONG"):
        flags.append("legacy_label_demoted")
        flags.append("legacy_label_not_decision_authority")
    if np_label == "NEW_PUMP_WEAK":
        flags.append("np_weak_elevated")
        if _sp in ("EARLY_STRUCTURE", "SETUP_PHASE"):
            flags.append("weak_label_early_structure")
    elif np_label == "NEW_PUMP_NONE":
        flags.append("np_none_caution")

    # ── Advisory context flags (informational only) ───────────────────────────
    if ftr == "HIGH":
        flags.append("borderline_high_ftr")
    if ce_state == "OVERHEATED_EXPANSION":
        flags.append("borderline_overheated_but_structural"
                     if _sp in ("CONFIRMED_STRUCTURE", "TRIGGERED_STRUCTURE")
                     else "overheated_expansion_note")
    if bq_score is not None and bq_score >= 35:
        flags.append("bq_medium_bucket")
    _l34_only = (age_l34 is not None and age_fri34 is None)
    if _l34_only:
        flags.append("np_l34_pure_strength")
    _setup_ages = [a for a in [age_l34, age_fri34] if a is not None]
    if _setup_ages:
        _min_age = min(_setup_ages)
        if 3 < _min_age <= 7:
            flags.append("np_moderate_freshness")
        elif _min_age <= 3:
            flags.append("np_fresh_early")
    if ce_state == "COMPRESSED_BASE":
        flags.append("ce_compressed_base_caution")
    elif ce_state == "EXPANSION_START":
        flags.append("ce_expansion_start_weak")
    elif ce_state in ("ACCUMULATION_READY",):
        flags.append("ce_accumulation_ready")

    # ── Phase hard-reject (belt-and-suspenders after state checks) ────────────
    if _sp in ("DEGRADED", "BROKEN_STRUCTURE", "TRUE_NONE"):
        flags.append("degraded_or_broken_structure")
        return "AVOID", f"phase={_sp} — structure not viable", flags

    # ── Structure-score tiers (universal gates) ───────────────────────────────
    _high_ss = _ss >= 66
    _mid_ss  = 46 <= _ss <= 65

    if _high_ss:
        flags.append("high_structure_score")
    if _mid_ss:
        flags.append("mid_structure_score_caution")

    # ── A. High-confidence BUY ─────────────────────────────────────────────────
    # Requires: ss >= 66 + CONFIRMED/TRIGGERED phase + whitelisted sequence.
    # R21: structure_score 66_100 was strongly positive; whitelist removes negative seqs.
    if (_high_ss
            and _sp in ("CONFIRMED_STRUCTURE", "TRIGGERED_STRUCTURE")
            and seq_lbl in _BUY_SEQUENCE_WHITELIST):
        flags.append("structure_score_66_buy")
        return (
            "BUY_CANDIDATE",
            f"phase={_sp} ss={_ss} seq={seq_lbl}",
            flags,
        )

    # ── B. CONFIRMED/TRIGGERED mid score → WATCH (not BUY) ────────────────────
    # R21: structure_score 46_65 bucket -0.70% 5d — cap at WATCH.
    if _sp in ("CONFIRMED_STRUCTURE", "TRIGGERED_STRUCTURE") and _mid_ss:
        return "WATCH", f"phase={_sp} ss={_ss} — mid score caution", flags

    # ── C. CONFIRMED/TRIGGERED high score but non-whitelisted → WATCH ─────────
    if _sp in ("CONFIRMED_STRUCTURE", "TRIGGERED_STRUCTURE") and _high_ss:
        flags.append("triggered_not_whitelisted_watch")
        return "WATCH", f"phase={_sp} ss={_ss} seq={seq_lbl} — not whitelisted for BUY", flags

    # ── D. Early / setup structure ─────────────────────────────────────────────
    # v3.7 (R22): SETUP_ONLY_L34 + mid_ss → AVOID (was WATCH).
    # R22: WATCH|46_65 -0.84% 5d, 37.8% WR (n=219, mostly SETUP_ONLY_L34).
    # SETUP_ONLY_L34 also = 44.2% of all FPs (n=126/285), FP rate 32.9%.
    # SETUP_ONLY_FRI34 (base ss=62) lands in 66_100 → keeps WATCH path.
    if _sp in ("EARLY_STRUCTURE", "SETUP_PHASE"):
        if seq_lbl == "SETUP_ONLY_L34":
            # SETUP_ONLY_L34 needs ss>=66 to earn even WATCH (rare: 38 base + 28pts).
            if _high_ss:
                flags.append("setup_only_l34_high_score_watch")
                return "WATCH", f"phase={_sp} ss={_ss} seq=SETUP_ONLY_L34 — high score", flags
            flags.append("l34_setup_only_mid_score_avoid")
            return "AVOID", f"SETUP_ONLY_L34 ss={_ss} — no edge at mid/weak score", flags

        if seq_lbl == "SETUP_ONLY_FRI34":
            flags.append("watch_fri34_setup_strength")
        if _high_ss:
            flags.append("early_structure_high_score_watch")
            return "WATCH", f"phase={_sp} ss={_ss} — waiting for trigger/confirm", flags
        if _mid_ss:
            return "WATCH", f"phase={_sp} ss={_ss}", flags
        flags.append("weak_structure_score_avoid")
        return "AVOID", f"phase={_sp} ss={_ss} — weak structure score", flags

    # ── E. Fallback ────────────────────────────────────────────────────────────
    flags.append("decision_fallback_used")
    return "AVOID", f"no structure rule matched (phase={_sp} ss={_ss})", flags


# ---------------------------------------------------------------------------
# Structure-phase layer (additive semantic layer on top of existing NP output)
# ---------------------------------------------------------------------------

# Base score by sequence — upweights progression sequences (R19 calibration)
_STRUCTURE_SCORE_MAP = {
    "CONFIRM_AFTER_G4":    85,  # R20: n=9 +10.29% 5d, 77.8% WR — raised from 80
    "FULL_L34_G4_B2":      90,
    "FULL_FRI34_G4_B2":    85,
    "TRIGGER_AFTER_L34":   75,  # R20: n=19 +4.61% 5d, 63.2% WR
    "TRIGGER_AFTER_FRI34": 60,
    "SETUP_ONLY_FRI34":    62,  # R20: n=128 +4.15% 5d, 68.0% WR — raised from 55
    "SETUP_ONLY_L34":      38,  # boosted by freshness modifier below
    "ISOLATED_G4":         22,
    "ISOLATED_B2":          8,  # downweighted: R20 DEGRADED phase
    "NONE":                 5,  # downweighted: R20 n=44 -3.48% 5d
}


def _compute_structure_phase(seq_lbl, state, engine_path, np_label,
                              age_l34, age_fri34, impulse_label, impulse_score):
    """
    Semantic structure-phase layer — additive, does NOT modify existing labels.
    Returns (structure_phase: str, structure_score: int, structure_advisory: list).

    Phase values (best → worst):
      CONFIRMED_STRUCTURE  — full NP sequence validated
      TRIGGERED_STRUCTURE  — G4 trigger with known setup sequence
      EARLY_STRUCTURE      — NP_WEAK + active setup (forming, not just "weak")
      SETUP_PHASE          — active setup, trigger pending
      IMPULSE_ONLY         — impulse engine path (any strength), no structure
      BROKEN_STRUCTURE     — BROKEN_SETUP state (R20: -1.15% 5d, 33.3% WR — negative)
      TRUE_NONE            — NP_NONE + no structural or impulse signal
      DEGRADED             — NEUTRAL, FAILED_SETUP, OVEREXTENDED, ISOLATED_B2
    """
    advisory = []

    # ── Base score from sequence ──────────────────────────────────────────────
    score = _STRUCTURE_SCORE_MAP.get(seq_lbl, 15)

    # SETUP_ONLY_L34: moderate age 4-7 bars earns bonus (R20: MODERATE +3.17% vs FRESH +1.09%)
    if seq_lbl == "SETUP_ONLY_L34" and age_l34 is not None:
        if 3 < age_l34 <= 7:
            score += 10
            advisory.append("moderate_setup_age_strength")
        # FRESH (≤3) and STALE (>7): no bonus — do not auto-penalise

    # SETUP_ONLY_FRI34: same moderate-age bonus (FRI34 setup age uses fri34)
    if seq_lbl == "SETUP_ONLY_FRI34" and age_fri34 is not None:
        if 3 < age_fri34 <= 7:
            score += 8
            advisory.append("fri34_moderate_setup_age")

    # NP label modifier — no penalty for absent FRI34
    if np_label == "NEW_PUMP_STRONG":
        score += 15
    elif np_label == "NEW_PUMP_WEAK":
        score += 10
    elif np_label in ("NEW_PUMP_SETUP", "NEW_PUMP_TRIGGER_ONLY"):
        score += 5

    # Strong impulse modifier
    _strong_impulse = (
        impulse_label == "IMPULSE_STRONG" or (impulse_score or 0) >= 50
    )
    if engine_path == "impulse" and _strong_impulse:
        score += 15

    score = min(100, max(0, score))

    # ── Phase classification ──────────────────────────────────────────────────
    _CONFIRMED_SEQS = frozenset(("CONFIRM_AFTER_G4", "FULL_L34_G4_B2", "FULL_FRI34_G4_B2"))
    _TRIGGERED_SEQS = frozenset(("TRIGGER_AFTER_L34", "TRIGGER_AFTER_FRI34"))
    _SETUP_SEQS     = frozenset(("SETUP_ONLY_L34", "SETUP_ONLY_FRI34"))
    _has_setup      = (age_l34 is not None or age_fri34 is not None)

    if state in ("NEUTRAL", "FAILED_SETUP", "OVEREXTENDED") or seq_lbl == "ISOLATED_B2":
        phase = "DEGRADED"
    elif state == "BROKEN_SETUP":
        phase = "BROKEN_STRUCTURE"
    elif seq_lbl in _CONFIRMED_SEQS or state == "CONFIRMED":
        phase = "CONFIRMED_STRUCTURE"
    elif seq_lbl in _TRIGGERED_SEQS or state == "TRIGGERED":
        phase = "TRIGGERED_STRUCTURE"
    elif np_label == "NEW_PUMP_WEAK" and _has_setup and seq_lbl in _SETUP_SEQS:
        # WEAK + active setup = early structure forming, not merely "weak"
        phase = "EARLY_STRUCTURE"
        advisory.append("np_weak_with_setup_context")
    elif seq_lbl in _SETUP_SEQS:
        phase = "SETUP_PHASE"
    elif engine_path == "impulse":
        # Single canonical phase for all impulse-path candidates
        phase = "IMPULSE_ONLY"
    else:
        phase = "TRUE_NONE"

    return phase, score, advisory


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

    # R59: bullish engulfing count in last 20 bars — BOOST 2.0× vs false_positive
    bull_eng_count_20 = 0
    for _i in range(max(1, last - 19), last + 1):
        _pb = bars[_i - 1]; _cb = bars[_i]
        if (_cb["close"] > _cb["open"] and _pb["close"] < _pb["open"]
                and min(_cb["open"], _cb["close"]) <= min(_pb["open"], _pb["close"])
                and max(_cb["open"], _cb["close"]) >= max(_pb["open"], _pb["close"])):
            bull_eng_count_20 += 1

    # R59: extreme-anomaly day count in last 20 bars excluding today — PENALIZE (FP higher)
    extreme_anom_count_20 = 0
    if vol_mid is not None and vol_std is not None and vol_std > 0:
        for _j in range(max(0, last - 19), last):  # exclude today
            if (volumes[_j] - vol_mid) / vol_std > 3.5:
                extreme_anom_count_20 += 1

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

    # R59: B2 event count in last 20 bars — b2_count_pre PENALIZE (FP 2× more cycling B2 bars)
    b2_count_20 = sum(1 for b in tracking["b2_bars"] if last - b < 20)

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
        bull_eng_count_20=bull_eng_count_20,
        extreme_anom_count_20=extreme_anom_count_20,
        b2_count_20=b2_count_20,
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

    # v3.6: structure phase computed BEFORE _decide() — primary decision authority.
    structure_phase, structure_score, structure_advisory = _compute_structure_phase(
        seq_lbl=seq_lbl,
        state=state,
        engine_path=engine_path,
        np_label=capped_label,
        age_l34=age_l34,
        age_fri34=age_fri34,
        impulse_label=impulse["impulse_label"],
        impulse_score=impulse["impulse_score"],
    )

    # Final decision layer — now receives structure_phase + structure_score.
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
        np_label=capped_label,
        age_l34=age_l34,
        age_fri34=age_fri34,
        structure_phase=structure_phase,
        structure_score=structure_score,
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
        structure_phase=structure_phase,
        structure_score=structure_score,
        structure_advisory=structure_advisory,
        decision_authority="structure_phase_score",
        legacy_label_role="diagnostic_only",
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
