from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from urllib.parse import parse_qs, urlsplit

import httpx

from app.domain.confluence.ports import RawAttachment, RawConfluencePage

_PAGE_EXPAND = "body.storage,version,metadata.labels,history.lastUpdated"
_PAGE_LIMIT = 50


class ConfluenceApiClient:
    """Implements app.domain.confluence.ports.ConfluenceClientPort against the
    Confluence Cloud REST API v1, authenticating with an OAuth 2.0 (3LO)
    Bearer access token via the API gateway. `base_url` is the gateway root
    including the `/wiki/rest/api` suffix, e.g.
    `https://api.atlassian.com/ex/confluence/{cloudId}/wiki/rest/api`.

    Pagination links returned by Confluence (`_links.next`) come back as
    host-relative paths scoped to the classic site form (e.g.
    `/wiki/rest/api/content?...`), not the gateway's `/ex/confluence/{cloudId}`
    prefix — resolving them directly against base_url would silently drop
    that prefix. We extract just the query params from `next` and re-issue
    against our own fixed endpoint instead of following the path as-is."""

    def __init__(self, base_url: str, api_token: str, *, http_client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = http_client or httpx.AsyncClient(
            base_url=self._base_url,
            headers={"Authorization": f"Bearer {api_token}", "Accept": "application/json"},
            timeout=30.0,
        )

    async def list_pages(self, space_key: str) -> AsyncIterator[RawConfluencePage]:
        params: dict | None = {
            "spaceKey": space_key,
            "type": "page",
            "expand": _PAGE_EXPAND,
            "limit": _PAGE_LIMIT,
        }

        while params is not None:
            response = await self._client.get("/content", params=params)
            response.raise_for_status()
            payload = response.json()

            for raw in payload.get("results", []):
                yield await self._to_raw_page(raw)

            next_link = payload.get("_links", {}).get("next")
            params = self._params_from_link(next_link) if next_link else None

    @staticmethod
    def _params_from_link(link: str) -> dict:
        query = parse_qs(urlsplit(link).query)
        return {key: values[0] for key, values in query.items()}

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
        response = await self._client.get(f"/content/{confluence_page_id}/child/attachment")
        response.raise_for_status()
        payload = response.json()
        attachments = []
        for raw in payload.get("results", []):
            extensions = raw.get("extensions", {})
            attachments.append(
                RawAttachment(
                    file_name=raw["title"],
                    media_type=extensions.get("mediaType", "application/octet-stream"),
                    # Same host-relative caveat as pagination links: Confluence's
                    # _links.download omits the gateway's /ex/confluence/{cloudId}
                    # prefix. Not corrected here since nothing downloads attachment
                    # bytes yet — fix this the same way as _params_from_link before
                    # wiring up an actual download call against this URL.
                    download_url=self._base_url + raw["_links"]["download"],
                    size_bytes=extensions.get("fileSize", 0),
                )
            )
        return attachments

    async def aclose(self) -> None:
        await self._client.aclose()
