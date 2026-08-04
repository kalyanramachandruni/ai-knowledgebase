from __future__ import annotations

import json
import logging
import uuid
from typing import Annotated, AsyncGenerator

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
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
from app.domain.extraction.entities import ExtractionStatus, PageSourceType
from app.domain.extraction.ports import ExtractionResult, LLMExtractionPort
from app.domain.extraction.schema import KNOWLEDGE_EXTRACTION_SCHEMA
from app.domain.governance.value_objects import Role
from app.domain.knowledge_product.value_objects import VersionBump
from app.infrastructure.db.extraction_repository import SqlAlchemyExtractionRunRepository
from app.infrastructure.db.models import KnowledgeProductModel, KnowledgeProductVersionModel
from app.infrastructure.db.repository import SqlAlchemyKnowledgeProductRepository

router = APIRouter(tags=["extraction"])

_OWNER_OR_ADMIN = require_roles(Role.KNOWLEDGE_OWNER, Role.ADMIN)
_ANY_ROLE = require_roles(Role.KNOWLEDGE_OWNER, Role.ADMIN, Role.REVIEWER, Role.CONSUMER)


async def _confluence_page_url(page, session) -> str | None:
    """Build the canonical Confluence page URL by loading the parent space."""
    if page is None:
        return None
    try:
        from app.infrastructure.db.models import ConfluenceSpace as ConfluenceSpaceModel
        space = await session.get(ConfluenceSpaceModel, page.space_id)
        if space and space.base_url:
            return f"{space.base_url.rstrip('/')}/wiki/pages/{page.confluence_page_id}"
        return None
    except Exception:
        return None


async def _fetch_version_map(
    session: AsyncSession,
    version_ids: list[uuid.UUID],
    entry_ids_for_fk: list[uuid.UUID],
) -> tuple[dict[uuid.UUID, CompiledProductSummary], dict[uuid.UUID, uuid.UUID]]:
    """
    Returns (version_id→summary, entry_id→version_id).
    Looks up via both compiled_version_id and legacy source_extraction_entry_id FK.
    """
    version_map: dict[uuid.UUID, CompiledProductSummary] = {}
    entry_to_version: dict[uuid.UUID, uuid.UUID] = {}

    all_version_ids = list(set(version_ids))
    if entry_ids_for_fk:
        fk_stmt = (
            select(KnowledgeProductVersionModel, KnowledgeProductModel)
            .join(KnowledgeProductModel, KnowledgeProductVersionModel.product_id == KnowledgeProductModel.id)
            .where(KnowledgeProductVersionModel.source_extraction_entry_id.in_(entry_ids_for_fk))
        )
        for version, product in (await session.execute(fk_stmt)).all():
            vid = version.id
            entry_to_version[version.source_extraction_entry_id] = vid
            if vid not in all_version_ids:
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

    return version_map, entry_to_version


