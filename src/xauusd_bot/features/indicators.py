"""Causal technical indicators over a canonical candle series.

Every indicator here is STRICTLY CAUSAL: the value emitted at row ``i`` uses
only candles ``0..i``. Warm-up positions that lack enough history are returned
as ``None`` (never ``0``) so downstream code cannot accidentally train on
lookahead-contaminated or fabricated values.

The functions accept the canonical schema (``list[dict]`` with keys
``timestamp/open/high/low/close/volume``; see :mod:`xauusd_bot.data`) and return
plain ``list`` series aligned 1:1 with the input rows. Numeric work is delegated
to :mod:`xauusd_bot.compat`, which already provides a pure-stdlib fallback and
transparently uses numpy/pandas when available (via the ``HAS_*`` flags).
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

from .. import compat

Candle = Dict[str, object]
Series = List[Optional[float]]


# ---------------------------------------------------------------------------
# Column extraction helpers
# ---------------------------------------------------------------------------
def _col(rows: Sequence[Candle], key: str) -> List[Optional[float]]:
    """Extract one OHLCV column as a list of floats (None-safe)."""
    out: List[Optional[float]] = []
    for r in rows:
        v = r.get(key) if isinstance(r, dict) else None
        try:
            out.append(None if v is None else float(v))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            out.append(None)
    return out


def closes(rows: Sequence[Candle]) -> List[Optional[float]]:
    """Close prices."""
    return _col(rows, "close")


def highs(rows: Sequence[Candle]) -> List[Optional[float]]:
    """High prices."""
    return _col(rows, "high")


def lows(rows: Sequence[Candle]) -> List[Optional[float]]:
    """Low prices."""
    return _col(rows, "low")


def opens(rows: Sequence[Candle]) -> List[Optional[float]]:
    """Open prices."""
    return _col(rows, "open")


# ---------------------------------------------------------------------------
# Returns & volatility
# ---------------------------------------------------------------------------
def simple_returns(rows: Sequence[Candle], periods: int = 1) -> Series:
    """Simple return ``close_t / close_{t-periods} - 1``. Causal."""
    return compat.pct_change(closes(rows), periods=periods)


def log_returns(rows: Sequence[Candle], periods: int = 1) -> Series:
    """Log return ``ln(close_t / close_{t-periods})``. Causal.

    The first ``periods`` positions are ``None`` (no history).
    """
    c = closes(rows)
    n = len(c)
    out: Series = [None] * n
    for i in range(periods, n):
        a, b = c[i], c[i - periods]
        if a is None or b is None or a <= 0 or b <= 0:
            out[i] = None
        else:
            out[i] = math.log(a / b)
    return out


def rolling_volatility(rows: Sequence[Candle], window: int = 20) -> Series:
    """Rolling std of simple returns over a trailing ``window``. Causal."""
    rets = simple_returns(rows, periods=1)
    return compat.rolling_std(rets, window=window, ddof=1)


# ---------------------------------------------------------------------------
# Moving averages
# ---------------------------------------------------------------------------
def sma(rows_or_series, window: int) -> Series:
    """Simple moving average. Accepts candle rows or a raw numeric series."""
    series = _as_series(rows_or_series)
    return compat.rolling_mean(series, window=window)


def ema(rows_or_series, span: int) -> Series:
    """Exponential moving average (EMA) with the standard non-adjusted recursion.

    Causal: seeded from the first valid observation, then updated one step at a
    time. Leading ``None`` positions remain ``None``.
    """
    series = _as_series(rows_or_series)
    return compat.ewm(series, span=span, adjust=False)


def _as_series(rows_or_series) -> List[Optional[float]]:
    """Normalise input to a numeric series.

    If given candle rows (list of dict) use the close column; if given a numeric
    list, use it directly.
    """
    if rows_or_series and isinstance(rows_or_series[0], dict):
        return closes(rows_or_series)
    return [None if v is None else float(v) for v in rows_or_series]


# ---------------------------------------------------------------------------
# RSI (Wilder's smoothing)
# ---------------------------------------------------------------------------
def rsi(rows: Sequence[Candle], window: int = 14) -> Series:
    """Relative Strength Index using Wilder's smoothing. Causal.

    The first valid RSI value appears at index ``window`` (needs ``window``
    deltas). Values are in ``[0, 100]``; ``None`` during warm-up.
    """
    c = closes(rows)
    n = len(c)
    out: Series = [None] * n
    if n < window + 1 or window <= 0:
        return out

    gains: List[float] = [0.0] * n
    losses: List[float] = [0.0] * n
    for i in range(1, n):
        if c[i] is None or c[i - 1] is None:
            gains[i] = 0.0
            losses[i] = 0.0
            continue
        delta = c[i] - c[i - 1]
        gains[i] = delta if delta > 0 else 0.0
        losses[i] = -delta if delta < 0 else 0.0

    # Seed with the simple average of the first `window` deltas (indices 1..window).
    avg_gain = math.fsum(gains[1 : window + 1]) / window
    avg_loss = math.fsum(losses[1 : window + 1]) / window
    out[window] = _rsi_from_averages(avg_gain, avg_loss)

    for i in range(window + 1, n):
        avg_gain = (avg_gain * (window - 1) + gains[i]) / window
        avg_loss = (avg_loss * (window - 1) + losses[i]) / window
        out[i] = _rsi_from_averages(avg_gain, avg_loss)
    return out


def _rsi_from_averages(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


# ---------------------------------------------------------------------------
# MACD
# ---------------------------------------------------------------------------
def macd(
    rows: Sequence[Candle],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Dict[str, Series]:
    """MACD line, signal line, and histogram. Causal.

    Returns a dict with keys ``macd``, ``signal``, ``hist``. The MACD line is
    ``EMA(fast) - EMA(slow)``; the signal is ``EMA(signal)`` of the MACD line;
    the histogram is ``macd - signal``.
    """
    c = closes(rows)
    ema_fast = compat.ewm(c, span=fast, adjust=False)
    ema_slow = compat.ewm(c, span=slow, adjust=False)
    macd_line = compat.vsub(ema_fast, ema_slow)
    # Signal EMA is only meaningful once the slow EMA has warmed up; mask the
    # macd line before the slow span so the signal EMA does not seed early.
    masked = list(macd_line)
    for i in range(min(slow - 1, len(masked))):
        masked[i] = None
    signal_line = compat.ewm(masked, span=signal, adjust=False)
    hist = compat.vsub(masked, signal_line)
    return {"macd": masked, "signal": signal_line, "hist": hist}


# ---------------------------------------------------------------------------
# True range / ATR
# ---------------------------------------------------------------------------
def true_range(rows: Sequence[Candle]) -> Series:
    """True Range per bar. Causal. First bar is ``None`` (needs prior close)."""
    h = highs(rows)
    low = lows(rows)
    c = closes(rows)
    n = len(rows)
    out: Series = [None] * n
    for i in range(n):
        if h[i] is None or low[i] is None:
            out[i] = None
            continue
        if i == 0 or c[i - 1] is None:
            out[i] = h[i] - low[i]
        else:
            prev_close = c[i - 1]
            out[i] = max(
                h[i] - low[i],
                abs(h[i] - prev_close),
                abs(low[i] - prev_close),
            )
    return out


def atr(rows: Sequence[Candle], window: int = 14) -> Series:
    """Average True Range using Wilder's smoothing. Causal.

    First value appears at index ``window`` (needs ``window`` true ranges that
    themselves start at index 1). ``None`` during warm-up.
    """
    tr = true_range(rows)
    n = len(tr)
    out: Series = [None] * n
    if n < window + 1 or window <= 0:
        return out
    # Wilder seed: simple mean of TR over indices 1..window.
    chunk = tr[1 : window + 1]
    if any(x is None for x in chunk):
        # Fall back to a plain rolling mean if the seed window has gaps.
        return compat.rolling_mean(tr, window=window)
    prev = math.fsum(chunk) / window
    out[window] = prev
    for i in range(window + 1, n):
        if tr[i] is None:
            out[i] = prev
            continue
        prev = (prev * (window - 1) + tr[i]) / window
        out[i] = prev
    return out


# ---------------------------------------------------------------------------
# Bollinger bands
# ---------------------------------------------------------------------------
def bollinger_bands(
    rows: Sequence[Candle], window: int = 20, num_std: float = 2.0
) -> Dict[str, Series]:
    """Bollinger Bands. Causal.

    Returns ``mid`` (SMA), ``upper``, ``lower``, ``pctb`` (%B), and ``bandwidth``.
    %B is ``(close - lower) / (upper - lower)``; bandwidth is
    ``(upper - lower) / mid``. ``None`` during warm-up.
    """
    c = closes(rows)
    mid = compat.rolling_mean(c, window=window)
    std = compat.rolling_std(c, window=window, ddof=0)
    n = len(c)
    upper: Series = [None] * n
    lower: Series = [None] * n
    pctb: Series = [None] * n
    bandwidth: Series = [None] * n
    for i in range(n):
        if mid[i] is None or std[i] is None:
            continue
        up = mid[i] + num_std * std[i]
        lo = mid[i] - num_std * std[i]
        upper[i] = up
        lower[i] = lo
        rng = up - lo
        if rng != 0 and c[i] is not None:
            pctb[i] = (c[i] - lo) / rng
        if mid[i] != 0:
            bandwidth[i] = rng / mid[i]
    return {
        "mid": mid,
        "upper": upper,
        "lower": lower,
        "pctb": pctb,
        "bandwidth": bandwidth,
    }


# ---------------------------------------------------------------------------
# Rolling high/low channels (Donchian-style)
# ---------------------------------------------------------------------------
def rolling_high(rows: Sequence[Candle], window: int = 20) -> Series:
    """Rolling max of highs over a trailing ``window``. Causal."""
    return compat.rolling_max(highs(rows), window=window)


def rolling_low(rows: Sequence[Candle], window: int = 20) -> Series:
    """Rolling min of lows over a trailing ``window``. Causal."""
    return compat.rolling_min(lows(rows), window=window)


def channel_position(rows: Sequence[Candle], window: int = 20) -> Series:
    """Where close sits in the rolling high/low channel, in ``[0, 1]``. Causal.

    ``(close - rolling_low) / (rolling_high - rolling_low)``. ``None`` when the
    channel is degenerate or during warm-up.
    """
    c = closes(rows)
    hi = rolling_high(rows, window=window)
    lo = rolling_low(rows, window=window)
    n = len(c)
    out: Series = [None] * n
    for i in range(n):
        if c[i] is None or hi[i] is None or lo[i] is None:
            continue
        rng = hi[i] - lo[i]
        if rng > 0:
            out[i] = (c[i] - lo[i]) / rng
    return out
