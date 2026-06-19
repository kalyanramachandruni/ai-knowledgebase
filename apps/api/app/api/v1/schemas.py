from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.domain.knowledge_product.entities import KnowledgeProduct, KnowledgeProductVersion
from app.domain.knowledge_product.value_objects import VersionBump


class RuleSchema(BaseModel):
    condition: str
    action: str


class EscalationSchema(BaseModel):
    after: str
    escalate_to: str


class CompileRequest(BaseModel):
    process_steps: list[str] = Field(default_factory=list)
    rules: list[RuleSchema] = Field(default_factory=list)
    policies: list[RuleSchema] = Field(default_factory=list)
    sla_target: str | None = None
    escalations: list[EscalationSchema] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    bump: VersionBump = VersionBump.MINOR
    created_by: uuid.UUID


class CreateKnowledgeProductRequest(BaseModel):
    product_key: str
    name: str
    owner: str
    compile: CompileRequest


class UpdateKnowledgeProductRequest(BaseModel):
    compile: CompileRequest


class TransitionRequest(BaseModel):
    actor_id: uuid.UUID


class KnowledgeProductVersionResponse(BaseModel):
    id: uuid.UUID
    semver: str
    status: str
    content: dict

    @classmethod
    def from_domain(cls, version: KnowledgeProductVersion, *, product_key: str, name: str, owner: str) -> "KnowledgeProductVersionResponse":
        return cls(
            id=version.id,
            semver=str(version.semver),
            status=version.status.value,
            content=version.to_canonical_dict(product_key=product_key, name=name, owner=owner),
        )


class KnowledgeProductResponse(BaseModel):
    id: uuid.UUID
    product_key: str
    name: str
    owner: str
    current_version: KnowledgeProductVersionResponse
    versions: list[KnowledgeProductVersionResponse]

    @classmethod
    def from_domain(cls, product: KnowledgeProduct) -> "KnowledgeProductResponse":
        version_responses = [
            KnowledgeProductVersionResponse.from_domain(
                v, product_key=product.product_key, name=product.name, owner=product.owner
            )
            for v in product.versions
        ]
        return cls(
            id=product.id,
            product_key=product.product_key,
            name=product.name,
            owner=product.owner,
            current_version=version_responses[-1],
            versions=version_responses,
        )


class KnowledgeProductSummaryResponse(BaseModel):
    id: uuid.UUID
    product_key: str
    name: str
    owner: str
    current_status: str
    current_semver: str

    @classmethod
    def from_domain(cls, product: KnowledgeProduct) -> "KnowledgeProductSummaryResponse":
        current = product.current_version
        return cls(
            id=product.id,
            product_key=product.product_key,
            name=product.name,
            owner=product.owner,
            current_status=current.status.value,
            current_semver=str(current.semver),
        )


class VersionDiffResponse(BaseModel):
    diff: dict