def _run_to_response(
    r,  # ExtractionRun domain entity
    version_map: dict[uuid.UUID, CompiledProductSummary],
    entry_to_version: dict[uuid.UUID, uuid.UUID],
    prev_compiled_product: CompiledProductSummary | None = None,
    prev_compiled_at: str | None = None,
) -> ExtractionRunWithProductResponse:
    compiled_product: CompiledProductSummary | None = None
    if r.compiled_version_id:
        compiled_product = version_map.get(r.compiled_version_id)
    elif r.id in entry_to_version:
        compiled_product = version_map.get(entry_to_version[r.id])

    return ExtractionRunWithProductResponse(
        id=r.id, page_id=r.page_id, status=r.status.value if hasattr(r.status, "value") else r.status,
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

    repo = SqlAlchemyExtractionRunRepository(session)
    all_runs = await repo.list_by_pages(page_ids)
    runs = [r for r in all_runs if r.page_source_type == PageSourceType.CONFLUENCE]

    version_ids = [r.compiled_version_id for r in runs if r.compiled_version_id]
    entry_ids = [r.id for r in runs]
    version_map, entry_to_version = await _fetch_version_map(session, version_ids, entry_ids)

    page_first_success: dict[str, tuple[CompiledProductSummary | None, str | None]] = {}
    page_second_success: dict[str, tuple[CompiledProductSummary | None, str | None]] = {}
    for r in runs:
        pid = str(r.page_id)
        if r.compile_status == "succeeded":
            product: CompiledProductSummary | None = None
            if r.compiled_version_id:
                product = version_map.get(r.compiled_version_id)
            elif r.id in entry_to_version:
                product = version_map.get(entry_to_version[r.id])
            compiled_at_str = r.compiled_at.isoformat() if r.compiled_at else None
            if pid not in page_first_success:
                page_first_success[pid] = (product, compiled_at_str)
            elif pid not in page_second_success:
                page_second_success[pid] = (product, compiled_at_str)

    result: dict[str, list[ExtractionRunWithProductResponse]] = {}
    for r in runs:
        pid = str(r.page_id)
        prev_product: CompiledProductSummary | None = None
        prev_at: str | None = None
        if r.compile_status == "failed":
            prev_entry = page_first_success.get(pid)
            if prev_entry:
                prev_product, prev_at = prev_entry
        elif r.compile_status == "succeeded" and page_second_success.get(pid):
            prev_product, prev_at = page_second_success[pid]

        entry = _run_to_response(r, version_map, entry_to_version, prev_product, prev_at)
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
        started = run.started_at
        if started and started.tzinfo is None:
            from datetime import timezone as _tz
            started = started.replace(tzinfo=_tz.utc)
        lm = page.last_modified_at
        if lm and lm.tzinfo is None:
            from datetime import timezone as _tz
            lm = lm.replace(tzinfo=_tz.utc)
        if (
            run.status is ExtractionStatus.SUCCEEDED
            and started is not None
            and started > lm
        ):
            return ExtractionRunResponse(
                id=run.id, page_id=run.page_id, status=run.status.value,
                llm_provider=run.llm_provider, llm_model=run.llm_model,
                structured_draft=run.structured_draft, error_message=run.error_message,
                reused=True,
            )

    try:
        run = await use_case.execute(page_id, source_url=await _confluence_page_url(page, session))
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
    session: SessionDep,
    use_case: Annotated[ExtractKnowledgeFromPageUseCase, Depends(get_extract_use_case)],
    _current_user: Annotated[CurrentUser, Depends(_OWNER_OR_ADMIN)],
) -> ExtractionRunResponse:
    from app.infrastructure.db.models import ConfluencePage as ConfluencePageModel
    page = await session.get(ConfluencePageModel, page_id)
    try:
        run = await use_case.execute(page_id, source_url=await _confluence_page_url(page, session))
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
    repo = SqlAlchemyExtractionRunRepository(session)
    runs = await repo.list_by_page(page_id)
    runs = [r for r in runs if r.page_source_type == PageSourceType.CONFLUENCE]

    version_ids = [r.compiled_version_id for r in runs if r.compiled_version_id]
    entry_ids = [r.id for r in runs]
    version_map, entry_to_version = await _fetch_version_map(session, version_ids, entry_ids)

    first_success: tuple[CompiledProductSummary | None, str | None] | None = None
    second_success: tuple[CompiledProductSummary | None, str | None] | None = None
    for r in runs:
        if r.compile_status == "succeeded":
            product: CompiledProductSummary | None = None
            if r.compiled_version_id:
                product = version_map.get(r.compiled_version_id)
            elif r.id in entry_to_version:
                product = version_map.get(entry_to_version[r.id])
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
        result.append(_run_to_response(r, version_map, entry_to_version, prev_product, prev_at))
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

        await session.commit()

    except Exception as exc:
        await session.commit()
        raise

    return KnowledgeProductResponse.from_domain(product)


