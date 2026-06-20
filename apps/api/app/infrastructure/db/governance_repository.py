from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.governance.entities import ApprovalRequest
from app.domain.governance.value_objects import ApprovalDecision
from app.infrastructure.db.models import ApprovalRequest as ApprovalRequestModel


def _to_domain(row: ApprovalRequestModel) -> ApprovalRequest:
    return ApprovalRequest(
        id=row.id,
        version_id=row.version_id,
        requested_by=row.requested_by,
        reviewer_id=row.reviewer_id,
        decision=ApprovalDecision(row.decision),
        comment=row.comment,
        requested_at=row.requested_at,
        decided_at=row.decided_at,
    )


class SqlAlchemyApprovalRequestRepository:
    """Implements app.domain.governance.repository.ApprovalRequestRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, request_id: uuid.UUID) -> ApprovalRequest | None:
        row = await self._session.get(ApprovalRequestModel, request_id)
        return _to_domain(row) if row else None

    async def get_pending_for_version(self, version_id: uuid.UUID) -> ApprovalRequest | None:
        row = (
            await self._session.execute(
                select(ApprovalRequestModel).where(
                    ApprovalRequestModel.version_id == version_id,
                    ApprovalRequestModel.decision == ApprovalDecision.PENDING.value,
                )
            )
        ).scalar_one_or_none()
        return _to_domain(row) if row else None

    async def save(self, request: ApprovalRequest) -> ApprovalRequest:
        row = await self._session.get(ApprovalRequestModel, request.id)
        if row is None:
            row = ApprovalRequestModel(
                id=request.id,
                version_id=request.version_id,
                requested_by=request.requested_by,
                reviewer_id=request.reviewer_id,
                decision=request.decision.value,
                comment=request.comment,
            )
            self._session.add(row)
        else:
            row.reviewer_id = request.reviewer_id
            row.decision = request.decision.value
            row.comment = request.comment
            row.decided_at = request.decided_at

        await self._session.flush()
        await self._session.commit()
        return _to_domain(row)
