"""FastAPI application entrypoint.

Wires CORS, mounts routers and exposes a liveness `/health` endpoint. Settings
are validated at startup so a misconfigured production deploy fails fast.
"""

from __future__ import annotations

import logging
import re
import time
import uuid
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.db.session import get_engine
from app.middleware.body_limit import MediaUploadBodyLimitMiddleware
from app.routers import (
    agent,
    assistant,
    auth,
    broadcasts,
    calendar,
    cell_central,
    cell_discipulo,
    cell_materials,
    cell_meetings,
    cell_notices,
    cell_requests,
    cells,
    church,
    consolidacao,
    contacts,
    conversations,
    dashboard,
    events,
    multiplicacoes,
    pipeline,
    platform_admin,
    platform_consent_governance,
    reports,
    roles,
    setup,
    subscription,
    team,
    whatsapp,
    work_queue,
)
from app.services.celula_membro import (
    MembroInelegivelError,
    TransferenciaNaoAutorizadaError,
)
from app.services.clerk import ClerkClient
from app.services.rate_limit import RateLimitExceeded
from app.services.readiness import collect_readiness

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("pastorai")

_REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def _request_id(value: str | None) -> str:
    """Return a log-safe correlation id, never echoing arbitrary input."""
    if value and _REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return uuid.uuid4().hex


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Validate config on boot and release shared clients on shutdown."""
    settings = get_settings()
    settings.assert_production_ready()
    # A FastAPI instance can enter its lifespan more than once in tests or
    # managed hosts. Each startup gets a fresh, open pool; each shutdown closes
    # exactly the pool created for that lifespan.
    clerk_client = ClerkClient(settings=settings)
    app.state.clerk_client = clerk_client
    logger.info("PastorAI backend starting (env=%s)", settings.app_env)
    try:
        connection = get_engine().connect()
        try:
            connection.exec_driver_sql("SELECT 1").scalar_one()
            connection.rollback()
        finally:
            connection.close()
        logger.info("Database connection pool warmed")
    except (RuntimeError, SQLAlchemyError):
        logger.warning("Database warmup unavailable; startup continuing")
    try:
        yield
    finally:
        clerk_client.close()
        logger.info("Clerk HTTP connection pool closed")
        # Graceful shutdown: close pooled connections if the engine was created.
        try:
            get_engine().dispose()
            logger.info("Database connection pool disposed")
        except RuntimeError:
            # Engine was never initialized (e.g. no DATABASE_URL in dev/tests).
            pass


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="PastorAI API",
        version="1.0.0",
        lifespan=lifespan,
    )

    # Guard the base64 media upload before Starlette/Pydantic buffers and parses
    # its JSON body. Added before CORS so even a 413 carries the normal CORS
    # response headers; all non-media routes pass through unchanged.
    app.add_middleware(MediaUploadBodyLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        # Explicit origins only — never a wildcard together with credentials
        # (MEDIO-001). In production assert_production_ready guarantees these
        # are real https hosts; a bad config fails fast at startup.
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=[_REQUEST_ID_HEADER, "Server-Timing"],
    )

    @app.middleware("http")
    async def _request_observability(request: Request, call_next):
        """Emit low-cardinality request timing without query strings or bodies."""
        request_id = _request_id(request.headers.get(_REQUEST_ID_HEADER))
        started = time.perf_counter()
        request.state.request_id = request_id
        request.state.request_started = started
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            duration_ms = (time.perf_counter() - started) * 1000
            response.headers[_REQUEST_ID_HEADER] = request_id
            response.headers["Server-Timing"] = f"app;dur={duration_ms:.2f}"
            return response
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            route = request.scope.get("route")
            route_path = getattr(route, "path", "<unmatched>")
            logger.info(
                "http_request request_id=%s method=%s route=%s status=%d duration_ms=%.2f",
                request_id,
                request.method,
                route_path,
                status_code,
                duration_ms,
            )

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        """Keep correlation headers even for failures outside user middleware."""
        request_id = getattr(request.state, "request_id", None) or _request_id(None)
        started = getattr(request.state, "request_started", time.perf_counter())
        duration_ms = (time.perf_counter() - started) * 1000
        logger.exception("Unhandled request error request_id=%s", request_id, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={"detail": "Erro interno do servidor."},
            headers={
                _REQUEST_ID_HEADER: request_id,
                "Server-Timing": f"app;dur={duration_ms:.2f}",
            },
        )

    @app.exception_handler(RateLimitExceeded)
    async def _rate_limit_exceeded_handler(
        _: Request, exc: RateLimitExceeded
    ) -> JSONResponse:
        # Corpo genérico e idêntico em toda rota (ALTO-002) — não deve dar
        # nenhuma pista adicional sobre qual limite/conta foi atingido.
        return JSONResponse(
            status_code=429,
            content={"detail": "Muitas tentativas. Tente novamente mais tarde."},
            headers={"Retry-After": str(exc.retry_after)},
        )

    @app.exception_handler(MembroInelegivelError)
    async def _membro_inelegivel_handler(
        _: Request, exc: MembroInelegivelError
    ) -> JSONResponse:
        # Missão M7B-W1.2: a guarda de elegibilidade de membro (seam canônico
        # ensure_active_membro + entrada direta add_cell_member) recusa pastor /
        # líder da própria célula / número do WhatsApp em QUALQUER rota que crie
        # vínculo (link_cell, convite, ativação, membro direto). Um único ponto
        # de tradução → 409 acionável, em vez de repetir o try/except em cada router.
        return JSONResponse(
            status_code=409,
            content={"detail": {"error": exc.code, "message": exc.message}},
        )

    @app.exception_handler(TransferenciaNaoAutorizadaError)
    async def _transferencia_nao_autorizada_handler(
        _: Request, exc: TransferenciaNaoAutorizadaError
    ) -> JSONResponse:
        # D2: o domínio (ensure_active_membro) recusa reatribuição de célula sem
        # a capacidade pode_transferir. Mesmo 403 com detail string que o adapter
        # administrativo (link_cell) respondia antes — contrato preservado.
        return JSONResponse(status_code=403, content={"detail": exc.message})

    app.include_router(auth.router)
    app.include_router(church.router)
    app.include_router(contacts.router)
    app.include_router(cells.router)
    app.include_router(cell_meetings.router)
    app.include_router(cell_discipulo.router)
    app.include_router(cell_requests.router)
    app.include_router(cell_notices.router)
    app.include_router(cell_materials.router)
    app.include_router(cell_central.router)
    app.include_router(pipeline.router)
    app.include_router(work_queue.router)
    app.include_router(consolidacao.router)
    app.include_router(multiplicacoes.router)
    app.include_router(whatsapp.router)
    app.include_router(conversations.router)
    app.include_router(dashboard.router)
    app.include_router(agent.router)
    app.include_router(assistant.router)
    app.include_router(reports.router)
    app.include_router(broadcasts.router)
    app.include_router(events.router)
    app.include_router(calendar.router)
    app.include_router(team.router)
    app.include_router(roles.router)
    app.include_router(setup.router)
    app.include_router(subscription.router)
    # Plano de plataforma (Super-Admin, cross-tenant). Gated por
    # get_platform_admin — fora do RLS por tenant. Ver routers/platform_admin.py.
    app.include_router(platform_admin.router)
    # D2B2b3A: preparação DRAFT_ONLY pelo Console Master. A superfície
    # nasce desligada e não autoriza aprovação, catálogo, writer ou runtime.
    app.include_router(platform_consent_governance.router)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        """Liveness probe — always 200 when the process is up."""
        return {"status": "ok"}

    @app.get("/ready", tags=["health"])
    async def readiness(request: Request) -> JSONResponse:
        """Dependency readiness, sanitized for public operational checks."""
        report = await collect_readiness()
        logger.info(
            "readiness_check request_id=%s status=%s "
            "required_failures=%d optional_failures=%d",
            request.state.request_id,
            report.status,
            report.required_failures,
            report.optional_failures,
        )
        return JSONResponse(
            status_code=report.http_status,
            content=report.public_payload(),
        )

    return app


app = create_app()
