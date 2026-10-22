"""Broker interface (SPEC §7). Replay, paper, and live differ only in which Broker runs."""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol, TypeVar

log = logging.getLogger(__name__)

Side = Literal["buy", "sell"]
OrderType = Literal["market", "limit", "stop"]
# Normalised broker order status. Maps 1:1 onto our order states after `submitted`.
BrokerStatus = Literal["accepted", "partially_filled", "filled", "canceled", "rejected", "expired"]
OPEN_STATUSES: frozenset[str] = frozenset({"accepted", "partially_filled"})


@dataclass(frozen=True)
class OrderRequest:
    client_order_id: str
    symbol: str
    side: Side
    type: OrderType = "market"
    qty: Decimal | None = None
    notional: Decimal | None = None
    limit_price: Decimal | None = None
    stop_price: Decimal | None = None

    def __post_init__(self) -> None:
        if (self.qty is None) == (self.notional is None):
            raise ValueError("exactly one of qty or notional is required")


@dataclass(frozen=True)
class BrokerOrder:
    broker_order_id: str
    client_order_id: str
    symbol: str
    side: Side
    status: BrokerStatus
    filled_qty: Decimal
    filled_avg_price: Decimal | None
    fee: Decimal
    updated_at: datetime
    reject_reason: str | None = None


@dataclass(frozen=True)
class BrokerPosition:
    symbol: str
    qty: Decimal
    avg_price: Decimal


@dataclass(frozen=True)
class AccountInfo:
    cash: Decimal
    buying_power: Decimal
    equity: Decimal


class BrokerError(Exception):
    """Base for broker failures."""


class BrokerTransientError(BrokerError):
    """5xx, timeouts, rate limits: safe to retry."""


class BrokerAuthError(BrokerError):
    """Expired or invalid credentials: pause the instance and alert."""


class BrokerRejected(BrokerError):
    """The broker refused this order; retrying won't help."""


class DuplicateClientOrderId(BrokerError):
    """The broker already has an order with this client_order_id (a retried submit)."""


class LiveTradingRefused(BrokerError):
    """Live trading requested without ALLOW_LIVE_TRADING=true and an is_live account."""


class Broker(Protocol):
    name: str

    async def submit_order(self, req: OrderRequest) -> BrokerOrder: ...
    async def cancel_order(self, broker_order_id: str) -> None: ...
    async def get_order(self, broker_order_id: str) -> BrokerOrder: ...
    async def get_order_by_client_id(self, client_order_id: str) -> BrokerOrder | None: ...
    async def list_open_orders(self) -> list[BrokerOrder]: ...
    async def get_positions(self) -> list[BrokerPosition]: ...
    async def get_account(self) -> AccountInfo: ...


T = TypeVar("T")


async def with_retry(
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int = 4,
    base_delay: float = 0.5,
    what: str = "broker call",
) -> T:
    """Retry transient broker errors with jittered exponential backoff."""
    for attempt in range(1, attempts + 1):
        try:
            return await fn()
        except BrokerTransientError as e:
            if attempt == attempts:
                raise
            delay = base_delay * 2 ** (attempt - 1) * (0.5 + random.random())
            log.warning(
                "transient broker error, retrying",
                extra={"what": what, "attempt": attempt, "delay_s": round(delay, 2), "error": str(e)},
            )
            await asyncio.sleep(delay)
    raise AssertionError("unreachable")
