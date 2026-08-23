"""NASDAQ.com data source (no API key).

Yahoo Finance frequently rate-limits (429) shared/flagged IPs, so for US stocks
we use NASDAQ's own public API, which is reliable and needs no key. It requires
browser-ish Origin/Referer headers.

Endpoints used (all under https://api.nasdaq.com):
  /api/quote/{sym}/historical   daily OHLCV (~2y)
  /api/quote/{sym}/summary      MarketCap, Sector, Yield, 52w range
  /api/quote/{sym}/eps          quarterly EPS -> trailing-twelve-month P/E
"""

from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta

import requests

from .history import History

_BASE = "https://api.nasdaq.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Origin": "https://www.nasdaq.com",
    "Referer": "https://www.nasdaq.com/",
}

_session: requests.Session | None = None
_lock = threading.Lock()


def _get_session() -> requests.Session:
    global _session
    if _session is None:
        with _lock:
            if _session is None:
                s = requests.Session()
                s.headers.update(_HEADERS)
                _session = s
    return _session


def _get(path: str, params: dict, *, timeout: float, retries: int = 3):
    """GET JSON with backoff on 429/5xx. Returns ``(payload, error)``."""
    sess = _get_session()
    last = "unknown error"
    for attempt in range(retries):
        try:
            r = sess.get(f"{_BASE}{path}", params=params, timeout=timeout)
        except requests.RequestException as exc:
            last = f"network: {exc}"
            continue
        if r.status_code in (429, 500, 502, 503, 504):
            last = f"http {r.status_code} (rate-limited/busy)"
            if attempt < retries - 1:
                time.sleep(min(0.8 * (2**attempt), 5.0))
            continue
        try:
            r.raise_for_status()
            return r.json(), None
        except requests.RequestException:
            return None, f"http {r.status_code}"
        except ValueError as exc:
            return None, f"bad json: {exc}"
    return None, last


# --------------------------------------------------------------------------- #
# parsing helpers
# --------------------------------------------------------------------------- #
def _num(s) -> float | None:
    if s is None:
        return None
    t = str(s).strip().replace("$", "").replace(",", "").replace("%", "")
    if t in ("", "N/A", "--", "NA"):
        return None
    try:
        return float(t)
    except ValueError:
        return None


_NAME_SUFFIXES = (
    " New York Registry Shares", " American Depositary Shares",
    " Class A Common Stock", " Class B Common Stock", " Class C Capital Stock",
    " Class A Ordinary Shares", " Ordinary Shares", " Depositary Shares",
    " Common Shares", " Common Stock",
)


def _clean_name(raw: str | None) -> str | None:
    """Trim NASDAQ's boilerplate (e.g. 'Apple Inc. Common Stock' -> 'Apple Inc.')."""
    if not raw:
        return None
    name = raw.strip()
    for suf in _NAME_SUFFIXES:
        if name.endswith(suf):
            name = name[: -len(suf)].strip()
            break
    return name or None


def fetch_name(symbol: str, *, timeout: float = 12.0) -> str | None:
    """Company name via the info endpoint. Best-effort; returns None on failure."""
    payload, err = _get(f"/api/quote/{symbol.upper()}/info", {"assetclass": "stocks"}, timeout=timeout)
    if err or not payload:
        return None
    return _clean_name(((payload.get("data") or {}).get("companyName")))


def _rows_to_history(symbol: str, rows: list[dict], *, currency="USD", name=None) -> History:
    # NASDAQ returns newest-first; we want oldest-first.
    closes, highs, lows, vols = [], [], [], []
    for r in reversed(rows):
        c = _num(r.get("close"))
        if c is None:
            continue
        closes.append(c)
        highs.append(_num(r.get("high")) or c)
        lows.append(_num(r.get("low")) or c)
        vols.append(_num(r.get("volume")) or 0.0)
    if len(closes) < 2:
        return History(symbol=symbol, error="insufficient history")
    return History(
        symbol=symbol, closes=closes, highs=highs, lows=lows, volumes=vols,
        currency=currency, name=name,
        fifty_two_high=max(closes[-252:]) if len(closes) >= 1 else None,
        fifty_two_low=min(closes[-252:]) if len(closes) >= 1 else None,
    )


# --------------------------------------------------------------------------- #
# public fetchers
# --------------------------------------------------------------------------- #
def fetch_history(symbol: str, *, years: int = 2, timeout: float = 12.0, assetclass: str = "stocks") -> History:
    """Daily OHLCV for the last ``years`` years. Never raises."""
    today = date.today()
    frm = today - timedelta(days=int(years * 365.25) + 5)
    payload, err = _get(
        f"/api/quote/{symbol.upper()}/historical",
        {"assetclass": assetclass, "fromdate": frm.isoformat(),
         "todate": today.isoformat(), "limit": 9999},
        timeout=timeout,
    )
    if err:
        return History(symbol=symbol, error=err)
    data = (payload or {}).get("data") or {}
    table = (data.get("tradesTable") or {})
    rows = table.get("rows") if isinstance(table, dict) else None
    if not rows:
        # NASDAQ returns data=None for unknown symbols / non-US listings.
        return History(symbol=symbol, error="no data (unknown/non-US symbol?)")
    return _rows_to_history(symbol.upper(), rows)


def fetch_index_history(*, timeout: float = 12.0) -> History:
    """NASDAQ Composite (COMP) history for relative-strength baselines."""
    return fetch_history("COMP", timeout=timeout, assetclass="index")


def _ttm_pe(symbol: str, price: float | None, *, timeout: float) -> float | None:
    """Trailing P/E = price / sum(last 4 reported quarterly EPS)."""
    if not price:
        return None
    payload, err = _get(f"/api/quote/{symbol.upper()}/eps", {"assetclass": "stocks"}, timeout=timeout)
    if err or not payload:
        return None
    eps = ((payload.get("data") or {}).get("earningsPerShare")) or []
    reported = [_num(e.get("earnings")) for e in eps if e.get("type") == "PreviousQuarter"]
    reported = [x for x in reported if x is not None and x != 0.0]
    if len(reported) < 4:
        return None
    ttm = sum(reported[-4:])
    return price / ttm if ttm > 0 else None


def fetch_fundamentals_one(symbol: str, price: float | None, *, timeout: float = 12.0) -> dict:
    """Summary (MarketCap/Sector/Yield) + trailing P/E for one symbol."""
    out: dict = {"name": None, "marketCap": None, "sector": None, "trailingPE": None,
                 "forwardPE": None, "priceToBook": None, "dividendYield": None}
    out["name"] = fetch_name(symbol, timeout=timeout)
    payload, err = _get(f"/api/quote/{symbol.upper()}/summary", {"assetclass": "stocks"}, timeout=timeout)
    if not err and payload:
        sd = (payload.get("data") or {}).get("summaryData") or {}

        def val(key):
            v = sd.get(key)
            return v.get("value") if isinstance(v, dict) else None

        out["marketCap"] = _num(val("MarketCap"))
        out["sector"] = val("Sector")
        out["dividendYield"] = _num(val("Yield"))
    out["trailingPE"] = _ttm_pe(symbol, price, timeout=timeout)
    return out


def fetch_fundamentals(price_by_symbol: dict[str, float | None], *, timeout: float = 12.0, workers: int = 6) -> dict[str, dict]:
    """Concurrently fetch fundamentals for many symbols."""
    syms = list(price_by_symbol)
    if not syms:
        return {}
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        results = pool.map(
            lambda s: (s, fetch_fundamentals_one(s, price_by_symbol.get(s), timeout=timeout)),
            syms,
        )
        return {s: d for s, d in results}
