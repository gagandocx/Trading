"""Pure-stdlib numeric helpers backing the indicator / feature code.

This module provides deterministic rolling and exponential-weighted operations
over ``list[float]`` using only the Python standard library. When numpy / pandas
are installed the higher-level modules may take a faster vectorized path, but the
functions here are always available and are the single source of truth for the
fallback path.

Conventions
-----------
* Series are plain ``list`` of ``float`` (or ``None`` for missing values).
* Leading positions that do not have enough history to compute a value are
  filled with ``None`` (the logical "NaN"). This is critical to avoid lookahead
  bias: a window of length ``w`` first produces a value at index ``w - 1``.
* All functions are pure and deterministic; they never read future values beyond
  the position being computed (except ``diff``/``pct_change`` which look back one
  step, which is the standard definition).
"""

from __future__ import annotations

import math
from typing import List, Optional, Sequence

# ---------------------------------------------------------------------------
# Optional-dependency capability flags. Detected once at import time via
# try/except so the rest of the codebase can branch on availability without
# repeating the guard. Importing this module NEVER requires these packages.
# ---------------------------------------------------------------------------
try:  # pragma: no cover - depends on environment
    import numpy as _np  # noqa: F401

    HAS_NUMPY = True
except Exception:  # pragma: no cover
    HAS_NUMPY = False

try:  # pragma: no cover - depends on environment
    import pandas as _pd  # noqa: F401

    HAS_PANDAS = True
except Exception:  # pragma: no cover
    HAS_PANDAS = False


Number = Optional[float]


def _to_float(x: Number) -> Optional[float]:
    """Coerce a value to float, mapping ``None`` and NaN to ``None``."""
    if x is None:
        return None
    try:
        f = float(x)
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        return None
    return f


def rolling_mean(values: Sequence[Number], window: int) -> List[Optional[float]]:
    """Simple moving average over a trailing ``window``.

    Positions with fewer than ``window`` valid observations are ``None``.
    A window that contains any ``None`` yields ``None`` for that position.
    """
    if window <= 0:
        raise ValueError("window must be positive")
    vals = [_to_float(v) for v in values]
    n = len(vals)
    out: List[Optional[float]] = [None] * n
    for i in range(window - 1, n):
        chunk = vals[i - window + 1 : i + 1]
        if any(c is None for c in chunk):
            out[i] = None
        else:
            out[i] = math.fsum(chunk) / window  # type: ignore[arg-type]
    return out


def rolling_std(
    values: Sequence[Number], window: int, ddof: int = 1
) -> List[Optional[float]]:
    """Rolling standard deviation over a trailing ``window``.

    ``ddof`` is the delta degrees of freedom (1 == sample std, 0 == population).
    """
    if window <= 0:
        raise ValueError("window must be positive")
    if window - ddof <= 0:
        # Not enough degrees of freedom to compute a std for this window.
        return [None] * len(list(values))
    vals = [_to_float(v) for v in values]
    n = len(vals)
    out: List[Optional[float]] = [None] * n
    for i in range(window - 1, n):
        chunk = vals[i - window + 1 : i + 1]
        if any(c is None for c in chunk):
            out[i] = None
            continue
        mean = math.fsum(chunk) / window  # type: ignore[arg-type]
        var = math.fsum((c - mean) ** 2 for c in chunk) / (window - ddof)
        out[i] = math.sqrt(var)
    return out


def ewm(
    values: Sequence[Number],
    span: Optional[int] = None,
    alpha: Optional[float] = None,
    adjust: bool = False,
) -> List[Optional[float]]:
    """Exponentially weighted moving average.

    Provide either ``span`` (``alpha = 2 / (span + 1)``) or ``alpha`` directly.
    When ``adjust`` is False (default, matching the common EMA used by RSI/MACD)
    the recursion is ``y_t = alpha * x_t + (1 - alpha) * y_{t-1}`` seeded with the
    first valid observation. Leading ``None`` values stay ``None``.
    """
    if alpha is None:
        if span is None:
            raise ValueError("provide either span or alpha")
        if span < 1:
            raise ValueError("span must be >= 1")
        alpha = 2.0 / (span + 1.0)
    if not (0.0 < alpha <= 1.0):
        raise ValueError("alpha must be in (0, 1]")

    vals = [_to_float(v) for v in values]
    n = len(vals)
    out: List[Optional[float]] = [None] * n

    if adjust:
        num = 0.0
        den = 0.0
        started = False
        for i in range(n):
            x = vals[i]
            if x is None:
                out[i] = out[i - 1] if (i > 0 and started) else None
                continue
            num = x + (1 - alpha) * num
            den = 1.0 + (1 - alpha) * den
            out[i] = num / den
            started = True
        return out

    prev: Optional[float] = None
    for i in range(n):
        x = vals[i]
        if x is None:
            out[i] = prev
            continue
        if prev is None:
            prev = x
        else:
            prev = alpha * x + (1 - alpha) * prev
        out[i] = prev
    return out


