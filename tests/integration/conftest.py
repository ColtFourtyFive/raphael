"""Integration fixtures: real Postgres and NATS from `docker compose up -d`.

WARNING: wipes the NATS streams (MD, JOBS, JOBS_DLQ, EVENTS) on the target server and
recreates the test database schema.
"""

from __future__ import annotations

import asyncio
import json
import socket
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
from nats.js import JetStreamContext
from nats.js.errors import NotFoundError
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from atp import bus
from atp.config import get_settings
from atp.control.actions import load_agent, read_definition
from atp.db.session import get_engine, session_factory
from atp.marketdata.base import previous_weekdays, upsert_bars
from atp.marketdata.synthetic import synth_days
from atp.watch.engine import run_watch
from atp.worker.ai import AIFilterRunner
from atp.worker.decision import DecisionWorker
from atp.worker.service import run_worker

ROOT = Path(__file__).parents[2]
DAY = date(2026, 10, 14)
SYMBOLS = ["SPY", "QQQ", "AAPL", "MSFT", "NVDA"]


def _up(host: str, port: int) -> bool:
    try:
        socket.create_connection((host, port), timeout=1).close()
        return True
    except OSError:
        return False


def pytest_collection_modifyitems(config: Any, items: list[Any]) -> None:
    if _up("localhost", 5432) and _up("localhost", 4222):
        return
    skip = pytest.mark.skip(reason="needs `docker compose up -d` (Postgres + NATS)")
    for item in items:
        if "integration" in str(item.fspath):
            item.add_marker(skip)


@pytest.fixture(scope="session")
def migrated() -> None:
    url = get_settings().database_url
    admin = create_engine(url.rsplit("/", 1)[0] + "/atp", isolation_level="AUTOCOMMIT")
    dbname = url.rsplit("/", 1)[1]
    with admin.connect() as c:
        if not c.scalar(text("SELECT 1 FROM pg_database WHERE datname=:n"), {"n": dbname}):
            c.execute(text(f'CREATE DATABASE "{dbname}"'))
    admin.dispose()
    eng = create_engine(url, isolation_level="AUTOCOMMIT")
    with eng.connect() as c:
        c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public;"))
    eng.dispose()
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "src/atp/db/migrations"))
    command.upgrade(cfg, "head")


@pytest_asyncio.fixture(scope="session")
async def engine(migrated: None) -> AsyncIterator[AsyncEngine]:
    eng = get_engine()
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture(scope="session")
async def factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    f = session_factory(engine)
    days = [*previous_weekdays(DAY, 6), DAY]
    async with f() as s, s.begin():
        await upsert_bars(s, synth_days(SYMBOLS, days), source="synthetic")
    for p in [*(ROOT / "agents/examples").glob("*.json"), *(ROOT / "tests/fixtures").glob("*.json")]:
        await load_agent(f, read_definition(p))
    return f


@pytest_asyncio.fixture(scope="session")
async def js() -> AsyncIterator[JetStreamContext]:
    nc, jsc = await bus.connect(name="atp-tests")
    for name in ("MD", "JOBS", "JOBS_DLQ", "EVENTS"):
        try:
            await jsc.delete_stream(name)
        except NotFoundError:
            pass
    await bus.ensure_streams(jsc)
    yield jsc
    await nc.drain()


class FakeChat:
    """Deterministic stand-in for the gateway: TAKE unless RSI is extremely low."""

    def __init__(self, cost: str = "0.00021") -> None:
        self.calls = 0
        self.cost = cost

    async def complete(self, request: dict[str, Any]) -> tuple[str, Any]:
        from decimal import Decimal

        self.calls += 1
        snap = json.loads(request["messages"][1]["content"])
        rsi = next(iter(v for k, v in snap["indicators"].items() if k.startswith("rsi")))
        if rsi is not None and rsi < 12:
            return "SKIP: capitulation, wait for stabilisation.", Decimal(self.cost)
        return "TAKE: shallow dip inside an uptrend.", Decimal(self.cost)


@dataclass
class Services:
    js: JetStreamContext
    factory: async_sessionmaker[AsyncSession]
    engine: AsyncEngine
    worker: DecisionWorker
    watch_task: asyncio.Task[None] | None = None
    worker_tasks: list[asyncio.Task[None]] = field(default_factory=list)
    _stops: dict[int, asyncio.Event] = field(default_factory=dict)

    def _spawn(self, coro_fn: Any) -> asyncio.Task[None]:
        stop = asyncio.Event()
        task = asyncio.create_task(coro_fn(stop))
        self._stops[id(task)] = stop
        return task

    def start_watch(self) -> None:
        self.watch_task = self._spawn(lambda stop: run_watch(self.js, self.factory, self.engine, stop))

    def start_workers(self, worker: DecisionWorker | None = None, n: int = 2) -> None:
        w = worker or self.worker
        for _ in range(n):
            self.worker_tasks.append(self._spawn(lambda stop: run_worker(self.js, w, concurrency=8, stop=stop)))

    async def _halt(self, task: asyncio.Task[None], hard: bool) -> None:
        if hard:
            task.cancel()
        else:
            self._stops[id(task)].set()
        await asyncio.gather(task, return_exceptions=True)

    async def stop_watch(self, hard: bool = False) -> None:
        if self.watch_task:
            await self._halt(self.watch_task, hard)
            self.watch_task = None

    async def stop_workers(self, hard: bool = False) -> None:
        await asyncio.gather(*(self._halt(t, hard) for t in self.worker_tasks))
        self.worker_tasks = []

    async def stop(self) -> None:
        await self.stop_watch()
        await self.stop_workers()


@pytest.fixture
def fake_chat() -> FakeChat:
    return FakeChat()


@pytest_asyncio.fixture
async def services(
    js: JetStreamContext, factory: async_sessionmaker[AsyncSession], engine: AsyncEngine, fake_chat: FakeChat
) -> AsyncIterator[Services]:
    worker = DecisionWorker(factory, ai=AIFilterRunner(factory, client=fake_chat))
    svc = Services(js, factory, engine, worker)
    yield svc
    await svc.stop()
