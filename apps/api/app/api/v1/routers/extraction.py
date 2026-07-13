from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    SessionDep,
    get_compile_from_extraction_use_case,
    get_compile_use_case,
    get_create_use_case,
    get_extract_use_case,
    get_llm_port,
    get_repository,
)
from app.api.v1.extraction_schemas import (
    CompileFromExtractionRequest,
    CompiledProductSummary,
    ExtractionRunResponse,
    ExtractionRunWithProductResponse,
)
from app.api.v1.schemas import KnowledgeProductResponse
from app.application.extraction.compiler import (
    CompileFromExtractionUseCase,
    _extraction_result_to_compile_input,
    _version_to_extraction_result,
)
from app.application.extraction.exceptions import (
    ConfluencePageNotFound,
    ExtractionRunNotFound,
    ExtractionRunNotSucceeded,
)
from app.application.extraction.use_cases import ExtractKnowledgeFromPageUseCase
from app.application.knowledge_product.dto import CreateKnowledgeProductInput
from app.application.knowledge_product.use_cases import CompileNewVersionUseCase, CreateKnowledgeProductUseCase
from app.core.security import CurrentUser, require_roles
from app.domain.extraction.entities import ExtractionStatus
from app.domain.extraction.ports import ExtractionResult, LLMExtractionPort
from app.domain.extraction.schema import KNOWLEDGE_EXTRACTION_SCHEMA
from app.domain.governance.value_objects import Role
from app.domain.knowledge_product.value_objects import VersionBump
from app.infrastructure.db.extraction_repository import SqlAlchemyExtractionRunRepository
from app.infrastructure.db.models import ExtractionRun as ExtractionRunModel
from app.infrastructure.db.models import KnowledgeProductModel, KnowledgeProductVersionModel
from app.infrastructure.db.repository import SqlAlchemyKnowledgeProductRepository

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


class BatchCompileRequest(BaseModel):
    run_ids: list[uuid.UUID]
    product_key: str
    name: str
    owner: str
    created_by: uuid.UUID
    bump: VersionBump = VersionBump.MINOR


@router.post("/extraction-runs/batch-compile", response_model=KnowledgeProductResponse)
async def batch_compile_from_extractions(
    payload: BatchCompileRequest,
    session: SessionDep,
    llm_port: Annotated[LLMExtractionPort, Depends(get_llm_port)],
    repository: Annotated[SqlAlchemyKnowledgeProductRepository, Depends(get_repository)],
    create_use_case: Annotated[CreateKnowledgeProductUseCase, Depends(get_create_use_case)],
    compile_use_case: Annotated[CompileNewVersionUseCase, Depends(get_compile_use_case)],
    _current_user: Annotated[CurrentUser, Depends(_OWNER_OR_ADMIN)],
) -> KnowledgeProductResponse:
    """Extract multiple runs' drafts, LLM-merge them into one result, then compile a single version."""
    repo = SqlAlchemyExtractionRunRepository(session)

    # Collect all succeeded drafts
    results: list[ExtractionResult] = []
    for run_id in payload.run_ids:
        run = await repo.get_by_id(run_id)
        if run is None or run.status is not ExtractionStatus.SUCCEEDED or not run.structured_draft:
            continue
        draft = run.structured_draft
        results.append(ExtractionResult(
            process_overview=draft.get("process_overview", {}),
            process_steps=draft.get("process_steps", []),
            rules=draft.get("rules", []),
            policies=draft.get("policies", []),
            sla_target=draft.get("sla_target"),
            escalations=draft.get("escalations", []),
            roles=draft.get("roles", []),
            tools=draft.get("tools", []),
            raw_model_output=draft,
        ))

    if not results:
        raise HTTPException(status_code=422, detail="No succeeded extraction runs found in the provided IDs")

    # Merge all results into one via sequential LLM merges
    merged = results[0]
    for next_result in results[1:]:
        merged = await llm_port.merge(merged, next_result, KNOWLEDGE_EXTRACTION_SCHEMA)

    compile_input = _extraction_result_to_compile_input(
        merged,
        created_by=payload.created_by,
        bump=payload.bump,
        source_extraction_run_id=None,
    )

    existing = await repository.get_by_key(payload.product_key)
    if existing is None:
        product = await create_use_case.execute(
            CreateKnowledgeProductInput(
                product_key=payload.product_key,
                name=payload.name,
                owner=payload.owner,
                compile_input=compile_input,
            )
        )
    else:
        existing_result = _version_to_extraction_result(existing.current_version)
        final_merged = await llm_port.merge(existing_result, merged, KNOWLEDGE_EXTRACTION_SCHEMA)
        final_input = _extraction_result_to_compile_input(
            final_merged,
            created_by=payload.created_by,
            bump=payload.bump,
            source_extraction_run_id=None,
        )
        await compile_use_case.execute(existing.id, final_input)
        product = await repository.get_by_id(existing.id)

    return KnowledgeProductResponse.from_domain(product)


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
