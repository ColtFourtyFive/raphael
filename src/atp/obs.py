"""Structured JSON logging, alerts, and optional Sentry."""

from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

import httpx

from atp.config import get_settings

_RESERVED = set(logging.makeLogRecord({}).__dict__) | {"message", "asctime"}
alert_log = logging.getLogger("atp.alert")


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for k, v in record.__dict__.items():
            if k not in _RESERVED:
                out[k] = v
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def setup(service: str) -> None:
    s = get_settings()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(s.log_level)
    for noisy in ("httpx", "httpcore", "nats", "sqlalchemy.engine"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    if s.sentry_dsn:
        import sentry_sdk

        sentry_sdk.init(dsn=s.sentry_dsn, server_name=service, traces_sample_rate=0.0)


async def alert(kind: str, message: str, **detail: Any) -> None:
    """Alert = an ERROR log line with alert=true (CloudWatch metric filter) plus an optional webhook."""
    alert_log.error(message, extra={"alert": True, "alert_kind": kind, **detail})
    url = get_settings().alert_webhook_url
    if not url:
        return
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            await client.post(url, json={"text": f"[atp:{kind}] {message}", "detail": detail})
    except httpx.HTTPError:
        alert_log.exception("alert webhook failed")
