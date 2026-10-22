"""Alpaca market data (free IEX feed): historical REST and the live websocket.

Alpaca's websocket only streams 1-minute bars, so `stream()` aggregates them into the
requested timeframe. A bucket is emitted when its last minute arrives or when a later
bucket starts (IEX skips minutes with no prints).
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from alpaca.data.enums import DataFeed
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.live import StockDataStream
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame, TimeFrameUnit

from atp.marketdata.base import in_regular_session
from atp.schema.agent import TIMEFRAME_SECONDS
from atp.schema.messages import Bar

log = logging.getLogger(__name__)

_TF = {
    "1Min": TimeFrame(1, TimeFrameUnit.Minute),
    "5Min": TimeFrame(5, TimeFrameUnit.Minute),
    "15Min": TimeFrame(15, TimeFrameUnit.Minute),
    "1Hour": TimeFrame(1, TimeFrameUnit.Hour),
}


def _bar(symbol: str, timeframe: str, raw: Any) -> Bar:
    return Bar(
        symbol=symbol,
        timeframe=timeframe,
        ts=raw.timestamp,
        open=Decimal(str(raw.open)),
        high=Decimal(str(raw.high)),
        low=Decimal(str(raw.low)),
        close=Decimal(str(raw.close)),
        volume=Decimal(str(raw.volume)),
    )


class BarAggregator:
    """Rolls 1-minute bars into N-second buckets aligned to the epoch."""

    def __init__(self, timeframe: str) -> None:
        self.timeframe = timeframe
        self.seconds = TIMEFRAME_SECONDS[timeframe]
        self._open: dict[str, Bar] = {}

    def _bucket(self, ts: datetime) -> datetime:
        epoch = int(ts.timestamp())
        return datetime.fromtimestamp(epoch - epoch % self.seconds, ts.tzinfo)

    def add(self, minute: Bar) -> list[Bar]:
        out: list[Bar] = []
        start = self._bucket(minute.ts)
        cur = self._open.get(minute.symbol)
        if cur is not None and cur.ts != start:
            out.append(cur)
            cur = None
        if cur is None:
            cur = minute.model_copy(update={"ts": start, "timeframe": self.timeframe})
        else:
            cur = cur.model_copy(
                update={
                    "high": max(cur.high, minute.high),
                    "low": min(cur.low, minute.low),
                    "close": minute.close,
                    "volume": cur.volume + minute.volume,
                }
            )
        if minute.ts + timedelta(seconds=60) >= start + timedelta(seconds=self.seconds):
            out.append(cur)
            self._open.pop(minute.symbol, None)
        else:
            self._open[minute.symbol] = cur
        return out


class AlpacaDataSource:
    def __init__(self, api_key: str, secret_key: str, feed: str = "iex") -> None:
        if not api_key or not secret_key:
            raise ValueError("Alpaca market data needs ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY")
        self._key, self._secret = api_key, secret_key
        self._feed = DataFeed(feed)
        self._hist = StockHistoricalDataClient(api_key, secret_key)

    async def history(
        self, symbols: Sequence[str], start: datetime, end: datetime, timeframe: str
    ) -> list[Bar]:
        req = StockBarsRequest(
            symbol_or_symbols=list(symbols),
            timeframe=_TF[timeframe],
            start=start,
            end=end,
            feed=self._feed,
        )
        resp: Any = await asyncio.to_thread(self._hist.get_stock_bars, req)
        out: list[Bar] = []
        for symbol, rows in resp.data.items():
            out.extend(_bar(symbol, timeframe, r) for r in rows if in_regular_session(r.timestamp))
        out.sort(key=lambda b: (b.ts, b.symbol))
        return out

    async def stream(self, symbols: Sequence[str], timeframe: str) -> AsyncIterator[Bar]:
        queue: asyncio.Queue[Bar] = asyncio.Queue()
        agg = BarAggregator(timeframe)
        ws = StockDataStream(self._key, self._secret, feed=self._feed)

        async def on_bar(raw: Any) -> None:
            minute = _bar(raw.symbol, "1Min", raw)
            if not in_regular_session(minute.ts):
                return
            for b in agg.add(minute) if timeframe != "1Min" else [minute]:
                await queue.put(b)

        ws.subscribe_bars(on_bar, *symbols)
        task = asyncio.create_task(ws._run_forever())
        try:
            while True:
                yield await queue.get()
        finally:
            await ws.stop_ws()
            task.cancel()
