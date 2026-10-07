"""ICT detector tests: FVG, iFVG polarity flip, swing confirmation delay, causality."""

import unittest

import _util  # noqa: F401
from xauusd_bot.data.sample_data import generate_sample
from xauusd_bot.features import ict
from xauusd_bot.features.indicators import atr


def _c(ts, o, h, l, cl):
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": cl, "volume": 1.0}


class TestFVG(unittest.TestCase):
    def test_bullish_fvg_on_hand_built_imbalance(self):
        # Three candles where high[0] < low[2] -> a bullish FVG (gap left unfilled).
        rows = [
            _c("2023-01-01T00:00:00", 100.0, 101.0, 99.5, 100.5),   # i-2: high=101
            _c("2023-01-01T00:15:00", 101.0, 104.0, 100.8, 103.5),  # i-1: strong up
            _c("2023-01-01T00:30:00", 103.5, 106.0, 102.0, 105.0),  # i: low=102 > 101
        ]
        fvgs = ict.detect_fvgs(rows, atr_series=None, min_gap_atr=0.0)
        self.assertTrue(fvgs, "expected at least one FVG")
        bull = [f for f in fvgs if f["type"] == "bullish"]
        self.assertTrue(bull)
        g = bull[0]
        self.assertEqual(g["created_index"], 2)  # recorded on completing bar
        self.assertAlmostEqual(g["bottom"], 101.0)  # high[i-2]
        self.assertAlmostEqual(g["top"], 102.0)     # low[i]

    def test_bearish_fvg(self):
        rows = [
            _c("2023-01-01T00:00:00", 105.0, 106.0, 104.0, 104.5),  # i-2: low=104
            _c("2023-01-01T00:15:00", 104.0, 104.2, 101.0, 101.5),  # i-1: strong down
            _c("2023-01-01T00:30:00", 101.5, 103.0, 100.0, 100.5),  # i: high=103 < 104
        ]
        fvgs = ict.detect_fvgs(rows, atr_series=None, min_gap_atr=0.0)
        bear = [f for f in fvgs if f["type"] == "bearish"]
        self.assertTrue(bear)
        self.assertEqual(bear[0]["created_index"], 2)


class TestIFVG(unittest.TestCase):
    def test_polarity_flip_on_constructed_sequence(self):
        # Build a bullish FVG, then a later close BELOW its bottom flips it to a
        # bearish iFVG.
        rows = [
            _c("2023-01-01T00:00:00", 100.0, 101.0, 99.5, 100.5),   # 0: high=101
            _c("2023-01-01T00:15:00", 101.0, 104.0, 100.8, 103.5),  # 1
            _c("2023-01-01T00:30:00", 103.5, 106.0, 102.0, 105.0),  # 2: bullish FVG [101,102]
            _c("2023-01-01T00:45:00", 105.0, 105.5, 103.0, 103.2),  # 3
            _c("2023-01-01T01:00:00", 103.0, 103.5, 100.0, 100.4),  # 4: close 100.4 < 101 -> flip
        ]
        ifvgs = ict.detect_ifvgs(rows, atr_series=None, min_gap_atr=0.0)
        self.assertTrue(ifvgs, "expected an iFVG after price traded through the FVG")
        flip = ifvgs[0]
        self.assertEqual(flip["type"], "bearish")  # bullish FVG -> bearish iFVG
        self.assertEqual(flip["source_fvg_index"], 2)
        self.assertEqual(flip["created_index"], 4)  # flip bar
        self.assertGreater(flip["created_index"], flip["source_fvg_index"])


class TestSwingConfirmationDelay(unittest.TestCase):
    def test_swing_confirmed_at_j_plus_lookback(self):
        lookback = 3
        rows = generate_sample(120, seed=9)
        conf_high, conf_low, hi_idx, lo_idx = ict.swing_points(rows, lookback=lookback)
        # Every confirmed swing must be reported exactly ``lookback`` bars after
        # the originating swing bar (never earlier -> no lookahead).
        found_any = False
        for conf_at, raw in enumerate(hi_idx):
            if raw is not None:
                self.assertEqual(conf_at, raw + lookback)
                found_any = True
        for conf_at, raw in enumerate(lo_idx):
            if raw is not None:
                self.assertEqual(conf_at, raw + lookback)
                found_any = True
        self.assertTrue(found_any, "expected some swings on the sample")


class TestICTCausality(unittest.TestCase):
    def test_fvg_detection_truncation_no_lookahead(self):
        # FVGs detected on rows[:i+1] must match (by created_index/top/bottom) the
        # FVGs the full series reports with created_index <= i.
        rows = generate_sample(200, seed=4)
        i = 150
        full = [f for f in ict.detect_fvgs(rows, None, 0.0) if f["created_index"] <= i]
        trunc = ict.detect_fvgs(rows[: i + 1], None, 0.0)
        key = lambda g: (g["created_index"], round(g["top"], 6), round(g["bottom"], 6), g["type"])
        self.assertEqual(sorted(map(key, full)), sorted(map(key, trunc)))

    def test_market_structure_bias_causal(self):
        rows = generate_sample(200, seed=4)
        full = ict.market_structure(rows, lookback=5)["bias"]
        for i in (60, 120, 199):
            trunc = ict.market_structure(rows[: i + 1], lookback=5)["bias"]
            self.assertEqual(full[i], trunc[i])


if __name__ == "__main__":
    unittest.main()
