from __future__ import annotations

import uuid
from typing import Annotated, Literal

import yaml
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response

from app.api.deps import (
    get_compare_use_case,
    get_compile_use_case,
    get_context_package_use_case,
    get_create_use_case,
    get_decide_approval_use_case,
    get_get_use_case,
    get_list_use_case,
    get_submit_for_review_use_case,
    get_transition_use_case,
)
from app.api.v1.schemas import (
    ApprovalRequestResponse,
    CompileRequest,
    CreateKnowledgeProductRequest,
    DecideApprovalRequest,
    KnowledgeProductResponse,
    KnowledgeProductSummaryResponse,
    KnowledgeProductVersionResponse,
    TransitionRequest,
    UpdateKnowledgeProductRequest,
    VersionDiffResponse,
)
from app.application.context_package.use_cases import GetContextPackageUseCase
from app.application.governance.exceptions import ApprovalRequestNotFound, NoPendingApprovalRequest
from app.application.governance.use_cases import DecideApprovalUseCase, SubmitForReviewUseCase
from app.application.knowledge_product.dto import (
    CompileKnowledgeProductInput,
    CreateKnowledgeProductInput,
    EscalationInput,
    RuleInput,
)
from app.application.knowledge_product.exceptions import (
    KnowledgeProductAlreadyExists,
    KnowledgeProductNotFound,
    KnowledgeProductVersionNotFound,
    KnowledgeProductVersionNotPublished,
)
from app.application.knowledge_product.use_cases import (
    CompareVersionsUseCase,
    CompileNewVersionUseCase,
    CreateKnowledgeProductUseCase,
    GetKnowledgeProductUseCase,
    ListKnowledgeProductsUseCase,
    TransitionStatusUseCase,
)
from app.core.security import CurrentUser, get_current_user, require_roles
from app.domain.governance.value_objects import Role
from app.domain.knowledge_product.value_objects import KnowledgeProductStatus

router = APIRouter(prefix="/knowledge-products", tags=["knowledge-products"])

_OWNER_OR_ADMIN = require_roles(Role.KNOWLEDGE_OWNER, Role.ADMIN)
_REVIEWER_OR_ADMIN = require_roles(Role.REVIEWER, Role.ADMIN)


def _to_compile_input(compile_request: CompileRequest, source_extraction_run_id: uuid.UUID | None = None) -> CompileKnowledgeProductInput:
    return CompileKnowledgeProductInput(
        process_steps=compile_request.process_steps,
        rules=[RuleInput(condition=r.condition, action=r.action) for r in compile_request.rules],
        policies=[RuleInput(condition=p.condition, action=p.action) for p in compile_request.policies],
        sla_target=compile_request.sla_target,
        escalations=[EscalationInput(after=e.after, escalate_to=e.escalate_to) for e in compile_request.escalations],
        roles=compile_request.roles,
        tools=compile_request.tools,
        created_by=compile_request.created_by,
        bump=compile_request.bump,
        source_extraction_run_id=source_extraction_run_id,
    )


