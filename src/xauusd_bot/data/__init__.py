"""Data ingestion for xauusd_bot.

Submodules:
    * :mod:`xauusd_bot.data.sample_data`  - deterministic synthetic OHLCV generator.
    * :mod:`xauusd_bot.data.csv_loader`   - load / clean OHLCV CSV files.
    * :mod:`xauusd_bot.data.mt5_connector` - optional MetaTrader 5 fetcher.

Canonical candle schema (used everywhere, pandas or not) is a record / mapping
with the fields::

    {"timestamp": <ISO-8601 str>, "open": float, "high": float,
     "low": float, "close": float, "volume": float}

In the stdlib fallback path a series is a ``list[dict]`` of these records, sorted
strictly ascending by ``timestamp``.
"""

# Canonical column order for the OHLCV schema. Kept here as the single source of
# truth so loaders / generators / writers agree.
CANONICAL_FIELDS = ("timestamp", "open", "high", "low", "close", "volume")

__all__ = ["CANONICAL_FIELDS"]
