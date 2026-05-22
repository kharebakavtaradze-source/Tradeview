"""Subsector taxonomy for all 11 GICS sectors — strength labels and drill-down data."""

# ── Strength label constants ───────────────────────────────────────────────────
_TREND_TO_SECTOR: dict[str, str] = {
    "LEADING":   "SECTOR_LEADING",
    "IMPROVING": "SECTOR_IMPROVING",
    "NEUTRAL":   "SECTOR_NEUTRAL",
    "WEAKENING": "SECTOR_WEAKENING",
    "LAGGING":   "SECTOR_LAGGING",
}

# ── Full subsector taxonomy: ETF → {subsector_name → [tickers]} ───────────────
SUBSECTOR_TAXONOMY: dict[str, dict[str, list[str]]] = {
    "XLK": {
        "Semiconductors":          ["NVDA", "AMD", "INTC", "QCOM", "AVGO", "TXN", "MU", "LRCX", "COHR", "SMCI"],
        "Software—Application":    ["MSFT", "ORCL", "ADBE", "CRM", "AAPL", "BBAI", "SOUN", "CXAI", "GFAI", "AIOT"],
        "AI / Quantum":            ["IONQ", "RGTI", "QUBT", "QBTS", "BBAI", "SOUN", "AIXI", "AITX", "CXAI"],
        "Cybersecurity":           ["GEN", "RDWR"],
        "IT Services":             ["ACN", "ITRI", "TUYA"],
        "Hardware":                ["AAPL", "SMCI", "NTGR"],
        "Software—Infrastructure": ["MSFT", "ORCL"],
    },
    "XLV": {
        "Biotechnology":       ["KPTI", "VOR", "INMB", "CAPR", "BNGO", "NVAX", "OCGN", "SAVA", "TPST",
                                "DNLI", "FOLD", "MIST", "RCKT", "RYTM", "CRVS", "HUMA", "INAB", "ZLAB",
                                "NRIX", "VSTM", "ATAI", "CLDX", "BCYC", "XNCR", "SANA", "TGTX", "TNXP",
                                "PCVX", "IMVT", "BHVN", "VRCA", "IDYA", "STRO", "ALLO", "ERAS", "FATE",
                                "ITRM", "CRBU", "REPL", "ARRY", "KYMR", "IBRX", "ANNX", "KLTR", "CTKB"],
        "Drug Manufacturers":  ["MRK", "ABBV", "ADMA", "AMRX", "CPRX", "NRXS", "PDSB"],
        "Medical Devices":     ["ABT", "MYGN", "SENS", "CODX", "HALO"],
        "Health Insurance":    ["UNH"],
        "Diagnostics":         ["MYGN", "CODX", "BNGO"],
    },
    "XLF": {
        "Banks":               ["RF", "CFFN", "HFWA", "EFSC", "JPM"],
        "Asset Management":    ["BX", "JHG", "MS", "GS"],
        "Insurance":           ["PGR", "ALL", "SPNT"],
        "Fintech":             ["SOFI", "HOOD"],
        "Crypto Mining":       ["MARA", "RIOT", "CLSK", "HUT", "BITF", "WULF", "BTBT", "CIFR", "IREN", "GREE"],
        "Mortgage Finance":    ["AGNC", "CIM", "RITM", "GPGI"],
    },
    "XLC": {
        "Social Media":            ["META", "GOOGL", "MTCH"],
        "Streaming/Entertainment": ["NFLX", "DIS", "AMC", "CRCL"],
        "Telecom":                 ["T", "VZ", "CMCSA", "UNIT", "SATS", "LUMN", "NXST"],
        "Ridesharing":             ["LYFT", "UBER"],
        "Satellite":               ["ASTS", "SATL", "GSAT", "VSAT", "SPIR"],
    },
    "XLY": {
        "Electric Vehicles":       ["RIVN", "LCID", "NKLA", "FFIE", "GOEV", "MULN", "SOLO", "AYRO", "IDEX"],
        "EV Charging":             ["BLNK", "EVGO", "CHPT"],
        "Gaming / Gambling":       ["GME", "DKNG", "PENN"],
        "Retail / Consumer":       ["CELH", "TILE", "CURV"],
        "Automotive Parts":        ["ADNT"],
        "Home Services":           ["ANGI"],
    },
    "XLE": {
        "Oil & Gas E&P": ["APA", "DVN", "COP", "XOM", "CVX", "EOG", "SLB", "PXD", "WRD"],
        "Uranium":       ["UEC", "NXE"],
    },
    "XLI": {
        "Aerospace & Defense":  ["LUNR", "RKLB", "MNTS", "VORB", "ASTRA", "EVTL"],
        "Transport/Logistics":  ["UPS"],
        "Industrial Equipment": ["TITN", "NNBR", "ABM", "WKHS", "PTRA"],
    },
    "XLB": {
        "Gold / Precious Metals": ["AGI", "BVN", "HMY", "CEF"],
        "Specialty Chemicals":    ["AMCR"],
    },
    "XLRE": {
        "Commercial REITs":  ["HIW", "CTRE"],
        "Residential REITs": ["NXRT"],
    },
    "XLP": {
        "Cannabis":           ["SNDL", "TLRY", "CGC", "ACB", "CRON", "HEXO"],
        "Food / Beverage":    ["CALM", "LW", "HAIN", "EL"],
        "Household Products": ["PG", "NWL", "SCHL"],
    },
    "XLU": {
        "Electric Utilities": [],
        "Gas Utilities":      [],
        "Multi-Utilities":    [],
    },
}

