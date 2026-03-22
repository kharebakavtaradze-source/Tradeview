"""
Fetch small-cap ticker symbols from Finviz screener.
Falls back to Yahoo Finance screener, then to a large static list.
"""
import asyncio
import logging
from typing import List

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

FINVIZ_BASE = "https://finviz.com/screener.ashx"

# Primary filter: small-cap + micro-cap, USA, avg vol > 300K, price $1-$50
_FILTER_SMALLCAP = "v=111&f=cap_smallunder,geo_usa,sh_avgvol_o300,sh_price_u50,sh_price_o1&ft=4"
# Secondary filter: nano/micro-cap, high relative volume (adds more pump candidates)
_FILTER_MICROCAP = "v=111&f=cap_microunder,geo_usa,sh_avgvol_o100,sh_price_u20,sh_price_o0.5&ft=4"
# Tertiary: small+mid cap gainers with volume (catches sympathy plays)
_FILTER_GAINERS  = "v=111&f=cap_smallunder,geo_usa,sh_avgvol_o200,ta_change_u15&ft=4"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://finviz.com/",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

# Large static fallback list of known small-cap / mid-cap US stocks
FALLBACK_TICKERS = [
    # Tech small-caps
    "BBAI", "SOUN", "AIXI", "AITX", "BRSH", "CXAI", "GFAI", "IREN", "CIFR",
    "BTBT", "MARA", "RIOT", "HUT", "CLSK", "BITF", "WULF", "ARIS", "GRIID",
    "ACHR", "JOBY", "LILM", "EVTL", "BLDE", "WKHS", "AYRO",
    "SOLO", "GOEV", "NKLA", "FFIE", "IDEX", "MULN", "EVGO", "BLNK", "CHPT",
    "PTRA", "DKNG", "PENN", "GNOG", "ACMR", "GRND", "ASTS", "SATL",
    # Biotech / Pharma
    "ACAD", "ACLS", "ACNB", "ADMA", "ADTX", "AGIO", "AGTC", "AGRX",
    "AKBA", "AKRO", "ALEC", "ALIT", "ALLO", "ALNY", "ALPN", "AMRX",
    "ANAB", "ANTE", "ARAV", "ARDX", "AREB", "ARQT", "ARRY", "ASND",
    "ATAI", "ATEC", "ATHA", "ATLO", "ATNF", "ATRC", "ATXI", "AUPH",
    "AVDL", "AVEO", "AVIR", "AXSM", "AZTA", "BCAB", "BCLI", "BCYC",
    "BDSI", "BFRI", "BHVN", "BIOL", "BKNG", "BLCM", "BLUE", "BNGO",
    "BNTX", "BPMC", "BPTH", "BRBR", "BRBT", "BSGM", "BTAI", "BYFC",
    "CAPR", "CARA", "CARV", "CASI", "CBPO", "CCCC", "CCXI", "CDMO",
    "CERS", "CGEM", "CHMA", "CHRS", "CKPT", "CLDX", "CLFD", "CLRB",
    "CLVS", "CMRX", "CNCE", "CNTB", "COCP", "CODA", "CODX", "COGT",
    "CORT", "CPIX", "CPRX", "CRBU", "CRDF", "CRIS", "CRNX", "CRTX",
    "CRVS", "CTMX", "CTSO", "CYCN", "CYTH", "DARE", "DAVA", "DBVT",
    "DCPH", "DERM", "DNLI", "DOCS", "DRRX", "DRUG", "DVAX", "DXCM",
    "EDSA", "EFSC", "EIGR", "ENTA", "EPZM", "EQRX", "ERAS", "ESPR",
    "ETNB", "EVFM", "EVGN", "FATE", "FBIO", "FDMT", "FGEN", "FLGT",
    "FOLD", "FORM", "FULC", "FUSN", "GALT", "GDRX", "GERN", "GILD",
    "GLPG", "GMDA", "GMVD", "GNFT", "GOSS", "GPCR", "GRNV", "GRTS",
    "GTHX", "GWRS", "HALO", "HARP", "HAVN", "HGEN", "HIIQ", "HLVX",
    "HRTX", "HTTX", "HUMA", "HYLN", "ICAD", "ICVX", "IDYA", "IFRX",
    "IGMS", "IMAB", "IMCR", "IMGN", "IMMP", "IMRN", "IMUX", "IMVT",
    "INAB", "INCY", "INFI", "INFN", "INGN", "INMB", "INMD", "INVA",
    "IONS", "IOVA", "IPSC", "IRWD", "ISEE", "ITCI", "ITOS", "JAZZ",
    "JNCE", "KALA", "KALU", "KDNY", "KPTI", "KRTX", "KYMR", "LBPH",
    "LBRDA", "LCNB", "LGND", "LHCG", "LMNX", "LOGC", "LPTX", "LQDA",
    "LSCC", "LSPD", "LTRN", "LUMO", "LUNA", "LUNG", "LYRA", "MACK",
    "MASS", "MBCN", "MCFT", "MDGL", "MDVX", "MGNX", "MGTA", "MGTX",
    "MIST", "MITT", "MKSI", "MNKD", "MNMD", "MNPR", "MNTA", "MREO",
    "MRKR", "MRNS", "MRSN", "MRTX", "MRUS", "MSRT", "MSVB", "MTSI",
    "MUNE", "MYMD", "MYNA", "MYOV", "NAOV", "NARI", "NBEV", "NBIX",
    "NCNO", "NEOS", "NERV", "NKTR", "NLNK", "NMIH", "NRIX", "NRXS",
    "NTRA", "NTST", "NURO", "NVAX", "NVCN", "NVCR", "NVRO", "NWBO",
    "NXGN", "NXTC", "OCGN", "OMER", "OMGA", "ONCS", "ONTX", "OPCH",
    "OPGN", "ORGO", "ORMP", "ORTX", "OSMT", "OVID", "PACB", "PAHC",
    "PBYI", "PCVX", "PDCO", "PDLI", "PDSB", "PHAT", "PHIO", "PHVS",
    "PING", "PIRS", "PLRX", "PLSE", "PMVP", "PNTM", "POCI", "PRAX",
    "PRLD", "PRME", "PRTK", "PRVB", "PTCT", "PTEN", "PTGX", "PTLO",
    "PULM", "PYPD", "QNST", "RCEL", "RCKT", "RCUS", "RDHL", "RDNT",
    "REPL", "RGEN", "RGLS", "RGNX", "RLMD", "RLYB", "RMBL", "RMCF",
    "RMED", "RNA", "RNLX", "RPID", "RPTX", "RRBI", "RRGB", "RSSS",
    "RUBY", "RVMD", "RVNC", "RYTM", "SAGE", "SANA", "SAVA", "SBGI",
    "SBTX", "SCPH", "SCVL", "SDGR", "SEER", "SESN", "SGEN", "SGMO",
    "SHBI", "SHIP", "SHOT", "SHYF", "SILK", "SLDB", "SLGL", "SLNM",
    "SLNO", "SLRX", "SMMT", "SNOA", "SNPX", "SNSE", "SOLY", "SPPI",
    "SPRO", "SRGA", "SRRK", "SRTS", "SSYS", "STOK", "STRO", "STSA",
    "STTK", "SURF", "SWAV", "SYRS", "TALK", "TBIO", "TBPH", "TCRR",
    "TELA", "TENB", "TERN", "TGTX", "THMO", "THTX", "TILS", "TIRX",
    "TLIS", "TLSA", "TLYS", "TMDI", "TNXP", "TORC", "TPST", "TPVG",
    "TRDA", "TRIL", "TRVI", "TTOO", "TTPH", "TVTX", "TXMD", "TYRA",
    "UCTT", "URGN", "UTHR", "VBIV", "VCNX", "VKTX", "VNDA", "VNET",
    "VNRX", "VRAY", "VRCA", "VRTX", "VSTM", "VTAK", "VTVT", "VXRT",
    "VYGR", "WINT", "WKHS", "WORH", "WRBY", "XBIO", "XCUR", "XENE",
    "XERS", "XFOR", "XNCR", "XOMA", "XPON", "XTLB", "YMAB", "YMTX",
    "YNDX", "YTEN", "ZFGN", "ZLAB", "ZMTP", "ZNTL", "ZSAN", "ZYXI",
    # Meme / retail favorites
    "AMC", "GME", "BB", "NOK", "BBIG", "MVIS", "EXPR", "SPCE", "WISH",
    "CLOV", "GOEV", "NKLA", "PLTR", "SOFI", "HOOD", "RIVN",
    "LCID", "OPEN", "SNDL", "TLRY", "CGC", "ACB", "CRON", "HEXO",
    "SENS", "GNUS", "NAKD", "KOSS",
    # Energy small-caps
    "AMPE", "AMPY", "ARNC", "BATL", "CDEV", "CLMT", "COHN",
    "CORE", "DGLY", "DNOW", "DRIL", "ENVA", "FLNG", "FTIV", "GATO",
    "GPOR", "GRNT", "HNRG", "INDO", "KLXE",
    "MNRL", "MTDR", "NEXT", "NINE", "NRGU", "PNRG", "PUMP",
    "REI", "RES", "RRIG", "SDRL", "SESI", "SHPW", "SIBN", "SNDE",
    "STNG", "TELL", "TRMD", "USWS", "VET", "VTLE", "WTTR",
    # AI / quantum / defense (2024-2025 hot sectors)
    "IONQ", "RGTI", "QUBT", "QBTS", "ARQQ", "AEVA", "LIDR", "OUST",
    "LUNR", "RDW", "MNTS", "VORB", "RKLB", "ASTR", "SPIR", "GSAT",
    "TSAT", "VSAT", "GILT", "MAXN", "NOVA", "ARRY", "FLNC", "STEM",
    "FREYR", "MVST", "NXRT", "NXST", "SMCI", "NVTS", "AIOT", "ITRM",
    "RSSS", "BFRG", "AGFY", "GREE", "MIGI", "AIBR",
]


