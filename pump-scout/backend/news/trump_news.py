"""
Trump News Event Bias Layer — Version Alpha
===========================================
Read-only contextual intelligence layer.
Monitors Trump-related policy/news → structured market context.

CRITICAL RULES:
  - NEVER modifies total_score, tier, scanner ranking
  - NEVER modifies journal logic or AI portfolio decisions
  - Display-only layer — purely additive, purely informational

Architecture:
  1. Ingestion      — fetch news from RSS/NewsAPI or manual injection
  2. Detection      — filter for Trump relevance (score 0–100, threshold ≥50)
  3. Classification — map to PRIMARY_CLASSES with sector impact
  4. Normalization  — structured output → DB → API → frontend
  5. Active Bias    — weighted aggregate of recent events (1–3 days)
"""

import hashlib
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

# ─── Primary Event Classes ────────────────────────────────────────────────────

PRIMARY_CLASSES = [
    "TARIFF_TRADE",
    "CHINA_SUPPLY_CHAIN",
    "ENERGY_OIL",
    "GEOPOLITICS_SANCTIONS",
    "DEFENSE_SECURITY",
    "HEALTHCARE_POLICY",
    "TECH_SEMICONDUCTOR",
    "TELECOM_INFRA",
    "TAX_FISCAL",
    "DOMESTIC_GROWTH_POLICY",
    "REGULATORY_SHOCK",
    "GENERAL_POLITICAL_NOISE",
]

# ─── Keyword → Class Mapping ──────────────────────────────────────────────────

_CLASS_KEYWORDS: dict[str, list[str]] = {
    "TARIFF_TRADE": [
        "tariff", "tariffs", "trade war", "import tax", "import duty",
        "export ban", "trade deal", "trade deficit", "WTO", "Section 301",
        "customs", "duties", "reciprocal", "retaliatory",
    ],
    "CHINA_SUPPLY_CHAIN": [
        "china", "chinese", "beijing", "CCP", "supply chain", "decoupling",
        "semiconductor ban", "chip ban", "TSMC", "huawei", "tiktok",
        "fentanyl", "taiwan", "strait", "rare earth",
    ],
    "ENERGY_OIL": [
        "oil", "gas", "LNG", "crude", "OPEC", "pipeline", "drill",
        "fracking", "energy independence", "SPR", "strategic reserve",
        "fossil fuel", "natural gas", "petroleum", "refinery",
        "keystone", "offshore drilling",
    ],
    "GEOPOLITICS_SANCTIONS": [
        "sanction", "sanctions", "russia", "ukraine", "iran", "north korea",
        "nato", "alliance", "ceasefire", "peace deal", "diplomacy",
        "foreign policy", "embassy", "troops", "military aid",
        "missile", "nuclear", "geopolit",
    ],
    "DEFENSE_SECURITY": [
        "defense", "military", "pentagon", "nato spending", "weapons",
        "lockheed", "raytheon", "northrop", "defense contract", "army",
        "navy", "air force", "border security", "national guard",
        "homeland", "cybersecurity", "drone",
    ],
    "HEALTHCARE_POLICY": [
        "medicaid", "medicare", "ACA", "obamacare", "drug price",
        "pharma", "FDA", "health insurance", "healthcare reform",
        "vaccine", "NIH", "CDC", "biosecure",
    ],
    "TECH_SEMICONDUCTOR": [
        "AI", "artificial intelligence", "semiconductor", "chip",
        "nvidia", "intel", "CHIPS act", "export control", "tech ban",
        "quantum", "data center", "cloud", "tech regulation",
        "antitrust tech", "big tech",
    ],
    "TELECOM_INFRA": [
        "5G", "broadband", "telecom", "FCC", "spectrum", "infrastructure",
        "fiber", "rural broadband", "starlink", "satellite internet",
        "AT&T", "Verizon", "T-Mobile",
    ],
    "TAX_FISCAL": [
        "tax cut", "tax reform", "IRS", "deficit", "debt ceiling",
        "budget", "spending bill", "tax credit", "income tax",
        "corporate tax", "fiscal", "stimulus", "TCJA", "tax extension",
    ],
    "DOMESTIC_GROWTH_POLICY": [
        "jobs", "employment", "GDP", "manufacturing", "reshoring",
        "onshoring", "factory", "steel", "aluminum", "union",
        "minimum wage", "infrastructure bill", "deregulation",
        "small business", "economic growth",
    ],
    "REGULATORY_SHOCK": [
        "SEC", "regulation", "deregulation", "EPA", "antitrust",
        "FTC", "DOJ", "executive order", "EO", "rollback",
        "agency cut", "DOGE", "federal worker", "government shutdown",
        "budget cut", "spending freeze",
    ],
    "GENERAL_POLITICAL_NOISE": [
        "trump", "president", "white house", "congress", "senate",
        "democrat", "republican", "election", "impeach", "indictment",
        "rally", "maga", "poll", "approval rating", "cabinet",
    ],
}

