"""
Stock Universe Filter
=====================
Hard **allowlist** filter — only common stocks (CS, ADR, ADRC, ADRW, ADRR)
are permitted in the scan universe.  Every other instrument type is excluded
by default.

This is the single source of truth for what counts as a "common stock" in
Pump Scout.  Applied consistently across:

  - live universe scan       (scanner/universe_scan.py)
  - historical replay scan   (replay/replay_engine.py)
  - missed mover analysis    (replay/outcome_engine.py)
  - Pump Engine / Ribbon / Ignition endpoints (via _strip_non_stocks in main.py)

STRICTNESS RULE
---------------
If the Polygon ``type`` field is absent, empty, or not in COMMON_STOCK_TYPES,
the symbol is EXCLUDED.  Do not guess; do not keep ambiguous symbols "just in
case".

Filter reason codes
-------------------
``None``                → include (confirmed common stock)
``NOT_COMMON_STOCK``    → type is known but is not common equity
``ETF``                 → exchange-traded fund
``ETN``                 → exchange-traded note (incl. ETV)
``CEF``                 → closed-end fund
``MUTUAL_FUND``         → open-end mutual fund (FUND / MF)
``BOND_FUND``           → bond ETF or fixed-income fund
``LEVERAGED_PRODUCT``   → leveraged product
``INVERSE_PRODUCT``     → inverse product
``CRYPTO_ETF``          → crypto ETP / crypto-backed ETF
``WARRANT``             → warrant, right, subscription receipt
``PREFERRED_STOCK``     → preferred equity (not common)
``UNIT``                → trust unit / split-structure unit
``STRUCTURED_PRODUCT``  → structured or synthetic product
``UNKNOWN_SECURITY_TYPE``  → type not returned by provider (absent / null)
"""

import logging

logger = logging.getLogger(__name__)

# ── Allowlist: Polygon types that represent common equity ─────────────────────
# ONLY symbols whose Polygon "type" is one of these pass the universe filter.

COMMON_STOCK_TYPES: frozenset[str] = frozenset({
    "CS",     # Common Stock
    "ADR",    # American Depositary Receipt — foreign company on US exchange
    "ADRC",   # ADR — Common Share class
    "ADRW",   # ADR — Warrant
    "ADRR",   # ADR — Right
})

# Backwards-compatibility alias used by massive_data.py (EQUITY_TYPES)
# and any other code that imports it directly.
EQUITY_TYPES: frozenset[str] = COMMON_STOCK_TYPES


# ── Polygon type → exclusion reason code ─────────────────────────────────────

_POLYGON_TYPE_TO_REASON: dict[str, str] = {
    "ETF":     "ETF",
    "ETN":     "ETN",
    "ETV":     "ETN",           # exchange-traded vehicle = same exclusion class
    "CEF":     "CEF",
    "FUND":    "MUTUAL_FUND",
    "MF":      "MUTUAL_FUND",
    "SP":      "STRUCTURED_PRODUCT",
    "WARRANT": "WARRANT",
    "RIGHT":   "WARRANT",
    "UNIT":    "UNIT",
    "BOND":    "BOND_FUND",
    "NOTE":    "ETN",
    "PFD":     "PREFERRED_STOCK",
    "OS":      "NOT_COMMON_STOCK",   # some foreign ordinary-share listings
    "LTD":     "NOT_COMMON_STOCK",
}


# ── Public helpers ────────────────────────────────────────────────────────────

def is_common_stock(symbol_meta: dict) -> bool:
    """
    Return True only if *symbol_meta* represents a common equity.

    Parameters
    ----------
    symbol_meta : dict containing at least a ``"type"`` key, e.g.
                  ``{"type": "CS", "ticker": "AAPL", ...}``.
                  Polygon reference API returns this under ``results.type``.

    Returns
    -------
    bool
        ``True``  → include in universe (confirmed common stock)
        ``False`` → exclude (not a common stock, or type is absent/unknown)

    Strictness: an absent or null ``type`` returns ``False`` — unknown
    symbols are excluded, not kept.
    """
    ticker_type = (symbol_meta.get("type") or "").strip().upper()
    if not ticker_type:
        return False          # unknown → exclude by default
    return ticker_type in COMMON_STOCK_TYPES


def get_universe_filter_reason(symbol_meta: dict) -> str | None:
    """
    Return the exclusion reason for *symbol_meta*, or ``None`` if the symbol
    is a common stock and should be included.

    Parameters
    ----------
    symbol_meta : dict containing at least a ``"type"`` key.

    Returns
    -------
    ``None``  → symbol is a confirmed common stock; include in universe.
    ``str``   → exclusion reason code (see module-level docstring).
    """
    ticker_type = (symbol_meta.get("type") or "").strip().upper()

    if not ticker_type:
        return "UNKNOWN_SECURITY_TYPE"

    if ticker_type in COMMON_STOCK_TYPES:
        return None            # confirmed common stock

    reason = _POLYGON_TYPE_TO_REASON.get(ticker_type)
    return reason or "NOT_COMMON_STOCK"
