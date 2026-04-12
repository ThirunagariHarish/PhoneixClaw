"""
Resolve which connector UUIDs power the agent Feed (channel_messages).

Ingestion persists Discord messages to ``channel_messages`` and publishes Redis
``stream:channel:{connector_id}``; live agents consume Redis. The Feed API reads
the same ``channel_messages`` rows — this module unions ``connector_agents`` with
``agent.config["connector_ids"]`` and self-heals missing ``ConnectorAgent`` rows
when the connector still exists.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from shared.db.models.agent import Agent
from shared.db.models.connector import Connector, ConnectorAgent

logger = logging.getLogger(__name__)


def parse_connector_ids_from_config(config: dict | None) -> set[uuid.UUID]:
    """Return valid UUIDs from ``config[\"connector_ids\"]`` (strings or UUIDs)."""
    out: set[uuid.UUID] = set()
    if not config:
        return out
    raw = config.get("connector_ids", [])
    if not isinstance(raw, list):
        return out
    for item in raw:
        try:
            uid = item if isinstance(item, uuid.UUID) else uuid.UUID(str(item))
            out.add(uid)
        except (ValueError, TypeError):
            continue
    return out


async def resolve_agent_connector_ids_for_feed(
    session: AsyncSession,
    agent_id: uuid.UUID,
) -> list[uuid.UUID]:
    """Active connector IDs for Feed/backfill: union DB links + config; repair missing links."""
    agent = (await session.execute(select(Agent).where(Agent.id == agent_id))).scalar_one_or_none()
    if not agent:
        return []

    sub_q = select(ConnectorAgent.connector_id).where(
        ConnectorAgent.agent_id == agent_id,
        ConnectorAgent.is_active.is_(True),
    )
    from_active = {row[0] for row in (await session.execute(sub_q)).all()}
    config_ids = parse_connector_ids_from_config(agent.config)

    if config_ids:
        for cid in config_ids:
            if cid in from_active:
                continue
            conn_exists = (
                await session.execute(select(Connector.id).where(Connector.id == cid))
            ).scalar_one_or_none()
            if not conn_exists:
                logger.debug(
                    "[feed_connectors] agent %s config lists connector %s but no Connector row; skip repair",
                    agent_id,
                    cid,
                )
                continue
            existing = (
                await session.execute(
                    select(ConnectorAgent).where(
                        ConnectorAgent.agent_id == agent_id,
                        ConnectorAgent.connector_id == cid,
                    )
                )
            ).scalar_one_or_none()
            if existing:
                if not existing.is_active:
                    existing.is_active = True
            else:
                session.add(
                    ConnectorAgent(
                        id=uuid.uuid4(),
                        connector_id=cid,
                        agent_id=agent_id,
                        channel="*",
                        is_active=True,
                    )
                )
        await session.flush()
        sub_q2 = select(ConnectorAgent.connector_id).where(
            ConnectorAgent.agent_id == agent_id,
            ConnectorAgent.is_active.is_(True),
        )
        from_active = {row[0] for row in (await session.execute(sub_q2)).all()}

    merged = from_active | config_ids
    return sorted(merged, key=lambda u: str(u))
