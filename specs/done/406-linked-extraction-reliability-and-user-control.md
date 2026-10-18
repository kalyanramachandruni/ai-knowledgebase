# Linked Page Extraction — Reliability & User Control

## Context

Four problems exist in the current linked page extraction flow:

1. **Crawl and curation can run concurrently on the same source.** There is no mutual
   exclusion between the main crawl (`POST /{source_id}/crawl`) and curation
   (`POST /{source_id}/pages/{page_id}/extract`). A crawl that updates page content while
   curation is running produces a stale draft and an incorrect `changed_since_extraction`
   state. The fix is to track an `is_crawling` flag on `web_source` and enforce that crawl
   and curation never overlap on the same source.

2. **Auto-extraction of linked pages without user confirmation.** Every successful curation
   silently triggers a background crawl + auto-extraction of all linked pages. The user has no
   visibility into what is being queued and no way to opt out.

3. **Duplicate linked-page extraction in bulk mode.** When multiple pages are curated in
   bulk, each triggers its own `_crawl_and_extract_linked` call. Pages linked from more than
   one selected page get crawled and extracted N times — once per parent.

4. **No durability for background tasks.** `BackgroundTasks.add_task` is in-process and
   fire-and-forget. If the server is interrupted (Ctrl+C, crash, OOM) all queued linked crawls
   are silently lost.

## Data model

### New column: `web_source.crawl_status`

```sql
ALTER TABLE web_source
    ADD COLUMN crawl_status TEXT
        CHECK (crawl_status IN ('PENDING', 'SUCCESSFUL', 'FAILED'));
```

`NULL` means the source has never been crawled. The three explicit values:

| Value | Meaning |
|---|---|
| `PENDING` | A crawl is currently in progress; curation is blocked |
| `SUCCESSFUL` | Last crawl completed without error |
| `FAILED` | Last crawl errored or was interrupted (server crash); re-crawl required |

Transitions:
- Crawl starts → `PENDING`
- Crawl completes successfully → `SUCCESSFUL`
- Crawl errors (caught exception) → `FAILED`
- **Server startup**: any source with `crawl_status = 'PENDING'` → `FAILED`

The linked crawl job worker follows the same transitions.

### New column: `web_source_history.crawl_status`

```sql
ALTER TABLE web_source_history
    ADD COLUMN crawl_status TEXT
        CHECK (crawl_status IN ('SUCCESSFUL', 'FAILED'));
```

A history row is written at the end of every crawl attempt (success or failure) so that
the count of prior successful crawls is queryable:

```sql
SELECT COUNT(*) FROM web_source_history
WHERE source_id = :id AND crawl_status = 'SUCCESSFUL';
```

This count is returned in the `WebSource` API response as `successful_crawl_count` and
used to build the UI tip message.

### Entry tables as the job queue

Rather than a separate job table, the existing entry tables are used as the queue.
`pending` entries are the work items; background workers poll and process them.

**`page_curation_session_entry`** — `curation_status` enum already has all needed values:
`pending → running → succeeded | failed`. No schema change required.

**`kp_compile_session_entry`** — currently only allows `compiled | discarded | skipped`.
Add `pending` and `running`:

```sql
ALTER TABLE kp_compile_session_entry
    DROP CONSTRAINT compile_session_entry_status_check;
ALTER TABLE kp_compile_session_entry
    ADD CONSTRAINT kp_compile_session_entry_status_check
        CHECK (status IN ('pending', 'running', 'compiled', 'discarded', 'skipped', 'failed'));
```

`failed` is also added to cover compile errors explicitly (previously these were `skipped`).

Migration file: `docs/migrations/20261003_linked_crawl_job.sql` (rename to
`20261003_crawl_status_and_entry_queue.sql` — include all schema changes from this spec).

## Backend

### 1. Source-level crawl/curation mutual exclusion

**Main crawl endpoint** (`POST /{source_id}/crawl`):
- At the start, set `source.crawl_status = 'PENDING'` and write a new `web_source_history`
  row with `crawl_status = NULL` (in-progress placeholder; updated at the end).
- On successful completion: set `source.crawl_status = 'SUCCESSFUL'` and update the
  history row to `crawl_status = 'SUCCESSFUL'`.
- On any exception: set `source.crawl_status = 'FAILED'` and update the history row to
  `crawl_status = 'FAILED'`.
- Use `try/finally` to guarantee one of `SUCCESSFUL` or `FAILED` is always written.
- If `crawl_status = 'PENDING'` when the request arrives, return `409 Conflict`:
  "A crawl is already running for this source."
- `SUCCESSFUL` and `FAILED` sources may be re-crawled freely.