# ─── Sector Impact Map ─────────────────────────────────────────────────────────

SECTOR_IMPACT: dict[str, dict] = {
    "TARIFF_TRADE": {
        "bullish_sectors":  ["Industrials", "Materials", "Consumer Staples"],
        "bearish_sectors":  ["Consumer Discretionary", "Information Technology", "Retail"],
        "bullish_industries": ["Steel", "Aluminum", "Domestic Manufacturing"],
        "bearish_industries": ["Import-Dependent Retail", "Consumer Electronics", "Apparel"],
        "volatility_bias":  "HIGH",
        "oil_bias":         "NEUTRAL",
        "rates_bias":       "NEUTRAL",
        "dollar_bias":      "BULLISH",
        "market_bias":      "MIXED",
        "time_horizon":     "MEDIUM",  # 1–4 weeks
    },
    "CHINA_SUPPLY_CHAIN": {
        "bullish_sectors":  ["Industrials", "Materials", "Defense"],
        "bearish_sectors":  ["Information Technology", "Consumer Discretionary"],
        "bullish_industries": ["Domestic Chip Design", "Rare Earth Alternatives"],
        "bearish_industries": ["Fabless Semiconductors", "Consumer Electronics"],
        "volatility_bias":  "HIGH",
        "oil_bias":         "NEUTRAL",
        "rates_bias":       "NEUTRAL",
        "dollar_bias":      "BULLISH",
        "market_bias":      "RISK_OFF",
        "time_horizon":     "LONG",    # weeks to months
    },
    "ENERGY_OIL": {
        "bullish_sectors":  ["Energy"],
        "bearish_sectors":  ["Utilities", "Consumer Discretionary"],
        "bullish_industries": ["Oil & Gas E&P", "LNG", "Pipeline"],
        "bearish_industries": ["Electric Vehicles", "Solar", "Wind"],
        "volatility_bias":  "MEDIUM",
        "oil_bias":         "BULLISH",
        "rates_bias":       "BEARISH",  # higher energy → inflation → rates up
        "dollar_bias":      "BULLISH",
        "market_bias":      "MIXED",
        "time_horizon":     "SHORT",   # days to 1 week
    },
    "GEOPOLITICS_SANCTIONS": {
        "bullish_sectors":  ["Defense", "Energy", "Materials"],
        "bearish_sectors":  ["Financials", "Industrials"],
        "bullish_industries": ["Defense Contractors", "Gold Mining", "Oil & Gas"],
        "bearish_industries": ["International Banks", "Export-Dependent Industrials"],
        "volatility_bias":  "VERY_HIGH",
        "oil_bias":         "BULLISH",
        "rates_bias":       "BEARISH",
        "dollar_bias":      "BULLISH",
        "market_bias":      "RISK_OFF",
        "time_horizon":     "SHORT",
    },
    "DEFENSE_SECURITY": {
        "bullish_sectors":  ["Industrials", "Information Technology"],
        "bearish_sectors":  [],
        "bullish_industries": ["Defense Contractors", "Cybersecurity", "Aerospace"],
        "bearish_industries": [],
        "volatility_bias":  "LOW",
        "oil_bias":         "NEUTRAL",
        "rates_bias":       "NEUTRAL",
        "dollar_bias":      "NEUTRAL",
        "market_bias":      "BULLISH",
        "time_horizon":     "MEDIUM",
    },
    "HEALTHCARE_POLICY": {
        "bullish_sectors":  ["Health Care"],
        "bearish_sectors":  ["Health Care"],  # depends on direction
        "bullish_industries": ["Managed Care", "Biotech (deregulation)"],
        "bearish_industries": ["Pharma (price controls)", "Hospital Systems"],
        "volatility_bias":  "MEDIUM",
        "oil_bias":         "NEUTRAL",
        "rates_bias":       "NEUTRAL",
        "dollar_bias":      "NEUTRAL",
        "market_bias":      "MIXED",
        "time_horizon":     "MEDIUM",
    },
    "TECH_SEMICONDUCTOR": {
        "bullish_sectors":  ["Information Technology"],
        "bearish_sectors":  ["Information Technology"],  # depends on direction
        "bullish_industries": ["Domestic AI Infrastructure", "Data Centers"],
        "bearish_industries": ["Fabless Chip Design", "Cloud (China-exposed)"],
        "volatility_bias":  "HIGH",
        "oil_bias":         "NEUTRAL",
        "rates_bias":       "NEUTRAL",
        "dollar_bias":      "NEUTRAL",
        "market_bias":      "MIXED",
        "time_horizon":     "MEDIUM",
    },
    "TELECOM_INFRA": {
        "bullish_sectors":  ["Communication Services", "Industrials"],
        "bearish_sectors":  [],
        "bullish_industries": ["5G Infrastructure", "Rural Broadband", "Satellites"],
        "bearish_industries": [],
        "volatility_bias":  "LOW",
        "oil_bias":         "NEUTRAL",
        "rates_bias":       "NEUTRAL",
        "dollar_bias":      "NEUTRAL",
        "market_bias":      "BULLISH",
        "time_horizon":     "LONG",
    },
    "TAX_FISCAL": {
        "bullish_sectors":  ["Financials", "Consumer Discretionary", "Industrials"],
        "bearish_sectors":  ["Utilities", "Real Estate"],
        "bullish_industries": ["Banks", "Small Cap Growth", "Cyclicals"],
        "bearish_industries": ["REITs", "Utilities (rate-sensitive)"],
        "volatility_bias":  "MEDIUM",
        "oil_bias":         "NEUTRAL",
        "rates_bias":       "BEARISH",  # fiscal stimulus → higher rates
        "dollar_bias":      "BULLISH",
        "market_bias":      "BULLISH",
        "time_horizon":     "LONG",
    },
    "DOMESTIC_GROWTH_POLICY": {
        "bullish_sectors":  ["Industrials", "Materials", "Consumer Discretionary"],
        "bearish_sectors":  [],
        "bullish_industries": ["Construction", "Steel", "Automotive"],
        "bearish_industries": [],
        "volatility_bias":  "LOW",
        "oil_bias":         "NEUTRAL",
        "rates_bias":       "NEUTRAL",
        "dollar_bias":      "NEUTRAL",
        "market_bias":      "BULLISH",
        "time_horizon":     "LONG",
    },
    "REGULATORY_SHOCK": {
        "bullish_sectors":  ["Financials", "Energy", "Information Technology"],
        "bearish_sectors":  ["Utilities", "Consumer Staples"],
        "bullish_industries": ["Deregulated Banks", "Oil & Gas", "Crypto"],
        "bearish_industries": ["Regulated Utilities", "Telecom (heavy regulation)"],
        "volatility_bias":  "HIGH",
        "oil_bias":         "NEUTRAL",
        "rates_bias":       "NEUTRAL",
        "dollar_bias":      "NEUTRAL",
        "market_bias":      "MIXED",
        "time_horizon":     "SHORT",
    },
    "GENERAL_POLITICAL_NOISE": {
        "bullish_sectors":  [],
        "bearish_sectors":  [],
        "bullish_industries": [],
        "bearish_industries": [],
        "volatility_bias":  "LOW",
        "oil_bias":         "NEUTRAL",
        "rates_bias":       "NEUTRAL",
        "dollar_bias":      "NEUTRAL",
        "market_bias":      "NEUTRAL",
        "time_horizon":     "SHORT",
    },
}

