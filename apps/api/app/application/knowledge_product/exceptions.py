from __future__ import annotations


class ApplicationError(Exception):
    """Base class for application-layer errors (distinct from app.domain.shared.base.DomainError —
    this layer raises for things like "not found", which aren't domain rule violations)."""


class KnowledgeProductNotFound(ApplicationError):
    pass


class KnowledgeProductAlreadyExists(ApplicationError):
    pass


class KnowledgeProductVersionNotFound(ApplicationError):
    pass


class KnowledgeProductVersionNotPublished(ApplicationError):
    pass
