from __future__ import annotations

from typing import Protocol

from app.domain.shared.base import DomainEvent


class EventPublisherPort(Protocol):
    """Port implemented in app/infrastructure/db/outbox.py via the
    transactional outbox pattern (docs/architecture.md §3, Event-Driven).
    Domain/application code publishes events through this interface only —
    it never knows whether the transport is an outbox table, Kafka, or SNS."""

    async def publish(self, event: DomainEvent) -> None: ...
