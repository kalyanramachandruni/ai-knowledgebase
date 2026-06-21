# Knowledge Product Studio

Confluence → Knowledge Product → Agent Context Package.

Treats business-process knowledge as a versioned, governed, deployable artifact — not a vector index.

## Status

MVP complete (all 8 build steps): domain model + DB schema, Knowledge Product Registry,
Confluence ingestion, LLM extraction + compiler, Context Package Generator + Agent API,
governance (RBAC + approval workflow), the Next.js frontend, and deployment/CI-CD/observability.
See [docs/architecture.md](docs/architecture.md) for the full design.

## Repo layout

```
apps/api/       FastAPI backend — Domain-Driven Design, Clean Architecture
apps/web/       Next.js frontend — Dashboard, Knowledge Product List/Details, Version History
docs/           Architecture, schema, sample artifacts
k8s/            Kubernetes manifests (kustomize)
observability/  OpenTelemetry Collector, Prometheus, Grafana config for local dev
.github/        CI (lint/test/build) and CD (image build+push) workflows
```

## Local development

```
cp .env.example .env   # fill in Confluence + LLM credentials
docker compose up postgres redis opensearch otel-collector prometheus grafana
docker compose up api web   # or run each with hot-reload: uvicorn / npm run dev
```

Sign in at http://localhost:3000/login — this issues a dev JWT for any role with no real
credential check (`ENABLE_DEV_LOGIN=true` by default). Set it to `false` once a real OIDC
provider is wired up; that's the only thing standing in for SSO right now.

Observability: API traces flow to the OTel Collector (`:4317`), `/metrics` is scraped by
Prometheus (http://localhost:9090), and Grafana (http://localhost:3001, admin/admin) comes
with the Prometheus datasource pre-provisioned.

## Tests

```
cd apps/api && pip install -e ".[dev]" && pytest
cd apps/web && npm ci && npx tsc --noEmit && npm run build
```

## Deploying

```
kubectl create configmap db-schema -n knowledge-product-studio \
  --from-file=schema.sql=docs/db_schema.sql --dry-run=client -o yaml | kubectl apply -f -
kubectl apply -k k8s/
kubectl apply -f k8s/11-migration-job.yaml
```

Push real secrets into `kps-secrets` (see the comment at the top of `k8s/02-secret.yaml`) before
applying in any environment that matters — the checked-in version is a template with empty values.
The CD workflow ([.github/workflows/cd.yml](.github/workflows/cd.yml)) builds and pushes images to
GHCR on every push to `main`; the actual cluster deploy step is a placeholder pending cluster
credentials.

## Key documents

- [docs/architecture.md](docs/architecture.md) — bounded contexts, layering, event model, extension points
- [docs/db_schema.sql](docs/db_schema.sql) — canonical PostgreSQL schema
- [docs/sample_knowledge_product.yaml](docs/sample_knowledge_product.yaml) — canonical compiled artifact
- [docs/sample_agent_context.json](docs/sample_agent_context.json) — runtime export consumed by agents
