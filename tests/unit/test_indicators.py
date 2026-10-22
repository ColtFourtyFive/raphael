import pandas as pd
import pytest

from atp.indicators import ema, rsi, sma

CLOSES = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08, 45.89, 46.03, 45.61, 46.28,
          46.28, 46.00, 46.03, 46.41, 46.22, 45.64]


def test_sma_known_values() -> None:
    assert sma([1, 2, 3, 4, 5], 5) == 3
    assert sma([1, 2, 3, 4, 5], 2) == 4.5
    assert sma([1, 2], 3) is None


def test_ema_matches_pandas_after_sma_seed() -> None:
    period = 10
    seed = sum(CLOSES[:period]) / period
    s = pd.Series([seed, *CLOSES[period:]])
    expected = s.ewm(span=period, adjust=False).mean().iloc[-1]
    assert ema(CLOSES, period) == pytest.approx(expected)
    assert ema(CLOSES[:9], period) is None


def test_rsi_wilder_hand_computed() -> None:
    # changes +1, -1 -> avg gain 0.5, avg loss 0.5 -> RSI 50
    assert rsi([1, 2, 1], 2) == pytest.approx(50.0)
    # next change +1 -> gain (0.5*1 + 1)/2 = 0.75, loss (0.5*1 + 0)/2 = 0.25 -> RS 3 -> RSI 75
    assert rsi([1, 2, 1, 2], 2) == pytest.approx(75.0)
    assert rsi(CLOSES[:14], 14) is None
    assert 0 < (rsi(CLOSES, 14) or 0) < 100


def test_rsi_edges() -> None:
    assert rsi([1, 2, 3, 4, 5, 6], 5) == 100.0
    assert rsi([5, 5, 5, 5, 5, 5], 5) == 50.0
    assert rsi([6, 5, 4, 3, 2, 1], 5) == 0.0
