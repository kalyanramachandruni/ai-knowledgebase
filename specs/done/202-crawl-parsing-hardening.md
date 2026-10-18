# Crawl Parsing Hardening

## Context
The HTML helpers in `apps/api/app/api/v1/routers/web_crawl.py` (`_node_to_markdown`,
`_extract_text`, `_same_origin_links`, `_all_http_links`, `_parent_domain`) have
correctness gaps that degrade both the crawl and the text sent to the LLM:

- **URL normalisation is inconsistent.** `_same_origin_links` keeps trailing slashes, but
  `_all_http_links` strips them. Pages queued as `/a/` are stored under that URL, while
  `web_page_link` records `/a`, so `linked_page_id` never resolves. The same page can be
  stored twice (`/a` and `/a/`). Host case, default ports, userinfo and http/https also
  produce duplicates.
- **The domain scope is wrong.** `_parent_domain` keeps the last two host labels. This
  makes every `*.co.uk` / `*.com.au` site "same origin" and lets the crawler wander across
  `*.github.io`, `*.vercel.app`, etc.
- **Query strings are always dropped.** That merges distinct pages (`?id=123`, `?page=2`)
  into one.
- **Links are resolved against the wrong base.** Links are resolved against the
  *requested* URL, not the post-redirect URL, and `<base href>` is ignored.
- **Requests are wasted, and crawl etiquette is ignored.**
  - `.pdf`/`.zip`/image links are fetched before the content-type check rejects them.
  - `robots.txt` and `rel="nofollow"` are ignored.
- **`plain_text` contains text the LLM shouldn't see, and loses text it should.**
  - Relative links stay relative (the code comment claiming otherwise is wrong).
  - HTML comments leak into the text.
  - Block elements run together with no separator.
  - `mailto:`/`tel:`/`JavaScript:` links pass the filter, and `]`/`)` in links produce
    broken markdown.
  - Article-level `<header>`/`<footer>`/`<aside>` content is lost, while `<noscript>`,
    `<svg>`, `<iframe>`, forms and cookie banners are kept.
  - Deeply nested DOMs can hit the recursion limit.
- **Title selection misses cases.** `<title>` with more than one child node returns
  `None`. The `<h1>` fallback runs after `<header>` is removed, so it misses headline
  `<h1>`s.
- **JS-rendered pages fail silently.** They yield near-empty `plain_text`, and nothing
  flags it.
- **There is avoidable inefficiency.** Each page is parsed three times, and `clean not in
  links` makes deduplication O(n²).

## Data model
New SQL migration `docs/migrations/20261001_crawl_parsing_hardening.sql` (repo convention; applied manually with `psql`):
- `web_source.include_query_strings BOOLEAN NOT NULL DEFAULT false`: when true, query
  strings are kept as part of a page's identity (tracking params are still removed).
- `web_page.is_thin_content BOOLEAN NOT NULL DEFAULT false`: set when extracted text is
  too short to be useful (likely a JS-rendered page).

ORM: add both columns in `apps/api/app/infrastructure/db/models.py`.

## Backend

### New module `apps/api/app/infrastructure/crawl/html_parsing.py`
This is a pure module with no FastAPI or DB imports, so it can be unit-tested. It replaces
the five helpers in `web_crawl.py`.

- `normalize_url(url: str, *, keep_query: bool) -> str | None`
  - Returns `None` for any scheme other than `http`/`https`. Scheme matching is
    case-insensitive.
  - Lowercases the scheme and host.
  - Drops userinfo, default ports (`:80` for http, `:443` for https) and the fragment.
  - Strips the trailing slash from the path. The root path `/` becomes an empty path, which
    matches how `root_url` is stored today.
  - With `keep_query=False`, drops the query string. With `keep_query=True`:
    - removes `utm_*`, `fbclid`, `gclid`, `mc_cid`, `mc_eid`;
    - sorts the remaining params;
    - drops the `?` if nothing remains.
- `site_key(host: str) -> str`
  - Returns the registrable domain using `tldextract`, with the Public Suffix List private
    section enabled (`include_psl_private_domains=True`). It must use the bundled snapshot
    only, with no network fetch at runtime (`suffix_list_urls=()`).
  - Examples: `www.bbc.co.uk` → `bbc.co.uk`, `foo.github.io` → `foo.github.io`,
    `adressesok.posten.no` → `posten.no`.
  - Add `tldextract` to `apps/api/pyproject.toml`.
