"""ATR-sized triple-barrier labeling, direction-aware.

For each candidate row the barriers are placed relative to the entry close:

  * long  : target = entry + target_mult * ATR  (above)
            stop   = entry - stop_mult   * ATR  (below)
  * short : target = entry - target_mult * ATR  (below)
            stop   = entry + stop_mult   * ATR  (above)

We then scan forward up to ``max_horizon`` bars and record which barrier is hit
first using each bar's high/low:

  * +1  target hit first   (a correct directional call)
  * -1  stop hit first      (a wrong directional call)
  *  0  neither -> vertical (time) barrier expired

CAUSALITY / LEAKAGE
-------------------
Labels look FORWARD by construction. The forward window length actually consumed
is returned per row so the caller can purge those bars from training (walk-forward
embargo). Rows whose forward window would extend past the end of the dataset are
left UNLABELED (``None``) and must be excluded from training.

If a ``directions`` array is supplied (e.g. from
:func:`xauusd_bot.features.signals.generate_signals`) each row is labeled with the
appropriate barrier orientation; a direction of ``"none"``/``0`` yields an
unlabeled row (``None``). When no directions are given, every bar is labeled as a
LONG candidate (useful for research / feature-target studies).
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

Candle = dict
Series = List[Optional[float]]


def _dir_to_int(d) -> int:
    """Normalise a direction token to +1 (long), -1 (short), or 0 (none)."""
    if d is None:
        return 0
    if isinstance(d, (int, float)):
        if d > 0:
            return 1
        if d < 0:
            return -1
        return 0
    s = str(d).lower()
    if s in ("long", "buy", "+1", "1"):
        return 1
    if s in ("short", "sell", "-1"):
        return -1
    return 0


def triple_barrier_labels(
    rows: Sequence[Candle],
    atr_series: Series,
    target_mult: float = 2.0,
    stop_mult: float = 1.0,
    max_horizon: int = 24,
    directions: Optional[Sequence] = None,
) -> Tuple[List[Optional[int]], List[Optional[int]]]:
    """Compute triple-barrier labels and the per-row forward window used.

    Parameters
    ----------
    rows:
        Canonical candles.
    atr_series:
        ATR aligned to ``rows`` (used to size the barriers at the entry bar).
    target_mult, stop_mult:
        Barrier distances in ATR multiples.
    max_horizon:
        Vertical (time) barrier - max bars to look forward.
    directions:
        Optional per-row trade direction (``"long"``/``"short"``/``"none"`` or
        ``+1``/``-1``/``0``). Defaults to all-long when omitted.

    Returns
    -------
    (labels, horizon_used):
        ``labels[i]`` in ``{-1, 0, +1}`` or ``None`` (unlabeled). ``horizon_used[i]``
        is the number of forward bars consumed before a barrier was hit (or the
        full horizon on expiry), or ``None`` when the row is unlabeled.
    """
    n = len(rows)
    labels: List[Optional[int]] = [None] * n
    horizon_used: List[Optional[int]] = [None] * n

    highs = [_f(r.get("high")) for r in rows]
    lows = [_f(r.get("low")) for r in rows]
    closes = [_f(r.get("close")) for r in rows]

    for i in range(n):
        direction = _dir_to_int(directions[i]) if directions is not None else 1
        if direction == 0:
            continue  # no trade -> unlabeled

        entry = closes[i]
        atr_i = atr_series[i] if i < len(atr_series) else None
        if entry is None or atr_i is None or atr_i <= 0:
            continue

        # Not enough forward bars to resolve the vertical barrier -> exclude.
        if i + max_horizon >= n:
            continue

        if direction > 0:
            target = entry + target_mult * atr_i
            stop = entry - stop_mult * atr_i
        else:
            target = entry - target_mult * atr_i
            stop = entry + stop_mult * atr_i

        label = 0
        used = max_horizon
        for step in range(1, max_horizon + 1):
            j = i + step
            hj, lj = highs[j], lows[j]
            if hj is None or lj is None:
                continue
            if direction > 0:
                hit_target = hj >= target
                hit_stop = lj <= stop
            else:
                hit_target = lj <= target
                hit_stop = hj >= stop
            # If both touched within the same bar, treat as stop-first
            # (conservative: assume the adverse move was reached first).
            if hit_target and hit_stop:
                label = -1
                used = step
                break
            if hit_target:
                label = 1
                used = step
                break
            if hit_stop:
                label = -1
                used = step
                break

        labels[i] = label
        horizon_used[i] = used

    return labels, horizon_used


def _f(v) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None