def _parse_tickers_from_screener(html: str) -> list:
    """
    Parse ticker symbols specifically from the Finviz screener results table.
    Targets the screener-table rows to avoid picking up navigation links.
    Falls back to broad href search if table structure changes.
    """
    soup = BeautifulSoup(html, "html.parser")
    tickers = []
    seen = set()

    # Try the dedicated screener table first (most accurate)
    screener_table = (
        soup.find("table", {"class": "screener_table"})
        or soup.find("table", id="screener-table")
        or soup.find("table", {"class": "table-light"})
    )
    if screener_table:
        for a in screener_table.find_all("a", href=True):
            href = a.get("href", "")
            if "quote.ashx?t=" in href:
                ticker = href.split("t=")[1].split("&")[0].strip().upper()
                if ticker and 1 <= len(ticker) <= 5 and ticker.isalpha() and ticker not in seen:
                    tickers.append(ticker)
                    seen.add(ticker)
        if tickers:
            return tickers

    # Fallback: all quote links on page (still filters to actual tickers)
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if "quote.ashx?t=" in href:
            ticker = href.split("t=")[1].split("&")[0].strip().upper()
            if ticker and 1 <= len(ticker) <= 5 and ticker.isalpha() and ticker not in seen:
                tickers.append(ticker)
                seen.add(ticker)
    return tickers


