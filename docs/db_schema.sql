-- Knowledge Product Studio — canonical schema
-- Postgres 15+. Mirrors apps/api/app/infrastructure/db/models.py exactly;
-- Alembic migrations under apps/api/migrations/ are generated from the ORM models.

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============ Identity / Governance ============

CREATE TABLE app_user (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email           TEXT NOT NULL UNIQUE,
    display_name    TEXT NOT NULL,
    sso_subject     TEXT UNIQUE,             -- OIDC `sub` claim, nullable for non-SSO
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TYPE role_name AS ENUM ('admin', 'knowledge_owner', 'reviewer', 'consumer');

CREATE TABLE user_role (
    user_id     UUID NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    role        role_name NOT NULL,
    PRIMARY KEY (user_id, role)
);

-- ============ Confluence Ingestion ============

CREATE TABLE confluence_space (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    space_key       TEXT NOT NULL UNIQUE,
    name            TEXT NOT NULL,
    base_url        TEXT NOT NULL,
    last_synced_at  TIMESTAMPTZ,
    last_sync_created INTEGER,
    last_sync_updated INTEGER,
    last_sync_skipped INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE confluence_page (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    space_id            UUID NOT NULL REFERENCES confluence_space(id) ON DELETE CASCADE,
    confluence_page_id  TEXT NOT NULL,              -- Confluence's own page id
    title               TEXT NOT NULL,
    body_storage_format TEXT NOT NULL,               -- raw Confluence storage-format XHTML
    labels              TEXT[] NOT NULL DEFAULT '{}',
    confluence_version  INTEGER NOT NULL,             -- Confluence's version number, drives incremental sync
    last_modified_at    TIMESTAMPTZ NOT NULL,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (space_id, confluence_page_id)
);

CREATE INDEX ix_confluence_page_space ON confluence_page(space_id);

CREATE TABLE confluence_attachment (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    page_id         UUID NOT NULL REFERENCES confluence_page(id) ON DELETE CASCADE,
    file_name       TEXT NOT NULL,
    media_type      TEXT NOT NULL,
    download_url    TEXT NOT NULL,
    size_bytes      BIGINT NOT NULL,
    fetched_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============ Knowledge Extraction ============

CREATE TYPE extraction_status AS ENUM ('pending', 'running', 'succeeded', 'failed');

CREATE TABLE extraction_run (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    page_id         UUID NOT NULL REFERENCES confluence_page(id) ON DELETE CASCADE,
    status          extraction_status NOT NULL DEFAULT 'pending',
    llm_provider    TEXT NOT NULL,                  -- e.g. "anthropic", "openai"
    llm_model       TEXT NOT NULL,
    structured_draft JSONB,                          -- raw extracted components before compilation
    error_message   TEXT,
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    compiled_at         TIMESTAMPTZ,
    compiled_version_id UUID REFERENCES knowledge_product_version(id),
    compile_status      TEXT,                         -- 'succeeded' | 'failed'
    compile_error       TEXT
);

CREATE INDEX ix_extraction_run_page ON extraction_run(page_id);

-- ============ Knowledge Product Registry ============

CREATE TYPE knowledge_product_status AS ENUM ('draft', 'review', 'approved', 'published', 'retired');

-- Stable identity across all versions of one product.
CREATE TABLE knowledge_product (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_key     TEXT NOT NULL UNIQUE,            -- human-stable slug, e.g. "shipment_creation"
    name            TEXT NOT NULL,
    owner           TEXT NOT NULL,                   -- owning team/business unit
    current_version_id UUID,                          -- FK to latest knowledge_product_version, set after insert
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Immutable version snapshot. Every edit creates a new row, never an UPDATE of yaml_content.
CREATE TABLE knowledge_product_version (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id      UUID NOT NULL REFERENCES knowledge_product(id) ON DELETE CASCADE,
    semver          TEXT NOT NULL,                    -- e.g. "1.2.0"
    status          knowledge_product_status NOT NULL DEFAULT 'draft',
    yaml_content     JSONB NOT NULL,                  -- canonical Knowledge Product YAML, stored as JSONB
    source_extraction_run_id UUID REFERENCES extraction_run(id),
    created_by      UUID NOT NULL REFERENCES app_user(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    published_at    TIMESTAMPTZ,
    retired_at      TIMESTAMPTZ,
    UNIQUE (product_id, semver)
);

CREATE INDEX ix_kp_version_product ON knowledge_product_version(product_id);
CREATE INDEX ix_kp_version_status ON knowledge_product_version(status);
CREATE INDEX ix_kp_version_yaml_gin ON knowledge_product_version USING GIN (yaml_content);

ALTER TABLE knowledge_product
    ADD CONSTRAINT fk_kp_current_version
    FOREIGN KEY (current_version_id) REFERENCES knowledge_product_version(id);

-- ============ Governance: Approval workflow + Audit ============

CREATE TYPE approval_decision AS ENUM ('pending', 'approved', 'rejected');

CREATE TABLE approval_request (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id      UUID NOT NULL REFERENCES knowledge_product_version(id) ON DELETE CASCADE,
    requested_by    UUID NOT NULL REFERENCES app_user(id),
    reviewer_id     UUID REFERENCES app_user(id),
    decision        approval_decision NOT NULL DEFAULT 'pending',
    comment         TEXT,
    requested_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    decided_at      TIMESTAMPTZ
);

CREATE TABLE audit_entry (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_type     TEXT NOT NULL,                   -- "knowledge_product_version", "approval_request", ...
    entity_id       UUID NOT NULL,
    action          TEXT NOT NULL,                   -- "created", "status_changed", "approved", "published", ...
    actor_id        UUID REFERENCES app_user(id),
    diff            JSONB,                            -- field-level before/after, when applicable
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX ix_audit_entity ON audit_entry(entity_type, entity_id);

-- ============ Event Outbox (in-process event bus → future Kafka/SNS) ============

CREATE TABLE event_outbox (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type      TEXT NOT NULL,                   -- "PageIngested", "KnowledgeExtracted", "ProductPublished", ...
    payload         JSONB NOT NULL,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at    TIMESTAMPTZ
);
