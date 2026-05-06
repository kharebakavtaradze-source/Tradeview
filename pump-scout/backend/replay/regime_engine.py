"""
Price / Volatility Regime Layer — research-only analysis for Raw Pattern Discovery.

Computes per-episode regime buckets from pre-phase daily bar data and/or
episode stored fields. Builds regime-stratified performance tables for
pattern analysis so questions like "does FLOW_DIVERGENCE work better above $1?"
can be answered.

Production contract
-------------------
  RESEARCH_ONLY. Do NOT route to Scanner V2 BUY/WATCH/AVOID.
  Do NOT promote to BUY. Do NOT alter Pump Watch scoring.

Anti-leakage
------------
  Reads only PRE-window fields. Never reads group_type outcome data
  during episode regime computation. group_type is only used in
  aggregate stats (build_regime_performance / build_pattern_regime_breakdown)
  which are post-hoc research analyses, not live signal generation.
"""

# ── Price bucket constants ─────────────────────────────────────────────────────

PBUCKET_MICRO    = "PRICE_MICRO_LT_050"
PBUCKET_SUB1     = "PRICE_SUB_1"
PBUCKET_1_TO_3   = "PRICE_1_TO_3"
PBUCKET_3_TO_10  = "PRICE_3_TO_10"
PBUCKET_10_TO_25 = "PRICE_10_TO_25"
PBUCKET_GT25     = "PRICE_GT_25"

ALL_PRICE_BUCKETS: list[str] = [
    PBUCKET_MICRO, PBUCKET_SUB1, PBUCKET_1_TO_3,
    PBUCKET_3_TO_10, PBUCKET_10_TO_25, PBUCKET_GT25,
]

# ── Dollar-volume bucket constants ─────────────────────────────────────────────

DVBUCKET_ILLIQUID = "DV_ILLIQUID_LT_50K"
DVBUCKET_THIN     = "DV_THIN_50K_250K"
DVBUCKET_OK       = "DV_OK_250K_1M"
DVBUCKET_LIQUID   = "DV_LIQUID_1M_10M"
DVBUCKET_HIGH     = "DV_HIGH_GT_10M"

ALL_DV_BUCKETS: list[str] = [
    DVBUCKET_ILLIQUID, DVBUCKET_THIN, DVBUCKET_OK,
    DVBUCKET_LIQUID, DVBUCKET_HIGH,
]

# ── ATR bucket constants ───────────────────────────────────────────────────────

ABUCKET_LOW     = "ATR_LOW_LT_5"
ABUCKET_NORMAL  = "ATR_NORMAL_5_15"
ABUCKET_HIGH    = "ATR_HIGH_15_40"
ABUCKET_EXTREME = "ATR_EXTREME_GT_40"

ALL_ATR_BUCKETS: list[str] = [
    ABUCKET_LOW, ABUCKET_NORMAL, ABUCKET_HIGH, ABUCKET_EXTREME,
]

# ── Compression bucket constants ───────────────────────────────────────────────

CBUCKET_NONE    = "COMP_NONE"
CBUCKET_SHORT   = "COMP_SHORT"
CBUCKET_MEDIUM  = "COMP_MEDIUM"
CBUCKET_LONG    = "COMP_LONG"
CBUCKET_EXTREME = "COMP_EXTREME"

ALL_COMP_BUCKETS: list[str] = [
    CBUCKET_NONE, CBUCKET_SHORT, CBUCKET_MEDIUM, CBUCKET_LONG, CBUCKET_EXTREME,
]

# ── Gap-risk bucket constants ──────────────────────────────────────────────────

GBUCKET_LOW    = "GAP_LOW"
GBUCKET_MEDIUM = "GAP_MEDIUM"
GBUCKET_HIGH   = "GAP_HIGH"

ALL_GAP_BUCKETS: list[str] = [GBUCKET_LOW, GBUCKET_MEDIUM, GBUCKET_HIGH]

# Split-context values used in analysis
_SPLIT_CONTEXTS = ["NO_SPLIT", "OLD_REVERSE_SPLIT", "RECENT_REVERSE_SPLIT"]

