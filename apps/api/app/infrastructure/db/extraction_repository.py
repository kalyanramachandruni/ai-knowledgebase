from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.extraction.entities import ExtractionRun, ExtractionStatus
from app.infrastructure.db.models import ExtractionRun as ExtractionRunModel


def _to_domain(row: ExtractionRunModel) -> ExtractionRun:
    return ExtractionRun(
        id=row.id,
        page_id=row.page_id,
        llm_provider=row.llm_provider,
        llm_model=row.llm_model,
        status=ExtractionStatus(row.status),
        structured_draft=row.structured_draft,
        error_message=row.error_message,
        started_at=row.started_at,
        completed_at=row.completed_at,
    )


class SqlAlchemyExtractionRunRepository:
    """Implements app.domain.extraction.repository.ExtractionRunRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_pages(self, page_ids: list[uuid.UUID]) -> list[ExtractionRun]:
        if not page_ids:
            return []
        stmt = (
            select(ExtractionRunModel)
            .where(ExtractionRunModel.page_id.in_(page_ids))
            .order_by(ExtractionRunModel.started_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_domain(r) for r in rows]

    async def list_by_page(self, page_id: uuid.UUID) -> list[ExtractionRun]:
        stmt = (
            select(ExtractionRunModel)
            .where(ExtractionRunModel.page_id == page_id)
            .order_by(ExtractionRunModel.started_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        return [_to_domain(r) for r in rows]

    async def get_by_id(self, run_id: uuid.UUID) -> ExtractionRun | None:
        row = await self._session.get(ExtractionRunModel, run_id)
        return _to_domain(row) if row else None

    async def mark_compiled(
        self,
        run_id: uuid.UUID,
        version_id: uuid.UUID | None,
        status: str,
        error: str | None = None,
    ) -> None:
        row = await self._session.get(ExtractionRunModel, run_id)
        if row is None:
            return
        row.compiled_at = datetime.now(timezone.utc)
        row.compiled_version_id = version_id
        row.compile_status = status
        row.compile_error = error
        await self._session.flush()

    async def list_pending_compile(self, page_ids: list[uuid.UUID]) -> list[ExtractionRun]:
        """Most recent succeeded run per page that has not yet been compiled."""
        if not page_ids:
            return []
        # Get all succeeded runs for these pages ordered desc; caller picks first per page
        stmt = (
            select(ExtractionRunModel)
            .where(
                ExtractionRunModel.page_id.in_(page_ids),
                ExtractionRunModel.status == "succeeded",
                ExtractionRunModel.compiled_at.is_(None),
            )
            .order_by(ExtractionRunModel.started_at.desc())
        )
        rows = (await self._session.execute(stmt)).scalars().all()
        # One run per page (most recent)
        seen: set[uuid.UUID] = set()
        result = []
        for row in rows:
            if row.page_id not in seen:
                seen.add(row.page_id)
                result.append(_to_domain(row))
        return result

    async def save(self, run: ExtractionRun) -> ExtractionRun:
        row = await self._session.get(ExtractionRunModel, run.id)
        if row is None:
            row = ExtractionRunModel(
                id=run.id,
                page_id=run.page_id,
                llm_provider=run.llm_provider,
                llm_model=run.llm_model,
                status=run.status.value,
                structured_draft=run.structured_draft,
                error_message=run.error_message,
            )
            self._session.add(row)
        else:
            row.status = run.status.value
            row.structured_draft = run.structured_draft
            row.error_message = run.error_message
            row.completed_at = run.completed_at

        await self._session.flush()
        await self._session.commit()
        return _to_domain(row)
