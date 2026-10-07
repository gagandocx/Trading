"""Configuration schema and loader for xauusd_bot.

The configuration lives in ``configs/default.yaml``. Loading is layered so the
package works in any environment:

1. PyYAML (``import yaml``) if installed  -> full YAML support.
2. ruamel.yaml (preinstalled in many envs) -> full YAML support.
3. A minimal pure-stdlib fallback parser   -> handles the flat / simple-nested
   mapping-of-scalars structure used by ``default.yaml`` (no flow sequences,
   anchors, or multi-line scalars).

The parsed mapping is coerced into typed dataclasses so downstream code accesses
config via attributes (e.g. ``cfg.execution.live_trading_enabled``) rather than
raw dict lookups.
"""

from __future__ import annotations

import typing
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Typed config sections
# ---------------------------------------------------------------------------
@dataclass
class DataConfig:
    """Where candle data comes from and goes to."""

    symbol: str = "XAUUSD"
    timeframe: str = "M15"  # informational; MT5 maps this to its own enum
    sample_csv: str = "data/sample/XAUUSD_sample.csv"
    csv_path: str = "data/sample/XAUUSD_sample.csv"


@dataclass
class ICTConfig:
    """ICT (Inner Circle Trader) concept parameters.

    These drive the Smart-Money-Concepts features computed in a later feature
    (market structure, order blocks, fair value gaps, liquidity sweeps,
    premium/discount zones). Captured here so the config foundation is ready.
    """

    enabled: bool = True
    swing_lookback: int = 5  # bars each side to confirm a swing high/low (BOS/CHOCH)
    fvg_min_gap_atr: float = 0.25  # min fair-value-gap size in ATR multiples
    order_block_lookback: int = 20  # bars to scan for the originating order block
    liquidity_lookback: int = 50  # bars used to locate buy/sell-side liquidity pools
    equal_level_tol_atr: float = 0.1  # tolerance for equal highs/lows in ATR mults
    killzones: List[str] = field(
        default_factory=lambda: ["london", "newyork_am"]
    )  # session killzones to flag for entries
    # Entry preference: an inverse FVG (iFVG) forms when price trades fully
    # through an existing fair-value gap, flipping it from support to resistance
    # (or vice versa). The signal/labeling stage should treat iFVG retests as the
    # primary entry trigger when this is enabled.
    primary_entry: str = "ifvg"  # ifvg | fvg | order_block
    ifvg_enabled: bool = True
    ifvg_retest_atr_tol: float = 0.15  # retest proximity to the iFVG, ATR mults


@dataclass
class FeatureConfig:
    """Technical-indicator window parameters."""

    rsi_window: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    atr_window: int = 14
    bb_window: int = 20
    bb_std: float = 2.0
    ema_windows: List[int] = field(default_factory=lambda: [9, 21, 50, 200])
    return_windows: List[int] = field(default_factory=lambda: [1, 5, 10])
    ict: ICTConfig = field(default_factory=ICTConfig)


@dataclass
class LabelingConfig:
    """Triple-barrier labeling parameters."""

    horizon: int = 24  # max candles to hold before the vertical (time) barrier
    target_atr_mult: float = 2.0  # take-profit distance in ATR multiples
    stop_atr_mult: float = 1.0  # stop-loss distance in ATR multiples
    # ATR window used to size the LABEL barriers. MUST equal
    # features.atr_window (enforced at load; see Config._validate) so the model
    # learns the same barrier geometry the backtest trades.
    atr_window: int = 14


@dataclass
class ModelConfig:
    """Model hyper-parameters (LightGBM path; the stdlib GBT mirrors a subset)."""

    model_type: str = "lightgbm"  # falls back to a pure-stdlib GBT if unavailable
    n_estimators: int = 300
    learning_rate: float = 0.05
    max_depth: int = 6
    num_leaves: int = 31
    min_child_samples: int = 20
    subsample: float = 0.8
    colsample_bytree: float = 0.8
    random_state: int = 42


@dataclass
class BacktestConfig:
    """Backtest cost and sizing assumptions."""

    spread_pips: float = 25.0  # XAUUSD spread in cents (pips); ~ $0.25 per side
    commission_per_lot: float = 7.0  # round-turn commission per 1.0 lot, USD
    initial_capital: float = 10000.0  # starting account equity, USD
    train_size: int = 2000  # candles per walk-forward train window
    test_size: int = 500  # candles per walk-forward test window
    embargo: int = 24  # purge/embargo candles between train and test
    prob_threshold: float = 0.5  # min model probability to take a signalled trade


