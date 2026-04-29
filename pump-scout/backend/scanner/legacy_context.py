"""
Legacy Scanner Context Extractor
=================================
Status: LEGACY_FEATURE_SOURCE

The old main scanner (runner.py / scoring.py) is FROZEN as a feature source.
It is NOT the future final decision engine. Usage rules:

  - Old scanner remains available and all existing endpoints continue to work.
  - Old scanner FIRE/ARM/BASE/WATCH are LEGACY tier labels only.
    They do NOT map directly to Scanner v2 BUY/WATCH/AVOID decisions.
  - Old FIRE cannot create a Scanner v2 BUY signal.
  - Old HYPE/SYMPATHY/FLOW/STEALTH/SILENT features may be reused as context
    inputs in Scanner v2, but they cannot create Scanner v2 BUY by themselves.
  - New Pump engine (new_pump_runner.py) is the authoritative decision engine.

This module exposes raw legacy feature fields in a stable shape for consumption
by Scanner v2, research pipelines, and the frontend context layer.
"""
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# ── Freeze marker ─────────────────────────────────────────────────────────────
OLD_MAIN_SCANNER_STATUS: str = "LEGACY_FEATURE_SOURCE"

# ── Tag constants ─────────────────────────────────────────────────────────────
_ALL_LEGACY_TAGS = frozenset({
    "FIRE", "ARM", "BASE", "WATCH", "STEALTH",
    "SYMPATHY", "FLOW", "SILENT", "HYPE",
})

_TIER_TO_TAG = {
    "FIRE":     "FIRE",
    "ARM":      "ARM",
    "BASE":     "BASE",
    "STEALTH":  "STEALTH",
    "WATCH":    "WATCH",
    "SYMPATHY": "SYMPATHY",
    # SKIP has no positive tag
}


def _get_score(candidate: dict) -> dict:
    sc = candidate.get("score")
    if isinstance(sc, dict):
        return sc
    return {}


def _build_legacy_tags(candidate: dict) -> list[str]:
    """
    Derive the active feature tags from an old-scanner candidate dict.
    Tags are additive — a FIRE candidate may also carry FLOW, STEALTH, etc.
    """
    tags: list[str] = []
    sc     = _get_score(candidate)
    inds   = candidate.get("indicators") or {}
    symp   = candidate.get("sympathy") or {}

    tier = sc.get("tier") or candidate.get("tier") or ""
    tier_tag = _TIER_TO_TAG.get(tier)
    if tier_tag:
        tags.append(tier_tag)

    # STEALTH — high-volume low-price-move accumulation pattern
    stealth = inds.get("stealth") or {}
    if stealth.get("is_stealth") or sc.get("stealth_bonus", 0) >= 10:
        if "STEALTH" not in tags:
            tags.append("STEALTH")

    # FLOW — institutional smart-money flow signal
    flow = inds.get("institutional_flow") or {}
    if flow.get("is_institutional") or (flow.get("flow_score") or 0) >= 50:
        tags.append("FLOW")

    # SILENT — stealth + OBV divergence + high CMF (silent accumulation)
    if sc.get("silent_volume"):
        tags.append("SILENT")

    # SYMPATHY — sector leader pull signal
    if symp.get("is_sympathy"):
        if "SYMPATHY" not in tags:
            tags.append("SYMPATHY")

    # HYPE — populated after enrich step (may be absent if hype not checked)
    hype_data = candidate.get("hype") or {}
    hype_tier = (hype_data.get("hype_score") or {}).get("hype_tier") or "COLD"
    if hype_tier in ("HOT", "VIRAL"):
        tags.append("HYPE")

    return tags


def _build_hype_raw(candidate: dict, symbol: str) -> Optional[dict]:
    """Extract hype fields from candidate or hype monitor in-memory cache."""
    # 1. Pre-attached hype data (from scan run with hype enrichment)
    hype_data = candidate.get("hype") if candidate else None
    if hype_data:
        return hype_data

    # 2. Hype monitor live cache (covers top-30 old-scanner tickers)
    try:
        from hype_monitor.monitor import get_hype_for_ticker
        result = get_hype_for_ticker(symbol.upper())
        return result  # None if not covered
    except Exception:
        return None


def _build_sympathy_raw(candidate: dict) -> Optional[dict]:
    """Return the sympathy dict from runner.py Step 4.5."""
    symp = candidate.get("sympathy")
    if not symp:
        return None
    return {
        "is_sympathy":    symp.get("is_sympathy", False),
        "sympathy_score": symp.get("sympathy_score", 0),
        "leaders":        symp.get("leaders", []),
        "sector":         symp.get("sector"),
        "industry":       symp.get("industry"),
        "reason":         symp.get("reason"),
    }


def _build_flow_raw(candidate: dict) -> Optional[dict]:
    """Extract institutional flow data from indicators."""
    inds = candidate.get("indicators") or {}
    flow = inds.get("institutional_flow")
    if not flow:
        return None
    return {
        "is_institutional": flow.get("is_institutional", False),
        "flow_score":       flow.get("flow_score", 0),
        "days":             flow.get("days"),
        "signal":           "FLOW" if flow.get("is_institutional") else "NO_FLOW",
    }


