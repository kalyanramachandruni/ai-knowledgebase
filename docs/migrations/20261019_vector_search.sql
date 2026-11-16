-- Vector search: pgvector extension + web page and KP embedding tables
-- Requires PostgreSQL with the pgvector extension available.

CREATE EXTENSION IF NOT EXISTS vector;

-- Stores the latest embedding vector for a web page's plain text content.
CREATE TABLE IF NOT EXISTS web_page_embedding (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    page_id       UUID NOT NULL UNIQUE REFERENCES web_page(id) ON DELETE CASCADE,
    content_hash  VARCHAR(64) NOT NULL,
    model         VARCHAR NOT NULL,
    embedding     vector(1024),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- HNSW index for fast approximate nearest-neighbour search (cosine distance).
CREATE INDEX IF NOT EXISTS web_page_embedding_hnsw_idx
    ON web_page_embedding USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- Stores the latest embedding vector for a knowledge product's intent text.
CREATE TABLE IF NOT EXISTS knowledge_product_embedding (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    product_id   UUID NOT NULL UNIQUE REFERENCES knowledge_product(id) ON DELETE CASCADE,
    intent_hash  VARCHAR(64) NOT NULL,
    model        VARCHAR NOT NULL,
    embedding    vector(1024),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
