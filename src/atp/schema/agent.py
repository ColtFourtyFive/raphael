"""Agent definition (SPEC §4). An agent is data: this model is the whole contract."""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Op = Literal["<", "<=", ">", ">=", "==", "!="]
Timeframe = Literal["1Min", "5Min", "15Min", "1Hour"]
PRICE_FIELDS = ("open", "high", "low", "close", "volume")

TIMEFRAME_SECONDS: dict[str, int] = {"1Min": 60, "5Min": 300, "15Min": 900, "1Hour": 3600}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class IndicatorSpec(_Strict):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    type: Literal["SMA", "EMA", "RSI"]
    period: int = Field(ge=2, le=500)


class Comparison(_Strict):
    """`lhs op rhs` where each side is an indicator id, a price field, or a number."""

    lhs: str | float
    op: Op
    rhs: str | float


class StopLossPct(_Strict):
    type: Literal["stop_loss_pct"]
    value: float = Field(gt=0, lt=100)


class TakeProfitPct(_Strict):
    type: Literal["take_profit_pct"]
    value: float = Field(gt=0, le=1000)


ExitCondition = Annotated[StopLossPct | TakeProfitPct, Field(discriminator="type")]
Condition = Comparison | ExitCondition


class AllOf(_Strict):
    all: list[Comparison] = Field(min_length=1)


class AnyOf(_Strict):
    any: list[Comparison | ExitCondition] = Field(min_length=1)


class Schedule(_Strict):
    timeframe: Timeframe
    session: Literal["regular"] = "regular"


class FixedNotional(_Strict):
    type: Literal["fixed_notional"]
    usd: Decimal = Field(gt=0)


class AIFilter(_Strict):
    model: str
    prompt: str = Field(min_length=1)
    fail_mode: Literal["skip", "take"] = "skip"


class Guardrails(_Strict):
    max_position_usd: Decimal = Field(gt=0)
    max_open_positions: int = Field(ge=1)
    max_daily_loss_usd: Decimal = Field(gt=0)
    approval_mode: Literal["auto", "manual"] = "auto"


class AgentDefinition(_Strict):
    agent_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    version: int = Field(ge=1)
    name: str
    universe: list[str] = Field(min_length=1, max_length=100)
    schedule: Schedule
    indicators: list[IndicatorSpec]
    entry: AllOf
    exit: AnyOf
    sizing: FixedNotional
    ai_filter: AIFilter | None = None
    guardrails: Guardrails

    @model_validator(mode="after")
    def _check_refs(self) -> AgentDefinition:
        ids = [i.id for i in self.indicators]
        if len(set(ids)) != len(ids):
            raise ValueError("indicator ids must be unique")
        clash = set(ids) & set(PRICE_FIELDS)
        if clash:
            raise ValueError(f"indicator ids clash with price fields: {sorted(clash)}")
        known = set(ids) | set(PRICE_FIELDS)
        comparisons = list(self.entry.all) + [c for c in self.exit.any if isinstance(c, Comparison)]
        for c in comparisons:
            for side in (c.lhs, c.rhs):
                if isinstance(side, str) and side not in known:
                    raise ValueError(f"unknown operand {side!r}; expected one of {sorted(known)}")
        if any(s != s.upper() or not s.isalnum() for s in self.universe):
            raise ValueError("universe symbols must be uppercase alphanumeric tickers")
        if self.sizing.usd > self.guardrails.max_position_usd:
            raise ValueError("sizing.usd exceeds guardrails.max_position_usd")
        return self

    @property
    def timeframe_seconds(self) -> int:
        return TIMEFRAME_SECONDS[self.schedule.timeframe]

    @property
    def max_period(self) -> int:
        return max((i.period for i in self.indicators), default=1)
