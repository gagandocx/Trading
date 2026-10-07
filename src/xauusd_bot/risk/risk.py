"""ATR-based position sizing and drawdown guardrails for XAUUSD.

Contract specifics for spot gold (XAUUSD)
-----------------------------------------
XAUUSD is quoted in USD per troy ounce. A standard lot is 100 ounces, so a
1.00-lot position gains/loses ``100 * price_move`` USD for a ``price_move`` dollar
change in the gold price. We expose this as ``CONTRACT_SIZE`` (ounces per lot) so
sizing math is explicit and auditable.

Position sizing
---------------
Given account ``capital``, a per-trade risk fraction ``risk_per_trade`` and a
``stop_distance`` expressed in PRICE units (dollars of gold, typically
``atr_stop_mult * ATR``), the number of lots that risks exactly
``risk_per_trade * capital`` if the stop is hit is::

    risk_usd = risk_per_trade * capital
    loss_per_lot = stop_distance * CONTRACT_SIZE
    lots = risk_usd / loss_per_lot

The result is clamped to ``[0, max_position_lots]``. All functions are pure.

Drawdown guardrail
------------------
:class:`DrawdownGuard` tracks the running equity peak and reports whether the
current drawdown has breached ``max_drawdown_pct``. The backtest engine consults
it before opening any new position: once breached, NO new entries are taken
(existing positions are still allowed to close). :func:`drawdown_exceeded` is the
stateless predicate behind it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Ounces of gold per 1.0 standard lot of XAUUSD.
CONTRACT_SIZE = 100.0


def position_size(
    capital: float,
    risk_per_trade: float,
    stop_distance: float,
    max_position_lots: float = 1.0,
    contract_size: float = CONTRACT_SIZE,
) -> float:
    """Return the position size in lots for a single XAUUSD trade.

    Parameters
    ----------
    capital:
        Current account equity in USD.
    risk_per_trade:
        Fraction of equity to risk if the stop is hit (e.g. ``0.01`` for 1%).
    stop_distance:
        Distance from entry to stop in PRICE units (USD of gold). Typically
        ``atr_stop_mult * ATR``.
    max_position_lots:
        Hard cap on the returned size (lots).
    contract_size:
        Ounces per lot (default ``CONTRACT_SIZE`` = 100 for XAUUSD).

    Returns
    -------
    float
        Lots to trade, clamped to ``[0, max_position_lots]``. Returns ``0.0`` for
        non-positive capital, risk, or stop distance (nothing tradable).
    """
    if capital <= 0 or risk_per_trade <= 0 or stop_distance <= 0:
        return 0.0
    if contract_size <= 0:
        return 0.0
    risk_usd = risk_per_trade * capital
    loss_per_lot = stop_distance * contract_size
    if loss_per_lot <= 0:
        return 0.0
    lots = risk_usd / loss_per_lot
    return cap_lots(lots, max_position_lots)


def cap_lots(lots: float, max_position_lots: float) -> float:
    """Clamp a lot size into ``[0, max_position_lots]``."""
    if lots <= 0:
        return 0.0
    if max_position_lots is not None and lots > max_position_lots:
        return float(max_position_lots)
    return float(lots)


def drawdown_exceeded(equity: float, peak_equity: float, max_drawdown_pct: float) -> bool:
    """Stateless guardrail predicate.

    Returns ``True`` when the drawdown from ``peak_equity`` down to ``equity``
    meets or exceeds ``max_drawdown_pct`` (a fraction, e.g. ``0.20`` for 20%).
    """
    if peak_equity <= 0:
        return False
    drawdown = (peak_equity - equity) / peak_equity
    return drawdown >= max_drawdown_pct


@dataclass
class DrawdownGuard:
    """Stateful max-drawdown guardrail that halts new entries when breached.

    Usage::

        guard = DrawdownGuard(max_drawdown_pct=0.20, initial_equity=10000)
        ...
        guard.update(current_equity)
        if guard.halted:
            # skip new entries
            ...

    Once the drawdown breaches ``max_drawdown_pct`` the guard latches
    ``halted = True`` for the remainder of the run (a tripped risk limit should
    not silently re-arm just because equity wobbled back up).
    """

    max_drawdown_pct: float = 0.20
    initial_equity: float = 0.0
    peak_equity: float = 0.0
    halted: bool = False

    def __post_init__(self) -> None:
        if self.peak_equity <= 0:
            self.peak_equity = max(self.initial_equity, 0.0)

    def update(self, equity: float) -> bool:
        """Record the latest equity and return whether new entries are halted."""
        if equity > self.peak_equity:
            self.peak_equity = equity
        if not self.halted and drawdown_exceeded(
            equity, self.peak_equity, self.max_drawdown_pct
        ):
            self.halted = True
        return self.halted

    def can_enter(self, equity: Optional[float] = None) -> bool:
        """Whether a NEW entry is permitted now (optionally updating equity)."""
        if equity is not None:
            self.update(equity)
        return not self.halted

    def current_drawdown(self, equity: float) -> float:
        """Current drawdown fraction from the running peak (>= 0)."""
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - equity) / self.peak_equity)
