"""
Sector Resolver v2
==================
Multi-source GICS sector + industry resolution with coverage metrics.

Resolution priority (highest to lowest confidence):
  1. Static SECTOR_MAP     — hard-coded for 200+ known tickers
  2. UniverseCache         — sic_description from Massive reference sync
  3. Raw provider sector   — normalised through FINVIZ_TO_GICS
  4. SIC description kw    — keyword scan of sic_description text
  5. SIC code range        — coarse mapping from 2-4 digit SIC code
  6. UNKNOWN               — cannot be determined

resolve() never raises.  Returns (gics_sector, industry, source_label).

Coverage metrics:
  compute_coverage(rows) → {
      sector_context_present_pct,   # any sector_context attached
      sector_known_pct,             # sector != UNKNOWN
      subsector_known_pct,          # subsector not None
      sector_unknown_count,
      subsector_unknown_count,
  }
UNKNOWN is never counted as useful coverage.
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── SIC description keyword → (GICS sector, industry hint) ───────────────────
# Longest/most-specific keywords first so they shadow shorter ones.
_SIC_KW: list[tuple[list[str], str, str]] = [
    # Health Care
    (["biopharmaceutical", "biotechnology", "biologics"], "Health Care", "Biotechnology"),
    (["pharmaceutical prep", "pharmaceutical"],           "Health Care", "Drug Manufacturers"),
    (["medical device", "surgical instrument", "dental"], "Health Care", "Medical Devices"),
    (["diagnostic", "in vitro", "laboratory test"],       "Health Care", "Diagnostics"),
    (["hospital", "health service", "nursing", "clinic"], "Health Care", "Health Services"),
    # Information Technology
    (["semiconductor", "integrated circuit", "microprocessor", "wafer"],
     "Information Technology", "Semiconductors"),
    (["electronic computer", "computer storage", "computer peripheral"],
     "Information Technology", "Hardware"),
    (["prepackaged software", "custom software", "computer programming"],
     "Information Technology", "Software"),
    (["data processing", "computer processing", "information retrieval"],
     "Information Technology", "IT Services"),
    (["electronic component", "printed circuit", "capacitor", "transistor"],
     "Information Technology", "Electronic Components"),
    # Communication Services
    (["radio telephone", "cellular", "wireless telecom", "telephone communication"],
     "Communication Services", "Telecommunications"),
    (["cable television", "television broadcast", "satellite telecom"],
     "Communication Services", "Media"),
    (["motion picture", "entertainment", "video game"],
     "Communication Services", "Entertainment"),
    # Financials
    (["national commercial bank", "state commercial bank", "savings institution"],
     "Financials", "Banks"),
    (["life insurance", "accident and health", "fire marine", "casualty insurance"],
     "Financials", "Insurance"),
    (["security broker", "investment bank", "commodity contract", "investment advice"],
     "Financials", "Asset Management"),
    (["mortgage", "home equity", "consumer finance"],
     "Financials", "Consumer Finance"),
    (["bitcoin", "digital asset", "blockchain", "cryptocurrency"],
     "Financials", "Crypto"),
    # Real Estate
    (["real estate", "apartment", "office building", "shopping center"],
     "Real Estate", "Real Estate"),
    # Energy
    (["crude petroleum", "oil and gas", "petroleum refin", "natural gas liquid"],
     "Energy", "Oil & Gas"),
    (["uranium", "nuclear"],           "Energy", "Uranium"),
    (["coal mining"],                  "Energy", "Coal"),
    # Materials
    (["gold mining", "silver mining", "precious metal"],   "Materials", "Gold & Silver"),
    (["steel", "aluminum", "iron"],                        "Materials", "Metals"),
    (["chemical", "industrial chemical", "plastic", "rubber"],
     "Materials", "Chemicals"),
    (["paper", "pulp", "forestry", "lumber"],              "Materials", "Forest Products"),
    # Industrials
    (["aerospace", "aircraft", "missile", "defense"],       "Industrials", "Aerospace & Defense"),
    (["air transportation", "trucking", "railroad", "freight"],
     "Industrials", "Transportation"),
    (["construction", "building material", "engineering"],  "Industrials", "Construction"),
    (["machinery", "industrial equipment"],                 "Industrials", "Machinery"),
    # Consumer Discretionary
    (["automotive", "motor vehicle", "auto dealer"],
     "Consumer Discretionary", "Automotive"),
    (["apparel", "clothing", "footwear"],
     "Consumer Discretionary", "Apparel"),
    (["retail", "department store", "specialty store"],
     "Consumer Discretionary", "Retail"),
    (["restaurant", "fast food", "eating place"],
     "Consumer Discretionary", "Restaurants"),
    (["hotel", "motel", "resort", "casino"],
     "Consumer Discretionary", "Hospitality"),
    # Consumer Staples
    (["food", "beverage", "grocery", "supermarket"],     "Consumer Staples", "Food & Beverage"),
    (["tobacco"],                                         "Consumer Staples", "Tobacco"),
    (["cannabis", "marijuana"],                           "Consumer Staples", "Cannabis"),
    # Utilities
    (["electric service", "gas distribution", "water supply", "power generation"],
     "Utilities", "Utilities"),
]


# ── Coarse SIC code range → GICS sector ──────────────────────────────────────
# Only used when keyword matching fails.
# Format: (sic_low, sic_high_inclusive, gics_sector)
_SIC_RANGES: list[tuple[int, int, str]] = [
    (100,  999,  "Consumer Staples"),       # Agriculture
    (1000, 1040, "Materials"),              # Metal Mining
    (1041, 1099, "Materials"),              # Gold/Silver Mining
    (1300, 1399, "Energy"),                 # Oil & Gas
    (1400, 1499, "Materials"),              # Non-Metallic Minerals
    (2000, 2099, "Consumer Staples"),       # Food
    (2100, 2199, "Consumer Staples"),       # Tobacco
    (2300, 2399, "Consumer Discretionary"), # Apparel
    (2600, 2699, "Materials"),              # Paper
    (2800, 2836, "Materials"),              # Industrial Chemicals
    (2836, 2836, "Health Care"),            # Pharmaceutical (exact code 2836)
    (2837, 2899, "Materials"),              # Other Chemicals
    (2900, 2999, "Energy"),                 # Petroleum Refining
    (3559, 3579, "Information Technology"), # Computers/Machinery
    (3600, 3669, "Information Technology"), # Electronic Equipment
    (3670, 3679, "Information Technology"), # Electronic Components
    (3760, 3769, "Industrials"),            # Aerospace/Defense
    (3812, 3812, "Industrials"),            # Defense Electronics
    (4000, 4899, "Industrials"),            # Transportation
    (4900, 4999, "Utilities"),              # Utilities
    (5000, 5099, "Consumer Discretionary"), # Wholesale Trade (Durable)
    (5100, 5199, "Consumer Staples"),       # Wholesale Trade (Non-Durable)
    (5200, 5999, "Consumer Discretionary"), # Retail Trade
    (6000, 6199, "Financials"),             # Banks
    (6200, 6299, "Financials"),             # Security Brokers
    (6300, 6399, "Financials"),             # Insurance
    (6500, 6599, "Real Estate"),            # Real Estate
    (6700, 6999, "Financials"),             # Holding/Investment
    (7000, 7099, "Consumer Discretionary"), # Hotels
    (7200, 7299, "Consumer Discretionary"), # Personal Services
    (7370, 7379, "Information Technology"), # Computer Services
    (7380, 7389, "Industrials"),            # Miscellaneous Services
    (7800, 7999, "Communication Services"), # Amusement/Recreation
    (8000, 8099, "Health Care"),            # Health Services
    (8200, 8299, "Consumer Discretionary"), # Educational Services
    (8700, 8742, "Industrials"),            # Engineering/Management Services
]


def _kw_resolve(sic_desc: str) -> tuple[Optional[str], Optional[str]]:
    """
    Match sic_description (lowercase) against keyword lists.
    Returns (gics_sector, industry) or (None, None) on miss.
    """
    desc_low = sic_desc.lower()
    for keywords, sector, industry in _SIC_KW:
        if any(kw in desc_low for kw in keywords):
            return sector, industry
    return None, None


def _range_resolve(sic_code: int) -> Optional[str]:
    """Return GICS sector for a SIC code using coarse range map."""
    for lo, hi, sector in _SIC_RANGES:
        if lo <= sic_code <= hi:
            return sector
    return None


# ── Public API ────────────────────────────────────────────────────────────────

def resolve_sector(
    symbol:          str,
    raw_sector:      Optional[str] = None,
    raw_industry:    Optional[str] = None,
    sic_code:        Optional[int] = None,
    sic_description: Optional[str] = None,
) -> tuple[str, Optional[str], str]:
    """
    Resolve GICS sector + industry for one ticker.

    Returns
    -------
    (gics_sector, industry, source)
        gics_sector : one of GICS_11_SECTORS or "Unknown"
        industry    : sub-industry hint (may be None)
        source      : "static_map" | "sic_keyword" | "sic_range" |
                      "raw_provider" | "unknown"
    """
    try:
        from scanner.sector_map import SECTOR_MAP, TICKER_INDUSTRY, FINVIZ_TO_GICS
        from scanner.sector_map import GICS_11_SECTORS
    except Exception:
        SECTOR_MAP    = {}
        TICKER_INDUSTRY = {}
        FINVIZ_TO_GICS  = {}
        GICS_11_SECTORS = []

    sym = (symbol or "").upper()

    # ── 1. Static map ─────────────────────────────────────────────────────────
    if sym in SECTOR_MAP:
        s = SECTOR_MAP[sym]
        ind = TICKER_INDUSTRY.get(sym)
        return s, ind, "static_map"

    # ── 2. SIC description keyword match ─────────────────────────────────────
    if sic_description:
        s, ind = _kw_resolve(sic_description)
        if s:
            return s, ind or raw_industry, "sic_keyword"

    # ── 3. Raw provider sector (normalised) ───────────────────────────────────
    if raw_sector:
        s = FINVIZ_TO_GICS.get(raw_sector, raw_sector)
        if s and s in GICS_11_SECTORS:
            return s, raw_industry, "raw_provider"
        # Try direct GICS match
        if raw_sector in GICS_11_SECTORS:
            return raw_sector, raw_industry, "raw_provider"

    # ── 4. SIC range ──────────────────────────────────────────────────────────
    if sic_code:
        s = _range_resolve(int(sic_code))
        if s:
            return s, raw_industry, "sic_range"

    return "Unknown", raw_industry, "unknown"


def resolve_sector_from_row(row: dict) -> tuple[str, Optional[str], str]:
    """
    Convenience wrapper — extracts fields from a UniverseCache-shaped dict
    or SectorCache-shaped dict and calls resolve_sector().
    """
    return resolve_sector(
        symbol          = row.get("symbol") or "",
        raw_sector      = row.get("sector"),
        raw_industry    = row.get("industry"),
        sic_code        = row.get("sic_code"),
        sic_description = row.get("sic_description"),
    )


# ── Coverage metrics ──────────────────────────────────────────────────────────

def compute_coverage(results: list[dict]) -> dict:
    """
    Compute sector coverage metrics over a batch of enriched result rows.

    Each row should have keys:
      sector_context   (dict with "sector_strength" and "sector")
      subsector        (str or None)

    Returns
    -------
    {
        sector_context_present_pct : float   # has any sector_context attached
        sector_known_pct           : float   # sector != Unknown / UNKNOWN
        subsector_known_pct        : float   # subsector not None
        sector_unknown_count       : int
        subsector_unknown_count    : int
    }
    """
    n = len(results)
    if n == 0:
        return {
            "sector_context_present_pct": 0.0,
            "sector_known_pct":           0.0,
            "subsector_known_pct":        0.0,
            "sector_unknown_count":       0,
            "subsector_unknown_count":    0,
        }

    ctx_present = 0
    sector_known  = 0
    subsec_known  = 0

    for row in results:
        sc = row.get("sector_context") or {}
        if sc:
            ctx_present += 1

        strength = sc.get("sector_strength") or ""
        raw_s    = sc.get("sector") or row.get("sector") or ""
        known = bool(
            raw_s
            and raw_s.lower() not in ("unknown", "")
            and strength not in ("SECTOR_UNKNOWN", "")
        )
        if known:
            sector_known += 1

        sub = sc.get("subsector") or row.get("subsector")
        if sub:
            subsec_known += 1

    sector_unknown_count  = n - sector_known
    subsec_unknown_count  = n - subsec_known

    return {
        "sector_context_present_pct": round(ctx_present  / n * 100, 1),
        "sector_known_pct":           round(sector_known  / n * 100, 1),
        "subsector_known_pct":        round(subsec_known  / n * 100, 1),
        "sector_unknown_count":       sector_unknown_count,
        "subsector_unknown_count":    subsec_unknown_count,
    }
