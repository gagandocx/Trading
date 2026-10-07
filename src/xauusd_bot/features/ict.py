"""ICT (Inner Circle Trader) / smart-money-concept detectors.

This module is the heart of the strategy. It implements the smart-money concepts
the user asked for, with inverse Fair Value Gaps (iFVGs) as the primary entry
construct (consumed by :mod:`xauusd_bot.features.signals`).

CAUSALITY CONTRACT (read before editing)
-----------------------------------------
Every detector is strictly causal: a value reported at row ``i`` is derived only
from candles ``0..i``. The one subtlety is *swing confirmation delay*. A swing
high/low at index ``j`` cannot be known until ``swing_lookback`` bars have formed
AFTER it (we need to see that the following bars did not exceed it). Therefore a
swing at ``j`` is only CONFIRMED - and only allowed to influence any per-row
feature - at index ``j + swing_lookback`` and never earlier. Everything built on
top of swings (BOS, CHoCH, bias, order blocks) inherits that same delay. The
per-row feature arrays this module produces are safe to feed to a model as-is.

Detectors implemented
----------------------
* Market structure: swing highs/lows, Break of Structure (BOS),
  Change of Character (CHoCH), running trend/bias state.
* Fair Value Gaps (FVG): 3-candle imbalance, size-filtered by ``fvg_min_gap_atr``,
  with mitigation tracking.
* Inverse FVG (iFVG): polarity flip when price trades fully through an unmitigated
  FVG.
* Order blocks: last opposing candle before a BOS, within ``order_block_lookback``.
* Liquidity: buy-side / sell-side pools (equal highs/lows) and sweeps.
* Premium / discount zones relative to the current dealing range.
* Killzone / session flags from the candle timestamp hour (UTC assumption).
"""

from __future__ import annotations

from datetime import datetime
from typing import Dict, List, Optional, Sequence

from .indicators import atr as _atr
from .indicators import closes, highs, lows

Candle = Dict[str, object]
Series = List[Optional[float]]


# ---------------------------------------------------------------------------
# Timestamp / session helpers
#
# UTC ASSUMPTION: candle timestamps are treated as UTC. ICT killzones are defined
# in New York time, but for a self-contained, dependency-free implementation we
# map them to fixed UTC hour windows (standard-time approximation):
#   * London killzone:    07:00-10:00 UTC
#   * New York AM killzone:12:00-15:00 UTC
# If the user's data is in a different timezone they should normalise upstream;
# this is documented so the mapping is explicit and reproducible.
# ---------------------------------------------------------------------------
KILLZONE_HOURS = {
    "london": (7, 10),
    "newyork_am": (12, 15),
    "newyork_pm": (17, 20),
    "asia": (0, 3),
}


def _hour_of(ts: object) -> Optional[int]:
    """Parse the hour (UTC) from a canonical ISO-8601 timestamp string."""
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.utcfromtimestamp(float(ts)).hour
        except (OverflowError, OSError, ValueError):
            return None
    try:
        return datetime.fromisoformat(str(ts)).hour
    except ValueError:
        return None


def killzone_flags(
    rows: Sequence[Candle], zones: Sequence[str]
) -> Dict[str, List[Optional[bool]]]:
    """Per-row boolean flags for each requested killzone + a combined flag.

    Causal: depends only on the row's own timestamp.
    """
    out: Dict[str, List[Optional[bool]]] = {z: [] for z in zones}
    combined: List[Optional[bool]] = []
    for r in rows:
        hr = _hour_of(r.get("timestamp") if isinstance(r, dict) else None)
        any_zone = False
        for z in zones:
            lo_hi = KILLZONE_HOURS.get(z)
            if hr is None or lo_hi is None:
                out[z].append(None if hr is None else False)
                continue
            lo, hi = lo_hi
            inside = lo <= hr < hi
            out[z].append(inside)
            any_zone = any_zone or inside
        combined.append(None if hr is None else any_zone)
    out["in_killzone"] = combined
    return out


