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

    # Full-sequence bonus sharply cut — replay FULL_* both negative
    # TRIGGER_AFTER_* bonuses mildly increased — replay positive
    if good_fri34 and good_b2:
        return 4
    if good_l34 and good_b2:
        return 3
    if good_fri34:
        return 9             # TRIGGER_AFTER_FRI34 avg +2.3%
    if good_l34:
        return 7             # TRIGGER_AFTER_L34 positive
    return 0


def _modifier_score(age_l34, age_fri34, age_g4, age_b2,
                    ema20, ema50, ema200, close, volume_z, body_ratio, dv_ratio):
    mod = 0

    # --- Positive modifiers ---

    # 1. Bull stack persistence (up to +8)
    ema20_ok  = ema20  is not None
    ema50_ok  = ema50  is not None
    ema200_ok = ema200 is not None
    if ema20_ok and ema50_ok and ema200_ok and ema20 > ema50 > ema200:
        mod += 8
    elif ema20_ok and ema50_ok and ema20 > ema50:
        mod += 4
    elif ema20_ok and ema200_ok and ema20 > ema200:
        mod += 2

    # 2. Moderate expansion context (up to +4): body ratio 1.2x–2.5x is constructive
    if body_ratio is not None:
        if 1.2 <= body_ratio <= 2.5:
            mod += 4
        elif 1.0 <= body_ratio < 1.2:
            mod += 2

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

    # --- Negative modifiers ---

    # 5. Ultra-extreme anomaly spike (up to -8)
    if volume_z is not None:
        if volume_z > 4.0:
            mod -= 8
        elif volume_z > 3.5:
            mod -= 5
        elif volume_z > 3.0:
            mod -= 3

    # 6. Wide EMA spread penalty (up to -6): EMA20 vs EMA200
    if ema20_ok and ema200_ok and ema200 > 0:
        spread_pct = (ema20 - ema200) / ema200 * 100
        if spread_pct > 50:
            mod -= 6
        elif spread_pct > 30:
            mod -= 4
        elif spread_pct > 20:
            mod -= 2

    # 7. Overly extended above EMA200 (up to -4)
    if ema200_ok and ema200 > 0:
        ext = close / ema200
        if ext > 1.5:
            mod -= 4
        elif ext > 1.3:
            mod -= 2

    # 8. Stale setup penalty (up to -4)
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

    # 9. Isolated B2 penalty (up to -6)
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
    )


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

    # Scores
    setup_score   = _setup_score(age_l34, age_fri34, count_l34_w, count_fri34_w)
    trigger_score = _trigger_score(age_g4, age_l34, age_fri34)
    confirm_score = _confirm_score(age_b2, age_g4, age_l34, age_fri34)
    seq_bonus     = _sequence_bonus(age_l34, age_fri34, age_g4, age_b2)
    mod_score     = _modifier_score(
        age_l34, age_fri34, age_g4, age_b2,
        ema20, ema50, ema200, closes[last],
        volume_z, body_ratio, dv_ratio,
    )

    total = max(0, setup_score + trigger_score + confirm_score + seq_bonus + mod_score)

    return dict(
        has_l34=has_l34, has_fri34=has_fri34, has_g4=has_g4, has_b2=has_b2,
        age_l34=age_l34, age_fri34=age_fri34, age_g4=age_g4, age_b2=age_b2,
        new_pump_setup_score=setup_score,
        new_pump_trigger_score=trigger_score,
        new_pump_confirm_score=confirm_score,
        new_pump_modifier_score=mod_score,
        new_pump_score=total,
        new_pump_sequence_label=_sequence_label(age_l34, age_fri34, age_g4, age_b2),
        new_pump_label=_final_label(total),
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
