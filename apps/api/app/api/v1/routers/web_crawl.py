from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
import uuid
from collections import deque
from typing import Annotated
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update

from app.api.deps import SessionDep
from app.core.config import settings
from app.core.security import CurrentUser, require_roles
from app.domain.extraction.entities import ExtractionRun, ExtractionStatus, PageSourceType
from app.domain.extraction.schema import KNOWLEDGE_EXTRACTION_SCHEMA
from app.domain.governance.value_objects import Role
from app.domain.shared.base import utc_now
from app.infrastructure.db.extraction_repository import SqlAlchemyExtractionRunRepository
from app.infrastructure.db.models import ExtractionSessionEntry as ExtractionRunModel, WebPage as WebPageModel, WebPageLink as WebPageLinkModel, WebSource as WebSourceModel
from app.infrastructure.db.session import SessionLocal
from app.infrastructure.llm.factory import get_llm_extraction_port

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/web-sources", tags=["web-sources"])

_ANY_ROLE = require_roles(Role.KNOWLEDGE_OWNER, Role.ADMIN, Role.REVIEWER, Role.CONSUMER)
_OWNER_OR_ADMIN = require_roles(Role.KNOWLEDGE_OWNER, Role.ADMIN)


# ── Schemas ──────────────────────────────────────────────────────────────────

class CreateWebSourceRequest(BaseModel):
    name: str
    root_url: str
    crawl_depth: int | None = None  # None = unlimited; 1 = root page links only


class WebSourceResponse(BaseModel):
    id: str
    name: str
    root_url: str
    crawl_depth: int | None
    last_crawled_at: str | None
    page_count: int
    last_crawl_created: int | None
    last_crawl_updated: int | None
    last_crawl_skipped: int | None


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


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _extract_text(html: str) -> tuple[str, str]:
    """Return (title, plain_text) from raw HTML."""
    soup = BeautifulSoup(html, "lxml")
    # Remove nav/header/footer/script/style noise
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    title = ""
    if soup.title and soup.title.string:
        title = soup.title.string.strip()
    elif soup.find("h1"):
        title = soup.find("h1").get_text(" ", strip=True)
    plain_text = soup.get_text(" ", strip=True)
    return title or "Untitled", plain_text


def _same_origin_links(html: str, base_url: str) -> list[str]:
    """Extract all <a href> links on the same origin as base_url."""
    parsed_base = urlparse(base_url)
    origin = f"{parsed_base.scheme}://{parsed_base.netloc}"
    soup = BeautifulSoup(html, "lxml")
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        # Strip fragment and query
        clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
        if clean.startswith(origin) and clean not in links:
            links.append(clean)
    return links


def _all_http_links(html: str, base_url: str) -> list[str]:
    """Extract all http/https <a href> links from a page (any domain)."""
    soup = BeautifulSoup(html, "lxml")
    seen: set[str] = set()
    links: list[str] = []
    for a in soup.find_all("a", href=True):
        href: str = a["href"]
        full = urljoin(base_url, href)
        parsed = urlparse(full)
        if parsed.scheme not in ("http", "https"):
            continue
        clean = f"{parsed.scheme}://{parsed.netloc}{parsed.path}".rstrip("/")
        if clean and clean not in seen:
            seen.add(clean)
            links.append(clean)
    return links


# ── Background: crawl + extract linked pages ──────────────────────────────────

