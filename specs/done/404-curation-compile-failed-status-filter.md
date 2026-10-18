# Curation Failed / Compile Failed Status Filter

## Context
The Web Wikis status filter currently treats all failures as a single "Failed"
bucket. Two distinct failure modes exist:
- **Curation failed** — the LLM curation step failed (`page_curation_session_entry.status = "failed"`)
- **Compile failed** — the page was included in a compile run but errored out (`kp_compile_session_entry.status = "skipped"`)

These need to be separate filter options so operators can triage each failure type
independently.

## Data model
No schema changes. `kp_compile_session_entry.status` already records `"skipped"`
for pages that errored during compilation.

## Backend

### `apps/api/app/api/v1/routers/web_crawl.py`
- Add `latest_compile_status: str | None = None` to `WebPageResponse`
- Replace the existing compile query (which only fetches `max(compiled_at)` for
  `status = "compiled"`) with a query that fetches the latest
  `kp_compile_session_entry` row per page regardless of status, ordered by
  `created_at DESC`
- Populate `latest_compile_status` and `is_compiled` / `compiled_at` from that result

## Frontend

### `apps/web/src/lib/types.ts`
- Add `latest_compile_status?: string | null` to `WebPage`

### `apps/web/src/app/sources/page.tsx`
- Rename `"failed"` status option to `"curation_failed"` / label "Curation Failed"
- Add `"compile_failed"` / label "Compile Failed" to `STATUS_OPTIONS`
- Update `getDistinctStatuses`:
  - emit `"curation_failed"` when `latest_run_status === "failed"`
  - emit `"compile_failed"` when `latest_compile_status === "skipped"`
- Update filter predicate to match

## Acceptance criteria
- [x] `WebPageResponse` includes `latest_compile_status`
- [x] "Curation Failed" and "Compile Failed" appear as separate options in the status dropdown
- [x] Only options present in the actual data are shown
- [x] Filtering by "Curation Failed" shows only pages where curation errored
- [x] Filtering by "Compile Failed" shows only pages where the compile step errored
- [x] TypeScript compiles without errors

## Out of scope
- Changes to `kp_compile_session_entry` status values
- Any other tabs or pages
