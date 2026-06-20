from __future__ import annotations

import uuid

from app.application.extraction.exceptions import ExtractionRunNotFound, ExtractionRunNotSucceeded
from app.application.knowledge_product.dto import (
    CompileKnowledgeProductInput,
    CreateKnowledgeProductInput,
    EscalationInput,
    RuleInput,
)
from app.application.knowledge_product.use_cases import CompileNewVersionUseCase, CreateKnowledgeProductUseCase
from app.domain.extraction.entities import ExtractionStatus
from app.domain.extraction.repository import ExtractionRunRepository
from app.domain.knowledge_product.entities import KnowledgeProduct
from app.domain.knowledge_product.repository import KnowledgeProductRepository
from app.domain.knowledge_product.value_objects import VersionBump


class CompileFromExtractionUseCase:
    """Capability 3: Knowledge Product Compiler. Maps a succeeded
    ExtractionRun's structured draft into the canonical Knowledge Product
    shape and hands it to the registry — creating the product if its
    product_key doesn't exist yet, or compiling a new version if it does.
    Reuses the step-2 registry use cases rather than duplicating their
    versioning/audit logic."""

    def __init__(
        self,
        extraction_repository: ExtractionRunRepository,
        knowledge_product_repository: KnowledgeProductRepository,
        create_use_case: CreateKnowledgeProductUseCase,
        compile_new_version_use_case: CompileNewVersionUseCase,
    ) -> None:
        self._extraction_repository = extraction_repository
        self._knowledge_product_repository = knowledge_product_repository
        self._create_use_case = create_use_case
        self._compile_new_version_use_case = compile_new_version_use_case

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
        run = await self._extraction_repository.get_by_id(run_id)
        if run is None:
            raise ExtractionRunNotFound(f"Extraction run {run_id} not found")
        if run.status is not ExtractionStatus.SUCCEEDED or run.structured_draft is None:
            raise ExtractionRunNotSucceeded(f"Extraction run {run_id} has not succeeded; cannot compile")

        draft = run.structured_draft
        compile_input = CompileKnowledgeProductInput(
            process_steps=draft["process_steps"],
            rules=[RuleInput(condition=r["condition"], action=r["action"]) for r in draft["rules"]],
            policies=[RuleInput(condition=p["condition"], action=p["action"]) for p in draft["policies"]],
            sla_target=draft["sla_target"],
            escalations=[
                EscalationInput(after=e["after"], escalate_to=e["escalate_to"]) for e in draft["escalations"]
            ],
            roles=draft["roles"],
            tools=draft["tools"],
            created_by=created_by,
            bump=bump,
            source_extraction_run_id=run_id,
        )

        existing = await self._knowledge_product_repository.get_by_key(product_key)
        if existing is None:
            return await self._create_use_case.execute(
                CreateKnowledgeProductInput(
                    product_key=product_key, name=name, owner=owner, compile_input=compile_input
                )
            )

        await self._compile_new_version_use_case.execute(existing.id, compile_input)
        return await self._knowledge_product_repository.get_by_id(existing.id)
