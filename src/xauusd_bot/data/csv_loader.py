"""OHLCV CSV loading and cleaning.

``load_candles(path)`` reads an OHLCV CSV and returns the canonical schema (see
:mod:`xauusd_bot.data`). It uses pandas when available for speed, otherwise the
stdlib :mod:`csv` module. Either way it:

* maps column names case-insensitively to time/open/high/low/close/volume,
* parses timestamps to ISO-8601 strings,
* sorts strictly ascending by time (never shuffles),
* drops duplicate timestamps (keeping the first occurrence),
* validates ``high >= low`` and non-negative OHLC / volume,
* returns ``list[dict]`` records.
"""

from __future__ import annotations

import csv as _csv
from datetime import datetime
from typing import Dict, List, Optional

from . import CANONICAL_FIELDS

Candle = Dict[str, object]

# Case-insensitive aliases mapping input headers to canonical field names.
_COLUMN_ALIASES = {
    "timestamp": "timestamp",
    "time": "timestamp",
    "date": "timestamp",
    "datetime": "timestamp",
    "ts": "timestamp",
    "open": "open",
    "o": "open",
    "high": "high",
    "h": "high",
    "low": "low",
    "l": "low",
    "close": "close",
    "c": "close",
    "adj close": "close",
    "volume": "volume",
    "vol": "volume",
    "v": "volume",
    "tickvol": "volume",
    "tick_volume": "volume",
}

# Timestamp formats tried in order before giving up.
_TS_FORMATS = (
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%d/%m/%Y",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y",
)


def _normalize_header(name: str) -> Optional[str]:
    """Map a raw CSV header to its canonical field, or None if unrecognized."""
    key = (name or "").strip().lower()
    return _COLUMN_ALIASES.get(key)


def _parse_timestamp(raw: object) -> str:
    """Parse a timestamp value into a normalized ISO-8601 string.

    Accepts ISO strings, common datetime formats, and epoch seconds. The output
    is a lexicographically sortable ISO string so plain string sort == time sort.
    """
    if raw is None:
        raise ValueError("missing timestamp")
    s = str(raw).strip()
    if not s:
        raise ValueError("empty timestamp")

    # Epoch seconds (or ms) given as a bare number.
    try:
        num = float(s)
        # Treat very large values as milliseconds.
        if num > 1e12:
            num /= 1000.0
        return datetime.utcfromtimestamp(num).isoformat()
    except (ValueError, OverflowError, OSError):
        pass

    # ISO-8601 directly.
    try:
        return datetime.fromisoformat(s).isoformat()
    except ValueError:
        pass

    for fmt in _TS_FORMATS:
        try:
            return datetime.strptime(s, fmt).isoformat()
        except ValueError:
            continue
    raise ValueError(f"unrecognized timestamp format: {s!r}")


def _to_float(raw: object, field: str) -> float:
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        raise ValueError(f"non-numeric {field} value: {raw!r}")


def _records_from_stdlib(path: str) -> List[Dict[str, object]]:
    with open(path, "r", newline="", encoding="utf-8") as fh:
        reader = _csv.DictReader(fh)
        if reader.fieldnames is None:
            return []
        header_map = {h: _normalize_header(h) for h in reader.fieldnames}
        rows: List[Dict[str, object]] = []
        for raw_row in reader:
            mapped: Dict[str, object] = {}
            for original, value in raw_row.items():
                canonical = header_map.get(original)
                if canonical is not None:
                    mapped[canonical] = value
            rows.append(mapped)
        return rows


def _records_from_pandas(path: str) -> Optional[List[Dict[str, object]]]:
    try:
        import pandas as pd  # type: ignore
    except Exception:
        return None
    df = pd.read_csv(path)
    rename = {}
    for col in df.columns:
        canonical = _normalize_header(str(col))
        if canonical is not None:
            rename[col] = canonical
    df = df.rename(columns=rename)
    keep = [c for c in CANONICAL_FIELDS if c in df.columns]
    df = df[keep]
    return df.to_dict("records")


def load_candles(path: str) -> List[Candle]:
    """Load and clean an OHLCV CSV at ``path`` into the canonical schema.

    Raises
    ------
    FileNotFoundError
        If ``path`` does not exist.
    ValueError
        If required columns are missing or a row violates OHLC invariants.
    """
    raw_rows = _records_from_pandas(path)
    if raw_rows is None:
        raw_rows = _records_from_stdlib(path)

    cleaned: List[Candle] = []
    seen_ts = set()
    for row in raw_rows:
        if "timestamp" not in row:
            raise ValueError("CSV is missing a time/timestamp column")
        missing = [f for f in ("open", "high", "low", "close") if f not in row]
        if missing:
            raise ValueError(f"CSV is missing required column(s): {missing}")

        ts = _parse_timestamp(row["timestamp"])
        o = _to_float(row["open"], "open")
        h = _to_float(row["high"], "high")
        lo = _to_float(row["low"], "low")
        c = _to_float(row["close"], "close")
        v = _to_float(row.get("volume", 0.0), "volume") if row.get("volume") not in (None, "") else 0.0

        # Validate invariants.
        if h < lo:
            raise ValueError(f"high < low at {ts}: high={h} low={lo}")
        if min(o, h, lo, c) < 0 or v < 0:
            raise ValueError(f"negative value at {ts}")
        if not (lo <= o <= h and lo <= c <= h):
            # Tolerate tiny float noise but reject genuine inconsistencies.
            raise ValueError(f"open/close outside [low, high] at {ts}")

        if ts in seen_ts:
            continue  # drop duplicate timestamp (keep first)
        seen_ts.add(ts)

        cleaned.append(
            {
                "timestamp": ts,
                "open": o,
                "high": h,
                "low": lo,
                "close": c,
                "volume": v,
            }
        )

    # Strict ascending sort by timestamp (ISO strings sort chronologically).
    cleaned.sort(key=lambda r: r["timestamp"])
    return cleaned
