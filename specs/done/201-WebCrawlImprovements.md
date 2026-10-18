# Recursive Links Tree in Popup

## Context
The Links popup on the Sources page shows only the direct outbound links from one
page. Pages discovered during a recursive crawl have multi-level link relationships
stored in `web_page_link`. Users need to see the full bidirectional context:
- **Parent lineage** — which pages link TO this page (ancestors, going up)
- **Child lineage** — which pages this page links TO (descendants, going down)

## Data model
No schema changes. Uses existing `web_page_link`:
- `source_page_id → linked_page_id` (outbound: child direction)
- `linked_page_id → source_page_id` (inbound: parent direction)
Both traversed recursively via SQL CTEs, scoped to the same source.

## Backend
- New endpoint: `GET /web-sources/{source_id}/pages/{page_id}/links/tree`
- Returns:
  ```json
  {
    "page": { "page_id", "url", "title", "run_status", "is_compiled" },
    "parents": [ { "page_id", "url", "title", "depth", "run_status", "is_compiled", "parents": [...] } ],
    "children": [ { "page_id", "url", "title", "depth", "run_status", "is_compiled", "children": [...] } ]
  }
  ```
- Parents CTE: walk `web_page_link` upward (where `linked_page_id = page_id`)
- Children CTE: walk `web_page_link` downward (where `source_page_id = page_id`)
- Cap both directions at depth 10 to prevent runaway queries
- Scoped to `source_id` — only pages belonging to this source appear

## Frontend
- Links popup calls the new tree endpoint
- Renders two collapsible sections: **"Referenced by"** (parents) and **"Links to"** (children)
- Tree nodes indented 16px per depth level with expand/collapse toggle
- Nodes at depth > 2 collapsed by default
- Each node shows: title, URL (monospace, truncated), extraction status badge, compiled badge
- Pages with `linked_page_id IS NULL` (not yet crawled) shown as plain URL + "Not crawled" label

## Self-link filtering

A page may contain a hyperlink pointing to itself (e.g. a nav bar item for the current page).
These must be excluded at two layers:

### During crawl (link collection)
- `_all_http_links` and `_same_origin_links` both skip any href that resolves to the same
  URL as the page being parsed (`clean != base_url.rstrip("/")`).
- This prevents a `web_page_link` row where `source_page_id == linked_page_id` from ever
  being inserted.

### In the recursive CTE (query guardrail)
- Both the children CTE and parents CTE add `wpl.source_page_id != wpl.linked_page_id`
  (and `wpl2.source_page_id != wpl2.linked_page_id` in the recursive step) to each
  `WHERE` clause, so any pre-existing self-link rows are silently ignored at query time.

## Acceptance criteria
- [x] Popup shows "Referenced by" section listing pages that link to this page, recursively
- [x] Popup shows "Links to" section listing pages this page links to, recursively
- [x] Each node is indented per depth and has expand/collapse for nodes with children
- [x] Nodes beyond depth 2 start collapsed
- [x] Each node shows title, URL, extraction and compiled status badges
- [x] Uncrawled link targets shown as plain URL with "Not crawled"
- [x] Tree is scoped to the same source — no cross-source pages appear
- [x] Self-links (page linking to itself) are skipped during link collection
- [x] Recursive CTE guardrail ignores any pre-existing self-link rows

## Out of scope
- Triggering extraction from within the tree
- External-domain URLs in the tree
- Editing link relationships
