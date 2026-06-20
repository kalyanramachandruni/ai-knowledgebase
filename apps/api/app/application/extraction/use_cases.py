from __future__ import annotations

import dataclasses
import uuid

from app.application.extraction.exceptions import ConfluencePageNotFound
from app.application.extraction.html import strip_storage_format
from app.domain.confluence.repository import ConfluencePageRepository
from app.domain.extraction.entities import ExtractionRun, ExtractionStatus
from app.domain.extraction.events import ExtractionFailed, KnowledgeExtracted
from app.domain.extraction.ports import LLMExtractionPort
from app.domain.extraction.repository import ExtractionRunRepository
from app.domain.extraction.schema import KNOWLEDGE_EXTRACTION_SCHEMA
from app.domain.shared.base import utc_now
from app.domain.shared.event_bus import EventPublisherPort


class ExtractKnowledgeFromPageUseCase:
    """Capability 2: runs the LLM extraction pipeline against one ingested
    Confluence page and persists the result as an ExtractionRun, regardless
    of success or failure, so every attempt is auditable."""

    def __init__(
        self,
        page_repository: ConfluencePageRepository,
        extraction_repository: ExtractionRunRepository,
        llm_port: LLMExtractionPort,
        event_publisher: EventPublisherPort,
        *,
        llm_provider: str,
        llm_model: str,
    ) -> None:
        self._page_repository = page_repository
        self._extraction_repository = extraction_repository
        self._llm_port = llm_port
        self._event_publisher = event_publisher
        self._llm_provider = llm_provider
        self._llm_model = llm_model

    async def execute(self, page_id: uuid.UUID) -> ExtractionRun:
        page = await self._page_repository.get_by_id(page_id)
        if page is None:
            raise ConfluencePageNotFound(f"Confluence page {page_id} not found")

        run = ExtractionRun(
            page_id=page_id,
            llm_provider=self._llm_provider,
            llm_model=self._llm_model,
            status=ExtractionStatus.RUNNING,
            started_at=utc_now(),
        )
        run = await self._extraction_repository.save(run)

        try:
            plain_text = strip_storage_format(page.body_storage_format)
            result = await self._llm_port.extract(plain_text, KNOWLEDGE_EXTRACTION_SCHEMA)
        except Exception as exc:
            run.status = ExtractionStatus.FAILED
            run.error_message = str(exc)
            run.completed_at = utc_now()
            run = await self._extraction_repository.save(run)
            await self._event_publisher.publish(
                ExtractionFailed(run_id=run.id, page_id=page_id, error_message=str(exc))
            )
            return run

        run.structured_draft = {
            k: v for k, v in dataclasses.asdict(result).items() if k != "raw_model_output"
        }
        run.status = ExtractionStatus.SUCCEEDED
        run.completed_at = utc_now()
        run = await self._extraction_repository.save(run)
        await self._event_publisher.publish(KnowledgeExtracted(run_id=run.id, page_id=page_id))
        return run