# ─── Trump Relevance Keywords ─────────────────────────────────────────────────

_TRUMP_SIGNALS = [
    "trump", "donald trump", "president trump", "trump administration",
    "white house", "mar-a-lago", "maga", "trump executive order",
    "tariff", "trade war", "trump tariff",
]

_TRUMP_ANTI_SIGNALS = [
    "ivanka", "melania", "trump hotel", "trump golf", "trump tower real estate",
]

# ─── RSS Sources (public, no API key required) ────────────────────────────────
# Google News RSS: always reliable, no API key, returns recent news per query.
# Note: Reuters killed public RSS in 2023; replaced with Google News + AP + BBC.

RSS_SOURCES = [
    # Google News search RSS — directly targets Trump policy news
    "https://news.google.com/rss/search?q=trump+tariff+trade&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=trump+executive+order+policy&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=trump+china+sanctions+market&hl=en-US&gl=US&ceid=US:en",
    "https://news.google.com/rss/search?q=trump+economy+tax+fiscal&hl=en-US&gl=US&ceid=US:en",
    # BBC Business (still active)
    "https://feeds.bbci.co.uk/news/business/rss.xml",
    # AP News politics/business
    "https://apnews.com/rss/politics",
    "https://apnews.com/rss/business",
]

# ─── Helpers ──────────────────────────────────────────────────────────────────


