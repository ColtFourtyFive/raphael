"""Control panel (SPEC §7): FastAPI + server-rendered HTML (Jinja/HTMX), one admin token."""

from __future__ import annotations

import hmac
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, select

from atp import bus, ledger, store
from atp.config import get_settings
from atp.control import actions
from atp.db.models import (
    Decision,
    Instance,
    Order,
    OrderEvent,
    Position,
    ReconciliationRun,
    RiskEvent,
)
from atp.db.session import session_factory

TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))
COOKIE = "atp_admin"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.factory = session_factory()
    try:
        app.state.nc, app.state.js = await bus.connect(name="atp-panel")
    except Exception:  # panel still works read-only without NATS
        app.state.nc, app.state.js = None, None
    yield
    if app.state.nc is not None:
        await app.state.nc.drain()


app = FastAPI(title="atp control panel", lifespan=lifespan)


def _token_ok(given: str | None) -> bool:
    expected = get_settings().admin_token.get_secret_value()
    return bool(expected) and given is not None and hmac.compare_digest(given, expected)


async def require_admin(request: Request) -> None:
    auth = request.headers.get("authorization", "")
    bearer = auth.removeprefix("Bearer ").strip() if auth.startswith("Bearer ") else None
    if _token_ok(bearer) or _token_ok(request.cookies.get(COOKIE)):
        return
    raise HTTPException(status_code=303, headers={"Location": "/login"})


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/login", response_class=HTMLResponse)
async def login_form(request: Request) -> Response:
    return TEMPLATES.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
async def login(request: Request, token: str = Form(...)) -> Response:
    if not _token_ok(token):
        return TEMPLATES.TemplateResponse(request, "login.html", {"error": "invalid token"}, status_code=401)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie(COOKIE, token, httponly=True, samesite="strict", secure=request.url.scheme == "https")
    return resp


def _f(request: Request) -> Any:
    return request.app.state.factory


