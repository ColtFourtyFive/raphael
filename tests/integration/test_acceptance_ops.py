"""SPEC §9 acceptance tests for operations on the paper (non-replay) path:
#5 broker failures, #6 kill switch, plus manual approval, reconciliation, and the panel."""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atp import store
from atp.brokers.base import BrokerAuthError, BrokerTransientError, OrderRequest
from atp.brokers.paper import PaperBroker
from atp.control import actions
from atp.db.models import Decision, Instance, Order, PaperOrder, PaperPosition, ReconciliationRun
from atp.reconcile import reconcile_instance
from atp.schema.messages import Bar, WakeJob
from atp.worker import decision as decision_mod
from atp.worker.decision import DecisionWorker, FixedClock

from .conftest import FakeChat

MARKET_OPEN = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)  # 11:00 New York, a Wednesday


def entry_job(instance_id: uuid.UUID, ts: datetime, symbol: str = "SPY") -> WakeJob:
    bar = Bar(
        symbol=symbol,
        timeframe="5Min",
        ts=ts,
        open=Decimal(100),
        high=Decimal(101),
        low=Decimal(99),
        close=Decimal(100),
        volume=Decimal(1000),
    )
    return WakeJob(
        instance_id=instance_id,
        agent_id="test-rsi-fast",
        version=1,
        symbol=symbol,
        bar=bar,
        indicators={"rsi5": 20.0, "sma50": 95.0},
        recent_closes=["100"],
        trigger="entry",
    )


async def paper_instance(factory: async_sessionmaker[AsyncSession], agent: str = "test-rsi-fast") -> Instance:
    return await actions.create_instance(factory, agent, 1, "paper", status="running")


def worker_at(factory: async_sessionmaker[AsyncSession], at: datetime) -> DecisionWorker:
    from atp.worker.ai import AIFilterRunner

    return DecisionWorker(factory, ai=AIFilterRunner(factory, client=FakeChat()), live_clock=FixedClock(at))


class FlakyBroker:
    """Wraps PaperBroker and injects failures per method."""

    def __init__(self, inner: PaperBroker, fail: dict[str, list[Exception]]) -> None:
        self.inner, self.fail, self.name = inner, fail, "flaky"
        self.calls: dict[str, int] = {}

    def __getattr__(self, method: str) -> Any:
        target = getattr(self.inner, method)

        async def call(*a: Any, **kw: Any) -> Any:
            self.calls[method] = self.calls.get(method, 0) + 1
            queue = self.fail.get(method, [])
            if queue:
                raise queue.pop(0)
            return await target(*a, **kw)

        return call


# --- #6 kill switch -------------------------------------------------------------------


async def test_kill_switch_cancels_open_orders_and_blocks_new_ones(factory: Any, js: Any) -> None:
    insts = [await paper_instance(factory) for _ in range(3)]
    w = worker_at(factory, MARKET_OPEN)
    for i in insts:
        out = await w.handle(entry_job(i.id, MARKET_OPEN - timedelta(minutes=5)))
        assert out.action == "buy"
    async with factory() as s:
        open_ids = [
            o.id for o in await s.scalars(select(Order).where(Order.instance_id.in_([i.id for i in insts])))
        ]
        assert all(
            o.state == "accepted" for o in await s.scalars(select(Order).where(Order.id.in_(open_ids)))
        )

    started = time.monotonic()
    try:
        canceled = await actions.kill_all(factory, js)
        elapsed = time.monotonic() - started
        assert canceled == 3 and elapsed < 5
        async with factory() as s:
            states = set(await s.scalars(select(Order.state).where(Order.id.in_(open_ids))))
            broker_states = set(
                await s.scalars(
                    select(PaperOrder.status).where(PaperOrder.account_ref.in_([str(i.id) for i in insts]))
                )
            )
        assert states == {"canceled"} and broker_states == {"canceled"}

        later = await w.handle(entry_job(insts[0].id, MARKET_OPEN, symbol="QQQ"))
        assert later.action == "blocked" and later.order_id is None
        async with factory() as s:
            d = await s.get(Decision, later.decision_id)
        assert d is not None and "kill_switch" in (d.reasoning or "")
    finally:
        await actions.release_kill_switch(factory, js)