# ---------------------------------------------------------------------------
# Market structure: swings, BOS, CHoCH, bias
# ---------------------------------------------------------------------------
def swing_points(rows: Sequence[Candle], lookback: int = 5):
    """Detect fractal swing highs / lows with a confirmation delay.

    A bar ``j`` is a swing high if its high is the strict maximum of the window
    ``[j-lookback, j+lookback]`` (and likewise for swing lows with lows). Because
    we must see ``lookback`` bars AFTER ``j`` to confirm it, the swing is only
    *confirmed* at index ``j + lookback``.

    Returns two aligned ``list`` arrays (``swing_high_price``,
    ``swing_low_price``) placed at the CONFIRMATION index ``j + lookback`` (not at
    ``j``), guaranteeing no lookahead. Each non-None entry is the price of the
    swing that just became confirmed. Also returns the raw swing index so callers
    can reference the originating bar.
    """
    h = highs(rows)
    low = lows(rows)
    n = len(rows)
    conf_high: Series = [None] * n
    conf_low: Series = [None] * n
    conf_high_idx: List[Optional[int]] = [None] * n
    conf_low_idx: List[Optional[int]] = [None] * n
    if lookback <= 0:
        return conf_high, conf_low, conf_high_idx, conf_low_idx

    for j in range(lookback, n - lookback):
        window_h = h[j - lookback : j + lookback + 1]
        window_l = low[j - lookback : j + lookback + 1]
        if any(x is None for x in window_h) or any(x is None for x in window_l):
            continue
        center_h = h[j]
        center_l = low[j]
        conf_at = j + lookback  # confirmation index (causal)
        if center_h == max(window_h) and window_h.count(center_h) == 1:
            conf_high[conf_at] = center_h
            conf_high_idx[conf_at] = j
        if center_l == min(window_l) and window_l.count(center_l) == 1:
            conf_low[conf_at] = center_l
            conf_low_idx[conf_at] = j
    return conf_high, conf_low, conf_high_idx, conf_low_idx


def market_structure(rows: Sequence[Candle], lookback: int = 5) -> Dict[str, list]:
    """Compute BOS / CHoCH and a running bias from confirmed swings.

    All signals are emitted at the swing confirmation index (``j + lookback``) or
    later, so the output arrays are causal.

    Returns a dict of aligned series:
      * ``bias``: ``+1`` bullish, ``-1`` bearish, ``0`` undetermined (running).
      * ``bos``: ``+1`` bullish BOS at this bar, ``-1`` bearish BOS, else ``0``.
      * ``choch``: ``+1`` / ``-1`` change-of-character at this bar, else ``0``.
      * ``bars_since_bos`` / ``bars_since_choch``: integer counters (``None`` until
        the first event).
      * ``last_swing_high`` / ``last_swing_low``: most recent CONFIRMED swing price
        available at each bar (carried forward).
    """
    conf_high, conf_low, hi_idx, lo_idx = swing_points(rows, lookback=lookback)
    c = closes(rows)
    n = len(rows)

    bias: List[int] = [0] * n
    bos: List[int] = [0] * n
    choch: List[int] = [0] * n
    bars_since_bos: List[Optional[int]] = [None] * n
    bars_since_choch: List[Optional[int]] = [None] * n
    last_sh: Series = [None] * n
    last_sl: Series = [None] * n

    cur_bias = 0
    prev_sh: Optional[float] = None
    prev_sl: Optional[float] = None
    last_bos_i: Optional[int] = None
    last_choch_i: Optional[int] = None

    for i in range(n):
        event_bos = 0
        event_choch = 0

        # When a new swing confirms at this bar, test for BOS/CHoCH against the
        # previous confirmed swing of the same type, using the close at i.
        new_sh = conf_high[i]
        new_sl = conf_low[i]

        if new_sh is not None:
            if prev_sh is not None and c[i] is not None and c[i] > prev_sh:
                # Price broke above the prior swing high -> bullish break.
                if cur_bias <= 0:
                    event_choch = 1
                    cur_bias = 1
                else:
                    event_bos = 1
            prev_sh = new_sh

        if new_sl is not None:
            if prev_sl is not None and c[i] is not None and c[i] < prev_sl:
                # Price broke below the prior swing low -> bearish break.
                if cur_bias >= 0:
                    event_choch = -1
                    cur_bias = -1
                else:
                    event_bos = -1
            prev_sl = new_sl

        bos[i] = event_bos
        choch[i] = event_choch
        bias[i] = cur_bias

        if event_bos != 0 or event_choch != 0:
            last_bos_i = i
        if event_choch != 0:
            last_choch_i = i

        bars_since_bos[i] = None if last_bos_i is None else i - last_bos_i
        bars_since_choch[i] = None if last_choch_i is None else i - last_choch_i
        last_sh[i] = prev_sh
        last_sl[i] = prev_sl

    return {
        "bias": bias,
        "bos": bos,
        "choch": choch,
        "bars_since_bos": bars_since_bos,
        "bars_since_choch": bars_since_choch,
        "last_swing_high": last_sh,
        "last_swing_low": last_sl,
        "swing_high_idx": hi_idx,
        "swing_low_idx": lo_idx,
    }


