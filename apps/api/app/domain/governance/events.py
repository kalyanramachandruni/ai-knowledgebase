from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.domain.shared.base import DomainEvent


@dataclass
class ApprovalRequested(DomainEvent):
    request_id: uuid.UUID
    version_id: uuid.UUID
    requested_by: uuid.UUID


@dataclass
class ApprovalDecided(DomainEvent):
    request_id: uuid.UUID
    version_id: uuid.UUID
    decision: str
    reviewer_id: uuid.UUID
