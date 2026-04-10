"""
Unified Ignition Engine  —  scanner/ignition_engine.py
═══════════════════════════════════════════════════════
Standalone scoring system that combines five independent signal layers:

  Layer               Weight   Source
  ──────────────────  ──────   ────────────────────────────────────────
  EMA Ribbon          35 pts   compression, bullish stack, BB squeeze
  Base Ignition       25 pts   calc_ignition() quality, scaled 0-100→0-25
  Sector Context      15 pts   sector class A-F, outperformance, sympathy plays
  Social Hype         15 pts   VIRAL/HOT/WARM tier, velocity, divergence penalty
  Macro / News        10 pts   Trump/event market bias + sector-level impact
  ──────────────────  ──────
  Total max           100 pts

Unified signal tiers
  STRONG_BUY  ≥ 85
  BUY         ≥ 65
  WATCH       ≥ 45
  NEUTRAL     ≥ 25
  AVOID       <  25

Optional AI layer (with_ai=True):
  Top-N candidates (unified_score ≥ 65) receive a Claude Haiku signal with
  entry_thesis, key_risk, catalyst_type, and confidence — cheap & fast.

Entry point:  await run_ignition_engine(main_results, ribbon_results, **kwargs)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# ─── Scoring weights (must sum to 100) ───────────────────────────────────────
_W_RIBBON   = 35
_W_IGNITION = 25
_W_SECTOR   = 15
_W_HYPE     = 15
_W_MACRO    = 10

# AI config
_AI_MODEL     = "claude-haiku-4-5-20251001"   # fast + low cost signal generation
_AI_TOP_N     = 10                             # max candidates that receive AI
_AI_MIN_SCORE = 65                             # unified_score floor for AI queue

# Unified signal tiers (highest threshold first)
_SIGNAL_TIERS: list[tuple[int, str]] = [
    (85, "STRONG_BUY"),
    (65, "BUY"),
    (45, "WATCH"),
    (25, "NEUTRAL"),
    (0,  "AVOID"),
]


def _to_signal(score: int) -> str:
    for threshold, label in _SIGNAL_TIERS:
        if score >= threshold:
            return label
    return "AVOID"


# ─── Candidate tagging ───────────────────────────────────────────────────────

def _tag_main(r: dict) -> dict:
    """Flatten a main-scan result into the canonical candidate shape."""
    ind = r.get("indicators") or {}
    sc  = r.get("score")      or {}
    obv = ind.get("obv")      or {}
    rsi = ind.get("rsi")      or {}
    return {
        "symbol":                  r.get("symbol"),
        "price":                   r.get("price"),
        "sector":                  r.get("sector", "Unknown"),
        "industry":                r.get("industry", ""),
        "tier":                    sc.get("tier"),
        "total_score":             sc.get("total_score"),
        "source":                  "main_scan",
        "anomaly_ratio":           ind.get("anomaly_ratio"),
        "cmf_pctl":                ind.get("cmf_pctl"),
        "obv_strength":            obv.get("obv_strength"),
        "obv_divergence":          obv.get("obv_divergence"),
        "ribbon_compression":      ind.get("ribbon_compression"),
        "bullish_stack":           ind.get("bullish_stack"),
        "bearish_stack":           ind.get("bearish_stack"),
        "compression_and_bullish": ind.get("compression_and_bullish"),
        "ema_spread_pct":          ind.get("ema_spread_pct"),
        "ema8_slope":              ind.get("ema8_slope"),
        "rs_score":                float(ind.get("rs_score") or 0.0),
        "today_vol":               ind.get("today_vol") or r.get("volume_today"),
        "avg_vol_20":              ind.get("avg_vol_20") or 0,
        "bb_sqz_bars":             ind.get("bb_sqz_bars", 0),
        "rsi":                     rsi.get("value"),
        "price_change_pct":        ind.get("price_change_pct", 0.0),
        "earnings_risk":           r.get("earnings_risk", "NONE"),
        "ai_analysis":             r.get("ai_analysis"),
        # preserved for calc_ignition + find_sector_leaders
        "_indicators": ind,
        "_regime":     r.get("regime") or {},
        "_score":      sc,
    }


def _tag_ribbon(r: dict) -> dict:
    """Flatten a ribbon-candidate DB row into the canonical candidate shape."""
    return {
        "symbol":                  r.get("symbol"),
        "price":                   r.get("price"),
        "sector":                  r.get("sector", "Unknown"),
        "industry":                r.get("industry", ""),
        "tier":                    None,
        "total_score":             None,
        "source":                  "ribbon_pass",
        "anomaly_ratio":           r.get("anomaly_ratio"),
        "cmf_pctl":                r.get("cmf_pctl"),
        "obv_strength":            r.get("obv_strength"),
        "obv_divergence":          None,
        "ribbon_compression":      r.get("ribbon_compression"),
        "bullish_stack":           r.get("bullish_stack", False),
        "bearish_stack":           r.get("bearish_stack", False),
        "compression_and_bullish": r.get("compression_and_bullish", False),
        "ema_spread_pct":          r.get("ema_spread_pct"),
        "ema8_slope":              r.get("ema8_slope"),
        "rs_score":                float(r.get("rs_score") or 0.0),
        "today_vol":               r.get("today_vol"),
        "avg_vol_20":              0,
        "bb_sqz_bars":             r.get("bb_sqz_bars", 0),
        "rsi":                     r.get("rsi"),
        "price_change_pct":        0.0,
        "earnings_risk":           "NONE",
        "ai_analysis":             None,
        # reconstructed minimal indicators dict for calc_ignition
        "_indicators": {
            "ribbon_compression":      r.get("ribbon_compression", "NONE"),
            "bullish_stack":           r.get("bullish_stack", False),
            "bearish_stack":           r.get("bearish_stack", False),
            "compression_and_bullish": r.get("compression_and_bullish", False),
            "ema8_slope":              r.get("ema8_slope", "FLAT"),
            "ema_spread_pct":          float(r.get("ema_spread_pct") or 999.0),
            "above_ema20":             True,   # conservative default
            "above_ema50":             bool(r.get("bullish_stack", False)),
            "bb_sqz_bars":             r.get("bb_sqz_bars", 0),
            "anomaly_ratio":           float(r.get("anomaly_ratio") or 0.0),
            "vol_z":                   0.0,
            "cmf_pctl":                float(r.get("cmf_pctl") or 0.0),
            "cmf":                     0.0,
            "obv": {
                "obv_strength":  r.get("obv_strength", "WEAK"),
                "obv_divergence": False,
            },
            "rsi":    {"value": float(r.get("rsi") or 50.0), "has_divergence": False},
            "stealth": {},
            "today_vol":        int(r.get("today_vol") or 0),
            "rs_score":         float(r.get("rs_score") or 0.0),
            "price_change_pct": 0.0,
        },
        "_regime": {},
        "_score":  {},
    }


# ─── Sub-scorers ─────────────────────────────────────────────────────────────

def _ribbon_sub(r: dict) -> tuple[int, list[str]]:
    """EMA ribbon quality  →  0-35 pts."""
    score = 0
    facts: list[str] = []
    comp  = (r.get("ribbon_compression") or "NONE")
    bull  = bool(r.get("bullish_stack"))
    bear  = bool(r.get("bearish_stack"))
    cb    = bool(r.get("compression_and_bullish"))
    spread = float(r.get("ema_spread_pct") or 999.0)
    slope  = (r.get("ema8_slope") or "FLAT")
    sqz    = int(r.get("bb_sqz_bars") or 0)

    if   comp == "STRONG": score += 20; facts.append("strong_compression")
    elif comp == "MEDIUM": score += 13; facts.append("medium_compression")
    elif comp == "WEAK":   score +=  6; facts.append("weak_compression")

    if   cb:   score += 10; facts.append("coiled_bullish")
    elif bull: score +=  6; facts.append("bullish_stack")

    if   slope == "RISING":  score += 5; facts.append("ema8_rising")
    elif slope == "FALLING": score -= 5; facts.append("ema8_falling")

    if   sqz >= 10: score += 5; facts.append(f"bb_squeeze_{sqz}d")
    elif sqz >=  5: score += 3; facts.append(f"bb_squeeze_{sqz}d")

    if bear:     score -= 15; facts.append("bearish_penalty")
    if spread > 8: score -= 5; facts.append("wide_spread")

    return max(0, min(_W_RIBBON, score)), facts


def _ignition_sub(ignition: dict) -> tuple[int, list[str]]:
    """Scale calc_ignition quality (0-100)  →  0-25 pts."""
    quality = int(ignition.get("ignition_quality") or 0)
    signal  = ignition.get("ignition_signal", "NO_IGNITION")
    scaled  = round(quality / 100 * _W_IGNITION)
    facts: list[str] = []
    if   signal == "IGNITION_CONFIRMED": facts.append("ignition_confirmed")
    elif signal == "EARLY_IGNITION":     facts.append("early_ignition")
    elif signal == "IGNITION_WATCH":     facts.append("ignition_watch")
    return max(0, min(_W_IGNITION, scaled)), facts


def _sector_sub(
    sector:      str,
    sector_perf: dict,
    sympathy:    dict | None,
    macro_bias:  dict | None,
) -> tuple[int, list[str], dict]:
    """Sector context  →  0-15 pts."""
    score = 0
    facts: list[str] = []
    sp = (sector_perf or {}).get(sector) or {}

    # Sector class A/B/C/D/F
    sc          = sp.get("sector_class", "C")
    class_delta = {"A": 8, "B": 5, "C": 0, "D": -3, "F": -7}.get(sc, 0)
    score      += class_delta
    if class_delta > 0: facts.append(f"sector_class_{sc}")
    if class_delta < 0: facts.append(f"sector_drag_{sc}")

    # vs SPY 1-day
    vs_spy = float(sp.get("vs_spy_1d") or 0)
    if   vs_spy >  0.5: score += 3; facts.append("sector_outperforming")
    elif vs_spy < -1.0: score -= 3; facts.append("sector_underperforming")

    # Sympathy play bonus
    sym_score = 0
    if sympathy and sympathy.get("is_sympathy"):
        sym_score = int(sympathy.get("sympathy_score") or 0)
        bonus     = min(7, round(sym_score / 100 * 7))
        score    += bonus
        if bonus > 0:
            facts.append(f"sympathy_{sympathy.get('leader', '?')}")

    # Macro sector cross-check (sector already in macro's bullish/bearish list)
    if macro_bias:
        if sector in set(macro_bias.get("top_bullish_sectors") or []):
            score += 3; facts.append("macro_sector_tailwind")
        elif sector in set(macro_bias.get("top_bearish_sectors") or []):
            score -= 3; facts.append("macro_sector_headwind")

    ctx = {
        "sector":          sector,
        "sector_class":    sc,
        "sector_vs_spy":   round(vs_spy, 2),
        "is_sympathy":     bool(sympathy and sympathy.get("is_sympathy")),
        "sympathy_score":  sym_score,
        "sympathy_leader": (sympathy or {}).get("leader"),
    }
    return max(0, min(_W_SECTOR, score)), facts, ctx


def _hype_sub(hype: dict | None) -> tuple[int, list[str], dict]:
    """Social hype signal  →  0-15 pts."""
    null_ctx = {"hype_tier": "COLD", "hype_index": 0, "velocity_2h": 0, "divergence": None}
    if not hype:
        return 0, [], null_ctx

    hs        = hype.get("hype_score") or hype    # support raw or nested
    vel       = hype.get("velocity")   or {}
    div_list  = hype.get("divergences") or []
    divergence = div_list[0] if div_list else None

    hype_index = float(hs.get("hype_index") or 0)
    hype_tier  = (hs.get("hype_tier") or "COLD")
    vel_2h     = float(
        vel.get("combined_velocity_2h")
        or vel.get("velocity_2h")
        or hs.get("velocity_2h")
        or 0
    )

    score = 0
    facts: list[str] = []

    if   hype_tier == "VIRAL": score += 12; facts.append("hype_viral")
    elif hype_tier == "HOT":   score +=  8; facts.append("hype_hot")
    elif hype_tier == "WARM":  score +=  4; facts.append("hype_warm")

    if   vel_2h >= 3.0: score += 3; facts.append("hype_accelerating")
    elif vel_2h >= 1.5: score += 1; facts.append("hype_rising")

    if divergence:
        div_type = (divergence.get("type") or "")
        if   div_type == "PEAK_FADING":    score -= 5; facts.append("hype_fading")
        elif div_type == "HYPE_NO_VOLUME": score -= 3; facts.append("hype_no_volume")

    ctx = {
        "hype_index":  round(hype_index, 1),
        "hype_tier":   hype_tier,
        "velocity_2h": round(vel_2h, 2),
        "divergence":  divergence,
    }
    return max(0, min(_W_HYPE, score)), facts, ctx


def _macro_sub(sector: str, macro_bias: dict | None) -> tuple[int, list[str], dict]:
    """Macro / news bias  →  0-10 pts  (neutral baseline = 5)."""
    null_ctx = {
        "market_bias": "NEUTRAL", "sector_impact": "NEUTRAL",
        "volatility_bias": "LOW", "active_events": 0, "regime_summary": "",
    }
    if not macro_bias:
        return 5, [], null_ctx

    market_bias = (macro_bias.get("overall_market_bias") or "NEUTRAL")
    vol_bias    = (macro_bias.get("overall_volatility")   or "LOW")
    bull_secs   = set(macro_bias.get("top_bullish_sectors") or [])
    bear_secs   = set(macro_bias.get("top_bearish_sectors") or [])
    ev_count    = int(macro_bias.get("event_count") or 0)

    score = 5   # neutral baseline
    facts: list[str] = []

    bias_delta = {
        "BULLISH": 4, "MIXED": 0, "NEUTRAL": 0, "RISK_OFF": -4, "BEARISH": -5,
    }.get(market_bias, 0)
    score += bias_delta
    if bias_delta > 0: facts.append(f"macro_{market_bias.lower()}")
    if bias_delta < 0: facts.append(f"macro_{market_bias.lower()}")

    sector_impact = "NEUTRAL"
    if   sector in bull_secs: score += 3; sector_impact = "BULLISH"; facts.append("macro_tailwind")
    elif sector in bear_secs: score -= 3; sector_impact = "BEARISH"; facts.append("macro_headwind")

    if vol_bias in ("HIGH", "VERY_HIGH"):
        score -= 2; facts.append("high_vol_env")

    ctx = {
        "market_bias":    market_bias,
        "sector_impact":  sector_impact,
        "volatility_bias": vol_bias,
        "active_events":  ev_count,
        "regime_summary": (macro_bias.get("regime_summary") or ""),
    }
    return max(0, min(_W_MACRO, score)), facts, ctx


# ─── AI signal ───────────────────────────────────────────────────────────────

async def _ai_signal(candidate: dict) -> dict | None:
    """
    Ask Claude Haiku for a structured trading signal on one candidate.
    Only called for top-N results with unified_score ≥ _AI_MIN_SCORE.
    Returns a dict with: signal, confidence, entry_thesis, key_risk, catalyst_type.
    Returns None on any failure (non-fatal).
    """
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        sym     = candidate.get("symbol", "?")
        us      = candidate.get("unified_score", 0)
        iq      = candidate.get("ignition_quality", 0)
        sig     = candidate.get("ignition_signal", "")
        ribbon  = candidate.get("ribbon_compression", "NONE")
        sector  = candidate.get("sector", "Unknown")
        rs      = float(candidate.get("rs_score") or 0)
        anomaly = float(candidate.get("anomaly_ratio") or 0)
        confs   = candidate.get("ignition_confirmations") or []
        warns   = candidate.get("ignition_warnings")      or []
        factors = candidate.get("score_factors")          or []
        sc_ctx  = candidate.get("sector_context")         or {}
        ht_ctx  = candidate.get("hype_context")           or {}
        mc_ctx  = candidate.get("macro_context")          or {}

        prompt = f"""Momentum trading signal analyst. Analyze this pre-breakout setup.

