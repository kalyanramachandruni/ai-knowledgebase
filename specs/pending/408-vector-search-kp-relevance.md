# Vector Search — KP Relevance Scoring for Pages

## Context

Compiling a knowledge product today requires the user to manually select pages or rely
on the LLM's brief filter to silently drop irrelevant ones during the merge pass.
There is no way to ask "which of these 400 crawled pages are actually relevant to KP X
before I run a compile?" — the user has to guess or run an expensive LLM pass first.

This spec adds embedding-based relevance scoring so that any page in a source can be
ranked against a KP's intent before curation or compilation begins.

The goal is:
1. Surface a **relevance score** per page in the Sources page when a KP is selected.
2. Let users click **"Find relevant pages"** to pre-rank and pre-select pages before
   bulk curation or compile.
3. Store embeddings persistently so ranking is fast (no LLM call at query time).

## Infrastructure

Use **pgvector** (PostgreSQL extension) rather than adding a dedicated vector database.
The project already uses PostgreSQL; pgvector adds a `vector` column type and
approximate nearest-neighbour (ANN) index support.

Add to Docker Compose / server provisioning: `pgvector` extension enabled.
No new service, no new connection string.

Embedding model: use the same LLM provider already configured:
- Anthropic: `voyage-3` (Voyage AI, accessible via `anthropic` SDK)
- OpenAI / Azure: `text-embedding-3-small`

## Data model

### New: `web_page_embedding` table

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE web_page_embedding (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    page_id     UUID NOT NULL REFERENCES web_page(id) ON DELETE CASCADE,
    content_hash VARCHAR NOT NULL,   -- hash of the text that was embedded; used to detect stale embeddings
    model       VARCHAR NOT NULL,    -- e.g. 'voyage-3', 'text-embedding-3-small'
    embedding   vector(1024),        -- 1024-dim for voyage-3 / text-embedding-3-small (adjust per model)
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (page_id)                 -- one current embedding per page
);

CREATE INDEX web_page_embedding_hnsw
    ON web_page_embedding USING hnsw (embedding vector_cosine_ops);
```

Embedding is generated from the first 8 000 tokens of `web_page.plain_text`.
`content_hash` is the same `web_page.content_hash` at embedding time; if the page is
re-crawled and the hash changes, the embedding row is replaced.

### New: `knowledge_product_embedding` table

```sql
CREATE TABLE knowledge_product_embedding (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id  UUID NOT NULL REFERENCES knowledge_product(id) ON DELETE CASCADE,
    intent_hash VARCHAR NOT NULL,    -- SHA-256 of the concatenated intent text
    model       VARCHAR NOT NULL,
    embedding   vector(1024),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (product_id)
);
```

Intent text = `"{name}. {brief}. {process_overview.summary}"` — whichever fields are
present, joined by newline. Updated whenever the compiled KP or brief changes.

## Backend

### New port method — `LLMCurationPort.embed()`

```python
async def embed(self, texts: list[str]) -> list[list[float]]:
    """Return one embedding vector per text. Batched for efficiency."""
    ...
```

Implement in each adapter:
- `AnthropicExtractionAdapter`: call Voyage AI (`voyageai` SDK, or REST directly) with
  `model="voyage-3"`, dimension 1024.
- `OpenAIExtractionAdapter` / `AzureOpenAIExtractionAdapter`: call
  `client.embeddings.create(model="text-embedding-3-small", ...)`, dimension 1024.

### Background embedding worker (`main.py`)

Add a third background worker `_embedding_worker()` alongside the existing curation and
compile workers:

```
loop every 10 s:
  SELECT web_page WHERE id NOT IN (SELECT page_id FROM web_page_embedding)
     OR content_hash != (SELECT content_hash FROM web_page_embedding WHERE page_id = web_page.id)
  LIMIT 20   -- batch
  embed plain_text[:8000 chars] in batch
  UPSERT into web_page_embedding
```

Processing up to 20 pages per tick keeps the embedding API calls batched while not
blocking other workers.

### New API endpoints in `web_crawl.py`

#### `GET /{source_id}/pages/relevance?product_id={uuid}&limit={int}`

Rank all pages in the source by cosine similarity to the KP's intent embedding.
Returns every page with its similarity score (0–1), sorted descending.

```python
class PageRelevanceScore(BaseModel):
    page_id: str
    title: str
    url: str
    similarity: float           # cosine similarity 0–1
    has_embedding: bool         # false if page not yet embedded
    latest_run_status: str | None
    compiled_kp_count: int
