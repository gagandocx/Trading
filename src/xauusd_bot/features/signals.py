"""Entry-signal generation driven by iFVG retests (the PRIMARY trigger).

Per the user's requirement, the most probable trades are entries on inverse Fair
Value Gaps (iFVGs). This module turns the ICT constructs from
:mod:`xauusd_bot.features.ict` into a per-bar signal record that the ML model
learns to filter and that labeling / backtest key off.

Entry logic (primary = iFVG retest)
------------------------------------
At bar ``i`` an entry is emitted when ALL hold:
  1. An iFVG zone exists and was created at some bar ``< i`` and is still
     unmitigated as of ``i``.
  2. Price retests that zone within ``ifvg_retest_atr_tol`` ATR multiples
     (bar ``i``'s range comes within tolerance of the zone edge).
  3. The iFVG polarity aligns with the market-structure bias: a bullish iFVG in a
     non-bearish (bias >= 0 or recent bullish CHoCH) context -> LONG candidate;
     a bearish iFVG in a non-bullish context -> SHORT candidate.

If ``primary_entry`` is not ``ifvg`` (or ``ifvg_enabled`` is false, or no iFVG is
present), the generator falls back to the configured secondary trigger
(``fvg`` retest, then ``order_block`` proximity) WITHOUT crashing.

CAUSALITY: every zone used at bar ``i`` has ``created_index < i`` or ``<= i`` for
the completing bar, and mitigation is checked only against bars ``<= i`` (we do
NOT use the forward-annotated ``mitigated_index``; we recompute "unmitigated as of
i" causally). Structure bias at ``i`` already carries the swing-confirmation
delay. Stops/targets are ATR-based distances known at ``i``.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from .ict import (
    detect_fvgs,
    detect_ifvgs,
    detect_order_blocks,
    market_structure,
)
from .indicators import atr as _atr
from .indicators import closes, highs, lows

Candle = Dict[str, object]
Series = List[Optional[float]]


def _unmitigated_as_of(zone: Dict[str, object], upto: int, h: Series, low: Series) -> bool:
    """Causally decide whether ``zone`` is still unmitigated at bar ``upto``.

    Scans bars strictly between the zone's creation and ``upto`` (exclusive of
    ``upto`` itself so the retest bar can still count as a fresh touch). A zone is
    mitigated once a bar's range has already traded back into it.
    """
    created = int(zone["created_index"])  # type: ignore[arg-type]
    top = float(zone["top"])  # type: ignore[arg-type]
    bottom = float(zone["bottom"])  # type: ignore[arg-type]
    for j in range(created + 1, upto):
        if j >= len(h) or h[j] is None or low[j] is None:
            continue
        if low[j] <= top and h[j] >= bottom:
            return False
    return True


def _retests(zone: Dict[str, object], i: int, h: Series, low: Series, tol: float) -> bool:
    """True when bar ``i`` comes within ``tol`` (price units) of the zone."""
    if i >= len(h) or h[i] is None or low[i] is None:
        return False
    top = float(zone["top"])  # type: ignore[arg-type]
    bottom = float(zone["bottom"])  # type: ignore[arg-type]
    # Bar range expanded by tolerance overlaps the zone band.
    return (low[i] - tol) <= top and (h[i] + tol) >= bottom


def generate_signals(rows: Sequence[Candle], cfg) -> List[Dict[str, object]]:
    """Produce one signal record per bar.

    Each record::

        {"index": int, "timestamp": str, "direction": "long"|"short"|"none",
         "entry_type": "ifvg"|"fvg"|"order_block"|"none",
         "entry_price": float|None, "stop_dist": float|None,
         "target_dist": float|None, "zone_top": float|None,
         "zone_bottom": float|None}

    Honors ``cfg.features.ict.primary_entry`` with fallbacks. Fully causal.
    """
    ict_cfg = cfg.features.ict
    atr_window = cfg.features.atr_window
    label_cfg = cfg.labeling

    atr_series = _atr(rows, window=atr_window)
    h = highs(rows)
    low = lows(rows)
    c = closes(rows)
    n = len(rows)

    structure = market_structure(rows, lookback=ict_cfg.swing_lookback)
    bias = structure["bias"]

    # Pre-detect all zones once (each carries a causal created_index).
    ifvgs = (
        detect_ifvgs(rows, atr_series, min_gap_atr=ict_cfg.fvg_min_gap_atr)
        if ict_cfg.ifvg_enabled
        else []
    )
    fvgs = detect_fvgs(rows, atr_series, min_gap_atr=ict_cfg.fvg_min_gap_atr)
    order_blocks = detect_order_blocks(
        rows,
        structure=structure,
        lookback=ict_cfg.order_block_lookback,
        swing_lookback=ict_cfg.swing_lookback,
    )

    target_mult = label_cfg.target_atr_mult
    stop_mult = label_cfg.stop_atr_mult

    # Resolve the trigger order from config: primary first, then the rest.
    order = _trigger_order(ict_cfg.primary_entry, ict_cfg.ifvg_enabled)

    signals: List[Dict[str, object]] = []
    for i in range(n):
        atr_i = atr_series[i] if i < len(atr_series) else None
        record = {
            "index": i,
            "timestamp": rows[i].get("timestamp") if isinstance(rows[i], dict) else None,
            "direction": "none",
            "entry_type": "none",
            "entry_price": c[i],
            "stop_dist": None,
            "target_dist": None,
            "zone_top": None,
            "zone_bottom": None,
        }

        if atr_i is None or atr_i <= 0:
            signals.append(record)
            continue

        tol = ict_cfg.ifvg_retest_atr_tol * atr_i
        bias_i = bias[i]

        hit = None
        for trigger in order:
            if trigger == "ifvg":
                hit = _match_zone(ifvgs, i, h, low, tol, bias_i, "ifvg")
            elif trigger == "fvg":
                hit = _match_zone(fvgs, i, h, low, tol, bias_i, "fvg")
            elif trigger == "order_block":
                hit = _match_order_block(order_blocks, i, h, low, tol, bias_i)
            if hit is not None:
                break

        if hit is not None:
            direction, entry_type, zone = hit
            record["direction"] = direction
            record["entry_type"] = entry_type
            record["zone_top"] = float(zone["top"])  # type: ignore[arg-type]
            record["zone_bottom"] = float(zone["bottom"])  # type: ignore[arg-type]
            record["stop_dist"] = stop_mult * atr_i
            record["target_dist"] = target_mult * atr_i

        signals.append(record)

    return signals


def _trigger_order(primary: str, ifvg_enabled: bool) -> List[str]:
    """Return the ordered list of triggers to try, primary first."""
    all_triggers = ["ifvg", "fvg", "order_block"]
    if not ifvg_enabled and "ifvg" in all_triggers:
        all_triggers = [t for t in all_triggers if t != "ifvg"]
    primary = primary if primary in all_triggers else all_triggers[0]
    order = [primary] + [t for t in all_triggers if t != primary]
    return order


def _match_zone(zones, i, h, low, tol, bias_i, entry_type):
    """Find a causal, unmitigated zone retested at bar ``i`` aligned with bias."""
    best = None
    for z in zones:
        created = int(z["created_index"])  # type: ignore[arg-type]
        if created >= i:  # zone must already exist strictly before this bar
            continue
        if not _unmitigated_as_of(z, i, h, low):
            continue
        if not _retests(z, i, h, low, tol):
            continue
        ztype = z["type"]
        # Bullish zone -> long when bias not bearish; bearish zone -> short.
        if ztype == "bullish" and bias_i >= 0:
            best = ("long", entry_type, z)
        elif ztype == "bearish" and bias_i <= 0:
            best = ("short", entry_type, z)
        if best is not None:
            # Prefer the most recently created qualifying zone.
            return best
    return best


def _match_order_block(blocks, i, h, low, tol, bias_i):
    """Order-block fallback: proximity retest of the last OB before a BOS."""
    for z in blocks:
        created = int(z["created_index"])  # type: ignore[arg-type]
        if created >= i:
            continue
        if z.get("top") is None or z.get("bottom") is None:
            continue
        if not _retests(z, i, h, low, tol):
            continue
        ztype = z["type"]
        if ztype == "bullish" and bias_i >= 0:
            return ("long", "order_block", z)
        if ztype == "bearish" and bias_i <= 0:
            return ("short", "order_block", z)
    return None
