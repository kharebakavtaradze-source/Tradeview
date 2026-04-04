"""
Finviz sector performance scraper.
Fetches live daily change% for all 11 GICS sectors.
Cached in memory for up to 4 hours — sector rotation doesn't change minute-to-minute.
"""
import logging
from datetime import datetime, timedelta

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

FINVIZ_SECTOR_URL = "https://finviz.com/groups.ashx?g=sector&o=name"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
    "Accept-Language": "en-US,en;q=0.9",
}

_sector_cache: dict = {}
_sector_cache_time: datetime | None = None
_CACHE_TTL = timedelta(hours=4)


async def fetch_sector_performance() -> dict:
    """
    Scrape Finviz sector performance page.
    Returns dict keyed by sector name:
      {
        "Basic Materials":    {"change_pct": 0.97, "direction": "UP",   "strong": True,  "weak": False},
        "Technology":         {"change_pct": -1.98,"direction": "DOWN",  "strong": False, "weak": True},
        ...
      }
    Falls back to cached data if request fails. Returns {} if no data available.
    """
    global _sector_cache, _sector_cache_time

    now = datetime.now()
    if _sector_cache and _sector_cache_time and (now - _sector_cache_time) < _CACHE_TTL:
        return _sector_cache

    try:
        async with httpx.AsyncClient(
            headers=_HEADERS,
            timeout=15.0,
            follow_redirects=True,
        ) as client:
            resp = await client.get(FINVIZ_SECTOR_URL)
            resp.raise_for_status()

        soup = BeautifulSoup(resp.text, "lxml")
        result = _parse_sector_table(soup)

        if result:
            _sector_cache = result
            _sector_cache_time = now
            logger.info(f"Finviz sector performance: {len(result)} sectors fetched")
        else:
            logger.warning("Finviz sector parse returned empty result — check HTML structure")

        return result or _sector_cache

    except Exception as e:
        logger.warning(f"Finviz sector fetch failed (non-fatal): {e}")
        return _sector_cache or {}


def _parse_sector_table(soup: BeautifulSoup) -> dict:
    """Parse Finviz groups page. Tries multiple selectors for robustness."""
    result: dict = {}

    # Finviz groups page: rows have class 'styled-row' or 'table-light'
    rows = soup.select("tr.styled-row") or soup.select("tr.table-light")

    # Fallback: find any table row with a link to groups.ashx?g=sector
    if not rows:
        for row in soup.find_all("tr"):
            cells = row.find_all("td")
            if len(cells) >= 3:
                link = cells[0].find("a", href=lambda h: h and "g=sector" in h)
                if link:
                    rows.append(row)

    for row in rows:
        cells = row.find_all("td")
        if len(cells) < 3:
            continue

        name = cells[0].get_text(strip=True)
        # Change% is typically in column index 2 (Name, Stocks, Change%, ...)
        change_str = cells[2].get_text(strip=True)

        if not name or not change_str:
            continue

        try:
            change_pct = float(change_str.replace("%", "").replace("+", "").strip())
        except ValueError:
            continue

        result[name] = {
            "change_pct": round(change_pct, 2),
            "direction": "UP" if change_pct > 0 else "DOWN",
            "strong": change_pct > 0.5,
            "weak": change_pct < -1.5,
        }

    return result


def get_strong_sectors(data: dict) -> list[str]:
    """Return GICS sector names with change_pct > +0.5%."""
    from scanner.sector_map import FINVIZ_TO_GICS
    result = []
    for name, d in data.items():
        if d["change_pct"] > 0.5:
            result.append(FINVIZ_TO_GICS.get(name, name))
    return result


def get_weak_sectors(data: dict) -> list[str]:
    """Return GICS sector names with change_pct < -1.5%."""
    from scanner.sector_map import FINVIZ_TO_GICS
    result = []
    for name, d in data.items():
        if d["change_pct"] < -1.5:
            result.append(FINVIZ_TO_GICS.get(name, name))
    return result


def calc_sector_momentum(data: dict) -> dict:
    """
    Rank sectors by today's performance. Adds rank_1d and trending flag.
    Returns data dict enriched with momentum fields (keyed by Finviz name).
    """
    if not data:
        return {}

    sorted_sectors = sorted(data.items(), key=lambda x: x[1]["change_pct"], reverse=True)
    result = {}
    for rank, (name, d) in enumerate(sorted_sectors, 1):
        result[name] = {
            **d,
            "rank_1d": rank,
            "trending": rank <= 3 and d["change_pct"] > 0,
        }
    return result


async def fetch_sector_performance_with_momentum() -> dict:
    """Fetch sector performance and enrich with momentum ranking."""
    data = await fetch_sector_performance()
    return calc_sector_momentum(data)
