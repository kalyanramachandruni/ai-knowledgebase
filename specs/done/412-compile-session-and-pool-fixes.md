# Compile Session Status and Page Pool Bug Fixes

## Context

Two bugs were discovered during post-compile investigation of a cs-102 session
(October 2026):

1. **Compile session stuck in `running`**: After all entries finished compiling, the
   `kp_compile_session.status` column was never updated to `"completed"` and
   `completed_at` was never written. The SSE `done` event was emitted correctly to the
   frontend, so users saw the compile finish — but the DB row remained `status = "running"`
   indefinitely.

2. **Silent page drops when status filters are active**: The compile button called
   `handleCompile(src.id, filteredPages)` where `filteredPages` reflects active UI
   filters (search terms, status checkboxes). If the user had, say, "not compiled to KP"
   checked when clicking Compile, only pages matching that filter were included in the
   compile pool — even if more pages had been explicitly selected via the bucket
   checkboxes. For the cs-102 session: 72 pages were selected but only 30 were submitted
   because a status filter was active.

## Data model

No schema changes.

## Backend

### Fix 1 — mark session completed (`curation.py`)

In the `generate()` SSE generator, after the page-processing loop and before yielding
the `done` event, open a new DB session and update the compile session:

```python
async with SessionLocal() as fin_session:
    fin_obj = await fin_session.get(CompileSession, compile_session_id)
    if fin_obj:
        fin_obj.status = "completed"
        fin_obj.completed_at = datetime.now(tz.utc)
        fin_session.add(fin_obj)
        await fin_session.commit()
yield _sse({"type": "done", ...})
```

A separate session is used because the outer `session` context is still open during
streaming and may have a stale view of the object.

Sessions created before this fix that are stuck in `running` with all entries in a
terminal state can be manually closed:

```sql
UPDATE kp_compile_session
SET status = 'completed', completed_at = NOW()
WHERE status = 'running'
  AND NOT EXISTS (
    SELECT 1 FROM kp_compile_session_entry
    WHERE session_id = kp_compile_session.id
      AND status IN ('pending', 'running')
  );
```

## Frontend

### Fix 2 — compile pool uses full source page list (`sources/page.tsx`)

Change the compile button's `onClick` to pass `srcPages` (the full unfiltered page list
for the source) instead of `filteredPages`:

```tsx
// Before
onClick={() => handleCompile(src.id, filteredPages)}

// After
onClick={() => handleCompile(src.id, srcPages)}
```

`handleCompile` already intersects the pool with `selectedWebPages`, so the effective
set is still exactly what the user selected via the bucket checkboxes. The change only
removes the unintentional further intersection with active UI filters.

`srcPages` is defined as `const srcPages = pages[src.id] ?? []` at the top of the
source card render, before any filter or sort is applied.

## Acceptance criteria

- [x] After all compile session entries reach a terminal state, `kp_compile_session.status`
      is set to `"completed"` and `completed_at` is populated
- [x] The `done` SSE event is still emitted to the frontend after the DB update
- [x] Compile button passes `srcPages` to `handleCompile`; active status/search filters
      do not reduce the number of pages submitted to the backend
- [x] Existing stuck `running` sessions (cs-102, October 2026) manually closed via SQL

## Out of scope

- Persisting the product brief text alongside the compile session (separate concern;
  would require a `brief_text` column on `kp_compile_session`)
- Automatic recovery of stuck sessions on server startup (the existing startup recovery
  in `main.py` already resets `running` entries to `failed`; a separate pass to close
  stuck sessions where all entries are compiled could be added later)
