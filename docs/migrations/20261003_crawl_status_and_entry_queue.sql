-- Spec 406: Linked Page Extraction — Reliability & User Control
--
-- 1. Track crawl status on web_source so crawl and curation cannot overlap.
-- 2. Track crawl_status on web_source_history so we can count prior successful crawls.
-- 3. Extend kp_compile_session_entry status to include pending/running/failed,
--    making the compile entry table usable as a persistent job queue.

BEGIN;

-- 1. web_source: crawl lifecycle status
ALTER TABLE web_source
    ADD COLUMN crawl_status TEXT
        CHECK (crawl_status IN ('PENDING', 'SUCCESSFUL', 'FAILED'));

-- 2. web_source_history: record outcome of each historical crawl
--    NULL = crawl predating this migration (treat as SUCCESSFUL for counting purposes)
ALTER TABLE web_source_history
    ADD COLUMN crawl_status TEXT
        CHECK (crawl_status IN ('SUCCESSFUL', 'FAILED'));

-- 3. kp_compile_session_entry: add pending/running/failed to the status check
ALTER TABLE kp_compile_session_entry
    DROP CONSTRAINT compile_session_entry_status_check;

ALTER TABLE kp_compile_session_entry
    ADD CONSTRAINT kp_compile_session_entry_status_check
        CHECK (status IN ('pending', 'running', 'compiled', 'discarded', 'skipped', 'failed'));

COMMIT;
