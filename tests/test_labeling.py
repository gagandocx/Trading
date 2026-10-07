"""Triple-barrier labeling tests."""

import unittest

import _util  # noqa: F401
from xauusd_bot.labeling.triple_barrier import triple_barrier_labels


def _row(c):
    return {"timestamp": "2023-01-01T00:00:00", "open": c, "high": c + 0.1, "low": c - 0.1, "close": c, "volume": 1.0}


class TestLabeling(unittest.TestCase):
    def test_long_target_hit(self):
        # Entry at 100, ATR=1, target=+2 (102), stop=-1 (99). Price rises to 103.
        rows = [
            {"timestamp": "t0", "open": 100, "high": 100.1, "low": 99.9, "close": 100.0, "volume": 1},
            {"timestamp": "t1", "open": 100, "high": 101.0, "low": 100.0, "close": 100.5, "volume": 1},
            {"timestamp": "t2", "open": 100, "high": 103.0, "low": 100.5, "close": 102.5, "volume": 1},
            {"timestamp": "t3", "open": 102, "high": 103.5, "low": 101.5, "close": 103.0, "volume": 1},
        ]
        atr = [1.0, 1.0, 1.0, 1.0]
        labels, used = triple_barrier_labels(
            rows, atr, target_mult=2.0, stop_mult=1.0, max_horizon=2, directions=["long", "none", "none", "none"]
        )
        self.assertEqual(labels[0], 1)   # target hit first
        self.assertIsNotNone(used[0])

    def test_short_direction_barriers(self):
        # Short entry at 100, target below (98), stop above (101). Price falls.
        rows = [
            {"timestamp": "t0", "open": 100, "high": 100.1, "low": 99.9, "close": 100.0, "volume": 1},
            {"timestamp": "t1", "open": 100, "high": 100.2, "low": 98.5, "close": 99.0, "volume": 1},
            {"timestamp": "t2", "open": 99, "high": 99.2, "low": 97.0, "close": 97.5, "volume": 1},
            {"timestamp": "t3", "open": 97, "high": 97.5, "low": 96.5, "close": 97.0, "volume": 1},
        ]
        atr = [1.0, 1.0, 1.0, 1.0]
        labels, _ = triple_barrier_labels(
            rows, atr, target_mult=2.0, stop_mult=1.0, max_horizon=2, directions=["short", "none", "none", "none"]
        )
        self.assertEqual(labels[0], 1)  # short target (down) hit first -> +1

    def test_values_subset(self):
        rows = [_row(100.0 + (i % 5)) for i in range(60)]
        atr = [1.0] * 60
        labels, _ = triple_barrier_labels(rows, atr, 2.0, 1.0, 10)
        vals = set(l for l in labels if l is not None)
        self.assertTrue(vals.issubset({-1, 0, 1}))

    def test_end_of_series_excluded(self):
        rows = [_row(100.0) for _ in range(30)]
        atr = [1.0] * 30
        max_h = 10
        labels, used = triple_barrier_labels(rows, atr, 2.0, 1.0, max_h)
        # Rows within max_horizon of the end must be unlabeled.
        for i in range(len(rows) - max_h, len(rows)):
            self.assertIsNone(labels[i], f"row {i} should be excluded")
            self.assertIsNone(used[i])

    def test_forward_window_accounting(self):
        # horizon_used must never exceed max_horizon and must be positive on labels.
        rows = [_row(100.0 + (i % 7) * 0.5) for i in range(80)]
        atr = [1.0] * 80
        max_h = 12
        labels, used = triple_barrier_labels(rows, atr, 2.0, 1.0, max_h)
        for i in range(len(rows)):
            if labels[i] is not None:
                self.assertIsNotNone(used[i])
                self.assertGreaterEqual(used[i], 1)
                self.assertLessEqual(used[i], max_h)

    def test_direction_none_unlabeled(self):
        rows = [_row(100.0) for _ in range(20)]
        atr = [1.0] * 20
        labels, _ = triple_barrier_labels(
            rows, atr, 2.0, 1.0, 5, directions=["none"] * 20
        )
        self.assertTrue(all(l is None for l in labels))


if __name__ == "__main__":
    unittest.main()
