from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.domain.shared.base import Entity


class ExtractionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass
class ExtractionRun(Entity):
    page_id: uuid.UUID = field(default_factory=uuid.uuid4)
    llm_provider: str = ""
    llm_model: str = ""
    status: ExtractionStatus = ExtractionStatus.PENDING
    structured_draft: dict | None = None
    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
