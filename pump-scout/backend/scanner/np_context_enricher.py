"""
NP Context Enricher — attaches sector/macro/news/sympathy context to New Pump candidates.

Design constraints:
- NO per-ticker network calls; uses only in-memory cached snapshots
- All failures are non-fatal: returns UNKNOWN/null, never raises
- Context is purely additive — decision/score/routing are never touched
- Call enrich_np_candidates(results) once per scan batch

Cache freshness (module-level, independent of existing module caches):
- sector_snapshot  : 30 min  (mirrors sector_engine._TTL)
- market_regime    : 60 min  (regime is daily; re-fetching hourly is cheap)
- hype_map         : sync from hype_monitor._latest_results (schedule-driven)
"""
import logging
import time

logger = logging.getLogger(__name__)

# ── Module-level snapshot cache ──────────────────────────────────────────────
_sector_snapshot: dict | None = None
_sector_snapshot_ts: float    = 0.0
_SECTOR_TTL = 1800  # 30 min

_regime: dict | None  = None
_regime_ts: float     = 0.0
_REGIME_TTL = 3600    # 60 min

# ── GICS ↔ ETF mappings ──────────────────────────────────────────────────────
_GICS_TO_ETF: dict[str, str] = {
    "Information Technology":  "XLK",
    "Health Care":             "XLV",
    "Financials":              "XLF",
    "Consumer Discretionary":  "XLY",
    "Consumer Staples":        "XLP",
    "Energy":                  "XLE",
    "Industrials":             "XLI",
    "Materials":               "XLB",
    "Real Estate":             "XLRE",
    "Communication Services":  "XLC",
    "Utilities":               "XLU",
}

# Known normalized GICS sector names (whitelist)
_GICS_SECTORS: frozenset[str] = frozenset(_GICS_TO_ETF.keys())

# ── Regime-specific sector alignment ────────────────────────────────────────
# Authoritative per-regime sector lists used for macro tailwind/headwind.
# Ignores the Finviz broad enrichment (>0.5% threshold) which can flag 7–8
# sectors on a green day and produce false tailwinds for unrelated tickers.
_REGIME_STRONG: dict[str, frozenset[str]] = {
    "RISK_ON":            frozenset({"Information Technology", "Communication Services",
                                     "Consumer Discretionary", "Financials", "Industrials"}),
    "ROTATION_ENERGY":    frozenset({"Energy"}),
    "ROTATION_DEFENSIVE": frozenset({"Health Care", "Consumer Staples", "Utilities"}),
    "RISK_OFF":           frozenset({"Utilities", "Health Care", "Consumer Staples"}),
    "FEAR":               frozenset({"Materials", "Utilities", "Health Care"}),
    "STAGFLATION":        frozenset({"Energy", "Materials"}),
    "LATE_CYCLE":         frozenset({"Energy", "Materials", "Industrials"}),
    "SMALL_CAP_RISK_ON":  frozenset({"Information Technology", "Consumer Discretionary",
                                     "Financials", "Industrials"}),
    "GROWTH_ROTATION":    frozenset({"Information Technology", "Communication Services",
                                     "Consumer Discretionary"}),
}
_REGIME_WEAK: dict[str, frozenset[str]] = {
    "RISK_ON":            frozenset({"Utilities", "Consumer Staples"}),
    "ROTATION_ENERGY":    frozenset({"Information Technology", "Consumer Discretionary"}),
    "ROTATION_DEFENSIVE": frozenset({"Information Technology", "Communication Services",
                                     "Consumer Discretionary"}),
    "RISK_OFF":           frozenset({"Information Technology", "Communication Services",
                                     "Consumer Discretionary"}),
    "FEAR":               frozenset({"Information Technology", "Consumer Discretionary",
                                     "Financials"}),
    "STAGFLATION":        frozenset({"Information Technology", "Communication Services"}),
    "LATE_CYCLE":         frozenset({"Information Technology", "Consumer Discretionary"}),
}

# Sectors that are growth-oriented (positive in RISK_ON)
_GROWTH_SECTORS: set[str] = {
    "Information Technology", "Communication Services",
    "Consumer Discretionary", "Financials", "Industrials",
}
# Sectors that are defensive (positive in RISK_OFF / FEAR)
_DEFENSIVE_SECTORS: set[str] = {
    "Utilities", "Consumer Staples", "Health Care", "Real Estate",
}

