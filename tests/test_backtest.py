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