# Gap threshold (absolute % change) to count a day as "gapped"
_GAP_DAY_THRESHOLD = 2.0


# ── Bucket classifiers ─────────────────────────────────────────────────────────

def compute_price_bucket(price: float) -> str:
    if not price or price <= 0:
        return PBUCKET_MICRO
    if price < 0.50:
        return PBUCKET_MICRO
    if price < 1.00:
        return PBUCKET_SUB1
    if price < 3.00:
        return PBUCKET_1_TO_3
    if price < 10.00:
        return PBUCKET_3_TO_10
    if price < 25.00:
        return PBUCKET_10_TO_25
    return PBUCKET_GT25


def compute_dv_bucket(dollar_volume: float) -> str:
    if not dollar_volume or dollar_volume < 0:
        return DVBUCKET_ILLIQUID
    if dollar_volume < 50_000:
        return DVBUCKET_ILLIQUID
    if dollar_volume < 250_000:
        return DVBUCKET_THIN
    if dollar_volume < 1_000_000:
        return DVBUCKET_OK
    if dollar_volume < 10_000_000:
        return DVBUCKET_LIQUID
    return DVBUCKET_HIGH


def compute_atr_bucket(atr_pct: float) -> str:
    if atr_pct is None or atr_pct < 0:
        return ABUCKET_NORMAL
    if atr_pct < 5.0:
        return ABUCKET_LOW
    if atr_pct < 15.0:
        return ABUCKET_NORMAL
    if atr_pct < 40.0:
        return ABUCKET_HIGH
    return ABUCKET_EXTREME


def compute_compression_bucket(compression_days: int, min_bb_width) -> str:
    days = compression_days or 0
    if days == 0:
        return CBUCKET_NONE
    if days <= 3:
        return CBUCKET_SHORT
    if days <= 7:
        return CBUCKET_MEDIUM
    if days <= 14:
        return CBUCKET_LONG
    return CBUCKET_EXTREME


def compute_gap_risk_bucket(gap_count: int, max_gap_pct: float) -> str:
    gc  = gap_count  or 0
    mgp = max_gap_pct or 0.0
    if gc == 0 and mgp < _GAP_DAY_THRESHOLD:
        return GBUCKET_LOW
    if mgp >= 10.0 or gc >= 3:
        return GBUCKET_HIGH
    return GBUCKET_MEDIUM


# ── Per-episode regime computation ─────────────────────────────────────────────

def _median(values: list) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 == 1 else (s[mid - 1] + s[mid]) / 2.0


