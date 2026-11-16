# Two-Phase Compile: Client-Side Semantic Filter

## Context

Spec 409 added a vector pre-filter as a backend step that ran silently during
compilation and immediately discarded pages before the LLM merge loop. In practice
this gave users no control — pages were filtered and compiled in one uninterruptible
operation, and they could not review which pages were selected before committing to
an expensive compile run.

This spec replaces that approach with an explicit two-phase workflow:

1. **Score & Pre-select** — user triggers semantic scoring, sees a score per page, and
   adjusts the threshold. Selected pages are visible before any compilation begins.
2. **Compile selected** — user explicitly confirms the selection and kicks off compilation
   with only those pages.

The backend vector pre-filter (`similarity_threshold` field in `BatchCompileStreamRequest`)
is no longer used by the frontend. Client-side pre-selection replaces it entirely.

Additionally, spec 408's "Find relevant" button required an existing KP to be selected.
This spec adds scoring support for new/unnamed KPs via a dedicated "score by brief" endpoint.

## Data model

No new tables. Uses `web_page_embedding` from spec 408. The `not_relevant` status on
`kp_compile_session_entry` (added by spec 409) is retained for backward compatibility
with existing compiled sessions.

Migration `docs/migrations/20261018_add_not_relevant_kp_status.sql` extends the status
check constraint to include `not_relevant`.

## Backend

### New endpoint: `POST /{source_id}/pages/relevance/score-by-brief`

Scores all pages in a source against an ad-hoc brief without needing an existing KP or
its stored embedding. Useful when creating a new KP or when the user wants to score
before selecting a product key.

```python
class ScoreByBriefRequest(BaseModel):
    brief: str

@router.post("/{source_id}/pages/relevance/score-by-brief")
async def score_pages_by_brief(
    source_id: uuid.UUID,
    payload: ScoreByBriefRequest,
    ...
) -> list[PageRelevanceScore]:
```

Implementation:
1. Embed `payload.brief` using `llm_port.embed([brief])` → single 1024-dim vector
2. SQL: cosine similarity of each `web_page_embedding` row against the brief embedding
3. Pages with no embedding row return `similarity: null`, `has_embedding: false`
4. Results ordered: embedded pages first (by similarity DESC), then unembedded pages

```sql
SELECT wp.id AS page_id, wp.title, wp.url,
       CASE WHEN wpe.embedding IS NOT NULL
            THEN 1.0 - (wpe.embedding <=> CAST(:kp_emb AS vector(1024)))
            ELSE NULL END AS similarity,
       wpe.embedding IS NOT NULL AS has_embedding
FROM web_page wp
LEFT JOIN web_page_embedding wpe ON wpe.page_id = wp.id
WHERE wp.source_id = CAST(:source_id AS uuid)
ORDER BY CASE WHEN wpe.embedding IS NOT NULL THEN 0 ELSE 1 END,
         CASE WHEN wpe.embedding IS NOT NULL
              THEN wpe.embedding <=> CAST(:kp_emb AS vector(1024))
              ELSE 0 END ASC
```

No KP embedding is stored. The brief is embedded transiently per request.

## Frontend

### Compile form — two-phase layout

Replace the "Vector pre-filter" checkbox (spec 409) with a **Step 1 — Semantic filter**
panel inside the compile form. It is shown only when the Product Brief field is non-empty.

```
┌──────────────────────────────────────────────────────┐
│ Step 1 — Semantic filter                             │
│                                                      │
│ Filter by: [Percentile rank] [Absolute score]        │
│                                                      │
│ ☑ Top 10% (22)   ☑ 11–20% (22)   ☑ 21–30% (22) …  │
│ 196 of 196 scored pages selected                     │
│                                                      │
│ [Score & Pre-select pages]                           │
│ ✓ 196 pages selected  [Show all pages]               │
└──────────────────────────────────────────────────────┘

[Step 2 — Compile 196 selected → KP]
```

#### Bucket checkboxes

Selection is controlled by 10 checkboxes, one per decile. Two filter modes are
available, toggled by pill buttons above the checkboxes:

**Percentile rank** (default):
- Pages are ranked by similarity score descending and divided into 10 equal-sized
  deciles regardless of raw score values.
- Bucket 0 = top 10 % of scorers ("Top 10%"), bucket 9 = bottom 10 % ("Bottom 10%"),
  buckets 1–8 labelled "11–20 %", "21–30 %", … "81–90 %".
- Each bucket contains approximately `N/10` pages (N = scored pages). Buckets are
  always evenly populated regardless of score distribution.

**Absolute score**:
- Fixed score ranges: bucket 0 = 0–10 %, bucket 1 = 11–20 %, … bucket 9 = 91–100 %.
- Bucket labels: "0–10 %", "11–20 %", … (no "Top" prefix).
- Bucket sizes vary with score distribution; for typical cosine similarity values most
  pages cluster in the 41–60 % range, so many buckets will be empty.

Each checkbox label shows the page count in brackets: `Top 10% (22)`.
Checkboxes are disabled (greyed out) until scoring has been run.

Switching filter mode immediately recalculates which pages fall in each checked bucket
and updates `selectedWebPages` — no API call.

State: `pageScoreBuckets: Record<string, Set<number>>` (checked bucket indices per source)
and `filterMode: Record<string, "percentile" | "absolute">` per source.

The bucket map is computed:
- **Percentile**: sort scores desc, `bucket = Math.min(Math.floor(rank / total * 10), 9)`
- **Absolute**: `bucket = Math.min(Math.floor(similarity * 10), 9)`