@router.get("", response_model=list[KnowledgeProductSummaryResponse])
async def list_knowledge_products(
    use_case: Annotated[ListKnowledgeProductsUseCase, Depends(get_list_use_case)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[KnowledgeProductSummaryResponse]:
    products = await use_case.execute(status=status, search=search, limit=limit, offset=offset)
    return [KnowledgeProductSummaryResponse.from_domain(p) for p in products]


@router.post("", response_model=KnowledgeProductResponse, status_code=201)
async def create_knowledge_product(
    payload: CreateKnowledgeProductRequest,
    use_case: Annotated[CreateKnowledgeProductUseCase, Depends(get_create_use_case)],
    _current_user: Annotated[CurrentUser, Depends(_OWNER_OR_ADMIN)],
) -> KnowledgeProductResponse:
    try:
        product = await use_case.execute(
            CreateKnowledgeProductInput(
                product_key=payload.product_key,
                name=payload.name,
                owner=payload.owner,
                compile_input=_to_compile_input(payload.compile),
            )
        )
    except KnowledgeProductAlreadyExists as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return KnowledgeProductResponse.from_domain(product)


@router.get("/{product_id}", response_model=KnowledgeProductResponse)
async def get_knowledge_product(
    product_id: uuid.UUID,
    use_case: Annotated[GetKnowledgeProductUseCase, Depends(get_get_use_case)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> KnowledgeProductResponse:
    try:
        product = await use_case.execute(product_id)
    except KnowledgeProductNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return KnowledgeProductResponse.from_domain(product)


@router.get("/{product_id}/context")
async def get_context_package(
    product_id: uuid.UUID,
    use_case: Annotated[GetContextPackageUseCase, Depends(get_context_package_use_case)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
    version_id: uuid.UUID | None = Query(default=None),
    format: Literal["json", "yaml"] = Query(default="json"),
):
    try:
        package = await use_case.execute(product_id, version_id)
    except KnowledgeProductNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgeProductVersionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except KnowledgeProductVersionNotPublished as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    if format == "yaml":
        return Response(content=yaml.dump(package, sort_keys=False), media_type="application/x-yaml")
    return package


@router.get("/{product_id}/versions", response_model=list[KnowledgeProductVersionResponse])
async def list_versions(
    product_id: uuid.UUID,
    use_case: Annotated[GetKnowledgeProductUseCase, Depends(get_get_use_case)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> list[KnowledgeProductVersionResponse]:
    try:
        product = await use_case.execute(product_id)
    except KnowledgeProductNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return KnowledgeProductResponse.from_domain(product).versions


@router.put("/{product_id}", response_model=KnowledgeProductResponse)
async def update_knowledge_product(
    product_id: uuid.UUID,
    payload: UpdateKnowledgeProductRequest,
    compile_use_case: Annotated[CompileNewVersionUseCase, Depends(get_compile_use_case)],
    get_use_case: Annotated[GetKnowledgeProductUseCase, Depends(get_get_use_case)],
    _current_user: Annotated[CurrentUser, Depends(_OWNER_OR_ADMIN)],
) -> KnowledgeProductResponse:
    try:
        await compile_use_case.execute(product_id, _to_compile_input(payload.compile))
        product = await get_use_case.execute(product_id)
    except KnowledgeProductNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return KnowledgeProductResponse.from_domain(product)


@router.post("/{product_id}/versions/{version_id}/submit-for-review", response_model=KnowledgeProductResponse)
async def submit_for_review(
    product_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: TransitionRequest,
    use_case: Annotated[SubmitForReviewUseCase, Depends(get_submit_for_review_use_case)],
    _current_user: Annotated[CurrentUser, Depends(_OWNER_OR_ADMIN)],
) -> KnowledgeProductResponse:
    try:
        product, _request = await use_case.execute(product_id, version_id, payload.actor_id)
    except KnowledgeProductNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # domain.DomainError on illegal transition
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return KnowledgeProductResponse.from_domain(product)


@router.post("/{product_id}/approval-requests/{request_id}/decide", response_model=ApprovalRequestResponse)
async def decide_approval(
    product_id: uuid.UUID,
    request_id: uuid.UUID,
    payload: DecideApprovalRequest,
    use_case: Annotated[DecideApprovalUseCase, Depends(get_decide_approval_use_case)],
    current_user: Annotated[CurrentUser, Depends(_REVIEWER_OR_ADMIN)],
) -> ApprovalRequestResponse:
    try:
        _product, request = await use_case.execute(
            product_id, request_id, current_user.user_id, payload.decision, payload.comment
        )
    except ApprovalRequestNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (NoPendingApprovalRequest, KnowledgeProductNotFound) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ApprovalRequestResponse.from_domain(request)


@router.post("/{product_id}/versions/{version_id}/publish", response_model=KnowledgeProductResponse)
async def publish(
    product_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: TransitionRequest,
    use_case: Annotated[TransitionStatusUseCase, Depends(get_transition_use_case)],
    _current_user: Annotated[CurrentUser, Depends(_OWNER_OR_ADMIN)],
) -> KnowledgeProductResponse:
    return await _transition(use_case, product_id, version_id, KnowledgeProductStatus.PUBLISHED, payload.actor_id)


@router.post("/{product_id}/versions/{version_id}/retire", response_model=KnowledgeProductResponse)
async def retire(
    product_id: uuid.UUID,
    version_id: uuid.UUID,
    payload: TransitionRequest,
    use_case: Annotated[TransitionStatusUseCase, Depends(get_transition_use_case)],
    _current_user: Annotated[CurrentUser, Depends(_OWNER_OR_ADMIN)],
) -> KnowledgeProductResponse:
    return await _transition(use_case, product_id, version_id, KnowledgeProductStatus.RETIRED, payload.actor_id)


async def _transition(
    use_case: TransitionStatusUseCase,
    product_id: uuid.UUID,
    version_id: uuid.UUID,
    target: KnowledgeProductStatus,
    actor_id: uuid.UUID,
) -> KnowledgeProductResponse:
    try:
        product = await use_case.execute(product_id, version_id, target, actor_id)
    except KnowledgeProductNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:  # domain.DomainError on illegal transition
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return KnowledgeProductResponse.from_domain(product)


@router.get("/{product_id}/versions/{from_version_id}/diff/{to_version_id}", response_model=VersionDiffResponse)
async def compare_versions(
    product_id: uuid.UUID,
    from_version_id: uuid.UUID,
    to_version_id: uuid.UUID,
    use_case: Annotated[CompareVersionsUseCase, Depends(get_compare_use_case)],
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> VersionDiffResponse:
    try:
        diff = await use_case.execute(product_id, from_version_id, to_version_id)
    except KnowledgeProductNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return VersionDiffResponse(diff=diff)
