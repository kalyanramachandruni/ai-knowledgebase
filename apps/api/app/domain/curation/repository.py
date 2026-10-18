from __future__ import annotations

import uuid
from typing import Protocol

from app.domain.curation.entities import CurationRun


class CurationRunRepository(Protocol):
    async def get_by_id(self, run_id: uuid.UUID) -> CurationRun | None: ...

    async def save(self, run: CurationRun) -> CurationRun: ...
