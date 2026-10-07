# xauusd_bot

A research-first machine-learning trading bot for **XAUUSD (spot gold)**. It makes
a decision on each candle using technical analysis and **ICT (Inner Circle Trader)
Smart-Money-Concepts**, with machine learning to study historical price data and
predict high-probability entry / exit points. Live execution is **disabled by
default**; the project is for research and paper trading first.

> This repository is being built feature by feature. FEAT-001 lays the
> foundation: package scaffold, configuration, a pure-stdlib numeric compat
> layer, and data ingestion (synthetic sample generator, CSV loader, and an
> optional MetaTrader 5 connector). Feature engineering, labeling, models,
> backtesting, and execution arrive in later features.

## Design principle: graceful degradation

Every heavy dependency (pandas, numpy, scikit-learn, lightgbm, matplotlib,
PyYAML, MetaTrader5) is **optional** and imported lazily behind `try/except`. The
package always imports and the sample pipeline always runs with **only the Python
standard library**. Installing the production stack from `requirements.txt` simply
unlocks the faster, full-featured path on your own machine.

## Trading approach (ICT-based)

Entries are built around ICT concepts: market structure (BOS / CHOCH), order
blocks, fair value gaps, liquidity sweeps, and premium/discount zones. The
**primary entry trigger is the inverse Fair Value Gap (iFVG)** retest — when price
trades fully through an existing FVG and flips its polarity. These parameters live
under `features.ict` in `configs/default.yaml` and are consumed by the feature /
signal stages added in later features.

## Layout

```
src/xauusd_bot/        # the package (src layout)
  __init__.py
  config.py            # typed Config dataclasses + layered YAML loader
  compat.py            # pure-stdlib rolling/ewm/diff numeric helpers + HAS_* flags
  data/
    __init__.py        # canonical OHLCV schema
    sample_data.py     # deterministic synthetic XAUUSD generator
    csv_loader.py      # OHLCV CSV load + clean + strict time sort
    mt5_connector.py   # optional MetaTrader 5 fetcher (import-safe)
configs/default.yaml   # XAUUSD defaults; live_trading_enabled: false
data/sample/           # small generated sample CSV, runnable out of the box
requirements.txt       # production stack (install on your own machine)
```

## Running (stdlib only, no installs)

Run from the repository root with `PYTHONPATH=src`:

```bash
# import the package and read config
PYTHONPATH=src python -c "from xauusd_bot import config; print(config.load_config('configs/default.yaml').execution.live_trading_enabled)"

# regenerate the sample dataset
PYTHONPATH=src python -m xauusd_bot.data.sample_data --out data/sample/XAUUSD_sample.csv --rows 300 --seed 7

# load candles back
PYTHONPATH=src python -c "from xauusd_bot.data.csv_loader import load_candles; print(len(load_candles('data/sample/XAUUSD_sample.csv')), 'candles')"
```

## Running the full stack (your machine)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

MetaTrader 5 is Windows-only and optional; see the setup notes in
`src/xauusd_bot/data/mt5_connector.py` for connecting your own broker.

## Canonical candle schema

Every data source returns records with these fields, strictly time-sorted
ascending:

```
timestamp (ISO-8601 str), open, high, low, close, volume (floats)
```

## Status / safety

Live trading is **off by default** (`execution.live_trading_enabled: false`,
`execution.mode: paper`). This is research software, not financial advice.