@router.get("/extraction-runs/{run_id}", response_model=ExtractionRunWithProductResponse)
async def get_extraction_run(
    run_id: uuid.UUID,
    session: SessionDep,
    _current_user: Annotated[CurrentUser, Depends(_ANY_ROLE)],
) -> ExtractionRunWithProductResponse:
    repo = SqlAlchemyExtractionRunRepository(session)
    run = await repo.get_by_id(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Extraction run not found")
    return ExtractionRunWithProductResponse(
        id=run.id,
        page_id=run.page_id,
        status=run.status.value if hasattr(run.status, "value") else run.status,
        llm_provider=run.llm_provider,
        llm_model=run.llm_model,
        structured_draft=run.structured_draft,
        error_message=run.error_message,
        started_at=run.started_at.isoformat() if run.started_at else None,
        compiled_product=None,
        compiled_at=run.compiled_at.isoformat() if run.compiled_at else None,
        compile_status=run.compile_status,
        compile_error=run.compile_error,
        compiled_version_id=str(run.compiled_version_id) if run.compiled_version_id else None,
    )


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


# ---------------------------------------------------------------------------
# SSE streaming compile endpoint
# ---------------------------------------------------------------------------

class BatchCompileStreamItem(BaseModel):
    run_id: uuid.UUID
    page_id: uuid.UUID


class BatchCompileStreamRequest(BaseModel):
    items: list[BatchCompileStreamItem]
    product_key: str
    name: str
    owner: str
    created_by: uuid.UUID
    bump: VersionBump = VersionBump.MINOR
    force: bool = False  # when True, ignores current draft and starts from last published version
    brief: str | None = None  # optional product description used to filter irrelevant pages during merge


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.post("/extraction-runs/batch-compile-stream")
async def batch_compile_stream(
    payload: BatchCompileStreamRequest,
    session: SessionDep,
    llm_port: Annotated[LLMExtractionPort, Depends(get_llm_port)],
    repository: Annotated[SqlAlchemyKnowledgeProductRepository, Depends(get_repository)],
    create_use_case: Annotated[CreateKnowledgeProductUseCase, Depends(get_create_use_case)],
    compile_use_case: Annotated[CompileNewVersionUseCase, Depends(get_compile_use_case)],
    _current_user: Annotated[CurrentUser, Depends(_OWNER_OR_ADMIN)],
) -> StreamingResponse:
    """SSE endpoint — streams per-page merge progress then emits a final done event."""

    async def generate() -> AsyncGenerator[str, None]:
        from sqlalchemy import select as sa_select
        from app.infrastructure.db.models import CompileSession, CompileSessionEntry, ConfluencePage
        from app.core.config import settings as _settings

        repo = SqlAlchemyExtractionRunRepository(session)
        total = len(payload.items)
        logger.info("[compile-stream] starting: product_key=%r items=%d", payload.product_key, total)
        yield _sse({"type": "start", "total": total})

        # Pre-load page titles for compile session entries
        from app.infrastructure.db.models import WebPage as WebPageModel
        page_ids = [item.page_id for item in payload.items]
        page_titles: dict[uuid.UUID, str] = {}  # page_id → title
        if page_ids:
            # Confluence pages
            conf_rows = (await session.execute(
                sa_select(ConfluencePage.id, ConfluencePage.title)
                .where(ConfluencePage.id.in_(page_ids))
            )).all()
            for r in conf_rows:
                page_titles[r.id] = r.title
            # Web pages
            missing_ids = [pid for pid in page_ids if pid not in page_titles]
            if missing_ids:
                web_rows = (await session.execute(
                    sa_select(WebPageModel.id, WebPageModel.title)
                    .where(WebPageModel.id.in_(missing_ids))
                )).all()
                for r in web_rows:
                    page_titles[r.id] = r.title or ""

        # Pre-load all drafts from DB before any LLM calls
        drafts: list[tuple[uuid.UUID, uuid.UUID, ExtractionResult]] = []
        for item in payload.items:
            run = await repo.get_by_id(item.run_id)
            if run is None:
                logger.warning("[compile-stream] run not found: run_id=%s page_id=%s", item.run_id, item.page_id)
                yield _sse({"type": "skipped", "run_id": str(item.run_id), "page_id": str(item.page_id), "reason": "run not found"})
                continue
            if run.status is not ExtractionStatus.SUCCEEDED:
                logger.warning("[compile-stream] run not succeeded: run_id=%s status=%s", item.run_id, run.status)
                yield _sse({"type": "skipped", "run_id": str(item.run_id), "page_id": str(item.page_id), "reason": f"status={run.status}"})
                continue
            if not run.structured_draft:
                logger.warning("[compile-stream] run has no draft: run_id=%s", item.run_id)
                yield _sse({"type": "skipped", "run_id": str(item.run_id), "page_id": str(item.page_id), "reason": "no structured draft"})
                continue
            logger.debug("[compile-stream] loaded draft: run_id=%s page_id=%s", item.run_id, item.page_id)
            d = run.structured_draft
            drafts.append((item.run_id, item.page_id, ExtractionResult(
                process_overview=d.get("process_overview", {}),
                process_steps=d.get("process_steps", []),
                rules=d.get("rules", []),
                policies=d.get("policies", []),
                sla_target=d.get("sla_target"),
                escalations=d.get("escalations", []),
                roles=d.get("roles", []),
                tools=d.get("tools", []),
                raw_model_output=d,
            )))

        logger.info("[compile-stream] drafts loaded: %d/%d eligible", len(drafts), total)

        if not drafts:
            logger.error("[compile-stream] no eligible drafts — aborting")
            yield _sse({"type": "error", "message": "No succeeded extraction runs found"})
            return

        # Incremental compile using a SINGLE draft version updated in place.
        # One semver bump total; yaml_content is overwritten after each page merge.
        # If interrupted, work up to that point is persisted in the draft.

        _bootstrap_entry: tuple[uuid.UUID, uuid.UUID] | None = None

        try:
            # Step 1 — ensure KP exists and get/create the draft version
            existing = await repository.get_by_key(payload.product_key)
            new_kp = existing is None
            if new_kp:
                logger.info("[compile-stream] creating new KP: product_key=%r", payload.product_key)
                # Bootstrap with first page's content; we'll overwrite this immediately
                first_input = _extraction_result_to_compile_input(
                    drafts[0][2], created_by=payload.created_by, bump=payload.bump, source_extraction_run_id=None,
                )
                product = await create_use_case.execute(
                    CreateKnowledgeProductInput(
                        product_key=payload.product_key,
                        name=payload.name,
                        owner=payload.owner,
                        compile_input=first_input,
                    )
                )
                # First page already baked in — skip it in the loop
                bootstrap_run_id, bootstrap_page_id, _ = drafts[0]
                drafts = drafts[1:]
                draft_version_id = product.current_version.id
                current_merged: ExtractionResult = _version_to_extraction_result(product.current_version)
                draft_semver = str(product.current_version.semver)
                product_id = str(product.id)

                _bootstrap_entry = (bootstrap_run_id, bootstrap_page_id)
                await session.commit()
                logger.info("[compile-stream] bootstrap page compiled: version_id=%s semver=%s", draft_version_id, draft_semver)
                bootstrap_total = len(drafts) + 1  # drafts already has first page removed
                yield _sse({
                    "type": "page_compiled",
                    "run_id": str(bootstrap_run_id),
                    "page_id": str(bootstrap_page_id),
                    "index": 1,
                    "total": bootstrap_total,
                    "product_id": product_id,
                    "product_key": payload.product_key,
                    "semver": draft_semver,
                })
            else:
                from app.domain.knowledge_product.value_objects import KnowledgeProductStatus as KPStatus

                published = [v for v in existing.versions if v.status is KPStatus.PUBLISHED]
                existing_draft = next(
                    (v for v in reversed(existing.versions) if v.status is KPStatus.DRAFT), None
                )

                if payload.force:
                    # force=True: reset content to last published version (or empty).
                    # Reuse the existing draft row if one exists — no new version row, no orphan.
                    base_version = published[-1] if published else None
                    base_result = _version_to_extraction_result(base_version) if base_version else drafts[0][2]
                    logger.info(
                        "[compile-stream] force=True — resetting draft to base: %s",
                        str(base_version.semver) if base_version else "empty",
                    )
                    if existing_draft:
                        # Reset existing draft content to the published base in place
                        from app.application.knowledge_product.use_cases import _compile_args as _build_compile_args
                        from app.domain.knowledge_product.entities import KnowledgeProductVersion as KPVersion
                        from app.domain.knowledge_product.value_objects import SemVer
                        base_input = _extraction_result_to_compile_input(
                            base_result, created_by=payload.created_by, bump=payload.bump, source_extraction_run_id=None,
                        )
                        args = _build_compile_args(base_input)
                        tmp = KPVersion(
                            id=existing_draft.id,
                            product_id=existing.id,
                            semver=existing_draft.semver,
                            process_steps=args["process_steps"],
                            rules=args["rules"],
                            policies=args["policies"],
                            sla=args["sla"],
                            escalations=args["escalations"],
                            roles=args["roles"],
                            tools=args["tools"],
                            created_by=payload.created_by,
                            process_overview=args.get("process_overview", {}),
                        )
                        reset_yaml = tmp.to_canonical_dict(
                            product_key=existing.product_key,
                            name=existing.name,
                            owner=existing.owner,
                        )
                        await repository.update_draft_content(existing_draft.id, reset_yaml)
                        await session.commit()
                        draft_version_id = existing_draft.id
                        draft_semver = str(existing_draft.semver)
                        logger.info("[compile-stream] existing draft reset in place: version_id=%s semver=%s", draft_version_id, draft_semver)
                    else:
                        # No draft exists yet — create one
                        await compile_use_case.execute(
                            existing.id,
                            _extraction_result_to_compile_input(
                                base_result, created_by=payload.created_by, bump=payload.bump, source_extraction_run_id=None,
                            ),
                        )
                        product = await repository.get_by_id(existing.id)
                        draft_version_id = product.current_version.id
                        draft_semver = str(product.current_version.semver)
                        await session.commit()
                        logger.info("[compile-stream] new draft created: version_id=%s semver=%s", draft_version_id, draft_semver)
                else:
                    # force=False: resume from current version (may be draft or published)
                    base_result = _version_to_extraction_result(existing.current_version)
                    logger.info("[compile-stream] resume — base: %s", existing.current_version.semver)
                    if existing_draft:
                        # Continue merging into the existing draft
                        draft_version_id = existing_draft.id
                        draft_semver = str(existing_draft.semver)
                        logger.info("[compile-stream] resuming into existing draft: version_id=%s", draft_version_id)
                    else:
                        # No draft — create one
                        await compile_use_case.execute(
                            existing.id,
                            _extraction_result_to_compile_input(
                                base_result, created_by=payload.created_by, bump=payload.bump, source_extraction_run_id=None,
                            ),
                        )
                        product = await repository.get_by_id(existing.id)
                        draft_version_id = product.current_version.id
                        draft_semver = str(product.current_version.semver)
                        await session.commit()
                        logger.info("[compile-stream] new draft created for resume: version_id=%s semver=%s", draft_version_id, draft_semver)

                current_merged = base_result
                product_id = str(existing.id)

        except Exception as exc:
            logger.exception("[compile-stream] failed to initialise draft: %s", exc)
            yield _sse({"type": "error", "message": f"Failed to initialise draft: {exc}"})
            return

        # Step 2 — create compile session + detect discarded pages
        from app.application.knowledge_product.use_cases import _compile_args as _build_compile_args
        from app.domain.knowledge_product.entities import KnowledgeProductVersion as KPVersion
        from app.domain.knowledge_product.value_objects import SemVer
        from datetime import datetime, timezone as tz

        _llm_provider = _settings.llm_provider
        _llm_model = _settings.anthropic_model if _llm_provider == "anthropic" else _settings.openai_model

        # Resolve knowledge_product_id from product_id string
        _kp_id: uuid.UUID | None = None
        try:
            _kp_id = uuid.UUID(product_id)
        except Exception:
            pass

        compile_session_obj = CompileSession(
            id=uuid.uuid4(),
            version_id=draft_version_id,
            knowledge_product_id=_kp_id,
            product_name=payload.name,
            llm_provider=_llm_provider,
            llm_model=_llm_model,
            status="running",
            started_at=datetime.now(tz.utc),
            created_by=payload.created_by,
        )
        session.add(compile_session_obj)
        await session.flush()
        compile_session_id = compile_session_obj.id

        # Find pages already compiled into this version in a PREVIOUS session (only relevant without force)
        already_compiled_page_ids: set[uuid.UUID] = set()
        if not payload.force:
            prior_entries = (await session.execute(
                sa_select(CompileSessionEntry.page_id)
                .join(CompileSession, CompileSession.id == CompileSessionEntry.session_id)
                .where(CompileSession.version_id == draft_version_id)
                .where(CompileSession.id != compile_session_id)
                .where(CompileSessionEntry.status == "compiled")
            )).scalars().all()
            already_compiled_page_ids = set(prior_entries)

        total_pages = len(drafts) + (1 if new_kp else 0)

        # Emit discarded events for pages that were already compiled in a prior session
        discarded_page_ids: set[uuid.UUID] = set()
        for run_id, page_id, _ in drafts:
            if page_id in already_compiled_page_ids:
                session.add(CompileSessionEntry(
                    session_id=compile_session_id,
                    entry_id=run_id,
                    page_id=page_id,
                    page_title=page_titles.get(page_id, ""),
                    status="discarded",
                    reason="already compiled in a previous session",
                    compiled_at=None,
                ))
                discarded_page_ids.add(page_id)
                yield _sse({"type": "discarded", "run_id": str(run_id), "page_id": str(page_id), "reason": "already compiled in previous session"})

        # Record bootstrap page in compile session (if new KP, the first page was pre-compiled above)
        if new_kp and _bootstrap_entry:
            _bs_run, _bs_page = _bootstrap_entry
            session.add(CompileSessionEntry(
                session_id=compile_session_id,
                entry_id=_bs_run,
                page_id=_bs_page,
                page_title=page_titles.get(_bs_page, ""),
                status="compiled",
                compiled_at=datetime.now(tz.utc),
            ))

        await session.flush()
        # Remove discarded pages from the work list
        drafts = [(r, p, res) for r, p, res in drafts if p not in discarded_page_ids]
        logger.info("[compile-stream] session created: session_id=%s discarded=%d remaining=%d", compile_session_id, len(discarded_page_ids), len(drafts))

        for idx, (run_id, page_id, result) in enumerate(drafts):
            page_num = idx + (2 if new_kp else 1)
            logger.info("[compile-stream] page %d/%d: merging run_id=%s page_id=%s", page_num, total_pages, run_id, page_id)
            yield _sse({"type": "merging", "run_id": str(run_id), "page_id": str(page_id), "index": page_num, "total": total_pages})
            try:
                current_merged = await llm_port.merge(current_merged, result, KNOWLEDGE_EXTRACTION_SCHEMA, brief=payload.brief)

                # Build canonical yaml_content via a temporary domain object — same shape as save()
                compile_input = _extraction_result_to_compile_input(
                    current_merged, created_by=payload.created_by, bump=VersionBump.MINOR, source_extraction_run_id=None,
                )
                args = _build_compile_args(compile_input)
                tmp_version = KPVersion(
                    id=draft_version_id,
                    product_id=uuid.UUID(product_id),
                    semver=SemVer(*[int(x) for x in draft_semver.split(".")]),
                    process_steps=args["process_steps"],
                    rules=args["rules"],
                    policies=args["policies"],
                    sla=args["sla"],
                    escalations=args["escalations"],
                    roles=args["roles"],
                    tools=args["tools"],
                    created_by=payload.created_by,
                    process_overview=args.get("process_overview", {}),
                )
                new_yaml = tmp_version.to_canonical_dict(
                    product_key=payload.product_key,
                    name=payload.name,
                    owner=payload.owner,
                )

                now = datetime.now(tz.utc)
                await repository.update_draft_content(draft_version_id, new_yaml)
                session.add(CompileSessionEntry(
                    session_id=compile_session_id,
                    entry_id=run_id,
                    page_id=page_id,
                    page_title=page_titles.get(page_id, ""),
                    status="compiled",
                    compiled_at=now,
                ))
                await session.commit()
                logger.info("[compile-stream] page %d/%d merged into draft version_id=%s", page_num, total_pages, draft_version_id)
                yield _sse({
                    "type": "page_compiled",
                    "run_id": str(run_id),
                    "page_id": str(page_id),
                    "index": page_num,
                    "total": total_pages,
                    "product_id": product_id,
                    "product_key": payload.product_key,
                    "semver": draft_semver,
                })
            except Exception as exc:
                logger.exception("[compile-stream] page %d FAILED run_id=%s: %s", page_num, run_id, exc)
                try:
                    session.add(CompileSessionEntry(
                        session_id=compile_session_id,
                        entry_id=run_id,
                        page_id=page_id,
                        page_title=page_titles.get(page_id, ""),
                        status="skipped",
                        reason=str(exc),
                    ))
                    await session.commit()
                except Exception:
                    logger.exception("[compile-stream] also failed to mark run as failed")
                yield _sse({"type": "page_error", "run_id": str(run_id), "page_id": str(page_id), "index": page_num, "total": total_pages, "message": str(exc)})

        logger.info("[compile-stream] all pages processed — product_id=%s draft_version=%s", product_id, draft_version_id)
        yield _sse({"type": "done", "product_id": product_id, "product_key": payload.product_key, "name": payload.name, "semver": draft_semver})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