def compute_episode_regime(episode: dict, daily_rows: list[dict]) -> dict:
    """
    Compute regime fields for one episode from PRE-phase daily rows.

    Falls back to episode stored fields (median_dollar_volume_pre,
    compression_days_pre) when daily_rows are sparse or missing.

    Returns a dict with all regime fields. The caller should attach
    this dict to the episode (or store in a cache) — it is not persisted
    to the DB automatically.

    Anti-leakage: reads only close, dollar_volume, atr_pct, bb_width,
    gap_pct from rows and pre-window stored fields on the episode.
    Never reads group_type, pump_multiple, or outcome fields.
    """
    # ── Filter to PRE phase (best-effort) ──────────────────────────────────────
    pre = [r for r in daily_rows if r.get("phase") == "PRE"]
    if not pre:
        pre = daily_rows  # use all if phase tag absent

    # ── Price ──────────────────────────────────────────────────────────────────
    closes = [r["close"] for r in pre if r.get("close") and r["close"] > 0]
    if closes:
        avg_close_pre    = sum(closes) / len(closes)
        median_close_pre = _median(closes)
        breakout_price   = closes[-1]          # last PRE bar = approximate setup price
    else:
        avg_close_pre    = None
        median_close_pre = None
        breakout_price   = None

    price_bucket = (
        compute_price_bucket(median_close_pre)
        if median_close_pre else "PRICE_UNKNOWN"
    )

    # ── Dollar volume ──────────────────────────────────────────────────────────
    dvols = [r["dollar_volume"] for r in pre if r.get("dollar_volume") is not None and r["dollar_volume"] >= 0]
    if dvols:
        median_dv = _median(dvols)
        max_dv    = max(dvols)
    else:
        # Fall back to episode stored field
        median_dv = episode.get("median_dollar_volume_pre")
        max_dv    = None

    dollar_volume_bucket = (
        compute_dv_bucket(median_dv)
        if median_dv is not None else "DV_UNKNOWN"
    )

    # ── Volatility (ATR) ───────────────────────────────────────────────────────
    atrs = [r["atr_pct"] for r in pre if r.get("atr_pct") is not None]
    if atrs:
        avg_atr_pct = sum(atrs) / len(atrs)
        max_atr_pct = max(atrs)
    else:
        avg_atr_pct = None
        max_atr_pct = None

    atr_bucket = (
        compute_atr_bucket(avg_atr_pct)
        if avg_atr_pct is not None else "ATR_UNKNOWN"
    )

    # ── Compression ────────────────────────────────────────────────────────────
    comp_days  = episode.get("compression_days_pre") or 0
    bb_widths  = [r["bb_width"] for r in pre if r.get("bb_width") is not None]
    min_bb_width = min(bb_widths) if bb_widths else None

    compression_bucket = compute_compression_bucket(comp_days, min_bb_width)

    # ── Gap risk ───────────────────────────────────────────────────────────────
    gap_pcts = [r["gap_pct"] for r in pre if r.get("gap_pct") is not None]
    if gap_pcts:
        gap_count   = sum(1 for g in gap_pcts if abs(g) >= _GAP_DAY_THRESHOLD)
        max_gap_pct = max(abs(g) for g in gap_pcts)
    else:
        gap_count   = 0
        max_gap_pct = 0.0

    gap_risk_bucket = compute_gap_risk_bucket(gap_count, max_gap_pct)

    return {
        "avg_close_pre":            round(avg_close_pre,    4) if avg_close_pre    is not None else None,
        "median_close_pre":         round(median_close_pre, 4) if median_close_pre is not None else None,
        "breakout_price":           round(breakout_price,   4) if breakout_price   is not None else None,
        "price_bucket":             price_bucket,
        "median_dollar_volume_pre": round(median_dv, 0)        if median_dv        is not None else None,
        "max_dollar_volume_pre":    round(max_dv,    0)        if max_dv           is not None else None,
        "dollar_volume_bucket":     dollar_volume_bucket,
        "avg_atr_pct_pre":          round(avg_atr_pct, 2)      if avg_atr_pct      is not None else None,
        "max_atr_pct_pre":          round(max_atr_pct, 2)      if max_atr_pct      is not None else None,
        "atr_bucket":               atr_bucket,
        "compression_days_pre":     comp_days,
        "min_bb_width_pre":         round(min_bb_width, 4)     if min_bb_width     is not None else None,
        "compression_bucket":       compression_bucket,
        "gap_count_pre":            gap_count,
        "max_gap_pct_pre":          round(max_gap_pct, 2),
        "gap_risk_bucket":          gap_risk_bucket,
        "split_context":            episode.get("split_context") or "NO_SPLIT",
    }


def _partial_regime_from_episode(episode: dict) -> dict:
    """
    Build a partial regime dict using only stored episode fields
    (no daily rows needed). Price and ATR buckets will be UNKNOWN.
    """
    dv        = episode.get("median_dollar_volume_pre")
    comp_days = episode.get("compression_days_pre") or 0
    sc        = episode.get("split_context") or "NO_SPLIT"

    return {
        "avg_close_pre":            None,
        "median_close_pre":         None,
        "breakout_price":           None,
        "price_bucket":             "PRICE_UNKNOWN",
        "median_dollar_volume_pre": dv,
        "max_dollar_volume_pre":    None,
        "dollar_volume_bucket":     compute_dv_bucket(dv) if dv is not None else "DV_UNKNOWN",
        "avg_atr_pct_pre":          None,
        "max_atr_pct_pre":          None,
        "atr_bucket":               "ATR_UNKNOWN",
        "compression_days_pre":     comp_days,
        "min_bb_width_pre":         None,
        "compression_bucket":       compute_compression_bucket(comp_days, None),
        "gap_count_pre":            0,
        "max_gap_pct_pre":          0.0,
        "gap_risk_bucket":          "GAP_UNKNOWN",
        "split_context":            sc,
        "_partial":                 True,
    }


