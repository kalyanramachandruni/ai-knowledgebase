from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.domain.knowledge_product.value_objects import VersionBump


@dataclass(frozen=True)
class ProcessStepInput:
    name: str
    description: str = ""
    responsible_role: str = ""
    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    decision: str | None = None
    tools_used: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RuleInput:
    condition: str
    action: str
    rationale: str = ""


@dataclass(frozen=True)
class EscalationInput:
    after: str
    escalate_to: str
    action: str = ""


@dataclass(frozen=True)
class RoleInput:
    name: str
    responsibilities: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ToolInput:
    name: str
    purpose: str = ""


@dataclass(frozen=True)
class CompileKnowledgeProductInput:
    """Shared payload for both create (first version) and update (new version)."""

    process_steps: list[ProcessStepInput]
    rules: list[RuleInput]
    policies: list[RuleInput]
    sla_target: str | None
    escalations: list[EscalationInput]
    roles: list[RoleInput]
    tools: list[ToolInput]
    created_by: uuid.UUID
    process_overview: dict = field(default_factory=dict)
    bump: VersionBump = VersionBump.MINOR
    source_extraction_run_id: uuid.UUID | None = None


@dataclass(frozen=True)
class CreateKnowledgeProductInput:
    product_key: str
    name: str
    owner: str
    compile_input: CompileKnowledgeProductInput