async def _crawl_and_extract_linked(source_id: uuid.UUID, page_id: uuid.UUID) -> None:
    """After a page is extracted, crawl any uncrawled linked pages and extract all unextracted linked pages."""
    print(f"[linked] starting for page_id={page_id}", flush=True)
    llm_port = get_llm_extraction_port()
    llm_provider = settings.llm_provider
    llm_model = settings.anthropic_model if llm_provider == "anthropic" else settings.openai_model

    async with SessionLocal() as session:
        source = await session.get(WebSourceModel, source_id)
        if not source:
            return

        # Fetch all link URLs discovered on this page
        link_rows = (await session.execute(
            select(WebPageLinkModel.url, WebPageLinkModel.linked_page_id)
            .where(WebPageLinkModel.source_page_id == page_id)
        )).all()

        print(f"[linked] page_id={page_id} has {len(link_rows)} links", flush=True)
        if not link_rows:
            return

        # Separate uncrawled links from already-crawled ones
        uncrawled_urls = list({r.url for r in link_rows if r.linked_page_id is None})
        linked_page_ids = [r.linked_page_id for r in link_rows if r.linked_page_id is not None]
        print(f"[linked] linked={len(linked_page_ids)} uncrawled={len(uncrawled_urls)}", flush=True)

        # Crawl uncrawled links and add them to the source
        newly_crawled_ids: list[uuid.UUID] = []
        if uncrawled_urls:
            async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
                for url in uncrawled_urls:
                    # Skip if already in web_page
                    existing = (await session.execute(
                        select(WebPageModel).where(WebPageModel.source_id == source_id, WebPageModel.url == url)
                    )).scalar_one_or_none()
                    if existing:
                        newly_crawled_ids.append(existing.id)
                        # Back-fill linked_page_id so the Links panel shows the correct status
                        await session.execute(
                            update(WebPageLinkModel)
                            .where(WebPageLinkModel.source_page_id == page_id, WebPageLinkModel.url == url)
                            .values(linked_page_id=existing.id)
                        )
                        print(f"[linked] already exists (back-filled): {url}", flush=True)
                        continue
                    try:
                        resp = await client.get(url)
                        ct = resp.headers.get("content-type", "")
                        print(f"[linked] fetched {url} status={resp.status_code} ct={ct}", flush=True)
                        if resp.status_code != 200 or "text/html" not in ct:
                            continue
                    except Exception as exc:
                        print(f"[linked] fetch error {url}: {exc}", flush=True)
                        continue
                    html = resp.text
                    content_hash = hashlib.sha256(html.encode()).hexdigest()
                    title, plain_text = _extract_text(html)
                    new_page = WebPageModel(
                        source_id=source_id, url=url, title=title,
                        plain_text=plain_text, content_hash=content_hash,
                    )
                    session.add(new_page)
                    await session.flush()
                    newly_crawled_ids.append(new_page.id)
                    await session.execute(
                        WebPageLinkModel.__table__.update()
                        .where(WebPageLinkModel.source_page_id == page_id, WebPageLinkModel.url == url)
                        .values(linked_page_id=new_page.id)
                    )
                    print(f"[linked] crawled new page: {url} title={title}", flush=True)
            await session.commit()

        # All pages to potentially extract: already-linked + newly crawled
        all_candidate_ids = linked_page_ids + newly_crawled_ids
        if not all_candidate_ids:
            return

        # Find which ones have no succeeded extraction run
        from app.infrastructure.db.models import ExtractionSession as ExtractionSessionModel
        run_rows = (await session.execute(
            select(ExtractionRunModel.page_id, ExtractionRunModel.status)
            .join(ExtractionSessionModel, ExtractionSessionModel.id == ExtractionRunModel.session_id)
            .where(ExtractionRunModel.page_id.in_(all_candidate_ids),
                   ExtractionRunModel.page_source_type == PageSourceType.WEB.value)
            .order_by(ExtractionSessionModel.started_at.desc())
        )).all()
        latest_status: dict[uuid.UUID, str] = {}
        for r in run_rows:
            if r.page_id not in latest_status:
                latest_status[r.page_id] = r.status

        to_extract = [pid for pid in all_candidate_ids if latest_status.get(pid) != "succeeded"]

        # Extract each page sequentially
        extraction_repo = SqlAlchemyExtractionRunRepository(session)
        for pid in to_extract:
            linked_page = await session.get(WebPageModel, pid)
            if not linked_page:
                continue
            run = ExtractionRun(
                page_id=pid,
                page_source_type=PageSourceType.WEB,
                llm_provider=llm_provider,
                llm_model=llm_model,
                status=ExtractionStatus.RUNNING,
                started_at=utc_now(),
            )
            run = await extraction_repo.save(run)
            try:
                result = await llm_port.extract(linked_page.plain_text, KNOWLEDGE_EXTRACTION_SCHEMA, source_url=linked_page.url)
                run.status = ExtractionStatus.SUCCEEDED
                run.structured_draft = {k: v for k, v in dataclasses.asdict(result).items() if k != "raw_model_output"}
                run.completed_at = utc_now()
                print(f"[linked] extracted: {linked_page.url}", flush=True)
            except Exception as exc:
                logger.exception("Linked-page extraction failed for %s", pid)
                run.status = ExtractionStatus.FAILED
                run.error_message = str(exc)
                run.completed_at = utc_now()
            await extraction_repo.save(run)
            await session.commit()


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
    )
    session.add(row)
    await session.flush()
    await session.commit()
    await session.refresh(row)
    return WebSourceResponse(
        id=str(row.id),
        name=row.name,
        root_url=row.root_url,
        crawl_depth=row.crawl_depth,
        last_crawled_at=row.last_crawled_at.isoformat() if row.last_crawled_at else None,
        page_count=0,
        last_crawl_created=None,
        last_crawl_updated=None,
        last_crawl_skipped=None,
    )


