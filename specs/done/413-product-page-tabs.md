# Product Page Tabs: Overview and Content

## Context

The product page currently shows a single scrolling view that mixes KP metadata,
compiled content (process steps, roles, tools, SLA, etc.), and action buttons. As KPs
grow, this becomes hard to navigate. Two distinct concerns — "what is this product and
where did it come from?" vs. "what knowledge does it contain?" — deserve separate views.

This spec introduces a two-tab layout on the product page:

- **Overview tab** — product identity, compilation metadata (product brief + compiled
  pages list), and links to sources
- **Content tab** — the full KP content as it exists today (the `ViewMode` / `EditMode`
  components)

It also adds persistence for the product brief (stored in `kp_compile_session`) so the
Overview tab can display it.

This spec supersedes the separate draft specs 413 and 414.

## Data model

### Add `brief_text` to `kp_compile_session`

```sql
-- docs/migrations/20261115_compile_session_brief.sql
ALTER TABLE kp_compile_session ADD COLUMN brief_text TEXT;
```

Nullable. Existing sessions remain NULL.

## Backend

### Save brief during compile stream (`curation.py`)

`BatchCompileStreamRequest` already carries `brief`. When creating `compile_session_obj`,
assign it:

```python
compile_session_obj = CompileSession(
    ...
    brief_text=payload.brief or None,
)
```

### New endpoint: latest compile session

```
GET /knowledge-products/{product_id}/latest-compile-session
```

Returns the most recent compile session and all its entries, joined to `web_page` (for
URL) and `web_source` (for source name). Used by the Overview tab.

Response schema:

```python
{
    "session_id": str,
    "status": str,                  # "running" | "completed" | "failed"
    "created_at": str,              # ISO-8601
    "completed_at": str | None,
    "brief_text": str | None,
    "totals": {
        "compiled": int,
        "not_relevant": int,
        "discarded": int,
        "failed": int,
    },
    "pages": [
        {
            "page_id": str,
            "title": str,
            "url": str | None,       # from web_page; null for Confluence entries
            "source_name": str | None,
            "status": str,           # "compiled" | "not_relevant" | "discarded" | "failed" | …
            "reason": str | None,
            "compiled_at": str | None,
        },
        ...
    ],
}
```

The join is `LEFT OUTER JOIN web_page ON entry.page_id = web_page.id` and
`LEFT OUTER JOIN web_source ON web_page.source_id = web_source.id`.

Returns `null` (HTTP 200 with body `null`) if no compile session exists for the product.

### Extend existing compiled-pages endpoint

`GET /{product_id}/versions/{version_id}/compiled-pages` — add `brief_text` per session
object and add `url` + `source_name` per entry (same joins as above). No breaking change.

## Frontend

### Tab bar

Replace the content area below the action buttons on `apps/web/src/app/products/[id]/page.tsx`
with a two-tab layout. Tabs sit below the existing header (product name, key, owner,
version badge, action buttons):

```
[ Overview ]  [ Content ]
──────────────────────────────
```

Default active tab: **Overview**.

State: `const [tab, setTab] = useState<"overview" | "content">("overview")`

Tab indicator: bottom border on the active tab, e.g. `border-b-2 border-indigo-600`.

### Overview tab

Three sections stacked vertically:

#### 1. Product identity

Re-uses the existing header fields (already rendered above the tabs):
- Name, product key, owner, current version semver, status badge, compiled-at timestamp
- "View version history →" link

No new data needed here — this section is just documentation of what stays in the header.

#### 2. Product brief

Fetched from `latest-compile-session.brief_text`.

```
┌─────────────────────────────────────────────────────┐
│ Product brief                                       │
│                                                     │
│ Covers the end-to-end customer journey: tracking    │
│ parcels and letters; flexible delivery options…     │
│                                                     │
│ From compile session · 28 Oct 2026                  │
└─────────────────────────────────────────────────────┘
```

- Shown as a plain `<p>` block with `whitespace-pre-wrap` for multi-line briefs
- If `brief_text` is null: italic muted text "No product brief was recorded for this
  compilation."
