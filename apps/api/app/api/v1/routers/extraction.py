from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import SessionDep, get_compile_from_extraction_use_case, get_extract_use_case
from app.api.v1.extraction_schemas import (
    CompileFromExtractionRequest,
    CompiledProductSummary,
    ExtractionRunResponse,
    ExtractionRunWithProductResponse,
)
from app.api.v1.schemas import KnowledgeProductResponse
from app.application.extraction.compiler import CompileFromExtractionUseCase
from app.application.extraction.exceptions import (
    ConfluencePageNotFound,
    ExtractionRunNotFound,
    ExtractionRunNotSucceeded,
)
from app.application.extraction.use_cases import ExtractKnowledgeFromPageUseCase
from app.core.security import CurrentUser, require_roles
from app.domain.governance.value_objects import Role
from app.infrastructure.db.extraction_repository import SqlAlchemyExtractionRunRepository
from app.infrastructure.db.models import ExtractionRun as ExtractionRunModel
from app.infrastructure.db.models import KnowledgeProductModel, KnowledgeProductVersionModel

router = APIRouter(tags=["extraction"])

_OWNER_OR_ADMIN = require_roles(Role.KNOWLEDGE_OWNER, Role.ADMIN)
_ANY_ROLE = require_roles(Role.KNOWLEDGE_OWNER, Role.ADMIN, Role.REVIEWER, Role.CONSUMER)


@router.post("/confluence/pages/{page_id}/extract", response_model=ExtractionRunResponse)
async def extract_page(
    page_id: uuid.UUID,
    use_case: Annotated[ExtractKnowledgeFromPageUseCase, Depends(get_extract_use_case)],
    _current_user: Annotated[CurrentUser, Depends(_OWNER_OR_ADMIN)],
) -> ExtractionRunResponse:
    try:
        run = await use_case.execute(page_id)
    except ConfluencePageNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ExtractionRunResponse(
        id=run.id,
        page_id=run.page_id,
        status=run.status.value,
        llm_provider=run.llm_provider,
        llm_model=run.llm_model,
        structured_draft=run.structured_draft,
        error_message=run.error_message,
    )


@router.get("/confluence/pages/{page_id}/extraction-history", response_model=list[ExtractionRunWithProductResponse])
async def get_page_extraction_history(
    page_id: uuid.UUID,
    session: SessionDep,
    _current_user: Annotated[CurrentUser, Depends(_ANY_ROLE)],
) -> list[ExtractionRunWithProductResponse]:
    repo = SqlAlchemyExtractionRunRepository(session)
    runs = await repo.list_by_page(page_id)

    # For each succeeded run, find the version that was compiled from it
    run_ids = [r.id for r in runs]
    compiled_map: dict[uuid.UUID, CompiledProductSummary] = {}
    if run_ids:
        stmt = (
            select(KnowledgeProductVersionModel, KnowledgeProductModel)
            .join(KnowledgeProductModel, KnowledgeProductVersionModel.product_id == KnowledgeProductModel.id)
            .where(KnowledgeProductVersionModel.source_extraction_run_id.in_(run_ids))
        )
        rows = (await session.execute(stmt)).all()
        for version, product in rows:
            compiled_map[version.source_extraction_run_id] = CompiledProductSummary(
                product_id=product.id,
                product_key=product.product_key,
                name=product.name,
                version_id=version.id,
                semver=version.semver,
            )

    return [
        ExtractionRunWithProductResponse(
            id=r.id,
            page_id=r.page_id,
            status=r.status.value,
            llm_provider=r.llm_provider,
            llm_model=r.llm_model,
            structured_draft=r.structured_draft,
            error_message=r.error_message,
            started_at=r.started_at.isoformat() if r.started_at else None,
            compiled_product=compiled_map.get(r.id),
        )
        for r in runs
    ]


@router.post("/extraction-runs/{run_id}/compile", response_model=KnowledgeProductResponse)
async def compile_from_extraction(
    run_id: uuid.UUID,
    payload: CompileFromExtractionRequest,
    use_case: Annotated[CompileFromExtractionUseCase, Depends(get_compile_from_extraction_use_case)],
    _current_user: Annotated[CurrentUser, Depends(_OWNER_OR_ADMIN)],
) -> KnowledgeProductResponse:
    try:
        product = await use_case.execute(
            run_id,
            product_key=payload.product_key,
            name=payload.name,
            owner=payload.owner,
            created_by=payload.created_by,
            bump=payload.bump,
        )
    except (ExtractionRunNotFound, ExtractionRunNotSucceeded) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return KnowledgeProductResponse.from_domain(product)