# ---------------------------------------------------------------------------
# Fair Value Gaps
# ---------------------------------------------------------------------------
def detect_fvgs(
    rows: Sequence[Candle],
    atr_series: Optional[Series] = None,
    min_gap_atr: float = 0.25,
) -> List[Dict[str, object]]:
    """Detect 3-candle Fair Value Gaps.

    A bullish FVG forms on the triple ``(i-2, i-1, i)`` when
    ``high[i-2] < low[i]`` (a gap the middle candle leaves unfilled). A bearish
    FVG forms when ``low[i-2] > high[i]``.

    CAUSALITY: the gap is only known once candle ``i`` closes, so each FVG is
    recorded with ``created_index = i`` (the bar that completes the pattern) and
    is usable from bar ``i`` onward - never before.

    The gap size (``top - bottom``) is filtered to be ``>= min_gap_atr * ATR`` at
    the creation bar when an ``atr_series`` is supplied (``min_gap_atr=0`` keeps
    all gaps). Each record is a dict::

        {"type": "bullish"|"bearish", "top": float, "bottom": float,
         "created_index": int, "mitigated_index": int|None}

    ``mitigated_index`` is filled in by scanning forward ONLY to annotate the
    history (it is never used to compute a feature at an earlier bar).
    """
    h = highs(rows)
    low = lows(rows)
    n = len(rows)
    fvgs: List[Dict[str, object]] = []
    for i in range(2, n):
        if h[i] is None or low[i] is None or h[i - 2] is None or low[i - 2] is None:
            continue
        atr_i = None
        if atr_series is not None and i < len(atr_series):
            atr_i = atr_series[i]
        min_gap = (min_gap_atr * atr_i) if (atr_i is not None) else 0.0

        if h[i - 2] < low[i]:
            gap = low[i] - h[i - 2]
            if gap >= min_gap:
                fvgs.append(
                    {
                        "type": "bullish",
                        "top": low[i],
                        "bottom": h[i - 2],
                        "created_index": i,
                        "mitigated_index": None,
                    }
                )
        elif low[i - 2] > h[i]:
            gap = low[i - 2] - h[i]
            if gap >= min_gap:
                fvgs.append(
                    {
                        "type": "bearish",
                        "top": low[i - 2],
                        "bottom": h[i],
                        "created_index": i,
                        "mitigated_index": None,
                    }
                )

    _annotate_mitigation(rows, fvgs)
    return fvgs


def _annotate_mitigation(rows: Sequence[Candle], gaps: List[Dict[str, object]]) -> None:
    """Fill ``mitigated_index`` for each gap (first bar after creation whose range
    re-enters the gap zone). This is a history annotation; callers that need a
    causal "is this gap unmitigated at bar i" must compare indices themselves.
    """
    h = highs(rows)
    low = lows(rows)
    n = len(rows)
    for g in gaps:
        start = int(g["created_index"]) + 1  # type: ignore[call-overload]
        top = float(g["top"])  # type: ignore[arg-type]
        bottom = float(g["bottom"])  # type: ignore[arg-type]
        for j in range(start, n):
            if h[j] is None or low[j] is None:
                continue
            # Price trades back into the gap zone.
            if low[j] <= top and h[j] >= bottom:
                g["mitigated_index"] = j
                break


