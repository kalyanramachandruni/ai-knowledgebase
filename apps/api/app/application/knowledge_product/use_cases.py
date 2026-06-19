from __future__ import annotations

import uuid

from app.application.knowledge_product.dto import CompileKnowledgeProductInput, CreateKnowledgeProductInput
from app.application.knowledge_product.exceptions import KnowledgeProductAlreadyExists, KnowledgeProductNotFound
from app.domain.governance.ports import AuditPort
from app.domain.knowledge_product.entities import KnowledgeProduct, KnowledgeProductVersion
from app.domain.knowledge_product.repository import KnowledgeProductRepository
from app.domain.knowledge_product.value_objects import (
    BusinessRule,
    Escalation,
    KnowledgeProductStatus,
    Policy,
    ProcessStep,
    Role,
    ServiceLevelAgreement,
    ToolReference,
    VersionBump,
)


def _compile_args(compile_input: CompileKnowledgeProductInput) -> dict:
    return {
        "process_steps": [ProcessStep(name=name, sequence=i) for i, name in enumerate(compile_input.process_steps)],
        "rules": [BusinessRule(condition=r.condition, action=r.action) for r in compile_input.rules],
        "policies": [Policy(condition=p.condition, action=p.action) for p in compile_input.policies],
        "sla": ServiceLevelAgreement(target=compile_input.sla_target) if compile_input.sla_target else None,
        "escalations": [Escalation(after=e.after, escalate_to=e.escalate_to) for e in compile_input.escalations],
        "roles": [Role(name=name) for name in compile_input.roles],
        "tools": [ToolReference(key=key, display_name=key) for key in compile_input.tools],
        "created_by": compile_input.created_by,
        "bump": compile_input.bump,
        "source_extraction_run_id": compile_input.source_extraction_run_id,
    }


class CreateKnowledgeProductUseCase:
    def __init__(self, repository: KnowledgeProductRepository, audit: AuditPort) -> None:
        self._repository = repository
        self._audit = audit

    async def execute(self, payload: CreateKnowledgeProductInput) -> KnowledgeProduct:
        existing = await self._repository.get_by_key(payload.product_key)
        if existing is not None:
            raise KnowledgeProductAlreadyExists(f"Knowledge Product {payload.product_key!r} already exists")

        product = KnowledgeProduct(product_key=payload.product_key, name=payload.name, owner=payload.owner)
        compile_input = payload.compile_input
        version = product.compile_new_version(**_compile_args(compile_input) | {"bump": VersionBump.MAJOR})

        await self._repository.save(product)
        await self._audit.record(
            entity_type="knowledge_product",
            entity_id=product.id,
            action="created",
            actor_id=compile_input.created_by,
            diff={"semver": str(version.semver)},
        )
        return product


class CompileNewVersionUseCase:
    """Adds a new version to an existing product — used by both manual edits (UI) and the
    extraction→compile pipeline (step 4)."""

    def __init__(self, repository: KnowledgeProductRepository, audit: AuditPort) -> None:
        self._repository = repository
        self._audit = audit

    async def execute(self, product_id: uuid.UUID, compile_input: CompileKnowledgeProductInput) -> KnowledgeProductVersion:
        product = await self._repository.get_by_id(product_id)
        if product is None:
            raise KnowledgeProductNotFound(f"Knowledge Product {product_id} not found")

        version = product.compile_new_version(**_compile_args(compile_input))
        await self._repository.save(product)
        await self._audit.record(
            entity_type="knowledge_product_version",
            entity_id=version.id,
            action="compiled",
            actor_id=compile_input.created_by,
            diff={"semver": str(version.semver)},
        )
        return version


class TransitionStatusUseCase:
    """Backs submit-for-review / approve / publish / retire — all are the same
    shape: load aggregate, attempt transition (domain enforces legality), save, audit."""

    def __init__(self, repository: KnowledgeProductRepository, audit: AuditPort) -> None:
        self._repository = repository
        self._audit = audit

    async def execute(
        self, product_id: uuid.UUID, version_id: uuid.UUID, target: KnowledgeProductStatus, actor_id: uuid.UUID
    ) -> KnowledgeProduct:
        product = await self._repository.get_by_id(product_id)
        if product is None:
            raise KnowledgeProductNotFound(f"Knowledge Product {product_id} not found")

        from_status = next(v for v in product.versions if v.id == version_id).status
        product.transition(version_id, target)
        await self._repository.save(product)
        await self._audit.record(
            entity_type="knowledge_product_version",
            entity_id=version_id,
            action="status_changed",
            actor_id=actor_id,
            diff={"from": from_status.value, "to": target.value},
        )
        return product


class GetKnowledgeProductUseCase:
    def __init__(self, repository: KnowledgeProductRepository) -> None:
        self._repository = repository

    async def execute(self, product_id: uuid.UUID) -> KnowledgeProduct:
        product = await self._repository.get_by_id(product_id)
        if product is None:
            raise KnowledgeProductNotFound(f"Knowledge Product {product_id} not found")
        return product


class ListKnowledgeProductsUseCase:
    def __init__(self, repository: KnowledgeProductRepository) -> None:
        self._repository = repository

    async def execute(
        self, *, status: str | None = None, search: str | None = None, limit: int = 50, offset: int = 0
    ) -> list[KnowledgeProduct]:
        return await self._repository.list(status=status, search=search, limit=limit, offset=offset)


class CompareVersionsUseCase:
    """Field-level diff between two versions of the same product, for the
    Version History UI."""

    def __init__(self, repository: KnowledgeProductRepository) -> None:
        self._repository = repository

    async def execute(self, product_id: uuid.UUID, from_version_id: uuid.UUID, to_version_id: uuid.UUID) -> dict:
        product = await self._repository.get_by_id(product_id)
        if product is None:
            raise KnowledgeProductNotFound(f"Knowledge Product {product_id} not found")

        from_version = next(v for v in product.versions if v.id == from_version_id)
        to_version = next(v for v in product.versions if v.id == to_version_id)

        from_dict = from_version.to_canonical_dict(
            product_key=product.product_key, name=product.name, owner=product.owner
        )
        to_dict = to_version.to_canonical_dict(
            product_key=product.product_key, name=product.name, owner=product.owner
        )

        diff: dict = {}
        for key in set(from_dict) | set(to_dict):
            if from_dict.get(key) != to_dict.get(key):
                diff[key] = {"from": from_dict.get(key), "to": to_dict.get(key)}
        return diff
