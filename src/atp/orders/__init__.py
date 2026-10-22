"""Order manager (SPEC §7): state machine, idempotent submission, broker sync.

proposed → approved → submitted → accepted → partially_filled → filled,
and → canceled | rejected | expired from any open state. Every transition is an
`order_events` row. `client_order_id` is unique in Postgres and at the broker, so a
retried submit can never place a second order.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atp import ledger
from atp.brokers.base import (
    Broker,
    BrokerOrder,
    BrokerRejected,
    DuplicateClientOrderId,
    OrderRequest,
    with_retry,
)
from atp.clock import Clock
from atp.db.models import Order, OrderEvent

log = logging.getLogger(__name__)

OPEN_STATES = frozenset({"proposed", "approved", "submitted", "accepted", "partially_filled"})
AT_BROKER_STATES = frozenset({"submitted", "accepted", "partially_filled"})
TERMINAL = frozenset({"filled", "canceled", "rejected", "expired"})

TRANSITIONS: dict[str, frozenset[str]] = {
    "proposed": frozenset({"approved", "rejected", "canceled"}),
    "approved": frozenset({"submitted", "rejected", "canceled"}),
    "submitted": frozenset({"accepted", "partially_filled", "filled", "rejected", "canceled", "expired"}),
    "accepted": frozenset({"partially_filled", "filled", "rejected", "canceled", "expired"}),
    "partially_filled": frozenset({"partially_filled", "filled", "canceled", "expired"}),
}


class InvalidTransition(RuntimeError):
    pass


def client_order_id(instance_id: uuid.UUID, decision_id: uuid.UUID) -> str:
    return f"{instance_id}-{decision_id}"


def transition(session: AsyncSession, order: Order, to: str, ts: datetime, **payload: Any) -> None:
    frm = order.state
    if frm == to and to != "partially_filled":
        return
    if to not in TRANSITIONS.get(frm, frozenset()):
        raise InvalidTransition(f"order {order.client_order_id}: {frm} → {to}")
    order.state = to
    order.updated_at = ts
    session.add(OrderEvent(order_id=order.id, from_state=frm, to_state=to, payload=payload, ts=ts))


def new_order(
    session: AsyncSession,
    *,
    instance_id: uuid.UUID,
    decision_id: uuid.UUID,
    symbol: str,
    side: str,
    ts: datetime,
    qty: Decimal | None = None,
    notional: Decimal | None = None,
    type: str = "market",
) -> Order:
    order = Order(
        id=uuid.uuid4(),
        client_order_id=client_order_id(instance_id, decision_id),
        instance_id=instance_id,
        decision_id=decision_id,
        symbol=symbol,
        side=side,
        qty=qty,
        notional=notional,
        type=type,
        state="proposed",
        created_at=ts,
        updated_at=ts,
    )
    session.add(order)
    session.add(OrderEvent(order_id=order.id, from_state=None, to_state="proposed", payload={}, ts=ts))
    return order


async def apply_broker_order(session: AsyncSession, order: Order, bo: BrokerOrder) -> bool:
    """Fold the broker's view of an order into ours. Returns True if anything changed."""
    changed = False
    ts = bo.updated_at
    if order.state == "approved":
        transition(session, order, "submitted", ts, broker_order_id=bo.broker_order_id)
        changed = True
    if order.broker_order_id is None:
        order.broker_order_id = bo.broker_order_id
    delta = bo.filled_qty - order.filled_qty
    if delta > 0:
        prev_cost = order.filled_qty * (order.filled_avg_price or Decimal(0))
        total_cost = bo.filled_qty * (bo.filled_avg_price or Decimal(0))
        price = ((total_cost - prev_cost) / delta).quantize(ledger.PRICE_STEP)
        fee = bo.fee if bo.status == "filled" else Decimal(0)
        if await ledger.record_fill(
            session, order, delta, price, fee, ts, f"{bo.broker_order_id}:{bo.filled_qty}"
        ):
            order.filled_qty = bo.filled_qty
            order.filled_avg_price = bo.filled_avg_price
            changed = True
    target: str = bo.status
    if target == "partially_filled" and delta <= 0:
        target = order.state  # no new fill: nothing to log
    if target != order.state and order.state not in TERMINAL:
        transition(session, order, target, ts, filled_qty=str(bo.filled_qty), reason=bo.reject_reason)
        if target == "rejected":
            order.reject_reason = bo.reject_reason
        changed = True
    return changed


