from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import uuid
from collections import deque
from typing import Annotated
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx
from playwright.async_api import async_playwright, Browser
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select, text, update

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.security import CurrentUser, require_roles
from app.domain.curation.entities import CurationRun, CurationStatus, PageSourceType
from app.domain.curation.schema import KNOWLEDGE_CURATION_SCHEMA
from app.domain.governance.value_objects import Role
from app.domain.shared.base import utc_now
from app.infrastructure.crawl.html_parsing import has_skipped_extension, normalize_url, parse_page, url_site_key
from app.infrastructure.db.curation_repository import SqlAlchemyCurationRunRepository
from app.infrastructure.llm.factory import get_llm_curation_port
from app.infrastructure.db.models import (
    PageCurationSession as CurationSessionModel,
    PageCurationSessionEntry as CurationRunModel,
    WebPage as WebPageModel,
    WebPageHistory as WebPageHistoryModel,
    WebPageLink as WebPageLinkModel,
    WebSource as WebSourceModel,
    WebSourceHistory as WebSourceHistoryModel,
)
from app.infrastructure.db.session import SessionLocal

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/web-sources", tags=["web-sources"])

_ANY_ROLE = require_roles(Role.KNOWLEDGE_OWNER, Role.ADMIN, Role.REVIEWER, Role.CONSUMER)
_OWNER_OR_ADMIN = require_roles(Role.KNOWLEDGE_OWNER, Role.ADMIN)

CRAWLER_USER_AGENT = "ai-knowledgebase-crawler"
_CRAWL_HEADERS = {"User-Agent": CRAWLER_USER_AGENT}


# ── Schemas ──────────────────────────────────────────────────────────────────

class CreateWebSourceRequest(BaseModel):
    name: str
    root_url: str
    crawl_depth: int | None = None  # None = unlimited; 1 = root page links only
    include_query_strings: bool = False


class WebSourceResponse(BaseModel):
    id: str
    name: str
    root_url: str
    crawl_depth: int | None
    include_query_strings: bool
    last_crawled_at: str | None
    page_count: int
    last_crawl_created: int | None
    last_crawl_updated: int | None
    last_crawl_skipped: int | None
    crawl_status: str | None
    successful_crawl_count: int


class WebPageResponse(BaseModel):
    id: str
    source_id: str
    url: str
    title: str
    content_hash: str | None
    fetched_at: str
    latest_run_id: str | None = None
    latest_run_status: str | None = None  # running | succeeded | failed
    latest_run_error: str | None = None
    page_tags: list[str] = []
    is_compiled: bool = False
    compiled_at: str | None = None
    latest_compile_status: str | None = None  # compiled | discarded | skipped
    changed_since_extraction: bool = False
    is_thin_content: bool = False
    compiled_kp_count: int = 0


class CompiledKpSummary(BaseModel):
    product_id: str
    product_key: str
    product_name: str
    compiled_page_count: int


class PageKpStatus(BaseModel):
    page_id: str
    status: str  # "compiled" | "not_relevant" | "none"


class BatchQueueCurationRequest(BaseModel):
    page_ids: list[uuid.UUID]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


async def _successful_crawl_count(session, source_id: uuid.UUID) -> int:
    row = await session.execute(
        select(func.count()).where(
            WebSourceHistoryModel.source_id == source_id,
            # NULL = pre-migration crawl (treated as SUCCESSFUL); explicit SUCCESSFUL = success
            (WebSourceHistoryModel.crawl_status == "SUCCESSFUL") | WebSourceHistoryModel.crawl_status.is_(None),
        )
    )
    return row.scalar() or 0


def _source_to_response(source: WebSourceModel, page_count: int, successful_count: int) -> WebSourceResponse:
    return WebSourceResponse(
        id=str(source.id),
        name=source.name,
        root_url=source.root_url,
        crawl_depth=source.crawl_depth,
        include_query_strings=source.include_query_strings,
        last_crawled_at=source.last_crawled_at.isoformat() if source.last_crawled_at else None,
        page_count=page_count,
        last_crawl_created=source.last_crawl_created,
        last_crawl_updated=source.last_crawl_updated,
        last_crawl_skipped=source.last_crawl_skipped,
        crawl_status=source.crawl_status,
        successful_crawl_count=successful_count,
    )


