# [Feature Title]

## Context
<!-- Why this is needed. What problem it solves. Reference related tables, endpoints, or UI areas. -->

## Data model
<!-- New tables, columns, or constraints. Include SQL for migrations. -->
<!-- Example:
- Add `compiled_at TIMESTAMPTZ` to `knowledge_product_version`
- New table `web_page_history` — snapshot of web_page before overwrite
-->

## Backend
<!-- New or changed API endpoints. Pydantic schema changes. Business logic. -->
<!-- Example:
- `GET /web-sources/{id}/pages` — add `changed_since_extraction: bool` to response
- On crawl update: set flag, snapshot old row
-->

## Frontend
<!-- Component changes, new state, UI behaviour, type changes. -->
<!-- Example:
- `WebPage` type: add `changed_since_extraction: boolean`
- Row highlighted red when flag is true; "Changed" badge in extraction column
-->

## Acceptance criteria
<!-- Concrete, testable statements. Agent checks these off during implementation. -->
- [ ] ...
- [ ] ...
- [ ] ...

## Out of scope
<!-- Explicitly list anything that might seem related but is not part of this spec. -->
