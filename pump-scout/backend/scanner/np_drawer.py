"""
New Pump ticker detail drawer — backend aggregation layer.

Builds a structured payload for one symbol to power the right-side drawer on the NP page.
All sections fail independently — one broken source never kills the whole response.

Cache: in-memory 30-min TTL per symbol.
"""
import asyncio
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ── In-memory drawer cache ────────────────────────────────────────────────────
_cache: dict[str, dict] = {}
_CACHE_TTL = 1800  # 30 min


def _cached(symbol: str) -> Optional[dict]:
    entry = _cache.get(symbol)
    if entry and (time.time() - entry["ts"]) < _CACHE_TTL:
        return entry["data"]
    return None


def _store(symbol: str, data: dict) -> None:
    _cache[symbol] = {"data": data, "ts": time.time()}


def invalidate(symbol: str | None = None) -> None:
    if symbol:
        _cache.pop(symbol.upper(), None)
    else:
        _cache.clear()


# ── Section builders ──────────────────────────────────────────────────────────

def _build_signal_timeline(np: dict) -> dict:
    age_l34   = np.get("age_l34")
    age_fri34 = np.get("age_fri34")
    age_g4    = np.get("age_g4")
    age_b2    = np.get("age_b2")
    seq       = np.get("new_pump_sequence_label", "NONE")

    def _sig(exists, age, max_fresh):
        return {
            "exists": bool(exists),
            "age":    age,
            "fresh":  age is not None and age <= max_fresh,
            "stale":  age is not None and age > max_fresh,
        }

    notes = []
    if age_fri34 is not None and age_l34 is not None:
        notes.append(f"FRI34 at bar -{age_fri34}, L34 at bar -{age_l34}")
    elif age_fri34 is not None:
        notes.append(f"FRI34 setup at bar -{age_fri34}")
    elif age_l34 is not None:
        notes.append(f"L34 setup at bar -{age_l34}")

    if age_g4 is not None:
        notes.append(f"G4 trigger at bar -{age_g4}")
    if age_b2 is not None:
        notes.append(f"B2 confirm at bar -{age_b2}")

    if seq.startswith("FULL"):
        notes.append("Full setup→trigger→confirm sequence detected")
    elif seq.startswith("TRIGGER_AFTER"):
        notes.append("Setup + trigger present, no confirmation yet")
    elif seq.startswith("SETUP_ONLY"):
        notes.append("Setup visible, trigger not yet fired")
    elif seq == "ISOLATED_G4":
        notes.append("Isolated G4 trigger — no supporting setup")
    elif seq == "CONFIRM_AFTER_G4":
        notes.append("Confirmation after trigger — no fresh setup")

    return {
        "l34":   _sig(np.get("has_l34"),   age_l34,   10),
        "fri34": _sig(np.get("has_fri34"), age_fri34, 10),
        "g4":    _sig(np.get("has_g4"),    age_g4,    5),
        "b2":    _sig(np.get("has_b2"),    age_b2,    5),
        "sequence_label":  seq,
        "sequence_valid":  seq not in ("NONE", "ISOLATED_B2"),
        "notes": notes,
    }


