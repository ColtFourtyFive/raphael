"""Indicators: our own SMA, EMA, RSI (no TA-Lib).

Every function takes the full window of closes (oldest first) and returns the value
at the last bar, or None when the window is too short. Values depend only on the
window, so a restarted watch engine computes exactly what an uninterrupted one would.
"""

from __future__ import annotations

from collections.abc import Sequence

from atp.schema.agent import IndicatorSpec


def sma(closes: Sequence[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    return sum(closes[-period:]) / period


def ema(closes: Sequence[float], period: int) -> float | None:
    """EMA seeded with the SMA of the first `period` closes in the window."""
    if len(closes) < period:
        return None
    alpha = 2.0 / (period + 1)
    value = sum(closes[:period]) / period
    for c in closes[period:]:
        value = alpha * c + (1 - alpha) * value
    return value


def rsi(closes: Sequence[float], period: int) -> float | None:
    """Wilder's RSI, seeded with simple averages of the first `period` changes."""
    if len(closes) < period + 1:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(1, period + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0.0)
        losses += max(-d, 0.0)
    avg_gain = gains / period
    avg_loss = losses / period
    for i in range(period + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * (period - 1) + max(d, 0.0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-d, 0.0)) / period
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


_FUNCS = {"SMA": sma, "EMA": ema, "RSI": rsi}


def compute(spec: IndicatorSpec, closes: Sequence[float]) -> float | None:
    return _FUNCS[spec.type](closes, spec.period)


def spec_key(spec: IndicatorSpec) -> tuple[str, int]:
    """Indicators are shared across instances by (type, period), not by agent-local id."""
    return (spec.type, spec.period)
