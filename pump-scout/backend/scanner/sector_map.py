"""
Canonical sector map for Pump Scout.
Priority: SECTOR_MAP → Yahoo Finance API (via sector_sympathy.get_sector).
"""

SECTOR_MAP: dict[str, str] = {
    # ── Technology ────────────────────────────────────────────────────────────
    "AAPL": "Technology", "MSFT": "Technology",
    "NVDA": "Technology", "AMD": "Technology",
    "INTC": "Technology", "CSCO": "Technology",
    "QCOM": "Technology", "AVGO": "Technology",
    "TXN": "Technology", "MU": "Technology",
    "LRCX": "Technology", "COHR": "Technology",
    "SMCI": "Technology", "RDWR": "Technology",
    "ITRI": "Technology", "TUYA": "Technology",
    "GEN": "Technology", "PL": "Technology",
    "DXYZ": "Technology", "NTGR": "Technology",
    # AI / Quantum
    "BBAI": "Technology", "SOUN": "Technology", "AIXI": "Technology",
    "AITX": "Technology", "IONQ": "Technology", "RGTI": "Technology",
    "QUBT": "Technology", "QBTS": "Technology", "CXAI": "Technology",
    "GFAI": "Technology", "AIOT": "Technology",
    # ── Communication Services ─────────────────────────────────────────────────
    "LYFT": "Communication", "UBER": "Communication",
    "CMCSA": "Communication", "T": "Communication",
    "VZ": "Communication", "UNIT": "Communication",
    "SATS": "Communication", "LUMN": "Communication",
    "MTCH": "Communication", "META": "Communication",
    "GOOGL": "Communication", "DIS": "Communication",
    "NFLX": "Communication", "CRCL": "Communication",
    "AMC": "Communication",
    # Space / Satellite
    "ASTS": "Communication", "SATL": "Communication",
    "GSAT": "Communication", "VSAT": "Communication",
    "NXST": "Communication", "SPIR": "Communication",
    # ── Energy ────────────────────────────────────────────────────────────────
    "APA": "Energy", "DVN": "Energy",
    "COP": "Energy", "XOM": "Energy",
    "WRD": "Energy", "UEC": "Energy",
    "CVX": "Energy", "EOG": "Energy",
    "SLB": "Energy", "PXD": "Energy",
    # ── Healthcare ────────────────────────────────────────────────────────────
    "UNH": "Healthcare", "ABT": "Healthcare",
    "MRK": "Healthcare", "ABBV": "Healthcare",
    "IRWD": "Healthcare", "VOR": "Healthcare",
    "INMB": "Healthcare", "BNGO": "Healthcare",
    "CAPR": "Healthcare", "MYGN": "Healthcare",
    "KPTI": "Healthcare", "ADMA": "Healthcare",
    "IBRX": "Healthcare", "KLTR": "Healthcare",
    "CTKB": "Healthcare", "ANNX": "Healthcare",
    "NVAX": "Healthcare", "OCGN": "Healthcare",
    "SAVA": "Healthcare", "SENS": "Healthcare",
    "CODX": "Healthcare", "TPST": "Healthcare",
    "HALO": "Healthcare", "DNLI": "Healthcare",
    "FOLD": "Healthcare", "MIST": "Healthcare",
    "RCKT": "Healthcare", "RYTM": "Healthcare",
    "CRVS": "Healthcare", "DERM": "Healthcare",
    "HUMA": "Healthcare", "INAB": "Healthcare",
    "ZLAB": "Healthcare", "NRIX": "Healthcare",
    "VSTM": "Healthcare", "CORT": "Healthcare",
    "ATAI": "Healthcare", "CLDX": "Healthcare",
    "VNDA": "Healthcare", "AKBA": "Healthcare",
    "BCYC": "Healthcare", "XNCR": "Healthcare",
    "SANA": "Healthcare", "TGTX": "Healthcare",
    "TNXP": "Healthcare", "PCVX": "Healthcare",
    "IMVT": "Healthcare", "BHVN": "Healthcare",
    "VRCA": "Healthcare", "IDYA": "Healthcare",
    "CPRX": "Healthcare", "NRXS": "Healthcare",
    "STRO": "Healthcare", "PDSB": "Healthcare",
    "ALLO": "Healthcare", "AMRX": "Healthcare",
    "ERAS": "Healthcare", "FATE": "Healthcare",
    "ITRM": "Healthcare", "CRBU": "Healthcare",
    "REPL": "Healthcare", "ARRY": "Healthcare",
    "KYMR": "Healthcare",
    # ── Financial ─────────────────────────────────────────────────────────────
    "RF": "Financial", "RITM": "Financial", "WT": "Financial",
    "AGNC": "Financial", "SKWD": "Financial",
    "CFFN": "Financial", "HFWA": "Financial",
    "JHG": "Financial", "SPNT": "Financial",
    "CIM": "Financial", "BX": "Financial",
    "MS": "Financial", "JPM": "Financial",
    "GS": "Financial", "PGR": "Financial",
    "ALL": "Financial", "GPGI": "Financial",
    "EFSC": "Financial", "SOFI": "Financial",
    "HOOD": "Financial",
    # Crypto miners (classified as Financial)
    "MARA": "Financial", "RIOT": "Financial",
    "CLSK": "Financial", "HUT": "Financial",
    "BITF": "Financial", "WULF": "Financial",
    "BTBT": "Financial", "CIFR": "Financial",
    "IREN": "Financial", "GREE": "Financial",
    # ── Consumer Defensive ────────────────────────────────────────────────────
    "PG": "Consumer Defensive",
    "CALM": "Consumer Defensive",
    "WLY": "Consumer Defensive",
    "NWL": "Consumer Defensive",
    "LW": "Consumer Defensive",
    "SCHL": "Consumer Defensive",
    "SFD": "Consumer Defensive", "EL": "Consumer Defensive",
    "HAIN": "Consumer Defensive",
    "SNDL": "Consumer Defensive", "TLRY": "Consumer Defensive",
    "CGC": "Consumer Defensive", "ACB": "Consumer Defensive",
    "CRON": "Consumer Defensive", "HEXO": "Consumer Defensive",
    # ── Consumer Cyclical ─────────────────────────────────────────────────────
    "ANGI": "Consumer Cyclical",
    "CURV": "Consumer Cyclical",
    "GTM": "Consumer Cyclical",
    "TILE": "Consumer Cyclical",
    "CELH": "Consumer Cyclical",
    "ADNT": "Consumer Cyclical",
    "DOUG": "Consumer Cyclical",
    "NSP": "Consumer Cyclical",
    "GME": "Consumer Cyclical",
    "DKNG": "Consumer Cyclical", "PENN": "Consumer Cyclical",
    # EV
    "NKLA": "Consumer Cyclical", "FFIE": "Consumer Cyclical",
    "GOEV": "Consumer Cyclical", "MULN": "Consumer Cyclical",
    "RIVN": "Consumer Cyclical", "LCID": "Consumer Cyclical",
    "SOLO": "Consumer Cyclical", "BLNK": "Consumer Cyclical",
    "EVGO": "Consumer Cyclical", "CHPT": "Consumer Cyclical",
    "AYRO": "Consumer Cyclical", "IDEX": "Consumer Cyclical",
    # ── Industrials ───────────────────────────────────────────────────────────
    "UPS": "Industrials", "TITN": "Industrials",
    "NNBR": "Industrials", "USAR": "Industrials",
    "LUNR": "Industrials", "ABM": "Industrials",
    "EVTL": "Industrials", "NXE": "Industrials",
    "RKLB": "Industrials", "MNTS": "Industrials",
    "VORB": "Industrials", "ASTRA": "Industrials",
    "WKHS": "Industrials", "PTRA": "Industrials",
    # ── Materials ─────────────────────────────────────────────────────────────
    "AGI": "Materials", "BVN": "Materials",
    "HMY": "Materials", "CEF": "Materials",
    "AMCR": "Materials",
    # ── Real Estate ───────────────────────────────────────────────────────────
    "CTRE": "Real Estate", "HIW": "Real Estate",
    "NXRT": "Real Estate",
    # ── Utilities ─────────────────────────────────────────────────────────────
    "XLU": "Utilities",
}


