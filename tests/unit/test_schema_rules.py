import json
from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from atp.rules import evaluate_entry, evaluate_exit
from atp.schema.agent import AgentDefinition

ROOT = Path(__file__).parents[2]


def load(name: str) -> AgentDefinition:
    return AgentDefinition.model_validate(json.loads((ROOT / "agents/examples" / name).read_text()))


def test_examples_validate() -> None:
    basic = load("rsi-ma-basic.json")
    ai = load("rsi-ma-ai-filter.json")
    assert basic.ai_filter is None and ai.ai_filter is not None
    assert basic.timeframe_seconds == 300
    for p in (ROOT / "tests/fixtures").glob("*.json"):
        AgentDefinition.model_validate(json.loads(p.read_text()))


def test_unknown_operand_rejected() -> None:
    raw = json.loads((ROOT / "agents/examples/rsi-ma-basic.json").read_text())
    raw["entry"]["all"][0]["lhs"] = "rsi99"
    with pytest.raises(ValidationError, match="unknown operand"):
        AgentDefinition.model_validate(raw)


def test_sizing_cannot_exceed_guardrail() -> None:
    raw = json.loads((ROOT / "agents/examples/rsi-ma-basic.json").read_text())
    raw["sizing"]["usd"] = 1000
    with pytest.raises(ValidationError, match="max_position_usd"):
        AgentDefinition.model_validate(raw)


def test_extra_fields_rejected() -> None:
    raw = json.loads((ROOT / "agents/examples/rsi-ma-basic.json").read_text())
    raw["guardrails"]["disable_kill_switch"] = True
    with pytest.raises(ValidationError):
        AgentDefinition.model_validate(raw)


def test_entry_all_and_warmup() -> None:
    d = load("rsi-ma-basic.json")
    assert evaluate_entry(d, {"rsi14": 25, "sma50": 99, "close": 100}).fired
    assert not evaluate_entry(d, {"rsi14": 25, "sma50": 101, "close": 100}).fired
    r = evaluate_entry(d, {"rsi14": None, "sma50": 99, "close": 100})
    assert not r.fired and "warming up" in r.detail[0]


def test_exit_any_including_stops() -> None:
    d = load("rsi-ma-basic.json")
    avg = Decimal(100)
    assert evaluate_exit(d, {"rsi14": 65, "close": 100}, avg).fired
    assert not evaluate_exit(d, {"rsi14": 50, "close": 100}, avg).fired
    assert evaluate_exit(d, {"rsi14": 50, "close": 98.99}, avg).fired  # stop -1%
    assert evaluate_exit(d, {"rsi14": 50, "close": 102.0}, avg).fired  # take profit +2%
    assert not evaluate_exit(d, {"rsi14": 50, "close": 101.9}, avg).fired
