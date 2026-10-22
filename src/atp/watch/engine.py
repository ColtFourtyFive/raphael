"""Watch engine (SPEC §7).

Per bar: (1) the paper exchange fills what the bar can fill and our books sync those
fills, (2) indicators are computed once per (symbol, timeframe, type, period), shared
by every instance, (3) each running instance's entry/exit conditions are evaluated,
(4) a wake job is published per firing instance with a dedup message ID.

Indicators are recomputed over a fixed lookback window, so a restarted engine (warmed
from the `bars` table) produces exactly the triggers an uninterrupted one would.
Only one engine is active per partition, guarded by a Postgres advisory lock.
"""

from __future__ import annotations

import asyncio
import bisect
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field

from nats.errors import TimeoutError as NatsTimeout
from nats.js import JetStreamContext
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, AsyncSession, async_sessionmaker

from atp import bus, store
from atp.brokers.factory import broker_for
from atp.brokers.paper import PaperExchange
from atp.clock import RealClock
from atp.config import get_settings
from atp.db.models import Instance, Position
from atp.indicators import compute, spec_key
from atp.marketdata.base import load_lookback, upsert_bars
from atp.orders import OrderManager
from atp.rules import evaluate_entry, evaluate_exit
from atp.schema.agent import AgentDefinition
from atp.schema.messages import Bar, PositionSnapshot, WakeJob
from atp.worker.decision import FixedClock

log = logging.getLogger(__name__)

WindowKey = tuple[uuid.UUID | None, str, str]  # (run_id, symbol, timeframe)


@dataclass
class Window:
    bars: list[Bar] = field(default_factory=list)

    def insert(self, bar: Bar, keep: int) -> None:
        keys = [b.ts for b in self.bars]
        i = bisect.bisect_left(keys, bar.ts)
        if i < len(self.bars) and self.bars[i].ts == bar.ts:
            self.bars[i] = bar
        else:
            self.bars.insert(i, bar)
        if len(self.bars) > keep * 2:
            del self.bars[: len(self.bars) - keep]

    def upto(self, bar: Bar, keep: int) -> list[Bar]:
        keys = [b.ts for b in self.bars]
        j = bisect.bisect_right(keys, bar.ts)
        return self.bars[max(0, j - keep) : j]