- `parse_page(html: str, page_url: str, *, keep_query: bool) -> ParsedPage`
  - Parses the HTML **once** and returns a dataclass with these fields:
    - `title: str`
    - `plain_text: str`
    - `links: list[str]`: all normalised http(s) links, deduplicated in order, self
      excluded.
    - `follow_links: list[str]`: the subset with the same `site_key` as `page_url`, not
      `rel="nofollow"`, and not a skipped file extension.
    - `is_thin_content: bool`
  - **Base URL:** use `<base href>` if present (resolved against `page_url`), otherwise
    `page_url`. All `urljoin` calls use this base.
  - **Link collection happens before any tree mutation.** It runs over all `<a href>` in
    the full document, matching today's behaviour of recording nav and footer links. It
    uses a `set` for deduplication.
  - **Skipped file extensions:** `.pdf .zip .gz .tar .rar .7z .exe .dmg .msi .jpg .jpeg
    .png .gif .webp .svg .ico .mp3 .mp4 .mov .avi .webm .woff .woff2 .ttf .css .js .xml
    .json .csv .xls .xlsx .doc .docx .ppt .pptx`. The match is case-insensitive on the
    path. Such links are still recorded in `links`.
  - **Title, in this order:**
    1. `<title>` via `get_text(" ", strip=True)`;
    2. `<meta property="og:title">`;
    3. the first `<h1>`, captured **before** noise removal;
    4. `"Untitled"`.
  - **Noise removal:**
    - Always remove: `script style noscript template svg iframe form button nav`.
    - Remove any element with `role` in `navigation`, `banner` or `contentinfo`.
    - Remove any element whose `id` or `class` contains `cookie`, `consent` or `gdpr`
      (case-insensitive).
    - Remove `header`, `footer` and `aside` **only when** they have no `article`, `main`
      or `section` ancestor.
    - Remove all `Comment`, `CData`, `ProcessingInstruction`, `Declaration` and `Doctype`
      nodes.
  - **Text conversion:** iterative (explicit stack), not recursive.
    - Plain text nodes are emitted as-is.
    - `<a href>`:
      - The href is resolved to an absolute URL against the base.
      - It is rendered `[text](url)` only when the resolved scheme is http(s) and the href
        is not a bare `#fragment`.
      - Otherwise only the text is emitted.
      - In link text, escape `[` and `]` as `\[` and `\]`. In URLs, percent-encode `(`,
        `)` and spaces.
    - `<br>` emits `\n`.
    - Block elements (`p div section article main li ul ol table tr h1–h6 blockquote pre
      dl dt dd figure figcaption`) are surrounded by `\n`.
    - `h1`–`h6` are prefixed with `#`×level plus a space.
    - `li` is prefixed with `- `.
    - `pre` content keeps its whitespace.
    - **Post-processing:** collapse runs of spaces and tabs to one space (outside `pre`),
      collapse 3+ newlines to 2, and strip each line and the whole text.
  - **Thin content:** `is_thin_content = True` when the final `plain_text` with markdown
    link syntax removed has fewer than 200 characters **and** the raw HTML contains at
    least one `<script>`.

### `apps/api/app/api/v1/routers/web_crawl.py`
- Delete `_node_to_markdown`, `_extract_text`, `_parent_domain`, `_same_origin_links` and
  `_all_http_links`. Use `parse_page` / `normalize_url` / `site_key` instead.
- **`crawl_web_source`:**
  - `root_url` = `normalize_url(source.root_url, keep_query=source.include_query_strings)`.
  - The crawl scope is `site_key` of the **root URL** (not of the current page).
  - `visited` and `queued` are `set`s of normalised URLs.
  - **Redirects:** after the fetch, compute `final_url = normalize_url(str(resp.url),
    ...)`.
    - If `site_key(final_url)` is outside the scope, skip the page with
      `page_skipped` reason `"redirected off-site"`.
    - Otherwise add `final_url` to `visited`.
    - If `final_url` is already stored for this source, treat it as that page. Do not
      create a second row under the requested URL.
    - Store and parse the page under `final_url`.
  - **Before fetching any queued URL:**
    - Skip URLs with a skipped file extension. These are not counted or emitted.
    - Check `robots.txt`:
      - It is fetched once per host per crawl via `urllib.robotparser`, using the
        `httpx` client.
      - A 4xx response means allow all. A network error or 5xx means allow all and log a
        warning.
      - Check with the crawler's User-Agent `ai-knowledgebase-crawler`, which is also set
        as the client's `User-Agent` header.
      - Disallowed URLs emit `page_skipped` with reason `"robots.txt"` and count as
        skipped.
  - Enqueue `parsed.follow_links` (depth rules unchanged). Store `parsed.links` in
    `web_page_link`.
  - Persist `is_thin_content` on create and update. Emit `"thin_content": true` in the
    `page_found` / `page_updated` SSE event when it is set.
- **`_crawl_and_extract_linked`:**
  - Use `site_key` of the source root for scope, `parse_page` for text, and the same
    redirect and robots.txt handling.
  - Look up URLs normalised with the source's `include_query_strings`.
- **Schemas:**
  - `CreateWebSourceRequest.include_query_strings: bool = False`
  - `WebSourceResponse.include_query_strings: bool`
  - `WebPageResponse.is_thin_content: bool = False`

### Tests: `apps/api/tests/test_html_parsing.py`
Unit tests for `normalize_url`, `site_key` and `parse_page` covering every acceptance
criterion below that is marked *(unit)*.

## Frontend
- **`apps/web/src/lib/types.ts`:**
  - Add `include_query_strings: boolean` to the web source type.
  - Add `is_thin_content: boolean` to `WebPage`.
