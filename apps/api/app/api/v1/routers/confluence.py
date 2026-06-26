from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from httpx import HTTPError

from app.api.deps import ConfluencePageRepositoryDep, ConfluenceSpaceRepositoryDep, EventOutboxDep, build_confluence_client
from app.api.v1.confluence_schemas import SyncSpaceRequest, SyncSpaceResponse
from app.application.confluence.dto import SyncSpaceInput
from app.application.confluence.use_cases import SyncConfluenceSpaceUseCase
from app.core.security import CurrentUser, require_roles
from app.domain.governance.value_objects import Role

router = APIRouter(prefix="/confluence", tags=["confluence"])

_OWNER_OR_ADMIN = require_roles(Role.KNOWLEDGE_OWNER, Role.ADMIN)


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