@dataclass
class RiskConfig:
    """Risk management parameters."""

    risk_per_trade: float = 0.01  # fraction of equity risked per trade (1%)
    max_drawdown_pct: float = 0.20  # halt trading beyond 20% drawdown
    atr_stop_mult: float = 1.0  # stop distance in ATR multiples
    max_position_lots: float = 1.0  # hard cap on position size


@dataclass
class ExecutionConfig:
    """Execution layer. LIVE TRADING IS OFF BY DEFAULT."""

    live_trading_enabled: bool = False  # must stay False unless user opts in
    mode: str = "paper"  # one of: paper, live
    broker: str = "mt5"
    magic_number: int = 20240101


@dataclass
class Config:
    """Top-level configuration aggregating all sections."""

    data: DataConfig = field(default_factory=DataConfig)
    features: FeatureConfig = field(default_factory=FeatureConfig)
    labeling: LabelingConfig = field(default_factory=LabelingConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)


# ---------------------------------------------------------------------------
# YAML loading (layered)
# ---------------------------------------------------------------------------
def _parse_yaml_text(text: str) -> Dict[str, Any]:
    """Parse YAML text using whichever backend is available.

    Order: PyYAML, then ruamel.yaml, then the stdlib fallback parser.
    """
    try:  # 1) PyYAML
        import yaml  # type: ignore

        data = yaml.safe_load(text)
        return data or {}
    except Exception:
        pass

    try:  # 2) ruamel.yaml (preinstalled in the sandbox)
        from ruamel.yaml import YAML  # type: ignore
        import io

        yml = YAML(typ="safe")
        data = yml.load(io.StringIO(text))
        return dict(data) if data else {}
    except Exception:
        pass

    # 3) Pure-stdlib fallback for simple mapping-of-scalars / nested mappings.
    return _fallback_yaml_parse(text)


def _coerce_scalar(raw: str) -> Any:
    """Convert a YAML scalar token into a Python value."""
    s = raw.strip()
    if s == "" or s == "~" or s.lower() == "null":
        return None
    low = s.lower()
    if low in ("true", "yes", "on"):
        return True
    if low in ("false", "no", "off"):
        return False
    # Quoted string
    if (len(s) >= 2) and ((s[0] == s[-1] == '"') or (s[0] == s[-1] == "'")):
        return s[1:-1]
    # Inline flow list: [a, b, c]
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1].strip()
        if not inner:
            return []
        return [_coerce_scalar(part) for part in _split_flow(inner)]
    # Numbers
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    return s


def _split_flow(inner: str) -> List[str]:
    """Split a flow-list body on commas not inside quotes."""
    parts: List[str] = []
    buf = []
    quote = None
    for ch in inner:
        if quote:
            buf.append(ch)
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
            buf.append(ch)
        elif ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return parts


def _fallback_yaml_parse(text: str) -> Dict[str, Any]:
    """Minimal indentation-based YAML parser for simple nested mappings.

    Supports: ``key: value`` scalars, nested mappings via indentation, inline
    flow lists ``[a, b]``, and block lists of scalars (``- item``). Comments
    (``#``) and blank lines are ignored. This is intentionally limited to what
    ``default.yaml`` needs; richer YAML should install PyYAML.
    """
    root: Dict[str, Any] = {}
    # Stack of (indent, container) where container is the dict being filled.
    stack: List[Any] = [(-1, root)]
    pending_list_key: Optional[str] = None
    pending_list_indent = -1

    for raw_line in text.splitlines():
        # Strip trailing comments (only when not inside quotes - inputs are simple).
        line = raw_line.split("#", 1)[0].rstrip() if "#" in raw_line else raw_line.rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        content = line.strip()

        # Block list item belonging to the most recent key.
        if content.startswith("- "):
            item = _coerce_scalar(content[2:])
            parent = _container_for_indent(stack, indent)
            if pending_list_key is not None:
                parent.setdefault(pending_list_key, [])
                if isinstance(parent.get(pending_list_key), list):
                    parent[pending_list_key].append(item)
            continue

        if ":" not in content:
            continue
        key, _, rest = content.partition(":")
        key = key.strip()
        rest = rest.strip()

        parent = _container_for_indent(stack, indent)

        if rest == "":
            # Could be a nested mapping or a block list; create a dict and let
            # subsequent lines decide. Register as pending list key too.
            child: Dict[str, Any] = {}
            parent[key] = child
            stack.append((indent, child))
            pending_list_key = key
            pending_list_indent = indent
        else:
            parent[key] = _coerce_scalar(rest)
            pending_list_key = None

    _prune_empty_mappings(root)
    return root


