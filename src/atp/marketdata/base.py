"""MarketDataSource interface, session calendar helpers, and the `bars` cache."""

from __future__ import annotations

from collections.abc import AsyncIterator, Iterable, Sequence
from datetime import UTC, date, datetime, time, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from atp.db.models import BarRow
from atp.schema.messages import Bar

NY = ZoneInfo("America/New_York")
SESSION_OPEN = time(9, 30)
SESSION_CLOSE = time(16, 0)


class MarketDataSource(Protocol):
    def stream(self, symbols: Sequence[str], timeframe: str) -> AsyncIterator[Bar]: ...

    async def history(
        self, symbols: Sequence[str], start: datetime, end: datetime, timeframe: str
    ) -> list[Bar]: ...


def session_bounds(day: date) -> tuple[datetime, datetime]:
    """Regular session [open, close) for a New York trading day, in UTC."""
    open_ = datetime.combine(day, SESSION_OPEN, NY).astimezone(UTC)
    close = datetime.combine(day, SESSION_CLOSE, NY).astimezone(UTC)
    return open_, close


def in_regular_session(ts: datetime) -> bool:
    local = ts.astimezone(NY)
    return local.weekday() < 5 and SESSION_OPEN <= local.time() < SESSION_CLOSE


def previous_weekdays(day: date, n: int) -> list[date]:
    out: list[date] = []
    d = day
    while len(out) < n:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            out.append(d)
    return sorted(out)


def bar_from_row(r: BarRow) -> Bar:
    return Bar(
        symbol=r.symbol,
        timeframe=r.timeframe,
        ts=r.ts,
        open=r.open,
        high=r.high,
        low=r.low,
        close=r.close,
        volume=r.volume,
    )


async def upsert_bars(session: AsyncSession, bars: Iterable[Bar], source: str) -> int:
    rows = [
        {
            "symbol": b.symbol,
            "timeframe": b.timeframe,
            "ts": b.ts,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
            "source": source,
        }
        for b in bars
    ]
    for i in range(0, len(rows), 1000):
        chunk = rows[i : i + 1000]
        stmt = insert(BarRow).values(chunk)
        stmt = stmt.on_conflict_do_update(
            index_elements=["symbol", "timeframe", "ts"],
            set_={k: stmt.excluded[k] for k in ("open", "high", "low", "close", "volume", "source")},
        )
        await session.execute(stmt)
    return len(rows)


async def load_bars(
    session: AsyncSession,
    symbols: Sequence[str],
    timeframe: str,
    start: datetime,
    end: datetime,
) -> list[Bar]:
    rows = await session.scalars(
        select(BarRow)
        .where(
            BarRow.symbol.in_(list(symbols)),
            BarRow.timeframe == timeframe,
            BarRow.ts >= start,
            BarRow.ts < end,
        )
        .order_by(BarRow.ts, BarRow.symbol)
    )
    return [bar_from_row(r) for r in rows]


async def load_lookback(
    session: AsyncSession, symbol: str, timeframe: str, before: datetime, n: int
) -> list[Bar]:
    """The `n` bars strictly before `before`, oldest first (indicator warm-up)."""
    rows = await session.scalars(
        select(BarRow)
        .where(BarRow.symbol == symbol, BarRow.timeframe == timeframe, BarRow.ts < before)
        .order_by(BarRow.ts.desc())
        .limit(n)
    )
    return [bar_from_row(r) for r in reversed(list(rows))]
