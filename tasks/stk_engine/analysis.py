"""Turn raw history + fundamentals into a decision scorecard.

The score is intentionally transparent: four pillars (Trend, Momentum, Value,
Risk) each on 0-100, blended with fixed weights into an overall 0-100 and a
Bullish / Neutral / Bearish label. Value and Risk use *cross-sectional*
percentile ranks within the analysed set — "cheap/safe versus its peers" — which
is more meaningful than absolute thresholds for a tech-heavy index.

None of this predicts the future. It summarises each stock's current technical
and valuation posture so you can compare like-for-like and dig in from there.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from . import indicators as ind
from .history import History

# Pillar weights for a position / long-term posture (must sum to 1.0).
WEIGHTS = {"trend": 0.30, "momentum": 0.25, "value": 0.20, "risk": 0.25}


@dataclass
class Analysis:
    symbol: str
    name: str | None = None
    currency: str | None = None
    price: float | None = None

    # returns (%)
    ret_1m: float | None = None
    ret_3m: float | None = None
    ret_6m: float | None = None
    ret_1y: float | None = None

    # trend
    sma50: float | None = None
    sma200: float | None = None
    above_sma50: bool | None = None
    above_sma200: bool | None = None
    golden_cross: bool | None = None

    # momentum
    rsi: float | None = None
    macd_hist: float | None = None
    rel_str_6m: float | None = None  # stock 6m return minus index 6m return

    # risk
    volatility: float | None = None  # annualized %
    atr_pct: float | None = None
    max_dd: float | None = None  # 1y max drawdown %
    dist_from_high: float | None = None  # % below 52w high (<=0)

    # fundamentals
    sector: str | None = None
    market_cap: float | None = None
    trailing_pe: float | None = None
    forward_pe: float | None = None
    price_to_book: float | None = None

    # pillar scores (0-100) + overall
    trend_score: float | None = None
    momentum_score: float | None = None
    value_score: float | None = None
    risk_score: float | None = None
    overall: float | None = None
    signal: str = "N/A"

    error: str | None = None


def _percentile_rank(value: float | None, sorted_vals: list[float], ascending: bool) -> float | None:
    """Return the 0-100 percentile of ``value`` within ``sorted_vals``.

    ``ascending=True`` means *smaller is better* (e.g. P/E, volatility): the
    smallest value scores 100.
    """
    if value is None or not sorted_vals:
        return None
    below = sum(1 for v in sorted_vals if v < value)
    equal = sum(1 for v in sorted_vals if v == value)
    # midrank percentile
    pct = (below + equal / 2.0) / len(sorted_vals) * 100.0
    return 100.0 - pct if ascending else pct


def _compute_raw(hist: History, index_returns: dict[str, float | None], funda: dict) -> Analysis:
    a = Analysis(symbol=hist.symbol, name=hist.name, currency=hist.currency)
    c, h, l = hist.closes, hist.highs, hist.lows
    a.price = c[-1]

    a.ret_1m = ind.pct_return(c, ind.TRADING_DAYS["1m"])
    a.ret_3m = ind.pct_return(c, ind.TRADING_DAYS["3m"])
    a.ret_6m = ind.pct_return(c, ind.TRADING_DAYS["6m"])
    a.ret_1y = ind.pct_return(c, ind.TRADING_DAYS["1y"])

    a.sma50 = ind.sma(c, 50)
    a.sma200 = ind.sma(c, 200)
    if a.sma50 is not None:
        a.above_sma50 = a.price > a.sma50
    if a.sma200 is not None:
        a.above_sma200 = a.price > a.sma200
    if a.sma50 is not None and a.sma200 is not None:
        a.golden_cross = a.sma50 > a.sma200

    a.rsi = ind.rsi(c, 14)
    m = ind.macd(c)
    if m is not None:
        a.macd_hist = m[2]

    if a.ret_6m is not None and index_returns.get("6m") is not None:
        a.rel_str_6m = a.ret_6m - index_returns["6m"]

    a.volatility = ind.annualized_volatility(c, 63)
    atr_abs = ind.atr(h, l, c, 14)
    if atr_abs is not None and a.price:
        a.atr_pct = atr_abs / a.price * 100.0
    a.max_dd = ind.max_drawdown(c, ind.TRADING_DAYS["1y"])

    high52 = hist.fifty_two_high or max(c[-min(len(c), 252):])
    if high52:
        a.dist_from_high = (a.price / high52 - 1.0) * 100.0

    a.name = funda.get("name") or hist.name
    a.sector = funda.get("sector")
    a.market_cap = funda.get("marketCap")
    a.trailing_pe = funda.get("trailingPE")
    a.forward_pe = funda.get("forwardPE")
    a.price_to_book = funda.get("priceToBook")
    return a


def _score_trend(a: Analysis) -> float:
    s = 0.0
    if a.above_sma200:
        s += 35
    if a.above_sma50:
        s += 25
    if a.golden_cross:
        s += 20
    if a.ret_6m is not None and a.ret_6m > 0:
        s += 10
    if a.ret_1y is not None and a.ret_1y > 0:
        s += 10
    return min(s, 100.0)


def _score_momentum(a: Analysis, rel_rank: float | None) -> float:
    s = 0.0
    # RSI: reward healthy uptrend (50-70), penalise overbought/oversold extremes.
    if a.rsi is not None:
        if 50 <= a.rsi <= 70:
            s += 30
        elif 40 <= a.rsi < 50 or 70 < a.rsi <= 80:
            s += 18
        elif a.rsi < 30:
            s += 8  # oversold — possible bounce but weak trend
        else:
            s += 5
    if a.macd_hist is not None and a.macd_hist > 0:
        s += 25
    if a.ret_3m is not None and a.ret_3m > 0:
        s += 15
    if rel_rank is not None:  # relative strength percentile within the set
        s += rel_rank * 0.30
    return min(s, 100.0)


def _label(overall: float | None) -> str:
    if overall is None:
        return "N/A"
    if overall >= 65:
        return "Bullish"
    if overall >= 45:
        return "Neutral"
    return "Bearish"


def analyse_universe(
    symbols: list[str],
    *,
    history_fn,
    fundamentals_fn=None,
    index_fn=None,
    with_fundamentals: bool = True,
    workers: int = 6,
    timeout: float = 12.0,
    progress=None,
) -> list[Analysis]:
    """Fetch, compute, and cross-sectionally score every symbol.

    Data access is injected so the engine is source-agnostic and testable:
      * ``history_fn(symbol, timeout=...)``  -> History
      * ``index_fn()``                        -> History | None (relative strength)
      * ``fundamentals_fn(price_by_symbol)``  -> {symbol: {marketCap, trailingPE, ...}}
    ``progress`` is an optional callable ``(done, total)`` for UI feedback.
    """
    # 1) Index history for relative strength.
    index_returns: dict[str, float | None] = {"6m": None}
    if index_fn is not None:
        idx = index_fn()
        if idx is not None and idx.ok:
            index_returns["6m"] = ind.pct_return(idx.closes, ind.TRADING_DAYS["6m"])

    # 2) Per-symbol history, concurrently (prices are needed before fundamentals).
    total = len(symbols)
    done = 0
    histories: dict[str, History] = {}

    def fetch_one(sym: str):
        return sym, history_fn(sym, timeout=timeout)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        for sym, hist in pool.map(fetch_one, symbols):
            histories[sym] = hist
            done += 1
            if progress:
                progress(done, total)

    # 3) Fundamentals, keyed by symbol (needs latest price for trailing P/E).
    price_by_symbol = {s: (h.closes[-1] if h.ok else None) for s, h in histories.items()}
    funda: dict = {}
    if with_fundamentals and fundamentals_fn is not None:
        if progress:
            progress(total, total)  # histories done; fundamentals starting
        funda = fundamentals_fn(price_by_symbol) or {}

    # 4) Compute raw metrics.
    raws: list[Analysis] = []
    for sym in symbols:
        hist = histories.get(sym)
        if hist is None or not hist.ok:
            raws.append(Analysis(symbol=sym, error=(hist.error if hist else "no data")))
            continue
        raws.append(_compute_raw(hist, index_returns, funda.get(sym, {})))

    good = [a for a in raws if a.error is None]

    # 4) Cross-sectional distributions for percentile scoring.
    pe_vals = sorted(a.forward_pe or a.trailing_pe for a in good if (a.forward_pe or a.trailing_pe) and (a.forward_pe or a.trailing_pe) > 0)
    pb_vals = sorted(a.price_to_book for a in good if a.price_to_book and a.price_to_book > 0)
    vol_vals = sorted(a.volatility for a in good if a.volatility is not None)
    dd_vals = sorted(a.max_dd for a in good if a.max_dd is not None)
    rel_vals = sorted(a.rel_str_6m for a in good if a.rel_str_6m is not None)

    for a in good:
        # Value: cheaper vs peers = higher. Blend forward/trailing P/E with P/B.
        pe = a.forward_pe or a.trailing_pe
        pe_rank = _percentile_rank(pe if (pe and pe > 0) else None, pe_vals, ascending=True)
        pb_rank = _percentile_rank(a.price_to_book if (a.price_to_book and a.price_to_book > 0) else None, pb_vals, ascending=True)
        value_parts = [r for r in (pe_rank, pb_rank) if r is not None]
        a.value_score = sum(value_parts) / len(value_parts) if value_parts else None

        # Risk: lower volatility + shallower drawdown vs peers = safer = higher.
        vol_rank = _percentile_rank(a.volatility, vol_vals, ascending=True)
        dd_rank = _percentile_rank(a.max_dd, dd_vals, ascending=False)  # less negative is better
        risk_parts = [r for r in (vol_rank, dd_rank) if r is not None]
        a.risk_score = sum(risk_parts) / len(risk_parts) if risk_parts else None

        rel_rank = _percentile_rank(a.rel_str_6m, rel_vals, ascending=False)
        a.trend_score = _score_trend(a)
        a.momentum_score = _score_momentum(a, rel_rank)

        # Overall: weighted blend, renormalising over whichever pillars exist.
        pillars = {
            "trend": a.trend_score,
            "momentum": a.momentum_score,
            "value": a.value_score,
            "risk": a.risk_score,
        }
        num, den = 0.0, 0.0
        for k, v in pillars.items():
            if v is not None:
                num += v * WEIGHTS[k]
                den += WEIGHTS[k]
        a.overall = num / den if den else None
        a.signal = _label(a.overall)

    # Sort best-first; errored rows go last.
    raws.sort(key=lambda a: (a.overall is None, -(a.overall or 0)))
    return raws
