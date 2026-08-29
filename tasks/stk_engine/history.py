"""Historical OHLCV and batch fundamentals from Yahoo Finance."""

from __future__ import annotations

from dataclasses import dataclass, field

from .net import get_crumb, get_json


@dataclass
class History:
    """Daily OHLCV series (oldest first) plus lightweight metadata."""

    symbol: str
    closes: list[float] = field(default_factory=list)
    highs: list[float] = field(default_factory=list)
    lows: list[float] = field(default_factory=list)
    volumes: list[float] = field(default_factory=list)
    currency: str | None = None
    name: str | None = None
    fifty_two_high: float | None = None
    fifty_two_low: float | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None and len(self.closes) > 1


def fetch_history(
    symbol: str, *, rng: str = "2y", interval: str = "1d", timeout: float = 12.0
) -> History:
    """Fetch daily history. Never raises — failures land on ``History.error``."""
    payload, err = get_json(
        f"/v8/finance/chart/{symbol}",
        params={"range": rng, "interval": interval, "includePrePost": "false"},
        timeout=timeout,
    )
    if err:
        return History(symbol=symbol, error=err)

    chart = (payload or {}).get("chart") or {}
    if chart.get("error"):
        e = chart["error"]
        return History(symbol=symbol, error=(e.get("description") if isinstance(e, dict) else str(e)))
    results = chart.get("result") or []
    if not results:
        return History(symbol=symbol, error="no data (unknown symbol?)")

    res = results[0]
    meta = res.get("meta") or {}
    quote = ((res.get("indicators") or {}).get("quote") or [{}])[0]

    def clean(seq):
        return [float(x) for x in (seq or []) if x is not None]

    closes = clean(quote.get("close"))
    highs = clean(quote.get("high"))
    lows = clean(quote.get("low"))
    volumes = clean(quote.get("volume"))

    if len(closes) < 2:
        return History(symbol=symbol, error="insufficient history")

    return History(
        symbol=meta.get("symbol") or symbol,
        closes=closes,
        highs=highs if len(highs) == len(closes) else closes,
        lows=lows if len(lows) == len(closes) else closes,
        volumes=volumes,
        currency=meta.get("currency"),
        name=meta.get("longName") or meta.get("shortName"),
        fifty_two_high=meta.get("fiftyTwoWeekHigh"),
        fifty_two_low=meta.get("fiftyTwoWeekLow"),
        error=None,
    )


def fetch_fundamentals(symbols: list[str], *, timeout: float = 12.0) -> dict[str, dict]:
    """Batch-fetch valuation fundamentals via the v7 quote endpoint.

    Returns ``{symbol: {marketCap, trailingPE, forwardPE, priceToBook, ...}}``.
    Best-effort: needs a crumb; on failure returns an empty dict so callers just
    treat fundamentals as unavailable.
    """
    crumb = get_crumb(timeout=timeout)
    if not crumb or not symbols:
        return {}

    out: dict[str, dict] = {}
    # Chunk to keep URLs short and reduce per-request load.
    for i in range(0, len(symbols), 20):
        chunk = symbols[i : i + 20]
        payload, err = get_json(
            "/v7/finance/quote",
            params={"symbols": ",".join(chunk), "crumb": crumb},
            timeout=timeout,
        )
        if err or not payload:
            continue
        for item in (payload.get("quoteResponse") or {}).get("result") or []:
            sym = item.get("symbol")
            if not sym:
                continue
            out[sym] = {
                "marketCap": item.get("marketCap"),
                "trailingPE": item.get("trailingPE"),
                "forwardPE": item.get("forwardPE"),
                "priceToBook": item.get("priceToBook"),
                "epsTrailing": item.get("epsTrailingTwelveMonths"),
                "dividendYield": item.get("trailingAnnualDividendYield"),
                "avgVol3M": item.get("averageDailyVolume3Month"),
            }
    return out
