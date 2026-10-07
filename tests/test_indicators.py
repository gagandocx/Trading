"""Indicator correctness + causality (no-lookahead) checks."""

import unittest

import _util  # noqa: F401  (sets up sys.path)
from xauusd_bot.features import indicators as ind
from xauusd_bot.data.sample_data import generate_sample


def _mkrows(closes):
    rows = []
    for i, c in enumerate(closes):
        rows.append(
            {
                "timestamp": f"2023-01-01T00:{i:02d}:00",
                "open": c,
                "high": c + 1.0,
                "low": c - 1.0,
                "close": c,
                "volume": 100.0,
            }
        )
    return rows


class TestIndicatorCorrectness(unittest.TestCase):
    def test_simple_returns(self):
        rows = _mkrows([100.0, 110.0, 99.0])
        r = ind.simple_returns(rows, periods=1)
        self.assertIsNone(r[0])
        self.assertAlmostEqual(r[1], 0.10, places=9)
        self.assertAlmostEqual(r[2], (99.0 / 110.0) - 1.0, places=9)

    def test_sma_known_values(self):
        rows = _mkrows([1.0, 2.0, 3.0, 4.0, 5.0])
        sma = ind.sma(rows, window=3)
        # Warm-up positions are None until the window is full.
        self.assertIsNone(sma[0])
        self.assertIsNone(sma[1])
        self.assertAlmostEqual(sma[2], 2.0, places=9)
        self.assertAlmostEqual(sma[3], 3.0, places=9)
        self.assertAlmostEqual(sma[4], 4.0, places=9)

    def test_atr_positive_after_warmup(self):
        rows = generate_sample(120, seed=11)
        a = ind.atr(rows, window=14)
        self.assertEqual(len(a), len(rows))
        self.assertIsNone(a[0])
        tail = [x for x in a[30:] if x is not None]
        self.assertTrue(tail, "ATR should be populated after warm-up")
        self.assertTrue(all(x > 0 for x in tail))

    def test_rsi_bounds(self):
        rows = generate_sample(200, seed=5)
        r = ind.rsi(rows, window=14)
        vals = [x for x in r if x is not None]
        self.assertTrue(vals)
        self.assertTrue(all(0.0 <= x <= 100.0 for x in vals))


class TestIndicatorCausality(unittest.TestCase):
    """Recomputing an indicator on the truncated series rows[:i+1] must give the
    SAME value at index i as computing it on the full series (no lookahead)."""

    def _assert_causal(self, fn, rows, idxs):
        full = fn(rows)
        for i in idxs:
            truncated = fn(rows[: i + 1])
            self.assertEqual(
                len(truncated),
                i + 1,
                "indicator must align 1:1 with its input length",
            )
            a, b = full[i], truncated[i]
            if a is None or b is None:
                self.assertEqual(a, b)
            else:
                self.assertAlmostEqual(a, b, places=9)

    def test_rsi_atr_macd_causal(self):
        rows = generate_sample(300, seed=3)
        idxs = [40, 80, 160, 299]
        self._assert_causal(lambda r: ind.rsi(r, window=14), rows, idxs)
        self._assert_causal(lambda r: ind.atr(r, window=14), rows, idxs)
        self._assert_causal(lambda r: ind.ema(r, span=21), rows, idxs)
        self._assert_causal(
            lambda r: ind.macd(r, fast=12, slow=26, signal=9)["hist"], rows, idxs
        )


if __name__ == "__main__":
    unittest.main()
