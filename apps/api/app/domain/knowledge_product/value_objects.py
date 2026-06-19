from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from app.domain.shared.base import DomainError, ValueObject

_SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


class KnowledgeProductStatus(str, Enum):
    DRAFT = "draft"
    REVIEW = "review"
    APPROVED = "approved"
    PUBLISHED = "published"
    RETIRED = "retired"


# Legal forward transitions. Anything not listed (including all backward moves) is illegal.
_ALLOWED_TRANSITIONS: dict[KnowledgeProductStatus, set[KnowledgeProductStatus]] = {
    KnowledgeProductStatus.DRAFT: {KnowledgeProductStatus.REVIEW},
    KnowledgeProductStatus.REVIEW: {KnowledgeProductStatus.APPROVED, KnowledgeProductStatus.DRAFT},
    KnowledgeProductStatus.APPROVED: {KnowledgeProductStatus.PUBLISHED, KnowledgeProductStatus.DRAFT},
    KnowledgeProductStatus.PUBLISHED: {KnowledgeProductStatus.RETIRED},
    KnowledgeProductStatus.RETIRED: set(),
}


def assert_legal_transition(current: KnowledgeProductStatus, target: KnowledgeProductStatus) -> None:
    if target not in _ALLOWED_TRANSITIONS[current]:
        raise DomainError(f"Illegal status transition: {current.value} -> {target.value}")


class VersionBump(str, Enum):
    MAJOR = "major"
    MINOR = "minor"
    PATCH = "patch"


@dataclass(frozen=True)
class SemVer(ValueObject):
    major: int
    minor: int
    patch: int

    @staticmethod
    def parse(raw: str) -> "SemVer":
        match = _SEMVER_RE.match(raw)
        if not match:
            raise DomainError(f"Invalid semantic version: {raw!r}")
        major, minor, patch = (int(part) for part in match.groups())
        return SemVer(major, minor, patch)

    def bump(self, kind: VersionBump) -> "SemVer":
        if kind is VersionBump.MAJOR:
            return SemVer(self.major + 1, 0, 0)
        if kind is VersionBump.MINOR:
            return SemVer(self.major, self.minor + 1, 0)
        return SemVer(self.major, self.minor, self.patch + 1)

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"


@dataclass(frozen=True)
class ProcessStep(ValueObject):
    name: str
    sequence: int


@dataclass(frozen=True)
class BusinessRule(ValueObject):
    condition: str
    action: str


@dataclass(frozen=True)
class Policy(ValueObject):
    condition: str
    action: str


@dataclass(frozen=True)
class ServiceLevelAgreement(ValueObject):
    target: str  # e.g. "2h" — free-form duration, parsed at the edges, not in the domain


@dataclass(frozen=True)
class Escalation(ValueObject):
    after: str          # e.g. "90m"
    escalate_to: str    # role name


@dataclass(frozen=True)
class Role(ValueObject):
    name: str


@dataclass(frozen=True)
class ToolReference(ValueObject):
    key: str            # e.g. "sap_create_shipment"
    display_name: str