```

Query:
```sql
SELECT wp.id, wp.title, wp.url, wp.latest_run_status, ...,
       1 - (wpe.embedding <=> :kp_embedding) AS similarity
FROM web_page wp
LEFT JOIN web_page_embedding wpe ON wpe.page_id = wp.id
WHERE wp.source_id = :source_id
ORDER BY wpe.embedding <=> :kp_embedding   -- cosine distance ASC = similarity DESC
```

If no KP embedding exists yet, trigger its creation inline (fast: single short text).

#### `POST /{source_id}/pages/relevance/generate-kp-embedding`

Trigger (re)generation of the KP intent embedding on demand — called by the frontend
when a new brief is entered or when the dropdown KP selection changes and no embedding
exists yet.

```json
{ "product_id": "uuid", "brief": "optional override text" }
```

Returns `{ "status": "ok" | "queued" }`.

### `web_crawl.py` — `list_web_pages` extension

Add `embedding_status: "ready" | "pending" | "stale" | "none"` to `WebPageResponse`:
- `ready` — embedding exists and `content_hash` matches
- `stale` — embedding exists but `content_hash` differs (re-crawled since last embed)
- `pending` — no embedding yet but page has plain_text
- `none` — page has no plain_text (thin content)

## Frontend

### Sources page — relevance ranking mode

When a KP is selected in the KP dropdown, show a **"Find relevant"** button next to it.

Clicking it:
1. Calls `GET /{source_id}/pages/relevance?product_id=...`
2. Enters **relevance mode** for that source: replaces the KP-filtered view with a
   ranked list, adding a **Relevance** column showing a visual score bar (0–100 %).
3. Pages with `has_embedding=false` are shown at the bottom with a "Not yet scored" note.
4. Pre-selects the top-N pages above a threshold (default: similarity ≥ 0.65) for
   bulk curation or compile.

The existing KP filter ("Show pages not in KP" checkbox) continues to work alongside
relevance ranking — they are composable filters.

### New Relevance column

Shown only in relevance mode (not always visible — avoids cluttering the default view).

```
[███████░░░] 72 %
```

Rendered as a thin horizontal bar + percentage. Green ≥ 0.65, amber 0.40–0.65, grey < 0.40.

### "Select relevant pages" shortcut

In relevance mode, a button **"Select top N (≥ 65 %)"** pre-checks all pages above the
threshold so the user can immediately click "Curate N selected" or "Compile N selected".

Threshold is adjustable via a small slider (0.40–0.90, step 0.05).

### Embedding coverage indicator

Below the KP dropdown, a small line:
> "432 / 450 pages scored  ·  18 pending"

Refreshes every 15 s while there are pending pages. Links to a "Re-score all" button
that calls the generate-kp-embedding endpoint.

## Acceptance criteria

- [ ] `pgvector` extension enabled; `web_page_embedding` and `knowledge_product_embedding` tables created by migration
- [ ] `LLMCurationPort.embed()` implemented in Anthropic and OpenAI adapters
- [ ] Background embedding worker processes up to 20 pages per tick; stale embeddings (changed `content_hash`) are replaced
- [ ] `GET /{source_id}/pages/relevance` returns all pages with similarity scores in < 500 ms for a 500-page source (HNSW index)
- [ ] Selecting a KP in the dropdown and clicking "Find relevant" shows pages ranked by similarity with score bars
- [ ] Pages without an embedding are shown at the bottom with "Not yet scored"
- [ ] "Select top N (≥ 65 %)" button pre-selects matching pages for bulk curation/compile
- [ ] Threshold slider adjusts the pre-selection live
- [ ] Embedding coverage line below the dropdown shows pending count and refreshes
- [ ] `embedding_status` field appears on `WebPage` API response
- [ ] KP intent embedding is (re)generated when a brief is added or the KP version changes

## Out of scope

- Semantic search across multiple sources (cross-source search)
- Embedding Confluence pages (web sources only for now)
- Fine-tuning or custom embedding models
- Storing embeddings for curated structured drafts (future: could enable "find pages that curated into similar processes")
