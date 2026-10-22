"""`atp` command line (SPEC §7)."""

from __future__ import annotations

import asyncio
import json
import os
import signal
import uuid
from collections.abc import Awaitable, Callable, Coroutine
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, TypeVar

import typer
from sqlalchemy import select

from atp import bus, obs
from atp.config import get_settings
from atp.control import actions
from atp.db.models import AgentVersion, Decision, Instance, Order
from atp.db.session import get_engine, session_factory

T = TypeVar("T")

app = typer.Typer(no_args_is_help=True, help="Agent Trading Platform v0")
agent_app = typer.Typer(no_args_is_help=True, help="Agent definitions")
instance_app = typer.Typer(no_args_is_help=True, help="Instances (an agent version running somewhere)")
bars_app = typer.Typer(no_args_is_help=True, help="Historical bar cache")
orders_app = typer.Typer(no_args_is_help=True, help="Orders and manual approvals")
decisions_app = typer.Typer(no_args_is_help=True, help="Decision log")
account_app = typer.Typer(no_args_is_help=True, help="Broker accounts")
run_app = typer.Typer(no_args_is_help=True, help="Run a long-lived service")
for sub, name in [
    (agent_app, "agent"),
    (instance_app, "instance"),
    (bars_app, "bars"),
    (orders_app, "orders"),
    (decisions_app, "decisions"),
    (account_app, "account"),
    (run_app, "run"),
]:
    app.add_typer(sub, name=name)


def _run(coro: Coroutine[Any, Any, T]) -> T:
    return asyncio.run(coro)


async def _with_js(fn: Callable[[Any], Awaitable[T]]) -> T:
    nc, js = await bus.connect(name="atp-cli")
    try:
        await bus.ensure_streams(js)
        return await fn(js)
    finally:
        await nc.drain()


def _parse_date(value: str) -> date:
    return date.fromisoformat(value)


# --- setup -----------------------------------------------------------------


@app.command()
def migrate() -> None:
    """Apply database migrations (alembic upgrade head)."""
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config("alembic.ini"), "head")


@app.command("init-bus")
def init_bus() -> None:
    """Create or update NATS streams and consumers."""
    _run(_with_js(lambda js: asyncio.sleep(0)))
    typer.echo("streams ready: MD, JOBS, JOBS_DLQ, EVENTS")


@app.command()
def keygen() -> None:
    """Print a new LOCAL_ENCRYPTION_KEY for dev credential encryption."""
    from cryptography.fernet import Fernet

    typer.echo(Fernet.generate_key().decode())


# --- agents ----------------------------------------------------------------


@agent_app.command("load")
def agent_load(paths: list[Path]) -> None:
    """Validate and load agent definition JSON files."""
    factory = session_factory()
    for p in paths:
        defn = actions.read_definition(p)
        created = _run(actions.load_agent(factory, defn))
        typer.echo(f"{'loaded' if created else 'unchanged'}: {defn.agent_id}@{defn.version} ({p})")


@agent_app.command("list")
def agent_list() -> None:
    async def go() -> None:
        async with session_factory()() as s:
            for v in await s.scalars(
                select(AgentVersion).order_by(AgentVersion.agent_id, AgentVersion.version)
            ):
                ai = "AI filter" if v.definition_json.get("ai_filter") else "rules only"
                typer.echo(f"{v.agent_id}@{v.version}  {ai}  {v.definition_json['name']}")

    _run(go())


# --- instances -------------------------------------------------------------


@instance_app.command("create")
def instance_create(
    agent: str = typer.Option(...),
    version: int = typer.Option(1),
    mode: str = typer.Option("paper", help="paper | alpaca_paper | alpaca_live"),
    account: str | None = typer.Option(None, help="broker account name (Alpaca modes)"),
    start: bool = typer.Option(False, help="start running immediately"),
) -> None:
    inst = _run(
        actions.create_instance(
            session_factory(),
            agent,
            version,
            mode,
            account_name=account,
            status="running" if start else "paused",
        )
    )
    typer.echo(f"instance {inst.id} ({mode}, {inst.status})")


