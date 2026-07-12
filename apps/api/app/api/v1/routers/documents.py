from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    SessionDep,
    get_compile_from_extraction_use_case,
    get_create_use_case,
    get_compile_use_case,
    get_llm_port,
    get_repository,
)
from app.application.extraction.compiler import CompileFromExtractionUseCase, _extraction_result_to_compile_input
from app.application.knowledge_product.dto import CreateKnowledgeProductInput
from app.application.knowledge_product.use_cases import CreateKnowledgeProductUseCase, CompileNewVersionUseCase
from app.core.config import settings
from app.core.security import CurrentUser, get_current_user
from app.domain.extraction.ports import LLMExtractionPort
from app.domain.extraction.schema import KNOWLEDGE_EXTRACTION_SCHEMA
from app.domain.knowledge_product.value_objects import VersionBump
from app.infrastructure.db.models import Document
from app.infrastructure.db.repository import SqlAlchemyKnowledgeProductRepository

router = APIRouter(prefix="/documents", tags=["documents"])


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class DocumentSummary(BaseModel):
    id: uuid.UUID
    title: str
    parent_id: uuid.UUID | None
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentDetail(DocumentSummary):
    content: dict | None
    created_at: datetime


class CreateDocumentRequest(BaseModel):
    title: str = "Untitled"
    parent_id: uuid.UUID | None = None


class UpdateDocumentRequest(BaseModel):
    title: str | None = None
    content: dict | None = None


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=list[DocumentSummary])
async def list_documents(
    session: SessionDep,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> list[DocumentSummary]:
    rows = (await session.execute(select(Document).order_by(Document.updated_at.desc()))).scalars().all()
    return [DocumentSummary.model_validate(r) for r in rows]


@router.get("/{doc_id}", response_model=DocumentDetail)
async def get_document(
    doc_id: uuid.UUID,
    session: SessionDep,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> DocumentDetail:
    row = await session.get(Document, doc_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentDetail.model_validate(row)


@router.post("", response_model=DocumentDetail, status_code=201)
async def create_document(
    payload: CreateDocumentRequest,
    session: SessionDep,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> DocumentDetail:
    doc = Document(title=payload.title, parent_id=payload.parent_id)
    session.add(doc)
    await session.commit()
    await session.refresh(doc)
    return DocumentDetail.model_validate(doc)


@router.put("/{doc_id}", response_model=DocumentDetail)
async def update_document(
    doc_id: uuid.UUID,
    payload: UpdateDocumentRequest,
    session: SessionDep,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> DocumentDetail:
    doc = await session.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    if payload.title is not None:
        doc.title = payload.title
    if payload.content is not None:
        doc.content = payload.content
    # Manually bump updated_at since onupdate only fires on ORM flush via Core UPDATE
    from app.domain.shared.base import utc_now
    doc.updated_at = utc_now()
    await session.commit()
    await session.refresh(doc)
    return DocumentDetail.model_validate(doc)


@router.delete("/{doc_id}", status_code=204)
async def delete_document(
    doc_id: uuid.UUID,
    session: SessionDep,
    _current_user: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    doc = await session.get(Document, doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")
    await session.delete(doc)
    await session.commit()


# ── Compile document(s) → Knowledge Product ───────────────────────────────────

class CompileDocumentRequest(BaseModel):
    product_key: str
    name: str
    owner: str
    include_subpages: bool = True
    bump: str = "minor"


def _tiptap_to_text(node: dict) -> str:
    """Recursively convert a TipTap JSON node to plain text."""
    if not node:
        return ""
    ntype = node.get("type", "")
    if ntype == "text":
        return node.get("text", "")
    children = node.get("content", [])
    parts = [_tiptap_to_text(c) for c in children]
    joined = "".join(parts)
    if ntype in ("paragraph", "heading"):
        return joined + "\n"
    if ntype == "listItem":
        return "• " + joined
    if ntype == "codeBlock":
        return "```\n" + joined + "\n```\n"
    if ntype == "hardBreak":
        return "\n"
    return joined


async def _collect_doc_text(
    session: AsyncSession, root_id: uuid.UUID, include_subpages: bool
) -> str:
    """Gather the root doc + optional subpages and return combined plain text."""
    root = await session.get(Document, root_id)
    if root is None:
        raise HTTPException(status_code=404, detail="Document not found")

    docs = [root]
    if include_subpages:
        # BFS over children
        queue = [root_id]
        while queue:
            parent_id = queue.pop(0)
            rows = (
                await session.execute(
                    select(Document).where(Document.parent_id == parent_id)
                )
            ).scalars().all()
            for child in rows:
                docs.append(child)
                queue.append(child.id)

    sections: list[str] = []
    for doc in docs:
        header = f"# {doc.title}\n"
        body = _tiptap_to_text(doc.content or {})
        sections.append(header + body)

    return "\n\n".join(sections)


@router.post("/{doc_id}/compile")
async def compile_document_to_knowledge_product(
    doc_id: uuid.UUID,
    payload: CompileDocumentRequest,
    session: SessionDep,
    current_user: Annotated[CurrentUser, Depends(get_current_user)],
    llm_port: Annotated[LLMExtractionPort, Depends(get_llm_port)],
    repository: Annotated[SqlAlchemyKnowledgeProductRepository, Depends(get_repository)],
    create_use_case: Annotated[CreateKnowledgeProductUseCase, Depends(get_create_use_case)],
    compile_use_case: Annotated[CompileNewVersionUseCase, Depends(get_compile_use_case)],
) -> dict:
    plain_text = await _collect_doc_text(session, doc_id, payload.include_subpages)

    result = await llm_port.extract(plain_text, KNOWLEDGE_EXTRACTION_SCHEMA)

    bump = VersionBump(payload.bump)
    created_by = current_user.user_id if isinstance(current_user.user_id, uuid.UUID) else uuid.UUID(current_user.user_id)

    compile_input = _extraction_result_to_compile_input(
        result, created_by=created_by, bump=bump, source_extraction_run_id=None
    )

    existing = await repository.get_by_key(payload.product_key)
    if existing is None:
        product = await create_use_case.execute(
            CreateKnowledgeProductInput(
                product_key=payload.product_key,
                name=payload.name,
                owner=payload.owner,
                compile_input=compile_input,
            )
        )
    else:
        from app.application.extraction.compiler import _version_to_extraction_result
        existing_result = _version_to_extraction_result(existing.current_version)
        merged = await llm_port.merge(existing_result, result, KNOWLEDGE_EXTRACTION_SCHEMA)
        merged_input = _extraction_result_to_compile_input(
            merged, created_by=created_by, bump=bump, source_extraction_run_id=None
        )
        await compile_use_case.execute(existing.id, merged_input)
        product = await repository.get_by_id(existing.id)

    return {"id": str(product.id), "product_key": product.product_key, "name": product.name}
