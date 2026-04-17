"""
New Pump Engine
Thinks in order: Setup -> Trigger -> Confirmation
Components: L34, FRI34, G4, B2
"""

MIN_BODY_RATIO = 1.0
SETUP_STALENESS = 5


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

    gains = [max(closes[j] - closes[j - 1], 0) for j in range(1, len(closes))]
    losses = [max(closes[j - 1] - closes[j], 0) for j in range(1, len(closes))]

    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def _rs_to_rsi(ag, al):
        return 100.0 if al == 0 else 100 - 100 / (1 + ag / al)

    rsi[period] = _rs_to_rsi(avg_gain, avg_loss)
    for j in range(period + 1, len(closes)):
        avg_gain = (avg_gain * (period - 1) + gains[j - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[j - 1]) / period
        rsi[j] = _rs_to_rsi(avg_gain, avg_loss)

    return rsi


# ---------------------------------------------------------------------------
# Bar primitives
# ---------------------------------------------------------------------------

def _bar_primitives(bars, i):
    """Return dict of all bar primitives for bar i (current) and i-1 (previous)."""
    cb = bars[i]
    pb = bars[i - 1]

    o  = cb["open"];  h  = cb["high"];  l  = cb["low"];  c  = cb["close"];  v  = cb["volume"]
    o1 = pb["open"];  h1 = pb["high"];  l1 = pb["low"];  c1 = pb["close"];  v1 = pb["volume"]

    body  = abs(c - o)
    pbody = abs(c1 - o1)
    cTop  = max(o, c);   cBot  = min(o, c)
    pTop  = max(o1, c1); pBot  = min(o1, c1)

    isBull = c > o;  isBear = c < o;  isDoji = c == o
    p1Bull = c1 > o1
    p1Bear = c1 <= o1

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
    """
    L34 — quiet bullish setup.
    Rising participation, price improves vs prev close,
    but not yet breaking prev high.
    """
    return (
        p["v"] > p["v1"]
        and p["c"] > p["c1"]
        and p["c"] <= p["h1"]
        and p["c"] >= p["o"]
    )


def _sig_BLUE(p, volume_z, rsi_range3):
    """
    BLUE — internal helper: volume spike without chaotic RSI expansion.
    """
    if volume_z is None or rsi_range3 is None:
        return False
    return volume_z >= 1.1 and rsi_range3 <= 5.0


def _sig_FRI34(l34, blue):
    """FRI34 — stronger validated setup: BLUE + L34."""
    return blue and l34


# ---------------------------------------------------------------------------
# T-signals (bullish)
# ---------------------------------------------------------------------------

def _t_signals(p):
    o, c, o1, c1 = p["o"], p["c"], p["o1"], p["c1"]
    bull, p1bull, p1bear = p["isBull"], p["p1Bull"], p["p1Bear"]
    eng, ins = p["engOk"], p["insOk"]

    t1g = p1bear and o > c1 and o > o1 and c > o1 and bull
    t1  = p1bear and o >= c1 and o1 >= o and c > o1 and bull
    t2g = p1bull and o >= o1 and o > c1 and c > c1 and bull
    t2  = p1bull and o >= o1 and o <= c1 and c > c1 and bull
    t3  = p1bear and bull and o < o1 and o < c1 and c < o1 and c > c1
    t4  = p1bear and bull and eng
    t6  = p1bull and bull and eng
    t10 = p1bull and bull and ins
    t11 = p1bull and bull and o < o1 and c >= o1 and c < c1

    return dict(T1G=t1g, T1=t1, T2G=t2g, T2=t2,
                T3=t3, T4=t4, T6=t6, T10=t10, T11=t11)


# ---------------------------------------------------------------------------
# Z-signals (bearish)
# ---------------------------------------------------------------------------

def _z_signals(p):
    o, c, o1, c1 = p["o"], p["c"], p["o1"], p["c1"]
    bear, p1bear, p1bull = p["isBear"], p["p1Bear"], p["p1Bull"]
    eng, ins = p["engOk"], p["insOk"]

    z2g = p1bear and o <= o1 and o < c1 and c < c1 and bear
    z6  = p1bear and bear and eng
    z10 = p1bear and bear and ins
    z11 = p1bear and bear and o > o1 and (c > c1 or c > o1)
    z12 = p1bull and o <= o1 and bear

    return dict(Z2G=z2g, Z6=z6, Z10=z10, Z11=z11, Z12=z12)


# ---------------------------------------------------------------------------
# G4 state machine
# ---------------------------------------------------------------------------

def _update_g4(g_armed, t, z):
    """
    Arm on Z10 | Z11 | Z12.
    G4 fires when armed and T4 is the first resolving bullish trigger.
    T1, T1G, T4, T6 all consume the armed state.
    Returns (g4_fired, new_g_armed).
    """
    if z["Z10"] or z["Z11"] or z["Z12"]:
        g_armed = True

    g4 = False
    if g_armed:
        if t["T4"]:
            g4 = True
            g_armed = False
        elif t["T1"] or t["T1G"] or t["T6"]:
            g_armed = False

    return g4, g_armed


# ---------------------------------------------------------------------------
# B2 confirmation
# ---------------------------------------------------------------------------

_B2_BRANCH1_CODES = {"T1", "T1G", "T2", "T2G", "T3", "T4", "T6", "T10", "T11"}
_B2_BRANCH2_CODES = {"T1", "T1G", "T2G", "T3", "T4", "T6", "T10", "T11"}


def _sig_B2(i, t, z, history):
    """
    B2 — bullish confirmation / continuation.
    Branches check prior bar codes (history dict: index -> frozenset).
    """
    def h(idx):
        return history.get(idx, frozenset())

    b2 = False

    if t["T4"]:
        # Branch 1: any T-code two bars ago
        if h(i - 2) & _B2_BRANCH1_CODES:
            b2 = True
        # Branch 4: T3 three bars ago
        if "T3" in h(i - 3):
            b2 = True
        # Branch 5: T3 six bars ago
        if "T3" in h(i - 6):
            b2 = True
        # Branch 6: Z2G one bar ago
        if "Z2G" in h(i - 1):
            b2 = True
        # Branch 7: Z6 one or two bars ago
        if "Z6" in h(i - 1) or "Z6" in h(i - 2):
            b2 = True

    if t["T6"]:
        # Branch 2: any T-code one bar ago
        if h(i - 1) & _B2_BRANCH2_CODES:
            b2 = True
        # Branch 3: T11 two bars ago
        if "T11" in h(i - 2):
            b2 = True

    return b2


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run(bars):
    """
    Run the New Pump engine over a list of bar dicts (oldest-first).

    Each bar dict must have keys: open, high, low, close, volume.

    Returns a list of signal dicts:
      - index     : bar index
      - sequence  : e.g. "FRI34->G4->B2"
      - strength  : "strong" | "moderate" | "weak"
      - components: list of component names active at this bar
      - reason    : short explanation string
    """
    n = len(bars)
    if n < 2:
        return []

    closes  = [b["close"]  for b in bars]
    volumes = [b["volume"] for b in bars]
    rsi_series = _compute_rsi(closes)

    signals  = []
    history  = {}   # i -> frozenset of code names that fired at bar i
    g_armed  = False

    # Setup tracking for sequence labeling
    setup_bar  = None
    setup_type = None
    trigger_bar = None

    for i in range(1, n):
        p = _bar_primitives(bars, i)

        # --- Volume stats for BLUE ---
        vol_window = volumes[max(0, i - 19): i + 1]
        vol_mid = _sma(vol_window, 20)
        vol_std = _std(vol_window, 20)
        volume_z = None
        if vol_mid is not None and vol_std is not None and vol_std > 0:
            volume_z = (p["v"] - vol_mid) / vol_std

        # RSI range over last 3 bars including current
        rsi_range3 = None
        if i >= 2:
            rsi_vals = [rsi_series[j] for j in (i - 2, i - 1, i) if rsi_series[j] is not None]
            if len(rsi_vals) == 3:
                rsi_range3 = max(rsi_vals) - min(rsi_vals)

        # --- Compute all sub-signals ---
        t = _t_signals(p)
        z = _z_signals(p)

        l34  = _sig_L34(p)
        blue = _sig_BLUE(p, volume_z, rsi_range3)
        fri34 = _sig_FRI34(l34, blue)

        g4, g_armed = _update_g4(g_armed, t, z)
        b2 = _sig_B2(i, t, z, history)

        # --- Record all codes for this bar (for B2 lookback) ---
        bar_codes = set()
        if l34:   bar_codes.add("L34")
        if fri34: bar_codes.add("FRI34")
        for name, fired in t.items():
            if fired: bar_codes.add(name)
        for name, fired in z.items():
            if fired: bar_codes.add(name)
        if g4: bar_codes.add("G4")
        if b2: bar_codes.add("B2")
        history[i] = frozenset(bar_codes)

        # --- Setup tracking ---
        if fri34:
            setup_bar = i; setup_type = "FRI34"; trigger_bar = None
        elif l34:
            setup_bar = i; setup_type = "L34"; trigger_bar = None

        setup_age = (i - setup_bar) if setup_bar is not None else None
        setup_fresh = setup_age is not None and 1 <= setup_age <= SETUP_STALENESS

        if g4 and setup_fresh:
            trigger_bar = i

        trigger_age = (i - trigger_bar) if trigger_bar is not None else None
        trigger_fresh = trigger_age is not None and 1 <= trigger_age <= 3

        # --- Classify and emit ---
        active_components = []
        if fri34:  active_components.append("FRI34")
        elif l34:  active_components.append("L34")
        if g4:     active_components.append("G4")
        if b2:     active_components.append("B2")

        has_setup   = l34 or fri34
        has_trigger = g4
        has_confirm = b2

        if has_setup and has_trigger and has_confirm:
            seq      = f"{setup_type}->G4->B2"
            strength = "strong"
            reason   = f"full sequence: {seq}"
        elif has_setup and has_trigger:
            seq      = f"{setup_type}->G4"
            strength = "moderate"
            reason   = f"setup+trigger: {seq}"
        elif has_trigger and has_confirm:
            # trigger+confirm without same-bar setup — use most recent setup label
            prior_label = setup_type if setup_fresh else None
            seq      = f"{prior_label}->G4->B2" if prior_label else "G4->B2"
            strength = "strong" if prior_label else "moderate"
            reason   = f"trigger+confirmation: {seq}"
        elif has_trigger:
            # G4 with no fresh setup
            seq      = f"{setup_type}->G4" if setup_fresh else "G4"
            strength = "moderate" if setup_fresh else "weak"
            reason   = f"trigger {'with' if setup_fresh else 'without'} setup: {seq}"
        elif has_confirm and trigger_fresh:
            # B2 after recent trigger
            seq      = "->B2"
            strength = "moderate"
            reason   = "confirmation after recent trigger"
        elif has_setup:
            # setup only — log, await trigger
            seq      = setup_type
            strength = "weak"
            reason   = f"setup only: {seq}, awaiting trigger"
        else:
            continue

        signals.append({
            "index":      i,
            "sequence":   seq,
            "strength":   strength,
            "components": active_components,
            "reason":     reason,
        })

    return signals
