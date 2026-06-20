from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import AuditEntry


class SqlAlchemyAuditLog:
    """Implements app.domain.governance.ports.AuditPort."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        *,
        entity_type: str,
        entity_id: uuid.UUID,
        action: str,
        actor_id: uuid.UUID | None,
        diff: dict | None = None,
    ) -> None:
        self._session.add(
            AuditEntry(
                entity_type=entity_type,
                entity_id=entity_id,
                action=action,
                actor_id=actor_id,
                diff=diff,
            )
        )
        await self._session.flush()
        await self._session.commit()
