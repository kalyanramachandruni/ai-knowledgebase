from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
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


def _build_compiled_product_map(
    version_ids: list[uuid.UUID],
    run_id_to_version_id: dict[uuid.UUID, uuid.UUID],
    version_rows: list,
) -> dict[uuid.UUID, CompiledProductSummary]:
    """Build a map from version_id → CompiledProductSummary."""
    result: dict[uuid.UUID, CompiledProductSummary] = {}
    for version, product in version_rows:
        result[version.id] = CompiledProductSummary(
            product_id=product.id,
            product_key=product.product_key,
            name=product.name,
            version_id=version.id,
            semver=version.semver,
        )
    return result


async def _fetch_compiled_product_map(
    session: AsyncSession,
    version_ids: list[uuid.UUID],
    run_ids_for_fk: list[uuid.UUID],
) -> tuple[dict[uuid.UUID, CompiledProductSummary], dict[uuid.UUID, uuid.UUID]]:
    """
    Returns (version_id→summary, run_id→version_id).
    Looks up via both compiled_version_id (new) and source_extraction_run_id (legacy FK).
    """
    version_map: dict[uuid.UUID, CompiledProductSummary] = {}
    run_to_version: dict[uuid.UUID, uuid.UUID] = {}

    all_version_ids = list(set(version_ids))
    # Also collect version_ids via the legacy FK path
    if run_ids_for_fk:
        fk_stmt = (
            select(KnowledgeProductVersionModel, KnowledgeProductModel)
            .join(KnowledgeProductModel, KnowledgeProductVersionModel.product_id == KnowledgeProductModel.id)
            .where(KnowledgeProductVersionModel.source_extraction_run_id.in_(run_ids_for_fk))
        )
        for version, product in (await session.execute(fk_stmt)).all():
            vid = version.id
            run_to_version[version.source_extraction_run_id] = vid
            if vid not in [v for v in all_version_ids]:
                all_version_ids.append(vid)
            version_map[vid] = CompiledProductSummary(
                product_id=product.id, product_key=product.product_key,
                name=product.name, version_id=vid, semver=version.semver,
            )

    if all_version_ids:
        ver_stmt = (
            select(KnowledgeProductVersionModel, KnowledgeProductModel)
            .join(KnowledgeProductModel, KnowledgeProductVersionModel.product_id == KnowledgeProductModel.id)
            .where(KnowledgeProductVersionModel.id.in_(all_version_ids))
        )
        for version, product in (await session.execute(ver_stmt)).all():
            version_map[version.id] = CompiledProductSummary(
                product_id=product.id, product_key=product.product_key,
                name=product.name, version_id=version.id, semver=version.semver,
            )

    return version_map, run_to_version


def _run_to_response(
    r: ExtractionRunModel,
    version_map: dict[uuid.UUID, CompiledProductSummary],
    run_to_version: dict[uuid.UUID, uuid.UUID],
    prev_compiled_product: CompiledProductSummary | None = None,
    prev_compiled_at: str | None = None,
) -> ExtractionRunWithProductResponse:
    # Resolve compiled product: new path (compiled_version_id) or legacy FK path
    compiled_product: CompiledProductSummary | None = None
    if r.compiled_version_id:
        compiled_product = version_map.get(r.compiled_version_id)
    elif r.id in run_to_version:
        compiled_product = version_map.get(run_to_version[r.id])

    return ExtractionRunWithProductResponse(
        id=r.id, page_id=r.page_id, status=r.status,
        llm_provider=r.llm_provider, llm_model=r.llm_model,
        structured_draft=r.structured_draft, error_message=r.error_message,
        started_at=r.started_at.isoformat() if r.started_at else None,
        compiled_product=compiled_product,
        compiled_at=r.compiled_at.isoformat() if r.compiled_at else None,
        compile_status=r.compile_status,
        compile_error=r.compile_error,
        compiled_version_id=str(r.compiled_version_id) if r.compiled_version_id else None,
        prev_compiled_product=prev_compiled_product,
        prev_compiled_at=prev_compiled_at,
    )


