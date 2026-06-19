from __future__ import annotations

import uuid
from typing import Protocol


class AuditPort(Protocol):
    """Port implemented in app/infrastructure/db/audit.py.
    Every governance-relevant mutation in the application layer writes
    through this port — append-only, never mutated, never deleted."""

    async def record(
        self,
        *,
        entity_type: str,
        entity_id: uuid.UUID,
        action: str,
        actor_id: uuid.UUID | None,
        diff: dict | None = None,
    ) -> None: ...
