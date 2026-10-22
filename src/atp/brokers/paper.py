"""Our own paper broker (SPEC §7).

PaperBroker is the client side: it accepts, cancels, and reports orders from its own
books (`paper_*` tables). PaperExchange is the matching side: on every bar it fills
open orders for that symbol:
- market orders at the bar's open plus slippage (configurable bps, default 5)
- limit/stop orders when the bar's range crosses the price
- a fee model (default $0)

Orders submitted at time t fill on the first bar whose open time is >= t, i.e. a
decision made at a bar's close fills at the next bar's open.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atp.brokers.base import (
    OPEN_STATUSES,
    AccountInfo,
    BrokerOrder,
    BrokerPosition,
    BrokerRejected,
    DuplicateClientOrderId,
    OrderRequest,
)
from atp.clock import Clock
from atp.db.models import PaperAccount, PaperOrder, PaperPosition
from atp.schema.messages import Bar

QTY_STEP = Decimal("0.000001")
PRICE_STEP = Decimal("0.0001")


def _to_broker_order(o: PaperOrder) -> BrokerOrder:
    return BrokerOrder(
        broker_order_id=str(o.id),
        client_order_id=o.client_order_id,
        symbol=o.symbol,
        side=o.side,  # type: ignore[arg-type]
        status=o.status,  # type: ignore[arg-type]
        filled_qty=o.filled_qty,
        filled_avg_price=o.filled_avg_price,
        fee=o.fee,
        updated_at=o.filled_at or o.submitted_at,
        reject_reason=o.reject_reason,
    )


async def open_paper_account(
    session: AsyncSession, account_ref: str, cash: Decimal, run_id: uuid.UUID | None
) -> None:
    if await session.get(PaperAccount, account_ref) is None:
        session.add(PaperAccount(account_ref=account_ref, cash=cash, run_id=run_id))


class PaperBroker:
    name = "paper"

    def __init__(
        self,
        account_ref: str,
        factory: async_sessionmaker[AsyncSession],
        clock: Clock,
    ) -> None:
        self.account_ref = account_ref
        self._factory = factory
        self._clock = clock

    async def submit_order(self, req: OrderRequest) -> BrokerOrder:
        async with self._factory() as s:
            existing = await self._by_client_id(s, req.client_order_id)
            if existing is not None:
                raise DuplicateClientOrderId(req.client_order_id)
            acct = await s.get(PaperAccount, self.account_ref)
            if acct is None:
                raise BrokerRejected(f"no paper account {self.account_ref}")
            status, reason = "accepted", None
            if req.side == "sell":
                pos = await s.get(PaperPosition, (self.account_ref, req.symbol))
                held = pos.qty if pos else Decimal(0)
                if req.qty is None or req.qty > held:
                    status, reason = "rejected", f"insufficient position: have {held}"
            elif req.notional is not None and req.notional > acct.cash:
                status, reason = "rejected", f"insufficient cash: have {acct.cash}"
            order = PaperOrder(
                account_ref=self.account_ref,
                run_id=acct.run_id,
                client_order_id=req.client_order_id,
                symbol=req.symbol,
                side=req.side,
                qty=req.qty,
                notional=req.notional,
                type=req.type,
                limit_price=req.limit_price,
                stop_price=req.stop_price,
                status=status,
                submitted_at=self._clock.now(),
                reject_reason=reason,
            )
            s.add(order)
            try:
                await s.commit()
            except IntegrityError as e:
                raise DuplicateClientOrderId(req.client_order_id) from e
            if status == "rejected":
                raise BrokerRejected(reason or "rejected")
            return _to_broker_order(order)

    async def cancel_order(self, broker_order_id: str) -> None:
        async with self._factory() as s, s.begin():
            o = await s.get(PaperOrder, uuid.UUID(broker_order_id), with_for_update=True)
            if o is not None and o.status in OPEN_STATUSES:
                o.status = "canceled"

    async def get_order(self, broker_order_id: str) -> BrokerOrder:
        async with self._factory() as s:
            o = await s.get(PaperOrder, uuid.UUID(broker_order_id))
            if o is None:
                raise BrokerRejected(f"unknown order {broker_order_id}")
            return _to_broker_order(o)

    async def get_order_by_client_id(self, client_order_id: str) -> BrokerOrder | None:
        async with self._factory() as s:
            o = await self._by_client_id(s, client_order_id)
            return _to_broker_order(o) if o else None

    async def list_open_orders(self) -> list[BrokerOrder]:
        async with self._factory() as s:
            rows = await s.scalars(
                select(PaperOrder).where(
                    PaperOrder.account_ref == self.account_ref,
                    PaperOrder.status.in_(OPEN_STATUSES),
                )
            )
            return [_to_broker_order(o) for o in rows]

    async def get_positions(self) -> list[BrokerPosition]:
        async with self._factory() as s:
            rows = await s.scalars(
                select(PaperPosition).where(
                    PaperPosition.account_ref == self.account_ref, PaperPosition.qty != 0
                )
            )
            return [BrokerPosition(p.symbol, p.qty, p.avg_price) for p in rows]

    async def get_account(self) -> AccountInfo:
        async with self._factory() as s:
            acct = await s.get(PaperAccount, self.account_ref)
            if acct is None:
                raise BrokerRejected(f"no paper account {self.account_ref}")
            positions = await s.scalars(
                select(PaperPosition).where(PaperPosition.account_ref == self.account_ref)
            )
            held = sum((p.qty * p.avg_price for p in positions), Decimal(0))
            return AccountInfo(cash=acct.cash, buying_power=acct.cash, equity=acct.cash + held)

    async def _by_client_id(self, s: AsyncSession, cid: str) -> PaperOrder | None:
        result: PaperOrder | None = await s.scalar(
            select(PaperOrder).where(PaperOrder.client_order_id == cid)
        )
        return result


class PaperExchange:
    """Fills open paper orders against incoming bars. Deterministic given the bars."""

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        slippage_bps: Decimal = Decimal(5),
        fee_per_order: Decimal = Decimal(0),
    ) -> None:
        self._factory = factory
        self.slippage = slippage_bps / Decimal(10_000)
        self.fee = fee_per_order

    async def on_bar(self, bar: Bar) -> list[str]:
        """Fill what this bar can fill. Returns the account refs that changed."""
        touched: list[str] = []
        async with self._factory() as s, s.begin():
            q = (
                select(PaperOrder)
                .where(
                    PaperOrder.symbol == bar.symbol,
                    PaperOrder.status.in_(OPEN_STATUSES),
                    PaperOrder.submitted_at <= bar.ts,
                    PaperOrder.run_id.is_(None) if bar.run_id is None else PaperOrder.run_id == bar.run_id,
                )
                .order_by(PaperOrder.submitted_at, PaperOrder.client_order_id)
                .with_for_update(skip_locked=True)
            )
            for order in (await s.scalars(q)).all():
                price = self._fill_price(order, bar)
                if price is None:
                    continue
                await self._apply_fill(s, order, price, bar.ts)
                touched.append(order.account_ref)
        return touched

    def _fill_price(self, o: PaperOrder, bar: Bar) -> Decimal | None:
        if o.type == "market":
            slip = self.slippage if o.side == "buy" else -self.slippage
            return (bar.open * (1 + slip)).quantize(PRICE_STEP)
        if o.type == "limit" and o.limit_price is not None:
            if o.side == "buy" and bar.low <= o.limit_price:
                return min(bar.open, o.limit_price)
            if o.side == "sell" and bar.high >= o.limit_price:
                return max(bar.open, o.limit_price)
        if o.type == "stop" and o.stop_price is not None:
            if o.side == "sell" and bar.low <= o.stop_price:
                return min(bar.open, o.stop_price)
            if o.side == "buy" and bar.high >= o.stop_price:
                return max(bar.open, o.stop_price)
        return None

    async def _apply_fill(self, s: AsyncSession, o: PaperOrder, price: Decimal, ts: datetime) -> None:
        acct = await s.get(PaperAccount, o.account_ref, with_for_update=True)
        assert acct is not None
        pos = await s.get(PaperPosition, (o.account_ref, o.symbol), with_for_update=True)
        if o.qty is not None:
            qty = o.qty
        else:
            assert o.notional is not None
            qty = (o.notional / price).quantize(QTY_STEP, rounding=ROUND_DOWN)
        held = pos.qty if pos else Decimal(0)
        if o.side == "sell" and qty > held:
            o.status, o.reject_reason = "rejected", f"insufficient position at fill: {held}"
            return
        cost = qty * price
        if o.side == "buy" and cost + self.fee > acct.cash:
            o.status, o.reject_reason = "rejected", "insufficient cash at fill"
            return
        if o.side == "buy":
            acct.cash -= cost + self.fee
            if pos is None:
                s.add(PaperPosition(account_ref=o.account_ref, symbol=o.symbol, qty=qty, avg_price=price))
            else:
                new_qty = pos.qty + qty
                pos.avg_price = ((pos.qty * pos.avg_price + cost) / new_qty).quantize(PRICE_STEP)
                pos.qty = new_qty
        else:
            assert pos is not None
            acct.cash += cost - self.fee
            pos.qty -= qty
            if pos.qty == 0:
                await s.delete(pos)
        o.status = "filled"
        o.filled_qty = qty
        o.filled_avg_price = price
        o.fee = self.fee
        o.filled_at = ts
