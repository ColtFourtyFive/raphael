"""AI filter via the LiteLLM gateway, with a request-hash cache for deterministic replay.

Only the market snapshot is sent: never credentials, account numbers, or balances.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal, Protocol

import httpx
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from atp.config import Settings, get_settings
from atp.db.models import LlmCache
from atp.schema.agent import AIFilter
from atp.schema.messages import WakeJob

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AIVerdict:
    verdict: Literal["TAKE", "SKIP"]
    reasoning: str
    request_hash: str
    raw_output: str | None
    cost_usd: Decimal
    cached: bool
    error: str | None = None


class ChatClient(Protocol):
    async def complete(self, request: dict[str, Any]) -> tuple[str, Decimal]: ...


class LiteLLMClient:
    """OpenAI-compatible /chat/completions on the LiteLLM proxy."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.s = settings or get_settings()

    async def complete(self, request: dict[str, Any]) -> tuple[str, Decimal]:
        headers = {}
        key = self.s.litellm_master_key.get_secret_value()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        async with httpx.AsyncClient(base_url=self.s.litellm_base_url, timeout=self.s.ai_timeout_s) as c:
            r = await c.post("/chat/completions", json=request, headers=headers)
            r.raise_for_status()
            body = r.json()
        text = str(body["choices"][0]["message"]["content"] or "")
        cost_hdr = r.headers.get("x-litellm-response-cost")
        if cost_hdr not in (None, "", "None"):
            cost = Decimal(cost_hdr)
        else:
            usage = body.get("usage") or {}
            cost = (
                Decimal(usage.get("prompt_tokens", 0)) * self.s.ai_input_usd_per_mtok
                + Decimal(usage.get("completion_tokens", 0)) * self.s.ai_output_usd_per_mtok
            ) / Decimal(1_000_000)
        return text, cost


def build_request(cfg: AIFilter, job: WakeJob, model: str) -> dict[str, Any]:
    snapshot = {
        "symbol": job.symbol,
        "bar_time": job.bar.ts.isoformat(),
        "price": {k: str(getattr(job.bar, k)) for k in ("open", "high", "low", "close", "volume")},
        "indicators": {
            k: (round(v, 4) if v is not None else None) for k, v in sorted(job.indicators.items())
        },
        "recent_closes": job.recent_closes[-20:],
        "signal": job.trigger,
    }
    return {
        "model": model,
        "temperature": 0,
        "max_tokens": 120,
        "messages": [
            {"role": "system", "content": cfg.prompt + "\nReply starting with TAKE or SKIP."},
            {"role": "user", "content": json.dumps(snapshot, sort_keys=True)},
        ],
    }


def request_hash(request: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def parse_verdict(text: str) -> Literal["TAKE", "SKIP"] | None:
    head = text.strip().upper()
    words = re.findall(r"[A-Z]+", head)
    if words and words[0] in ("TAKE", "SKIP") and (len(words) < 2 or words[1] != "OR"):
        return words[0]  # type: ignore[return-value]
    has_take, has_skip = "TAKE" in head, "SKIP" in head
    if has_take != has_skip:
        return "TAKE" if has_take else "SKIP"
    return None


class AIFilterRunner:
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        client: ChatClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._factory = factory
        self.s = settings or get_settings()
        self._client = client or LiteLLMClient(self.s)

    async def run(self, cfg: AIFilter, job: WakeJob) -> AIVerdict:
        model = self.s.ai_model_override or cfg.model
        req = build_request(cfg, job, model)
        h = request_hash(req)
        async with self._factory() as s:
            hit = await s.get(LlmCache, h)
        if hit is not None:
            return self._verdict(cfg, hit.response, h, Decimal(0), cached=True)
        started = time.monotonic()
        try:
            text, cost = await self._client.complete(req)
        except (httpx.HTTPError, KeyError, ValueError) as e:
            log.warning("AI filter call failed", extra={"error": str(e), "symbol": job.symbol})
            verdict: Literal["TAKE", "SKIP"] = "SKIP" if cfg.fail_mode == "skip" else "TAKE"
            return AIVerdict(
                verdict,
                f"AI unavailable ({type(e).__name__}); fail_mode={cfg.fail_mode}",
                h,
                None,
                Decimal(0),
                cached=False,
                error=str(e),
            )
        log.info(
            "AI filter call",
            extra={"latency_ms": int((time.monotonic() - started) * 1000), "cost_usd": str(cost)},
        )
        async with self._factory() as s, s.begin():
            await s.execute(
                insert(LlmCache)
                .values(request_hash=h, response=text, model=model, cost_usd=cost)
                .on_conflict_do_nothing()
            )
        return self._verdict(cfg, text, h, cost, cached=False)

    def _verdict(self, cfg: AIFilter, text: str, h: str, cost: Decimal, cached: bool) -> AIVerdict:
        v = parse_verdict(text)
        if v is None:
            v = "SKIP" if cfg.fail_mode == "skip" else "TAKE"
            reasoning = f"unparseable model output; fail_mode={cfg.fail_mode}"
        else:
            reasoning = text.strip()
        return AIVerdict(v, reasoning, h, text, cost, cached)