# ── Sector rotation helpers ──────────────────────────────────────────────────

# Previous RRG quadrant per ETF — populated when sector snapshot refreshes
_prev_rrg_quadrants: dict[str, str] = {}

# Heuristic macro themes per GICS sector (for display only; not used in scoring)
_MACRO_THEMES_BY_SECTOR: dict[str, list[str]] = {
    "Information Technology":  ["AI capex cycle", "rate sensitivity", "export controls"],
    "Communication Services":  ["AI advertising", "streaming consolidation", "regulatory risk"],
    "Financials":              ["rate environment", "credit cycle", "banking stress"],
    "Consumer Discretionary":  ["consumer confidence", "China tariffs", "employment trends"],
    "Consumer Staples":        ["inflation pass-through", "defensive rotation"],
    "Energy":                  ["oil supply/demand", "energy transition", "geopolitical risk"],
    "Industrials":             ["defense spending", "infrastructure buildout", "reshoring"],
    "Materials":               ["commodity cycle", "tariffs", "construction activity"],
    "Real Estate":             ["rate sensitivity", "commercial RE stress"],
    "Utilities":               ["rate sensitivity", "energy transition", "defensive bid"],
    "Health Care":             ["drug pricing regulation", "defensive rotation", "M&A cycle"],
}

# Bias score from RRG quadrant position
_QUADRANT_BIAS: dict[str, int] = {
    "LEADING":   2,
    "IMPROVING": 1,
    "WEAKENING": -1,
    "LAGGING":   -2,
}

_POSITIVE_TRANSITIONS = frozenset({("LAGGING", "IMPROVING"), ("IMPROVING", "LEADING")})
_NEGATIVE_TRANSITIONS = frozenset({("LEADING", "WEAKENING"), ("WEAKENING", "LAGGING")})


# ── Snapshot helpers ─────────────────────────────────────────────────────────

async def _get_sector_snapshot() -> dict:
    """Return cached sector snapshot (30-min TTL). Empty dict on failure."""
    global _sector_snapshot, _sector_snapshot_ts
    now = time.time()
    if _sector_snapshot is not None and now - _sector_snapshot_ts < _SECTOR_TTL:
        return _sector_snapshot
    try:
        from sectors.sector_engine import get_sector_snapshot
        snap = await get_sector_snapshot()
        new_snap = snap or {}
        # Snapshot prev quadrants before replacing (enables transition detection)
        if _sector_snapshot:
            _capture_prev_quadrants(_sector_snapshot)
        _sector_snapshot = new_snap
        _sector_snapshot_ts = now
        return _sector_snapshot
    except Exception as exc:
        logger.debug(f"[NpEnricher] sector_snapshot unavailable: {exc}")
        return _sector_snapshot or {}


async def _get_regime() -> dict:
    """Return cached market regime (60-min TTL). Empty dict on failure."""
    global _regime, _regime_ts
    now = time.time()
    if _regime is not None and now - _regime_ts < _REGIME_TTL:
        return _regime
    try:
        from scanner.market_regime import get_latest_regime
        reg = await get_latest_regime()
        _regime = reg or {}
        _regime_ts = now
        return _regime
    except Exception as exc:
        logger.debug(f"[NpEnricher] market_regime unavailable: {exc}")
        return _regime or {}


def _get_hype_map() -> dict[str, dict]:
    """Return {SYMBOL: hype_result} from hype monitor in-memory state. Never raises."""
    try:
        from hype_monitor.monitor import get_latest_hype_results
        results = get_latest_hype_results()
        return {r["ticker"].upper(): r for r in results if r.get("ticker")}
    except Exception:
        return {}


def _capture_prev_quadrants(snapshot: dict) -> None:
    """Store current ETF RRG quadrants before snapshot is replaced (for transition detection)."""
    global _prev_rrg_quadrants
    for etf, data in snapshot.get("sectors", {}).items():
        q = data.get("rrg_quadrant")
        if q:
            _prev_rrg_quadrants[etf] = q