- **`apps/web/src/lib/api.ts`:** pass `include_query_strings` in the create-web-source
  request.
- **`apps/web/src/app/sources/page.tsx`:**
  - Add a checkbox "Treat query strings as separate pages" to the create-web-source form,
    default unchecked, with a helper tooltip: "Enable for sites where `?id=` or `?page=`
    selects different content".
  - Add an amber "Thin content" badge in the page row when `is_thin_content` is true. Its
    tooltip: "Very little text was found — the page may require JavaScript to render."
  - Handle the `thin_content` flag in crawl SSE events (show it in the crawl log line).

## Acceptance criteria
- [x] *(unit)* `normalize_url` maps `HTTPS://Example.no:443/a/`, `https://example.no/a`
      and `https://user@example.no/a#x` to the same string.
- [x] *(unit)* `normalize_url` returns `None` for `mailto:`, `tel:` and `JavaScript:`
      URLs.
- [x] *(unit)* With `keep_query=False` the query is dropped. With `keep_query=True`,
      `?b=2&utm_source=x&a=1` becomes `?a=1&b=2`.
- [x] *(unit)* `site_key` returns `bbc.co.uk`, `foo.github.io` and `posten.no` for the
      examples above, without network access.
- [x] *(unit)* `parse_page` resolves relative links against `<base href>` when present,
      otherwise against the page URL. Every link in `plain_text` is absolute.
- [x] *(unit)* HTML comments do not appear in `plain_text`.
- [x] *(unit)* `<p>One</p><p>Two</p>` (no whitespace between) yields `One` and `Two` on
      separate lines. Headings get `#` prefixes and list items get `- `.
- [x] *(unit)* `<a href="mailto:x@y">Mail</a>` yields `Mail` with no link syntax. Link
      text containing `]` and URLs containing `)` produce valid markdown.
- [x] *(unit)* `<article><header><h1>Headline</h1></header>…</article>` keeps
      "Headline" in `plain_text`. A top-level `<header>` and `<nav>` are removed.
- [x] *(unit)* `<noscript>`, `<svg>`, `<form>`, `role="navigation"` and
      `id="cookie-banner"` content is absent from `plain_text`.
- [x] *(unit)* The title is read with `get_text` and its whitespace is collapsed
      (`<title>\n  Foo\n   Bar </title>` gives `Foo Bar`). With no `<title>`, an `<h1>`
      inside a top-level `<header>` is used as the title. (Changed from a `<!-- -->` example:
      `<title>` is raw text in HTML, so a comment inside it is literal text, exactly as
      browsers display it.)
- [x] *(unit)* A 5000-level nested `<div>` document parses without `RecursionError`.
- [x] *(unit)* `follow_links` excludes other sites, `rel="nofollow"` links and `.pdf`
      links. `links` still includes the latter two.
- [x] *(unit)* An empty SPA shell (`<div id="root"></div><script src=…>`) gives
      `is_thin_content = True`. A normal article page gives `False`.
- [x] After a crawl, every `web_page_link` whose URL matches a `web_page.url` in the
      same source has `linked_page_id` set. No source contains two pages whose URLs
      differ only by a trailing slash, case, port or fragment.
- [x] A page that redirects off-site is skipped with reason `"redirected off-site"`. A
      same-site redirect is stored under its final URL.
- [x] URLs disallowed by `robots.txt` are not fetched and appear as `page_skipped` with
      reason `"robots.txt"`.
- [x] Links with skipped file extensions are never fetched.
- [x] A source created with `include_query_strings = true` stores `?page=1` and
      `?page=2` as separate pages. The default source merges them.
- [x] Each crawled page's HTML is parsed by BeautifulSoup exactly once.
- [x] The create-source form has the query-string checkbox, and the value round-trips
      through the API.
- [x] Pages with `is_thin_content` show the amber "Thin content" badge on the Sources
      page.

## Out of scope
- **Rewriting existing `web_page` / `web_page_link` rows.** Already-stored URLs are not
  re-normalised or merged. Duplicates created before this change remain until the source
  is deleted and re-crawled. See open question 1.
- Rendering JS-heavy pages with a headless browser (only flagging them).
- `Crawl-delay`, rate limiting, `sitemap.xml` discovery, or a max-pages cap.
- Re-running extraction automatically on pages whose `plain_text` changes because of the
  new text format. The existing `changed_since_extraction` flag covers this on the next
  re-crawl.
- Editing `include_query_strings` on an existing source.

## Open questions
1. Should the migration also normalise existing `web_page.url` / `web_page_link.url` rows?
   Doing so means merging duplicate pages, and with them their extraction runs and
   compile entries, under the `(source_id, url)` unique constraint. That is significantly
   more work, and it is excluded above.
2. Every existing page's `content_hash` is computed on raw HTML, so the new text format
   alone won't mark pages changed. Is it acceptable that existing pages keep old-format
   `plain_text` until their HTML changes, or should a re-crawl force a re-parse?
3. Are the 200-character thin-content threshold and the cookie/consent/gdpr class
   heuristics acceptable defaults?