# ── Reverse lookup: ticker → (etf, subsector) ────────────────────────────────
def _build_reverse() -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for etf, subs in SUBSECTOR_TAXONOMY.items():
        for sub, tickers in subs.items():
            for t in tickers:
                if t not in out:
                    out[t] = (etf, sub)
    return out

TICKER_TO_SUBSECTOR: dict[str, tuple[str, str]] = _build_reverse()


# ── Strength helpers ──────────────────────────────────────────────────────────
def sector_trend_to_strength(trend_label: str) -> str:
    return _TREND_TO_SECTOR.get(trend_label or "", "SECTOR_UNKNOWN")


def _active_score(row: dict) -> float:
    s = row.get("score")
    if isinstance(s, dict):
        return s.get("total_score", 0) or 0
    return s or 0


def compute_subsector_strength(
    subsector_tickers: list[str],
    scan_results: list[dict],
    parent_trend_label: str,
) -> str:
    """Derive subsector strength from scan activity and parent sector trend."""
    if not subsector_tickers:
        return "SUBSECTOR_UNKNOWN"

    scored = {r["symbol"]: r for r in scan_results}
    active = [t for t in subsector_tickers if t in scored and _active_score(scored[t]) > 30]
    pct = len(active) / len(subsector_tickers)

    parent_rank = {"LEADING": 4, "IMPROVING": 3, "NEUTRAL": 2, "WEAKENING": 1, "LAGGING": 0}.get(
        parent_trend_label or "", 2
    )

    if pct >= 0.25 and parent_rank >= 3:
        return "SUBSECTOR_LEADING"
    if pct >= 0.10 or parent_rank >= 3:
        return "SUBSECTOR_IMPROVING"
    if pct > 0 or parent_rank >= 2:
        return "SUBSECTOR_NEUTRAL"
    if parent_rank == 1:
        return "SUBSECTOR_WEAKENING"
    if parent_rank == 0:
        return "SUBSECTOR_LAGGING"
    return "SUBSECTOR_NEUTRAL"


def _get_scan_results() -> list[dict]:
    try:
        from scanner.new_pump_runner import get_latest
        scan = get_latest()
        return scan.get("results", []) if scan else []
    except Exception:
        return []


# ── Public API ────────────────────────────────────────────────────────────────
def get_subsector_map() -> dict:
    """Full static taxonomy — ETF → subsector → tickers (no live data)."""
    return {
        "taxonomy": {
            etf: {sub: list(tickers) for sub, tickers in subs.items()}
            for etf, subs in SUBSECTOR_TAXONOMY.items()
        }
    }


