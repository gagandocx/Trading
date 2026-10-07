"""Tests for the fetch-mt5 CLI date-window resolution (--days option).

These test ONLY the pure-Python date math in ``_resolve_fetch_window`` and the
argument parser wiring. They never import MetaTrader5 (which is unavailable in
the sandbox and on non-Windows machines).
"""

import unittest
from datetime import datetime, timedelta

import _util  # noqa: F401
from xauusd_bot.cli import _resolve_fetch_window, build_parser


class TestResolveFetchWindow(unittest.TestCase):
    def test_days_365_produces_year_window_up_to_now(self):
        before = datetime.utcnow()
        start, end = _resolve_fetch_window(None, None, 365)
        after = datetime.utcnow()
        # Both bounds are filled in as ISO strings.
        self.assertIsNotNone(start)
        self.assertIsNotNone(end)
        start_dt = datetime.fromisoformat(start)
        end_dt = datetime.fromisoformat(end)
        # end is "now" (within the test's wall-clock window).
        self.assertTrue(before <= end_dt <= after)
        # start is approximately end - 365 days (exact to the second here).
        delta = end_dt - start_dt
        self.assertEqual(delta, timedelta(days=365))

    def test_days_with_explicit_end_anchors_on_end(self):
        start, end = _resolve_fetch_window(None, "2024-06-01T00:00:00", 30)
        self.assertEqual(end, "2024-06-01T00:00:00")
        start_dt = datetime.fromisoformat(start)
        self.assertEqual(start_dt, datetime(2024, 5, 2, 0, 0, 0))

    def test_explicit_start_wins_over_days(self):
        # --start is used verbatim; --days must NOT override it.
        start, end = _resolve_fetch_window("2020-01-01T00:00:00", None, 365)
        self.assertEqual(start, "2020-01-01T00:00:00")
        # end still defaults to ~now because --days was supplied.
        self.assertIsNotNone(end)

    def test_explicit_start_and_end_both_win(self):
        start, end = _resolve_fetch_window(
            "2023-01-01T00:00:00", "2023-02-01T00:00:00", 365
        )
        self.assertEqual(start, "2023-01-01T00:00:00")
        self.assertEqual(end, "2023-02-01T00:00:00")

    def test_no_days_leaves_bounds_untouched(self):
        # Default behavior unchanged when --days is absent.
        self.assertEqual(_resolve_fetch_window(None, None, None), (None, None))
        self.assertEqual(
            _resolve_fetch_window("2021-01-01", None, None), ("2021-01-01", None)
        )


class TestFetchMt5Parser(unittest.TestCase):
    def test_days_option_parsed_as_int(self):
        parser = build_parser()
        args = parser.parse_args(
            ["fetch-mt5", "--symbol", "XAUUSD", "--timeframe", "M5", "--days", "365"]
        )
        self.assertEqual(args.symbol, "XAUUSD")
        self.assertEqual(args.timeframe, "M5")
        self.assertEqual(args.days, 365)

    def test_days_defaults_to_none(self):
        parser = build_parser()
        args = parser.parse_args(["fetch-mt5"])
        self.assertIsNone(args.days)
        self.assertEqual(args.symbol, "XAUUSD")


if __name__ == "__main__":
    unittest.main()
