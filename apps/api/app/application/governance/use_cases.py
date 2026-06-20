from __future__ import annotations

import uuid

from app.application.governance.exceptions import ApprovalRequestNotFound, NoPendingApprovalRequest
from app.application.knowledge_product.exceptions import KnowledgeProductNotFound
from app.domain.governance.entities import ApprovalRequest
from app.domain.governance.events import ApprovalDecided, ApprovalRequested
from app.domain.governance.ports import AuditPort
from app.domain.governance.repository import ApprovalRequestRepository
from app.domain.governance.value_objects import ApprovalDecision
from app.domain.knowledge_product.repository import KnowledgeProductRepository
from app.domain.knowledge_product.value_objects import KnowledgeProductStatus
from app.domain.shared.base import utc_now
from app.domain.shared.event_bus import EventPublisherPort


class SubmitForReviewUseCase:
    """Submitting for review both transitions the version (domain-enforced
    draft -> review) and opens an ApprovalRequest a Reviewer must act on —
    the two are kept in lockstep so there's never a version sitting in
    'review' status with no corresponding approval request to decide it."""

    def __init__(
        self,
        product_repository: KnowledgeProductRepository,
        approval_repository: ApprovalRequestRepository,
        audit: AuditPort,
        event_publisher: EventPublisherPort,
    ) -> None:
        self._product_repository = product_repository
        self._approval_repository = approval_repository
        self._audit = audit
        self._event_publisher = event_publisher

    async def execute(self, product_id: uuid.UUID, version_id: uuid.UUID, requested_by: uuid.UUID):
        product = await self._product_repository.get_by_id(product_id)
        if product is None:
            raise KnowledgeProductNotFound(f"Knowledge Product {product_id} not found")

        product.transition(version_id, KnowledgeProductStatus.REVIEW)
        await self._product_repository.save(product)

        request = ApprovalRequest(version_id=version_id, requested_by=requested_by, requested_at=utc_now())
        request = await self._approval_repository.save(request)

        await self._audit.record(
            entity_type="knowledge_product_version",
            entity_id=version_id,
            action="submitted_for_review",
            actor_id=requested_by,
        )
        await self._event_publisher.publish(
            ApprovalRequested(request_id=request.id, version_id=version_id, requested_by=requested_by)
        )
        return product, request


class DecideApprovalUseCase:
    """A Reviewer's decision drives the version's status: approved moves it
    to APPROVED (ready for a Knowledge Owner to publish); rejected sends it
    back to DRAFT (the domain's status machine already allows review->draft)
    so the owner can revise and resubmit."""

    def __init__(
        self,
        product_repository: KnowledgeProductRepository,
        approval_repository: ApprovalRequestRepository,
        audit: AuditPort,
        event_publisher: EventPublisherPort,
    ) -> None:
        self._product_repository = product_repository
        self._approval_repository = approval_repository
        self._audit = audit
        self._event_publisher = event_publisher

    async def execute(
        self,
        product_id: uuid.UUID,
        request_id: uuid.UUID,
        reviewer_id: uuid.UUID,
        decision: ApprovalDecision,
        comment: str | None = None,
    ):
        request = await self._approval_repository.get_by_id(request_id)
        if request is None:
            raise ApprovalRequestNotFound(f"Approval request {request_id} not found")
        if request.decision is not ApprovalDecision.PENDING:
            raise NoPendingApprovalRequest(f"Approval request {request_id} is already {request.decision.value}")

        request.decide(reviewer_id, decision, comment, utc_now())
        request = await self._approval_repository.save(request)

        product = await self._product_repository.get_by_id(product_id)
        if product is None:
            raise KnowledgeProductNotFound(f"Knowledge Product {product_id} not found")

        target_status = (
            KnowledgeProductStatus.APPROVED if decision is ApprovalDecision.APPROVED else KnowledgeProductStatus.DRAFT
        )
        product.transition(request.version_id, target_status)
        await self._product_repository.save(product)

        await self._audit.record(
            entity_type="approval_request",
            entity_id=request.id,
            action="decided",
            actor_id=reviewer_id,
            diff={"decision": decision.value, "comment": comment},
        )
        await self._event_publisher.publish(
            ApprovalDecided(
                request_id=request.id, version_id=request.version_id, decision=decision.value, reviewer_id=reviewer_id
            )
        )
        return product, request
