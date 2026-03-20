"""
Fetch small-cap ticker symbols from Finviz screener.
No API key required — parses public HTML.
"""
import asyncio
import logging
from typing import List

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

FINVIZ_BASE = "https://finviz.com/screener.ashx"
FINVIZ_PARAMS = "v=111&f=cap_smallunder,geo_usa,sh_avgvol_o300,sh_price_u50,sh_price_o1&ft=4"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://finviz.com/",
}

FALLBACK_TICKERS = [
    "SNDL", "CLOV", "WISH", "EXPR", "BBBY", "AMC", "GME", "TLRY", "ACB", "CRON",
    "APHA", "HEXO", "OGI", "KERN", "IDEX", "XPEV", "NIO", "RIDE", "WKHS", "SOLO",
    "BLNK", "PLUG", "FCEL", "BLDP", "RUN", "NOVA", "SPWR", "ENPH", "SEDG", "CSIQ",
    "JKS", "DQ", "AZRE", "MAXN", "ARRY", "SHLS", "STEM", "BEEM", "FLUX", "PEGI",
    "AMRC", "HASI", "CWEN", "AY", "BEP", "CLNE", "HYLN", "NKLA", "FSR", "GOEV",
]


def _parse_tickers(html: str) -> list:
    """Parse ticker symbols from Finviz screener HTML table."""
    soup = BeautifulSoup(html, "html.parser")
    tickers = []

    # Finviz screener table: look for ticker links
    # Tickers appear in <td> with class 'screener-link-primary' or as links to /quote.ashx?t=
    for tag in soup.find_all("a", href=True):
        href = tag.get("href", "")
        if "quote.ashx?t=" in href:
            ticker = href.split("t=")[1].split("&")[0].strip().upper()
            if ticker and 1 <= len(ticker) <= 5 and ticker.isalpha():
                tickers.append(ticker)

    return tickers


async def get_tickers() -> List[str]:
    """
    Fetch small-cap tickers from Finviz screener with pagination.
    Returns deduplicated list (max 800 tickers).
    Falls back to hardcoded list on failure.
    """
    all_tickers = []
    max_tickers = 800
    page_size = 20

    try:
        async with httpx.AsyncClient(
            headers=HEADERS, timeout=30.0, follow_redirects=True
        ) as client:
            row = 1
            while len(all_tickers) < max_tickers:
                url = f"{FINVIZ_BASE}?{FINVIZ_PARAMS}&r={row}"
                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        logger.warning(f"Finviz returned {resp.status_code} at row {row}")
                        break

                    page_tickers = _parse_tickers(resp.text)
                    if not page_tickers:
                        logger.info(f"No more tickers at row {row}, stopping pagination")
                        break

                    new_tickers = [t for t in page_tickers if t not in all_tickers]
                    if not new_tickers:
                        break

                    all_tickers.extend(new_tickers)
                    logger.info(f"Fetched row={row}, got {len(new_tickers)} new tickers, total={len(all_tickers)}")

                    if len(page_tickers) < page_size:
                        break

                    row += page_size
                    await asyncio.sleep(0.5)  # polite delay

                except httpx.TimeoutException:
                    logger.warning(f"Timeout fetching Finviz page at row {row}")
                    break
                except Exception as e:
                    logger.warning(f"Error fetching Finviz page at row {row}: {e}")
                    break

    except Exception as e:
        logger.error(f"Failed to initialize Finviz client: {e}")

    if not all_tickers:
        logger.warning("Finviz scraping failed — using fallback ticker list")
        return FALLBACK_TICKERS

    # Deduplicate while preserving order
    seen = set()
    unique = []
    for t in all_tickers:
        if t not in seen:
            seen.add(t)
            unique.append(t)

    return unique[:max_tickers]