- If no compile session: section not shown at all

#### 3. Compiled pages

Fetched from the same `latest-compile-session` call (reuse the response).

**Summary row** (always visible):

```
Compiled pages  ·  Last compiled 28 Oct 2026

  ● 30 compiled   ⊘ 0 filtered   ✕ 0 failed
```

**Page list** (below summary, with status filter tabs):

```
[ All (30) ]  [ Compiled (30) ]  [ Filtered (0) ]  [ Failed (0) ]

  Title                           Source          Status     Compiled at
  ─────────────────────────────── ─────────────── ────────── ───────────
  Tracking your parcel            Customer Svc    ● Compiled  28 Oct 12:04
  Pakkeboks parcel lockers        Customer Svc    ● Compiled  28 Oct 12:03
  About bicycles (FAQ)            Customer Svc    ⊘ Filtered  —
```

- **Title** is a `<a href={url} target="_blank">` when `url` is non-null
- Status badge colours: `compiled` → green · `not_relevant` → grey ("Filtered") ·
  `discarded` → amber ("Skipped") · `failed` → red
- Sort order: compiled (by `compiled_at` desc) → filtered → discarded → failed
- Filter tab "Filtered" groups `not_relevant` + `discarded`
- When no session exists: "No compilation has been run for this product yet."

State:

```typescript
const [compiledPagesTab, setCompiledPagesTab] =
  useState<"all" | "compiled" | "filtered" | "failed">("all");
```

### Content tab

Move the existing `ViewMode` / `EditMode` rendering (everything currently below the
action buttons) into the Content tab. The edit/save/cancel action buttons and the
"Show source pages" toggle remain inside this tab.

No functional changes to the content itself — it is purely a layout move.

### API client additions (`api.ts`)

```typescript
getLatestCompileSession: (productId: string) =>
  apiFetch<CompileSessionDetail | null>(
    `/knowledge-products/${productId}/latest-compile-session`
  )
```

### New types (`types.ts`)

```typescript
export interface CompilePageEntry {
  page_id: string;
  title: string;
  url: string | null;
  source_name: string | null;
  status: "compiled" | "not_relevant" | "discarded" | "failed" | "skipped" | "running" | "pending";
  reason: string | null;
  compiled_at: string | null;
}

export interface CompileSessionDetail {
  session_id: string;
  status: string;
  created_at: string;
  completed_at: string | null;
  brief_text: string | null;
  totals: {
    compiled: number;
    not_relevant: number;
    discarded: number;
    failed: number;
  };
  pages: CompilePageEntry[];
}
```

## Acceptance criteria

- [x] Migration `20261115_compile_session_brief.sql` adds `brief_text TEXT` to
      `kp_compile_session`; existing rows remain NULL
- [x] `BatchCompileStreamRequest.brief` is saved to `compile_session_obj.brief_text`
      during compile session creation
- [x] `GET /knowledge-products/{product_id}/latest-compile-session` returns the most
      recent session with `brief_text`, `totals`, and `pages[]` including `url` and
      `source_name`; returns null when no session exists
- [x] Product page renders a tab bar with "Overview" and "Content" tabs; "Overview" is
      the default active tab
- [x] Overview tab shows product brief from the latest compile session; shows "No brief
      recorded" when `brief_text` is null; hides the section entirely when no session exists
- [x] Overview tab shows compiled pages summary (counts) and a filterable page list
- [x] Page list title links to `url` when available; plain text otherwise
- [x] Status filter tabs (All / Compiled / Filtered / Failed) correctly filter the rows
- [x] Content tab contains all existing view/edit functionality with no regressions
- [x] Edit, Export, Submit, Approve actions still work correctly from the Content tab

## Out of scope

- Showing compile history across multiple sessions (only the latest session is surfaced)
- Triggering a re-compile from the product page
- Showing pages that were curated but never submitted to a compile session ("pending"
  pages outside any session)
- Confluence page URLs (entries with no `web_page` row show plain text title)
- Backfilling `brief_text` for sessions created before this spec
