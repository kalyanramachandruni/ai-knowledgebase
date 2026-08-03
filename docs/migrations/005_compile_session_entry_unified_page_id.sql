-- Migration 005: Unify compile_session_entry page reference
-- Drops the FK to confluence_page and the confluence_page_id TEXT column.
-- page_id becomes a plain UUID matching extraction_run.page_id (polymorphic).

BEGIN;

-- 1. Drop FK constraint on page_id (points to confluence_page)
ALTER TABLE compile_session_entry
    DROP CONSTRAINT IF EXISTS compile_session_entry_page_id_fkey;

-- 2. Back-fill page_id for web-page entries using extraction_run.page_id via run_id
--    (Confluence entries already have page_id set correctly; web entries had NULL)
UPDATE compile_session_entry cse
SET page_id = er.page_id
FROM extraction_run er
WHERE cse.run_id = er.id
  AND cse.page_id IS NULL
  AND er.page_source_type = 'web';

-- 3. Drop confluence_page_id column (denormalized Confluence external string ID)
ALTER TABLE compile_session_entry
    DROP COLUMN IF EXISTS confluence_page_id;

COMMIT;