def _compute_sector_forward_bias(
    rrg_quadrant: str | None,
    strong_sector: bool,
    weak_sector: bool,
    risk_mode: str | None,
    rotation_direction: str,
) -> tuple[str, str, str]:
    """
    Returns (bias, confidence, interpretation).
    bias: BULLISH | MILDLY_BULLISH | NEUTRAL | MILDLY_BEARISH | BEARISH
    confidence: HIGH | MEDIUM | LOW
    """
    pts = _QUADRANT_BIAS.get(rrg_quadrant or "", 0)

    if strong_sector:
        pts += 1
    elif weak_sector:
        pts -= 1

    if (risk_mode or "") in ("RISK_OFF", "FEAR"):
        pts -= 1

    abs_pts = abs(pts)
    dir_boost = 1 if rotation_direction == "UPGRADING" else (-1 if rotation_direction == "DOWNGRADING" else 0)
    confidence = "HIGH" if abs_pts + abs(dir_boost) >= 3 else ("MEDIUM" if abs_pts >= 1 else "LOW")

    if pts >= 2:
        bias = "BULLISH"
    elif pts == 1:
        bias = "MILDLY_BULLISH"
    elif pts <= -2:
        bias = "BEARISH"
    elif pts == -1:
        bias = "MILDLY_BEARISH"
    else:
        bias = "NEUTRAL"

    q = rrg_quadrant or "UNKNOWN"
    if bias == "BULLISH":
        interp = f"{q} quadrant with regime tailwind — bullish sector backdrop"
    elif bias == "MILDLY_BULLISH":
        interp = f"Sector in {q} quadrant — mild bullish lean"
    elif bias == "BEARISH":
        interp = f"{q} quadrant with regime headwind — bearish sector backdrop"
    elif bias == "MILDLY_BEARISH":
        interp = f"Sector in {q} quadrant — mild bearish lean"
    elif q != "UNKNOWN":
        interp = f"Sector in {q} quadrant — neutral backdrop"
    else:
        interp = "Sector rotation data unavailable"

    if rotation_direction == "UPGRADING":
        interp += " (rotation improving)"
    elif rotation_direction == "DOWNGRADING":
        interp += " (rotation deteriorating)"

    return bias, confidence, interp


# ── Per-field builders ───────────────────────────────────────────────────────

