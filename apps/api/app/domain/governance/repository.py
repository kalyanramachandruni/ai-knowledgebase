from __future__ import annotations

import uuid
from typing import Protocol

from app.domain.governance.entities import ApprovalRequest


class ApprovalRequestRepository(Protocol):
    async def get_by_id(self, request_id: uuid.UUID) -> ApprovalRequest | None: ...

    async def get_pending_for_version(self, version_id: uuid.UUID) -> ApprovalRequest | None: ...

    async def save(self, request: ApprovalRequest) -> ApprovalRequest: ...
