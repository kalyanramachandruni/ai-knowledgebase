-- Migration 006: Split extraction_run into extraction_session + extraction_session_entry
-- Also adds LLM/status/timing fields to compile_session, product_name, knowledge_product_id.
-- Renames compile_session_entry.run_id → entry_id with FK to extraction_session_entry.

BEGIN;

-- ── 1. Create extraction_session ────────────────────────────────────────────

CREATE TABLE extraction_session (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    llm_provider    TEXT NOT NULL,
    llm_model       TEXT NOT NULL,
    status          extraction_status NOT NULL DEFAULT 'pending',
    started_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ
);

-- ── 2. Create extraction_session_entry from extraction_run ───────────────────

-- One session per existing run (1:1 mapping for historical data)
INSERT INTO extraction_session (id, llm_provider, llm_model, status, started_at, completed_at)
SELECT
    id,
    llm_provider,
    llm_model,
    status::extraction_status,
    started_at,
    completed_at
FROM extraction_run;

CREATE TABLE extraction_session_entry (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id      UUID NOT NULL REFERENCES extraction_session(id) ON DELETE CASCADE,
    page_id         UUID,
    page_source_type page_source_type_enum,
    status          extraction_status NOT NULL DEFAULT 'pending',
    structured_draft JSONB,
    error_message   TEXT
);

-- Copy rows from extraction_run → extraction_session_entry
-- Each old run becomes one entry in its own session (same UUID for both)
INSERT INTO extraction_session_entry (id, session_id, page_id, page_source_type, status, structured_draft, error_message)
SELECT
    id,
    id AS session_id,  -- session.id = entry.id = old run.id (1:1)
    page_id,
    page_source_type,
    status::extraction_status,
    structured_draft,
    error_message
FROM extraction_run;

CREATE INDEX ix_extraction_session_entry_page ON extraction_session_entry(page_id, page_source_type);

-- ── 3. Update knowledge_product_version FK ───────────────────────────────────

-- Rename column (still references same UUID, now points to extraction_session_entry)
ALTER TABLE knowledge_product_version
    RENAME COLUMN source_extraction_run_id TO source_extraction_entry_id;

-- Drop old FK constraint and re-add pointing to new table
ALTER TABLE knowledge_product_version
    DROP CONSTRAINT IF EXISTS knowledge_product_version_source_extraction_run_id_fkey;

ALTER TABLE knowledge_product_version
    ADD CONSTRAINT knowledge_product_version_source_extraction_entry_id_fkey
    FOREIGN KEY (source_extraction_entry_id) REFERENCES extraction_session_entry(id);

-- ── 4. Update compile_session_entry: rename run_id → entry_id ───────────────

-- Drop old FK constraint on run_id
ALTER TABLE compile_session_entry
    DROP CONSTRAINT IF EXISTS compile_session_entry_run_id_fkey;

ALTER TABLE compile_session_entry
    RENAME COLUMN run_id TO entry_id;

ALTER TABLE compile_session_entry
    ADD CONSTRAINT compile_session_entry_entry_id_fkey
    FOREIGN KEY (entry_id) REFERENCES extraction_session_entry(id);

-- ── 5. Add new columns to compile_session ────────────────────────────────────

ALTER TABLE compile_session
    ADD COLUMN IF NOT EXISTS knowledge_product_id UUID REFERENCES knowledge_product(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS product_name         TEXT,
    ADD COLUMN IF NOT EXISTS llm_provider         TEXT,
    ADD COLUMN IF NOT EXISTS llm_model            TEXT,
    ADD COLUMN IF NOT EXISTS status               TEXT,
    ADD COLUMN IF NOT EXISTS started_at           TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS completed_at         TIMESTAMPTZ;

-- Back-fill knowledge_product_id from version → product
UPDATE compile_session cs
SET knowledge_product_id = kpv.product_id
FROM knowledge_product_version kpv
WHERE kpv.id = cs.version_id
  AND cs.knowledge_product_id IS NULL;

-- Back-fill product_name from knowledge_product
UPDATE compile_session cs
SET product_name = kp.name
FROM knowledge_product kp
WHERE kp.id = cs.knowledge_product_id
  AND cs.product_name IS NULL;

-- ── 6. Drop extraction_run (data migrated above) ─────────────────────────────

-- Remove FKs that reference extraction_run before dropping
ALTER TABLE knowledge_product_version
    DROP CONSTRAINT IF EXISTS knowledge_product_version_source_extraction_run_id_fkey;

DROP TABLE IF EXISTS extraction_run;

COMMIT;
