"""Replay (SPEC §7): a historical day through the exact live pipeline, on a SimClock.

Bars go to NATS like live bars (tagged with the run's `run_id`); the same watch engine,
workers, risk engine, and order manager handle them. After each bar timestamp the
replayer waits for the watch and worker consumers to drain, so every run of the same
day produces the same decisions and orders regardless of speed.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from nats.js import JetStreamContext
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atp import bus, store
from atp.clock import SimClock
from atp.control.actions import create_instance
from atp.db.models import Decision, Fill, Instance, Order
from atp.marketdata.base import load_bars, session_bounds
from atp.reconcile import reconcile_instance
from atp.schema.messages import Bar

log = logging.getLogger(__name__)


class MissingBars(RuntimeError):
    pass


@dataclass
class ReplaySummary:
    run_id: uuid.UUID
    instance_ids: list[uuid.UUID]
    bars: int
    decisions: int
    orders: int
    fills: int
    actions: dict[str, int] = field(default_factory=dict)
    reconcile: dict[str, int] = field(default_factory=dict)
    max_lag_s: float = 0.0
    wall_s: float = 0.0
    cost_usd: Decimal = Decimal(0)


class ReplayDataSource:
    """Historical bars from the `bars` cache, grouped by timestamp, on a SimClock."""

    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory

    async def day(self, symbols: list[str], timeframe: str, day: date) -> list[Bar]:
        start, end = session_bounds(day)
        async with self._factory() as s:
            return await load_bars(s, symbols, timeframe, start, end)


async def wait_drained(js: JetStreamContext, timeout_s: float = 300) -> float:
    """Wait until the watch engine and workers have nothing pending. Returns seconds waited."""
    started = time.monotonic()
    while True:
        md = await bus.consumer_backlog(js, "MD", bus.WATCH_CONSUMER)
        jobs = await bus.consumer_backlog(js, "JOBS", bus.WORKER_CONSUMER)
        if md == 0 and jobs == 0:
            return time.monotonic() - started
        if time.monotonic() - started > timeout_s:
            raise TimeoutError(f"pipeline did not drain (md={md}, jobs={jobs})")
        await asyncio.sleep(0.01)


async def run_replay(
    factory: async_sessionmaker[AsyncSession],
    js: JetStreamContext,
    agent_id: str,
    version: int,
    day: date,
    speed: float | None = 20.0,
    copies: int = 1,
    on_step: Callable[[int], Awaitable[None]] | None = None,
) -> ReplaySummary:
    async with factory() as s:
        defn = await store.load_definition(s, agent_id, version)
    bars = await ReplayDataSource(factory).day(defn.universe, defn.schedule.timeframe, day)
    if not bars:
        raise MissingBars(
            f"no {defn.schedule.timeframe} bars cached for {day}; run `atp bars fetch` "
            f"(Alpaca) or `atp bars synth` (synthetic) first"
        )
    run_id = uuid.uuid4()
    open_, _ = session_bounds(day)
    instances = []
    for _ in range(copies):
        instances.append(
            await create_instance(
                factory, agent_id, version, "replay", run_id=run_id, status="running", at=open_
            )
        )
    ids = [i.id for i in instances]
    log.info(
        "replay started",
        extra={"run_id": str(run_id), "day": day.isoformat(), "bars": len(bars), "copies": copies},
    )

    clock = SimClock(open_, speed)
    step = timedelta(seconds=defn.timeframe_seconds)
    wall_start = time.monotonic()
    max_lag = 0.0
    for step_no, (ts, group) in enumerate(itertools.groupby(bars, key=lambda b: b.ts)):
        if on_step is not None:
            await on_step(step_no)  # test seam for fault injection between bars
        await clock.sleep_until(ts + step)  # a bar is published when it closes
        # One symbol at a time, draining in between: decisions within a timestamp then
        # happen in symbol order, so shared limits (open positions, daily loss) resolve
        # the same way on every run.
        for bar in sorted(group, key=lambda b: b.symbol):
            tagged = bar.model_copy(update={"run_id": run_id})
            await bus.publish_model(
                js,
                bus.MD_SUBJECT.format(symbol=bar.symbol),
                tagged,
                msg_id=f"{run_id}:{bar.symbol}:{bar.timeframe}:{bar.ts.isoformat()}",
            )
            max_lag = max(max_lag, await wait_drained(js))

    async with factory() as s, s.begin():
        for iid in ids:
            await store.set_instance_status(s, iid, "completed", "replay finished")
    recon: dict[str, int] = {}
    for iid in ids:
        run = await reconcile_instance(factory, iid, js, clock=clock, pause_on_mismatch=False)
        recon[run.status] = recon.get(run.status, 0) + 1
    return await summarize(factory, run_id, len(bars), recon, max_lag, time.monotonic() - wall_start)


async def summarize(
    factory: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    n_bars: int,
    recon: dict[str, int],
    max_lag: float,
    wall: float,
) -> ReplaySummary:
    async with factory() as s:
        ids = list(await s.scalars(select(Instance.id).where(Instance.run_id == run_id)))
        actions = dict(
            (a, int(n))
            for a, n in await s.execute(
                select(Decision.action, func.count())
                .where(Decision.instance_id.in_(ids))
                .group_by(Decision.action)
            )
        )
        n_orders = await s.scalar(select(func.count()).select_from(Order).where(Order.instance_id.in_(ids)))
        n_fills = await s.scalar(
            select(func.count())
            .select_from(Fill)
            .join(Order, Fill.order_id == Order.id)
            .where(Order.instance_id.in_(ids))
        )
        cost = await s.scalar(
            select(func.coalesce(func.sum(Decision.cost_usd), 0)).where(Decision.instance_id.in_(ids))
        )
    return ReplaySummary(
        run_id=run_id,
        instance_ids=ids,
        bars=n_bars,
        decisions=sum(actions.values()),
        orders=int(n_orders or 0),
        fills=int(n_fills or 0),
        actions=actions,
        reconcile=recon,
        max_lag_s=round(max_lag, 3),
        wall_s=round(wall, 2),
        cost_usd=Decimal(cost or 0),
    )


async def trade_tape(
    factory: async_sessionmaker[AsyncSession], instance_id: uuid.UUID
) -> list[dict[str, Any]]:
    """Comparable record of a run's orders and fills (ids stripped) for parity checks."""
    async with factory() as s:
        rows = await s.execute(
            select(
                Decision.symbol,
                Decision.bar_ts,
                Decision.action,
                Order.side,
                Order.state,
                Fill.qty,
                Fill.price,
            )
            .join(Order, Order.decision_id == Decision.id, isouter=True)
            .join(Fill, Fill.order_id == Order.id, isouter=True)
            .where(Decision.instance_id == instance_id)
            .order_by(Decision.bar_ts, Decision.symbol)
        )
        return [
            {
                "symbol": r[0],
                "bar_ts": r[1].isoformat(),
                "action": r[2],
                "side": r[3],
                "state": r[4],
                "qty": str(r[5]) if r[5] is not None else None,
                "price": str(r[6]) if r[6] is not None else None,
            }
            for r in rows
        ]