def _is_blocked(html: str) -> bool:
    """Detect Finviz CAPTCHA / block page."""
    low = html.lower()
    return (
        "captcha" in low
        or "you have been blocked" in low
        or "access denied" in low
        or len(html) < 2000  # real pages are much larger
    )


async def _fetch_finviz_filter(
    client: httpx.AsyncClient,
    filter_params: str,
    max_tickers: int,
) -> list[str]:
    """
    Paginate through one Finviz screener filter set and collect tickers.
    Returns list of unique tickers (up to max_tickers).
    """
    all_tickers: list[str] = []
    seen: set[str] = set()
    page_size = 20  # Finviz overview shows 20 rows per page
    row = 1
    max_pages = max_tickers // page_size + 2  # safety ceiling

    for _ in range(max_pages):
        if len(all_tickers) >= max_tickers:
            break
        url = f"{FINVIZ_BASE}?{filter_params}&r={row}"
        try:
            resp = await client.get(url)
            if resp.status_code != 200:
                logger.warning(f"Finviz returned {resp.status_code} at row {row}")
                break
            if _is_blocked(resp.text):
                logger.warning(f"Finviz appears to be blocking at row {row}")
                break

            page_tickers = _parse_tickers_from_screener(resp.text)
            if not page_tickers:
                break

            added = 0
            for t in page_tickers:
                if t not in seen:
                    seen.add(t)
                    all_tickers.append(t)
                    added += 1

            logger.info(
                f"Finviz filter row={row}: +{added} new, "
                f"page_size={len(page_tickers)}, total={len(all_tickers)}"
            )

            # Last page if fewer results than expected
            if len(page_tickers) < page_size:
                break

            row += page_size
            await asyncio.sleep(1.0)  # respectful delay between pages

        except httpx.TimeoutException:
            logger.warning(f"Finviz timeout at row {row}")
            break
        except Exception as e:
            logger.warning(f"Finviz error at row {row}: {e}")
            break

    return all_tickers


