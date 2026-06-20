from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class RawAttachment:
    file_name: str
    media_type: str
    download_url: str
    size_bytes: int


@dataclass(frozen=True)
class RawConfluencePage:
    """DTO at the external boundary — shaped like the Confluence REST API
    response, not the domain entity. The application layer maps this to
    app.domain.confluence.entities.ConfluencePage."""

    confluence_page_id: str
    title: str
    body_storage_format: str
    labels: list[str]
    version: int
    last_modified_at: datetime
    attachments: list[RawAttachment] = field(default_factory=list)


class ConfluenceClientPort(Protocol):
    """Port implemented by app.infrastructure.confluence.client.ConfluenceApiClient.
    Domain/application code never imports httpx or knows about Confluence's
    REST API shape directly."""

    def list_pages(self, space_key: str) -> AsyncIterator[RawConfluencePage]:
        """Streams every page in the space, paginating internally."""
        ...
