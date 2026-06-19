from __future__ import annotations

import uuid
from typing import Protocol


class KnowledgeGraphPort(Protocol):
    """Extension point — NOT implemented in MVP.

    Future: model relationships between processes, roles, and tools across
    multiple Knowledge Products (e.g. shared roles, upstream/downstream processes).
    """

    async def link(self, source_product_id: uuid.UUID, target_product_id: uuid.UUID, relation: str) -> None: ...

    async def neighbors(self, product_id: uuid.UUID) -> list[uuid.UUID]: ...