# ---------------------------------------------------------------------------
# Inverse Fair Value Gaps (iFVG)  -- PRIMARY entry construct
# ---------------------------------------------------------------------------
def detect_ifvgs(
    rows: Sequence[Candle],
    atr_series: Optional[Series] = None,
    min_gap_atr: float = 0.25,
) -> List[Dict[str, object]]:
    """Detect inverse Fair Value Gaps (iFVGs).

    An iFVG forms when price trades *fully through* an existing unmitigated FVG,
    flipping its polarity:

      * A **bullish FVG** that is violated to the DOWNSIDE (a close below its
        bottom) becomes a **bearish iFVG** (old support flips to resistance).
      * A **bearish FVG** that is violated to the UPSIDE (a close above its top)
        becomes a **bullish iFVG** (old resistance flips to support).

    CAUSALITY: the flip is detected at the bar ``k`` whose close breaches the gap,
    strictly after the FVG's ``created_index``. Each iFVG carries
    ``created_index = k`` (the flip bar) and ``source_fvg_index`` (the original
    FVG's creation bar). The zone is the original gap's ``top``/``bottom``.

    Returns a list of dicts::

        {"type": "bullish"|"bearish", "top": float, "bottom": float,
         "created_index": int, "source_fvg_index": int, "mitigated_index": int|None}
    """
    fvgs = detect_fvgs(rows, atr_series=atr_series, min_gap_atr=min_gap_atr)
    c = closes(rows)
    n = len(rows)
    ifvgs: List[Dict[str, object]] = []

    for g in fvgs:
        created = int(g["created_index"])  # type: ignore[arg-type]
        top = float(g["top"])  # type: ignore[arg-type]
        bottom = float(g["bottom"])  # type: ignore[arg-type]
        gtype = g["type"]
        # Scan forward for the first close that trades fully through the gap.
        for k in range(created + 1, n):
            if c[k] is None:
                continue
            if gtype == "bullish" and c[k] < bottom:
                ifvgs.append(
                    {
                        "type": "bearish",  # polarity flips
                        "top": top,
                        "bottom": bottom,
                        "created_index": k,
                        "source_fvg_index": created,
                        "mitigated_index": None,
                    }
                )
                break
            if gtype == "bearish" and c[k] > top:
                ifvgs.append(
                    {
                        "type": "bullish",  # polarity flips
                        "top": top,
                        "bottom": bottom,
                        "created_index": k,
                        "source_fvg_index": created,
                        "mitigated_index": None,
                    }
                )
                break

    _annotate_mitigation(rows, ifvgs)
    return ifvgs


# ---------------------------------------------------------------------------
# Order blocks
# ---------------------------------------------------------------------------
def detect_order_blocks(
    rows: Sequence[Candle],
    structure: Optional[Dict[str, list]] = None,
    lookback: int = 20,
    swing_lookback: int = 5,
) -> List[Dict[str, object]]:
    """Detect order blocks: the last opposing candle before a BOS.

    For a bullish BOS at bar ``i`` we scan back up to ``lookback`` bars for the
    most recent bearish candle (``close < open``) - that is the bullish order
    block. For a bearish BOS we find the most recent bullish candle.

    CAUSALITY: the BOS itself is only confirmed at bar ``i`` (it already carries
    the swing confirmation delay), and the order block lies strictly before ``i``,
    so each record is usable from ``i`` onward. ``created_index`` is the BOS bar.
    """
    if structure is None:
        structure = market_structure(rows, lookback=swing_lookback)
    bos = structure["bos"]
    o = [None if (not isinstance(r, dict)) else _f(r.get("open")) for r in rows]
    c = closes(rows)
    h = highs(rows)
    low = lows(rows)
    n = len(rows)
    blocks: List[Dict[str, object]] = []

    for i in range(n):
        direction = bos[i]
        if direction == 0:
            continue
        start = max(0, i - lookback)
        found = None
        for j in range(i - 1, start - 1, -1):
            if o[j] is None or c[j] is None:
                continue
            if direction > 0 and c[j] < o[j]:  # last down candle before bull BOS
                found = j
                break
            if direction < 0 and c[j] > o[j]:  # last up candle before bear BOS
                found = j
                break
        if found is None:
            continue
        blocks.append(
            {
                "type": "bullish" if direction > 0 else "bearish",
                "top": h[found],
                "bottom": low[found],
                "ob_index": found,
                "created_index": i,
            }
        )
    return blocks


def _f(v) -> Optional[float]:
    try:
        return None if v is None else float(v)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Liquidity pools and sweeps
