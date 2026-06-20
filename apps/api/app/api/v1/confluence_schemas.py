from __future__ import annotations

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
