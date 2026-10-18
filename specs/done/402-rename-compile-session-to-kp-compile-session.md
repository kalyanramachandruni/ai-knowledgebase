# Rename compile_session Tables to kp_compile_session

## Context
`compile_session` and `compile_session_entry` are knowledge-product compile tables but their
names don't reflect that clearly. Prefixing with `kp_` makes their ownership explicit and
consistent with the knowledge-product domain.

## Renames

### DB tables
| Old | New |
|-----|-----|
| `compile_session` | `kp_compile_session` |
| `compile_session_entry` | `kp_compile_session_entry` |

### ORM classes
| Old | New |
|-----|-----|
| `CompileSession` | `KpCompileSession` |
| `CompileSessionEntry` | `KpCompileSessionEntry` |

## Backend

### `apps/api/app/infrastructure/db/models.py`
- Rename class `CompileSession` → `KpCompileSession`, `__tablename__` = `"kp_compile_session"`
- Rename class `CompileSessionEntry` → `KpCompileSessionEntry`, `__tablename__` = `"kp_compile_session_entry"`
- Update FK in `KpCompileSessionEntry.session_id` to reference `kp_compile_session`
- Update relationship strings

### `apps/api/app/infrastructure/db/extraction_repository.py`
- Update imports and all class references

### `apps/api/app/api/v1/routers/extraction.py`
- Update inline import and all class references

### `apps/api/app/api/v1/routers/web_crawl.py`
- Update inline imports and all class references

### `apps/api/app/api/v1/routers/knowledge_products.py`
- Update top-level import and all class references

## DB migration (raw SQL — no alembic)
```sql
ALTER TABLE compile_session RENAME TO kp_compile_session;
ALTER TABLE compile_session_entry RENAME TO kp_compile_session_entry;
```

## Acceptance criteria
- [x] `compile_session` renamed to `kp_compile_session` in DB
- [x] `compile_session_entry` renamed to `kp_compile_session_entry` in DB
- [x] All ORM model classes updated to new names
- [x] All repository/router code updated — no references to old names remain
- [x] API starts without error
- [x] Existing compile flows work end-to-end

## Out of scope
- Renaming any columns within these tables
- Frontend changes
