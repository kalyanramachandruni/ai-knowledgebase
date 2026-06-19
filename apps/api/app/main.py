from __future__ import annotations

from fastapi import FastAPI

from app.api.v1.routers.knowledge_products import router as knowledge_products_router

app = FastAPI(title="Knowledge Product Studio API", version="0.1.0")

app.include_router(knowledge_products_router, prefix="/api/v1")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}
