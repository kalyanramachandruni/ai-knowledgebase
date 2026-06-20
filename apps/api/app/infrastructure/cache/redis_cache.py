from __future__ import annotations

import json

from redis.asyncio import Redis


class RedisContextPackageCache:
    """Implements app.domain.context_package.ports.ContextPackageCachePort."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def get(self, key: str) -> dict | None:
        raw = await self._redis.get(key)
        return json.loads(raw) if raw is not None else None

    async def set(self, key: str, value: dict, ttl_seconds: int) -> None:
        await self._redis.set(key, json.dumps(value), ex=ttl_seconds)
