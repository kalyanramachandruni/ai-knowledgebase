from __future__ import annotations

import uuid

from app.application.curation.exceptions import CurationRunNotFound, CurationRunNotSucceeded
from app.application.knowledge_product.dto import (
    CompileKnowledgeProductInput,
    CreateKnowledgeProductInput,
    EscalationInput,
    ProcessStepInput,
    RoleInput,
    RuleInput,
    ToolInput,
)
from app.application.knowledge_product.use_cases import CompileNewVersionUseCase, CreateKnowledgeProductUseCase
from app.domain.curation.entities import CurationStatus
from app.domain.curation.ports import CurationResult, LLMCurationPort
from app.domain.curation.repository import CurationRunRepository
from app.domain.curation.schema import KNOWLEDGE_CURATION_SCHEMA
from app.domain.knowledge_product.entities import KnowledgeProduct, KnowledgeProductVersion
from app.domain.knowledge_product.repository import KnowledgeProductRepository
from app.domain.knowledge_product.value_objects import VersionBump


def _version_to_curation_result(version: KnowledgeProductVersion) -> CurationResult:
    """Convert an existing compiled version back into CurationResult for LLM merge."""
    steps = []
    for s in sorted(version.process_steps, key=lambda s: s.sequence):
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
        step["sources"] = list(s.sources)
        steps.append(step)

    roles = []
    for r in version.roles:
        role_dict: dict = {"name": r.name}
        if r.responsibilities:
            role_dict["responsibilities"] = list(r.responsibilities)
        role_dict["sources"] = list(r.sources)
        roles.append(role_dict)

    tools = []
    for t in version.tools:
        tool_dict: dict = {"name": t.display_name or t.key}
        if t.purpose:
            tool_dict["purpose"] = t.purpose
        tool_dict["sources"] = list(t.sources)
        tools.append(tool_dict)

    return CurationResult(
        process_overview=version.process_overview or {},
        process_steps=steps,
        rules=[
            {k: v for k, v in {"condition": r.condition, "action": r.action, "rationale": r.rationale, "sources": list(r.sources)}.items() if v is not None}
            for r in version.rules
        ],
        policies=[
            {k: v for k, v in {"condition": p.condition, "action": p.action, "rationale": p.rationale, "sources": list(p.sources)}.items() if v is not None}
            for p in version.policies
        ],
        sla_target=version.sla.target if version.sla else None,
        escalations=[
            {k: v for k, v in {"after": e.after, "escalate_to": e.escalate_to, "action": e.action, "sources": list(e.sources)}.items() if v is not None}
            for e in version.escalations
        ],
        roles=roles,
        tools=tools,
        raw_model_output={},
    )


def _curation_result_to_compile_input(
    result: CurationResult,
    *,
    created_by: uuid.UUID,
    bump: VersionBump,
    source_curation_run_id: uuid.UUID,
) -> CompileKnowledgeProductInput:
    steps = []
    for s in result.process_steps:
        if isinstance(s, str):
            # backward compat: old curation runs stored steps as plain strings
            steps.append(ProcessStepInput(name=s))
        else:
            steps.append(ProcessStepInput(
                name=s.get("name", ""),
                description=s.get("description", ""),
                responsible_role=s.get("responsible_role", ""),
                inputs=s.get("inputs") or [],
                outputs=s.get("outputs") or [],
                decision=s.get("decision"),
                tools_used=s.get("tools_used") or [],
                sources=s.get("sources") or [],
            ))

    roles = []
    for r in result.roles:
        if isinstance(r, str):
            roles.append(RoleInput(name=r))
        else:
            roles.append(RoleInput(name=r.get("name", ""), responsibilities=r.get("responsibilities") or [], sources=r.get("sources") or []))

    tools = []
    for t in result.tools:
        if isinstance(t, str):
            tools.append(ToolInput(name=t))
        else:
            tools.append(ToolInput(name=t.get("name", ""), purpose=t.get("purpose", ""), sources=t.get("sources") or []))

    return CompileKnowledgeProductInput(
        process_overview=result.process_overview or {},
        process_steps=steps,
        rules=[RuleInput(condition=r["condition"], action=r["action"], rationale=r.get("rationale", ""), sources=r.get("sources") or []) for r in result.rules],
        policies=[RuleInput(condition=p["condition"], action=p["action"], rationale=p.get("rationale", ""), sources=p.get("sources") or []) for p in result.policies],
        sla_target=result.sla_target,
        escalations=[
            EscalationInput(
                after=e.get("trigger") or e.get("after", ""),
                escalate_to=e["escalate_to"],
                action=e.get("action", ""),
                sources=e.get("sources") or [],
            )
            for e in result.escalations
        ],
        roles=roles,
        tools=tools,
        created_by=created_by,
        bump=bump,
        source_extraction_run_id=source_curation_run_id,
    )


class CompileFromCurationUseCase:
    """Capability 3: Knowledge Product Compiler. Maps a succeeded
    CurationRun's structured draft into the canonical Knowledge Product
    shape and hands it to the registry — creating the product if its
    product_key doesn't exist yet, or using the LLM to intelligently merge
    the new curation with the existing version if it does."""

    def __init__(
        self,
        curation_repository: CurationRunRepository,
        knowledge_product_repository: KnowledgeProductRepository,
        create_use_case: CreateKnowledgeProductUseCase,
        compile_new_version_use_case: CompileNewVersionUseCase,
        llm_port: LLMCurationPort,
    ) -> None:
        self._curation_repository = curation_repository
        self._knowledge_product_repository = knowledge_product_repository
        self._create_use_case = create_use_case
        self._compile_new_version_use_case = compile_new_version_use_case
        self._llm_port = llm_port

    async def execute(
        self,
        run_id: uuid.UUID,
        *,
        product_key: str,
        name: str,
        owner: str,
        created_by: uuid.UUID,
        bump: VersionBump = VersionBump.MINOR,
    ) -> KnowledgeProduct:
        run = await self._curation_repository.get_by_id(run_id)
        if run is None:
            raise CurationRunNotFound(f"Curation run {run_id} not found")
        if run.status is not CurationStatus.SUCCEEDED or run.structured_draft is None:
            raise CurationRunNotSucceeded(f"Curation run {run_id} has not succeeded; cannot compile")

        draft = run.structured_draft
        incoming = CurationResult(
            process_overview=draft.get("process_overview", {}),
            process_steps=draft.get("process_steps", []),
            rules=draft.get("rules", []),
            policies=draft.get("policies", []),
            sla_target=draft.get("sla_target"),
            escalations=draft.get("escalations", []),
            roles=draft.get("roles", []),
            tools=draft.get("tools", []),
            raw_model_output=draft,
        )

        existing = await self._knowledge_product_repository.get_by_key(product_key)
        if existing is None:
            compile_input = _curation_result_to_compile_input(
                incoming, created_by=created_by, bump=bump, source_curation_run_id=run_id
            )
            return await self._create_use_case.execute(
                CreateKnowledgeProductInput(
                    product_key=product_key, name=name, owner=owner, compile_input=compile_input
                )
            )

        # LLM-based merge: ask the model to intelligently combine existing
        # version content with the new curation rather than blindly appending.
        existing_result = _version_to_curation_result(existing.current_version)
        merged, _ = await self._llm_port.merge(existing_result, incoming, KNOWLEDGE_CURATION_SCHEMA)
        compile_input = _curation_result_to_compile_input(
            merged, created_by=created_by, bump=bump, source_curation_run_id=run_id
        )
        await self._compile_new_version_use_case.execute(existing.id, compile_input)
        return await self._knowledge_product_repository.get_by_id(existing.id)