def get_subsectors_for_etf(etf: str, sector_snapshot: dict) -> dict:
    """Subsectors for one ETF with per-subsector strength labels."""
    subs = SUBSECTOR_TAXONOMY.get(etf, {})
    if not subs:
        return {}

    sector_data    = (sector_snapshot.get("sectors") or {}).get(etf, {})
    parent_trend   = sector_data.get("trend_label", "NEUTRAL")
    sector_strength = sector_trend_to_strength(parent_trend)
    scan_results   = _get_scan_results()

    subsectors_out = []
    for sub_name, tickers in subs.items():
        strength   = compute_subsector_strength(tickers, scan_results, parent_trend)
        scored     = {r["symbol"]: r for r in scan_results}
        active     = [t for t in tickers if t in scored and _active_score(scored[t]) > 30]
        subsectors_out.append({
            "name":               sub_name,
            "subsector_strength": strength,
            "ticker_count":       len(tickers),
            "active_count":       len(active),
            "tickers":            tickers,
        })

    return {
        "etf":             etf,
        "name":            sector_data.get("name", etf),
        "sector_strength": sector_strength,
        "trend_label":     parent_trend,
        "subsectors":      subsectors_out,
    }


def get_subsector_detail(etf: str, subsector: str, sector_snapshot: dict) -> dict:
    """Tickers + active movers for one subsector."""
    subs     = SUBSECTOR_TAXONOMY.get(etf, {})
    tickers  = subs.get(subsector)
    if tickers is None:
        return {}

    sector_data  = (sector_snapshot.get("sectors") or {}).get(etf, {})
    parent_trend = sector_data.get("trend_label", "NEUTRAL")
    strength     = compute_subsector_strength(tickers, _get_scan_results(), parent_trend)
    scan_results = _get_scan_results()
    scored       = {r["symbol"]: r for r in scan_results}

    top_active = []
    for t in tickers:
        if t in scored:
            row   = scored[t]
            score = _active_score(row)
            if score > 0:
                s = row.get("score", {})
                top_active.append({
                    "symbol": t,
                    "score":  round(score, 1),
                    "tier":   s.get("tier") if isinstance(s, dict) else None,
                    "price_change_pct": row.get("indicators", {}).get("price_change_pct"),
                })
    top_active.sort(key=lambda x: x["score"], reverse=True)

    return {
        "etf":               etf,
        "sector_name":       sector_data.get("name", etf),
        "subsector":         subsector,
        "subsector_strength": strength,
        "tickers":           tickers,
        "top_active":        top_active[:10],
    }


def get_symbol_context(symbol: str, sector_snapshot: dict) -> dict:
    """Sector + subsector context for a single symbol."""
    sym = symbol.upper()
    result = TICKER_TO_SUBSECTOR.get(sym)

    # Sector ETF
    if result:
        etf, subsector = result
    else:
        # Fall back to GICS_SECTOR_ETFS via sector_map
        from scanner.sector_map import SECTOR_MAP, GICS_SECTOR_ETFS
        gics = SECTOR_MAP.get(sym, "")
        etf  = GICS_SECTOR_ETFS.get(gics, "")
        subsector = None

    sector_data = (sector_snapshot.get("sectors") or {}).get(etf, {}) if etf else {}

    parent_trend    = sector_data.get("trend_label", "NEUTRAL")
    sector_strength = sector_trend_to_strength(parent_trend) if etf else "SECTOR_UNKNOWN"

    sub_strength = "SUBSECTOR_UNKNOWN"
    if subsector and etf:
        sub_tickers = SUBSECTOR_TAXONOMY.get(etf, {}).get(subsector, [])
        sub_strength = compute_subsector_strength(sub_tickers, _get_scan_results(), parent_trend)

    return {
        "symbol":             sym,
        "sector_etf":         etf or None,
        "sector_name":        sector_data.get("name"),
        "subsector":          subsector,
        "sector_strength":    sector_strength,
        "subsector_strength": sub_strength,
        "trend_label":        parent_trend,
        "rrg_quadrant":       sector_data.get("rrg_quadrant"),
        "ret_1d":             sector_data.get("ret_1d"),
        "ret_5d":             sector_data.get("ret_5d"),
        "vs_spy_1d":          sector_data.get("vs_spy_1d"),
        "rs_trend":           sector_data.get("rs_trend"),
    }