async def test_instance_kill_is_permanent(factory: Any, js: Any) -> None:
    inst = await paper_instance(factory)
    await actions.set_status(factory, inst.id, "killed", "test", js)
    with pytest.raises(ValueError, match="cannot be restarted"):
        await actions.set_status(factory, inst.id, "running", "test", js)


# --- #5 broker failures -----------------------------------------------------------------


async def test_transient_broker_errors_retry_then_succeed(factory: Any, monkeypatch: Any) -> None:
    inst = await paper_instance(factory)
    flaky: FlakyBroker | None = None

    async def broker_for(i: Instance, f: Any, clock: Any) -> Any:
        nonlocal flaky
        if flaky is None:
            flaky = FlakyBroker(
                PaperBroker(str(i.id), f, clock),
                {"submit_order": [BrokerTransientError("503"), BrokerTransientError("timeout")]},
            )
        return flaky

    monkeypatch.setattr(decision_mod, "broker_for", broker_for)
    out = await worker_at(factory, MARKET_OPEN).handle(entry_job(inst.id, MARKET_OPEN - timedelta(minutes=5)))
    assert out.action == "buy" and flaky is not None and flaky.calls["submit_order"] == 3
    async with factory() as s:
        order = await s.get(Order, out.order_id)
    assert order is not None and order.state == "accepted"


async def test_broker_outage_leaves_order_safe_and_retry_resumes(factory: Any, monkeypatch: Any) -> None:
    """Broker down for longer than in-call retries: the job fails (NAK), the order stays
    approved, and the redelivered job submits it exactly once."""
    inst = await paper_instance(factory)
    down = [BrokerTransientError("503")] * 4
    brokers: dict[str, FlakyBroker] = {}

    async def broker_for(i: Instance, f: Any, clock: Any) -> Any:
        return brokers.setdefault("b", FlakyBroker(PaperBroker(str(i.id), f, clock), {"submit_order": down}))

    monkeypatch.setattr(decision_mod, "broker_for", broker_for)
    monkeypatch.setattr("atp.brokers.base.asyncio.sleep", _no_sleep)
    w = worker_at(factory, MARKET_OPEN)
    job = entry_job(inst.id, MARKET_OPEN - timedelta(minutes=5))
    with pytest.raises(BrokerTransientError):
        await w.handle(job)
    async with factory() as s:
        orders = list(await s.scalars(select(Order).where(Order.instance_id == inst.id)))
    assert [o.state for o in orders] == ["approved"]

    out = await w.handle(job)  # redelivery after the outage
    assert out.resumed
    async with factory() as s:
        orders = list(await s.scalars(select(Order).where(Order.instance_id == inst.id)))
        at_broker = list(await s.scalars(select(PaperOrder).where(PaperOrder.account_ref == str(inst.id))))
    assert [o.state for o in orders] == ["accepted"] and len(at_broker) == 1


async def _no_sleep(_: float) -> None:
    return None


async def test_expired_keys_pause_instance(factory: Any, monkeypatch: Any) -> None:
    inst = await paper_instance(factory)

    async def broker_for(i: Instance, f: Any, clock: Any) -> Any:
        return FlakyBroker(
            PaperBroker(str(i.id), f, clock),
            {"get_account": [BrokerAuthError("401")] * 10, "get_positions": [BrokerAuthError("401")] * 10},
        )

    monkeypatch.setattr(decision_mod, "broker_for", broker_for)
    with pytest.raises(BrokerAuthError):
        await worker_at(factory, MARKET_OPEN).handle(entry_job(inst.id, MARKET_OPEN - timedelta(minutes=5)))
    async with factory() as s:
        refreshed = await s.get(Instance, inst.id)
    assert (
        refreshed is not None and refreshed.status == "paused" and "auth" in (refreshed.status_reason or "")
    )

    # reconciliation hitting the same expired keys also pauses and records an error run
    inst2 = await paper_instance(factory)
    monkeypatch.setattr("atp.reconcile.broker_for", broker_for)
    run = await reconcile_instance(factory, inst2.id)
    assert run.status == "error"
    async with factory() as s:
        refreshed = await s.get(Instance, inst2.id)
    assert refreshed is not None and refreshed.status == "paused"


# --- manual approval -----------------------------------------------------------------------


