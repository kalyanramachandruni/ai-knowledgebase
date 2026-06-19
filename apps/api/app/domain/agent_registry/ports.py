from __future__ import annotations

import uuid
from typing import Protocol


class AgentRegistryPort(Protocol):
    """Extension point — NOT implemented in MVP.

    Future: catalog of deployed agents and which Knowledge Products / Skill
    Bundles each agent consumes, for impact analysis when a product changes.
    """

    async def register_agent(self, name: str, consumed_product_ids: list[uuid.UUID]) -> uuid.UUID: ...

    async def consumers_of(self, product_id: uuid.UUID) -> list[uuid.UUID]: ...
