# Vector Pre-filter for KP Compilation

## Context

After spec 408 added embedding-based relevance scoring on the Sources page, the expensive
LLM merge loop during compilation still processes every selected page regardless of
relevance. On a 400-page source this means hundreds of LLM calls even when only a
handful of pages are actually related to the target KP.

This spec adds a **vector similarity pre-filter** that runs before the merge loop:
pages whose cosine similarity to the KP intent embedding falls below a user-set
threshold are discarded before any LLM call, making compilation significantly cheaper
and faster when most selected pages are irrelevant.

The feature is opt-in (threshold defaults to disabled) so it does not break existing
compile flows.

## Data model

No new tables. Uses `web_page_embedding` and `knowledge_product_embedding` introduced
in spec 408.

## Backend

### `BatchCompileStreamRequest` — new field

```python
similarity_threshold: float | None = None
# 0.0–1.0; when None the filter is disabled (default, preserves existing behaviour)
```

### Pre-filter block in `batch_compile_stream` (`curation.py`)

Inserted between the discarded-pages cleanup and the LLM merge loop:

```
if similarity_threshold is set and _kp_id is known and drafts non-empty:
  1. Load KP embedding from knowledge_product_embedding WHERE product_id = _kp_id
  2. If no row found — generate inline:
       intent_text = payload.name + "\n" + kp_version.process_overview.summary (if present)
                   + "\n" + payload.brief (if present)
       embed(intent_text) → UPSERT into knowledge_product_embedding
  3. Bulk-query cosine similarities:
       SELECT page_id::text, 1.0 - (embedding <=> CAST(:kp_emb AS vector(1024))) AS similarity
       FROM web_page_embedding
       WHERE page_id::text = ANY(:page_ids)
         AND embedding IS NOT NULL
  4. For each draft page:
       if similarity < threshold:
         → CompileSessionEntry(status="not_relevant", reason="vector similarity X% below threshold Y%")
         → yield SSE { type: "page_not_relevant", page_id, similarity, threshold, reason: "vector_similarity" }
         → remove from drafts
       if no embedding exists for page:
         → keep in drafts (let LLM decide)
  5. yield SSE { type: "filter_stats", filtered, no_embedding, remaining, warning? }
```

If the KP embedding cannot be generated (API error), a `filter_stats` event with
`warning: "no_kp_embedding"` is emitted and the merge loop proceeds unfiltered.

Pages with no `web_page_embedding` row are kept — the filter degrades gracefully when
the background worker has not yet embedded a page.

### SSE events added

| Event | Fields | When |
|---|---|---|
| `page_not_relevant` | `page_id`, `run_id`, `similarity`, `threshold`, `reason: "vector_similarity"` | Each filtered page |
| `filter_stats` | `threshold`, `filtered`, `no_embedding`, `remaining`, `warning?` | After filter runs (or is skipped) |

### Inline KP embedding generation

The pre-filter can generate a KP intent embedding on the fly without requiring the user
to run relevance mode first. It reuses the same intent-text format and UPSERT as the
`POST /{source_id}/pages/relevance/generate-kp-embedding` endpoint from spec 408.

## Frontend

### Compile form — new controls

Below the Product Brief textarea, add:

- **"Vector pre-filter" checkbox** (default: unchecked → `similarityThreshold: null`)
- When checked: show a **threshold slider** (0–100 %, step 5 %, default 50 %)
  and a label "min similarity"

```
☐ Vector pre-filter   [────────●────] 50%  min similarity
```

### Compile progress — filter stats display

When a `filter_stats` SSE event arrives during compilation, show a line above the
progress bar:

- Normal: `Vector pre-filter: N filtered, M sent to LLM (K had no embedding — kept)`
- Warning: `⚠ Vector pre-filter skipped — no KP embedding could be generated`

### `compilePageStatus` — new value

Add `"not_relevant"` to the page status union. Badge: grey background, label "Filtered".

### State additions

| State | Type | Purpose |
|---|---|---|
| `compileForm[id].similarityThreshold` | `number \| null` | Per-source threshold; null = disabled |
| `compileFilterStats[id]` | `{ filtered, noEmbedding, remaining, warning? } \| null` | Result of last filter run |

## Acceptance criteria

- [x] `BatchCompileStreamRequest` accepts optional `similarity_threshold: float | None`
- [x] When threshold is null/absent, compile behaviour is identical to pre-408 (no regression)
- [x] Pages with embedding below threshold receive `status="not_relevant"` in `kp_compile_session_entry`
- [x] Pages with no embedding in `web_page_embedding` are kept and sent to the LLM merge loop
- [x] KP intent embedding is generated inline if not already present (no prior relevance-mode step needed)
- [x] `filter_stats` SSE event is emitted after the filter runs, showing filtered/no_embedding/remaining counts
- [x] `⚠ no_kp_embedding` warning is emitted (and merge loop still runs) if embedding generation fails
- [x] Compile form shows "Vector pre-filter" checkbox and threshold slider
- [x] Filter stats line appears in the compile progress area during compilation
- [x] Pages filtered by vector similarity show a grey "Filtered" badge in the page table

## Out of scope

- Filtering pages that have no embedding (they are always kept — the filter is additive, not a gate)
- Persisting the threshold as a KP-level default (per-compile choice only)
- Applying the pre-filter to the non-streaming `batch-compile` endpoint
