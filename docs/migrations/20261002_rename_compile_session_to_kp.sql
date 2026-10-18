-- Rename compile_session tables to kp_compile_session to make their
-- knowledge-product ownership explicit.
--
-- Run this migration once against the target database before deploying the updated API.

BEGIN;

-- 1. Rename the session table (Postgres auto-renames its indexes/sequences)
ALTER TABLE compile_session RENAME TO kp_compile_session;

-- 2. Rename the entry table
ALTER TABLE compile_session_entry RENAME TO kp_compile_session_entry;

-- 3. Fix the FK constraint name on kp_compile_session_entry
ALTER TABLE kp_compile_session_entry
    RENAME CONSTRAINT compile_session_entry_session_id_fkey
    TO kp_compile_session_entry_session_id_fkey;

COMMIT;