def _status(instance_id: str, status: str, reason: str) -> None:
    n = _run(
        _with_js(lambda js: actions.set_status(session_factory(), uuid.UUID(instance_id), status, reason, js))
    )
    typer.echo(f"{instance_id}: {status}" + (f", canceled {n} open order(s)" if n else ""))


@instance_app.command("start")
def instance_start(instance_id: str) -> None:
    _status(instance_id, "running", "started by admin")


@instance_app.command("pause")
def instance_pause(instance_id: str) -> None:
    _status(instance_id, "paused", "paused by admin")


@instance_app.command("kill")
def instance_kill(instance_id: str) -> None:
    _status(instance_id, "killed", "killed by admin")


@instance_app.command("list")
def instance_list(all_: bool = typer.Option(False, "--all", help="include replay instances")) -> None:
    async def go() -> None:
        async with session_factory()() as s:
            q = select(Instance).order_by(Instance.created_at.desc())
            if not all_:
                q = q.where(Instance.run_id.is_(None))
            for i in await s.scalars(q.limit(50)):
                typer.echo(
                    f"{i.id}  {i.agent_id}@{i.version}  {i.mode:<12} {i.status:<9} {i.status_reason or ''}"
                )

    _run(go())


@app.command("kill-all")
def kill_all(release: bool = typer.Option(False, help="turn the global kill switch back off")) -> None:
    """Global kill switch: block all new orders and cancel every open order."""
    if release:
        _run(_with_js(lambda js: actions.release_kill_switch(session_factory(), js)))
        typer.echo("kill switch released")
        return
    n = _run(_with_js(lambda js: actions.kill_all(session_factory(), js)))
    typer.echo(f"KILL SWITCH ON: canceled {n} open order(s)")


# --- replay ----------------------------------------------------------------


@app.command()
def replay(
    agent: str = typer.Option(...),
    version: int = typer.Option(1),
    date_: str = typer.Option(..., "--date", help="YYYY-MM-DD (New York trading day)"),
    speed: float = typer.Option(20.0, help="x real time; 0 = as fast as possible"),
    copies: int = typer.Option(1, help="identical instances (burst test)"),
    inline: bool = typer.Option(False, help="run the watch engine and workers in this process"),
) -> None:
    """Replay a historical day through the full pipeline on a simulated clock."""
    from atp.replay import run_replay

    async def go(js: Any) -> Any:
        factory = session_factory()
        stop = asyncio.Event()
        services: list[asyncio.Task[None]] = []
        if inline:
            services = _start_services(js, factory, stop)
        try:
            return await run_replay(factory, js, agent, version, _parse_date(date_), speed or None, copies)
        finally:
            stop.set()
            await asyncio.gather(*services, return_exceptions=True)

    summary = _run(_with_js(go))
    typer.echo(json.dumps(summary.__dict__, default=str, indent=2))


def _start_services(js: Any, factory: Any, stop: asyncio.Event) -> list[asyncio.Task[None]]:
    from atp.watch.engine import run_watch
    from atp.worker.decision import DecisionWorker
    from atp.worker.service import run_worker

    return [
        asyncio.create_task(run_watch(js, factory, get_engine(), stop)),
        asyncio.create_task(run_worker(js, DecisionWorker(factory), stop=stop)),
    ]


# --- reconcile / orders / decisions ------------------------------------------


@app.command()
def reconcile(instance_id: str | None = typer.Argument(None)) -> None:
    """Reconcile one instance (or every paper/live instance) with its broker now."""
    from atp.reconcile import reconcile_instance

    async def go(js: Any) -> None:
        factory = session_factory()
        async with factory() as s:
            ids = (
                [uuid.UUID(instance_id)]
                if instance_id
                else list(
                    await s.scalars(
                        select(Instance.id).where(Instance.run_id.is_(None), Instance.status != "killed")
                    )
                )
            )
        for iid in ids:
            run = await reconcile_instance(factory, iid, js)
            typer.echo(f"{iid}: {run.status} {json.dumps(run.diffs_json) if run.diffs_json else ''}")

    _run(_with_js(go))


