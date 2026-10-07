"""Deterministic synthetic XAUUSD OHLCV generator.

Produces a seeded random walk with volatility clustering (a lightweight GARCH-ish
process) centred in a realistic spot-gold range (~1800-2400). The output follows
the canonical schema (see :mod:`xauusd_bot.data`) so it is a drop-in substitute
for real data when running the pipeline offline or in tests.

Pure stdlib only: uses ``random``, ``math``, ``csv``, ``datetime``.
"""

from __future__ import annotations

import csv
import math
import os
import random
from datetime import datetime, timedelta
from typing import Dict, List

from . import CANONICAL_FIELDS

Candle = Dict[str, object]

# Timeframe label -> minutes per bar, for timestamp spacing.
_TIMEFRAME_MINUTES = {
    "M1": 1,
    "M5": 5,
    "M15": 15,
    "M30": 30,
    "H1": 60,
    "H4": 240,
    "D1": 1440,
}


def generate_sample(
    n_rows: int = 300,
    seed: int = 7,
    start_price: float = 2000.0,
    start_time: str = "2023-01-02T00:00:00",
    timeframe: str = "M15",
) -> List[Candle]:
    """Generate ``n_rows`` synthetic XAUUSD candles.

    Parameters
    ----------
    n_rows:
        Number of candles to produce.
    seed:
        RNG seed for full reproducibility (same seed -> identical series).
    start_price:
        Opening price of the first candle (kept near realistic gold levels).
    start_time:
        ISO-8601 timestamp of the first candle.
    timeframe:
        Bar size label controlling timestamp spacing (default ``M15``).

    Returns
    -------
    list of dict
        Candles in canonical schema, strictly time-sorted ascending.
    """
    if n_rows <= 0:
        return []

    rng = random.Random(seed)
    minutes = _TIMEFRAME_MINUTES.get(timeframe.upper(), 15)
    t0 = datetime.fromisoformat(start_time)
    step = timedelta(minutes=minutes)

    # Volatility-clustering state (EWMA of squared returns -> conditional sigma).
    base_vol = 0.0025  # ~0.25% per bar baseline return volatility
    vol = base_vol
    vol_persistence = 0.94  # how strongly volatility clusters
    vol_reaction = 0.06  # sensitivity to the latest shock

    # Keep price inside a plausible gold band via a gentle mean-reversion pull.
    lower, upper = 1800.0, 2400.0
    mean_level = 2100.0
    reversion = 0.001  # strength of the pull toward mean_level

    candles: List[Candle] = []
    price = float(start_price)

    for i in range(n_rows):
        # Update conditional volatility (GARCH-like persistence + reaction).
        shock = rng.gauss(0.0, 1.0)
        vol = math.sqrt(
            vol_persistence * (vol ** 2)
            + vol_reaction * (base_vol ** 2) * (shock ** 2)
            + (1.0 - vol_persistence - vol_reaction) * (base_vol ** 2)
        )

        drift = reversion * (mean_level - price) / mean_level
        ret = drift + vol * rng.gauss(0.0, 1.0)

        open_px = price
        close_px = open_px * (1.0 + ret)

        # Intrabar range scaled by current volatility; ensure high>=max(o,c) etc.
        intrabar = abs(open_px) * vol * (0.5 + rng.random())
        hi_wick = intrabar * rng.random()
        lo_wick = intrabar * rng.random()
        high_px = max(open_px, close_px) + hi_wick
        low_px = min(open_px, close_px) - lo_wick

        # Keep prices positive and roughly inside the band.
        low_px = max(low_px, 1.0)
        if close_px < lower:
            close_px = lower + abs(ret) * close_px
        elif close_px > upper:
            close_px = upper - abs(ret) * close_px

        volume = round(500.0 + 4000.0 * (vol / base_vol) * rng.random(), 2)

        ts = (t0 + i * step).isoformat()
        candles.append(
            {
                "timestamp": ts,
                "open": round(open_px, 2),
                "high": round(high_px, 2),
                "low": round(low_px, 2),
                "close": round(close_px, 2),
                "volume": volume,
            }
        )
        price = close_px

    return candles


def write_sample_csv(
    path: str = "data/sample/XAUUSD_sample.csv",
    n_rows: int = 300,
    seed: int = 7,
    **kwargs,
) -> str:
    """Generate a sample series and write it to ``path`` as CSV.

    Creates parent directories as needed. Returns the written path.
    """
    candles = generate_sample(n_rows=n_rows, seed=seed, **kwargs)
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(CANONICAL_FIELDS))
        writer.writeheader()
        for c in candles:
            writer.writerow(c)
    return path


if __name__ == "__main__":  # pragma: no cover - convenience entry point
    import argparse

    parser = argparse.ArgumentParser(description="Generate synthetic XAUUSD OHLCV CSV")
    parser.add_argument("--out", default="data/sample/XAUUSD_sample.csv")
    parser.add_argument("--rows", type=int, default=300)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    out = write_sample_csv(args.out, n_rows=args.rows, seed=args.seed)
    print(f"wrote {args.rows} rows to {out}")
