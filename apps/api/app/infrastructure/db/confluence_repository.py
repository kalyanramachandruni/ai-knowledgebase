from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.confluence.entities import ConfluencePage, ConfluenceSpace
from app.domain.confluence.value_objects import AttachmentRef
from app.domain.shared.base import utc_now
from app.infrastructure.db.models import ConfluenceAttachment, ConfluencePage as ConfluencePageModel
from app.infrastructure.db.models import ConfluenceSpace as ConfluenceSpaceModel


def _space_to_domain(row: ConfluenceSpaceModel) -> ConfluenceSpace:
    return ConfluenceSpace(
        id=row.id, space_key=row.space_key, name=row.name, base_url=row.base_url, last_synced_at=row.last_synced_at
    )


def _page_to_domain(row: ConfluencePageModel, attachments: list[ConfluenceAttachment]) -> ConfluencePage:
    return ConfluencePage(
        id=row.id,
        space_id=row.space_id,
        confluence_page_id=row.confluence_page_id,
        title=row.title,
        body_storage_format=row.body_storage_format,
        labels=list(row.labels),
        confluence_version=row.confluence_version,
        last_modified_at=row.last_modified_at,
        attachments=[
            AttachmentRef(
                file_name=a.file_name, media_type=a.media_type, download_url=a.download_url, size_bytes=a.size_bytes
            )
            for a in attachments
        ],
    )


class SqlAlchemyConfluenceSpaceRepository:
    """Implements app.domain.confluence.repository.ConfluenceSpaceRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_key(self, space_key: str) -> ConfluenceSpace | None:
        row = (
            await self._session.execute(select(ConfluenceSpaceModel).where(ConfluenceSpaceModel.space_key == space_key))
        ).scalar_one_or_none()
        return _space_to_domain(row) if row else None

    async def get_or_create(self, space_key: str, name: str, base_url: str) -> ConfluenceSpace:
        existing = await self.get_by_key(space_key)
        if existing:
            return existing
        row = ConfluenceSpaceModel(space_key=space_key, name=name, base_url=base_url)
        self._session.add(row)
        await self._session.flush()
        return _space_to_domain(row)

    async def mark_synced(self, space_id: uuid.UUID) -> None:
        row = await self._session.get(ConfluenceSpaceModel, space_id)
        if row is not None:
            row.last_synced_at = utc_now()
            await self._session.flush()
            await self._session.commit()


class SqlAlchemyConfluencePageRepository:
    """Implements app.domain.confluence.repository.ConfluencePageRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_pages(self, space_key: str | None = None) -> list[ConfluencePage]:
        stmt = select(ConfluencePageModel)
        if space_key:
            stmt = stmt.join(ConfluenceSpaceModel).where(ConfluenceSpaceModel.space_key == space_key)
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_page_to_domain(row, []) for row in rows]

    async def get_by_id(self, page_id: uuid.UUID) -> ConfluencePage | None:
        row = await self._session.get(ConfluencePageModel, page_id)
        if row is None:
            return None
        attachments = (
            (await self._session.execute(select(ConfluenceAttachment).where(ConfluenceAttachment.page_id == row.id)))
            .scalars()
            .all()
        )
        return _page_to_domain(row, list(attachments))

    async def get_by_confluence_id(self, space_id: uuid.UUID, confluence_page_id: str) -> ConfluencePage | None:
        row = (
            await self._session.execute(
                select(ConfluencePageModel).where(
                    ConfluencePageModel.space_id == space_id,
                    ConfluencePageModel.confluence_page_id == confluence_page_id,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            return None
        attachments = (
            (await self._session.execute(select(ConfluenceAttachment).where(ConfluenceAttachment.page_id == row.id)))
            .scalars()
            .all()
        )
        return _page_to_domain(row, list(attachments))

    async def upsert(self, page: ConfluencePage) -> ConfluencePage:
        # Atomic INSERT ... ON CONFLICT DO UPDATE avoids the SELECT-then-insert
        # race that caused UniqueViolationError on re-sync of the same space.
        stmt = (
            pg_insert(ConfluencePageModel)
            .values(
                id=page.id,
                space_id=page.space_id,
                confluence_page_id=page.confluence_page_id,
                title=page.title,
                body_storage_format=page.body_storage_format,
                labels=page.labels,
                confluence_version=page.confluence_version,
                last_modified_at=page.last_modified_at,
            )
            .on_conflict_do_update(
                constraint="confluence_page_space_id_confluence_page_id_key",
                set_={
                    "title": page.title,
                    "body_storage_format": page.body_storage_format,
                    "labels": page.labels,
                    "confluence_version": page.confluence_version,
                    "last_modified_at": page.last_modified_at,
                },
            )
            .returning(ConfluencePageModel.id)
        )
        result = await self._session.execute(stmt)
        row_id: uuid.UUID = result.scalar_one()

        existing_attachments = (
            (await self._session.execute(select(ConfluenceAttachment).where(ConfluenceAttachment.page_id == row_id)))
            .scalars()
            .all()
        )
        for attachment in existing_attachments:
            await self._session.delete(attachment)
        await self._session.flush()

        for attachment in page.attachments:
            self._session.add(
                ConfluenceAttachment(
                    page_id=row_id,
                    file_name=attachment.file_name,
                    media_type=attachment.media_type,
                    download_url=attachment.download_url,
                    size_bytes=attachment.size_bytes,
                )
            )

        await self._session.flush()
        await self._session.commit()
        return await self.get_by_confluence_id(page.space_id, page.confluence_page_id)