def _make_event_id(title: str, published_at: str) -> str:
    """Deterministic event ID: SHA1 of (title + date) → 12-char hex."""
    raw = f"{title.lower().strip()}|{published_at[:10]}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _score_trump_relevance(text: str) -> int:
    """
    Returns 0–100 Trump relevance score.
    ≥50 = relevant, proceed; <50 = skip.
    """
    lower = text.lower()
    score = 0

    for kw in _TRUMP_SIGNALS:
        if kw in lower:
            # "trump" core signal gets high weight
            if kw in ("trump", "donald trump", "president trump"):
                score += 35
            else:
                score += 15

    for kw in _TRUMP_ANTI_SIGNALS:
        if kw in lower:
            score -= 25  # personal/lifestyle news, not policy

    return max(0, min(100, score))


def _detect_classes(text: str) -> list[str]:
    """
    Detect which PRIMARY_CLASSES apply to this text.
    Returns list of matched class names (may be empty → GENERAL_POLITICAL_NOISE).
    """
    lower = text.lower()
    matched = []
    for cls, keywords in _CLASS_KEYWORDS.items():
        if cls == "GENERAL_POLITICAL_NOISE":
            continue  # fallback only
        for kw in keywords:
            if kw.lower() in lower:
                if cls not in matched:
                    matched.append(cls)
                break

    if not matched:
        matched = ["GENERAL_POLITICAL_NOISE"]

    return matched


def _score_surprise(title: str) -> int:
    """
    Estimate surprise level 0–100 based on intensity language.
    High surprise → higher weight in active bias computation.
    """
    surprise_words = [
        ("shock", 30), ("unexpected", 25), ("sudden", 20), ("surprise", 20),
        ("emergency", 25), ("escalat", 20), ("collapse", 25), ("crash", 20),
        ("ban", 15), ("halt", 15), ("suspend", 15), ("new tariff", 25),
        ("impose", 15), ("announce", 5), ("sign", 5),
    ]
    lower = title.lower()
    score = 20  # baseline
    for word, pts in surprise_words:
        if word in lower:
            score += pts
    return min(100, score)


