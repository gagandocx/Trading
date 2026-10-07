"""Honest performance metrics for a backtest run.

Computes, from an equity curve and a trade log:

* ``total_return``   - final/initial - 1.
* ``cagr``           - compound annual growth rate (needs >= 2 timestamps).
* ``sharpe``         - annualised Sharpe of per-bar equity returns. The
  annualisation factor assumes ``BARS_PER_YEAR`` M15 bars per year (documented
  below); override via ``bars_per_year``.
* ``max_drawdown``   - magnitude of the largest peak-to-trough equity decline
  (a POSITIVE fraction; never hidden) and its duration in bars.
* ``win_rate``       - fraction of trades with positive NET PnL.
* ``avg_win`` / ``avg_loss`` - mean net PnL of winning / losing trades.
* ``profit_factor``  - gross profit / gross loss (``inf`` if no losses).
* ``num_trades``     - number of completed trades.
* ``exposure``       - fraction of bars with an open position.

Every statistic degrades gracefully: an empty or all-flat trade log yields zeros
(and ``report()`` still renders) rather than raising.

Rendering: :func:`report` returns a human-readable string; :func:`compute_metrics`
returns a JSON-able dict. If matplotlib is installed, :func:`save_equity_curve`
writes a PNG; otherwise it writes the equity curve to CSV. Drawdown is always
reported.
"""

from __future__ import annotations

import csv
import math
from datetime import datetime
from typing import Dict, List, Optional, Sequence

# M15 bars: 4 per hour * 24 hours * 252 trading days ~= 24,192 bars/year.
# Documented assumption; pass ``bars_per_year`` to override for other timeframes.
BARS_PER_YEAR = 4 * 24 * 252


def _returns(equity: Sequence[float]) -> List[float]:
    out: List[float] = []
    for i in range(1, len(equity)):
        prev = equity[i - 1]
        if prev == 0:
            out.append(0.0)
        else:
            out.append((equity[i] - prev) / prev)
    return out


def _max_drawdown(equity: Sequence[float]):
    """Return ``(magnitude, duration_bars)``; magnitude is a positive fraction."""
    if not equity:
        return 0.0, 0
    peak = equity[0]
    peak_idx = 0
    max_dd = 0.0
    max_dur = 0
    for i, v in enumerate(equity):
        if v > peak:
            peak = v
            peak_idx = i
        if peak > 0:
            dd = (peak - v) / peak
        else:
            dd = 0.0
        if dd > max_dd:
            max_dd = dd
            max_dur = i - peak_idx
    return max_dd, max_dur


def _parse_time(t) -> Optional[datetime]:
    if isinstance(t, datetime):
        return t
    if isinstance(t, str):
        try:
            return datetime.fromisoformat(t)
        except ValueError:
            return None
    return None