# ── Episode-level aggregate regime performance ─────────────────────────────────

def _bucket_stats(episodes: list[dict], bucket_field: str, all_buckets: list[str]) -> dict:
    """
    Compute 4x / FP / normal / split counts and rates per bucket value.

    Episodes must have both `bucket_field` and `group_type` (or similar
    indicator of outcome group).
    """
    by_bucket: dict[str, dict] = {}
    for b in all_buckets:
        by_bucket[b] = {"total": 0, "4x": 0, "fp": 0, "normal": 0, "split": 0}

    for ep in episodes:
        bv    = ep.get(bucket_field) or "UNKNOWN"
        group = ep.get("group_type") or ""

        # Normalise group labels to canonical forms
        is_4x  = "4x" in group or group in ("missed_4x_pump", "detected_4x_pump")
        is_fp  = group == "false_positive"
        is_nw  = group == "normal_winner"
        is_art = (group == "split_artifact") or bool(ep.get("split_artifact_risk"))

        if bv not in by_bucket:
            by_bucket[bv] = {"total": 0, "4x": 0, "fp": 0, "normal": 0, "split": 0}

        by_bucket[bv]["total"]  += 1
        if is_4x:  by_bucket[bv]["4x"]     += 1
        if is_fp:  by_bucket[bv]["fp"]     += 1
        if is_nw:  by_bucket[bv]["normal"] += 1
        if is_art: by_bucket[bv]["split"]  += 1

    result: dict = {}
    for bv, counts in by_bucket.items():
        total = counts["total"]
        if total == 0:
            continue
        denom = counts["4x"] + counts["fp"]
        result[bv] = {
            "episode_count": total,
            "count_4x":      counts["4x"],
            "count_fp":      counts["fp"],
            "count_normal":  counts["normal"],
            "count_split":   counts["split"],
            "4x_rate":       round(counts["4x"] / denom, 3) if denom > 0 else None,
            "fp_rate":       round(counts["fp"] / denom, 3) if denom > 0 else None,
        }

    return result


def build_regime_performance(episodes: list[dict]) -> dict:
    """
    Build regime-stratified episode performance tables.

    Input episodes must have regime fields attached (via compute_episode_regime
    or _partial_regime_from_episode). Returns one sub-dict per bucket dimension.
    """
    return {
        "by_price_bucket":         _bucket_stats(episodes, "price_bucket",         ALL_PRICE_BUCKETS),
        "by_dollar_volume_bucket": _bucket_stats(episodes, "dollar_volume_bucket", ALL_DV_BUCKETS),
        "by_atr_bucket":           _bucket_stats(episodes, "atr_bucket",           ALL_ATR_BUCKETS),
        "by_compression_bucket":   _bucket_stats(episodes, "compression_bucket",   ALL_COMP_BUCKETS),
        "by_gap_risk_bucket":      _bucket_stats(episodes, "gap_risk_bucket",       ALL_GAP_BUCKETS),
        "by_split_context":        _bucket_stats(episodes, "split_context",         _SPLIT_CONTEXTS),
    }


# ── Per-pattern regime breakdown ───────────────────────────────────────────────