_YAHOO_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
}

# Small-cap US screener filter body for Yahoo POST API
_YAHOO_SCREENER_BODY = {
    "offset": 0,
    "size": 100,
    "sortField": "intradaymarketcap",
    "sortType": "ASC",
    "quoteType": "EQUITY",
    "query": {
        "operator": "AND",
        "operands": [
            {"operator": "GT", "operands": ["intradaymarketcap", 50_000_000]},
            {"operator": "LT", "operands": ["intradaymarketcap", 2_000_000_000]},
            {"operator": "GT", "operands": ["avgdailyvol3month", 300_000]},
            {"operator": "GT", "operands": ["regularmarketprice", 1.0]},
            {"operator": "LT", "operands": ["regularmarketprice", 50.0]},
            {"operator": "EQ", "operands": ["region", "us"]},
        ],
    },
    "userId": "",
    "userIdType": "guid",
}

_PREDEFINED_SCREENS = [
    "small_cap_gainers",
    "most_actives",
    "undervalued_growth_stocks",
    "aggressive_small_caps",
]


def _extract_yahoo_symbols(data: dict) -> list[str]:
    """Extract valid US stock symbols from Yahoo Finance screener response."""
    tickers = []
    quotes = (
        data.get("finance", {}).get("result", [{}])[0].get("quotes", [])
        or data.get("quotes", [])
    )
    for q in quotes:
        sym = q.get("symbol", "")
        if sym and 1 <= len(sym) <= 5 and sym.replace("-", "").isalpha():
            tickers.append(sym.upper())
    return tickers


async def _fetch_yahoo_post_screener(client: httpx.AsyncClient, max_tickers: int = 500) -> list[str]:
    """
    Yahoo Finance POST screener — returns small-cap US stocks by market cap.
    Paginates 0, 100, 200, 300, 400 until max_tickers reached.
    """
    url = "https://query1.finance.yahoo.com/v1/finance/screener"
    tickers: list[str] = []
    seen: set[str] = set()

    for offset in range(0, max_tickers, 100):
        body = {**_YAHOO_SCREENER_BODY, "offset": offset}
        try:
            resp = await client.post(url, json=body, headers=_YAHOO_HEADERS)
            if resp.status_code != 200:
                logger.warning(f"Yahoo POST screener returned {resp.status_code} at offset {offset}")
                break
            symbols = _extract_yahoo_symbols(resp.json())
            if not symbols:
                break
            added = 0
            for s in symbols:
                if s not in seen:
                    seen.add(s)
                    tickers.append(s)
                    added += 1
            logger.info(f"Yahoo POST screener offset={offset}: +{added}, total={len(tickers)}")
            if len(symbols) < 100:
                break
            await asyncio.sleep(0.3)
        except Exception as e:
            logger.warning(f"Yahoo POST screener failed at offset {offset}: {e}")
            break

    return tickers


