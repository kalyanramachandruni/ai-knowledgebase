from __future__ import annotations

import asyncio
import dataclasses
import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select, update

from app.api.v1.routers.auth import router as auth_router
from app.api.v1.routers.confluence import router as confluence_router
from app.api.v1.routers.curation import router as curation_router
from app.api.v1.routers.documents import router as documents_router
from app.api.v1.routers.knowledge_products import router as knowledge_products_router
from app.api.v1.routers.web_crawl import router as web_crawl_router
from app.core.config import settings
from app.core.telemetry import setup_telemetry
from app.domain.curation.entities import CurationStatus, PageSourceType
from app.domain.curation.schema import KNOWLEDGE_CURATION_SCHEMA
from app.domain.shared.base import utc_now
from app.infrastructure.db.models import (
    KpCompileSessionEntry as CompileSessionEntry,
    PageCurationSession as CurationSessionModel,
    PageCurationSessionEntry as CurationEntryModel,
    WebPage as WebPageModel,
    WebSource as WebSourceModel,
    WebSourceHistory as WebSourceHistoryModel,
)
from app.infrastructure.db.session import SessionLocal
from app.infrastructure.llm.factory import get_llm_curation_port

logger = logging.getLogger(__name__)


async def _startup_recovery() -> None:
    """Reset any in-flight state left over from a server crash."""
    async with SessionLocal() as session:
        # 1. Sources stuck in PENDING: mark FAILED + update their open history row
        pending_sources = (await session.execute(
            select(WebSourceModel).where(WebSourceModel.crawl_status == "PENDING")
        )).scalars().all()

        for src in pending_sources:
            src.crawl_status = "FAILED"
            # Find the most-recent history row with crawl_status IS NULL (in-progress placeholder)
            history_row = (await session.execute(
                select(WebSourceHistoryModel)
                .where(
                    WebSourceHistoryModel.source_id == src.id,
                    WebSourceHistoryModel.crawl_status.is_(None),
                )
                .order_by(WebSourceHistoryModel.created_at.desc())
                .limit(1)
            )).scalar_one_or_none()
            if history_row:
                history_row.crawl_status = "FAILED"
            logger.warning("Startup recovery: source %s PENDING → FAILED", src.id)

        # 2. Curation entries stuck in 'running': mark failed
        await session.execute(
            update(CurationEntryModel)
            .where(CurationEntryModel.status == "running")
            .values(status="failed", error_message="Server restarted")
        )

        # 3. Compile entries stuck in 'running': mark failed
        await session.execute(
            update(CompileSessionEntry)
            .where(CompileSessionEntry.status == "running")
            .values(status="failed", reason="Server restarted")
        )

        await session.commit()
    logger.info("Startup recovery complete.")


async def _curation_worker() -> None:
    """Background worker: processes pending page_curation_session_entry rows every 5 s."""
    llm_port = get_llm_curation_port()
    llm_provider = settings.llm_provider
    llm_model = settings.anthropic_model if llm_provider == "anthropic" else settings.openai_model

    while True:
        await asyncio.sleep(5)
        try:
            await _process_one_curation_entry(llm_port, llm_provider, llm_model)
        except Exception:
            logger.exception("Curation worker: unhandled error in poll cycle")


async def _process_one_curation_entry(llm_port, llm_provider: str, llm_model: str) -> None:
    async with SessionLocal() as session:
        # Find one pending entry (skip entries whose source is currently being crawled)
        entry_row = (await session.execute(
            select(CurationEntryModel)
            .join(CurationSessionModel, CurationSessionModel.id == CurationEntryModel.session_id)
            .where(
                CurationEntryModel.status == "pending",
                CurationEntryModel.page_source_type == PageSourceType.WEB.value,
            )
            .order_by(CurationSessionModel.started_at)
            .limit(1)
        )).scalar_one_or_none()

        if not entry_row:
            return

        # Check the source is not actively crawling
        page = await session.get(WebPageModel, entry_row.page_id)
        if page:
            source = await session.get(WebSourceModel, page.source_id)
            if source and source.crawl_status == "PENDING":
                return  # defer until crawl finishes

        entry_row.status = "running"
        await session.flush()

        try:
            if not page:
                entry_row.status = "failed"
                entry_row.error_message = "Page not found"
                await session.commit()
                return

            result = await llm_port.extract(
                page.plain_text, KNOWLEDGE_CURATION_SCHEMA, source_url=page.url
            )
            entry_row.status = "succeeded"
            entry_row.structured_draft = {
                k: v for k, v in dataclasses.asdict(result).items() if k != "raw_model_output"
            }
            page.changed_since_extraction = False
        except Exception as exc:
            logger.exception("Curation worker: curation failed for page %s", entry_row.page_id)
            entry_row.status = "failed"
            entry_row.error_message = str(exc)
        finally:
            session.add(entry_row)
            if page and entry_row.status == "succeeded":
                session.add(page)
            # Update the parent session completed_at if all entries are done
            await session.commit()

    logger.info(
        "Curation worker: entry %s → %s", entry_row.id, entry_row.status
    )


async def _compile_worker() -> None:
    """Background worker: processes pending kp_compile_session_entry rows every 5 s."""
    while True:
        await asyncio.sleep(5)
        try:
            await _process_one_compile_entry()
        except Exception:
            logger.exception("Compile worker: unhandled error in poll cycle")


async def _process_one_compile_entry() -> None:
    async with SessionLocal() as session:
        entry_row = (await session.execute(
            select(CompileSessionEntry)
            .where(CompileSessionEntry.status == "pending")
            .order_by(CompileSessionEntry.created_at)
            .limit(1)
        )).scalar_one_or_none()

        if not entry_row:
            return

        entry_row.status = "running"
        await session.flush()

        try:
            # Per-entry compile logic: incorporates the linked page's curation draft into the
            # KP version referenced by the session. Full LLM merge is handled by the user-driven
            # compile workflow; the worker's job here is to mark entries that were pre-queued as
            # part of the linked-page queue so they don't stay pending indefinitely.
            # A future iteration will wire the full compile merge here.
            entry_row.status = "discarded"
            entry_row.reason = "Linked page compile not yet supported by background worker; use the compile form."
        except Exception as exc:
            logger.exception("Compile worker: compile failed for entry %s", entry_row.id)
            entry_row.status = "failed"
            entry_row.reason = str(exc)
        finally:
            session.add(entry_row)
            await session.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await _startup_recovery()
    curation_task = asyncio.create_task(_curation_worker())
    compile_task = asyncio.create_task(_compile_worker())
    yield
    curation_task.cancel()
    compile_task.cancel()
    await asyncio.gather(curation_task, compile_task, return_exceptions=True)


app = FastAPI(title="Knowledge Product Studio API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:3002"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Without this, Starlette's default 500 response is generated by
    ServerErrorMiddleware, which sits *outside* CORSMiddleware in the stack —
    so it never gets CORS headers added, and browsers report a generic
    network failure instead of showing the actual error. Registering a
    handler here routes the response back through ExceptionMiddleware
    (inside CORSMiddleware), so error responses behave like any other."""
    logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})

app.include_router(knowledge_products_router, prefix="/api/v1")
app.include_router(confluence_router, prefix="/api/v1")
app.include_router(curation_router, prefix="/api/v1")
app.include_router(documents_router, prefix="/api/v1")
app.include_router(web_crawl_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")

setup_telemetry(app)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/metrics")
async def metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
