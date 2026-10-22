"""Reconciliation (SPEC §7): compare the broker's books with ours; any diff pauses.

Every run first pulls order updates (fills) from the broker, then diffs positions and
open orders. For Alpaca, an instance is assumed to own its whole account in v0.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from decimal import Decimal
from typing import Any

from nats.js import JetStreamContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atp import ledger, store
from atp.brokers.base import BrokerAuthError, BrokerError
from atp.brokers.factory import broker_for
from atp.clock import Clock, RealClock
from atp.control.actions import publish_event
from atp.db.models import Instance, Order, ReconciliationRun
from atp.obs import alert
from atp.orders import AT_BROKER_STATES, OrderManager
from atp.schema.messages import Event

log = logging.getLogger(__name__)
TOLERANCE = Decimal("0.000001")


async def reconcile_instance(
    factory: async_sessionmaker[AsyncSession],
    instance_id: uuid.UUID,
    js: JetStreamContext | None = None,
    clock: Clock | None = None,
    pause_on_mismatch: bool = True,
) -> ReconciliationRun:
    clock = clock or RealClock()
    async with factory() as s:
        inst = await s.get(Instance, instance_id)
    if inst is None:
        raise LookupError(instance_id)
    diffs: dict[str, Any] = {}
    status = "clean"
    try:
        broker = await broker_for(inst, factory, clock)
        await OrderManager(factory, clock).sync_instance(inst.id, broker)
        theirs = {p.symbol: p.qty for p in await broker.get_positions()}
        their_open = {o.client_order_id for o in await broker.list_open_orders()}
        async with factory() as s:
            ours = {sym: p.qty for sym, p in (await ledger.positions_for(s, inst.id)).items()}
            our_open = set(
                await s.scalars(
                    select(Order.client_order_id).where(
                        Order.instance_id == inst.id, Order.state.in_(AT_BROKER_STATES)
                    )
                )
            )
        pos_diff = {
            sym: {"ours": str(ours.get(sym, 0)), "broker": str(theirs.get(sym, 0))}
            for sym in set(ours) | set(theirs)
            if abs(ours.get(sym, Decimal(0)) - theirs.get(sym, Decimal(0))) > TOLERANCE
        }
        if pos_diff:
            diffs["positions"] = pos_diff
        if their_open - our_open:
            diffs["unknown_broker_orders"] = sorted(their_open - our_open)
        if our_open - their_open:
            diffs["orders_missing_at_broker"] = sorted(our_open - their_open)
        status = "mismatch" if diffs else "clean"
    except BrokerAuthError as e:
        status, diffs = "error", {"error": f"auth: {e}"}
    except BrokerError as e:
        status, diffs = "error", {"error": str(e)}

    async with factory() as s, s.begin():
        run = ReconciliationRun(instance_id=inst.id, ts=clock.now(), status=status, diffs_json=diffs)
        s.add(run)
        if status != "clean" and pause_on_mismatch and inst.status == "running":
            await store.set_instance_status(s, inst.id, "paused", f"reconciliation {status}")
    if status != "clean":
        await publish_event(js, Event(kind=f"reconcile.{status}", instance_id=inst.id, detail=diffs))
        await alert(
            f"reconcile_{status}",
            "reconciliation failed; instance paused",
            instance_id=str(inst.id),
            diffs=diffs,
        )
    return run


async def run_reconciler(
    factory: async_sessionmaker[AsyncSession],
    js: JetStreamContext | None,
    interval_s: float,
    stop: asyncio.Event | None = None,
) -> None:
    stop = stop or asyncio.Event()
    while not stop.is_set():
        async with factory() as s:
            ids = list(
                await s.scalars(
                    select(Instance.id).where(
                        Instance.run_id.is_(None), Instance.status.in_(["running", "paused"])
                    )
                )
            )
        for iid in ids:
            try:
                await reconcile_instance(factory, iid, js)
            except Exception:
                log.exception("reconcile failed", extra={"instance_id": str(iid)})
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_s)
        except TimeoutError:
            pass
