"""
Custom D/L/WLNBB Signal Layer — research-only add-on for Raw Pattern Discovery.

Defines the CUSTOM_SIGNAL and FLOW_CUSTOM_COMBINED feature families.

Tags are populated from pre-computed boolean flags stored in
raw_pattern_daily_features.feature_json by an upstream signal-computation
process.  The composite multi-bar tags (D4_THEN_BEUP_5B etc.) are derived
here from single-bar flags during the snapshot augmentation pass.

Production contract
-------------------
  RESEARCH_ONLY.  Do NOT route to Scanner V2 BUY/WATCH/AVOID.
  Do NOT promote to BUY.  Do NOT alter Pump Watch scoring.

Anti-leakage
------------
  Reads only PRE-window snapshot fields.  No outcome fields
  (pump_multiple, group_type, forward returns, etc.) are accessed.
"""

# ── Custom signal tag constants ───────────────────────────────────────────────

# L-level setup bars
CTAG_L22  = "L22"
CTAG_L34  = "L34"
CTAG_L43  = "L43"
CTAG_L64  = "L64"

# FRI setup bars
CTAG_FRI34 = "FRI34"
CTAG_FRI64 = "FRI64"

# D-breakout / entry bars
CTAG_D3_BEUP = "D3_BEUP"
CTAG_D4_BEUP = "D4_BEUP"
CTAG_D6_BEUP = "D6_BEUP"

# D + L single-bar combos
CTAG_D4_L34 = "D4_L34"
CTAG_D3_L34 = "D3_L34"

# Multi-bar composite tags — computed over 5-bar windows
CTAG_D3_THEN_BEUP_5B = "D3_THEN_BEUP_5B"
CTAG_D4_THEN_BEUP_5B = "D4_THEN_BEUP_5B"
CTAG_D6_THEN_BEUP_5B = "D6_THEN_BEUP_5B"

# Setup-only and trigger-state context
CTAG_SETUP_ONLY_L34      = "SETUP_ONLY_L34"
CTAG_SETUP_ONLY_FRI34    = "SETUP_ONLY_FRI34"
CTAG_TRIGGER_AFTER_L34   = "TRIGGER_AFTER_L34"
CTAG_TRIGGER_AFTER_FRI34 = "TRIGGER_AFTER_FRI34"

# Full-sequence confirmation tags (setup → trigger within 3 bars)
CTAG_FULL_L34_G4_B2   = "FULL_L34_G4_B2"
CTAG_FULL_FRI34_G4_B2 = "FULL_FRI34_G4_B2"
CTAG_CONFIRM_AFTER_G4 = "CONFIRM_AFTER_G4"

# Volume context
CTAG_VBO  = "VBO"
CTAG_LVBO = "LVBO"
CTAG_LD   = "LD"

# Fallback (no custom signal active)
CTAG_CUSTOM_FLAT = "CUSTOM_FLAT"

ALL_CUSTOM_TAGS: list[str] = [
    CTAG_L22, CTAG_L34, CTAG_L43, CTAG_L64,
    CTAG_FRI34, CTAG_FRI64,
    CTAG_D3_BEUP, CTAG_D4_BEUP, CTAG_D6_BEUP,
    CTAG_D4_L34, CTAG_D3_L34,
    CTAG_D3_THEN_BEUP_5B, CTAG_D4_THEN_BEUP_5B, CTAG_D6_THEN_BEUP_5B,
    CTAG_SETUP_ONLY_L34, CTAG_SETUP_ONLY_FRI34,
    CTAG_TRIGGER_AFTER_L34, CTAG_TRIGGER_AFTER_FRI34,
    CTAG_FULL_L34_G4_B2, CTAG_FULL_FRI34_G4_B2, CTAG_CONFIRM_AFTER_G4,
    CTAG_VBO, CTAG_LVBO, CTAG_LD,
]

# Tags that indicate a bullish breakout entry (any D-level signal)
_BEUP_TAGS: frozenset[str] = frozenset({
    CTAG_D3_BEUP, CTAG_D4_BEUP, CTAG_D6_BEUP,
})