@app.get("/", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def index(request: Request) -> Response:
    f = _f(request)
    async with f() as s:
        insts = list(
            await s.scalars(
                select(Instance).where(Instance.run_id.is_(None)).order_by(Instance.created_at.desc())
            )
        )
        kill = await store.kill_switch_on(s)
        rows = []
        for i in insts:
            pnl = -(await ledger.balance(s, i.id, "realized_pnl")) - await ledger.balance(s, i.id, "fees")
            cost = await s.scalar(
                select(func.coalesce(func.sum(Decision.cost_usd), 0)).where(Decision.instance_id == i.id)
            )
            last_rec = await s.scalar(
                select(ReconciliationRun)
                .where(ReconciliationRun.instance_id == i.id)
                .order_by(ReconciliationRun.ts.desc())
                .limit(1)
            )
            rows.append({"i": i, "pnl": pnl, "cost": Decimal(cost), "recon": last_rec})
        pending = await s.scalar(select(func.count()).select_from(Order).where(Order.state == "proposed"))
    return TEMPLATES.TemplateResponse(request, "index.html", {"rows": rows, "kill": kill, "pending": pending})


@app.post("/instances/{iid}/{action}", dependencies=[Depends(require_admin)])
async def instance_action(request: Request, iid: uuid.UUID, action: str) -> Response:
    status = {"start": "running", "pause": "paused", "kill": "killed"}.get(action)
    if status is None:
        raise HTTPException(404)
    await actions.set_status(_f(request), iid, status, f"{action} via panel", request.app.state.js)
    return RedirectResponse("/", status_code=303)


@app.post("/kill-switch", dependencies=[Depends(require_admin)])
async def kill_switch(request: Request, on: bool = Form(...)) -> Response:
    if on:
        await actions.kill_all(_f(request), request.app.state.js, "kill switch via panel")
    else:
        await actions.release_kill_switch(_f(request), request.app.state.js)
    return RedirectResponse("/", status_code=303)


@app.get("/instances/{iid}", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def instance_detail(request: Request, iid: uuid.UUID) -> Response:
    async with _f(request)() as s:
        inst = await s.get(Instance, iid)
        if inst is None:
            raise HTTPException(404)
        positions = list(await s.scalars(select(Position).where(Position.instance_id == iid)))
        orders = list(
            await s.scalars(
                select(Order).where(Order.instance_id == iid).order_by(Order.created_at.desc()).limit(50)
            )
        )
        recon = list(
            await s.scalars(
                select(ReconciliationRun)
                .where(ReconciliationRun.instance_id == iid)
                .order_by(ReconciliationRun.ts.desc())
                .limit(10)
            )
        )
        cash = await ledger.balance(s, iid, "cash")
    return TEMPLATES.TemplateResponse(
        request,
        "instance.html",
        {"inst": inst, "positions": positions, "orders": orders, "recon": recon, "cash": cash},
    )


@app.get("/orders/{oid}", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def order_detail(request: Request, oid: uuid.UUID) -> Response:
    async with _f(request)() as s:
        order = await s.get(Order, oid)
        if order is None:
            raise HTTPException(404)
        events = list(
            await s.scalars(select(OrderEvent).where(OrderEvent.order_id == oid).order_by(OrderEvent.id))
        )
        decision = await s.get(Decision, order.decision_id) if order.decision_id else None
        risks = (
            list(await s.scalars(select(RiskEvent).where(RiskEvent.decision_id == order.decision_id)))
            if decision
            else []
        )
    return TEMPLATES.TemplateResponse(
        request, "order.html", {"o": order, "events": events, "d": decision, "risks": risks}
    )


@app.get("/decisions", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def decisions(request: Request, instance: uuid.UUID | None = None, limit: int = 100) -> Response:
    async with _f(request)() as s:
        q = select(Decision).order_by(Decision.created_at.desc()).limit(min(limit, 500))
        if instance:
            q = q.where(Decision.instance_id == instance)
        rows = list(await s.scalars(q))
    tpl = "decision_rows.html" if request.headers.get("hx-request") else "decisions.html"
    return TEMPLATES.TemplateResponse(request, tpl, {"rows": rows, "instance": instance})


@app.get("/approvals", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def approvals(request: Request) -> Response:
    async with _f(request)() as s:
        rows = list(
            await s.scalars(select(Order).where(Order.state == "proposed").order_by(Order.created_at))
        )
    return TEMPLATES.TemplateResponse(request, "approvals.html", {"rows": rows})


@app.post("/approvals/{oid}", dependencies=[Depends(require_admin)])
async def approve(request: Request, oid: uuid.UUID, approve: bool = Form(...)) -> Response:
    await actions.decide_pending(_f(request), oid, approve)
    return RedirectResponse("/approvals", status_code=303)


@app.get("/replays", response_class=HTMLResponse, dependencies=[Depends(require_admin)])
async def replays(request: Request) -> Response:
    async with _f(request)() as s:
        rows = (
            await s.execute(
                select(
                    Instance.run_id,
                    Instance.agent_id,
                    Instance.version,
                    func.min(Instance.created_at),
                    func.count(Instance.id),
                    func.min(Instance.id),
                )
                .where(Instance.run_id.is_not(None))
                .group_by(Instance.run_id, Instance.agent_id, Instance.version)
                .order_by(func.min(Instance.created_at).desc())
                .limit(50)
            )
        ).all()
        runs = []
        for run_id, agent_id, version, created, copies, first in rows:
            n_dec = await s.scalar(
                select(func.count()).select_from(Decision).where(Decision.instance_id == first)
            )
            n_ord = await s.scalar(select(func.count()).select_from(Order).where(Order.instance_id == first))
            pnl = -(await ledger.balance(s, first, "realized_pnl")) - await ledger.balance(s, first, "fees")
            runs.append(
                {
                    "run_id": run_id,
                    "agent": f"{agent_id}@{version}",
                    "created": created,
                    "copies": copies,
                    "first": first,
                    "decisions": n_dec,
                    "orders": n_ord,
                    "pnl": pnl,
                }
            )
    return TEMPLATES.TemplateResponse(request, "replays.html", {"runs": runs})
