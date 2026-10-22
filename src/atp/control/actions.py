"""Operator actions shared by the CLI and the control panel."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from nats.js import JetStreamContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atp import bus, ledger, store
from atp.brokers.factory import PAPER_MODES, broker_for, paper_account_ref
from atp.brokers.paper import open_paper_account
from atp.clock import RealClock
from atp.config import get_settings
from atp.crypto import encrypt_credentials
from atp.db.models import BrokerAccount, Instance, Order
from atp.orders import OPEN_STATES, OrderManager
from atp.schema.agent import AgentDefinition
from atp.schema.messages import Event

log = logging.getLogger(__name__)

MODES = ("replay", "paper", "alpaca_paper", "alpaca_live")


def read_definition(path: Path) -> AgentDefinition:
    return AgentDefinition.model_validate(json.loads(path.read_text()))


async def load_agent(factory: async_sessionmaker[AsyncSession], defn: AgentDefinition) -> bool:
    async with factory() as s, s.begin():
        return await store.save_definition(s, defn)


async def ensure_paper_account_row(s: AsyncSession) -> BrokerAccount:
    row = await s.scalar(select(BrokerAccount).where(BrokerAccount.name == "paper"))
    if row is None:
        row = BrokerAccount(id=uuid.uuid4(), name="paper", broker="paper", is_live=False)
        s.add(row)
        await s.flush()
    return row


async def add_alpaca_account(
    factory: async_sessionmaker[AsyncSession], name: str, api_key: str, secret: str, is_live: bool
) -> uuid.UUID:
    blob = encrypt_credentials({"api_key_id": api_key, "api_secret_key": secret})
    async with factory() as s, s.begin():
        row = BrokerAccount(
            id=uuid.uuid4(), name=name, broker="alpaca", encrypted_credentials=blob, is_live=is_live
        )
        s.add(row)
    return row.id


async def create_instance(
    factory: async_sessionmaker[AsyncSession],
    agent_id: str,
    version: int,
    mode: str,
    *,
    account_name: str | None = None,
    run_id: uuid.UUID | None = None,
    status: str = "paused",
    starting_cash: Decimal | None = None,
    at: datetime | None = None,
) -> Instance:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if mode == "alpaca_live" and not get_settings().allow_live_trading:
        raise PermissionError("alpaca_live instances need ALLOW_LIVE_TRADING=true")
    if (mode == "replay") != (run_id is not None):
        raise ValueError("replay instances (and only they) carry a run_id")
    at = at or datetime.now(UTC)
    async with factory() as s, s.begin():
        await store.load_definition(s, agent_id, version)
        if mode in PAPER_MODES:
            account = await ensure_paper_account_row(s)
        else:
            found = await s.scalar(
                select(BrokerAccount).where(BrokerAccount.name == (account_name or "alpaca"))
            )
            if found is None:
                raise LookupError("no Alpaca account row; add one with `atp account add-alpaca`")
            account = found
            if (mode == "alpaca_live") != account.is_live:
                raise PermissionError(f"mode {mode} does not match account is_live={account.is_live}")
        inst = Instance(
            id=uuid.uuid4(),
            agent_id=agent_id,
            version=version,
            mode=mode,
            status=status,
            account_ref=account.id,
            run_id=run_id,
        )
        s.add(inst)
        await s.flush()
        if mode in PAPER_MODES:
            cash = starting_cash or get_settings().paper_starting_cash
            await open_paper_account(s, paper_account_ref(inst), cash, run_id)
            await ledger.deposit(s, inst.id, cash, at)
    return inst


async def publish_event(js: JetStreamContext | None, event: Event) -> None:
    if js is None:
        return
    await js.publish(f"events.{event.kind}", event.model_dump_json().encode())


async def set_status(
    factory: async_sessionmaker[AsyncSession],
    instance_id: uuid.UUID,
    status: str,
    reason: str,
    js: JetStreamContext | None = None,
) -> int:
    """start (running) / pause / kill. Kill also cancels open orders. Returns orders canceled."""
    async with factory() as s, s.begin():
        inst = await store.set_instance_status(s, instance_id, status, reason)
    canceled = 0
    if status == "killed":
        broker = await broker_for(inst, factory, RealClock())
        canceled = await OrderManager(factory, RealClock()).cancel_open(inst.id, broker, reason)
    await publish_event(
        js, Event(kind=f"instance.{status}", instance_id=instance_id, detail={"reason": reason})
    )
    return canceled


async def kill_all(
    factory: async_sessionmaker[AsyncSession],
    js: JetStreamContext | None = None,
    reason: str = "global kill switch",
) -> int:
    """Flip the global switch first (blocks new orders), then cancel everything open."""
    async with factory() as s, s.begin():
        await store.set_kill_switch(s, True)
    await publish_event(js, Event(kind="kill.on", detail={"reason": reason}))
    async with factory() as s:
        ids = set(await s.scalars(select(Order.instance_id).where(Order.state.in_(OPEN_STATES)).distinct()))
        insts = list(await s.scalars(select(Instance).where(Instance.id.in_(ids)))) if ids else []

    async def cancel(inst: Instance) -> int:
        try:
            broker = await broker_for(inst, factory, RealClock())
            return await OrderManager(factory, RealClock()).cancel_open(inst.id, broker, reason)
        except Exception:
            log.exception("kill: cancel failed", extra={"instance_id": str(inst.id)})
            return 0

    return sum(await asyncio.gather(*(cancel(i) for i in insts)))


async def release_kill_switch(
    factory: async_sessionmaker[AsyncSession], js: JetStreamContext | None = None
) -> None:
    async with factory() as s, s.begin():
        await store.set_kill_switch(s, False)
    await publish_event(js, Event(kind="kill.off"))


async def decide_pending(
    factory: async_sessionmaker[AsyncSession], order_id: uuid.UUID, approve: bool
) -> Order:
    async with factory() as s:
        order = await s.get(Order, order_id)
        if order is None:
            raise LookupError(order_id)
        inst = await s.get(Instance, order.instance_id)
    assert inst is not None
    om = OrderManager(factory, RealClock())
    if approve:
        broker = await broker_for(inst, factory, RealClock())
        return await om.approve(order_id, broker)
    await om.reject(order_id)
    async with factory() as s:
        result = await s.get(Order, order_id)
        assert result is not None
        return result


async def ensure_bus(js: JetStreamContext) -> None:
    await bus.ensure_streams(js)
