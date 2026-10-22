"""Condition evaluation, shared by the watch engine (to wake) and the worker (to decide)."""

from __future__ import annotations

import operator
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal

from atp.schema.agent import AgentDefinition, Comparison, StopLossPct, TakeProfitPct

_OPS: dict[str, Callable[[float, float], bool]] = {
    "<": operator.lt,
    "<=": operator.le,
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
}


@dataclass(frozen=True)
class RuleResult:
    fired: bool
    detail: list[str]


def _operand(side: str | float, values: Mapping[str, float | None]) -> float | None:
    if isinstance(side, str):
        return values.get(side)
    return float(side)


def _compare(c: Comparison, values: Mapping[str, float | None]) -> tuple[bool, str]:
    lhs = _operand(c.lhs, values)
    rhs = _operand(c.rhs, values)
    if lhs is None or rhs is None:
        return False, f"{c.lhs} {c.op} {c.rhs}: n/a (warming up)"
    ok = _OPS[c.op](lhs, rhs)
    return ok, f"{c.lhs}={lhs:.4f} {c.op} {c.rhs}={rhs:.4f}: {ok}"


def evaluate_entry(defn: AgentDefinition, values: Mapping[str, float | None]) -> RuleResult:
    detail: list[str] = []
    fired = True
    for c in defn.entry.all:
        ok, line = _compare(c, values)
        detail.append(line)
        fired = fired and ok
    return RuleResult(fired, detail)


def evaluate_exit(
    defn: AgentDefinition,
    values: Mapping[str, float | None],
    avg_price: Decimal,
) -> RuleResult:
    detail: list[str] = []
    fired = False
    close = values.get("close")
    for c in defn.exit.any:
        if isinstance(c, Comparison):
            ok, line = _compare(c, values)
        elif close is None or avg_price <= 0:
            ok, line = False, f"{c.type}: n/a"
        elif isinstance(c, StopLossPct):
            change = (close / float(avg_price) - 1) * 100
            ok = change <= -c.value
            line = f"stop_loss {change:.3f}% <= -{c.value}%: {ok}"
        elif isinstance(c, TakeProfitPct):
            change = (close / float(avg_price) - 1) * 100
            ok = change >= c.value
            line = f"take_profit {change:.3f}% >= {c.value}%: {ok}"
        detail.append(line)
        fired = fired or ok
    return RuleResult(fired, detail)