# Map D-level tag → its 5-bar composite follow-through tag
_D_TO_THEN_BEUP: dict[str, str] = {
    CTAG_D3_BEUP: CTAG_D3_THEN_BEUP_5B,
    CTAG_D4_BEUP: CTAG_D4_THEN_BEUP_5B,
    CTAG_D6_BEUP: CTAG_D6_THEN_BEUP_5B,
}


# ── Single-bar tag derivation ─────────────────────────────────────────────────

def bars_to_custom_tags(snap: dict) -> list[str]:
    """
    Derive custom signal tags for one bar snapshot.

    Reads pre-populated boolean fields extracted from feature_json:
      has_l43, has_l34, has_l22, has_l64, has_fri34, has_fri64,
      has_d3_beup, has_d4_beup, has_d6_beup, has_d4_l34, has_d3_l34,
      has_vbo, has_lvbo, has_ld, np_is_setup, np_is_trigger.

    Returns sorted list of CTAG_* strings; [CTAG_CUSTOM_FLAT] when no
    signal is active.
    """
    tags: list[str] = []

    # L-level setups
    if snap.get("has_l43"):  tags.append(CTAG_L43)
    if snap.get("has_l34"):  tags.append(CTAG_L34)
    if snap.get("has_l22"):  tags.append(CTAG_L22)
    if snap.get("has_l64"):  tags.append(CTAG_L64)

    # FRI setups
    if snap.get("has_fri34"): tags.append(CTAG_FRI34)
    if snap.get("has_fri64"): tags.append(CTAG_FRI64)

    # D-breakout entries
    if snap.get("has_d3_beup"): tags.append(CTAG_D3_BEUP)
    if snap.get("has_d4_beup"): tags.append(CTAG_D4_BEUP)
    if snap.get("has_d6_beup"): tags.append(CTAG_D6_BEUP)

    # D + L single-bar combos (pre-computed upstream)
    if snap.get("has_d4_l34"): tags.append(CTAG_D4_L34)
    if snap.get("has_d3_l34"): tags.append(CTAG_D3_L34)

    # Setup / trigger state derived from NP flags + active L/FRI signal
    np_setup   = snap.get("np_is_setup")
    np_trigger = snap.get("np_is_trigger")
    has_l34    = snap.get("has_l34")
    has_fri34  = snap.get("has_fri34")

    if np_setup   and has_l34:  tags.append(CTAG_SETUP_ONLY_L34)
    if np_setup   and has_fri34: tags.append(CTAG_SETUP_ONLY_FRI34)
    if np_trigger and has_l34:  tags.append(CTAG_TRIGGER_AFTER_L34)
    if np_trigger and has_fri34: tags.append(CTAG_TRIGGER_AFTER_FRI34)

    # Volume context
    if snap.get("has_vbo"):  tags.append(CTAG_VBO)
    if snap.get("has_lvbo"): tags.append(CTAG_LVBO)
    if snap.get("has_ld"):   tags.append(CTAG_LD)

    result = sorted(set(tags))
    return result if result else [CTAG_CUSTOM_FLAT]


# ── Multi-bar augmentation ────────────────────────────────────────────────────

