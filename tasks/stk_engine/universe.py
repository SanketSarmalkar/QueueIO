"""Built-in stock universes.

The NASDAQ-100 constituents drift over time (names get added/removed each
year). This is a reasonable recent snapshot; override with ``--symbols`` or a
file if you want an exact, up-to-date set.
"""

from __future__ import annotations

# Index proxy used for relative-strength calculations.
NASDAQ_INDEX = "^IXIC"  # NASDAQ Composite (also try QQQ for the NDX ETF)

NASDAQ_100: list[str] = [
    "AAPL", "ABNB", "ADBE", "ADI", "ADP", "ADSK", "AEP", "AMAT", "AMD", "AMGN",
    "AMZN", "ANSS", "APP", "ARM", "ASML", "AVGO", "AZN", "BKNG", "BKR", "CCEP",
    "CDNS", "CDW", "CEG", "CHTR", "CMCSA", "COST", "CPRT", "CRWD", "CSCO", "CSGP",
    "CSX", "CTAS", "CTSH", "DASH", "DDOG", "DXCM", "EA", "EXC", "FANG", "FAST",
    "FTNT", "GEHC", "GFS", "GILD", "GOOG", "GOOGL", "HON", "IDXX", "INTC", "INTU",
    "ISRG", "KDP", "KHC", "KLAC", "LIN", "LRCX", "LULU", "MAR", "MCHP", "MDLZ",
    "MELI", "META", "MNST", "MRVL", "MSFT", "MSTR", "MU", "NFLX", "NVDA", "NXPI",
    "ODFL", "ON", "ORLY", "PANW", "PAYX", "PCAR", "PDD", "PEP", "PLTR", "PYPL",
    "QCOM", "REGN", "ROP", "ROST", "SBUX", "SNPS", "TEAM", "TMUS", "TSLA", "TTD",
    "TTWO", "TXN", "VRSK", "VRTX", "WBD", "WDAY", "XEL", "ZS",
]


def get_universe(name: str) -> list[str]:
    """Return a named universe. Currently only ``nasdaq100``."""
    key = name.lower().replace("-", "").replace("_", "")
    if key in ("nasdaq100", "ndx", "nasdaq"):
        return list(NASDAQ_100)
    raise ValueError(f"unknown universe: {name!r}")