def _build_stealth_raw(candidate: dict) -> Optional[dict]:
    """Extract stealth accumulation signal from indicators."""
    sc   = _get_score(candidate)
    inds = candidate.get("indicators") or {}
    stealth = inds.get("stealth")
    if not stealth:
        # Reconstruct minimal dict from score fields
        bonus = sc.get("stealth_bonus", 0) or 0
        if bonus == 0:
            return None
        return {"is_stealth": False, "stealth_score": round(bonus / 0.3), "source": "score_bonus_only"}
    return {
        "is_stealth":   stealth.get("is_stealth", False),
        "stealth_score": stealth.get("stealth_score", 0),
        "strength":     stealth.get("strength", "WEAK"),
        "vol_ratio":    stealth.get("vol_ratio"),
    }


def _build_silent_raw(candidate: dict) -> Optional[dict]:
    """Extract silent volume signal (stealth + OBV divergence + CMF confluence)."""
    sc = _get_score(candidate)
    silent = sc.get("silent_volume")
    if silent is None:
        return None
    return {
        "silent_volume": bool(silent),
        "signal":        "SILENT" if silent else "NO_SILENT",
        "vol_dim":       sc.get("vol_dim"),
        "smart_dim":     sc.get("smart_dim"),
    }


def _build_legacy_reason(candidate: dict, tags: list[str]) -> str:
    """One-line human-readable summary of the legacy signal."""
    sc       = _get_score(candidate)
    tier     = sc.get("tier") or candidate.get("tier") or "UNKNOWN"
    score    = sc.get("total_score") or 0
    tag_str  = "+".join(tags) if tags else "NONE"
    vol_dim  = sc.get("vol_dim")
    smart_dim = sc.get("smart_dim")

    parts = [f"tier={tier} score={score:.0f} tags=[{tag_str}]"]
    if vol_dim is not None:
        parts.append(f"vol={vol_dim:.0f}")
    if smart_dim is not None:
        parts.append(f"smart={smart_dim:.0f}")
    return " ".join(parts)


def extract_legacy_context(
    candidate_or_symbol,
    scan_data: Optional[dict] = None,
) -> dict:
    """
    Extract legacy scanner feature context for one ticker.

    Parameters
    ----------
    candidate_or_symbol:
        Either a candidate dict (from old scanner results) or a symbol string.
        If a string, looks up the latest scan results via get_latest_scan().
    scan_data:
        Pre-fetched scan data dict (avoids a redundant get_latest_scan() call).
        Only used when candidate_or_symbol is a symbol string.

    Returns
    -------
    Legacy context dict. All fields gracefully null on missing data.
    """
    # ── Resolve candidate dict ────────────────────────────────────────────────
    if isinstance(candidate_or_symbol, dict):
        candidate = candidate_or_symbol
        symbol    = (candidate.get("symbol") or "").upper()
    else:
        symbol    = str(candidate_or_symbol).upper()
        candidate = {}
        try:
            from database import get_latest_scan as _get_scan
            import asyncio
            # get_latest_scan is async — run synchronously only if no event loop
            # In async context callers should pass pre-fetched scan_data instead.
            data = scan_data
            if data is None:
                # Best-effort: pull from the in-memory scan cache (no DB call)
                from database import _latest_scan  # type: ignore
                data = _latest_scan if hasattr(
                    __import__("database"), "_latest_scan"
                ) else {}
        except Exception:
            data = scan_data or {}

        for r in (data or {}).get("results", []):
            if (r.get("symbol") or "").upper() == symbol:
                candidate = r
                break

    if not symbol:
        return {
            "symbol":       None,
            "source_status": "unavailable",
            "old_main_scanner_status": OLD_MAIN_SCANNER_STATUS,
        }

    sc        = _get_score(candidate)
    tier      = sc.get("tier") or candidate.get("tier") or "UNKNOWN"
    score_val = sc.get("total_score")

    # Build feature blocks (all non-fatal)
    try:
        tags = _build_legacy_tags(candidate)
    except Exception:
        tags = []

    try:
        hype_raw = _build_hype_raw(candidate, symbol)
    except Exception:
        hype_raw = None

    try:
        sympathy_raw = _build_sympathy_raw(candidate)
    except Exception:
        sympathy_raw = None

    try:
        flow_raw = _build_flow_raw(candidate)
    except Exception:
        flow_raw = None

    try:
        stealth_raw = _build_stealth_raw(candidate)
    except Exception:
        stealth_raw = None

    try:
        silent_raw = _build_silent_raw(candidate)
    except Exception:
        silent_raw = None

    try:
        legacy_reason = _build_legacy_reason(candidate, tags)
    except Exception:
        legacy_reason = None

    source_status = "live" if candidate else "unavailable"

    return {
        "symbol":          symbol,
        "scan_date":       candidate.get("scanned_at") or candidate.get("scan_date"),
        "legacy_tier":     tier,
        "legacy_score":    round(score_val, 1) if score_val is not None else None,
        "legacy_tags":     tags,
        "hype_raw":        hype_raw,
        "sympathy_raw":    sympathy_raw,
        "flow_raw":        flow_raw,
        "stealth_raw":     stealth_raw,
        "silent_raw":      silent_raw,
        "legacy_reason":   legacy_reason,
        "source_status":   source_status,
        # ── Freeze marker — always present ────────────────────────────────────
        "old_main_scanner_status": OLD_MAIN_SCANNER_STATUS,
    }