def _build_sector_context(row: dict, snapshot: dict, scan_results: list | None = None) -> dict:
    """
    sector_context fields derived from sector_engine snapshot.
    scan_results: full NP batch (used for subsector_strength computation).
    Never raises.
    """
    symbol   = (row.get("symbol") or "").upper()
    sector   = row.get("sector") or ""
    industry = row.get("industry") or ""
    raw_sector_input: str | None = None   # original raw value before normalization

    # ── Sector normalization ─────────────────────────────────────────────────
    # SectorCache often stores raw SIC descriptions ("SERVICES-COMPUTER PROCESSING...")
    # instead of normalized GICS names ("Information Technology").
    # Run sector_resolver when sector is non-empty but not a known GICS name.
    if sector and sector not in _GICS_SECTORS:
        raw_sector_input = sector           # preserve for UI drawer
        try:
            from scanner.sector_resolver import resolve_sector as _resolve
            _resolved, _resolved_industry, _ = _resolve(
                symbol          = symbol,
                raw_sector      = sector,   # let FINVIZ_TO_GICS handle clean provider names
                raw_industry    = industry or sector,
                sic_code        = None,
                sic_description = sector,   # treat raw SIC text as sic_description for keyword match
            )
            if _resolved and _resolved != "Unknown":
                sector = _resolved
                if not industry and _resolved_industry:
                    industry = _resolved_industry
        except Exception:
            pass

    # ── UniverseCache fallback when sector is still missing or unresolvable ─
    # Also retries when sector="Unknown" (stored in SectorCache for unenriched tickers)
    # since "Unknown" is truthy and would otherwise skip this fallback.
    if not sector or sector not in _GICS_SECTORS:
        try:
            from scanner.massive_reference import get_cached_ticker as _get_ref
            from scanner.sector_resolver import resolve_sector as _resolve
            _meta = _get_ref(symbol)
            if _meta:
                _resolved, _resolved_industry, _ = _resolve(
                    symbol          = symbol,
                    raw_sector      = None,
                    raw_industry    = _meta.get("sic_description"),
                    sic_code        = _meta.get("sic_code"),
                    sic_description = _meta.get("sic_description"),
                )
                if _resolved and _resolved != "Unknown":
                    sector = _resolved
                    if not industry and _resolved_industry:
                        industry = _resolved_industry
        except Exception:
            pass

    etf      = _GICS_TO_ETF.get(sector, "")

    sector_data: dict = {}
    if etf:
        sector_data = snapshot.get("sectors", {}).get(etf, {})

    trend_label  = sector_data.get("trend_label")    or "UNKNOWN"
    rs_trend     = sector_data.get("rs_trend")        or "UNKNOWN"
    rs_momentum  = sector_data.get("rs_momentum")
    rrg_quadrant = sector_data.get("rrg_quadrant")

    risk_mode   = snapshot.get("risk_mode")
    strong_secs = set()
    weak_secs   = set()

    # Derive strong/weak from risk_mode
    if risk_mode == "RISK_ON":
        strong_secs = _GROWTH_SECTORS
        weak_secs   = _DEFENSIVE_SECTORS
    elif risk_mode in ("RISK_OFF", "FEAR"):
        strong_secs = _DEFENSIVE_SECTORS
        weak_secs   = _GROWTH_SECTORS

    strong_sector = bool(sector and sector in strong_secs)
    weak_sector   = bool(sector and sector in weak_secs)

    # ── Sector rotation context ───────────────────────────────────────────────
    prev_quadrant = _prev_rrg_quadrants.get(etf) if etf else None
    rotation_transition = None
    rotation_direction  = "STABLE"

    if prev_quadrant and rrg_quadrant and prev_quadrant != rrg_quadrant:
        rotation_transition = f"{prev_quadrant}→{rrg_quadrant}"
        pair = (prev_quadrant, rrg_quadrant)
        if pair in _POSITIVE_TRANSITIONS:
            rotation_direction = "UPGRADING"
        elif pair in _NEGATIVE_TRANSITIONS:
            rotation_direction = "DOWNGRADING"
        else:
            rotation_direction = "SHIFTING"

    sector_forward_bias, sector_forward_confidence, sector_rotation_interpretation = \
        _compute_sector_forward_bias(
            rrg_quadrant, strong_sector, weak_sector, risk_mode, rotation_direction
        )

    macro_themes = _MACRO_THEMES_BY_SECTOR.get(sector, [])

    source_status = "live" if sector_data else ("static" if (sector and sector in _GICS_SECTORS) else "unavailable")

    # ── Subsector + strength labels ───────────────────────────────────────────
    try:
        from sectors.subsector_map import (
            TICKER_TO_SUBSECTOR, SUBSECTOR_TAXONOMY,
            sector_trend_to_strength, compute_subsector_strength,
        )
        # Subsector for this ticker
        sub_result = TICKER_TO_SUBSECTOR.get(symbol)
        subsector  = sub_result[1] if sub_result else None

        # Sector-level strength label
        sector_strength = sector_trend_to_strength(trend_label if trend_label != "UNKNOWN" else "")

        # Subsector-level strength: use NP batch as scan_results proxy
        _scan = scan_results or []
        sub_tickers = SUBSECTOR_TAXONOMY.get(etf, {}).get(subsector, []) if (etf and subsector) else []
        # Adapt: subsector_map expects score field; NP results use new_pump_score
        _proxy = [{"symbol": r.get("symbol"), "score": r.get("new_pump_score")} for r in _scan]
        subsector_strength = compute_subsector_strength(sub_tickers, _proxy, trend_label) if sub_tickers else "SUBSECTOR_UNKNOWN"
    except Exception:
        subsector          = None
        sector_strength    = "SECTOR_UNKNOWN"
        subsector_strength = "SUBSECTOR_UNKNOWN"

    # Subsector fallback: use resolved industry as subsector hint when static map has no entry.
    # Populates column with values like "IT Services", "Banks", "Oil & Gas" instead of blank.
    if not subsector and industry:
        subsector = industry

    return {
        "sector":              sector   or None,
        "sector_etf":          etf      or None,
        "subsector":           subsector,
        "industry":            industry or None,
        "raw_sector_input":    raw_sector_input,   # original raw value before normalization (drawer only)
        "sector_strength":     sector_strength,
        "subsector_strength":  subsector_strength,
        "sector_trend":        trend_label,
        "sector_rs_momentum":  rs_momentum,
        "sector_rrg_quadrant": rrg_quadrant,
        "sector_risk_mode":    risk_mode,
        "strong_sector":       strong_sector,
        "weak_sector":         weak_sector,
        "sector_context_source": source_status,
        # Sector rotation layer
        "sector_rotation_prev_quadrant":     prev_quadrant,
        "sector_rotation_transition":        rotation_transition,
        "sector_rotation_direction":         rotation_direction,
        "sector_forward_bias":               sector_forward_bias,
        "sector_forward_confidence":         sector_forward_confidence,
        "sector_macro_themes":               macro_themes,
        "sector_rotation_interpretation":    sector_rotation_interpretation,
    }


