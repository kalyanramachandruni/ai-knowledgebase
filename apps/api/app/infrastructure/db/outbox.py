from __future__ import annotations

import dataclasses
import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.shared.base import DomainEvent
from app.infrastructure.db.models import EventOutbox


def _default(value: object) -> object:
    if isinstance(value, uuid.UUID):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    raise TypeError(f"Cannot serialize {value!r} to the event outbox")


class SqlAlchemyEventOutbox:
    """Implements app.domain.shared.event_bus.EventPublisherPort via the
    transactional outbox pattern: events are written to event_outbox in the
    same DB transaction as the state change. A separate dispatcher process
    (not built in MVP) would poll processed_at IS NULL and publish externally."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def publish(self, event: DomainEvent) -> None:
        payload = {k: v for k, v in dataclasses.asdict(event).items()}
        self._session.add(
            EventOutbox(
                event_type=type(event).__name__,
                payload=json.loads(json.dumps(payload, default=_default)),
            )
        )
        await self._session.flush()
