# Web Page Change Detection

## Context
Re-crawling a source overwrites `web_page` rows silently. Agents and users have
no way to know which pages changed since their last extraction, making it hard to
decide what needs re-extracting and re-compiling.

## Data model
- Add `changed_since_extraction BOOLEAN NOT NULL DEFAULT false` to `web_page`
- New table `web_page_history` — full snapshot of a `web_page` row captured just
  before a re-crawl overwrites it:
  ```sql
  CREATE TABLE web_page_history (
      id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      page_id UUID NOT NULL REFERENCES web_page(id) ON DELETE CASCADE,
      source_id UUID NOT NULL,
      url TEXT NOT NULL,
      title TEXT NOT NULL,
      plain_text TEXT NOT NULL,
      content_hash VARCHAR(64),
      fetched_at TIMESTAMPTZ NOT NULL,
      recorded_at TIMESTAMPTZ NOT NULL DEFAULT now()
  );
  ```

## Backend
- `apps/api/app/infrastructure/db/models.py`
  - Add `changed_since_extraction` to `WebPage` ORM model
  - Add `WebPageHistory` ORM model
- `apps/api/app/api/v1/routers/web_crawl.py`
  - On page update (content_hash differs): snapshot old row into `web_page_history`,
    set `changed_since_extraction = True`
  - On successful extraction: set `changed_since_extraction = False`
  - Add `changed_since_extraction: bool = False` to `WebPageResponse`
  - Populate field in list endpoint

## Frontend
- `apps/web/src/lib/types.ts` — add `changed_since_extraction: boolean` to `WebPage`
- `apps/web/src/app/sources/page.tsx`
  - Row background `bg-red-50` when `changed_since_extraction` is true
  - Red "Changed" badge in extraction status cell with tooltip explaining re-extract needed

## Acceptance criteria
- [x] Re-crawling a page whose HTML changed sets `changed_since_extraction = true` in DB
- [x] Old row is snapshotted to `web_page_history` before overwrite
- [x] Successful extraction clears the flag back to false
- [x] UI shows red row highlight and "Changed" badge
- [x] Pages with no content change are unaffected (flag stays false)

## Out of scope
- Automatic re-extraction trigger on flag set (user initiates manually)
- Diff view between history and current content