def _build_np_explanation(np: dict) -> list[str]:
    expl = []
    age_fri34 = np.get("age_fri34")
    age_l34   = np.get("age_l34")
    age_g4    = np.get("age_g4")
    age_b2    = np.get("age_b2")
    score     = np.get("new_pump_score", 0) or 0
    seq       = np.get("new_pump_sequence_label", "NONE")
    mod       = np.get("new_pump_modifier_score", 0) or 0

    if age_fri34 is not None:
        tag = "fresh" if age_fri34 <= 3 else ("recent" if age_fri34 <= 10 else "stale")
        expl.append(f"FRI34 setup detected ({tag}, age {age_fri34})")
    elif age_l34 is not None:
        tag = "fresh" if age_l34 <= 3 else ("recent" if age_l34 <= 10 else "stale")
        expl.append(f"L34 setup detected ({tag}, age {age_l34})")
    else:
        expl.append("No setup signal (L34/FRI34 absent or stale)")

    if age_g4 is not None:
        tag = "fresh" if age_g4 <= 3 else ("recent" if age_g4 <= 5 else "stale")
        expl.append(f"G4 trigger detected ({tag}, age {age_g4})")

    if age_b2 is not None:
        tag = "fresh" if age_b2 <= 3 else ("recent" if age_b2 <= 5 else "stale")
        expl.append(f"B2 confirmation detected ({tag}, age {age_b2})")

    if seq.startswith("FULL"):
        expl.append("Full ordered sequence bonus applied (reduced — replay penalty)")
    elif seq.startswith("TRIGGER_AFTER_FRI34"):
        expl.append("TRIGGER_AFTER_FRI34 — historically positive sequence")
    elif seq.startswith("TRIGGER_AFTER"):
        expl.append("Trigger after setup — sequence bonus applied")

    if mod >= 8:
        expl.append("Strong EMA bull stack (modifier positive)")
    elif mod <= -4:
        expl.append("Modifier penalty: stale setup or extreme volume anomaly")

    setup_s = np.get("new_pump_setup_score", 0) or 0
    trig_s  = np.get("new_pump_trigger_score", 0) or 0
    conf_s  = np.get("new_pump_confirm_score", 0) or 0
    expl.append(f"Score breakdown: setup={setup_s} trigger={trig_s} confirm={conf_s} mod={mod} → {score:.1f}")

    return expl


def _build_red_flags(np: dict, news: dict, identity: dict) -> list[str]:
    flags = []
    age_l34   = np.get("age_l34")
    age_fri34 = np.get("age_fri34")
    age_g4    = np.get("age_g4")
    age_b2    = np.get("age_b2")
    seq       = np.get("new_pump_sequence_label", "NONE")
    state     = np.get("state", "")

    best_setup = min((a for a in (age_l34, age_fri34) if a is not None), default=None)
    if best_setup is None:
        flags.append("no_setup_signal")
    elif best_setup > 8:
        # Stale setup age — show as caution, but do NOT treat as late confirm
        flags.append("stale_setup")

    if seq in ("ISOLATED_G4", "ISOLATED_B2"):
        flags.append("isolated_signal")

    # Late Confirm: only flag when B2 is absent/stale OR state is not CONFIRMED.
    # FULL sequences with fresh B2 (age_b2 <= 2) + CONFIRMED state are NOT late —
    # v3.6 BUY whitelist explicitly includes FULL_FRI34_G4_B2 and FULL_L34_G4_B2.
    if seq in ("FULL_FRI34_G4_B2", "FULL_L34_G4_B2"):
        if state == "CONFIRMED" and age_b2 is not None and age_b2 <= 2:
            pass  # fresh confirmed — not late
        elif age_b2 is not None and age_b2 > 2:
            flags.append("late_confirm_sequence")
        # else: no B2 age data or non-confirmed — treat as neutral, not late
    elif seq == "CONFIRM_AFTER_G4":
        flags.append("late_confirm_sequence")

    avg_vol = identity.get("avg_volume_20d") or 0
    if avg_vol and avg_vol < 200_000:
        flags.append("low_liquidity")

    if news:
        headlines = news.get("headlines_7d", [])
        for h in headlines:
            title_low = (h.get("title") or "").lower()
            if any(w in title_low for w in ("offering", "dilut", "shares sold", "registered direct")):
                flags.append("dilution_risk")
                break
        for h in headlines:
            title_low = (h.get("title") or "").lower()
            if "reverse split" in title_low or "reverse stock split" in title_low:
                flags.append("reverse_split_risk")
                break
        if not news.get("has_real_news") and not news.get("catalyst_summary"):
            flags.append("no_catalyst")

    market_cap = identity.get("market_cap") or 0
    if market_cap and market_cap < 50_000_000:
        flags.append("micro_cap")

    return list(dict.fromkeys(flags))  # deduplicate, preserve order


