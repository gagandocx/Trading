"""xauusd_bot: a research-first machine-learning trading bot for XAUUSD (spot gold).

This package implements a candle-by-candle technical-analysis trading research
pipeline: data ingestion, feature engineering, triple-barrier labeling, model
training, walk-forward backtesting, risk management, and a disabled-by-default
paper/live execution layer.

Design principle: *graceful degradation*. Every heavy third-party dependency
(numpy, pandas, scikit-learn, lightgbm, matplotlib, MetaTrader5) is optional and
imported lazily behind ``try/except``. The package always imports and runs with
only the Python standard library; a pure-stdlib fallback provides correctness so
the pipeline is runnable anywhere. Importing ``xauusd_bot`` must never require a
third-party package.

Run from the repository root with ``PYTHONPATH=src`` so the ``xauusd_bot``
package on the ``src/`` layout is importable, e.g.::

    PYTHONPATH=src python -c "import xauusd_bot; print(xauusd_bot.__version__)"
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
