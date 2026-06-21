from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.routers.auth import router as auth_router
from app.api.v1.routers.confluence import router as confluence_router
from app.api.v1.routers.extraction import router as extraction_router
from app.api.v1.routers.knowledge_products import router as knowledge_products_router

app = FastAPI(title="Knowledge Product Studio API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(knowledge_products_router, prefix="/api/v1")
app.include_router(confluence_router, prefix="/api/v1")
app.include_router(extraction_router, prefix="/api/v1")
app.include_router(auth_router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
