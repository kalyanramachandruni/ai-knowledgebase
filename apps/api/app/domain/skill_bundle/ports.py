from __future__ import annotations

from typing import Protocol

from app.domain.knowledge_product.entities import KnowledgeProduct


class SkillBundlePort(Protocol):
    """Extension point — NOT implemented in MVP.

    Future: package multiple published KnowledgeProducts plus their associated
    tools into a single deployable "skill" artifact an agent runtime can load.
    """

    async def bundle(self, products: list[KnowledgeProduct]) -> dict: ...
