"""Backtest tests: cost model, model probability filter, drawdown in metrics."""

import unittest

import _util  # noqa: F401
from xauusd_bot.backtest.engine import apply_costs, run_backtest
from xauusd_bot.backtest.metrics import compute_metrics, report
from xauusd_bot.config import load_config


def _cfg():
    return load_config("configs/default.yaml")


def _rows_rising(n=60, step=1.0, start=100.0):
    rows = []
    p = start
    for i in range(n):
        o = p
        c = p + step
        rows.append(
            {
                "timestamp": f"2023-01-01T00:{i:02d}:00",
                "open": o,
                "high": c + 0.5,
                "low": o - 0.5,
                "close": c,
                "volume": 1.0,
            }
        )
        p = c
    return rows


class TestCostModel(unittest.TestCase):
    def test_zero_move_round_trip_is_negative(self):
        pnl = apply_costs(gross_pnl=0.0, spread=0.3, commission=7.0, lots=1.0)
        self.assertLess(pnl, 0.0)
        # Exactly the modeled costs: spread*contract*lots + commission*lots.
        self.assertAlmostEqual(pnl, -(0.3 * 100 * 1.0 + 7.0 * 1.0), places=6)

    def test_zero_lots_zero_cost(self):
        self.assertAlmostEqual(apply_costs(0.0, 0.3, 7.0, 0.0), 0.0, places=9)