@router.get("/confluence/extraction-history", response_model=dict[str, list[ExtractionRunWithProductResponse]])
async def get_bulk_extraction_history(
    session: SessionDep,
    _current_user: Annotated[CurrentUser, Depends(_ANY_ROLE)],
    space_key: str | None = None,
) -> dict[str, list[ExtractionRunWithProductResponse]]:
    """Return extraction history for all pages (optionally filtered by space_key) in one query."""
    from app.infrastructure.db.models import ConfluencePage as ConfluencePageModel, ConfluenceSpace as ConfluenceSpaceModel

    page_id_stmt = select(ConfluencePageModel.id)
    if space_key:
        page_id_stmt = (
            page_id_stmt.join(ConfluenceSpaceModel, ConfluencePageModel.space_id == ConfluenceSpaceModel.id)
            .where(ConfluenceSpaceModel.space_key == space_key)
        )
    page_ids = list((await session.execute(page_id_stmt)).scalars().all())

    if not page_ids:
        return {}

    run_stmt = (
        select(ExtractionRunModel)
        .where(ExtractionRunModel.page_id.in_(page_ids))
        .order_by(ExtractionRunModel.started_at.desc())
    )
    runs: list[ExtractionRunModel] = list((await session.execute(run_stmt)).scalars().all())

    version_ids = [r.compiled_version_id for r in runs if r.compiled_version_id]
    run_ids = [r.id for r in runs]
    version_map, run_to_version = await _fetch_compiled_product_map(session, version_ids, run_ids)

    # Group runs by page, track prev succeeded compile per page
    result: dict[str, list[ExtractionRunWithProductResponse]] = {}
    prev_compile: dict[str, tuple[CompiledProductSummary | None, str | None]] = {}  # page_id → (product, compiled_at)

    # Runs are desc by started_at; process per page to find prev succeeded compile
    page_compile_count: dict[str, int] = {}
    for r in runs:
        pid = str(r.page_id)
        if r.compile_status == "succeeded":
            page_compile_count[pid] = page_compile_count.get(pid, 0) + 1

    # Build per-page prev compile (second succeeded compile in desc order)
    page_first_success: dict[str, tuple[CompiledProductSummary | None, str | None]] = {}
    page_second_success: dict[str, tuple[CompiledProductSummary | None, str | None]] = {}
    for r in runs:
        pid = str(r.page_id)
        if r.compile_status == "succeeded":
            product: CompiledProductSummary | None = None
            if r.compiled_version_id:
                product = version_map.get(r.compiled_version_id)
            elif r.id in run_to_version:
                product = version_map.get(run_to_version[r.id])
            compiled_at_str = r.compiled_at.isoformat() if r.compiled_at else None
            if pid not in page_first_success:
                page_first_success[pid] = (product, compiled_at_str)
            elif pid not in page_second_success:
                page_second_success[pid] = (product, compiled_at_str)

    for r in runs:
        pid = str(r.page_id)
        # Determine prev compile to attach: if this run IS the first success, prev = second success
        prev_product: CompiledProductSummary | None = None
        prev_at: str | None = None
        if r.compile_status == "failed":
            # Show the previous succeeded compile alongside this failure
            prev_entry = page_first_success.get(pid)
            if prev_entry:
                prev_product, prev_at = prev_entry
        elif r.compile_status == "succeeded" and page_second_success.get(pid):
            prev_product, prev_at = page_second_success[pid]

        entry = _run_to_response(r, version_map, run_to_version, prev_product, prev_at)
        result.setdefault(pid, []).append(entry)

    return result



