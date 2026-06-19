# Knowledge Product Studio — Architecture

## 1. Vision

```
Confluence  ──ingest──>  Raw Content Store  ──extract──>  Structured Knowledge
                                                                  │
                                                              compile
                                                                  ▼
                                                  Knowledge Product (versioned, governed)
                                                                  │
                                                              generate
                                                                  ▼
                                                       Agent Context Package (JSON/YAML)
                                                                  │
                                                              consume
                                                                  ▼
                                                              AI Agents
```

This is not a RAG platform. A Knowledge Product is a **governed, versioned, deployable artifact** — analogous to a build artifact in software delivery — not a vector index.

## 2. Architectural style

- **Domain-Driven Design**: each capability is a bounded context with its own aggregates, value objects, and repository interface.
- **Clean Architecture / Hexagonal**: domain has zero framework dependencies. Application layer orchestrates use cases. Infrastructure implements ports (DB, LLM, search, Confluence client). API layer is a thin adapter.
- **Event-Driven**: state transitions (`PageIngested`, `KnowledgeExtracted`, `ProductCompiled`, `ProductApproved`, `ProductPublished`, `ProductRetired`) are emitted as domain events. MVP uses an in-process event bus (outbox table) so it can later move to Kafka/SNS without changing domain code.

## 3. Bounded contexts

| Context | Responsibility | Key aggregate |
|---|---|---|
| Confluence Ingestion | Connect, crawl, sync raw pages | `ConfluencePage` |
| Knowledge Extraction | LLM-driven structuring of raw content | `ExtractionRun` |
| Knowledge Product | Canonical compiled artifact, versioning | `KnowledgeProduct` |
| Governance | RBAC, approval workflow, audit | `ApprovalRequest`, `AuditEntry` |
| Context Package | Runtime export for agents | (read-model / projection, no own aggregate) |

Each lives under `apps/api/app/domain/<context>/` with its own `entities.py`, `value_objects.py`, `events.py`, `repository.py` (interface only).

## 4. Layout

```
apps/api/app/
  domain/                 # pure Python, no I/O, no framework imports
    knowledge_product/
    confluence/
    extraction/
    governance/
    shared/               # base Entity, AggregateRoot, DomainEvent, ValueObject
  application/             # use cases / command handlers, orchestrate domain + ports
  infrastructure/
    db/                   # SQLAlchemy models + repository implementations
    confluence/            # Confluence REST client (port implementation)
    llm/                   # Provider-agnostic LLM port + Anthropic/OpenAI adapters
    search/                 # OpenSearch adapter
    cache/                  # Redis adapter
  api/v1/                  # FastAPI routers, request/response schemas
  core/                     # settings, security (OAuth2/JWT), DI wiring, logging, otel
```

Dependency rule: `domain` depends on nothing in this codebase. `application` depends only on `domain`. `infrastructure` implements interfaces defined in `domain`/`application`. `api` depends on `application` and DI-wires `infrastructure`.

## 5. LLM provider abstraction (extension point)

`domain` and `application` only see a port:

```python
class LLMExtractionPort(Protocol):
    async def extract(self, raw_text: str, schema: ExtractionSchema) -> ExtractionResult: ...
```

`infrastructure/llm/` provides:
- `anthropic_adapter.py` (default — Claude Sonnet 4.6, structured output via tool-use/JSON schema)
- `openai_adapter.py` (alternate implementation, same port)
- `factory.py` selects adapter from `LLM_PROVIDER` env var.

Swapping providers is a config change, never a code change in domain/application.

## 6. Versioning & governance model

- Every mutation to a `KnowledgeProduct` produces a new immutable version row (`knowledge_product_version`), not an in-place update.
- Status machine: `draft → review → approved → published → retired`, enforced in the domain aggregate (illegal transitions raise domain exceptions).
- Semantic version bump rule (default, overridable by Knowledge Owner):
  - MAJOR: rule/policy logic change, or process step removed
  - MINOR: new step/rule/policy/role/tool added
  - PATCH: metadata/text/doc-only edit
- All transitions and field-level diffs are written to `audit_entry` (immutable, append-only).

## 7. Future extension points (not implemented in MVP)

Each is reserved as an interface/empty module so later work doesn't require restructuring:

- `domain/skill_bundle/` — package multiple Knowledge Products + tools as a deployable "skill"
- `domain/knowledge_graph/` — relationships between processes/roles/tools across products
- `domain/agent_registry/` — catalog of agents and which Knowledge Products they consume
- `domain/policy_studio/` — authoring UI/DSL for policies independent of Confluence source
- `infrastructure/bpmn/` — BPMN import/export adapter
- `infrastructure/orchestration/langgraph_adapter.py`, `openai_agents_adapter.py` — implement `AgentOrchestrationPort`
- `infrastructure/integrations/copilot_adapter.py`, `servicenow_adapter.py`

These are stub modules with docstring-only `Port` interfaces — no logic, so they compile but do nothing yet.

## 8. Non-functional mapping

| Concern | Choice |
|---|---|
| API | FastAPI, async, Pydantic v2 |
| ORM | SQLAlchemy 2.0 (async engine) + Alembic migrations |
| DB | PostgreSQL (raw content, products as JSONB, audit log) |
| Search | OpenSearch (full-text over compiled products, for the List/Search UI) |
| Cache | Redis (context package cache, session/rate-limit) |
| Auth | OAuth2 (Authorization Code + PKCE), JWT bearer tokens, SSO-ready (OIDC discovery) |
| Frontend | Next.js 14 (App Router), React, TypeScript, Tailwind |
| Deployment | Docker images per service, Kubernetes manifests, Helm-ready structure |
| CI/CD | GitHub Actions: lint → test → build → push image → deploy |
| Observability | OpenTelemetry SDK (traces+metrics) → OTel Collector → Prometheus + Grafana |

## 9. Sequence: Confluence page → Agent Context Package

1. `ConfluenceSyncJob` (scheduled or triggered) crawls a space, diffs by `version` field, upserts `confluence_page` rows, emits `PageIngested`.
2. `ExtractionUseCase` consumes `PageIngested`, calls `LLMExtractionPort.extract(...)`, persists `extraction_run` + structured draft, emits `KnowledgeExtracted`.
3. `CompileKnowledgeProductUseCase` maps the structured draft into the canonical YAML schema, creates `KnowledgeProduct` version in `draft`, emits `ProductCompiled`.
4. Knowledge Owner reviews in UI → `review` → Reviewer approves → `approved` → Knowledge Owner publishes → `published`, emits `ProductPublished`.
5. `ContextPackageGenerator` projects the published `KnowledgeProduct` into the Agent Context JSON/YAML on demand (and caches in Redis), served via `GET /knowledge-products/{id}/context`.
