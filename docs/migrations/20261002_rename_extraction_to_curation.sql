-- Rename extraction tables and column to reflect their actual domain role:
-- page curation (LLM-driven structuring of page content), not "extraction" (which sounds like crawling).
--
-- Run this migration once against the target database before deploying the updated API.

BEGIN;

-- 1. Rename the enum type used by both tables
ALTER TYPE extraction_status RENAME TO curation_status;

-- 2. Rename the session table
ALTER TABLE extraction_session RENAME TO page_curation_session;

-- 3. Rename the entry table
ALTER TABLE extraction_session_entry RENAME TO page_curation_session_entry;

-- 4. Fix the FK constraint name on page_curation_session_entry (Postgres auto-renamed the
--    column's constraint when the parent table was renamed, but the constraint itself keeps
--    the old name — rename it for clarity).
ALTER TABLE page_curation_session_entry
    RENAME CONSTRAINT extraction_session_entry_session_id_fkey
    TO page_curation_session_entry_session_id_fkey;

-- 5. Rename entry_id → curation_entry_id in kp_compile_session_entry
ALTER TABLE kp_compile_session_entry RENAME COLUMN entry_id TO curation_entry_id;

COMMIT;