class OrderManager:
    def __init__(self, factory: async_sessionmaker[AsyncSession], clock: Clock) -> None:
        self._factory = factory
        self._clock = clock

    async def submit(self, order_id: uuid.UUID, broker: Broker) -> Order:
        """Send an approved order. Safe to call any number of times for the same order."""
        async with self._factory() as s:
            order = await s.get(Order, order_id)
            if order is None:
                raise LookupError(order_id)
            if order.state != "approved":
                return order
            req = OrderRequest(
                client_order_id=order.client_order_id,
                symbol=order.symbol,
                side=order.side,  # type: ignore[arg-type]
                type=order.type,  # type: ignore[arg-type]
                qty=order.qty,
                notional=order.notional,
                limit_price=order.limit_price,
                stop_price=order.stop_price,
            )
        try:
            bo = await with_retry(lambda: broker.submit_order(req), what="submit_order")
        except DuplicateClientOrderId:
            # A previous attempt reached the broker; adopt that order instead of re-sending.
            found = await broker.get_order_by_client_id(req.client_order_id)
            if found is None:
                raise
            bo = found
            log.info("adopted existing broker order", extra={"client_order_id": req.client_order_id})
        except BrokerRejected as e:
            async with self._factory() as s, s.begin():
                order = await s.get(Order, order_id, with_for_update=True)
                assert order is not None
                if order.state == "approved":
                    order.reject_reason = str(e)
                    transition(s, order, "rejected", self._clock.now(), reason=str(e))
                return order
        async with self._factory() as s, s.begin():
            order = await s.get(Order, order_id, with_for_update=True)
            assert order is not None
            await apply_broker_order(s, order, bo)
            return order

    async def sync_order(self, order_id: uuid.UUID, broker: Broker) -> bool:
        async with self._factory() as s:
            order = await s.get(Order, order_id)
            if order is None or order.broker_order_id is None or order.state in TERMINAL:
                return False
            ref = order.broker_order_id
        bo = await with_retry(lambda: broker.get_order(ref), what="get_order")
        async with self._factory() as s, s.begin():
            order = await s.get(Order, order_id, with_for_update=True)
            assert order is not None
            return await apply_broker_order(s, order, bo)

    async def sync_instance(self, instance_id: uuid.UUID, broker: Broker) -> int:
        """Pull fills and status for every open order of an instance. Returns orders changed."""
        async with self._factory() as s:
            ids = list(
                await s.scalars(
                    select(Order.id)
                    .where(Order.instance_id == instance_id, Order.state.in_(AT_BROKER_STATES))
                    .order_by(Order.created_at)
                )
            )
        changed = 0
        for oid in ids:
            changed += int(await self.sync_order(oid, broker))
        return changed

    async def cancel_open(self, instance_id: uuid.UUID, broker: Broker, reason: str) -> int:
        """Cancel everything open for an instance: unsent orders locally, sent ones at the broker."""
        now = self._clock.now()
        n = 0
        async with self._factory() as s, s.begin():
            local = await s.scalars(
                select(Order)
                .where(Order.instance_id == instance_id, Order.state.in_(["proposed", "approved"]))
                .with_for_update()
            )
            for order in local:
                transition(s, order, "canceled", now, reason=reason)
                n += 1
        async with self._factory() as s:
            sent = list(
                await s.scalars(
                    select(Order).where(Order.instance_id == instance_id, Order.state.in_(AT_BROKER_STATES))
                )
            )
        for order in sent:
            assert order.broker_order_id is not None
            ref = order.broker_order_id
            await with_retry(lambda ref=ref: broker.cancel_order(ref), what="cancel_order")  # type: ignore[misc]
            await self.sync_order(order.id, broker)
            n += 1
        return n

    async def approve(self, order_id: uuid.UUID, broker: Broker) -> Order:
        async with self._factory() as s, s.begin():
            order = await s.get(Order, order_id, with_for_update=True)
            if order is None:
                raise LookupError(order_id)
            transition(s, order, "approved", self._clock.now(), by="admin")
        return await self.submit(order_id, broker)

    async def reject(self, order_id: uuid.UUID, reason: str = "rejected by admin") -> None:
        async with self._factory() as s, s.begin():
            order = await s.get(Order, order_id, with_for_update=True)
            if order is None:
                raise LookupError(order_id)
            transition(s, order, "rejected", self._clock.now(), reason=reason)
            order.reject_reason = reason
