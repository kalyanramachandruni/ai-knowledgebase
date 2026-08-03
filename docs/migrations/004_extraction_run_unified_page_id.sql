-- Migration 004: Unify extraction_run page references into a single page_id column
-- with a page_source_type enum to distinguish confluence vs web pages.
--
-- Before: two nullable FK columns (page_id → confluence_page, web_page_id → web_page)
-- After:  one plain UUID column (page_id) + page_source_type enum

BEGIN;

-- 1. Create the enum type
CREATE TYPE page_source_type_enum AS ENUM ('confluence', 'web');

-- 2. Add the new columns
ALTER TABLE extraction_run
    ADD COLUMN page_source_type page_source_type_enum,
    ADD COLUMN new_page_id UUID;

-- 3. Back-fill from existing columns
--    Rows with page_id set (confluence) → copy to new_page_id, set type = confluence
UPDATE extraction_run
SET new_page_id = page_id,
    page_source_type = 'confluence'
WHERE page_id IS NOT NULL;

--    Rows with web_page_id set → copy to new_page_id, set type = web
UPDATE extraction_run
SET new_page_id = web_page_id,
    page_source_type = 'web'
WHERE web_page_id IS NOT NULL AND page_id IS NULL;

-- 4. Drop old FK constraints (names may vary — drop both known names)
ALTER TABLE extraction_run
    DROP CONSTRAINT IF EXISTS extraction_run_page_id_fkey,
    DROP CONSTRAINT IF EXISTS extraction_run_web_page_id_fkey;

-- 5. Drop old index on page_id
DROP INDEX IF EXISTS ix_extraction_run_page;

-- 6. Drop old columns
ALTER TABLE extraction_run
    DROP COLUMN page_id,
    DROP COLUMN web_page_id;

-- 7. Rename new_page_id → page_id
ALTER TABLE extraction_run
    RENAME COLUMN new_page_id TO page_id;

-- 8. Recreate index
CREATE INDEX ix_extraction_run_page ON extraction_run(page_id, page_source_type);

COMMIT;
