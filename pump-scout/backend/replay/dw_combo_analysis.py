"""
D/WLNBB Combo Analysis — Layer 2 validation script.

Run this on Railway (or locally with DATABASE_URL set) to validate which
d_confluence_type_v2 combos qualify for the structure-score boost gate:
  Qualification: n >= 30  AND  WR5d >= 65%

Usage:
  DATABASE_URL=postgresql+asyncpg://... python -m replay.dw_combo_analysis
  -- or --
  cd pump-scout/backend && python -m replay.dw_combo_analysis

Output: per-combo table with n, WR5d, avg_ret5d, and QUALIFIED flag.
"""
import asyncio
import json
import os
import sys

REQUIRED_N   = 30
REQUIRED_WR  = 65.0   # percent


async def _run() -> None:
    # Add backend to path
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from database import get_replay_history, get_replay_candidates, get_replay_outcomes

    # Load most recent completed replay runs (up to 3 for cross-run stability)
    runs = await get_replay_history(limit=10)
    completed = [r for r in runs if r.get("status") == "completed"][:3]

    if not completed:
        print("No completed replay runs found.")
        return

    # Aggregate across runs
    buckets: dict[str, list[float]] = {}

    for run in completed:
        run_id = run["id"]
        run_date = (run.get("created_at") or "")[:10]
        total = run.get("total_candidates", 0)
        print(f"Loading run #{run_id} ({run_date})  n={total} candidates …")

        candidates = await get_replay_candidates(run_id, limit=10000)
        outcomes   = await get_replay_outcomes(run_id)

        out_map: dict[int, float] = {
            o["replay_candidate_id"]: o["return_pct"]
            for o in outcomes
            if o.get("horizon") == "5d" and o.get("return_pct") is not None
        }

        for c in candidates:
            cid = c.get("id")
            if cid not in out_map:
                continue

            snap     = c.get("snapshot") or {}
            np_snap  = snap.get("new_pump") or {}

            combo = (np_snap.get("d_confluence_type_v2")
                     or snap.get("d_confluence_type_v2")
                     or "NONE")

            if combo == "NONE":
                continue   # skip no-combo rows — we only care about combos

            ret = out_map[cid]
            if combo not in buckets:
                buckets[combo] = []
            buckets[combo].append(ret)

    if not buckets:
        print("\nNo D/WLNBB combo data found in snapshot JSON.")
        print("Ensure manual_d_wlnbb_features is running and candidates have snapshot data.")
        return

    # Build results table
    rows = []
    for combo, returns in buckets.items():
        n       = len(returns)
        wr      = sum(1 for r in returns if r > 0) / n * 100
        avg_ret = sum(returns) / n
        qualified = n >= REQUIRED_N and wr >= REQUIRED_WR
        rows.append((combo, n, wr, avg_ret, qualified))

    rows.sort(key=lambda x: x[2], reverse=True)  # sort by WR desc

    # Print table
    print()
    print(f"{'COMBO':<30}  {'N':>6}  {'WR5d':>7}  {'AvgRet5d':>9}  {'STATUS'}")
    print("-" * 70)
    for combo, n, wr, avg_ret, qualified in rows:
        status = "✅ QUALIFIED" if qualified else (
                 f"⚠ low-n={n}"  if n < REQUIRED_N else
                 f"✗ WR={wr:.1f}%")
        print(f"  {combo:<28}  {n:>6}  {wr:>6.1f}%  {avg_ret:>+8.2f}%  {status}")

    print()
    print(f"Gate: n ≥ {REQUIRED_N} AND WR5d ≥ {REQUIRED_WR}%")
    print()
    qualified_combos = [combo for combo, n, wr, avg_ret, q in rows if q]
    if qualified_combos:
        print("QUALIFIED combos for _COMBO_BOOST_MAP in new_pump_engine.py:")
        for c in qualified_combos:
            print(f"  \"{c}\": 5,")
    else:
        print("No combos qualify yet — increase replay history or collect more data.")


if __name__ == "__main__":
    asyncio.run(_run())
