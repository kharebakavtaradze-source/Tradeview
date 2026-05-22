"""
Unified scoring configuration for the Demand Composite Scanner.
Edit signal scores here and re-run any studio — no other code changes needed.
Bump VERSION after each meaningful change so runs can be compared by config version.
"""

VERSION = "v3"

SIGNALS: dict[str, dict] = {
    # ── Gap signals ───────────────────────────────────────────────────────────
    "GAP_GTE_100PCT":     {"score": +3, "enabled": True, "group": "gap",      "desc": "Gap ≥100% in last 5 bars (6.18x lift, R92)"},
    "GAP_GTE_50PCT":      {"score": +1, "enabled": True, "group": "gap",      "desc": "Gap ≥50% in last 5 bars (2.97x lift, R92)"},
    # ── Volume anomaly ────────────────────────────────────────────────────────
    "VOL_ANOMALY_500X":   {"score": +2, "enabled": True, "group": "volume",   "desc": "Volume ≥500x avg in last 5 bars (2.95x lift, R92)"},
    "VOL_ANOMALY_100X":   {"score": +1, "enabled": True, "group": "volume",   "desc": "Volume ≥100x avg in last 5 bars (2.42x lift, R92)"},
    # ── VIX / PSAR / RSI2 combos ──────────────────────────────────────────────
    "VX_PS_R2X_BREAKOUT": {"score": +2, "enabled": True, "group": "momentum", "desc": "VX+PSAR+RSI2-extreme breakout setup (3.27x lift, R92)"},
    "PS_R2L_SETUP":       {"score": +1, "enabled": True, "group": "momentum", "desc": "PSAR bull + RSI2 low, no VX — pullback setup"},
    # ── Preup (EMA stack aligning) ────────────────────────────────────────────
    "PREUP_P55":          {"score": +2, "enabled": True, "group": "preup",    "desc": "EMA55 stack aligning bullish (+2.17 alpha, R42)"},
    "PREUP_NOW":          {"score": +1, "enabled": True, "group": "preup",    "desc": "EMA stack aligning (not P55/P89)"},
    "PREUP_RECENT":       {"score": +1, "enabled": True, "group": "preup",    "desc": "EMA stack aligned in prev/prev2 bar"},
    "PREUP_P89_LATE":     {"score": -1, "enabled": True, "group": "preup",    "desc": "EMA89 already extended (-0.73 alpha, R42)"},
    # ── T/Z signals ───────────────────────────────────────────────────────────
    "T1T2_BAR":           {"score": +1, "enabled": True, "group": "tz",       "desc": "T1/T2 demand bar in last 3 bars"},
    "BEARISH_TZ_T10":     {"score": -2, "enabled": True, "group": "tz",       "desc": "T10 bearish distribution bar (-1.97 alpha, R42)"},
    "BEARISH_TZ_T11":     {"score": -2, "enabled": True, "group": "tz",       "desc": "T11 bearish distribution bar (-1.41 alpha, R42)"},
    "BEARISH_TZ_RECENT":  {"score": -1, "enabled": True, "group": "tz",       "desc": "T10/T11 in prev/prev2 bar"},
    # ── WLNBB ─────────────────────────────────────────────────────────────────
    "WLNBB_L":            {"score": +1, "enabled": True, "group": "wlnbb",    "desc": "Still in Bollinger squeeze (L bucket)"},
    # ── Pump state ────────────────────────────────────────────────────────────
    "NEW_PUMP_STRONG":    {"score": -2, "enabled": True, "group": "pump",     "desc": "Already extended, -1.72 alpha (R42)"},
}

THRESHOLDS: dict[str, float] = {
    "gap_100_pct": 100.0,
    "gap_50_pct":   50.0,
    "vol_500x":    500.0,
    "vol_100x":    100.0,
}


def get_score(signal: str) -> int:
    """Return the score for a named signal. Returns 0 if unknown or disabled."""
    cfg = SIGNALS.get(signal)
    if not cfg or not cfg.get("enabled", True):
        return 0
    return int(cfg["score"])


def as_dict() -> dict:
    """Serialise the full config for API responses and run storage."""
    return {
        "version":    VERSION,
        "signals":    SIGNALS,
        "thresholds": THRESHOLDS,
    }
