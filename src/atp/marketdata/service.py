"""Live market data process: Alpaca websocket → NATS `md.bars.<symbol>`.

Subscribes to the union of universes of running paper/live instances at startup;
restart the service after adding an instance with new symbols (v0).
"""

from __future__ import annotations

import asyncio
import logging

from nats.js import JetStreamContext
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atp import bus, store
from atp.config import get_settings
from atp.marketdata.alpaca import AlpacaDataSource

log = logging.getLogger(__name__)


async def run_marketdata(
    js: JetStreamContext, factory: async_sessionmaker[AsyncSession], stop: asyncio.Event | None = None
) -> None:
    stop = stop or asyncio.Event()
    s = get_settings()
    async with factory() as session:
        insts = await store.running_instances(session, None)
        wanted: dict[str, set[str]] = {}
        for inst in insts:
            defn = await store.load_definition(session, inst.agent_id, inst.version)
            wanted.setdefault(defn.schedule.timeframe, set()).update(defn.universe)
    if not wanted:
        log.warning("no running paper/live instances; marketdata has nothing to stream")
        await stop.wait()
        return
    src = AlpacaDataSource(
        s.alpaca_api_key_id.get_secret_value(), s.alpaca_api_secret_key.get_secret_value(), s.alpaca_data_feed
    )

    async def pump(timeframe: str, symbols: set[str]) -> None:
        log.info("streaming bars", extra={"timeframe": timeframe, "symbols": sorted(symbols)})
        async for bar in src.stream(sorted(symbols), timeframe):
            await bus.publish_model(
                js,
                bus.MD_SUBJECT.format(symbol=bar.symbol),
                bar,
                msg_id=f"live:{bar.symbol}:{bar.timeframe}:{bar.ts.isoformat()}",
            )

    tasks = [asyncio.create_task(pump(tf, syms)) for tf, syms in wanted.items()]
    await stop.wait()
    for t in tasks:
        t.cancel()
