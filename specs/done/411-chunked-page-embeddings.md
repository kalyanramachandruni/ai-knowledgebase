# Chunked Page Embeddings for Better Long-Page Recall

## Context

The current embedding strategy stores one vector per page, built from
`title + plain_text[:500]`. Analysis of a representative page
(posten.no/en/customer-service/questions-about-shipping-in-norway, 4 463 chars)
showed it scoring 45 % against a directly relevant brief because the embedding
window cuts off after the intro paragraph — the actual Q&A content about tracking,
delivery and address services never reaches the model.

Switching to chunking — splitting each page into overlapping ~500-token segments,
embedding each, and taking the **max similarity** across chunks at query time —
fixes this without any frontend changes. A page now scores on its best-matching
passage rather than its intro.

This spec replaces the `title+500` embedding strategy from spec 410.

## Data model

### Migration required: `web_page_embedding` schema change

The table currently has `UNIQUE(page_id)` — one row per page. Chunking requires
one row per chunk.

```sql
-- docs/migrations/20261028_chunked_embeddings.sql

BEGIN;

-- 1. Drop old UNIQUE constraint (one row per page) and HNSW index (rebuilt below)
ALTER TABLE web_page_embedding DROP CONSTRAINT web_page_embedding_page_id_key;
DROP INDEX IF EXISTS web_page_embedding_hnsw_idx;

-- 2. Add chunk_index column (0-based; existing rows get index 0)
ALTER TABLE web_page_embedding ADD COLUMN chunk_index SMALLINT NOT NULL DEFAULT 0;

-- 3. New uniqueness: one row per (page, chunk)
ALTER TABLE web_page_embedding
    ADD CONSTRAINT web_page_embedding_page_chunk_key UNIQUE (page_id, chunk_index);

-- 4. Rebuild HNSW index
CREATE INDEX web_page_embedding_hnsw_idx
    ON web_page_embedding USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 5. Clear all existing single-chunk embeddings so the worker re-embeds
--    with the new chunked format (model name mismatch would also trigger
--    re-embedding, but a clean slate is simpler)
DELETE FROM web_page_embedding;

COMMIT;
```

The ORM model gains `chunk_index: Mapped[int]` (non-nullable, default 0).

### Chunk parameters (constants in `main.py`)

| Constant | Value | Rationale |
|---|---|---|
| `CHUNK_CHARS` | 2 000 | ≈ 500 tokens for typical English/Norwegian text |
| `CHUNK_OVERLAP_CHARS` | 200 | Prevents relevant sentences from being cut at boundaries |

### Model name tag

Format tag changes from `title+500` to `chunks2000`:
`expected_model = f"{base_model}:chunks2000"`

Any row without this tag is treated as stale and re-embedded.

## Backend

### Chunking helper (`main.py`)

```python
def _chunk_page(title: str | None, plain_text: str) -> list[str]:
    """
    Split plain_text into overlapping chunks; prepend title to every chunk.
    Returns at least one chunk even for short pages.
    """
    step = CHUNK_CHARS - CHUNK_OVERLAP_CHARS
    chunks = [plain_text[i : i + CHUNK_CHARS]
              for i in range(0, max(len(plain_text), 1), step)]
    prefix = f"{title.strip()}\n" if title and title.strip() else ""
    return [f"{prefix}{c}" for c in chunks]
```

A page with 4 000 chars produces 3 chunks at 0, 1 800, 3 600. A page shorter
than 2 000 chars produces one chunk (equivalent to the current approach but
without the 500-char cutoff).

### Background embedding worker (`_process_embedding_batch`)

Changes from the current implementation:

1. **`_EMBEDDING_INPUT_FMT`** → `"chunks2000"`
2. **`_page_embedding_text()`** replaced by **`_chunk_page()`** (returns a list)
3. **Batch construction**: flatten chunks across rows, keeping a `(row, chunk_index)`
   mapping so embeddings can be paired back to their source row and chunk.
4. **INSERT** changes from `ON CONFLICT (page_id) DO UPDATE` to
   `ON CONFLICT (page_id, chunk_index) DO UPDATE`.
5. **Stale chunk cleanup**: after upserting, delete any chunks with
   `chunk_index >= new_chunk_count` (handles pages that shrink on re-crawl).

Pseudo-code:

