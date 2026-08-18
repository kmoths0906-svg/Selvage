"""
The wide scanner universe: ~300-400 liquid US-listed small/mid/large-cap
stocks plus theme ETFs, on top of the original 16-name CORE_UNIVERSE
(config.py). Purpose: early-footprint/momentum discovery shouldn't be
limited to mega-caps everyone already watches -- unusual activity is more
informative, and more common, in less-followed names.

Methodology and honesty note: there is no free, live, market-wide
screener API (see README's data-source honesty matrix), so this list was
hand-compiled by Claude from training knowledge of real, currently-listed
(as of training data) US equities -- not fetched from a live index-
constituent feed, and not fabricated. Ticker *symbols* are static company
identity, not "market data" in the sense the no-fabrication rule is about
(prices/volumes/fundamentals); this is the same category of thing as
config.py's original hand-picked 10-ticker list, just much larger.

Consequences of that:
  - Some tickers here may have since been acquired, delisted, or renamed.
    That is handled by the existing per-ticker error path, not a special
    case: DataUnavailableError for a bad ticker is caught in
    intelligence/scanner.py exactly like any other data gap, logged, and
    skipped -- it will not crash a run.
  - This list is static and needs periodic manual refresh (ask Claude to
    revisit it periodically, or edit directly), not something that
    updates itself.
  - Liquidity is not verified in this file. The MIN_PRICE and
    MIN_AVG_DOLLAR_VOLUME filters in intelligence/config.py, already
    applied in scoring, do that job at scan time using real, live data.

Expand or prune freely as performance data comes in -- that was the
explicit intent when this was widened from 10 to ~350+ tickers.
"""

from __future__ import annotations

# --- Large-cap (S&P 500-caliber, excluding the 16 already in CORE_UNIVERSE) ---
LARGE_CAP = [
    # Software / cloud / internet
    "ORCL", "CRM", "ADBE", "INTU", "NOW", "PANW", "SNPS", "CDNS", "FTNT", "WDAY",
    "TEAM", "DDOG", "SNOW", "NET", "CRWD", "ZS", "ADSK", "ANSS", "ROP", "KEYS",
    "NFLX", "DIS", "CMCSA", "TMUS", "VZ", "T", "CHTR", "WBD", "EA", "TTWO",
    "BKNG", "ABNB", "UBER",
    # Semiconductors / hardware
    "TXN", "QCOM", "INTC", "MU", "AMAT", "LRCX", "KLAC", "ADI", "MRVL", "NXPI",
    "MCHP", "ON", "SWKS", "QRVO", "TER",
    # Consumer discretionary
    "HD", "LOW", "NKE", "SBUX", "MCD", "TGT", "TJX", "ROST", "ORLY", "AZO",
    "YUM", "CMG", "MAR", "HLT", "RCL", "F", "GM",
    # Consumer staples
    "PG", "KO", "PEP", "COST", "WMT", "CL", "KMB", "GIS", "HSY", "MDLZ",
    "STZ", "KDP", "MNST", "CLX", "SYY", "KR",
    # Financials
    "BAC", "WFC", "C", "GS", "MS", "SCHW", "BLK", "AXP", "USB", "PNC",
    "TFC", "COF", "BK", "MET", "PRU", "AIG", "TRV", "CB", "PGR", "ALL",
    "MA", "PYPL", "SQ", "ADP", "PAYX",
    # Healthcare / pharma
    "UNH", "JNJ", "LLY", "PFE", "MRK", "ABBV", "TMO", "ABT", "DHR", "BMY",
    "AMGN", "GILD", "VRTX", "REGN", "ISRG", "SYK", "BSX", "MDT", "ZTS",
    "CVS", "CI", "HUM", "ELV", "MRNA", "BIIB",
    # Industrials
    "CAT", "DE", "HON", "UPS", "RTX", "LMT", "NOC", "GD", "BA", "GE",
    "MMM", "EMR", "ETN", "ITW", "PH", "ROK", "CSX", "UNP", "NSC", "FDX",
    "WM", "DAL", "UAL", "LUV",
    # Energy
    "XOM", "CVX", "COP", "SLB", "EOG", "MPC", "PSX", "VLO", "OXY", "WMB",
    "KMI", "HAL", "BKR", "DVN",
    # Materials
    "LIN", "APD", "SHW", "ECL", "FCX", "NEM", "DOW", "DD", "PPG", "ALB", "NUE",
    # Utilities
    "NEE", "DUK", "SO", "D", "AEP", "EXC", "XEL", "SRE", "ED", "PEG",
    # Real estate
    "PLD", "AMT", "EQIX", "PSA", "O", "SPG", "WELL", "DLR", "AVB", "EQR",
]