def _build_macro_context(row: dict, regime: dict) -> dict:
    """
    macro_context fields derived from market_regime snapshot.
    Never raises.

    macro_tailwind / macro_headwind use authoritative per-regime sector sets
    (_REGIME_STRONG / _REGIME_WEAK), NOT the Finviz-enriched strong_sectors list.
    The Finviz list uses a >0.5% threshold that flags 5–8 sectors on a green day
    and produces false tailwinds for unrelated tickers.
    Sector matching is exact GICS name membership (no substring matching).
    """
    if not regime:
        return {
            "market_regime":    "UNKNOWN",
            "risk_mode":        None,
            "strong_sectors":   [],
            "weak_sectors":     [],
            "macro_tailwind":   False,
            "macro_headwind":   False,
            "macro_reason":     None,
            "macro_context_source": "unavailable",
        }

    market_regime  = regime.get("regime")  or "NEUTRAL"
    risk_mode      = regime.get("risk_mode") or market_regime
    # Keep Finviz-enriched lists for UI display only (do NOT use for tailwind matching)
    strong_sectors = regime.get("strong_sectors") or []
    weak_sectors   = regime.get("weak_sectors")   or []

    # Use normalized GICS sector from sector_context when available;
    # fall back to top-level row["sector"] (already promoted by enrich_np_candidates).
    sector = row.get("sector") or ""

    # Authoritative regime-specific sector sets for tailwind/headwind
    regime_strong = _REGIME_STRONG.get(market_regime, frozenset())
    regime_weak   = _REGIME_WEAK.get(market_regime, frozenset())

    # Exact GICS membership — prevents raw SIC substring false-matches
    macro_tailwind = bool(sector and sector in regime_strong)
    macro_headwind = bool(sector and sector in regime_weak)

    if macro_tailwind:
        macro_reason = f"Sector '{sector}' aligned with {market_regime} regime"
    elif macro_headwind:
        macro_reason = f"Sector '{sector}' faces {market_regime} headwind"
    else:
        macro_reason = f"Neutral in {market_regime} regime"

    return {
        "market_regime":    market_regime,
        "risk_mode":        risk_mode,
        "strong_sectors":   strong_sectors,      # Finviz-enriched (for display only)
        "weak_sectors":     weak_sectors,         # Finviz-enriched (for display only)
        "regime_strong_sectors": sorted(regime_strong),  # authoritative (used for tailwind)
        "regime_weak_sectors":   sorted(regime_weak),    # authoritative (used for headwind)
        "macro_tailwind":   macro_tailwind,
        "macro_headwind":   macro_headwind,
        "macro_reason":     macro_reason,
        "macro_context_source": "live",
    }