@router.get("", response_model=list[WebSourceResponse])
async def list_web_sources(
    session: SessionDep,
    _current_user: Annotated[CurrentUser, Depends(_ANY_ROLE)],
) -> list[WebSourceResponse]:
    rows = (await session.execute(select(WebSourceModel).order_by(WebSourceModel.created_at))).scalars().all()
    result = []
    for s in rows:
        page_count_row = await session.execute(
            select(func.count()).where(WebPageModel.source_id == s.id)
        )
        page_count = page_count_row.scalar() or 0
        result.append(WebSourceResponse(
            id=str(s.id),
            name=s.name,
            root_url=s.root_url,
            crawl_depth=s.crawl_depth,
            last_crawled_at=s.last_crawled_at.isoformat() if s.last_crawled_at else None,
            page_count=page_count,
            last_crawl_created=s.last_crawl_created,
            last_crawl_updated=s.last_crawl_updated,
            last_crawl_skipped=s.last_crawl_skipped,
        ))
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

    # Fetch latest extraction run per page in one query
    from app.infrastructure.db.models import ExtractionSession as ExtractionSessionModel
    page_ids = [p.id for p in rows]
    run_map: dict[uuid.UUID, ExtractionRunModel] = {}
    if page_ids:
        run_rows = (
            await session.execute(
                select(ExtractionRunModel)
                .join(ExtractionSessionModel, ExtractionSessionModel.id == ExtractionRunModel.session_id)
                .where(ExtractionRunModel.page_id.in_(page_ids),
                       ExtractionRunModel.page_source_type == PageSourceType.WEB.value)
                .order_by(ExtractionSessionModel.started_at.desc())
            )
        ).scalars().all()
        for r in run_rows:
            if r.page_id not in run_map:
                run_map[r.page_id] = r

    # Fetch compile status: latest compiled_at per page (any entry compiled into any session)
    from app.infrastructure.db.models import CompileSessionEntry
    compile_map: dict[uuid.UUID, str] = {}  # page_id → compiled_at ISO string
    if page_ids:
        compile_rows = (await session.execute(
            select(
                ExtractionRunModel.page_id,
                func.max(CompileSessionEntry.compiled_at).label("compiled_at"),
            )
            .join(CompileSessionEntry, CompileSessionEntry.entry_id == ExtractionRunModel.id)
            .where(
                ExtractionRunModel.page_id.in_(page_ids),
                ExtractionRunModel.page_source_type == PageSourceType.WEB.value,
                CompileSessionEntry.status == "compiled",
            )
            .group_by(ExtractionRunModel.page_id)
        )).all()
        for r in compile_rows:
            compile_map[r.page_id] = r.compiled_at.isoformat() if r.compiled_at else ""

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
            is_compiled=p.id in compile_map,
            compiled_at=compile_map.get(p.id),
        )
        for p in rows
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

    async def generate():
        created = updated = skipped = 0
        visited: set[str] = set()
        root_url = source.root_url.rstrip("/")
        max_depth: int | None = source.crawl_depth
        # Queue entries are (url, depth). Depth 0 = root page.
        queue: deque[tuple[str, int]] = deque([(root_url, 0)])
        parsed_base = urlparse(root_url)
        origin = f"{parsed_base.scheme}://{parsed_base.netloc}"

        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            while queue:
                url, depth = queue.popleft()
                if url in visited:
                    continue
                visited.add(url)

                yield _sse({"type": "crawling", "url": url, "queued": len(queue), "visited": len(visited)})

                try:
                    resp = await client.get(url)
                    if resp.status_code != 200:
                        yield _sse({"type": "page_skipped", "url": url, "reason": f"HTTP {resp.status_code}"})
                        skipped += 1
                        continue
                    content_type = resp.headers.get("content-type", "")
                    if "text/html" not in content_type:
                        skipped += 1
                        continue
                except Exception as e:
                    yield _sse({"type": "page_error", "url": url, "error": str(e)})
                    skipped += 1
                    continue

                html = resp.text
                content_hash = hashlib.sha256(html.encode()).hexdigest()
                title, plain_text = _extract_text(html)

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
                        skipped += 1
                        yield _sse({"type": "page_unchanged", "url": url, "page_id": str(existing.id)})
                    else:
                        existing.title = title
                        existing.plain_text = plain_text
                        existing.content_hash = content_hash
                        existing.fetched_at = utc_now()
                        await session.flush()
                        updated += 1
                        yield _sse({"type": "page_updated", "url": url, "page_id": str(existing.id), "title": title})
                else:
                    page = WebPageModel(
                        source_id=source_id,
                        url=url,
                        title=title,
                        plain_text=plain_text,
                        content_hash=content_hash,
                    )
                    session.add(page)
                    await session.flush()
                    created += 1
                    yield _sse({"type": "page_found", "url": url, "page_id": str(page.id), "title": title})

                # Save all discovered links for this page
                page_obj_id = existing.id if existing else page.id
                all_links = _all_http_links(html, url)
                if all_links:
                    # Resolve which links are already crawled (have a web_page row)
                    crawled_map: dict[str, uuid.UUID] = {}
                    crawled_rows = (await session.execute(
                        select(WebPageModel.url, WebPageModel.id).where(WebPageModel.url.in_(all_links))
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
                    queued_urls = {u for u, _ in queue}
                    for link in _same_origin_links(html, url):
                        if link not in visited and link not in queued_urls:
                            queue.append((link, depth + 1))

        # Update source stats
        source.last_crawled_at = utc_now()
        source.last_crawl_created = created
        source.last_crawl_updated = updated
        source.last_crawl_skipped = skipped
        await session.flush()
        await session.commit()
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

    # For linked pages, fetch their title and latest extraction status
    linked_ids = [lnk.linked_page_id for lnk in link_rows if lnk.linked_page_id]
    page_info: dict[uuid.UUID, tuple[str, str | None]] = {}  # id → (title, run_status)
    if linked_ids:
        page_rows = (await session.execute(
            select(WebPageModel.id, WebPageModel.title).where(WebPageModel.id.in_(linked_ids))
        )).all()
        page_info = {r.id: (r.title, None) for r in page_rows}
        # Latest extraction run per linked page
        from app.infrastructure.db.models import ExtractionSession as ExtractionSessionModel
        run_rows = (await session.execute(
            select(ExtractionRunModel.page_id, ExtractionRunModel.id, ExtractionRunModel.status)
            .join(ExtractionSessionModel, ExtractionSessionModel.id == ExtractionRunModel.session_id)
            .where(ExtractionRunModel.page_id.in_(linked_ids),
                   ExtractionRunModel.page_source_type == PageSourceType.WEB.value)
            .order_by(ExtractionSessionModel.started_at.desc())
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
        from app.infrastructure.db.models import CompileSessionEntry
        compile_map: dict[uuid.UUID, str] = {}  # page_id → compiled_at ISO
        compile_rows = (await session.execute(
            select(
                ExtractionRunModel.page_id,
                func.max(CompileSessionEntry.compiled_at).label("compiled_at"),
            )
            .join(CompileSessionEntry, CompileSessionEntry.entry_id == ExtractionRunModel.id)
            .where(
                ExtractionRunModel.page_id.in_(linked_ids),
                ExtractionRunModel.page_source_type == PageSourceType.WEB.value,
                CompileSessionEntry.status == "compiled",
            )
            .group_by(ExtractionRunModel.page_id)
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


@router.post("/{source_id}/pages/{page_id}/extract")
async def extract_web_page(
    source_id: uuid.UUID,
    page_id: uuid.UUID,
    session: SessionDep,
    background_tasks: BackgroundTasks,
    _current_user: Annotated[CurrentUser, Depends(_OWNER_OR_ADMIN)],
) -> dict:
    page = await session.get(WebPageModel, page_id)
    if not page or page.source_id != source_id:
        raise HTTPException(status_code=404, detail="Web page not found")

    extraction_repo = SqlAlchemyExtractionRunRepository(session)
    llm_port = get_llm_extraction_port()
    llm_provider = settings.llm_provider
    llm_model = settings.anthropic_model if llm_provider == "anthropic" else settings.openai_model

    run = ExtractionRun(
        page_id=page_id,
        page_source_type=PageSourceType.WEB,
        llm_provider=llm_provider,
        llm_model=llm_model,
        status=ExtractionStatus.RUNNING,
        started_at=utc_now(),
    )
    run = await extraction_repo.save(run)

    try:
        result = await llm_port.extract(page.plain_text, KNOWLEDGE_EXTRACTION_SCHEMA, source_url=page.url)
        run.status = ExtractionStatus.SUCCEEDED
        run.structured_draft = {k: v for k, v in dataclasses.asdict(result).items() if k != "raw_model_output"}
        run.completed_at = utc_now()
    except Exception as exc:
        logger.exception("Web page extraction failed for page %s", page_id)
        run.status = ExtractionStatus.FAILED
        run.error_message = str(exc)
        run.completed_at = utc_now()

    run = await extraction_repo.save(run)

    print(f"[extract] run.status={run.status} page_id={page_id}", flush=True)
    if run.status == ExtractionStatus.SUCCEEDED:
        print(f"[extract] scheduling background task for page_id={page_id}", flush=True)
        background_tasks.add_task(_crawl_and_extract_linked, source_id, page_id)

    return {
        "run_id": str(run.id),
        "status": run.status.value,
        "error_message": run.error_message,
    }
