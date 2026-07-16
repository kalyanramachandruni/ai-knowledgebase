from __future__ import annotations

import uuid as _uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from httpx import HTTPError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import ConfluencePageRepositoryDep, ConfluenceSpaceRepositoryDep, EventOutboxDep, SessionDep, build_confluence_client
from app.infrastructure.db.extraction_repository import SqlAlchemyExtractionRunRepository
from app.infrastructure.db.models import ConfluencePage as ConfluencePageModel, ConfluenceSpace as ConfluenceSpaceModel
from app.api.v1.confluence_schemas import ConfluencePageDetailResponse, ConfluencePageResponse, ConfluenceSpaceResponse, SyncSpaceRequest, SyncSpaceResponse
from app.application.confluence.dto import SyncSpaceInput
from app.application.confluence.use_cases import SyncConfluenceSpaceUseCase
from app.application.extraction.html import strip_storage_format
from app.core.security import CurrentUser, require_roles
from app.domain.governance.value_objects import Role

router = APIRouter(prefix="/confluence", tags=["confluence"])

_OWNER_OR_ADMIN = require_roles(Role.KNOWLEDGE_OWNER, Role.ADMIN)
_ANY_ROLE = require_roles(Role.KNOWLEDGE_OWNER, Role.ADMIN, Role.REVIEWER, Role.CONSUMER)


@router.get("/spaces", response_model=list[ConfluenceSpaceResponse])
async def list_spaces(
    space_repository: ConfluenceSpaceRepositoryDep,
    _current_user: Annotated[CurrentUser, Depends(_ANY_ROLE)],
) -> list[ConfluenceSpaceResponse]:
    rows = await space_repository.list_spaces()
    return [
        ConfluenceSpaceResponse(
            id=s.id,
            space_key=s.space_key,
            name=s.name,
            base_url=s.base_url,
            last_synced_at=s.last_synced_at,
            page_count=page_count,
            last_sync_created=s.last_sync_created,
            last_sync_updated=s.last_sync_updated,
            last_sync_skipped=s.last_sync_skipped,
        )
        for s, page_count in rows
    ]


@router.get("/pages", response_model=list[ConfluencePageResponse])
async def list_pages(
    page_repository: ConfluencePageRepositoryDep,
    _current_user: Annotated[CurrentUser, Depends(_ANY_ROLE)],
    space_key: str | None = Query(default=None),
) -> list[ConfluencePageResponse]:
    rows = await page_repository.list_pages(space_key)
    return [
        ConfluencePageResponse(
            id=p.id,
            space_id=p.space_id,
            space_key=sk,
            confluence_page_id=p.confluence_page_id,
            title=p.title,
            confluence_version=p.confluence_version,
            last_modified_at=p.last_modified_at,
        )
        for p, sk in rows
    ]


@router.get("/pages/pending-compile", response_model=list[dict])
async def get_pending_compile_runs(
    session: SessionDep,
    _current_user: Annotated[CurrentUser, Depends(_ANY_ROLE)],
    space_key: str = Query(...),
) -> list[dict]:
    page_id_stmt = (
        select(ConfluencePageModel.id)
        .join(ConfluenceSpaceModel, ConfluencePageModel.space_id == ConfluenceSpaceModel.id)
        .where(ConfluenceSpaceModel.space_key == space_key)
    )
    page_ids = list((await session.execute(page_id_stmt)).scalars().all())
    repo = SqlAlchemyExtractionRunRepository(session)
    pending = await repo.list_pending_compile(page_ids)
    return [{"page_id": str(r.page_id), "run_id": str(r.id)} for r in pending]


@router.get("/pages/{page_id}", response_model=ConfluencePageDetailResponse)
async def get_page(
    page_id: str,
    page_repository: ConfluencePageRepositoryDep,
    _current_user: Annotated[CurrentUser, Depends(_ANY_ROLE)],
) -> ConfluencePageDetailResponse:
    try:
        pid = _uuid.UUID(page_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid page id")
    page = await page_repository.get_by_id(pid)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")
    return ConfluencePageDetailResponse(
        id=page.id,
        space_id=page.space_id,
        space_key="",
        confluence_page_id=page.confluence_page_id,
        title=page.title,
        confluence_version=page.confluence_version,
        last_modified_at=page.last_modified_at,
        plain_text=strip_storage_format(page.body_storage_format or ""),
        labels=page.labels,
    )


@router.post("/spaces/sync", response_model=SyncSpaceResponse)
async def sync_space(
    payload: SyncSpaceRequest,
    space_repository: ConfluenceSpaceRepositoryDep,
    page_repository: ConfluencePageRepositoryDep,
    outbox: EventOutboxDep,
    _current_user: Annotated[CurrentUser, Depends(_OWNER_OR_ADMIN)],
) -> SyncSpaceResponse:
    client = build_confluence_client(payload.base_url)
    try:
        use_case = SyncConfluenceSpaceUseCase(client, space_repository, page_repository, outbox)
        result = await use_case.execute(
            SyncSpaceInput(space_key=payload.space_key, space_name=payload.space_name, base_url=payload.base_url)
        )
    except HTTPError as exc:
        raise HTTPException(
            status_code=502, detail=f"Failed to reach Confluence at {payload.base_url!r}: {exc}"
        ) from exc
    finally:
        await client.aclose()

    return SyncSpaceResponse(
        space_key=result.space_key,
        pages_created=result.pages_created,
        pages_updated=result.pages_updated,
        pages_skipped_unchanged=result.pages_skipped_unchanged,
    )
