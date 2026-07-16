from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel


class SyncSpaceRequest(BaseModel):
    space_key: str
    space_name: str
    base_url: str


class SyncSpaceResponse(BaseModel):
    space_key: str
    pages_created: int
    pages_updated: int
    pages_skipped_unchanged: int


class ConfluenceSpaceResponse(BaseModel):
    id: uuid.UUID
    space_key: str
    name: str
    base_url: str
    last_synced_at: datetime | None = None
    page_count: int = 0
    last_sync_created: int | None = None
    last_sync_updated: int | None = None
    last_sync_skipped: int | None = None


class ConfluencePageResponse(BaseModel):
    id: uuid.UUID
    space_id: uuid.UUID
    space_key: str
    confluence_page_id: str
    title: str
    confluence_version: int
    last_modified_at: datetime


class ConfluencePageDetailResponse(ConfluencePageResponse):
    plain_text: str
    labels: list[str]
