"""Postgres tables (SPEC §6).

Additions beyond the SPEC table list, each needed by a SPEC behaviour:
- `instances.run_id`: separates replay runs from paper/live records.
- `decisions.symbol` + unique (instance_id, symbol, bar_ts): one decision per wake, so a
  redelivered job never decides twice.
- `system_flags`: the global kill switch.
- `paper_*`: the PaperBroker's own books. It is a separate "broker", so reconciliation
  compares two independent records exactly as it does for Alpaca.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

Money = Numeric(20, 8)


class Base(DeclarativeBase):
    type_annotation_map = {
        dict[str, Any]: JSONB,
        list[Any]: JSONB,
        datetime: DateTime(timezone=True),
        Decimal: Money,
        uuid.UUID: UUID(as_uuid=True),
    }


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Agent(Base):
    __tablename__ = "agents"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class AgentVersion(Base):
    __tablename__ = "agent_versions"
    agent_id: Mapped[str] = mapped_column(ForeignKey("agents.id"), primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    definition_json: Mapped[dict[str, Any]]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class BrokerAccount(Base):
    __tablename__ = "broker_accounts"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    broker: Mapped[str] = mapped_column(String(32))  # paper | alpaca
    encrypted_credentials: Mapped[bytes | None] = mapped_column(LargeBinary)
    is_live: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Instance(Base):
    __tablename__ = "instances"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    agent_id: Mapped[str] = mapped_column(String(64))
    version: Mapped[int]
    mode: Mapped[str] = mapped_column(String(16))  # replay|paper|alpaca_paper|alpaca_live
    status: Mapped[str] = mapped_column(String(16), default="paused")  # running|paused|killed|completed
    account_ref: Mapped[uuid.UUID] = mapped_column(ForeignKey("broker_accounts.id"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    status_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        ForeignKeyConstraint(["agent_id", "version"], ["agent_versions.agent_id", "agent_versions.version"]),
        Index("ix_instances_status", "status"),
    )


class BarRow(Base):
    __tablename__ = "bars"
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    timeframe: Mapped[str] = mapped_column(String(8), primary_key=True)
    ts: Mapped[datetime] = mapped_column(primary_key=True)
    open: Mapped[Decimal]
    high: Mapped[Decimal]
    low: Mapped[Decimal]
    close: Mapped[Decimal]
    volume: Mapped[Decimal]
    source: Mapped[str] = mapped_column(String(16), default="alpaca")


class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    instance_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("instances.id"))
    symbol: Mapped[str] = mapped_column(String(16))
    bar_ts: Mapped[datetime]
    inputs_json: Mapped[dict[str, Any]]
    rule_result: Mapped[dict[str, Any]]
    model_request_hash: Mapped[str | None] = mapped_column(String(64))
    model_output: Mapped[str | None] = mapped_column(Text)
    reasoning: Mapped[str | None] = mapped_column(Text)
    action: Mapped[str] = mapped_column(String(16))  # buy|sell|hold|skip|blocked|pending
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[Decimal] = mapped_column(default=Decimal(0))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    __table_args__ = (
        UniqueConstraint("instance_id", "symbol", "bar_ts", name="uq_decisions_wake"),
        Index("ix_decisions_instance_created", "instance_id", "created_at"),
    )


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    client_order_id: Mapped[str] = mapped_column(String(128), unique=True)
    instance_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("instances.id"), index=True)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("decisions.id"))
    symbol: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(4))
    qty: Mapped[Decimal | None]
    notional: Mapped[Decimal | None]
    type: Mapped[str] = mapped_column(String(16))  # market|limit|stop
    limit_price: Mapped[Decimal | None]
    stop_price: Mapped[Decimal | None]
    state: Mapped[str] = mapped_column(String(20), index=True)
    broker_order_id: Mapped[str | None] = mapped_column(String(64))
    filled_qty: Mapped[Decimal] = mapped_column(default=Decimal(0))
    filled_avg_price: Mapped[Decimal | None]
    reject_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime]
    updated_at: Mapped[datetime]


class OrderEvent(Base):
    __tablename__ = "order_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    from_state: Mapped[str | None] = mapped_column(String(20))
    to_state: Mapped[str] = mapped_column(String(20))
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    ts: Mapped[datetime]


class Fill(Base):
    __tablename__ = "fills"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    order_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("orders.id"), index=True)
    qty: Mapped[Decimal]
    price: Mapped[Decimal]
    fee: Mapped[Decimal] = mapped_column(default=Decimal(0))
    ts: Mapped[datetime]
    broker_fill_id: Mapped[str] = mapped_column(String(128), unique=True)


class Position(Base):
    __tablename__ = "positions"
    instance_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("instances.id"), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    qty: Mapped[Decimal]
    avg_price: Mapped[Decimal]
    updated_at: Mapped[datetime]


class LedgerEntry(Base):
    __tablename__ = "ledger_entries"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instance_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("instances.id"), index=True)
    account: Mapped[str] = mapped_column(String(32))  # cash|position:SYM|fees|realized_pnl|equity
    amount: Mapped[Decimal]
    ref: Mapped[str] = mapped_column(String(128))
    ts: Mapped[datetime]


class RiskEvent(Base):
    __tablename__ = "risk_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instance_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("instances.id"), index=True)
    decision_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("decisions.id"))
    rule: Mapped[str] = mapped_column(String(32))
    outcome: Mapped[str] = mapped_column(String(16))  # pass|block|hold
    detail: Mapped[str] = mapped_column(Text, default="")
    ts: Mapped[datetime] = mapped_column(server_default=func.now())


class ReconciliationRun(Base):
    __tablename__ = "reconciliation_runs"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    instance_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("instances.id"), index=True)
    ts: Mapped[datetime] = mapped_column(server_default=func.now())
    status: Mapped[str] = mapped_column(String(16))  # clean|mismatch|error
    diffs_json: Mapped[dict[str, Any]] = mapped_column(default=dict)


class LlmCache(Base):
    __tablename__ = "llm_cache"
    request_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    response: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(String(64))
    cost_usd: Mapped[Decimal] = mapped_column(default=Decimal(0))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SystemFlag(Base):
    __tablename__ = "system_flags"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


# --- PaperBroker's own books (the "broker side" for paper and replay) ---


class PaperAccount(Base):
    __tablename__ = "paper_accounts"
    account_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(index=True)
    cash: Mapped[Decimal]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class PaperOrder(Base):
    __tablename__ = "paper_orders"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=_uuid)
    account_ref: Mapped[str] = mapped_column(String(64), index=True)
    run_id: Mapped[uuid.UUID | None]
    client_order_id: Mapped[str] = mapped_column(String(128), unique=True)
    symbol: Mapped[str] = mapped_column(String(16))
    side: Mapped[str] = mapped_column(String(4))
    qty: Mapped[Decimal | None]
    notional: Mapped[Decimal | None]
    type: Mapped[str] = mapped_column(String(16))
    limit_price: Mapped[Decimal | None]
    stop_price: Mapped[Decimal | None]
    status: Mapped[str] = mapped_column(String(20))  # accepted|filled|canceled|rejected
    filled_qty: Mapped[Decimal] = mapped_column(default=Decimal(0))
    filled_avg_price: Mapped[Decimal | None]
    fee: Mapped[Decimal] = mapped_column(default=Decimal(0))
    submitted_at: Mapped[datetime]
    filled_at: Mapped[datetime | None]
    reject_reason: Mapped[str | None] = mapped_column(Text)
    __table_args__ = (Index("ix_paper_orders_open", "symbol", "status", "run_id"),)


class PaperPosition(Base):
    __tablename__ = "paper_positions"
    account_ref: Mapped[str] = mapped_column(String(64), primary_key=True)
    symbol: Mapped[str] = mapped_column(String(16), primary_key=True)
    qty: Mapped[Decimal]
    avg_price: Mapped[Decimal]
