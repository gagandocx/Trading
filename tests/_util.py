"""Shared test helpers: ensure ``src`` is importable without PYTHONPATH set."""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if os.path.isdir(_SRC) and _SRC not in sys.path:
    sys.path.insert(0, _SRC)


def candle(ts, o, h, l, c, v=1000.0):
    """Build a canonical OHLCV candle dict."""
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": v}
