"""Execution layer for xauusd_bot.

Two pieces, both designed so the research pipeline never accidentally touches a
real broker:

* :mod:`xauusd_bot.execution.live_guard` - the single safety switch. Any code
  path that would place a REAL order must call :func:`ensure_live_allowed` first.
  It refuses (raises :class:`LiveTradingDisabled`) unless the config explicitly
  enables live trading AND sets ``execution.mode == 'live'``. MetaTrader5 is
  imported lazily and only ever reached through this guard.
* :mod:`xauusd_bot.execution.paper_trader` - a broker-free paper-trading engine
  that simulates fills against incoming candles using the SAME cost model as the
  backtest, tracking a virtual account. This is what you run day to day.

Live trading is OFF BY DEFAULT and stays off unless the user opts in on purpose.
"""

from .live_guard import (
    LiveTradingDisabled,
    ensure_live_allowed,
    is_live_allowed,
)
from .paper_trader import PaperAccount, PaperTrader

__all__ = [
    "LiveTradingDisabled",
    "ensure_live_allowed",
    "is_live_allowed",
    "PaperAccount",
    "PaperTrader",
]
