"""Technical indicators, pure-Python (no numpy needed).

All functions take plain lists of floats (oldest first) and return either a
single latest value or a full series. They return ``None`` when there isn't
enough data rather than raising, so callers can degrade gracefully.

Formulas follow the standard/Wilder definitions used by most charting tools.
"""

from __future__ import annotations

import math

TRADING_DAYS = {"1m": 21, "3m": 63, "6m": 126, "1y": 252}


def sma(values: list[float], period: int) -> float | None:
    if len(values) < period or period <= 0:
        return None
    return sum(values[-period:]) / period


def ema_series(values: list[float], period: int) -> list[float] | None:
    """EMA series seeded with the SMA of the first ``period`` values."""
    if len(values) < period or period <= 0:
        return None
    k = 2 / (period + 1)
    seed = sum(values[:period]) / period
    out = [seed]
    for v in values[period:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes: list[float], period: int = 14) -> float | None:
    """Wilder's RSI. Needs > ``period`` closes."""
    if len(closes) < period + 1:
        return None
    gains, losses = 0.0, 0.0
    # Seed with the simple average of the first `period` changes.
    for i in range(1, period + 1):
        delta = closes[i] - closes[i - 1]
        gains += max(delta, 0.0)
        losses += max(-delta, 0.0)
    avg_gain, avg_loss = gains / period, losses / period
    # Wilder smoothing over the remainder.
    for i in range(period + 1, len(closes)):
        delta = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(delta, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-delta, 0.0)) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def macd(
    closes: list[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[float, float, float] | None:
    """Return ``(macd_line, signal_line, histogram)`` latest values."""
    fast_e = ema_series(closes, fast)
    slow_e = ema_series(closes, slow)
    if fast_e is None or slow_e is None:
        return None
    # Align tails (slow EMA is shorter because it starts later).
    n = min(len(fast_e), len(slow_e))
    macd_line = [fast_e[-n + i] - slow_e[-n + i] for i in range(n)]
    sig = ema_series(macd_line, signal)
    if sig is None:
        return None
    macd_v = macd_line[-1]
    signal_v = sig[-1]
    return macd_v, signal_v, macd_v - signal_v


def atr(
    highs: list[float], lows: list[float], closes: list[float], period: int = 14
) -> float | None:
    """Wilder's Average True Range (absolute, same units as price)."""
    n = len(closes)
    if n < period + 1 or len(highs) != n or len(lows) != n:
        return None
    trs = []
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    if len(trs) < period:
        return None
    atr_v = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr_v = (atr_v * (period - 1) + tr) / period
    return atr_v


def pct_return(closes: list[float], lookback_days: int) -> float | None:
    """Percent return over ``lookback_days`` trading days."""
    if len(closes) <= lookback_days:
        return None
    past = closes[-lookback_days - 1]
    if not past:
        return None
    return (closes[-1] / past - 1.0) * 100.0


def annualized_volatility(closes: list[float], window: int = 63) -> float | None:
    """Annualized volatility (%) from daily log returns over the last ``window``."""
    if len(closes) < window + 1:
        return None
    rets = []
    for i in range(len(closes) - window, len(closes)):
        prev = closes[i - 1]
        if prev > 0 and closes[i] > 0:
            rets.append(math.log(closes[i] / prev))
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var) * math.sqrt(252) * 100.0


def max_drawdown(closes: list[float], lookback_days: int = 252) -> float | None:
    """Worst peak-to-trough decline (%) over the window (negative number)."""
    series = closes[-lookback_days:] if len(closes) > lookback_days else closes
    if len(series) < 2:
        return None
    peak = series[0]
    mdd = 0.0
    for p in series:
        peak = max(peak, p)
        if peak > 0:
            mdd = min(mdd, p / peak - 1.0)
    return mdd * 100.0