def _score_confidence(classes: list[str], relevance: int) -> int:
    """
    Classification confidence 0–100.
    Higher when: single class detected, high relevance, specific (not GENERAL).
    """
    if classes == ["GENERAL_POLITICAL_NOISE"]:
        return max(20, relevance // 2)
    base = min(80, relevance)
    if len(classes) == 1:
        base = min(100, base + 15)
    elif len(classes) >= 3:
        base = max(30, base - 10)
    return base


def classify_event(title: str, description: str = "") -> dict:
    """
    Full classification pipeline for a single news item.
    Returns structured event dict (not yet saved to DB).
    """
    combined = f"{title} {description}"
    relevance_score = _score_trump_relevance(combined)

    if relevance_score < 35:
        return {"relevant": False, "relevance_score": relevance_score}

    event_classes = _detect_classes(combined)
    primary_class = event_classes[0]  # most-matched class
    impact = SECTOR_IMPACT.get(primary_class, SECTOR_IMPACT["GENERAL_POLITICAL_NOISE"])
    surprise_level = _score_surprise(title)
    confidence = _score_confidence(event_classes, relevance_score)

    now_iso = datetime.now(timezone.utc).isoformat()

    return {
        "relevant": True,
        "relevance_score": relevance_score,
        "event_classes": event_classes,
        "primary_class": primary_class,
        "market_bias": impact["market_bias"],
        "time_horizon": impact["time_horizon"],
        "confidence": confidence,
        "surprise_level": surprise_level,
        "volatility_bias": impact["volatility_bias"],
        "oil_bias": impact["oil_bias"],
        "rates_bias": impact["rates_bias"],
        "dollar_bias": impact["dollar_bias"],
        "bullish_sectors": impact["bullish_sectors"],
        "bearish_sectors": impact["bearish_sectors"],
        "bullish_industries": impact["bullish_industries"],
        "bearish_industries": impact["bearish_industries"],
        "fetched_at": now_iso,
    }


# ─── RSS Parser ───────────────────────────────────────────────────────────────


_RSS_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; PumpScoutBot/1.0; +https://pumpscout.io) "
        "Googlebot/2.1 (+http://www.google.com/bot.html)"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


async def _parse_rss_feed(url: str, client: httpx.AsyncClient) -> list[dict]:
    """
    Fetch and parse a simple RSS/Atom feed.
    Returns list of {title, description, published_at, source_url}.
    Handles: CDATA-wrapped titles/descs, Google News RSS, BBC, AP.
    """
    items = []
    try:
        resp = await client.get(url, headers=_RSS_HEADERS, timeout=httpx.Timeout(10.0, connect=5.0))
        if resp.status_code != 200:
            logger.warning(f"RSS {url} → HTTP {resp.status_code}")
            return []

        text = resp.text

        # ── Item-level extraction ──────────────────────────────────────────────
        # Split by <item> boundaries first for cleaner per-item parsing
        item_blocks = re.split(r"<item[>\s]", text, flags=re.IGNORECASE)[1:]

        if not item_blocks:
            # Atom fallback: split by <entry>
            item_blocks = re.split(r"<entry[>\s]", text, flags=re.IGNORECASE)[1:]

        from email.utils import parsedate_to_datetime

        for raw in item_blocks[:25]:
            # Title: CDATA or plain
            title_m = re.search(
                r"<title><!\[CDATA\[(.*?)\]\]></title>|<title>(.*?)</title>",
                raw, re.DOTALL | re.IGNORECASE,
            )
            if not title_m:
                continue
            title = (title_m.group(1) or title_m.group(2) or "").strip()
            # Strip HTML tags from title
            title = re.sub(r"<[^>]+>", "", title).strip()
            if not title or len(title) < 10:
                continue

            # Description: CDATA or plain
            desc_m = re.search(
                r"<description><!\[CDATA\[(.*?)\]\]></description>|<description>(.*?)</description>",
                raw, re.DOTALL | re.IGNORECASE,
            )
            desc = ""
            if desc_m:
                desc = (desc_m.group(1) or desc_m.group(2) or "").strip()
                desc = re.sub(r"<[^>]+>", "", desc).strip()[:500]

            # pubDate (RSS) or published / updated (Atom)
            pub_m = re.search(r"<pubDate>(.*?)</pubDate>", raw, re.IGNORECASE)
            if not pub_m:
                pub_m = re.search(r"<published>(.*?)</published>", raw, re.IGNORECASE)
            pub_raw = pub_m.group(1).strip() if pub_m else ""
            try:
                dt = parsedate_to_datetime(pub_raw)
                pub_iso = dt.astimezone(timezone.utc).isoformat()
            except Exception:
                try:
                    # ISO 8601 from Atom feeds
                    pub_iso = datetime.fromisoformat(
                        pub_raw.replace("Z", "+00:00")
                    ).isoformat()
                except Exception:
                    pub_iso = datetime.now(timezone.utc).isoformat()

            # Link: text content or href attribute
            link_m = re.search(
                r"<link>(https?://[^<]+)</link>|<link[^>]+href=['\"]([^'\"]+)['\"]",
                raw, re.IGNORECASE,
            )
            link = ""
            if link_m:
                link = (link_m.group(1) or link_m.group(2) or "").strip()

            items.append({
                "title":        title,
                "description":  desc,
                "published_at": pub_iso,
                "source_url":   link,
            })

    except Exception as e:
        logger.warning(f"RSS fetch failed for {url}: {e}")

    return items


# ─── Manual Event Injection ───────────────────────────────────────────────────

MANUAL_EVENTS: list[dict] = [
    # Inject test events here for development/demo mode
    # {
    #     "title": "Trump announces 25% tariffs on all Canadian goods",
    #     "description": "President Trump signed executive order imposing 25% import duties on all Canadian goods effective Monday",
    #     "published_at": "2025-04-08T14:00:00+00:00",
    #     "source_url": "",
    # },
]


# ─── Main Ingestion Function ──────────────────────────────────────────────────


async def fetch_and_classify_events(use_manual: bool = False) -> list[dict]:
    """
    Main entry point: fetch news → filter Trump relevance → classify → return.

    Args:
        use_manual: If True, also include MANUAL_EVENTS (for development/testing).

    Returns:
        List of classified event dicts ready for DB upsert.
    """
    raw_items: list[dict] = []

    if use_manual and MANUAL_EVENTS:
        raw_items.extend(MANUAL_EVENTS)
        logger.info(f"Loaded {len(MANUAL_EVENTS)} manual event(s)")

    # Fetch from RSS sources
    async with httpx.AsyncClient() as client:
        for url in RSS_SOURCES:
            items = await _parse_rss_feed(url, client)
            raw_items.extend(items)
            logger.debug(f"RSS {url}: {len(items)} items")

    logger.info(f"Total raw news items: {len(raw_items)}")

    # Deduplicate by title
    seen_titles: set[str] = set()
    unique_items = []
    for item in raw_items:
        key = item["title"].lower().strip()[:80]
        if key not in seen_titles:
            seen_titles.add(key)
            unique_items.append(item)

    logger.info(f"After dedup: {len(unique_items)} unique items")

    # Classify each item
    classified = []
    for item in unique_items:
        result = classify_event(item["title"], item.get("description", ""))
        if not result["relevant"]:
            continue

        event_id = _make_event_id(item["title"], item["published_at"])

        classified.append({
            "event_id":          event_id,
            "title":             item["title"],
            "source_url":        item.get("source_url", ""),
            "published_at":      item["published_at"],
            "fetched_at":        result["fetched_at"],
            "relevance_score":   result["relevance_score"],
            "event_classes":     result["event_classes"],
            "primary_class":     result["primary_class"],
            "market_bias":       result["market_bias"],
            "time_horizon":      result["time_horizon"],
            "confidence":        result["confidence"],
            "surprise_level":    result["surprise_level"],
            "volatility_bias":   result["volatility_bias"],
            "oil_bias":          result["oil_bias"],
            "rates_bias":        result["rates_bias"],
            "dollar_bias":       result["dollar_bias"],
            "bullish_sectors":   result["bullish_sectors"],
            "bearish_sectors":   result["bearish_sectors"],
            "bullish_industries": result["bullish_industries"],
            "bearish_industries": result["bearish_industries"],
            "is_active":         True,
        })

    logger.info(f"Classified {len(classified)} Trump-relevant events")
    return classified


# ─── Active Bias Aggregation ──────────────────────────────────────────────────


def compute_active_bias(events: list[dict], max_age_days: int = 3) -> dict:
    """
    Aggregate recent events into a single active-bias snapshot.
    Weighted by: relevance_score × surprise_level × confidence × recency_factor.

    Returns:
        {
          overall_market_bias: str,
          overall_volatility:  str,
          top_bullish_sectors: list[str],
          top_bearish_sectors: list[str],
          active_classes:      list[str],
          event_count:         int,
          regime_summary:      str,
          computed_at:         str,
        }
    """
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=max_age_days)

    # Filter to recent events
    recent = []
    for ev in events:
        try:
            pub = datetime.fromisoformat(ev["published_at"].replace("Z", "+00:00"))
            if pub >= cutoff:
                recent.append((ev, pub))
        except Exception:
            continue

    if not recent:
        return {
            "overall_market_bias": "NEUTRAL",
            "overall_volatility":  "LOW",
            "top_bullish_sectors": [],
            "top_bearish_sectors": [],
            "active_classes":      [],
            "event_count":         0,
            "regime_summary":      "No recent Trump policy events detected.",
            "computed_at":         now.isoformat(),
        }

    # Score tallies
    bias_weights = {"BULLISH": 0.0, "BEARISH": 0.0, "RISK_OFF": 0.0, "MIXED": 0.0, "NEUTRAL": 0.0}
    vol_weights  = {"VERY_HIGH": 0.0, "HIGH": 0.0, "MEDIUM": 0.0, "LOW": 0.0}
    bullish_sector_tally: dict[str, float] = {}
    bearish_sector_tally: dict[str, float] = {}
    active_classes: list[str] = []

    for ev, pub in recent:
        age_hours = (now - pub).total_seconds() / 3600
        recency   = max(0.1, 1.0 - age_hours / (max_age_days * 24))
        weight    = (ev.get("relevance_score", 50) / 100) * \
                    (ev.get("surprise_level", 30)  / 100) * \
                    (ev.get("confidence", 50)       / 100) * \
                    recency

        mb = ev.get("market_bias", "NEUTRAL")
        if mb in bias_weights:
            bias_weights[mb] += weight

        vb = ev.get("volatility_bias", "LOW")
        if vb in vol_weights:
            vol_weights[vb] += weight

        for sec in (ev.get("bullish_sectors") or []):
            bullish_sector_tally[sec] = bullish_sector_tally.get(sec, 0) + weight
        for sec in (ev.get("bearish_sectors") or []):
            bearish_sector_tally[sec] = bearish_sector_tally.get(sec, 0) + weight

        for cls in (ev.get("event_classes") or []):
            if cls not in active_classes:
                active_classes.append(cls)

    overall_bias = max(bias_weights, key=bias_weights.get)  # type: ignore
    overall_vol  = max(vol_weights,  key=vol_weights.get)   # type: ignore

    top_bull = sorted(bullish_sector_tally, key=bullish_sector_tally.get, reverse=True)[:5]  # type: ignore
    top_bear = sorted(bearish_sector_tally, key=bearish_sector_tally.get, reverse=True)[:5]  # type: ignore

    # Generate human-readable regime summary
    event_count = len(recent)
    dominant_class = active_classes[0] if active_classes else "GENERAL_POLITICAL_NOISE"
    summary = _build_regime_summary(overall_bias, overall_vol, dominant_class, event_count, top_bull, top_bear)

    return {
        "overall_market_bias": overall_bias,
        "overall_volatility":  overall_vol,
        "top_bullish_sectors": top_bull,
        "top_bearish_sectors": top_bear,
        "active_classes":      active_classes,
        "event_count":         event_count,
        "regime_summary":      summary,
        "computed_at":         now.isoformat(),
    }


