from __future__ import annotations

from enum import Enum


class Role(str, Enum):
    ADMIN = "admin"
    KNOWLEDGE_OWNER = "knowledge_owner"
    REVIEWER = "reviewer"
    CONSUMER = "consumer"


class ApprovalDecision(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
