"""FastAPI application entrypoint.

Wires CORS, mounts routers and exposes a liveness `/health` endpoint. Settings
are validated at startup so a misconfigured production deploy fails fast.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.db.session import get_engine
from app.routers import (
    agent,
    assistant,
    auth,
    broadcasts,
    cells,
    consolidacao,
    contacts,
    conversations,
    events,
    multiplicacoes,
    pipeline,
    reports,
    roles,
    subscription,
    system_managers,
    team,
    whatsapp,
    work_queue,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("pastorai")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Validate config on boot and dispose the DB pool on shutdown."""
    settings = get_settings()
    settings.assert_production_ready()
    logger.info("PastorAI backend starting (env=%s)", settings.app_env)
    yield
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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins or ["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(auth.router)
    app.include_router(contacts.router)
    app.include_router(cells.router)
    app.include_router(pipeline.router)
    app.include_router(work_queue.router)
    app.include_router(consolidacao.router)
    app.include_router(multiplicacoes.router)
    app.include_router(whatsapp.router)
    app.include_router(conversations.router)
    app.include_router(agent.router)
    app.include_router(assistant.router)
    app.include_router(reports.router)
    app.include_router(broadcasts.router)
    app.include_router(events.router)
    app.include_router(team.router)
    app.include_router(roles.router)
    app.include_router(system_managers.router)
    app.include_router(subscription.router)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        """Liveness probe — always 200 when the process is up."""
        return {"status": "ok"}

    return app


app = create_app()
