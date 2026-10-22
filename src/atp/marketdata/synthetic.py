"""Deterministic synthetic bars for keyless development and tests.

NOT market data. Rows are stored with source="synthetic" and the CLI labels them as such.
Trending days with sharp multi-bar pullbacks, so RSI dips above the trend actually happen.
"""

from __future__ import annotations

import hashlib
import random
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

from atp.marketdata.base import session_bounds
from atp.schema.agent import TIMEFRAME_SECONDS
from atp.schema.messages import Bar

_BASE = {"SPY": 580.0, "QQQ": 500.0, "AAPL": 230.0, "MSFT": 420.0, "NVDA": 130.0}


def _rng(symbol: str, day: date) -> random.Random:
    seed = int(hashlib.sha256(f"{symbol}:{day.isoformat()}".encode()).hexdigest()[:16], 16)
    return random.Random(seed)


def synth_day(symbol: str, day: date, timeframe: str = "5Min", start_price: float | None = None) -> list[Bar]:
    rng = _rng(symbol, day)
    open_, close = session_bounds(day)
    step = timedelta(seconds=TIMEFRAME_SECONDS[timeframe])
    price = start_price or _BASE.get(symbol, 100.0) * (1 + rng.uniform(-0.03, 0.03))
    trend = rng.uniform(0.0002, 0.0007)  # per-bar drift: mostly up-trending days
    out: list[Bar] = []
    ts = open_
    pullback = 0
    while ts < close:
        if pullback == 0 and rng.random() < 0.03:
            pullback = rng.randint(2, 3)  # a sharp multi-bar sell-off inside the trend
        if pullback > 0:
            ret = -abs(rng.gauss(0.004, 0.001))
            pullback -= 1
        else:
            ret = trend + rng.gauss(0, 0.0005)
        o = price
        c = max(0.01, price * (1 + ret))
        hi = max(o, c) * (1 + abs(rng.gauss(0, 0.0005)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, 0.0005)))
        q = Decimal("0.01")
        out.append(
            Bar(
                symbol=symbol,
                timeframe=timeframe,
                ts=ts,
                open=Decimal(o).quantize(q),
                high=Decimal(hi).quantize(q),
                low=Decimal(lo).quantize(q),
                close=Decimal(c).quantize(q),
                volume=Decimal(rng.randint(5_000, 80_000)),
            )
        )
        price = c
        ts += step
    return out


def synth_days(symbols: Sequence[str], days: Sequence[date], timeframe: str = "5Min") -> list[Bar]:
    bars: list[Bar] = []
    for sym in symbols:
        last: float | None = None
        for d in sorted(days):
            day_bars = synth_day(sym, d, timeframe, last)
            bars.extend(day_bars)
            last = float(day_bars[-1].close) if day_bars else last
    bars.sort(key=lambda b: (b.ts, b.symbol))
    return bars
