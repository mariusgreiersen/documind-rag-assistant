"""FastAPI application factory.

Run locally with:  uvicorn documind.main:app --reload   (from the backend/ directory)
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from documind import __version__
from documind.api.deps import limits
from documind.api.routes import chat, documents, search
from documind.container import Container, build_container
from documind.core.config import Settings, get_settings
from documind.core.errors import DocuMindError
from documind.core.logging import configure_logging, log_event
from documind.models.schemas import ConfigOut, HealthOut

logger = logging.getLogger("documind")


def _error(status: int, code: str, message: str, details: dict[str, Any] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details or {}}})


def create_app(settings: Settings | None = None, container_factory: Callable[[Settings], Container] | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)
    factory = container_factory or build_container

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        container = factory(settings)
        container.documents.validate_configuration()
        container.documents.reconcile()
        if settings.seed_demo_on_startup:
            container.documents.seed_demo()
        app.state.container = container
        log_event(
            logger,
            "startup_completed",
            embedding_model=container.embedder.model_id,
            llm_provider=container.llm.name if container.llm else None,
            read_only=settings.read_only,
            documents=len(container.documents.list_documents()),
        )
        yield
        container.close()

    app = FastAPI(
        title="DocuMind API",
        version=__version__,
        summary="Grounded question answering over your PDF documents, with verified page-level citations.",
        description=(
            "DocuMind indexes text-based PDFs, retrieves relevant passages with semantic search and generates answers "
            "that cite the exact document and page. Search works without an LLM API key."
        ),
        lifespan=lifespan,
        openapi_tags=[
            {"name": "documents", "description": "Upload, list, inspect and delete documents."},
            {"name": "search", "description": "Semantic passage search (no LLM required)."},
            {"name": "chat", "description": "Grounded question answering with citations."},
            {"name": "demo", "description": "Bundled sample documents."},
            {"name": "system", "description": "Health and public configuration."},
        ],
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type"],
        allow_credentials=False,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next: Callable[[Request], Any]) -> Any:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response

    @app.exception_handler(DocuMindError)
    async def handle_domain_error(_: Request, exc: DocuMindError) -> JSONResponse:
        log_event(
            logger, "request_rejected", logging.INFO if exc.status_code < 500 else logging.WARNING, code=exc.code, status=exc.status_code
        )
        return _error(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"field": ".".join(str(p) for p in e.get("loc", ())[1:]), "message": e.get("msg", "")} for e in exc.errors()]
        message = errors[0]["message"] if errors else "Invalid request."
        if errors and errors[0]["field"]:
            message = f"{errors[0]['field']}: {message}"
        return _error(422, "validation_error", message, {"errors": errors})

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return _error(exc.status_code, code, str(exc.detail))

    @app.exception_handler(Exception)
    async def handle_unexpected(_: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", extra={"fields": {"error": type(exc).__name__}})
        return _error(500, "internal_error", "Something went wrong. Please try again.")

    @app.get("/health", response_model=HealthOut, tags=["system"], summary="Liveness check")
    def health() -> HealthOut:
        return HealthOut(status="ok", version=__version__)

    @app.get("/api/v1/config", response_model=ConfigOut, tags=["system"], summary="Public configuration for the UI")
    def config(request: Request) -> ConfigOut:
        c: Container = request.app.state.container
        s = c.settings
        return ConfigOut(
            version=__version__,
            llm_configured=c.llm is not None,
            llm_provider=c.llm.name if c.llm else None,
            llm_model=c.llm.model if c.llm else None,
            embedding_model=c.embedder.model_id,
            embedding_dimension=c.embedder.dimension,
            max_seq_length=c.embedder.max_seq_length,
            max_input_tokens=c.embedder.max_input_tokens,
            chunk_size_tokens=s.chunk_size_tokens,
            chunk_overlap_tokens=s.chunk_overlap_tokens,
            default_top_k=s.default_top_k,
            min_relevance_score=s.min_relevance_score,
            read_only=s.read_only,
            diagnostics_enabled=s.enable_diagnostics,
            demo_available=bool(c.documents.demo_manifest()),
            limits=limits(c),
        )

    app.include_router(documents.router)
    app.include_router(search.router)
    app.include_router(chat.router)
    return app


app = create_app()
