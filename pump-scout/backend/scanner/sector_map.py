"""
Canonical sector map for Pump Scout — GICS 11 sector classification.
Priority: SECTOR_MAP → Yahoo Finance API (via sector_sympathy.get_sector).
"""

# ── GICS 11 Standard Sectors ──────────────────────────────────────────────────
GICS_11_SECTORS = [
    'Information Technology',
    'Health Care',
    'Financials',
    'Consumer Discretionary',
    'Consumer Staples',
    'Energy',
    'Industrials',
    'Materials',
    'Real Estate',
    'Communication Services',
    'Utilities',
]

# ETF proxy for each GICS sector (used in market regime tracking)
GICS_SECTOR_ETFS = {
    'Information Technology':  'XLK',
    'Health Care':             'XLV',
    'Financials':              'XLF',
    'Consumer Discretionary':  'XLY',
    'Consumer Staples':        'XLP',
    'Energy':                  'XLE',
    'Industrials':             'XLI',
    'Materials':               'XLB',
    'Real Estate':             'XLRE',
    'Communication Services':  'XLC',
    'Utilities':               'XLU',
}

# Finviz sector name → GICS sector name mapping
FINVIZ_TO_GICS: dict[str, str] = {
    'Technology':              'Information Technology',
    'Healthcare':              'Health Care',
    'Financial':               'Financials',
    'Financial Services':      'Financials',
    'Consumer Cyclical':       'Consumer Discretionary',
    'Consumer Defensive':      'Consumer Staples',
    'Basic Materials':         'Materials',
    'Communication Services':  'Communication Services',
    'Energy':                  'Energy',
    'Industrials':             'Industrials',
    'Real Estate':             'Real Estate',
    'Utilities':               'Utilities',
}

