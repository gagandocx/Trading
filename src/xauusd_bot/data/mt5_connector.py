"""Optional MetaTrader 5 (MT5) candle fetcher.

=============================================================================
 PLUG IN YOUR OWN BROKER HERE.
 This module is a thin, optional adapter for pulling live/historical candles
 from a MetaTrader 5 terminal. It is intentionally inert until you install the
 `MetaTrader5` package and run on a machine with an MT5 terminal + broker
 account. Importing this module NEVER requires MetaTrader5 to be installed.
=============================================================================

The `MetaTrader5` package is Windows-only and is imported LAZILY inside the
functions below. If it is unavailable, a clear, informative error is raised only
when you actually call a connector function, so the rest of the pipeline (and
plain `import xauusd_bot`) works everywhere with zero third-party packages.

Setup on your machine
----------------------
1. Install the MetaTrader 5 terminal from your broker and log into an account.
2. `pip install MetaTrader5` (Windows; see requirements.txt).
3. Ensure "Allow automated trading" / API access is enabled in the terminal.
4. Call :func:`fetch_candles` with your symbol / timeframe / date range.

All returned data follows the canonical schema (see :mod:`xauusd_bot.data`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional

from . import CANONICAL_FIELDS

Candle = Dict[str, object]

_INSTALL_HINT = (
    "The 'MetaTrader5' package is not available in this environment. "
    "The MT5 connector is optional: install it with `pip install MetaTrader5` "
    "on a Windows machine running the MetaTrader 5 terminal, then retry. "
    "For offline work use xauusd_bot.data.sample_data or a CSV via "
    "xauusd_bot.data.csv_loader instead."
)


def _import_mt5():
    """Lazily import the MetaTrader5 package, raising a clear error if absent."""
    try:
        import MetaTrader5 as mt5  # type: ignore
    except Exception as exc:  # ImportError or platform-specific load error
        raise RuntimeError(_INSTALL_HINT) from exc
    return mt5


def is_available() -> bool:
    """Return True if the MetaTrader5 package can be imported, else False.

    Never raises; safe to call for capability probing.
    """
    try:
        import MetaTrader5  # type: ignore  # noqa: F401

        return True
    except Exception:
        return False


# Map our timeframe labels to MT5 enum attribute names. Resolved lazily so we do
# not reference the MT5 package at import time.
_TIMEFRAME_ATTR = {
    "M1": "TIMEFRAME_M1",
    "M5": "TIMEFRAME_M5",
    "M15": "TIMEFRAME_M15",
    "M30": "TIMEFRAME_M30",
    "H1": "TIMEFRAME_H1",
    "H4": "TIMEFRAME_H4",
    "D1": "TIMEFRAME_D1",
}


def _resolve_timeframe(mt5, timeframe: str):
    attr = _TIMEFRAME_ATTR.get(str(timeframe).upper())
    if attr is None or not hasattr(mt5, attr):
        raise ValueError(f"unsupported MT5 timeframe: {timeframe!r}")
    return getattr(mt5, attr)


def _coerce_dt(value) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


# Approximate number of bars per calendar day for each timeframe, used only to
# size the count-based fallback (copy_rates_from / _from_pos) when the ranged
# fetch returns nothing. Deliberately generous (treats the market as 24h) so we
# over-request rather than under-request; the result is still filtered to the
# requested [start, end] window afterwards.
_BARS_PER_DAY = {
    "M1": 24 * 60,
    "M5": 24 * 12,
    "M15": 24 * 4,
    "M30": 24 * 2,
    "H1": 24,
    "H4": 6,
    "D1": 1,
}

# Upper bound on bars requested via the fallback so a huge/open-ended window
# cannot ask MT5 for an unbounded amount. ~400k comfortably covers a year of M1
# (~525k calendar-minute bars, far fewer when the market is closed on weekends).
_MAX_FALLBACK_BARS = 400_000


def _approx_bar_count(timeframe: str, start_dt: datetime, end_dt: datetime) -> int:
    """Estimate how many bars span [start_dt, end_dt] for ``timeframe``.

    Used only to size the count-based fallback. Returns at least a small floor so
    the fallback always requests something, and is capped at ``_MAX_FALLBACK_BARS``.
    """
    per_day = _BARS_PER_DAY.get(str(timeframe).upper(), 24 * 12)
    span_days = max(1.0, (end_dt - start_dt).total_seconds() / 86400.0)
    # Pad by 20% to be safe against gaps / partial first bar.
    count = int(span_days * per_day * 1.2) + 10
    return max(10, min(count, _MAX_FALLBACK_BARS))


def fetch_candles(
    symbol: str = "XAUUSD",
    timeframe: str = "M15",
    start: Optional[object] = None,
    end: Optional[object] = None,
    *,
    login: Optional[int] = None,
    password: Optional[str] = None,
    server: Optional[str] = None,
) -> List[Candle]:
    """Fetch candles for ``symbol`` between ``start`` and ``end`` from MT5.

    Parameters
    ----------
    symbol:
        Broker symbol, e.g. ``"XAUUSD"`` (exact name is broker-specific).
    timeframe:
        One of M1/M5/M15/M30/H1/H4/D1.
    start, end:
        ``datetime`` or ISO-8601 strings bounding the request (inclusive start).
    login, password, server:
        Optional explicit MT5 account credentials. If omitted, the already
        running / logged-in terminal session is used.

    Returns
    -------
    list of dict
        Candles in canonical schema, strictly time-sorted ascending.

    Raises
    ------
    RuntimeError
        If MetaTrader5 is not installed, initialization fails, or the request
        returns no data. Importing this module does not raise.
    """
    mt5 = _import_mt5()

    init_kwargs = {}
    if login is not None:
        init_kwargs["login"] = int(login)
    if password is not None:
        init_kwargs["password"] = password
    if server is not None:
        init_kwargs["server"] = server

    if not mt5.initialize(**init_kwargs):
        err = mt5.last_error() if hasattr(mt5, "last_error") else "unknown error"
        raise RuntimeError(f"MT5 initialize() failed: {err}")

    try:
        tf = _resolve_timeframe(mt5, timeframe)
        start_dt = _coerce_dt(start) if start is not None else datetime(1970, 1, 1)
        end_dt = _coerce_dt(end) if end is not None else datetime.utcnow()

        # --- validate / enable the symbol -----------------------------------
        # Fusion Markets (and many brokers) only serve history for a symbol that
        # is present in Market Watch. If symbol_info() is None the name does not
        # exist for this account at all -> fail loudly with guidance. Otherwise
        # make sure it is selected/visible so copy_rates_* has data to return.
        info = mt5.symbol_info(symbol) if hasattr(mt5, "symbol_info") else True
        if info is None:
            last = mt5.last_error() if hasattr(mt5, "last_error") else "unknown error"
            raise RuntimeError(
                f"MT5 symbol_info({symbol!r}) returned None: the symbol was not "
                "found for this account. The symbol name must match your MT5 "
                "Market Watch EXACTLY (case sensitive). Some brokers add a "
                "suffix (e.g. 'XAUUSD.m', 'XAUUSD-ECN'); check the Market Watch "
                f"window and pass that exact name. last_error={last!r}"
            )
        if hasattr(mt5, "symbol_select"):
            # Guarded: enabling the symbol is best-effort; copy_rates may still
            # work even if this returns False on some builds.
            try:
                mt5.symbol_select(symbol, True)
            except Exception:
                pass

        # --- primary fetch: ranged -----------------------------------------
        rates = mt5.copy_rates_range(symbol, tf, start_dt, end_dt)

        # --- fallback: count-based -----------------------------------------
        # A full year of M5 (~75k bars) or M1 (~370k bars) is often not yet
        # downloaded into the terminal, in which case copy_rates_range returns
        # None/empty. Fall back to pulling a bar COUNT (from the end, then from
        # the newest position) and filter back to [start, end] below.
        if rates is None or len(rates) == 0:
            count = _approx_bar_count(timeframe, start_dt, end_dt)
            if hasattr(mt5, "copy_rates_from"):
                rates = mt5.copy_rates_from(symbol, tf, end_dt, count)
            if (rates is None or len(rates) == 0) and hasattr(mt5, "copy_rates_from_pos"):
                rates = mt5.copy_rates_from_pos(symbol, tf, 0, count)
    finally:
        mt5.shutdown()

    if rates is None or len(rates) == 0:
        last = mt5.last_error() if hasattr(mt5, "last_error") else "unknown error"
        raise RuntimeError(
            f"MT5 returned no data for symbol={symbol!r} timeframe={timeframe!r}. "
            "Check the symbol name matches Market Watch exactly, that the "
            "terminal is open and logged in, and that the requested history has "
            f"been downloaded (scroll the chart back to force a download). "
            f"last_error={last!r}"
        )

    # Lower/upper epoch bounds for filtering the count-based fallback back into
    # the requested window. (The ranged fetch is already bounded by MT5.) We use
    # calendar.timegm so the naive start/end datetimes are interpreted on the
    # SAME clock as datetime.utcfromtimestamp(ts) below, i.e. the raw MT5 epoch
    # seconds, without applying the host machine's local timezone offset.
    import calendar

    start_epoch = calendar.timegm(start_dt.timetuple())
    end_epoch = calendar.timegm(end_dt.timetuple())

    candles: List[Candle] = []
    for r in rates:
        # MT5 rates are numpy structured records / tuples with named fields.
        ts = int(r["time"]) if _has_field(r, "time") else int(r[0])
        o = float(r["open"]) if _has_field(r, "open") else float(r[1])
        h = float(r["high"]) if _has_field(r, "high") else float(r[2])
        lo = float(r["low"]) if _has_field(r, "low") else float(r[3])
        c = float(r["close"]) if _has_field(r, "close") else float(r[4])
        vol_field = "tick_volume" if _has_field(r, "tick_volume") else None
        # Spot gold has no exchange-traded volume, so MT5 reports tick_volume
        # (number of price updates). We keep that as our 'volume'.
        v = float(r[vol_field]) if vol_field else 0.0

        # Filter the count-based fallback back into the requested window. The
        # ranged fetch is already bounded by MT5, so this is a no-op there.
        if ts < start_epoch or ts > end_epoch:
            continue

        # NOTE on timestamps: MT5 reports `time` as seconds since epoch in the
        # TERMINAL/BROKER SERVER timezone (Fusion Markets' server is typically
        # UTC+2/UTC+3 with DST), NOT necessarily UTC. We format it with
        # utcfromtimestamp to get a stable ISO string but DO NOT shift it, so
        # the timestamps reflect broker-server time. This is fine for a first
        # real run; be aware it matters for killzone/session-of-day features,
        # which are defined relative to the broker clock here.
        candles.append(
            {
                "timestamp": datetime.utcfromtimestamp(ts).isoformat(),
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "volume": v,
            }
        )

    if not candles:
        raise RuntimeError(
            f"MT5 returned rows for symbol={symbol!r} timeframe={timeframe!r} but "
            "none fell inside the requested [start, end] window after filtering. "
            "Widen the date range or check that history for that period exists."
        )

    candles.sort(key=lambda x: x["timestamp"])
    return candles


def _has_field(record, name: str) -> bool:
    """True if a numpy structured record exposes the named field."""
    dtype = getattr(record, "dtype", None)
    names = getattr(dtype, "names", None)
    return bool(names) and name in names


__all__ = ["fetch_candles", "is_available", "CANONICAL_FIELDS"]