def _build_news_hype_context(row: dict, hype_map: dict[str, dict]) -> dict:
    """
    news_hype_context fields from hype_monitor in-memory results.
    Only covers tickers that appear in the hype monitor's last run.
    Never raises.
    """
    sym = (row.get("symbol") or "").upper()
    hr  = hype_map.get(sym)

    if not hr:
        return {
            "hype_score":        None,
            "hype_tier":         "COLD",
            "hype_state":        "UNKNOWN",
            "article_count_2h":  None,
            "article_count_6h":  None,
            "article_count_24h": None,
            "catalyst_type":     None,
            "catalyst_risk_flags": [],
            "news_context_source": "unavailable",
        }

    hs       = hr.get("hype_score") or {}
    vel      = hr.get("velocity")   or {}
    divs     = hr.get("divergences") or []
    news     = hr.get("news")        or {}

    hype_index = hs.get("hype_index")
    hype_tier  = hs.get("hype_tier") or "COLD"

    # hype_state: derive from divergences
    div_types = [d.get("type") for d in divs if d.get("type")]
    if "SILENT_VOLUME" in div_types:
        hype_state = "SILENT_ACCUMULATION"
    elif "HYPE_NO_VOLUME" in div_types:
        hype_state = "HYPE_WITHOUT_VOLUME"
    elif "PEAK_FADING" in div_types:
        hype_state = "PEAK_FADING"
    elif hype_tier in ("HOT", "VIRAL"):
        hype_state = "ACTIVE_HYPE"
    elif hype_tier == "WARM":
        hype_state = "MILD_HYPE"
    else:
        hype_state = "COLD"

    # Catalyst type
    catalyst_type = None
    if news.get("has_sec_filing"):
        catalyst_type = "SEC_FILING"
    elif news.get("has_real_news"):
        catalyst_type = "REAL_NEWS"
    elif (news.get("count_24h") or 0) > 2:
        catalyst_type = "PR_ACTIVITY"

    # Risk flags
    catalyst_risk_flags: list[str] = []
    if "HYPE_NO_VOLUME" in div_types:
        catalyst_risk_flags.append("HYPE_NO_VOLUME")
    if "PEAK_FADING" in div_types:
        catalyst_risk_flags.append("PEAK_FADING")

    return {
        "hype_score":        round(hype_index, 1) if hype_index is not None else None,
        "hype_tier":         hype_tier,
        "hype_state":        hype_state,
        "article_count_2h":  round(vel.get("velocity_2h") or 0, 1),
        "article_count_6h":  round(vel.get("velocity_6h") or 0, 1),
        "article_count_24h": round(vel.get("velocity_24h") or 0, 1),
        "catalyst_type":     catalyst_type,
        "catalyst_risk_flags": catalyst_risk_flags,
        "news_context_source": "live",
    }


def _build_sympathy_context(row: dict, all_results: list[dict], snapshot: dict) -> dict:
    """
    sympathy_context: identify the sector/industry leader and alignment.
    Uses only already-enriched rows from the same scan batch.
    Never raises.
    """
    symbol   = (row.get("symbol") or "").upper()
    sector   = row.get("sector")   or ""
    industry = row.get("industry") or ""
    my_score = row.get("new_pump_score") or 0

    if not sector:
        return {
            "sympathy_theme":      None,
            "leader_symbol":       None,
            "leader_return_1d":    None,
            "leader_return_5d":    None,
            "candidate_alignment": "UNKNOWN",
            "sympathy_score":      0,
            "sympathy_reason":     "No sector data",
        }

    # Pool: same sector, different symbol
    same_sector = [
        r for r in all_results
        if r.get("sector") == sector and (r.get("symbol") or "").upper() != symbol
    ]
    # Prefer industry-level pool (stronger sympathy signal)
    same_industry = [
        r for r in same_sector
        if industry and r.get("industry") == industry
    ] if industry else []

    pool = same_industry or same_sector

    if not pool:
        # We might be the only ticker in this sector — still provide sector ETF context
        etf = _GICS_TO_ETF.get(sector, "")
        sec_data = snapshot.get("sectors", {}).get(etf, {})
        return {
            "sympathy_theme":      industry or sector,
            "leader_symbol":       None,
            "leader_return_1d":    sec_data.get("ret_1d"),
            "leader_return_5d":    sec_data.get("ret_5d"),
            "candidate_alignment": "LEAD",
            "sympathy_score":      0,
            "sympathy_reason":     f"Only ticker from {industry or sector} in current scan",
        }

    # Identify leader by NP score
    pool_sorted = sorted(pool, key=lambda r: r.get("new_pump_score") or 0, reverse=True)
    leader      = pool_sorted[0]
    leader_sym  = (leader.get("symbol") or "").upper()
    leader_score = leader.get("new_pump_score") or 0

    # Sector ETF returns for leader-level context
    etf = _GICS_TO_ETF.get(sector, "")
    sec_data = snapshot.get("sectors", {}).get(etf, {})
    leader_ret_1d = sec_data.get("ret_1d")
    leader_ret_5d = sec_data.get("ret_5d")

    # Alignment
    if leader_score > my_score + 5:
        alignment = "LAG"
        reason    = f"{leader_sym} leads {industry or sector} (score {leader_score:.0f} vs {my_score:.0f})"
    elif my_score >= leader_score:
        alignment = "LEAD"
        reason    = f"Leading {industry or sector} in current scan (score {my_score:.0f})"
    else:
        alignment = "PEER"
        reason    = f"Peer in {industry or sector} (score spread <5pts)"

    # Sympathy score: how valuable is this sympathy signal?
    # Higher if leader has a strong NP label and we're lagging
    leader_label = leader.get("new_pump_label") or ""
    base = 0
    if leader_label in ("NEW_PUMP_FIRE", "NEW_PUMP_STRONG"):
        base = 30
    elif leader_label == "NEW_PUMP_SETUP":
        base = 15

    sym_score = base + min(50, int(leader_score * 0.5)) if alignment == "LAG" else 0

    return {
        "sympathy_theme":      industry or sector,
        "leader_symbol":       leader_sym if alignment != "LEAD" else None,
        "leader_return_1d":    leader_ret_1d,
        "leader_return_5d":    leader_ret_5d,
        "candidate_alignment": alignment,
        "sympathy_score":      sym_score,
        "sympathy_reason":     reason,
    }


