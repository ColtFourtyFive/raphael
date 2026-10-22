"""SPEC §9 acceptance tests that run through the full replay pipeline:
#1 replay parity, #3 worker crash, #4 watch engine restart, #7 market-open burst, #9 AI cost."""

from __future__ import annotations

import asyncio
import os
import uuid
from collections import Counter
from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select

from atp import store
from atp.backtest.reference import run_reference
from atp.db.models import Decision, Order, PaperOrder, Position
from atp.marketdata.base import load_bars, load_lookback, session_bounds
from atp.replay import run_replay, trade_tape
from atp.watch.engine import WatchEngine
from atp.worker.ai import AIFilterRunner
from atp.worker.decision import DecisionWorker

from .conftest import DAY, FakeChat, Services

AGENT = "test-rsi-fast"


async def replay(svc: Services, agent: str = AGENT, **kw: Any) -> Any:
    if svc.watch_task is None:
        svc.start_watch()
    if not svc.worker_tasks:
        svc.start_workers()
    return await run_replay(svc.factory, svc.js, agent, 1, DAY, speed=None, **kw)


def fills_only(tape: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [t for t in tape if t["qty"] is not None]


async def assert_no_duplicate_orders(svc: Services, instance_id: uuid.UUID) -> None:
    async with svc.factory() as s:
        per_decision = await s.execute(
            select(Order.decision_id, func.count()).where(Order.instance_id == instance_id).group_by(Order.decision_id)
        )
        assert all(n == 1 for _, n in per_decision)
        ours = await s.scalar(select(func.count()).select_from(Order).where(Order.instance_id == instance_id))
        theirs = await s.scalar(
            select(func.count()).select_from(PaperOrder).where(PaperOrder.account_ref == str(instance_id))
        )
        assert ours == theirs  # nothing reached the broker twice


# --- #1 replay parity -------------------------------------------------------------


async def test_replay_parity_with_reference_and_reruns(services: Services) -> None:
    a = await replay(services)
    b = await replay(services)
    assert a.orders > 0 and a.fills > 0, "fixture day must trade for parity to mean anything"
    assert a.reconcile == {"clean": 1} and b.reconcile == {"clean": 1}

    tape_a = await trade_tape(services.factory, a.instance_ids[0])
    tape_b = await trade_tape(services.factory, b.instance_ids[0])
    assert tape_a == tape_b, "two replays of the same day must give identical decisions and orders"

    async with services.factory() as s:
        defn = await store.load_definition(s, AGENT, 1)
        start, end = session_bounds(DAY)
        day_bars = await load_bars(s, defn.universe, "5Min", start, end)
        warmup = [b for sym in defn.universe for b in await load_lookback(s, sym, "5Min", start, 250)]
    ref = run_reference(defn, warmup, day_bars)
    ours = [(t["symbol"], t["side"], t["bar_ts"], Decimal(t["qty"]), Decimal(t["price"])) for t in fills_only(tape_a)]
    theirs = [(t.symbol, t.side, t.decided_at.isoformat(), t.qty, t.price) for t in ref]
    assert sorted(ours) == sorted(theirs)


# --- #3 worker crash ---------------------------------------------------------------


async def test_worker_crash_after_commit_and_after_submit(services: Services, fake_chat: FakeChat) -> None:
    baseline = await replay(services)
    expected = await trade_tape(services.factory, baseline.instance_ids[0])
    await services.stop_workers()

    crashed: Counter[str] = Counter()

    async def hook(point: str) -> None:
        # crash on the first decision after commit, and on the first one after broker submit
        if crashed[point] == 0:
            crashed[point] += 1
            raise RuntimeError(f"injected crash at {point}")

    flaky = DecisionWorker(services.factory, ai=AIFilterRunner(services.factory, client=fake_chat), hook=hook)
    services.start_workers(flaky)
    run = await replay(services)
    assert crashed == {"after_commit": 1, "after_submit": 1}
    assert await trade_tape(services.factory, run.instance_ids[0]) == expected
    await assert_no_duplicate_orders(services, run.instance_ids[0])


async def test_worker_killed_mid_job_is_redelivered(services: Services, fake_chat: FakeChat) -> None:
    """Hard-kill a worker task while it holds an un-acked job: the job is redelivered after
    ack_wait, a fresh worker resumes it, and the order is not duplicated."""
    in_flight = asyncio.Event()
    hung = {"done": False}

    async def hang(point: str) -> None:
        if point == "after_submit" and not hung["done"]:
            hung["done"] = True
            in_flight.set()
            await asyncio.sleep(3600)  # stuck until the task is killed

    stuck = DecisionWorker(services.factory, ai=AIFilterRunner(services.factory, client=fake_chat), hook=hang)
    services.start_watch()
    services.start_workers(stuck, n=1)

    async def killer() -> None:
        await in_flight.wait()
        await services.stop_workers(hard=True)
        services.start_workers(n=1)  # a healthy replacement

    k = asyncio.create_task(killer())
    run = await replay(services)
    await k
    assert hung["done"]
    await assert_no_duplicate_orders(services, run.instance_ids[0])
    async with services.factory() as s:
        clean = await s.scalar(select(func.count()).select_from(Order).where(Order.instance_id == run.instance_ids[0]))
    assert clean == run.orders and run.reconcile == {"clean": 1}


# --- #4 watch engine restart ---------------------------------------------------------


async def test_watch_engine_restart_misses_nothing(services: Services, monkeypatch: Any) -> None:
    baseline = await replay(services)
    expected = await trade_tape(services.factory, baseline.instance_ids[0])

    original = WatchEngine.on_bar
    calls = {"n": 0}

    async def crash_once_after_publish(self: WatchEngine, bar: Any) -> int:
        n = await original(self, bar)
        calls["n"] += 1
        if calls["n"] == 40:  # jobs published, bar not yet acked: NAK + redelivery
            raise RuntimeError("injected watch crash before ack")
        return n

    monkeypatch.setattr(WatchEngine, "on_bar", crash_once_after_publish)

    async def restart_at(step: int) -> None:
        if step in (15, 50):
            await services.stop_watch(hard=True)

            async def later() -> None:
                await asyncio.sleep(1.5)  # bars pile up in the MD stream meanwhile
                services.start_watch()

            asyncio.create_task(later())

    run = await replay(services, on_step=restart_at)
    assert calls["n"] > 40
    assert await trade_tape(services.factory, run.instance_ids[0]) == expected


# --- #7 market-open burst --------------------------------------------------------------


async def test_market_open_burst(services: Services) -> None:
    copies = int(os.environ.get("BURST_COPIES", "200"))
    services.start_watch()
    services.start_workers(n=4)
    run = await replay(services, copies=copies)
    assert len(run.instance_ids) == copies
    assert run.max_lag_s < timedelta(minutes=5).total_seconds(), "queue lag must stay within ~1 bar"
    per_copy = run.orders / copies
    assert per_copy == int(per_copy), "every copy should trade identically"
    async with services.factory() as s:
        worst = await s.scalar(
            select(func.max(func.coalesce(Order.notional, Decimal(0)))).where(Order.instance_id.in_(run.instance_ids))
        )
        assert worst is None or worst <= Decimal(500)
        held = await s.execute(
            select(Position.instance_id, func.count())
            .where(Position.instance_id.in_(run.instance_ids))
            .group_by(Position.instance_id)
        )
        assert all(n <= 3 for _, n in held)
    assert run.reconcile == {"clean": copies}


# --- #9 AI cost -------------------------------------------------------------------------


async def test_ai_filter_cost_and_deterministic_cache(services: Services, fake_chat: FakeChat) -> None:
    first = await replay(services, agent="test-rsi-fast-ai")
    calls_first = fake_chat.calls
    second = await replay(services, agent="test-rsi-fast-ai")
    assert calls_first > 0 and fake_chat.calls == calls_first, "re-run must be served from llm_cache"
    assert first.cost_usd == Decimal("0.00021") * calls_first and second.cost_usd == 0
    assert await trade_tape(services.factory, first.instance_ids[0]) == await trade_tape(
        services.factory, second.instance_ids[0]
    )
    async with services.factory() as s:
        ai_rows = list(
            await s.scalars(
                select(Decision).where(
                    Decision.instance_id == first.instance_ids[0], Decision.model_request_hash.is_not(None)
                )
            )
        )
    assert ai_rows and all(d.model_output and d.reasoning for d in ai_rows)
    assert {d.action for d in ai_rows} <= {"buy", "skip", "blocked"}