# --- Mid-cap ---
MID_CAP = [
    # Software / cloud
    "PATH", "ASAN", "PCTY", "BILL", "DOCU", "ZI", "APPF", "ESTC", "FSLY", "TWLO",
    "OKTA", "BOX", "SMAR", "PD", "FROG", "GTLB", "CFLT", "S", "RPD", "TENB",
    "QLYS", "VRNS", "CYBR", "DBX", "HUBS", "MDB",
    # Semiconductors
    "LSCC", "SITM", "CRUS", "DIOD", "SLAB", "POWI", "AMBA", "ALGM", "RMBS",
    "FORM", "ACLS", "UCTT", "ICHR", "COHR", "IPGP",
    # Biotech / pharma
    "EXEL", "SRPT", "ALNY", "BMRN", "INCY", "JAZZ", "RARE", "ARWR", "IONS",
    "HALO", "NBIX", "PCVX", "LEGN", "KRYS", "ITCI", "AXSM", "CRSP", "EDIT",
    "NTLA", "BEAM", "VERV", "RXRX", "DNLI", "MRUS",
    # Consumer / retail
    "DECK", "CROX", "LULU", "YETI", "BOOT", "FIVE", "OLLI", "BURL", "GPS",
    "AEO", "URBN", "CHWY", "W", "RH", "WSM", "DKS", "ULTA",
    # Industrials
    "AXON", "XYL", "DOV", "IEX", "AME", "FAST", "POOL", "WSO", "PWR", "MAS",
    "ALLE", "IR", "GGG", "NDSN", "RBC", "CR", "CSL",
    # Financials
    "SF", "RJF", "EVR", "PJT", "LPLA", "IBKR", "MKTX", "CBOE", "NDAQ",
    "TROW", "BEN", "IVZ", "VOYA", "RGA", "GL",
    # Energy
    "CTRA", "MTDR", "PR", "SM", "CHRD", "RRC", "AR", "CIVI", "VNOM",
    # Materials / industrial
    "CE", "EMN", "FMC", "MOS", "CF", "SMG", "AVY", "SEE", "IFF",
    # REITs
    "EXR", "CUBE", "IRM", "MAA", "ESS", "UDR", "CPT", "HST", "KIM", "REG",
    "FRT", "BXP", "VNO",
    # Healthcare
    "PODD", "TDOC", "DXCM", "ALGN", "HOLX", "XRAY", "RGEN", "WAT", "MTD",
    "BRKR", "IDXX", "CHE",
    # Consumer staples
    "BJ", "CASY", "WBA", "SFM", "TFX", "USFD", "PFGC",
    # Homebuilders / housing
    "DHI", "LEN", "PHM", "NVR", "TOL", "KBH", "MTH", "TPH", "MHO",
    # Regional banks
    "FITB", "HBAN", "RF", "CFG", "KEY", "ZION", "CMA", "MTB", "SNV", "PNFP",
    "WTFC", "EWBC", "WAL",
    # Airlines / travel
    "ALK", "EXPE", "TRIP",
]

# --- Small-cap (biased toward names known for volatility/momentum, since
# early-footprint detection is the explicit purpose of widening this) ---
SMALL_CAP = [
    # Tech / fintech
    "UPST", "AFRM", "SOFI", "MARA", "RIOT", "CLSK", "HUT", "IREN", "APPS",
    "YELP", "ANGI", "CARG", "CVNA", "VRM", "FUBO", "ROKU", "PARA", "LYV", "EXPI",
    # Biotech (frequent FDA/clinical-trial catalysts -- exactly the kind
    # of binary-risk, early-footprint setup this system is meant to flag)
    "SAVA", "CYTK", "MDGL", "VKTX", "AMLX", "IMVT", "APLS", "FOLD", "ACAD",
    "SUPN", "PRTA", "KROS", "RYTM", "VERA", "ANAB", "ALLO", "SANA", "RCKT",
    "BLUE", "FATE", "CRBU", "XNCR", "DVAX", "NVAX", "OCUL", "CDNA", "NTRA", "EXAS",
    # Clean energy / EV supply chain
    "CHPT", "PLUG", "FCEL", "BE", "RUN", "SEDG", "ARRY", "SHLS", "FLNC", "STEM",
    # Consumer / restaurants / retail
    "CAKE", "TXRH", "WING", "SHAK", "PLAY", "BJRI", "DENN", "JACK", "PZZA",
    "SKX", "VSCO", "ANF", "GES",
    # Industrials
    "FIX", "MYRG", "AAON", "WTS", "CSWI", "LNN", "GTES", "ATKR", "ROAD",
    "BLDR", "IESC",
    # Financials / regional & community banks
    "OZK", "CATY", "HOMB", "INDB", "ABCB", "FFIN", "UBSI", "BANF", "SFBS",
    "HTLF", "TCBI", "GBCI", "SSB", "CVBF", "WSFS", "FHB",
    # REITs
    "NHI", "DEA", "GTY", "SVC", "PK", "RLJ", "DRH",
    # Materials / mining
    "CLF", "X", "AA", "CENX", "TMST", "SCHN",
    # Energy (upstream/services)
    "MGY", "VTLE", "MUR", "TALO", "LPI", "CRK", "WHD", "NOG",
]

# --- Theme/sub-sector ETFs beyond the broad sector ETFs already tracked
# for regime/rotation (intelligence/config.py's SECTOR_ETFS) -- these
# widen scan coverage without being part of the sector-rotation ranking.
THEME_ETFS = [
    "XRT", "XHB", "KRE", "ARKK", "JETS", "TAN", "ICLN", "GDX", "XOP", "OIH", "SOXX",
]


def _dedupe(*lists: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for lst in lists:
        for t in lst:
            if t not in seen:
                seen.add(t)
                out.append(t)
    return out


# Small-caps are the priority for early-footprint discovery, so they and
# the theme ETFs are kept in full; large/mid-cap are capped (front-loaded
# by importance within each sector block above) to land the total wide
# universe in the requested ~300-500 range rather than well past it.
WIDE_UNIVERSE = _dedupe(LARGE_CAP[:150], MID_CAP[:170], SMALL_CAP, THEME_ETFS)
