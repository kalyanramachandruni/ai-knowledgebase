from __future__ import annotations

import uuid

from app.application.context_package.generator import ContextPackageGenerator
from app.application.knowledge_product.exceptions import (
    KnowledgeProductNotFound,
    KnowledgeProductVersionNotFound,
    KnowledgeProductVersionNotPublished,
)
from app.domain.context_package.ports import ContextPackageCachePort
from app.domain.knowledge_product.repository import KnowledgeProductRepository
from app.domain.knowledge_product.value_objects import KnowledgeProductStatus

_CACHE_TTL_SECONDS = 300


class GetContextPackageUseCase:
    """Serves Capability 6 at request time. Only PUBLISHED versions may be
    exported as an Agent Context Package — agents must never consume a
    draft, in-review, or retired process. Results are cached because the
    underlying data only changes on publish, which is comparatively rare."""

    def __init__(
        self,
        repository: KnowledgeProductRepository,
        cache: ContextPackageCachePort,
        generator: ContextPackageGenerator,
    ) -> None:
        self._repository = repository
        self._cache = cache
        self._generator = generator

    async def execute(self, product_id: uuid.UUID, version_id: uuid.UUID | None = None) -> dict:
        cache_key = f"context:{product_id}:{version_id or 'current'}"
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached

        product = await self._repository.get_by_id(product_id)
        if product is None:
            raise KnowledgeProductNotFound(f"Knowledge Product {product_id} not found")

        if version_id is None:
            version = product.current_version
        else:
            version = next((v for v in product.versions if v.id == version_id), None)
            if version is None:
                raise KnowledgeProductVersionNotFound(f"Version {version_id} not found on product {product_id}")

        if version.status is not KnowledgeProductStatus.PUBLISHED:
            raise KnowledgeProductVersionNotPublished(
                f"Version {version.semver} of {product.product_key} is {version.status.value}, not published"
            )

        package = self._generator.build(product_key=product.product_key, version=version)
        await self._cache.set(cache_key, package, _CACHE_TTL_SECONDS)
        return package
