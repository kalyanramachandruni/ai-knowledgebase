from __future__ import annotations

from app.application.confluence.dto import SyncSpaceInput, SyncSpaceResult
from app.domain.confluence.entities import ConfluencePage
from app.domain.confluence.events import PageIngested, PageSkippedUnchanged
from app.domain.confluence.ports import ConfluenceClientPort
from app.domain.confluence.repository import ConfluencePageRepository, ConfluenceSpaceRepository
from app.domain.confluence.value_objects import AttachmentRef
from app.domain.shared.event_bus import EventPublisherPort


class SyncConfluenceSpaceUseCase:
    """Incremental sync: a page is only re-persisted (and only then does an
    event fire) when Confluence's own version number has advanced past what
    we already stored — this is the entirety of the "incremental" behavior,
    deliberately not driven by timestamps, which are less reliable across
    Confluence's own caching/replication."""

    def __init__(
        self,
        client: ConfluenceClientPort,
        space_repository: ConfluenceSpaceRepository,
        page_repository: ConfluencePageRepository,
        event_publisher: EventPublisherPort,
    ) -> None:
        self._client = client
        self._space_repository = space_repository
        self._page_repository = page_repository
        self._event_publisher = event_publisher

    async def execute(self, payload: SyncSpaceInput) -> SyncSpaceResult:
        space = await self._space_repository.get_or_create(
            payload.space_key, payload.space_name, payload.base_url
        )

        created = updated = skipped = 0

        async for raw_page in self._client.list_pages(payload.space_key):
            existing = await self._page_repository.get_by_confluence_id(space.id, raw_page.confluence_page_id)

            if existing is not None and existing.confluence_version >= raw_page.version:
                skipped += 1
                await self._event_publisher.publish(
                    PageSkippedUnchanged(page_id=existing.id, confluence_page_id=raw_page.confluence_page_id)
                )
                continue

            page = ConfluencePage(
                space_id=space.id,
                confluence_page_id=raw_page.confluence_page_id,
                title=raw_page.title,
                body_storage_format=raw_page.body_storage_format,
                labels=raw_page.labels,
                confluence_version=raw_page.version,
                last_modified_at=raw_page.last_modified_at,
                attachments=[
                    AttachmentRef(
                        file_name=a.file_name,
                        media_type=a.media_type,
                        download_url=a.download_url,
                        size_bytes=a.size_bytes,
                    )
                    for a in raw_page.attachments
                ],
            )
            if existing is not None:
                page.id = existing.id

            saved = await self._page_repository.upsert(page)
            await self._event_publisher.publish(
                PageIngested(
                    page_id=saved.id,
                    space_key=payload.space_key,
                    confluence_page_id=raw_page.confluence_page_id,
                    confluence_version=raw_page.version,
                )
            )

            if existing is None:
                created += 1
            else:
                updated += 1

        await self._space_repository.mark_synced(space.id, created=created, updated=updated, skipped=skipped)

        return SyncSpaceResult(
            space_key=payload.space_key,
            pages_created=created,
            pages_updated=updated,
            pages_skipped_unchanged=skipped,
        )