**Curation endpoint** (`POST /{source_id}/pages/{page_id}/extract`):
- If `crawl_status = 'PENDING'`, return `409 Conflict`:
  "Cannot curate while a crawl is running for this source."
- `SUCCESSFUL`, `FAILED`, and `NULL` sources allow curation.

**Linked crawl job worker** (see §5):
- Skip pending jobs where `source.crawl_status = 'PENDING'`; process all others.

**Frontend**:
- Include `crawl_status` and `successful_crawl_count` in `WebSource` API response and TS type.
- While `crawl_status === 'PENDING'`: show "Crawl in progress…" badge; disable Extract/Curate.
- While `crawl_status === 'FAILED'`: show warning banner with tip message (see below); Crawl
  and Extract buttons remain enabled.
- Disable the Crawl button while any curation is in flight (tracked by existing
  `extractingAll` state).

**Tip message** (shown in the `FAILED` warning banner):

| `successful_crawl_count` | Message |
|---|---|
| `0` | "This source has never been successfully crawled." |
| `1` | "Previously crawled successfully 1 time." |
| `N > 1` | "Previously crawled successfully N times." |

### 2. Startup recovery

The FastAPI lifespan `startup` hook runs the following resets **before** the server begins
accepting requests:

A `running` entry means an attempt was made. A server crash mid-attempt is a failure —
the operation did not complete and no result was written. Resetting to `failed` is the
honest state: the parent page succeeded, the child pages were attempted and did not finish.
The user sees exactly which pages failed and can choose to retry them.

`pending` entries were never attempted, so they survive the crash unchanged and are picked
up by the worker on the next poll — no user action needed for those.

| Stuck state | Recovery action | User-visible result |
|---|---|---|
| `web_source.crawl_status = 'PENDING'` | → `'FAILED'`; history row also `'FAILED'` | Warning banner; re-crawl enabled |
| `page_curation_session_entry.status = 'running'` | → `'failed'`, `error_message = 'Server restarted'` | Page shows Curation Failed; user sees child pages failed and can re-trigger |
| `kp_compile_session_entry.status = 'running'` | → `'failed'`, `error_message = 'Server restarted'` | Page shows Compile Failed; user can re-compile |
| `page_curation_session_entry.status = 'pending'` | Leave as-is | Worker picks up automatically on next poll |
| `kp_compile_session_entry.status = 'pending'` | Leave as-is | Worker picks up automatically on next poll |

After startup recovery, failed entries are visible to the user for manual retry; pending
entries resume automatically.

### 4. Enqueue linked pages in the same transaction as the triggering action

**Curation of a page (user-confirmed linked curation):**

When the user confirms curation of linked pages from the modal:
1. Create a `page_curation_session` row for the batch.
2. In the **same transaction**, create one `page_curation_session_entry` per linked page
   with `status = 'pending'`.
3. The curation worker (see §5) picks these up — `pending → running → succeeded | failed`.

Deduplication: if a `pending` curation entry already exists for a page (from a prior
unprocessed batch), skip creating a duplicate. Check with:
```sql
SELECT 1 FROM page_curation_session_entry
WHERE page_id = :pid AND status = 'pending' LIMIT 1;
```

**Compilation of a session (user-confirmed linked compilation):**

When the user confirms compilation of linked pages:
1. Reuse or create a `kp_compile_session` row.
2. In the **same transaction**, create one `kp_compile_session_entry` per linked page
   with `status = 'pending'`.
3. The compile worker (see §5) picks these up — `pending → running → compiled | discarded | failed`.

Remove all `BackgroundTasks` parameters from the curation and compile route signatures.

### 5. Background workers (startup lifespan tasks)

Two long-running coroutines are launched from the FastAPI lifespan:

**Curation worker** — polls `page_curation_session_entry WHERE status = 'pending'` every 5 s:
1. For each pending entry (skip if source `crawl_status = 'PENDING'`):
   a. Set entry `status = 'running'`.
   b. Run the LLM curation against `web_page.plain_text`.
   c. Set entry `status = 'succeeded'` (with `structured_draft`) or `'failed'` (with
      `error_message`). Always via `try/finally`.

**Compile worker** — polls `kp_compile_session_entry WHERE status = 'pending'` every 5 s:
1. For each pending entry:
   a. Set entry `status = 'running'`.
   b. Run the compile logic.
   c. Set entry `status = 'compiled' | 'discarded' | 'failed'`. Always via `try/finally`.

Both workers process one entry at a time per poll cycle (no parallelism within a worker)
to keep load predictable. If the server shuts down mid-entry, startup recovery resets the
`running` entry to `failed` / `pending` as shown in §2.

### 6. New endpoint: list pages pending curation/compilation

