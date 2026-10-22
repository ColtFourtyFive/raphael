from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from atp.risk import RiskContext, evaluate
from atp.schema.agent import Guardrails

G = Guardrails(max_position_usd=Decimal(500), max_open_positions=3, max_daily_loss_usd=Decimal(50))
OPEN = datetime(2026, 10, 14, 15, 0, tzinfo=UTC)  # 11:00 New York

BASE = RiskContext(
    instance_status="running", kill_switch=False, now=OPEN, side="buy", symbol="SPY",
    order_notional=Decimal(200), position_value=Decimal(0), open_positions=0, holds_symbol=False,
    daily_pnl=Decimal(0), buying_power=Decimal(10_000), open_orders_for_symbol=0, guardrails=G,
)


def blocked_rules(ctx: RiskContext) -> set[str]:
    return {c.rule for c in evaluate(ctx).checks if c.outcome == "block"}


def test_all_clear_approves() -> None:
    d = evaluate(BASE)
    assert d.outcome == "approve" and not blocked_rules(BASE)


@pytest.mark.parametrize(
    ("change", "rule"),
    [
        ({"instance_status": "paused"}, "instance_status"),
        ({"instance_status": "killed"}, "instance_status"),
        ({"kill_switch": True}, "kill_switch"),
        ({"now": datetime(2026, 10, 14, 20, 0, tzinfo=UTC)}, "market_hours"),  # 16:00 NY
        ({"now": datetime(2026, 10, 17, 15, 0, tzinfo=UTC)}, "market_hours"),  # Saturday
        ({"position_value": Decimal(400)}, "max_position"),
        ({"open_positions": 3}, "max_open_positions"),
        ({"daily_pnl": Decimal(-50)}, "max_daily_loss"),
        ({"buying_power": Decimal(199)}, "buying_power"),
        ({"open_orders_for_symbol": 1}, "open_order_conflict"),
    ],
)
def test_each_rule_blocks(change: dict[str, object], rule: str) -> None:
    ctx = replace(BASE, **change)  # type: ignore[arg-type]
    d = evaluate(ctx)
    assert d.outcome == "block"
    assert blocked_rules(ctx) == {rule}


def test_adding_to_held_symbol_not_counted_as_new_position() -> None:
    assert evaluate(replace(BASE, open_positions=3, holds_symbol=True, position_value=Decimal(100))).outcome == "approve"


def test_exits_skip_exposure_checks_but_not_kill_switch() -> None:
    sell = replace(BASE, side="sell", daily_pnl=Decimal(-500), buying_power=Decimal(0), open_positions=9)
    assert evaluate(sell).outcome == "approve"
    assert evaluate(replace(sell, kill_switch=True)).outcome == "block"


def test_manual_mode_holds() -> None:
    ctx = replace(BASE, guardrails=G.model_copy(update={"approval_mode": "manual"}))
    assert evaluate(ctx).outcome == "hold"
    assert evaluate(replace(ctx, kill_switch=True)).outcome == "block"
