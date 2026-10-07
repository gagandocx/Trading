"""Command-line entry point wiring the full research pipeline.

Subcommands
-----------
* ``run``        - full pipeline: ingest -> features -> signals -> label ->
                   walk-forward train/backtest -> metrics report -> artifacts.
* ``backtest``   - alias for ``run`` (same end-to-end flow; kept for clarity).
* ``make-sample``- (re)generate the synthetic sample CSV.
* ``fetch-mt5``  - OPTIONAL: pull candles from a MetaTrader 5 terminal to CSV.

Both ``run`` and ``backtest`` accept ``--config`` and ``--data``; ``--data``
defaults to the config's ``data.csv_path`` and is generated on the fly if absent.
Artifacts (``metrics.json``, ``equity_curve.csv`` or ``.png``, and the trained
model) are written under ``runs/<timestamp>/``.

Run it either way::

    python -m xauusd_bot.cli run --config configs/default.yaml
    python -m xauusd_bot.cli run --sample          # generate + use sample data

The pipeline is fully runnable with ONLY the Python standard library: when
LightGBM/pandas/matplotlib are absent, the stdlib fallback paths kick in.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional, Sequence

from .config import Config, load_config


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------
def _load_candles(cfg: Config, data_path: Optional[str], use_sample: bool) -> List[Dict]:
    """Load candles from ``data_path``/config, generating a sample if needed."""
    from .data.csv_loader import load_candles
    from .data.sample_data import write_sample_csv

    path = data_path or cfg.data.csv_path
    if use_sample or not os.path.exists(path):
        # Generate a larger sample dataset so a brand-new user can run with zero
        # setup. We write it to a gitignored generated/ dir so the small tracked
        # sample CSV (data/sample/XAUUSD_sample.csv) is never clobbered.
        rows = cfg.backtest.train_size + cfg.backtest.test_size + cfg.labeling.horizon + 50
        rows = max(rows, 700)
        gen_path = os.path.join("data", "generated", "XAUUSD_generated.csv")
        print(f"[data] generating sample ({rows} rows) -> {gen_path}")
        write_sample_csv(gen_path, n_rows=rows, seed=7)
        path = gen_path
    print(f"[data] loading candles from {path}")
    return load_candles(path)


def _build_training_table(candles, cfg):
    """Build features, signals, and triple-barrier labels aligned by index.

    Returns ``(feature_matrix, signals, labels, horizon_used, feature_names)``.
    """
    from .features.engineering import build_feature_matrix
    from .features.indicators import atr
    from .features.signals import generate_signals
    from .labeling.triple_barrier import triple_barrier_labels

    fm = build_feature_matrix(candles, cfg)
    feature_names = list(getattr(fm, "feature_names", []))
    signals = generate_signals(candles, cfg)
    directions = [s["direction"] for s in signals]

    atr_series = atr(candles, window=cfg.labeling.atr_window)
    labels, horizon_used = triple_barrier_labels(
        candles,
        atr_series,
        target_mult=cfg.labeling.target_atr_mult,
        stop_mult=cfg.labeling.stop_atr_mult,
        max_horizon=cfg.labeling.horizon,
        directions=directions,
    )
    return fm, signals, labels, horizon_used, feature_names


def _row_vector(fm_row, feature_names) -> List[float]:
    """Extract a feature vector in ``feature_names`` order (None -> 0.0)."""
    out = []
    for name in feature_names:
        v = fm_row.get(name) if isinstance(fm_row, dict) else None
        out.append(0.0 if v is None else float(v))
    return out


def run_pipeline(cfg: Config, data_path: Optional[str], use_sample: bool, out_dir: str) -> Dict:
    """Execute the full pipeline and return the metrics dict.

    ingest -> features -> signals -> triple-barrier labels -> walk-forward folds
    (train a probability FILTER per fold) -> cost-aware backtest on the iFVG/ICT
    entries -> metrics + artifacts.
    """
    from .backtest.engine import run_backtest
    from .backtest.metrics import compute_metrics, report, save_equity_curve
    from .backtest.walk_forward import walk_forward_splits
    from .models.model import Classifier

    candles = _load_candles(cfg, data_path, use_sample)
    n = len(candles)
    if n == 0:
        raise RuntimeError("no candles loaded; cannot run the pipeline")

    print(f"[features] building feature matrix + ICT/iFVG signals for {n} bars")
    fm, signals, labels, horizon_used, feature_names = _build_training_table(candles, cfg)

    # Walk-forward folds sized to the data (shrink windows for small samples).
    train_size = min(cfg.backtest.train_size, max(50, int(n * 0.6)))
    test_size = min(cfg.backtest.test_size, max(20, int(n * 0.2)))
    folds = walk_forward_splits(
        n=n,
        train_size=train_size,
        test_size=test_size,
        embargo=cfg.backtest.embargo,
        horizon=cfg.labeling.horizon,
        mode="expanding",
    )
    if not folds:
        # Fall back to a single split so even tiny samples produce a backtest.
        gap = max(cfg.backtest.embargo, cfg.labeling.horizon)
        split = max(1, n - test_size)
        train_idx = list(range(0, max(1, split - gap)))
        test_idx = list(range(split, n))
        folds = [(train_idx, test_idx)] if test_idx else []
    print(f"[walk-forward] {len(folds)} fold(s); train~{train_size} test~{test_size}")

    # Per-bar probability of the signalled trade reaching target (+1), filled by
    # the model trained on each fold's PAST (purged/embargoed) rows.
    probabilities: List[Optional[float]] = [None] * n
    model = None
    for fold_i, (train_idx, test_idx) in enumerate(folds):
        X_train, y_train = [], []
        for i in train_idx:
            if i >= len(labels):
                continue
            lbl = labels[i]
            if lbl is None:
                continue
            row = fm[i]
            if isinstance(row, dict) and row.get("warmup"):
                continue
            X_train.append(_row_vector(row, feature_names))
            y_train.append(int(lbl))

        if len(set(y_train)) < 2 or len(X_train) < 10:
            # Not enough labelled signal to train a filter -> let trades through.
            for i in test_idx:
                probabilities[i] = 1.0
            continue

        model = Classifier.from_config(cfg)
        model.fit(X_train, y_train)
        X_test = [_row_vector(fm[i], feature_names) for i in test_idx]
        probs = model.prob_for(X_test, 1)  # P(target hit)
        for j, i in enumerate(test_idx):
            probabilities[i] = probs[j]

    test_indices = sorted({i for _, test in folds for i in test})
    print(f"[backtest] running cost-aware backtest over {len(test_indices)} test bars")
    result = run_backtest(candles, signals, probabilities, cfg, test_indices=test_indices)

    metrics = compute_metrics(result)
    print()
    print(report(result))
    print()

    # --- artifacts ---------------------------------------------------------
    os.makedirs(out_dir, exist_ok=True)
    metrics_path = os.path.join(out_dir, "metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as fh:
        json.dump(metrics, fh, indent=2, default=str)
    equity_written = save_equity_curve(
        result,
        path_png=os.path.join(out_dir, "equity_curve.png"),
        path_csv=os.path.join(out_dir, "equity_curve.csv"),
    )
    if model is not None:
        try:
            model_path = os.path.join(out_dir, "model.json")
            model.save(model_path)
            print(f"[artifacts] model -> {model_path}")
        except Exception as exc:  # pragma: no cover - persistence is best-effort
            print(f"[artifacts] model not saved: {exc}")
    print(f"[artifacts] metrics -> {metrics_path}")
    print(f"[artifacts] equity  -> {equity_written}")

    return metrics


# ---------------------------------------------------------------------------
# Subcommand handlers
# ---------------------------------------------------------------------------
def _timestamped_run_dir(base: str = "runs") -> str:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(base, stamp)


def cmd_run(args) -> int:
    cfg = load_config(args.config)
    out_dir = args.out or _timestamped_run_dir()
    run_pipeline(cfg, data_path=args.data, use_sample=args.sample, out_dir=out_dir)
    return 0


def cmd_make_sample(args) -> int:
    from .data.sample_data import write_sample_csv

    path = write_sample_csv(args.out, n_rows=args.rows, seed=args.seed)
    print(f"wrote {args.rows} sample rows to {path}")
    return 0


def cmd_fetch_mt5(args) -> int:  # pragma: no cover - requires MetaTrader5 + terminal
    import csv

    from .data.mt5_connector import fetch_candles

    candles = fetch_candles(
        symbol=args.symbol,
        timeframe=args.timeframe,
        start=args.start,
        end=args.end,
    )
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["timestamp", "open", "high", "low", "close", "volume"])
        writer.writeheader()
        for c in candles:
            writer.writerow(c)
    print(f"fetched {len(candles)} candles -> {args.out}")
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="xauusd_bot",
        description="XAUUSD ICT/iFVG research bot - pipeline runner.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    def add_run_like(name: str, help_text: str):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--config", default="configs/default.yaml", help="path to the YAML config")
        p.add_argument("--data", default=None, help="path to an OHLCV CSV (defaults to config csv_path)")
        p.add_argument("--sample", action="store_true", help="generate + use the synthetic sample dataset")
        p.add_argument("--out", default=None, help="output artifacts directory (default runs/<timestamp>)")
        p.set_defaults(func=cmd_run)
        return p

    add_run_like("run", "run the full pipeline end-to-end")
    add_run_like("backtest", "run the full pipeline (alias of run)")

    ps = sub.add_parser("make-sample", help="generate the synthetic sample CSV")
    ps.add_argument("--out", default="data/sample/XAUUSD_sample.csv")
    ps.add_argument("--rows", type=int, default=300)
    ps.add_argument("--seed", type=int, default=7)
    ps.set_defaults(func=cmd_make_sample)

    pm = sub.add_parser("fetch-mt5", help="OPTIONAL: fetch candles from MetaTrader 5")
    pm.add_argument("--symbol", default="XAUUSD")
    pm.add_argument("--timeframe", default="M15")
    pm.add_argument("--start", default=None)
    pm.add_argument("--end", default=None)
    pm.add_argument("--out", default="data/mt5_candles.csv")
    pm.set_defaults(func=cmd_fetch_mt5)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
