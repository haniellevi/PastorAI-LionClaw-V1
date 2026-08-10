"""Sanitized readiness probes for the API process.

DB and Redis are required by the API.  Evolution and background workers are
operational signals: their failure degrades the report but must not remove the
API from service or create a container restart loop.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable

import httpx
import redis

from app.config import Settings, get_settings
from app.db.session import get_engine
from app.services.worker_health import (
    ALIVE_STATES,
    WORKER_NAMES,
    worker_heartbeat_states,
)

logger = logging.getLogger("pastorai.readiness")

_PROBE_TIMEOUT_SECONDS = 2.0
_REDIS_TIMEOUT_SECONDS = 1.0
_EVOLUTION_TIMEOUT_SECONDS = 1.5
_OPTIONAL_HEALTHY_STATES = frozenset({"ok", "disabled"})


@dataclass(frozen=True)
class ReadinessReport:
    status: str
    required: dict[str, str]
    optional: dict[str, str]
    workers: dict[str, str]

    @property
    def http_status(self) -> int:
        return 503 if self.status == "not_ready" else 200

    @property
    def required_failures(self) -> int:
        return sum(state != "ok" for state in self.required.values())

    @property
    def optional_failures(self) -> int:
        return sum(
            state not in _OPTIONAL_HEALTHY_STATES for state in self.optional.values()
        ) + sum(state != "ok" for state in self.workers.values())

    def public_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "process": "api",
            "required": self.required,
            "optional": self.optional,
            "workers": self.workers,
        }


def _check_database() -> None:
    connection = get_engine().connect()
    try:
        value = connection.exec_driver_sql("SELECT 1").scalar_one()
        if value != 1:
            raise RuntimeError("database probe failed")
        connection.rollback()
    finally:
        connection.close()


def _check_redis_and_workers(settings: Settings) -> dict[str, str | None]:
    client = redis.Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=_REDIS_TIMEOUT_SECONDS,
        socket_timeout=_REDIS_TIMEOUT_SECONDS,
        retry_on_timeout=False,
    )
    try:
        if client.ping() is not True:
            raise RuntimeError("redis probe failed")
        return worker_heartbeat_states(None, client=client)
    finally:
        client.close()


def _check_evolution(settings: Settings) -> None:
    headers = (
        {"apikey": settings.evolution_api_key}
        if settings.evolution_api_key
        else {}
    )
    timeout = httpx.Timeout(
        _EVOLUTION_TIMEOUT_SECONDS,
        connect=_EVOLUTION_TIMEOUT_SECONDS,
    )
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        response = client.get(
            settings.evolution_api_url.rstrip("/") + "/",
            headers=headers,
        )
    # Authentication failures still prove that the optional service is reachable.
    if response.status_code >= 500:
        raise RuntimeError("evolution probe failed")


async def _bounded_probe(
    name: str,
    probe: Callable[[], Any],
    *,
    timeout_seconds: float,
) -> tuple[str, Any | None]:
    try:
        payload = await asyncio.wait_for(
            asyncio.to_thread(probe),
            timeout=timeout_seconds,
        )
        return "ok", payload
    except TimeoutError:
        logger.warning("readiness_probe_failed dependency=%s error_type=Timeout", name)
        return "timeout", None
    except Exception as exc:  # noqa: BLE001 - every dependency failure is a result
        logger.warning(
            "readiness_probe_failed dependency=%s error_type=%s",
            name,
            type(exc).__name__,
        )
        return "unavailable", None


def _public_worker_states(raw: dict[str, str | None] | None) -> dict[str, str]:
    raw = raw or {}
    return {
        name: "ok" if raw.get(name) in ALIVE_STATES else "unknown"
        if raw.get(name) is None
        else "unavailable"
        for name in WORKER_NAMES
    }


async def collect_readiness(
    settings: Settings | None = None,
    *,
    timeout_seconds: float | None = None,
) -> ReadinessReport:
    """Collect required and optional states with one bounded timeout each."""
    settings = settings or get_settings()
    timeout = _PROBE_TIMEOUT_SECONDS if timeout_seconds is None else timeout_seconds

    database_task = _bounded_probe("database", _check_database, timeout_seconds=timeout)
    redis_task = _bounded_probe(
        "redis",
        lambda: _check_redis_and_workers(settings),
        timeout_seconds=timeout,
    )
    if settings.evolution_api_url:
        evolution_task = _bounded_probe(
            "evolution",
            lambda: _check_evolution(settings),
            timeout_seconds=timeout,
        )
    else:
        evolution_task = None

    if evolution_task is None:
        database_result, redis_result = await asyncio.gather(
            database_task,
            redis_task,
        )
        evolution_result = ("disabled", None)
    else:
        database_result, redis_result, evolution_result = await asyncio.gather(
            database_task,
            redis_task,
            evolution_task,
        )

    required = {
        "database": database_result[0],
        "redis": redis_result[0],
    }
    workers = _public_worker_states(
        redis_result[1] if redis_result[0] == "ok" else None
    )
    optional = {"evolution": evolution_result[0]}

    if any(state != "ok" for state in required.values()):
        status = "not_ready"
    elif any(
        state not in _OPTIONAL_HEALTHY_STATES for state in optional.values()
    ) or any(state != "ok" for state in workers.values()):
        status = "degraded"
    else:
        status = "ready"
    return ReadinessReport(status, required, optional, workers)
