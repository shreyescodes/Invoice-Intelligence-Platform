"""FastAPI application factory. Run with `uvicorn app.main:app`."""

from __future__ import annotations

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import Any

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text
from sqlalchemy.orm.exc import StaleDataError

from app import __version__
from app.api.routes import analytics, auth, invoices, vendors
from app.config import Settings, get_settings
from app.db import get_engine
from app.errors import DomainError
from app.observability import HTTP_LATENCY, HTTP_REQUESTS, configure_logging, get_logger
from app.runtime import get_document_store
from app.security import LoginThrottle

log = get_logger("app.http")


def _problem(status: int, detail: str, code: str, extra: dict[str, Any] | None = None) -> JSONResponse:
    body: dict[str, Any] = {
        "type": "about:blank",
        "title": HTTPStatus(status).phrase,
        "status": status,
        "detail": detail,
        "code": code,
    }
    if extra:
        body["extra"] = extra
    return JSONResponse(body, status_code=status, media_type="application/problem+json")


def _install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def domain_error(_: Request, exc: DomainError) -> JSONResponse:
        headers = {"WWW-Authenticate": "Bearer"} if exc.status_code == 401 else None
        response = _problem(exc.status_code, exc.message, exc.code, exc.extra or None)
        if headers:
            response.headers.update(headers)
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"loc": ".".join(str(p) for p in e["loc"]), "message": e["msg"]} for e in exc.errors()]
        detail = "; ".join(f"{e['loc']}: {e['message']}" for e in errors[:3])
        return _problem(422, detail or "Invalid request", "validation_error", {"errors": errors})

    @app.exception_handler(StaleDataError)
    async def stale(_: Request, __: StaleDataError) -> JSONResponse:
        return _problem(409, "The invoice was changed by someone else. Reload and try again.", "concurrent_update")

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled_error", path=request.url.path)
        return _problem(
            500,
            "An unexpected error occurred",
            "internal_error",
            {"request_id": structlog.contextvars.get_contextvars().get("request_id")},
        )


def _install_middleware(app: FastAPI, settings: Settings) -> None:
    @app.middleware("http")
    async def request_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
        finally:
            elapsed = time.perf_counter() - started
            route = request.scope.get("route")
            template = getattr(route, "path", "unmatched")
            if template not in ("/metrics", "/health/live", "/health/ready"):
                HTTP_REQUESTS.labels(request.method, template, str(status_code)).inc()
                HTTP_LATENCY.labels(request.method, template).observe(elapsed)
                log.info(
                    "request",
                    method=request.method,
                    path=request.url.path,
                    route=template,
                    status=status_code,
                    duration_ms=round(elapsed * 1000, 1),
                )
        response.headers["X-Request-ID"] = request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        if request.url.path.startswith("/api/") and "cache-control" not in response.headers:
            response.headers["Cache-Control"] = "no-store"
        return response

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=["X-Request-ID", "Location", "X-Page-Count"],
    )


def _install_operational_routes(app: FastAPI) -> None:
    @app.get("/health/live", include_in_schema=False)
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", include_in_schema=False)
    def ready() -> JSONResponse:
        checks: dict[str, str] = {}
        try:
            with get_engine().connect() as conn:
                conn.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as exc:
            checks["database"] = f"error: {type(exc).__name__}"
        try:
            get_document_store().ping()
            checks["storage"] = "ok"
        except Exception as exc:
            checks["storage"] = f"error: {type(exc).__name__}"
        healthy = all(v == "ok" for v in checks.values())
        return JSONResponse(
            {"status": "ok" if healthy else "degraded", "checks": checks}, status_code=200 if healthy else 503
        )

    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        stop = None
        if settings.embedded_worker:
            from app.runtime import build_pipeline_services
            from app.worker import start_background_worker

            _thread, stop = start_background_worker(build_pipeline_services)
            log.info("embedded_worker_started")
        log.info("api_started", version=__version__, environment=settings.environment)
        yield
        if stop is not None:
            stop.set()

    app = FastAPI(
        title="Invoice Intelligence Platform API",
        version=__version__,
        description="Accounts-payable automation: invoice capture, 3-way matching, anomaly scoring and approvals.",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
        swagger_ui_parameters={"persistAuthorization": True},
    )
    app.state.settings = settings
    app.state.login_throttle = LoginThrottle(settings.login_max_failures, settings.login_lockout_seconds)

    _install_error_handlers(app)
    _install_middleware(app, settings)
    _install_operational_routes(app)
    for module in (auth, invoices, vendors, analytics):
        app.include_router(module.router, prefix="/api/v1")
    return app


app = create_app()
