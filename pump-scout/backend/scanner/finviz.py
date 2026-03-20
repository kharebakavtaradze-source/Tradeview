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
FINVIZ_PARAMS = "v=111&f=cap_smallunder,geo_usa,sh_avgvol_o300,sh_price_u50,sh_price_o1&ft=4"
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
]


def _parse_tickers(html: str) -> list:
    """Parse ticker symbols from Finviz screener HTML table."""
    soup = BeautifulSoup(html, "html.parser")
    tickers = []
    for tag in soup.find_all("a", href=True):
        href = tag.get("href", "")
        if "quote.ashx?t=" in href:
            ticker = href.split("t=")[1].split("&")[0].strip().upper()
            if ticker and 1 <= len(ticker) <= 5 and ticker.isalpha():
                tickers.append(ticker)
    return tickers


async def _fetch_yahoo_screener() -> List[str]:
    """Fetch small-cap tickers from Yahoo Finance screener as backup."""
    tickers = []
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json",
    }
    try:
        async with httpx.AsyncClient(headers=headers, timeout=20.0) as client:
            for offset in range(0, 400, 100):
                url = (
                    f"https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
                    f"?scrIds=small_cap_gainers&count=100&offset={offset}"
                )
                resp = await client.get(url)
                if resp.status_code != 200:
                    break
                data = resp.json()
                quotes = data.get("finance", {}).get("result", [{}])[0].get("quotes", [])
                for q in quotes:
                    sym = q.get("symbol", "")
                    if sym and 1 <= len(sym) <= 5 and sym.isalpha():
                        tickers.append(sym)
                if len(quotes) < 100:
                    break
                await asyncio.sleep(0.3)
    except Exception as e:
        logger.warning(f"Yahoo screener failed: {e}")
    return tickers


async def get_tickers() -> List[str]:
    """
    Fetch small-cap tickers. Priority:
    1. Finviz screener (HTML scrape)
    2. Yahoo Finance screener (API)
    3. Static fallback list
    Returns deduplicated list (max 500 tickers).
    """
    all_tickers = []
    max_tickers = 500
    page_size = 20

    # --- Try Finviz ---
    try:
        async with httpx.AsyncClient(
            headers=HEADERS, timeout=20.0, follow_redirects=True
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
                        break
                    new_tickers = [t for t in page_tickers if t not in all_tickers]
                    if not new_tickers:
                        break
                    all_tickers.extend(new_tickers)
                    logger.info(f"Finviz row={row}: +{len(new_tickers)} tickers, total={len(all_tickers)}")
                    if len(page_tickers) < page_size:
                        break
                    row += page_size
                    await asyncio.sleep(0.5)
                except httpx.TimeoutException:
                    logger.warning(f"Finviz timeout at row {row}")
                    break
                except Exception as e:
                    logger.warning(f"Finviz error at row {row}: {e}")
                    break
    except Exception as e:
        logger.error(f"Finviz client error: {e}")

    if len(all_tickers) >= 50:
        logger.info(f"Finviz OK: {len(all_tickers)} tickers")
    else:
        logger.warning(f"Finviz returned only {len(all_tickers)} — trying Yahoo screener")
        yahoo_tickers = await _fetch_yahoo_screener()
        if yahoo_tickers:
            logger.info(f"Yahoo screener: {len(yahoo_tickers)} tickers")
            for t in yahoo_tickers:
                if t not in all_tickers:
                    all_tickers.append(t)

    if len(all_tickers) < 50:
        logger.warning(f"Both sources failed ({len(all_tickers)} tickers) — using static fallback list")
        for t in FALLBACK_TICKERS:
            if t not in all_tickers:
                all_tickers.append(t)

    # Deduplicate
    seen = set()
    unique = []
    for t in all_tickers:
        if t not in seen:
            seen.add(t)
            unique.append(t)

    logger.info(f"Final ticker list: {len(unique)} tickers")
    return unique[:max_tickers]
