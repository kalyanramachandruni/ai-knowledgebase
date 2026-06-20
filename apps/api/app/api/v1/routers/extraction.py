from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_compile_from_extraction_use_case, get_extract_use_case
from app.api.v1.extraction_schemas import CompileFromExtractionRequest, ExtractionRunResponse
from app.api.v1.schemas import KnowledgeProductResponse
from app.application.extraction.compiler import CompileFromExtractionUseCase
from app.application.extraction.exceptions import (
    ConfluencePageNotFound,
    ExtractionRunNotFound,
    ExtractionRunNotSucceeded,
)
from app.application.extraction.use_cases import ExtractKnowledgeFromPageUseCase

router = APIRouter(tags=["extraction"])


@router.post("/confluence/pages/{page_id}/extract", response_model=ExtractionRunResponse)
async def extract_page(
    page_id: uuid.UUID,
    use_case: Annotated[ExtractKnowledgeFromPageUseCase, Depends(get_extract_use_case)],
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


@router.post("/extraction-runs/{run_id}/compile", response_model=KnowledgeProductResponse)
async def compile_from_extraction(
    run_id: uuid.UUID,
    payload: CompileFromExtractionRequest,
    use_case: Annotated[CompileFromExtractionUseCase, Depends(get_compile_from_extraction_use_case)],
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
