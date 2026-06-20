from __future__ import annotations

import uuid
from typing import Protocol

from app.domain.confluence.entities import ConfluencePage, ConfluenceSpace


class ConfluenceSpaceRepository(Protocol):
    async def get_by_key(self, space_key: str) -> ConfluenceSpace | None: ...

    async def get_or_create(self, space_key: str, name: str, base_url: str) -> ConfluenceSpace: ...

    async def mark_synced(self, space_id: uuid.UUID) -> None: ...


class ConfluencePageRepository(Protocol):
    async def get_by_confluence_id(
        self, space_id: uuid.UUID, confluence_page_id: str
    ) -> ConfluencePage | None: ...

    async def upsert(self, page: ConfluencePage) -> ConfluencePage: ...
