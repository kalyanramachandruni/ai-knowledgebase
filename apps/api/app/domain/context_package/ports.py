from __future__ import annotations

from typing import Protocol


class ContextPackageCachePort(Protocol):
    """Port implemented in app/infrastructure/cache/redis_cache.py.
    Context packages are derived purely from a published KnowledgeProductVersion,
    so caching is a pure performance optimization — a miss always recomputes
    correctly. Keys should be invalidated (or just left to expire via TTL) on
    re-publish; MVP relies on TTL only."""

    async def get(self, key: str) -> dict | None: ...

    async def set(self, key: str, value: dict, ttl_seconds: int) -> None: ...
