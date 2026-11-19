"""Broker-native protective stops (SPEC §4: exits use broker-native stop orders where
the broker supports them).

After an entry fills, a stop-loss sell rests at the broker at avg * (1 - stop%), so the
position is protected even if our services are down. Take-profit stays rule-evaluated:
two resting sells without OCO could double-sell, or open a short on a margin account.

Stops are DAY orders at Alpaca, so the client order id includes the session date and a
new one is placed each trading day the position is still open.
"""

from __future__ import annotations

import logging
import uuid
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atp import ledger, orders, store
from atp.brokers.base import Broker, with_retry
from atp.clock import Clock
from atp.db.models import Instance, Order
from atp.marketdata.base import NY
from atp.orders import AT_BROKER_STATES, OPEN_STATES, OrderManager
from atp.schema.agent import AgentDefinition, StopLossPct

log = logging.getLogger(__name__)

PROTECTIVE = "protective_stop"
CENT = Decimal("0.01")


def stop_loss_pct(defn: AgentDefinition) -> float | None:
    return next((c.value for c in defn.exit.any if isinstance(c, StopLossPct)), None)


def stop_price(avg_price: Decimal, pct: float) -> Decimal:
    return (avg_price * (1 - Decimal(str(pct)) / 100)).quantize(CENT, rounding=ROUND_DOWN)


async def ensure_protective_stops(
    factory: async_sessionmaker[AsyncSession],
    inst: Instance,
    defn: AgentDefinition,
    broker: Broker,
    clock: Clock,
) -> int:
    """Place a stop for every held symbol that has none. Idempotent. Returns stops placed."""
    pct = stop_loss_pct(defn)
    if pct is None:
        return 0
    now = clock.now()
    session_day = now.astimezone(NY).strftime("%Y%m%d")
    to_submit: list[uuid.UUID] = []
    async with factory() as s, s.begin():
        current = await s.get(Instance, inst.id, with_for_update=True)
        if current is None or current.status != "running" or await store.kill_switch_on(s):
            return 0
        for symbol, pos in (await ledger.positions_for(s, inst.id)).items():
            busy = await s.scalar(
                select(Order.id).where(
                    Order.instance_id == inst.id,
                    Order.symbol == symbol,
                    Order.side == "sell",
                    Order.state.in_(OPEN_STATES),
                )
            )
            if busy is not None:
                continue  # a stop is already resting, or an exit is in flight
            entry = await s.scalar(
                select(Order)
                .where(
                    Order.instance_id == inst.id,
                    Order.symbol == symbol,
                    Order.side == "buy",
                    Order.filled_qty > 0,
                )
                .order_by(Order.created_at.desc())
                .limit(1)
            )
            if entry is None:
                continue
            cid = f"{entry.id}-sl-{session_day}"
            if await s.scalar(select(Order.id).where(Order.client_order_id == cid)) is not None:
                continue  # already placed today (and canceled/expired/rejected): don't loop
            order = Order(
                id=uuid.uuid4(),
                client_order_id=cid,
                instance_id=inst.id,
                decision_id=entry.decision_id,
                symbol=symbol,
                side="sell",
                qty=pos.qty,
                type="stop",
                purpose=PROTECTIVE,
                stop_price=stop_price(pos.avg_price, pct),
                state="proposed",
                created_at=now,
                updated_at=now,
            )
            s.add(order)
            await s.flush()
            orders.transition(
                s, order, "approved", now, by="protective_stop", stop_price=str(order.stop_price)
            )
            to_submit.append(order.id)
    om = OrderManager(factory, clock)
    for oid in to_submit:
        await om.submit(oid, broker)
    return len(to_submit)


async def cancel_protective(
    factory: async_sessionmaker[AsyncSession],
    instance_id: uuid.UUID,
    symbol: str,
    broker: Broker,
    clock: Clock,
) -> None:
    """Cancel resting protective stops for a symbol (before a rule-based exit)."""
    om = OrderManager(factory, clock)
    async with factory() as s:
        rows = list(
            await s.scalars(
                select(Order).where(
                    Order.instance_id == instance_id,
                    Order.symbol == symbol,
                    Order.purpose == PROTECTIVE,
                    Order.state.in_(OPEN_STATES),
                )
            )
        )
    for o in rows:
        if o.state in AT_BROKER_STATES and o.broker_order_id:
            ref = o.broker_order_id
            await with_retry(lambda ref=ref: broker.cancel_order(ref), what="cancel_stop")  # type: ignore[misc]
            await om.sync_order(o.id, broker)
        else:
            async with factory() as s, s.begin():
                row = await s.get(Order, o.id, with_for_update=True)
                if row is not None and row.state in ("proposed", "approved"):
                    orders.transition(s, row, "canceled", clock.now(), reason="exit replaces stop")
