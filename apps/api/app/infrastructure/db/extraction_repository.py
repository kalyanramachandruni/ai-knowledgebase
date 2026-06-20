from __future__ import annotations

import uuid

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

    async def get_by_id(self, run_id: uuid.UUID) -> ExtractionRun | None:
        row = await self._session.get(ExtractionRunModel, run_id)
        return _to_domain(row) if row else None

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
