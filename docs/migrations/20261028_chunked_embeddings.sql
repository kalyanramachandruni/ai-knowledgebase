-- Chunked page embeddings: replace one-row-per-page with one-row-per-chunk.
-- Chunk parameters: 2 000-char chunks, 200-char overlap, title prepended to every chunk.
-- Similarity queries use MAX() across chunks so each page scores on its best passage.

BEGIN;

-- 1. Drop old UNIQUE(page_id) constraint — one chunk per page no longer holds
ALTER TABLE web_page_embedding DROP CONSTRAINT web_page_embedding_page_id_key;

-- 2. Drop HNSW index (rebuilt after schema change)
DROP INDEX IF EXISTS web_page_embedding_hnsw_idx;

-- 3. Add chunk_index; existing rows (if any) become chunk 0
ALTER TABLE web_page_embedding ADD COLUMN chunk_index SMALLINT NOT NULL DEFAULT 0;

-- 4. New uniqueness: one row per (page, chunk)
ALTER TABLE web_page_embedding
    ADD CONSTRAINT web_page_embedding_page_chunk_key UNIQUE (page_id, chunk_index);

-- 5. Rebuild HNSW index
CREATE INDEX web_page_embedding_hnsw_idx
    ON web_page_embedding USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- 6. Clear all existing single-chunk embeddings; the background worker
--    re-embeds with the new chunked format (model tag changes to :chunks2000)
DELETE FROM web_page_embedding;

COMMIT;
