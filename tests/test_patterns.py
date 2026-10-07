"""Candlestick-pattern flag correctness."""

import unittest

import _util  # noqa: F401
from xauusd_bot.features import patterns as pat


def _c(o, h, l, cl):
    return {"timestamp": "2023-01-01T00:00:00", "open": o, "high": h, "low": l, "close": cl, "volume": 1.0}


class TestPatterns(unittest.TestCase):
    def test_doji(self):
        # Tiny body relative to a large range.
        rows = [_c(100.0, 105.0, 95.0, 100.2)]
        self.assertTrue(pat.is_doji(rows)[0])
        # Big body -> not a doji.
        rows2 = [_c(100.0, 105.0, 99.0, 104.5)]
        self.assertFalse(pat.is_doji(rows2)[0])

    def test_hammer(self):
        # Long lower wick, small body & upper wick.
        # body = |100.0-100.3| = 0.3; lower = min(o,c)-low = 100.0-95.0 = 5.0 (>= 2*body);
        # upper = high-max(o,c) = 100.3-100.3 = 0.0 (<= body).
        rows = [_c(100.0, 100.3, 95.0, 100.3)]
        self.assertTrue(pat.is_hammer(rows)[0])

    def test_shooting_star(self):
        # body=0.3; upper = 105.0-100.3 = 4.7 (>= 2*body); lower = 100.0-100.0 = 0 (<= body).
        rows = [_c(100.3, 105.0, 100.0, 100.0)]
        self.assertTrue(pat.is_shooting_star(rows)[0])

    def test_bullish_engulfing_first_bar_none(self):
        rows = [
            _c(100.0, 101.0, 98.0, 98.5),   # bearish
            _c(98.0, 102.0, 97.5, 101.5),   # bullish engulfs prev body
        ]
        flags = pat.is_bullish_engulfing(rows)
        self.assertIsNone(flags[0])  # two-bar pattern: bar 0 undefined
        self.assertTrue(flags[1])

    def test_bearish_engulfing(self):
        rows = [
            _c(98.0, 102.0, 97.5, 101.5),   # bullish
            _c(101.5, 102.0, 97.0, 98.0),   # bearish engulfs prev body
        ]
        flags = pat.is_bearish_engulfing(rows)
        self.assertTrue(flags[1])

    def test_all_patterns_keys(self):
        rows = [_c(100.0, 101.0, 99.0, 100.5), _c(100.5, 101.5, 99.5, 101.0)]
        d = pat.all_patterns(rows)
        for key in (
            "body_ratio", "upper_wick_ratio", "lower_wick_ratio", "candle_range",
            "is_doji", "is_hammer", "is_shooting_star",
            "is_bullish_engulfing", "is_bearish_engulfing",
        ):
            self.assertIn(key, d)
            self.assertEqual(len(d[key]), len(rows))


if __name__ == "__main__":
    unittest.main()