async def _fetch_yahoo_predefined_screens(client: httpx.AsyncClient) -> list[str]:
    """
    Fetch 4 predefined Yahoo Finance screens concurrently.
    Returns combined unique symbols.
    """
    base_url = "https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
    tickers: list[str] = []
    seen: set[str] = set()

    async def fetch_screen(screen_id: str) -> list[str]:
        result = []
        for offset in range(0, 200, 100):
            try:
                resp = await client.get(
                    base_url,
                    params={"scrIds": screen_id, "count": 100, "offset": offset, "region": "US"},
                    headers=_YAHOO_HEADERS,
                )
                if resp.status_code != 200:
                    break
                symbols = _extract_yahoo_symbols(resp.json())
                result.extend(symbols)
                if len(symbols) < 100:
                    break
                await asyncio.sleep(0.2)
            except Exception as e:
                logger.debug(f"Yahoo predefined screen {screen_id} offset {offset}: {e}")
                break
        return result

    raw = await asyncio.gather(
        *[fetch_screen(s) for s in _PREDEFINED_SCREENS],
        return_exceptions=True,
    )
    for batch in raw:
        if isinstance(batch, list):
            for s in batch:
                if s not in seen:
                    seen.add(s)
                    tickers.append(s)

    logger.info(f"Yahoo predefined screens: {len(tickers)} tickers from {_PREDEFINED_SCREENS}")
    return tickers


async def _fetch_yahoo_screener() -> List[str]:
    """
    Combined Yahoo Finance screener: POST API + 4 predefined screens.
    Returns deduplicated list of US small-cap tickers.
    """
    tickers: list[str] = []
    seen: set[str] = set()

    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            # Run POST screener and predefined screens concurrently
            post_result, predefined_result = await asyncio.gather(
                _fetch_yahoo_post_screener(client, max_tickers=500),
                _fetch_yahoo_predefined_screens(client),
                return_exceptions=True,
            )

        for batch in (post_result, predefined_result):
            if isinstance(batch, list):
                for t in batch:
                    if t not in seen:
                        seen.add(t)
                        tickers.append(t)

        logger.info(f"Yahoo combined screener total: {len(tickers)} tickers")
    except Exception as e:
        logger.warning(f"Yahoo screener failed: {e}")

    return tickers


async def get_tickers() -> List[str]:
    """
    Fetch small-cap tickers. Priority:
    1. Finviz screener — three filter sets (small-cap, micro-cap, gainers)
    2. Yahoo Finance screener (API)
    3. Static fallback list
    Returns deduplicated list (max 800 tickers).
    """
    max_tickers = 800
    all_tickers: list[str] = []
    seen: set[str] = set()

    def _add_unique(source: list[str]) -> int:
        added = 0
        for t in source:
            if t not in seen:
                seen.add(t)
                all_tickers.append(t)
                added += 1
        return added

    # --- Try Finviz (three filter passes) ---
    filters = [
        ("smallcap", _FILTER_SMALLCAP, 400),
        ("microcap", _FILTER_MICROCAP, 250),
        ("gainers",  _FILTER_GAINERS,  150),
    ]
    try:
        async with httpx.AsyncClient(
            headers=HEADERS,
            timeout=25.0,
            follow_redirects=True,
        ) as client:
            for label, fparams, limit in filters:
                page_tickers = await _fetch_finviz_filter(client, fparams, limit)
                added = _add_unique(page_tickers)
                logger.info(f"Finviz {label}: {len(page_tickers)} raw → +{added} unique, total={len(all_tickers)}")
                if len(all_tickers) >= max_tickers:
                    break
                if page_tickers:
                    await asyncio.sleep(1.5)  # pause between filter sets
    except Exception as e:
        logger.error(f"Finviz client error: {e}")

    finviz_count = len(all_tickers)
    if finviz_count >= 100:
        logger.info(f"Finviz OK: {finviz_count} tickers")
    else:
        logger.warning(f"Finviz returned only {finviz_count} (< 100) — running Yahoo screener")
        yahoo_tickers = await _fetch_yahoo_screener()
        if yahoo_tickers:
            added = _add_unique(yahoo_tickers)
            logger.info(f"Yahoo screener: {len(yahoo_tickers)} raw → +{added} unique, total={len(all_tickers)}")
        else:
            logger.warning("Yahoo screener also returned 0 tickers")

    if len(all_tickers) < 50:
        logger.warning(f"Both scrapers failed ({len(all_tickers)}) — using static fallback")
        _add_unique(FALLBACK_TICKERS)

    logger.info(f"Final ticker list: {len(all_tickers[:max_tickers])} tickers")
    return all_tickers[:max_tickers]
