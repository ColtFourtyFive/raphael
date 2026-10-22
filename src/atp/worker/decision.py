"""Decision worker core (SPEC §7): one wake job in, one decision (and maybe one order) out.

Idempotency: a decision is unique per (instance, symbol, bar_ts). A redelivered job finds
the existing decision and only finishes what's left (submitting an approved order), so a
crash at any point never produces a second order.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atp import ledger, orders, risk, store
from atp.brokers.base import Broker, BrokerAuthError, with_retry
from atp.brokers.factory import broker_for
from atp.clock import Clock, RealClock
from atp.db.models import Decision, Instance, Order, RiskEvent
from atp.marketdata.base import NY
from atp.orders import OPEN_STATES, OrderManager
from atp.rules import evaluate_entry, evaluate_exit
from atp.schema.messages import WakeJob
from atp.worker.ai import AIFilterRunner, AIVerdict

log = logging.getLogger(__name__)


class TerminalJobError(Exception):
    """The job can never succeed (bad payload, missing instance): dead-letter it."""


class FixedClock:
    """A clock pinned to one instant: the decision time of a replay job."""

    def __init__(self, at: datetime) -> None:
        self._at = at

    def now(self) -> datetime:
        return self._at

    async def sleep_until(self, when: datetime) -> None:
        return None


@dataclass(frozen=True)
class Outcome:
    decision_id: uuid.UUID
    action: str
    order_id: uuid.UUID | None
    resumed: bool = False


Hook = Callable[[str], Awaitable[None]]


async def _noop(_: str) -> None:
    return None


class DecisionWorker:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        ai: AIFilterRunner | None = None,
        live_clock: Clock | None = None,
        hook: Hook = _noop,
    ) -> None:
        self._factory = factory
        self._ai = ai or AIFilterRunner(factory)
        self._live_clock = live_clock or RealClock()
        # Test seam: called at named points ("after_commit", "after_submit") to inject crashes.
        self._hook = hook

    def clock_for(self, job: WakeJob, timeframe_s: int) -> Clock:
        """Replay decides at the bar's close on simulated time; paper/live on real time."""
        if job.run_id is not None:
            return FixedClock(job.bar.ts + timedelta(seconds=timeframe_s))
        return self._live_clock

    async def handle(self, job: WakeJob) -> Outcome:
        async with self._factory() as s:
            inst = await s.get(Instance, job.instance_id)
            if inst is None:
                raise TerminalJobError(f"instance {job.instance_id} not found")
            try:
                defn = await store.load_definition(s, inst.agent_id, inst.version)
            except LookupError as e:
                raise TerminalJobError(str(e)) from e
            existing = await s.scalar(
                select(Decision).where(
                    Decision.instance_id == job.instance_id,
                    Decision.symbol == job.symbol,
                    Decision.bar_ts == job.bar.ts,
                )
            )
        clock = self.clock_for(job, defn.timeframe_seconds)
        broker = await broker_for(inst, self._factory, clock)
        om = OrderManager(self._factory, clock)
        if existing is not None:
            return await self._resume(existing, om, broker)

        started = time.monotonic()
        now = clock.now()
        if job.run_id is None and now - (job.bar.ts + timedelta(seconds=defn.timeframe_seconds)) > timedelta(
            seconds=2 * defn.timeframe_seconds
        ):
            return await self._record(
                job, inst, now, {"stale": True}, "hold", "stale wake job; market moved on", None, started
            )

        async with self._factory() as s:
            positions = await ledger.positions_for(s, inst.id)
        pos = positions.get(job.symbol)
        values: dict[str, float | None] = {**job.indicators}
        for f in ("open", "high", "low", "close", "volume"):
            values[f] = float(getattr(job.bar, f))

        if pos is None:
            rr = evaluate_entry(defn, values)
            side = "buy" if rr.fired else None
        else:
            rr = evaluate_exit(defn, values, pos.avg_price)
            side = "sell" if rr.fired else None
        rule = {"fired": rr.fired, "detail": rr.detail, "evaluated": "exit" if pos else "entry"}

        if side is None:
            return await self._record(job, inst, now, rule, "hold", "conditions no longer met", None, started)

        verdict: AIVerdict | None = None
        if side == "buy" and defn.ai_filter is not None:
            if inst.status != "running":
                reasoning = f"instance {inst.status}; AI not called"
                return await self._record(job, inst, now, rule, "skip", reasoning, None, started)
            verdict = await self._ai.run(defn.ai_filter, job)
            if verdict.verdict == "SKIP":
                return await self._record(job, inst, now, rule, "skip", verdict.reasoning, verdict, started)

        reasoning = verdict.reasoning if verdict else "; ".join(d for d in rr.detail if d.endswith("True"))
        return await self._decide_and_order(
            job, inst, defn, broker, om, clock, rule, side, pos, positions, verdict, reasoning, started
        )

    async def _decide_and_order(
        self,
        job: WakeJob,
        inst: Instance,
        defn: Any,
        broker: Broker,
        om: OrderManager,
        clock: Clock,
        rule: dict[str, Any],
        side: str,
        pos: Any,
        positions: dict[str, Any],
        verdict: AIVerdict | None,
        reasoning: str,
        started: float,
    ) -> Outcome:
        now = clock.now()
        try:
            account = await with_retry(broker.get_account, what="get_account")
        except BrokerAuthError:
            async with self._factory() as s, s.begin():
                await store.set_instance_status(s, inst.id, "paused", "broker auth failed")
            raise
        close = job.bar.close
        notional = defn.sizing.usd if side == "buy" else (pos.qty * close)
        day_start = now.astimezone(NY).replace(hour=0, minute=0, second=0, microsecond=0)

        decision_id = uuid.uuid4()
        try:
            async with self._factory() as s, s.begin():
                # Row lock: one decision per instance at a time, so concurrent symbols
                # can't both slip under max_open_positions.
                inst_now = await s.get(Instance, inst.id, with_for_update=True)
                assert inst_now is not None
                open_orders = await s.scalar(
                    select(func.count())
                    .select_from(Order)
                    .where(
                        Order.instance_id == inst.id, Order.symbol == job.symbol, Order.state.in_(OPEN_STATES)
                    )
                )
                pending_buys = set(
                    await s.scalars(
                        select(Order.symbol).where(
                            Order.instance_id == inst.id, Order.side == "buy", Order.state.in_(OPEN_STATES)
                        )
                    )
                )
                held = set((await ledger.positions_for(s, inst.id)).keys())
                ctx = risk.RiskContext(
                    instance_status=inst_now.status,
                    kill_switch=await store.kill_switch_on(s),
                    now=now,
                    side=side,  # type: ignore[arg-type]
                    symbol=job.symbol,
                    order_notional=notional,
                    position_value=(pos.qty * close) if pos else Decimal(0),
                    open_positions=len(held | pending_buys),
                    holds_symbol=pos is not None,
                    daily_pnl=await ledger.realized_pnl_since(s, inst.id, day_start),
                    buying_power=account.buying_power,
                    open_orders_for_symbol=int(open_orders or 0),
                    guardrails=defn.guardrails,
                )
                rd = risk.evaluate(ctx)
                action = {"approve": side, "block": "blocked", "hold": "pending"}[rd.outcome]
                if rd.outcome != "approve":
                    reasoning = f"{reasoning} | risk: {'; '.join(rd.reasons)}"
                s.add(
                    self._decision_row(decision_id, job, inst.id, rule, action, reasoning, verdict, started)
                )
                await s.flush()
                for c in rd.checks:
                    s.add(
                        RiskEvent(
                            instance_id=inst.id,
                            decision_id=decision_id,
                            rule=c.rule,
                            outcome=c.outcome,
                            detail=c.detail,
                            ts=now,
                        )
                    )
                order_id: uuid.UUID | None = None
                if rd.outcome != "block":
                    order = orders.new_order(
                        s,
                        instance_id=inst.id,
                        decision_id=decision_id,
                        symbol=job.symbol,
                        side=side,
                        ts=now,
                        notional=defn.sizing.usd if side == "buy" else None,
                        qty=pos.qty if side == "sell" else None,
                    )
                    order_id = order.id
                    if rd.outcome == "approve":
                        orders.transition(s, order, "approved", now, by="risk_engine")
        except IntegrityError:
            # Another delivery of this job committed first; finish its work instead.
            async with self._factory() as s:
                existing = await s.scalar(
                    select(Decision).where(
                        Decision.instance_id == job.instance_id,
                        Decision.symbol == job.symbol,
                        Decision.bar_ts == job.bar.ts,
                    )
                )
            if existing is None:
                raise
            return await self._resume(existing, om, broker)

        await self._hook("after_commit")
        if order_id is not None and rd.outcome == "approve":
            await om.submit(order_id, broker)
            await self._hook("after_submit")
        return Outcome(decision_id, action, order_id)

    async def _resume(self, decision: Decision, om: OrderManager, broker: Broker) -> Outcome:
        async with self._factory() as s:
            order = await s.scalar(select(Order).where(Order.decision_id == decision.id))
        if order is not None and order.state == "approved":
            log.info(
                "resuming approved order after redelivery", extra={"client_order_id": order.client_order_id}
            )
            await om.submit(order.id, broker)
        return Outcome(decision.id, decision.action, order.id if order else None, resumed=True)

    def _decision_row(
        self,
        decision_id: uuid.UUID,
        job: WakeJob,
        instance_id: uuid.UUID,
        rule: dict[str, Any],
        action: str,
        reasoning: str,
        verdict: AIVerdict | None,
        started: float,
    ) -> Decision:
        return Decision(
            id=decision_id,
            instance_id=instance_id,
            symbol=job.symbol,
            bar_ts=job.bar.ts,
            inputs_json=job.model_dump(mode="json"),
            rule_result=rule,
            model_request_hash=verdict.request_hash if verdict else None,
            model_output=verdict.raw_output if verdict else None,
            reasoning=reasoning,
            action=action,
            latency_ms=int((time.monotonic() - started) * 1000),
            cost_usd=verdict.cost_usd if verdict else Decimal(0),
        )

    async def _record(
        self,
        job: WakeJob,
        inst: Instance,
        now: datetime,
        rule: dict[str, Any],
        action: str,
        reasoning: str,
        verdict: AIVerdict | None,
        started: float,
    ) -> Outcome:
        decision_id = uuid.uuid4()
        try:
            async with self._factory() as s, s.begin():
                s.add(
                    self._decision_row(decision_id, job, inst.id, rule, action, reasoning, verdict, started)
                )
        except IntegrityError:
            async with self._factory() as s:
                existing = await s.scalar(
                    select(Decision.id).where(
                        Decision.instance_id == job.instance_id,
                        Decision.symbol == job.symbol,
                        Decision.bar_ts == job.bar.ts,
                    )
                )
            assert existing is not None
            return Outcome(existing, action, None, resumed=True)
        return Outcome(decision_id, action, None)