# ── Main entry point ─────────────────────────────────────────────────────────

async def enrich_np_candidates(results: list[dict]) -> list[dict]:
    """
    Attach sector_context / macro_context / news_hype_context / sympathy_context
    to every row in results.  Mutates rows in-place for efficiency; also returns list.

    Guaranteed non-fatal: any per-section failure falls back to null/UNKNOWN fields.
    Cache freshness: sector 30min, regime 60min, hype sync from last monitor run.
    """
    if not results:
        return results

    # ── Fetch snapshots (one I/O round per TTL, shared across all rows) ───────
    try:
        snapshot = await _get_sector_snapshot()
    except Exception:
        snapshot = {}

    try:
        regime = await _get_regime()
    except Exception:
        regime = {}

    hype_map = _get_hype_map()

    logger.info(
        f"[NpEnricher] Enriching {len(results)} candidates | "
        f"sector_snap={'ok' if snapshot else 'empty'} "
        f"regime={'ok' if regime else 'empty'} "
        f"hype_tickers={len(hype_map)}"
    )

    for row in results:
        try:
            row["sector_context"] = _build_sector_context(row, snapshot, results)
        except Exception as exc:
            logger.debug(f"[NpEnricher] sector_context failed {row.get('symbol')}: {exc}")
            row["sector_context"] = {"sector_context_source": "error"}

        # Promote normalized GICS sector/industry to top-level so that
        # _build_macro_context and _build_sympathy_context see the resolved name.
        # This ensures exact GICS matching works correctly for tailwind/headwind.
        _sc_out = row.get("sector_context") or {}
        _resolved_sector   = _sc_out.get("sector")
        _resolved_industry = _sc_out.get("industry")
        if _resolved_sector and _resolved_sector not in ("Unknown", "UNKNOWN"):
            row["sector"] = _resolved_sector
        if _resolved_industry and not row.get("industry"):
            row["industry"] = _resolved_industry

        try:
            row["macro_context"] = _build_macro_context(row, regime)
        except Exception as exc:
            logger.debug(f"[NpEnricher] macro_context failed {row.get('symbol')}: {exc}")
            row["macro_context"] = {"macro_context_source": "error"}

        try:
            row["news_hype_context"] = _build_news_hype_context(row, hype_map)
        except Exception as exc:
            logger.debug(f"[NpEnricher] news_hype_context failed {row.get('symbol')}: {exc}")
            row["news_hype_context"] = {"news_context_source": "error"}

    # Sympathy needs all rows with sectors already present, so runs after sector pass
    for row in results:
        try:
            row["sympathy_context"] = _build_sympathy_context(row, results, snapshot)
        except Exception as exc:
            logger.debug(f"[NpEnricher] sympathy_context failed {row.get('symbol')}: {exc}")
            row["sympathy_context"] = {"candidate_alignment": "UNKNOWN", "sympathy_score": 0}

    # Priority scoring — runs last so all context blocks are already attached
    try:
        from scanner.np_priority_scorer import compute_priority
        for row in results:
            try:
                p = compute_priority(row)
                row["priority_score"]  = p["priority_score"]
                row["priority_label"]  = p["priority_label"]
                row["priority_flags"]  = p["priority_flags"]
                row["priority_reason"] = p["priority_reason"]
            except Exception as exc:
                logger.debug(f"[NpEnricher] priority failed {row.get('symbol')}: {exc}")
        logger.info(f"[NpEnricher] Priority scoring complete for {len(results)} rows")
    except Exception as exc:
        logger.warning(f"[NpEnricher] Priority scoring skipped (non-fatal): {exc}")

    return results
