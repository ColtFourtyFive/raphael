"""Fills, positions, and the double-entry ledger. Callers own the transaction.

Accounts per instance (every posting sums to zero):
- deposit:  cash +X, equity -X
- buy:      position:SYM +cost, cash -(cost+fee), fees +fee
- sell:     cash +(proceeds-fee), position:SYM -(qty*avg), realized_pnl -(proceeds-qty*avg), fees +fee
Realized P&L is the negated balance of `realized_pnl` (income is a credit).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from atp.db.models import Fill, LedgerEntry, Order, Position

PRICE_STEP = Decimal("0.0001")


async def deposit(session: AsyncSession, instance_id: uuid.UUID, amount: Decimal, ts: datetime) -> None:
    session.add_all(
        [
            LedgerEntry(instance_id=instance_id, account="cash", amount=amount, ref="deposit", ts=ts),
            LedgerEntry(instance_id=instance_id, account="equity", amount=-amount, ref="deposit", ts=ts),
        ]
    )


async def record_fill(
    session: AsyncSession,
    order: Order,
    qty: Decimal,
    price: Decimal,
    fee: Decimal,
    ts: datetime,
    broker_fill_id: str,
) -> bool:
    """Write the fill, position, and ledger postings. False if this fill was already recorded."""
    inserted = await session.scalar(
        insert(Fill)
        .values(
            id=uuid.uuid4(),
            order_id=order.id,
            qty=qty,
            price=price,
            fee=fee,
            ts=ts,
            broker_fill_id=broker_fill_id,
        )
        .on_conflict_do_nothing(index_elements=["broker_fill_id"])
        .returning(Fill.id)
    )
    if inserted is None:
        return False

    pos = await session.get(Position, (order.instance_id, order.symbol), with_for_update=True)
    ref = order.client_order_id
    entries: list[tuple[str, Decimal]] = []
    if order.side == "buy":
        cost = qty * price
        if pos is None:
            session.add(
                Position(
                    instance_id=order.instance_id,
                    symbol=order.symbol,
                    qty=qty,
                    avg_price=price,
                    updated_at=ts,
                )
            )
        else:
            new_qty = pos.qty + qty
            pos.avg_price = ((pos.qty * pos.avg_price + cost) / new_qty).quantize(PRICE_STEP)
            pos.qty = new_qty
            pos.updated_at = ts
        entries = [(f"position:{order.symbol}", cost), ("cash", -(cost + fee)), ("fees", fee)]
    else:
        if pos is None or pos.qty < qty:
            raise ValueError(f"sell fill of {qty} {order.symbol} exceeds recorded position")
        proceeds = qty * price
        basis = qty * pos.avg_price
        pos.qty -= qty
        pos.updated_at = ts
        if pos.qty == 0:
            await session.delete(pos)
        entries = [
            ("cash", proceeds - fee),
            (f"position:{order.symbol}", -basis),
            ("realized_pnl", -(proceeds - basis)),
            ("fees", fee),
        ]
    session.add_all(
        LedgerEntry(instance_id=order.instance_id, account=a, amount=amt, ref=ref, ts=ts)
        for a, amt in entries
        if amt != 0
    )
    return True


async def balance(session: AsyncSession, instance_id: uuid.UUID, account: str) -> Decimal:
    v = await session.scalar(
        select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
            LedgerEntry.instance_id == instance_id, LedgerEntry.account == account
        )
    )
    return Decimal(v or 0)


async def realized_pnl_since(session: AsyncSession, instance_id: uuid.UUID, since: datetime) -> Decimal:
    """Realized P&L net of fees since `since` (negative = loss)."""
    rows = await session.execute(
        select(LedgerEntry.account, func.sum(LedgerEntry.amount))
        .where(
            LedgerEntry.instance_id == instance_id,
            LedgerEntry.ts >= since,
            LedgerEntry.account.in_(["realized_pnl", "fees"]),
        )
        .group_by(LedgerEntry.account)
    )
    sums = {a: Decimal(v) for a, v in rows}
    return -sums.get("realized_pnl", Decimal(0)) - sums.get("fees", Decimal(0))


async def positions_for(session: AsyncSession, instance_id: uuid.UUID) -> dict[str, Position]:
    rows = await session.scalars(
        select(Position).where(Position.instance_id == instance_id, Position.qty != 0)
    )
    return {p.symbol: p for p in rows}