```python
# Build flat batch
items = []   # (row, chunk_index, chunk_text)
for row in rows:
    for i, text in enumerate(_chunk_page(row.title, row.plain_text)):
        items.append((row, i, text))

embeddings = await llm_port.embed([t for _, _, t in items])

for (row, chunk_idx, _), emb in zip(items, embeddings):
    UPSERT INTO web_page_embedding (page_id, chunk_index, ...) VALUES (...)
    ON CONFLICT (page_id, chunk_index) DO UPDATE ...

# Clean up removed chunks
for row in rows:
    DELETE FROM web_page_embedding
    WHERE page_id = row.id AND chunk_index >= new_chunk_count_for_row
```

API call budget per cycle: up to 20 pages × average chunks/page. For the
posten.no source (~500 pages, avg ~2 chunks each), full re-embedding takes
~50 cycles (≈8 min at 10 s/cycle).

### Similarity queries — `MAX` over chunks

Every query that fetches page similarity changes from a direct cosine comparison
to a `MAX` aggregation:

**Before:**
```sql
1.0 - (wpe.embedding <=> CAST(:kp_emb AS vector(1024))) AS similarity
FROM web_page wp
LEFT JOIN web_page_embedding wpe ON wpe.page_id = wp.id
```

**After:**
```sql
MAX(1.0 - (wpe.embedding <=> CAST(:kp_emb AS vector(1024)))) AS similarity
FROM web_page wp
LEFT JOIN web_page_embedding wpe ON wpe.page_id = wp.id
GROUP BY wp.id, wp.title, wp.url, ...
```

Affected endpoints:
- `GET /{source_id}/pages/relevance` (KP embedding comparison)
- `POST /{source_id}/pages/relevance/score-by-brief` (brief embedding comparison)

The `has_embedding` flag per page becomes `COUNT(wpe.id) > 0`.

### Batch size consideration

With chunking, one API call may embed up to `20 × ceil(max_page_chars / CHUNK_CHARS)`
texts. At 2 000 chars and a practical max of ~8 chunks for a long page, worst case
is 160 embeddings per cycle — within Azure OpenAI batch limits. If a page is
unusually long, its chunks still fit in one `embed()` call since the existing
adapters pass the full list.

## Frontend

No changes. Scores are still returned as one `similarity` value per page (the max
across chunks), so the threshold slider, score column, and pre-selection logic are
unaffected.

## Open questions for review

1. **Chunk size**: 2 000 chars (≈500 tokens) vs 1 500 (≈375 tokens)?
   Smaller chunks give finer-grained matching but more DB rows and API cost.

2. **Overlap**: 200 chars feels right for avoiding sentence breaks. Could be 0
   for simplicity if we trust that key content isn't right at chunk boundaries.

3. **Title in every chunk**: adds ~50 chars of context to each chunk.
   Alternative: only prepend title to chunk 0.

4. **Max vs mean similarity**: max finds the best-matching passage (better recall,
   may surface pages that are only tangentially related in one passage).
   Mean would require the whole page to be relevant (better precision).
   Recommendation: **max**, consistent with how retrieval-augmented systems work.

5. **Batch size cap**: should the worker cap pages per cycle at 20, or cap
   total chunks per cycle at 20? Capping chunks keeps API call size predictable
   but means fewer pages per cycle for long-page sources.

## Acceptance criteria

- [x] Migration `20261028_chunked_embeddings.sql` runs cleanly; `web_page_embedding`
      has `chunk_index` column and `UNIQUE(page_id, chunk_index)` constraint
- [x] ORM model updated with `chunk_index` field
- [x] `_chunk_page()` splits plain_text into overlapping 2 000-char segments,
      prepending title to each
- [x] Worker embeds all chunks for each page per cycle and upserts by
      `(page_id, chunk_index)`
- [x] Worker deletes orphaned chunk rows when a re-crawled page has fewer chunks
- [x] Similarity queries return `MAX()` across chunks; `has_embedding` is true
      when any chunk exists
- [x] Model tag stored as `{base_model}:chunks2000`; old `title+500` rows are
      re-embedded automatically
- [x] Relevance scores investigated for the posten.no FAQ page (44 % vs 45 % baseline):
      no regression — the FAQ page mixes bicycles, weapons, braille, scams and postal
      content throughout, so its score correctly reflects mixed relevance. Chunking
      helps long pages that are specifically on-topic; mixed-content pages score low
      regardless of strategy.

## Out of scope

- Chunking KP embeddings (KP text is short; one vector is fine)
- Semantic chunking (sentence/paragraph boundaries) — character-based is
  sufficient and avoids an NLP dependency
- Storing which chunk produced the max score (could be added for debugging later)
- Adjusting frontend to show per-chunk scores