{sym} | {sector} | sector_class={sc_ctx.get('sector_class', 'C')}
unified={us}/100  ignition={iq}/100 ({sig})
ribbon={ribbon}  rs_vs_spy={rs:+.1f}%  vol_anomaly={anomaly:.1f}x
hype={ht_ctx.get('hype_tier','COLD')} vel_2h={ht_ctx.get('velocity_2h',0):.1f}x
macro={mc_ctx.get('market_bias','NEUTRAL')}  sector_macro={mc_ctx.get('sector_impact','NEUTRAL')}
sympathy={sc_ctx.get('is_sympathy',False)} leader={sc_ctx.get('sympathy_leader','none')}
confirmations=[{', '.join(confs[:5])}]
warnings=[{', '.join(warns[:3])}]
key_factors=[{', '.join(factors[:8])}]

Respond in JSON only (no markdown):
{{
  "signal": "STRONG_BUY|BUY|WATCH|NEUTRAL|AVOID",
  "confidence": <0-100>,
  "entry_thesis": "<one sentence max>",
  "key_risk": "<one sentence max>",
  "catalyst_type": "compression_breakout|sympathy|hype_driven|macro_tailwind|volume_anomaly|mixed"
}}"""

        msg = client.messages.create(
            model=_AI_MODEL,
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}],
        )
        return json.loads(msg.content[0].text.strip())

    except Exception as e:
        logger.warning(f"AI signal failed for {candidate.get('symbol')}: {e}")
        return None


# ─── Main engine ─────────────────────────────────────────────────────────────

async def run_ignition_engine(
    main_results:   list[dict],
    ribbon_results: list[dict],
    mode:           str  = "all",
    min_volume:     int  = 200_000,
    min_quality:    int  = 0,
    bullish_only:   bool = False,
    max_results:    int  = 100,
    with_ai:        bool = False,
) -> dict:
    """
    Run the full unified ignition engine and return a response dict.

    Response extends the standard ignition format with:
      unified_score      int  0-100   combined score
      unified_signal     str          STRONG_BUY / BUY / WATCH / NEUTRAL / AVOID
      ribbon_score       int  0-35    ribbon sub-score
      ignition_score     int  0-25    ignition sub-score
      sector_score       int  0-15    sector sub-score
      hype_score_pts     int  0-15    hype sub-score
      macro_score        int  0-10    macro sub-score
      score_factors      list[str]    all contributing factors
      sector_context     dict         sector_class, vs_spy, sympathy info
      hype_context       dict         hype_index, tier, velocity, divergence
      macro_context      dict         market_bias, sector_impact, events
      ai_signal          dict | None  Claude signal (only when with_ai=True)
    """
    from scanner.early_ignition  import calc_ignition
    from scanner.sector_sympathy import (
        get_sectors_batch, find_sector_leaders, calc_sympathy_score,
    )
    from scanner.sector_performance import fetch_sector_performance
    from database                   import get_macro_events_active
    from hype_monitor.monitor       import get_latest_hype_results

    # ── Phase 1: Gather global context (all parallel) ─────────────────────────
    gathered = await asyncio.gather(
        fetch_sector_performance(),
        get_macro_events_active(),
        return_exceptions=True,
    )
    sector_perf, macro_events = gathered
    sector_perf  = sector_perf  if not isinstance(sector_perf,  Exception) else {}
    macro_events = macro_events if not isinstance(macro_events, Exception) else []

    # Hype results are in-memory (no I/O) — call synchronously
    try:
        hype_list: list[dict] = get_latest_hype_results() or []
    except Exception:
        hype_list = []

    # Build hype lookup keyed by ticker symbol (uppercase)
    hype_by_sym: dict[str, dict] = {
        (h.get("ticker") or "").upper(): h
        for h in hype_list
        if h.get("ticker")
    }

    # Aggregate macro events into a single active-bias snapshot
    macro_bias: dict | None = None
    if macro_events:
        try:
            from news.trump_news import compute_active_bias
            macro_bias = compute_active_bias(macro_events)
        except Exception as e:
            logger.warning(f"compute_active_bias: {e}")

    # ── Phase 2: Merge + tag candidates ──────────────────────────────────────
    main_tagged   = [_tag_main(r)   for r in main_results]
    ribbon_tagged = [_tag_ribbon(r) for r in ribbon_results]
    main_syms     = {r["symbol"] for r in main_tagged}
    all_candidates = main_tagged + [r for r in ribbon_tagged if r["symbol"] not in main_syms]

    if not all_candidates:
        return _empty_response()

    # ── Phase 3: Batch sector lookup ──────────────────────────────────────────
    try:
        sectors_data = await get_sectors_batch([r["symbol"] for r in all_candidates])
    except Exception as e:
        logger.warning(f"get_sectors_batch: {e}")
        sectors_data = {}

    for r in all_candidates:
        si = sectors_data.get(r["symbol"], {})
        if isinstance(si, dict):
            r["sector"]   = si.get("sector",   "Unknown") or "Unknown"
            r["industry"] = si.get("industry", "")        or ""
        elif isinstance(si, str):
            r["sector"]   = si or "Unknown"
            r["industry"] = ""

    # Build sector leaders list (needed for sympathy scoring)
    try:
        leaders_input = [
            {
                "symbol":   r["symbol"],
                "sector":   r.get("sector", "Unknown"),
                "industry": r.get("industry", ""),
                "score":    {"total_score": r.get("total_score") or 50},
                "indicators": {
                    "price_change_pct": r.get("price_change_pct", 0),
                    "anomaly_ratio":    float(r.get("anomaly_ratio") or 0),
                    "cmf_pctl":         float(r.get("cmf_pctl") or 0),
                    "today_vol":        int(r.get("today_vol") or 0),
                    "avg_vol_20":       int(r.get("avg_vol_20") or 0),
                },
            }
            for r in all_candidates
        ]
        sector_leaders = find_sector_leaders(leaders_input)
    except Exception as e:
        logger.warning(f"find_sector_leaders: {e}")
        sector_leaders = {}

    # ── Phase 4: Per-symbol scoring ───────────────────────────────────────────
    for r in all_candidates:
        sym    = r["symbol"]
        sector = r.get("sector", "Unknown")

        # Base ignition (existing system)
        try:
            ignition = calc_ignition(
                indicators    = r.pop("_indicators"),
                regime        = r.pop("_regime"),
                rs_score      = float(r.get("rs_score") or 0.0),
                earnings_risk = r.get("earnings_risk", "NONE"),
            )
        except Exception as e:
            logger.warning(f"calc_ignition({sym}): {e}")
            r.pop("_indicators", None)
            r.pop("_regime",     None)
            ignition = {
                "ignition_signal":        "NO_IGNITION",
                "ignition_bucket":        "NONE",
                "ignition_quality":       0,
                "ignition_reason":        "Error",
                "ignition_confirmations": [],
                "ignition_warnings":      [],
            }

        # Flatten ignition fields onto the candidate
        for k, v in ignition.items():
            r[k] = v

        # Sympathy play detection
        sympathy: dict | None = None
        try:
            sympathy = calc_sympathy_score(
                {
                    "symbol":   sym,
                    "sector":   sector,
                    "industry": r.get("industry", ""),
                    "score":    {"total_score": r.get("total_score") or 50},
                    "indicators": {
                        "price_change_pct": r.get("price_change_pct", 0),
                        "anomaly_ratio":    float(r.get("anomaly_ratio") or 0),
                        "cmf_pctl":         float(r.get("cmf_pctl") or 0),
                        "today_vol":        int(r.get("today_vol") or 0),
                        "avg_vol_20":       0,
                    },
                },
                sector_leaders,
            )
        except Exception:
            pass

        # Sub-scores
        r_pts, r_f = _ribbon_sub(r)
        i_pts, i_f = _ignition_sub(ignition)
        s_pts, s_f, sec_ctx  = _sector_sub(sector, sector_perf, sympathy, macro_bias)
        h_pts, h_f, hype_ctx = _hype_sub(hype_by_sym.get(sym.upper()))
        m_pts, m_f, mac_ctx  = _macro_sub(sector, macro_bias)

        unified = max(0, min(100, r_pts + i_pts + s_pts + h_pts + m_pts))

        r.update({
            "unified_score":  unified,
            "unified_signal": _to_signal(unified),
            "ribbon_score":   r_pts,
            "ignition_score": i_pts,
            "sector_score":   s_pts,
            "hype_score_pts": h_pts,
            "macro_score":    m_pts,
            "score_factors":  r_f + i_f + s_f + h_f + m_f,
            "sector_context": sec_ctx,
            "hype_context":   hype_ctx,
            "macro_context":  mac_ctx,
            "ai_signal":      None,
        })
        r.pop("_score", None)  # internal field no longer needed

    # ── Phase 5: Filter ───────────────────────────────────────────────────────
    filtered: list[dict] = []
    for r in all_candidates:
        vol = r.get("today_vol") or 0
        if vol and vol < min_volume:
            continue
        if r.get("ignition_quality", 0) < min_quality:
            continue
        if bullish_only and r.get("bearish_stack"):
            continue
        sig = r.get("ignition_signal", "NO_IGNITION")
        if mode == "confirmed" and sig != "IGNITION_CONFIRMED":
            continue
        if mode == "early" and sig not in ("IGNITION_CONFIRMED", "EARLY_IGNITION"):
            continue
        if mode == "watch" and sig == "NO_IGNITION":
            continue
        filtered.append(r)

    # ── Phase 6: Sort — unified_score primary, ignition_quality secondary ─────
    filtered.sort(
        key=lambda x: (x["unified_score"], x.get("ignition_quality", 0)),
        reverse=True,
    )
    filtered = filtered[:max_results]

    # ── Phase 7: AI signals for top qualifying candidates (optional) ──────────
    if with_ai and filtered:
        ai_queue = [
            r for r in filtered
            if r["unified_score"] >= _AI_MIN_SCORE
        ][:_AI_TOP_N]
        if ai_queue:
            ai_outcomes = await asyncio.gather(
                *[_ai_signal(r) for r in ai_queue],
                return_exceptions=True,
            )
            for r, ai in zip(ai_queue, ai_outcomes):
                if ai and not isinstance(ai, Exception):
                    r["ai_signal"] = ai

    # ── Phase 8: Summary ──────────────────────────────────────────────────────
    return _build_summary(filtered)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _build_summary(filtered: list[dict]) -> dict:
    all_sigs   = [r.get("ignition_signal", "NO_IGNITION") for r in filtered]
    by_bucket:  dict[str, int] = {}
    by_signal:  dict[str, int] = {}
    for r in filtered:
        b = r.get("ignition_bucket", "NONE")
        s = r.get("unified_signal",  "AVOID")
        by_bucket[b] = by_bucket.get(b, 0) + 1
        by_signal[s] = by_signal.get(s, 0) + 1

    return {
        "results": filtered,
        "summary": {
            "total":        len(filtered),
            "confirmed":    all_sigs.count("IGNITION_CONFIRMED"),
            "early":        all_sigs.count("EARLY_IGNITION"),
            "watch":        all_sigs.count("IGNITION_WATCH"),
            "no_signal":    all_sigs.count("NO_IGNITION"),
            "from_main":    sum(1 for r in filtered if r.get("source") == "main_scan"),
            "from_ribbon":  sum(1 for r in filtered if r.get("source") == "ribbon_pass"),
            "by_bucket":    by_bucket,
            "by_unified_signal": by_signal,
            "strong_buy":   by_signal.get("STRONG_BUY", 0),
            "buy":          by_signal.get("BUY",        0),
            "watch_count":  by_signal.get("WATCH",      0),
            "hype_enriched": sum(
                1 for r in filtered
                if (r.get("hype_context") or {}).get("hype_tier") not in ("COLD", None)
            ),
            "macro_enriched": sum(
                1 for r in filtered
                if (r.get("macro_context") or {}).get("market_bias")
                not in ("NEUTRAL", None, "")
            ),
            "sympathy_plays": sum(
                1 for r in filtered
                if (r.get("sector_context") or {}).get("is_sympathy")
            ),
            "ai_analyzed":  sum(1 for r in filtered if r.get("ai_signal")),
            "scoring_weights": {
                "ribbon":   _W_RIBBON,
                "ignition": _W_IGNITION,
                "sector":   _W_SECTOR,
                "hype":     _W_HYPE,
                "macro":    _W_MACRO,
            },
        },
    }


def _empty_response() -> dict:
    return {
        "results": [],
        "summary": {
            "total": 0, "confirmed": 0, "early": 0, "watch": 0,
            "no_signal": 0, "from_main": 0, "from_ribbon": 0,
            "by_bucket": {}, "by_unified_signal": {},
            "strong_buy": 0, "buy": 0, "watch_count": 0,
            "hype_enriched": 0, "macro_enriched": 0,
            "sympathy_plays": 0, "ai_analyzed": 0,
            "scoring_weights": {
                "ribbon": _W_RIBBON, "ignition": _W_IGNITION,
                "sector": _W_SECTOR, "hype": _W_HYPE, "macro": _W_MACRO,
            },
        },
    }
