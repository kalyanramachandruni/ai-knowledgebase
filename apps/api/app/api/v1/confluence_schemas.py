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


class ConfluencePageResponse(BaseModel):
    id: uuid.UUID
    space_id: uuid.UUID
    confluence_page_id: str
    title: str
    confluence_version: int
    last_modified_at: datetime