def _build_final_verdict(np: dict, flags: list[str], news: dict) -> dict:
    seq      = np.get("new_pump_sequence_label", "NONE")
    score    = np.get("new_pump_score", 0) or 0
    label    = np.get("new_pump_label", "NEW_PUMP_NONE")
    decision = np.get("decision")                   # v3.6 engine decision (authoritative)
    d_reason = np.get("decision_reason") or ""
    ss       = np.get("structure_score") or 0

    # Hard invalidation — ONLY dilution / reverse split override BUY_CANDIDATE.
    # late_confirm, no_catalyst, mixed_catalyst are informational cautions, not hard blocks.
    hard_flags = {"dilution_risk", "reverse_split_risk"}
    has_hard_danger = bool(set(flags) & hard_flags)

    if has_hard_danger:
        return {
            "technical_decision": decision or "AVOID",
            "verdict": "avoid",
            "short_reason": "Dilution or reverse-split risk detected — hard invalidation",
            "key_confirmation_note": None,
            "invalidation_note": "Dilution or reverse split confirmed — hard invalidation",
        }

    # ── v3.6 engine decision is the primary authority ────────────────────────
    if decision == "BUY_CANDIDATE":
        return {
            "technical_decision": "BUY_CANDIDATE",
            "verdict": "strong_setup",
            "short_reason": d_reason or f"BUY_CANDIDATE — structure confirmed (score {ss})",
            "key_confirmation_note": "Structure phase confirmed by v3.6 engine",
            "invalidation_note": "Close below setup low or volume dry-up invalidates",
        }

    if decision == "WATCH":
        return {
            "technical_decision": "WATCH",
            "verdict": "watch",
            "short_reason": d_reason or f"WATCH — {seq}",
            "key_confirmation_note": None,
            "invalidation_note": None,
        }

    if decision in ("AVOID", "IMPULSE_RISK"):
        return {
            "technical_decision": decision,
            "verdict": "avoid",
            "short_reason": d_reason or f"{decision} — {seq}",
            "key_confirmation_note": None,
            "invalidation_note": None,
        }

    # ── Legacy fallback (no decision field — pre-v3.6 cache entry) ───────────
    has_catalyst = news.get("has_real_news") or bool(news.get("catalyst_summary"))

    if label in ("NEW_PUMP_FIRE", "NEW_PUMP_STRONG") and seq.startswith("TRIGGER_AFTER"):
        return {
            "technical_decision": None,
            "verdict": "strong_setup",
            "short_reason": f"Strong score ({score:.0f}) with clean trigger sequence",
            "key_confirmation_note": "Watch for B2 confirmation in next 1–3 bars",
            "invalidation_note": "Trigger fails if price closes below setup low",
        }

    if label in ("NEW_PUMP_STRONG", "NEW_PUMP_SETUP") and has_catalyst:
        return {
            "technical_decision": None,
            "verdict": "interesting",
            "short_reason": f"{seq} + catalyst present",
            "key_confirmation_note": "Catalyst + structure aligned",
            "invalidation_note": "Fades on volume dry-up",
        }

    if label in ("NEW_PUMP_TRIGGER_ONLY", "NEW_PUMP_SETUP") and "stale_setup" not in flags:
        return {
            "technical_decision": None,
            "verdict": "watch",
            "short_reason": "Early structure visible — not confirmed",
            "key_confirmation_note": "Watch for G4 or B2 follow-through",
            "invalidation_note": "No follow-through in 3–5 bars = invalidated",
        }

    return {
        "technical_decision": None,
        "verdict": "watch",
        "short_reason": f"Score {score:.0f}, sequence {seq}",
        "key_confirmation_note": None,
        "invalidation_note": None,
    }


