from __future__ import annotations

import dataclasses
import uuid

from app.application.curation.exceptions import ConfluencePageNotFound
from app.application.curation.html import strip_storage_format
from app.domain.confluence.repository import ConfluencePageRepository
from app.domain.curation.entities import CurationRun, CurationStatus, PageSourceType
from app.domain.curation.events import CurationFailed, KnowledgeCurated
from app.domain.curation.ports import LLMCurationPort
from app.domain.curation.repository import CurationRunRepository
from app.domain.curation.schema import KNOWLEDGE_CURATION_SCHEMA
from app.domain.shared.base import utc_now
from app.domain.shared.event_bus import EventPublisherPort


class ExtractKnowledgeFromPageUseCase:
    """Capability 2: runs the LLM curation pipeline against one ingested
    Confluence page and persists the result as a CurationRun, regardless
    of success or failure, so every attempt is auditable."""

    def __init__(
        self,
        page_repository: ConfluencePageRepository,
        curation_repository: CurationRunRepository,
        llm_port: LLMCurationPort,
        event_publisher: EventPublisherPort,
        *,
        llm_provider: str,
        llm_model: str,
    ) -> None:
        self._page_repository = page_repository
        self._curation_repository = curation_repository
        self._llm_port = llm_port
        self._event_publisher = event_publisher
        self._llm_provider = llm_provider
        self._llm_model = llm_model

    async def execute(self, page_id: uuid.UUID, *, source_url: str | None = None) -> CurationRun:
        page = await self._page_repository.get_by_id(page_id)
        if page is None:
            raise ConfluencePageNotFound(f"Confluence page {page_id} not found")

        run = CurationRun(
            page_id=page_id,
            page_source_type=PageSourceType.CONFLUENCE,
            llm_provider=self._llm_provider,
            llm_model=self._llm_model,
            status=CurationStatus.RUNNING,
            started_at=utc_now(),
        )
        run = await self._curation_repository.save(run)

        try:
            plain_text = strip_storage_format(page.body_storage_format)
            result = await self._llm_port.extract(plain_text, KNOWLEDGE_CURATION_SCHEMA, source_url=source_url)
        except Exception as exc:
            run.status = CurationStatus.FAILED
            run.error_message = str(exc)
            run.completed_at = utc_now()
            run = await self._curation_repository.save(run)
            await self._event_publisher.publish(
                CurationFailed(run_id=run.id, page_id=page_id, error_message=str(exc))
            )
            return run

        run.structured_draft = {
            k: v for k, v in dataclasses.asdict(result).items() if k != "raw_model_output"
        }
        run.status = CurationStatus.SUCCEEDED
        run.completed_at = utc_now()
        run = await self._curation_repository.save(run)
        await self._event_publisher.publish(KnowledgeCurated(run_id=run.id, page_id=page_id))
        return run
