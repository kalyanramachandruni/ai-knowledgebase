# Rename Extraction Tables to Page Curation

## Context
`extraction_session` and `extraction_session_entry` are confusingly named — they
sound like they belong to the crawl pipeline. They actually represent the LLM-driven
step of reviewing and structuring a page's content into a knowledge draft.
Renaming them to `page_curation_session` / `page_curation_session_entry` makes
the domain clearer and avoids confusion with the web crawl session concept.

## Renames

### DB tables
| Old | New |
|-----|-----|
| `extraction_session` | `page_curation_session` |
| `extraction_session_entry` | `page_curation_session_entry` |

### Column renames in related tables
| Table | Old column | New column |
|-------|-----------|-----------|
| `compile_session_entry` | `entry_id` | `curation_entry_id` |

### Enum renames
| Old | New |
|-----|-----|
| `extraction_status` (Postgres enum) | `curation_status` |

## Backend

### `apps/api/app/infrastructure/db/models.py`
- Rename class `ExtractionSession` → `PageCurationSession`
- Rename class `ExtractionSessionEntry` → `PageCurationSessionEntry`
- Update `__tablename__` on both
- Update `__tablename__` FK references: `session_id` on `ExtractionSessionEntry` points to `page_curation_session`
- Rename `CompileSessionEntry.entry_id` column → `curation_entry_id`
- Update FK reference in `CompileSessionEntry`
- Rename Enum name `extraction_status` → `curation_status`

### `apps/api/app/infrastructure/db/extraction_repository.py`
- Update all ORM class references from `ExtractionSessionEntry` / `ExtractionSession` → new names
- Rename file to `curation_repository.py` (optional, lower priority)

### `apps/api/app/api/v1/routers/web_crawl.py`
- Update all imports and references to ORM models

### `apps/api/app/api/v1/routers/extraction.py`
- Update all imports and references to ORM models

### `apps/api/app/api/v1/routers/knowledge_products.py`
- Update any references to `CompileSessionEntry.entry_id` → `curation_entry_id`

### All other files that import `ExtractionSession` or `ExtractionSessionEntry`
- Update imports and attribute access

## DB migration (raw SQL — no alembic)
```sql
-- Rename tables
ALTER TABLE extraction_session RENAME TO page_curation_session;
ALTER TABLE extraction_session_entry RENAME TO page_curation_session_entry;

-- Rename column in compile_session_entry
ALTER TABLE compile_session_entry RENAME COLUMN entry_id TO curation_entry_id;

-- Rename enum
ALTER TYPE extraction_status RENAME TO curation_status;

-- Rename indexes/constraints referencing old names (Postgres renames these automatically on table rename,
-- but FK constraint names may need updating for clarity)
```

## Frontend
- `apps/web/src/lib/types.ts` — `ExtractionRun` type references no table names directly; no changes needed
- No API path changes (routes stay the same)

## Acceptance criteria
- [x] `extraction_session` table renamed to `page_curation_session` in DB
- [x] `extraction_session_entry` table renamed to `page_curation_session_entry` in DB
- [x] `compile_session_entry.entry_id` renamed to `curation_entry_id` in DB
- [x] `extraction_status` enum renamed to `curation_status` in DB
- [x] All ORM model classes updated to match new names
- [x] All repository/router code updated — no references to old names remain
- [x] API starts without error
- [x] Existing extraction and compile flows work end-to-end

## Out of scope
- Renaming `compile_session` / `compile_session_entry` tables
- Renaming the repository file
- Frontend type changes
