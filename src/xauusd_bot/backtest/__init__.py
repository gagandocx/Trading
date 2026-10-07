"""Backtest package: walk-forward validation, cost-aware engine, and metrics.

The research core. Components:

* :mod:`walk_forward` - strictly time-ordered expanding/rolling train/test splits
  with a PURGE/EMBARGO gap >= the labelling horizon so a training row's forward
  label window can never overlap the test set. No shuffling.
* :mod:`engine` - an event-driven, bar-by-bar backtest. Trades are triggered by
  the ICT/iFVG signals; the ML model acts as a calibrated-probability FILTER.
  Realistic gold costs (half-spread each side + commission) and triple-barrier
  style exits are applied. No future information is used at decision time.
* :mod:`metrics` - honest performance statistics (returns, Sharpe, max drawdown,
  win rate, profit factor, exposure) plus a human-readable report.
"""

from .engine import BacktestResult, apply_costs, run_backtest  # noqa: F401
from .metrics import compute_metrics, report  # noqa: F401
from .walk_forward import walk_forward_splits  # noqa: F401
