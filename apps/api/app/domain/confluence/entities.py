from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.domain.confluence.value_objects import AttachmentRef
from app.domain.shared.base import Entity, new_id


@dataclass
class ConfluenceSpace(Entity):
    space_key: str = ""
    name: str = ""
    base_url: str = ""
    last_synced_at: datetime | None = None


@dataclass
class ConfluencePage(Entity):
    """Raw ingested content — a 1:1 mirror of a Confluence page, not yet
    interpreted. Extraction (step 4) reads these to produce structured
    Knowledge Product drafts; this entity itself has no business rules."""

    space_id: uuid.UUID = field(default_factory=new_id)
    confluence_page_id: str = ""
    title: str = ""
    body_storage_format: str = ""
    labels: list[str] = field(default_factory=list)
    confluence_version: int = 0
    last_modified_at: datetime | None = None
    attachments: list[AttachmentRef] = field(default_factory=list)
