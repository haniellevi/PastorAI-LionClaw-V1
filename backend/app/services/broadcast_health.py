"""Broadcast compatibility wrappers around generic worker health."""

from __future__ import annotations

from app.services.worker_health import (
    ALIVE_STATES,
    heartbeat_key,
    publish_worker_heartbeat,
    worker_heartbeat_state,
)

HEARTBEAT_KEY = heartbeat_key("broadcast-worker")
READY_VALUE = "ready"
IDLE_VALUE = "idle"


def publish_broadcast_worker_state(
    redis_url: str, *, state: str, ttl_seconds: int
) -> None:
    publish_worker_heartbeat(
        redis_url,
        worker_name="broadcast-worker",
        state=state,
        ttl_seconds=ttl_seconds,
    )


def publish_broadcast_worker_heartbeat(
    redis_url: str, *, enabled: bool, ttl_seconds: int
) -> None:
    publish_worker_heartbeat(
        redis_url,
        worker_name="broadcast-worker",
        state=READY_VALUE if enabled else IDLE_VALUE,
        ttl_seconds=ttl_seconds,
    )


def broadcast_worker_ready(redis_url: str) -> bool:
    state = worker_heartbeat_state(redis_url, "broadcast-worker")
    return state in ALIVE_STATES and state != IDLE_VALUE
