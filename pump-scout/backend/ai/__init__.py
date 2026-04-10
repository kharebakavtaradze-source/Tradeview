"""
AI Analysis Layer — advisory, read-only, additive.

Three modules:
  analyst        — per-ticker structured commentary on current scan candidates
  reviewer       — retrospective review of past trades and missed opportunities
  insight_engine — pattern-level observations and suggested experiments

None of these modules modify scan scores, tiers, or any production logic.
"""