def build_custom_signal_tags(snapshots: list[dict]) -> list[dict]:
    """
    Augment bar snapshots with custom signal tags (in-place).

    Pass 1 — Single-bar: sets custom_tags / custom_tag_signature from
              feature_json boolean flags via bars_to_custom_tags().

    Pass 2 — 5-bar composite: D_THEN_BEUP_5B
              If D3/D4/D6_BEUP on bar i and any BEUP tag appears on
              bars i+1..i+4, mark bar i with the composite tag.

    Pass 3 — 3-bar full-sequence: FULL_L34_G4_B2 / FULL_FRI34_G4_B2
              L34/FRI34 on bar i followed by TRIGGER_AFTER or D4_BEUP
              within 3 bars → mark bar i with the FULL tag.

    Pass 4 — 1-bar confirmation: CONFIRM_AFTER_G4
              Bar immediately after a G4-context bar (D4_BEUP or D4_L34)
              that itself shows another BEUP or trigger signal.

    Pass 5 — Re-sort, merge flow_custom_combined_tags (sorted union of
              flow_tags + custom_tags, FLAT markers excluded).

    Anti-leakage: reads only snap["flow_tags"] and the has_* boolean
    fields.  Never reads group_type, pump_multiple, or future returns.
    """
    if not snapshots:
        return snapshots

    n = len(snapshots)

    # ── Pass 1: single-bar custom tags ────────────────────────────────────────
    for snap in snapshots:
        ct = bars_to_custom_tags(snap)
        snap["custom_tags"]          = ct
        snap["custom_tag_signature"] = "+".join(ct)

    # ── Pass 2: D_THEN_BEUP_5B composite ─────────────────────────────────────
    for i in range(n):
        snap_tags = set(snapshots[i].get("custom_tags") or [])
        for d_tag, composite in _D_TO_THEN_BEUP.items():
            if d_tag not in snap_tags:
                continue
            # Look ahead up to 4 bars for any BEUP tag
            for j in range(i + 1, min(i + 5, n)):
                future = set(snapshots[j].get("custom_tags") or [])
                if future & _BEUP_TAGS:
                    snapshots[i]["custom_tags"].append(composite)
                    break

    # ── Pass 3: FULL_L34/FRI34_G4_B2 (setup → trigger within 3 bars) ─────────
    _trigger_or_entry = {CTAG_TRIGGER_AFTER_L34, CTAG_TRIGGER_AFTER_FRI34,
                         CTAG_D4_BEUP, CTAG_D3_BEUP}
    for i in range(n):
        snap_tags = set(snapshots[i].get("custom_tags") or [])
        if CTAG_L34 in snap_tags:
            for j in range(i + 1, min(i + 4, n)):
                if set(snapshots[j].get("custom_tags") or []) & _trigger_or_entry:
                    snapshots[i]["custom_tags"].append(CTAG_FULL_L34_G4_B2)
                    break
        if CTAG_FRI34 in snap_tags:
            for j in range(i + 1, min(i + 4, n)):
                if set(snapshots[j].get("custom_tags") or []) & _trigger_or_entry:
                    snapshots[i]["custom_tags"].append(CTAG_FULL_FRI34_G4_B2)
                    break

    # ── Pass 4: CONFIRM_AFTER_G4 ──────────────────────────────────────────────
    _g4_context  = {CTAG_D4_BEUP, CTAG_D4_L34}
    _confirm_set = {CTAG_D4_BEUP, CTAG_D3_BEUP, CTAG_TRIGGER_AFTER_L34, CTAG_TRIGGER_AFTER_FRI34}
    for i in range(n - 1):
        if set(snapshots[i].get("custom_tags") or []) & _g4_context:
            if set(snapshots[i + 1].get("custom_tags") or []) & _confirm_set:
                snapshots[i + 1]["custom_tags"].append(CTAG_CONFIRM_AFTER_G4)

    # ── Pass 5: re-sort, re-sign, build flow_custom_combined ──────────────────
    for snap in snapshots:
        ct = sorted(set(snap.get("custom_tags") or [CTAG_CUSTOM_FLAT]))
        snap["custom_tags"]          = ct
        snap["custom_tag_signature"] = "+".join(ct)

        # Merge flow + custom, stripping FLAT sentinel values from both
        flow_tags   = [t for t in (snap.get("flow_tags") or []) if t != "FLAT"]
        custom_tags = [t for t in ct if t != CTAG_CUSTOM_FLAT]
        merged = sorted(set(flow_tags + custom_tags))
        if not merged:
            merged = ["FLAT"]
        snap["flow_custom_combined_tags"]          = merged
        snap["flow_custom_combined_tag_signature"] = "+".join(merged)

    return snapshots
