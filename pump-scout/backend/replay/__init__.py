"""
Historical Replay / Backdated Scan Mode
========================================
Research-only module. Completely isolated from live production flow.

DOES NOT:
  - modify live scan results or total_score
  - modify live tiers or journal logic
  - mix replay data into live endpoints
  - use future data (strict as_of_date cutoff)

Entry points:
  from replay.replay_engine import run_single_day_replay, run_date_range_replay, get_replay_progress
  from replay.outcome_engine import compute_outcomes_for_run
"""
