"""Event-driven, cost-aware backtest engine.

The entry trigger is the ICT/iFVG signal (``direction`` + ATR stop/target
distances) produced by :func:`xauusd_bot.features.signals.generate_signals`. The
ML model is a PROBABILITY FILTER: for each signalled entry we read the model's
calibrated probability that the trade reaches its target (class ``+1``) and only
take the trade when that probability clears a configured threshold.

Simulation (per test bar ``i``, decisions use only information available at ``i``)
---------------------------------------------------------------------------------
1. If a position is open, check whether this bar's high/low hits the stop or
   target (barrier direction matches the signal direction) or the time barrier;
   if so, close it, applying exit costs, and book PnL.
2. If flat and bar ``i`` has an entry signal AND the drawdown guard allows new
   entries AND the model probability passes the threshold: open a position sized
   by the risk module at this bar's close, applying entry costs. The protective
   stop/target/horizon are fixed from information known at ``i`` (ATR-based).

Costs
-----
``apply_costs`` subtracts the realistic round-trip trading cost from a trade's
gross PnL: half the spread on entry PLUS half the spread on exit (= one full
spread, in price units, times the contract size and lots) PLUS the commission per
lot. A ZERO-move round trip therefore returns a NEGATIVE PnL equal to the modeled
costs - this is unit-tested and must never be positive.

No lookahead: a bar's entry decision uses that bar's close and features only; exit
checks use the bar's own high/low AFTER the position already existed.

Mark-to-market equity
---------------------
Each bar the equity curve is marked at ``realized_equity + unrealized_pnl`` where
``unrealized_pnl`` is the open position's PnL at this bar's CLOSE, net of the
round-trip costs that will be charged when it exits (``apply_costs`` with a zero
gross). This means ``max_drawdown``, the annualized Sharpe, and the
``DrawdownGuard`` all see intra-trade risk - a position sitting deep underwater
dips the curve immediately instead of showing a flat line until it closes. The
realized cash accounting on close is unchanged (``net_pnl`` already includes
costs), so costs are modeled exactly once: the mid-trade mark is a transient
display/guard value, and when the trade actually closes ``realized_equity`` moves
to the same net figure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

from ..risk.risk import CONTRACT_SIZE, DrawdownGuard, position_size

Candle = Dict[str, object]


def apply_costs(
    gross_pnl: float,
    spread: float,
    commission: float,
    lots: float,
    contract_size: float = CONTRACT_SIZE,
) -> float:
    """Return ``gross_pnl`` net of realistic round-trip trading costs.

    Parameters
    ----------
    gross_pnl:
        Trade PnL in USD before costs (price move * contract_size * lots).
    spread:
        The full bid/ask spread in PRICE units (USD of gold). Half is charged on
        entry and half on exit, so one full ``spread`` is paid per round trip.
    commission:
        Round-turn commission per 1.0 lot (USD).
    lots:
        Position size in lots.
    contract_size:
        Ounces per lot (default ``CONTRACT_SIZE`` = 100 for XAUUSD).

    Returns
    -------
    float
        Net PnL = gross_pnl - spread_cost - commission_cost. For a zero-move round
        trip (``gross_pnl == 0``) with any positive lots this is strictly
        NEGATIVE.
    """
    lots = max(0.0, float(lots))
    # Half-spread on entry + half-spread on exit == one full spread per round trip.
    spread_cost = spread * contract_size * lots
    commission_cost = commission * lots
    return gross_pnl - spread_cost - commission_cost


@dataclass
class Trade:
    """A single completed round-trip trade."""

    entry_index: int
    exit_index: int
    direction: str  # "long" | "short"
    entry_price: float
    exit_price: float
    lots: float
    gross_pnl: float
    net_pnl: float
    exit_reason: str  # "target" | "stop" | "time"
    entry_type: str


@dataclass
class BacktestResult:
    """Container for backtest outputs."""

    equity_curve: List[float] = field(default_factory=list)
    equity_times: List[object] = field(default_factory=list)
    trades: List[Trade] = field(default_factory=list)
    initial_capital: float = 0.0
    final_equity: float = 0.0
    halted: bool = False
    bars_in_market: int = 0
    total_bars: int = 0


def _f(v) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


def run_backtest(
    rows: Sequence[Candle],
    signals: Sequence[Dict[str, object]],
    probabilities: Sequence[Optional[float]],
    cfg,
    test_indices: Optional[Sequence[int]] = None,
) -> BacktestResult:
    """Run the event-driven backtest.

    Parameters
    ----------
    rows:
        Canonical candles (full series; ``test_indices`` restricts the active
        window).
    signals:
        Per-bar signal records from ``generate_signals`` (same length as ``rows``,
        indexed by bar). Each has ``direction``, ``entry_type``, ``stop_dist``,
        ``target_dist``.
    probabilities:
        Per-bar model probability that the signalled trade reaches its target
        (class ``+1``), aligned to ``rows``. ``None`` means "no score" -> treated
        as failing the threshold (trade skipped). On bars with no signal this is
        ignored.
    cfg:
        Config object (uses ``backtest``, ``risk``, ``labeling``).
    test_indices:
        Optional subset of bar indices to trade over (the test fold). Defaults to
        the whole series. The engine still reads prices on any bar to resolve an
        open position's exit, but only OPENS trades on bars in this set.

    Returns
    -------
    BacktestResult
    """
    rows = list(rows)
    n = len(rows)
    bcfg = cfg.backtest
    rcfg = cfg.risk
    horizon = cfg.labeling.horizon

    threshold = getattr(bcfg, "prob_threshold", None)
    if threshold is None:
        threshold = getattr(rcfg, "prob_threshold", 0.5)

    spread = _spread_price(bcfg)
    commission = float(bcfg.commission_per_lot)
    initial_capital = float(bcfg.initial_capital)

    if test_indices is None:
        tradable = set(range(n))
        start = 0
        end = n
    else:
        tradable = set(int(i) for i in test_indices)
        start = min(tradable) if tradable else 0
        end = (max(tradable) + 1) if tradable else 0

    highs = [_f(r.get("high")) for r in rows]
    lows = [_f(r.get("low")) for r in rows]
    closes = [_f(r.get("close")) for r in rows]

    equity = initial_capital
    guard = DrawdownGuard(
        max_drawdown_pct=rcfg.max_drawdown_pct, initial_equity=initial_capital
    )

    result = BacktestResult(
        initial_capital=initial_capital,
        total_bars=max(0, end - start),
    )

    # Open-position state.
    open_pos = None  # dict or None

    for i in range(start, end):
        close_i = closes[i]

        # --- 1) Manage an open position (exit checks use THIS bar's range) ---
        if open_pos is not None:
            exit_reason, exit_price = _check_exit(
                open_pos, i, highs[i], lows[i], closes[i], horizon
            )
            if exit_reason is not None:
                trade = _close_trade(
                    open_pos, i, exit_price, exit_reason, spread, commission
                )
                equity += trade.net_pnl
                result.trades.append(trade)
                open_pos = None

        # Count market exposure.
        if open_pos is not None:
            result.bars_in_market += 1

        # Mark equity (realized + open-position mark-to-market) and update the
        # drawdown guard once per bar. The unrealized PnL is netted of the
        # round-trip costs the position will pay on exit so the curve, Sharpe,
        # drawdown, and the halt guardrail reflect intra-trade risk honestly and
        # transition smoothly into the realized figure when the trade closes.
        marked_equity = equity + _unrealized_pnl(
            open_pos, closes[i], spread, commission
        )
        result.equity_curve.append(marked_equity)
        result.equity_times.append(
            rows[i].get("timestamp") if isinstance(rows[i], dict) else i
        )
        guard.update(marked_equity)

        # --- 2) Consider a new entry (only on tradable test bars, when flat) --
        if open_pos is not None or i not in tradable:
            continue
        if not guard.can_enter():
            continue

        sig = signals[i] if i < len(signals) else None
        if not sig:
            continue
        direction = sig.get("direction")
        if direction not in ("long", "short"):
            continue

        stop_dist = _f(sig.get("stop_dist"))
        target_dist = _f(sig.get("target_dist"))
        if not stop_dist or stop_dist <= 0 or close_i is None:
            continue

        # Model probability FILTER: probability the trade hits target (+1).
        p = probabilities[i] if i < len(probabilities) else None
        if p is None or p < threshold:
            continue

        lots = position_size(
            capital=equity,
            risk_per_trade=rcfg.risk_per_trade,
            stop_distance=stop_dist,
            max_position_lots=rcfg.max_position_lots,
        )
        if lots <= 0:
            continue

        open_pos = _open_position(
            i, direction, close_i, stop_dist, target_dist, lots, sig
        )

    # Force-close any position left open at the end of the window at last close.
    if open_pos is not None and end > start:
        last = end - 1
        trade = _close_trade(
            open_pos, last, closes[last], "time", spread, commission
        )
        equity += trade.net_pnl
        result.trades.append(trade)
        if result.equity_curve:
            result.equity_curve[-1] = equity

    result.final_equity = equity
    result.halted = guard.halted
    return result


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _spread_price(bcfg) -> float:
    """Convert the configured spread into PRICE units (USD of gold).

    ``spread_pips`` is documented in cents for XAUUSD (e.g. 25.0 == $0.25). We
    convert cents -> dollars so costs are in the same units as price moves.
    """
    return float(bcfg.spread_pips) / 100.0


def _unrealized_pnl(pos, close, spread, commission) -> float:
    """Mark-to-market PnL of an open position at ``close``, net of exit costs.

    Returns ``0.0`` when flat or when the current close is unknown. The gross
    move is valued at this bar's close in the signalled direction, then run
    through :func:`apply_costs` (with a zero gross so only the modeled round-trip
    costs are subtracted). This mirrors exactly what ``_close_trade`` would book
    if the position exited here at the close, so marking it onto the equity curve
    does not double-count costs: on the real close the realized equity moves to
    this same net figure.
    """
    if pos is None or close is None:
        return 0.0
    entry_price = pos["entry_price"]
    lots = pos["lots"]
    if pos["direction"] == "long":
        move = close - entry_price
    else:
        move = entry_price - close
    gross = move * CONTRACT_SIZE * lots
    return apply_costs(gross, spread=spread, commission=commission, lots=lots)


def _open_position(index, direction, entry_price, stop_dist, target_dist, lots, sig):
    """Create the open-position state dict with fixed protective barriers."""
    if direction == "long":
        stop_price = entry_price - stop_dist
        target_price = (entry_price + target_dist) if target_dist else None
    else:
        stop_price = entry_price + stop_dist
        target_price = (entry_price - target_dist) if target_dist else None
    return {
        "entry_index": index,
        "direction": direction,
        "entry_price": entry_price,
        "stop_price": stop_price,
        "target_price": target_price,
        "lots": lots,
        "entry_type": sig.get("entry_type", "none"),
    }


def _check_exit(pos, i, hi, lo, close, horizon):
    """Return ``(exit_reason, exit_price)`` or ``(None, None)`` for bar ``i``.

    Barrier direction matches the signal direction. If both stop and target are
    touched within the same bar we resolve to the STOP (conservative). The time
    barrier closes the trade at the bar's close once ``horizon`` bars have
    elapsed since entry.
    """
    if hi is None or lo is None:
        return None, None
    direction = pos["direction"]
    stop_price = pos["stop_price"]
    target_price = pos["target_price"]

    if direction == "long":
        hit_stop = lo <= stop_price
        hit_target = target_price is not None and hi >= target_price
    else:
        hit_stop = hi >= stop_price
        hit_target = target_price is not None and lo <= target_price

    if hit_stop and hit_target:
        return "stop", stop_price  # conservative: assume adverse first
    if hit_stop:
        return "stop", stop_price
    if hit_target:
        return "target", target_price

    # Time barrier: close at this bar's close once the horizon has elapsed.
    if i - pos["entry_index"] >= horizon:
        return "time", close
    return None, None


def _close_trade(pos, exit_index, exit_price, exit_reason, spread, commission):
    """Build a :class:`Trade`, computing gross and net (cost-adjusted) PnL."""
    direction = pos["direction"]
    entry_price = pos["entry_price"]
    lots = pos["lots"]
    if exit_price is None:
        exit_price = entry_price
    if direction == "long":
        move = exit_price - entry_price
    else:
        move = entry_price - exit_price
    gross = move * CONTRACT_SIZE * lots
    net = apply_costs(gross, spread=spread, commission=commission, lots=lots)
    return Trade(
        entry_index=pos["entry_index"],
        exit_index=exit_index,
        direction=direction,
        entry_price=entry_price,
        exit_price=exit_price,
        lots=lots,
        gross_pnl=gross,
        net_pnl=net,
        exit_reason=exit_reason,
        entry_type=pos.get("entry_type", "none"),
    )
