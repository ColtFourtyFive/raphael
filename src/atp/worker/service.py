"""Decision worker process: pull consumer on `jobs.wake` with explicit ack, NAK + backoff,
and our own dead-letter queue after max deliveries (NATS has none built in)."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from nats.errors import TimeoutError as NatsTimeout
from nats.js import JetStreamContext
from pydantic import ValidationError

from atp import bus
from atp.brokers.base import BrokerAuthError
from atp.config import get_settings
from atp.obs import alert
from atp.schema.messages import WakeJob
from atp.worker.decision import DecisionWorker, TerminalJobError

log = logging.getLogger(__name__)


async def _dead_letter(js: JetStreamContext, msg: Any, reason: str) -> None:
    md = msg.metadata
    payload = {
        "reason": reason,
        "num_delivered": md.num_delivered,
        "stream_seq": md.sequence.stream,
        "data": msg.data.decode(errors="replace"),
    }
    await js.publish(bus.DLQ_SUBJECT, json.dumps(payload).encode())
    await msg.term()
    await alert("dlq", "wake job dead-lettered", reason=reason, stream_seq=md.sequence.stream)


async def handle_message(js: JetStreamContext, worker: DecisionWorker, msg: Any) -> None:
    s = get_settings()
    try:
        job = WakeJob.model_validate_json(msg.data)
    except ValidationError as e:
        await _dead_letter(js, msg, f"invalid payload: {e.error_count()} errors")
        return
    try:
        outcome = await worker.handle(job)
    except TerminalJobError as e:
        await _dead_letter(js, msg, str(e))
        return
    except asyncio.CancelledError:
        raise
    except Exception as e:
        delivered = msg.metadata.num_delivered
        if isinstance(e, BrokerAuthError):
            await alert(
                "broker_auth",
                "broker credentials rejected; instance paused",
                instance_id=str(job.instance_id),
            )
        if delivered >= s.worker_max_deliver:
            await _dead_letter(js, msg, f"max deliveries: {type(e).__name__}: {e}")
            return
        delay = min(2**delivered, 30)
        log.warning(
            "job failed, NAK with backoff",
            exc_info=True,
            extra={"msg_id": job.msg_id, "delivered": delivered, "delay_s": delay},
        )
        await msg.nak(delay=delay)
        return
    await msg.ack()  # only after the decision is committed
    log.info(
        "decision",
        extra={
            "msg_id": job.msg_id,
            "action": outcome.action,
            "resumed": outcome.resumed,
            "run_id": str(job.run_id) if job.run_id else None,
        },
    )


async def run_worker(
    js: JetStreamContext,
    worker: DecisionWorker,
    *,
    concurrency: int = 16,
    stop: asyncio.Event | None = None,
) -> None:
    stop = stop or asyncio.Event()
    sub = await js.pull_subscribe(bus.WAKE_SUBJECT, durable=bus.WORKER_CONSUMER, stream="JOBS")
    sem = asyncio.Semaphore(concurrency)
    tasks: set[asyncio.Task[None]] = set()

    async def run_one(m: Any) -> None:
        async with sem:
            await handle_message(js, worker, m)

    log.info("worker started", extra={"concurrency": concurrency})
    try:
        while not stop.is_set():
            try:
                msgs = await sub.fetch(batch=concurrency, timeout=1)
            except NatsTimeout:
                continue
            for m in msgs:
                t = asyncio.create_task(run_one(m))
                tasks.add(t)
                t.add_done_callback(tasks.discard)
            while len(tasks) >= concurrency * 2:
                await asyncio.sleep(0.01)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await sub.unsubscribe()