def _container_for_indent(stack: List[Any], indent: int) -> Dict[str, Any]:
    """Pop the stack until the top container is a strict parent of ``indent``."""
    while len(stack) > 1 and stack[-1][0] >= indent:
        stack.pop()
    return stack[-1][1]


def _prune_empty_mappings(d: Dict[str, Any]) -> None:
    """Replace empty-dict values that were actually block lists already handled.

    Block lists are stored under their key as a list by the ``- `` branch, which
    overwrites the placeholder dict. Any remaining empty dict is left as-is (a
    genuinely empty mapping)."""
    return None


# ---------------------------------------------------------------------------
# Mapping -> dataclass coercion
# ---------------------------------------------------------------------------
def _build_dataclass(cls, data: Optional[Dict[str, Any]]):
    """Recursively instantiate dataclass ``cls`` from a mapping, keeping defaults."""
    if data is None:
        return cls()
    if not isinstance(data, dict):
        raise TypeError(f"expected mapping for {cls.__name__}, got {type(data)!r}")
    kwargs: Dict[str, Any] = {}
    # Resolve annotations to real types (``from __future__ import annotations``
    # makes ``f.type`` a string, so is_dataclass() would never recurse).
    try:
        type_hints = typing.get_type_hints(cls)
    except Exception:
        type_hints = {f.name: f.type for f in fields(cls)}
    type_hints = {f.name: type_hints.get(f.name, f.type) for f in fields(cls)}
    valid = set(type_hints)
    for name, value in data.items():
        if name not in valid:
            continue  # ignore unknown keys for forward-compatibility
        ftype = type_hints[name]
        if is_dataclass(ftype):
            kwargs[name] = _build_dataclass(ftype, value)
        else:
            kwargs[name] = value
    return cls(**kwargs)


def _validate(cfg: Config) -> Config:
    """Validate cross-section invariants, failing loud on silent footguns.

    ATR window coupling: the triple-barrier LABELS (what the model learns from)
    are sized with ``labeling.atr_window`` while the stops/targets the backtest
    actually TRADES are sized with ``features.atr_window``. If these two
    independent keys ever disagree, the model would be trained on a different
    barrier distance than the one executed, silently degrading the filter. Rather
    than let that pass unnoticed we refuse to load such a config and name both
    keys so the fix is obvious. (See the README "Configuration" section.)
    """
    if cfg.features.atr_window != cfg.labeling.atr_window:
        raise ValueError(
            "ATR window mismatch: features.atr_window "
            f"({cfg.features.atr_window}) must equal labeling.atr_window "
            f"({cfg.labeling.atr_window}). The backtest sizes traded stops/"
            "targets from features.atr_window while the training labels are "
            "sized from labeling.atr_window; keeping them equal ensures the "
            "model learns the same barrier geometry the backtest executes. "
            "Set both keys to the same value in your config."
        )
    return cfg


def from_dict(data: Dict[str, Any]) -> Config:
    """Build a :class:`Config` from a plain mapping (e.g. parsed YAML)."""
    data = data or {}
    cfg = Config(
        data=_build_dataclass(DataConfig, data.get("data")),
        features=_build_dataclass(FeatureConfig, data.get("features")),
        labeling=_build_dataclass(LabelingConfig, data.get("labeling")),
        model=_build_dataclass(ModelConfig, data.get("model")),
        backtest=_build_dataclass(BacktestConfig, data.get("backtest")),
        risk=_build_dataclass(RiskConfig, data.get("risk")),
        execution=_build_dataclass(ExecutionConfig, data.get("execution")),
    )
    return _validate(cfg)


def load_config(path: str = "configs/default.yaml") -> Config:
    """Load and parse the YAML config file at ``path`` into a :class:`Config`.

    Falls back through PyYAML -> ruamel.yaml -> stdlib parser. Raises
    ``FileNotFoundError`` if the file does not exist.
    """
    with open(path, "r", encoding="utf-8") as fh:
        text = fh.read()
    raw = _parse_yaml_text(text)
    return from_dict(raw)
