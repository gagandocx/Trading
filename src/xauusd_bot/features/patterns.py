"""Causal candlestick-pattern flags and body/wick geometry.

Each flag at row ``i`` uses only candles ``<= i`` (single-bar patterns use just
bar ``i``; two-bar patterns use ``i-1`` and ``i``). Warm-up rows that lack the
required prior bar are ``None``.

Pattern definitions (documented precisely so they are reproducible)
-------------------------------------------------------------------
Let for a bar: ``body = |close - open|``, ``range = high - low``,
``upper_wick = high - max(open, close)``, ``lower_wick = min(open, close) - low``.

* **doji**: ``body <= 0.1 * range`` (tiny body relative to range).
* **hammer / bullish pin bar**: ``lower_wick >= 2 * body`` and
  ``upper_wick <= body`` and ``body > 0`` (long lower wick, small upper wick).
* **shooting star**: ``upper_wick >= 2 * body`` and ``lower_wick <= body`` and
  ``body > 0`` (long upper wick, small lower wick).
* **bullish engulfing**: previous bar bearish (``close<open``), current bar
  bullish (``close>open``), and current body fully engulfs the previous body:
  ``close >= open_prev`` and ``open <= close_prev``.
* **bearish engulfing**: previous bar bullish, current bar bearish, and current
  body fully engulfs the previous body: ``open >= close_prev`` and
  ``close <= open_prev``.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

Candle = Dict[str, object]
Series = List[Optional[float]]
BoolSeries = List[Optional[bool]]

DOJI_BODY_RATIO = 0.1
WICK_BODY_MULT = 2.0


def _ohlc(row: Candle):
    try:
        return (
            float(row["open"]),  # type: ignore[index]
            float(row["high"]),  # type: ignore[index]
            float(row["low"]),  # type: ignore[index]
            float(row["close"]),  # type: ignore[index]
        )
    except (KeyError, TypeError, ValueError):
        return None


def _geometry(row: Candle):
    """Return (body, rng, upper_wick, lower_wick) or None."""
    vals = _ohlc(row)
    if vals is None:
        return None
    o, h, low, c = vals
    body = abs(c - o)
    rng = h - low
    upper = h - max(o, c)
    lower = min(o, c) - low
    return body, rng, upper, lower


def body_ratio(rows: Sequence[Candle]) -> Series:
    """Body as a fraction of the full candle range. Causal, single-bar."""
    out: Series = []
    for r in rows:
        g = _geometry(r)
        if g is None or g[1] <= 0:
            out.append(None)
        else:
            out.append(g[0] / g[1])
    return out


def upper_wick_ratio(rows: Sequence[Candle]) -> Series:
    """Upper wick as a fraction of range. Causal, single-bar."""
    out: Series = []
    for r in rows:
        g = _geometry(r)
        if g is None or g[1] <= 0:
            out.append(None)
        else:
            out.append(g[2] / g[1])
    return out


def lower_wick_ratio(rows: Sequence[Candle]) -> Series:
    """Lower wick as a fraction of range. Causal, single-bar."""
    out: Series = []
    for r in rows:
        g = _geometry(r)
        if g is None or g[1] <= 0:
            out.append(None)
        else:
            out.append(g[3] / g[1])
    return out


def candle_range(rows: Sequence[Candle]) -> Series:
    """High-low range per bar. Causal, single-bar."""
    out: Series = []
    for r in rows:
        g = _geometry(r)
        out.append(None if g is None else g[1])
    return out


def is_doji(rows: Sequence[Candle]) -> BoolSeries:
    """Tiny body relative to range. Causal, single-bar."""
    out: BoolSeries = []
    for r in rows:
        g = _geometry(r)
        if g is None or g[1] <= 0:
            out.append(None)
        else:
            out.append(g[0] <= DOJI_BODY_RATIO * g[1])
    return out


def is_hammer(rows: Sequence[Candle]) -> BoolSeries:
    """Hammer / bullish pin bar: long lower wick, small upper wick. Causal."""
    out: BoolSeries = []
    for r in rows:
        g = _geometry(r)
        if g is None:
            out.append(None)
            continue
        body, _rng, upper, lower = g
        out.append(body > 0 and lower >= WICK_BODY_MULT * body and upper <= body)
    return out


def is_shooting_star(rows: Sequence[Candle]) -> BoolSeries:
    """Shooting star: long upper wick, small lower wick. Causal, single-bar."""
    out: BoolSeries = []
    for r in rows:
        g = _geometry(r)
        if g is None:
            out.append(None)
            continue
        body, _rng, upper, lower = g
        out.append(body > 0 and upper >= WICK_BODY_MULT * body and lower <= body)
    return out


def is_bullish_engulfing(rows: Sequence[Candle]) -> BoolSeries:
    """Bullish engulfing (two-bar). Causal; first bar is None."""
    out: BoolSeries = [None]
    for i in range(1, len(rows)):
        prev = _ohlc(rows[i - 1])
        cur = _ohlc(rows[i])
        if prev is None or cur is None:
            out.append(None)
            continue
        po, _ph, _pl, pc = prev
        o, _h, _l, c = cur
        prev_bear = pc < po
        cur_bull = c > o
        engulf = c >= po and o <= pc
        out.append(prev_bear and cur_bull and engulf)
    return out


def is_bearish_engulfing(rows: Sequence[Candle]) -> BoolSeries:
    """Bearish engulfing (two-bar). Causal; first bar is None."""
    out: BoolSeries = [None]
    for i in range(1, len(rows)):
        prev = _ohlc(rows[i - 1])
        cur = _ohlc(rows[i])
        if prev is None or cur is None:
            out.append(None)
            continue
        po, _ph, _pl, pc = prev
        o, _h, _l, c = cur
        prev_bull = pc > po
        cur_bear = c < o
        engulf = o >= pc and c <= po
        out.append(prev_bull and cur_bear and engulf)
    return out


def all_patterns(rows: Sequence[Candle]) -> Dict[str, List[Optional[object]]]:
    """Compute every pattern flag + geometry ratio as a dict of aligned series."""
    return {
        "body_ratio": body_ratio(rows),
        "upper_wick_ratio": upper_wick_ratio(rows),
        "lower_wick_ratio": lower_wick_ratio(rows),
        "candle_range": candle_range(rows),
        "is_doji": is_doji(rows),
        "is_hammer": is_hammer(rows),
        "is_shooting_star": is_shooting_star(rows),
        "is_bullish_engulfing": is_bullish_engulfing(rows),
        "is_bearish_engulfing": is_bearish_engulfing(rows),
    }
