#!/usr/bin/env python3
"""One-command end-to-end pipeline runner.

A thin wrapper around the CLI ``run`` subcommand so a brand-new user can execute a
full backtest on generated sample data with ZERO third-party installs::

    PYTHONPATH=src python3 scripts/run_pipeline.py --sample

``--sample`` (the convenience default here) tells the pipeline to generate and use
the synthetic XAUUSD dataset. Any other CLI ``run`` flags are forwarded, so you
can also point it at your own CSV::

    PYTHONPATH=src python3 scripts/run_pipeline.py --data path/to/your.csv
    PYTHONPATH=src python3 scripts/run_pipeline.py --config configs/default.yaml

It prints a performance report (including max drawdown and Sharpe) and writes
artifacts under ``runs/<timestamp>/``.
"""

from __future__ import annotations

import os
import sys

# Make ``src`` importable whether or not PYTHONPATH was set, so the single command
# works out of the box from a fresh checkout.
_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(os.path.dirname(_HERE), "src")
if os.path.isdir(_SRC) and _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from xauusd_bot.cli import main  # noqa: E402


def _run(argv):
    # Default to --sample when the user passes no data/config of their own, so
    # the zero-setup path "just works".
    forwarded = list(argv)
    if not any(a in ("--data", "--sample", "--config") for a in forwarded):
        forwarded.append("--sample")
    return main(["run"] + forwarded)


if __name__ == "__main__":
    raise SystemExit(_run(sys.argv[1:]))
