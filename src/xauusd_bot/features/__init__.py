"""Feature engineering for xauusd_bot.

This package turns a canonical OHLCV candle series (see :mod:`xauusd_bot.data`)
into model-ready features. The design is built around ICT (Inner Circle Trader)
smart-money concepts, with inverse Fair Value Gap (iFVG) retests as the PRIMARY
trade-entry trigger, supported by classic technical indicators and candlestick
patterns.

Submodules
----------
* :mod:`xauusd_bot.features.indicators`  - causal technical indicators.
* :mod:`xauusd_bot.features.patterns`    - causal candlestick-pattern flags.
* :mod:`xauusd_bot.features.ict`         - ICT / smart-money-concept detectors.
* :mod:`xauusd_bot.features.signals`     - iFVG-primary entry-signal generation.
* :mod:`xauusd_bot.features.engineering` - assemble the full feature matrix.

Causality guarantee
--------------------
Every feature/signal value at row ``i`` is computed using ONLY rows ``<= i``.
Swing-based ICT structure carries an explicit confirmation delay: a swing at
index ``j`` is only confirmed/usable at index ``j + swing_lookback``. The sole
intentionally forward-looking component lives in :mod:`xauusd_bot.labeling`
(the triple-barrier label), whose forward window is tracked for purge/embargo.
"""

__all__ = [
    "indicators",
    "patterns",
    "ict",
    "signals",
    "engineering",
]
