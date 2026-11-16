# 414 — Compile UX Improvements (Sources Page)

## Context
A series of UX improvements to the Filters & Compile panel on the Sources page, focused on improving the compile workflow: cleaner form layout, smarter auto-population, and independent regex filtering for compiled KP membership.

## Changes

### Panel layout & flow
- Removed the status filter (StatusMultiSelect + hide vector-filtered) from the top of the collapsible panel
- Moved regex filter section to below Step 1 Semantic Filter and above Step 2 Compile button
- Moved "Score & Pre-select pages" button above the bucket checkboxes (action first, results second)
- Removed standalone "Curate" button next to "Compile" in the action bar (from prior session)
- Removed "Find Relevant", KP filter bar, Relevance mode, and all related UI/state (`selectedKpId`, `kpStatusMap`, `relevanceMode`, `showNotInKp`, `relevanceBrief`, `relevanceThreshold`, `relevanceScoreMap`)

### Form auto-population
- Product Key field now has a `<datalist>` autocomplete from all existing KPs
- Selecting a known product key auto-fills Name, Owner, and Brief (from latest compile session's `brief_text`)
- Shows an amber warning banner when the selected key matches an existing KP ("compiling will merge into existing draft")
- Name field initialises empty (was defaulting to source name)

### Compiled KP column
- When a product key is selected, pages already compiled into that product show `✓ <Product Name>` in the Compiled KP column (fetched via `getKpPageStatus`)

### Compiled KP regex filter
- Replaced "Fetched" filter field with "Compiled KP" in the regex filter row dropdown
- Added backend endpoint `GET /web-sources/{source_id}/pages/compiled-kp-names` returning all `(page_id, kp_key, kp_name)` pairs for a source from the DB
- Filter loads on source expand, independent of product key selection
- Regex tests against `"<kp_name> <kp_key>"` string — e.g. `102` matches pages in `cs-102`

### Bug fixes
- "Re-score pages" button now shows whenever scores exist (`hasScores`), not only when `compileScoredApplied` is true
- Step 2 compile button count now reflects regex filter (uses `compileCount` not raw `selectedWebPages.size`)

## Acceptance criteria
- [x] Removed KP filter bar, relevance mode, and all related state from sources page
- [x] Regex filter appears below Step 1 semantic filter, above Step 2 compile button
- [x] Score & Pre-select button appears above bucket checkboxes
- [x] Re-score button label shows correctly when scores already exist
- [x] Compile button count updates when regex filter changes
- [x] Selecting an existing product key auto-fills Name, Owner, Brief
- [x] Product Key field shows autocomplete from existing KPs
- [x] Compiled KP column shows product name for pages already in selected product
- [x] Compiled KP regex filter works independently of product key selection
- [x] `GET /web-sources/{source_id}/pages/compiled-kp-names` endpoint returns correct data

## Out of scope
- Filtering against multiple KPs simultaneously (only the selected product key's membership is shown in the column)
- Persisting regex filter state across sessions