# ---------------------------------------------------------------------------
def detect_liquidity(
    rows: Sequence[Candle],
    atr_series: Optional[Series] = None,
    lookback: int = 50,
    equal_tol_atr: float = 0.1,
    swing_lookback: int = 5,
) -> Dict[str, list]:
    """Detect buy-side / sell-side liquidity pools and sweeps.

    Buy-side liquidity sits above equal highs; sell-side below equal lows. We
    locate equal levels among CONFIRMED swings within ``lookback`` bars whose
    prices are within ``equal_tol_atr * ATR`` of each other. A sweep is flagged at
    bar ``i`` when price pierces such a level and closes back on the other side
    (a classic stop-run).

    CAUSALITY: pools are built only from swings already confirmed at or before
    ``i``; sweeps use only bar ``i``'s own high/low/close. Returns aligned series:
      * ``buyside_level`` / ``sellside_level``: nearest pooled level at bar ``i``.
      * ``buyside_sweep`` / ``sellside_sweep``: bool flags at bar ``i``.
    """
    structure = market_structure(rows, lookback=swing_lookback)
    conf_high = structure["last_swing_high"]
    conf_low = structure["last_swing_low"]
    sh_series, sl_series, _, _ = swing_points(rows, lookback=swing_lookback)
    h = highs(rows)
    low = lows(rows)
    c = closes(rows)
    n = len(rows)

    buyside_level: Series = [None] * n
    sellside_level: Series = [None] * n
    buyside_sweep: List[Optional[bool]] = [None] * n
    sellside_sweep: List[Optional[bool]] = [None] * n

    recent_highs: List[tuple] = []  # (index, price) of confirmed swing highs
    recent_lows: List[tuple] = []

    for i in range(n):
        if sh_series[i] is not None:
            recent_highs.append((i, sh_series[i]))
        if sl_series[i] is not None:
            recent_lows.append((i, sl_series[i]))
        # Drop entries older than lookback.
        recent_highs = [(idx, p) for (idx, p) in recent_highs if i - idx <= lookback]
        recent_lows = [(idx, p) for (idx, p) in recent_lows if i - idx <= lookback]

        atr_i = atr_series[i] if (atr_series is not None and i < len(atr_series)) else None
        tol = (equal_tol_atr * atr_i) if atr_i else None

        bs = _nearest_equal_level([p for _, p in recent_highs], tol)
        ss = _nearest_equal_level([p for _, p in recent_lows], tol)
        buyside_level[i] = bs
        sellside_level[i] = ss

        if bs is not None and h[i] is not None and c[i] is not None and tol is not None:
            buyside_sweep[i] = h[i] > bs + 0 and c[i] < bs
        else:
            buyside_sweep[i] = False if bs is not None else None
        if ss is not None and low[i] is not None and c[i] is not None and tol is not None:
            sellside_sweep[i] = low[i] < ss and c[i] > ss
        else:
            sellside_sweep[i] = False if ss is not None else None

    return {
        "buyside_level": buyside_level,
        "sellside_level": sellside_level,
        "buyside_sweep": buyside_sweep,
        "sellside_sweep": sellside_sweep,
    }


def _nearest_equal_level(prices: List[float], tol: Optional[float]) -> Optional[float]:
    """Return the average of the most recent cluster of near-equal prices.

    Two prices are "equal" when within ``tol``. With no tolerance we simply return
    the most recent price (a single-level pool).
    """
    if not prices:
        return None
    if tol is None or tol <= 0:
        return prices[-1]
    anchor = prices[-1]
    cluster = [p for p in prices if abs(p - anchor) <= tol]
    return sum(cluster) / len(cluster)


# ---------------------------------------------------------------------------
# Premium / discount zones
# ---------------------------------------------------------------------------
def premium_discount(
    rows: Sequence[Candle], window: int = 50
) -> Dict[str, list]:
    """Position of close within the recent dealing range (premium vs discount).

    The dealing range is the rolling ``[min low, max high]`` over the trailing
    ``window`` bars. ``equilibrium`` is the midpoint. ``pd_position`` is in
    ``[0, 1]`` (0 = deep discount at the range low, 1 = deep premium at the high),
    and ``premium`` is a bool (``position > 0.5``). Causal (trailing window only).
    """
    h = highs(rows)
    low = lows(rows)
    c = closes(rows)
    n = len(rows)
    pos: Series = [None] * n
    premium: List[Optional[bool]] = [None] * n
    for i in range(n):
        start = max(0, i - window + 1)
        win_h = [x for x in h[start : i + 1] if x is not None]
        win_l = [x for x in low[start : i + 1] if x is not None]
        if not win_h or not win_l or c[i] is None or i < window - 1:
            continue
        hi = max(win_h)
        lo = min(win_l)
        rng = hi - lo
        if rng <= 0:
            continue
        p = (c[i] - lo) / rng
        pos[i] = p
        premium[i] = p > 0.5
    return {"pd_position": pos, "premium": premium}


# ---------------------------------------------------------------------------
# Convenience: ATR passthrough so callers can get a default ATR for the detectors
# ---------------------------------------------------------------------------
def default_atr(rows: Sequence[Candle], window: int = 14) -> Series:
    """Convenience wrapper around :func:`indicators.atr`."""
    return _atr(rows, window=window)
