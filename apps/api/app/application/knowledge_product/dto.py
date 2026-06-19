from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.domain.knowledge_product.value_objects import VersionBump


@dataclass(frozen=True)
class RuleInput:
    condition: str
    action: str


@dataclass(frozen=True)
class EscalationInput:
    after: str
    escalate_to: str


@dataclass(frozen=True)
class CompileKnowledgeProductInput:
    """Shared payload for both create (first version) and update (new version)."""

    process_steps: list[str]
    rules: list[RuleInput]
    policies: list[RuleInput]
    sla_target: str | None
    escalations: list[EscalationInput]
    roles: list[str]
    tools: list[str]
    created_by: uuid.UUID
    bump: VersionBump = VersionBump.MINOR
    source_extraction_run_id: uuid.UUID | None = None


@dataclass(frozen=True)
class CreateKnowledgeProductInput:
    product_key: str
    name: str
    owner: str
    compile_input: CompileKnowledgeProductInput
