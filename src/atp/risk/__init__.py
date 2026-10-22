"""Risk engine (SPEC §7): pure functions over a context snapshot. No I/O here.

Guardrails live outside the agent: the worker gathers the facts, this module judges.
Exits (sells that only reduce a long position) skip the exposure checks (4-7) but are
still stopped by instance status, the kill switch, market hours, and open-order conflicts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

from atp.marketdata.base import in_regular_session
from atp.schema.agent import Guardrails

Outcome = Literal["pass", "block", "hold"]


@dataclass(frozen=True)
class RiskContext:
    instance_status: str
    kill_switch: bool
    now: datetime
    side: Literal["buy", "sell"]
    symbol: str
    order_notional: Decimal
    position_value: Decimal  # current value of this symbol's position
    open_positions: int  # symbols with a non-zero position
    holds_symbol: bool
    daily_pnl: Decimal  # realized today, net of fees; negative is a loss
    buying_power: Decimal
    open_orders_for_symbol: int
    guardrails: Guardrails


@dataclass(frozen=True)
class RuleCheck:
    rule: str
    outcome: Outcome
    detail: str


@dataclass(frozen=True)
class RiskDecision:
    outcome: Literal["approve", "block", "hold"]
    checks: list[RuleCheck] = field(default_factory=list)

    @property
    def reasons(self) -> list[str]:
        return [f"{c.rule}: {c.detail}" for c in self.checks if c.outcome != "pass"]


def _check(rule: str, ok: bool, detail: str) -> RuleCheck:
    return RuleCheck(rule, "pass" if ok else "block", detail)


def evaluate(ctx: RiskContext) -> RiskDecision:
    g = ctx.guardrails
    entry = ctx.side == "buy"
    checks = [
        _check("instance_status", ctx.instance_status == "running", f"status={ctx.instance_status}"),
        _check("kill_switch", not ctx.kill_switch, "global kill switch on" if ctx.kill_switch else "off"),
        _check("market_hours", in_regular_session(ctx.now), f"at {ctx.now.isoformat()}"),
    ]
    if entry:
        after = ctx.position_value + ctx.order_notional
        checks += [
            _check("max_position", after <= g.max_position_usd, f"{after:.2f} vs max {g.max_position_usd}"),
            _check(
                "max_open_positions",
                ctx.holds_symbol or ctx.open_positions < g.max_open_positions,
                f"{ctx.open_positions} open vs max {g.max_open_positions}",
            ),
            _check(
                "max_daily_loss",
                ctx.daily_pnl > -g.max_daily_loss_usd,
                f"today {ctx.daily_pnl:.2f} vs limit -{g.max_daily_loss_usd}",
            ),
            _check(
                "buying_power",
                ctx.order_notional <= ctx.buying_power,
                f"need {ctx.order_notional:.2f}, have {ctx.buying_power:.2f}",
            ),
        ]
    checks.append(
        _check(
            "open_order_conflict",
            ctx.open_orders_for_symbol == 0,
            f"{ctx.open_orders_for_symbol} open order(s) for {ctx.symbol}",
        )
    )
    if any(c.outcome == "block" for c in checks):
        return RiskDecision("block", checks)
    if g.approval_mode == "manual":
        return RiskDecision("hold", [*checks, RuleCheck("approval_mode", "hold", "manual approval required")])
    return RiskDecision("approve", checks)
