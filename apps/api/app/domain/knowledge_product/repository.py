from __future__ import annotations

import uuid
from typing import Protocol

from app.domain.knowledge_product.entities import KnowledgeProduct


class KnowledgeProductRepository(Protocol):
    """Port. Implemented in app/infrastructure/db/. Domain and application
    code depend only on this interface, never on SQLAlchemy directly."""

    async def get_by_id(self, product_id: uuid.UUID) -> KnowledgeProduct | None: ...

    async def get_by_key(self, product_key: str) -> KnowledgeProduct | None: ...

    async def list(
        self, *, status: str | None = None, search: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[KnowledgeProduct]: ...

    async def save(self, product: KnowledgeProduct) -> None: ...