class WatchEngine:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        js: JetStreamContext,
        lookback: int | None = None,
    ) -> None:
        s = get_settings()
        self._factory = factory
        self._js = js
        self.lookback = lookback or s.indicator_lookback_bars
        self._windows: dict[WindowKey, Window] = {}
        self._exchange = PaperExchange(factory, s.paper_slippage_bps, s.paper_fee_per_order)
        self.published = 0

    async def _window(self, key: WindowKey, before: Bar) -> Window:
        w = self._windows.get(key)
        if w is None:
            async with self._factory() as s:
                warm = await load_lookback(s, key[1], key[2], before.ts, self.lookback)
            w = Window(warm)
            self._windows[key] = w
        return w

    async def _sync_paper_fills(self, bar: Bar, touched: Sequence[str]) -> None:
        if not touched:
            return
        async with self._factory() as s:
            insts = list(
                await s.scalars(select(Instance).where(Instance.id.in_([uuid.UUID(t) for t in set(touched)])))
            )
        for inst in insts:
            clock = FixedClock(bar.ts) if inst.run_id else RealClock()
            broker = await broker_for(inst, self._factory, clock)
            await OrderManager(self._factory, clock).sync_instance(inst.id, broker)

    async def on_bar(self, bar: Bar) -> int:
        # 1. Fills first, so exits below see positions as of this bar's open.
        touched = await self._exchange.on_bar(bar)
        await self._sync_paper_fills(bar, touched)

        if bar.run_id is None:
            async with self._factory() as s, s.begin():
                await upsert_bars(s, [bar], source="alpaca")

        key: WindowKey = (bar.run_id, bar.symbol, bar.timeframe)
        window = await self._window(key, bar)
        window.insert(bar, self.lookback)
        series = window.upto(bar, self.lookback)
        closes = [float(b.close) for b in series]

        async with self._factory() as s:
            instances = await store.running_instances(s, bar.run_id)
            candidates: list[tuple[Instance, AgentDefinition]] = []
            for inst in instances:
                defn = await store.load_definition(s, inst.agent_id, inst.version)
                if bar.symbol in defn.universe and defn.schedule.timeframe == bar.timeframe:
                    candidates.append((inst, defn))
            if not candidates:
                return 0
            pos_rows = await s.scalars(
                select(Position).where(
                    Position.symbol == bar.symbol,
                    Position.instance_id.in_([i.id for i, _ in candidates]),
                    Position.qty != 0,
                )
            )
            positions = {p.instance_id: p for p in pos_rows}

        # 2. Each indicator once per symbol/timeframe, shared across instances.
        cache: dict[tuple[str, int], float | None] = {}
        for _, defn in candidates:
            for spec in defn.indicators:
                k = spec_key(spec)
                if k not in cache:
                    cache[k] = compute(spec, closes)

        recent = [str(b.close) for b in series[-20:]]
        price = {f: float(getattr(bar, f)) for f in ("open", "high", "low", "close", "volume")}
        published = 0
        for inst, defn in candidates:
            ind = {spec.id: cache[spec_key(spec)] for spec in defn.indicators}
            values = {**ind, **price}
            pos = positions.get(inst.id)
            if pos is not None:
                fired = evaluate_exit(defn, values, pos.avg_price).fired
                trigger = "exit"
            else:
                fired = evaluate_entry(defn, values).fired
                trigger = "entry"
            if not fired:
                continue
            job = WakeJob(
                instance_id=inst.id,
                agent_id=inst.agent_id,
                version=inst.version,
                symbol=bar.symbol,
                bar=bar,
                indicators=ind,
                recent_closes=recent,
                trigger=trigger,  # type: ignore[arg-type]
                position=PositionSnapshot(qty=pos.qty, avg_price=pos.avg_price) if pos else None,
                run_id=bar.run_id,
            )
            await bus.publish_model(self._js, bus.WAKE_SUBJECT, job, msg_id=job.msg_id)
            published += 1
        self.published += published
        return published


LEADER_LOCK_KEY = 0x41545057  # "ATPW": watch engine partition 0


async def acquire_leadership(engine: AsyncEngine, stop: asyncio.Event) -> AsyncConnection | None:
    """Hold a session-level advisory lock on a dedicated connection while leader."""
    conn = await engine.connect()
    while not stop.is_set():
        got = await conn.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": LEADER_LOCK_KEY})
        await conn.commit()
        if got:
            log.info("watch engine is leader")
            return conn
        log.info("another watch engine holds the lock; standing by")
        try:
            await asyncio.wait_for(stop.wait(), timeout=5)
        except TimeoutError:
            pass
    await conn.close()
    return None


async def run_watch(
    js: JetStreamContext,
    factory: async_sessionmaker[AsyncSession],
    engine: AsyncEngine,
    stop: asyncio.Event | None = None,
) -> None:
    stop = stop or asyncio.Event()
    lock_conn = await acquire_leadership(engine, stop)
    if lock_conn is None:
        return
    watch = WatchEngine(factory, js)
    sub = await js.pull_subscribe("md.bars.>", durable=bus.WATCH_CONSUMER, stream="MD")
    try:
        while not stop.is_set():
            try:
                msgs = await sub.fetch(batch=200, timeout=1)
            except NatsTimeout:
                continue
            for m in msgs:
                bar = Bar.model_validate_json(m.data)
                try:
                    await watch.on_bar(bar)
                except Exception:
                    log.exception(
                        "watch engine failed on bar; will be redelivered", extra={"symbol": bar.symbol}
                    )
                    await m.nak(delay=2)
                    continue
                await m.ack()  # after jobs are published; a crash before this replays the bar
    finally:
        await sub.unsubscribe()
        # Invalidate (not close): a closed connection goes back to the pool with its
        # Postgres session, and the advisory lock, still alive.
        await lock_conn.invalidate()
        await lock_conn.close()
