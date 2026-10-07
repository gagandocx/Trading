"""Config loader tests: typed coercion and cross-section invariants."""

import unittest

import _util  # noqa: F401
from xauusd_bot.config import from_dict, load_config


class TestConfigLoad(unittest.TestCase):
    def test_default_config_loads(self):
        cfg = load_config("configs/default.yaml")
        # The default ships both ATR windows equal (the invariant below).
        self.assertEqual(cfg.features.atr_window, cfg.labeling.atr_window)
        # Live trading must stay off by default.
        self.assertFalse(cfg.execution.live_trading_enabled)


class TestAtrWindowInvariant(unittest.TestCase):
    def test_equal_atr_windows_load_ok(self):
        cfg = from_dict(
            {
                "features": {"atr_window": 20},
                "labeling": {"atr_window": 20},
            }
        )
        self.assertEqual(cfg.features.atr_window, 20)
        self.assertEqual(cfg.labeling.atr_window, 20)

    def test_mismatched_atr_windows_raise(self):
        with self.assertRaises(ValueError) as ctx:
            from_dict(
                {
                    "features": {"atr_window": 20},
                    "labeling": {"atr_window": 14},
                }
            )
        msg = str(ctx.exception)
        # The error must name BOTH keys so the fix is obvious.
        self.assertIn("features.atr_window", msg)
        self.assertIn("labeling.atr_window", msg)

    def test_defaults_satisfy_invariant(self):
        # Building from an empty mapping uses dataclass defaults (both 14).
        cfg = from_dict({})
        self.assertEqual(cfg.features.atr_window, cfg.labeling.atr_window)


if __name__ == "__main__":
    unittest.main()
