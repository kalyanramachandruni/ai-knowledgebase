# Web Wiki Status Multi-Select Filter

## Context
The Web Wikis tab had a row of single-select pill buttons for filtering pages by
extraction/compile status. Only one status could be active at a time, and all
possible values were hardcoded regardless of whether any pages in the source
actually had that status. Replacing it with a multi-select dropdown that derives
its options from the actual page data makes the filter both more useful and less
noisy.

## Frontend

### `apps/web/src/app/sources/page.tsx`
- Replace `extractionStatusFilter` state type from single-value `Record<string, string | null>`
  to multi-value `Record<string, string[]>`
- Update filter predicate to OR across all selected statuses
- Add `getDistinctStatuses(pages)` helper that inspects loaded page data and
  returns only the status values actually present (using the same "none" /
  "succeeded" / "failed" / "running" / "compiled" / "not_compiled" keys as before)
- Add `StatusMultiSelect` component: a button that opens a dropdown with one
  checkbox per distinct status; closes on outside click; shows "All" when nothing
  is selected, or a truncated comma-list of selected labels otherwise
- Update `hasFilter` and `clearFilters` to work with the new array-based state

## Acceptance criteria
- [x] Status filter is a dropdown, not a row of pill buttons
- [x] Dropdown options are derived from actual page data — only statuses present
      in the source's pages appear as options
- [x] Multiple statuses can be selected simultaneously (OR logic)
- [x] Selecting no statuses shows all pages (same as "All" previously)
- [x] "Clear selection" inside the dropdown resets to show all
- [x] TypeScript compiles without errors

## Out of scope
- Backend changes — filtering is client-side only
- Persisting filter state across page reloads
