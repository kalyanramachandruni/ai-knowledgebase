# Per-KP Page Compilation Status on Sources Page

## Context

The Sources page shows curation status per page but gives no visibility into which pages
have been compiled into Knowledge Products. A user crawling a 400-page source has no way
to answer "which pages are already in KP X?" or "which pages are curated but not yet in
any KP?" without opening each KP individually.

This spec adds:
1. A **Compiled** column next to Curation showing how many KPs each page is in.
2. A **KP dropdown** above the table listing all KPs that have at least one page from
   this source compiled into them.
3. A **"Show pages not in KP"** checkbox that inverts the KP filter to surface gaps.
4. A **`not_relevant` status** in the compile entry table so that pages the LLM brief
   filter skipped are recorded and visible when browsing the gap list — rather than
   silently disappearing.

## Data model

### `kp_compile_session_entry.status` extension

Add `not_relevant` as a new valid value alongside `compiled | discarded | skipped`.
A page gets this status when the LLM `merge()` detects it is off-topic relative to the
product brief (i.e. the merge returned the existing KP unchanged).

Migration:
```sql
-- Extend the status check constraint to allow 'not_relevant'
ALTER TABLE kp_compile_session_entry
  DROP CONSTRAINT IF EXISTS kp_compile_session_entry_status_check;
ALTER TABLE kp_compile_session_entry
  ADD CONSTRAINT kp_compile_session_entry_status_check
  CHECK (status IN ('compiled','discarded','skipped','pending','running','failed','not_relevant'));
```

No new table is needed. All KP membership queries are derivable from existing tables:

```
kp_compile_session_entry
  .curation_entry_id → page_curation_session_entry.id → .page_id → web_page
  .session_id        → kp_compile_session.knowledge_product_id / product_name
```

(`kp_compile_session_entry.page_id` mirrors the curation entry's page_id and can also
be used directly for these joins.)

### LLM `merge()` — `changed` signal

`LLMCurationPort.merge()` must return a `(CurationResult, changed: bool)` pair.
When `changed=False`, the batch-compile endpoint records the page as `not_relevant`
rather than `compiled`.

**Detection approach**: add a `relevant: bool` field to the `extract_knowledge` tool
schema used during merge, and instruct the LLM to set it `false` when the brief filter
causes it to return the existing KP unchanged. This is an explicit signal — no fragile
before/after deep-equal comparison needed.

## Backend

### New endpoint — compiled KPs for a source

```
GET /web-sources/{source_id}/compiled-kps
```

Response:
```json
[
  {
    "product_id": "uuid",
    "product_key": "onboarding-process",
    "product_name": "Onboarding Process",
    "compiled_page_count": 12
  }
]
```

Returns one row per KP that has at least one `compiled` entry whose page belongs to
this source. Ordered by `product_name`.

### Extended `WebPage` response

Add one field to the existing `WebPage` API schema:

```python
compiled_kp_count: int  # 0 = not in any KP; ≥1 = compiled into that many KPs
```

Populated by a single aggregation query alongside the existing `listWebPages` join.

### New endpoint — per-page KP status for one KP

```
GET /web-sources/{source_id}/pages/kp-status?product_id={uuid}
```

Response:
```json
[
  { "page_id": "uuid", "status": "compiled" | "not_relevant" | "none" }
]
```

`compiled`     — page has a `compiled` entry in this KP's sessions  
`not_relevant` — page has a `not_relevant` entry (brief filter rejected it)  
`none`         — page has no entry for this KP at all

Every page in the source is returned (pages with no entry get `none`).

### Batch-compile endpoint changes

After each `llm_port.merge()` call:
- If `changed=True`  → record entry as `compiled` (existing behaviour)
- If `changed=False` → record entry as `not_relevant` with reason
  `"LLM brief filter: page not relevant to this Knowledge Product"`

## Frontend

### Compiled column

Add a **Compiled** column to the right of Curation in the pages table.

- `compiled_kp_count == 0` → `—`
- `compiled_kp_count >= 1` → green badge **"In N KPs"**

Column width ~110 px; same resize handle as existing columns.

### KP dropdown

Above the pages table (to the right of the existing filter row), render a `<select>`
populated from `GET /web-sources/{source_id}/compiled-kps`.

- Default option: **"All pages"** (no filter)
- Each option: `{product_name}` with compiled page count in parentheses

Only render the dropdown when the source has ≥ 1 compiled KP. Fetch the list once when
the source's pages panel is expanded; refresh after each compile.

### "Show pages not in KP" checkbox

Rendered next to the KP dropdown; disabled when no KP is selected.

**Filter behaviour**

| KP selected | Checkbox | What is shown |
|-------------|----------|---------------|
| No          | —        | All pages (default) |
| Yes         | Off      | Only pages with `kp-status = compiled` for that KP |
| Yes         | On       | Pages with `kp-status = not_relevant` OR `none` for that KP |

When the checkbox is on, show a small label next to each page row indicating
`Not relevant` (amber badge) vs `Not compiled` (grey badge) so the user can distinguish
"was tried and rejected" from "never included".

### State

```typescript
// per source
selectedKpId: string | null
showNotInKp: boolean
kpStatusMap: Record<string, "compiled" | "not_relevant" | "none">  // page_id → status
```

`kpStatusMap` is fetched from the `pages/kp-status` endpoint whenever `selectedKpId`
changes, then used to filter `filteredPages` before rendering.

## Acceptance criteria

- [x] `kp_compile_session_entry` allows `not_relevant` status without DB errors
- [x] `LLMCurationPort.merge()` returns `(CurationResult, changed: bool)`; the batch-compile endpoint records `not_relevant` when `changed=False`
- [x] `GET /web-sources/{source_id}/compiled-kps` returns correct list and counts
- [x] `WebPage` API response includes `compiled_kp_count`
- [x] `GET /web-sources/{source_id}/pages/kp-status?product_id=...` returns a row for every page in the source with correct status
- [x] Sources page shows a **Compiled** column with "In N KPs" badge or "—"
- [x] KP dropdown appears when source has ≥ 1 compiled KP; not shown otherwise
- [x] Selecting a KP (checkbox off) shows only pages compiled into that KP
- [x] Selecting a KP + checking "Show pages not in KP" shows pages with `not_relevant` or `none` status, with distinct badges for each
- [x] "Show pages not in KP" checkbox is disabled when no KP is selected
- [x] KP dropdown and status map refresh after a compile completes
- [x] Legend updated to explain the new "In N KPs", "Not relevant", and "Not compiled" badges

## Out of scope

- Showing compile history / version details per page (covered by the existing Compiled badge tooltip)
- Filtering by multiple KPs simultaneously
- "Force-recompile pages already in KP" action (separate feature)
- Confluence pages (web sources only for now)