@orders_app.command("list")
def orders_list(
    instance_id: str | None = typer.Option(None, "--instance"),
    pending: bool = typer.Option(False),
    n: int = 30,
) -> None:
    async def go() -> None:
        async with session_factory()() as s:
            q = select(Order).order_by(Order.created_at.desc()).limit(n)
            if instance_id:
                q = q.where(Order.instance_id == uuid.UUID(instance_id))
            if pending:
                q = q.where(Order.state == "proposed")
            for o in await s.scalars(q):
                size = f"qty={o.qty}" if o.qty is not None else f"${o.notional}"
                px = f" @ {o.filled_avg_price}" if o.filled_avg_price else ""
                typer.echo(
                    f"{o.id}  {o.created_at:%Y-%m-%d %H:%M}  {o.side:<4} {o.symbol:<5} {size:<16} {o.state:<16}{px}"
                )

    _run(go())


@orders_app.command("approve")
def orders_approve(order_id: str) -> None:
    o = _run(actions.decide_pending(session_factory(), uuid.UUID(order_id), approve=True))
    typer.echo(f"{order_id}: {o.state}")


@orders_app.command("reject")
def orders_reject(order_id: str) -> None:
    o = _run(actions.decide_pending(session_factory(), uuid.UUID(order_id), approve=False))
    typer.echo(f"{order_id}: {o.state}")


@decisions_app.command("tail")
def decisions_tail(
    instance_id: str | None = typer.Option(None, "--instance"),
    n: int = typer.Option(20, "-n"),
    follow: bool = typer.Option(False, "-f", "--follow"),
) -> None:
    """Show recent decisions (inputs summary, action, reasoning)."""

    async def go() -> None:
        seen: set[uuid.UUID] = set()
        while True:
            async with session_factory()() as s:
                q = select(Decision).order_by(Decision.created_at.desc()).limit(n)
                if instance_id:
                    q = q.where(Decision.instance_id == uuid.UUID(instance_id))
                rows = list(await s.scalars(q))
            for d in reversed(rows):
                if d.id in seen:
                    continue
                seen.add(d.id)
                ind = d.inputs_json.get("indicators", {})
                ind_s = " ".join(f"{k}={v:.2f}" for k, v in ind.items() if v is not None)
                typer.echo(
                    f"{d.bar_ts:%Y-%m-%d %H:%M} {d.symbol:<5} {d.action:<8} ${d.cost_usd:.5f}  {ind_s}\n"
                    f"    {d.reasoning}"
                )
            if not follow:
                return
            await asyncio.sleep(2)

    _run(go())


# --- bars --------------------------------------------------------------------


@bars_app.command("fetch")
def bars_fetch(
    symbols: str = typer.Option("SPY,QQQ,AAPL,MSFT,NVDA"),
    start: str = typer.Option(..., help="YYYY-MM-DD"),
    end: str = typer.Option(..., help="YYYY-MM-DD (inclusive)"),
    timeframe: str = typer.Option("5Min"),
) -> None:
    """Download historical bars from Alpaca (IEX) into the `bars` cache."""
    from atp.marketdata.alpaca import AlpacaDataSource
    from atp.marketdata.base import NY, upsert_bars

    s = get_settings()
    src = AlpacaDataSource(
        s.alpaca_api_key_id.get_secret_value(), s.alpaca_api_secret_key.get_secret_value(), s.alpaca_data_feed
    )
    t0 = datetime.combine(_parse_date(start), datetime.min.time(), NY)
    t1 = datetime.combine(_parse_date(end) + timedelta(days=1), datetime.min.time(), NY)

    async def go() -> int:
        bars = await src.history(symbols.split(","), t0, t1, timeframe)
        async with session_factory()() as sess, sess.begin():
            return await upsert_bars(sess, bars, source="alpaca")

    typer.echo(f"cached {_run(go())} bars")