def build_pattern_regime_breakdown(
    pattern: dict,
    episode_regime_map: dict,   # ep_id → regime dict
) -> dict:
    """
    Compute regime breakdown for one pattern using its matched episode IDs.

    Reads `_matched_by_group` from the pattern dict (set by mine_bar_patterns).
    Returns sub-dicts per bucket dimension, each with matched_count, 4x_count,
    fp_count, 4x_rate, fp_rate per bucket value.

    Returns {} when _matched_by_group is absent or episode_regime_map is empty.
    """
    matched_by_group: dict = pattern.get("_matched_by_group") or {}
    if not matched_by_group or not episode_regime_map:
        return {}

    # Collect all matched episodes with their regime + group label
    matched_eps: list[dict] = []
    for group, ep_ids in matched_by_group.items():
        for ep_id in (ep_ids or []):
            regime = episode_regime_map.get(ep_id)
            if regime is None:
                continue
            matched_eps.append({
                "episode_id": ep_id,
                "group_type": group,
                **regime,
            })

    if not matched_eps:
        return {}

    def _pat_bucket_stats(eps: list[dict], bucket_field: str) -> dict:
        by_b: dict[str, dict] = {}
        for ep in eps:
            b     = ep.get(bucket_field) or "UNKNOWN"
            group = ep.get("group_type") or ""
            is_4x = "4x" in group or group in ("missed_4x_pump", "detected_4x_pump")
            is_fp = group == "false_positive"
            if b not in by_b:
                by_b[b] = {"matched": 0, "4x": 0, "fp": 0}
            by_b[b]["matched"] += 1
            if is_4x: by_b[b]["4x"] += 1
            if is_fp: by_b[b]["fp"] += 1

        result: dict = {}
        for b, c in by_b.items():
            denom = c["4x"] + c["fp"]
            result[b] = {
                "matched_count": c["matched"],
                "4x_count":      c["4x"],
                "fp_count":      c["fp"],
                "4x_rate":  round(c["4x"] / denom, 3) if denom > 0 else None,
                "fp_rate":  round(c["fp"] / denom, 3) if denom > 0 else None,
            }
        return result

    return {
        "by_price_bucket":         _pat_bucket_stats(matched_eps, "price_bucket"),
        "by_dollar_volume_bucket": _pat_bucket_stats(matched_eps, "dollar_volume_bucket"),
        "by_atr_bucket":           _pat_bucket_stats(matched_eps, "atr_bucket"),
        "by_split_context":        _pat_bucket_stats(matched_eps, "split_context"),
        "total_matched":           len(matched_eps),
    }


# ── Clean-tradeable filter ─────────────────────────────────────────────────────

def filter_clean_tradeable_patterns(patterns: list[dict]) -> list[dict]:
    """
    Filter patterns to those most likely to be tradeable in normal market conditions.

    Criteria (cumulative):
      - split_artifact_exposure <= 0.25
      - reverse_split_exposure  <= 0.25 (or None)
      - count_all_4x >= 4
      - false_positive_rate <= 0.35
      - If regime_breakdown present: PRICE_MICRO < 60% of matches
      - If regime_breakdown present: ATR_EXTREME  < 60% of matches
    """
    result = []
    for p in patterns:
        if (p.get("split_artifact_exposure") or 0) > 0.25:
            continue
        if (p.get("reverse_split_exposure")  or 0) > 0.25:
            continue
        if (p.get("count_all_4x") or 0) < 4:
            continue
        if (p.get("false_positive_rate") or 1.0) > 0.35:
            continue

        # Regime dominance check (optional — skip if breakdown absent)
        bd = p.get("regime_breakdown") or {}
        if bd:
            total     = bd.get("total_matched") or 1
            price_bd  = bd.get("by_price_bucket")  or {}
            atr_bd    = bd.get("by_atr_bucket")    or {}
            micro_cnt = (price_bd.get(PBUCKET_MICRO)    or {}).get("matched_count", 0)
            xtr_cnt   = (atr_bd.get(ABUCKET_EXTREME)    or {}).get("matched_count", 0)
            if total > 0:
                if micro_cnt / total > 0.60:
                    continue
                if xtr_cnt   / total > 0.60:
                    continue

        result.append(p)

    return sorted(result, key=lambda x: -(x.get("reliability_score") or 0))


# ── Warning banners ────────────────────────────────────────────────────────────

