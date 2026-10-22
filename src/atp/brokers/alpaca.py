"""Alpaca broker adapter (paper and live) wrapping `alpaca-py`.

Live trading requires BOTH `ALLOW_LIVE_TRADING=true` and an account row with
`is_live=true`; otherwise construction refuses (SPEC §7, §8).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, TypeVar

import httpx
import requests
from alpaca.common.exceptions import APIError
from alpaca.trading.client import TradingClient
from alpaca.trading.enums import OrderSide, QueryOrderStatus, TimeInForce
from alpaca.trading.requests import (
    GetOrdersRequest,
    LimitOrderRequest,
    MarketOrderRequest,
    StopOrderRequest,
)

from atp.brokers.base import (
    AccountInfo,
    BrokerAuthError,
    BrokerOrder,
    BrokerPosition,
    BrokerRejected,
    BrokerStatus,
    BrokerTransientError,
    DuplicateClientOrderId,
    LiveTradingRefused,
    OrderRequest,
)

T = TypeVar("T")

_STATUS: dict[str, BrokerStatus] = {
    "new": "accepted",
    "accepted": "accepted",
    "pending_new": "accepted",
    "accepted_for_bidding": "accepted",
    "held": "accepted",
    "calculated": "accepted",
    "pending_cancel": "accepted",
    "pending_replace": "accepted",
    "replaced": "canceled",
    "partially_filled": "partially_filled",
    "filled": "filled",
    "done_for_day": "expired",
    "expired": "expired",
    "canceled": "canceled",
    "stopped": "accepted",
    "suspended": "accepted",
    "rejected": "rejected",
}


def _dec(v: Any) -> Decimal | None:
    return None if v in (None, "") else Decimal(str(v))


def _status(raw: Any) -> BrokerStatus:
    key = str(getattr(raw, "value", raw)).lower()
    return _STATUS.get(key, "accepted")


def _to_order(o: Any) -> BrokerOrder:
    return BrokerOrder(
        broker_order_id=str(o.id),
        client_order_id=str(o.client_order_id),
        symbol=str(o.symbol),
        side="buy" if str(getattr(o.side, "value", o.side)).lower() == "buy" else "sell",
        status=_status(o.status),
        filled_qty=_dec(o.filled_qty) or Decimal(0),
        filled_avg_price=_dec(o.filled_avg_price),
        fee=Decimal(0),  # Alpaca equities are commission-free; reg fees settle separately
        updated_at=o.updated_at or o.submitted_at or datetime.now(UTC),
    )


class AlpacaBroker:
    def __init__(
        self,
        api_key: str,
        secret_key: str,
        *,
        live: bool,
        allow_live_trading: bool,
        account_is_live: bool,
        client: TradingClient | None = None,
    ) -> None:
        if live and not (allow_live_trading and account_is_live):
            raise LiveTradingRefused(
                "live Alpaca trading needs ALLOW_LIVE_TRADING=true and an is_live account row"
            )
        if not live and account_is_live:
            raise LiveTradingRefused("paper mode was requested for a live account row")
        self.name = "alpaca_live" if live else "alpaca_paper"
        self._client = client or TradingClient(api_key, secret_key, paper=not live)

    async def _call(self, fn: Callable[..., T], *args: Any) -> T:
        try:
            return await asyncio.wait_for(asyncio.to_thread(fn, *args), timeout=15)
        except TimeoutError as e:
            raise BrokerTransientError("alpaca timeout") from e
        except (requests.ConnectionError, requests.Timeout, httpx.TransportError) as e:
            raise BrokerTransientError(f"alpaca connection error: {e}") from e
        except APIError as e:
            code = e.status_code or 0
            msg = str(e)
            if code in (401, 403):
                raise BrokerAuthError(f"alpaca auth failed ({code})") from e
            if code == 429 or code >= 500:
                raise BrokerTransientError(f"alpaca {code}: {msg}") from e
            if code == 422 and "client_order_id" in msg.lower():
                raise DuplicateClientOrderId(msg) from e
            if code == 404:
                raise BrokerRejected(f"not found: {msg}") from e
            raise BrokerRejected(f"alpaca {code}: {msg}") from e

    async def submit_order(self, req: OrderRequest) -> BrokerOrder:
        common: dict[str, Any] = {
            "symbol": req.symbol,
            "side": OrderSide.BUY if req.side == "buy" else OrderSide.SELL,
            "time_in_force": TimeInForce.DAY,
            "client_order_id": req.client_order_id,
        }
        if req.qty is not None:
            common["qty"] = float(req.qty)
        else:
            common["notional"] = float(req.notional or 0)
        order_req: MarketOrderRequest | LimitOrderRequest | StopOrderRequest
        if req.type == "limit":
            order_req = LimitOrderRequest(limit_price=float(req.limit_price or 0), **common)
        elif req.type == "stop":
            order_req = StopOrderRequest(stop_price=float(req.stop_price or 0), **common)
        else:
            order_req = MarketOrderRequest(**common)
        return _to_order(await self._call(self._client.submit_order, order_req))

    async def cancel_order(self, broker_order_id: str) -> None:
        await self._call(self._client.cancel_order_by_id, broker_order_id)

    async def get_order(self, broker_order_id: str) -> BrokerOrder:
        return _to_order(await self._call(self._client.get_order_by_id, broker_order_id))

    async def get_order_by_client_id(self, client_order_id: str) -> BrokerOrder | None:
        try:
            return _to_order(await self._call(self._client.get_order_by_client_id, client_order_id))
        except BrokerRejected as e:
            if str(e).startswith("not found"):
                return None
            raise

    async def list_open_orders(self) -> list[BrokerOrder]:
        rows = await self._call(
            self._client.get_orders, GetOrdersRequest(status=QueryOrderStatus.OPEN, limit=500)
        )
        return [_to_order(o) for o in rows]

    async def get_positions(self) -> list[BrokerPosition]:
        rows: Any = await self._call(self._client.get_all_positions)
        return [
            BrokerPosition(str(p.symbol), _dec(p.qty) or Decimal(0), _dec(p.avg_entry_price) or Decimal(0))
            for p in rows
        ]

    async def get_account(self) -> AccountInfo:
        a: Any = await self._call(self._client.get_account)
        return AccountInfo(
            cash=_dec(a.cash) or Decimal(0),
            buying_power=_dec(a.buying_power) or Decimal(0),
            equity=_dec(a.equity) or Decimal(0),
        )