class TestModelFilter(unittest.TestCase):
    def _signals(self, rows):
        # Every bar emits a long iFVG entry with ATR-ish stop/target.
        sigs = []
        for i in range(len(rows)):
            sigs.append(
                {
                    "index": i,
                    "direction": "long",
                    "entry_type": "ifvg",
                    "stop_dist": 2.0,
                    "target_dist": 2.0,
                }
            )
        return sigs

    def test_probabilities_filter_entries(self):
        cfg = _cfg()
        cfg.backtest.prob_threshold = 0.6
        rows = _rows_rising(60)
        sigs = self._signals(rows)
        test_idx = list(range(5, 55))

        # All probabilities below threshold -> NO trades taken.
        low = [0.1] * len(rows)
        res_low = run_backtest(rows, sigs, low, cfg, test_indices=test_idx)
        self.assertEqual(len(res_low.trades), 0)

        # High probabilities -> trades ARE taken (iFVG entries pass the filter).
        high = [0.9] * len(rows)
        res_high = run_backtest(rows, sigs, high, cfg, test_indices=test_idx)
        self.assertGreater(len(res_high.trades), 0)
        self.assertTrue(all(t.entry_type == "ifvg" for t in res_high.trades))

    def test_metrics_include_drawdown(self):
        cfg = _cfg()
        rows = _rows_rising(60)
        sigs = self._signals(rows)
        res = run_backtest(rows, sigs, [0.9] * len(rows), cfg, test_indices=list(range(5, 55)))
        m = compute_metrics(res)
        for key in ("total_return", "sharpe", "max_drawdown", "win_rate", "num_trades"):
            self.assertIn(key, m)
        self.assertGreaterEqual(m["max_drawdown"], 0.0)
        # report() renders without raising and mentions drawdown + sharpe.
        text = report(res)
        self.assertIn("Max drawdown", text)
        self.assertIn("Sharpe", text)

    def test_mark_to_market_dips_equity_mid_trade(self):
        """A position underwater mid-trade must dip the curve BEFORE it exits.

        We open a single long on the first tradable bar, then feed bars whose
        close swings against the account without touching the (wide) stop, then
        recover. A realized-only curve would stay perfectly flat until the exit;
        the mark-to-market curve must show an intra-trade drawdown.
        """
        cfg = _cfg()
        cfg.backtest.prob_threshold = 0.5
        # Wide stop/target so the adverse swing never triggers an exit; the trade
        # is closed by the time barrier at the end instead.
        cfg.labeling.horizon = 100

        # Flat-ish series: enter at 100, drop to ~90 mid-trade, recover to ~100.
        closes_path = [100.0] * 3 + [100.0, 95.0, 90.0, 93.0, 98.0, 100.0] + [100.0] * 3
        rows = []
        for i, c in enumerate(closes_path):
            o = closes_path[i - 1] if i > 0 else c
            rows.append(
                {
                    "timestamp": f"2023-01-01T00:{i:02d}:00",
                    "open": o,
                    "high": max(o, c) + 0.1,
                    "low": min(o, c) - 0.1,
                    "close": c,
                    "volume": 1.0,
                }
            )
        n = len(rows)
        # One long signal on bar 3 with a very wide stop so no stop-out occurs.
        sigs = [
            {"index": i, "direction": "none", "entry_type": "none", "stop_dist": None, "target_dist": None}
            for i in range(n)
        ]
        sigs[3] = {
            "index": 3,
            "direction": "long",
            "entry_type": "ifvg",
            "stop_dist": 50.0,
            "target_dist": 50.0,
        }
        probs = [None] * n
        probs[3] = 0.9

        res = run_backtest(rows, sigs, probs, cfg, test_indices=list(range(n)))
        self.assertEqual(len(res.trades), 1)

        # Realized-only equity would be flat (initial_capital) for every bar from
        # entry until the single exit; max drawdown would be ~0. With
        # mark-to-market the curve must dip while the trade is underwater.
        cap = cfg.backtest.initial_capital
        min_marked = min(res.equity_curve)
        self.assertLess(min_marked, cap, "mark-to-market curve should dip below initial capital mid-trade")

        m = compute_metrics(res)
        # The intra-trade excursion (~ -10 * 100 lots) produces a real drawdown.
        self.assertGreater(m["max_drawdown"], 0.0)

    def test_drawdown_guard_halts_on_unrealized_loss(self):
        """The guard must trip on a mark-to-market loss, not only on realized."""
        cfg = _cfg()
        cfg.backtest.prob_threshold = 0.5
        cfg.labeling.horizon = 100
        # Risk per trade is ~1% of equity (sized from the stop), so a mid-trade
        # excursion that reaches most of the way to the stop is ~1% unrealized.
        # Set the guard below that so the UNREALIZED loss alone trips it.
        cfg.risk.max_drawdown_pct = 0.005  # 0.5%

        # Enter long at 1000 with a 100-wide stop (lots sized from that stop).
        # Price drops toward but never past the stop (lowest close 901, low
        # ~900.9 > 900 stop), so no stop-out: the loss is purely unrealized.
        closes_path = [1000.0] * 3 + [1000.0, 970.0, 940.0, 920.0, 905.0, 901.0]
        rows = []
        for i, c in enumerate(closes_path):
            o = closes_path[i - 1] if i > 0 else c
            rows.append(
                {
                    "timestamp": f"2023-01-01T00:{i:02d}:00",
                    "open": o,
                    "high": max(o, c) + 0.1,
                    "low": min(o, c) - 0.1,
                    "close": c,
                    "volume": 1.0,
                }
            )
        n = len(rows)
        sigs = [
            {"index": i, "direction": "none", "entry_type": "none", "stop_dist": None, "target_dist": None}
            for i in range(n)
        ]
        sigs[3] = {"index": 3, "direction": "long", "entry_type": "ifvg", "stop_dist": 100.0, "target_dist": 100.0}
        probs = [None] * n
        probs[3] = 0.9

        res = run_backtest(rows, sigs, probs, cfg, test_indices=list(range(n)))
        # The unrealized loss alone (position never closed before series end)
        # must have latched the guard.
        self.assertTrue(res.halted)

    def test_empty_metrics_do_not_raise(self):
        cfg = _cfg()
        rows = _rows_rising(30)
        sigs = [{"index": i, "direction": "none", "entry_type": "none", "stop_dist": None, "target_dist": None} for i in range(len(rows))]
        res = run_backtest(rows, sigs, [None] * len(rows), cfg, test_indices=list(range(len(rows))))
        m = compute_metrics(res)
        self.assertEqual(m["num_trades"], 0)
        self.assertIsInstance(report(res), str)


if __name__ == "__main__":
    unittest.main()
