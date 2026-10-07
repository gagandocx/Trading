"""End-to-end SMOKE test: the full pipeline runs on generated data stdlib-only."""

import os
import tempfile
import unittest

import _util  # noqa: F401
from xauusd_bot.cli import run_pipeline
from xauusd_bot.config import load_config


class TestEndToEnd(unittest.TestCase):
    def test_full_pipeline_produces_metrics(self):
        cfg = load_config("configs/default.yaml")
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = os.path.join(tmp, "run")
            # use_sample=True generates its own dataset; nothing third-party needed.
            metrics = run_pipeline(cfg, data_path=None, use_sample=True, out_dir=out_dir)

            # Required metric keys present.
            for key in ("total_return", "sharpe", "max_drawdown", "win_rate", "num_trades"):
                self.assertIn(key, metrics)

            # Artifacts written.
            self.assertTrue(os.path.exists(os.path.join(out_dir, "metrics.json")))
            equity_csv = os.path.join(out_dir, "equity_curve.csv")
            equity_png = os.path.join(out_dir, "equity_curve.png")
            self.assertTrue(os.path.exists(equity_csv) or os.path.exists(equity_png))

            # Metrics are sane types.
            self.assertIsInstance(metrics["num_trades"], int)
            self.assertGreaterEqual(metrics["max_drawdown"], 0.0)


if __name__ == "__main__":
    unittest.main()
