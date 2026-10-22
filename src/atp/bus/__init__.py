"""NATS JetStream layout (SPEC §5): streams, consumers, and publish helpers."""

from __future__ import annotations

import logging
from typing import Any

import nats
from nats.aio.client import Client as NATS
from nats.js import JetStreamContext
from nats.js.api import (
    AckPolicy,
    ConsumerConfig,
    DeliverPolicy,
    RetentionPolicy,
    StorageType,
    StreamConfig,
)
from nats.js.errors import NotFoundError
from pydantic import BaseModel

from atp.config import get_settings

log = logging.getLogger(__name__)

DAY = 24 * 3600

MD_SUBJECT = "md.bars.{symbol}"
WAKE_SUBJECT = "jobs.wake"
DLQ_SUBJECT = "jobs.dlq"

WATCH_CONSUMER = "watch"
WORKER_CONSUMER = "workers"


def stream_configs(replicas: int) -> list[StreamConfig]:
    return [
        StreamConfig(
            name="MD",
            subjects=["md.>"],
            retention=RetentionPolicy.LIMITS,
            max_age=7 * DAY,
            storage=StorageType.FILE,
            duplicate_window=120,
            num_replicas=replicas,
        ),
        StreamConfig(
            name="JOBS",
            subjects=[WAKE_SUBJECT],
            retention=RetentionPolicy.WORK_QUEUE,
            storage=StorageType.FILE,
            duplicate_window=600,  # SPEC: >= 2 min
            num_replicas=replicas,
        ),
        StreamConfig(
            name="JOBS_DLQ",
            subjects=[DLQ_SUBJECT],
            retention=RetentionPolicy.LIMITS,
            max_age=30 * DAY,
            storage=StorageType.FILE,
            num_replicas=replicas,
        ),
        StreamConfig(
            name="EVENTS",
            subjects=["events.>"],
            retention=RetentionPolicy.LIMITS,
            max_age=7 * DAY,
            storage=StorageType.FILE,
            num_replicas=replicas,
        ),
    ]


async def connect(url: str | None = None, name: str = "atp") -> tuple[NATS, JetStreamContext]:
    nc = await nats.connect(url or get_settings().nats_url, name=name, max_reconnect_attempts=-1)
    return nc, nc.jetstream()


async def ensure_streams(js: JetStreamContext, replicas: int | None = None) -> None:
    """Create or update every stream and durable consumer. Safe to call at every startup."""
    replicas = replicas or get_settings().nats_replicas
    for cfg in stream_configs(replicas):
        try:
            await js.stream_info(cfg.name)  # type: ignore[arg-type]
            await js.update_stream(cfg)
        except NotFoundError:
            await js.add_stream(cfg)
            log.info("created stream", extra={"stream": cfg.name})
    s = get_settings()
    await js.add_consumer(
        "MD",
        ConsumerConfig(
            durable_name=WATCH_CONSUMER,
            filter_subject="md.bars.>",
            ack_policy=AckPolicy.EXPLICIT,
            deliver_policy=DeliverPolicy.NEW,
            ack_wait=60,
            max_ack_pending=1000,
        ),
    )
    await js.add_consumer(
        "JOBS",
        ConsumerConfig(
            durable_name=WORKER_CONSUMER,
            ack_policy=AckPolicy.EXPLICIT,
            ack_wait=s.worker_ack_wait_s,
            max_deliver=s.worker_max_deliver,
            max_ack_pending=10_000,
        ),
    )


async def publish_model(
    js: JetStreamContext, subject: str, model: BaseModel, msg_id: str | None = None
) -> Any:
    headers = {"Nats-Msg-Id": msg_id} if msg_id else None
    return await js.publish(subject, model.model_dump_json().encode(), headers=headers)


async def consumer_backlog(js: JetStreamContext, stream: str, durable: str) -> int:
    """Messages not yet delivered plus delivered-but-unacked."""
    info = await js.consumer_info(stream, durable)
    return int(info.num_pending or 0) + int(info.num_ack_pending or 0)
