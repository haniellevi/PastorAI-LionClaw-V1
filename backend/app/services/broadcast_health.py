"""Redis heartbeat shared by the broadcast worker and API capabilities."""

from __future__ import annotations

import redis

HEARTBEAT_KEY = "pastorai:broadcast-worker:heartbeat:v1"
READY_VALUE = "ready"
IDLE_VALUE = "idle"


def _client(redis_url: str):
    return redis.Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
    )


def publish_broadcast_worker_heartbeat(
    redis_url: str, *, enabled: bool, ttl_seconds: int
) -> None:
    client = _client(redis_url)
    try:
        client.setex(
            HEARTBEAT_KEY,
            max(5, ttl_seconds),
            READY_VALUE if enabled else IDLE_VALUE,
        )
    finally:
        client.close()


def broadcast_worker_ready(redis_url: str) -> bool:
    if not redis_url:
        return False
    try:
        client = _client(redis_url)
    except (ValueError, redis.RedisError):
        return False
    try:
        return client.get(HEARTBEAT_KEY) == READY_VALUE
    except redis.RedisError:
        return False
    finally:
        client.close()
