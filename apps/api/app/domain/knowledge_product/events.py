from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.domain.shared.base import DomainEvent


@dataclass
class ProductCompiled(DomainEvent):
    product_id: uuid.UUID
    version_id: uuid.UUID
    semver: str


@dataclass
class ProductStatusChanged(DomainEvent):
    product_id: uuid.UUID
    version_id: uuid.UUID
    from_status: str
    to_status: str


@dataclass
class ProductPublished(DomainEvent):
    product_id: uuid.UUID
    version_id: uuid.UUID
    semver: str


@dataclass
class ProductRetired(DomainEvent):
    product_id: uuid.UUID
    version_id: uuid.UUID