```
GET /web-sources/{source_id}/pages?status=pending_curation
GET /web-sources/{source_id}/pages?status=pending_compilation
```

These filter pages by whether they have a `pending` or `running` entry in the respective
tables, giving the UI a way to show the queue without polling the entry tables directly.

### 7. No separate "confirm" endpoint needed

Confirmation is done from the frontend modal. On confirm, the frontend calls the existing
endpoints to create curation or compile sessions with the selected page IDs. No new
backend route is required.

## Frontend

### Linked curation/compilation confirmation modal

After curation (single or bulk) completes, the frontend queries
`GET /web-sources/{source_id}/pages` for this source and checks if any linked pages have
`latest_run_status = null` or `changed_since_extraction = true`. If so, show a modal:

> **N linked pages are uncurated or have changed content**
> Curate them now?

The modal lists each page's title and URL with a checkbox (all checked by default). The user
can uncheck individual pages.

Buttons:
- **Curate linked pages** — creates a curation session for the checked pages. The server
  creates `pending` curation entries in the same transaction (§4). The UI immediately
  reflects the new `pending` status for each page.
- **Skip** — dismisses the modal without curating.

The same pattern applies after compilation: show linked pages eligible for compilation
(curated but not yet compiled) and let the user confirm.

Once the user acts, store the dismissed page IDs in `localStorage` so the modal does not
reappear for the same set unless content changes again.

### Updated `handleExtractAll` candidate filter

Add `changed_since_extraction === true` pages to the "pending" candidate set so bulk
extraction also picks up pages whose content changed since last curation:

```typescript
const pending = filtered.filter(
  (pg) =>
    !pg.latest_run_status ||
    pg.latest_run_status === "failed" ||
    pg.latest_run_status === "running" ||
    pg.changed_since_extraction            // ← add this
);
```

Expose `changed_since_extraction` on the `WebPage` type (it already exists in the API
response but is unused in the filter).

## Acceptance criteria

**Crawl status & mutual exclusion**
- [x] Starting a crawl while `crawl_status = 'PENDING'` returns 409
- [x] Starting curation while `crawl_status = 'PENDING'` returns 409
- [x] `crawl_status` transitions correctly: start → `PENDING`, success → `SUCCESSFUL`, error → `FAILED`
- [x] `crawl_status` and `successful_crawl_count` are returned in the `WebSource` API response and `WebSource` TS type
- [x] Extract/Curate buttons are disabled in the UI while `crawl_status === 'PENDING'`
- [x] A source with `crawl_status = 'FAILED'` shows a warning banner with tip: "Previously crawled successfully N times" (or "never")
- [x] A source with `crawl_status = 'FAILED'` still allows curation and re-crawl

**Startup recovery**
- [x] Sources with `crawl_status = 'PENDING'` on startup are set to `'FAILED'`; their in-progress history row is also set to `'FAILED'`
- [x] `page_curation_session_entry` rows with `status = 'running'` on startup are reset to `'failed'` with `error_message = 'Server restarted'`
- [x] `kp_compile_session_entry` rows with `status = 'running'` on startup are reset to `'failed'` with `error_message = 'Server restarted'`
- [x] `pending` entries of both types are left untouched and picked up by workers on the next poll

**Entry-table queue (curation)**
- [x] When the user confirms curation of linked pages, `page_curation_session_entry` rows are created with `status = 'pending'` in the same transaction as the session row
- [x] Pages immediately show `pending` status in the UI after confirmation
- [x] The curation worker transitions entries: `pending → running → succeeded | failed`
- [x] If a `pending` curation entry already exists for a page, no duplicate is created

**Entry-table queue (compilation)**
- [x] `kp_compile_session_entry` accepts `pending` and `running` statuses
- [ ] When the user confirms compilation of linked pages, entries are created with `status = 'pending'` in the same transaction
- [x] The compile worker transitions entries: `pending → running → compiled | discarded | failed` (compile entries are marked `discarded` pending full per-entry compile logic; see worker in `main.py`)

**User confirmation modal**
- [x] After curation completes, a modal lists linked pages that are uncurated or have changed content
- [ ] After compilation completes, a modal lists linked pages eligible for compilation
- [x] User can uncheck individual pages before confirming
- [x] Dismissing the modal creates no entries and triggers no background work
- [x] `handleExtractAll` includes `changed_since_extraction = true` pages in its candidate set
- [x] TypeScript compiles without errors

## Out of scope

- Full task queue infrastructure (Redis / ARQ / Celery)
- Retry logic with exponential backoff for failed entries
- Linked curation/compilation confirmation for Confluence pages
- Persisting modal acknowledgement in the DB (localStorage is sufficient)
- Parallel processing within a single worker (sequential is sufficient for now)
