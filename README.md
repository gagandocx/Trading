# xauusd_bot - an ICT / iFVG research trading bot for XAUUSD (spot gold)

A research-first machine-learning trading bot for **XAUUSD (spot gold)**. It makes
a decision on every candle using **ICT (Inner Circle Trader) smart-money
concepts**. The **primary entry trigger is the inverse Fair Value Gap (iFVG)
retest**, and a machine-learning model acts as a **probability filter** that
decides which of those iFVG entries are worth taking.

Live execution is **DISABLED BY DEFAULT**. This is research and paper-trading
software first.

---

## ⚠️ RISK WARNING - read this first

- **Trading leveraged instruments like spot gold carries a high risk of loss.**
  You can lose some or all of your capital. Only risk money you can afford to lose.
- **No model can reliably predict the next candle.** Markets are noisy and
  adversarial. This bot tilts the odds using disciplined, well-known techniques;
  it does **not** have a crystal ball, and past backtest performance does not
  guarantee future results.
- **Live trading is OFF by default** (`execution.live_trading_enabled: false`,
  `execution.mode: paper`). A hard safety guard refuses to place real orders
  unless you deliberately turn both switches on. See
  [Enabling live trading](#enabling-live-trading-carefully).
- This is **not financial advice**. Use at your own risk.

---

## What this bot actually does (honest framing)

- It **learns from historical price data** using established quant-finance and ICT
  techniques (feature engineering, triple-barrier labeling, walk-forward
  validation, a gradient-boosted classifier).
- It **does NOT scrape the live internet**, read news, or ingest social sentiment.
  Its only input is OHLCV candles (from a CSV or MetaTrader 5).
- The ML model is a **filter**, not an oracle. The *entry idea* is the ICT iFVG
  retest; the model only estimates the probability that a given iFVG entry reaches
  its profit target before its stop, and we skip entries whose probability is too
  low.
- Reported metrics are **honest**: drawdown is always shown and never hidden, and
  the backtest charges realistic spread + commission costs so you don't fool
  yourself.

---

## ICT concepts in plain language

ICT ("Inner Circle Trader") is a popular framework describing how large
institutions ("smart money") push price around to fill their orders. You don't
need to be an expert - here is what the terms mean and how our entry forms.

- **Candle / OHLCV** - one time slice of price: open, high, low, close, and
  volume. We work on M15 (15-minute) candles by default.
- **Swing high / swing low** - a local peak / trough in price. A swing is only
  *confirmed* once enough later candles have formed to prove it was a turning
  point (we wait `swing_lookback` bars; this delay is enforced so we never "see
  the future").
- **BOS (Break of Structure)** - price breaks beyond the most recent swing in the
  direction of the existing trend. It confirms the trend is continuing.
- **CHoCH (Change of Character)** - price breaks a swing *against* the current
  trend. It is the first hint the trend may be flipping (bias changes).
- **Liquidity** - clusters of stop orders. **Buy-side liquidity** sits above equal
  highs; **sell-side liquidity** sits below equal lows. Smart money often spikes
  price into these pools to trigger stops (a **liquidity sweep**) before reversing.
- **Order block** - the last opposing candle right before a strong move / BOS.
  Institutions often leave resting orders there, so price frequently reacts when
  it returns.
- **Premium / discount** - split the current trading range in half. The top half
  is "premium" (expensive - favour selling); the bottom half is "discount"
  (cheap - favour buying). The midpoint is "equilibrium".
- **Killzone** - the times of day when the big moves usually happen (we flag the
  London and New York AM sessions, defined in UTC hours - see
  `features/ict.py` for the exact windows and the UTC assumption).

### FVG, iFVG, and the entry we trade

- **FVG (Fair Value Gap)** - a 3-candle **imbalance**. If candle A's high is below
  candle C's low (with B spiking between them), price moved so fast it left an
  untraded gap between A's high and C's low. That gap is a **bullish FVG** (and the
  mirror image, A's low above C's high, is a **bearish FVG**). Price often returns
  to "rebalance" the gap.
- **iFVG (inverse Fair Value Gap)** - our **primary entry**. When price trades
  *fully through* an existing FVG (e.g. closes below the bottom of a bullish FVG),
  the gap **flips polarity**: old support becomes new resistance (a **bearish
  iFVG**), and vice-versa. The iFVG marks a zone where the market has "changed its
  mind".
- **The entry: an iFVG retest.** After an iFVG forms, we wait for price to come
  **back to retest that zone** (within a small ATR-based tolerance,
  `ifvg_retest_atr_tol`). If the retest **aligns with market-structure bias** (a
  bullish iFVG retest in a non-bearish context → long; a bearish iFVG retest in a
  non-bullish context → short), that bar emits an **entry candidate**. This is the
  "most probable trade" the strategy is built around.
- **Then the model filters it.** For each iFVG entry candidate the trained model
  outputs the probability it hits target before stop. Only candidates clearing
  `backtest.prob_threshold` are actually taken.

If `features.ict.ifvg_enabled` is false or `primary_entry` is changed, the signal
generator falls back gracefully to plain FVG retests and then order-block
proximity - but the recommended, default configuration trades **iFVG retests
first**.

---

## Architecture / module map

```
src/xauusd_bot/
  config.py                 # typed Config dataclasses + layered YAML loader
  compat.py                 # pure-stdlib rolling/ewm/diff numeric helpers + HAS_* flags
  cli.py                    # argparse CLI: run / backtest / make-sample / fetch-mt5
  data/
    sample_data.py          # deterministic synthetic XAUUSD generator
    csv_loader.py           # OHLCV CSV load + clean + strict time sort
    mt5_connector.py        # optional MetaTrader 5 fetcher (import-safe, lazy)
  features/
    indicators.py           # causal RSI/MACD/ATR/Bollinger/EMA/returns/volatility
    patterns.py             # candlestick pattern flags + body/wick geometry
    ict.py                  # ICT core: swings, BOS/CHoCH, FVG, iFVG, OB, liquidity, P/D, killzones
    signals.py              # iFVG-retest PRIMARY entry signals (the trade idea)
    engineering.py          # assemble the model-ready feature matrix
  labeling/
    triple_barrier.py       # ATR triple-barrier labels (direction-aware, forward window tracked)
  models/
    model.py                # Classifier: calibrated LightGBM OR stdlib fallback
    fallback_gbt.py         # pure-stdlib deterministic classifier (sandbox path)
  backtest/
    walk_forward.py         # strictly time-ordered splits with purge/embargo
    engine.py               # event-driven, cost-aware backtest (iFVG entries + model filter)
    metrics.py              # honest metrics (drawdown, Sharpe, profit factor, ...)
  risk/
    risk.py                 # ATR position sizing + drawdown guardrail
  execution/
    live_guard.py           # the live-trading safety switch (refuses by default)
    paper_trader.py         # broker-free paper trading using the same cost model
configs/default.yaml        # XAUUSD defaults; live_trading_enabled: false
scripts/run_pipeline.py     # one-command end-to-end runner (--sample)
data/sample/                # small tracked sample CSV, runnable out of the box
tests/                      # unittest suite incl. an end-to-end smoke test
runs/                       # (gitignored) pipeline artifacts: metrics, equity, model
requirements.txt            # production stack (install on your own machine)
```

The two features/ modules that carry the strategy are **`features/ict.py`**
(detects the smart-money constructs) and **`features/signals.py`** (turns the iFVG
retest into the primary entry signal).

---

## Design principle: graceful degradation

Every heavy dependency (pandas, numpy, scikit-learn, lightgbm, matplotlib,
PyYAML, MetaTrader5) is **optional** and imported lazily behind `try/except`. The
package always imports, and the full pipeline always runs with **only the Python
standard library**. Installing `requirements.txt` simply unlocks the faster,
LightGBM-backed path.

> **Sandbox note.** This project was developed and verified in a network-restricted
> sandbox where the heavy ML stack (pandas/numpy/scikit-learn/LightGBM/matplotlib/
> MetaTrader5) **could not be installed** (`pip` is blocked). Verification therefore
> used the **pure-stdlib fallback path** (a deterministic stdlib classifier instead
> of LightGBM, a CSV equity curve instead of a PNG). On your own machine, run
> `pip install -r requirements.txt` to get the LightGBM-backed results - the code
> auto-selects the heavy path when those packages are present.

---

## Quick start - zero dependencies

Run the whole pipeline on generated data with **nothing but Python 3.9+**
(no installs). From the repository root:

```bash
# One command, end-to-end on a generated sample dataset:
PYTHONPATH=src python scripts/run_pipeline.py --sample
```

> In this sandbox the interpreter is `python3` (bare `python` is not on PATH).
> On your own machine use whichever maps to Python 3.9+ (`python` or `python3`).

This prints a performance report (total return, Sharpe, **max drawdown**, win
rate, number of trades, ...) and writes artifacts under `runs/<timestamp>/`:
`metrics.json`, `equity_curve.csv` (or `.png` if matplotlib is installed), and the
trained `model.json`.

You can also drive the CLI directly:

```bash
# Full pipeline with the default config (generates sample data if none present):
PYTHONPATH=src python -m xauusd_bot.cli run --config configs/default.yaml --sample

# Same thing; 'backtest' is an alias of 'run':
PYTHONPATH=src python -m xauusd_bot.cli backtest --sample

# (Re)generate the small sample CSV:
PYTHONPATH=src python -m xauusd_bot.cli make-sample --out data/sample/XAUUSD_sample.csv --rows 300
```

---

## Running the full stack (your machine)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m xauusd_bot.cli run --config configs/default.yaml --sample
```

With LightGBM + scikit-learn installed, the model backend automatically switches
to a **calibrated LightGBM** classifier, which handles the non-linear
interactions among the ICT/iFVG features far better than the linear stdlib
fallback.

---

## Supplying your own data

Provide any OHLCV CSV; the loader maps common column names case-insensitively
(`time`/`date`/`timestamp`, `open`, `high`, `low`, `close`, `volume`), parses
timestamps, sorts strictly ascending, and validates OHLC invariants.

```bash
PYTHONPATH=src python -m xauusd_bot.cli run --data path/to/your_XAUUSD.csv
```

Or point `data.csv_path` in `configs/default.yaml` at your file. The canonical
schema is:

```
timestamp (ISO-8601 str), open, high, low, close, volume (floats)
```

---

## Plugging in MetaTrader 5 (optional, Windows-oriented)

MetaTrader 5 (MT5) is how you connect a real broker feed. The connector is inert
until you install the package and run on Windows with an MT5 terminal.

1. Install the **MetaTrader 5 terminal** from your broker and log into an account
   (a demo account is perfect for testing).
2. `pip install MetaTrader5` (Windows only; it is in `requirements.txt`).
3. In the terminal, enable **"Allow automated trading" / API access**.
4. Fetch candles to a CSV, then run the pipeline on it:

```bash
python -m xauusd_bot.cli fetch-mt5 --symbol XAUUSD --timeframe M15 \
    --start 2023-01-01 --end 2024-01-01 --out data/mt5_XAUUSD.csv
python -m xauusd_bot.cli run --data data/mt5_XAUUSD.csv
```

See `src/xauusd_bot/data/mt5_connector.py` for details. Importing the package
never requires MetaTrader5 - it is imported lazily, only when you call the
connector.

---

## How we avoid "backtest fantasies"

Naive backtests lie. We defend against the common ways in several places:

- **Strict causality.** Every feature/signal at bar *i* uses only bars `0..i`.
  Swing-based constructs enforce a confirmation delay so a swing at bar *j* is
  only usable at `j + swing_lookback`. The only intentionally forward-looking
  component is the label.
- **Triple-barrier labeling.** Each entry gets an ATR-sized profit target, an
  ATR-sized stop, and a time (vertical) barrier. The label is which barrier is hit
  first (`+1` target, `-1` stop, `0` time), with the barrier orientation matching
  the trade direction (shorts invert target/stop). Rows whose forward window would
  run past the end of the data are left **unlabeled** and excluded from training.
- **Walk-forward validation with purge/embargo.** We train on the past and test on
  the future, never shuffling. Between every train block and its test block we
  insert a **purge/embargo gap of at least the label horizon**, so a training
  row's forward-looking label window can never overlap the test set (no leakage).
- **Realistic costs.** The backtest charges the configured **spread** (half on
  entry, half on exit) plus **commission per lot** on every round trip. A
  zero-move round trip therefore loses money - exactly the modeled cost - which is
  unit-tested. This keeps marginal, over-traded strategies honest.
- **Honest metrics.** Drawdown (magnitude and duration) is always reported, and
  the risk module can halt new entries once drawdown breaches `max_drawdown_pct`.

---

## Enabling live trading (carefully)

**Live trading is off by default and should stay that way until you have fully
paper-traded the strategy and understand the risk.**

A single guard, `xauusd_bot.execution.live_guard.ensure_live_allowed(config)`,
sits in front of any real order routing. It **refuses** (raises
`LiveTradingDisabled`) unless **both** of these are set:

```yaml
execution:
  live_trading_enabled: true   # ⚠️ you are opting in to real financial risk
  mode: live                   # ⚠️ must be 'live', not 'paper'
```

Even with both flags on, actual broker order routing
(`live_guard.route_order_mt5`) is left as a deliberate stub you must wire to your
broker's MetaTrader5 `order_send` yourself - on a Windows machine, with an account
you control, after you have paper-traded first.

> ⚠️ **Repeat warning:** turning these on puts **real money at risk**. There is no
> warranty. Start on a demo account. You are solely responsible for any losses.

Day-to-day, use the broker-free **paper trader**
(`xauusd_bot.execution.paper_trader.PaperTrader`), which simulates fills against
incoming candles using the exact same cost model as the backtest - no broker and
no live-guard needed.

---

## Development & testing

```bash
# Byte-compile (catches syntax errors):
python -m compileall src

# Run the full test suite (stdlib only - no third-party packages required):
python -m unittest discover -s tests -p 'test_*.py' -v
```

The suite covers indicators (correctness + causality), candlestick patterns, the
ICT detectors (FVG, iFVG polarity flip, swing confirmation delay, no-lookahead),
the iFVG entry signals, triple-barrier labeling, walk-forward purge/embargo, the
cost-aware backtest and model filter, risk sizing + drawdown guard, the
live-trading guard, and an **end-to-end smoke test** that runs the whole pipeline
on generated data and asserts a metrics dict with `total_return`, `sharpe`,
`max_drawdown`, `win_rate`, and `num_trades`.

---

## Status / safety

Live trading is **off by default** (`execution.live_trading_enabled: false`,
`execution.mode: paper`). This is research software, not financial advice. Trade
at your own risk.
