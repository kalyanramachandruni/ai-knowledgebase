from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.curation.entities import CurationRun, CurationStatus, PageSourceType
from app.infrastructure.db.models import (
    KpCompileSession as CompileSession,
    KpCompileSessionEntry as CompileSessionEntry,
    PageCurationSession as CurationSessionModel,
    PageCurationSessionEntry as CurationSessionEntryModel,
)


def _coerce_draft(draft: object) -> dict | None:
    if draft is None:
        return None
    if isinstance(draft, dict):
        return draft
    if isinstance(draft, str):
        try:
            parsed = json.loads(draft)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None
    return None


def _to_curation_result(
    entry: CurationSessionEntryModel,
    session: CurationSessionModel,
    compile_entry: CompileSessionEntry | None = None,
    compile_version_id: uuid.UUID | None = None,
) -> CurationRun:
    compile_status: str | None = None
    compiled_at: datetime | None = None
    compile_error: str | None = None

    if compile_entry:
        if compile_entry.status == "compiled":
            compile_status = "succeeded"
            compiled_at = compile_entry.compiled_at
        elif compile_entry.status == "skipped":
            compile_status = "failed"
            compile_error = compile_entry.reason

    return CurationRun(
        id=entry.id,
        session_id=entry.session_id,
        page_id=entry.page_id,
        page_source_type=PageSourceType(entry.page_source_type) if entry.page_source_type else None,
        status=CurationStatus(entry.status),
        structured_draft=_coerce_draft(entry.structured_draft),
        error_message=entry.error_message,
        llm_provider=session.llm_provider,
        llm_model=session.llm_model,
        started_at=session.started_at,
        completed_at=session.completed_at,
        compiled_at=compiled_at,
        compile_status=compile_status,
        compile_error=compile_error,
        compiled_version_id=compile_version_id,
    )


async def _latest_compile_per_entry(
    db: AsyncSession, entry_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[CompileSessionEntry, uuid.UUID | None]]:
    """Return {entry_id: (CompileSessionEntry, version_id)} for the most recent compile per entry."""
    if not entry_ids:
        return {}

    rows = (await db.execute(
        select(CompileSessionEntry, CompileSession.version_id)
        .join(CompileSession, CompileSession.id == CompileSessionEntry.session_id)
        .where(CompileSessionEntry.curation_entry_id.in_(entry_ids))
        .order_by(CompileSessionEntry.created_at.desc())
    )).all()

    result: dict[uuid.UUID, tuple[CompileSessionEntry, uuid.UUID | None]] = {}
    for cse, version_id in rows:
        if cse.curation_entry_id not in result:
            result[cse.curation_entry_id] = (cse, version_id)
    return result


