from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.confluence.use_cases import SyncConfluenceSpaceUseCase
from app.application.context_package.generator import ContextPackageGenerator
from app.application.context_package.use_cases import GetContextPackageUseCase
from app.application.extraction.compiler import CompileFromExtractionUseCase
from app.application.extraction.use_cases import ExtractKnowledgeFromPageUseCase
from app.application.governance.use_cases import DecideApprovalUseCase, SubmitForReviewUseCase
from app.application.knowledge_product.use_cases import (
    CompareVersionsUseCase,
    CompileNewVersionUseCase,
    CreateKnowledgeProductUseCase,
    GetKnowledgeProductUseCase,
    ListKnowledgeProductsUseCase,
    TransitionStatusUseCase,
)
from app.core.config import settings
from app.domain.extraction.ports import LLMExtractionPort
from app.infrastructure.cache.client import redis_client
from app.infrastructure.cache.redis_cache import RedisContextPackageCache
from app.infrastructure.confluence.client import ConfluenceApiClient
from app.infrastructure.db.audit import SqlAlchemyAuditLog
from app.infrastructure.db.confluence_repository import (
    SqlAlchemyConfluencePageRepository,
    SqlAlchemyConfluenceSpaceRepository,
)
from app.infrastructure.db.extraction_repository import SqlAlchemyExtractionRunRepository
from app.infrastructure.db.governance_repository import SqlAlchemyApprovalRequestRepository
from app.infrastructure.db.outbox import SqlAlchemyEventOutbox
from app.infrastructure.db.repository import SqlAlchemyKnowledgeProductRepository
from app.infrastructure.db.session import get_session
from app.infrastructure.llm.factory import get_llm_extraction_port

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def get_repository(session: SessionDep) -> SqlAlchemyKnowledgeProductRepository:
    return SqlAlchemyKnowledgeProductRepository(session)


def get_audit_log(session: SessionDep) -> SqlAlchemyAuditLog:
    return SqlAlchemyAuditLog(session)


RepositoryDep = Annotated[SqlAlchemyKnowledgeProductRepository, Depends(get_repository)]
AuditDep = Annotated[SqlAlchemyAuditLog, Depends(get_audit_log)]


def get_create_use_case(repository: RepositoryDep, audit: AuditDep) -> CreateKnowledgeProductUseCase:
    return CreateKnowledgeProductUseCase(repository, audit)


def get_compile_use_case(repository: RepositoryDep, audit: AuditDep) -> CompileNewVersionUseCase:
    return CompileNewVersionUseCase(repository, audit)


def get_transition_use_case(repository: RepositoryDep, audit: AuditDep) -> TransitionStatusUseCase:
    return TransitionStatusUseCase(repository, audit)


def get_get_use_case(repository: RepositoryDep) -> GetKnowledgeProductUseCase:
    return GetKnowledgeProductUseCase(repository)


def get_list_use_case(repository: RepositoryDep) -> ListKnowledgeProductsUseCase:
    return ListKnowledgeProductsUseCase(repository)


def get_compare_use_case(repository: RepositoryDep) -> CompareVersionsUseCase:
    return CompareVersionsUseCase(repository)


def get_confluence_client() -> ConfluenceApiClient:
    return ConfluenceApiClient(
        base_url=settings.confluence_base_url,
        user_email=settings.confluence_user_email,
        api_token=settings.confluence_api_token,
    )


def get_confluence_space_repository(session: SessionDep) -> SqlAlchemyConfluenceSpaceRepository:
    return SqlAlchemyConfluenceSpaceRepository(session)


def get_confluence_page_repository(session: SessionDep) -> SqlAlchemyConfluencePageRepository:
    return SqlAlchemyConfluencePageRepository(session)


def get_event_outbox(session: SessionDep) -> SqlAlchemyEventOutbox:
    return SqlAlchemyEventOutbox(session)


def get_sync_confluence_space_use_case(
    client: Annotated[ConfluenceApiClient, Depends(get_confluence_client)],
    space_repository: Annotated[SqlAlchemyConfluenceSpaceRepository, Depends(get_confluence_space_repository)],
    page_repository: Annotated[SqlAlchemyConfluencePageRepository, Depends(get_confluence_page_repository)],
    outbox: Annotated[SqlAlchemyEventOutbox, Depends(get_event_outbox)],
) -> SyncConfluenceSpaceUseCase:
    return SyncConfluenceSpaceUseCase(client, space_repository, page_repository, outbox)


def get_llm_port() -> LLMExtractionPort:
    return get_llm_extraction_port()


def get_extraction_repository(session: SessionDep) -> SqlAlchemyExtractionRunRepository:
    return SqlAlchemyExtractionRunRepository(session)


def _current_llm_model() -> str:
    return settings.anthropic_model if settings.llm_provider == "anthropic" else settings.openai_model


def get_extract_use_case(
    page_repository: Annotated[SqlAlchemyConfluencePageRepository, Depends(get_confluence_page_repository)],
    extraction_repository: Annotated[SqlAlchemyExtractionRunRepository, Depends(get_extraction_repository)],
    llm_port: Annotated[LLMExtractionPort, Depends(get_llm_port)],
    outbox: Annotated[SqlAlchemyEventOutbox, Depends(get_event_outbox)],
) -> ExtractKnowledgeFromPageUseCase:
    return ExtractKnowledgeFromPageUseCase(
        page_repository,
        extraction_repository,
        llm_port,
        outbox,
        llm_provider=settings.llm_provider,
        llm_model=_current_llm_model(),
    )


def get_compile_from_extraction_use_case(
    extraction_repository: Annotated[SqlAlchemyExtractionRunRepository, Depends(get_extraction_repository)],
    repository: RepositoryDep,
    create_use_case: Annotated[CreateKnowledgeProductUseCase, Depends(get_create_use_case)],
    compile_use_case: Annotated[CompileNewVersionUseCase, Depends(get_compile_use_case)],
) -> CompileFromExtractionUseCase:
    return CompileFromExtractionUseCase(extraction_repository, repository, create_use_case, compile_use_case)


def get_context_package_cache() -> RedisContextPackageCache:
    return RedisContextPackageCache(redis_client)


def get_context_package_generator() -> ContextPackageGenerator:
    return ContextPackageGenerator()


def get_context_package_use_case(
    repository: RepositoryDep,
    cache: Annotated[RedisContextPackageCache, Depends(get_context_package_cache)],
    generator: Annotated[ContextPackageGenerator, Depends(get_context_package_generator)],
) -> GetContextPackageUseCase:
    return GetContextPackageUseCase(repository, cache, generator)


def get_approval_repository(session: SessionDep) -> SqlAlchemyApprovalRequestRepository:
    return SqlAlchemyApprovalRequestRepository(session)


ApprovalRepositoryDep = Annotated[SqlAlchemyApprovalRequestRepository, Depends(get_approval_repository)]


def get_submit_for_review_use_case(
    repository: RepositoryDep,
    approval_repository: ApprovalRepositoryDep,
    audit: AuditDep,
    outbox: Annotated[SqlAlchemyEventOutbox, Depends(get_event_outbox)],
) -> SubmitForReviewUseCase:
    return SubmitForReviewUseCase(repository, approval_repository, audit, outbox)


def get_decide_approval_use_case(
    repository: RepositoryDep,
    approval_repository: ApprovalRepositoryDep,
    audit: AuditDep,
    outbox: Annotated[SqlAlchemyEventOutbox, Depends(get_event_outbox)],
) -> DecideApprovalUseCase:
    return DecideApprovalUseCase(repository, approval_repository, audit, outbox)
