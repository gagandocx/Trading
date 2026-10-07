"""The live-trading safety switch.

This module centralises the ONE decision that separates harmless research from
placing real money at risk: *are we allowed to send a live order right now?*

The rule is intentionally strict and fails CLOSED:

    A real order is permitted ONLY when BOTH
      * ``config.execution.live_trading_enabled is True``  (an explicit opt-in), AND
      * ``config.execution.mode == 'live'``               (an explicit mode)
    hold. In EVERY other case :func:`ensure_live_allowed` raises
    :class:`LiveTradingDisabled` with a loud, explicit message.

Any MetaTrader5 (or other broker) order routing MUST call
:func:`ensure_live_allowed` before doing anything, and MetaTrader5 is imported
LAZILY (inside the routing function) so merely importing this module never needs
the package and never risks a connection.

Default config ships with ``live_trading_enabled: false`` and ``mode: paper``, so
out of the box this guard refuses everything. That is deliberate.
"""

from __future__ import annotations

from typing import Any


class LiveTradingDisabled(RuntimeError):
    """Raised when a real order is attempted while live trading is not enabled.

    This is a loud, explicit refusal - never swallow it to "just place the
    order". If you see this, live trading is OFF by design.
    """


def _execution_cfg(config: Any):
    """Return the ``execution`` section of a Config, tolerating a raw section."""
    return getattr(config, "execution", config)


def is_live_allowed(config: Any) -> bool:
    """Return ``True`` only if BOTH the enable flag and live mode are set.

    Pure predicate; never raises. Use :func:`ensure_live_allowed` at the actual
    order-routing boundary so the refusal is loud.
    """
    exe = _execution_cfg(config)
    enabled = bool(getattr(exe, "live_trading_enabled", False))
    mode = str(getattr(exe, "mode", "paper")).lower()
    return enabled and mode == "live"


def ensure_live_allowed(config: Any) -> None:
    """Guard that REFUSES real orders unless live trading is explicitly enabled.

    Raises
    ------
    LiveTradingDisabled
        Unless ``execution.live_trading_enabled`` is ``True`` AND
        ``execution.mode == 'live'``.
    """
    exe = _execution_cfg(config)
    enabled = bool(getattr(exe, "live_trading_enabled", False))
    mode = str(getattr(exe, "mode", "paper")).lower()

    if not enabled:
        raise LiveTradingDisabled(
            "LIVE TRADING IS DISABLED. Refusing to place a real order because "
            "execution.live_trading_enabled is False. This is the safe default. "
            "To trade live you must deliberately set execution.live_trading_enabled: "
            "true AND execution.mode: live in your config, and you accept full "
            "responsibility for the financial risk."
        )
    if mode != "live":
        raise LiveTradingDisabled(
            "LIVE TRADING IS DISABLED. execution.live_trading_enabled is True but "
            f"execution.mode is {mode!r}, not 'live'. Refusing to place a real "
            "order. Set execution.mode: live to confirm you intend to send real "
            "orders."
        )
    # Both conditions satisfied: the caller may proceed to route a real order.
    return None


def route_order_mt5(config: Any, order: Any):  # pragma: no cover - needs MT5 + opt-in
    """Route a real order to MetaTrader 5 - gated by :func:`ensure_live_allowed`.

    This is the ONLY place that would send a live order. It:

    1. Calls :func:`ensure_live_allowed` first (raises if live trading is off).
    2. Imports MetaTrader5 LAZILY (never required to import this module).

    It is intentionally left as a thin stub: wiring a specific broker's
    ``order_send`` request is deployment-specific and must be done by the user on
    a Windows machine with a funded/demo account they control.
    """
    ensure_live_allowed(config)

    try:
        import MetaTrader5 as mt5  # type: ignore  # noqa: F401
    except Exception as exc:
        raise RuntimeError(
            "MetaTrader5 is not installed. Live order routing requires the "
            "MetaTrader5 package on a Windows machine with a running MT5 terminal. "
            "See src/xauusd_bot/data/mt5_connector.py for setup."
        ) from exc

    raise NotImplementedError(
        "Live order routing is intentionally not implemented. Even with live "
        "trading enabled, wire your broker's MetaTrader5 order_send() here only "
        "after you fully understand the risk. Paper-trade first."
    )