def diff(values: Sequence[Number], periods: int = 1) -> List[Optional[float]]:
    """First difference ``x_t - x_{t-periods}``. First ``periods`` are ``None``."""
    if periods <= 0:
        raise ValueError("periods must be positive")
    vals = [_to_float(v) for v in values]
    n = len(vals)
    out: List[Optional[float]] = [None] * n
    for i in range(periods, n):
        a, b = vals[i], vals[i - periods]
        out[i] = None if (a is None or b is None) else a - b
    return out


def pct_change(values: Sequence[Number], periods: int = 1) -> List[Optional[float]]:
    """Relative change ``(x_t - x_{t-periods}) / x_{t-periods}``."""
    if periods <= 0:
        raise ValueError("periods must be positive")
    vals = [_to_float(v) for v in values]
    n = len(vals)
    out: List[Optional[float]] = [None] * n
    for i in range(periods, n):
        a, b = vals[i], vals[i - periods]
        if a is None or b is None or b == 0:
            out[i] = None
        else:
            out[i] = (a - b) / b
    return out


def rolling_max(values: Sequence[Number], window: int) -> List[Optional[float]]:
    """Rolling maximum over a trailing ``window``."""
    if window <= 0:
        raise ValueError("window must be positive")
    vals = [_to_float(v) for v in values]
    n = len(vals)
    out: List[Optional[float]] = [None] * n
    for i in range(window - 1, n):
        chunk = [c for c in vals[i - window + 1 : i + 1]]
        if any(c is None for c in chunk):
            out[i] = None
        else:
            out[i] = max(chunk)  # type: ignore[type-var]
    return out


def rolling_min(values: Sequence[Number], window: int) -> List[Optional[float]]:
    """Rolling minimum over a trailing ``window``."""
    if window <= 0:
        raise ValueError("window must be positive")
    vals = [_to_float(v) for v in values]
    n = len(vals)
    out: List[Optional[float]] = [None] * n
    for i in range(window - 1, n):
        chunk = [c for c in vals[i - window + 1 : i + 1]]
        if any(c is None for c in chunk):
            out[i] = None
        else:
            out[i] = min(chunk)  # type: ignore[type-var]
    return out


# ---------------------------------------------------------------------------
# Simple element-wise vector ops over list[float]. These tolerate ``None`` by
# propagating it (any None operand -> None result), mirroring NaN semantics.
# ---------------------------------------------------------------------------
def _binary(a: Sequence[Number], b: Sequence[Number], op) -> List[Optional[float]]:
    av = [_to_float(x) for x in a]
    bv = [_to_float(x) for x in b]
    if len(av) != len(bv):
        raise ValueError("vectors must have equal length")
    out: List[Optional[float]] = []
    for x, y in zip(av, bv):
        out.append(None if (x is None or y is None) else op(x, y))
    return out


def vadd(a: Sequence[Number], b: Sequence[Number]) -> List[Optional[float]]:
    """Element-wise addition."""
    return _binary(a, b, lambda x, y: x + y)


def vsub(a: Sequence[Number], b: Sequence[Number]) -> List[Optional[float]]:
    """Element-wise subtraction (``a - b``)."""
    return _binary(a, b, lambda x, y: x - y)


def vmul(a: Sequence[Number], b: Sequence[Number]) -> List[Optional[float]]:
    """Element-wise multiplication."""
    return _binary(a, b, lambda x, y: x * y)


def vdiv(a: Sequence[Number], b: Sequence[Number]) -> List[Optional[float]]:
    """Element-wise division (``a / b``); division by zero yields ``None``."""
    return _binary(a, b, lambda x, y: (x / y) if y != 0 else None)


def scalar_mul(a: Sequence[Number], k: float) -> List[Optional[float]]:
    """Multiply every element by scalar ``k``."""
    return [None if _to_float(x) is None else _to_float(x) * k for x in a]  # type: ignore[operator]


def clamp(x: float, lo: float, hi: float) -> float:
    """Clamp scalar ``x`` into ``[lo, hi]``."""
    return max(lo, min(hi, x))
