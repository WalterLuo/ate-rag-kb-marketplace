"""FastAPI application factory."""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from ate_rag_kb.api.routes import (
    is_retriever_initialized,
    router,
    set_coordinator,
    set_planner,
    set_retriever,
)
from ate_rag_kb.retrieval.coordinator import build_retrieval_coordinator
from ate_rag_kb.retrieval.planner import RetrievalPlanner
from ate_rag_kb.utils.config import Config

logger = logging.getLogger(__name__)


class TimingMiddleware(BaseHTTPMiddleware):
    """Adds ``X-Process-Time-Ms`` response header and structured log entry."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        start = time.perf_counter()
        response: Response = await call_next(request)
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        response.headers["X-Process-Time-Ms"] = f"{elapsed_ms:.1f}"
        logger.info(
            "API request: %s %s -> %s (%.1f ms)",
            request.method,
            request.url.path,
            response.status_code,
            elapsed_ms,
        )
        return response


def create_app(config: Config) -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="ATE RAG Knowledge Base",
        description="Agentic RAG API for ATE Test Engineer documentation.",
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
    )

    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Timing middleware (after CORS so headers are set on final response)
    app.add_middleware(TimingMiddleware)

    # Health check
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> dict[str, str]:
        if not is_retriever_initialized():
            raise HTTPException(status_code=503, detail="Retrieval backend not initialized")
        return {"status": "ok"}

    # Include API routes
    app.include_router(router, prefix="/api/v1")

    # Lifecycle: inject retriever backend if available
    @app.on_event("startup")
    async def _startup() -> None:
        retriever = _build_retriever(config)
        if retriever is not None:
            set_retriever(retriever)
            set_planner(RetrievalPlanner(config))
            set_coordinator(build_retrieval_coordinator(config, retriever))
            logger.info("Retriever backend initialized")

    return app


def _build_retriever(config: Config) -> object | None:
    """Attempt to build the retriever from config."""
    try:
        # Deferred import to avoid heavy startup cost when retriever is not yet implemented
        from ate_rag_kb.retrieval.pipeline import RetrievalPipeline

        return RetrievalPipeline(config)
    except Exception:
        logger.warning("Retriever backend not available; API will return 503")
        return None