def _tag_headline(title: str) -> str | None:
    t = title.lower()
    if any(w in t for w in ("earn", "eps", "revenue", "beat", "miss")):
        return "earnings"
    if any(w in t for w in ("fda", "approval", "pdufa", "nda", "510k")):
        return "FDA"
    if any(w in t for w in ("offering", "dilut", "shares sold", "atm")):
        return "dilution_risk"
    if any(w in t for w in ("contract", "award", "defense", "government")):
        return "contract"
    if any(w in t for w in ("partner", "agreement", "deal", "collaborat")):
        return "partnership"
    if any(w in t for w in (" ai ", "artificial intelligence", "llm", "chatgpt")):
        return "AI"
    if any(w in t for w in ("crypto", "bitcoin", "blockchain")):
        return "crypto"
    if any(w in t for w in ("lawsuit", "sec invest", "fraud", "probe")):
        return "legal_issue"
    if any(w in t for w in ("reverse split",)):
        return "dilution_risk"
    return None


def _build_news_section(raw: dict) -> dict:
    headlines = raw.get("headlines_7d", raw.get("headlines", []))[:5]
    tagged = []
    for h in headlines:
        tagged.append({
            "title":     h.get("title") or "",
            "source":    h.get("publisher") or h.get("source") or "",
            "hours_ago": h.get("hours_ago"),
            "sentiment": h.get("sentiment") or "neutral",
            "tag":       _tag_headline(h.get("title") or ""),
            "url":       h.get("url"),
        })

    catalyst = raw.get("catalyst_summary") or ""
    has_real  = raw.get("has_real_news", False)
    count     = raw.get("count_7d", 0) or 0

    if not has_real and count == 0:
        verdict = "no_meaningful_catalyst"
    elif any(h.get("sentiment") == "bearish" for h in tagged):
        verdict = "negative_catalyst" if sum(
            1 for h in tagged if h.get("sentiment") == "bearish"
        ) > len(tagged) // 2 else "mixed_catalyst"
    elif has_real and catalyst:
        verdict = "strong_catalyst"
    else:
        verdict = "mixed_catalyst"

    return {
        "headlines":        tagged,
        "catalyst_summary": catalyst,
        "has_real_news":    has_real,
        "has_sec_filing":   raw.get("has_sec_filing", False),
        "count_7d":         count,
        "verdict":          verdict,
    }


def _build_d_wlnbb_section(bars: list[dict], np_result: dict) -> dict:
    """
    Build D / WLNBB confluence section for the drawer.
    Research-only — not used in scoring/routing.
    """
    has_runner_fields = np_result.get("d_confluence_type") is not None

    if has_runner_fields:
        from scanner.manual_d_wlnbb_features import _empty_confluence as _ec
        _defaults = _ec()
        result = {k: np_result.get(k, v) for k, v in _defaults.items()}
        result["source"] = "scan_cache"
        return result

    if not bars or len(bars) < 30:
        return {"d_confluence_type": "NONE", "active_d_signals": [], "active_wlnbb_signals": [], "source": "unavailable"}

    try:
        from scanner.manual_d_wlnbb_features import compute_d_wlnbb_confluence
        result = compute_d_wlnbb_confluence(bars)
        result["source"] = "fresh_compute"
        return result
    except Exception as e:
        logger.warning(f"[NpDrawer] d_wlnbb fresh compute failed: {e}")
        return {"d_confluence_type": "NONE", "active_d_signals": [], "active_wlnbb_signals": [], "source": "error"}


