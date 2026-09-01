"""Application factory and ASGI entrypoint."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response

from app.api.v1.health import router as health_router
from app.api.v1.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging, get_logger, request_id_ctx
from app.core.metrics import APP_INFO, DB_UP, MetricsMiddleware, metrics_response
from app.db.session import check_database

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    APP_INFO.labels(settings.version, settings.environment).set(1)

    # Probe once at boot and log it, but do NOT fail startup on it: a pod that
    # refuses to start when the database is briefly unavailable cannot be
    # rolled out during a database failover. Readiness keeps it out of the
    # Service until the dependency is actually back.
    db_ok = check_database()
    DB_UP.set(1 if db_ok else 0)
    log.info(
        "startup",
        service=settings.project_name,
        version=settings.version,
        environment=settings.environment,
        database_reachable=db_ok,
    )
    yield
    log.info("shutdown", service=settings.project_name)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(level=settings.log_level, json_output=settings.log_json)

    app = FastAPI(
        title=settings.project_name,
        version=settings.version,
        description=(
            "Reference production-shaped service: FastAPI + PostgreSQL, "
            "containerised, orchestrated and observable."
        ),
        # Interactive docs are a discovery surface; off in production.
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
        lifespan=lifespan,
    )
    app.state.settings = settings

    @app.middleware("http")
    async def request_context(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        # Honour an upstream id if the ingress or a caller already set one, so
        # a trace survives across service hops instead of restarting here.
        rid = request.headers.get("x-request-id") or str(uuid.uuid4())
        token = request_id_ctx.set(rid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        finally:
            request_id_ctx.reset(token)
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        response.headers["x-request-id"] = rid
        log.info(
            "request",
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=elapsed_ms,
        )
        return response

    if settings.metrics_enabled:
        app.add_middleware(MetricsMiddleware)

        @app.get("/metrics", include_in_schema=False)
        def metrics() -> Response:
            return metrics_response()

    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    @app.get("/", include_in_schema=False)
    def root() -> dict[str, str]:
        return {
            "service": settings.project_name,
            "version": settings.version,
            "docs": "/docs" if not settings.is_production else "disabled",
        }

    return app


app = create_app()