@router.post("/confluence/pages/{page_id}/smart-extract", response_model=ExtractionRunResponse)
async def smart_extract_page(
    page_id: uuid.UUID,
    session: SessionDep,
    use_case: Annotated[ExtractKnowledgeFromPageUseCase, Depends(get_extract_use_case)],
    _current_user: Annotated[CurrentUser, Depends(_OWNER_OR_ADMIN)],
) -> ExtractionRunResponse:
    """Return cached run if page unchanged since last extraction, else run fresh LLM extraction."""
    from app.infrastructure.db.models import ConfluencePage as ConfluencePageModel

    page = await session.get(ConfluencePageModel, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="Page not found")

    repo = SqlAlchemyExtractionRunRepository(session)
    runs = await repo.list_by_page(page_id)
    for run in runs:  # sorted desc by started_at
        if (
            run.status is ExtractionStatus.SUCCEEDED
            and run.started_at is not None
            and run.started_at > page.last_modified_at
        ):
            return ExtractionRunResponse(
                id=run.id, page_id=run.page_id, status=run.status.value,
                llm_provider=run.llm_provider, llm_model=run.llm_model,
                structured_draft=run.structured_draft, error_message=run.error_message,
                reused=True,
            )

    try:
        run = await use_case.execute(page_id)
    except ConfluencePageNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return ExtractionRunResponse(
        id=run.id, page_id=run.page_id, status=run.status.value,
        llm_provider=run.llm_provider, llm_model=run.llm_model,
        structured_draft=run.structured_draft, error_message=run.error_message,
        reused=False,
    )


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
        id=run.id, page_id=run.page_id, status=run.status.value,
        llm_provider=run.llm_provider, llm_model=run.llm_model,
        structured_draft=run.structured_draft, error_message=run.error_message,
    )


@router.get("/confluence/pages/{page_id}/extraction-history", response_model=list[ExtractionRunWithProductResponse])
async def get_page_extraction_history(
    page_id: uuid.UUID,
    session: SessionDep,
    _current_user: Annotated[CurrentUser, Depends(_ANY_ROLE)],
) -> list[ExtractionRunWithProductResponse]:
    run_stmt = (
        select(ExtractionRunModel)
        .where(ExtractionRunModel.page_id == page_id)
        .order_by(ExtractionRunModel.started_at.desc())
    )
    runs: list[ExtractionRunModel] = list((await session.execute(run_stmt)).scalars().all())

    version_ids = [r.compiled_version_id for r in runs if r.compiled_version_id]
    run_ids = [r.id for r in runs]
    version_map, run_to_version = await _fetch_compiled_product_map(session, version_ids, run_ids)

    # Find first and second succeeded compile for prev display
    first_success: tuple[CompiledProductSummary | None, str | None] | None = None
    second_success: tuple[CompiledProductSummary | None, str | None] | None = None
    for r in runs:
        if r.compile_status == "succeeded":
            product: CompiledProductSummary | None = None
            if r.compiled_version_id:
                product = version_map.get(r.compiled_version_id)
            elif r.id in run_to_version:
                product = version_map.get(run_to_version[r.id])
            compiled_at_str = r.compiled_at.isoformat() if r.compiled_at else None
            if first_success is None:
                first_success = (product, compiled_at_str)
            elif second_success is None:
                second_success = (product, compiled_at_str)

    result = []
    for r in runs:
        prev_product: CompiledProductSummary | None = None
        prev_at: str | None = None
        if r.compile_status == "failed" and first_success:
            prev_product, prev_at = first_success
        elif r.compile_status == "succeeded" and second_success:
            prev_product, prev_at = second_success
        result.append(_run_to_response(r, version_map, run_to_version, prev_product, prev_at))
    return result


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
    """LLM-merge multiple extraction drafts into one, compile a single KP version, mark runs."""
    repo = SqlAlchemyExtractionRunRepository(session)

    # Collect valid succeeded drafts; track which run_ids contributed
    results: list[ExtractionResult] = []
    contributing_run_ids: list[uuid.UUID] = []
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
        contributing_run_ids.append(run_id)

    if not results:
        raise HTTPException(status_code=422, detail="No succeeded extraction runs found in the provided IDs")

    try:
        merged = results[0]
        for next_result in results[1:]:
            merged = await llm_port.merge(merged, next_result, KNOWLEDGE_EXTRACTION_SCHEMA)

        compile_input = _extraction_result_to_compile_input(
            merged, created_by=payload.created_by, bump=payload.bump, source_extraction_run_id=None,
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
                final_merged, created_by=payload.created_by, bump=payload.bump, source_extraction_run_id=None,
            )
            await compile_use_case.execute(existing.id, final_input)
            product = await repository.get_by_id(existing.id)

        version_id = product.current_version.id
        for run_id in contributing_run_ids:
            await repo.mark_compiled(run_id, version_id, status="succeeded")
        await session.commit()

    except Exception as exc:
        for run_id in contributing_run_ids:
            await repo.mark_compiled(run_id, None, status="failed", error=str(exc))
        await session.commit()
        raise

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
