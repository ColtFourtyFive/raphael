"""Market-open burst test (SPEC §9 #7) at full scale.

Replays one day with N identical instances through the real pipeline (watch engine and
workers in this process) and prints the replay summary. Needs `docker compose up -d`,
migrations, the fixture agents loaded, and bars for the day (`atp bars synth`).

    uv run python scripts/burst.py --copies 1000 --workers 6 --date 2026-10-14
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import date

from atp import bus, obs
from atp.db.session import get_engine, session_factory
from atp.replay import run_replay
from atp.watch.engine import run_watch
from atp.worker.decision import DecisionWorker
from atp.worker.service import run_worker


async def main(args: argparse.Namespace) -> None:
    obs.setup("burst")
    logging.getLogger().setLevel("WARNING")
    nc, js = await bus.connect(name="atp-burst")
    await bus.ensure_streams(js)
    factory = session_factory()
    stop = asyncio.Event()
    tasks = [asyncio.create_task(run_watch(js, factory, get_engine(), stop))]
    tasks += [
        asyncio.create_task(run_worker(js, DecisionWorker(factory), concurrency=8, stop=stop))
        for _ in range(args.workers)
    ]
    try:
        summary = await run_replay(
            factory, js, args.agent, 1, date.fromisoformat(args.date), None, args.copies
        )
    finally:
        stop.set()
        await asyncio.gather(*tasks, return_exceptions=True)
        await nc.drain()
    out = {k: v for k, v in summary.__dict__.items() if k != "instance_ids"}
    print(json.dumps(out, default=str, indent=2))
    if summary.max_lag_s >= 300:
        raise SystemExit("FAIL: a bar took longer than one 5-minute bar to drain")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--copies", type=int, default=1000)
    p.add_argument("--workers", type=int, default=6)
    p.add_argument("--agent", default="test-rsi-fast")
    p.add_argument("--date", default="2026-10-14")
    asyncio.run(main(p.parse_args()))
