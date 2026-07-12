from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from app.domain.knowledge_product.events import (
    ProductCompiled,
    ProductPublished,
    ProductRetired,
    ProductStatusChanged,
)
from app.domain.knowledge_product.value_objects import (
    BusinessRule,
    Escalation,
    KnowledgeProductStatus,
    Policy,
    ProcessStep,
    Role,
    SemVer,
    ServiceLevelAgreement,
    ToolReference,
    VersionBump,
    assert_legal_transition,
)
from app.domain.shared.base import AggregateRoot, DomainError, new_id


@dataclass
class KnowledgeProductVersion:
    """Immutable snapshot of one compiled version of a Knowledge Product.

    Created fresh on every meaningful edit — never mutated in place once persisted.
    `status` is the one field that *does* change in place, because status transitions
    are workflow state, not content edits, and re-snapshotting content on every
    review/approve click would explode the version table for no benefit.
    """

    product_id: uuid.UUID
    semver: SemVer
    process_steps: list[ProcessStep]
    rules: list[BusinessRule]
    policies: list[Policy]
    sla: ServiceLevelAgreement | None
    escalations: list[Escalation]
    roles: list[Role]
    tools: list[ToolReference]
    created_by: uuid.UUID
    id: uuid.UUID = field(default_factory=new_id)
    status: KnowledgeProductStatus = KnowledgeProductStatus.DRAFT
    source_extraction_run_id: uuid.UUID | None = None
    process_overview: dict = field(default_factory=dict)

    def to_canonical_dict(self, *, product_key: str, name: str, owner: str) -> dict:
        """Shape matching the canonical Knowledge Product YAML schema."""
        steps = []
        for s in sorted(self.process_steps, key=lambda s: s.sequence):
            step: dict = {"name": s.name}
            if s.description:
                step["description"] = s.description
            if s.responsible_role:
                step["responsible_role"] = s.responsible_role
            if s.inputs:
                step["inputs"] = list(s.inputs)
            if s.outputs:
                step["outputs"] = list(s.outputs)
            if s.decision:
                step["decision"] = s.decision
            if s.tools_used:
                step["tools_used"] = list(s.tools_used)
            steps.append(step)

        roles = []
        for r in self.roles:
            role_dict: dict = {"name": r.name}
            if r.responsibilities:
                role_dict["responsibilities"] = list(r.responsibilities)
            roles.append(role_dict)

        tools = []
        for t in self.tools:
            tool_dict: dict = {"name": t.display_name or t.key}
            if t.purpose:
                tool_dict["purpose"] = t.purpose
            tools.append(tool_dict)

        return {
            "metadata": {
                "id": product_key,
                "name": name,
                "owner": owner,
                "version": str(self.semver),
            },
            "process_overview": self.process_overview or None,
            "process": {"steps": steps},
            "rules": [
                {k: v for k, v in {"condition": r.condition, "action": r.action, "rationale": r.rationale}.items() if v}
                for r in self.rules
            ],
            "policies": [
                {k: v for k, v in {"condition": p.condition, "action": p.action, "rationale": p.rationale}.items() if v}
                for p in self.policies
            ],
            "sla": {"target": self.sla.target} if self.sla else None,
            "escalations": [
                {k: v for k, v in {"after": e.after, "escalate_to": e.escalate_to, "action": e.action}.items() if v}
                for e in self.escalations
            ],
            "roles": roles,
            "tools": tools,
        }


@dataclass
class KnowledgeProduct(AggregateRoot):
    """Aggregate root. `product_key` is the stable identity across all versions;
    `versions` holds the full immutable history with the latest at versions[-1]."""

    product_key: str = ""
    name: str = ""
    owner: str = ""
    versions: list[KnowledgeProductVersion] = field(default_factory=list)

    @property
    def current_version(self) -> KnowledgeProductVersion:
        if not self.versions:
            raise DomainError("Knowledge Product has no versions yet")
        return self.versions[-1]

    def compile_new_version(
        self,
        *,
        process_steps: list[ProcessStep],
        rules: list[BusinessRule],
        policies: list[Policy],
        sla: ServiceLevelAgreement | None,
        escalations: list[Escalation],
        roles: list[Role],
        tools: list[ToolReference],
        created_by: uuid.UUID,
        bump: VersionBump,
        source_extraction_run_id: uuid.UUID | None = None,
        process_overview: dict | None = None,
    ) -> KnowledgeProductVersion:
        previous = self.versions[-1].semver if self.versions else SemVer(0, 0, 0)
        next_semver = previous.bump(bump) if self.versions else SemVer(1, 0, 0)

        version = KnowledgeProductVersion(
            product_id=self.id,
            semver=next_semver,
            process_steps=process_steps,
            rules=rules,
            policies=policies,
            sla=sla,
            escalations=escalations,
            roles=roles,
            tools=tools,
            created_by=created_by,
            source_extraction_run_id=source_extraction_run_id,
            process_overview=process_overview or {},
        )
        self.versions.append(version)
        self.record_event(ProductCompiled(product_id=self.id, version_id=version.id, semver=str(next_semver)))
        return version

    def transition(self, version_id: uuid.UUID, target: KnowledgeProductStatus) -> None:
        version = self._get_version(version_id)
        assert_legal_transition(version.status, target)
        previous = version.status
        version.status = target
        self.record_event(
            ProductStatusChanged(
                product_id=self.id,
                version_id=version.id,
                from_status=previous.value,
                to_status=target.value,
            )
        )
        if target is KnowledgeProductStatus.PUBLISHED:
            self.record_event(ProductPublished(product_id=self.id, version_id=version.id, semver=str(version.semver)))
        if target is KnowledgeProductStatus.RETIRED:
            self.record_event(ProductRetired(product_id=self.id, version_id=version.id))

    def submit_for_review(self, version_id: uuid.UUID) -> None:
        self.transition(version_id, KnowledgeProductStatus.REVIEW)

    def approve(self, version_id: uuid.UUID) -> None:
        self.transition(version_id, KnowledgeProductStatus.APPROVED)

    def publish(self, version_id: uuid.UUID) -> None:
        # published_at/retired_at timestamps are stamped by the repository on save, not here
        self.transition(version_id, KnowledgeProductStatus.PUBLISHED)

    def retire(self, version_id: uuid.UUID) -> None:
        self.transition(version_id, KnowledgeProductStatus.RETIRED)

    def _get_version(self, version_id: uuid.UUID) -> KnowledgeProductVersion:
        for v in self.versions:
            if v.id == version_id:
                return v
        raise DomainError(f"Version {version_id} not found on product {self.product_key}")
