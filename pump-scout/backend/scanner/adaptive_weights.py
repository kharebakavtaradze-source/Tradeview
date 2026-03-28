"""
Adaptive scoring weights derived from closed journal trades.
Activates after 30+ closed trades with known outcome.
"""
import logging
import time

logger = logging.getLogger(__name__)

_cache: dict | None = None
_cache_ts: float = 0
_CACHE_TTL = 3600  # 1 hour


async def get_adaptive_weights() -> dict:
    """
    Analyze closed journal trades and return weight adjustments.
    Returns defaults with explanation if fewer than 5 trades available.
    """
    global _cache, _cache_ts

    now = time.time()
    if _cache and (now - _cache_ts) < _CACHE_TTL:
        return _cache

    try:
        from database import get_journal
        entries = await get_journal()
        closed = [
            e for e in entries
            if e.get("status") in ("CLOSED", "STOPPED")
            and e.get("final_pnl_pct") is not None
        ]
    except Exception as e:
        logger.warning(f"adaptive_weights: DB lookup failed: {e}")
        return _default_weights(0)

    if len(closed) < 30:
        result = _default_weights(len(closed))
        _cache = result
        _cache_ts = now
        return result

    wins = [t for t in closed if (t.get("final_pnl_pct") or 0) > 0]

    win_cmf_avg = (
        sum(t.get("entry_cmf_pctl") or 50 for t in wins) / len(wins)
        if wins else 50.0
    )
    win_hype_avg = (
        sum(t.get("entry_hype") or 20 for t in wins) / len(wins)
        if wins else 20.0
    )

    # Best Wyckoff state by win frequency
    win_wyckoff: dict = {}
    for t in wins:
        w = t.get("entry_wyckoff") or "UNKNOWN"
        win_wyckoff[w] = win_wyckoff.get(w, 0) + 1
    best_wyckoff = (
        max(win_wyckoff, key=win_wyckoff.get)
        if win_wyckoff else "STEALTH_BASE"
    )

    result = {
        "active": True,
        "win_rate": round(len(wins) / len(closed), 3),
        "data_points": len(closed),
        "best_wyckoff": best_wyckoff,
        "optimal_cmf_min": round(win_cmf_avg * 0.8, 1),
        "optimal_hype_max": round(win_hype_avg * 1.2, 1),
        "cmf_weight": 1.2 if win_cmf_avg > 70 else 0.8,
        "wyckoff_weight": 1.3,
        "vol_weight": 1.0,
        "hype_weight": 1.1,
        "note": f"Адаптировано на основе {len(closed)} закрытых сделок",
    }

    _cache = result
    _cache_ts = now
    return result


def _default_weights(data_points: int) -> dict:
    return {
        "active": False,
        "win_rate": None,
        "data_points": data_points,
        "best_wyckoff": None,
        "optimal_cmf_min": None,
        "optimal_hype_max": None,
        "cmf_weight": 1.0,
        "wyckoff_weight": 1.0,
        "vol_weight": 1.0,
        "hype_weight": 1.0,
        "note": f"Нужно минимум 30 закрытых сделок для адаптации (сейчас {data_points})",
    }
