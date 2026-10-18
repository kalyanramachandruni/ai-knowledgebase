from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ARRAY, BigInteger, Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.sql import func

# This module mirrors docs/db_schema.sql exactly. If you change one, change the other.


class Base(DeclarativeBase):
    pass


class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String, nullable=False)
    sso_subject: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ConfluenceSpace(Base):
    __tablename__ = "confluence_space"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    space_key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    base_url: Mapped[str] = mapped_column(String, nullable=False)
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_sync_created: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_sync_updated: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_sync_skipped: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    pages: Mapped[list["ConfluencePage"]] = relationship(back_populates="space")


class ConfluencePage(Base):
    __tablename__ = "confluence_page"
    __table_args__ = (UniqueConstraint("space_id", "confluence_page_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    space_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("confluence_space.id", ondelete="CASCADE"))
    confluence_page_id: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body_storage_format: Mapped[str] = mapped_column(Text, nullable=False)
    labels: Mapped[list[str]] = mapped_column(ARRAY(String), default=list)
    confluence_version: Mapped[int] = mapped_column(Integer, nullable=False)
    last_modified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    space: Mapped[ConfluenceSpace] = relationship(back_populates="pages")


class ConfluenceAttachment(Base):
    __tablename__ = "confluence_attachment"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("confluence_page.id", ondelete="CASCADE"))
    file_name: Mapped[str] = mapped_column(String, nullable=False)
    media_type: Mapped[str] = mapped_column(String, nullable=False)
    download_url: Mapped[str] = mapped_column(String, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebSource(Base):
    __tablename__ = "web_source"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String, nullable=False)
    root_url: Mapped[str] = mapped_column(String, nullable=False)
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_crawl_created: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_crawl_updated: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_crawl_skipped: Mapped[int | None] = mapped_column(Integer, nullable=True)
    crawl_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None = unlimited
    include_query_strings: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    crawl_status: Mapped[str | None] = mapped_column(String, nullable=True)  # PENDING | SUCCESSFUL | FAILED | NULL=never crawled
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    pages: Mapped[list["WebPage"]] = relationship(back_populates="source", cascade="all, delete-orphan", passive_deletes=True)


class WebSourceHistory(Base):
    __tablename__ = "web_source_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("web_source.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    root_url: Mapped[str] = mapped_column(String, nullable=False)
    crawl_depth: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_crawled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_crawl_created: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_crawl_updated: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_crawl_skipped: Mapped[int | None] = mapped_column(Integer, nullable=True)
    crawl_status: Mapped[str | None] = mapped_column(String, nullable=True)  # SUCCESSFUL | FAILED | NULL=pre-406
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebPage(Base):
    __tablename__ = "web_page"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("web_source.id", ondelete="CASCADE"), nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False, unique=False)
    title: Mapped[str] = mapped_column(String, nullable=False, default="Untitled")
    plain_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    changed_since_extraction: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_thin_content: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    js_rendered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")

    source: Mapped["WebSource"] = relationship(back_populates="pages")

    __table_args__ = (UniqueConstraint("source_id", "url"),)


class WebPageHistory(Base):
    """Snapshot of a web_page row captured just before a re-crawl update overwrites it."""
    __tablename__ = "web_page_history"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("web_page.id", ondelete="CASCADE"), nullable=False, index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    plain_text: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class WebPageLink(Base):
    """Links discovered on a web page during crawl."""
    __tablename__ = "web_page_link"
    __table_args__ = (UniqueConstraint("source_page_id", "url"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("web_page.id", ondelete="CASCADE"), nullable=False)
    url: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(String, nullable=True)
    # Set when the linked URL has been crawled into web_page
    linked_page_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("web_page.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class PageCurationSession(Base):
    """Session-level metadata: one LLM curation call context that may cover one or more pages."""
    __tablename__ = "page_curation_session"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    llm_provider: Mapped[str] = mapped_column(String, nullable=False)
    llm_model: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("pending", "running", "succeeded", "failed", name="curation_status"),
        default="pending",
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    entries: Mapped[list["PageCurationSessionEntry"]] = relationship(
        "PageCurationSessionEntry", back_populates="session_obj", cascade="all, delete-orphan"
    )


class PageCurationSessionEntry(Base):
    """Per-page curation result within a session."""
    __tablename__ = "page_curation_session_entry"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("page_curation_session.id", ondelete="CASCADE"), nullable=False
    )
    # page_id points to either confluence_page.id or web_page.id depending on page_source_type
    page_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    page_source_type: Mapped[str | None] = mapped_column(
        Enum("confluence", "web", name="page_source_type_enum"), nullable=True
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "running", "succeeded", "failed", name="curation_status"),
        default="pending",
    )
    structured_draft: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    session_obj: Mapped["PageCurationSession"] = relationship("PageCurationSession", back_populates="entries")


