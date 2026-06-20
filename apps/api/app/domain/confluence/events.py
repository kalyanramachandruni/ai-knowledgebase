from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.domain.shared.base import DomainEvent


@dataclass
class PageIngested(DomainEvent):
    page_id: uuid.UUID
    space_key: str
    confluence_page_id: str
    confluence_version: int


@dataclass
class PageSkippedUnchanged(DomainEvent):
    page_id: uuid.UUID
    confluence_page_id: str
