"""Walk-forward split tests: strict ordering + purge/embargo gap."""

import unittest

import _util  # noqa: F401
from xauusd_bot.backtest.walk_forward import walk_forward_splits


class TestWalkForward(unittest.TestCase):
    def test_strict_ordering_and_purge(self):
        n = 2000
        horizon = 24
        embargo = 10
        folds = walk_forward_splits(
            n=n, train_size=500, test_size=200, embargo=embargo, horizon=horizon, mode="expanding"
        )
        self.assertTrue(folds, "expected at least one fold")
        gap = max(embargo, horizon)
        for train_idx, test_idx in folds:
            self.assertTrue(train_idx and test_idx)
            # Train strictly precedes test.
            self.assertLess(max(train_idx), min(test_idx))
            # Test indices contiguous and increasing.
            self.assertEqual(test_idx, list(range(test_idx[0], test_idx[-1] + 1)))
            # No train index may fall within [test_start - horizon, test_end].
            test_start = min(test_idx)
            test_end = max(test_idx)
            for t in train_idx:
                self.assertFalse(test_start - horizon <= t <= test_end)
            # The gap between last train and first test is at least the horizon.
            self.assertGreaterEqual(test_start - max(train_idx), gap)

    def test_rolling_fixed_window(self):
        folds = walk_forward_splits(
            n=1500, train_size=400, test_size=150, embargo=20, horizon=24, mode="rolling"
        )
        self.assertTrue(folds)
        for train_idx, test_idx in folds:
            self.assertLessEqual(len(train_idx), 400)
            self.assertLess(max(train_idx), min(test_idx))

    def test_empty_when_insufficient_data(self):
        self.assertEqual(walk_forward_splits(n=10, train_size=500, test_size=200, embargo=10, horizon=24), [])


if __name__ == "__main__":
    unittest.main()
