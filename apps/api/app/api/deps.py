from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.knowledge_product.use_cases import (
    CompareVersionsUseCase,
    CompileNewVersionUseCase,
    CreateKnowledgeProductUseCase,
    GetKnowledgeProductUseCase,
    ListKnowledgeProductsUseCase,
    TransitionStatusUseCase,
)
from app.infrastructure.db.audit import SqlAlchemyAuditLog
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