def build_regime_warnings(episodes: list[dict]) -> list[dict]:
    """
    Generate warning banners from episode regime distribution.

    Checks four conditions and returns a list of warning dicts each with
    level (WARNING | CAUTION), code, and message.
    """
    if not episodes:
        return []

    total = len(episodes)
    warnings: list[dict] = []

    # 1. Reverse-split domination
    rev_split = sum(
        1 for ep in episodes
        if (ep.get("split_context") or "") in ("RECENT_REVERSE_SPLIT", "OLD_REVERSE_SPLIT")
    )
    if rev_split / total > 0.35:
        warnings.append({
            "level":   "WARNING",
            "code":    "REVERSE_SPLIT_DOMINATION",
            "message": (
                f"{rev_split}/{total} episodes ({round(100 * rev_split / total)}%) "
                "involve a reverse split. Pattern performance may be dominated by "
                "reverse-split behaviour rather than clean pump setups. "
                "Use filter_clean_tradeable_patterns to exclude."
            ),
        })

    # 2. Low dollar-volume domination
    low_dv = sum(
        1 for ep in episodes
        if (ep.get("dollar_volume_bucket") or "") in (DVBUCKET_ILLIQUID, DVBUCKET_THIN)
    )
    if low_dv / total > 0.40:
        warnings.append({
            "level":   "WARNING",
            "code":    "LOW_DV_DOMINATION",
            "message": (
                f"{low_dv}/{total} episodes ({round(100 * low_dv / total)}%) "
                "are in ILLIQUID or THIN dollar-volume buckets (<$250K/day). "
                "Most discovered patterns may not be executable at scale."
            ),
        })

    # 3. ATR_EXTREME in false positives
    fp_eps    = [ep for ep in episodes if (ep.get("group_type") or "") == "false_positive"]
    fp_xtreme = sum(1 for ep in fp_eps if (ep.get("atr_bucket") or "") == ABUCKET_EXTREME)
    if fp_eps and fp_xtreme / len(fp_eps) > 0.30:
        warnings.append({
            "level":   "CAUTION",
            "code":    "ATR_EXTREME_IN_FALSE_POSITIVES",
            "message": (
                f"{fp_xtreme}/{len(fp_eps)} false-positive episodes "
                f"({round(100 * fp_xtreme / len(fp_eps))}%) are in ATR_EXTREME regime (>40%). "
                "High-volatility false positives dominate — be cautious with ATR_HIGH+ patterns."
            ),
        })

    # 4. Price < $0.50 domination
    micro_eps = sum(1 for ep in episodes if (ep.get("price_bucket") or "") == PBUCKET_MICRO)
    if micro_eps / total > 0.35:
        warnings.append({
            "level":   "WARNING",
            "code":    "PRICE_MICRO_DOMINATION",
            "message": (
                f"{micro_eps}/{total} episodes ({round(100 * micro_eps / total)}%) "
                "are priced below $0.50 (PRICE_MICRO). "
                "Pattern results are skewed toward sub-penny stocks with high execution risk."
            ),
        })

    return warnings


# ── Master regime analysis builder ────────────────────────────────────────────

_PRICE_BUCKET_LEGEND = {
    PBUCKET_MICRO:    "< $0.50",
    PBUCKET_SUB1:     "$0.50 – $1.00",
    PBUCKET_1_TO_3:   "$1.00 – $3.00",
    PBUCKET_3_TO_10:  "$3.00 – $10.00",
    PBUCKET_10_TO_25: "$10.00 – $25.00",
    PBUCKET_GT25:     "> $25.00",
}

_DV_BUCKET_LEGEND = {
    DVBUCKET_ILLIQUID: "< $50K/day",
    DVBUCKET_THIN:     "$50K – $250K/day",
    DVBUCKET_OK:       "$250K – $1M/day",
    DVBUCKET_LIQUID:   "$1M – $10M/day",
    DVBUCKET_HIGH:     "> $10M/day",
}

_ATR_BUCKET_LEGEND = {
    ABUCKET_LOW:     "ATR < 5%",
    ABUCKET_NORMAL:  "5% – 15%",
    ABUCKET_HIGH:    "15% – 40%",
    ABUCKET_EXTREME: "> 40%",
}


