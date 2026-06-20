from __future__ import annotations

import uuid

from pydantic import BaseModel

from app.domain.knowledge_product.value_objects import VersionBump


class ExtractionRunResponse(BaseModel):
    id: uuid.UUID
    page_id: uuid.UUID
    status: str
    llm_provider: str
    llm_model: str
    structured_draft: dict | None
    error_message: str | None


class CompileFromExtractionRequest(BaseModel):
    product_key: str
    name: str
    owner: str
    created_by: uuid.UUID
    bump: VersionBump = VersionBump.MINOR
