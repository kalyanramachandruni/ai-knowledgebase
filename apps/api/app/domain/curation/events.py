from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.domain.shared.base import DomainEvent


@dataclass
class KnowledgeCurated(DomainEvent):
    run_id: uuid.UUID
    page_id: uuid.UUID


@dataclass
class CurationFailed(DomainEvent):
    run_id: uuid.UUID
    page_id: uuid.UUID
    error_message: str
