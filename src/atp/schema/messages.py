"""Messages that cross process boundaries (NATS payloads)."""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_serializer


class Bar(BaseModel):
    """One OHLCV bar. `ts` is the bar's open time (UTC), matching Alpaca's convention."""

    model_config = ConfigDict(frozen=True)

    symbol: str
    timeframe: str
    ts: AwareDatetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal
    # Set for replay runs so replay bars never reach paper or live instances.
    run_id: uuid.UUID | None = None

    @field_serializer("open", "high", "low", "close", "volume")
    def _dec(self, v: Decimal) -> str:
        return str(v)


class PositionSnapshot(BaseModel):
    qty: Decimal
    avg_price: Decimal

    @field_serializer("qty", "avg_price")
    def _dec(self, v: Decimal) -> str:
        return str(v)


class WakeJob(BaseModel):
    """Published by the watch engine; one per (instance, symbol, bar).

    Carries everything the worker needs to decide, so decisions replay exactly.
    """

    instance_id: uuid.UUID
    agent_id: str
    version: int
    symbol: str
    bar: Bar
    indicators: dict[str, float | None]
    recent_closes: list[str]
    trigger: Literal["entry", "exit"]
    position: PositionSnapshot | None = None
    run_id: uuid.UUID | None = None

    @property
    def msg_id(self) -> str:
        # SPEC §5 names `{instance_id}:{bar_ts}`; the symbol is added because one
        # instance watches several symbols that close bars at the same timestamp.
        return wake_msg_id(self.instance_id, self.symbol, self.bar.ts)


def wake_msg_id(instance_id: uuid.UUID, symbol: str, bar_ts: datetime) -> str:
    return f"{instance_id}:{symbol}:{bar_ts.isoformat()}"


class Event(BaseModel):
    kind: str
    instance_id: uuid.UUID | None = None
    detail: dict[str, object] = {}