async def test_manual_approval_parks_then_submits(factory: Any, monkeypatch: Any) -> None:
    inst = await paper_instance(factory, "test-rsi-fast-manual")
    job = entry_job(inst.id, MARKET_OPEN - timedelta(minutes=5)).model_copy(
        update={"agent_id": "test-rsi-fast-manual"}
    )
    out = await worker_at(factory, MARKET_OPEN).handle(job)
    assert out.action == "pending" and out.order_id is not None
    async with factory() as s:
        order = await s.get(Order, out.order_id)
    assert order is not None and order.state == "proposed"
    monkeypatch.setattr("atp.control.actions.RealClock", lambda: FixedClock(MARKET_OPEN))
    approved = await actions.decide_pending(factory, out.order_id, approve=True)
    assert approved.state == "accepted" and approved.broker_order_id


# --- reconciliation -------------------------------------------------------------------------


async def test_reconciliation_mismatch_pauses_instance(factory: Any) -> None:
    inst = await paper_instance(factory)
    clean = await reconcile_instance(factory, inst.id)
    assert clean.status == "clean"
    async with factory() as s, s.begin():  # someone trades the account behind our back
        s.add(PaperPosition(account_ref=str(inst.id), symbol="TSLA", qty=Decimal(3), avg_price=Decimal(200)))
    run = await reconcile_instance(factory, inst.id)
    assert run.status == "mismatch" and "TSLA" in run.diffs_json["positions"]
    async with factory() as s:
        refreshed = await s.get(Instance, inst.id)
        n = len(
            list(await s.scalars(select(ReconciliationRun).where(ReconciliationRun.instance_id == inst.id)))
        )
    assert refreshed is not None and refreshed.status == "paused" and n == 2


async def test_duplicate_client_order_id_is_adopted_not_resent(factory: Any) -> None:
    inst = await paper_instance(factory)
    broker = PaperBroker(str(inst.id), factory, FixedClock(MARKET_OPEN))
    req = OrderRequest(client_order_id=f"{inst.id}-dup", symbol="SPY", side="buy", notional=Decimal(50))
    first = await broker.submit_order(req)
    from atp.brokers.base import DuplicateClientOrderId

    with pytest.raises(DuplicateClientOrderId):
        await broker.submit_order(req)
    assert (await broker.get_order_by_client_id(req.client_order_id)) == first


# --- control panel ---------------------------------------------------------------------------


def test_panel_requires_token_and_renders(factory: Any) -> None:
    from atp.control.app import app

    with TestClient(app) as client:
        r = client.get("/", follow_redirects=False)
        assert r.status_code == 303 and r.headers["location"] == "/login"
        assert client.post("/login", data={"token": "wrong"}).status_code == 401
        r = client.post("/login", data={"token": "test-admin-token"}, follow_redirects=False)
        assert r.status_code == 303
        for path in ("/", "/decisions", "/approvals", "/replays", "/healthz"):
            page = client.get(path)
            assert page.status_code == 200, path
        hdr = {"Authorization": "Bearer test-admin-token"}
        with TestClient(app) as fresh:
            assert fresh.get("/decisions", headers=hdr).status_code == 200


async def test_live_mode_refused_without_flag(factory: Any) -> None:
    with pytest.raises(PermissionError):
        await actions.create_instance(factory, "test-rsi-fast", 1, "alpaca_live")
    assert not (await _kill_switch(factory))


async def _kill_switch(factory: Any) -> bool:
    async with factory() as s:
        return await store.kill_switch_on(s)


# --- LiteLLM gateway (real container, mock model: no provider call) ----------------------------


async def test_litellm_gateway_roundtrip() -> None:
    import httpx

    from atp.config import Settings
    from atp.schema.agent import AIFilter
    from atp.worker.ai import LiteLLMClient, build_request, parse_verdict

    s = Settings(litellm_base_url="http://localhost:4000", litellm_master_key="sk-local-dev")  # type: ignore[arg-type]
    try:
        async with httpx.AsyncClient(timeout=2) as c:
            await c.get("http://localhost:4000/health/liveliness")
    except httpx.HTTPError:
        pytest.skip("LiteLLM gateway not running")
    req = build_request(
        AIFilter(model="mock-take", prompt="decide"), entry_job(uuid.uuid4(), MARKET_OPEN), "mock-take"
    )
    assert "temperature" not in req
    text, cost = await LiteLLMClient(s).complete(req)
    assert parse_verdict(text) == "TAKE" and cost >= 0
