from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.confluence.use_cases import SyncConfluenceSpaceUseCase
from app.application.knowledge_product.use_cases import (
    CompareVersionsUseCase,
    CompileNewVersionUseCase,
    CreateKnowledgeProductUseCase,
    GetKnowledgeProductUseCase,
    ListKnowledgeProductsUseCase,
    TransitionStatusUseCase,
)
from app.core.config import settings
from app.infrastructure.confluence.client import ConfluenceApiClient
from app.infrastructure.db.audit import SqlAlchemyAuditLog
from app.infrastructure.db.confluence_repository import (
    SqlAlchemyConfluencePageRepository,
    SqlAlchemyConfluenceSpaceRepository,
)
from app.infrastructure.db.outbox import SqlAlchemyEventOutbox
from app.infrastructure.db.repository import SqlAlchemyKnowledgeProductRepository
from app.infrastructure.db.session import get_session

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
