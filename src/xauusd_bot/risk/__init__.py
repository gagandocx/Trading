"""Risk-management package.

Position sizing and portfolio guardrails for XAUUSD trading. All sizing is
ATR-based (stop distance derived from ATR) and the module enforces a hard
max-drawdown guardrail that halts new entries once equity falls too far from its
running peak. Functions are pure where possible so they are trivially testable.
"""

from .risk import (  # noqa: F401
    DrawdownGuard,
    drawdown_exceeded,
    position_size,
    cap_lots,
)
