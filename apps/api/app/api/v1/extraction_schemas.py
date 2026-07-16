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
    reused: bool = False


class CompiledProductSummary(BaseModel):
    product_id: uuid.UUID
    product_key: str
    name: str
    version_id: uuid.UUID
    semver: str


class ExtractionRunWithProductResponse(ExtractionRunResponse):
    started_at: str | None = None
    compiled_product: CompiledProductSummary | None = None
    compiled_at: str | None = None
    compile_status: str | None = None
    compile_error: str | None = None
    compiled_version_id: str | None = None
    prev_compiled_product: CompiledProductSummary | None = None
    prev_compiled_at: str | None = None


class CompileFromExtractionRequest(BaseModel):
    product_key: str
    name: str
    owner: str
    created_by: uuid.UUID
    bump: VersionBump = VersionBump.MINOR
