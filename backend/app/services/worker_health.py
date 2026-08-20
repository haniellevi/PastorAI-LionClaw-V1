"""Short-lived Redis heartbeats for long-running PastorAI workers.

Container state only proves that a Python process still exists.  These keys
prove that each worker loop is progressing.  Heartbeats are deliberately
small, bounded and free of hostnames, URLs or credentials.
"""

from __future__ import annotations

import re
from typing import Any

import redis

HEARTBEAT_PREFIX = "pastorai"
WORKER_NAMES = ("queue-worker", "cron-worker", "broadcast-worker")
ALIVE_STATES = frozenset({"ready", "running", "idle"})
TERMINAL_STATES = frozenset({"error", "stopped"})
_WORKER_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def heartbeat_key(worker_name: str) -> str:
    """Return the stable Redis key for a log-safe worker name."""
    if not _WORKER_NAME_RE.fullmatch(worker_name):
        raise ValueError("invalid worker name")
    return f"{HEARTBEAT_PREFIX}:{worker_name}:heartbeat:v1"


def _client(redis_url: str):
    return redis.Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )


def publish_worker_heartbeat(
    redis_url: str | None,
    *,
    worker_name: str,
    state: str,
    ttl_seconds: int,
    client: Any | None = None,
) -> None:
    """Publish a bounded heartbeat without ever logging connection details."""
    if state not in ALIVE_STATES | TERMINAL_STATES:
        raise ValueError("invalid worker heartbeat state")
    owned_client = client is None
    if client is None:
        if not redis_url:
            raise ValueError("redis URL is required")
        client = _client(redis_url)
    try:
        client.set(
            heartbeat_key(worker_name),
            state,
            ex=max(5, int(ttl_seconds)),
        )
    finally:
        if owned_client:
            client.close()


def worker_heartbeat_states(
    redis_url: str | None,
    *,
    client: Any | None = None,
) -> dict[str, str | None]:
    """Read all known worker states using one bounded Redis operation."""
    owned_client = client is None
    if client is None:
        if not redis_url:
            return {name: None for name in WORKER_NAMES}
        client = _client(redis_url)
    try:
        values = client.mget([heartbeat_key(name) for name in WORKER_NAMES])
        return {
            name: str(value) if value is not None else None
            for name, value in zip(WORKER_NAMES, values, strict=True)
        }
    finally:
        if owned_client:
            client.close()


def worker_heartbeat_state(redis_url: str, worker_name: str) -> str | None:
    """Read one heartbeat, returning ``None`` for unavailable Redis."""
    if not redis_url:
        return None
    try:
        client = _client(redis_url)
    except (ValueError, redis.RedisError):
        return None
    try:
        value = client.get(heartbeat_key(worker_name))
        return str(value) if value is not None else None
    except (ValueError, redis.RedisError):
        return None
    finally:
        client.close()


def worker_heartbeat_alive(redis_url: str, worker_name: str) -> bool:
    """True only while a worker publishes a fresh progress state."""
    return worker_heartbeat_state(redis_url, worker_name) in ALIVE_STATES
