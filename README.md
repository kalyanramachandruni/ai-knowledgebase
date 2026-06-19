# Knowledge Product Studio

Confluence → Knowledge Product → Agent Context Package.

Treats business-process knowledge as a versioned, governed, deployable artifact — not a vector index.

## Status

MVP build in progress. See [docs/architecture.md](docs/architecture.md) for the full design and
[task tracker] for current build step. Implemented so far: domain model + DB schema (step 1 of 8).

## Repo layout

```
apps/api/    FastAPI backend — Domain-Driven Design, Clean Architecture
apps/web/    Next.js frontend (not yet scaffolded — step 7)
docs/        Architecture, schema, sample artifacts
k8s/         Kubernetes manifests (step 8)
.github/     CI/CD workflows (step 8)
```

## Local development

```
cp .env.example .env   # fill in Confluence + LLM credentials
docker compose up postgres redis opensearch   # api/web services come online in later steps
```

## Key documents

- [docs/architecture.md](docs/architecture.md) — bounded contexts, layering, event model, extension points
- [docs/db_schema.sql](docs/db_schema.sql) — canonical PostgreSQL schema
- [docs/sample_knowledge_product.yaml](docs/sample_knowledge_product.yaml) — canonical compiled artifact
- [docs/sample_agent_context.json](docs/sample_agent_context.json) — runtime export consumed by agents