def compute_metrics(
    result,
    bars_per_year: int = BARS_PER_YEAR,
) -> Dict[str, object]:
    """Compute the full metrics dict from a :class:`BacktestResult`.

    Robust to empty/all-flat logs: returns zeros rather than raising.
    """
    equity = list(getattr(result, "equity_curve", []) or [])
    trades = list(getattr(result, "trades", []) or [])
    initial = float(getattr(result, "initial_capital", 0.0) or 0.0)
    final = float(getattr(result, "final_equity", equity[-1] if equity else initial))
    times = list(getattr(result, "equity_times", []) or [])

    total_return = (final / initial - 1.0) if initial > 0 else 0.0

    # Sharpe from per-bar equity returns, annualised.
    rets = _returns(equity)
    sharpe = 0.0
    if len(rets) >= 2:
        mean = math.fsum(rets) / len(rets)
        var = math.fsum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
        std = math.sqrt(var)
        if std > 0:
            sharpe = (mean / std) * math.sqrt(bars_per_year)

    max_dd, dd_dur = _max_drawdown(equity)

    # Trade-level stats on NET PnL.
    net_pnls = [float(t.net_pnl) for t in trades]
    wins = [p for p in net_pnls if p > 0]
    losses = [p for p in net_pnls if p < 0]
    num_trades = len(net_pnls)
    win_rate = (len(wins) / num_trades) if num_trades else 0.0
    avg_win = (math.fsum(wins) / len(wins)) if wins else 0.0
    avg_loss = (math.fsum(losses) / len(losses)) if losses else 0.0
    gross_profit = math.fsum(wins)
    gross_loss = -math.fsum(losses)
    if gross_loss > 0:
        profit_factor = gross_profit / gross_loss
    else:
        profit_factor = float("inf") if gross_profit > 0 else 0.0

    # CAGR if timestamps allow.
    cagr = 0.0
    if initial > 0 and len(times) >= 2:
        t0 = _parse_time(times[0])
        t1 = _parse_time(times[-1])
        if t0 and t1 and t1 > t0:
            years = (t1 - t0).total_seconds() / (365.25 * 24 * 3600)
            if years > 0 and final > 0:
                cagr = (final / initial) ** (1.0 / years) - 1.0

    total_bars = int(getattr(result, "total_bars", len(equity)) or 0)
    bars_in_market = int(getattr(result, "bars_in_market", 0) or 0)
    exposure = (bars_in_market / total_bars) if total_bars > 0 else 0.0

    return {
        "initial_capital": initial,
        "final_equity": final,
        "total_return": total_return,
        "cagr": cagr,
        "sharpe": sharpe,
        "bars_per_year": bars_per_year,
        "max_drawdown": max_dd,
        "max_drawdown_duration": dd_dur,
        "win_rate": win_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "profit_factor": profit_factor,
        "num_trades": num_trades,
        "exposure": exposure,
        "halted": bool(getattr(result, "halted", False)),
    }


def _fmt_pct(x: float) -> str:
    try:
        return f"{x * 100:.2f}%"
    except (TypeError, ValueError):
        return str(x)


def report(result, bars_per_year: int = BARS_PER_YEAR) -> str:
    """Return a human-readable performance report string.

    Never raises on an empty or all-flat trade log. Always shows drawdown.
    """
    m = result if isinstance(result, dict) else compute_metrics(result, bars_per_year)
    pf = m["profit_factor"]
    pf_str = "inf" if pf == float("inf") else f"{pf:.2f}"
    lines = [
        "===== Backtest Performance =====",
        f"Initial capital : {m['initial_capital']:.2f}",
        f"Final equity    : {m['final_equity']:.2f}",
        f"Total return    : {_fmt_pct(m['total_return'])}",
        f"CAGR            : {_fmt_pct(m['cagr'])}",
        f"Sharpe (ann.)   : {m['sharpe']:.2f}  (bars/year={m['bars_per_year']})",
        f"Max drawdown    : {_fmt_pct(m['max_drawdown'])}"
        f"  (duration {m['max_drawdown_duration']} bars)",
        f"Win rate        : {_fmt_pct(m['win_rate'])}",
        f"Avg win / loss  : {m['avg_win']:.2f} / {m['avg_loss']:.2f}",
        f"Profit factor   : {pf_str}",
        f"Num trades      : {m['num_trades']}",
        f"Exposure        : {_fmt_pct(m['exposure'])}",
        f"Trading halted  : {m['halted']}",
        "================================",
    ]
    return "\n".join(lines)


def save_equity_curve(result, path_png: str, path_csv: str) -> str:
    """Render the equity curve to a PNG if matplotlib is available, else CSV.

    Returns the path actually written. Never raises if matplotlib is missing.
    """
    equity = list(getattr(result, "equity_curve", []) or [])
    times = list(getattr(result, "equity_times", []) or [])

    try:  # pragma: no cover - only runs where matplotlib exists
        import matplotlib  # type: ignore

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt  # type: ignore

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(range(len(equity)), equity, color="#1f77b4")
        ax.set_title("Equity curve")
        ax.set_xlabel("bar")
        ax.set_ylabel("equity (USD)")
        fig.tight_layout()
        fig.savefig(path_png)
        plt.close(fig)
        return path_png
    except Exception:
        # Fallback: write the equity curve to CSV.
        with open(path_csv, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["bar", "timestamp", "equity"])
            for i, eq in enumerate(equity):
                ts = times[i] if i < len(times) else ""
                writer.writerow([i, ts, eq])
        return path_csv
