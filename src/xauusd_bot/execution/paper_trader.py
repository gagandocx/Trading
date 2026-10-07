"""Broker-free paper trading.

:class:`PaperTrader` simulates order placement and fills against a stream of
incoming candles, tracking a virtual account. It NEVER touches a broker, so it is
always safe to run (no :func:`live_guard.ensure_live_allowed` needed - no real
orders are placed).

Fidelity: it uses the SAME cost model as the backtest
(:func:`xauusd_bot.backtest.engine.apply_costs`) and the SAME ATR-based risk
sizing (:func:`xauusd_bot.risk.risk.position_size`), so paper results line up with
backtest results. Entries are driven by the ICT/iFVG signal records (the primary
trigger) and may be gated by a model probability, exactly like the backtest.

Usage::

    trader = PaperTrader(cfg)
    for i, candle in enumerate(candles):
        trader.on_candle(i, candle, signal=signals[i], probability=probs[i])
    print(trader.account.equity)

It processes candles one at a time (streaming), so it can also drive a live-paper
loop that pulls fresh candles from a feed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..backtest.engine import apply_costs
from ..risk.risk import CONTRACT_SIZE, DrawdownGuard, position_size

Candle = Dict[str, object]


@dataclass
class PaperFill:
    """A completed round-trip paper trade."""

    entry_index: int
    exit_index: int
    direction: str
    entry_price: float
    exit_price: float
    lots: float
    gross_pnl: float
    net_pnl: float
    exit_reason: str
    entry_type: str


@dataclass
class PaperAccount:
    """The virtual account state tracked by the paper trader."""

    initial_capital: float = 10000.0
    equity: float = 10000.0
    peak_equity: float = 10000.0
    fills: List[PaperFill] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)

    def record_equity(self) -> None:
        self.equity_curve.append(self.equity)
        if self.equity > self.peak_equity:
            self.peak_equity = self.equity


def _f(v) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


class PaperTrader:
    """Streaming paper-trading simulator (one open position at a time)."""

    def __init__(self, cfg) -> None:
        self.cfg = cfg
        bcfg = cfg.backtest
        rcfg = cfg.risk
        self.spread = float(bcfg.spread_pips) / 100.0  # cents -> dollars
        self.commission = float(bcfg.commission_per_lot)
        self.horizon = int(cfg.labeling.horizon)
        self.risk_per_trade = float(rcfg.risk_per_trade)
        self.max_position_lots = float(rcfg.max_position_lots)
        self.threshold = _resolve_threshold(cfg)

        self.account = PaperAccount(
            initial_capital=float(bcfg.initial_capital),
            equity=float(bcfg.initial_capital),
            peak_equity=float(bcfg.initial_capital),
        )
        self.guard = DrawdownGuard(
            max_drawdown_pct=rcfg.max_drawdown_pct,
            initial_equity=float(bcfg.initial_capital),
        )
        self._open: Optional[Dict[str, object]] = None

    @property
    def position(self) -> Optional[Dict[str, object]]:
        """The currently open position (or ``None`` when flat)."""
        return self._open

    def on_candle(
        self,
        index: int,
        candle: Candle,
        signal: Optional[Dict[str, object]] = None,
        probability: Optional[float] = None,
    ) -> Optional[PaperFill]:
        """Advance the simulation by one candle.

        1. If a position is open, check this candle's range for a stop/target/time
           exit and close if hit (booking cost-adjusted PnL).
        2. Mark equity and update the drawdown guard.
        3. If flat and the candle carries a tradable signal that clears the
           probability threshold and the guard allows it, open a sized position.

        Returns the :class:`PaperFill` if a position closed on this candle, else
        ``None``.
        """
        hi = _f(candle.get("high"))
        lo = _f(candle.get("low"))
        close = _f(candle.get("close"))

        closed: Optional[PaperFill] = None

        # --- 1) manage open position --------------------------------------
        if self._open is not None:
            reason, exit_price = self._check_exit(index, hi, lo, close)
            if reason is not None:
                closed = self._close(index, exit_price, reason)

        # --- 2) mark equity + guard ---------------------------------------
        self.account.record_equity()
        self.guard.update(self.account.equity)

        # --- 3) consider a new entry --------------------------------------
        if self._open is None and signal and self.guard.can_enter():
            self._maybe_open(index, close, signal, probability)

        return closed

    # ------------------------------------------------------------------ open
    def _maybe_open(self, index, close, signal, probability) -> None:
        direction = signal.get("direction")
        if direction not in ("long", "short") or close is None:
            return
        stop_dist = _f(signal.get("stop_dist"))
        target_dist = _f(signal.get("target_dist"))
        if not stop_dist or stop_dist <= 0:
            return
        # Probability filter (same semantics as the backtest).
        if probability is None or float(probability) < self.threshold:
            return
        lots = position_size(
            capital=self.account.equity,
            risk_per_trade=self.risk_per_trade,
            stop_distance=stop_dist,
            max_position_lots=self.max_position_lots,
        )
        if lots <= 0:
            return
        if direction == "long":
            stop_price = close - stop_dist
            target_price = (close + target_dist) if target_dist else None
        else:
            stop_price = close + stop_dist
            target_price = (close - target_dist) if target_dist else None
        self._open = {
            "entry_index": index,
            "direction": direction,
            "entry_price": close,
            "stop_price": stop_price,
            "target_price": target_price,
            "lots": lots,
            "entry_type": signal.get("entry_type", "none"),
        }

    # ------------------------------------------------------------------ exit
    def _check_exit(self, i, hi, lo, close):
        if hi is None or lo is None:
            return None, None
        pos = self._open
        direction = pos["direction"]
        stop_price = pos["stop_price"]
        target_price = pos["target_price"]
        if direction == "long":
            hit_stop = lo <= stop_price
            hit_target = target_price is not None and hi >= target_price
        else:
            hit_stop = hi >= stop_price
            hit_target = target_price is not None and lo <= target_price
        if hit_stop:  # conservative: adverse barrier assumed first
            return "stop", stop_price
        if hit_target:
            return "target", target_price
        if i - pos["entry_index"] >= self.horizon:
            return "time", close
        return None, None

    def _close(self, exit_index, exit_price, reason) -> PaperFill:
        pos = self._open
        direction = pos["direction"]
        entry_price = pos["entry_price"]
        lots = pos["lots"]
        if exit_price is None:
            exit_price = entry_price
        move = (exit_price - entry_price) if direction == "long" else (entry_price - exit_price)
        gross = move * CONTRACT_SIZE * lots
        net = apply_costs(gross, spread=self.spread, commission=self.commission, lots=lots)
        self.account.equity += net
        fill = PaperFill(
            entry_index=pos["entry_index"],
            exit_index=exit_index,
            direction=direction,
            entry_price=entry_price,
            exit_price=exit_price,
            lots=lots,
            gross_pnl=gross,
            net_pnl=net,
            exit_reason=reason,
            entry_type=pos.get("entry_type", "none"),
        )
        self.account.fills.append(fill)
        self._open = None
        return fill

    # --------------------------------------------------------------- control
    def close_open_position(self, index: int, price: float) -> Optional[PaperFill]:
        """Force-close any open position at ``price`` (e.g. end of a session)."""
        if self._open is None:
            return None
        return self._close(index, price, "forced")


def _resolve_threshold(cfg) -> float:
    """Mirror the backtest's threshold resolution: backtest -> risk -> 0.5."""
    t = getattr(cfg.backtest, "prob_threshold", None)
    if t is None:
        t = getattr(cfg.risk, "prob_threshold", 0.5)
    return float(t)