def build_regime_analysis(
    patterns: list[dict],
    episodes: list[dict],
    episode_regime_map: dict,   # {ep_id: regime_dict} — may be empty on cold start
) -> dict:
    """
    Master regime analysis: episode-level performance + per-pattern regime
    breakdowns + regime-filtered ranking tables.

    episode_regime_map is populated during the pipeline run
    (_episode_regime_cache in pattern_discovery_engine). When empty (cold start),
    per-pattern breakdowns are skipped and only episode stored fields are used
    for aggregate performance.

    Returns a dict suitable for inclusion in build_discovery_export() output.
    """
    # ── Enrich episodes with regime fields ────────────────────────────────────
    enriched: list[dict] = []
    for ep in episodes:
        ep_id = ep.get("episode_id") or ep.get("id")
        regime = episode_regime_map.get(ep_id) if ep_id else None
        if regime:
            enriched.append({**ep, **regime})
        else:
            enriched.append({**ep, **_partial_regime_from_episode(ep)})

    # ── Episode-level regime performance ─────────────────────────────────────
    perf = build_regime_performance(enriched)

    # ── Per-pattern regime breakdown ──────────────────────────────────────────
    has_full = bool(episode_regime_map)
    if has_full:
        for p in patterns:
            if "_matched_by_group" in p:
                p["regime_breakdown"] = build_pattern_regime_breakdown(p, episode_regime_map)

    # ── Regime-filtered ranking tables ───────────────────────────────────────
    accepted = [p for p in patterns if p.get("status") in (
        "EXPERIMENTAL", "EXPERIMENTAL_RARE", "RESEARCH_ONLY",
        "VALIDATED_WATCH", "VALIDATED_BUY_SUPPORT",
    )]

    flow_pats   = [p for p in accepted if p.get("feature_family") == "FLOW"]
    custom_pats = [p for p in accepted if p.get("feature_family") == "CUSTOM_SIGNAL"]
    fcc_pats    = [p for p in accepted if p.get("feature_family") == "FLOW_CUSTOM_COMBINED"]

    def _top_by_bucket(pats: list[dict], bucket_dim: str, n: int = 20) -> dict:
        """Group patterns by their best-performing bucket, sorted by reliability."""
        by_b: dict[str, list] = {}
        for p in pats:
            bd = (p.get("regime_breakdown") or {}).get(bucket_dim) or {}
            if not bd:
                continue
            best = max(
                (b for b, stats in bd.items() if (stats.get("4x_rate") or 0) > 0),
                key=lambda b: (bd[b].get("4x_rate") or 0),
                default=None,
            )
            if best:
                by_b.setdefault(best, []).append(p)

        return {
            b: sorted(lst, key=lambda x: -(x.get("reliability_score") or 0))[:n]
            for b, lst in by_b.items()
            if lst
        }

    top_flow_by_price     = _top_by_bucket(flow_pats,   "by_price_bucket")
    top_flow_by_vol       = _top_by_bucket(flow_pats,   "by_atr_bucket")
    top_custom_by_price   = _top_by_bucket(custom_pats + fcc_pats, "by_price_bucket")
    top_fcc_by_regime     = _top_by_bucket(fcc_pats,    "by_price_bucket")

    clean_tradeable = filter_clean_tradeable_patterns(accepted)
    warnings        = build_regime_warnings(enriched)

    return {
        "regime_performance":            perf,
        "top_flow_by_price_regime":      top_flow_by_price,
        "top_flow_by_volatility_regime": top_flow_by_vol,
        "top_custom_by_price_regime":    top_custom_by_price,
        "top_flow_custom_by_regime":     top_fcc_by_regime,
        "top_patterns_clean_tradeable":  clean_tradeable[:50],
        "regime_warnings":               warnings,
        "has_full_regime_data":          has_full,
        "price_bucket_legend":           _PRICE_BUCKET_LEGEND,
        "dv_bucket_legend":              _DV_BUCKET_LEGEND,
        "atr_bucket_legend":             _ATR_BUCKET_LEGEND,
        "note": (
            "RESEARCH_ONLY. Regime analysis uses PRE-window daily bars. "
            "Does NOT modify Scanner V2 routing or Pump Watch scoring."
        ),
    }