class SqlAlchemyCurationRunRepository:
    """Handles page_curation_session + page_curation_session_entry as a unified flat CurationRun."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_latest_succeeded_by_pages(self, page_ids: list[uuid.UUID]) -> list[CurationRun]:
        """Return the single most-recent succeeded run per page. Pages with no succeeded run are omitted."""
        if not page_ids:
            return []
        rows = (await self._session.execute(
            select(CurationSessionEntryModel, CurationSessionModel)
            .join(CurationSessionModel, CurationSessionModel.id == CurationSessionEntryModel.session_id)
            .where(
                CurationSessionEntryModel.page_id.in_(page_ids),
                CurationSessionEntryModel.status == "succeeded",
            )
            .order_by(CurationSessionModel.started_at.desc())
        )).all()
        seen: set[uuid.UUID] = set()
        result = []
        for entry, session in rows:
            if entry.page_id not in seen:
                seen.add(entry.page_id)
                result.append(_to_curation_result(entry, session))
        return result

    async def list_by_pages(self, page_ids: list[uuid.UUID]) -> list[CurationRun]:
        if not page_ids:
            return []
        rows = (await self._session.execute(
            select(CurationSessionEntryModel, CurationSessionModel)
            .join(CurationSessionModel, CurationSessionModel.id == CurationSessionEntryModel.session_id)
            .where(CurationSessionEntryModel.page_id.in_(page_ids))
            .order_by(CurationSessionModel.started_at.desc())
        )).all()
        entry_ids = [entry.id for entry, _ in rows]
        compile_map = await _latest_compile_per_entry(self._session, entry_ids)
        return [_to_curation_result(e, s, *compile_map.get(e.id, (None, None))) for e, s in rows]

    async def list_by_page(self, page_id: uuid.UUID) -> list[CurationRun]:
        rows = (await self._session.execute(
            select(CurationSessionEntryModel, CurationSessionModel)
            .join(CurationSessionModel, CurationSessionModel.id == CurationSessionEntryModel.session_id)
            .where(CurationSessionEntryModel.page_id == page_id)
            .order_by(CurationSessionModel.started_at.desc())
        )).all()
        entry_ids = [entry.id for entry, _ in rows]
        compile_map = await _latest_compile_per_entry(self._session, entry_ids)
        return [_to_curation_result(e, s, *compile_map.get(e.id, (None, None))) for e, s in rows]

    async def get_by_id(self, run_id: uuid.UUID) -> CurationRun | None:
        row = (await self._session.execute(
            select(CurationSessionEntryModel, CurationSessionModel)
            .join(CurationSessionModel, CurationSessionModel.id == CurationSessionEntryModel.session_id)
            .where(CurationSessionEntryModel.id == run_id)
        )).first()
        if row is None:
            return None
        entry, session = row
        compile_map = await _latest_compile_per_entry(self._session, [entry.id])
        cse, vid = compile_map.get(entry.id, (None, None))
        return _to_curation_result(entry, session, cse, vid)

    async def list_pending_compile(self, page_ids: list[uuid.UUID]) -> list[CurationRun]:
        """Most recent succeeded entry per page that has no compiled compile_session_entry."""
        if not page_ids:
            return []
        # Subquery: entry_ids that already have a 'compiled' compile_session_entry
        compiled_entry_ids_stmt = select(CompileSessionEntry.curation_entry_id).where(
            CompileSessionEntry.status == "compiled",
            CompileSessionEntry.curation_entry_id.isnot(None),
        )
        rows = (await self._session.execute(
            select(CurationSessionEntryModel, CurationSessionModel)
            .join(CurationSessionModel, CurationSessionModel.id == CurationSessionEntryModel.session_id)
            .where(
                CurationSessionEntryModel.page_id.in_(page_ids),
                CurationSessionEntryModel.status == "succeeded",
                CurationSessionEntryModel.id.not_in(compiled_entry_ids_stmt),
            )
            .order_by(CurationSessionModel.started_at.desc())
        )).all()
        seen: set[uuid.UUID] = set()
        result = []
        for entry, session in rows:
            if entry.page_id not in seen:
                seen.add(entry.page_id)
                result.append(_to_curation_result(entry, session))
        return result

    async def save(self, run: CurationRun) -> CurationRun:
        """Create or update a session+entry pair atomically."""
        entry_row = await self._session.get(CurationSessionEntryModel, run.id)
        if entry_row is None:
            # Create a new session for this run
            session_row = CurationSessionModel(
                id=uuid.uuid4(),
                llm_provider=run.llm_provider,
                llm_model=run.llm_model,
                status=run.status.value,
                started_at=run.started_at or datetime.now(timezone.utc),
                completed_at=run.completed_at,
            )
            self._session.add(session_row)
            await self._session.flush()

            entry_row = CurationSessionEntryModel(
                id=run.id,
                session_id=session_row.id,
                page_id=run.page_id,
                page_source_type=run.page_source_type.value if run.page_source_type else None,
                status=run.status.value,
                structured_draft=_coerce_draft(run.structured_draft),
                error_message=run.error_message,
            )
            self._session.add(entry_row)
        else:
            entry_row.status = run.status.value
            entry_row.structured_draft = _coerce_draft(run.structured_draft)
            entry_row.error_message = run.error_message

            # Update session completed_at and status on completion
            session_row = await self._session.get(CurationSessionModel, entry_row.session_id)
            if session_row and run.completed_at:
                session_row.completed_at = run.completed_at
                session_row.status = run.status.value

        await self._session.flush()
        await self._session.commit()
        return _to_curation_result(
            entry_row,
            session_row if entry_row.session_id else CurationSessionModel(
                llm_provider=run.llm_provider, llm_model=run.llm_model,
                started_at=run.started_at, completed_at=run.completed_at,
            ),
        )
