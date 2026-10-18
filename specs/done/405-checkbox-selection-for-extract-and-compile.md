# Checkbox Selection for Extract and Compile

## Context
The Web Wikis table has two independent filter/selection layers but they are not
wired up correctly:

1. **Header-level filters** (status dropdown + regex rows) narrow which pages appear
   in the table. This works correctly today.
2. **Checkboxes** (header + row) are meant to be a second-level selection within
   the filtered set, driving both Extract and Compile. Today they only feed the
   Compile button — the Extract button always ignores checkbox state and works on
   all filtered pending pages. The header checkbox also only selects succeeded
   pages, not all filtered pages.

## Desired behaviour

### Header checkbox
- Selects / deselects **all** `filteredPages` (not just succeeded ones).
- Indeterminate when some but not all filtered pages are checked.

### Row checkboxes
- Enabled for **all** pages regardless of curation status (currently disabled
  for non-succeeded pages).
- Tooltip: "Select for extraction or compilation".

### Extract button
- **With selection:** extract only the checked pages that are pending
  (`!latest_run_status || latest_run_status === "failed"`).
  Label: `Extract X selected`.
- **Without selection:** extract all filtered pending pages (current behaviour).
  Label: `Extract N pending`.
- Button is disabled when the relevant pending count is 0.

### Compile button
- **With selection:** compile only checked pages with `latest_run_status === "succeeded"`.
  Label: `Compile X selected → KP`.
- **Without selection:** compile all filtered succeeded pages (current behaviour).
  No change to existing logic.

## Frontend

### `apps/web/src/app/sources/page.tsx`
- `handleExtractAll(sourceId, pages)` — `pages` becomes the explicit list to
  extract (already filtered to pending inside the function); no logic change
  needed there, just call it with the right list.
- Derive `pendingInSelection` = checked pages that are pending.
- Derive `extractTarget` = `selSize > 0 ? pendingInSelection : allFilteredPending`.
- Extract button: label and disabled state based on `extractTarget`.
- Extract button `onClick`: call `handleExtractAll(src.id, extractTarget)`.
- Header checkbox `onChange`: toggle all `filteredPages` (not just succeeded).
- Header checkbox `checked` / `indeterminate`: based on all `filteredPages`.
- Row checkbox: remove the `disabled` prop so all rows are checkable.

## Acceptance criteria
- [x] Header checkbox selects / deselects all filtered pages
- [x] Row checkboxes are enabled for all pages
- [x] With pages checked, Extract button label shows count of selected pending pages
- [x] With pages checked, Extract runs only on the checked pending subset
- [x] With no pages checked, Extract behaviour is unchanged
- [x] With pages checked, Compile button reflects selected succeeded count (unchanged)
- [x] With no pages checked, Compile behaviour is unchanged

## Out of scope
- Backend changes
- Confluence pages tab
