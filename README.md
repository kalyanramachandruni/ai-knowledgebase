# Knowledge Product Studio

Confluence → Knowledge Product → Agent Context Package.

Treats business-process knowledge as a versioned, governed, deployable artifact — not a vector index.

## Status

MVP build in progress. See [docs/architecture.md](docs/architecture.md) for the full design.
Implemented so far: domain model + DB schema, Knowledge Product Registry, Confluence ingestion,
LLM extraction + compiler, Context Package Generator + Agent API, governance (RBAC + approval
workflow), and the Next.js frontend (steps 1–7 of 8). Remaining: Docker/K8s/CI-CD polish + observability.

## Repo layout

```
apps/api/    FastAPI backend — Domain-Driven Design, Clean Architecture
apps/web/    Next.js frontend — Dashboard, Knowledge Product List/Details, Version History
docs/        Architecture, schema, sample artifacts
k8s/         Kubernetes manifests (step 8)
.github/     CI/CD workflows (step 8)
```

## Local development

```
cp .env.example .env   # fill in Confluence + LLM credentials
docker compose up postgres redis opensearch
docker compose up api web   # or run each with hot-reload: uvicorn / npm run dev
```

Sign in at http://localhost:3000/login — this issues a dev JWT for any role with no real
credential check (`ENABLE_DEV_LOGIN=true` by default). Set it to `false` once a real OIDC
provider is wired up; that's the only thing standing in for SSO right now.

## Key documents

- [docs/architecture.md](docs/architecture.md) — bounded contexts, layering, event model, extension points
- [docs/db_schema.sql](docs/db_schema.sql) — canonical PostgreSQL schema
- [docs/sample_knowledge_product.yaml](docs/sample_knowledge_product.yaml) — canonical compiled artifact
- [docs/sample_agent_context.json](docs/sample_agent_context.json) — runtime export consumed by agents