def _build_technical_context(bars: list[dict], np: dict) -> dict:
    if not bars or len(bars) < 20:
        return {}

    closes  = [b["close"]  for b in bars]
    volumes = [b["volume"] for b in bars]
    last    = len(bars) - 1

    from scanner.new_pump_engine import _compute_ema, _sma, _std

    ema20  = _compute_ema(closes, 20)[last]
    ema50  = _compute_ema(closes, 50)[last]
    ema200 = _compute_ema(closes, 200)[last]
    close  = closes[last]

    vol_win = volumes[max(0, last - 19): last + 1]
    vol_mid = _sma(vol_win, 20)
    vol_std = _std(vol_win, 20)
    volume_z = None
    if vol_mid and vol_std and vol_std > 0:
        volume_z = round((volumes[last] - vol_mid) / vol_std, 2)

    dv_win  = [closes[j] * volumes[j] for j in range(max(0, last - 19), last + 1)]
    avg_dv  = sum(dv_win) / len(dv_win) if dv_win else None
    cur_dv  = close * volumes[last]
    dv_ratio = round(cur_dv / avg_dv, 2) if avg_dv else None

    ema_stack = None
    if ema20 and ema50 and ema200:
        if ema20 > ema50 > ema200:
            ema_stack = "full_bull"
        elif ema20 > ema50:
            ema_stack = "partial_bull"
        elif ema20 < ema50 < ema200:
            ema_stack = "full_bear"
        else:
            ema_stack = "mixed"
    elif ema20 and ema50:
        ema_stack = "partial_bull" if ema20 > ema50 else "partial_bear"

    ema_spread_pct = None
    if ema20 and ema200 and ema200 > 0:
        ema_spread_pct = round((ema20 - ema200) / ema200 * 100, 1)

    return {
        "ema_stack":       ema_stack,
        "ema20":           round(ema20, 2) if ema20 else None,
        "ema50":           round(ema50, 2) if ema50 else None,
        "ema200":          round(ema200, 2) if ema200 else None,
        "above_ema50":     bool(ema50 and close > ema50),
        "above_ema200":    bool(ema200 and close > ema200),
        "ema_spread_pct":  ema_spread_pct,
        "volume_z":        volume_z,
        "avg_dv_20d":      round(avg_dv) if avg_dv else None,
        "dv_ratio":        dv_ratio,
    }


# ── Main aggregator ───────────────────────────────────────────────────────────