def get_sector_sync(symbol: str) -> str:
    """Synchronous sector lookup — checks SECTOR_MAP only."""
    return SECTOR_MAP.get(symbol.upper(), "Unknown")


# ── Non-stock securities ───────────────────────────────────────────────────────
# Volume anomalies in these instruments are often driven by NAV discounts,
# distribution mechanics, or fund events — not institutional accumulation.

# Known closed-end funds (CEFs)
CLOSED_END_FUNDS: set[str] = {
    'BRW', 'ARDC', 'AWF', 'ACP', 'BCX',
    'BGB', 'BGH', 'BGT', 'BGX', 'BHK',
    'BIT', 'BKT', 'BLW', 'BME', 'BNA',
    'BOE', 'BPK', 'BRA', 'BRB', 'BSL',
    'BTZ', 'BUI', 'CEM', 'CHI', 'CHW',
    'CHY', 'CIK', 'CIZ', 'CLM', 'CRF',
    'CSQ', 'CXE', 'CXH', 'DHY', 'DFP',
    'DMO', 'DSM', 'DSU', 'DUC', 'EAD',
    'EDD', 'EFR', 'EFT', 'EHI', 'EIM',
    'EMD', 'EMF', 'EMI', 'ERC', 'ETB',
    'ETG', 'ETJ', 'ETW', 'ETX', 'ETV',
    'EVG', 'EVN', 'EVT', 'EXG', 'FAX',
    'FFA', 'FFC', 'FHY', 'FIF', 'FLC',
    'FMN', 'FMO', 'FMY', 'FNF', 'FPF',
    'FRA', 'FRD', 'FSK', 'GAB', 'GDL',
    'GDO', 'GGM', 'GGT', 'GGZ', 'GLO',
    'GLQ', 'GLU', 'GLV', 'GNT', 'GOF',
    'GPM', 'GRX', 'HNW', 'HPI', 'HPF',
    'HPS', 'HTD', 'HTM', 'HYB', 'HYI',
    'HYT', 'IGA', 'IGD', 'IGI', 'IGR',
    'JCE', 'JDD', 'JEQ', 'JFR', 'JGH',
    'JHB', 'JHD', 'JHS', 'JMT', 'JPC',
    'JPT', 'JQC', 'JRS', 'JSD', 'JSM',
    'JTD', 'KIO', 'KMF', 'LDP', 'MCR',
    'MHD', 'MHF', 'MHI', 'MHN', 'MIE',
    'MIN', 'MMD', 'MMT', 'MNP', 'MPA',
    'MPV', 'MQT', 'MQY', 'MSD', 'MSF',
    'MVF', 'MYC', 'MYD', 'MYF', 'MYI',
    'MYJ', 'MYN', 'NBB', 'NBD', 'NBH',
    'NBO', 'NBW', 'NEA', 'NID', 'NIE',
    'NIM', 'NIO', 'NKX', 'NMI', 'NMO',
    'NMT', 'NMZ', 'NPF', 'NPM', 'NPP',
    'NPT', 'NQP', 'NRK', 'NSL', 'NUO',
    'NUW', 'NVG', 'NXC', 'NXE', 'NXJ',
    'NXP', 'NXQ', 'NXR', 'NXZ', 'NYV',
    'OIA', 'PCF', 'PCK', 'PCN', 'PCQ',
    'PCI', 'PDI', 'PDO', 'PFD', 'PFN',
    'PHD', 'PHK', 'PHT', 'PKO', 'PMF',
    'PML', 'PMM', 'PMO', 'PMX', 'PNI',
    'PPT', 'PTA', 'PTY', 'PXF', 'PYN',
    'RCS', 'RFI', 'RFM', 'RIF', 'RMT',
    'RSF', 'RVT', 'SAF', 'SBI', 'SCM',
    'SCD', 'SCZ', 'SDF', 'SDHY', 'SRH',
    'STK', 'SZC', 'TDF', 'TFI', 'THQ',
    'THW', 'TPZ', 'TYG', 'USA',
    'UTF', 'UTG', 'VBF', 'VFL', 'VGI',
    'VGM', 'VHI', 'VMO', 'VPV', 'VSC',
    'WDI', 'WIA', 'WIW', 'WMC',
    'XAI', 'ZTR',
    # SABA funds
    'SABA', 'BRWN',
}

# Exchange-traded notes (ETNs — not stocks)
EXCHANGE_TRADED_NOTES: set[str] = {
    'TVIX', 'UVXY', 'VXX', 'SVXY',
    'VIXY', 'VIXM', 'ZIV', 'XIV',
}

# Combined lookup set
NON_STOCK_SECURITIES: set[str] = CLOSED_END_FUNDS | EXCHANGE_TRADED_NOTES
