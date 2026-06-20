from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime

import httpx

from app.domain.confluence.ports import RawAttachment, RawConfluencePage

_PAGE_EXPAND = "body.storage,version,metadata.labels,history.lastUpdated"
_PAGE_LIMIT = 50


class ConfluenceApiClient:
    """Implements app.domain.confluence.ports.ConfluenceClientPort against the
    Confluence Cloud REST API v1 (`/wiki/rest/api/content`), authenticating with
    an Atlassian API token (Basic auth: account email + token)."""

    def __init__(self, base_url: str, user_email: str, api_token: str, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = http_client or httpx.AsyncClient(
            base_url=self._base_url,
            auth=(user_email, api_token),
            timeout=30.0,
        )

    async def list_pages(self, space_key: str) -> AsyncIterator[RawConfluencePage]:
        url: str | None = "/wiki/rest/api/content"
        params: dict | None = {
            "spaceKey": space_key,
            "type": "page",
            "expand": _PAGE_EXPAND,
            "limit": _PAGE_LIMIT,
        }

        while url is not None:
            response = await self._client.get(url, params=params)
            response.raise_for_status()
            payload = response.json()

            for raw in payload.get("results", []):
                yield await self._to_raw_page(raw)

            next_link = payload.get("_links", {}).get("next")
            url = next_link
            params = None  # pagination links from Confluence already carry the full query string

    async def _to_raw_page(self, raw: dict) -> RawConfluencePage:
        confluence_page_id = raw["id"]
        attachments = await self._list_attachments(confluence_page_id)
        labels = [label["name"] for label in raw.get("metadata", {}).get("labels", {}).get("results", [])]
        last_modified_raw = raw["history"]["lastUpdated"]["when"]
        return RawConfluencePage(
            confluence_page_id=confluence_page_id,
            title=raw["title"],
            body_storage_format=raw.get("body", {}).get("storage", {}).get("value", ""),
            labels=labels,
            version=raw["version"]["number"],
            last_modified_at=datetime.fromisoformat(last_modified_raw),
            attachments=attachments,
        )

    async def _list_attachments(self, confluence_page_id: str) -> list[RawAttachment]:
        response = await self._client.get(f"/wiki/rest/api/content/{confluence_page_id}/child/attachment")
        response.raise_for_status()
        payload = response.json()
        attachments = []
        for raw in payload.get("results", []):
            extensions = raw.get("extensions", {})
            attachments.append(
                RawAttachment(
                    file_name=raw["title"],
                    media_type=extensions.get("mediaType", "application/octet-stream"),
                    download_url=self._base_url + raw["_links"]["download"],
                    size_bytes=extensions.get("fileSize", 0),
                )
            )
        return attachments

    async def aclose(self) -> None:
        await self._client.aclose()