@bars_app.command("synth")
def bars_synth(
    symbols: str = typer.Option("SPY,QQQ,AAPL,MSFT,NVDA"),
    start: str = typer.Option(..., help="YYYY-MM-DD"),
    end: str = typer.Option(..., help="YYYY-MM-DD (inclusive)"),
    timeframe: str = typer.Option("5Min"),
) -> None:
    """Generate deterministic SYNTHETIC bars (not market data) for keyless testing."""
    from atp.marketdata.base import upsert_bars
    from atp.marketdata.synthetic import synth_days

    d0, d1 = _parse_date(start), _parse_date(end)
    days = [
        d0 + timedelta(days=i) for i in range((d1 - d0).days + 1) if (d0 + timedelta(days=i)).weekday() < 5
    ]
    bars = synth_days(symbols.split(","), days, timeframe)

    async def go() -> int:
        async with session_factory()() as sess, sess.begin():
            return await upsert_bars(sess, bars, source="synthetic")

    typer.echo(f"cached {_run(go())} SYNTHETIC bars for {len(days)} weekday(s)")


# --- accounts ----------------------------------------------------------------


@account_app.command("add-alpaca")
def account_add_alpaca(
    name: str = typer.Option("alpaca"),
    live: bool = typer.Option(False, help="mark as a LIVE account (real money)"),
) -> None:
    """Store Alpaca credentials (from ALPACA_API_KEY_ID / ALPACA_API_SECRET_KEY), encrypted."""
    s = get_settings()
    key, secret = s.alpaca_api_key_id.get_secret_value(), s.alpaca_api_secret_key.get_secret_value()
    if not key or not secret:
        raise typer.BadParameter("set ALPACA_API_KEY_ID and ALPACA_API_SECRET_KEY first")
    if live and not typer.confirm("This account trades REAL money. Continue?"):
        raise typer.Abort()
    aid = _run(actions.add_alpaca_account(session_factory(), name, key, secret, live))
    typer.echo(f"account {name} ({'LIVE' if live else 'paper'}): {aid}")


# --- services ----------------------------------------------------------------


def _serve(name: str, body: Callable[[Any, Any, asyncio.Event], Awaitable[None]]) -> None:
    obs.setup(name)

    async def go() -> None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
        nc, js = await bus.connect(name=f"atp-{name}")
        await bus.ensure_streams(js)
        try:
            await body(js, session_factory(), stop)
        finally:
            await nc.drain()

    asyncio.run(go())


@run_app.command("watch")
def run_watch_cmd() -> None:
    from atp.watch.engine import run_watch

    _serve("watch", lambda js, f, stop: run_watch(js, f, get_engine(), stop))


@run_app.command("worker")
def run_worker_cmd(concurrency: int = typer.Option(16)) -> None:
    from atp.worker.decision import DecisionWorker
    from atp.worker.service import run_worker

    _serve(
        "worker", lambda js, f, stop: run_worker(js, DecisionWorker(f), concurrency=concurrency, stop=stop)
    )


@run_app.command("reconciler")
def run_reconciler_cmd() -> None:
    from atp.reconcile import run_reconciler

    _serve("reconciler", lambda js, f, stop: run_reconciler(f, js, get_settings().reconcile_interval_s, stop))


@run_app.command("marketdata")
def run_marketdata_cmd() -> None:
    from atp.marketdata.service import run_marketdata

    _serve("marketdata", lambda js, f, stop: run_marketdata(js, f, stop))


@run_app.command("panel")
def run_panel_cmd(host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    obs.setup("panel")
    uvicorn.run("atp.control.app:app", host=host, port=port, log_config=None, proxy_headers=True)


@app.command()
def version() -> None:
    typer.echo(f"atp 0.1.0  ({os.environ.get('ATP_IMAGE_TAG', 'local')}) {datetime.now(UTC):%Y-%m-%d}")


if __name__ == "__main__":
    app()