class KnowledgeProductModel(Base):
    __tablename__ = "knowledge_product"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_key: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    owner: Mapped[str] = mapped_column(String, nullable=False)
    current_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("knowledge_product_version.id", use_alter=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    versions: Mapped[list["KnowledgeProductVersionModel"]] = relationship(
        back_populates="product",
        foreign_keys="KnowledgeProductVersionModel.product_id",
        order_by="KnowledgeProductVersionModel.created_at",
    )


class KnowledgeProductVersionModel(Base):
    __tablename__ = "knowledge_product_version"
    __table_args__ = (UniqueConstraint("product_id", "semver"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_product.id", ondelete="CASCADE"))
    semver: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(
        Enum("draft", "review", "approved", "published", "retired", name="knowledge_product_status"),
        default="draft",
    )
    yaml_content: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_extraction_entry_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("page_curation_session_entry.id"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    compiled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    product: Mapped[KnowledgeProductModel] = relationship(
        back_populates="versions", foreign_keys=[product_id]
    )


class ApprovalRequest(Base):
    __tablename__ = "approval_request"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("knowledge_product_version.id", ondelete="CASCADE")
    )
    requested_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("app_user.id"), nullable=False)
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    decision: Mapped[str] = mapped_column(
        Enum("pending", "approved", "rejected", name="approval_decision"), default="pending"
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEntry(Base):
    __tablename__ = "audit_entry"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(String, nullable=False)
    entity_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)
    diff: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EventOutbox(Base):
    __tablename__ = "event_outbox"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_type: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Document(Base):
    """Confluence-like rich-text document for the built-in wiki/docs editor."""

    __tablename__ = "document"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="Untitled")
    # TipTap stores its document as a JSON object; TEXT falls back for plain HTML
    content: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    children: Mapped[list["Document"]] = relationship(
        "Document",
        backref=__import__("sqlalchemy.orm", fromlist=["backref"]).backref("parent", remote_side="Document.id"),
        foreign_keys=[parent_id],
    )


class KpCompileSession(Base):
    __tablename__ = "kp_compile_session"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("knowledge_product_version.id", ondelete="CASCADE"), nullable=False)
    knowledge_product_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("knowledge_product.id", ondelete="SET NULL"), nullable=True)
    product_name: Mapped[str | None] = mapped_column(String, nullable=True)
    llm_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    llm_model: Mapped[str | None] = mapped_column(String, nullable=True)
    status: Mapped[str | None] = mapped_column(String, nullable=True)  # running | succeeded | failed
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("app_user.id"), nullable=True)

    entries: Mapped[list["KpCompileSessionEntry"]] = relationship("KpCompileSessionEntry", back_populates="session", cascade="all, delete-orphan")


class KpCompileSessionEntry(Base):
    __tablename__ = "kp_compile_session_entry"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kp_compile_session.id", ondelete="CASCADE"), nullable=False)
    curation_entry_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("page_curation_session_entry.id"), nullable=True)
    # page_id mirrors page_curation_session_entry.page_id — same polymorphic UUID, no FK constraint
    page_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    page_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String, nullable=False)   # compiled | discarded | skipped
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    compiled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped["KpCompileSession"] = relationship("KpCompileSession", back_populates="entries")
