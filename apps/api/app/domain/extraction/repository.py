from __future__ import annotations

import uuid
from typing import Protocol

from app.domain.extraction.entities import ExtractionRun


class ExtractionRunRepository(Protocol):
    async def get_by_id(self, run_id: uuid.UUID) -> ExtractionRun | None: ...

    async def save(self, run: ExtractionRun) -> ExtractionRun: ...
