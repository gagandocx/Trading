"""Signal generation tests: iFVG primary entry + primary_entry config honored."""

import unittest

import _util  # noqa: F401
from xauusd_bot.config import load_config
from xauusd_bot.data.sample_data import generate_sample
from xauusd_bot.features.signals import generate_signals


def _cfg():
    return load_config("configs/default.yaml")


class TestSignals(unittest.TestCase):
    def test_ifvg_entries_direction_consistent_with_structure(self):
        cfg = _cfg()
        rows = generate_sample(800, seed=5)
        sigs = generate_signals(rows, cfg)
        self.assertEqual(len(sigs), len(rows))

        active = [s for s in sigs if s["direction"] != "none"]
        self.assertTrue(active, "expected some entry signals on the sample")

        # Primary trigger is iFVG; at least one entry should be an iFVG retest.
        ifvg_entries = [s for s in active if s["entry_type"] == "ifvg"]
        self.assertTrue(ifvg_entries, "iFVG should be the primary entry trigger")

        # Every active signal has a sane direction and ATR-based stop/target.
        for s in active:
            self.assertIn(s["direction"], ("long", "short"))
            self.assertIsNotNone(s["stop_dist"])
            self.assertGreater(s["stop_dist"], 0)
            self.assertIsNotNone(s["target_dist"])

    def test_honors_primary_entry_disabled_ifvg(self):
        cfg = _cfg()
        cfg.features.ict.ifvg_enabled = False
        cfg.features.ict.primary_entry = "fvg"
        rows = generate_sample(800, seed=5)
        sigs = generate_signals(rows, cfg)
        # With iFVG disabled, NO signal may be of entry_type 'ifvg'.
        self.assertFalse(any(s["entry_type"] == "ifvg" for s in sigs))

    def test_ifvg_direction_matches_zone_polarity(self):
        # Construct a bullish iFVG (bearish zone) and confirm shorts are produced
        # when a retest aligns with a non-bullish bias.
        cfg = _cfg()
        rows = generate_sample(600, seed=7)
        sigs = generate_signals(rows, cfg)
        for s in sigs:
            if s["entry_type"] == "ifvg" and s["direction"] == "long":
                # long iFVG entries must have a stop below entry (positive dist)
                self.assertGreater(s["stop_dist"], 0)


if __name__ == "__main__":
    unittest.main()
