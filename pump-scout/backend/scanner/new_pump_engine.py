"""
New Pump Engine
Thinks in order: Setup -> Trigger -> Confirmation
Components: L34, FRI34, G4, B2
"""

MIN_BODY_RATIO = 1.0
SETUP_STALENESS = 5  # bars before a setup is considered stale


def _bar_primitives(bars, i):
    """Extract bar primitives for index i (current) and i-1 (previous)."""
    c_bar = bars[i]
    p_bar = bars[i - 1] if i > 0 else None

    o = c_bar["open"]
    h = c_bar["high"]
    l = c_bar["low"]
    c = c_bar["close"]
    v = c_bar["volume"]

    body = abs(c - o)
    cTop = max(o, c)
    cBot = min(o, c)

    isBull = c > o
    isBear = c < o
    isDoji = c == o

    result = dict(o=o, h=h, l=l, c=c, v=v, body=body,
                  cTop=cTop, cBot=cBot, isBull=isBull, isBear=isBear, isDoji=isDoji)

    if p_bar is not None:
        o1 = p_bar["open"]
        h1 = p_bar["high"]
        l1 = p_bar["low"]
        c1 = p_bar["close"]
        v1 = p_bar["volume"]

        pbody = abs(c1 - o1)
        pTop = max(o1, c1)
        pBot = min(o1, c1)

        p1Bull = c1 > o1
        p1Bear = c1 <= o1

        engOk = (
            pbody > 0
            and pbody > 0 and body / pbody >= MIN_BODY_RATIO
            and cTop >= pTop
            and pBot >= cBot
        )

        insOk = cTop <= pTop and cBot >= pBot

        result.update(dict(
            o1=o1, h1=h1, l1=l1, c1=c1, v1=v1,
            pbody=pbody, pTop=pTop, pBot=pBot,
            p1Bull=p1Bull, p1Bear=p1Bear,
            engOk=engOk, insOk=insOk,
        ))
    else:
        result.update(dict(
            o1=None, h1=None, l1=None, c1=None, v1=None,
            pbody=0, pTop=0, pBot=0,
            p1Bull=False, p1Bear=True,
            engOk=False, insOk=False,
        ))

    return result


def _is_L34(p):
    """
    L34 — quiet bullish setup.
    A bearish or doji bar followed by a small inside or near-inside bar
    that holds the previous bar's body range, signaling quiet compression
    before a potential move up.
    Conditions:
      - previous bar is bearish (p1Bear)
      - current bar is inside previous bar (insOk) OR body is small relative to previous
      - current bar is not strongly bearish itself (not a strong down continuation)
    """
    if not p["p1Bear"]:
        return False
    if not p["insOk"]:
        return False
    # Current bar should not be a strong bearish continuation
    if p["isBear"] and p["pbody"] > 0 and p["body"] / p["pbody"] >= 0.8:
        return False
    return True


def _is_FRI34(p):
    """
    FRI34 — stronger validated setup.
    A bearish bar followed by a bullish engulfing bar that fully recovers
    the prior body, showing buyers stepping in with conviction.
    Conditions:
      - previous bar is bearish (p1Bear)
      - current bar is bullish (isBull)
      - current bar body engulfs previous bar body (engOk)
    """
    return p["p1Bear"] and p["isBull"] and p["engOk"]


def _is_G4(p):
    """
    G4 — bullish reversal trigger.
    A strong bullish bar that breaks above recent compression/bearish structure.
    Conditions:
      - current bar is bullish (isBull)
      - body is substantial (body > pbody * 0.6, i.e., meaningful thrust)
      - current bar closes above previous bar top (cTop > pTop) — breaks structure
    """
    if not p["isBull"]:
        return False
    if p["pbody"] > 0 and p["body"] / p["pbody"] < 0.6:
        return False
    if p["pTop"] > 0 and p["cTop"] <= p["pTop"]:
        return False
    return True


def _is_B2(p):
    """
    B2 — bullish confirmation / continuation.
    A follow-through bullish bar that holds above previous bar's body,
    confirming the move without needing a full engulf.
    Conditions:
      - current bar is bullish (isBull)
      - current bar does not undercut previous bar bottom (cBot >= pBot)
      - body is meaningful (not a doji)
    """
    return p["isBull"] and not p["isDoji"] and p["cBot"] >= p["pBot"]


def _is_chaotic_spike(p):
    """Detect an isolated extreme spike with no body structure (wick >> body)."""
    bar_range = p["h"] - p["l"]
    if bar_range == 0:
        return False
    wick_ratio = (bar_range - p["body"]) / bar_range
    return wick_ratio > 0.85


def run(bars):
    """
    Run the New Pump engine over a list of bar dicts.

    Each bar dict must have keys: open, high, low, close, volume.
    Bars are ordered oldest-first.

    Returns a list of signal dicts, one per bar index where a signal fires.
    Signal fields:
      - index: bar index
      - sequence: e.g. "L34->G4->B2"
      - strength: "strong" | "moderate" | "weak"
      - components: list of component names active at this bar
      - reason: short explanation string
    """
    signals = []

    # Track setup state
    setup_bar = None      # index where a setup (L34 or FRI34) last fired
    setup_type = None     # "L34" or "FRI34"
    trigger_bar = None    # index where G4 last fired (after a valid setup)

    for i in range(1, len(bars)):
        p = _bar_primitives(bars, i)

        active = []

        # --- SETUP PHASE ---
        if _is_L34(p):
            active.append("L34")
            setup_bar = i
            setup_type = "L34"
            trigger_bar = None  # reset trigger when new setup appears

        if _is_FRI34(p):
            active.append("FRI34")
            setup_bar = i
            setup_type = "FRI34"
            trigger_bar = None

        # --- TRIGGER PHASE ---
        if _is_G4(p):
            setup_age = (i - setup_bar) if setup_bar is not None else None
            setup_fresh = setup_age is not None and 1 <= setup_age <= SETUP_STALENESS
            chaotic = _is_chaotic_spike(p)

            if setup_fresh and not chaotic:
                active.append("G4")
                trigger_bar = i
            elif not setup_fresh:
                # Isolated G4 — weak signal
                active.append("G4")
                signals.append({
                    "index": i,
                    "sequence": "G4",
                    "strength": "weak",
                    "components": ["G4"],
                    "reason": "isolated G4 with no recent setup",
                })
                continue
            # chaotic spike: skip silently

        # --- CONFIRMATION PHASE ---
        if _is_B2(p):
            trigger_age = (i - trigger_bar) if trigger_bar is not None else None
            trigger_fresh = trigger_age is not None and 1 <= trigger_age <= 3

            if trigger_fresh:
                active.append("B2")
            else:
                # Isolated B2 — skip
                continue

        # --- EMIT SIGNAL ---
        if not active:
            continue

        has_setup = "L34" in active or "FRI34" in active
        has_trigger = "G4" in active
        has_confirm = "B2" in active

        if has_setup and has_trigger and has_confirm:
            seq = f"{setup_type}->G4->B2"
            strength = "strong"
            reason = f"full sequence: {seq}"
        elif has_setup and has_trigger:
            seq = f"{setup_type}->G4"
            strength = "moderate"
            reason = f"setup+trigger: {seq}"
        elif has_setup:
            seq = setup_type
            strength = "weak"
            reason = f"setup only: {seq}, awaiting trigger"
        else:
            continue  # no meaningful sequence

        signals.append({
            "index": i,
            "sequence": seq,
            "strength": strength,
            "components": list(active),
            "reason": reason,
        })

    return signals