#### "Score & Pre-select pages" button

Enabled when `brief.trim()` is non-empty.

Behaviour:
- If an existing KP matches `productKey`:
  1. `POST /{source_id}/pages/relevance/generate-kp-embedding` with brief
  2. `GET /{source_id}/pages/relevance?product_id=...`
- Otherwise (new KP or no match):
  1. `POST /{source_id}/pages/relevance/score-by-brief` with brief

After fetching scores:
- All 10 buckets are checked (all scored pages pre-selected)
- `pageScoreBuckets[src.id]` is set to `new Set([0,1,2,3,4,5,6,7,8,9])`
- Switches table to "Show selected only" view
- Marks `compileScoredApplied[src.id] = true`
- Button label changes to "Re-score pages" on subsequent presses

#### "Show all pages / Show selected only" toggle

Appears after scoring. Default: show selected only.
Clicking toggles between full table and selection-only view.

#### Compile button gating

When `brief.trim()` is non-empty, the compile button is disabled until scoring has been
applied at least once (`compileScoredApplied[src.id] === true`). This enforces the
two-phase workflow — scoring must happen before compiling when a brief is present.

Button label reflects state:
- Before scoring: "Compile"
- After scoring: "Step 2 — Compile N selected → KP"

#### Compile page pool

The compile button calls `handleCompile(src.id, srcPages)` where `srcPages` is the
**full unfiltered page list** for the source. Active UI filters (search, status) are
intentionally excluded from the compile pool: the intersection with `selectedWebPages`
is taken inside `handleCompile`, so pages that are selected but currently hidden by a
filter are still compiled.

This prevents silent page drops when users apply a status filter to review pages before
compiling.

### Score column in the page table

When `compileScoredApplied[src.id]` is true, a **Score** column appears after the Title
column in the page table.

```
[███████░░░]   Cells with a score: mini bar + percentage
   38 %        Color: purple if page's bucket is checked, grey if bucket unchecked

  —            Cells with no embedding: em dash in muted grey
```

Bar width = `Math.round(similarity * 100)%`. Column is 72 px wide.
`inRange` is determined by looking up the page's bucket in `pageScoreBuckets[src.id]`.
The bucket map is precomputed once per table render (`tableBucketMap`) for O(1) lookup.
`colSpan` on empty-state rows is incremented by 1 when the column is shown.

### "Hide vector-filtered pages" checkbox

Appears in the filter bar when any page in the source has
`compilePageStatus[src.id][pageId] === "not_relevant"` (set by a previous compile run
that used the backend pre-filter from spec 409).

When checked, such pages are hidden from the table. This is independent of the
bucket checkboxes — it hides pages from a past compile, not from the current scoring pass.

State: `hideVectorFiltered: Record<string, boolean>` keyed by source ID.

### `similarity_threshold` removed from compile request

The `similarity_threshold` field is no longer sent in the `BatchCompileStreamRequest`
body. Client-side pre-selection replaces the backend filter for new compiles.
The backend field is retained for backward compatibility but is unused by the current
frontend.

## Acceptance criteria

- [x] `POST /{source_id}/pages/relevance/score-by-brief` endpoint exists and returns `PageRelevanceScore[]`
- [x] Scoring works for new KPs (no existing product key required)
- [x] Scoring works for existing KPs (uses stored KP embedding + brief regeneration)
- [x] Compile form shows "Step 1 — Semantic filter" panel when brief is non-empty
- [x] Panel shows 10 bucket checkboxes; each shows page count in brackets; disabled until scored
- [x] "Percentile rank" mode: buckets divide scored pages into equal-sized deciles by rank
- [x] "Absolute score" mode: buckets are fixed 0–10 %, 11–20 %, … score ranges
- [x] Switching filter mode immediately recalculates selection from cached scores
- [x] "Score & Pre-select pages" button pre-selects all scored pages (all 10 buckets checked)
- [x] Unchecking a bucket immediately removes those pages from `selectedWebPages`
- [x] After scoring, table defaults to "Show selected only" view with a toggle to show all
- [x] Compile button is disabled until scoring is applied when brief is non-empty
- [x] Score column appears in the page table after scoring, showing bar + percentage per page
- [x] Score bar is purple when page's bucket is checked, grey when unchecked
- [x] Pages with no embedding show "—" in the score column
- [x] "Hide vector-filtered pages" checkbox appears when `not_relevant` pages exist (from prior compile)
- [x] `similarity_threshold` is not sent in the compile request body
- [x] Compile uses `srcPages` (full unfiltered list) so active UI filters do not silently drop selected pages

## Embedding input format

Pages are embedded using **title + first 500 characters of `plain_text`** rather than
the full page text. This reduces noise from boilerplate at the end of long pages and
gives the title (which is usually the strongest topical signal) explicit weight.

The stored model name includes a format tag: `{base_model}:title+500`
(e.g. `text-embedding-3-large:title+500`). The background worker re-embeds any page
whose stored model name does not match this expected name, so all existing embeddings
(generated with the old full-text format) are automatically replaced over the next
few worker cycles after deployment. No migration is needed.

Helper: `_page_embedding_text(title, plain_text)` in `main.py` builds the input string.

## Out of scope

- Persisting score results across sessions (scores are in-memory per page visit)
- Chunking long pages for better embedding signal
- Normalizing scores relative to the best-scoring page in the batch
- Storing the brief-based embedding (it is computed transiently per score request)
