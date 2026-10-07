"""Risk tests: ATR position sizing + drawdown guardrail."""

import unittest

import _util  # noqa: F401
from xauusd_bot.risk.risk import DrawdownGuard, cap_lots, drawdown_exceeded, position_size


class TestPositionSizing(unittest.TestCase):
    def test_basic_sizing(self):
        # Risk 1% of 10,000 = $100. Stop $5, contract 100 oz/lot -> loss/lot=$500.
        # lots = 100 / 500 = 0.2.
        lots = position_size(capital=10000.0, risk_per_trade=0.01, stop_distance=5.0, max_position_lots=10.0)
        self.assertAlmostEqual(lots, 0.2, places=9)

    def test_cap_enforced(self):
        lots = position_size(capital=1_000_000.0, risk_per_trade=0.5, stop_distance=1.0, max_position_lots=1.0)
        self.assertEqual(lots, 1.0)

    def test_non_positive_inputs(self):
        self.assertEqual(position_size(0.0, 0.01, 5.0), 0.0)
        self.assertEqual(position_size(10000.0, 0.0, 5.0), 0.0)
        self.assertEqual(position_size(10000.0, 0.01, 0.0), 0.0)

    def test_cap_lots(self):
        self.assertEqual(cap_lots(5.0, 1.0), 1.0)
        self.assertEqual(cap_lots(-1.0, 1.0), 0.0)
        self.assertEqual(cap_lots(0.5, 1.0), 0.5)


class TestDrawdownGuard(unittest.TestCase):
    def test_predicate(self):
        self.assertTrue(drawdown_exceeded(equity=80.0, peak_equity=100.0, max_drawdown_pct=0.20))
        self.assertFalse(drawdown_exceeded(equity=90.0, peak_equity=100.0, max_drawdown_pct=0.20))

    def test_guard_halts_and_latches(self):
        guard = DrawdownGuard(max_drawdown_pct=0.20, initial_equity=10000.0)
        self.assertTrue(guard.can_enter())
        guard.update(10500.0)      # new peak
        self.assertTrue(guard.can_enter())
        guard.update(8000.0)       # ~23.8% drawdown -> breach
        self.assertFalse(guard.can_enter())
        # Latches: even after recovery, new entries stay halted.
        guard.update(10600.0)
        self.assertFalse(guard.can_enter())


if __name__ == "__main__":
    unittest.main()