async def build_drawer_payload(symbol: str) -> dict:
    symbol = symbol.upper()

    cached = _cached(symbol)
    if cached:
        return cached

    # ── 1. New Pump fields (scan cache → fresh analyze fallback) ──────────────
    from scanner.new_pump_runner import get_latest
    np_result: dict = {}
    bars: list[dict] = []

    scan_data = get_latest()
    for r in scan_data.get("results", []):
        if r.get("symbol") == symbol:
            np_result = r
            break

    if not np_result:
        # Not in scan cache — fetch candles fresh and analyze
        try:
            from scanner.massive_data import fetch_candles_massive
            from scanner.new_pump_engine import analyze as np_analyze
            raw_bars = await fetch_candles_massive(symbol, days=200)
            if raw_bars and len(raw_bars) >= 60:
                bars = [{"open": c["o"], "high": c["h"], "low": c["l"],
                         "close": c["c"], "volume": c["v"]} for c in raw_bars]
                np_fields = np_analyze(bars)
                last = raw_bars[-1]
                vol_slice = [c["v"] for c in raw_bars[-20:] if c.get("v")]
                avg_vol = sum(vol_slice) / len(vol_slice) if vol_slice else 0
                np_result = {
                    "symbol": symbol,
                    "price": last.get("c"),
                    "volume_today": last.get("v"),
                    "avg_volume_20d": round(avg_vol),
                    **np_fields,
                }
        except Exception as e:
            logger.warning(f"[NpDrawer] fresh analyze failed for {symbol}: {e}")

    if not np_result:
        return {"ok": False, "symbol": symbol, "error": "Symbol not found in scan and fresh fetch failed"}

    # Build bars from cache candles if not already set
    if not bars:
        try:
            from scanner.massive_data import fetch_candles_massive
            raw_bars = await fetch_candles_massive(symbol, days=200)
            if raw_bars:
                bars = [{"open": c["o"], "high": c["h"], "low": c["l"],
                         "close": c["c"], "volume": c["v"]} for c in raw_bars]
        except Exception:
            pass

    # ── 2. Gather identity + news + regime concurrently ───────────────────────
    async def _get_sector():
        try:
            from database import get_sector_full_from_db
            return await get_sector_full_from_db(symbol)
        except Exception:
            return None

    async def _get_news():
        try:
            from hype_monitor.fetcher import fetch_yahoo_news_hype
            return await fetch_yahoo_news_hype(symbol)
        except Exception:
            return {}

    async def _get_regime():
        try:
            from database import get_market_regime_latest
            return await get_market_regime_latest()
        except Exception:
            return None

    sector_data, news_raw, regime = await asyncio.gather(
        _get_sector(), _get_news(), _get_regime(),
        return_exceptions=True,
    )
    if isinstance(sector_data, Exception): sector_data = None
    if isinstance(news_raw, Exception):    news_raw = {}
    if isinstance(regime, Exception):      regime = None

    # ── 3. Build sections ─────────────────────────────────────────────────────
    identity = {
        "symbol":         symbol,
        "company_name":   (sector_data or {}).get("company_name"),
        "sector":         (sector_data or {}).get("sector"),
        "industry":       (sector_data or {}).get("industry"),
        "market_cap":     (sector_data or {}).get("market_cap"),
        "exchange":       None,
        "country":        "US",
        "current_price":  np_result.get("price"),
        "avg_volume_20d": np_result.get("avg_volume_20d"),
    }

    np_section = {
        "new_pump_score":          np_result.get("new_pump_score"),
        "new_pump_label":          np_result.get("new_pump_label"),
        "new_pump_sequence_label": np_result.get("new_pump_sequence_label"),
        "has_l34":                 np_result.get("has_l34"),
        "has_fri34":               np_result.get("has_fri34"),
        "has_g4":                  np_result.get("has_g4"),
        "has_b2":                  np_result.get("has_b2"),
        "age_l34":                 np_result.get("age_l34"),
        "age_fri34":               np_result.get("age_fri34"),
        "age_g4":                  np_result.get("age_g4"),
        "age_b2":                  np_result.get("age_b2"),
        "new_pump_setup_score":    np_result.get("new_pump_setup_score"),
        "new_pump_trigger_score":  np_result.get("new_pump_trigger_score"),
        "new_pump_confirm_score":  np_result.get("new_pump_confirm_score"),
        "new_pump_modifier_score": np_result.get("new_pump_modifier_score"),
        "explanation":             _build_np_explanation(np_result),
        # v3.6 decision authority fields
        "decision":                np_result.get("decision"),
        "decision_reason":         np_result.get("decision_reason"),
        "decision_flags":          np_result.get("decision_flags"),
        "structure_phase":         np_result.get("structure_phase"),
        "structure_score":         np_result.get("structure_score"),
        "structure_advisory":      np_result.get("structure_advisory"),
        "state":                   np_result.get("state"),
    }

    signal_timeline  = _build_signal_timeline(np_result)
    company_summary  = {
        "sector":   identity["sector"],
        "industry": identity["industry"],
        "description": None,
    }
    news_section      = _build_news_section(news_raw or {})
    technical_context = _build_technical_context(bars, np_result)

    market_context = None
    if regime:
        market_context = {
            "regime":         regime.get("regime"),
            "strong_sectors": (regime.get("strong_sectors") or [])[:4],
            "weak_sectors":   (regime.get("weak_sectors") or [])[:4],
            "recommendation": regime.get("recommendation"),
        }

    red_flags     = _build_red_flags(np_result, news_raw or {}, identity)
    final_verdict = _build_final_verdict(np_result, red_flags, news_section)
    d_wlnbb       = _build_d_wlnbb_section(bars, np_result)

    payload = {
        "ok":               True,
        "symbol":           symbol,
        "identity":         identity,
        "new_pump":         np_section,
        "signal_timeline":  signal_timeline,
        "company_summary":  company_summary,
        "news":             news_section,
        "technical_context": technical_context,
        "market_context":   market_context,
        "ai_analysis":      None,
        "red_flags":        red_flags,
        "final_verdict":    final_verdict,
        "d_wlnbb":          d_wlnbb,
    }

    _store(symbol, payload)
    return payload