class _RobotsCache:
    """robots.txt rules fetched once per host for the lifetime of one crawl."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self._parsers: dict[str, RobotFileParser] = {}

    async def allowed(self, url: str) -> bool:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        parser = self._parsers.get(origin)
        if parser is None:
            parser = RobotFileParser()
            try:
                resp = await self._client.get(f"{origin}/robots.txt")
                if resp.status_code == 200:
                    parser.parse(resp.text.splitlines())
                elif resp.status_code >= 500:
                    logger.warning("robots.txt for %s returned HTTP %s; allowing all", origin, resp.status_code)
                    parser.allow_all = True
                else:
                    parser.allow_all = True
            except httpx.HTTPError as exc:
                logger.warning("robots.txt fetch failed for %s: %s; allowing all", origin, exc)
                parser.allow_all = True
            self._parsers[origin] = parser
        return parser.can_fetch(CRAWLER_USER_AGENT, url)


async def _fetch_rendered(browser: Browser, url: str) -> tuple[int, str, str]:
    """Fetch a URL using a Playwright browser page, returning (status, content_type, html).
    Waits for networkidle so JS-rendered content is fully loaded.
    Falls back to domcontentloaded if networkidle times out."""
    page = await browser.new_page()
    try:
        try:
            response = await page.goto(url, wait_until="networkidle", timeout=30000)
        except Exception:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        if response is None:
            return 0, "", ""
        html = await page.content()
        content_type = response.headers.get("content-type", "")
        return response.status, content_type, html
    finally:
        await page.close()


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("", response_model=WebSourceResponse)
async def create_web_source(
    payload: CreateWebSourceRequest,
    session: SessionDep,
    _current_user: Annotated[CurrentUser, Depends(_OWNER_OR_ADMIN)],
) -> WebSourceResponse:
    row = WebSourceModel(
        name=payload.name,
        root_url=payload.root_url.rstrip("/"),
        crawl_depth=payload.crawl_depth,
        include_query_strings=payload.include_query_strings,
    )
    session.add(row)
    await session.flush()
    await session.commit()
    await session.refresh(row)
    return _source_to_response(row, 0, 0)


@router.get("", response_model=list[WebSourceResponse])
async def list_web_sources(
    session: SessionDep,
    _current_user: Annotated[CurrentUser, Depends(_ANY_ROLE)],
) -> list[WebSourceResponse]:
    rows = (await session.execute(select(WebSourceModel).order_by(WebSourceModel.created_at))).scalars().all()
    result = []
    for s in rows:
        page_count = (await session.execute(
            select(func.count()).where(WebPageModel.source_id == s.id)
        )).scalar() or 0
        successful_count = await _successful_crawl_count(session, s.id)
        result.append(_source_to_response(s, page_count, successful_count))
    return result


@router.delete("/{source_id}", status_code=204)
async def delete_web_source(
    source_id: uuid.UUID,
    session: SessionDep,
    _current_user: Annotated[CurrentUser, Depends(_OWNER_OR_ADMIN)],
) -> None:
    row = await session.get(WebSourceModel, source_id)
    if not row:
        raise HTTPException(status_code=404, detail="Web source not found")
    await session.delete(row)
    await session.commit()


@router.get("/{source_id}/pages", response_model=list[WebPageResponse])
async def list_web_pages(
    source_id: uuid.UUID,
    session: SessionDep,
    _current_user: Annotated[CurrentUser, Depends(_ANY_ROLE)],
) -> list[WebPageResponse]:
    rows = (
        await session.execute(
            select(WebPageModel)
            .where(WebPageModel.source_id == source_id)
            .order_by(WebPageModel.fetched_at.desc())
        )
    ).scalars().all()

    # Fetch latest curation run per page in one query
    from app.infrastructure.db.models import PageCurationSession as PageCurationSessionModel
    page_ids = [p.id for p in rows]
    run_map: dict[uuid.UUID, CurationRunModel] = {}
    if page_ids:
        run_rows = (
            await session.execute(
                select(CurationRunModel)
                .join(PageCurationSessionModel, PageCurationSessionModel.id == CurationRunModel.session_id)
                .where(CurationRunModel.page_id.in_(page_ids),
                       CurationRunModel.page_source_type == PageSourceType.WEB.value)
                .order_by(PageCurationSessionModel.started_at.desc())
            )
        ).scalars().all()
        for r in run_rows:
            if r.page_id not in run_map:
                run_map[r.page_id] = r

    # Fetch latest compile entry per page (any status) to derive is_compiled and latest_compile_status
    from app.infrastructure.db.models import KpCompileSessionEntry as CompileSessionEntry, KpCompileSession as KpCompileSessionModel
    # page_id → (status, compiled_at ISO | None)
    compile_map: dict[uuid.UUID, tuple[str, str | None]] = {}
    if page_ids:
        compile_rows = (await session.execute(
            select(
                CurationRunModel.page_id,
                CompileSessionEntry.status,
                CompileSessionEntry.compiled_at,
            )
            .join(CompileSessionEntry, CompileSessionEntry.curation_entry_id == CurationRunModel.id)
            .where(
                CurationRunModel.page_id.in_(page_ids),
                CurationRunModel.page_source_type == PageSourceType.WEB.value,
            )
            .order_by(CompileSessionEntry.created_at.desc())
        )).all()
        for r in compile_rows:
            if r.page_id not in compile_map:
                compile_map[r.page_id] = (
                    r.status,
                    r.compiled_at.isoformat() if r.compiled_at else None,
                )

    # Fetch compiled_kp_count per page: count distinct KPs where this page has a "compiled" entry
    compiled_kp_counts: dict[uuid.UUID, int] = {}
    if page_ids:
        kp_counts_result = await session.execute(
            select(
                CurationRunModel.page_id,
                func.count(func.distinct(KpCompileSessionModel.knowledge_product_id)).label("kp_count"),
            )
            .join(CompileSessionEntry, CompileSessionEntry.curation_entry_id == CurationRunModel.id)
            .join(KpCompileSessionModel, KpCompileSessionModel.id == CompileSessionEntry.session_id)
            .where(
                CurationRunModel.page_id.in_(page_ids),
                CurationRunModel.page_source_type == PageSourceType.WEB.value,
                CompileSessionEntry.status == "compiled",
                KpCompileSessionModel.knowledge_product_id.isnot(None),
            )
            .group_by(CurationRunModel.page_id)
        )
        compiled_kp_counts = {row.page_id: row.kp_count for row in kp_counts_result}

    return [
        WebPageResponse(
            id=str(p.id),
            source_id=str(p.source_id),
            url=p.url,
            title=p.title,
            content_hash=p.content_hash,
            fetched_at=p.fetched_at.isoformat(),
            latest_run_id=str(run_map[p.id].id) if p.id in run_map else None,
            latest_run_status=run_map[p.id].status if p.id in run_map else None,
            latest_run_error=run_map[p.id].error_message if p.id in run_map else None,
            page_tags=(run_map[p.id].structured_draft or {}).get("page_tags", []) if p.id in run_map else [],
            is_compiled=compile_map.get(p.id, ("", None))[0] == "compiled",
            compiled_at=compile_map.get(p.id, ("", None))[1] if compile_map.get(p.id, ("", None))[0] == "compiled" else None,
            latest_compile_status=compile_map.get(p.id, (None, None))[0],
            changed_since_extraction=p.changed_since_extraction,
            is_thin_content=p.is_thin_content,
            compiled_kp_count=compiled_kp_counts.get(p.id, 0),
        )
        for p in rows
    ]


@router.get("/{source_id}/compiled-kps")
async def list_compiled_kps(
    source_id: uuid.UUID,
    session: SessionDep,
    _current_user: Annotated[CurrentUser, Depends(_ANY_ROLE)],
) -> list[CompiledKpSummary]:
    """Return one row per KP that has at least one 'compiled' entry whose page belongs to this source."""
    from app.infrastructure.db.models import (
        KpCompileSession as KpCompileSessionModel,
        KpCompileSessionEntry as KpCompileSessionEntryModel,
        PageCurationSessionEntry as CurationEntryModel,
        KnowledgeProductModel as KPModel,
        KnowledgeProductVersionModel as KPVersionModel,
    )
    # Primary path: pages compiled via batch-compile-stream or fixed single-page compile
    rows = (await session.execute(
        select(
            KPModel.id,
            KPModel.product_key,
            KpCompileSessionModel.product_name,
            func.count(func.distinct(CurationEntryModel.page_id)).label("page_count"),
        )
        .join(KpCompileSessionModel, KpCompileSessionModel.knowledge_product_id == KPModel.id)
        .join(KpCompileSessionEntryModel, KpCompileSessionEntryModel.session_id == KpCompileSessionModel.id)
        .join(CurationEntryModel, CurationEntryModel.id == KpCompileSessionEntryModel.curation_entry_id)
        .join(WebPageModel, WebPageModel.id == CurationEntryModel.page_id)
        .where(
            WebPageModel.source_id == source_id,
            KpCompileSessionEntryModel.status == "compiled",
            KpCompileSessionModel.knowledge_product_id.isnot(None),
        )
        .group_by(KPModel.id, KPModel.product_key, KpCompileSessionModel.product_name)
        .order_by(KpCompileSessionModel.product_name)
    )).all()

    seen_kp_ids: set[uuid.UUID] = {r.id for r in rows}
    result: list[CompiledKpSummary] = [
        CompiledKpSummary(
            product_id=str(r.id),
            product_key=r.product_key,
            product_name=r.product_name or r.product_key,
            compiled_page_count=r.page_count,
        )
        for r in rows
    ]

    # Fallback path: KPs compiled via the old single-page path (before this fix) that never
    # created kp_compile_session rows — link via knowledge_product_version.source_extraction_entry_id
    backfill_rows = (await session.execute(
        select(
            KPModel.id,
            KPModel.product_key,
            KPModel.name.label("product_name"),
            func.count(func.distinct(CurationEntryModel.page_id)).label("page_count"),
        )
        .join(KPVersionModel, KPVersionModel.product_id == KPModel.id)
        .join(CurationEntryModel, CurationEntryModel.id == KPVersionModel.source_extraction_entry_id)
        .join(WebPageModel, WebPageModel.id == CurationEntryModel.page_id)
        .where(
            WebPageModel.source_id == source_id,
            KPVersionModel.source_extraction_entry_id.isnot(None),
        )
        .group_by(KPModel.id, KPModel.product_key, KPModel.name)
    )).all()

    for r in backfill_rows:
        if r.id not in seen_kp_ids:
            seen_kp_ids.add(r.id)
            result.append(CompiledKpSummary(
                product_id=str(r.id),
                product_key=r.product_key,
                product_name=r.product_name or r.product_key,
                compiled_page_count=r.page_count,
            ))

    return sorted(result, key=lambda x: x.product_name)


@router.get("/{source_id}/pages/kp-status")
async def get_pages_kp_status(
    source_id: uuid.UUID,
    product_id: uuid.UUID,
    session: SessionDep,
    _current_user: Annotated[CurrentUser, Depends(_ANY_ROLE)],
) -> list[PageKpStatus]:
    """Return KP compilation status for every page in the source, relative to a specific KP."""
    from app.infrastructure.db.models import (
        KpCompileSession as KpCompileSessionModel,
        KpCompileSessionEntry as KpCompileSessionEntryModel,
        PageCurationSessionEntry as CurationEntryModel,
    )
    # All pages for the source
    all_page_ids = (await session.execute(
        select(WebPageModel.id).where(WebPageModel.source_id == source_id)
    )).scalars().all()

    # Pages with a status entry for this KP
    status_rows = (await session.execute(
        select(CurationEntryModel.page_id, KpCompileSessionEntryModel.status)
        .join(KpCompileSessionEntryModel, KpCompileSessionEntryModel.curation_entry_id == CurationEntryModel.id)
        .join(KpCompileSessionModel, KpCompileSessionModel.id == KpCompileSessionEntryModel.session_id)
        .where(
            CurationEntryModel.page_id.in_(all_page_ids),
            KpCompileSessionModel.knowledge_product_id == product_id,
            KpCompileSessionEntryModel.status.in_(["compiled", "not_relevant"]),
        )
        .order_by(KpCompileSessionModel.started_at.desc())
    )).all()

    # Take the latest status per page
    page_status: dict[uuid.UUID, str] = {}
    for row in status_rows:
        if row.page_id not in page_status:
            page_status[row.page_id] = row.status

    # Fallback: pages compiled via old single-page path (no kp_compile_session row)
    from app.infrastructure.db.models import KnowledgeProductVersionModel as KPVersionModel
    backfill_page_ids = (await session.execute(
        select(CurationEntryModel.page_id)
        .join(KPVersionModel, KPVersionModel.source_extraction_entry_id == CurationEntryModel.id)
        .where(
            CurationEntryModel.page_id.in_(all_page_ids),
            KPVersionModel.product_id == product_id,
        )
    )).scalars().all()
    for pid in backfill_page_ids:
        if pid not in page_status:
            page_status[pid] = "compiled"

    return [
        PageKpStatus(
            page_id=str(pid),
            status=page_status.get(pid, "none"),
        )
        for pid in all_page_ids
    ]


@router.post("/{source_id}/crawl")
async def crawl_web_source(
    source_id: uuid.UUID,
    session: SessionDep,
    _current_user: Annotated[CurrentUser, Depends(_OWNER_OR_ADMIN)],
) -> StreamingResponse:
    source = await session.get(WebSourceModel, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Web source not found")

    if source.crawl_status == "PENDING":
        raise HTTPException(status_code=409, detail="A crawl is already running for this source.")

    # Mark PENDING and create an in-progress history placeholder in the same transaction
    source.crawl_status = "PENDING"
    from app.infrastructure.db.models import WebSourceHistory
    history_row = WebSourceHistory(
        source_id=source.id,
        name=source.name,
        root_url=source.root_url,
        crawl_depth=source.crawl_depth,
        last_crawled_at=None,
        last_crawl_created=None,
        last_crawl_updated=None,
        last_crawl_skipped=None,
        crawl_status=None,  # NULL = in-progress; updated to SUCCESSFUL/FAILED at the end
    )
    session.add(history_row)
    await session.flush()
    await session.commit()

    # Re-fetch source to get a clean state (session was committed)
    source = await session.get(WebSourceModel, source_id)
    history_id = history_row.id

    async def generate():
        created = updated = skipped = 0
        final_status = "FAILED"
        try:
            keep_query = source.include_query_strings
            visited: set[str] = set()
            root_url = normalize_url(source.root_url, keep_query=keep_query) or source.root_url.rstrip("/")
            # Crawl scope is the root's registrable domain (all its subdomains), not the current page's.
            scope = url_site_key(root_url)
            max_depth: int | None = source.crawl_depth
            # Queue entries are (url, depth). Depth 0 = root page. URLs are always normalised.
            queue: deque[tuple[str, int]] = deque([(root_url, 0)])
            queued: set[str] = {root_url}

            async with httpx.AsyncClient(follow_redirects=True, timeout=15, headers=_CRAWL_HEADERS) as robots_client:
                robots = _RobotsCache(robots_client)
                async with async_playwright() as pw:
                    browser = await pw.chromium.launch(headless=True)
                    try:
                        while queue:
                            url, depth = queue.popleft()
                            queued.discard(url)
                            if url in visited:
                                continue
                            visited.add(url)
                            if has_skipped_extension(url):
                                continue
                            if not await robots.allowed(url):
                                yield _sse({"type": "page_skipped", "url": url, "reason": "robots.txt"})
                                skipped += 1
                                continue

                            yield _sse({"type": "crawling", "url": url, "queued": len(queue), "visited": len(visited)})

                            try:
                                status, ct, html = await _fetch_rendered(browser, url)
                            except Exception as e:
                                yield _sse({"type": "page_error", "url": url, "error": str(e)})
                                skipped += 1
                                continue

                            final_url = normalize_url(url, keep_query=keep_query) or url
                            if url_site_key(final_url) != scope:
                                yield _sse({"type": "page_skipped", "url": url, "reason": "redirected off-site"})
                                skipped += 1
                                continue
                            if status != 200:
                                yield _sse({"type": "page_skipped", "url": url, "reason": f"HTTP {status}"})
                                skipped += 1
                                continue
                            if "text/html" not in ct:
                                skipped += 1
                                continue
                            if final_url != url:
                                if final_url in visited:
                                    continue
                                visited.add(final_url)
                                url = final_url

                            content_hash = hashlib.sha256(html.encode()).hexdigest()
                            parsed = parse_page(html, url, keep_query=keep_query)
                            title, plain_text = parsed.title, parsed.plain_text

                            # Upsert web_page row
                            existing = (
                                await session.execute(
                                    select(WebPageModel).where(
                                        WebPageModel.source_id == source_id,
                                        WebPageModel.url == url,
                                    )
                                )
                            ).scalar_one_or_none()

                            if existing:
                                if existing.content_hash == content_hash:
                                    existing.is_thin_content = parsed.is_thin_content
                                    skipped += 1
                                    yield _sse({"type": "page_unchanged", "url": url, "page_id": str(existing.id)})
                                else:
                                    # Snapshot current row before overwriting
                                    session.add(WebPageHistoryModel(
                                        page_id=existing.id,
                                        source_id=existing.source_id,
                                        url=existing.url,
                                        title=existing.title,
                                        plain_text=existing.plain_text,
                                        content_hash=existing.content_hash,
                                        fetched_at=existing.fetched_at,
                                    ))
                                    existing.title = title
                                    existing.plain_text = plain_text
                                    existing.content_hash = content_hash
                                    existing.fetched_at = utc_now()
                                    existing.changed_since_extraction = True
                                    existing.is_thin_content = parsed.is_thin_content
                                    existing.js_rendered = True
                                    await session.flush()
                                    updated += 1
                                    yield _sse({
                                        "type": "page_updated", "url": url, "page_id": str(existing.id), "title": title,
                                        "thin_content": parsed.is_thin_content,
                                    })
                            else:
                                page = WebPageModel(
                                    source_id=source_id,
                                    url=url,
                                    title=title,
                                    plain_text=plain_text,
                                    content_hash=content_hash,
                                    is_thin_content=parsed.is_thin_content,
                                    js_rendered=True,
                                )
                                session.add(page)
                                await session.flush()
                                created += 1
                                yield _sse({
                                    "type": "page_found", "url": url, "page_id": str(page.id), "title": title,
                                    "thin_content": parsed.is_thin_content,
                                })

                            # Save all discovered links for this page
                            page_obj_id = existing.id if existing else page.id
                            all_links = parsed.links
                            if all_links:
                                # Only resolve linked_page_id to pages belonging to this source —
                                # no cross-source leakage even if the same URL exists elsewhere.
                                crawled_map: dict[str, uuid.UUID] = {}
                                crawled_rows = (await session.execute(
                                    select(WebPageModel.url, WebPageModel.id)
                                    .where(WebPageModel.source_id == source_id, WebPageModel.url.in_(all_links))
                                )).all()
                                for r in crawled_rows:
                                    crawled_map[r.url] = r.id
                                # Replace links for this page
                                await session.execute(delete(WebPageLinkModel).where(WebPageLinkModel.source_page_id == page_obj_id))
                                for href in all_links:
                                    session.add(WebPageLinkModel(
                                        source_page_id=page_obj_id,
                                        url=href,
                                        linked_page_id=crawled_map.get(href),
                                    ))
                                await session.flush()

                            # Enqueue same-origin links if within allowed depth.
                            if max_depth is None or depth < max_depth:
                                for link in parsed.follow_links:
                                    if link not in visited and link not in queued:
                                        queue.append((link, depth + 1))
                                        queued.add(link)
                    finally:
                        try:
                            await browser.close()
                        except Exception:
                            pass

            # Reconcile linked_page_id: for every link under this source whose target URL
            # has now been crawled (exists as a web_page under the same source), set the FK.
            unresolved_links = (await session.execute(
                select(WebPageLinkModel)
                .join(WebPageModel, WebPageModel.id == WebPageLinkModel.source_page_id)
                .where(
                    WebPageModel.source_id == source_id,
                    WebPageLinkModel.linked_page_id.is_(None),
                )
            )).scalars().all()
            if unresolved_links:
                unresolved_urls = list({lnk.url for lnk in unresolved_links})
                resolved_rows = (await session.execute(
                    select(WebPageModel.url, WebPageModel.id)
                    .where(WebPageModel.source_id == source_id, WebPageModel.url.in_(unresolved_urls))
                )).all()
                url_to_page_id = {r.url: r.id for r in resolved_rows}
                for lnk in unresolved_links:
                    if lnk.url in url_to_page_id:
                        lnk.linked_page_id = url_to_page_id[lnk.url]
                await session.flush()

            final_status = "SUCCESSFUL"

        except Exception as exc:
            logger.exception("Crawl failed for source %s", source_id)
            yield _sse({"type": "error", "detail": str(exc)})
            final_status = "FAILED"

        finally:
            # Always write final status back regardless of success or failure
            src = await session.get(WebSourceModel, source_id)
            if src:
                # Update or create the previous-crawl history snapshot
                if src.last_crawled_at is not None and final_status == "SUCCESSFUL":
                    # The in-progress placeholder row was already created above;
                    # update it with the final outcome and stats
                    pass

                # Update the in-progress history row created at start
                hist = await session.get(WebSourceHistoryModel, history_id)
                if hist:
                    hist.crawl_status = final_status
                    hist.last_crawled_at = utc_now()
                    hist.last_crawl_created = created
                    hist.last_crawl_updated = updated
                    hist.last_crawl_skipped = skipped

                src.crawl_status = final_status
                src.last_crawled_at = utc_now()
                src.last_crawl_created = created
                src.last_crawl_updated = updated
                src.last_crawl_skipped = skipped
                await session.flush()
                await session.commit()

        if final_status == "SUCCESSFUL":
            yield _sse({"type": "done", "created": created, "updated": updated, "skipped": skipped})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class WebPageLinkResponse(BaseModel):
    url: str
    title: str | None
    linked_page_id: str | None
    # populated when linked_page_id is set
    linked_page_title: str | None = None
    linked_page_run_status: str | None = None  # succeeded | failed | running | None
    linked_page_run_id: str | None = None
    linked_page_is_compiled: bool = False
    linked_page_compiled_at: str | None = None


@router.get("/{source_id}/pages/{page_id}/links", response_model=list[WebPageLinkResponse])
async def list_page_links(
    source_id: uuid.UUID,
    page_id: uuid.UUID,
    session: SessionDep,
    _current_user: Annotated[CurrentUser, Depends(_ANY_ROLE)],
) -> list[WebPageLinkResponse]:
    # Fetch all discovered links for this page
    link_rows = (
        await session.execute(
            select(WebPageLinkModel).where(WebPageLinkModel.source_page_id == page_id)
            .order_by(WebPageLinkModel.url)
        )
    ).scalars().all()

    # For linked pages, fetch their title and latest curation status
    linked_ids = [lnk.linked_page_id for lnk in link_rows if lnk.linked_page_id]
    page_info: dict[uuid.UUID, tuple[str, str | None]] = {}  # id → (title, run_status)
    if linked_ids:
        page_rows = (await session.execute(
            select(WebPageModel.id, WebPageModel.title).where(WebPageModel.id.in_(linked_ids))
        )).all()
        page_info = {r.id: (r.title, None) for r in page_rows}
        # Latest curation run per linked page
        from app.infrastructure.db.models import PageCurationSession as PageCurationSessionModel
        run_rows = (await session.execute(
            select(CurationRunModel.page_id, CurationRunModel.id, CurationRunModel.status)
            .join(PageCurationSessionModel, PageCurationSessionModel.id == CurationRunModel.session_id)
            .where(CurationRunModel.page_id.in_(linked_ids),
                   CurationRunModel.page_source_type == PageSourceType.WEB.value)
            .order_by(PageCurationSessionModel.started_at.desc())
        )).all()
        seen_runs: set[uuid.UUID] = set()
        run_info: dict[uuid.UUID, tuple[str, uuid.UUID]] = {}  # page_id → (status, run_id)
        for r in run_rows:
            if r.page_id not in seen_runs:
                seen_runs.add(r.page_id)
                title = page_info.get(r.page_id, ("", None))[0]
                page_info[r.page_id] = (title, r.status)
                run_info[r.page_id] = (r.status, r.id)

        # Compile status per linked page
        from app.infrastructure.db.models import KpCompileSessionEntry as CompileSessionEntry
        compile_map: dict[uuid.UUID, str] = {}  # page_id → compiled_at ISO
        compile_rows = (await session.execute(
            select(
                CurationRunModel.page_id,
                func.max(CompileSessionEntry.compiled_at).label("compiled_at"),
            )
            .join(CompileSessionEntry, CompileSessionEntry.curation_entry_id == CurationRunModel.id)
            .where(
                CurationRunModel.page_id.in_(linked_ids),
                CurationRunModel.page_source_type == PageSourceType.WEB.value,
                CompileSessionEntry.status == "compiled",
            )
            .group_by(CurationRunModel.page_id)
        )).all()
        for r in compile_rows:
            compile_map[r.page_id] = r.compiled_at.isoformat() if r.compiled_at else ""

    return [
        WebPageLinkResponse(
            url=lnk.url,
            title=lnk.title,
            linked_page_id=str(lnk.linked_page_id) if lnk.linked_page_id else None,
            linked_page_title=page_info[lnk.linked_page_id][0] if lnk.linked_page_id and lnk.linked_page_id in page_info else None,
            linked_page_run_status=page_info[lnk.linked_page_id][1] if lnk.linked_page_id and lnk.linked_page_id in page_info else None,
            linked_page_run_id=str(run_info[lnk.linked_page_id][1]) if lnk.linked_page_id and lnk.linked_page_id in run_info else None,
            linked_page_is_compiled=lnk.linked_page_id in compile_map if lnk.linked_page_id else False,
            linked_page_compiled_at=compile_map.get(lnk.linked_page_id) if lnk.linked_page_id else None,
        )
        for lnk in link_rows
    ]


class LinkTreeNode(BaseModel):
    page_id: str | None
    url: str
    title: str | None
    depth: int
    run_status: str | None = None
    is_compiled: bool = False
    children: list["LinkTreeNode"] = []

LinkTreeNode.model_rebuild()


class LinkTreeResponse(BaseModel):
    page_id: str
    url: str
    title: str
    run_status: str | None
    is_compiled: bool
    parents: list[LinkTreeNode]
    children: list[LinkTreeNode]


async def _page_status(
    session,
    page_ids: list[uuid.UUID],
) -> tuple[dict[uuid.UUID, str | None], dict[uuid.UUID, bool]]:
    """Return (run_status_map, is_compiled_map) for a list of page ids."""
    from app.infrastructure.db.models import KpCompileSessionEntry as CompileSessionEntry
    run_status: dict[uuid.UUID, str | None] = {}
    if page_ids:
        run_rows = (await session.execute(
            text("""
                SELECT DISTINCT ON (ese.page_id)
                    ese.page_id,
                    ese.status
                FROM page_curation_session_entry ese
                JOIN page_curation_session es ON es.id = ese.session_id
                WHERE ese.page_id = ANY(:page_ids)
                  AND ese.page_source_type = 'web'
                ORDER BY ese.page_id, es.started_at DESC
            """),
            {"page_ids": [str(p) for p in page_ids]},
        )).all()
        for r in run_rows:
            run_status[uuid.UUID(str(r.page_id))] = r.status

    compiled: dict[uuid.UUID, bool] = {}
    if page_ids:
        compile_rows = (await session.execute(
            select(CurationRunModel.page_id)
            .join(CompileSessionEntry, CompileSessionEntry.curation_entry_id == CurationRunModel.id)
            .where(
                CurationRunModel.page_id.in_(page_ids),
                CurationRunModel.page_source_type == PageSourceType.WEB.value,
                CompileSessionEntry.status == "compiled",
            )
            .group_by(CurationRunModel.page_id)
        )).all()
        for r in compile_rows:
            compiled[r.page_id] = True

    return run_status, compiled


@router.get("/{source_id}/pages/{page_id}/links/tree", response_model=LinkTreeResponse)
async def get_page_link_tree(
    source_id: uuid.UUID,
    page_id: uuid.UUID,
    session: SessionDep,
    _current_user: Annotated[CurrentUser, Depends(_ANY_ROLE)],
) -> LinkTreeResponse:
    """Return direct parents and children (depth 1) for a page.
    The UI lazy-loads deeper levels by calling this endpoint per expanded node."""
    root = await session.get(WebPageModel, page_id)
    if not root or root.source_id != source_id:
        raise HTTPException(status_code=404, detail="Page not found")

    # Direct children: pages this page links to
    child_rows = (await session.execute(
        select(WebPageLinkModel.url, WebPageLinkModel.linked_page_id, WebPageModel.title)
        .outerjoin(WebPageModel, WebPageModel.id == WebPageLinkModel.linked_page_id)
        .where(
            WebPageLinkModel.source_page_id == page_id,
            WebPageLinkModel.linked_page_id != page_id,
        )
        .order_by(WebPageModel.title)
    )).all()

    # Direct parents: pages that link to this page (within same source)
    parent_rows = (await session.execute(
        select(WebPageModel.id, WebPageModel.url, WebPageModel.title)
        .join(WebPageLinkModel, WebPageLinkModel.source_page_id == WebPageModel.id)
        .where(
            WebPageLinkModel.linked_page_id == page_id,
            WebPageLinkModel.source_page_id != page_id,
            WebPageModel.source_id == source_id,
        )
        .order_by(WebPageModel.title)
    )).all()

    # Collect all page_ids for status lookup
    all_ids: list[uuid.UUID] = []
    for r in child_rows:
        if r.linked_page_id:
            all_ids.append(r.linked_page_id)
    for r in parent_rows:
        all_ids.append(r.id)
    all_ids.append(page_id)

    run_status_map, compiled_map = await _page_status(session, list(set(all_ids)))

    def _node(pid, url, title, depth) -> LinkTreeNode:
        return LinkTreeNode(
            page_id=str(pid) if pid else None,
            url=url,
            title=title,
            depth=depth,
            run_status=run_status_map.get(pid) if pid else None,
            is_compiled=compiled_map.get(pid, False) if pid else False,
            children=[],
        )

    root_children = [_node(r.linked_page_id, r.url, r.title, 1) for r in child_rows]
    root_parents = [_node(r.id, r.url, r.title, 1) for r in parent_rows]

    return LinkTreeResponse(
        page_id=str(page_id),
        url=root.url,
        title=root.title,
        run_status=run_status_map.get(page_id),
        is_compiled=compiled_map.get(page_id, False),
        parents=root_parents,
        children=root_children,
    )


@router.post("/{source_id}/pages/{page_id}/curate")
async def curate_web_page(
    source_id: uuid.UUID,
    page_id: uuid.UUID,
    session: SessionDep,
    _current_user: Annotated[CurrentUser, Depends(_OWNER_OR_ADMIN)],
) -> dict:
    page = await session.get(WebPageModel, page_id)
    if not page or page.source_id != source_id:
        raise HTTPException(status_code=404, detail="Web page not found")

    source = await session.get(WebSourceModel, source_id)
    if source and source.crawl_status == "PENDING":
        raise HTTPException(status_code=409, detail="Cannot curate while a crawl is running for this source.")

    curation_repo = SqlAlchemyCurationRunRepository(session)
    llm_port = get_llm_curation_port()
    llm_provider = settings.llm_provider
    llm_model = settings.anthropic_model if llm_provider == "anthropic" else settings.openai_model

    run = CurationRun(
        page_id=page_id,
        page_source_type=PageSourceType.WEB,
        llm_provider=llm_provider,
        llm_model=llm_model,
        status=CurationStatus.RUNNING,
        started_at=utc_now(),
    )
    run = await curation_repo.save(run)

    try:
        result = await llm_port.extract(page.plain_text, KNOWLEDGE_CURATION_SCHEMA, source_url=page.url)
        run.status = CurationStatus.SUCCEEDED
        run.structured_draft = {k: v for k, v in dataclasses.asdict(result).items() if k != "raw_model_output"}
        run.completed_at = utc_now()
    except Exception as exc:
        logger.exception("Web page curation failed for page %s", page_id)
        run.status = CurationStatus.FAILED
        run.error_message = str(exc)
        run.completed_at = utc_now()

    run = await curation_repo.save(run)

    if run.status == CurationStatus.SUCCEEDED:
        page.changed_since_extraction = False
        await session.commit()

    return {
        "run_id": str(run.id),
        "status": run.status.value,
        "error_message": run.error_message,
    }


@router.post("/{source_id}/pages/batch-queue-curation")
async def batch_queue_curation(
    source_id: uuid.UUID,
    payload: BatchQueueCurationRequest,
    session: SessionDep,
    _current_user: Annotated[CurrentUser, Depends(_OWNER_OR_ADMIN)],
) -> dict:
    """Enqueue linked pages for background curation.
    Creates a curation session + pending entries in one transaction.
    Skips pages that already have a pending entry."""
    if not payload.page_ids:
        raise HTTPException(status_code=422, detail="page_ids must not be empty")

    source = await session.get(WebSourceModel, source_id)
    if not source:
        raise HTTPException(status_code=404, detail="Web source not found")
    if source.crawl_status == "PENDING":
        raise HTTPException(status_code=409, detail="Cannot queue curation while a crawl is running for this source.")

    # Find pages that already have a pending curation entry (deduplication)
    already_pending = set(
        (await session.execute(
            select(CurationRunModel.page_id)
            .where(
                CurationRunModel.page_id.in_(payload.page_ids),
                CurationRunModel.status == "pending",
                CurationRunModel.page_source_type == PageSourceType.WEB.value,
            )
        )).scalars().all()
    )

    to_enqueue = [pid for pid in payload.page_ids if pid not in already_pending]
    if not to_enqueue:
        return {"queued": 0, "skipped_duplicates": len(payload.page_ids)}

    llm_provider = settings.llm_provider
    llm_model = settings.anthropic_model if llm_provider == "anthropic" else settings.openai_model

    curation_session = CurationSessionModel(
        llm_provider=llm_provider,
        llm_model=llm_model,
        status="pending",
    )
    session.add(curation_session)
    await session.flush()

    for pid in to_enqueue:
        entry = CurationRunModel(
            session_id=curation_session.id,
            page_id=pid,
            page_source_type=PageSourceType.WEB.value,
            status="pending",
        )
        session.add(entry)

    await session.flush()
    await session.commit()

    return {
        "queued": len(to_enqueue),
        "skipped_duplicates": len(already_pending),
        "session_id": str(curation_session.id),
    }


