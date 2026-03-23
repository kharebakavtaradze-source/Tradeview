"""
Hype Monitor — Social Data Fetcher
Fetches StockTwits, Yahoo Finance News (v2+v1 fallback), Reddit, and Finviz News.
Classifies articles by type (real/pr/sec/unknown) with weights.
Returns unified mention lists with timestamps, sentiment, and rich news detail.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
}
HTML_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://finviz.com",
    "DNT": "1",
    "Connection": "keep-alive",
}

TIMEOUT = 15.0

# ── Article classification ────────────────────────────────────────────────────

_SEC_KEYWORDS = {"8-K", "10-Q", "10-K", "FORM 4", "SEC FILING", "DEF 14A", "S-1", "S-3"}
_PR_PUBLISHERS = {
    "GLOBE NEWSWIRE", "GLOBENEWSWIRE", "PR NEWSWIRE", "PRNEWSWIRE",
    "BUSINESS WIRE", "BUSINESSWIRE", "ACCESSWIRE",
}
_REAL_PUBLISHERS = {
    "REUTERS", "BLOOMBERG", "CNBC", "MARKETWATCH", "SEEKING ALPHA",
    "BENZINGA", "THESTREET", "YAHOO FINANCE", "MOTLEY FOOL", "BARRONS",
    "TIPRANKS", "FINVIZ", "INVESTORPLACE", "ZACKS", "FOOL.COM",
    "WALL STREET JOURNAL", "WSJ", "FINANCIAL TIMES", "FT",
    "INVESTOR'S BUSINESS DAILY", "IBD", "SCHAEFFERS", "SCHAEFFERRESEARCH",
    "NASDAQ", "NYSE", "STOCKANALYSIS", "SIMPLY WALL ST",
}


def _classify_article(title: str, publisher: str) -> tuple[str, float]:
    """Returns (type, weight): sec=1.5, real=1.0, unknown=0.7, pr=0.5."""
    title_up = title.upper()
    pub_up = publisher.upper()

    for kw in _SEC_KEYWORDS:
        if kw in title_up:
            return "sec", 1.5

    for pr in _PR_PUBLISHERS:
        if pr in pub_up:
            return "pr", 0.5

    for real in _REAL_PUBLISHERS:
        if real in pub_up:
            return "real", 1.0

    return "unknown", 0.7


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(ts_str: str | None) -> datetime | None:
    if not ts_str:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S+0000", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S"):
        try:
            dt = datetime.strptime(ts_str[:19], fmt[:len(fmt)])
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _hours_ago(ts: datetime) -> int:
    return max(0, int((_now_utc() - ts).total_seconds() / 3600))


# ── StockTwits ────────────────────────────────────────────────────────────────

def _parse_stocktwits_messages(messages: list) -> list[dict]:
    """Convert StockTwits API message list → unified mention dicts."""
    results = []
    for m in messages:
        ts = _parse_ts(m.get("created_at"))
        if not ts:
            continue
        sentiment_raw = (m.get("entities", {}) or {}).get("sentiment") or {}
        sentiment = sentiment_raw.get("basic", "").upper() if isinstance(sentiment_raw, dict) else ""
        results.append({
            "source": "stocktwits",
            "ts": ts,
            "text": (m.get("body") or "")[:280],
            "sentiment": sentiment,
            "_msg_id": m.get("id", 0),
        })
    return results


async def _fetch_stocktwits(ticker: str, client: httpx.AsyncClient) -> list[dict]:
    """
    Fetch StockTwits messages for a ticker.
    Paginates up to 3 pages (max ~90 messages) to build a proper 24h baseline.
    Uses max_id cursor to walk back in time.
    """
    base_url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
    all_results: list[dict] = []
    max_id: int | None = None
    cutoff_24h = _now_utc() - timedelta(hours=24)

    for page in range(3):  # up to 3 pages × 30 = 90 messages max
        url = base_url if max_id is None else f"{base_url}?max={max_id - 1}"
        try:
            resp = await client.get(url, headers=HEADERS)
            if resp.status_code == 429:
                logger.debug(f"StockTwits rate-limited for {ticker}")
                break
            if resp.status_code != 200:
                break
            messages = resp.json().get("messages", [])
            if not messages:
                break

            page_results = _parse_stocktwits_messages(messages)
            all_results.extend(page_results)

            # Track the oldest message id for next page cursor
            ids = [r["_msg_id"] for r in page_results if r.get("_msg_id")]
            if ids:
                max_id = min(ids)

            # Stop paginating if oldest message is already > 24h old
            oldest_ts = min((r["ts"] for r in page_results), default=None)
            if oldest_ts and oldest_ts < cutoff_24h:
                break

            # Small delay between pages to respect rate limits
            if page < 2:
                await asyncio.sleep(0.3)

        except Exception as e:
            logger.debug(f"StockTwits fetch failed for {ticker} page {page}: {e}")
            break

    # Strip internal cursor field before returning
    for r in all_results:
        r.pop("_msg_id", None)

    return all_results


# ── Yahoo Finance News (v2 + v1 fallback) ────────────────────────────────────

async def _fetch_yahoo_v2(ticker: str, client: httpx.AsyncClient) -> list[dict]:
    """
    Yahoo Finance v2 news endpoint — returns PR Newswire, SEC filings, etc.
    Tries query2 mirror first (more reliable on some networks), then query1.
    """
    for host in ("query2.finance.yahoo.com", "query1.finance.yahoo.com"):
        url = f"https://{host}/v2/finance/news?symbols={ticker}&count=30"
        try:
            resp = await client.get(url, headers=HEADERS)
            if resp.status_code != 200:
                continue
            data = resp.json()
            # v2 response shape: {"items": {"result": [...]}} or {"data": {"main": {"stream": [...]}}}
            items = (
                data.get("items", {}).get("result", [])
                or data.get("data", {}).get("main", {}).get("stream", [])
            )
            if not items:
                continue
            results = []
            for item in items:
                # Both shapes: top-level fields or nested under "content"
                content = item.get("content") or item
                pub_epoch = content.get("providerPublishTime") or item.get("providerPublishTime", 0)
                if not pub_epoch:
                    continue
                ts = datetime.fromtimestamp(pub_epoch, tz=timezone.utc)
                results.append({
                    "title": (content.get("title") or item.get("title") or "")[:200],
                    "publisher": (content.get("provider", {}).get("displayName") or
                                  content.get("publisher") or
                                  item.get("publisher") or "")[:100],
                    "summary": (content.get("summary") or item.get("summary") or "")[:200],
                    "url": content.get("canonicalUrl", {}).get("url") or item.get("link") or "",
                    "ts": ts,
                })
            if results:
                return results
        except Exception as e:
            logger.debug(f"Yahoo v2 news ({host}) failed for {ticker}: {e}")
    return []


async def _fetch_yahoo_v1(ticker: str, client: httpx.AsyncClient) -> list[dict]:
    """Yahoo Finance v1 search endpoint — fallback. Tries both query mirrors."""
    for host in ("query2.finance.yahoo.com", "query1.finance.yahoo.com"):
        url = (
            f"https://{host}/v1/finance/search"
            f"?q={ticker}&newsCount=25&quotesCount=0&enableFuzzyQuery=false"
        )
        try:
            resp = await client.get(url, headers=HEADERS)
            if resp.status_code != 200:
                continue
            news = resp.json().get("news", [])
            if not news:
                continue
            results = []
            for item in news:
                pub_epoch = item.get("providerPublishTime")
                if not pub_epoch:
                    continue
                ts = datetime.fromtimestamp(pub_epoch, tz=timezone.utc)
                results.append({
                    "title": (item.get("title") or "")[:200],
                    "publisher": item.get("publisher") or "",
                    "summary": "",
                    "url": "",
                    "ts": ts,
                })
            if results:
                return results
        except Exception as e:
            logger.debug(f"Yahoo v1 news ({host}) failed for {ticker}: {e}")
    return []


async def fetch_yahoo_news_hype(ticker: str, client: httpx.AsyncClient | None = None) -> dict:
    """
    Fetch Yahoo news using v2, falling back to v1, then Claude web search if both empty.
    Returns rich news detail dict with classification.
    """
    from hype_monitor.news_claude import fetch_news_claude

    _client = client
    _owned = False
    if _client is None:
        _client = httpx.AsyncClient(timeout=TIMEOUT)
        _owned = True

    try:
        raw = await _fetch_yahoo_v2(ticker, _client)
        if not raw:
            raw = await _fetch_yahoo_v1(ticker, _client)
    finally:
        if _owned:
            await _client.aclose()

    result = _build_news_detail(raw, source_tag="yahoo")

    # If Yahoo returns nothing, try Claude web search as fallback
    if result.get("total_count_24h", 0) == 0 and result.get("count_7d", 0) == 0:
        logger.info(f"Yahoo news empty for {ticker}, trying Claude web search...")
        result = await fetch_news_claude(ticker)

    return result


# ── Finviz News ───────────────────────────────────────────────────────────────

async def fetch_finviz_news(ticker: str, client: httpx.AsyncClient | None = None) -> dict:
    """
    Scrape Finviz quote page for news headlines.
    Returns count_24h, count_7d, headlines list.
    """
    url = f"https://finviz.com/quote.ashx?t={ticker}&p=d"
    _client = client
    _owned = False
    if _client is None:
        _client = httpx.AsyncClient(timeout=10.0)
        _owned = True

    try:
        resp = await _client.get(url, headers=HTML_HEADERS)
        if resp.status_code != 200:
            return _empty_news_detail()

        soup = BeautifulSoup(resp.text, "lxml")
        table = soup.find("table", id="news-table")
        if not table:
            return _empty_news_detail()

        rows = table.find_all("tr")
        articles = []
        last_date = None
        now = _now_utc()
        cutoff_24h = now - timedelta(hours=24)
        cutoff_7d = now - timedelta(days=7)

        for row in rows:
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            date_text = cells[0].get_text(strip=True)
            anchor = cells[1].find("a")
            if not anchor:
                continue
            title = anchor.get_text(strip=True)[:200]
            href = anchor.get("href", "")

            # Parse date/time
            try:
                if len(date_text) > 8:  # Has full date like "Mar-21-26 09:30AM"
                    parts = date_text.split()
                    date_part = parts[0]  # "Mar-21-26"
                    time_part = parts[1] if len(parts) > 1 else "12:00AM"
                    dt_str = f"{date_part} {time_part}"
                    ts = datetime.strptime(dt_str, "%b-%d-%y %I:%M%p").replace(tzinfo=timezone.utc)
                    last_date = date_part
                else:
                    # Time-only row — reuse last_date
                    if not last_date:
                        continue
                    dt_str = f"{last_date} {date_text}"
                    ts = datetime.strptime(dt_str, "%b-%d-%y %I:%M%p").replace(tzinfo=timezone.utc)
            except (ValueError, IndexError):
                continue

            articles.append({"title": title, "ts": ts, "url": href, "publisher": "Finviz"})

    except Exception as e:
        logger.debug(f"Finviz news failed for {ticker}: {e}")
        return _empty_news_detail()
    finally:
        if _owned:
            await _client.aclose()

    return _build_news_detail(articles, source_tag="finviz")


# ── News detail builder ───────────────────────────────────────────────────────

def _empty_news_detail() -> dict:
    return {
        "count_24h": 0, "count_2_7d": 0, "count_7d": 0, "weighted_count": 0.0,
        "has_sec_filing": False, "has_real_news": False,
        "headlines": [], "headlines_7d": [], "error": True,
    }


def _build_news_detail(raw_articles: list[dict], source_tag: str = "") -> dict:
    """
    Classify articles and build the rich news detail dict.
    Scoring uses a weighted time window:
      count_24h   × 1.0  (fresh news — full weight)
      count_2_7d  × 0.4  (recent but not today — partial credit)
    SEC filings and analyst upgrades from the past week stay visible.
    """
    now = _now_utc()
    cutoff_24h = now - timedelta(hours=24)
    cutoff_7d = now - timedelta(days=7)

    count_24h = 0
    count_2_7d = 0   # articles older than 24h but within 7 days
    count_7d = 0
    weighted_count = 0.0
    has_sec = False
    has_real = False
    headlines_24h = []   # for display — freshest only
    headlines_7d = []    # full 7-day list for /api/hype/{symbol}

    for article in raw_articles:
        ts = article.get("ts")
        if not isinstance(ts, datetime):
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)

        title = article.get("title", "")
        publisher = article.get("publisher", "")
        art_type, weight = _classify_article(title, publisher)
        h_ago = _hours_ago(ts)

        in_24h = ts >= cutoff_24h
        in_7d = ts >= cutoff_7d

        if in_7d:
            count_7d += 1
            if art_type == "sec":
                has_sec = True
            if art_type in ("real", "sec"):
                has_real = True

            if len(headlines_7d) < 20:
                headlines_7d.append({
                    "title": title,
                    "publisher": publisher,
                    "hours_ago": h_ago,
                    "type": art_type,
                    "weight": weight,
                })

        if in_24h:
            count_24h += 1
            weighted_count += weight * 1.0
            if len(headlines_24h) < 8:
                headlines_24h.append({
                    "title": title,
                    "publisher": publisher,
                    "hours_ago": h_ago,
                    "type": art_type,
                    "weight": weight,
                })
        elif in_7d:
            count_2_7d += 1
            weighted_count += weight * 0.4  # older news contributes at 40%

    headlines_24h.sort(key=lambda h: h["hours_ago"])
    headlines_7d.sort(key=lambda h: h["hours_ago"])

    return {
        "count_24h": count_24h,
        "count_2_7d": count_2_7d,
        "count_7d": count_7d,
        "weighted_count": round(weighted_count, 2),
        "has_sec_filing": has_sec,
        "has_real_news": has_real,
        "headlines": headlines_24h,        # fresh 24h — shown on cards
        "headlines_7d": headlines_7d,      # full 7d — returned by /api/hype/{symbol}
        "error": False,
    }


def _merge_news_details(yahoo: dict, finviz: dict) -> dict:
    """
    Merge Yahoo + Finviz news, deduplicating by first-40-char title match.
    Produces both a 24h headlines list (for cards) and a 7d list (for /api/hype/{symbol}).
    weighted_count already incorporates the time-decay window from _build_news_detail.
    """
    def _dedup_merge(a_list: list, b_list: list, limit: int) -> list:
        merged = list(a_list)
        seen = {h["title"][:40].lower() for h in merged}
        for h in b_list:
            prefix = h["title"][:40].lower()
            if prefix not in seen:
                merged.append(h)
                seen.add(prefix)
        merged.sort(key=lambda h: h["hours_ago"])
        return merged[:limit]

    headlines_24h = _dedup_merge(yahoo.get("headlines", []), finviz.get("headlines", []), 8)
    headlines_7d = _dedup_merge(yahoo.get("headlines_7d", []), finviz.get("headlines_7d", []), 20)

    # Combine weighted counts (already time-decayed inside each source's _build_news_detail)
    weighted = yahoo.get("weighted_count", 0.0) + finviz.get("weighted_count", 0.0)

    return {
        "yahoo_count_24h": yahoo.get("count_24h", 0),
        "finviz_count_24h": finviz.get("count_24h", 0),
        "total_count_24h": yahoo.get("count_24h", 0) + finviz.get("count_24h", 0),
        "count_2_7d": yahoo.get("count_2_7d", 0) + finviz.get("count_2_7d", 0),
        "count_7d": yahoo.get("count_7d", 0) + finviz.get("count_7d", 0),
        "weighted_count": round(weighted, 2),
        "has_sec_filing": yahoo.get("has_sec_filing", False) or finviz.get("has_sec_filing", False),
        "has_real_news": yahoo.get("has_real_news", False) or finviz.get("has_real_news", False),
        "headlines": headlines_24h,
        "headlines_7d": headlines_7d,
        "error": yahoo.get("error", True) and finviz.get("error", True),
    }


# ── Reddit ────────────────────────────────────────────────────────────────────

async def _fetch_reddit(ticker: str, client: httpx.AsyncClient) -> list[dict]:
    subreddits = "wallstreetbets+pennystocks+smallcapstocks+stocks"
    url = (
        f"https://www.reddit.com/r/{subreddits}/search.json"
        f"?q={ticker}&sort=new&t=day&restrict_sr=true&limit=25"
    )
    try:
        resp = await client.get(url, headers=HEADERS)
        if resp.status_code != 200:
            return []
        posts = resp.json().get("data", {}).get("children", [])
        results = []
        for p in posts:
            post = p.get("data", {})
            epoch = post.get("created_utc")
            if not epoch:
                continue
            ts = datetime.fromtimestamp(epoch, tz=timezone.utc)
            title = (post.get("title") or "")[:200]
            body = post.get("selftext") or ""
            combined = (title + " " + body).upper()
            if ticker.upper() not in combined and f"${ticker.upper()}" not in combined:
                continue
            results.append({
                "source": "reddit",
                "ts": ts,
                "text": title,
                "sentiment": "",
            })
        return results
    except Exception as e:
        logger.debug(f"Reddit fetch failed for {ticker}: {e}")
        return []


# ── Main entry point ──────────────────────────────────────────────────────────

async def fetch_all(ticker: str) -> dict[str, Any]:
    """
    Fetch all social sources for a ticker concurrently.
    Returns {ticker, mentions, by_source, news_detail, fetched_at}.
    Never raises — empty on any failure.
    """
    ticker = ticker.upper()
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT, follow_redirects=True) as client:
            twits, yahoo_raw, reddit, finviz_raw = await asyncio.gather(
                _fetch_stocktwits(ticker, client),
                _fetch_yahoo_v2_or_v1(ticker, client),
                _fetch_reddit(ticker, client),
                _fetch_finviz_raw(ticker, client),
                return_exceptions=True,
            )
        twits = twits if isinstance(twits, list) else []
        yahoo_raw = yahoo_raw if isinstance(yahoo_raw, list) else []
        reddit = reddit if isinstance(reddit, list) else []
        finviz_raw = finviz_raw if isinstance(finviz_raw, list) else []
    except Exception as e:
        logger.warning(f"Hype fetch failed for {ticker}: {e}")
        twits, yahoo_raw, reddit, finviz_raw = [], [], [], []

    # Build rich news detail from both sources
    yahoo_detail = _build_news_detail(yahoo_raw, "yahoo")
    finviz_detail = _build_news_detail(finviz_raw, "finviz")
    news_detail = _merge_news_details(yahoo_detail, finviz_detail)

    # If both scrapers returned nothing, fall back to Claude web search
    if news_detail.get("total_count_24h", 0) == 0 and news_detail.get("count_7d", 0) == 0:
        try:
            from hype_monitor.news_claude import fetch_news_claude
            logger.info(f"All scrapers empty for {ticker}, trying Claude web search...")
            claude_news = await fetch_news_claude(ticker)
            if not claude_news.get("error"):
                news_detail = claude_news
        except Exception as e:
            logger.debug(f"Claude news fallback failed for {ticker}: {e}")

    # Build unified mention list for velocity.py using full 7d news.
    # velocity.py will count windows (2h/6h/24h) from this list — we need
    # enough historical data so the 24h baseline is accurate, not just 2h.
    news_mentions = []
    now = _now_utc()
    for h in news_detail["headlines_7d"]:
        approx_ts = now - timedelta(hours=h["hours_ago"])
        news_mentions.append({
            "source": "news",
            "ts": approx_ts,
            "text": h["title"],
            "sentiment": "",
        })

    all_mentions = twits + news_mentions + reddit
    all_mentions.sort(key=lambda m: m["ts"], reverse=True)

    return {
        "ticker": ticker,
        "mentions": all_mentions,
        "by_source": {
            "stocktwits": twits,
            "news": news_mentions,
            "reddit": reddit,
        },
        "news_detail": news_detail,
        "fetched_at": _now_utc().isoformat(),
    }


async def _fetch_yahoo_v2_or_v1(ticker: str, client: httpx.AsyncClient) -> list[dict]:
    """Try v2, fall back to v1 if empty."""
    result = await _fetch_yahoo_v2(ticker, client)
    if not result:
        result = await _fetch_yahoo_v1(ticker, client)
    return result


async def _fetch_finviz_raw(ticker: str, client: httpx.AsyncClient) -> list[dict]:
    """Scrape Finviz and return raw article list."""
    url = f"https://finviz.com/quote.ashx?t={ticker}&p=d"
    try:
        resp = await client.get(url, headers=HTML_HEADERS)
        if resp.status_code != 200:
            return []
        soup = BeautifulSoup(resp.text, "lxml")
        table = soup.find("table", id="news-table")
        if not table:
            return []

        articles = []
        last_date = None
        for row in table.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) < 2:
                continue
            date_text = cells[0].get_text(strip=True)
            anchor = cells[1].find("a")
            if not anchor:
                continue
            title = anchor.get_text(strip=True)[:200]
            try:
                if len(date_text) > 8:
                    parts = date_text.split()
                    date_part = parts[0]
                    time_part = parts[1] if len(parts) > 1 else "12:00AM"
                    ts = datetime.strptime(f"{date_part} {time_part}", "%b-%d-%y %I:%M%p").replace(tzinfo=timezone.utc)
                    last_date = date_part
                else:
                    if not last_date:
                        continue
                    ts = datetime.strptime(f"{last_date} {date_text}", "%b-%d-%y %I:%M%p").replace(tzinfo=timezone.utc)
            except (ValueError, IndexError):
                continue
            articles.append({"title": title, "ts": ts, "publisher": "Finviz", "url": anchor.get("href", "")})
        return articles
    except Exception as e:
        logger.debug(f"Finviz raw fetch failed for {ticker}: {e}")
        return []
