from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.domain.shared.base import Entity


class CurationStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PageSourceType(str, Enum):
    CONFLUENCE = "confluence"
    WEB = "web"


@dataclass
class CurationSession(Entity):
    """Session-level metadata for a curation run (provider, model, timing)."""
    llm_provider: str = ""
    llm_model: str = ""
    status: CurationStatus = CurationStatus.PENDING
    started_at: datetime | None = None
    completed_at: datetime | None = None


@dataclass
class CurationRun(Entity):
    """
    Flat projection of page_curation_session_entry + page_curation_session
    (+ optional latest compile outcome from compile_session_entry).
    The repository joins the tables so callers always get a single flat object.
    """
    session_id: uuid.UUID | None = None
    page_id: uuid.UUID | None = None
    page_source_type: PageSourceType | None = None
    status: CurationStatus = CurationStatus.PENDING
    structured_draft: dict | None = None
    error_message: str | None = None
    # From curation_session (joined):
    llm_provider: str = ""
    llm_model: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None
    # Latest compile outcome (joined from compile_session_entry → compile_session):
    compiled_at: datetime | None = None
    compile_status: str | None = None
    compile_error: str | None = None
    compiled_version_id: uuid.UUID | None = None
