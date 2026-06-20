from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.domain.governance.value_objects import ApprovalDecision
from app.domain.shared.base import DomainError, Entity


@dataclass
class ApprovalRequest(Entity):
    version_id: uuid.UUID = field(default_factory=uuid.uuid4)
    requested_by: uuid.UUID = field(default_factory=uuid.uuid4)
    reviewer_id: uuid.UUID | None = None
    decision: ApprovalDecision = ApprovalDecision.PENDING
    comment: str | None = None
    requested_at: datetime | None = None
    decided_at: datetime | None = None

    def decide(self, reviewer_id: uuid.UUID, decision: ApprovalDecision, comment: str | None, decided_at: datetime) -> None:
        if self.decision is not ApprovalDecision.PENDING:
            raise DomainError(f"Approval request {self.id} has already been decided ({self.decision.value})")
        if decision is ApprovalDecision.PENDING:
            raise DomainError("Cannot decide an approval request to PENDING")
        self.reviewer_id = reviewer_id
        self.decision = decision
        self.comment = comment
        self.decided_at = decided_at
