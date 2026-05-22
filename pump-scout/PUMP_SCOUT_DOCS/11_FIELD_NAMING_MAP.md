# Field Naming Map — Cross-Table Signal Reference

Same concept, different column names across tables. The differences are
**semantic, not accidental** — each table captures the signal at a
different point in time. Use this map when writing cross-table joins or
analytics queries.

## Bar-level signals (TZ, PREUP, line3/4/5, WLNBB, wyckoff)

All four storage layers ultimately call the same computation in
`scanner/manual_d_wlnbb_features.py::compute_combined_bar_labels()`.
The only thing that differs is **at which bar** the value is captured.

| Concept                 | Live (`demand_ticker_history`)        | Replay (`replay_signal_candidates`) | Pump Study (`pump_episodes`)              | Raw Pattern (`raw_pattern_episode_features`) |
| ---                     | ---                                   | ---                                 | ---                                       | ---                                          |
| Current-bar T signal    | `tz_t_signal`                         | `tz_t_signal`                       | `tz_t_signal_at_breakout`                 | `tz_t_signal_at_breakout`                    |
| Current-bar Z signal    | `tz_z_signal`                         | `tz_z_signal`                       | `tz_z_signal_at_breakout`                 | `tz_z_signal_at_breakout`                    |
| Best T over 15 bars     | `best_tz_t_signal_15bar`              | `best_tz_t_signal_15bar`            | `best_tz_t_signal_15bar`                  | `best_tz_t_signal_15bar`                     |
| PREUP token (P55, P89…) | `preup_token`                         | `preup_token`                       | `preup_token_at_breakout`                 | `preup_token_at_breakout`                    |
| PREDN token (D55, D89…) | `predn_token`                         | `predn_token`                       | —                                         | —                                            |
| Body / wick class       | `line3`                               | `line3`                             | `line3_at_breakout`                       | `line3_at_breakout`                          |
| Gap / range class       | `line4`                               | `line4`                             | `line4_at_breakout`                       | `line4_at_breakout`                          |
| VX / PSAR / RSI2        | `line5`                               | `line5`                             | `line5_at_breakout`                       | `line5_at_breakout`                          |
| WLNBB L-digits          | `l_digits`                            | —                                   | embedded in `summary_json`                | —                                            |
| Wyckoff regime          | `wyckoff_state` (snapshot at scan)    | `wyckoff_state` (snapshot at scan)  | `strongest_wyckoff_state` (window-strongest) | `strongest_wyckoff_state`                 |

### Semantic difference: "at breakout" vs snapshot

- **`*_at_breakout`** (Pump Study, Raw Pattern) — captured on the **last
  PRE bar** of an episode (the bar immediately before pump_start_date).
  Immutable record of "what the bar looked like the day before it
  popped." Used for retrospective lift analysis.
- **`*` (no suffix)** (Live, Replay) — captured on the **current bar**
  of the scan. A daily snapshot. Used for forward monitoring.

A symbol can therefore appear with `tz_t_signal = T4` in
`demand_ticker_history` on 2026-04-10 (because scan-bar 2026-04-10 was
T4) and `tz_t_signal_at_breakout = T1G` in `pump_episodes` for an
episode that started 2026-04-15 (because pre-bar 2026-04-14 was T1G).
**These are different bars; both correct.**

### Wyckoff is the noisy one

| Column                         | Where         | Meaning                                                          |
| ---                            | ---           | ---                                                              |
| `wyckoff`                      | `scan_candidates` | Legacy short name. Current-day state.                        |
| `wyckoff_state`                | `demand_ticker_history`, `replay_signal_candidates` | Current-day state (renamed for clarity). |
| `strongest_wyckoff_state`      | `pump_episodes`, `raw_pattern_episode_features` | **Strongest** state observed across the episode's window. Always ≥ current state. |
| `entry_wyckoff`                | `journal` | State at the moment of journaling, frozen.                          |

Pattern Study analyses `strongest_wyckoff_state` because the question
is "what regime was the symbol *capable of* during the pre-pump window."
Live monitoring uses `wyckoff_state` because the question is "what is
the symbol in *right now*."

## Demand composite signals

| Concept                           | Live (`demand_ticker_history`) | Replay (`replay_signal_candidates`) | Pump Study (`pump_episodes`)             |
| ---                               | ---                            | ---                                 | ---                                      |
| Final 0–20 score                  | `demand_composite_score`       | `demand_composite_score`            | `demand_score_at_breakout`               |
| Tier (PRIME_BUY / HIGH_CONF / …)  | `demand_composite_tier`        | `demand_composite_tier`             | `demand_tier_at_breakout`                |
| ATS signal                        | `ats_signal`                   | `ats_signal`                        | `ats_at_breakout`                        |
| Confluence signal list            | `confluence_signals` (CSV)     | (in `flow_signals_json`)            | `confluence_signals` (JSON, episode-wide)|
| Score breakdown JSON              | —                              | `demand_breakdown_json`             | (in `summary_json`)                      |

`demand_*` fields **depend on `scoring_config.VERSION`**. Bar-level
signals (TZ, preup, line3-5, wlnbb) do NOT — they are pure OHLCV math.

## Run lineage

Every run row records the `scoring_config.VERSION` that produced it:

| Table                | Column                     | When captured                  |
| ---                  | ---                        | ---                            |
| `replay_runs`        | `scoring_config_version`   | `create_replay_run()`          |
| `pump_study_runs`    | `scoring_config_version`   | `create_pump_study_run()`      |
| `raw_pattern_runs`   | `scoring_config_version`   | `create_raw_pattern_run()`     |
| `demand_ticker_history` | `scoring_config_version`| `save_demand_ticker_history()` |

Use this column to filter results by config version when comparing
across calibration iterations. The Pump Study `/score-demand` endpoint
re-scores an existing run and bumps both the pump-study and linked
raw-pattern run to the current version.

## Cross-table query patterns

### "What did Live see the day before a confirmed pump?"

```sql
SELECT h.*
FROM   demand_ticker_history h
JOIN   pump_episodes        e ON e.symbol = h.symbol
WHERE  date(h.scanned_at) = date(e.pump_start_date, '-1 day')
   AND e.pump_multiple >= 2.0;
```

This is the **lift-analysis bridge**. Compare what the scanner emitted
in real time vs the back-tested view in `pump_episodes`. Catch /
missed-mover analysis becomes one query.

### "Filter Live history by signal combo"

```sql
SELECT *
FROM   demand_ticker_history
WHERE  tz_t_signal IN ('T1', 'T1G', 'T4')
  AND  preup_token = 'P55'
  AND  line5 LIKE '%R2X%'
  AND  scanned_at > date('now', '-30 days');
```

### "Same combo, but compare across config versions"

```sql
SELECT scoring_config_version,
       COUNT(*) AS n,
       AVG(demand_composite_score) AS avg_score,
       AVG(combined_score)         AS avg_combined
FROM   demand_ticker_history
WHERE  preup_token = 'P55' AND tz_t_signal = 'T1G'
GROUP BY scoring_config_version;
```

## Why we don't rename the columns

Several tables ship to production with established schemas. Renaming
`demand_tier_at_breakout` → `demand_composite_tier` would:

- Break every callsite that reads `pump_episodes`
- Erase the semantic distinction (the column really IS captured at a
  different bar than the Live column)
- Require migrations of years-old episode data

The naming differences encode meaning. This document is the lookup.
