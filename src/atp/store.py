"""Small data-access helpers shared by services."""

from __future__ import annotations

import uuid
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from atp.db.models import Agent, AgentVersion, Instance, SystemFlag
from atp.schema.agent import AgentDefinition

KILL_SWITCH = "kill_switch"


@lru_cache(maxsize=1024)
def _parse(raw: str) -> AgentDefinition:
    return AgentDefinition.model_validate_json(raw)


async def load_definition(session: AsyncSession, agent_id: str, version: int) -> AgentDefinition:
    """Agent versions are immutable, so parsed definitions are cached forever."""
    row = await session.get(AgentVersion, (agent_id, version))
    if row is None:
        raise LookupError(f"agent version {agent_id}@{version} not found")
    import json

    return _parse(json.dumps(row.definition_json, sort_keys=True))


async def save_definition(session: AsyncSession, defn: AgentDefinition) -> bool:
    """Insert an agent version. Returns False if that exact version already exists.

    Raises if the version exists with a different definition (versions are immutable).
    """
    payload: dict[str, Any] = defn.model_dump(mode="json")
    await session.execute(insert(Agent).values(id=defn.agent_id, name=defn.name).on_conflict_do_nothing())
    existing = await session.get(AgentVersion, (defn.agent_id, defn.version))
    if existing is not None:
        if existing.definition_json != payload:
            raise ValueError(
                f"{defn.agent_id}@{defn.version} already exists with a different definition; bump the version"
            )
        return False
    session.add(AgentVersion(agent_id=defn.agent_id, version=defn.version, definition_json=payload))
    return True


async def kill_switch_on(session: AsyncSession) -> bool:
    flag = await session.get(SystemFlag, KILL_SWITCH)
    return flag is not None and flag.value == "on"


async def set_kill_switch(session: AsyncSession, on: bool) -> None:
    value = "on" if on else "off"
    await session.execute(
        insert(SystemFlag)
        .values(key=KILL_SWITCH, value=value)
        .on_conflict_do_update(index_elements=["key"], set_={"value": value})
    )


async def set_instance_status(
    session: AsyncSession, instance_id: uuid.UUID, status: str, reason: str | None = None
) -> Instance:
    inst = await session.get(Instance, instance_id, with_for_update=True)
    if inst is None:
        raise LookupError(f"instance {instance_id} not found")
    if inst.status == "killed" and status == "running":
        raise ValueError("a killed instance cannot be restarted; create a new instance")
    inst.status = status
    inst.status_reason = reason
    return inst


async def running_instances(session: AsyncSession, run_id: uuid.UUID | None) -> list[Instance]:
    q = select(Instance).where(Instance.status == "running")
    q = q.where(Instance.run_id.is_(None) if run_id is None else Instance.run_id == run_id)
    return list(await session.scalars(q))