def _build_regime_summary(bias: str, vol: str, dominant_class: str, count: int,
                           bullish: list[str], bearish: list[str]) -> str:
    class_labels = {
        "TARIFF_TRADE":          "tariff/trade",
        "CHINA_SUPPLY_CHAIN":    "China/supply chain",
        "ENERGY_OIL":            "energy/oil",
        "GEOPOLITICS_SANCTIONS": "geopolitical",
        "DEFENSE_SECURITY":      "defense",
        "HEALTHCARE_POLICY":     "healthcare policy",
        "TECH_SEMICONDUCTOR":    "tech/semiconductor",
        "TELECOM_INFRA":         "telecom/infra",
        "TAX_FISCAL":            "tax/fiscal",
        "DOMESTIC_GROWTH_POLICY":"domestic growth",
        "REGULATORY_SHOCK":      "regulatory",
        "GENERAL_POLITICAL_NOISE":"political noise",
    }
    bias_phrases = {
        "BULLISH":  "favoring risk-on positioning",
        "BEARISH":  "creating headwinds for equities",
        "RISK_OFF": "driving risk-off sentiment",
        "MIXED":    "creating mixed sector rotation",
        "NEUTRAL":  "with limited directional impact",
    }
    vol_desc = "elevated" if vol in ("HIGH", "VERY_HIGH") else "moderate" if vol == "MEDIUM" else "low"

    lbl = class_labels.get(dominant_class, dominant_class.lower().replace("_", " "))
    bp  = bias_phrases.get(bias, "")
    bull_str = ", ".join(bullish[:3]) if bullish else "none"
    bear_str = ", ".join(bearish[:3]) if bearish else "none"

    return (
        f"{count} recent Trump {lbl} event{'s' if count != 1 else ''} {bp}. "
        f"Volatility bias is {vol_desc}. "
        f"Sectors to watch bullish: {bull_str}. "
        f"Sectors under pressure: {bear_str}."
    )
