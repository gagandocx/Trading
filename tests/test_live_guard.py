"""Live-trading guard tests: real orders refused unless explicitly enabled."""

import unittest

import _util  # noqa: F401
from xauusd_bot.config import load_config
from xauusd_bot.execution.live_guard import (
    LiveTradingDisabled,
    ensure_live_allowed,
    is_live_allowed,
    route_order_mt5,
)


class TestLiveGuard(unittest.TestCase):
    def test_default_config_refuses(self):
        cfg = load_config("configs/default.yaml")
        # Default config ships with live trading OFF.
        self.assertFalse(is_live_allowed(cfg))
        with self.assertRaises(LiveTradingDisabled):
            ensure_live_allowed(cfg)

    def test_enabled_but_paper_mode_refuses(self):
        cfg = load_config("configs/default.yaml")
        cfg.execution.live_trading_enabled = True
        cfg.execution.mode = "paper"  # still not 'live'
        self.assertFalse(is_live_allowed(cfg))
        with self.assertRaises(LiveTradingDisabled):
            ensure_live_allowed(cfg)

    def test_both_flags_required_to_allow(self):
        cfg = load_config("configs/default.yaml")
        cfg.execution.live_trading_enabled = True
        cfg.execution.mode = "live"
        self.assertTrue(is_live_allowed(cfg))
        # Now the guard permits (returns None, does not raise).
        self.assertIsNone(ensure_live_allowed(cfg))

    def test_route_order_refused_when_disabled(self):
        cfg = load_config("configs/default.yaml")
        with self.assertRaises(LiveTradingDisabled):
            route_order_mt5(cfg, {"symbol": "XAUUSD", "lots": 0.1})


if __name__ == "__main__":
    unittest.main()
