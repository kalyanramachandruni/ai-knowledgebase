from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def new_id() -> uuid.UUID:
    return uuid.uuid4()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class ValueObject:
    """Marker base for immutable value objects."""


@dataclass(kw_only=True)
class DomainEvent:
    """kw_only so subclasses can add required positional-looking fields
    without violating dataclass default-argument ordering."""

    occurred_at: datetime = field(default_factory=utc_now)


@dataclass
class Entity:
    id: uuid.UUID = field(default_factory=new_id)


@dataclass
class AggregateRoot(Entity):
    """An Entity that is the consistency boundary for a set of changes
    and accumulates DomainEvents to be published after a successful commit."""

    _events: list[DomainEvent] = field(default_factory=list, repr=False)

    def record_event(self, event: DomainEvent) -> None:
        self._events.append(event)

    def pull_events(self) -> list[DomainEvent]:
        events, self._events = self._events, []
        return events


class DomainError(Exception):
    """Base class for domain rule violations. Never raised from infrastructure/api layers directly."""