SECTOR_MAP: dict[str, str] = {
    # ── Information Technology ────────────────────────────────────────────────
    "AAPL": "Information Technology", "MSFT": "Information Technology",
    "NVDA": "Information Technology", "AMD": "Information Technology",
    "INTC": "Information Technology", "CSCO": "Information Technology",
    "QCOM": "Information Technology", "AVGO": "Information Technology",
    "TXN": "Information Technology", "MU": "Information Technology",
    "LRCX": "Information Technology", "COHR": "Information Technology",
    "SMCI": "Information Technology", "RDWR": "Information Technology",
    "ITRI": "Information Technology", "TUYA": "Information Technology",
    "GEN": "Information Technology", "PL": "Information Technology",
    "DXYZ": "Information Technology", "NTGR": "Information Technology",
    # AI / Quantum
    "BBAI": "Information Technology", "SOUN": "Information Technology",
    "AIXI": "Information Technology", "AITX": "Information Technology",
    "IONQ": "Information Technology", "RGTI": "Information Technology",
    "QUBT": "Information Technology", "QBTS": "Information Technology",
    "CXAI": "Information Technology", "GFAI": "Information Technology",
    "AIOT": "Information Technology",
    # ── Communication Services ────────────────────────────────────────────────
    "LYFT": "Communication Services", "UBER": "Communication Services",
    "CMCSA": "Communication Services", "T": "Communication Services",
    "VZ": "Communication Services", "UNIT": "Communication Services",
    "SATS": "Communication Services", "LUMN": "Communication Services",
    "MTCH": "Communication Services", "META": "Communication Services",
    "GOOGL": "Communication Services", "DIS": "Communication Services",
    "NFLX": "Communication Services", "CRCL": "Communication Services",
    "AMC": "Communication Services",
    # Space / Satellite
    "ASTS": "Communication Services", "SATL": "Communication Services",
    "GSAT": "Communication Services", "VSAT": "Communication Services",
    "NXST": "Communication Services", "SPIR": "Communication Services",
    # ── Energy ───────────────────────────────────────────────────────────────
    "APA": "Energy", "DVN": "Energy",
    "COP": "Energy", "XOM": "Energy",
    "WRD": "Energy", "UEC": "Energy",
    "CVX": "Energy", "EOG": "Energy",
    "SLB": "Energy", "PXD": "Energy",
    # ── Health Care ──────────────────────────────────────────────────────────
    "UNH": "Health Care", "ABT": "Health Care",
    "MRK": "Health Care", "ABBV": "Health Care",
    "IRWD": "Health Care", "VOR": "Health Care",
    "INMB": "Health Care", "BNGO": "Health Care",
    "CAPR": "Health Care", "MYGN": "Health Care",
    "KPTI": "Health Care", "ADMA": "Health Care",
    "IBRX": "Health Care", "KLTR": "Health Care",
    "CTKB": "Health Care", "ANNX": "Health Care",
    "NVAX": "Health Care", "OCGN": "Health Care",
    "SAVA": "Health Care", "SENS": "Health Care",
    "CODX": "Health Care", "TPST": "Health Care",
    "HALO": "Health Care", "DNLI": "Health Care",
    "FOLD": "Health Care", "MIST": "Health Care",
    "RCKT": "Health Care", "RYTM": "Health Care",
    "CRVS": "Health Care", "DERM": "Health Care",
    "HUMA": "Health Care", "INAB": "Health Care",
    "ZLAB": "Health Care", "NRIX": "Health Care",
    "VSTM": "Health Care", "CORT": "Health Care",
    "ATAI": "Health Care", "CLDX": "Health Care",
    "VNDA": "Health Care", "AKBA": "Health Care",
    "BCYC": "Health Care", "XNCR": "Health Care",
    "SANA": "Health Care", "TGTX": "Health Care",
    "TNXP": "Health Care", "PCVX": "Health Care",
    "IMVT": "Health Care", "BHVN": "Health Care",
    "VRCA": "Health Care", "IDYA": "Health Care",
    "CPRX": "Health Care", "NRXS": "Health Care",
    "STRO": "Health Care", "PDSB": "Health Care",
    "ALLO": "Health Care", "AMRX": "Health Care",
    "ERAS": "Health Care", "FATE": "Health Care",
    "ITRM": "Health Care", "CRBU": "Health Care",
    "REPL": "Health Care", "ARRY": "Health Care",
    "KYMR": "Health Care",
    # ── Financials ────────────────────────────────────────────────────────────
    "RF": "Financials", "RITM": "Financials", "WT": "Financials",
    "AGNC": "Financials", "SKWD": "Financials",
    "CFFN": "Financials", "HFWA": "Financials",
    "JHG": "Financials", "SPNT": "Financials",
    "CIM": "Financials", "BX": "Financials",
    "MS": "Financials", "JPM": "Financials",
    "GS": "Financials", "PGR": "Financials",
    "ALL": "Financials", "GPGI": "Financials",
    "EFSC": "Financials", "SOFI": "Financials",
    "HOOD": "Financials",
    # Crypto miners (classified under Financials)
    "MARA": "Financials", "RIOT": "Financials",
    "CLSK": "Financials", "HUT": "Financials",
    "BITF": "Financials", "WULF": "Financials",
    "BTBT": "Financials", "CIFR": "Financials",
    "IREN": "Financials", "GREE": "Financials",
    # ── Consumer Staples ──────────────────────────────────────────────────────
    "PG": "Consumer Staples",
    "CALM": "Consumer Staples",
    "WLY": "Consumer Staples",
    "NWL": "Consumer Staples",
    "LW": "Consumer Staples",
    "SCHL": "Consumer Staples",
    "SFD": "Consumer Staples", "EL": "Consumer Staples",
    "HAIN": "Consumer Staples",
    "SNDL": "Consumer Staples", "TLRY": "Consumer Staples",
    "CGC": "Consumer Staples", "ACB": "Consumer Staples",
    "CRON": "Consumer Staples", "HEXO": "Consumer Staples",
    # ── Consumer Discretionary ────────────────────────────────────────────────
    "ANGI": "Consumer Discretionary",
    "CURV": "Consumer Discretionary",
    "GTM": "Consumer Discretionary",
    "TILE": "Consumer Discretionary",
    "CELH": "Consumer Discretionary",
    "ADNT": "Consumer Discretionary",
    "DOUG": "Consumer Discretionary",
    "NSP": "Consumer Discretionary",
    "GME": "Consumer Discretionary",
    "DKNG": "Consumer Discretionary", "PENN": "Consumer Discretionary",
    # EV
    "NKLA": "Consumer Discretionary", "FFIE": "Consumer Discretionary",
    "GOEV": "Consumer Discretionary", "MULN": "Consumer Discretionary",
    "RIVN": "Consumer Discretionary", "LCID": "Consumer Discretionary",
    "SOLO": "Consumer Discretionary", "BLNK": "Consumer Discretionary",
    "EVGO": "Consumer Discretionary", "CHPT": "Consumer Discretionary",
    "AYRO": "Consumer Discretionary", "IDEX": "Consumer Discretionary",
    # ── Industrials ──────────────────────────────────────────────────────────
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


# ── Industry-level mapping ────────────────────────────────────────────────────
# Used for sub-industry sympathy tracking (stronger than sector-level)
TICKER_INDUSTRY: dict[str, str] = {
    # Biotechnology
    "KPTI": "Biotechnology", "MGTX": "Biotechnology",
    "VOR": "Biotechnology", "INMB": "Biotechnology",
    "CAPR": "Biotechnology", "BNGO": "Biotechnology",
    "NVAX": "Biotechnology", "OCGN": "Biotechnology",
    "SAVA": "Biotechnology", "TPST": "Biotechnology",
    "DNLI": "Biotechnology", "FOLD": "Biotechnology",
    "MIST": "Biotechnology", "RCKT": "Biotechnology",
    "RYTM": "Biotechnology", "CRVS": "Biotechnology",
    "HUMA": "Biotechnology", "INAB": "Biotechnology",
    "ZLAB": "Biotechnology", "NRIX": "Biotechnology",
    "VSTM": "Biotechnology", "ATAI": "Biotechnology",
    "CLDX": "Biotechnology", "BCYC": "Biotechnology",
    "XNCR": "Biotechnology", "SANA": "Biotechnology",
    "TGTX": "Biotechnology", "TNXP": "Biotechnology",
    "PCVX": "Biotechnology", "IMVT": "Biotechnology",
    "BHVN": "Biotechnology", "VRCA": "Biotechnology",
    "IDYA": "Biotechnology", "STRO": "Biotechnology",
    "ALLO": "Biotechnology", "ERAS": "Biotechnology",
    "FATE": "Biotechnology", "ITRM": "Biotechnology",
    "CRBU": "Biotechnology", "REPL": "Biotechnology",
    "ARRY": "Biotechnology", "KYMR": "Biotechnology",
    "IBRX": "Biotechnology", "ANNX": "Biotechnology",
    "KLTR": "Biotechnology", "CTKB": "Biotechnology",
    # Drug Manufacturers
    "MRK": "Drug Manufacturers", "ABBV": "Drug Manufacturers",
    "ADMA": "Drug Manufacturers", "AMRX": "Drug Manufacturers",
    "CPRX": "Drug Manufacturers", "NRXS": "Drug Manufacturers",
    "PDSB": "Drug Manufacturers",
    # Medical Devices / Diagnostics
    "ABT": "Medical Devices", "MYGN": "Medical Devices",
    "SENS": "Medical Devices", "CODX": "Medical Devices",
    "HALO": "Medical Devices", "BNGO": "Medical Devices",
    # Semiconductors
    "NVDA": "Semiconductors", "AMD": "Semiconductors",
    "INTC": "Semiconductors", "QCOM": "Semiconductors",
    "AVGO": "Semiconductors", "TXN": "Semiconductors",
    "MU": "Semiconductors", "LRCX": "Semiconductors",
    "COHR": "Semiconductors", "SMCI": "Semiconductors",
    "IONQ": "Semiconductors", "RGTI": "Semiconductors",
    "QUBT": "Semiconductors", "QBTS": "Semiconductors",
    # Software — Application
    "SST": "Software—Application", "BBAI": "Software—Application",
    "SOUN": "Software—Application", "CXAI": "Software—Application",
    "GFAI": "Software—Application", "AIOT": "Software—Application",
    "AIXI": "Software—Application", "AITX": "Software—Application",
    # Software — Infrastructure
    "OS": "Software—Infrastructure", "MSFT": "Software—Infrastructure",
    # Cybersecurity
    "GEN": "Cybersecurity", "RDWR": "Cybersecurity",
    # Aerospace & Defense
    "LUNR": "Aerospace & Defense", "RKLB": "Aerospace & Defense",
    "MNTS": "Aerospace & Defense", "VORB": "Aerospace & Defense",
    "ASTRA": "Aerospace & Defense", "EVTL": "Aerospace & Defense",
    # Oil & Gas E&P
    "APA": "Oil & Gas E&P", "DVN": "Oil & Gas E&P",
    "COP": "Oil & Gas E&P", "XOM": "Oil & Gas E&P",
    "CVX": "Oil & Gas E&P", "EOG": "Oil & Gas E&P",
    "SLB": "Oil & Gas E&P", "PXD": "Oil & Gas E&P",
    "WRD": "Oil & Gas E&P",
    # Uranium
    "UEC": "Uranium", "NXE": "Uranium",
    # Gold / Silver
    "AGI": "Gold", "BVN": "Gold", "HMY": "Gold",
    # Crypto Mining
    "MARA": "Crypto Mining", "RIOT": "Crypto Mining",
    "CLSK": "Crypto Mining", "HUT": "Crypto Mining",
    "BITF": "Crypto Mining", "WULF": "Crypto Mining",
    "BTBT": "Crypto Mining", "CIFR": "Crypto Mining",
    "IREN": "Crypto Mining", "GREE": "Crypto Mining",
    # Electric Vehicles
    "NKLA": "Electric Vehicles", "FFIE": "Electric Vehicles",
    "GOEV": "Electric Vehicles", "MULN": "Electric Vehicles",
    "RIVN": "Electric Vehicles", "LCID": "Electric Vehicles",
    "SOLO": "Electric Vehicles", "BLNK": "Electric Vehicles",
    "EVGO": "Electric Vehicles", "CHPT": "Electric Vehicles",
    "AYRO": "Electric Vehicles", "IDEX": "Electric Vehicles",
    # EV Charging
    "BLNK": "EV Charging", "EVGO": "EV Charging", "CHPT": "EV Charging",
    # Space / Satellite
    "ASTS": "Satellite", "SATL": "Satellite",
    "GSAT": "Satellite", "VSAT": "Satellite", "SPIR": "Satellite",
    # Leisure
    "PTON": "Leisure Products",
    # Banks—Regional
    "RF": "Banks—Regional", "CFFN": "Banks—Regional",
    "HFWA": "Banks—Regional", "EFSC": "Banks—Regional",
    # Fintech
    "SOFI": "Fintech", "HOOD": "Fintech",
    # Cannabis
    "SNDL": "Cannabis", "TLRY": "Cannabis",
    "CGC": "Cannabis", "ACB": "Cannabis",
    "CRON": "Cannabis", "HEXO": "Cannabis",
}

# Industries with strongest sympathy move correlation
SYMPATHY_INDUSTRIES: dict[str, str] = {
    "Biotechnology":        "STRONG",
    "Drug Manufacturers":   "STRONG",
    "Gold":                 "STRONG",
    "Silver":               "STRONG",
    "Oil & Gas E&P":        "STRONG",
    "Uranium":              "STRONG",
    "Solar":                "STRONG",
    "Semiconductors":       "STRONG",
    "Crypto Mining":        "STRONG",
    "Electric Vehicles":    "STRONG",
    "Cannabis":             "STRONG",
    "Aerospace & Defense":  "MEDIUM",
    "Cybersecurity":        "MEDIUM",
    "Steel":                "MEDIUM",
    "Copper":               "MEDIUM",
    "Satellite":            "MEDIUM",
    "EV Charging":          "MEDIUM",
    "Banks—Regional":       "WEAK",
    "Software—Application": "WEAK",
    "Insurance":            "WEAK",
    "Fintech":              "WEAK",
    "Medical Devices":      "WEAK",
}


# ── Non-stock securities ──────────────────────────────────────────────────────
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
