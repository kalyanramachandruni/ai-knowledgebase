# Playwright JS Rendering for Web Crawl

## Context
The current crawler uses `httpx` to fetch pages, which returns raw HTML before
JavaScript executes. Sites built as SPAs (e.g. `signering.posten.no`) return an
empty shell — `plain_text` is empty and no outbound links are discovered, making
these pages and everything they link to invisible to the knowledge extraction pipeline.

The fix is to replace httpx page fetching with Playwright, which runs a real
Chromium instance, waits for the DOM to settle after JS execution, then extracts
the fully-rendered HTML. This applies to all pages — not just detected empties —
because a page with thin httpx content may still have links that are JS-injected.

## Data model
- Add `js_rendered: bool = False` column to `web_page` — set to `True` when the
  page was fetched via Playwright (for observability/debugging)
- No other schema changes

## Backend

### Dependency
- Add `playwright` to `apps/api/requirements.txt` (or `pyproject.toml`)
- Install browser binaries: `playwright install chromium`
- Add to Docker image / startup: `RUN playwright install chromium --with-deps`

### New fetch helper
Replace the `httpx` fetch block in the crawl SSE endpoint with a Playwright-based
helper `_fetch_rendered(url) -> tuple[int, str, str]` returning
`(status_code, content_type, html)`:

```python
async def _fetch_rendered(url: str) -> tuple[int, str, str]:
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        response = await page.goto(url, wait_until="networkidle", timeout=30000)
        html = await page.content()
        await browser.close()
    status = response.status if response else 0
    content_type = (response.headers.get("content-type", "") if response else "")
    return status, content_type, html
```

Use a **shared browser instance** per crawl session (not per page) to avoid
launch overhead on every URL. Launch once before the crawl loop, close after.

### Changes to crawl route
- `apps/api/app/api/v1/routers/web_crawl.py`
  - Remove `import httpx` and `async with httpx.AsyncClient() as client:` block
  - Replace `resp = await client.get(url)` with `status, content_type, html = await _fetch_rendered(url)`
  - Adapt status/content_type checks to use the returned values
  - Set `js_rendered = True` on the `WebPage` row

### Changes to linked-page crawl
- `_crawl_and_extract_linked` also uses httpx — replace with the same Playwright helper

### Timeout & error handling
- Set `timeout=30000` (30s) per page in Playwright
- On timeout: treat as a skipped page (same as current network error handling)
- `wait_until="networkidle"` — waits until no network requests for 500ms, giving
  JS time to render. Fall back to `"domcontentloaded"` if networkidle times out.

## Frontend
No frontend changes required. The `js_rendered` flag is stored in DB for
observability but not surfaced in the UI (out of scope).

## Acceptance criteria
- [x] Crawling `https://signering.posten.no/` returns non-empty `plain_text`
- [x] Links found on JS-rendered pages (e.g. `/privat/slik-sender-du`) are
      discovered and added to the crawl queue
- [x] `js_rendered = true` is set on pages fetched via Playwright
- [x] A single browser instance is reused across all pages in one crawl session
      (not launched per page)
- [x] Timeout of 30s per page — timed-out pages are skipped, not crashed
- [x] All existing non-JS pages continue to crawl correctly

## Out of scope
- Per-page httpx fallback (all pages use Playwright)
- Screenshot capture
- Cookie consent / login handling
- Proxy support
- Parallel page fetching within one crawl (single browser, sequential pages)
