"""Assemble the full, model-ready feature matrix.

``build_feature_matrix(candles, config)`` composes:
  * classic technical indicators (:mod:`indicators`),
  * candlestick patterns (:mod:`patterns`),
  * ICT / smart-money-concept features (:mod:`ict`),
  * the iFVG / structure signal context (:mod:`signals`),
  * lagged windows of selected features,

into a feature table. When pandas is available a ``DataFrame`` is returned;
otherwise a ``list[dict]`` of rows (aligned by index) is returned - the two are
information-equivalent. The deterministic, ordered feature-name list is attached
as ``.feature_names`` (and returned by :func:`feature_names`).

Causality: every column is causal (see each source module). Warm-up rows that
contain any ``None`` are flagged via the ``warmup`` column so the training loop
can drop them. The sole forward-looking signal (the triple-barrier label) lives
in :mod:`xauusd_bot.labeling`, NOT here.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from .. import compat
from . import ict as ict_mod
from . import indicators as ind
from . import patterns as pat
from .signals import generate_signals

Candle = Dict[str, object]


class FeatureMatrix(list):
    """A ``list[dict]`` of feature rows carrying its ordered feature-name list.

    Behaves like a plain list (so ``len(X)`` is the row count) but also exposes
    ``.feature_names`` for the deterministic ordered column list.
    """

    feature_names: List[str] = []


def _lagged(series: List[Optional[float]], lag: int) -> List[Optional[float]]:
    """Shift a series forward by ``lag`` bars (value at i is series[i-lag]).

    Causal: references only past values. Leading positions are ``None``.
    """
    n = len(series)
    out: List[Optional[float]] = [None] * n
    for i in range(lag, n):
        out[i] = series[i - lag]
    return out


def _b2f(v: Optional[bool]) -> Optional[float]:
    """Encode a tri-state bool flag as 1.0 / 0.0 / None."""
    if v is None:
        return None
    return 1.0 if v else 0.0


def build_feature_matrix(candles: Sequence[Candle], config):
    """Build the feature matrix for ``candles`` under ``config``.

    Returns a :class:`FeatureMatrix` (list of dict rows) with ``.feature_names``.
    If pandas is installed the same data is returned as a ``DataFrame`` with an
    attached ``feature_names`` attribute.
    """
    rows = list(candles)
    n = len(rows)
    fcfg = config.features
    icfg = fcfg.ict

    columns: "Dict[str, List[Optional[float]]]" = {}

    # --- Returns & volatility -------------------------------------------------
    for w in fcfg.return_windows:
        columns[f"ret_{w}"] = ind.simple_returns(rows, periods=w)
        columns[f"logret_{w}"] = ind.log_returns(rows, periods=w)
    columns["volatility"] = ind.rolling_volatility(rows, window=fcfg.bb_window)

    # --- Moving averages (normalised distance of close to each EMA) ----------
    close = ind.closes(rows)
    for span in fcfg.ema_windows:
        e = ind.ema(rows, span=span)
        columns[f"ema_{span}_dist"] = [
            None if (e[i] is None or close[i] is None or e[i] == 0)
            else (close[i] - e[i]) / e[i]
            for i in range(n)
        ]

    # --- Oscillators ----------------------------------------------------------
    columns["rsi"] = ind.rsi(rows, window=fcfg.rsi_window)
    macd = ind.macd(rows, fast=fcfg.macd_fast, slow=fcfg.macd_slow, signal=fcfg.macd_signal)
    columns["macd"] = macd["macd"]
    columns["macd_signal"] = macd["signal"]
    columns["macd_hist"] = macd["hist"]

    # --- ATR (also used to ATR-normalise several ICT distances) --------------
    atr_series = ind.atr(rows, window=fcfg.atr_window)
    columns["atr"] = atr_series

    # --- Bollinger & channels -------------------------------------------------
    bb = ind.bollinger_bands(rows, window=fcfg.bb_window, num_std=fcfg.bb_std)
    columns["bb_pctb"] = bb["pctb"]
    columns["bb_bandwidth"] = bb["bandwidth"]
    columns["channel_pos"] = ind.channel_position(rows, window=fcfg.bb_window)

    # --- Candlestick patterns -------------------------------------------------
    pats = pat.all_patterns(rows)
    for name, series in pats.items():
        if name in ("body_ratio", "upper_wick_ratio", "lower_wick_ratio", "candle_range"):
            columns[name] = series  # already numeric
        else:
            columns[name] = [_b2f(v) for v in series]

    # --- ICT: market structure ------------------------------------------------
    structure = ict_mod.market_structure(rows, lookback=icfg.swing_lookback)
    columns["ms_bias"] = [float(x) for x in structure["bias"]]
    columns["ms_bos"] = [float(x) for x in structure["bos"]]
    columns["ms_choch"] = [float(x) for x in structure["choch"]]
    columns["bars_since_bos"] = [
        None if x is None else float(x) for x in structure["bars_since_bos"]
    ]
    columns["bars_since_choch"] = [
        None if x is None else float(x) for x in structure["bars_since_choch"]
    ]

    # --- ICT: killzones -------------------------------------------------------
    kz = ict_mod.killzone_flags(rows, icfg.killzones)
    columns["in_killzone"] = [_b2f(v) for v in kz["in_killzone"]]

    # --- ICT: premium / discount ---------------------------------------------
    pd_zone = ict_mod.premium_discount(rows, window=icfg.liquidity_lookback)
    columns["pd_position"] = pd_zone["pd_position"]
    columns["premium"] = [_b2f(v) for v in pd_zone["premium"]]

    # --- ICT: liquidity -------------------------------------------------------
    liq = ict_mod.detect_liquidity(
        rows,
        atr_series=atr_series,
        lookback=icfg.liquidity_lookback,
        equal_tol_atr=icfg.equal_level_tol_atr,
        swing_lookback=icfg.swing_lookback,
    )
    columns["buyside_sweep"] = [_b2f(v) for v in liq["buyside_sweep"]]
    columns["sellside_sweep"] = [_b2f(v) for v in liq["sellside_sweep"]]
    columns["dist_to_buyside"] = _atr_norm_distance(close, liq["buyside_level"], atr_series)
    columns["dist_to_sellside"] = _atr_norm_distance(close, liq["sellside_level"], atr_series)

    # --- ICT: FVG / iFVG distance context (ATR-normalised) -------------------
    fvgs = ict_mod.detect_fvgs(rows, atr_series, min_gap_atr=icfg.fvg_min_gap_atr)
    ifvgs = (
        ict_mod.detect_ifvgs(rows, atr_series, min_gap_atr=icfg.fvg_min_gap_atr)
        if icfg.ifvg_enabled
        else []
    )
    columns["dist_to_fvg"] = _dist_to_nearest_zone(rows, fvgs, atr_series)
    columns["dist_to_ifvg"] = _dist_to_nearest_zone(rows, ifvgs, atr_series)

    # --- Signal context (iFVG-primary entries) -------------------------------
    sigs = generate_signals(rows, config)
    columns["is_in_ifvg_retest"] = [
        1.0 if (s["entry_type"] == "ifvg" and s["direction"] != "none") else 0.0
        for s in sigs
    ]
    columns["signal_dir"] = [
        1.0 if s["direction"] == "long" else (-1.0 if s["direction"] == "short" else 0.0)
        for s in sigs
    ]
    columns["entry_is_primary"] = [
        1.0 if (s["direction"] != "none" and s["entry_type"] == icfg.primary_entry) else 0.0
        for s in sigs
    ]

    # --- Lagged windows of selected features ---------------------------------
    lag_sources = ["ret_1", "rsi", "macd_hist", "ms_bias", "atr"]
    lags = getattr(fcfg, "return_windows", [1, 5, 10])
    for src in lag_sources:
        if src not in columns:
            continue
        for lag in lags:
            columns[f"{src}_lag{lag}"] = _lagged(columns[src], lag)

    # --- Deterministic ordered feature-name list -----------------------------
    feature_order = _ordered_feature_names(columns, fcfg, lag_sources, lags)

    # --- Build rows + warm-up flag -------------------------------------------
    out_rows: List[Dict[str, object]] = []
    for i in range(n):
        rec: Dict[str, object] = {
            "index": i,
            "timestamp": rows[i].get("timestamp") if isinstance(rows[i], dict) else None,
            "close": close[i],
        }
        warmup = False
        for name in feature_order:
            val = columns[name][i]
            rec[name] = val
            if val is None:
                warmup = True
        rec["warmup"] = warmup
        out_rows.append(rec)

    if compat.HAS_PANDAS:  # pragma: no cover - exercised only with pandas installed
        try:
            import pandas as pd  # type: ignore

            df = pd.DataFrame(out_rows)
            df.feature_names = feature_order  # type: ignore[attr-defined]
            return df
        except Exception:
            pass

    fm = FeatureMatrix(out_rows)
    fm.feature_names = feature_order
    return fm


def feature_names(config) -> List[str]:
    """Return the deterministic ordered feature-name list for ``config``.

    Builds the list without needing data by reproducing the same ordering logic.
    """
    # Build on a tiny stub so the ordering mirrors build_feature_matrix exactly.
    from ..data.sample_data import generate_sample

    sample = generate_sample(5, seed=0)
    fm = build_feature_matrix(sample, config)
    return list(getattr(fm, "feature_names", []))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _atr_norm_distance(close, level, atr_series) -> List[Optional[float]]:
    """ATR-normalised signed distance from close to a per-bar level."""
    n = len(close)
    out: List[Optional[float]] = [None] * n
    for i in range(n):
        if close[i] is None or level[i] is None:
            continue
        a = atr_series[i] if i < len(atr_series) else None
        if a is None or a <= 0:
            continue
        out[i] = (close[i] - level[i]) / a
    return out


def _dist_to_nearest_zone(rows, zones, atr_series) -> List[Optional[float]]:
    """ATR-normalised distance from close to the nearest zone active at bar i.

    A zone is "active" at bar ``i`` when ``created_index <= i``. Distance is 0 when
    the close sits inside the zone band; otherwise the gap to the nearest edge.
    Causal: only zones created at or before ``i`` are considered.
    """
    close = ind.closes(rows)
    n = len(rows)
    out: List[Optional[float]] = [None] * n
    # Zones sorted by creation for a simple forward scan.
    zones_sorted = sorted(zones, key=lambda z: int(z["created_index"]))
    for i in range(n):
        if close[i] is None:
            continue
        a = atr_series[i] if i < len(atr_series) else None
        if a is None or a <= 0:
            continue
        best = None
        for z in zones_sorted:
            if int(z["created_index"]) > i:
                break
            top = float(z["top"])
            bottom = float(z["bottom"])
            if bottom <= close[i] <= top:
                d = 0.0
            elif close[i] > top:
                d = close[i] - top
            else:
                d = bottom - close[i]
            if best is None or d < best:
                best = d
        if best is not None:
            out[i] = best / a
    return out


def _ordered_feature_names(columns, fcfg, lag_sources, lags) -> List[str]:
    """Produce a stable, deterministic ordering of feature columns.

    The order groups features logically (returns -> MAs -> oscillators -> vol ->
    bands -> patterns -> ICT structure -> ICT zones/liquidity -> signal context ->
    lags) and is fully determined by config, so it is reproducible across runs.
    """
    order: List[str] = []

    for w in fcfg.return_windows:
        order += [f"ret_{w}", f"logret_{w}"]
    order.append("volatility")
    for span in fcfg.ema_windows:
        order.append(f"ema_{span}_dist")
    order += ["rsi", "macd", "macd_signal", "macd_hist", "atr"]
    order += ["bb_pctb", "bb_bandwidth", "channel_pos"]
    order += [
        "body_ratio", "upper_wick_ratio", "lower_wick_ratio", "candle_range",
        "is_doji", "is_hammer", "is_shooting_star",
        "is_bullish_engulfing", "is_bearish_engulfing",
    ]
    order += [
        "ms_bias", "ms_bos", "ms_choch", "bars_since_bos", "bars_since_choch",
    ]
    order += ["in_killzone", "pd_position", "premium"]
    order += [
        "buyside_sweep", "sellside_sweep", "dist_to_buyside", "dist_to_sellside",
    ]
    order += ["dist_to_fvg", "dist_to_ifvg"]
    order += ["is_in_ifvg_retest", "signal_dir", "entry_is_primary"]
    for src in lag_sources:
        for lag in lags:
            order.append(f"{src}_lag{lag}")

    # Only keep names actually present (defensive), preserving order + dedupe.
    seen = set()
    final = []
    for name in order:
        if name in columns and name not in seen:
            final.append(name)
            seen.add(name)
    return final
