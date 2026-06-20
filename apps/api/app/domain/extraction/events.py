from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.domain.shared.base import DomainEvent


@dataclass
class KnowledgeExtracted(DomainEvent):
    run_id: uuid.UUID
    page_id: uuid.UUID


@dataclass
class ExtractionFailed(DomainEvent):
    run_id: uuid.UUID
    page_id: uuid.UUID
    error_message: str
